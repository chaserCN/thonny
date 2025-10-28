"""
Highlights code blocks (functions, if, for, while, etc.) in the gutter with depth-based purple gradient.
"""

import logging
from logging import getLogger

from thonny import get_workbench

logger = getLogger(__name__)
# Uncomment to enable debug logging:
# logger.setLevel(logging.DEBUG)


class BlockHighlighter:
    """Highlights all code blocks (functions, if, for, while, etc.) in the gutter with depth-based purple gradient"""
    
    def __init__(self, text):
        self.text = text
        self.blocks = []  # List of (tag_name, start_line, start_col, end_line, end_col, depth)
        self._update_scheduled = False
        
        # Get gutter widget (line numbers panel)
        self.gutter = text.master._gutter
        
        # Configure highlight tags in gutter - purple gradient by depth
        # Lighter purple for outer blocks, darker for inner blocks
        self.depth_colors = [
            "#f5ebff",  # depth 0 - very light purple
            "#ead5ff",  # depth 1
            "#dfbfff",  # depth 2
            "#d4aaff",  # depth 3
            "#c994ff",  # depth 4
            "#be7eff",  # depth 5+
        ]
        
        for i, color in enumerate(self.depth_colors):
            self.gutter.tag_configure(f"block_line_depth_{i}", background=color)
        
        # Lower priority so other gutter elements (breakpoints, text) are visible on top
        for i in range(len(self.depth_colors)):
            self.gutter.tag_lower(f"block_line_depth_{i}")
        
        # Subscribe to breakpoint changes to reapply highlights
        self.text.bind("<<BreakpointChange>>", self._on_breakpoint_change, True)
    
    def get_blocks(self):
        """Parse code with parso and find all blocks (functions, if, for, while, etc.)"""
        import parso
        from parso.python import tree
        
        blocks = []
        source = self.text.get("1.0", "end-1c")
        source_lines = source.split('\n')  # Split once, reuse for all blocks
        
        try:
            module = parso.parse(source)
        except Exception:
            logger.exception("Failed to parse code")
            return []
        
        def is_block(node):
            """Check if node is a block we want to highlight"""
            # Skip file_input (entire file) and module
            if hasattr(node, 'type') and node.type in ('file_input', 'module'):
                return False
            # Flow includes: if, while, for, try, with
            # Scope includes: Function, Class, Lambda
            return isinstance(node, (tree.Function, tree.Class, tree.Flow, tree.Scope))
        
        def collect_blocks(node, depth=0):
            """Recursively collect all blocks with their positions"""
            # Skip file_input/module but recurse through their children
            skip_but_recurse = hasattr(node, 'type') and node.type in ('file_input', 'module')
            
            if is_block(node) and not skip_but_recurse:
                start_line, start_col = node.start_pos
                end_line, end_col = node.end_pos
                
                node_type = getattr(node, 'type', node.__class__.__name__)
                logger.info(f"Found block: {node_type} at ({start_line},{start_col})-({end_line},{end_col}), depth={depth}")
                
                # If end_col is 0, it means end_pos is at the start of the next line
                # We need to adjust to the end of the previous line
                if end_col == 0 and end_line > start_line:
                    end_line = end_line - 1
                    logger.debug(f"  Adjusted end to line {end_line} (was pointing to start of next line)")
                
                # Extend to include trailing empty/whitespace lines
                # that have indentation > the block's start column
                original_end = end_line
                
                # Check lines after end_line
                for line_num in range(end_line, len(source_lines)):
                    line = source_lines[line_num]
                    
                    # Calculate indentation
                    if line:
                        indent = len(line) - len(line.lstrip())
                    else:
                        # Completely empty line (no characters at all)
                        indent = 0
                    
                    # If line is empty or whitespace-only
                    if not line.strip():
                        # Completely empty line (0 chars) - NOT in block
                        if not line:
                            logger.debug(f"  Line {line_num + 1} is completely empty, ending block")
                            break
                        # Whitespace-only - check if indentation is enough
                        elif indent > start_col:
                            logger.debug(f"  Line {line_num + 1} has indent={indent} > {start_col}, including in block")
                            end_line = line_num + 1
                            continue
                        else:
                            logger.debug(f"  Line {line_num + 1} has indent={indent} <= {start_col}, ending block")
                            break
                    
                    # Non-empty line with code - check if it's more indented than block start
                    if indent > start_col:
                        # This line is more indented, include it
                        logger.debug(f"  Line {line_num + 1} has indent={indent} > {start_col}, including in block")
                        end_line = line_num + 1
                    else:
                        # Less or equal indentation - block ends
                        logger.debug(f"  Line {line_num + 1} has indent={indent} <= {start_col}, ending block")
                        break
                
                if end_line != original_end:
                    logger.debug(f"  Extended block to line {end_line} (from {original_end}) to include trailing whitespace")
                
                # Create unique tag name for this block
                tag_name = f"block_{start_line}_{start_col}_{end_line}_{end_col}"
                blocks.append((tag_name, start_line, start_col, end_line, end_col, depth))
                logger.info(f"  Added block: lines {start_line}-{end_line}")
                
                # Recurse with increased depth
                if hasattr(node, "children"):
                    for child in node.children:
                        collect_blocks(child, depth + 1)
            elif hasattr(node, "children"):
                # Not a block (or skipped file_input), recurse through children with same depth
                for child in node.children:
                    collect_blocks(child, depth)
        
        collect_blocks(module)
        return blocks
    
    def update_blocks(self):
        """Re-parse code and update block positions and highlights"""
        logger.info("=" * 60)
        logger.info("UPDATE_BLOCKS called")
        
        # Clear all previous highlights in gutter
        for i in range(len(self.depth_colors)):
            self.gutter.tag_remove(f"block_line_depth_{i}", "1.0", "end")
        
        # Get new blocks
        self.blocks = self.get_blocks()
        logger.info(f"Total blocks found: {len(self.blocks)}")
        
        # Sort blocks by depth (shallowest first) so deeper blocks are applied last and appear on top
        sorted_blocks = sorted(self.blocks, key=lambda b: b[5])  # Sort by depth, shallowest first
        
        # Highlight blocks in gutter
        for tag_name, start_line, start_col, end_line, end_col, depth in sorted_blocks:
            # Highlight in gutter with depth-based color
            color_index = min(depth, len(self.depth_colors) - 1)
            tag = f"block_line_depth_{color_index}"
            
            logger.info(f"Highlighting lines {start_line}-{end_line}, start_col={start_col}, depth={depth}, color_index={color_index}, color={self.depth_colors[color_index]}")
            
            for line in range(start_line, end_line + 1):
                gutter_start = f"{line}.0"
                gutter_end = f"{line}.end"
                self.gutter.tag_add(tag, gutter_start, gutter_end)
        
        # Lower all block tags below text and breakpoints (in reverse order to maintain depth priority)
        for i in range(len(self.depth_colors) - 1, -1, -1):
            self.gutter.tag_lower(f"block_line_depth_{i}")
        
        logger.debug("=" * 60)
    
    def _reapply_highlights(self, event=None):
        """Reapply block highlights without reparsing - called after breakpoint changes"""
        if not self.blocks:
            return
        
        logger.debug("Reapplying highlights after gutter change")
        
        # Clear all highlights first
        for i in range(len(self.depth_colors)):
            self.gutter.tag_remove(f"block_line_depth_{i}", "1.0", "end")
        
        # Sort blocks by depth (shallowest first) so deeper blocks are applied last and appear on top
        sorted_blocks = sorted(self.blocks, key=lambda b: b[5])  # Sort by depth, shallowest first
        
        # Reapply all block highlights
        for tag_name, start_line, start_col, end_line, end_col, depth in sorted_blocks:
            color_index = min(depth, len(self.depth_colors) - 1)
            tag = f"block_line_depth_{color_index}"
            
            for line in range(start_line, end_line + 1):
                gutter_start = f"{line}.0"
                gutter_end = f"{line}.end"
                self.gutter.tag_add(tag, gutter_start, gutter_end)
        
        # Lower all block tags below text and breakpoints (in reverse order to maintain depth priority)
        for i in range(len(self.depth_colors) - 1, -1, -1):
            self.gutter.tag_lower(f"block_line_depth_{i}")
    
    def _on_breakpoint_change(self, event=None):
        """Called when breakpoint is toggled - reapply highlights after gutter update"""
        # Use after_idle to reapply after gutter update completes
        self.text.after_idle(self._reapply_highlights)
    
    def _hide_for_screenshot(self, event=None):
        """Hide block highlights for screenshot"""
        # Remove all block highlight tags from gutter
        for i in range(len(self.depth_colors)):
            self.gutter.tag_remove(f"block_line_depth_{i}", "1.0", "end")
        logger.debug("Block highlights hidden for screenshot")
    
    def _show_after_screenshot(self, event=None):
        """Show block highlights after screenshot"""
        # Reapply all block highlights
        self._reapply_highlights()
        logger.debug("Block highlights restored after screenshot")
    
    def schedule_update(self):
        """Schedule block update (after text changes)"""
        # Skip if already updating
        if self._update_scheduled:
            return
            
        self._update_scheduled = True
        
        def perform_update():
            try:
                self.update_blocks()
            finally:
                self._update_scheduled = False
        
        # Small delay to batch rapid changes while keeping it responsive
        self.text.after(10, perform_update)


def update_blocks(event):
    """Called when text changes"""
    if not get_workbench().ready:
        return
    
    # Check if block highlighting is enabled
    if not get_workbench().get_option("view.block_highlighting"):
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
    
    # Check if block highlighting is enabled
    if not get_workbench().get_option("view.block_highlighting"):
            return

    if hasattr(event, "editor"):
        text = event.editor.get_text_widget()
    else:
        return

    if not hasattr(text, "block_highlighter"):
        text.block_highlighter = BlockHighlighter(text)
        # Initial update - small delay to let editor finish loading
        text.after(50, text.block_highlighter.schedule_update)


def load_plugin() -> None:
    wb = get_workbench()
    wb.set_default("view.block_highlighting", True)
    wb.bind_class("CodeViewText", "<<TextChange>>", update_blocks, True)
    # Initialize when editor opens
    wb.bind("Open", init_highlighter, True)
    wb.bind("EditorTextCreated", init_highlighter, True)
