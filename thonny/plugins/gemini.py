import tkinter as tk
from tkinter import ttk
from typing import Iterator, List, Optional

from thonny import get_workbench
from thonny.assistance import ChatContext, ChatMessage, ChatResponseChunk
from thonny.plugins.base_assistant import BaseAIAssistant
from thonny.ui_utils import create_url_label


API_KEY_SECRET_KEY = "Gemini.api_key"


class GeminiApiKeyDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Gemini API Key")
        self.transient(master)
        self.grab_set()

        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        intro_label = ttk.Label(
            main_frame,
            text="This assistant requires a Gemini API key.\nYou can get it from:",
        )
        intro_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        url_label = create_url_label(main_frame, "https://aistudio.google.com/app/apikey")
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


class GeminiAssistant(BaseAIAssistant):
    """Gemini assistant implementation"""
    
    def _get_saved_api_key(self) -> Optional[str]:
        return get_workbench().get_secret(API_KEY_SECRET_KEY)

    def _request_new_api_key(self) -> None:
        from logging import getLogger
        logger = getLogger(__name__)
        
        dlg = GeminiApiKeyDialog(get_workbench())
        dlg.wait_window()  # Wait for dialog to close
        
        if dlg.api_key:
            logger.info(f"Saving Gemini API key (length: {len(dlg.api_key)})")
            get_workbench().set_secret(API_KEY_SECRET_KEY, dlg.api_key)
            logger.info(f"Gemini API key saved to: {get_workbench()._get_secrets_path()}")
        else:
            logger.info("Gemini API key dialog cancelled or empty")
    
    def _prepare_messages(self, messages: List[ChatMessage]) -> List[dict]:
        """Convert ChatMessage list to Gemini API format with image support"""
        import base64
        
        history = []
        
        for msg in messages:
            role = msg.role.to_gemini()
            parts = [self.format_message(msg)]
            
            # Add image if present
            if msg.image:
                mime_type = f"image/{msg.image.get('format', 'jpeg')}"
                image_data = base64.b64decode(msg.image['base64'])
                # Use blob format for Gemini
                image_blob = {'mime_type': mime_type, 'data': image_data}
                parts.append(image_blob)
            
            history.append({
                "role": role,
                "parts": parts
            })
        
        return history
    
    def _send_to_api(self, system_prompt: str, messages: List[dict]) -> Iterator[ChatResponseChunk]:
        """Send request to Gemini API and stream response"""
        import google.generativeai as genai
        from google.api_core import exceptions as google_exceptions

        try:
            genai.configure(api_key=self._get_saved_api_key())
            
            # Create model with system instruction
            model_name = get_workbench().get_option("ai.gemini_model", "gemini-2.5-pro")
            model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
            
            # Separate last message from history
            if not messages:
                yield ChatResponseChunk("")
                return
            
            chat_history = messages[:-1]  # All except last
            last_message_parts = messages[-1]["parts"]  # Last message parts
            
            # Start chat with history
            chat = model.start_chat(history=chat_history)
            
            # Get complete response (no streaming to UI)
            response = chat.send_message(last_message_parts, stream=False)
            
            try:
                full_text = response.text

                print(f"Full text: {full_text}")

                if full_text:
                    yield ChatResponseChunk(full_text)
                else:
                    error_msg = "❌ **AI не повернув відповідь**\n\nСпробуйте перефразувати питання."
                    yield ChatResponseChunk(error_msg)
            except (ValueError, AttributeError) as e:
                error_msg = f"❌ **Помилка відповіді**\n\n{str(e)}"
                yield ChatResponseChunk(error_msg)
            
        except google_exceptions.ServiceUnavailable as e:
            error_msg = "❌ **Помилка з'єднання з Gemini API**\n\nПеревірте підключення до інтернету."
            yield ChatResponseChunk(error_msg)
        except google_exceptions.GoogleAPIError as e:
            error_msg = f"❌ **Помилка Gemini API**\n\n{str(e)}"
            yield ChatResponseChunk(error_msg)
        except Exception as e:
            error_msg = f"❌ **Неочікувана помилка**\n\n{str(e)}"
            yield ChatResponseChunk(error_msg)
    
    def explain_diagnostic(self, program_code: str, diagnostic_message: str, severity_type: str) -> str:
        """Fast diagnostic explanation using gemini-2.5-flash-lite"""
        import google.generativeai as genai
        from thonny.prompts import PromptType, get_prompt
        from logging import getLogger
        
        logger = getLogger(__name__)
        
        try:
            # Get language and prompt
            language = self._get_language()
            prompt = get_prompt(
                PromptType.USER_EXPLAIN_DIAGNOSTIC,
                language=language,
                code=program_code,
                diagnostic=diagnostic_message,
                severity_type=severity_type
            )

            #print(f"Prompt: {prompt}")
            
            # Use fast model
            genai.configure(api_key=self._get_saved_api_key())
            model = genai.GenerativeModel('gemini-2.5-flash-lite')
            
            # Fast request
            response = model.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.2
                }
            )

            #print(f"Response: {response}")
            
            return response.text.strip() if response.text else "⚠️ Немає відповіді від Gemini"
            
        except Exception as e:
            logger.exception("Error in explain_diagnostic")
            return f"⚠️ Помилка: {str(e)}"


def load_plugin():
    get_workbench().add_assistant("Gemini", GeminiAssistant())
    # Debug mode is the same assistant, just routes to _complete_debug_step
    get_workbench().add_assistant("DebugGemini", GeminiAssistant())
