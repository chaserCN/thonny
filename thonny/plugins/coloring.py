"""
Each text will get its on SyntaxColorer.

For performance reasons, coloring is updated in 2 phases:
    1. recolor single-line tokens on the modified line(s)
    2. recolor multi-line tokens (triple-quoted strings) in the whole text

First phase may insert wrong tokens inside triple-quoted strings, but the
priorities of triple-quoted-string tags are higher and therefore user
doesn't see these wrong taggings. In some cases (eg. open strings)
these wrong tags are removed later.

In Shell only current command entry is colored

Regexes are adapted from idlelib
"""

import re
from logging import getLogger

from thonny import get_workbench
from thonny.codeview import CodeViewText, SyntaxText
from thonny.shell import ShellText

logger = getLogger(__name__)

TODO = "COLOR_TODO"


class SyntaxColorer:
    def __init__(self, text: SyntaxText):
        self.text: SyntaxText = text
        self._compile_regexes()
        self._config_tags()
        self._update_scheduled = False
        self._use_coloring = True
        self._multiline_dirty = True
        self._highlight_tabs = True

    def _compile_regexes(self):
        from thonny.token_utils import (
            BUILTIN,
            COMMENT,
            COMMENT_WITH_Q3DELIMITER,
            FUNCTION_CALL,
            KEYWORD,
            MAGIC_COMMAND,
            METHOD_CALL,
            NUMBER,
            STRING3,
            STRING3_DELIMITER,
            STRING_CLOSED,
            STRING_OPEN,
            TAB,
        )

        self.uniline_regex = re.compile(
            KEYWORD
            + "|"
            + BUILTIN
            + "|"
            + NUMBER
            + "|"
            + COMMENT
            + "|"
            + MAGIC_COMMAND
            + "|"
            + STRING3_DELIMITER  # to avoid marking """ and ''' as single line string in uniline mode
            + "|"
            + STRING_CLOSED
            + "|"
            + STRING_OPEN
            + "|"
            + TAB
            + "|"
            + FUNCTION_CALL
            + "|"
            + METHOD_CALL,
            re.DOTALL | re.MULTILINE,
        )

        # need to notice triple-quotes inside comments and magic commands
        self.multiline_regex = re.compile(
            "(" + STRING3 + ")|" + COMMENT_WITH_Q3DELIMITER + "|" + MAGIC_COMMAND,
            re.S,  # @UndefinedVariable
        )

        self.id_regex = re.compile(r"\s+(\w+)", re.S)  # @UndefinedVariable

    def _config_tags(self):
        self.uniline_tags = {
            "comment",
            "magic",
            "string",
            "open_string",
            "keyword",
            "number",
            "builtin",
            "definition",
            "function_call",
            "method_call",
            "class_definition",
            "function_definition",
            "fstring_brace",  # F-string braces (highest priority)
        }
        self.multiline_tags = {"string3", "open_string3"}
        self._raise_tags()
        
        # F-string highlighting with debouncing
        self._fstring_update_timer = None
        
        # Bind event to re-color f-strings after text changes (fixes multi-line f-string editing)
        self.text.bind("<<TextChange>>", self._on_text_change_for_fstrings, True)

    def _on_text_change_for_fstrings(self, event):
        """
        Debounced event handler for f-string highlighting.
        Waits 150ms after last text change before re-highlighting.
        This prevents excessive highlighting when user types quickly.
        """
        # Cancel previous timer if exists
        if self._fstring_update_timer:
            self.text.after_cancel(self._fstring_update_timer)
        
        # Schedule new highlighting after 150ms delay
        self._fstring_update_timer = self.text.after(150, self._do_fstring_highlighting)
    
    def _do_fstring_highlighting(self):
        """
        Re-highlight f-strings after text changes to fix multi-line f-string editing.
        When user edits text inside {}, the string3 tag expands and covers new text.
        This handler re-runs f-string highlighting for the changed line.
        """
        try:
            # Get the line that was just changed
            insert_pos = self.text.index("insert")
            line_start = self.text.index(f"{insert_pos} linestart")
            line_end = self.text.index(f"{insert_pos} lineend")
            
            # Get few lines around for context (in case of multi-line f-strings)
            try:
                extended_start = self.text.index(f"{line_start} -3 lines")
            except:
                extended_start = "1.0"
            try:
                extended_end = self.text.index(f"{line_end} +3 lines")
            except:
                extended_end = "end"
            
            # Only re-highlight if the line contains f-string syntax
            chars = self.text.get(extended_start, extended_end)
            if 'f"' in chars or "f'" in chars or 'F"' in chars or "F'" in chars:
                # Re-run f-string highlighting for this region
                self._highlight_fstrings(extended_start, extended_end, chars)
        except:
            # Ignore errors to avoid breaking the editor
            pass
    
    def _raise_tags(self):
        self.text.tag_raise("string3")
        # yes, unclosed_expression is another plugin's issue,
        # but it must be higher than *string3
        self.text.tag_raise("tab")
        self.text.tag_raise("unclosed_expression")
        self.text.tag_raise("open_string3")
        self.text.tag_raise("open_string")
        self.text.tag_raise("fstring_brace", "string")  # f-string braces above string tag
        self.text.tag_raise("sel")
        self.text.tag_raise("builtin", "function_call")
        self.text.tag_raise("class_definition", "definition")
        self.text.tag_raise("function_definition", "definition")
        """
        tags = self.text.tag_names()
        # take into account that without themes some tags may be undefined
        if "string3" in tags:
            self.text.tag_raise("string3")
        if "open_string3" in tags:
            self.text.tag_raise("open_string3")
        """

    def mark_dirty(self, event=None):
        start_index = "1.0"
        end_index = "end"

        if hasattr(event, "sequence"):
            if event.sequence == "TextInsert":
                index = self.text.index(event.index)
                start_row = int(index.split(".")[0])
                end_row = start_row + event.text.count("\n")
                start_index = "%d.%d" % (start_row, 0)
                end_index = "%d.%d" % (end_row + 1, 0)
                if not event.trivial_for_coloring:
                    self._multiline_dirty = True

            elif event.sequence == "TextDelete":
                index = self.text.index(event.index1)
                start_row = int(index.split(".")[0])
                start_index = "%d.%d" % (start_row, 0)
                end_index = "%d.%d" % (start_row + 1, 0)
                if not event.trivial_for_coloring:
                    self._multiline_dirty = True

        self.text.tag_add(TODO, start_index, end_index)

    def schedule_update(self):
        self._highlight_tabs = get_workbench().get_option("view.highlight_tabs")
        self._use_coloring = get_workbench().get_option("view.syntax_coloring") and (
            self.text.is_python_text() or self.text.is_pythonlike_text()
        )

        if not self._update_scheduled:
            self._update_scheduled = True
            self.text.after_idle(self.perform_update)

    def perform_update(self):
        try:
            self._update_coloring()
        finally:
            self._update_scheduled = False

    def _update_coloring(self):
        raise NotImplementedError()

    def _update_uniline_tokens(self, start, end):
        chars = self.text.get(start, end)

        # clear old tags
        for tag in self.uniline_tags | {"tab"}:
            self.text.tag_remove(tag, start, end)

        if self._use_coloring:
            for match in self.uniline_regex.finditer(chars):
                for token_type, token_text in match.groupdict().items():
                    if token_text and token_type in self.uniline_tags:
                        token_text = token_text.strip()
                        match_start, match_end = match.span(token_type)

                        self.text.tag_add(
                            token_type, start + "+%dc" % match_start, start + "+%dc" % match_end
                        )

                        # Mark also the word following def or class
                        if token_text in ("def", "class"):
                            id_match = self.id_regex.match(chars, match_end)
                            if id_match:
                                id_match_start, id_match_end = id_match.span(1)
                                self.text.tag_add(
                                    "definition",
                                    start + "+%dc" % id_match_start,
                                    start + "+%dc" % id_match_end,
                                )
                                if token_text == "def":
                                    tag_type = "function_definition"
                                else:
                                    tag_type = "class_definition"
                                self.text.tag_add(
                                    tag_type,
                                    start + "+%dc" % id_match_start,
                                    start + "+%dc" % id_match_end,
                                )

        if self._highlight_tabs:
            self._update_tabs(start, end)
        
        # Highlight f-string interpolations for educational purposes
        # Single-line f-strings are handled here
        # Multi-line f-strings are handled after _update_multiline_tokens
        self._highlight_fstrings(start, end, chars)

        self.text.tag_remove(TODO, start, end)

    def _update_multiline_tokens(self, start, end):
        chars = self.text.get(start, end)
        # clear old tags
        for tag in self.multiline_tags:
            self.text.tag_remove(tag, start, end)

        if not self._use_coloring:
            return

        for match in self.multiline_regex.finditer(chars):
            token_text = match.group(1)
            if token_text is None:
                # not string3
                continue

            match_start, match_end = match.span()
            if (
                token_text.startswith('"""')
                and not token_text.endswith('"""')
                or token_text.startswith("'''")
                and not token_text.endswith("'''")
                or len(token_text) == 3
            ):
                token_type = "open_string3"
            elif len(token_text) >= 4 and token_text[-4] == "\\":
                token_type = "open_string3"
            else:
                token_type = "string3"

            token_start = start + "+%dc" % match_start
            token_end = start + "+%dc" % match_end
            self.text.tag_add(token_type, token_start, token_end)

        self._multiline_dirty = False
        self._raise_tags()

    def _update_tabs(self, start, end):
        while True:
            pos = self.text.search("\t", start, end)
            if pos:
                self.text.tag_add("tab", pos)
                start = self.text.index("%s +1 c" % pos)
            else:
                break
    
    def _highlight_fstrings(self, start, end, chars):
        """
        Highlight f-string interpolations: {variable} parts should show as code, not string.
        This helps students understand that f"{x}" is not just text, but code execution.
        
        Uses a simple parser instead of regex to handle all edge cases correctly:
        - {{escaped}} - literals (no highlighting)
        - {{'key': value}} - dict literal IN interpolation (highlight!)
        - {nested['key']} - nested braces in code (highlight!)
        """
        if not self._use_coloring:
            return
        
        # Find all f-strings (both single and double quoted)
        # IMPORTANT: Triple-quoted strings MUST be checked FIRST (they have higher priority)
        # Single-line strings use [^"\n]* to prevent matching across lines
        fstring_pattern = re.compile(r'[fF](""".*?"""|\'\'\'.*?\'\'\'|"[^"\n]*"|\'[^\'\n]*\')', re.DOTALL)
        
        for fstring_match in fstring_pattern.finditer(chars):
            fstring_start, fstring_end = fstring_match.span()
            fstring_text = fstring_match.group(1)  # the string content without f prefix
            
            # Parse f-string to find interpolation blocks
            from thonny.fstring_utils import parse_fstring_interpolations
            interpolations = parse_fstring_interpolations(fstring_text)
            
            for interp_start, interp_end, code_content in interpolations:
                # Calculate absolute positions (account for 'f' prefix)
                abs_brace_start = fstring_start + 1 + interp_start  # +1 for 'f' prefix
                abs_brace_end = fstring_start + 1 + interp_end
                abs_code_start = abs_brace_start + 1  # after {
                abs_code_end = abs_brace_end - 1  # before }
                
                # Tag the braces (dark green to distinguish from string)
                self.text.tag_add("fstring_brace", 
                                start + "+%dc" % abs_brace_start, 
                                start + "+%dc" % (abs_brace_start + 1))
                self.text.tag_add("fstring_brace", 
                                start + "+%dc" % (abs_brace_end - 1), 
                                start + "+%dc" % abs_brace_end)
                
                # IMPORTANT: Remove fstring_brace from the CODE part (only braces should be tagged!)
                # This prevents the tag from "stretching" when user edits code
                self.text.tag_remove("fstring_brace",
                                   start + "+%dc" % abs_code_start,
                                   start + "+%dc" % abs_code_end)
                
                # Remove ALL string tags from the code part (it's code, not string!)
                code_start_idx = start + "+%dc" % abs_code_start
                code_end_idx = start + "+%dc" % abs_code_end
                
                for string_tag in ["string", "string3", "open_string"]:
                    self.text.tag_remove(string_tag, code_start_idx, code_end_idx)
                
                # Parse code content for keywords/builtins/numbers/strings
                from thonny.token_utils import KEYWORD, BUILTIN, NUMBER, STRING_CLOSED, STRING3
                
                keyword_re = re.compile(KEYWORD)
                builtin_re = re.compile(BUILTIN)
                number_re = re.compile(NUMBER)
                # Match both single-line and multi-line strings
                string_re = re.compile(f"({STRING3}|{STRING_CLOSED})")
                
                # Apply syntax highlighting to the code inside {}
                # IMPORTANT: Apply strings FIRST (so they're not overridden by keywords)
                for str_match in string_re.finditer(code_content):
                    str_start, str_end = str_match.span()
                    self.text.tag_add("string",
                                    start + "+%dc" % (abs_code_start + str_start),
                                    start + "+%dc" % (abs_code_start + str_end))
                
                for kw_match in keyword_re.finditer(code_content):
                    kw_start, kw_end = kw_match.span()
                    self.text.tag_add("keyword",
                                    start + "+%dc" % (abs_code_start + kw_start),
                                    start + "+%dc" % (abs_code_start + kw_end))
                
                for builtin_match in builtin_re.finditer(code_content):
                    builtin_start, builtin_end = builtin_match.span()
                    self.text.tag_add("builtin",
                                    start + "+%dc" % (abs_code_start + builtin_start),
                                    start + "+%dc" % (abs_code_start + builtin_end))
                
                for num_match in number_re.finditer(code_content):
                    num_start, num_end = num_match.span()
                    self.text.tag_add("number",
                                    start + "+%dc" % (abs_code_start + num_start),
                                    start + "+%dc" % (abs_code_start + num_end))
        
        # Ensure f-string tags have higher priority than ALL string tags
        for tag in ["fstring_brace", "keyword", "builtin", "number"]:
            self.text.tag_raise(tag, "string")
            self.text.tag_raise(tag, "string3")  # Multi-line strings
            self.text.tag_raise(tag, "open_string")


class CodeViewSyntaxColorer(SyntaxColorer):
    def _update_coloring(self):
        viewport_start = self.text.index("@0,0")
        viewport_end = self.text.index(
            "@%d,%d lineend" % (self.text.winfo_width(), self.text.winfo_height())
        )

        search_start = viewport_start
        search_end = viewport_end

        while True:
            res = self.text.tag_nextrange(TODO, search_start, search_end)
            if res:
                update_start = res[0]
                update_end = res[1]
            else:
                # maybe the range started earlier
                res = self.text.tag_prevrange(TODO, search_start)
                if res and self.text.compare(res[1], ">", search_end):
                    update_start = search_start
                    update_end = res[1]
                else:
                    break

            if self.text.compare(update_end, ">", search_end):
                update_end = search_end

            self._update_uniline_tokens(update_start, update_end)

            if update_end == search_end:
                break
            else:
                search_start = update_end

        # Multiline tokens need to be searched from the whole source
        if self._multiline_dirty:
            self._update_multiline_tokens("1.0", "end")
            # Re-highlight f-strings after multiline tokens to ensure correct priority
            self._highlight_fstrings("1.0", "end", self.text.get("1.0", "end"))

        # Get rid of wrong open string tags (https://github.com/thonny/thonny/issues/943)
        search_start = viewport_start
        while True:
            tag_range = self.text.tag_nextrange("open_string", search_start, viewport_end)
            if not tag_range:
                break

            if "string3" in self.text.tag_names(tag_range[0]):
                self.text.tag_remove("open_string", tag_range[0], tag_range[1])

            search_start = tag_range[1]


class ShellSyntaxColorer(SyntaxColorer):
    def _update_coloring(self):
        parts = self.text.tag_prevrange("command", "end")

        if parts:
            end_row, end_col = map(int, self.text.index(parts[1]).split("."))

            if end_col != 0:  # if not just after the last linebreak
                end_row += 1  # then extend the range to the beginning of next line
                end_col = 0  # (otherwise open strings are not displayed correctly)

            start_index = parts[0]
            end_index = "%d.%d" % (end_row, end_col)

            self._update_uniline_tokens(start_index, end_index)
            self._update_multiline_tokens(start_index, end_index)
            # Re-highlight f-strings after multiline tokens to ensure correct priority
            self._highlight_fstrings(start_index, end_index, self.text.get(start_index, end_index))


def update_coloring_on_event(event):
    if hasattr(event, "text_widget"):
        text = event.text_widget
    else:
        text = event.widget

    try:
        update_coloring_on_text(text, event)
    except Exception as e:
        logger.error("Problem with coloring", exc_info=e)


def update_coloring_on_text(text, event=None):
    if not hasattr(text, "syntax_colorer"):
        if isinstance(text, ShellText):
            class_ = ShellSyntaxColorer
        elif isinstance(text, CodeViewText):
            class_ = CodeViewSyntaxColorer
        else:
            return

        text.syntax_colorer = class_(text)
        # mark whole text as unprocessed
        text.syntax_colorer.mark_dirty()
    else:
        text.syntax_colorer.mark_dirty(event)

    text.syntax_colorer.schedule_update()


def load_plugin() -> None:
    wb = get_workbench()

    wb.set_default("view.syntax_coloring", True)
    wb.set_default("view.highlight_tabs", True)
    wb.bind("TextInsert", update_coloring_on_event, True)
    wb.bind("TextDelete", update_coloring_on_event, True)
    wb.bind_class("CodeViewText", "<<VerticalScroll>>", update_coloring_on_event, True)
    wb.bind("<<UpdateAppearance>>", update_coloring_on_event, True)
