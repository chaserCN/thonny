import datetime
import os.path
import re
import threading
import tkinter as tk
from tkinter import ttk
import uuid
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from thonny import get_runner, get_shell, get_workbench, rst_utils, tktextext, ui_utils
from thonny.markdown_utils import (
    COLOR_BOT_MESSAGE_BG,
    COLOR_USER_MESSAGE_BG,
    COLOR_USER_MESSAGE_FG,
    COLOR_SELECT_BG,
    COLOR_SELECT_FG,
    COLOR_AVATAR,
    COLOR_TYPING_INDICATOR,
    MessageType,
    render_markdown,
)
from thonny.assistance import (
    Assistant,
    Attachment,
    ChatContext,
    ChatMessage,
    ChatResponseChunk,
    ChatResponseFragmentWithRequestId,
    ChatRole,
    EchoAssistant,
    format_file_url,
    logger,
)
from thonny.common import STRING_PSEUDO_FILENAME, ToplevelResponse
from thonny.languages import tr
from thonny.tktextext import EnhancedText, TweakableText
from thonny.ui_utils import (
    CustomToolbutton,
    LongTextDialog,
    create_custom_toolbutton_in_frame,
    ems_to_pixels,
    get_beam_cursor,
    get_hyperlink_cursor,
    lookup_style_option,
    shift_is_pressed,
    show_dialog,
    update_text_height,
)


class ChatView(tktextext.TextFrame):
    def __init__(self, master):
        tktextext.TextFrame.__init__(
            self,
            master,
            text_class=rst_utils.RstText,  # Use RstText for beautiful formatting!
            horizontal_scrollbar_class=ui_utils.AutoScrollbar,
            read_only=True,
            wrap="word",
            font="TkDefaultFont",
            # cursor="arrow",
            padx=0,
            pady=0,
            insertwidth=0,
            background="white",
            selectbackground=COLOR_SELECT_BG,  # Blue selection background
            selectforeground=COLOR_SELECT_FG,     # White selection text
            inactiveselectbackground=COLOR_SELECT_BG,  # Blue even during dragging
            suppress_events=True,
        )
        
        # Explicitly set selection colors (in case RstText overrides them)
        self.text.config(
            selectbackground=COLOR_SELECT_BG, 
            selectforeground=COLOR_SELECT_FG,
            inactiveselectbackground=COLOR_SELECT_BG
        )

        self._analyzer_instances = []

        self._chat_messages: List[ChatMessage] = []  # Full history for UI display
        self._ai_messages: List[ChatMessage] = []  # Compressed history for AI API (without debug after session ends)
        self._formatted_attachmets_per_message: Dict[str, str] = {}
        self._last_tagged_attachments: Dict[str, Attachment] = {}
        self._active_chat_request_id: Optional[str] = None
        self._current_pending_message: Optional[ChatMessage] = None  # User message pending AI response

        self._snapshots_per_main_file = {}
        self._current_snapshot = None
        self._current_suggestions: List[str] = []

        self._accepted_warning_sets = []
        self._last_auto_explained_step = None  # Track last auto-explained step to avoid duplicates
        self._current_debug_session_id: Optional[str] = None  # Current debug session ID
        self._loading_animation_step = 0  # For loading indicator animation
        self._attached_image: Optional[dict] = None  # Store selected image (path and base64)
        self._bot_avatar_added = False  # Track if bot avatar was added for current response
        self._typing_animation_id = None  # For typing indicator animation
        self._typing_animation_step = 0  # Current animation frame
        self._captured_program_context: Optional[str] = None  # Pre-captured debug context to avoid race conditions

        main_font = tk.font.nametofont("TkDefaultFont")

        italic_font = main_font.copy()
        italic_font.configure(slant="italic", size=main_font.cget("size"))

        # Underline on font looks better than underline on tag
        underline_font = main_font.copy()
        underline_font.configure(size=main_font.cget("size"), underline=True)

        italic_underline_font = main_font.copy()
        italic_underline_font.configure(slant="italic", size=main_font.cget("size"), underline=True)

        self.text.tag_configure(
            "section_title",
            spacing3=5,
            font="BoldTkDefaultFont",
        )
        self.text.tag_configure(
            "intro",
            # font="ItalicTkDefaultFont",
            spacing3=10,
        )
        self.text.tag_configure("relevant_suggestion_title", font="BoldTkDefaultFont")
        self.text.tag_configure("suggestion_title", lmargin2=16, spacing1=5, spacing3=5)
        self.text.tag_configure("suggestion_body", lmargin1=16, lmargin2=16)
        self.text.tag_configure("body", font="ItalicTkDefaultFont")

        self.text.tag_configure("suggestions_block", justify="right")

        self._last_analysis_start_index = "1.0"
        self._last_analysis_end_index = "1.0"

        # Common margin for both user and bot messages
        message_margin = ems_to_pixels(0.5)  # Одинаковый отступ слева для всех сообщений
        
        self.text.tag_configure(
            "bubble_message",
            lmargin1=12,   # Левый отступ (+50%)
            lmargin2=12,   # Левый отступ для остальных строк (+50%)
            rmargin=12,    # Правый отступ (+50%)
            # spacing handled manually to avoid gaps between lines
        )
        
        # Vertical padding tag (spacing at top/bottom of bubble)
        self.text.tag_configure(
            "bubble_padding",
            font=("TkDefaultFont", 1),  # Tiny font
            lmargin1=12,
            lmargin2=12,
            rmargin=12,
            spacing1=6,  # Half of desired padding (top)
            spacing3=6,  # Half of desired padding (bottom)
        )
        
        # Avatar styles
        self.text.tag_configure(
            "bubble_avatar",
            foreground=COLOR_AVATAR,  # Blue for user and bot
        )
        self.text.tag_configure(
            "typing_indicator",
            foreground=COLOR_TYPING_INDICATOR,  # Gray for typing indicator
            background=COLOR_BOT_MESSAGE_BG,  # Same as bot message background
        )
        
        # Configure bubble_padding tag
        self.text.tag_configure(
            "bubble_padding",
            font=("TkDefaultFont", 1),  # Small font for padding lines
            lmargin1=12,
            lmargin2=12,
            spacing1=6,  # Spacing above
            spacing3=6,  # Spacing below
        )

        # self.text.tag_configure("user_message_first_line", spacing1=ems_to_pixels(0.3))
        # self.text.tag_configure("user_message_last_line", spacing1=ems_to_pixels(0.3))

        self.text.bind("<Motion>", self._on_mouse_move_in_text, True)
        
        # Enable copy shortcuts even in read-only mode
        self.text.bind("<Control-c>", lambda e: self.text.event_generate("<<Copy>>"))
        self.text.bind("<Command-c>", lambda e: self.text.event_generate("<<Copy>>"))  # Mac
        self.text.bind("<Control-a>", lambda e: self.text.tag_add("sel", "1.0", "end"))
        self.text.bind("<Command-a>", lambda e: self.text.tag_add("sel", "1.0", "end"))  # Mac
        
        self.text.tag_configure("feedback_link", justify="right", font=italic_underline_font)
        self.text.tag_configure("python_errors_link", justify="right", font=italic_underline_font)
        self.text.tag_bind(
            "python_errors_link",
            "<ButtonRelease-1>",
            lambda e: get_workbench().open_url("errors.rst"),
            True,
        )

        self.text.tag_bind(
            "attachments_link",
            "<ButtonRelease-1>",
            self._on_click_attachments_link,
            True,
        )

        self.query_box = self.create_query_panel()
        self.query_box.grid(row=1, column=1, columnspan=2, sticky="nsew")

        from thonny.plugins.openai import OpenAIAssistant

        # Try to use DebugAI or DebugGemini based on saved preference, fallback to Echo
        try:
            saved_model = get_workbench().get_option("ai.model", "gpt")
        except Exception:
            saved_model = "gpt"
        
        # Use regular assistants by default (not debug versions)
        if saved_model == "gemini":
            self._current_assistant: Assistant = get_workbench().assistants.get("gemini", EchoAssistant())  # lowercase!
        elif saved_model == "claude":
            self._current_assistant: Assistant = get_workbench().assistants.get("claude", EchoAssistant())  # lowercase!
        else:
            self._current_assistant: Assistant = get_workbench().assistants.get("openai", EchoAssistant())  # lowercase!

        get_workbench().bind("ToplevelResponse", self.handle_toplevel_response, True)
        get_workbench().bind(
            "AiChatResponseFragment", self.handle_assistant_chat_response_fragment, True
        )
        get_workbench().bind("DebuggerResponse", self._handle_debugger_step, True)

        self.bind("<<ThemeChanged>>", self._on_theme_changed, True)
        self.bind("<Configure>", self._on_configure, True)
        get_workbench().bind("WorkbenchReady", self._workspace_ready, True)

    def create_query_panel(self) -> tk.Frame:

        background = lookup_style_option(".", "background")
        bordercolor = "#aaaaaa"  # TODO

        panel = tk.Frame(self, background=background)
        panel.rowconfigure(1, weight=0)  # top buttons row (attach, lang, model, clear)
        panel.rowconfigure(2, weight=1)  # input row
        panel.rowconfigure(3, weight=0)  # image preview row
        panel.columnconfigure(1, weight=0)  # attach button (fixed)
        panel.columnconfigure(2, weight=1)  # spacer (expanding)
        panel.columnconfigure(3, weight=0)  # lang, model, clear (fixed)

        pad = ems_to_pixels(1)
        pad_small = ems_to_pixels(0.67)  # ~8 pixels for smaller horizontal padding

        # Image attach button (top left)
        image_button_frame = create_custom_toolbutton_in_frame(
            panel,
            image=get_workbench().get_image("chat-attach-glyph.png", for_toolbar=True),
            command=self._attach_image,
            background=background,
            borderwidth=0,
            bordercolor=bordercolor,
        )
        image_button_frame.grid(row=1, column=1, sticky="w", padx=(pad_small, 0), pady=(pad//3, 0))
        
        # Explain Shell button (next to image button)
        explain_shell_button_frame = create_custom_toolbutton_in_frame(
            panel,
            image=get_workbench().get_image("bot_explain.png", for_toolbar=True),
            command=self._explain_shell_output,
            background=background,
            borderwidth=0,
            bordercolor=bordercolor,
        )
        explain_shell_button_frame.grid(row=1, column=2, sticky="w", padx=(pad_small//2, 0), pady=(pad//3, 0))
        
        # Add tooltip
        try:
            lang = get_workbench().get_option("general.language", "uk")
        except Exception:
            lang = "uk"
        tooltip_text = "Пояснити вивід Shell" if lang == "uk" else "Объяснить вывод Shell"
        ui_utils.create_tooltip(explain_shell_button_frame, tooltip_text)

        # Right frame for language, model and clear buttons
        right_buttons_frame = tk.Frame(panel, background=background)
        right_buttons_frame.grid(row=1, column=3, sticky="e", padx=(0, pad_small), pady=(pad//3, 0))

        # Language selection dropdown (УК/РУ)
        def _current_lang() -> str:
            try:
                return get_workbench().get_option("ai.language", "uk")
            except Exception:
                return "uk"

        def _lang_label_from(code: str) -> str:
            return "УК" if code == "uk" else "РУ"

        # Language dropdown (УК/РУ)
        self.lang_var = tk.StringVar(value=_lang_label_from(_current_lang()))
        self.lang_combobox = ttk.Combobox(
            right_buttons_frame,
            textvariable=self.lang_var,
            values=["УК", "РУ"],
            state="readonly",
            width=4,
        )
        self.lang_combobox.pack(side="left", padx=(0, 5))
        self.lang_combobox.bind("<<ComboboxSelected>>", lambda e: self._on_lang_selected())
        
        # Model selection dropdown (GPT/Gemini/Claude) next to language button
        def _current_model() -> str:
            try:
                return get_workbench().get_option("ai.model", "gemini")
            except Exception:
                return "gemini"
        
        def _model_label_from(model: str) -> str:
            return {"gpt": "GPT", "gemini": "Gemini", "claude": "Claude"}.get(model, "GPT")
        
        self.model_var = tk.StringVar(value=_model_label_from(_current_model()))
        self.model_combobox = ttk.Combobox(
            right_buttons_frame,
            textvariable=self.model_var,
            values=["Gemini", "Claude", "GPT"],
            state="readonly",
            width=8,
        )
        self.model_combobox.pack(side="left", padx=(0, 5))
        self.model_combobox.bind("<<ComboboxSelected>>", lambda e: self._on_model_selected())
        
        # Clear chat button (in right frame)
        clear_button = CustomToolbutton(
            right_buttons_frame,
            image=get_workbench().get_image("chat-clear-glyph.png", for_toolbar=True),
            command=self._clear_chat,
            background=background,
        )
        clear_button.pack(side="left", padx=(5, 0))

        # Input field (full width)
        # White background container
        # sticky="sew" makes it grow upward (bottom-anchored like Cursor)
        white_container = tk.Frame(panel, background="white")
        white_container.grid(row=2, column=1, columnspan=3, sticky="sew", padx=(pad_small, pad_small), pady=(pad//4, pad_small))
        white_container.rowconfigure(0, weight=1)
        white_container.columnconfigure(0, weight=1)
        
        # Simple Text widget with FIXED height (no auto-resize to prevent flickering)
        self.query_text = tk.Text(
            white_container,
            height=7,  # FIXED height - never changes to prevent flickering
            font=("TkDefaultFont", 10),
            borderwidth=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            insertwidth=2,  # Ширина курсора
            insertbackground="black",  # Цвет курсора
            padx=4,
            pady=4,
        )
        self.query_text.bind("<Return>", self._on_press_enter_in_chat_entry, True)
        # NO auto-resize - fixed height to prevent flickering
        
        # Bind paste event (works on ALL keyboard layouts, including Russian/Ukrainian)
        self.query_text.bind("<<Paste>>", self._on_paste_in_query, True)
        
        # Explicitly bind copy/cut for all layouts (Cmd+C/V/X on Mac, Ctrl+C/V/X on other OS)
        self.query_text.bind("<<Copy>>", lambda e: None, True)  # Allow default copy
        self.query_text.bind("<<Cut>>", lambda e: None, True)   # Allow default cut

        # sticky="sew" (south-east-west) makes it grow UPWARD like Cursor
        # Bottom edge stays in place, top edge expands
        self.query_text.grid(row=0, column=0, sticky="sew")

        # Set focus to input field on startup
        self.query_text.focus_set()
        
        # Image preview frame (below input, hidden by default)
        self.image_preview_frame = tk.Frame(panel, background=background)
        self.image_preview_frame.grid(row=3, column=1, columnspan=3, sticky="ew", padx=pad_small, pady=0)
        self.image_preview_frame.grid_remove()  # Hide by default

        return panel

    def handle_assistant_chat_response_fragment(
        self, fragment_with_request_id: ChatResponseFragmentWithRequestId
    ) -> None:
        if fragment_with_request_id.request_id != self._active_chat_request_id:
            logger.info("Skipping chat fragment, because request has been cancelled")
            return

        fragment = fragment_with_request_id.fragment
        
        # We always receive one final fragment (no streaming)
        if isinstance(self.text, rst_utils.RstText):
            # Stop animation and remove entire typing indicator line
            self._stop_typing_animation()
            if hasattr(self, '_typing_line_start'):
                try:
                    # Delete entire typing line (avatar + dots + newline)
                    self.text.direct_delete(self._typing_line_start, "end-1c")
                except:
                    pass
            
            # Parse fix suggestions from markdown
            clean_content, fixes = self._parse_fix_suggestions(fragment.content)
                
            # Insert complete bot message using universal method
            self._insert_message_bubble(
                avatar="🤖",
                content=clean_content,
                message_tag="bubble_message",
                bg_color=COLOR_BOT_MESSAGE_BG,  # Very light greige background
                message_type=MessageType.BOT,
                image_data=None,
                is_markdown=True
            )
            
            # If there are fix suggestions, show popup in editor after a short delay
            if fixes:
                # Take only first fix (as instructed in prompt)
                fix = fixes[0]
                self.after(500, lambda: self._show_fix_popup_in_editor(fix))
            
            self._bot_avatar_added = False
        else:
            # For regular text
            self._append_text(fragment.content, source="chat")
        
        # Add pending user message and bot response to histories
        if self._current_pending_message:
            # Add user message to both histories
            self._chat_messages.append(self._current_pending_message)
            self._ai_messages.append(self._current_pending_message)
            
            # Create bot message
            bot_msg = ChatMessage(
                ChatRole.ASSISTANT, 
                fragment.content,
                [], 
                self._current_pending_message.is_debug_related, 
                self._current_pending_message.debug_session_id
            )
            
            # Add bot message to both histories
            self._chat_messages.append(bot_msg)
            self._ai_messages.append(bot_msg)
            
            # Clear pending message
            self._current_pending_message = None
        
        # Finalize
            self._active_chat_request_id = None
            self._update_suggestions()
            self.text.see("end")
            
            # Remove image from history after AI has processed it
            for i in range(len(self._chat_messages) - 1, -1, -1):
                msg = self._chat_messages[i]
                if msg.role == ChatRole.USER and msg.image is not None:
                    # Replace message with version without image
                    self._chat_messages[i] = replace(msg, image=None)
                    logger.info(f"Removed image from message in history to save tokens")
                    break
            
            # Return focus to input field
            self.query_text.focus_set()

    def _on_lang_selected(self) -> None:
        """Handle language selection change (УК/РУ)"""
        # Map display name to internal value
        display_to_code = {"УК": "uk", "РУ": "ru"}
        selected = self.lang_var.get()
        new_lang = display_to_code.get(selected, "uk")
        
        try:
            get_workbench().set_option("ai.language", new_lang)
        except Exception:
            pass
        
        self._update_suggestions()
    
    def _on_model_selected(self) -> None:
        """Handle model selection change (GPT/Gemini/Claude), preserving chat history"""
        # Map display name to internal value
        label_to_model = {"GPT": "gpt", "Gemini": "gemini", "Claude": "claude"}
        selected_label = self.model_var.get()
        new_model = label_to_model.get(selected_label, "gpt")
        
        try:
            get_workbench().set_option("ai.model", new_model)
        except Exception:
            pass
        
        # Switch assistant while preserving history (case-insensitive keys)
        # Switch to regular assistants (not debug versions)
        assistants = get_workbench().assistants
        
        if new_model == "gpt":
            self._current_assistant = (
                assistants.get("openai")  # lowercase!
                or EchoAssistant()
            )
        elif new_model == "gemini":
            self._current_assistant = (
                assistants.get("gemini")  # lowercase!
                or EchoAssistant()
            )
        elif new_model == "claude":
            self._current_assistant = (
                assistants.get("claude")  # lowercase!
                or EchoAssistant()
            )
        
        # History is preserved in self._chat_messages - no need to clear it
    
    def _clear_chat(self) -> None:
        """Clear chat display and message history"""
        # Clear the displayed chat text
        self.text.direct_delete("1.0", "end")
        
        # Clear both histories
        self._chat_messages.clear()  # UI history
        self._ai_messages.clear()  # AI history
        self._current_pending_message = None
        
        # Clear debug session
        self._current_debug_session_id = None
        
        # Clear other state
        self._formatted_attachmets_per_message.clear()
        self._last_tagged_attachments.clear()
        self._last_auto_explained_step = None
        self._clear_attached_image()  # Clear image and hide preview
        self._bot_avatar_added = False
        
        # Stop typing animation
        self._stop_typing_animation()
        
        # Cancel any ongoing completion
        self._cancel_completion()

    def handle_toplevel_response(self, msg: ToplevelResponse) -> None:
        from thonny.plugins.cpython_frontend import LocalCPythonProxy

        if not isinstance(get_runner().get_backend_proxy(), LocalCPythonProxy):
            # TODO: add some support for MicroPython as well
            return

        # Can be called by event system or by Workbench
        # (if Assistant wasn't created yet but an error came)
        if not msg.get("user_exception") and msg.get("command_name") in [
            "execute_system_command",
            "execute_source",
        ]:
            # Shell commands may be used to investigate the problem, don't clear assistance
            return

        self._prepare_new_analysis()

        # prepare for snapshot
        # TODO: should distinguish between <string> and <stdin> ?
        key = msg.get("filename", STRING_PSEUDO_FILENAME)
        self._current_snapshot = {
            "timestamp": datetime.datetime.now().isoformat()[:19],
            "main_file_path": key,
        }
        self._snapshots_per_main_file.setdefault(key, [])
        self._snapshots_per_main_file[key].append(self._current_snapshot)

        if msg.get("filename") and os.path.exists(msg["filename"]):
            self.main_file_path = msg["filename"]
        else:
            self.main_file_path = None

    def _handle_debugger_step(self, msg) -> None:
        """Автоматически объясняет каждый шаг отладки"""
        from thonny.plugins.debugger import get_current_debugger
        
        debugger = get_current_debugger()
        if not debugger:
            # Debug session ended - remove debug messages from AI history (keep in UI history for display)
            if self._current_debug_session_id is not None:
                logger.info(f"Debug session {self._current_debug_session_id} ended, cleaning up AI history")
                # Remove debug messages from AI history only
                self._ai_messages = [
                    msg for msg in self._ai_messages
                    if not msg.is_debug_related
                ]
                # Keep debug messages in UI history (self._chat_messages) for display
                self._current_debug_session_id = None
            return
        
        # Start new debug session if needed
        if self._current_debug_session_id is None:
            self._current_debug_session_id = str(uuid.uuid4())
        
        # Проверяем что была команда step_over или step_into (или ручной explain)
        manual_explain = bool(getattr(debugger, '_manual_explain', False))
        if not manual_explain:
            last_cmd = getattr(debugger, '_last_debugger_command', None)
            if not last_cmd or last_cmd.name not in ['step_over', 'step_into']:
                return
        
        # Определяем, какую модель использовать (GPT/Gemini/Claude)
        # и получаем соответствующий Debug assistant для авто-объяснений
        try:
            current_model = get_workbench().get_option("ai.model", "gpt")
        except Exception:
            current_model = "gpt"
        
        assistants = get_workbench().assistants
        
        debug_assistant = None
        if current_model == "gpt":
            debug_assistant = assistants.get("debugai")  # lowercase!
        elif current_model == "gemini":
            debug_assistant = assistants.get("debuggemini")  # lowercase!
        elif current_model == "claude":
            debug_assistant = assistants.get("debugclaude")  # lowercase!
        
        if not debug_assistant:
            logger.warning(f"Debug assistant not found for model {current_model}")
            return
        
        # Избегаем повторной генерации для того же шага (но не для ручного explain)
        # Используем информацию о текущей строке кода
        if not manual_explain:
            if hasattr(msg, 'stack') and msg.stack:
                current_frame = msg.stack[-1]
                step_id = (current_frame.filename, current_frame.lineno, current_frame.event)
                
                if step_id == self._last_auto_explained_step:
                    return
                
                self._last_auto_explained_step = step_id
        
        # Проверяем одноразовый флаг "объяснить следующий шаг"
        explain_next = bool(getattr(debugger, '_explain_next_step', False))
        if not explain_next:
            return
        # Сбрасываем флаг, чтобы объяснение было одноразовым
        try:
            setattr(debugger, '_explain_next_step', False)
        except Exception:
            pass

        # Проверяем готовность debug ассистента (API ключ и т.д.)
        if not debug_assistant.get_ready():
            return
        
        # Автоматично генеруємо пояснення (локалізовано)
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"
        
        # Получаем номер текущей строки для более точного промпта
        current_line = None
        if hasattr(msg, 'stack') and msg.stack:
            current_frame = msg.stack[-1]
            current_line = current_frame.lineno
        
        # IMPORTANT: Захватываем debug контекст СЕЙЧАС, а не позже в thread!
        # Иначе если пользователь быстро нажмет step снова, контекст будет неправильный
        from thonny.plugins.debug_common import get_debug_context_from_msg
        debug_ctx = get_debug_context_from_msg(msg)
        
        # Короткое сообщение для отображения в UI (что видит ребенок)
        if manual_explain:
            # For manual explain, don't show [auto] prefix
            if lang == "ru":
                if current_line:
                    display_prompt = f"Что выполнится на строке {current_line}?"
                else:
                    display_prompt = "Что дальше?"
            else:
                if current_line:
                    display_prompt = f"Що виконається на рядку {current_line}?"
                else:
                    display_prompt = "Що далі?"
        else:
            # For auto explain after step, show [auto] prefix
            if lang == "ru":
                if current_line:
                    display_prompt = f"[auto] Что выполнится на строке {current_line}?"
                else:
                    display_prompt = "[auto] Что дальше?"
            else:
                if current_line:
                    display_prompt = f"[auto] Що виконається на рядку {current_line}?"
                else:
                    display_prompt = "[auto] Що далі?"
        
        # Полный промпт для AI с инструкциями и контекстом
        if manual_explain:
            # For manual explain, ask about current state only
            if lang == "ru":
                if current_line:
                    full_prompt = f"Поясни что выполнится на строке {current_line}"
                else:
                    full_prompt = "Поясни что выполнится дальше"
            else:
                if current_line:
                    full_prompt = f"Поясни що виконається на рядку {current_line}"
                else:
                    full_prompt = "Поясни що виконається далі"
        else:
            # For auto explain after step, mention what happened
            if lang == "ru":
                if current_line:
                    full_prompt = f"Поясни что произошло на последнем шаге и что выполнится на строке {current_line}"
                else:
                    full_prompt = "Поясни что произошло на последнем шаге и что выполнится дальше"
            else:
                if current_line:
                    full_prompt = f"Поясни що сталося на останньому кроці та що виконається на рядку {current_line}"
                else:
                    full_prompt = "Поясни що сталося на останньому кроці та що виконається далі"
        
        # Debug контекст НЕ добавляем к промпту здесь,
        # потому что он уже будет добавлен в _complete_debug_step через context.program_context
        
        # Временно подменяем assistant на debug версию для этого запроса
        original_assistant = self._current_assistant
        self._current_assistant = debug_assistant
        
        try:
            # Отправляем: полный промпт для AI, короткий для отображения
            # Передаём захваченный контекст, чтобы избежать race condition
            # (если пользователь быстро нажмёт step снова, состояние не изменится)
            self.submit_user_chat_message(
                full_prompt, 
                is_debug_related=True, 
                debug_session_id=self._current_debug_session_id,
                display_message=display_prompt,
                captured_program_context=debug_ctx
            )
        finally:
            # Восстанавливаем оригинальный assistant
            self._current_assistant = original_assistant

    def _on_configure(self, event: tk.Event) -> None:
        self._update_suggestions_box()

    def _workspace_ready(self, event: tk.Event) -> None:
        self._update_suggestions()

    def _explain_exception(self, error_info):
        rst = (
            self._get_rst_prelude()
            + rst_utils.create_title(
                error_info["type_name"] + ": " + rst_utils.escape(error_info["message"])
            )
            + "\n"
        )

        if (
            error_info.get("lineno") is not None
            and error_info.get("filename")
            and os.path.exists(error_info["filename"])
        ):
            rst += "`%s, line %d <%s>`__\n\n" % (
                os.path.basename(error_info["filename"]),
                error_info["lineno"],
                self._format_file_url(error_info),
            )
    
    def _append_text(self, chars, tags=(), source="analysis"):
        # Just insert text directly (RST handled separately in streaming handler)
        self.text.direct_insert("end", chars, tags=tags)

        if source == "analysis":
            self._last_analysis_end_index = self.text.index("end")

        self.text.see("end")

    def _prepare_new_analysis(self):
        self._cancel_analysis()
        self._cancel_completion()

        # Don't delete chat history on program run - preserve conversation
        # text_after_last_analysis = self.text.get(self._last_analysis_end_index, "end")
        # if not text_after_last_analysis.strip():
        #     # No question was asked after the last analysis, let's forget that analysis.
        #     self.text.direct_delete(self._last_analysis_start_index, "end-1c")

        self._last_analysis_start_index = self.text.index("end-1c")
        self._last_analysis_end_index = self.text.index("end-1c")

    def _prepare_new_completion(self):
        self._cancel_analysis()
        self._cancel_completion()
        # Reset bot avatar flag for new request
        self._bot_avatar_added = False

    def _cancel_analysis(self):
        if self._analysis_in_progress():
            self._accepted_warning_sets.clear()
            for wp in self._analyzer_instances:
                wp.cancel_analysis()
            self._analyzer_instances = []

    def _start_typing_animation(self):
        """Start animated typing indicator (·, ··, ···)"""
        self._typing_animation_step = 0
        self._update_typing_animation()
    
    def _stop_typing_animation(self):
        """Stop typing indicator animation"""
        if self._typing_animation_id is not None:
            try:
                self.after_cancel(self._typing_animation_id)
            except:
                pass
            self._typing_animation_id = None
    
    def _update_typing_animation(self):
        """Update typing indicator animation frame"""
        if not hasattr(self, '_typing_indicator_start') or not self._bot_avatar_added:
            return
        
        try:
            # Cycle through ·, ··, ···
            dots = ["·", "··", "···"]
            current_dots = dots[self._typing_animation_step % 3]
            
            # Delete ALL existing dots (find end by checking for "·" character)
            typing_end = self._typing_indicator_start
            for i in range(5):  # Max 5 iterations to prevent infinite loop
                next_char = self.text.get(typing_end, f"{typing_end}+1c")
                if next_char == "·":
                    typing_end = self.text.index(f"{typing_end}+1c")
                else:
                    break
            
            # Update only the dots, keep padding intact
            self.text.direct_delete(self._typing_indicator_start, typing_end)
            self.text.direct_insert(self._typing_indicator_start, current_dots, ("typing_indicator", "bubble_message"))
            
            # Next frame
            self._typing_animation_step += 1
            
            # Schedule next update (500ms)
            self._typing_animation_id = self.after(500, self._update_typing_animation)
        except:
            # If something fails, stop animation
            self._stop_typing_animation()

    def _cancel_completion(self):
        if self._current_assistant is None:
            return

        if self._chat_completion_in_progress():
            self._active_chat_request_id = None
            self._current_pending_message = None  # Clear pending message
            # self._hide_loading_indicator()  # Removed submit button
            self._stop_typing_animation()  # Stop animation on cancel
            
            # Remove bot avatar and typing indicator if they were added
            if self._bot_avatar_added and hasattr(self, '_typing_indicator_start'):
                try:
                    # Find where the bot avatar starts (before typing indicator)
                    # Avatar is "🤖 " (bot emoji + space), typing indicator starts after it
                    avatar_start = self.text.index(f"{self._typing_indicator_start}-3c")
                    self.text.direct_delete(avatar_start, "end-1c")
                except Exception:
                    pass
            
            #self._append_text("... [cancelled]", source="chat")
            self._bot_avatar_added = False  # Reset avatar flag

            self._current_assistant.cancel_completion()

    def _analysis_in_progress(self) -> bool:
        return len(self._analyzer_instances) > 0

    def _chat_completion_in_progress(self) -> bool:
        return self._active_chat_request_id is not None

    def _format_file_url(self, atts):
        return format_file_url(atts["filename"], atts.get("lineno"), atts.get("col_offset"))

    def _get_rst_prelude(self):
        return ".. default-role:: code\n\n" + ".. role:: light\n\n" + ".. role:: remark\n\n"

    def _on_theme_changed(self, event):
        self.text.configure(
            background=lookup_style_option("Text", "background"),
            foreground=lookup_style_option("Text", "foreground"),
        )

        if isinstance(self.text, rst_utils.RstText):
            self.text.on_theme_changed()

    def _explain_shell_output(self) -> None:
        """Get Shell output and explain it"""
        try:
            shell_view = get_workbench().get_view("ShellView")
            if shell_view:
                shell_view.explain_shell_output()
        except Exception as e:
            logger.exception("Failed to explain shell output", exc_info=e)
    
    def _attach_image(self) -> None:
        """Open file dialog to select an image"""
        from tkinter import filedialog
        
        filetypes = [
            ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
            ("All files", "*.*")
        ]
        
        filepath = filedialog.askopenfilename(
            title="Select an image",
            filetypes=filetypes
        )
        
        if filepath:
            self._load_image_from_file(filepath)
    
    def _on_paste_in_query(self, event) -> str:
        """Handle Ctrl+V / Cmd+V in query text - try to paste image from clipboard"""
        try:
            # Try to get image from clipboard
            from PIL import ImageGrab
            import io
            import base64
            
            image = ImageGrab.grabclipboard()
            
            if image is not None:
                # Image found in clipboard
                # Convert to PNG format in memory
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
                buffer.seek(0)
                
                # Encode to base64
                image_data = base64.b64encode(buffer.read()).decode('utf-8')
                
                self._attached_image = {
                    'path': 'clipboard.png',
                    'base64': image_data,
                    'format': 'png'
                }
                
                self._show_image_preview()
                
                # Prevent default paste behavior
                return "break"
        except Exception as e:
            logger.debug(f"Failed to paste image from clipboard: {e}")
        
        # If no image in clipboard or error, allow default text paste
        return None
    
    def _load_image_from_file(self, filepath: str) -> None:
        """Load image from file and show preview"""
        try:
            import base64
            import os
            
            # Read and encode image to base64
            with open(filepath, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Determine image format from extension
            ext = os.path.splitext(filepath)[1].lower().lstrip('.')
            if ext == 'jpg':
                ext = 'jpeg'
            
            self._attached_image = {
                'path': filepath,
                'base64': image_data,
                'format': ext
            }
            
            self._show_image_preview()
            
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Failed to load image: {e}")
    
    def _show_image_preview(self) -> None:
        """Show preview of attached image with thumbnail"""
        if not self._attached_image:
            return
        
        import os
        from PIL import Image
        import io
        import base64
        
        # Clear previous preview
        for widget in self.image_preview_frame.winfo_children():
            widget.destroy()
        
        try:
            # Decode base64 image
            image_bytes = base64.b64decode(self._attached_image['base64'])
            image = Image.open(io.BytesIO(image_bytes))
            
            # Create thumbnail (max 80px height)
            thumbnail_height = 80
            aspect_ratio = image.width / image.height
            thumbnail_width = int(thumbnail_height * aspect_ratio)
            image.thumbnail((thumbnail_width, thumbnail_height), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(image)
            
            # Create preview with thumbnail, filename, and close button
            preview_container = tk.Frame(
                self.image_preview_frame,
                background="#f0f0f0",
                relief="solid",
                borderwidth=1
            )
            preview_container.pack(fill="x", padx=5, pady=5)
            
            # Thumbnail
            img_label = tk.Label(preview_container, image=photo, background="#f0f0f0")
            img_label.image = photo  # Keep reference
            img_label.pack(side="left", padx=5, pady=5)
            
            # Close button (small emoji label, top-right)
            close_label = tk.Label(
                preview_container,
                text="❌",
                background="#f0f0f0",
                foreground="#666666",
                font=("TkDefaultFont", 10),
                cursor="hand2",
                padx=3,
                pady=0
            )
            close_label.pack(side="right", anchor="ne", padx=3, pady=3)
            close_label.bind("<Button-1>", lambda e: self._clear_attached_image())
            
            # Hover effects
            def on_enter(e):
                close_label.config(foreground="#333333")
            def on_leave(e):
                close_label.config(foreground="#666666")
            close_label.bind("<Enter>", on_enter)
            close_label.bind("<Leave>", on_leave)
            
            # Show the preview frame
            self.image_preview_frame.grid()
            
        except Exception as e:
            logger.error(f"Failed to show image preview: {e}")
    
    def _clear_attached_image(self) -> None:
        """Clear attached image and hide preview"""
        self._attached_image = None
        
        # Clear preview widgets
        for widget in self.image_preview_frame.winfo_children():
            widget.destroy()
        
        # Hide preview frame
        self.image_preview_frame.grid_remove()
        
        # Return focus to input field
        self.query_text.focus_set()
    
    def _append_image_preview_in_chat(self, image_data: dict) -> None:
        """Insert image thumbnail into chat with proper alignment and background"""
        try:
            from PIL import Image, ImageTk
            import io
            import base64
            
            # Decode base64 image
            image_bytes = base64.b64decode(image_data['base64'])
            image = Image.open(io.BytesIO(image_bytes))
            
            # Create thumbnail (max 150px width/height)
            max_size = 150
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)
            
            # Store reference to prevent garbage collection
            if not hasattr(self.text, '_image_references'):
                self.text._image_references = []
            self.text._image_references.append(photo)
            
            # Get current position and insert image with proper alignment
            # Use direct_insert for RstText, insert for regular Text
            insert_method = getattr(self.text, 'direct_insert', self.text.insert)
            current_pos = self.text.index("end-1c")
            
            # Insert image aligned with text (after avatar)
            # Use invisible space characters to create left margin instead of padx
            # (padx adds margin on both sides, we only want left margin)
            
            # Calculate how many spaces we need for alignment
            # Avatar (👤) + 2 spaces for padding to align with text
            num_spaces = 0  # Avatar width + padding
            spaces = " " * num_spaces
            
            # Insert spaces before image (with user_message tag for background)
            spaces_start = current_pos
            insert_method(current_pos, spaces, "bubble_message")
            
            # Now insert image right after the spaces (without padx)
            image_pos = self.text.index(f"{spaces_start}+{num_spaces}c")
            self.text.image_create(image_pos, image=photo)
            
            # Apply user_message tag to the image for background color
            image_end = self.text.index(f"{image_pos}+1c")
            self.text.tag_add("bubble_message", image_pos, image_end)
            
        except Exception as e:
            logger.error(f"Failed to insert image preview in chat: {e}")
            # Fallback to text indicator
            import os
            image_name = os.path.basename(image_data['path'])
            self._append_text(f"[🖼️ {image_name}]", tags=("bubble_message",))

    
    def _insert_message_bubble(
        self, 
        avatar: str, 
        content: str, 
        message_tag: str,
        bg_color: str,
        message_type: MessageType,
        fg_color: str = None,
        image_data: Optional[dict] = None,
        is_markdown: bool = False
    ) -> None:
        """Universal method to insert a message bubble (user or bot).
        
        Args:
            avatar: Avatar emoji ("👩" for user, "🤖" for bot)
            content: Message text content
            message_tag: Tag name (always "bubble_message" for both user and bot)
            bg_color: Background color for this message
            message_type: Type of message (BOT or USER) for styling
            fg_color: Foreground (text) color for this message (optional, default is black)
            image_data: Optional image attachment
            is_markdown: If True, render content as markdown
        """
        # Create a unique color tag for this message
        import time
        color_tag = f"color_{int(time.time() * 1000000)}"
        tag_config = {
            "background": bg_color,
            "spacing1": 0,  # Don't add spacing, let bubble_message handle it
            "spacing3": 0,
        }
        if fg_color:
            tag_config["foreground"] = fg_color
        self.text.tag_configure(color_tag, **tag_config)
        
        # Mark position before avatar
        bubble_start = self.text.index("end-1c")
        
        # Top padding
        self._append_text("\n", tags=("bubble_padding",))
        
        # Avatar with message tag (same for both user and bot)
        self._append_text(f"{avatar} ", tags=(message_tag,))
        
        # Mark position before markdown content
        content_start = self.text.index("end-1c")
        
        # Render markdown for both user and bot
        try:
            render_markdown(self.text, content, show_copy_button=True, message_type=message_type)
        except Exception as e:
            logger.warning(f"Markdown rendering failed: {e}", exc_info=True)
            self.text.direct_insert("end", content)
        
        # Apply message tag to markdown content
        content_end = self.text.index("end-1c")
        self.text.tag_add(message_tag, content_start, content_end)
        # Raise priority so margins apply
        self.text.tag_raise(message_tag)
        
        # Image preview (if any)
        if image_data:
            self._append_text("\n", tags=(message_tag,))
            self._append_image_preview_in_chat(image_data)
            self._append_text("\n", tags=(message_tag,))
        
        # Bottom padding
        self._append_text("\n", tags=("bubble_padding",))
        
        # Apply colors to entire bubble (from avatar to end of content)
        bubble_end = self.text.index("end-1c")
        self.text.tag_add(color_tag, bubble_start, bubble_end)
        # Lower priority so background is behind text formatting
        self.text.tag_lower(color_tag)
        
        # Raise code block tags to highest priority so their background (#E0E0E0) is visible over message background
        try:
            self.text.tag_raise("code_block_internal_padding")
            self.text.tag_raise("md_code_block")
            self.text.tag_raise("code_keyword")
            self.text.tag_raise("code_string")
            self.text.tag_raise("code_comment")
            self.text.tag_raise("code_number")
            self.text.tag_raise("code_builtin")
        except Exception:
            pass
        
        # Add spacing between messages (after color_tag was applied)
        self._append_text("\n")
        
        # No separator needed - markdown already adds \n at the end
    
    def _insert_user_bubble(self, display_text: str, image_data: Optional[dict]) -> None:
        """Insert a user message with full-width blue background."""
        self._insert_message_bubble(
            avatar="👩🏼",
            content=display_text if display_text else "",
            message_tag="bubble_message",
            bg_color=COLOR_USER_MESSAGE_BG,
            message_type=MessageType.USER,
            fg_color=COLOR_USER_MESSAGE_FG,  # Dark purple text for user
            image_data=image_data,
            is_markdown=False
        )
    
    def _parse_fix_suggestions(self, markdown_text: str) -> tuple:
        """Extract fix suggestions from markdown with ```fix{lines:N-M} blocks.
        
        Returns:
            tuple: (clean_text, list of fix dicts)
        """
        import re
        
        fixes = []
        
        # Pattern: ```fix{lines:5} or ```fix{lines:5-7}
        # Groups: (1) lines spec "5" or "5-7", (2) code inside block
        pattern = r'```fix\{lines:([\d\-]+)\}\s*\n(.*?)```'
        
        for match in re.finditer(pattern, markdown_text, re.DOTALL):
            lines_spec = match.group(1)  # "5" or "5-7"
            code = match.group(2).rstrip()  # Fix code
            
            # Parse line numbers
            if '-' in lines_spec:
                start_line, end_line = map(int, lines_spec.split('-'))
            else:
                start_line = end_line = int(lines_spec)
            
            # Validate range
            if end_line < start_line:
                logger.error(f"Fix has invalid range {start_line}-{end_line} (end < start), skipping")
                continue
            
            # Extract reason from text BEFORE the block (since last code block or start of message)
            before_fix = markdown_text[:match.start()]
            
            # Find last code block before this fix (any ``` block)
            last_code_block = None
            for code_match in re.finditer(r'```[^\n]*\n.*?```', before_fix, re.DOTALL):
                last_code_block = code_match
            
            # Text between last code block and current fix (or from start if no previous code)
            if last_code_block:
                text_for_reason = before_fix[last_code_block.end():]
            else:
                text_for_reason = before_fix
            
            # Try explicit "Що не так:" sections first
            reason_match = re.search(r'\*\*Что не так:\*\*\s*\n(.+?)(?=\n\*\*|$)', text_for_reason, re.DOTALL)
            if not reason_match:
                reason_match = re.search(r'\*\*Що не так:\*\*\s*\n(.+?)(?=\n\*\*|$)', text_for_reason, re.DOTALL)
            
            if reason_match:
                reason = reason_match.group(1).strip()
            else:
                # Fallback: use all text between code blocks (cleaned up)
                reason = text_for_reason.strip()
                # Remove leading/trailing newlines and excessive whitespace
                reason = re.sub(r'\n{3,}', '\n\n', reason).strip()
            
            # Skip only if BOTH code and reason are empty
            if not code.strip() and not reason.strip():
                logger.warning(f"Fix suggestion at lines {start_line}-{end_line} has no code and no reason, skipping")
                continue
            
            fixes.append({
                'start_line': start_line,
                'end_line': end_line,
                'new': code,
                'reason': reason,
                'has_code': bool(code.strip())  # For showing/hiding Apply button
            })
        
        # Keep ```fix blocks in text, but remove "**Как исправить:**" / "**Як виправити:**" headers
        # This way the code stays visible in chat, but the redundant header is removed
        clean_text = markdown_text
        
        # Remove "**Как исправить:**" or "**Як виправити:**" lines before fix blocks
        clean_text = re.sub(r'\*\*Как исправить:\*\*\s*\n(?=```fix)', '', clean_text)
        clean_text = re.sub(r'\*\*Як виправити:\*\*\s*\n(?=```fix)', '', clean_text)
        
        # Remove excessive empty lines
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
        
        return clean_text, fixes
    
    def _show_fix_popup_in_editor(self, fix: dict) -> None:
        """Generate event to show fix suggestion popup.
        
        The actual popup display is handled by the fix suggestion handler
        registered in load_plugin(), maintaining separation of concerns.
        """
        # Generate event with fix data - handler will display the popup
        get_workbench().event_generate("ShowFixSuggestion", fix=fix)

    # Removed submit button - use Enter key instead
    # def _on_click_submit(self) -> None:
    #     if self._current_assistant.get_ready():
    #         self.submit_user_chat_message(self.query_text.get("1.0", "end"))

    def _on_press_enter_in_chat_entry(self, event: tk.Event):
        if shift_is_pressed(event):
            return None

        if self._current_assistant.get_ready():
            self.submit_user_chat_message(self.query_text.get("1.0", "end"))

        return "break"

    def submit_user_chat_message(
        self, 
        message: str, 
        is_debug_related: bool = False, 
        debug_session_id: Optional[str] = None,
        display_message: Optional[str] = None,  # What to show in UI (if different from full message)
        captured_program_context: Optional[str] = None  # Pre-captured debug context (to avoid race conditions)
    ):
        self._remove_suggestions()
        message = message.rstrip()
        
        # If message is empty and image is attached, use default prompt based on language
        if not message and self._attached_image:
            try:
                lang = get_workbench().get_option("ai.language", "uk")
            except Exception:
                lang = "uk"
            
            if lang == "ru":
                message = "Опиши изображение и реши задачу, если она изображена."
                display_message = ""  # Don't show any text, only image preview
            else:  # uk
                message = "Опиши зображення та розв'яжи задачу, якщо вона зображена."
                display_message = ""  # Don't show any text, only image preview
        
        # Don't send empty messages without attachments
        if not message and not self._attached_image:
            return
        
        attachments, warnings = self.compile_attachments(message)
        self._prepare_new_completion()

        self._active_chat_request_id = str(uuid.uuid4())
        # self._show_loading_indicator()  # Removed submit button
        
        # Render using window_create-based bubble
        text_to_display = (display_message if display_message else message).strip()
        self._insert_user_bubble(text_to_display, self._attached_image if self._attached_image else None)
        
        if attachments:
            self._formatted_attachmets_per_message[self._active_chat_request_id] = (
                self._current_assistant.format_attachments(attachments)
            )
            self._append_text(
                " 📎",
                tags=("attachments_link", f"att_{self._active_chat_request_id}", "bubble_message"),
            )

        for warning in warnings:
            self._append_text("WARNING: " + warning + "\n\n")

        # Create new user message (don't add to history yet - will be added after AI response)
        new_user_message = ChatMessage(
            ChatRole.USER, 
            message, 
            attachments, 
            is_debug_related, 
            debug_session_id,
            self._attached_image  # Pass image to ChatMessage
        )
        
        # Save pending message to add to history after AI response
        self._current_pending_message = new_user_message
        
        # Show bot avatar and typing indicator immediately (before AI response starts)
        typing_bubble_start = self.text.index("end-1c")
        # Top padding for typing indicator
        self._append_text("\n", tags=("bubble_padding",))
        self._append_text("🤖 ", tags=("bubble_avatar", "bubble_message"))
        typing_start = self.text.index("end-1c")
        self._append_text("·", tags=("typing_indicator", "bubble_message"))
        # Bottom padding for typing indicator
        self._append_text("\n", tags=("bubble_padding",))
        # Add extra line for spacing (will be included in bubble background)
        self._append_text("\n", tags=("bubble_padding",))
        
        # Apply light greige background to typing indicator bubble
        typing_bubble_end = self.text.index("end-1c")
        import time
        typing_bg_tag = f"typing_bg_{int(time.time() * 1000000)}"
        self.text.tag_configure(typing_bg_tag, background=COLOR_BOT_MESSAGE_BG, spacing1=0, spacing3=0)
        self.text.tag_add(typing_bg_tag, typing_bubble_start, typing_bubble_end)
        self.text.tag_lower(typing_bg_tag)
        
        self._bot_avatar_added = True
        # Store position to update typing indicator (just the dots, not avatar)
        self._typing_indicator_start = typing_start
        self._typing_line_start = typing_bubble_start  # Store start for deletion
        # Start animation
        self._start_typing_animation()
        
        self.query_text.delete("1.0", "end")
        
        # Clear attached image and preview after sending
        self._clear_attached_image()
        
        # Note: _clear_attached_image already calls focus_set(), but call again to be sure
        self.query_text.focus_set()

        # Save captured context for thread to avoid race condition
        # (otherwise debugger state might change before thread reads it)
        self._captured_program_context = captured_program_context

        for assistant in self.select_assistants_for_user_message(message):
            threading.Thread(
                target=self._complete_chat_in_thread,
                daemon=True,
                args=(
                    assistant,
                    self._active_chat_request_id,
                    new_user_message,  # Pass new message to thread
                ),
            ).start()

        return "break"

    def compile_attachments(self, message: str) -> Tuple[List[Attachment], List[str]]:
        from thonny.shell import ExecutionInfo

        attachments = []
        warnings = []
        last_run_info: Optional[ExecutionInfo] = None
        tags = re.findall(r"#(\w+)", message)

        current_editor = get_workbench().get_editor_notebook().get_current_editor()

        # convert known tags to their proper forms
        proper_tags = {
            "currentfile": "currentFile",
            "selectedcode": "selectedCode",
            "lastrun": "lastRun",
            "selectedoutput": "selectedOutput",
        }
        tags = [proper_tags.get(tag.lower(), tag) for tag in tags]

        # best to process them in order
        for tag in ["currentFile", "selectedCode", "lastRun", "selectedOutput"]:
            if tag not in tags:
                continue

            attachment = None

            if tag == "currentFile":
                if current_editor is not None:
                    if current_editor.is_local():
                        editor_name = os.path.relpath(
                            current_editor.get_target_path(), get_workbench().get_local_cwd()
                        )

                    elif current_editor.is_remote():
                        # TODO: can do better
                        editor_name = current_editor.get_target_path().split("/")[-1]
                    else:
                        assert current_editor.is_untitled()
                        editor_name = "unnamed file"

                    attachment = Attachment(editor_name, tag, current_editor.get_content())
                    if not attachment.content.strip():
                        attachment = None
                        warnings.append("Not attaching empty #currentFile to avoid confusion")
                else:
                    warnings.append("Can't attach #currentFile as there is no current editor")

            elif tag == "selectedCode":
                current_editor = get_workbench().get_editor_notebook().get_current_editor()
                if current_editor is not None:
                    attachment = self.create_selection_attachment(
                        current_editor.get_code_view().text, "Selected code", tag
                    )

                    if attachment is None:
                        warnings.append(
                            "Can't attach #selectedCode as there is no selection in current editor"
                        )

                else:
                    warnings.append("Can't attach #selectedCode as there is no currentEditor")

            elif tag == "lastRun":
                # TODO: Consider also other commands besides %Run?
                last_run_info = get_shell().text.extract_last_execution_info("%Run")
                logger.info("last_run: %r", last_run_info)
                if last_run_info is None:
                    warnings.append("Could not find last run")
                else:
                    content = get_shell().text.get(
                        last_run_info.io_start_index, last_run_info.io_end_index
                    )
                    command_line = last_run_info.command_line.replace("%Run", "python")
                    attachment = Attachment(f"console log of `{command_line}`", tag, content)

            elif tag == "selectedOutput":
                attachment = self.create_selection_attachment(
                    get_shell().text, "Selected output", tag
                )
                if attachment is None:
                    warnings.append(
                        "Can't attach information about selected output, as nothing is selected in Shell"
                    )
            else:
                logger.warning("Unknown tag %r", tag)

            if attachment is None:
                continue

            if attachment.tag is not None:
                if self._last_tagged_attachments.get(attachment.tag) == attachment:
                    logger.info("Attachment %r already in context")
                    continue
                else:
                    self._last_tagged_attachments[attachment.tag] = attachment

            attachments.append(attachment)

        return attachments, warnings

    def create_selection_attachment(
        self,
        text: EnhancedText,
        description: str,
        tag: str,
    ) -> Optional[Attachment]:
        sel_start_index, sel_end_index = text.get_selection_indices()
        if sel_start_index is None:
            return None

        return Attachment(description, tag, text.get(sel_start_index, sel_end_index))

    def select_assistants_for_user_message(self, message: str) -> List[Assistant]:
        # Single active assistant only (model toggle controls which one)
            return [self._current_assistant]
    
    def _summarize_ai_history_if_needed(self) -> None:
        """Compress AI history using AI summarization (keeps UI history full)"""
        try:
            SUMMARY_MAX_MSGS = int(get_workbench().get_option("ai.summary_max_msgs", 25))
        except Exception:
            SUMMARY_MAX_MSGS = 25
        try:
            SUMMARY_MAX_CHARS = int(get_workbench().get_option("ai.summary_max_chars", 10000))
        except Exception:
            SUMMARY_MAX_CHARS = 10000
        
        # Calculate total size
        total_chars = sum(len(msg.content) for msg in self._ai_messages)
        
        # Check if summarization is needed
        if len(self._ai_messages) <= SUMMARY_MAX_MSGS and total_chars <= SUMMARY_MAX_CHARS:
            return  # No summarization needed
        
        logger.info(f"Summarizing AI history: {len(self._ai_messages)} messages, {total_chars} chars")
        
        # Request summary from AI (synchronous, blocking - but happens rarely)
        try:
            # Get summary from AI for all messages except last 5
            summary_text = self._current_assistant.get_history_summary(self._ai_messages[:-5])
            
            # Create summary message
            summary_message = ChatMessage(
                ChatRole.ASSISTANT,
                f"[Резюме беседы]\n{summary_text}",
                []
            )
            
            # Replace old messages with summary + keep last 5 messages
            self._ai_messages = [summary_message] + self._ai_messages[-5:]
            
            logger.info(f"After AI summarization: {len(self._ai_messages)} messages")
        except Exception as e:
            logger.warning(f"AI summarization failed, using simple truncation: {e}")
            # Fallback: just keep last 10 messages
            self._ai_messages = self._ai_messages[-10:]
            logger.info(f"After fallback summarization: {len(self._ai_messages)} messages")

    def _complete_chat_in_thread(self, assistant: Assistant, request_id: str, current_message: ChatMessage):
        try:
            # Check if this is a debug-related auto-generated request
            # For debug requests, we don't need file/selection info (already in debug context)
            is_debug_request = current_message.is_debug_related
            
            active_file_path = None
            active_file_selection = None
            program_context = None
            
            # Use pre-captured context if available (to avoid race conditions with debugger)
            # Otherwise, check if debugger is currently active
            from thonny.plugins.debug_common import get_debug_context, format_code_context
            if hasattr(self, '_captured_program_context') and self._captured_program_context:
                program_context = self._captured_program_context
                # Clear after use
                self._captured_program_context = None
            else:
                program_context = get_debug_context()
            
            # For non-debug requests, get editor context
            if not is_debug_request:
                editor = get_workbench().get_editor_notebook().get_current_editor()
                if editor:
                    active_file_path = editor.get_filename()
                    
                    # Format code context if not in debug mode
                    if not program_context:
                        file_content = editor.get_content()
                        program_context = format_code_context(file_content, active_file_path or "program.py")
                    
                    # Get selected text if any
                    text_widget = editor.get_text_widget()
                    try:
                        if text_widget.tag_ranges("sel"):
                            active_file_selection = text_widget.get("sel.first", "sel.last")
                    except tk.TclError:
                        # No selection
                        pass
            
            # Apply summarization to AI history if needed
            self._summarize_ai_history_if_needed()
            
            # Create context with AI history + current message
            context = ChatContext(
                messages=list(self._ai_messages),  # AI history (compressed, no debug after session ends)
                current_message=current_message,  # New message (will be added to both histories after response)
                active_file_path=active_file_path,
                active_file_selection=active_file_selection,
                program_context=program_context,  # Either debug context or formatted code
            )
            for fragment in assistant.complete_chat(context):
                get_workbench().queue_event(
                    "AiChatResponseFragment",
                    ChatResponseFragmentWithRequestId(fragment, request_id=request_id),
                )
        except Exception as e:
            logger.exception("Error when completing chat in thread")

            # Format error message for user
            import traceback
            error_type = type(e).__name__
            error_msg = str(e)
            
            # Shorten very long error messages
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "..."
            
            user_message = f"❌ **Помилка / Ошибка ({error_type}):**\n\n{error_msg}\n\n"
            
            # Add hints for common errors
            if "NotFound" in error_type or "404" in error_msg:
                user_message += "_Підказка: Перевірте назву моделі або доступність API._\n"
                user_message += "_Hint: Check model name or API availability._"
            elif "Unauthorized" in error_type or "401" in error_msg or "API" in error_msg and "key" in error_msg.lower():
                user_message += "_Підказка: Перевірте API ключ в Tools → Manage plug-ins._\n"
                user_message += "_Hint: Check API key in Tools → Manage plug-ins._"
            elif "RateLimitError" in error_type or "429" in error_msg:
                user_message += "_Підказка: Перевищено ліміт запитів. Спробуйте пізніше._\n"
                user_message += "_Hint: Rate limit exceeded. Try again later._"

            get_workbench().queue_event(
                "AiChatResponseFragment",
                ChatResponseFragmentWithRequestId(
                    ChatResponseChunk(
                        content=user_message,
                        is_interal_error=True,
                    ),
                    request_id=request_id,
                ),
            )

    def _on_mouse_move_in_text(self, event=None):
        tags = self.text.tag_names("@%d,%d" % (event.x, event.y))
        if "attachments_link" in tags or "python_errors_link" in tags:
            if self.text.cget("cursor") != get_hyperlink_cursor():
                self.text.config(cursor=get_hyperlink_cursor())
        else:
            if self.text.cget("cursor") != get_beam_cursor():
                self.text.config(cursor=get_beam_cursor())

    def _on_click_attachments_link(self, event: tk.Event):
        tags = self.text.tag_names("@%d,%d" % (event.x, event.y))
        for tag in tags:
            if tag.startswith("att_"):
                request_id = tag.removeprefix("att_")
                formatted_attachments = self._formatted_attachmets_per_message[request_id]
                dlg = LongTextDialog(
                    title=tr("Attachments"), text_content=formatted_attachments, parent=self
                )
                show_dialog(dlg, master=get_workbench())

    def _remove_suggestions(self) -> None:
        # Suggestions panel removed - do nothing
        self._current_suggestions = []

    def _update_suggestions(self) -> None:
        # Suggestions panel removed - do nothing
        return
        logger.debug("Updating suggestions")
        new_suggestions = []

        # Import here to avoid circular dependency
        from thonny.plugins.debugger import get_current_debugger
        
        # Add debug suggestions if debugging is active
        debugger = get_current_debugger()
        if debugger and hasattr(debugger, '_last_progress_message') and debugger._last_progress_message:
            try:
                lang = get_workbench().get_option("ai.language", "uk")
            except Exception:
                lang = "uk"
            if lang == "ru":
                new_suggestions.append("🐛 Что здесь?")
                new_suggestions.append("🔮 Что дальше?")
                new_suggestions.append("📊 Переменные")
            else:
                new_suggestions.append("🐛 Що тут?")
                new_suggestions.append("🔮 Що далі?")
                new_suggestions.append("📊 Змінні")

        # Removed: Check #currentFile, Explain #lastRun

        if new_suggestions != self._current_suggestions:
            self._remove_suggestions()
            for i, suggestion in enumerate(new_suggestions):
                self._append_suggestion(suggestion, first=i == 0)
            self._current_suggestions = new_suggestions
            self._update_suggestions_box()

    def _append_suggestion(self, text: str, first: bool) -> None:
        # Suggestions panel removed - do nothing
        pass

    def _update_suggestions_box(self):
        # Suggestions panel removed - do nothing
        return
        update_text_height(self.suggestions_text, min_lines=1, max_lines=5)
    
    # Removed submit button and loading indicator - using Enter to submit
    # def _show_loading_indicator(self):
    #     """Show animated loading indicator and hide submit button"""
    #     pass
    # 
    # def _hide_loading_indicator(self):
    #     """Hide loading indicator and show submit button"""
    #     pass
    # 
    # def _animate_loading(self):
    #     """Animate loading spinner"""
    #     pass


def take_screenshot_without_chat():
    """Global function to take screenshot while hiding Chat panel"""
    # Variables for finally block
    shell = None
    chat_view = None
    notebook = None
    was_visible = False
    
    try:
        import time
        from datetime import datetime
        from pathlib import Path
        
        workbench = get_workbench()
        
        # Get ChatView instance
        try:
            chat_view = workbench.get_view("ChatView", create=False)
            notebook = getattr(chat_view, 'containing_notebook', None)
            
            if notebook:
                # Check if chat is visible as a tab
                tabs = notebook.tabs()
                was_visible = len(tabs) > 0 and chat_view.winfo_manager() != ''
                
                if was_visible:
                    try:
                        notebook.forget(chat_view)
                    except Exception as e:
                        logger.warning(f"Could not hide chat panel: {e}")
                        was_visible = False
        except (RuntimeError, KeyError):
            pass
        
        # Hide Shell UI elements
        try:
            shell = workbench.get_view("ShellView", create=False)
            if shell and hasattr(shell, 'hide_for_screenshot'):
                shell.hide_for_screenshot()
        except:
            pass
        
        # Hide screenshot button
        if hasattr(workbench, 'hide_screenshot_button_for_screenshot'):
            try:
                workbench.hide_screenshot_button_for_screenshot()
            except:
                pass
        
        # Hide info buttons in all open editors
        try:
            editor_notebook = workbench.get_editor_notebook()
            if editor_notebook:
                for editor_tab in editor_notebook.winfo_children():
                    if hasattr(editor_tab, 'get_code_view'):
                        code_view = editor_tab.get_code_view()
                        if code_view and hasattr(code_view, 'hide_for_screenshot'):
                            code_view.hide_for_screenshot()
        except:
            pass
        
        # Single unified update cycle for all hidden elements
        # Exit early if chat is hidden and we've waited at least 150ms
        start_time = time.time()
        max_iterations = 10  # Maximum ~500ms (10 * 50ms)
        min_wait_time = 0.15  # Minimum 150ms
        
        for i in range(max_iterations):
            workbench.update_idletasks()
            workbench.update()
            time.sleep(0.05)
            
            elapsed = time.time() - start_time
            # Exit ONLY if BOTH conditions are met: elapsed >= 150ms AND chat is hidden
            if elapsed >= min_wait_time and (not was_visible or not chat_view.winfo_ismapped()):
                break
        
        # Prepare filename
        desktop_path = Path.home() / "Desktop"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"thonny_screenshot_{timestamp}.png"
        filepath = desktop_path / filename
        
        # Try mss library first (fast and reliable)
        try:
            import mss
            
            # Get window bounds
            x = workbench.winfo_rootx()
            y = workbench.winfo_rooty()
            width = workbench.winfo_width()
            height = workbench.winfo_height()
            
            monitor = {"top": y, "left": x, "width": width, "height": height}
            
            with mss.mss() as sct:
                # Capture the window area
                sct_img = sct.grab(monitor)
                # Save to file
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))
            
            logger.debug(f"Screenshot saved with mss: {filepath}")
            
        except ImportError:
            # Fallback to PIL if mss is not available
            logger.debug("mss not available, trying PIL")
            from PIL import ImageGrab
            
            x = workbench.winfo_rootx()
            y = workbench.winfo_rooty()
            width = workbench.winfo_width()
            height = workbench.winfo_height()
            
            # Bring window to front
            workbench.lift()
            workbench.attributes('-topmost', True)
            workbench.update()
            time.sleep(0.1)
            workbench.attributes('-topmost', False)
            
            screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            screenshot.save(filepath)
            logger.info(f"Screenshot saved with PIL: {filepath}")
        
        # Show brief notification in console
        print(f"✓ Скриншот сохранён: {filepath}")
        
    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}", exc_info=True)
        print(f"✗ Ошибка при создании скриншота: {e}")
        
    finally:
        # Restore Shell UI elements after screenshot
        if shell and hasattr(shell, 'show_after_screenshot'):
            try:
                shell.show_after_screenshot()
            except:
                pass
        
        # Restore screenshot button
        try:
            workbench = get_workbench()
            if hasattr(workbench, 'show_screenshot_button_after_screenshot'):
                workbench.show_screenshot_button_after_screenshot()
        except:
            pass
        
        # Restore info buttons in all open editors
        try:
            workbench = get_workbench()
            editor_notebook = workbench.get_editor_notebook()
            if editor_notebook:
                for editor_tab in editor_notebook.winfo_children():
                    if hasattr(editor_tab, 'get_code_view'):
                        code_view = editor_tab.get_code_view()
                        if code_view and hasattr(code_view, 'show_after_screenshot'):
                            code_view.show_after_screenshot()
        except:
            pass
        
        # Always restore chat panel if it was visible
        if was_visible and notebook and chat_view:
            try:
                # Re-add the chat tab to notebook
                logger.info(f"Restoring chat panel")
                notebook.add(chat_view, text=tr("Chat"))
                notebook.select(chat_view)
                get_workbench().update_idletasks()
                logger.info(f"Chat panel restored")
            except Exception as e:
                logger.error(f"Failed to restore chat panel: {e}")


# Global variable to track current fix popup (prevent multiple overlapping popups)
_current_fix_popup = None


def _handle_show_fix_suggestion(event):
    """Handler for ShowFixSuggestion event.
    
    This handler is decoupled from ChatView and can be called from anywhere.
    It gets the current editor and displays the fix popup.
    """
    from thonny.codeview_popup_utils import create_fix_popup
    global _current_fix_popup
    
    fix = event.fix
    editor = get_workbench().get_editor_notebook().get_current_editor()
    if not editor:
        logger.warning("No editor open to show fix popup")
        return
    
    text_widget = editor.get_text_widget()
    
    # Validate line numbers
    try:
        max_line = int(text_widget.index('end-1c').split('.')[0])
        start_line = fix['start_line']
        end_line = fix['end_line']
        
        # Allow start_line to be max_line+1 for "append to end" suggestions
        # This happens when AI suggests adding new code at the end of file
        if start_line < 1 or start_line > max_line + 1 or end_line < start_line:
            logger.error(f"Invalid line numbers: {start_line}-{end_line}, file has {max_line} lines")
            return
        
        # If suggesting to add at the end (start_line > max_line), adjust to show at last line
        if start_line > max_line:
            logger.info(f"Fix suggestion for lines {start_line}-{end_line} is beyond file end ({max_line} lines), treating as append")
            # Keep original line numbers in fix dict for display, but use last line for positioning
            fix['_is_append'] = True
            fix['_display_start'] = start_line
            fix['_actual_start'] = max_line
    except Exception as e:
        logger.error(f"Failed to validate line numbers: {e}")
        return
    
    # Close existing popup if any
    if _current_fix_popup and _current_fix_popup.winfo_exists():
        try:
            _current_fix_popup.destroy()
        except:
            pass
    
    # Show new popup
    _current_fix_popup = create_fix_popup(
        parent=editor,
        fix=fix,
        text_widget=text_widget,
        editor=editor
    )


def load_plugin():
    # Register AI options with defaults so they persist between sessions
    get_workbench().set_default("ai.model", "gemini")
    get_workbench().set_default("ai.language", "uk")
    get_workbench().set_default("ai.summary_max_msgs", 25)
    get_workbench().set_default("ai.summary_max_chars", 10000)
    
    get_workbench().add_view(ChatView, tr("Chat"), "se", visible_by_default=True)
    
    # Add screenshot command to toolbar (icon only, no caption)
    get_workbench().add_command(
        "take_screenshot",
        "tools",
        "",  # Empty command_label - no tooltip
        take_screenshot_without_chat,
        include_in_menu=False,  # Not in menu, only in toolbar
        include_in_toolbar=True,
        image="camera",
        caption=None,  # No caption - icon-only button
        group=210,  # Last button in toolbar (max used is 200)
    )
    
    # Register handler for fix suggestions from AI
    # This decouples ChatView from CodeView - chat only generates events,
    # and this handler displays popups
    get_workbench().bind("ShowFixSuggestion", _handle_show_fix_suggestion, True)