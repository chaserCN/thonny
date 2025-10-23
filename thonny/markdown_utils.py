"""Markdown rendering utilities for Thonny UI"""
import re
import tkinter as tk
import logging

logger = logging.getLogger(__name__)

# Try to import Pygments for better syntax highlighting
try:
    from pygments import lex
    from pygments.lexers import PythonLexer
    from pygments.token import Token
    HAS_PYGMENTS = True
except ImportError:
    HAS_PYGMENTS = False

# Track if we've logged the highlighting method
_HIGHLIGHTING_LOGGED = False


def highlight_python_syntax_with_pygments(text_widget: tk.Text, start_index: str, end_index: str) -> None:
    """Apply Python syntax highlighting using Pygments library"""
    code_text = text_widget.get(start_index, end_index)
    
    # Tokenize code with Pygments
    lexer = PythonLexer()
    tokens = list(lex(code_text, lexer))
    
    # Map Pygments tokens to our tags
    token_tag_map = {
        Token.Keyword: 'code_keyword',
        Token.Keyword.Constant: 'code_keyword',
        Token.Keyword.Namespace: 'code_keyword',
        Token.Name.Builtin: 'code_builtin',
        Token.Name.Builtin.Pseudo: 'code_builtin',
        Token.String: 'code_string',
        Token.String.Doc: 'code_comment',
        Token.Comment: 'code_comment',
        Token.Comment.Single: 'code_comment',
        Token.Comment.Multiline: 'code_comment',
        Token.Number: 'code_number',
        Token.Number.Integer: 'code_number',
        Token.Number.Float: 'code_number',
    }
    
    pos = 0
    for token_type, value in tokens:
        if not value:
            continue
        
        token_start = f"{start_index}+{pos}c"
        token_end = f"{start_index}+{pos + len(value)}c"
        
        # Find matching tag for this token type (check if token_type is subtype of mapped type)
        for mapped_type, tag in token_tag_map.items():
            if token_type in mapped_type:
                text_widget.tag_add(tag, token_start, token_end)
                break
        
        pos += len(value)
    
    # Raise priority of syntax tags above md_code_block
    for tag in ['code_keyword', 'code_string', 'code_comment', 'code_number', 'code_builtin']:
        text_widget.tag_raise(tag, 'md_code_block')


def highlight_python_syntax_simple(text_widget: tk.Text, start_index: str, end_index: str) -> None:
    """Apply Python syntax highlighting using simple regex (fallback when Pygments unavailable)"""
    
    # Python keywords
    keywords = {
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 
        'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 
        'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 
        'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield'
    }
    
    # Python builtins
    builtins = {
        'abs', 'all', 'any', 'bin', 'bool', 'chr', 'dict', 'dir', 'divmod', 'enumerate',
        'filter', 'float', 'format', 'help', 'hex', 'id', 'input', 'int', 'isinstance',
        'len', 'list', 'map', 'max', 'min', 'next', 'oct', 'open', 'ord', 'pow',
        'print', 'range', 'repr', 'reversed', 'round', 'set', 'slice', 'sorted',
        'str', 'sum', 'tuple', 'type', 'zip'
    }
    
    # Get text content
    code_text = text_widget.get(start_index, end_index)
    
    # Apply syntax highlighting
    for match in re.finditer(
        r'(#.*$)|'  # Comments
        r'(""".*?"""|\'\'\'.*?\'\'\')|'  # Triple-quoted strings
        r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|'  # Regular strings
        r'\b(\d+\.?\d*)\b|'  # Numbers
        r'\b(\w+)\b',  # Words (keywords/builtins/identifiers)
        code_text, 
        re.MULTILINE | re.DOTALL
    ):
        match_start = f"{start_index}+{match.start()}c"
        match_end = f"{start_index}+{match.end()}c"
        
        if match.group(1):  # Comment
            text_widget.tag_add("code_comment", match_start, match_end)
        elif match.group(2) or match.group(3):  # String
            text_widget.tag_add("code_string", match_start, match_end)
        elif match.group(4):  # Number
            text_widget.tag_add("code_number", match_start, match_end)
        elif match.group(5):  # Word - check if keyword or builtin
            word = match.group(5)
            if word in keywords:
                text_widget.tag_add("code_keyword", match_start, match_end)
            elif word in builtins:
                text_widget.tag_add("code_builtin", match_start, match_end)
    
    # Raise priority of syntax tags above md_code_block
    for tag in ['code_keyword', 'code_string', 'code_comment', 'code_number', 'code_builtin']:
        text_widget.tag_raise(tag, 'md_code_block')


def highlight_python_syntax(text_widget: tk.Text, start_index: str, end_index: str) -> None:
    """Apply Python syntax highlighting (uses Pygments if available, otherwise simple regex)"""
    global _HIGHLIGHTING_LOGGED
    
    # Log highlighting method once
    if not _HIGHLIGHTING_LOGGED:
        if HAS_PYGMENTS:
            try:
                import pygments
                logger.info(f"Using Pygments {pygments.__version__} for Python syntax highlighting")
            except:
                logger.info("Using Pygments for Python syntax highlighting")
        else:
            logger.info("Pygments not available, using simple regex syntax highlighting")
        _HIGHLIGHTING_LOGGED = True
    
    if HAS_PYGMENTS:
        highlight_python_syntax_with_pygments(text_widget, start_index, end_index)
    else:
        highlight_python_syntax_simple(text_widget, start_index, end_index)


def _add_copy_button(text_widget: tk.Text, code_start: str, code_end: str, code_text: str) -> None:
    """Add a copy button next to a code block"""
    try:
        # Get the background color from text_widget
        try:
            bg_color = str(text_widget.cget("background"))
            # Convert system colors to actual colors if needed
            if bg_color.startswith("system"):
                bg_color = "white"
        except:
            bg_color = "white"
        
        # Create a clickable label instead of button (no borders/shadows)
        button = tk.Label(
            text_widget,
            text="Copy 📋",
            font=("TkDefaultFont", 8),
            bg=bg_color,  # Match text widget background
            fg="#666",
            cursor="hand2",
            padx=0,  # No padding
            pady=0,  # No padding
        )
        
        # Make it clickable
        button.bind("<Button-1>", lambda e: _copy_code_to_clipboard(text_widget, code_text, button))
        
        # Add hover effects
        def on_enter(e):
            button.config(fg="#333")
        def on_leave(e):
            button.config(fg="#666")
        
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
        
        # Create a tag for right alignment with matching background
        tag_name = f"copy_button_{id(button)}"
        text_widget.tag_configure(tag_name, justify="right", background=bg_color, spacing1=0, spacing3=0)
        
        # Insert a newline at the END of code block for the button
        insert_method = getattr(text_widget, 'direct_insert', text_widget.insert)
        insert_method(code_end, "\n")
        
        # Add some spaces before button to push it to the right and fill the line
        insert_method(code_end, "                                                                              ")
        
        # Now the button will be on its own line at the bottom
        button_pos = text_widget.index(f"{code_end} lineend")
        
        # Insert the button
        text_widget.window_create(button_pos, window=button)
        
        # Apply right alignment tag to the entire line with the button
        line_start = f"{code_end} linestart"
        line_end = f"{button_pos} lineend +1c"
        text_widget.tag_add(tag_name, line_start, line_end)
        
        # Remove md_code_block and all syntax highlighting tags from button line to avoid gray background
        text_widget.tag_remove("md_code_block", line_start, line_end)
        text_widget.tag_remove("code_keyword", line_start, line_end)
        text_widget.tag_remove("code_string", line_start, line_end)
        text_widget.tag_remove("code_comment", line_start, line_end)
        text_widget.tag_remove("code_number", line_start, line_end)
        text_widget.tag_remove("code_builtin", line_start, line_end)
        
    except Exception as e:
        logger.warning(f"Failed to create copy button: {e}", exc_info=True)


def _copy_code_to_clipboard(text_widget: tk.Text, code_text: str, button: tk.Label) -> None:
    """Copy code to clipboard and show visual feedback"""
    try:
        # Copy to clipboard
        text_widget.clipboard_clear()
        text_widget.clipboard_append(code_text.rstrip('\n'))
        
        # Show visual feedback
        original_text = button.cget("text")
        button.config(text="Copied! ✓", fg="#22aa22")
        
        # Reset after 1.5 seconds
        def reset_button():
            try:
                button.config(text=original_text, fg="#666")
            except:
                pass  # Button might be destroyed
        
        text_widget.after(1500, reset_button)
        
        logger.info("Code copied to clipboard")
        
    except Exception as e:
        logger.error(f"Failed to copy code to clipboard: {e}")
        try:
            button.config(text="Error ✗", fg="#aa2222")
            text_widget.after(1500, lambda: button.config(text="Copy 📋", fg="#666"))
        except:
            pass


def render_markdown(text_widget: tk.Text, markdown_text: str) -> None:
    """
    Render markdown directly in tk.Text widget with tags.
    
    Supports:
    - Headings: ## text or **text:** (entire line)
    - Bold: **text**
    - Italic: *text*
    - Inline code: `code`
    - Code blocks: ```...```
    - Variable assignments: name = value (rendered as code blocks)
    - Bullet lists: - or *
    - Numbered lists: 1., 2., etc.
    - Empty lines (preserved)
    """
    
    # Determine which insert method to use (direct_insert for TweakableText, insert for regular Text)
    insert_method = getattr(text_widget, 'direct_insert', text_widget.insert)
    
    # Configure tags (always update to apply new settings)
    text_widget.tag_configure("md_heading", font=("TkDefaultFont", 10, "bold"), spacing1=4, spacing3=4)
    text_widget.tag_configure("md_normal_text", font=("TkDefaultFont", 10), spacing1=4, spacing3=4)
    text_widget.tag_configure("md_code_block", font=("TkFixedFont", 9), background="#f5f5f5", spacing1=4, spacing3=4, lmargin1=10, lmargin2=10, selectbackground="#4A90E2", selectforeground="white")
    text_widget.tag_configure("md_inline_code", font=("TkFixedFont", 9), background="#f5f5f5", selectbackground="#4A90E2", selectforeground="white")
    text_widget.tag_configure("md_bold", font=("TkDefaultFont", 10, "bold"))
    text_widget.tag_configure("md_italic", font=("TkDefaultFont", 10, "italic"))
    text_widget.tag_configure("md_list_item", lmargin1=20, lmargin2=30, spacing1=4, spacing3=4)
    
    # Syntax highlighting tags for code blocks (vibrant colors for visibility)
    text_widget.tag_configure("code_keyword", font=("TkFixedFont", 9, "bold"), foreground="#0000FF", background="#f5f5f5")  # Bright Blue Bold
    text_widget.tag_configure("code_string", font=("TkFixedFont", 9), foreground="#008000", background="#f5f5f5")  # Green
    text_widget.tag_configure("code_comment", font=("TkFixedFont", 9, "italic"), foreground="#999999", background="#f5f5f5")  # Gray Italic
    text_widget.tag_configure("code_number", font=("TkFixedFont", 9), foreground="#FF6600", background="#f5f5f5")  # Orange
    text_widget.tag_configure("code_builtin", font=("TkFixedFont", 9), foreground="#9900CC", background="#f5f5f5")  # Purple
    
    def insert_formatted_text(text):
        """Insert text with inline formatting (bold, italic, code)"""
        # Order matters: handle code first to avoid interfering with ** and *
        parts = re.split(r'(`[^`]+`)', text)
        
        for part in parts:
            if part.startswith("`") and part.endswith("`"):
                # Inline code
                code_content = part[1:-1]
                code_start = text_widget.index("end-1c")
                insert_method("end", code_content)
                code_end = text_widget.index("end-1c")
                text_widget.tag_add("md_inline_code", code_start, code_end)
                
                # Apply Python syntax highlighting to inline code
                try:
                    highlight_python_syntax(text_widget, code_start, code_end)
                except Exception as e:
                    pass  # Fallback to plain inline code if highlighting fails
            else:
                # Handle bold and italic
                # Bold: **text**
                subparts = re.split(r'(\*\*[^*]+\*\*)', part)
                for subpart in subparts:
                    if subpart.startswith("**") and subpart.endswith("**"):
                        bold_text = subpart[2:-2]
                        bold_start = text_widget.index("end-1c")
                        insert_method("end", bold_text)
                        text_widget.tag_add("md_bold", bold_start, text_widget.index("end-1c"))
                    else:
                        # Handle italic: *text* (but not ** which is already handled)
                        italic_parts = re.split(r'(\*[^*]+\*)', subpart)
                        for italic_part in italic_parts:
                            if italic_part.startswith("*") and italic_part.endswith("*") and not italic_part.startswith("**"):
                                italic_text = italic_part[1:-1]
                                italic_start = text_widget.index("end-1c")
                                insert_method("end", italic_text)
                                text_widget.tag_add("md_italic", italic_start, text_widget.index("end-1c"))
                            else:
                                insert_method("end", italic_part)
    
    lines = markdown_text.split("\n")
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Handle empty lines - preserve them
        if not stripped:
            insert_method("end", "\n")
            i += 1
            continue
        
        # Check for code block: ```
        if stripped.startswith("```"):
            # Extract language hint (e.g., ```python)
            lang = stripped[3:].strip().lower()
            
            # Collect all lines until closing ```
            i += 1
            code_lines = []
            while i < len(lines):
                if lines[i].strip().startswith("```"):
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            
            # Insert code block
            if code_lines:
                code_text = "\n".join(code_lines) + "\n"
                start = text_widget.index("end-1c")
                insert_method("end", code_text)
                end = text_widget.index("end-1c")
                text_widget.tag_add("md_code_block", start, end)
                
                # Apply Python syntax highlighting if language is python or not specified
                if not lang or lang == "python" or lang == "py":
                    try:
                        highlight_python_syntax(text_widget, start, end)
                    except Exception as e:
                        logger.warning(f"Syntax highlighting failed: {e}", exc_info=True)
                        pass  # Fallback to plain code block if highlighting fails
                
                # Add copy button at the end of code block
                try:
                    _add_copy_button(text_widget, start, end, code_text)
                except Exception as e:
                    logger.warning(f"Failed to add copy button: {e}", exc_info=True)
            continue
        
        # Check for headings with #
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip() + "\n"
            start = text_widget.index("end-1c")
            insert_method("end", heading_text)
            text_widget.tag_add("md_heading", start, text_widget.index("end-1c"))
            i += 1
            continue
        
        # Check for bold heading: **text:** (entire line)
        if stripped.startswith("**") and stripped.endswith("**"):
            heading_text = stripped.strip("*") + "\n"
            start = text_widget.index("end-1c")
            insert_method("end", heading_text)
            text_widget.tag_add("md_heading", start, text_widget.index("end-1c"))
            i += 1
            
            # Check next line for variable assignments (n = 3)
            if i < len(lines):
                next_stripped = lines[i].strip()
                if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*.+$', next_stripped):
                    # Collect variable lines
                    var_lines = []
                    while i < len(lines):
                        line_check = lines[i].strip()
                        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*.+$', line_check):
                            var_lines.append(line_check)
                            i += 1
                        elif not line_check:  # Empty line - stop but don't consume it
                            break
                        else:
                            break
                    
                    # Insert as code block
                    if var_lines:
                        var_text = "\n".join(var_lines) + "\n"
                        start = text_widget.index("end-1c")
                        insert_method("end", var_text)
                        text_widget.tag_add("md_code_block", start, text_widget.index("end-1c"))
            continue
        
        # Check for list items: - or * or numbers 1.
        list_match = re.match(r'^(\s*)([-*]|\d+\.)\s+(.*)$', stripped)
        if list_match:
            bullet = list_match.group(2)
            content = list_match.group(3)
            
            line_start = text_widget.index("end-1c")
            insert_method("end", "• " if bullet in ['-', '*'] else f"{bullet} ")
            insert_formatted_text(content)
            insert_method("end", "\n")
            text_widget.tag_add("md_list_item", line_start, text_widget.index("end-1c"))
            i += 1
            continue
        
        # Regular line - handle inline formatting
        if stripped:
            line_start = text_widget.index("end-1c")
            insert_formatted_text(line)
            insert_method("end", "\n")
            # Tag the whole line as normal_text for spacing
            text_widget.tag_add("md_normal_text", line_start, text_widget.index("end-1c"))
        
        i += 1

