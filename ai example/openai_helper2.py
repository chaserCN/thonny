from __future__ import annotations
import datetime
import logging
import base64
import warnings

import openai

# Filter out Pydantic field shadowing warnings
warnings.filterwarnings('ignore', message='Field name.*shadows an attribute')

import json
import httpx
import io
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from plugin_manager import PluginManager
from utils import is_direct_result, direct_result_kind, localized_text, print_object, random_file_name
from constants import MULTIUSER_CHAT_INSTRUCTIONS

class OpenAIHelper2:
    def __init__(self, config: dict, plugin_manager: PluginManager):
        """
        Initializes the OpenAI helper class with the given configuration.
        :param config: A dictionary containing the GPT configuration
        :param plugin_manager: The plugin manager
        """

        self.client = openai.AsyncOpenAI(api_key=config['api_key']) 
        self.config = config
        self.plugin_manager = plugin_manager
        self.last_response_ids: dict[int: str] = {}  # {chat_id: last_response_id}
        self.last_updated: dict[int: datetime] = {}  # {chat_id: last_update_timestamp}

    #########################################################
    # Chat model
    #########################################################

    async def get_chat_response(self, chat_id: int, query: str, user_name: str | None) -> Dict | str:
        response = await self.__send_query(chat_id, query, user_name, stream=False)    

        new_response, plugins_used = await self.__handle_function_call(chat_id, response, stream=False)
        if is_direct_result(new_response):
            return new_response

        self.last_response_ids[chat_id] = new_response.id

        result = await self.__process_nonfunction_response(new_response)
        result = self.__add_plugins_info(result, plugins_used)

        return result

    async def get_chat_response_stream(self, chat_id: int, query: str, user_name: str | None) -> tuple[str, bool]:
        response = await self.__send_query(chat_id, query, user_name, stream=True)
        
        response, plugins_used = await self.__handle_function_call(chat_id, response, stream=True)
        if is_direct_result(response):
            yield response, True
            return

        answer = ''

        async for event in response:
            if event.type == 'response.output_text.delta':
                answer += event.delta
                yield answer, False
                
            elif event.type == 'response.completed':
                self.last_response_ids[chat_id] = event.response.id

                result = await self.__process_nonfunction_response(event.response)
                result = self.__add_plugins_info(result, plugins_used)

                yield result, True
                return
                
            elif event.type == 'response.web_search_call.in_progress' or event.type == 'response.web_search_call.searching':
                yield answer + f"\n🔍 _{localized_text('web_search_in_progress', self.config['bot_language'])}_", False
                
            elif event.type == 'response.web_search_call.completed':
                yield answer + f"\n✅ _{localized_text('web_search_completed', self.config['bot_language'])}_", False

            elif event.type == 'error':
                raise Exception(f"Streaming error: {event.error}")

        # Fallback if we didn't get a completion event
        answer = answer.strip()
        result = self.__add_plugins_info(answer, plugins_used)

        yield result, True

    @retry(
        reraise=True,
        retry=retry_if_exception_type(openai.RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __send_query(self, chat_id: int, query: str, user_name: str | None, stream=False):
        bot_language = self.config['bot_language']
        try:
            if self.__max_age_reached(chat_id):
                self.last_response_ids[chat_id] = None

            self.last_updated[chat_id] = datetime.datetime.now()

            if user_name:
                query = f"{user_name} says: {query}"

            common_args = {
                'model': self.config['model'],
                'input': query,
                'stream': stream    
            }

            instructions = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                instructions += self.config['assistant_prompt']
            common_args['instructions'] = instructions

            if chat_id in self.last_response_ids and self.last_response_ids[chat_id]:
                common_args['previous_response_id'] = self.last_response_ids[chat_id]

            tools = self.__tools_for_request()
            if tools:
                common_args['tools'] = tools
                common_args['tool_choice'] = 'auto'

            #print(f"common_args: {json.dumps(common_args, indent=2, ensure_ascii=False)}")

            return await self.client.responses.create(**common_args)

        except openai.RateLimitError as e:
            raise e

        except openai.BadRequestError as e:
            raise Exception(f"⚠️ _{localized_text('openai_invalid', bot_language)}._ ⚠️\n{str(e)}") from e

        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    async def __handle_function_call(self, chat_id, response, stream=False, times=1, plugins_used=()):
        logging.info(f"__handle_function_call: chat_id={chat_id}, stream={stream}, times={times}, plugins_used={plugins_used}")
        if stream:
            final_tool_calls = {}
            response_id = None

            async for event in response:
                if response_id is None and hasattr(event, 'response') and hasattr(event.response, 'id'):
                    response_id = event.response.id
                    print_object("__handle_function_call response_id!!!:", response_id)
                
                if event.type == 'response.output_item.added':
                    if event.item.type == 'function_call':
                        final_tool_calls[event.output_index] = event.item
                    else:
                        return response, plugins_used
                elif event.type == 'response.function_call_arguments.done':
                    index = event.output_index
                    if index in final_tool_calls:
                        final_tool_calls[index].arguments = event.arguments
            
            if final_tool_calls:
                function_calls = list(final_tool_calls.values())
                return await self.__execute_function_calls(chat_id, function_calls, stream, times, plugins_used, response_id)
            else:
                return response, plugins_used
        else:
            if not response.output:
                return response, plugins_used
            
            function_calls = []
            for output_item in response.output:
                if output_item.type == "function_call":
                    function_calls.append(output_item)
            
            if len(function_calls) == 0:
                logging.info(f"__handle_function_call: no function calls found, returning response")
                return response, plugins_used
            
            logging.info(f"__handle_function_call: found {len(function_calls)} function calls, executing...")
            return await self.__execute_function_calls(chat_id, function_calls, stream, times, plugins_used, response.id)

    @retry(
        reraise=True,
        retry=retry_if_exception_type(openai.RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __execute_function_calls(self, chat_id, function_calls, stream, times, plugins_used, response_id):
        import json
        
        logging.info(f"__execute_function_calls: chat_id={chat_id}, function_calls_count={len(function_calls)}, stream={stream}, times={times}, response_id={response_id}")
        
        input_list = []
        
        for function_call in function_calls:
            function_name = function_call.name
            arguments = function_call.arguments 
            
            logging.info(f"__execute_function_calls: calling function '{function_name}' with arguments: {arguments}")
            function_response = await self.plugin_manager.call_function(function_name, self, arguments)
            logging.info(f"__execute_function_calls: function '{function_name}' returned: {type(function_response)}")
            
            if function_name not in plugins_used:
                plugins_used += (function_name,)
            
            input_list.append({
                "type": "function_call",
                "name": function_call.name,
                "arguments": function_call.arguments,
                "call_id": function_call.call_id
            })

            if is_direct_result(function_response):
                logging.info(f"__execute_function_calls: function '{function_name}' returned direct_result, making follow-up call to notify ChatGPT")
                
                input_list.append({
                    "type": "function_call_output",
                    "call_id": function_call.call_id,
                    "output": f"success, {direct_result_kind(function_response)} was sent to the users."
                })

                # Робимо follow-up виклик без tools (бо результат вже готовий)
                common_args = {
                    'model': self.config['model'],
                    'input': input_list,
                    'stream': False
                }

                if response_id:
                    common_args['previous_response_id'] = response_id
                elif chat_id in self.last_response_ids and self.last_response_ids[chat_id]:
                    common_args['previous_response_id'] = self.last_response_ids[chat_id]

                print(f"__execute_function_calls direct_result follow-up: {json.dumps(common_args, indent=2, ensure_ascii=False)}")
                new_response = await self.client.responses.create(**common_args)

                logging.info(f"__execute_function_calls: follow-up API call completed, handling response, {new_response.output_text}")      

                self.last_response_ids[chat_id] = new_response.id
                
                return function_response, plugins_used


            input_list.append({
                "type": "function_call_output",
                "call_id": function_call.call_id,
                "output": json.dumps(function_response) if isinstance(function_response, (dict, list)) else str(function_response)
            })

        common_args = {
            'model': self.config['model'],
            'input': input_list,
            'stream': stream
        }

        if response_id:
            common_args['previous_response_id'] = response_id
        elif chat_id in self.last_response_ids and self.last_response_ids[chat_id]:
            common_args['previous_response_id'] = self.last_response_ids[chat_id]
        
        tools = self.__tools_for_request()        
        if tools:
            common_args['tools'] = tools
            common_args['tool_choice'] = 'auto' if times < self.config.get('functions_max_consecutive_calls', 5) else 'none'

        print(f"__execute_function_calls common_args: {json.dumps(common_args, indent=2, ensure_ascii=False)}")
        new_response = await self.client.responses.create(**common_args)
        logging.info(f"__execute_function_calls: follow-up API call completed, handling response")
        
        return await self.__handle_function_call(chat_id, new_response, stream, times + 1, plugins_used)

    async def __process_nonfunction_response(self, response) -> Dict | str:
        new_response = self.__handle_generated_image(response)
        if is_direct_result(new_response):
            return new_response

        answer = self.__extract_text_from_response(response)
        
        has_web_search = any(output.type == "web_search_call" for output in response.output or [])
        if has_web_search:
            web_search_prefix = localized_text('web_search_result', self.config['bot_language'])
            answer = f"<i>{web_search_prefix}</i>\n\n{answer}"
        
        return answer

    def __handle_generated_image(self, response) -> Dict | None:
        image_data = [
            output.result
            for output in response.output
            if output.type == "image_generation_call"
        ]

        if len(image_data) == 0:
            return None

        filepath = random_file_name(directory_name="uploads/images") 
            
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(image_data[0]))  # Використовуємо перший елемент
            
        direct_result = {
            'direct_result': {
                'kind': 'photo',
                'format': 'path',
                'value': filepath
            }
        }
        
        return direct_result

    def __extract_text_from_response(self, response) -> str:
        try:
            return next(
                content_item.text
                for output_item in response.output or []
                if output_item.type == "message"
                for content_item in output_item.content or []
                if content_item.type == "output_text"
            ).strip()
        except StopIteration:
            return ""

    def __add_plugins_info(self, result, plugins_used):
        if isinstance(result, str) and len(plugins_used) > 0 and self.config['show_plugins_used']:
            plugin_names = tuple(
                self.plugin_manager.get_plugin_source_name_with_icon(plugin) for plugin in plugins_used)
            result += f"\n\n---\n{', '.join(plugin_names)}"
        
        return result

    def __tools_for_request(self) -> Dict:
        tools = []
        
        functions = self.plugin_manager.get_functions_specs()
        if len(functions) > 0:
            tools.extend(functions)
        
        # Add web search only if enabled in config
        if self.config.get('enable_web_search', True):
            tools.append({"type": "web_search_preview"})

        return tools

    def __max_age_reached(self, chat_id) -> bool:
        if chat_id not in self.last_updated:
            return True
        age = datetime.datetime.now() - self.last_updated[chat_id]
        return age.total_seconds() > self.config['max_conversation_age_minutes'] * 60

    #########################################################
    # Vision
    #########################################################

    async def interpret_image(self, chat_id: int, fileobj, user_name: str | None, prompt=None) -> str | Dict:
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt)

        answer = self.__extract_text_from_response(response)
        self.last_response_ids[chat_id] = response.id

        return answer

    async def interpret_image_stream(self, chat_id: int, fileobj, user_name: str | None, prompt=None) -> tuple[str, bool, bool]:
        response = await self.__send_vision_query(chat_id, fileobj, user_name, prompt, stream=True)

        answer = ''

        async for event in response:
            if event.type == 'response.output_text.delta':
                answer += event.delta
                yield answer, False, False
                
            elif event.type == 'response.completed':
                self.last_response_ids[chat_id] = event.response.id
                result = await self.__process_nonfunction_response(event.response)
                yield result, True, True
                return
                
            elif event.type == 'response.web_search_call.in_progress' or event.type == 'response.web_search_call.searching':
                yield answer + f"\n🔍 _{localized_text('web_search_in_progress', self.config['bot_language'])}_", False, True
                
            elif event.type == 'response.web_search_call.completed':
                yield answer + f"\n✅ _{localized_text('web_search_completed', self.config['bot_language'])}_", False, True

            elif event.type == 'error':
                raise Exception(f"Streaming error: {event.error}")

        # Fallback if we didn't get a completion event
        answer = answer.strip()
        
        yield answer, True, True

    @retry(
        reraise=True,
        retry=retry_if_exception_type(openai.RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __send_vision_query(self, chat_id: int, fileobj, user_name: str | None, prompt=None, stream=False):
        bot_language = self.config['bot_language']
        try:
            if self.__max_age_reached(chat_id):
                self.last_response_ids[chat_id] = None
            self.last_updated[chat_id] = datetime.datetime.now()

            # Set default prompt if none provided and no history
            if not prompt or not prompt.strip():
                if not (chat_id in self.last_response_ids and self.last_response_ids[chat_id]):
                    # No history - use default vision prompt
                    prompt = self.config['vision_prompt']
            if user_name and prompt and prompt.strip():
                prompt = f"{user_name}: {prompt}"
            else:
                prompt = f"{user_name} sends a picture"

            base64_image = base64.b64encode(fileobj.getvalue()).decode('utf-8')

            content = [{"type": "input_text", "text": prompt}, 
                       {"type": "input_image", "image_url": f'data:image/jpeg;base64,{base64_image}'}]

            common_args = {
                'model': self.config['model'],
                'input': [{"role":"user", "content":content}],
                'stream': stream
            }

            instructions = MULTIUSER_CHAT_INSTRUCTIONS
            if 'assistant_prompt' in self.config and self.config['assistant_prompt']:
                instructions += self.config['assistant_prompt']
            common_args['instructions'] = instructions

            if chat_id in self.last_response_ids and self.last_response_ids[chat_id]:
                common_args['previous_response_id'] = self.last_response_ids[chat_id]

            #print(f"common_args: {json.dumps(common_args, indent=2, ensure_ascii=False)}")

            return await self.client.responses.create(**common_args)

        except openai.RateLimitError as e:
            raise e

        except openai.BadRequestError as e:
            raise Exception(f"⚠️ _{localized_text('openai_invalid', bot_language)}._ ⚠️\n{str(e)}") from e

        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    #########################################################
    # Image model
    #########################################################

    async def generate_image(self, prompt: str) -> tuple[str, str]:
        bot_language = self.config['bot_language']
        try:
            response = await self.client.images.generate(
                prompt=prompt,
                n=1,
                model=self.config.get('image_model', 'gpt-image-1'),
                quality=self.config['image_quality'],
                style=self.config['image_style'],
                size=self.config['image_size']
            )

            #print_object("generate_image response:", response)

            if len(response.data) == 0:
                logging.error(f'No response from GPT: {str(response)}')
                raise Exception(
                    f"⚠️ _{localized_text('error', bot_language)}._ "
                    f"⚠️\n{localized_text('try_again', bot_language)}."
                )

            return response.data[0].url, self.config['image_size']
        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    #########################################################
    # TTS/Whisper model
    #########################################################

    async def generate_speech(self, text: str) -> tuple[any, int]:
        """
        Generates an audio from the given text using TTS model.
        :param prompt: The text to send to the model
        :return: The audio in bytes and the text size
        """
        bot_language = self.config['bot_language']
        try:
            response = await self.client.audio.speech.create(
                model=self.config['tts_model'],
                voice=self.config['tts_voice'],
                input=text,
                response_format='opus'
            )

            temp_file = io.BytesIO()
            temp_file.write(response.read())
            temp_file.seek(0)
            return temp_file, len(text)
        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    async def transcribe(self, filename, prompt=None):
        """
        Transcribes the audio file using the Whisper model.
        """
        try:
            with open(filename, "rb") as audio:
                # Create transcription prompt with Ukrainian base
                prompt_text = "Транскрибуй це аудіо точно. Поверни тільки транскрибований текст без жодних додаткових коментарів. "
                
                # Add specific prompt from caption or config
                if prompt:
                    prompt_text += prompt
                elif self.config['whisper_prompt']:
                    prompt_text += self.config['whisper_prompt']
                
                print(f"transcribe prompt: {prompt_text}")
                result = await self.client.audio.transcriptions.create(model="whisper-1", file=audio, prompt=prompt_text)
                return result.text
        except Exception as e:
            logging.exception(e)
            raise Exception(f"⚠️ _{localized_text('error', self.config['bot_language'])}._ ⚠️\n{str(e)}") from e

    def reset_chat_history(self, chat_id, content=''):
        if chat_id in self.last_response_ids:
            del self.last_response_ids[chat_id]
        if chat_id in self.last_updated:
            del self.last_updated[chat_id]
        logging.info(f'Chat history reset for chat {chat_id}')