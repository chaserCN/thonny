import datetime
import os.path
import re
import threading
import tkinter as tk
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
            # font=italic_font,
            lmargincolor="white",
            # background="#eeeeee",
            foreground="navy",
        )

        # self.text.tag_configure("user_message_first_line", spacing1=ems_to_pixels(0.3))
        # self.text.tag_configure("user_message_last_line", spacing1=ems_to_pixels(0.3))

        self.text.bind("<Motion>", self._on_mouse_move_in_text, True)
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

        # Try to use DebugAI if available, fallback to Echo
        self._current_assistant: Assistant = get_workbench().assistants.get("debugai", EchoAssistant())

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
        panel.rowconfigure(1, weight=0)  # lang button
        panel.rowconfigure(2, weight=1)  # input
        panel.columnconfigure(1, weight=1)

        pad = ems_to_pixels(1)

        # Language toggle button (UA/RU) above the input
        def _current_lang() -> str:
            try:
                return get_workbench().get_option("ai.language", "uk")
            except Exception:
                return "uk"

        def _lang_label_from(code: str) -> str:
            return "УК" if code == "uk" else "РУ"

        self.lang_button = tk.Button(
            panel,
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
        self.lang_button.grid(row=1, column=1, sticky="w", padx=pad, pady=(pad, 0))

        border_frame = tk.Frame(panel, background="#cccccc")
        border_frame.grid(row=2, column=1, sticky="nsew", padx=pad, pady=(pad//2, pad))
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

        submit_button_frame = create_custom_toolbutton_in_frame(
            panel,
            text=" ⏎ ",
            command=self._on_click_submit,
            background=background,
            borderwidth=1,
            bordercolor=bordercolor,
        )
        submit_button_frame.grid(row=2, column=2, sticky="e", padx=(0, pad), pady=(pad//2, pad))

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
                self._current_chat_response_buffer += fragment.content
                # Show a placeholder or progress indicator
                if not self._current_chat_response_buffer.strip():
                    return
            else:
                # Render accumulated RST at the end
                try:
                    # Convert Markdown to RST before rendering
                    rst_content = self._markdown_to_rst(self._current_chat_response_buffer)
                    self.text.append_rst(rst_content)
                except Exception as e:
                    # Fallback to plain text if RST parsing fails
                    logger.warning(f"RST/Markdown parsing failed: {e}")
                    self.text.direct_insert("end", self._current_chat_response_buffer)
                self.text.direct_insert("end", "\n")
                self._current_chat_response_buffer = ""  # Clear buffer
        else:
            # For regular text, use streaming
            self._append_text(fragment.content, source="chat")
        
        last_msg = self._chat_messages.pop()
        if last_msg.role == "user":
            self._chat_messages.append(last_msg)
            current_msg = ChatMessage("assistant", "", [])
        else:
            current_msg = last_msg

        current_msg = replace(current_msg, content=current_msg.content + fragment.content)
        self._chat_messages.append(current_msg)
        
        if fragment.is_final:
            self._active_chat_request_id = None
            self._update_suggestions()
            self.text.see("end")

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
        from thonny.plugins.debug_assistant import DebugAIAssistant
        
        debugger = get_current_debugger()
        if not debugger:
            return
        
        # Проверяем что была команда step_over или step_into
        last_cmd = getattr(debugger, '_last_debugger_command', None)
        if not last_cmd or last_cmd.name not in ['step_over', 'step_into']:
            return
        
        # Проверяем что используется DebugAI ассистент
        if not isinstance(self._current_assistant, DebugAIAssistant):
            return
        
        # Избегаем повторной генерации для того же шага
        # Используем информацию о текущей строке кода
        if hasattr(msg, 'stack') and msg.stack:
            current_frame = msg.stack[-1]
            step_id = (current_frame.filename, current_frame.lineno, current_frame.event)
            
            if step_id == self._last_auto_explained_step:
                return
            
            self._last_auto_explained_step = step_id
        
        # Автоматично генеруємо пояснення (локалізовано)
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"
        if lang == "ru":
            auto_prompt = "Что выполнено на предыдущем шаге? Что произойдёт на текущей строке?"
        else:
            auto_prompt = "Що виконалось на попередньому кроці? Що станеться коли виконається поточний рядок?"
        self.submit_user_chat_message(auto_prompt)

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

    def _markdown_to_rst(self, markdown_text: str) -> str:
        """Convert limited Markdown to RST for ChatView.

        Rules:
        - Keep headings like **Що сталось:**, **Поточний стан:**, **Що далі:** as-is (bold).
        - Preserve code fences (``` ... ```) as literal blocks (:: + indented lines).
        - For the "**Поточний стан:**" section, render following non-empty lines
          as a literal block to preserve line breaks (indented, monospace).
        - Convert inline `code` → ``code``.
        """
        import re

        lines = markdown_text.split("\n")
        rst_lines: list[str] = []

        in_fenced_code = False
        fenced_code_lines: list[str] = []
        previous_was_bullet = False

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Handle fenced code blocks
            if stripped.startswith("```"):
                if not in_fenced_code:
                    in_fenced_code = True
                    fenced_code_lines = []
                else:
                    # close fenced block → RST literal block
                    in_fenced_code = False
                    rst_lines.append("")
                    rst_lines.append("::")
                    rst_lines.append("")
                    for cl in fenced_code_lines:
                        rst_lines.append("    " + cl)
                    rst_lines.append("")
                i += 1
                continue

            if in_fenced_code:
                fenced_code_lines.append(line)
                i += 1
                continue

            # Convert inline code
            line = re.sub(r"`([^`]+)`", r"``\1``", line)

            # Simple Markdown headings (# → bold)
            if line.startswith('# '):
                line = '**' + line[2:] + '**'
            elif line.startswith('## '):
                line = '**' + line[3:] + '**'
            elif line.startswith('### '):
                line = '**' + line[4:] + '**'

            # Handle "Поточний стан" / "Текущее состояние" as literal block for preserving newlines
            if stripped.startswith('**Поточний стан:**') or stripped.startswith('**Текущее состояние:**'):
                rst_lines.append(line)
                i += 1

                # Collect subsequent non-empty, non-heading lines
                var_lines: list[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    nxs = nxt.strip()
                    if nxs.startswith('**') or nxs.startswith('```') or nxs.startswith('# '):
                        break
                    if nxs != "":
                        var_lines.append(nxt.rstrip())
                    i += 1

                if var_lines:
                    rst_lines.append("")
                    rst_lines.append("::")
                    rst_lines.append("")
                    for vl in var_lines:
                        rst_lines.append("    " + vl)
                    rst_lines.append("")
                continue

            # List handling (bullet and numbered): ensure a blank line before first item
            # Numbered list: 1), 2), etc.
            # Bullet list: -, *, etc.
            is_list_item = (stripped.startswith('- ') or stripped.startswith('* ') or
                           re.match(r'^\d+\)', stripped))
            
            if is_list_item:
                if len(rst_lines) > 0 and rst_lines[-1].strip() != "" and not previous_was_bullet:
                    rst_lines.append("")
                
                # For numbered lists, RST needs format: "1. " not "1)"
                # But we keep the original format and just ensure proper spacing
                rst_lines.append(line)
                previous_was_bullet = True
                i += 1
                continue

            previous_was_bullet = False

            # Default: keep line as-is (RST will wrap normal paragraphs)
            rst_lines.append(line)
            i += 1

        return "\n".join(rst_lines)
    
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

    def _cancel_completion(self):
        if self._current_assistant is None:
            return

        if self._chat_completion_in_progress():
            self._active_chat_request_id = None
            self._append_text("... [cancelled]", source="chat")

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

    def submit_user_chat_message(self, message: str):
        self._remove_suggestions()
        message = message.rstrip()
        attachments, warnings = self.compile_attachments(message)
        self._prepare_new_completion()

        self._active_chat_request_id = str(uuid.uuid4())
        self._append_text("\n")
        self._append_text(message, tags=("user_message",))
        if attachments:
            self._formatted_attachmets_per_message[self._active_chat_request_id] = (
                self._current_assistant.format_attachments(attachments)
            )
            self._append_text(
                " 📎",
                tags=("attachments_link", f"att_{self._active_chat_request_id}", "user_message"),
            )
        self._append_text("\n", tags=("user_message",))

        self._append_text("\n")

        for warning in warnings:
            self._append_text("WARNING: " + warning + "\n\n")

        self._chat_messages.append(ChatMessage("user", message, attachments))
        self.query_text.delete("1.0", "end")

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
        names = re.findall(r"@(\w+)", message)
        if not names:
            return [self._current_assistant]

        unique_norm_names = list(set(map(lambda s: s.lower(), names)))
        result = []
        for name in unique_norm_names:
            if name in get_workbench().assistants:
                result.append(get_workbench().assistants[name])

            else:
                # TODO:
                self._append_text(f"No assistant named {name}")

        return result

    def _complete_chat_in_thread(self, assistant: Assistant, request_id: str):
        try:
            # TODO: pass editor contents from UI thread
            context = ChatContext(
                messages=self._chat_messages,
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

            get_workbench().queue_event(
                "AiChatResponseFragment",
                ChatResponseFragmentWithRequestId(
                    ChatResponseChunk(
                        content=f"INTERNAL ERROR: {e}. See frontend.log for more details.",
                        is_final=True,
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


def load_plugin():
    get_workbench().add_view(ChatView, tr("Chat"), "se", visible_by_default=False)
