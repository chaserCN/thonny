from __future__ import annotations
import datetime
import logging
import base64
import io
import wave
import subprocess
import tempfile
import os
from enum import Enum
from typing import Dict

from google import genai
from google.genai import types
import io
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from plugin_manager import PluginManager
from utils import is_direct_result, direct_result_kind, localized_text, print_object, random_file_name
from constants import MULTIUSER_CHAT_INSTRUCTIONS

console = Console()

class Role(Enum):
    USER = "user"
    MODEL = "model"

class GoogleAIHelper:
    def __init__(self, config: dict, plugin_manager: PluginManager):
        self.client = genai.Client(api_key=config['api_key'])
        self.config = config
        self.plugin_manager = plugin_manager
        self.conversations: dict[int: list] = {}  # {chat_id: conversation_history}
        self.last_updated: dict[int: datetime] = {}  # {chat_id: last_update_timestamp} 

    def reset_chat_history(self, chat_id: int, content=''):
        """Reset the conversation history for a specific chat"""
        self.conversations[chat_id] = []

    def __add_to_history(self, chat_id: int, role: Role, content: str):
        """Add a message to the conversation history"""

        user_content = types.Content(
            role=role.value, parts=[types.Part(text=content)]
        )
        if chat_id not in self.conversations or not self.conversations[chat_id]:
            self.conversations[chat_id] = []

        self.conversations[chat_id].append(user_content)

    def __print_history_colored(self, chat_id: int):
        """Print conversation history with colors"""
        if chat_id not in self.conversations:
            console.print("[red]No conversation history found[/red]")
            return
            
        history = self.conversations[chat_id]
        if not history:
            console.print("[yellow]Empty conversation history[/yellow]")
            return
            
        console.print(f"\n[bold cyan]Conversation History (chat_id: {chat_id}):[/bold cyan]")
        
        for i, msg in enumerate(history):
            role = msg.role
            content = msg.parts[0].text if msg.parts else "No content"
            
            # Color coding based on role
            if role == "user":
                role_color = "[bold green]"
                content_color = "[green]"
            elif role == "model":
                role_color = "[bold blue]"
                content_color = "[blue]"
            else:
                role_color = "[bold white]"
                content_color = "[white]"
                
            # Truncate content for display
            display_content = content[:100] + "..." if len(content) > 100 else content
            
            panel = Panel(
                Text(display_content, style=content_color),
                title=f"{role_color}{role.upper()}[/{role_color[1:]} (#{i+1})",
                border_style="dim"
            )
            console.print(panel)

    def __max_age_reached(self, chat_id: int) -> bool:
        """Check if the maximum conversation age has been reached"""
        if chat_id not in self.last_updated:
            return True
        age = datetime.datetime.now() - self.last_updated[chat_id]
        return age.total_seconds() > self.config['max_conversation_age_minutes'] * 60

    #########################################################
    # Chat model
    #########################################################

    async def get_chat_response(self, chat_id: int, query: str, user_name: str | None) -> Dict | str:
        logging.info(f'[NON-STREAM] Starting get_chat_response: chat_id={chat_id}, query="{query[:50]}..."')        
        
        response = await self.__send_query(chat_id, query, user_name, stream=False)    
        
        return await self.__process_nonstreaming_response(response, chat_id)

    async def get_chat_response_stream(self, chat_id: int, query: str, user_name: str | None) -> tuple[str, bool]:
        logging.info(f'[STREAM] Starting get_chat_response_stream: chat_id={chat_id}, query="{query[:50]}..."')

        response = await self.__send_query(chat_id, query, user_name, stream=True)
        
        async for answer, is_final in self.__process_streaming_response(response, chat_id):
            yield answer, is_final

    # @retry(
    #     reraise=True,
    #     retry=retry_if_exception_type(Exception),
    #     wait=wait_fixed(20),
    #     stop=stop_after_attempt(3)
    # )
    async def __send_query(self, chat_id: int, query: str, user_name: str | None, stream=False):
        bot_language = self.config['bot_language']
        try:
            if chat_id not in self.conversations or self.__max_age_reached(chat_id):
                self.reset_chat_history(chat_id)

            self.last_updated[chat_id] = datetime.datetime.now()

            if user_name:
                query = f"{user_name}: {query}"

            self.__add_to_history(chat_id, role=Role.USER, content=query)

            instructions = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                instructions += self.config['assistant_prompt']

            tools = self.__tools_for_request()
            
            config = types.GenerateContentConfig(system_instruction=instructions, tools=tools)

            console.print(f"[bold yellow]🚀 [SEND] API request:[/bold yellow] [cyan]model={self.config['model']}, stream={stream}, history_length={len(self.conversations[chat_id])}[/cyan]")
            logging.info(f'[SEND] API request: model={self.config["model"]}, stream={stream}, history_length={len(self.conversations[chat_id])}')
            #self.__print_history_colored(chat_id)

            if stream:
                response = await self.client.aio.models.generate_content_stream(
                    model=self.config['model'],
                    contents=self.conversations[chat_id],
                    config=config
                )
            else:
                response = await self.client.aio.models.generate_content(
                    model=self.config['model'],
                    contents=self.conversations[chat_id],
                    config=config
                )

            logging.info(f'[SEND] Response received: type={type(response).__name__}')
            return response

        except Exception as e:
            logging.error(f'[SEND] General error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    def __tools_for_request(self) -> list[types.Tool]:
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        return [grounding_tool]

    async def __process_nonstreaming_response(self, response, chat_id: int) -> str:
        #print_object("[NON-STREAM] Response:", response)
        
        answer, has_grounding, _ = self.__process_nonfunction_response(response, check_grounding=True)
        answer = answer or ""
        
        logging.info(f'[NON-STREAM] Processed response: answer_length={len(answer)}, has_grounding={has_grounding}')
        
        if not answer.strip():
            logging.warning(f'[NON-STREAM] Empty response detected, using fallback message')
            answer = localized_text('empty_response', self.config['bot_language'])
            
        if has_grounding:
            logging.info(f'[NON-STREAM] Adding grounding prefix')
            grounding_prefix = localized_text('web_search_result', self.config['bot_language'])
            answer = f"<i>{grounding_prefix}</i>\n\n{answer}"
        
        # Add to history
        self.__add_to_history(chat_id, role=Role.MODEL, content=answer)
        
        console.print(f"[bold green]✅ [NON-STREAM] Final result:[/bold green] [cyan]length={len(answer)}[/cyan]")

        return answer

    async def __process_streaming_response(self, response, chat_id: int) -> tuple[str, bool]:
        """
        Process streaming response and yield chunks with final status
        :param response: The streaming response from Google AI
        :param chat_id: Chat ID for history management
        :yield: Tuple of (answer, is_final)
        """
        answer = ''
        has_grounding = False
        chunk_count = 0

        async for chunk in response:
            chunk_count += 1
            #print_object("Streaming chunk:", chunk)
            chunk_text, found_grounding, is_final = self.__process_nonfunction_response(chunk, check_grounding=not has_grounding)

            if found_grounding and not has_grounding:
                logging.info(f'[STREAM] Grounding found in chunk {chunk_count}, adding prefix')
                grounding_prefix = localized_text('web_search_result', self.config['bot_language'])
                answer = f"<i>{grounding_prefix}</i>\n\n{answer}"

            has_grounding |= found_grounding

            if chunk_text is not None:
                answer += chunk_text
                logging.info(f'[STREAM] Chunk {chunk_count}: text_length={len(chunk_text)}, is_final={is_final}, total_length={len(answer)}')

                if not is_final:
                    yield answer, False
                else:
                    logging.info(f'[STREAM] Final chunk {chunk_count} received')

        console.print(f"[bold blue]🔄 [STREAM] Streaming completed:[/bold blue] [cyan]chunks={chunk_count}, response_length={len(str(answer))}[/cyan]")
        logging.info(f'[STREAM] Streaming completed: chunks={chunk_count}, response_length={len(str(answer))}')

        # Check if answer is not empty
        if not answer.strip():
            logging.warning(f'[STREAM] Empty response detected')
            answer = localized_text('empty_response', self.config['bot_language'])
        
        # Add to history for all responses
        self.__add_to_history(chat_id, role=Role.MODEL, content=answer)
        
        yield answer, True

    def __process_nonfunction_response(self, response, check_grounding: bool) -> tuple[str | None, bool, bool]:
        answer = response.text
        
        has_grounding = False
        is_final = False
        
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            
            if check_grounding:
                has_grounding = (hasattr(candidate, 'grounding_metadata') and 
                               candidate.grounding_metadata and 
                               hasattr(candidate.grounding_metadata, 'web_search_queries') and 
                               candidate.grounding_metadata.web_search_queries is not None)
            
            if hasattr(candidate, 'finish_reason') and candidate.finish_reason == 'STOP':
                is_final = True

        return answer, has_grounding, is_final

    def reset_conversation(self, chat_id: int):
        """Reset the conversation history for a specific chat"""
        if chat_id in self.conversations:
            self.conversations[chat_id] = []
        if chat_id in self.last_updated:
            del self.last_updated[chat_id]

    #########################################################
    # Vision
    #########################################################

    async def interpret_image(self, chat_id: int, fileobj, user_name: str | None, prompt=None) -> str | Dict:
        # Log vision request
        logging.info(f'[VISION] Vision request: prompt="{prompt}", user_name={user_name}')
        
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt)

        return await self.__process_nonstreaming_response(response, chat_id)

    async def interpret_image_stream(self, chat_id: int, fileobj, user_name: str | None, prompt=None) -> tuple[str, bool, bool]:
        # Log streaming vision request
        logging.info(f'[VISION] Starting interpret_image_stream: prompt="{prompt}", user_name={user_name}')
        
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt, stream=True)
        
        async for answer, is_final in self.__process_streaming_response(response, chat_id):
            yield answer, is_final, is_final

    @retry(
        reraise=True,
        retry=retry_if_exception_type(Exception),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __send_vision_query(self, chat_id: int, fileobj, user_name: str | None, prompt=None, stream=False):
        bot_language = self.config['bot_language']
        try:
            logging.info(f'[VISION] Vision API request: model={self.config["model"]}, prompt="{prompt}", stream={stream}')

            # Set default prompt if none provided and no history
            if not prompt or not prompt.strip():
                if not (chat_id in self.conversations and self.conversations[chat_id]):
                    # No history - use default vision prompt
                    prompt = self.config['vision_prompt']
            
            # Add user name if provided
            if user_name and prompt and prompt.strip():
                prompt = f"{user_name}: {prompt}"
            else:
                prompt = f"{user_name} sends a picture"
            
            # Create parts with image and prompt (if any)
            parts = [types.Part.from_bytes(
                data=fileobj.getvalue(),
                mime_type='image/png',
            )]
            if prompt and prompt.strip():
                parts.append(types.Part(text=prompt))
            
            # Create contents
            if chat_id in self.conversations and self.conversations[chat_id]:
                # Include conversation history
                contents = self.conversations[chat_id].copy()
                contents.append(types.Content(role="user", parts=parts))
            else:
                # No history, just send current image and prompt
                contents = [types.Content(role="user", parts=parts)]

            # Create config with system instructions
            logging.info(f'[VISION] Creating config with system instructions')
            instructions = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                instructions += self.config['assistant_prompt']
                logging.info(f'[VISION] Added assistant prompt: {self.config["assistant_prompt"]}')

            config = types.GenerateContentConfig(system_instruction=instructions)
            logging.info(f'[VISION] Config created successfully')


            # Send vision request with history
            if stream:
                response = await self.client.aio.models.generate_content_stream(
                    model=self.config['model'],
                    contents=contents,
                    config=config
                )
            else:
                response = await self.client.aio.models.generate_content(
                    model=self.config['model'],
                    contents=contents,
                    config=config
                )

            logging.info(f'[VISION] Response received: type={type(response).__name__}')
            #print_object('[VISION] Response:', response)

            return response

        except Exception as e:
            logging.error(f'[VISION] Vision general error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    #########################################################
    # Image model
    #########################################################

    async def generate_image(self, prompt: str) -> tuple[str, str]:
        bot_language = self.config['bot_language']
        try:
            # Log image generation request
            logging.info(f'[IMAGE] Image generation request: prompt="{prompt}", model=imagen-4.0-generate-001')
            
            response = await self.client.aio.models.generate_images(
                model=self.config.get('image_model', 'imagen-4.0-generate-001'),
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                )
            )

            if not response.generated_images or len(response.generated_images) == 0:
                logging.error(f'[IMAGE] No images generated: {str(response)}')
                raise Exception(
                    f"⚠️ _{localized_text('error', bot_language)}._ "
                    f"⚠️\n{localized_text('try_again', bot_language)}."
                )

            # Get the first generated image
            generated_image = response.generated_images[0]
            
            if generated_image.image.image_bytes is not None:
                image_data = generated_image.image.image_bytes
                image_data = base64.b64decode(image_data)
                temp_filename = random_file_name('uploads', 'png')
                
                with open(temp_filename, 'wb') as f:
                    f.write(image_data)
                
                return temp_filename, "1024x1024"
                    
            elif generated_image.image.gcs_uri is not None:
                return generated_image.image.gcs_uri, "1024x1024"
                
            else:
                raise Exception("No image data received from Google AI")
            
        except Exception as e:
            logging.error(f'[IMAGE] Image generation error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    #########################################################
    # TTS/Whisper model
    #########################################################

    async def generate_speech(self, text: str) -> tuple[any, int]:
        """
        Generates an audio from the given text using TTS model.
        :param text: The text to send to the model
        :return: The audio in bytes and the text size
        """
        bot_language = self.config['bot_language']
        try:
            # Log TTS generation request
            logging.info(f'[TTS] TTS generation request: text="{text[:50]}...", model=gemini-2.5-flash-preview-tts')
            
            response = await self.client.aio.models.generate_content(
                model=self.config.get('tts_model', 'gemini-2.5-flash-preview-tts'),
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.config.get('tts_voice', 'Kore'),
                            )
                        )
                    ),
                )
            )

            if not response.candidates or len(response.candidates) == 0:
                logging.error(f'[TTS] No response from Google AI: {str(response)}')
                raise Exception(
                    f"⚠️ _{localized_text('error', bot_language)}._ "
                    f"⚠️\n{localized_text('try_again', bot_language)}."
                )

            # Get audio data and decode base64
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            import base64
            audio_data = base64.b64decode(audio_data)
            
            # Convert PCM to Opus for Telegram compatibility
            # Create temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
                with wave.open(wav_file.name, 'wb') as wf:
                    wf.setnchannels(1)  # Mono
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(24000)  # 24kHz
                    wf.writeframes(audio_data)
                
                # Convert to Opus
                opus_file = wav_file.name.replace('.wav', '.opus')
                subprocess.run([
                    'ffmpeg', '-i', wav_file.name, 
                    '-c:a', 'libopus', '-b:a', '64k',
                    '-y', opus_file
                ], check=True, capture_output=True)
                
                # Read Opus and return as BytesIO
                with open(opus_file, 'rb') as f:
                    opus_data = f.read()
                
                temp_file = io.BytesIO(opus_data)
                temp_file.seek(0)
                
                # Clean up temporary files
                os.unlink(wav_file.name)
                os.unlink(opus_file)
            
            logging.info(f'[TTS] TTS generation completed successfully, audio_size={len(audio_data)}')
            return temp_file, len(text)
            
        except Exception as e:
            logging.error(f'[TTS] TTS generation error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    async def transcribe(self, filename, prompt=None):
        """
        Transcribes the audio file using Google AI Gemini model.
        """
        bot_language = self.config['bot_language']
        try:
            # Log transcription request
            logging.info(f'[TRANSCRIBE] Transcription request: filename={filename}')
            
            # Read audio file
            with open(filename, 'rb') as f:
                audio_bytes = f.read()
            
            # Determine MIME type based on file extension
            mime_type = 'audio/mp3'  # default
            if filename.endswith('.wav'):
                mime_type = 'audio/wav'
            elif filename.endswith('.ogg'):
                mime_type = 'audio/ogg'
            elif filename.endswith('.opus'):
                mime_type = 'audio/opus'
            
            # Create transcription prompt
            # Use provided prompt, otherwise fall back to global whisper_prompt, then default
            transcription_prompt = "Транскрибуй це аудіо точно. Поверни тільки транскрибований текст без жодних додаткових коментарів. "
            if prompt:
                transcription_prompt += prompt
            elif 'whisper_prompt' in self.config and self.config['whisper_prompt']:
                transcription_prompt += self.config['whisper_prompt']
            
            # Send transcription request
            response = await self.client.aio.models.generate_content(
                model=self.config.get('transcription_model', 'gemini-2.5-flash'),
                contents=[
                    transcription_prompt,
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type=mime_type,
                    )
                ]
            )
            
            if not response.candidates or len(response.candidates) == 0:
                logging.error(f'[TRANSCRIBE] No response from Google AI: {str(response)}')
                raise Exception(
                    f"⚠️ _{localized_text('error', bot_language)}._ "
                    f"⚠️\n{localized_text('try_again', bot_language)}."
                )
            
            # Extract transcribed text
            transcribed_text = response.text
            logging.info(f'[TRANSCRIBE] Transcription completed: text_length={len(transcribed_text)}')
            
            return transcribed_text
            
        except Exception as e:
            logging.error(f'[TRANSCRIBE] Transcription error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

