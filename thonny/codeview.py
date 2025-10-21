# -*- coding: utf-8 -*-
import codecs
import io
import os
import re
import sys
import time
import tkinter as tk
from logging import getLogger
from tkinter import messagebox, ttk
from typing import Dict, Union  # @UnusedImport

from thonny import get_workbench, roughparse, tktextext, ui_utils
from thonny.common import TextRange
from thonny.languages import tr
from thonny.tktextext import EnhancedText
from thonny.ui_utils import EnhancedTextWithLogging, ask_string, compute_tab_stops

_syntax_options = {}  # type: Dict[str, Union[str, int]]
# BREAKPOINT_SYMBOL = "•" # Bullet
# BREAKPOINT_SYMBOL = "○" # White circle
BREAKPOINT_SYMBOL = "●"  # Black circle

OLD_MAC_LINEBREAK = re.compile("\r(?!\n)")
UNIX_LINEBREAK = re.compile("(?<!\r)\n")
WINDOWS_LINEBREAK = re.compile("\r\n")

NON_TEXT_CHARS = list(map(chr, range(32)))
NON_TEXT_CHARS.remove("\t")
NON_TEXT_CHARS.remove("\n")
NON_TEXT_CHARS.remove("\r")
NON_TEXT_CHARS.remove("\f")

logger = getLogger(__name__)


class SyntaxText(EnhancedText):
    def __init__(self, master, indent_width: int = 4, tab_width: int = 4, cnf={}, **kw):
        self.file_type = "python"
        self._syntax_options = {}
        super().__init__(
            master=master, indent_width=indent_width, tab_width=tab_width, cnf=cnf, **kw
        )
        get_workbench().bind("SyntaxThemeChanged", self._reload_syntax_options, True)
        self._reload_syntax_options()

    def set_syntax_options(self, syntax_options):
        # clear old options
        for tag_name in self._syntax_options:
            self.tag_reset(tag_name)

        background = syntax_options.get("TEXT", {}).get("background")

        # apply new options
        for tag_name in syntax_options:
            opts = syntax_options[tag_name]

            if tag_name == "string3":
                # Needs explicit background to override uniline tags
                opts["background"] = background

            if tag_name == "TEXT":
                self.configure(**opts)
            else:
                self.tag_configure(tag_name, **opts)

        self._syntax_options = syntax_options

        if "current_line" in syntax_options:
            self.tag_lower("current_line")

        self.tag_raise("sel")
        self.tag_lower("stdout")

    def _reload_theme_options(self, event=None):
        super()._reload_theme_options(event)
        self._reload_syntax_options(event)

    def _reload_syntax_options(self, event=None):
        global _syntax_options
        self.set_syntax_options(_syntax_options)

    def destroy(self):
        super().destroy()
        get_workbench().unbind("SyntaxThemeChanged", self._reload_syntax_options)

    def perform_return(self, event):
        if self.file_type == "python":
            return perform_python_return(self, event)
        else:
            return perform_simple_return(self, event)

    def perform_smart_backspace(self, event):
        if self.file_type == "python":
            return EnhancedText.perform_smart_backspace(self, event)
        else:
            self._log_keypress_for_undo(event)
            # let the default action work
            return

    def should_indent_with_tabs(self):
        return get_workbench().get_option("edit.indent_with_tabs")

    def set_file_type(self, file_type):
        self.file_type = file_type

    def is_python_text(self):
        return self.file_type == "python"

    def is_pythonlike_text(self):
        return self.file_type == "pythonlike"

    def update_tab_stops(self):
        tab_chars = get_workbench().get_option("edit.tab_width")
        font = tk.font.nametofont(self["font"])
        self.configure(tabs=tuple(compute_tab_stops(tab_chars, font)), tabstyle="wordprocessor")


class CodeViewText(EnhancedTextWithLogging, SyntaxText):
    """Provides opportunities for monkey-patching by plugins"""

    def __init__(self, master=None, cnf={}, **kw):
        indent_width = get_workbench().get_option("edit.indent_width")
        tab_width = get_workbench().get_option("edit.tab_width")
        super().__init__(
            master=master,
            indent_width=indent_width,
            tab_width=tab_width,
            tag_current_line=get_workbench().get_option("view.highlight_current_line"),
            cnf=cnf,
            **kw,
        )
        # Allow binding to events of all CodeView texts
        self.bindtags(self.bindtags() + ("CodeViewText",))
        tktextext.fixwordbreaks(tk._default_root)

    def on_secondary_click(self, event=None):
        super().on_secondary_click(event)
        self.mark_set("insert", "@%d,%d" % (event.x, event.y))

        menu = get_workbench().get_menu("edit")
        try:
            from thonny.plugins.debugger import get_current_debugger

            debugger = get_current_debugger()
            if debugger is not None:
                menu = debugger.get_editor_context_menu()
        except ImportError:
            pass

        menu.tk_popup(event.x_root, event.y_root)


class CodeView(tktextext.EnhancedTextFrame):
    def __init__(self, master, propose_remove_line_numbers=False, **text_frame_args):
        frame_args = text_frame_args.copy()
        if "text_class" not in frame_args:
            frame_args["text_class"] = CodeViewText

        super().__init__(
            master,
            undo=True,
            wrap=tk.NONE,
            horizontal_scrollbar_class=ui_utils.AutoScrollbar,
            vertical_scrollbar_rowspan=2,
            **frame_args,
        )

        # TODO: propose_remove_line_numbers on paste??

        assert self._first_line_number is not None

        get_workbench().bind("SyntaxThemeChanged", self._reload_theme_options, True)
        self._original_newlines = os.linesep
        self._reload_theme_options()
        self._start_toggle_breakpoint_index = None
        self._last_toggle_breakpoint_time = 0
        self._gutter.bind("<Button-1>", self._start_toggle_breakpoint, True)
        self._gutter.bind("<ButtonRelease-1>", self._consider_toggle_breakpoint, True)
        # self.text.tag_configure("breakpoint_line", background="pink")
        self._gutter.tag_configure("breakpoint", foreground="crimson")

        editor_font = tk.font.nametofont("EditorFont")
        spacer_font = editor_font.copy()
        spacer_font.configure(size=editor_font.cget("size") // 4)
        self._gutter.tag_configure("spacer", font=spacer_font)
        self._gutter.tag_configure("active", font="BoldEditorFont")
        self._gutter.tag_raise("spacer")
        
        # Create right info gutter
        self.create_right_gutter(width=3)
        self.set_right_gutter_visibility(True)
        
        # Configure clickable info buttons
        self._right_gutter.tag_configure("info_button", foreground="#0066cc")
        self._right_gutter.tag_bind("info_button", "<Button-1>", self._on_info_click)
        self._right_gutter.tag_bind("info_button", "<Enter>", lambda e: self._right_gutter.config(cursor="hand2"))
        self._right_gutter.tag_bind("info_button", "<Leave>", lambda e: self._right_gutter.config(cursor="arrow"))
        
        # Update right gutter when text changes
        self.text.bind("<<TextChange>>", self._update_right_gutter, True)
        self._update_right_gutter()

    def get_content(self, up_to_end=False):
        if not up_to_end:
            return self.text.get("1.0", "end-1c")  # -1c because Text always adds a newline itself
        else:
            return self.text.get("1.0", "end")

    def detect_encoding(self, data):
        enc = self.detect_encoding_without_check(data)
        try:
            codecs.lookup(enc)
            return enc
        except LookupError:
            messagebox.showerror(
                "Error", "Unknown encoding '%s'. Using utf-8 instead" % enc, master=self
            )
            return "utf-8"

    def detect_encoding_without_check(self, data):
        if self.text.is_python_text():
            import tokenize

            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            return encoding
        else:
            ENCODING_MARKER = re.compile(
                rb"(charset|coding)[\t ]*[=: ][\t ]*[\"\']?([a-z][0-9a-z-_ ]*[0-9a-z])[\"\'\n\r\t ]?",
                re.IGNORECASE,
            )

            for line in data[:1024].splitlines():
                match = ENCODING_MARKER.search(line)
                if match and len(match.group(2)) > 2:
                    return match.group(2).decode("ascii", errors="replace")

            return "UTF-8"

    def set_file_type(self, file_type):
        self.text.set_file_type(file_type)

    def get_content_as_bytes(self):
        content = self.get_content()

        for callback in get_workbench().iter_save_hooks():
            content = callback(self, content=content)

        # convert all linebreaks to original format
        content = OLD_MAC_LINEBREAK.sub(self._original_newlines, content)
        content = WINDOWS_LINEBREAK.sub(self._original_newlines, content)
        content = UNIX_LINEBREAK.sub(self._original_newlines, content)

        return content.encode(self.detect_encoding(content.encode("ascii", errors="replace")))

    def set_content_as_bytes(self, data, keep_undo=False):
        encoding = self.detect_encoding(data)
        logger.debug("Detected encoding %s", encoding)
        while True:
            try:
                chars = data.decode(encoding)
                if self.looks_like_text(chars):
                    self.set_content(chars, keep_undo)
                    return True
            except UnicodeDecodeError:
                pass

            encoding = ask_string(
                tr("Bad encoding"),
                tr("Could not read as %s text.\nYou could try another encoding") % encoding,
                initial_value=encoding,
                options=get_proposed_encodings(),
                master=self.winfo_toplevel(),
            )
            if not encoding:
                return False

    def looks_like_text(self, chars):
        if not chars:
            return True

        non_text_char_count = 0
        for ch in chars:
            if ch in NON_TEXT_CHARS:
                non_text_char_count += 1

        return non_text_char_count / len(chars) < 0.01

    def set_content(self, content, keep_undo=False):
        content, self._original_newlines = tweak_newlines(content)

        for callback in get_workbench().iter_load_hooks():
            content = callback(self, content=content)

        self.text.direct_delete("1.0", tk.END)
        self.text.direct_insert("1.0", content)

        if not keep_undo:
            self.text.edit_reset()

    def _start_toggle_breakpoint(self, event):
        self._start_toggle_breakpoint_index = "@%d,%d" % (event.x, event.y)

    def _consider_toggle_breakpoint(self, event):
        if time.time() - self._last_toggle_breakpoint_time < 0.3:
            # it was probably a double-click. Don't want to double-toggle in this case.
            return

        index = "@%d,%d" % (event.x, event.y)
        if index != self._start_toggle_breakpoint_index:
            # it was probably a drag
            return

        start_index = index + " linestart"
        end_index = index + " lineend"

        if self.text.tag_nextrange("breakpoint_line", start_index, end_index):
            self.text.tag_remove("breakpoint_line", start_index, end_index)
        else:
            line_content = self.text.get(start_index, end_index).strip()
            if line_content and line_content[0] != "#":
                self.text.tag_add("breakpoint_line", start_index, end_index)

        self.update_gutter(clean=True)
        self._last_toggle_breakpoint_time = time.time()

    def _clean_selection(self):
        self.text.tag_remove("sel", "1.0", "end")
        self._gutter.tag_remove("sel", "1.0", "end")

    def _text_changed(self, event):
        self.update_gutter(
            clean=self.text._last_event_changed_line_count
            and self.text.tag_ranges("breakpoint_line")
        )

    def compute_gutter_line(self, lineno, plain=False):
        if plain:
            yield str(lineno) + " ", ()
        else:
            visual_line_number = self._first_line_number + lineno - 1
            linestart = str(visual_line_number) + ".0"

            yield str(lineno), ()

            if self.text.tag_nextrange("breakpoint_line", linestart, linestart + " lineend"):
                yield BREAKPOINT_SYMBOL, ("breakpoint",)
            else:
                yield " ", ()

    def select_range(self, text_range):
        self.text.tag_remove("sel", "1.0", tk.END)

        if text_range:
            if isinstance(text_range, int):
                # it's line number
                start = str(text_range - self._first_line_number + 1) + ".0"
                end = str(text_range - self._first_line_number + 1) + ".end"
            elif isinstance(text_range, TextRange):
                start = "%s.%s" % (
                    text_range.lineno - self._first_line_number + 1,
                    text_range.col_offset,
                )
                end = "%s.%s" % (
                    text_range.end_lineno - self._first_line_number + 1,
                    text_range.end_col_offset,
                )
            else:
                assert isinstance(text_range, tuple)
                start, end = text_range

            self.text.tag_add("sel", start, end)
            if isinstance(text_range, int):
                self.text.mark_set("insert", end)
            self.text.see("%s -1 lines" % start)

    def get_breakpoint_line_numbers(self):
        result = set()
        for num_line in self._gutter.get("1.0", "end").splitlines():
            if BREAKPOINT_SYMBOL in num_line:
                result.add(int(num_line.replace(BREAKPOINT_SYMBOL, "")))
        return result

    def get_selected_range(self):
        if self.text.has_selection():
            lineno, col_offset = map(int, self.text.index(tk.SEL_FIRST).split("."))
            end_lineno, end_col_offset = map(int, self.text.index(tk.SEL_LAST).split("."))
        else:
            lineno, col_offset = map(int, self.text.index(tk.INSERT).split("."))
            end_lineno, end_col_offset = lineno, col_offset

        return TextRange(lineno, col_offset, end_lineno, end_col_offset)

    def destroy(self):
        super().destroy()
        get_workbench().unbind("SyntaxThemeChanged", self._reload_theme_options)

    def _reload_gutter_theme_options(self, event=None):
        # super()._reload_gutter_theme_options(event)
        if "GUTTER" in _syntax_options:
            opts = _syntax_options["GUTTER"].copy()
            if "background" in opts and "selectbackground" not in opts:
                opts["selectbackground"] = opts["background"]
                opts["inactiveselectbackground"] = opts["background"]
            if "foreground" in opts and "selectforeground" not in opts:
                opts["selectforeground"] = opts["foreground"]

            self._gutter.configure(opts)

            if "background" in opts:
                background = opts["background"]
                self._margin_line.configure(background=background)
                self._gutter.tag_configure("sel", background=background)

        if "breakpoint" in _syntax_options:
            self._gutter.tag_configure("breakpoint", _syntax_options["breakpoint"])
    
    def _update_right_gutter(self, event=None):
        """Update right info gutter with ℹ buttons for each line"""
        if not self._right_gutter:
            return
        
        # Count lines in editor
        line_count = int(self.text.index("end-1c").split(".")[0])
        
        # Update gutter content
        self._right_gutter.config(state="normal")
        self._right_gutter.delete("1.0", "end")
        
        for line_num in range(1, line_count + 1):
            # Add info button with line number tag
            self._right_gutter.insert("end", " ℹ\n", ("info_button", f"line_{line_num}"))
        
        self._right_gutter.config(state="disabled")
    
    def _on_info_click(self, event):
        """Handle click on info button - show line explanation popup"""
        # Get which line was clicked
        index = self._right_gutter.index(f"@{event.x},{event.y}")
        line_num = int(index.split(".")[0])
        
        # Get the line content
        line_content = self.text.get(f"{line_num}.0", f"{line_num}.end")
        
        # Skip empty lines
        if not line_content.strip():
            return
        
        # Show explanation popup
        self._show_line_explanation_popup(line_num, line_content)
    
    def _show_line_explanation_popup(self, line_num, line_content):
        """Show popup with AI explanation of the code line"""
        from tkinter import messagebox
        import threading
        from thonny import rst_utils
        
        # Create popup dialog
        popup = tk.Toplevel(self)
        popup.title(f"Рядок {line_num}: Пояснення")
        popup.geometry("600x400")
        popup.transient(self.winfo_toplevel())
        
        # Add RstText widget for beautiful formatting (like in chat)
        text_frame = tk.Frame(popup)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Use RstText for markdown/rst formatting
        explanation_text = rst_utils.RstText(
            text_frame, 
            wrap=tk.WORD, 
            font="TkDefaultFont",
            read_only=True,  # Read-only but allows selection and copying
            background="white"
        )
        explanation_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, command=explanation_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        explanation_text.config(yscrollcommand=scrollbar.set)
        
        # Show loading message
        loading_msg = f"**Рядок коду:**\n\n::\n\n    {line_content}\n\n⏳ *Запитую AI для пояснення...*\n"
        explanation_text.append_rst(loading_msg)
        
        # Close button
        close_btn = ttk.Button(popup, text="Закрити", command=popup.destroy)
        close_btn.pack(pady=(0, 10))
        
        # Get AI explanation in thread
        def get_explanation():
            try:
                explanation = self._request_line_explanation(line_num, line_content)
                
                # Update UI in main thread
                def update_ui():
                    # Clear and show formatted explanation
                    explanation_text.direct_delete("1.0", "end")
                    
                    # Format as RST
                    rst_content = f"**Рядок коду:**\n\n::\n\n    {line_content}\n\n"
                    rst_content += "**Пояснення:**\n\n"
                    
                    # Convert markdown response to RST for rendering
                    # The AI response is in markdown, convert to RST
                    explanation_rst = explanation.replace("```python", "::\n\n").replace("```", "")
                    
                    # Convert bullet lists: markdown uses "- " or "* ", RST uses "* "
                    # Also need blank line before list
                    lines = explanation_rst.split('\n')
                    converted_lines = []
                    in_list = False
                    for i, line in enumerate(lines):
                        stripped = line.lstrip()
                        # Check if this is a bullet point
                        if stripped.startswith('- ') or stripped.startswith('* '):
                            if not in_list:
                                # Add blank line before list starts
                                if converted_lines and converted_lines[-1].strip():
                                    converted_lines.append('')
                                in_list = True
                            # Convert to RST bullet (always use *)
                            indent = len(line) - len(stripped)
                            converted_lines.append(' ' * indent + '* ' + stripped[2:])
                        else:
                            if in_list and stripped:
                                # List ended
                                in_list = False
                            converted_lines.append(line)
                    
                    explanation_rst = '\n'.join(converted_lines)
                    rst_content += explanation_rst
                    
                    explanation_text.append_rst(rst_content)
                
                popup.after(0, update_ui)
            except Exception as e:
                def show_error():
                    explanation_text.direct_delete("1.0", "end")
                    explanation_text.append_rst(f"**Помилка:** {str(e)}")
                popup.after(0, show_error)
        
        threading.Thread(target=get_explanation, daemon=True).start()
    
    def _request_line_explanation(self, line_num, line_content):
        """Request AI explanation for a line of code with full context"""
        from thonny import get_workbench
        from thonny.assistance import ChatRole
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get current AI model choice
        try:
            model = get_workbench().get_option("ai.model", "gpt")
        except:
            model = "gpt"
        
        # Get base assistant (not debug version)
        assistants = get_workbench().assistants
        if model == "gpt":
            assistant = assistants.get("OpenAI") or assistants.get("openai")
        else:
            assistant = assistants.get("Gemini") or assistants.get("gemini")
        
        if not assistant:
            return "AI ассистент недоступен. Проверьте настройки API ключа."
        
        if not assistant.get_ready():
            return "AI ассистент не готов. Проверьте API ключ в Tools → Manage plug-ins."
        
        # Get language preference
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except:
            lang = "uk"
        
        # Get full program code for context
        full_code = self.get_content()
        
        # Check if we're in debug mode and get variables
        debug_vars = None
        try:
            from thonny.plugins.debugger import get_current_debugger
            debugger = get_current_debugger()
            if debugger and debugger._last_progress_message:
                msg = debugger._last_progress_message
                if msg.stack:
                    frame = msg.stack[-1]
                    # Combine globals and locals
                    all_vars = {}
                    if frame.globals:
                        all_vars.update(frame.globals)
                    if frame.locals:
                        all_vars.update(frame.locals)
                    # Filter out internal variables
                    debug_vars = {k: v for k, v in all_vars.items() if not k.startswith('__')}
        except:
            pass
        
        # Create system prompt
        if lang == "ru":
            system_prompt = """Ты — помощник для детей. Объясни строку кода КРАТКО и ПРОСТО.

Формат (максимум 5-6 предложений):
1. **Что делает:** одна фраза общего смысла
2. **Как работает:** 2-3 коротких пункта о порядке выполнения
3. **Пример:** один простой пример

ПРАВИЛА:
- Пиши КОРОТКО для детей 10-12 лет
- БЕЗ сложных терминов (индекс → номер, оператор → команда)
- НЕ используй местоимения (он, его, этот и т.д.) - ВСЕГДА показывай код в обратных кавычках
- Будь конкретным - указывай что именно получается
- Последний пункт "Как работает" начинай с "Таким образом..."
- Пиши на РУССКОМ языке

Пример ХОРОШЕГО формата для mas1=[mas[0]]:
**Как работает:**
- `mas[0]` берет первое число из списка mas
- `[mas[0]]` создает новый список из этого числа (например, из 10 делает [10])
- Таким образом mas1 получает список с одним элементом - первым числом из mas

Пример ХОРОШЕГО для input().split():
**Как работает:**
- `input()` читает введенную строку (например, "5 10 15")
- `.split()` делит строку на список строк по пробелам (получается ["5", "10", "15"])
- `map(int, ...)` превращает каждую строку "5", "10", "15" в числа 5, 10, 15
- Таким образом получается список чисел [5, 10, 15]

ВАЖНО - ВСЕГДА:
- Указывай ЧТО получается и КАКОГО ТИПА (строка, число, список строк, список чисел)
- Показывай примеры промежуточных результатов в скобках
- НЕ используй "такой", "такую часть", "это" - пиши конкретно что именно"""
        else:  # uk
            system_prompt = """Ти — помічник для дітей. Поясни рядок коду КОРОТКО і ПРОСТО.

Формат (максимум 5-6 речень):
1. **Що робить:** одна фраза загального змісту
2. **Як працює:** 2-3 короткі пункти про порядок виконання
3. **Приклад:** один простий приклад

ПРАВИЛА:
- Пиши КОРОТКО для дітей 10-12 років
- БЕЗ складних термінів (індекс → номер, оператор → команда)
- НЕ використовуй займенники (він, його, цей тощо) - ЗАВЖДИ показуй код у зворотних лапках
- Будь конкретним - вказуй що саме виходить
- Останній пункт "Як працює" починай з "Таким чином..."
- Пиши УКРАЇНСЬКОЮ мовою

Приклад ХОРОШОГО формату для mas1=[mas[0]]:
**Як працює:**
- `mas[0]` бере перше число зі списку mas
- `[mas[0]]` створює новий список з цього числа (наприклад, з 10 робить [10])
- Таким чином mas1 отримує список з одним елементом - першим числом зі списку mas

Приклад ХОРОШОГО для input().split():
**Як працює:**
- `input()` читає введений рядок (наприклад, "5 10 15")
- `.split()` ділить рядок на список рядків за пробілами (виходить ["5", "10", "15"])
- `map(int, ...)` перетворює кожен рядок "5", "10", "15" на числа 5, 10, 15
- Таким чином виходить список чисел [5, 10, 15]

ВАЖЛИВО - ЗАВЖДИ:
- Вказуй ЩО виходить і ЯКОГО ТИПУ (рядок, число, список рядків, список чисел)
- Показуй приклади проміжних результатів у дужках
- НЕ використовуй "такий", "таку частину", "це" - пиши конкретно що саме"""
        
        # Log system prompt
        logger.info("=" * 80)
        logger.info("SYSTEM PROMPT для пояснення рядка:")
        logger.info("-" * 80)
        logger.info(system_prompt)
        logger.info("=" * 80)
        
        # Create user prompt with full context
        if lang == "ru":
            user_prompt = f"""**Полная программа:**
```python
{full_code}
```

**Строка для разбора: {line_num}**
```python
{line_content}
```
"""
            if debug_vars:
                user_prompt += f"\n**Текущие переменные (во время отладки):**\n"
                for var_name, var_info in debug_vars.items():
                    var_repr = var_info.repr if hasattr(var_info, 'repr') else str(var_info)
                    user_prompt += f"  {var_name} = {var_repr}\n"
                user_prompt += "\n"
            
            user_prompt += f"Объясни подробно строку {line_num} используя контекст всей программы."
        else:  # uk
            user_prompt = f"""**Повна програма:**
```python
{full_code}
```

**Рядок для розбору: {line_num}**
```python
{line_content}
```
"""
            if debug_vars:
                user_prompt += f"\n**Поточні змінні (під час налагодження):**\n"
                for var_name, var_info in debug_vars.items():
                    var_repr = var_info.repr if hasattr(var_info, 'repr') else str(var_info)
                    user_prompt += f"  {var_name} = {var_repr}\n"
                user_prompt += "\n"
            
            user_prompt += f"Поясни детально рядок {line_num} використовуючи контекст всієї програми."
        
        # Log user prompt
        logger.info("USER PROMPT для пояснення рядка:")
        logger.info("-" * 80)
        logger.info(user_prompt)
        logger.info("=" * 80)
        
        # Make direct API call with custom system prompt
        response_parts = []
        try:
            if model == "gpt":
                # Direct OpenAI API call
                import openai
                from thonny.plugins.openai import API_KEY_SECRET_KEY as OPENAI_KEY
                
                api_key = get_workbench().get_secret(OPENAI_KEY, None)
                if not api_key:
                    return "API ключ OpenAI не настроен"
                
                client = openai.OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    stream=True
                )
                
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        response_parts.append(chunk.choices[0].delta.content)
            else:  # gemini
                # Direct Gemini API call
                import google.generativeai as genai
                from thonny.plugins.gemini import API_KEY_SECRET_KEY as GEMINI_KEY
                
                api_key = get_workbench().get_secret(GEMINI_KEY, None)
                if not api_key:
                    return "API ключ Gemini не настроен"
                
                genai.configure(api_key=api_key)
                model_obj = genai.GenerativeModel('gemini-2.5-flash')
                
                # Combine system prompt and user prompt for Gemini
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                response = model_obj.generate_content(full_prompt, stream=True)
                
                for chunk in response:
                    if chunk.text:
                        response_parts.append(chunk.text)
        except Exception as e:
            logger.exception("Ошибка при запросе объяснения строки")
            return f"Помилка при запиті до AI: {str(e)}"
        
        result = "".join(response_parts) if response_parts else "Немає відповіді від AI"
        
        # Log response
        logger.info("AI RESPONSE для пояснення рядка:")
        logger.info("-" * 80)
        logger.info(result)
        logger.info("=" * 80)
        
        return result


def set_syntax_options(syntax_options):
    global _syntax_options
    _syntax_options = syntax_options
    get_workbench().event_generate("SyntaxThemeChanged")


def get_syntax_options_for_tag(tag, **base_options):
    global _syntax_options
    if tag in _syntax_options:
        base_options.update(_syntax_options[tag])
    return base_options


def tweak_newlines(content):
    cr_count = len(OLD_MAC_LINEBREAK.findall(content))
    lf_count = len(UNIX_LINEBREAK.findall(content))
    crlf_count = len(WINDOWS_LINEBREAK.findall(content))

    if cr_count > 0 and lf_count == 0 and crlf_count == 0:
        original_newlines = "\r"
    elif crlf_count > 0 and lf_count == 0 and cr_count == 0:
        original_newlines = "\r\n"
    elif lf_count > 0 and crlf_count == 0 and cr_count == 0:
        original_newlines = "\n"
    else:
        original_newlines = os.linesep

    content = OLD_MAC_LINEBREAK.sub("\n", content)
    content = WINDOWS_LINEBREAK.sub("\n", content)

    return content, original_newlines


def perform_python_return(text: EnhancedText, event):
    # copied from idlelib.EditorWindow (Python 3.4.2)
    # slightly modified
    # pylint: disable=lost-exception

    assert text is event.widget
    assert isinstance(text, EnhancedText)

    try:
        # delete selection
        first, last = text.get_selection_indices()
        if first and last:
            text.delete(first, last)
            text.mark_set("insert", first)

        # Strip whitespace after insert point
        # (ie. don't carry whitespace from the right of the cursor over to the new line)
        while text.get("insert") in [" ", "\t"]:
            text.delete("insert")

        left_part = text.get("insert linestart", "insert")
        # locate first non-white character
        i = 0
        n = len(left_part)
        while i < n and left_part[i] in " \t":
            i = i + 1

        # is it only whitespace?
        if i == n:
            # start the new line with the same whitespace
            text.insert("insert", "\n" + left_part)
            return "break"

        # Turned out the left part contains visible chars
        # Remember the indent
        indent = left_part[:i]

        # Strip whitespace before insert point
        # (ie. after inserting the linebreak this line doesn't have trailing whitespace)
        while text.get("insert-1c", "insert") in [" ", "\t"]:
            text.delete("insert-1c", "insert")

        # start new line
        text.insert("insert", "\n")

        # adjust indentation for continuations and block
        # open/close first need to find the last stmt
        lno = tktextext.index2line(text.index("insert"))
        y = roughparse.RoughParser(text.indent_width, text.tab_width)

        for context in roughparse.NUM_CONTEXT_LINES:
            startat = max(lno - context, 1)
            startatindex = repr(startat) + ".0"
            rawtext = text.get(startatindex, "insert")
            y.set_str(rawtext)
            bod = y.find_good_parse_start(
                False, roughparse._build_char_in_string_func(startatindex)
            )
            if bod is not None or startat == 1:
                break
        y.set_lo(bod or 0)

        c = y.get_continuation_type()
        if c != roughparse.C_NONE:
            # The current stmt hasn't ended yet.
            if c == roughparse.C_STRING_FIRST_LINE:
                # after the first line of a string; do not indent at all
                pass
            elif c == roughparse.C_STRING_NEXT_LINES:
                # inside a string which started before this line;
                # just mimic the current indent
                text.insert("insert", indent)
            elif c == roughparse.C_BRACKET:
                # line up with the first (if any) element of the
                # last open bracket structure; else indent one
                # level beyond the indent of the line with the
                # last open bracket
                text._reindent_to(y.compute_bracket_indent())
            elif c == roughparse.C_BACKSLASH:
                # if more than one line in this stmt already, just
                # mimic the current indent; else if initial line
                # has a start on an assignment stmt, indent to
                # beyond leftmost =; else to beyond first chunk of
                # non-whitespace on initial line
                if y.get_num_lines_in_stmt() > 1:
                    text.insert("insert", indent)
                else:
                    text._reindent_to(y.compute_backslash_indent())
            else:
                assert 0, "bogus continuation type %r" % (c,)
            return "break"

        # This line starts a brand new stmt; indent relative to
        # indentation of initial line of closest preceding
        # interesting stmt.
        indent = y.get_base_indent_string()
        text.insert("insert", indent)
        if y.is_block_opener():
            text.perform_smart_tab(event)
        elif indent and y.is_block_closer():
            text.perform_smart_backspace(event)
        return "break"
    finally:
        text.see("insert")
        text.event_generate("<<NewLine>>")


def perform_simple_return(text: EnhancedText, event):
    assert text is event.widget
    assert isinstance(text, EnhancedText)

    text._log_keypress_for_undo(event)

    try:
        # delete selection
        first, last = text.get_selection_indices()
        if first and last:
            text.delete(first, last)
            text.mark_set("insert", first)

        # Strip whitespace after insert point
        # (ie. don't carry whitespace from the right of the cursor over to the new line)
        while text.get("insert") in [" ", "\t"]:
            text.delete("insert")

        left_part = text.get("insert linestart", "insert")
        # locate first non-white character
        i = 0
        n = len(left_part)
        while i < n and left_part[i] in " \t":
            i = i + 1

        # start the new line with the same whitespace
        text.insert("insert", "\n" + left_part[:i])
        return "break"

    finally:
        text.see("insert")
        text.event_generate("<<NewLine>>")


class BinaryFileException(RuntimeError):
    pass


def get_proposed_encodings():
    # https://w3techs.com/technologies/overview/character_encoding
    result = [
        "UTF-8",
        "ISO-8859-1",
        "Windows-1251",
        "Windows-1252",
        "GB2312",
        "Shift JIS",
        "GBK",
        "EUC-KR",
        "ISO-8859-9",
        "Windows-1254",
        "EUC-JP",
        "Big5",
        "ISO-8859-2  ",
        "Windows-1250",
        "Windows-874",
        "Windows-1256",
        "ISO-8859-15",
        "US-ASCII",
        "Windows-1255",
        "TIS-620",
        "ISO-8859-7",
        "Windows-1253",
        "UTF-16",
        "KOI8-R",
        "GB18030",
        "Windows-1257",
        "KS C 5601",
        "UTF-7",
        "ISO-8859-8",
        "Windows-31J",
        "ISO-8859-5",
        "ISO-8859-6",
        "ISO-8859-4",
        "ANSI_X3.110-1983",
        "ISO-8859-3",
        "KOI8-U",
        "Big5 HKSCS",
        "ISO-2022-JP",
        "Windows-1258",
        "ISO-8859-13",
        "ISO-8859-14",
        "Windows-949",
        "ISO-8859-10",
        "ISO-8859-11",
        "ISO-8859-16",
    ]

    sys_enc = sys.getdefaultencoding()
    for item in result[:]:
        if item.lower() == sys_enc.lower():
            result.remove(item)
            sys_enc = item

    result.insert(0, sys_enc)
    return result
