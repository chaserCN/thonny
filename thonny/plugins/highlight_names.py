import time
import tkinter as tk
from logging import getLogger
from tkinter import messagebox
from typing import List, Union

from thonny import get_runner, get_workbench, lsp_types
from thonny.codeview import SyntaxText
from thonny.editor_helpers import get_cursor_ls_position
from thonny.editors import Editor
from thonny.languages import tr
from thonny.lsp_types import DocumentHighlightParams, LspResponse, TextDocumentIdentifier

logger = getLogger(__name__)


class OccurrencesHighlighter:
    def __init__(self, text):
        self.text: SyntaxText = text
        self._request_scheduled: bool = False

    def get_positions_for(self, source, line, column):
        raise NotImplementedError()

    def get_positions(self):
        index = self.text.index("insert")

        # ignore if cursor in open string
        if self.text.tag_prevrange("open_string", index) or self.text.tag_prevrange(
            "open_string3", index
        ):
            return set()

        source = self.text.get("1.0", "end")
        index_parts = index.split(".")
        line, column = int(index_parts[0]), int(index_parts[1])

        return self.get_positions_for(source, line, column)

    def trigger(self):
        self._clear()

        if (
            not get_workbench().get_option("view.name_highlighting")
            or not self.text.is_python_text()
        ):
            return

        def consider_request():
            if time.time() - self.text.get_last_operation_time() < 0.3:
                # wait a bit more, there may be more keypresses or cursor location changes coming
                self.text.after(100, consider_request)
            else:
                try:
                    self._request()
                finally:
                    self._request_scheduled = False

        if not self._request_scheduled:
            self._request_scheduled = True
            self.text.after_idle(consider_request)

    def _clear(self) -> None:
        self.text.tag_remove("matched_name", "1.0", "end")

    def _request(self):
        self._clear()

        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is None:
            return

        ls_proxy.unbind_request_handler(self._handle_response)

        pos = get_cursor_ls_position(self.text)
        editor = self.text.master.master
        assert isinstance(editor, Editor)

        uri = editor.get_uri()
        if uri is None:
            return

        # Check if language server is initialized before making request
        if not ls_proxy.is_initialized():
            return

        # Check if language server supports document highlighting
        if not hasattr(ls_proxy, 'server_capabilities') or ls_proxy.server_capabilities is None:
            return
        if not ls_proxy.server_capabilities.documentHighlightProvider:
            return

        # Remember cursor position for validation in response
        self._request_cursor_pos = self.text.index("insert")

        ls_proxy.request_document_highlight(
            DocumentHighlightParams(textDocument=TextDocumentIdentifier(uri=uri), position=pos),
            self._handle_response,
        )

    def _handle_response(
        self, response: LspResponse[Union[List[lsp_types.DocumentHighlight], None]]
    ) -> None:
        error = response.get_error()
        if error:
            messagebox.showerror(tr("Error"), str(error), master=get_workbench())
            return

        # Check if cursor moved since request - ignore stale response
        current_cursor_pos = self.text.index("insert")
        if hasattr(self, '_request_cursor_pos') and current_cursor_pos != self._request_cursor_pos:
            return

        result = response.get_result_or_raise()

        if not result:
            return

        try:
            if len(result) > 1:
                # Check if cursor is actually on a word from the result
                cursor_pos = self.text.index("insert")
                cursor_line, cursor_col = map(int, cursor_pos.split('.'))
                cursor_on_word = False
                
                for ref in result:
                    range = ref.range
                    ref_line = range.start.line + 1
                    ref_start_col = range.start.character
                    ref_end_col = range.end.character
                    
                    if (ref_line == cursor_line and ref_start_col <= cursor_col <= ref_end_col):
                        # Cursor position matches - but check if text is still correct
                        start_index = f"{ref_line}.{ref_start_col}"
                        end_index = f"{ref_line}.{ref_end_col}"
                        actual_text = self.text.get(start_index, end_index)
                        if actual_text.strip():  # Not just whitespace
                            cursor_on_word = True
                            break
                
                if not cursor_on_word:
                    return
                
                # Get word at cursor (what we're highlighting)
                expected_word = None
                
                for ref in result:
                    # TODO: UTF-16
                    range = ref.range
                    start_index = f"{range.start.line + 1}.{range.start.character}"
                    end_index = f"{range.end.line + 1}.{range.end.character}"
                    # Get what character is at this position
                    char = self.text.get(start_index, end_index)
                    
                    # First occurrence - remember the word we're looking for
                    if expected_word is None and char.strip():
                        expected_word = char
                    
                    # Validate: only add tag if character matches expected word
                    if char == expected_word:
                        self.text.tag_add("matched_name", start_index, end_index)
        except Exception as e:
            logger.exception("Problem when updating name highlighting", exc_info=e)


def update_highlighting(event):
    if not get_workbench().ready:
        # don't slow down loading process
        return

    if not get_runner() or not get_runner().get_backend_proxy():
        # too early
        return

    assert isinstance(event.widget, tk.Text)
    text = event.widget
    if not hasattr(text, "name_highlighter"):
        text.name_highlighter = OccurrencesHighlighter(text)

    text.name_highlighter.trigger()


def load_plugin() -> None:
    wb = get_workbench()
    wb.set_default("view.name_highlighting", True)
    wb.bind_class("EditorCodeViewText", "<<CursorMove>>", update_highlighting, True)
    wb.bind_class("EditorCodeViewText", "<<TextChange>>", update_highlighting, True)
    wb.bind("<<UpdateAppearance>>", update_highlighting, True)
