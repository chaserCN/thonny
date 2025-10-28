"""
Highlights matching control flow keywords (if-elif-else, try-except-finally, etc.)
when clicking on them.
"""
import time
import tkinter as tk
from logging import getLogger
import parso

from thonny import get_workbench
from thonny.codeview import CodeViewText

logger = getLogger(__name__)


class KeywordMatcher:
    """Highlights related control flow keywords on click"""
    
    def __init__(self, text: CodeViewText):
        self.text = text
        self._request_scheduled = False
        self._last_highlight_time = 0
        
        # Configure highlight tag - same style as matched_name
        self.text.tag_configure(
            "matched_keyword",
            background="#e6ecfe"  # Same light blue as variable highlighting
        )
        
        # Bind click event
        self.text.bind("<Button-1>", self._on_click, add=True)
        
        # Clear on cursor move and text change (like highlight_names)
        self.text.bind("<<CursorMove>>", self._schedule_clear, add=True)
        self.text.bind("<<TextChange>>", self._clear_highlights, add=True)
    
    def _on_click(self, event):
        """Handle click in editor"""
        try:
            # Get click position
            index = self.text.index(f"@{event.x},{event.y}")
            line, col = map(int, index.split("."))
            
            # Check if clicked on a keyword
            keyword_range = self._get_keyword_at_position(line, col)
            if not keyword_range:
                self._clear_highlights()
                return
            
            keyword, start_pos, end_pos = keyword_range
            
            # Only handle control flow keywords
            if keyword not in ["if", "elif", "else", "try", "except", "finally", "for", "while", "with"]:
                self._clear_highlights()
                return
            
            # Find and highlight related keywords
            self._highlight_related_keywords(line, col, keyword)
            
        except Exception as e:
            logger.exception("Error in keyword matching", exc_info=e)
    
    def _get_keyword_at_position(self, line, col):
        """Get keyword at given position, returns (keyword, start_pos, end_pos) or None"""
        try:
            # Get the word at position
            word_start = self.text.index(f"{line}.{col} wordstart")
            word_end = self.text.index(f"{line}.{col} wordend")
            word = self.text.get(word_start, word_end)
            
            # Check if it's a Python keyword
            import keyword as kw
            if word in kw.kwlist:
                return (word, word_start, word_end)
            
            return None
        except:
            return None
    
    def _highlight_related_keywords(self, line, col, clicked_keyword):
        """Find and highlight all related keywords"""
        try:
            # Clear previous highlights
            self._clear_highlights()
            
            # Get source code
            source = self.text.get("1.0", "end-1c")
            if not source.strip():
                return
            
            # Parse with parso
            try:
                tree = parso.parse(source)
            except Exception as e:
                logger.debug(f"Parso parse error: {e}")
                return
            
            # Find the node at clicked position
            target_node = self._find_node_at_position(tree, line, col)
            if not target_node:
                return
            
            # Find the statement node containing this keyword
            statement_node = self._find_statement_node(target_node, clicked_keyword)
            if not statement_node:
                return
            
            # Extract and highlight all related keywords
            keywords = self._extract_keywords_from_statement(statement_node, clicked_keyword)
            
            for kw_line, kw_start_col, kw_end_col in keywords:
                start_index = f"{kw_line}.{kw_start_col}"
                end_index = f"{kw_line}.{kw_end_col}"
                self.text.tag_add("matched_keyword", start_index, end_index)
            
            # Remember when we highlighted
            self._last_highlight_time = time.time()
                
        except Exception as e:
            logger.exception("Error highlighting related keywords", exc_info=e)
    
    def _find_node_at_position(self, tree, line, col):
        """Find AST node at given position"""
        def search(node):
            if not hasattr(node, 'start_pos') or not hasattr(node, 'end_pos'):
                return None
            
            start_line, start_col = node.start_pos
            end_line, end_col = node.end_pos
            
            # Check if position is within this node
            if start_line <= line <= end_line:
                if start_line == line and col < start_col:
                    return None
                if end_line == line and col >= end_col:
                    return None
                
                # Search children first (find most specific node)
                if hasattr(node, 'children'):
                    for child in node.children:
                        result = search(child)
                        if result:
                            return result
                
                return node
            
            return None
        
        return search(tree)
    
    def _find_statement_node(self, node, clicked_keyword):
        """Find the if_stmt, try_stmt, etc. node that contains this keyword"""
        # Map keywords to their statement types
        keyword_to_type = {
            'if': 'if_stmt',
            'elif': 'if_stmt',
            'else': ['if_stmt', 'try_stmt', 'for_stmt', 'while_stmt'],
            'try': 'try_stmt',
            'except': 'try_stmt',
            'finally': 'try_stmt',
            'for': 'for_stmt',
            'while': 'while_stmt',
            'with': 'with_stmt',
        }
        
        target_types = keyword_to_type.get(clicked_keyword)
        if not target_types:
            return None
        
        if not isinstance(target_types, list):
            target_types = [target_types]
        
        # Walk up the tree to find the statement
        current = node
        depth = 0
        while current:
            if hasattr(current, 'type') and current.type in target_types:
                return current
            
            current = current.parent if hasattr(current, 'parent') else None
            depth += 1
            if depth > 50:
                break
        
        return None
    
    def _extract_keywords_from_statement(self, node, clicked_keyword):
        """Extract positions of all related keywords from a statement node"""
        keywords = []
        
        if node.type == 'if_stmt':
            keywords = self._extract_if_keywords(node)
        elif node.type == 'try_stmt':
            keywords = self._extract_try_keywords(node)
        elif node.type in ['for_stmt', 'while_stmt']:
            keywords = self._extract_loop_keywords(node)
        elif node.type == 'with_stmt':
            keywords = self._extract_with_keywords(node)
        
        return keywords
    
    def _extract_if_keywords(self, node):
        """Extract if, elif, else keywords from if_stmt"""
        keywords = []
        
        if not hasattr(node, 'children'):
            return keywords
        
        for child in node.children:
            if hasattr(child, 'type') and child.type == 'keyword':
                if child.value in ['if', 'elif', 'else']:
                    line, col = child.start_pos
                    end_col = col + len(child.value)
                    keywords.append((line, col, end_col))
        
        return keywords
    
    def _extract_try_keywords(self, node):
        """Extract try, except, finally keywords from try_stmt"""
        keywords = []
        
        if not hasattr(node, 'children'):
            return keywords
        
        for child in node.children:
            if hasattr(child, 'type'):
                if child.type == 'keyword' and child.value in ['try', 'finally']:
                    line, col = child.start_pos
                    end_col = col + len(child.value)
                    keywords.append((line, col, end_col))
                elif child.type == 'except_clause':
                    # Find 'except' keyword in except_clause
                    for subchild in child.children:
                        if hasattr(subchild, 'type') and subchild.type == 'keyword' and subchild.value == 'except':
                            line, col = subchild.start_pos
                            end_col = col + len(subchild.value)
                            keywords.append((line, col, end_col))
                            break
        
        return keywords
    
    def _extract_loop_keywords(self, node):
        """Extract for/while and optional else from loop statements"""
        keywords = []
        
        if not hasattr(node, 'children'):
            return keywords
        
        for child in node.children:
            if hasattr(child, 'type') and child.type == 'keyword':
                if child.value in ['for', 'while', 'else']:
                    line, col = child.start_pos
                    end_col = col + len(child.value)
                    keywords.append((line, col, end_col))
        
        return keywords
    
    def _extract_with_keywords(self, node):
        """Extract with keyword"""
        keywords = []
        
        if not hasattr(node, 'children'):
            return keywords
        
        for child in node.children:
            if hasattr(child, 'type') and child.type == 'keyword' and child.value == 'with':
                line, col = child.start_pos
                end_col = col + len(child.value)
                keywords.append((line, col, end_col))
        
        return keywords
    
    def _schedule_clear(self, event=None):
        """Schedule clearing highlights with delay (like highlight_names)"""
        # Don't clear immediately after highlighting
        if time.time() - self._last_highlight_time < 1.0:
            return
        
        if self._request_scheduled:
            return
        
        def consider_clear():
            if time.time() - self.text.get_last_operation_time() < 0.3:
                # wait a bit more, there may be more cursor movements coming
                self.text.after(100, consider_clear)
            else:
                try:
                    self._clear_highlights()
                finally:
                    self._request_scheduled = False
        
        self._request_scheduled = True
        self.text.after_idle(consider_clear)
    
    def _clear_highlights(self, event=None):
        """Remove all keyword highlights"""
        self.text.tag_remove("matched_keyword", "1.0", "end")


def init_keyword_matcher(event):
    """Initialize keyword matcher for a CodeView text widget"""
    if not get_workbench().ready:
        return
    
    if hasattr(event, "editor"):
        text = event.editor.get_text_widget()
    else:
        return
    
    if not hasattr(text, 'keyword_matcher'):
        text.keyword_matcher = KeywordMatcher(text)


def load_plugin():
    """Load the keyword matcher plugin"""
    wb = get_workbench()
    wb.bind("Open", init_keyword_matcher, True)
    wb.bind("EditorTextCreated", init_keyword_matcher, True)

