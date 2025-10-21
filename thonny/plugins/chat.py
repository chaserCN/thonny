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
            padx=10,
            pady=0,
            insertwidth=0,
            background="white",
            suppress_events=True,
        )

        self._analyzer_instances = []

        self._chat_messages: List[ChatMessage] = []
        self._formatted_attachmets_per_message: Dict[str, str] = {}
        self._last_tagged_attachments: Dict[str, Attachment] = {}
        self._active_chat_request_id: Optional[str] = None
        self._current_chat_response_buffer: str = ""  # Buffer for streaming RST

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

        user_margin = ems_to_pixels(8)
        self.text.tag_configure(
            "user_message",
            lmargin1=user_margin,
            lmargin2=user_margin,
            rmargin=ems_to_pixels(0.5),  # Правый отступ внутри фона
            spacing1=4,  # Отступ сверху
            spacing3=4,  # Отступ снизу
            # font=italic_font,
            lmargincolor="white",
            background="#E3F2FD",  # Светло-голубой фон
            foreground="#1565C0",  # Тёмно-синий текст
        )
        
        # Avatar styles
        self.text.tag_configure(
            "user_avatar",
            foreground="#4A90E2",  # Blue for user
        )
        self.text.tag_configure(
            "bot_avatar",
            foreground="#50C878",  # Green for bot
        )
        self.text.tag_configure(
            "typing_indicator",
            foreground="#999999",  # Gray for typing indicator
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
        self.query_box.grid(row=1, column=1, sticky="nsew")

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
        panel.rowconfigure(1, weight=0)  # buttons row
        panel.rowconfigure(2, weight=1)  # input
        panel.columnconfigure(1, weight=0)  # left buttons
        panel.columnconfigure(2, weight=1)  # loading indicator (expanding)
        panel.columnconfigure(3, weight=0)  # right buttons

        pad = ems_to_pixels(1)

        # Left frame for language and model buttons
        left_buttons_frame = tk.Frame(panel, background=background)
        left_buttons_frame.grid(row=1, column=1, sticky="w", padx=(pad, 0), pady=(pad, 0))

        # Language toggle button (UA/RU) above the input
        def _current_lang() -> str:
            try:
                return get_workbench().get_option("ai.language", "uk")
            except Exception:
                return "uk"

        def _lang_label_from(code: str) -> str:
            return "УК" if code == "uk" else "РУ"

        # Language toggle button (UA/RU)
        self.lang_button = tk.Button(
            left_buttons_frame,
            text=_lang_label_from(_current_lang()),
            command=self._toggle_lang,
            background=background,
            activebackground=background,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=4,
            pady=2,
        )
        self.lang_button.pack(side="left", padx=(0, 4))
        
        # Model selection dropdown (GPT/Gemini/Claude) next to language button
        def _current_model() -> str:
            try:
                return get_workbench().get_option("ai.model", "gpt")
            except Exception:
                return "gpt"
        
        def _model_label_from(model: str) -> str:
            return {"gpt": "GPT", "gemini": "Gemini", "claude": "Claude"}.get(model, "GPT")
        
        self.model_var = tk.StringVar(value=_model_label_from(_current_model()))
        self.model_combobox = ttk.Combobox(
            left_buttons_frame,
            textvariable=self.model_var,
            values=["GPT", "Gemini", "Claude"],
            state="readonly",
            width=8,
        )
        self.model_combobox.pack(side="left", padx=(0, 5))
        self.model_combobox.bind("<<ComboboxSelected>>", lambda e: self._on_model_selected())
        
        # Clear chat button (right side) - same style as submit button
        clear_button_frame = create_custom_toolbutton_in_frame(
            panel,
            text=" 🗑 ",  # Trash icon with padding
            command=self._clear_chat,
            background=background,
            borderwidth=1,
            bordercolor=bordercolor,
        )
        clear_button_frame.grid(row=1, column=3, sticky="e", padx=(0, pad), pady=(pad, 0))

        border_frame = tk.Frame(panel, background="#cccccc")
        border_frame.grid(row=2, column=1, columnspan=2, sticky="nsew", padx=(pad, 0), pady=(pad//2, pad))
        border_frame.rowconfigure(0, weight=1)
        border_frame.columnconfigure(0, weight=1)

        inside_frame = tk.Frame(border_frame, background="white")
        inside_frame.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        inside_frame.rowconfigure(0, weight=1)
        inside_frame.columnconfigure(0, weight=1)

        self.query_text = tk.Text(
            inside_frame,
            height=1,
            font="TkDefaultFont",
            borderwidth=0,
            highlightthickness=0,
            relief="groove",
            wrap="word",
            insertwidth=2,  # Ширина курсора
            insertbackground="black",  # Цвет курсора
        )
        self.query_text.bind("<Return>", self._on_press_enter_in_chat_entry, True)
        self.query_text.bind("<Key>", self._on_change_query_text, True)

        self.query_text.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        
        # Set focus to input field on startup
        self.query_text.focus_set()
        
        # Image attach button (left of submit button)
        image_button_frame = create_custom_toolbutton_in_frame(
            panel,
            text=" 🖼️ ",  # Image icon
            command=self._attach_image,
            background=background,
            borderwidth=1,
            bordercolor=bordercolor,
        )
        image_button_frame.grid(row=2, column=2, sticky="e", padx=(0, pad//2), pady=(pad//2, pad))

        # Create container for submit button and loading indicator (same position)
        submit_container = tk.Frame(panel, background=background)
        submit_container.grid(row=2, column=3, sticky="e", padx=(pad//2, pad), pady=(pad//2, pad))
        
        # Submit button (shown by default)
        self.submit_button_frame = create_custom_toolbutton_in_frame(
            submit_container,
            text=" ⏎ ",
            command=self._on_click_submit,
            background=background,
            borderwidth=1,
            bordercolor=bordercolor,
        )
        self.submit_button_frame.pack()
        
        # Loading indicator (hidden by default) - same size as submit button
        import tkinter.font as tkfont
        spinner_font = tkfont.Font(family="TkDefaultFont", size=14, weight="normal")
        
        self.loading_label = tk.Label(
            submit_container,
            text="",
            background=background,
            font=spinner_font,
            foreground="#666666",
            width=2,  # Same width as submit button
        )
        # Don't pack yet - will be shown when loading starts

        return panel

    def handle_assistant_chat_response_fragment(
        self, fragment_with_request_id: ChatResponseFragmentWithRequestId
    ) -> None:
        if fragment_with_request_id.request_id != self._active_chat_request_id:
            logger.info("Skipping chat fragment, because request has been cancelled")
            return

        fragment = fragment_with_request_id.fragment
        
        # For RstText, accumulate and render at the end
        if isinstance(self.text, rst_utils.RstText):
            if not fragment.is_final:
                # Just accumulate the content
                # Add bot avatar + typing indicator before first fragment
                if not self._bot_avatar_added:
                    self._append_text("🤖 ", tags=("bot_avatar",))
                    # Add typing indicator that will be animated
                    typing_start = self.text.index("end-1c")
                    self._append_text("·", tags=("typing_indicator",))
                    self._bot_avatar_added = True
                    # Store position to update typing indicator
                    self._typing_indicator_start = typing_start
                    # Start animation
                    self._start_typing_animation()
                
                self._current_chat_response_buffer += fragment.content
            else:
                # Stop animation and remove typing indicator
                self._stop_typing_animation()
                if hasattr(self, '_typing_indicator_start'):
                    try:
                        self.text.direct_delete(self._typing_indicator_start, "end")
                    except:
                        pass
                
                # Render accumulated content at the end
                try:
                    # Use markdown renderer for all messages
                    from thonny.markdown_utils import render_markdown
                    render_markdown(self.text, self._current_chat_response_buffer)
                except Exception as e:
                    # Fallback to plain text if formatting fails
                    logger.warning(f"Markdown rendering failed: {e}", exc_info=True)
                    self.text.direct_insert("end", self._current_chat_response_buffer)
                self.text.direct_insert("end", "\n")
                self._current_chat_response_buffer = ""  # Clear buffer
                self._bot_avatar_added = False  # Reset for next response
        else:
            # For regular text, use streaming
            self._append_text(fragment.content, source="chat")
        
        last_msg = self._chat_messages.pop()
        if last_msg.role == ChatRole.USER:
            self._chat_messages.append(last_msg)
            # Inherit debug-related status from user message
            current_msg = ChatMessage(ChatRole.ASSISTANT, "", [], last_msg.is_debug_related, last_msg.debug_session_id)
        else:
            current_msg = last_msg

        current_msg = replace(current_msg, content=current_msg.content + fragment.content)
        self._chat_messages.append(current_msg)
        
        if fragment.is_final:
            self._active_chat_request_id = None
            self._hide_loading_indicator()
            self._update_suggestions()
            self.text.see("end")
            
            # Remove image from history after AI has processed it
            # Find the last user message with an image and clear it
            for i in range(len(self._chat_messages) - 1, -1, -1):
                msg = self._chat_messages[i]
                if msg.role == ChatRole.USER and msg.image is not None:
                    # Replace message with version without image
                    self._chat_messages[i] = replace(msg, image=None)
                    logger.info(f"Removed image from message in history to save tokens")
                    break
            
            # Return focus to input field
            self.query_text.focus_set()

    def _toggle_lang(self) -> None:
        try:
            current = get_workbench().get_option("ai.language", "uk")
        except Exception:
            current = "uk"
        new_lang = "ru" if current == "uk" else "uk"
        try:
            get_workbench().set_option("ai.language", new_lang)
        except Exception:
            pass
        self.lang_button.config(text=("УК" if new_lang == "uk" else "РУ"))
        self._update_suggestions()
    
    def _on_model_selected(self) -> None:
        """Handle model selection change (GPT/Gemini/Claude), preserving chat history"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        # Map display name to internal value
        label_to_model = {"GPT": "gpt", "Gemini": "gemini", "Claude": "claude"}
        selected_label = self.model_var.get()
        new_model = label_to_model.get(selected_label, "gpt")
        
        logger.info(f"=" * 80)
        logger.info(f"MODEL SELECTED: {selected_label} (internal: {new_model})")
        logger.info(f"=" * 80)
        
        try:
            get_workbench().set_option("ai.model", new_model)
        except Exception:
            pass
        
        # Switch assistant while preserving history (case-insensitive keys)
        # Switch to regular assistants (not debug versions)
        assistants = get_workbench().assistants
        logger.info(f"Available assistants: {list(assistants.keys())}")
        
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
        
        logger.info(f"Selected assistant: {self._current_assistant.__class__.__name__}")
        
        # History is preserved in self._chat_messages - no need to clear it
    
    def _clear_chat(self) -> None:
        """Clear chat display and message history"""
        # Clear the displayed chat text
        self.text.direct_delete("1.0", "end")
        
        # Clear message history
        self._chat_messages.clear()
        
        # Clear debug session
        self._current_debug_session_id = None
        
        # Clear other state
        self._formatted_attachmets_per_message.clear()
        self._last_tagged_attachments.clear()
        self._current_chat_response_buffer = ""
        self._last_auto_explained_step = None
        self._attached_image = None  # Store selected image (path and base64)
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
            # Debug session ended - clear debug session ID and remove debug messages from history
            if self._current_debug_session_id is not None:
                logger.info(f"Debug session {self._current_debug_session_id} ended, cleaning up debug messages")
                # Remove all debug-related messages from history
                self._chat_messages = [
                    msg for msg in self._chat_messages
                    if not msg.is_debug_related
                ]
                self._current_debug_session_id = None
            return
        
        # Start new debug session if needed
        if self._current_debug_session_id is None:
            self._current_debug_session_id = str(uuid.uuid4())
        
        # Проверяем что была команда step_over или step_into
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
        
        # Избегаем повторной генерации для того же шага
        # Используем информацию о текущей строке кода
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
        
        # Добавляем debug контекст к полному промпту
        if debug_ctx:
            full_prompt = f"{full_prompt}\n\n{debug_ctx}"
        
        # Временно подменяем assistant на debug версию для этого запроса
        original_assistant = self._current_assistant
        self._current_assistant = debug_assistant
        
        try:
            # Отправляем: полный промпт для AI, короткий для отображения
            self.submit_user_chat_message(
                full_prompt, 
                is_debug_related=True, 
                debug_session_id=self._current_debug_session_id,
                display_message=display_prompt
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

        text_after_last_analysis = self.text.get(self._last_analysis_end_index, "end")
        if not text_after_last_analysis.strip():
            # No question was asked after the last analysis, let's forget that analysis.
            self.text.direct_delete(self._last_analysis_start_index, "end-1c")

        self._last_analysis_start_index = self.text.index("end-1c")
        self._last_analysis_end_index = self.text.index("end-1c")

    def _prepare_new_completion(self):
        self._cancel_analysis()
        self._cancel_completion()

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
            
            # Update the text
            self.text.direct_delete(self._typing_indicator_start, "end")
            self.text.direct_insert(self._typing_indicator_start, current_dots, ("typing_indicator",))
            
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
            self._hide_loading_indicator()
            self._stop_typing_animation()  # Stop animation on cancel
            self._append_text("... [cancelled]", source="chat")
            # Clear RST streaming buffer if any
            self._current_chat_response_buffer = ""
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

    def _attach_image(self) -> None:
        """Open file dialog to select an image"""
        from tkinter import filedialog
        import base64
        
        filetypes = [
            ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
            ("All files", "*.*")
        ]
        
        filepath = filedialog.askopenfilename(
            title="Select an image",
            filetypes=filetypes
        )
        
        if filepath:
            try:
                # Read and encode image to base64
                with open(filepath, "rb") as image_file:
                    image_data = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Determine image format from extension
                import os
                ext = os.path.splitext(filepath)[1].lower().lstrip('.')
                if ext == 'jpg':
                    ext = 'jpeg'
                
                self._attached_image = {
                    'path': filepath,
                    'base64': image_data,
                    'format': ext
                }
                
                # Clear any previous image indicator
                current_text = self.query_text.get("1.0", "end-1c")
                if current_text.startswith("[🖼️"):
                    # Remove old image indicator
                    first_newline = current_text.find("\n")
                    if first_newline != -1:
                        self.query_text.delete("1.0", f"1.{first_newline+1}")
                
                # Show image indicator at the top
                self.query_text.insert("1.0", f"[🖼️ {os.path.basename(filepath)}]\n")
                
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("Error", f"Failed to load image: {e}")
    
    def _on_click_submit(self) -> None:
        if self._current_assistant.get_ready():
            self.submit_user_chat_message(self.query_text.get("1.0", "end"))

    def _on_change_query_text(self, event: tk.Event):
        update_text_height(self.query_text, 1, max_lines=10)

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
        display_message: Optional[str] = None  # What to show in UI (if different from full message)
    ):
        self._remove_suggestions()
        message = message.rstrip()
        attachments, warnings = self.compile_attachments(message)
        self._prepare_new_completion()

        self._active_chat_request_id = str(uuid.uuid4())
        self._show_loading_indicator()
        self._append_text("\n")
        
        # Add user avatar before message (with same background as message)
        self._append_text("👤 ", tags=("user_avatar", "user_message"))
        
        # Show display_message in UI if provided, otherwise show full message
        text_to_display = display_message if display_message else message
        self._append_text(text_to_display, tags=("user_message",))
        
        # Show image indicator if image is attached
        if self._attached_image:
            import os
            image_name = os.path.basename(self._attached_image['path'])
            self._append_text(f" [🖼️ {image_name}]", tags=("user_message",))
        
        if attachments:
            self._formatted_attachmets_per_message[self._active_chat_request_id] = (
                self._current_assistant.format_attachments(attachments)
            )
            self._append_text(
                " 📎",
                tags=("attachments_link", f"att_{self._active_chat_request_id}", "user_message"),
            )
        self._append_text("\n", tags=("user_message",))  # Include newline in background

        self._append_text("\n")

        for warning in warnings:
            self._append_text("WARNING: " + warning + "\n\n")

        # Store full message (with context) for AI, including image if attached
        self._chat_messages.append(
            ChatMessage(
                ChatRole.USER, 
                message, 
                attachments, 
                is_debug_related, 
                debug_session_id,
                self._attached_image  # Pass image to ChatMessage
            )
        )
        self.query_text.delete("1.0", "end")
        
        # Clear attached image after sending
        self._attached_image = None
        
        # Return focus to input field after submitting
        self.query_text.focus_set()

        for assistant in self.select_assistants_for_user_message(message):
            threading.Thread(
                target=self._complete_chat_in_thread,
                daemon=True,
                args=(
                    assistant,
                    self._active_chat_request_id,
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

    def _complete_chat_in_thread(self, assistant: Assistant, request_id: str):
        try:
            # Check if this is a debug-related auto-generated request
            # For debug requests, we don't need file/selection info (already in debug context)
            last_message = self._chat_messages[-1] if self._chat_messages else None
            is_debug_request = last_message and last_message.is_debug_related if last_message else False
            
            active_file_path = None
            active_file_selection = None
            file_contents = {}
            execution_io = None
            
            # For non-debug requests, get editor context
            if not is_debug_request:
                editor = get_workbench().get_editor_notebook().get_current_editor()
                if editor:
                    # Get full file content (but not path - not needed)
                    file_content = editor.get_content()
                    # Use generic key instead of file path
                    file_contents['current_file'] = file_content
                    
                    # Get selected text if any
                    text_widget = editor.get_text_widget()
                    try:
                        if text_widget.tag_ranges("sel"):
                            active_file_selection = text_widget.get("sel.first", "sel.last")
                    except tk.TclError:
                        # No selection
                        pass
            
            # Check if debugger is active and add debug context
            from thonny.plugins.debugger import get_current_debugger
            debugger = get_current_debugger()
            if debugger:
                # Debugger is active - add current execution state
                from thonny.plugins.debug_common import get_debug_context
                debug_ctx = get_debug_context()
                if debug_ctx:
                    # Store debug context in execution_io field
                    execution_io = debug_ctx
            
            # snapshot messages to avoid races during parallel requests
            context = ChatContext(
                messages=list(self._chat_messages),
                active_file_path=active_file_path,
                active_file_selection=active_file_selection,
                file_contents_by_path=file_contents,
                execution_io=execution_io,  # Debug context if debugger is active
            )
            for fragment in assistant.complete_chat(context):
                get_workbench().queue_event(
                    "AiChatResponseFragment",
                    ChatResponseFragmentWithRequestId(fragment, request_id=request_id),
                )

                if fragment.is_final:
                    logger.debug("Finishing chat completion thread after final fragment")
                    break
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
                        is_final=True,
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
    
    def _show_loading_indicator(self):
        """Show animated loading indicator and hide submit button"""
        # Hide submit button
        self.submit_button_frame.pack_forget()
        
        # Show loading indicator
        self.loading_label.pack()
        
        # Start animation
        self._loading_animation_step = 0
        self._animate_loading()
    
    def _hide_loading_indicator(self):
        """Hide loading indicator and show submit button"""
        # Stop animation
        self.loading_label.config(text="")
        if hasattr(self, '_loading_after_id'):
            try:
                self.after_cancel(self._loading_after_id)
            except Exception:
                pass
        
        # Hide loading indicator
        self.loading_label.pack_forget()
        
        # Show submit button
        self.submit_button_frame.pack()
    
    def _animate_loading(self):
        """Animate loading spinner"""
        if not self._chat_completion_in_progress():
            self._hide_loading_indicator()
            return
        
        # Simple spinner animation
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        char = spinner_chars[self._loading_animation_step % len(spinner_chars)]
        self.loading_label.config(text=char)
        
        self._loading_animation_step += 1
        self._loading_after_id = self.after(100, self._animate_loading)


def load_plugin():
    # Register AI options with defaults so they persist between sessions
    get_workbench().set_default("ai.model", "gpt")
    get_workbench().set_default("ai.language", "uk")
    get_workbench().set_default("ai.summary_max_msgs", 25)
    get_workbench().set_default("ai.summary_max_chars", 10000)
    
    get_workbench().add_view(ChatView, tr("Chat"), "se", visible_by_default=False)
