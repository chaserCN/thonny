import tkinter as tk
from tkinter import ttk
from typing import Iterator, List, Optional

from thonny import get_workbench
from thonny.assistance import ChatContext, ChatMessage, ChatResponseChunk
from thonny.plugins.base_assistant import BaseAIAssistant
from thonny.ui_utils import create_url_label


API_KEY_SECRET_KEY = "Claude.api_key"


class ClaudeApiKeyDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Claude API Key")
        self.transient(master)
        self.grab_set()

        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        intro_label = ttk.Label(
            main_frame,
            text="This assistant requires a Claude API key.\nYou can get it from:",
        )
        intro_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        url_label = create_url_label(main_frame, "https://console.anthropic.com/settings/keys")
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


class ClaudeAssistant(BaseAIAssistant):
    """Claude (Anthropic) assistant implementation"""
    
    def _get_saved_api_key(self) -> Optional[str]:
        return get_workbench().get_secret(API_KEY_SECRET_KEY)

    def _request_new_api_key(self) -> None:
        from logging import getLogger
        logger = getLogger(__name__)
        
        dlg = ClaudeApiKeyDialog(get_workbench())
        dlg.wait_window()  # Wait for dialog to close
        
        if dlg.api_key:
            logger.info(f"Saving Claude API key (length: {len(dlg.api_key)})")
            get_workbench().set_secret(API_KEY_SECRET_KEY, dlg.api_key)
            logger.info(f"Claude API key saved to: {get_workbench()._get_secrets_path()}")
        else:
            logger.info("Claude API key dialog cancelled or empty")
    
    def _get_summary_role(self) -> str:
        """Claude doesn't have a special summary role, use 'user'"""
        return "user"
    
    def _prepare_messages(self, messages: List[ChatMessage]) -> List[dict]:
        """Convert ChatMessage list to Claude API format with image support"""
        out_msgs = []
        
        for msg in messages:
            formatted_content = self.format_message(msg)
            
            # If message has an image, use multimodal format
            if msg.image:
                content = []
                
                # Add image in Claude format
                image_format = msg.image.get('format', 'jpeg')
                media_type = f"image/{image_format}"
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": msg.image['base64']
                    }
                })
                
                # Add text
                content.append({
                    "type": "text",
                    "text": formatted_content
                })
                
                out_msgs.append({"role": msg.role.to_gemini(), "content": content})
            else:
                # Regular text message
                out_msgs.append({"role": msg.role.to_gemini(), "content": formatted_content})
        
        return out_msgs
    
    def _send_to_api(self, system_prompt: str, messages: List[dict]) -> Iterator[ChatResponseChunk]:
        """Send request to Claude API and stream response"""
        import anthropic

        client = anthropic.Anthropic(api_key=self._get_saved_api_key())

        # Claude uses separate system parameter (not in messages)
        # Note: messages should NOT include system messages
        response = client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=8192,
            system=system_prompt,
            messages=messages,
        )

        with response as stream:
            for text in stream.text_stream:
                yield ChatResponseChunk(text, is_final=False)

        yield ChatResponseChunk("", is_final=True)


def load_plugin():
    get_workbench().add_assistant("Claude", ClaudeAssistant())
    # Debug mode is the same assistant, just routes to _complete_debug_step
    get_workbench().add_assistant("DebugClaude", ClaudeAssistant())

