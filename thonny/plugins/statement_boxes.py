"""
Highlights code blocks (functions, if, for, while, etc.) when cursor/mouse is inside them.
"""

from logging import getLogger

from thonny import get_workbench

logger = getLogger(__name__)


class BlockHighlighter:
    """Highlights the current code block under cursor/mouse with a very light gray background"""
    
    def __init__(self, text):
        self.text = text
        self.blocks = []  # List of (tag_name, start_line, start_col, end_line, end_col, depth)
        self.current_block = None
        self._update_scheduled = False
        
        # Configure highlight tag - light gray
        self.text.tag_configure("current_block", background="#d0d0d0")
        self.text.tag_lower("current_block")  # Below selection and other tags
        
        # Bind cursor and mouse movement
        self.text.bind("<KeyPress>", self._on_cursor_move, True)
        self.text.bind("<KeyRelease>", self._on_cursor_move, True) 
        self.text.bind("<ButtonPress>", self._on_cursor_move, True)
        self.text.bind("<Motion>", self._on_mouse_move, True)
    
    def get_blocks(self):
        """Parse code with parso and find all blocks (functions, if, for, while, etc.)"""
        import parso
        from parso.python import tree
        
        blocks = []
        source = self.text.get("1.0", "end-1c")
        
        try:
            module = parso.parse(source)
        except Exception:
            logger.exception("Failed to parse code")
            return []
        
        def is_block(node):
            """Check if node is a block we want to highlight"""
            # Flow includes: if, while, for, try, with
            # Scope includes: Function, Class, Lambda
            return isinstance(node, (tree.Function, tree.Class, tree.Flow, tree.Scope))
        
        def collect_blocks(node, depth=0):
            """Recursively collect all blocks with their positions"""
            if is_block(node):
                start_line, start_col = node.start_pos
                end_line, end_col = node.end_pos
                
                # Create unique tag name for this block
                tag_name = f"block_{start_line}_{start_col}_{end_line}_{end_col}"
                blocks.append((tag_name, start_line, start_col, end_line, end_col, depth))
                
                # Recurse with increased depth
                if hasattr(node, "children"):
                    for child in node.children:
                        collect_blocks(child, depth + 1)
            elif hasattr(node, "children"):
                # Not a block, but recurse through children
                for child in node.children:
                    collect_blocks(child, depth)
        
        collect_blocks(module)
        return blocks
    
    def update_blocks(self):
        """Re-parse code and update block positions"""
        # Remove all old block tags
        for tag_name, _, _, _, _, _ in self.blocks:
            self.text.tag_remove(tag_name, "1.0", "end")
        
        # Get new blocks
        self.blocks = self.get_blocks()
        
        # Add tags for each block (but don't highlight yet)
        for tag_name, start_line, start_col, end_line, end_col, _ in self.blocks:
            start = f"{start_line}.{start_col}"
            end = f"{end_line}.{end_col}" if end_col > 0 else f"{end_line}.end"
            self.text.tag_add(tag_name, start, end)
    
    def find_deepest_block_at_cursor(self):
        """Find the deepest (most nested) block containing the cursor"""
        try:
            cursor_pos = self.text.index("insert")
            cursor_line, cursor_col = map(int, cursor_pos.split("."))
        except Exception:
            return None
        
        # Find all blocks containing cursor, pick the deepest one
        deepest_block = None
        max_depth = -1
        
        for tag_name, start_line, start_col, end_line, end_col, depth in self.blocks:
            # Check if cursor is inside this block
            if start_line <= cursor_line <= end_line:
                # For start line, check column
                if cursor_line == start_line and cursor_col < start_col:
                    continue
                # For end line, check column
                if cursor_line == end_line and end_col > 0 and cursor_col >= end_col:
                    continue
                
                # Cursor is inside this block
                if depth > max_depth:
                    max_depth = depth
                    deepest_block = tag_name
        
        return deepest_block
    
    def highlight_current_block(self):
        """Highlight the block under cursor - vertical line at block start column"""
        # Find deepest block at cursor
        block = self.find_deepest_block_at_cursor()
        
        # Only update if block changed
        if block == self.current_block:
            return
        
        # Clear previous highlight
        self.text.tag_remove("current_block", "1.0", "end")
        self.current_block = block
        
        # Apply new highlight if we have a block
        if block:
            # Get ranges of this block and apply highlight
            for tag_name, start_line, start_col, end_line, end_col, _ in self.blocks:
                if tag_name == block:
                    # Highlight vertical line at column start_col for all lines in block
                    for line in range(start_line, end_line + 1):
                        # Get line content to check if position exists
                        line_content = self.text.get(f"{line}.0", f"{line}.end")
                        
                        # Check if line has enough content
                        if len(line_content) > start_col:
                            # Normal case - highlight character at start_col
                            char_start = f"{line}.{start_col}"
                            char_end = f"{line}.{start_col + 1}"
                            self.text.tag_add("current_block", char_start, char_end)
                        elif len(line_content) > 0:
                            # Line is too short but not empty - highlight from end to newline
                            char_start = f"{line}.{len(line_content)}"
                            char_end = f"{line}.end"
                            self.text.tag_add("current_block", char_start, char_end)
                        else:
                            # Empty line - highlight the whole empty line (newline character)
                            char_start = f"{line}.0"
                            char_end = f"{line}.end"
                            self.text.tag_add("current_block", char_start, char_end)
                    break
    
    def _on_cursor_move(self, event=None):
        """Called when cursor moves (keyboard)"""
        self.highlight_current_block()
    
    def _on_mouse_move(self, event=None):
        """Called when mouse moves"""
        self.highlight_current_block()
    
    def schedule_update(self):
        """Schedule block update (after text changes)"""
        def perform_update():
            try:
                self.update_blocks()
                # Reset current block so next cursor move will re-highlight
                self.current_block = None
                self.highlight_current_block()
            finally:
                self._update_scheduled = False
        
        if not self._update_scheduled:
            self._update_scheduled = True
            # Delay update to avoid too frequent reparsing
            self.text.after(100, perform_update)


def update_blocks(event):
    """Called when text changes"""
    if not get_workbench().ready:
        return
    
    if hasattr(event, "text_widget"):
        text = event.text_widget
    elif hasattr(event, "widget"):
        text = event.widget
    else:
        return
    
    if not hasattr(text, "block_highlighter"):
        text.block_highlighter = BlockHighlighter(text)
        # Initial update
        text.block_highlighter.schedule_update()
    else:
        text.block_highlighter.schedule_update()


def init_highlighter(event):
    """Initialize highlighter for newly opened editor"""
    if not get_workbench().ready:
        return
    
    if hasattr(event, "editor"):
        text = event.editor.get_text_widget()
    else:
        return

    if not hasattr(text, "block_highlighter"):
        text.block_highlighter = BlockHighlighter(text)
        # Initial update after a short delay to let editor finish loading
        text.after(200, text.block_highlighter.schedule_update)


def load_plugin() -> None:
    wb = get_workbench()
    wb.set_default("view.block_highlighting", True)
    wb.bind_class("CodeViewText", "<<TextChange>>", update_blocks, True)
    # Initialize when editor opens
    wb.bind("Open", init_highlighter, True)
    wb.bind("EditorTextCreated", init_highlighter, True)
