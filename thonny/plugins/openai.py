import tkinter as tk
from tkinter import ttk
from typing import Iterator, List, Optional
from logging import getLogger

from thonny import get_workbench
from thonny.assistance import ChatContext, ChatMessage, ChatResponseChunk
from thonny.plugins.base_assistant import BaseAIAssistant
from thonny.ui_utils import create_url_label

logger = getLogger(__name__)


API_KEY_SECRET_KEY = "OpenAI.api_key"


class OpenAIApiKeyDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("OpenAI API Key")
        self.transient(master)
        self.grab_set()

        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        intro_label = ttk.Label(
            main_frame,
            text="This assistant requires an OpenAI API key.\nYou can get it from:",
        )
        intro_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        url_label = create_url_label(main_frame, "https://platform.openai.com/api-keys")
        url_label.grid(row=1, column=0, sticky="w", pady=(0, 15))

        key_label = ttk.Label(main_frame, text="API Key:")
        key_label.grid(row=2, column=0, sticky="w", pady=(0, 5))

        self.key_entry = ttk.Entry(main_frame, width=60, show="*")
        self.key_entry.grid(row=3, column=0, sticky="ew", pady=(0, 15))
        self.key_entry.focus_set()

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, sticky="e")

        ok_button = ttk.Button(button_frame, text="OK", command=self._ok, default="active")
        ok_button.grid(row=0, column=0, padx=(0, 5))

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._cancel)
        cancel_button.grid(row=0, column=1)

        self.bind("<Return>", lambda e: self._ok(), True)
        self.bind("<Escape>", lambda e: self._cancel(), True)

        self.api_key = None

    def _ok(self):
        key = self.key_entry.get().strip()
        if not key:
            # Don't close if empty
            self.key_entry.focus_set()
            return
        self.api_key = key
        self.destroy()

    def _cancel(self):
        self.api_key = None
        self.destroy()


class OpenAIAssistant(BaseAIAssistant):
    """OpenAI assistant implementation"""
    
    def __init__(self):
        super().__init__()
        self._client = None  # Cached OpenAI client
        self._configured_api_key = None  # Track which API key was configured
    
    def _get_saved_api_key(self) -> Optional[str]:
        return get_workbench().get_secret(API_KEY_SECRET_KEY)
    
    def _get_client(self):
        """Get or create cached OpenAI client"""
        from openai import OpenAI
        
        api_key = self._get_saved_api_key()
        
        # Recreate client if API key changed
        if api_key != self._configured_api_key or self._client is None:
            self._client = OpenAI(api_key=api_key)
            self._configured_api_key = api_key
        
        return self._client

    def _request_new_api_key(self) -> None:
        dlg = OpenAIApiKeyDialog(get_workbench())
        dlg.wait_window()  # Wait for dialog to close
        
        if dlg.api_key:
            logger.info(f"Saving OpenAI API key (length: {len(dlg.api_key)})")
            get_workbench().set_secret(API_KEY_SECRET_KEY, dlg.api_key)
            logger.info(f"OpenAI API key saved to: {get_workbench()._get_secrets_path()}")
        else:
            logger.info("OpenAI API key dialog cancelled or empty")
    
    def _prepare_messages(self, messages: List[ChatMessage]) -> List[dict]:
        """Convert ChatMessage list to OpenAI API format with image support"""
        out_msgs = []
        
        for msg in messages:
            formatted_content = self.format_message(msg)
            
            # If message has an image, use multimodal format
            if msg.image:
                content = [
                    {"type": "text", "text": formatted_content}
                ]
                # Add image in OpenAI format
                image_format = msg.image.get('format', 'jpeg')
                image_url = f"data:image/{image_format};base64,{msg.image['base64']}"
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
                out_msgs.append({"role": msg.role.to_openai(), "content": content})
            else:
                # Regular text message
                out_msgs.append({"role": msg.role.to_openai(), "content": formatted_content})
        
        return out_msgs
    
    def _send_to_api(self, system_prompt: str, messages: List[dict]) -> Iterator[ChatResponseChunk]:
        """Send request to OpenAI Responses API with full message history"""
        from openai import OpenAI, APIConnectionError, APIError

        try:
            # Use cached client
            client = self._get_client()

            # Combine system message with history
            all_messages = [{"role": "system", "content": system_prompt}] + messages

            # Use selected model API name from new system
            model_name = get_workbench().get_option("ai.selected_model_api_name", "gpt-5")
            logger.info(f"🤖 OpenAI: sending request with model '{model_name}'")
            response = client.responses.create(
                model=model_name,
                input=all_messages,
                stream=False,
            )

            # Get response content
            content = response.output_text if hasattr(response, 'output_text') else (response.output if hasattr(response, 'output') else "")
            if content:
                yield ChatResponseChunk(content)
            else:
                yield ChatResponseChunk("❌ **AI не повернув відповідь**")
            
        except APIConnectionError as e:
            error_msg = "❌ **Помилка з'єднання з OpenAI API**\n\nПеревірте підключення до інтернету."
            yield ChatResponseChunk(error_msg)
        except APIError as e:
            error_msg = f"❌ **Помилка OpenAI API**\n\n{str(e)}"
            yield ChatResponseChunk(error_msg)
        except Exception as e:
            error_msg = f"❌ **Неочікувана помилка**\n\n{str(e)}"
            yield ChatResponseChunk(error_msg)
    
    def explain_diagnostic(self, program_code: str, diagnostic_message: str, severity_type: str, line_number: int = None) -> str:
        """Fast diagnostic explanation using gpt-4o-mini"""
        from openai import OpenAI, APIConnectionError, APIError
        from thonny.prompts import PromptType, get_prompt
        
        try:
            # Get language and prompt
            language = self._get_language()
            prompt = get_prompt(
                PromptType.USER_EXPLAIN_DIAGNOSTIC,
                language=language,
                code=program_code,
                diagnostic=diagnostic_message,
                severity_type=severity_type,
                line_number=line_number or "unknown"
            )
            
            # Use cached client and fast model
            client = self._get_client()
            model_name = "gpt-4o-mini"
            logger.info(f"🤖 OpenAI: explaining diagnostic with model '{model_name}'")
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                
            )
            
            return response.choices[0].message.content.strip() if response.choices[0].message.content else "⚠️ Немає відповіді від GPT"
            
        except Exception as e:
            logger.exception("Error in explain_diagnostic")
            return f"⚠️ Помилка: {str(e)}"


def load_plugin():
    get_workbench().add_assistant("OpenAI", OpenAIAssistant())
    # Debug mode is the same assistant, just routes to _complete_debug_step
    get_workbench().add_assistant("DebugAI", OpenAIAssistant())
