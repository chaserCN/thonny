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

        # Get base menu
        menu = get_workbench().get_menu("edit")
        
        # Check for debugger menu
        try:
            from thonny.plugins.debugger import get_current_debugger
            debugger = get_current_debugger()
            if debugger is not None:
                menu = debugger.get_editor_context_menu()
        except ImportError:
            pass
        
        # Clone menu to avoid modifying original
        popup_menu = tk.Menu(self, tearoff=False)
        
        # Add "Explain Selection" at the TOP
        popup_menu.add_command(
            label=tr("Explain Selection..."),
            command=lambda: self.explain_token_under_cursor()
        )
        
        # Add code snippets at the TOP
        try:
            from thonny.plugins import code_snippets
            code_snippets._populate_editor_menu(popup_menu)
        except (ImportError, AttributeError):
            pass
        
        # Add separator before standard items
        popup_menu.add_separator()
        
        # Copy all items from original menu
        for i in range(menu.index("end") + 1):
            try:
                item_type = menu.type(i)
                if item_type == "separator":
                    popup_menu.add_separator()
                elif item_type == "command":
                    popup_menu.add_command(
                        label=menu.entrycget(i, "label"),
                        command=menu.entrycget(i, "command"),
                        accelerator=menu.entrycget(i, "accelerator") if menu.entrycget(i, "accelerator") else None
                    )
                elif item_type == "cascade":
                    popup_menu.add_cascade(
                        label=menu.entrycget(i, "label"),
                        menu=menu.nametowidget(menu.entrycget(i, "menu"))
                    )
            except:
                pass

        popup_menu.tk_popup(event.x_root, event.y_root)
    
    def explain_token_under_cursor(self):
        """Explain the token/construct under cursor or selected text using AI"""
        # Check if there's a selection
        try:
            sel_start = self.index("sel.first")
            sel_end = self.index("sel.last")
            # If we got here, there's a selection
            self._explain_selection(sel_start, sel_end)
            return
        except:
            # No selection, continue with token under cursor
            pass
        
        # Get cursor position
        cursor_index = self.index("insert")
        line_num = int(cursor_index.split(".")[0])
        col_num = int(cursor_index.split(".")[1])
        
        # Get the line content
        line_start = f"{line_num}.0"
        line_end = f"{line_num}.end"
        line_content = self.get(line_start, line_end)
        
        # Determine what's under cursor
        token_info = self._get_token_under_cursor(line_content, col_num)
        
        if not token_info:
            messagebox.showinfo(
                tr("Explain under cursor"),
                tr("Could not identify token under cursor")
            )
            return
        
        # Show explanation popup
        self._show_token_explanation_popup(line_num, line_content, token_info)
    
    def _explain_selection(self, sel_start, sel_end):
        """Explain selected code fragment using AI"""
        import re
        
        # Get selected text
        selected_text = self.get(sel_start, sel_end)
        
        # Expand to word boundaries if selection is partial
        # Check if start is in the middle of a word
        start_line, start_col = map(int, sel_start.split('.'))
        line_start_text = self.get(f"{start_line}.0", sel_start)
        if line_start_text and re.match(r'.*[a-zA-Z0-9_]$', line_start_text):
            # Expand left to word boundary
            while start_col > 0:
                char_before = self.get(f"{start_line}.{start_col-1}", f"{start_line}.{start_col}")
                if not (char_before.isalnum() or char_before == '_'):
                    break
                start_col -= 1
            sel_start = f"{start_line}.{start_col}"
        
        # Check if end is in the middle of a word
        end_line, end_col = map(int, sel_end.split('.'))
        char_at_end = self.get(sel_end, f"{end_line}.{end_col+1}")
        if char_at_end and (char_at_end.isalnum() or char_at_end == '_'):
            # Expand right to word boundary
            line_end_pos = self.index(f"{end_line}.end")
            line_end_col = int(line_end_pos.split('.')[1])
            while end_col < line_end_col:
                char = self.get(f"{end_line}.{end_col}", f"{end_line}.{end_col+1}")
                if not (char.isalnum() or char == '_'):
                    break
                end_col += 1
            sel_end = f"{end_line}.{end_col}"
        
        # Get the expanded selection
        selected_text = self.get(sel_start, sel_end)
        
        if not selected_text.strip():
            from tkinter import messagebox
            messagebox.showinfo(
                tr("Explain selection"),
                tr("Selection is empty")
            )
            return
        
        # Extract final line numbers after expansion
        final_start_line = int(sel_start.split('.')[0])
        final_end_line = int(sel_end.split('.')[0])
        
        # Show explanation popup for selected code
        self._show_selection_explanation_popup(selected_text, final_start_line, final_end_line)
    
    def _get_token_under_cursor(self, line_content, col_num):
        """Identify the token or construct under cursor
        
        Returns dict with 'token' (the actual token text) and 'type' (function, operator, etc.)
        """
        import re
        import keyword
        
        if col_num >= len(line_content):
            col_num = len(line_content) - 1
        
        if col_num < 0 or not line_content.strip():
            return None
        
        # Check for operators and special characters
        char_at_cursor = line_content[col_num] if col_num < len(line_content) else ''
        
        # Check for bracket operators - but look for the content type
        if char_at_cursor == '[':
            return {'token': '[]', 'type': 'operator', 'description': 'indexing/slicing operator'}
        elif char_at_cursor == ']':
            # Find matching opening bracket
            return {'token': '[]', 'type': 'operator', 'description': 'indexing/slicing operator'}
        elif char_at_cursor in '()':
            # Check if it's a method call (preceded by .method)
            before_cursor = line_content[:col_num]
            method_match = re.search(r'\.(\w+)\s*$', before_cursor)
            if method_match:
                method_name = method_match.group(1)
                return {'token': method_name + '()', 'type': 'method', 'description': 'method call'}
            
            # Check if it's a function call (preceded by function name)
            func_match = re.search(r'(\w+)\s*$', before_cursor)
            if func_match:
                func_name = func_match.group(1)
                return {'token': func_name + '()', 'type': 'function', 'description': 'function call'}
            return {'token': '()', 'type': 'operator', 'description': 'parentheses'}
        elif char_at_cursor in '{}':
            return {'token': '{}', 'type': 'operator', 'description': 'dictionary/set literal'}
        elif char_at_cursor == ':':
            return {'token': ':', 'type': 'operator', 'description': 'colon (slice or dict)'}
        elif char_at_cursor == '.':
            # Method call - get the method name after dot
            after_cursor = line_content[col_num+1:]
            method_match = re.match(r'(\w+)', after_cursor)
            if method_match:
                method_name = method_match.group(1)
                # Check if followed by (
                rest_after_method = line_content[col_num+1+len(method_name):].lstrip()
                if rest_after_method.startswith('('):
                    return {'token': method_name + '()', 'type': 'method', 'description': 'method call'}
                return {'token': method_name, 'type': 'method', 'description': 'method'}
            return {'token': '.', 'type': 'operator', 'description': 'dot operator'}
        
        # Find word boundaries around cursor
        # Expand left
        start = col_num
        while start > 0 and (line_content[start-1].isalnum() or line_content[start-1] in '_'):
            start -= 1
        
        # Expand right
        end = col_num
        while end < len(line_content) and (line_content[end].isalnum() or line_content[end] in '_'):
            end += 1
        
        if start == end:
            return None
        
        token = line_content[start:end]
        
        if not token:
            return None
        
        # Check if followed by parentheses (function/method call)
        rest_of_line = line_content[end:].lstrip()
        if rest_of_line.startswith('('):
            # Check if it's a method (preceded by .)
            before_token = line_content[:start]
            if before_token.rstrip().endswith('.'):
                return {'token': token + '()', 'type': 'method', 'description': 'method call'}
            return {'token': token + '()', 'type': 'function', 'description': 'function or method call'}
        
        # Check if it's a keyword
        if keyword.iskeyword(token):
            return {'token': token, 'type': 'keyword', 'description': 'Python keyword'}
        
        # Check if it's a built-in function
        if token in dir(__builtins__):
            return {'token': token, 'type': 'builtin', 'description': 'built-in function or type'}
        
        # Otherwise it's likely a variable
        return {'token': token, 'type': 'variable', 'description': 'variable or identifier'}
    
    def _show_token_explanation_popup(self, line_num, line_content, token_info):
        """Show popup with AI explanation of the token/construct"""
        from thonny.plugins.base_assistant import get_ai_assistant
        from thonny.codeview_popup_utils import get_localization, create_explanation_popup
        
        assistant = get_ai_assistant()
        if not assistant:
            return
        
        loc = get_localization("token")
        
        create_explanation_popup(
            parent=self,
            title=loc["title"].format(token=token_info['token']),
            width=600,
            height=520,
            loading_markdown=(
                f"**{loc['token_label']}** `{token_info['token']}`\n\n"
                f"{loc['loading']}\n"
            ),
            request_func=lambda: self._request_token_explanation(
                assistant, line_num, line_content, token_info
            ),
            format_result_func=lambda expl: expl,  # Just the explanation, no duplication
            error_label=loc["error_label"],
            position_mode="center",
        )
    
    def _show_selection_explanation_popup(self, selected_code, start_line, end_line):
        """Show popup with AI explanation of selected code fragment"""
        from thonny.plugins.base_assistant import get_ai_assistant
        from thonny.codeview_popup_utils import get_localization, create_explanation_popup
        
        assistant = get_ai_assistant()
        if not assistant:
            return
        
        loc = get_localization("selection")
        
        # Format selected code for display
        code_display = selected_code if len(selected_code) <= 500 else selected_code[:500] + "\n..."
        
        create_explanation_popup(
            parent=self,
            title=loc["title"],
            width=700,
            height=600,
            loading_markdown=(
                f"**{loc['code_label']}**\n\n```python\n{code_display}\n```\n\n"
                f"{loc['loading']}\n"
            ),
            request_func=lambda: self._request_selection_explanation(
                assistant, selected_code, start_line, end_line
            ),
            format_result_func=lambda expl: expl,  # Already formatted by request
            error_label=loc["error_label"],
            position_mode="center",
        )
    
    def _request_token_explanation(self, assistant, line_num, line_content, token_info):
        """Request AI explanation for a token with full program context
        
        Note: assistant.get_ready() must be called BEFORE this method in the main thread!
        """
        from thonny.assistance import TokenContext
        from thonny.codeview_popup_utils import get_program_context
        
        # Get program context (debug if available, or formatted code)
        program_context = get_program_context(self)
        
        # Create context with token info and program context
        context = TokenContext(
            line_num=line_num,
            line_content=line_content,
            token=token_info['token'],
            token_type=token_info['type'],
            token_description=token_info.get('description', token_info['type']),
            program_context=program_context
        )
        
        # Call assistant's explain_token method (all AI logic is there)
        return assistant.explain_token(context)
    
    def _request_selection_explanation(self, assistant, selected_code, start_line, end_line):
        """Request AI explanation for selected code fragment
        
        Note: assistant.get_ready() must be called BEFORE this method in the main thread!
        """
        from thonny.assistance import SelectionContext
        from thonny.codeview_popup_utils import get_program_context
        
        # Get program context (debug if available, or formatted code)
        program_context = get_program_context(self)
        
        # Create context with selected code and program context
        context = SelectionContext(
            selected_code=selected_code,
            start_line=start_line,
            end_line=end_line,
            program_context=program_context
        )
        
        # Call assistant's explain_selection method (all AI logic is there)
        return assistant.explain_selection(context)


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
        
        # Configure info button in gutter 
        self._gutter.tag_configure("info_button", foreground="#0066cc")
        self._gutter.tag_bind("info_button", "<Button-1>", self._on_info_click)
        self._gutter.tag_bind("info_button", "<Enter>", lambda e: self._gutter.config(cursor="hand2"))
        self._gutter.tag_bind("info_button", "<Leave>", lambda e: self._gutter.config(cursor="arrow"))
        
        # Hide/show info buttons on screenshot events
        self._gutter.bind("<<BeforeScreenshot>>", self._hide_info_buttons, True)
        self._gutter.bind("<<AfterScreenshot>>", self._show_info_buttons, True)
        self._info_buttons_hidden = False
        
        # Hide right info gutter (not needed anymore)
        self.create_right_gutter(width=3)
        self.set_right_gutter_visibility(False)
        
        # Ensure gutter is updated after initialization
        self.after_idle(lambda: self.update_gutter(clean=True))

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
        
        # Force gutter update to ensure all lines get info buttons
        self.update_gutter(clean=True)

    def _start_toggle_breakpoint(self, event):
        # Check if click is on info button
        click_index = self._gutter.index(f"@{event.x},{event.y}")
        tags_at_click = self._gutter.tag_names(click_index)
        if "info_button" in tags_at_click:
            return
        
        self._start_toggle_breakpoint_index = "@%d,%d" % (event.x, event.y)

    def _consider_toggle_breakpoint(self, event):
        # Check if click is on info button
        click_index = self._gutter.index(f"@{event.x},{event.y}")
        tags_at_click = self._gutter.tag_names(click_index)
        if "info_button" in tags_at_click:
            return
        
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
        
        # Generate event for plugins that need to react to breakpoint changes
        self.text.event_generate("<<BreakpointChange>>")

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

            # breakpoint на строке?
            bp_present = bool(self.text.tag_nextrange("breakpoint_line", linestart, linestart + " lineend"))
            bp = BREAKPOINT_SYMBOL if bp_present else " "

            left = "𝓲"
            left_tag = ("info_button",)

            # номер строки
            num = str(lineno)

            # ширина гаттера и вычисление паддинга
            gutter_width = int(self._gutter["width"]) if "width" in self._gutter.keys() else 5
            pad_len = gutter_width - len(left) - len(num) - len(bp)
            if pad_len < 1:
                pad_len = 1
            pad = " " * pad_len

            # отрисовка элементов
            yield left, left_tag              # "i" (тёмный или бледный)
            yield pad + num, ()               # номер строки
            if bp_present:
                yield bp, ("breakpoint",)
            else:
                yield bp, ()

    def compute_gutter_line2(self, lineno, plain=False):
        if plain:
            yield str(lineno) + " ", ()
        else:
            visual_line_number = self._first_line_number + lineno - 1
            linestart = str(visual_line_number) + ".0"

            # параметры разметки
            gutter_width = int(self._gutter["width"]) if "width" in self._gutter.keys() else 5
            bp_present = bool(self.text.tag_nextrange("breakpoint_line", linestart, linestart + " lineend"))
            bp = BREAKPOINT_SYMBOL if bp_present else " "

            left = "ⓘ"                       # левый индикатор
            num = str(lineno)                # номер строки

            # сколько пробелов надо, чтобы num «прилип» к правому краю (перед bp)
            pad_len = gutter_width - len(left) - len(num) - len(bp)
            if pad_len < 1:
                pad_len = 1
            pad = " " * pad_len

            # рисуем по сегментам: кликабельная "i", затем пробелы+номер, затем брейкпоинт/пусто
            yield left, ("info_button",)                 # остаётся у левого края
            yield pad + num, ()                          # номер выровнен вправо "жёстко"
            if bp_present:
                yield bp, ("breakpoint",)               # кликабельный символ брейкпоинта
            else:
                yield bp, ()

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

            # дублируем фон и цвет для выделенного состояния
            if "background" in opts and "selectbackground" not in opts:
                opts["selectbackground"] = opts["background"]
                opts["inactiveselectbackground"] = opts["background"]
            if "foreground" in opts and "selectforeground" not in opts:
                opts["selectforeground"] = opts["foreground"]

            # применяем цвета к гаттеру
            self._gutter.configure(opts)

            # применяем фон к margin line
            if "background" in opts:
                background = opts["background"]
                self._margin_line.configure(background=background)
                self._gutter.tag_configure("sel", background=background)

            # === настройка шрифта ===
            from tkinter import font as tkfont
            from thonny.tktextext import get_text_font

            # base_font = get_text_font(self.text)
            # mono_family = "Consolas" if "Consolas" in tkfont.families() else (
            #     "Courier New" if "Courier New" in tkfont.families() else base_font.cget("family")
            # )

            # gutter_font = base_font.copy()
            # gutter_font.configure(family=mono_family, size=base_font.cget("size"))
            # self._gutter.configure(font=gutter_font)

            # === настройка цветов тегов ===
            fg_normal = opts.get("foreground", "#404040")
            bg = opts.get("background", "#e0e0e0")

            # обычный info_button (непустые строки)
            self._gutter.tag_configure(
                "info_button",
                foreground=fg_normal,
                background=bg,
            )

        if "breakpoint" in _syntax_options:
            self._gutter.tag_configure("breakpoint", _syntax_options["breakpoint"])
    
    def _get_gutter_tags(self, content, tags):
        """Override to prevent info_button from getting content tag (which causes right alignment)"""
        if "info_button" in tags:
            # Don't add "content" tag to info buttons so they stay left-aligned
            return tags
        else:
            # Normal behavior for everything else
            return ("content",) + tags
    
    def _on_info_click(self, event):
        """Handle click on info button in gutter"""
        # Get which line was clicked
        click_index = self._gutter.index(f"@{event.x},{event.y}")
        
        # Check if click is on info_button tag
        tags_at_click = self._gutter.tag_names(click_index)
        if "info_button" not in tags_at_click:
            return
        
        line_num = int(click_index.split(".")[0])
        
        # Get the line content
        line_content = self.text.get(f"{line_num}.0", f"{line_num}.end")
        
        # Skip empty lines
        if not line_content.strip():
            return "break"
        
        # Show explanation popup positioned relative to the clicked button
        self._show_line_explanation_popup(line_num, line_content, event)
        return "break"  # Prevent breakpoint toggle
    
    def _hide_info_buttons(self, event=None):
        """Hide info buttons ('i' icons) in gutter for screenshot (event handler)"""
        self.hide_for_screenshot()
    
    def _show_info_buttons(self, event=None):
        """Show info buttons after screenshot (event handler)"""
        self.show_after_screenshot()
    
    def hide_for_screenshot(self):
        """Hide UI elements for screenshot"""
        if not self._info_buttons_hidden:
            # Change foreground to match background (effectively hiding them)
            bg_color = self._gutter.cget("background")
            self._gutter.tag_configure("info_button", foreground=bg_color)
            self._info_buttons_hidden = True
        
        # Hide block highlighter if present
        if hasattr(self.text, 'block_highlighter'):
            self.text.block_highlighter._hide_for_screenshot()
    
    def show_after_screenshot(self):
        """Show UI elements after screenshot"""
        if self._info_buttons_hidden:
            # Restore original color
            self._gutter.tag_configure("info_button", foreground="#0066cc")
            self._info_buttons_hidden = False
        
        # Show block highlighter if present
        if hasattr(self.text, 'block_highlighter'):
            self.text.block_highlighter._show_after_screenshot()
    
    def _show_line_explanation_popup(self, line_num, line_content, event):
        """Show popup with AI explanation of the code line"""
        from thonny.plugins.base_assistant import get_ai_assistant
        from thonny.codeview_popup_utils import get_localization, create_explanation_popup
        
        assistant = get_ai_assistant()
        if not assistant:
            return
        
        loc = get_localization("line")
        
        create_explanation_popup(
            parent=self,
            title=loc["title"].format(line_num=line_num),
            width=600,
            height=520,
            loading_markdown=f"**{loc['code_line_label']}** `{line_content}`\n\n{loc['loading']}\n",
            request_func=lambda: self._request_line_explanation(
                assistant, line_num, line_content
            ),
            format_result_func=lambda expl: expl,  # Just the explanation, no duplication
            error_label=loc["error_label"],
            position_mode="below_line",
            line_num=line_num,
        )
    
    def _request_line_explanation(self, assistant, line_num, line_content):
        """Request AI explanation for a line of code with full context
        
        Note: assistant.get_ready() must be called BEFORE this method in the main thread!
        """
        from thonny.assistance import CodeViewContext
        from thonny.codeview_popup_utils import get_program_context
        
        # Get program context (debug if available, or formatted code)
        program_context = get_program_context(self.text, self)
        
        # Create context with line info and code context
        context = CodeViewContext(
            line_num=line_num,
            line_content=line_content,
            program_context=program_context
        )
        
        # Call assistant's explain_line method (all AI logic is there)
        return assistant.explain_line(context)


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
