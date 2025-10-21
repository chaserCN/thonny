from tkinter import ttk
from typing import Iterator, List, Optional

from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk
from thonny.ui_utils import create_url_label, show_dialog
from thonny.workdlg import WorkDialog

API_KEY_SECRET_KEY = "gemini_api_key"


class GeminiApiKeyDialog(WorkDialog):
    def __init__(self, master):
        self.api_key: Optional[str] = None
        super().__init__(master)

    def init_main_frame(self):
        super().init_main_frame()
        url_label = create_url_label(self.main_frame, url="https://aistudio.google.com/app/apikey")
        url_label.grid(row=1, column=1, columnspan=3)

        key_label = ttk.Label(self.main_frame, text="API key")
        key_label.grid(row=2, column=1)

        self.key_entry = ttk.Entry(self.main_frame, width=50)
        self.key_entry.grid(row=2, column=2)

        paste_button = ttk.Button(self.main_frame, text="Paste", command=self._paste_from_clipboard)
        paste_button.grid(row=2, column=3)

    def _paste_from_clipboard(self):
        self.key_entry.delete("0", "end")
        self.key_entry.insert(0, get_workbench().clipboard_get())

    def get_instructions(self) -> Optional[str]:
        return """Чтобы использовать Gemini AI-ассистента для отладки:

1. Получите бесплатный API ключ на aistudio.google.com/app/apikey
2. Скопируйте ключ
3. Нажмите кнопку 'Paste' ниже или вставьте вручную
4. Нажмите 'OK'

После этого вы сможете задавать вопросы Gemini AI во время отладки!"""

    def is_ready_for_work(self):
        return len(self.key_entry.get().strip()) > 0

    def on_click_ok_button(self):
        self.api_key = self.key_entry.get().strip() or None
        if self.api_key is not None:
            self.close()


class GeminiAssistant(Assistant):

    def _get_saved_api_key(self) -> Optional[str]:
        return get_workbench().get_secret(API_KEY_SECRET_KEY, None)

    def _request_new_api_key(self):
        dlg = GeminiApiKeyDialog(get_workbench())
        show_dialog(dlg, get_workbench())
        get_workbench().set_secret(API_KEY_SECRET_KEY, dlg.api_key)

    def get_ready(self) -> bool:
        if self._get_saved_api_key() is None:
            self._request_new_api_key()

        return self._get_saved_api_key() is not None

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        import google.generativeai as genai

        genai.configure(api_key=self._get_saved_api_key())
        
        # Use gemini-1.5-flash for fast responses
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Build chat history (system message + previous messages)
        history = []
        
        # Add system message as first user message (Gemini doesn't have system role)
        if context.messages:
            # Convert messages to Gemini format
            for msg in context.messages[:-1]:  # All except the last one
                role = "user" if msg.role == "user" else "model"
                history.append({
                    "role": role,
                    "parts": [self.format_message(msg)]
                })
        
        # Start chat with history
        chat = model.start_chat(history=history)
        
        # Get the last user message
        last_message = context.messages[-1] if context.messages else None
        if not last_message:
            yield ChatResponseChunk("", is_final=True)
            return
        
        prompt = self.format_message(last_message)
        
        # Stream response
        response = chat.send_message(prompt, stream=True)
        
        for chunk in response:
            if chunk.text:
                yield ChatResponseChunk(chunk.text, is_final=False)
        
        yield ChatResponseChunk("", is_final=True)

    def cancel_completion(self) -> None:
        pass


def load_plugin():
    get_workbench().add_assistant("Gemini", GeminiAssistant())

