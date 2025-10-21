from __future__ import annotations
import datetime
import logging
import base64
import io
from enum import Enum
from typing import Dict

import anthropic
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from plugin_manager import PluginManager
from utils import is_direct_result, direct_result_kind, localized_text
from constants import MULTIUSER_CHAT_INSTRUCTIONS

console = Console()

class Role(Enum):
    USER = "user"
    ASSISTANT = "assistant"

class ClaudeHelper:
    def __init__(self, config: dict, plugin_manager: PluginManager):
        """
        Initializes the Claude helper class with the given configuration.
        :param config: A dictionary containing the Claude configuration
        :param plugin_manager: The plugin manager
        """
        self.client = anthropic.AsyncAnthropic(api_key=config['api_key'])
        self.config = config
        self.plugin_manager = plugin_manager
        self.conversations: dict[int: list] = {}  # {chat_id: conversation_history}
        self.last_updated: dict[int: datetime] = {}  # {chat_id: last_update_timestamp}

    def reset_chat_history(self, chat_id: int, content=''):
        """Reset the conversation history for a specific chat"""
        self.conversations[chat_id] = []

    def __add_to_history(self, chat_id: int, role: Role, content: str):
        """Add a message to the conversation history"""
        if chat_id not in self.conversations or not self.conversations[chat_id]:
            self.conversations[chat_id] = []

        self.conversations[chat_id].append({
            "role": role.value,
            "content": content
        })

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
            role = msg["role"]
            content = msg["content"]
            
            # Color coding based on role
            if role == "user":
                role_color = "[bold green]"
                content_color = "[green]"
            elif role == "assistant":
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
        logging.info(f'[CLAUDE NON-STREAM] Starting get_chat_response: chat_id={chat_id}, query="{query[:50]}..."')        
        
        response = await self.__send_query(chat_id, query, user_name, stream=False)    
        
        return await self.__process_nonstreaming_response(response, chat_id)

    async def get_chat_response_stream(self, chat_id: int, query: str, user_name: str | None) -> tuple[str, bool]:
        logging.info(f'[CLAUDE STREAM] Starting get_chat_response_stream: chat_id={chat_id}, query="{query[:50]}..."')

        response = await self.__send_query(chat_id, query, user_name, stream=True)
        
        async for answer, is_final in self.__process_streaming_response(response, chat_id):
            yield answer, is_final

    @retry(
        reraise=True,
        retry=retry_if_exception_type(Exception),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __send_query(self, chat_id: int, query: str, user_name: str | None, stream=False):
        bot_language = self.config['bot_language']
        try:
            if chat_id not in self.conversations or self.__max_age_reached(chat_id):
                self.reset_chat_history(chat_id)

            self.last_updated[chat_id] = datetime.datetime.now()

            if user_name:
                query = f"{user_name}: {query}"

            self.__add_to_history(chat_id, role=Role.USER, content=query)

            # Prepare system instruction
            system_instruction = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                system_instruction += self.config['assistant_prompt']


            console.print(f"[bold yellow]🚀 [CLAUDE SEND] API request:[/bold yellow] [cyan]model={self.config['model']}, stream={stream}, history_length={len(self.conversations[chat_id])}[/cyan]")
            logging.info(f'[CLAUDE SEND] API request: model={self.config["model"]}, stream={stream}, history_length={len(self.conversations[chat_id])}')
            
            # Debug: print request parameters for text messages
            console.print(f"[bold cyan]📋 [CLAUDE DEBUG] Request parameters:[/bold cyan]")
            console.print(f"  model: {self.config['model']}")
            console.print(f"  max_tokens: 32000")
            console.print(f"  stream: {stream}")
            console.print(f"  web_search_enabled: always")
            console.print(f"  system_instruction length: {len(system_instruction)}")
            console.print(f"  messages count: {len(self.conversations[chat_id])}")
            for i, msg in enumerate(self.conversations[chat_id]):
                console.print(f"    message {i}: role={msg['role']}, content_length={len(msg['content'])}")

            # Prepare request parameters
            request_params = {
                'model': self.config['model'],
                'max_tokens': 32000,
                'system': system_instruction,
                'messages': self.conversations[chat_id],
                'stream': stream
            }
            
            # Prepare tools (web search)
            tools = self.__tools_for_request()
            if tools:
                request_params['tools'] = tools

            response = await self.client.messages.create(**request_params)

            logging.info(f'[CLAUDE SEND] Response received: type={type(response).__name__}')
            return response

        except Exception as e:
            logging.error(f'[CLAUDE SEND] General error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    def __tools_for_request(self) -> list:
        """Prepare tools for Claude API request"""
        web_search_tool = {
            "type": "web_search_20250305", 
            "name": "web_search",
            "max_uses": 5
        }
        
        return [web_search_tool]

    async def __process_nonstreaming_response(self, response, chat_id: int) -> str:
        try:
            answer = ""
            has_web_search = False
            
            for content_block in response.content:
                if content_block.type == "text":
                    answer += content_block.text
                elif content_block.type == "tool_use" and content_block.name == "web_search":
                    has_web_search = True
            
            answer = answer or ""
            
            logging.info(f'[CLAUDE NON-STREAM] Processed response: answer_length={len(answer)}, has_web_search={has_web_search}')
            
            if not answer.strip():
                logging.warning(f'[CLAUDE NON-STREAM] Empty response detected, using fallback message')
                answer = localized_text('empty_response', self.config['bot_language'])
            
            # Add web search prefix if used
            if has_web_search:
                logging.info(f'[CLAUDE NON-STREAM] Adding web search prefix')
                web_search_prefix = localized_text('web_search_result', self.config['bot_language'])
                answer = f"<i>{web_search_prefix}</i>\n\n{answer}"
            
            # Add to history
            self.__add_to_history(chat_id, role=Role.ASSISTANT, content=answer)
            
            console.print(f"[bold green]✅ [CLAUDE NON-STREAM] Final result:[/bold green] [cyan]length={len(answer)}, web_search={has_web_search}[/cyan]")

            return answer
        except Exception as e:
            logging.error(f'[CLAUDE NON-STREAM] Processing error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', self.config['bot_language'])}._ ⚠️\n{str(e)}") from e

    async def __process_streaming_response(self, response, chat_id: int) -> tuple[str, bool]:
        """
        Process streaming response and yield chunks with final status
        :param response: The streaming response from Claude
        :param chat_id: Chat ID for history management
        :yield: Tuple of (answer, is_final)
        """
        answer = ''
        chunk_count = 0
        has_web_search = False

        try:
            async for event in response:
                chunk_count += 1
                
                if event.type == "content_block_delta":
                    if hasattr(event.delta, 'text'):
                        chunk_text = event.delta.text
                        answer += chunk_text
                        logging.info(f'[CLAUDE STREAM] Chunk {chunk_count}: text_length={len(chunk_text)}, total_length={len(answer)}')
                        yield answer, False
                        
                elif event.type == "content_block_start":
                    if hasattr(event.content_block, 'name') and event.content_block.name == "web_search":
                        has_web_search = True
                        logging.info(f'[CLAUDE STREAM] Web search detected in chunk {chunk_count}')
                        
                elif event.type == "message_stop":
                    logging.info(f'[CLAUDE STREAM] Final chunk {chunk_count} received')
                    break

            console.print(f"[bold blue]🔄 [CLAUDE STREAM] Streaming completed:[/bold blue] [cyan]chunks={chunk_count}, response_length={len(answer)}, web_search={has_web_search}[/cyan]")
            logging.info(f'[CLAUDE STREAM] Streaming completed: chunks={chunk_count}, response_length={len(answer)}, web_search={has_web_search}')

            # Check if answer is not empty
            if not answer.strip():
                logging.warning(f'[CLAUDE STREAM] Empty response detected')
                answer = localized_text('empty_response', self.config['bot_language'])
            
            # Add web search prefix if used
            if has_web_search:
                logging.info(f'[CLAUDE STREAM] Adding web search prefix')
                web_search_prefix = localized_text('web_search_result', self.config['bot_language'])
                answer = f"<i>{web_search_prefix}</i>\n\n{answer}"
            
            # Add to history for all responses
            self.__add_to_history(chat_id, role=Role.ASSISTANT, content=answer)
            
            yield answer, True
            
        except Exception as e:
            logging.error(f'[CLAUDE STREAM] Streaming error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', self.config['bot_language'])}._ ⚠️\n{str(e)}") from e

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
        logging.info(f'[CLAUDE VISION] Vision request: prompt="{prompt}", user_name={user_name}')
        
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt)

        return await self.__process_vision_response(response, chat_id)

    async def interpret_image_stream(self, chat_id: int, fileobj, user_name: str | None, prompt=None) -> tuple[str, bool, bool]:
        # Log streaming vision request
        logging.info(f'[CLAUDE VISION] Starting interpret_image_stream: prompt="{prompt}", user_name={user_name}')
        
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt, stream=True)
        
        async for answer, is_final in self.__process_streaming_vision_response(response, chat_id):
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
            logging.info(f'[CLAUDE VISION] Vision API request: model={self.config["model"]}, prompt="{prompt}", stream={stream}')

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
            
            # Encode image to base64
            image_bytes = fileobj.getvalue()
            image_data = base64.b64encode(image_bytes).decode('utf-8')
            
            # Determine media type by checking image header (magic bytes)
            if image_bytes.startswith(b'\x89PNG'):
                media_type = "image/png"
            elif image_bytes.startswith(b'\xff\xd8\xff'):
                media_type = "image/jpeg"
            elif image_bytes.startswith(b'RIFF') and b'WEBP' in image_bytes[:12]:
                media_type = "image/webp"
            elif image_bytes.startswith(b'GIF87a') or image_bytes.startswith(b'GIF89a'):
                media_type = "image/gif"
            else:
                # Default to JPEG if we can't detect the type
                # (most common format from mobile cameras)
                media_type = "image/jpeg"
            
            # Create message content with image and text
            content = []
            
            # Add image
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data
                }
            })
            
            # Add text prompt if provided
            if prompt and prompt.strip():
                content.append({
                    "type": "text",
                    "text": prompt
                })
            
            # Create messages list - if we have conversation history, include it, then add current message
            if chat_id in self.conversations and self.conversations[chat_id]:
                # Include conversation history
                messages = self.conversations[chat_id].copy()
                messages.append({
                    "role": "user",
                    "content": content
                })
            else:
                # No history, just send current image and prompt
                messages = [{
                    "role": "user", 
                    "content": content
                }]

            # Create system instructions
            logging.info(f'[CLAUDE VISION] Creating config with system instructions')
            system_instruction = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                system_instruction += self.config['assistant_prompt']
                logging.info(f'[CLAUDE VISION] Added assistant prompt: {self.config["assistant_prompt"]}')

            # Send vision request
            if stream:
                response = await self.client.messages.create(
                    model=self.config['model'],
                    max_tokens=32000,
                    system=system_instruction,
                    messages=messages,
                    stream=True
                )
            else:
                response = await self.client.messages.create(
                    model=self.config['model'],
                    max_tokens=32000,
                    system=system_instruction,
                    messages=messages
                )

            logging.info(f'[CLAUDE VISION] Response received: type={type(response).__name__}')

            return response

        except Exception as e:
            logging.error(f'[CLAUDE VISION] Vision general error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    async def __process_vision_response(self, response, chat_id: int) -> str:
        """Process non-streaming vision response"""
        try:
            answer = ""
            for content_block in response.content:
                if content_block.type == "text":
                    answer += content_block.text
            
            answer = answer or ""
            
            if not answer.strip():
                answer = localized_text('empty_response', self.config['bot_language'])
            
            # Add to history
            self.__add_to_history(chat_id, role=Role.ASSISTANT, content=answer)
            
            return answer
        except Exception as e:
            logging.error(f'[CLAUDE VISION] Processing error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', self.config['bot_language'])}._ ⚠️\n{str(e)}") from e

    async def __process_streaming_vision_response(self, response, chat_id: int) -> tuple[str, bool]:
        """Process streaming vision response"""
        answer = ''
        chunk_count = 0

        try:
            async for event in response:
                chunk_count += 1
                
                if event.type == "content_block_delta":
                    if hasattr(event.delta, 'text'):
                        chunk_text = event.delta.text
                        answer += chunk_text
                        yield answer, False
                        
                elif event.type == "message_stop":
                    break

            if not answer.strip():
                answer = localized_text('empty_response', self.config['bot_language'])
            
            # Add to history
            self.__add_to_history(chat_id, role=Role.ASSISTANT, content=answer)
            
            yield answer, True
            
        except Exception as e:
            logging.error(f'[CLAUDE VISION STREAM] Streaming error: {str(e)}')
            raise Exception(f"⚠️ _{localized_text('error', self.config['bot_language'])}._ ⚠️\n{str(e)}") from e

    #########################################################
    # Image model (Not supported by Claude natively)
    #########################################################

    async def generate_image(self, prompt: str) -> tuple[str, str]:
        """
        Claude doesn't support image generation natively.
        This method raises an exception to indicate it's not supported.
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\nImage generation is not supported by Claude API. Consider using other models for image generation.")

    #########################################################
    # TTS/Whisper model (Not supported by Claude natively)
    #########################################################

    async def generate_speech(self, text: str) -> tuple[any, int]:
        """
        Claude doesn't support TTS natively.
        This method raises an exception to indicate it's not supported.
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\nText-to-speech is not supported by Claude API. Consider using other models for TTS.")

    async def transcribe(self, filename, prompt=None):
        """
        Claude doesn't support audio transcription natively.
        This method raises an exception to indicate it's not supported.
        """
        bot_language = self.config['bot_language']
        raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\nAudio transcription is not supported by Claude API. Consider using other models for transcription.")
