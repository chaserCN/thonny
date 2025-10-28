import tkinter as tk
from logging import getLogger
from tkinter import messagebox
from typing import List, Optional, Union, cast

from thonny import editor_helpers, get_runner, get_workbench, lsp_types
from thonny.codeview import CodeViewText, SyntaxText, get_syntax_options_for_tag
from thonny.editor_helpers import DocuBox, EditorInfoBox
from thonny.languages import tr
from thonny.lsp_types import CompletionItem, CompletionParams, LspResponse, TextDocumentIdentifier
from thonny.misc_utils import running_on_mac_os
from thonny.shell import ShellText
from thonny.ui_utils import (
    alt_is_pressed_without_char,
    command_is_pressed,
    control_is_pressed,
    ems_to_pixels,
)

logger = getLogger(__name__)

"""
Completions get computed on the backend, therefore getting the completions is
asynchronous.
"""


def _infer_variable_types_with_parso(source_code: str) -> dict:
    """Use parso to infer simple types for variables (list, dict, set, tuple)."""
    try:
        import parso
        from parso.python import tree
        
        var_types = {}  # {var_name: type_hint}
        
        module = parso.parse(source_code)
        
        assignments_found = []  # For logging
        
        def get_outermost_function_name(node):
            """Extract outermost function name from expression like list(map(...))"""
            if node.type == 'atom_expr' and hasattr(node, 'children') and len(node.children) >= 2:
                # atom_expr: list(...) or foo.bar(...)
                # children[0] = name, children[1] = trailer (the parentheses)
                first_child = node.children[0]
                if first_child.type == 'name':
                    return first_child.value
            elif node.type == 'power' and hasattr(node, 'children'):
                # power = name + trailer*
                if node.children[0].type == 'name':
                    return node.children[0].value
            elif node.type == 'name':
                return node.value
            return None
        
        def analyze_node(node):
            # Look for assignments: x = [...]
            if isinstance(node, tree.ExprStmt) and node.children[0].type == 'name':
                var_name = node.children[0].value
                
                # Check if it's simple assignment (x = ...)
                if len(node.children) >= 3 and node.children[1].value == '=':
                    value = node.children[2]
                    value_type = value.type
                    inferred_type = None
                    
                    # Check for literals by looking at first character
                    if hasattr(value, 'children') and value.children:
                        first_char = value.children[0].value if hasattr(value.children[0], 'value') else None
                        
                        # List literal: x = [1, 2, 3]
                        if first_char == '[':
                            var_types[var_name] = 'list'
                            inferred_type = 'list'
                        
                        # Dict or Set literal: x = {1: 2} or x = {1, 2}
                        elif first_char == '{':
                            # Check if it's dict (has ':') or set (no ':')
                            # Empty {} is always dict
                            if len(value.children) == 2:  # Just { and }
                                var_types[var_name] = 'dict'
                                inferred_type = 'dict'
                            else:
                                # Look for ':' to distinguish dict from set
                                has_colon = False
                                for child in value.children:
                                    if hasattr(child, 'value') and child.value == ':':
                                        has_colon = True
                                        break
                                    # Also check in nested children
                                    if hasattr(child, 'children'):
                                        for subchild in child.children:
                                            if hasattr(subchild, 'value') and subchild.value == ':':
                                                has_colon = True
                                                break
                                
                                if has_colon:
                                    var_types[var_name] = 'dict'
                                    inferred_type = 'dict'
                                else:
                                    var_types[var_name] = 'set'
                                    inferred_type = 'set'
                        
                        # Tuple literal: x = (1, 2)
                        elif first_char == '(':
                            var_types[var_name] = 'tuple'
                            inferred_type = 'tuple'
                    
                    # Tuple from testlist (without parens): x = 1, 2
                    if not inferred_type and value.type == 'testlist':
                        var_types[var_name] = 'tuple'
                        inferred_type = 'tuple'
                    
                # Function calls: x = list(...), x = dict(...), even nested like list(map(...))
                if not inferred_type:
                    func_name = get_outermost_function_name(value)
                    if func_name and func_name in ('list', 'dict', 'set', 'tuple', 'range', 'enumerate', 
                                                   'zip', 'map', 'filter', 'reversed', 'sorted'):
                        var_types[var_name] = func_name
                        inferred_type = func_name
                    
                    # Track what we found
                    if inferred_type:
                        assignments_found.append(f"{var_name}={inferred_type}")
            
            # Recursively process children
            if hasattr(node, 'children'):
                for child in node.children:
                    analyze_node(child)
        
        analyze_node(module)
        
        if var_types:
            logger.info(f"🔬 Parso: {', '.join(assignments_found)}")
        
        return var_types
        
    except Exception as e:
        logger.warning(f"Parso type inference failed: {e}")
        return {}


def create_context_aware_sort_key(prefix: str, line_before_cursor: str, line_after_cursor: str, 
                                   source_code: str = None):
    """
    Factory function that creates a sort_key function for context-aware completion ranking.
    
    This enables fast local ranking (< 5ms) without AI, by analyzing:
    - Prefix matching (existing logic)
    - Context (for loops, imports, dot access, etc.)
    - Type information from LSP
    - Simple type inference via Parso (for small files)
    
    Args:
        prefix: The text user has typed so far
        line_before_cursor: Text from line start to cursor
        line_after_cursor: Text from cursor to line end
        source_code: Full source code (optional, for parso inference)
        
    Returns:
        A sort_key function that can be used with sorted()
    """
    
    # Try to infer types with parso (only for small files)
    var_types = {}
    if source_code and len(source_code) < 5000:  # Only for small files (< 5KB)
        var_types = _infer_variable_types_with_parso(source_code)
    
    def sort_key(completion: lsp_types.CompletionItem):
        sort_text = completion.sortText or completion.label
        label = completion.label
        kind = completion.kind
        detail = completion.detail or ""

        # Base prefix priority (existing Thonny logic)
        if not prefix:
            prefix_priority = 1 if label.startswith("_") else 0
        elif label.startswith(prefix):
            is_user_defined = sort_text.startswith(('00.', '01.', '02.'))
            
            if kind and kind.value == 6:  # Variable - highest priority
                prefix_priority = -3
            elif kind and kind.value in (3, 7, 9) and is_user_defined:  # User-defined Function/Class/Module
                prefix_priority = -2
            elif kind and kind.value in (3, 7, 9):  # Builtin Function/Class
                prefix_priority = -1.5
            else:
                prefix_priority = -1  # Keywords and other builtins
        elif label.lower().startswith(prefix.lower()):
            prefix_priority = -0.5
        else:
            prefix_priority = 0
        
        # Context-aware boost (NEW: makes autocomplete smarter!)
        context_boost = 0
        boost_reason = None  # For logging
        
        # 1. FOR LOOPS: boost iterables after "for x in "
        if " in " in line_before_cursor or line_before_cursor.strip().startswith("for "):
            if " in " in line_before_cursor:
                after_in = line_before_cursor.split(" in ")[-1].strip()
                # If cursor right after "in" or user started typing
                if len(after_in) <= len(prefix) + 3:
                    # STRONG boost for known iterable-returning functions/classes
                    if label in ["range", "enumerate", "zip", "map", "filter", "reversed", 
                               "sorted", "list", "tuple", "set", "dict", "keys", "values", "items"]:
                        # These can be Class or Function in LSP - boost both!
                        context_boost -= 5  # Very strong boost
                        boost_reason = f"for..in: iterable {lsp_types.CompletionItemKind(kind).name if kind else ''}"
                    
                    # Boost variables/objects (STRONGEST for user-defined!)
                    elif kind and kind.value == 6:  # Variable
                        # Check if it's user-defined (sortText starts with 00., 01., 02.)
                        is_user_defined = sort_text.startswith(('00.', '01.', '02.'))
                        detail_lower = detail.lower()
                        
                        # Check parso-inferred type
                        parso_type = var_types.get(label, '')
                        
                        if is_user_defined:
                            # User-defined variable - STRONGEST boost!
                            # Extra boost if we know it's iterable from parso
                            if parso_type in ('list', 'dict', 'set', 'tuple', 'range', 'enumerate', 'zip', 'map', 'filter'):
                                context_boost -= 10  # SUPER STRONG for known iterable locals
                                boost_reason = f"for..in: local {parso_type}"
                            else:
                                context_boost -= 8  # Strong for any local
                                boost_reason = f"for..in: user-defined var" + (f" ({detail[:30]})" if detail else "")
                        elif parso_type in ('list', 'dict', 'set', 'tuple', 'range'):
                            # Parso knows it's iterable
                            context_boost -= 7
                            boost_reason = f"for..in: {parso_type} (parso)"
                        elif any(t in detail_lower for t in ["list", "tuple", "set", "dict", "str", 
                                                           "iterator", "iterable", "sequence",
                                                           "range", "generator"]):
                            context_boost -= 6  # Strong boost for typed iterable variables
                            boost_reason = f"for..in: iterable var ({detail[:30]})"
                        else:
                            # Still boost regular variables (they might be iterables)
                            context_boost -= 2
                            boost_reason = f"for..in: variable"
                    
                    # Demote keywords in "for...in" context (we want functions/variables, not keywords)
                    elif kind and kind.value == 14:  # Keyword
                        context_boost += 3  # Push keywords down
                        boost_reason = f"for..in: demote keyword"
                    
                    # Demote classes (we want instances/functions, not class constructors)
                    elif kind and kind.value == 7:  # Class
                        context_boost += 1
                        boost_reason = f"for..in: demote class"
        
        # 2. IMPORT statements: boost modules
        if line_before_cursor.strip().startswith("import ") or line_before_cursor.strip().startswith("from "):
            if kind and kind.value == 9:  # Module
                context_boost -= 1
                boost_reason = "import: module"
        
        # 3. After DOT: boost methods/properties over functions
        if line_before_cursor.rstrip().endswith("."):
            if kind and kind.value in (2, 10):  # Method or Property
                context_boost -= 0.8
                boost_reason = "after dot: method/property"
            elif kind and kind.value == 3:  # Function - lower priority after dot
                context_boost += 0.5
                boost_reason = "after dot: demote function"
        
        # 4. Start of line: boost keywords and statements
        if len(line_before_cursor.strip()) <= len(prefix):
            if kind and kind.value == 14:  # Keyword
                if label in ["for", "if", "while", "def", "class", "return", "import"]:
                    context_boost -= 0.5
                    boost_reason = "line start: statement keyword"
        
        # 5. Inside expressions (after operators): prefer variables/functions over keywords  
        if any(op in line_before_cursor[-10:] for op in ["= ", "+ ", "- ", "* ", "/ ", "(", "[", ","]):
            if kind and kind.value == 14:  # Keyword - lower priority in expressions
                context_boost += 0.3
                boost_reason = "in expression: demote keyword"
            elif kind and kind.value in (3, 6):  # Function or Variable - higher priority
                context_boost -= 0.3
                boost_reason = "in expression: boost func/var"
        
        # Combined priority: base prefix matching + context boost
        final_priority = prefix_priority + context_boost
        return (final_priority, sort_text.lower(), label.lower(), label)
    
    return sort_key


class CompletionsDetailsBox(DocuBox):
    def __init__(self, completions_box: "CompletionsBox"):
        super().__init__()
        self._completions_box = completions_box

    def _get_related_box(self) -> Optional["EditorInfoBox"]:
        return self._completions_box


class CompletionsBox(EditorInfoBox):
    def __init__(self, completer: "Completer"):
        super().__init__()
        self._completer = completer
        self._listbox = tk.Listbox(
            self,
            font="EditorFont",
            activestyle="dotbox",
            exportselection=False,
            highlightthickness=0,
            borderwidth=0,
            height=5,
        )
        self._listbox.grid()
        self._tweaking_listbox_selection = False
        self._details_box: Optional[CompletionsDetailsBox] = None
        self._completions: List[lsp_types.CompletionItem] = []

        self._listbox.bind("<<ListboxSelect>>", self._on_select_item_via_event, True)

        # for cases when Listbox gets focus
        self.bind("<Return>", self._insert_current_selection)
        self.bind("<Tab>", self._insert_current_selection_replace_suffix)
        self.bind("<Double-Button-1>", self._insert_current_selection)

        self._update_theme()

    def present_completions(
        self, text: SyntaxText, completions: List[lsp_types.CompletionItem], skip_sorting: bool = False
    ) -> None:
        # Next events need to know this
        assert completions
        self._target_text_widget = text
        self._check_bind_for_keypress(text)

        prefix_start_index = self._find_completion_insertion_index()
        assert self._target_text_widget.compare(prefix_start_index, "<=", "insert")
        prefix = self._target_text_widget.get(prefix_start_index, "insert")
        
        # Get context for context-aware ranking
        try:
            line_before_cursor = text.get("insert linestart", "insert")
            line_after_cursor = text.get("insert", "insert lineend")
            source_code = text.get("1.0", "end")
        except:
            line_before_cursor = ""
            line_after_cursor = ""
            source_code = ""

        # Use shared context-aware sorting logic
        sort_key = create_context_aware_sort_key(prefix, line_before_cursor, line_after_cursor, source_code)

        if skip_sorting:
            # AI already sorted - don't re-sort!
            logger.info(f"🎯 Using AI-sorted order (skip_sorting=True)")
            sorted_completions = completions
        else:
            # Apply our sorting algorithm
            sorted_completions = sorted(completions, key=sort_key)
            
            # Log top results for debugging
            if sorted_completions:
                top_5 = ", ".join([comp.label for comp in sorted_completions[:5]])
                logger.info(f"📋 Top 5 completions: {top_5}")
        
        if not prefix.startswith("__"):
            sorted_completions = [
                comp
                for comp in sorted_completions
                if not comp.label.startswith("__")
                and comp.textEdit is None  # TODO: support textEdit
                and not comp.additionalTextEdits  # TODO: support this
            ]
        self._completions = sorted_completions

        # broadcast logging info
        row, column = editor_helpers.get_cursor_position(text)
        if isinstance(text, ShellText):
            row -= text.get_current_line_ls_offset()
            column -= text.get_current_column_ls_offset()

        get_workbench().event_generate(
            "AutocompleteProposal",
            text_widget=text,
            row=row,
            column=column,
            proposal_count=len(sorted_completions),
        )

        # present
        if len(sorted_completions) == 0:
            self.hide()
            return

        self._listbox.delete(0, self._listbox.size())
        self._listbox.insert(0, *[c.label for c in sorted_completions])
        self._listbox.activate(0)
        self._listbox.selection_set(0)

        max_visible_items = 10
        self._listbox["height"] = min(len(sorted_completions), max_visible_items)

        _, _, _, list_row_height = self._listbox.bbox(0)
        # the measurement is not accurate, but good enough for deciding whether
        # the box should be above or below the current line.
        # Actual placement will be managed otherwise
        approx_box_height = round(list_row_height * (self._listbox["height"] + 0.5))

        name_start_index = self._find_completion_insertion_index()

        self._show_on_target_text(name_start_index, approx_box_height, "below")

        self._check_request_details()

    def _get_related_box(self) -> Optional["EditorInfoBox"]:
        return self._details_box

    def tweak_first_appearance(self):
        super().tweak_first_appearance()
        if running_on_mac_os():
            self.update()
            self._listbox.grid_remove()
            self._listbox.grid()

    def _get_current_completion_index(self):
        selected = self._listbox.curselection()
        if len(selected) == 0:
            return 0
        else:
            return selected[0]

    def _move_selection(self, delta):
        old_flag = self._tweaking_listbox_selection
        self._tweaking_listbox_selection = True
        try:
            index = self._get_current_completion_index()
            index += delta
            index = max(0, min(self._listbox.size() - 1, index))

            self._listbox.selection_clear(0, self._listbox.size() - 1)
            self._listbox.selection_set(index)
            self._listbox.see(index)
            self._listbox.activate(index)
            self._check_request_details()
        finally:
            self._tweaking_listbox_selection = old_flag

    def _update_theme(self, event=None):
        gutter_opts = get_syntax_options_for_tag("GUTTER")
        text_opts = get_syntax_options_for_tag("TEXT")
        self._listbox["background"] = gutter_opts["background"]
        self._listbox["foreground"] = text_opts["foreground"]

    def _on_select_item_via_event(self, event=None) -> None:
        if self._tweaking_listbox_selection:
            return

        self._check_request_details()

    def _check_request_details(self) -> None:
        if not self.winfo_ismapped():
            # can happen, see https://github.com/thonny/thonny/issues/2162
            return

        if (
            self._details_box
            and self._details_box.is_visible()
            or get_workbench().get_option("edit.automatic_completion_details")
        ):
            self.request_details()

    def _on_text_keypress(self, event=None):
        if not self.is_visible():
            return None

        if event.keysym in ["Up", "KP_Up"]:
            self._move_selection(-1)
            return "break"
        elif event.keysym in ["Down", "KP_Down"]:
            self._move_selection(1)
            return "break"
        elif event.keysym in ["Return", "KP_Enter"]:
            assert self._listbox.size() > 0
            self._insert_current_selection()
            return "break"
        elif event.keysym == "Tab":
            assert self._listbox.size() > 0
            self._insert_current_selection_replace_suffix()
            return "break"
        elif event.keysym in ["BackSpace", "Left", "Right", "KP_Left", "KP_Right"]:
            self.after_idle(
                lambda: self._completer.request_completions_for_text(self._target_text_widget)
            )
        elif (
            event.char
            and not _is_python_name_char(event.char)
            and event.char != "."
            and not control_is_pressed(event)
        ):
            self.hide(event)

        return None

    def _insert_current_selection(self, event=None):
        self._insert_completion(self._get_current_completion(), replace_suffix=False)

    def _insert_current_selection_replace_suffix(self, event=None):
        self._insert_completion(self._get_current_completion(), replace_suffix=True)

    def _get_current_completion(self) -> Optional[CompletionItem]:
        sel = self._listbox.curselection()
        if len(sel) != 1:
            return None

        return self._completions[sel[0]]

    def _get_insert_text(self, completion: CompletionItem) -> str:
        if completion.textEdit is not None:
            raise RuntimeError("TODO: handle textEdit")

        if completion.insertText is not None:
            if completion.insertTextFormat == lsp_types.InsertTextFormat.Snippet:
                raise RuntimeError("TODO support snippets")
            if completion.insertTextMode == lsp_types.InsertTextMode.AdjustIndentation:
                raise RuntimeError("TODO support adjust indentation")
            return completion.insertText
        else:
            assert completion.label is not None
            return completion.label

    def _insert_completion(self, completion: CompletionItem, replace_suffix: bool) -> None:
        insert_text = self._get_insert_text(completion)
        prefix_start_index = self._find_completion_insertion_index()
        typed_prefix = self._target_text_widget.get(prefix_start_index, "insert")

        get_workbench().event_generate(
            "AutocompleteInsertion",
            text_widget=self._target_text_widget,
            typed_prefix=typed_prefix,
            replace_suffix=replace_suffix,
            completed_name=insert_text,
        )

        # Before insertion need to delete prefix, because it may not be name's prefix
        # (eg. with different case or even more different with fuzzy completions)
        self._target_text_widget.direct_delete(prefix_start_index, "insert")
        self._target_text_widget.insert("insert", insert_text)

        if replace_suffix:
            did_replace_suffix = False
            while _is_python_name_char(self._target_text_widget.get("insert")):
                self._target_text_widget.direct_delete("insert")
                did_replace_suffix = True

            last_char_inserted = self._target_text_widget.get("insert -1 chars")
            if (
                did_replace_suffix
                and last_char_inserted in ["(", "="]
                and self._target_text_widget.get("insert") == last_char_inserted
            ):
                self._target_text_widget.direct_delete("insert")

        get_workbench().event_generate(
            "AutocompletionInserted",
            text_widget=self._target_text_widget,
            typed_prefix=typed_prefix,
            replace_suffix=replace_suffix,
            completed_name=insert_text,
        )

        self.hide()
        
        # Ensure focus returns to the text widget after mouse selection
        self._target_text_widget.focus_set()

    def _find_completion_insertion_index(self):
        line, col = map(int, self._target_text_widget.index("insert").split("."))
        while col > 0:
            char_at_left: str = self._target_text_widget.get(f"{line}.{col-1}")
            if not char_at_left.isidentifier():
                break
            col -= 1

        return f"{line}.{col}"

    def request_details(self) -> None:
        completion = self._get_current_completion()

        if not self._details_box:
            self._details_box = CompletionsDetailsBox(self)

        self._details_box.set_content(completion)

        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is not None:
            # TODO: cancel previous request
            ls_proxy.unbind_request_handler(self._handle_details_response)
            ls_proxy.request_resolve_completion_item(completion, self._handle_details_response)

        self._show_next_to_completions()

    def _show_next_to_completions(self):
        self._details_box._show_on_screen(
            self.winfo_rootx() + self.winfo_width() + ems_to_pixels(0.5), self.winfo_rooty()
        )

    def _handle_details_response(self, response: LspResponse[CompletionItem]) -> None:
        if not self.is_visible():
            return

        basic_completion = self._get_current_completion()
        detailed_completion = response.get_result_or_raise()
        logger.debug("Got completion details: %r", detailed_completion)
        if detailed_completion.data != basic_completion.data:
            return

        self._update_completion(details=detailed_completion)

        if not self._details_box:
            self._details_box = CompletionsDetailsBox(self)

        self._details_box.set_content(detailed_completion)

        self._show_next_to_completions()

    def _update_completion(self, details: CompletionItem) -> None:
        # logger.debug("Handling completion details %r", details)
        for i, comp in enumerate(self._completions):
            assert isinstance(comp, CompletionItem)
            if comp.data == details.data:
                comp.label = details.label
                comp.detail = details.detail
                comp.labelDetails = details.labelDetails
                comp.documentation = details.documentation

                sel = self._listbox.curselection()
                old_flag = self._tweaking_listbox_selection
                self._tweaking_listbox_selection = True
                try:
                    self._listbox.delete(i)
                    self._listbox.insert(i, comp.label)
                    if len(sel) == 1:
                        self._listbox.selection_set(sel[0])
                        self._listbox.activate(sel[0])
                    break
                finally:
                    self._tweaking_listbox_selection = old_flag
    
    def update_order_from_ai(self, reranked_labels: List[str], original_completions: List[CompletionItem]) -> None:
        """Update completion order based on AI reranking (called async from background thread result)"""
        try:
            # Create mapping from label to completion item
            label_to_item = {item.label: item for item in original_completions}
            
            # Build reordered list
            reordered = []
            seen = set()
            
            # Add reranked items first (in AI's preferred order)
            for label in reranked_labels:
                if label in label_to_item and label not in seen:
                    reordered.append(label_to_item[label])
                    seen.add(label)
            
            # Add remaining items that AI didn't rank
            for item in self._completions:
                if item.label not in seen:
                    reordered.append(item)
            
            logger.info(f"📤 Final order shown to user ({len(reordered)} items):")
            for i, comp in enumerate(reordered[:20]):  # Show first 20
                kind_name = lsp_types.CompletionItemKind(comp.kind).name if comp.kind else "Unknown"
                logger.info(f"  [{i:2d}] {comp.label:30s} | {kind_name:12s}")
            if len(reordered) > 20:
                logger.info(f"  ... and {len(reordered) - 20} more")
            logger.info(f"━" * 80)
            
            # Update internal list
            self._completions = reordered
            
            # Update listbox display
            old_flag = self._tweaking_listbox_selection
            self._tweaking_listbox_selection = True
            try:
                # Remember current selection
                sel = self._listbox.curselection()
                selected_label = None
                if len(sel) == 1:
                    selected_label = self._listbox.get(sel[0])
                
                # Rebuild listbox
                self._listbox.delete(0, self._listbox.size())
                self._listbox.insert(0, *[c.label for c in reordered])
                
                # Restore selection if possible
                if selected_label:
                    for i, comp in enumerate(reordered):
                        if comp.label == selected_label:
                            self._listbox.selection_set(i)
                            self._listbox.activate(i)
                            break
                else:
                    # Default to first item
                    self._listbox.selection_set(0)
                    self._listbox.activate(0)
                    
            finally:
                self._tweaking_listbox_selection = old_flag
                
        except Exception as e:
            logger.exception("Error updating completion order from AI")


class Completer:
    """
    Manages completion requests and responses.
    Delegates user interactions with completions to CompletionsBox.
    """

    def __init__(self):
        self._last_request_text: Optional[SyntaxText] = None
        logger.debug("Creating Completer")
        self._completions_box: Optional[CompletionsBox] = None

        get_workbench().bind_class("EditorCodeViewText", "<Key>", self._on_keypress, True)
        get_workbench().bind_class("ShellText", "<Key>", self._on_keypress, True)
        get_workbench().bind(
            "editor_autocomplete_response", self._handle_completions_response, True
        )
        get_workbench().bind("shell_autocomplete_response", self._handle_completions_response, True)

    def request_completions(self, event=None) -> None:
        if self._box_is_visible():
            self._completions_box.request_details()
            return

        text = editor_helpers.get_active_text_widget()
        if text:
            self.request_completions_for_text(text)
        else:
            get_workbench().bell()

    def _should_open_box_automatically(self, event):
        assert isinstance(event.widget, tk.Text)
        if not get_workbench().get_option("edit.automatic_completions"):
            return False

        # Don't autocomplete inside comments
        line_prefix = event.widget.get("insert linestart", "insert")
        if "#" in line_prefix:
            # not very precise (eg. when inside a string), but good enough
            return False

        return True

    def _box_is_visible(self):
        if not self._completions_box:
            return False

        return self._completions_box.is_visible()

    def _close_box(self):
        if self._completions_box:
            self._completions_box.hide()

    def _on_keypress(self, event: tk.Event) -> None:
        self.cancel_active_request()
        runner = get_runner()
        if not runner or runner.is_running():
            return

        if (
            control_is_pressed(event)
            or command_is_pressed(event)
            or alt_is_pressed_without_char(event)
        ):
            return

        widget = event.widget
        if not widget or not isinstance(widget, SyntaxText):
            return

        if not widget.is_python_text():
            return

        if widget.is_read_only():
            return

        if not self._box_is_visible() and not self._should_open_box_automatically(event):
            return

        if event.keysym == "Escape":
            # Closing is handled by the box itself
            return

        if not event.char:
            # movement keypresses are handled by the box
            return

        if (
            not self._box_is_visible()
            and not _is_python_name_char(event.char)
            and not self._is_start_of_an_attribute(event)
        ):
            # non-word chars are allowed only while the box is already open
            return

        widget.after_idle(lambda: self.request_completions_for_text(widget))

    def _is_start_of_an_attribute(self, event: tk.Event) -> bool:
        if event.char != ".":
            return False

        text = cast(tk.Text, event.widget)
        preceding = text.get("insert -2 chars")
        if preceding.isnumeric():
            return False

        return True

    def cancel_active_request(self) -> None:
        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is not None:
            # TODO: actually cancel
            ls_proxy.unbind_request_handler(self._handle_completions_response)

    def request_completions_for_text(self, text: SyntaxText) -> None:
        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is None:
            return

        ls_proxy.unbind_request_handler(self._handle_completions_response)
        # TODO: cancel last unhandled request

        if isinstance(text, ShellText):
            text.send_changes_to_language_server()
            uri = text.get_ls_uri()
            position = editor_helpers.get_cursor_ls_position(
                text, text.get_current_line_ls_offset(), text.get_current_column_ls_offset()
            )
        else:
            editor = get_workbench().get_editor_notebook().get_current_editor()
            if editor.get_text_widget() is not text:
                logger.warning("Unexpected completions request in %r", text)
                return

            editor.send_changes_to_primed_servers()
            uri = editor.get_uri()
            position = editor_helpers.get_cursor_ls_position(text)

        if uri is None:
            # TODO:
            return

        self._last_request_text = text
        ls_proxy.request_completion(
            CompletionParams(textDocument=TextDocumentIdentifier(uri=uri), position=position),
            self._handle_completions_response,
        )

    def _handle_completions_response(
        self,
        response: LspResponse[
            Union[List[lsp_types.CompletionItem], lsp_types.CompletionList, None]
        ],
    ) -> None:
        error = response.get_error()
        if error is not None:
            self._close_box()
            messagebox.showerror("Autocomplete error", error.message, master=get_workbench())
            return

        if not self._last_request_text:
            logger.warning("Completions response without _last_request_text")
            return

        result = response.get_result_or_raise()
        if result is None:
            logger.info("None completions response")
            return

        completions: List[lsp_types.CompletionItem]
        if isinstance(result, list):
            completions = result
            is_incomplete = False
            item_defaults = None
        else:
            completions = result.items
            is_incomplete = result.isIncomplete
            item_defaults = result.itemDefaults

        assert not item_defaults

        if len(completions) == 0:
            # the user typed something which is not completable
            self._close_box()
            return
        else:
            # Log completion count
            logger.info(f"📥 LSP: {len(completions)} completions")
            
            # Show completions
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)

    def _rerank_completions_with_ai_async_and_show(self, completions: List[lsp_types.CompletionItem], text: SyntaxText) -> None:
        """Rerank completions using AI in background, then show (non-blocking - UI doesn't freeze!)"""
        import threading
        from thonny.plugins.base_assistant import get_ai_assistant
        
        # Mark AI request as in progress
        self._ai_request_in_progress = True
        logger.info(f"🔒 AI request started (blocking new requests)")
        
        # Get AI assistant
        assistant = get_ai_assistant()
        if not assistant:
            logger.info("No AI assistant available, showing completions immediately")
            self._ai_request_in_progress = False  # Release lock
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)  # Will apply our sorting
            return
        
        try:
            # Step 1: Apply our smart sorting (local variables first, etc.)
            prefix_start_index = text.tag_ranges("sel")
            if prefix_start_index:
                prefix_start_index = prefix_start_index[0]
            else:
                prefix_start_index = self._completions_box._find_completion_insertion_index() if self._completions_box else text.index("insert")
            
            prefix = text.get(prefix_start_index, "insert") if text.compare(prefix_start_index, "<=", "insert") else ""
            
            # Get context for context-aware ranking
            try:
                line_before_cursor = text.get("insert linestart", "insert")
                line_after_cursor = text.get("insert", "insert lineend")
                source_code = text.get("1.0", "end")
            except:
                line_before_cursor = ""
                line_after_cursor = ""
                source_code = ""
            
            # Use shared context-aware sorting logic
            logger.info(f"🔄 Applying context-aware sort to {len(completions)} completions (AI path)")
            sort_key = create_context_aware_sort_key(prefix, line_before_cursor, line_after_cursor, source_code)
            sorted_completions = sorted(completions, key=sort_key)
            
            logger.info(f"📋 Top 20 after context-aware sort:")
            for i, item in enumerate(sorted_completions[:20]):
                kind_name = lsp_types.CompletionItemKind(item.kind).name if item.kind else "Unknown"
                detail_str = f" ({item.detail[:20]}...)" if item.detail and len(item.detail) > 20 else f" ({item.detail})" if item.detail else ""
                logger.info(f"  [{i+1:2d}] {item.label:25s} | {kind_name:12s}{detail_str}")
            if len(sorted_completions) > 20:
                logger.info(f"  ... and {len(sorted_completions) - 20} more")
            logger.info(f"━" * 80)
            
            # Step 2: Take top 50 for AI reranking
            top_completions = sorted_completions[:50]
            
            # Extract labels and kinds
            labels = [item.label for item in top_completions]
            completion_kinds = {}
            for item in top_completions:
                if item.kind:
                    kind_name = lsp_types.CompletionItemKind(item.kind).name
                    completion_kinds[item.label] = kind_name
            
            logger.info(f"🤖 Sending top {len(labels)} to AI for reranking")
            
            # Step 3: Get reasonable context (last 100 lines or less)
            try:
                cursor_index = text.index("insert")
                cursor_line_num = int(cursor_index.split(".")[0])
                
                # Get last 100 lines (or from start if file is small)
                context_start_line = max(1, cursor_line_num - 100)
                code_context = text.get(f"{context_start_line}.0", cursor_index)
                cursor_line = text.get(f"{cursor_line_num}.0", cursor_index)
                
                logger.info(f"📝 Sending context: {len(code_context)} chars, lines {context_start_line}-{cursor_line_num}")
                logger.info(f"   Current line: '{cursor_line}' ← cursor here")
                
            except Exception as e:
                logger.warning(f"Failed to get full context: {e}")
                code_context = text.get("1.0", "end")
                cursor_line = ""
            
            # Remember current request to detect if it's stale
            request_text = text
            original_completions_list = sorted_completions
            
            # Step 4: Call AI in BACKGROUND THREAD (non-blocking!)
            logger.info(f"⏳ Starting AI request in background (UI не зависає!)...")
            
            def do_ai_reranking():
                try:
                    reranked_labels = assistant.rerank_completions(
                        code_context=code_context,
                        cursor_line=cursor_line,
                        completions=labels,
                        max_results=len(labels),  # Rerank ALL top-50
                        completion_kinds=completion_kinds
                    )
                    
                    logger.info(f"✅ AI returned {len(reranked_labels)} labels")
                    
                    # Step 5: Reorder based on AI ranking
                    label_to_item = {item.label: item for item in top_completions}
                    reordered = []
                    seen = set()
                    
                    for label in reranked_labels:
                        if label in label_to_item and label not in seen:
                            reordered.append(label_to_item[label])
                            seen.add(label)
                    
                    # Add any remaining from top-50 that AI didn't include
                    for item in top_completions:
                        if item.label not in seen:
                            reordered.append(item)
                    
                    # Add rest of completions (beyond top-50) at the end
                    for item in original_completions_list[50:]:
                        reordered.append(item)
                    
                    logger.info(f"📤 Final reranked list ({len(reordered)} items):")
                    for i, comp in enumerate(reordered[:20]):
                        kind_name = lsp_types.CompletionItemKind(comp.kind).name if comp.kind else "Unknown"
                        logger.info(f"  [{i:2d}] {comp.label:30s} | {kind_name:12s}")
                    if len(reordered) > 20:
                        logger.info(f"  ... and {len(reordered) - 20} more")
                    logger.info(f"━" * 80)
                    
                    # Show completions in UI thread
                    def show_completions():
                        try:
                            # Check if request is still valid (user didn't type more)
                            if self._last_request_text == request_text:
                                if not self._completions_box:
                                    self._completions_box = CompletionsBox(self)
                                # Pass skip_sorting=True so AI order is preserved!
                                self._completions_box.present_completions(request_text, reordered, skip_sorting=True)
                                logger.info(f"✅ Completions box shown to user (with AI sorting)")
                            else:
                                logger.info(f"⏭️  AI response ignored (user typed more, request stale)")
                        finally:
                            # Always release the lock
                            self._ai_request_in_progress = False
                            logger.info(f"🔓 AI request finished (accepting new requests)")
                    
                    # Schedule showing in UI thread
                    get_workbench().after(0, show_completions)
                    
                except Exception as e:
                    logger.exception(f"❌ AI reranking failed: {e}")
                    # Fallback: show original completions (pre-sorted by our algorithm)
                    def show_fallback():
                        try:
                            if self._last_request_text == request_text:
                                if not self._completions_box:
                                    self._completions_box = CompletionsBox(self)
                                # Original list is already sorted by our algorithm, skip re-sorting
                                self._completions_box.present_completions(request_text, original_completions_list, skip_sorting=True)
                        finally:
                            # Always release the lock
                            self._ai_request_in_progress = False
                            logger.info(f"🔓 AI request finished (error fallback, accepting new requests)")
                    get_workbench().after(0, show_fallback)
            
            # Start background thread
            thread = threading.Thread(target=do_ai_reranking, daemon=True)
            thread.start()
            # Return immediately - UI не зависає!
            
        except Exception as e:
            logger.exception(f"❌ AI reranking setup failed: {e}")
            # Release lock
            self._ai_request_in_progress = False
            logger.info(f"🔓 AI request failed to start (accepting new requests)")
            # Fallback: show completions immediately (without sorting - will be sorted by present_completions)
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)  # Let it sort naturally
    
    def _rerank_completions_with_ai_async(self, completions: List[lsp_types.CompletionItem], text: SyntaxText) -> None:
        """Rerank completions using AI in background (non-blocking)"""
        import threading
        from thonny.plugins.base_assistant import get_ai_assistant
        
        # Get AI assistant
        assistant = get_ai_assistant()
        if not assistant:
            return  # No AI available
        
        # Extract labels and kinds from completions
        labels = [item.label for item in completions]
        completion_kinds = {}
        for item in completions:
            if item.kind:
                kind_name = lsp_types.CompletionItemKind(item.kind).name
                completion_kinds[item.label] = kind_name
        
        logger.info(f"🤖 Starting AI reranking for {len(labels)} completions:")
        logger.info(f"   All labels: {labels}")
        logger.info(f"   With types: {completion_kinds}")
        
        # Get code context (10 lines before and after cursor)
        try:
            cursor_index = text.index("insert")
            cursor_line_num = int(cursor_index.split(".")[0])
            
            # Get surrounding lines
            start_line = max(1, cursor_line_num - 10)
            end_line = cursor_line_num + 10
            
            code_context = text.get(f"{start_line}.0", f"{end_line}.0")
            cursor_line = text.get(f"{cursor_line_num}.0", f"{cursor_line_num}.end")
            
            logger.info(f"📝 Code context (lines {start_line}-{end_line}, cursor at line {cursor_line_num}):")
            logger.info(f"━" * 80)
            logger.info(code_context)
            logger.info(f"   Current line: '{cursor_line}' ← cursor here")
            logger.info(f"━" * 80)
            
        except:
            # Fallback: use whole file
            code_context = text.get("1.0", "end")
            cursor_line = ""
            logger.info(f"⚠️  Failed to get cursor context, using whole file")
        
        # Remember current request to detect if it's stale
        request_text = text
        original_completions = completions
        
        def do_reranking():
            try:
                reranked_labels = assistant.rerank_completions(
                    code_context=code_context,
                    cursor_line=cursor_line,
                    completions=labels,
                    max_results=15,  # Limit to top 15
                    completion_kinds=completion_kinds  # Pass type information
                )
                
                # Update UI in main thread
                def update_ui():
                    # Check if completions box is still open and for the same text widget
                    if (self._completions_box and 
                        self._completions_box.winfo_exists() and 
                        self._last_request_text == request_text):
                        
                        logger.info(f"✅ AI returned {len(reranked_labels)} labels: {reranked_labels}")
                        self._completions_box.update_order_from_ai(reranked_labels, original_completions)
                    else:
                        logger.info(f"⏭️  AI response ignored (completions box closed or stale)")
                        logger.info(f"   Box exists: {self._completions_box is not None and self._completions_box.winfo_exists()}, Same text: {self._last_request_text == request_text}")
                
                # Schedule UI update in main thread
                if self._completions_box:
                    get_workbench().after(0, update_ui)
                    
            except Exception as e:
                logger.info(f"❌ AI reranking failed (async): {e}")
        
        # Start background thread (no join - truly async!)
        thread = threading.Thread(target=do_reranking, daemon=True)
        thread.start()
    
    def patched_perform_midline_tab(self, event):
        self.cancel_active_request()

        if not event or not isinstance(event.widget, SyntaxText):
            return
        text = event.widget

        if text.is_python_text():
            if isinstance(text, ShellText):
                option_name = "edit.tab_request_completions_in_shell"
            else:
                option_name = "edit.tab_request_completions_in_editors"

            if get_workbench().get_option(option_name):
                if not text.has_selection():
                    self.request_completions_for_text(text)
                    return "break"
                else:
                    return None

        return text.perform_dumb_tab(event)


def _is_python_name_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def load_plugin() -> None:
    completer = Completer()

    def can_complete():
        runner = get_runner()
        return runner and not runner.is_running()

    get_workbench().add_command(
        "autocomplete",
        "edit",
        tr("Auto-complete"),
        completer.request_completions,
        default_sequence="<Control-space>",
        tester=can_complete,
    )

    get_workbench().set_default("edit.tab_request_completions_in_editors", True)
    get_workbench().set_default("edit.tab_request_completions_in_shell", True)
    get_workbench().set_default("edit.automatic_completions", False)
    get_workbench().set_default("edit.automatic_completion_details", False)

    CodeViewText.perform_midline_tab = completer.patched_perform_midline_tab
    ShellText.perform_midline_tab = completer.patched_perform_midline_tab
