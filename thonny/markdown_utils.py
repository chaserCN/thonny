"""Markdown rendering utilities for Thonny UI"""
import re
import tkinter as tk
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Type of message for markdown rendering"""
    BOT = "bot"
    USER = "user"
    POPUP = "popup"

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

# Font configuration constants
FONT_FAMILY_DEFAULT = "TkDefaultFont"
FONT_FAMILY_CODE = "TkFixedFont"

# Font sizes (dynamic, based on TkDefaultFont)
def _get_font_sizes():
    """Get font sizes - fixed at 14pt"""
    return {
        'heading': 16,  # 14 * 1.14
        'normal': 14,
        'code': 14
    }

FONT_SIZE_HEADING = 11  # Will be updated dynamically
FONT_SIZE_NORMAL = 10   # Will be updated dynamically
FONT_SIZE_CODE = 10     # Will be updated dynamically

# Colors for chat message backgrounds
COLOR_BOT_MESSAGE_BG = "#F0F8FF"   # Very light blue for bot messages (lighter)
COLOR_USER_MESSAGE_BG = "#F3E5F5"  # Very light purple for user messages (same lightness as bot)
COLOR_USER_MESSAGE_FG = "#4A148C"  # Dark purple text for user messages
COLOR_CODE_BLOCK_BG = "#FAF8F5"    # Very light beige for code blocks

# Syntax highlighting colors
COLOR_KEYWORD = "#0000FF"    # Blue
COLOR_STRING = "#008000"     # Green
COLOR_COMMENT = "#999999"    # Gray
COLOR_NUMBER = "#0066AA"     # Darker blue (same as editor)
COLOR_BUILTIN = "#9900CC"    # Purple

# Selection colors
COLOR_SELECT_BG = "#4A90E2"  # Blue
COLOR_SELECT_FG = "white"

# UI colors
COLOR_AVATAR = "#4A90E2"        # Blue for avatars
COLOR_TYPING_INDICATOR = "#999999"  # Gray for typing animation


def highlight_python_syntax_with_pygments(text_widget: tk.Text, start_index: str, end_index: str, tag_suffix: str = "") -> None:
    """Apply Python syntax highlighting using Pygments library
    
    Args:
        tag_suffix: Suffix for md_code_block tag (e.g. "_bot", "_user", "_popup")
    """
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
        text_widget.tag_raise(tag, f'md_code_block{tag_suffix}')


def highlight_python_syntax_simple(text_widget: tk.Text, start_index: str, end_index: str, tag_suffix: str = "") -> None:
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
        text_widget.tag_raise(tag, f'md_code_block{tag_suffix}')


def highlight_python_syntax(text_widget: tk.Text, start_index: str, end_index: str, tag_suffix: str = "") -> None:
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
        highlight_python_syntax_with_pygments(text_widget, start_index, end_index, tag_suffix)
    else:
        highlight_python_syntax_simple(text_widget, start_index, end_index, tag_suffix)


def _show_copy_toast(text_widget: tk.Text, text: str, x: int, y: int, duration_ms: int = 700) -> None:
    import time

    root = text_widget.winfo_toplevel()

    # 1) Если уже есть активный тост — отменяем его таймер и закрываем
    prev = getattr(root, "_active_toast", None)
    if prev and prev.winfo_exists():
        # отменяем таймер старого тоста, если он ещё жив
        after_id = getattr(prev, "_after_id", None)
        if after_id:
            try:
                prev.after_cancel(after_id)
            except tk.TclError:
                pass
        try:
            prev.destroy()
        except tk.TclError:
            pass

    # 2) Создаём новый тост (скрытый, чтобы не мигал)
    toast = tk.Toplevel(root)
    toast.withdraw()
    toast.overrideredirect(True)
    toast.attributes('-topmost', True)

    # Use smaller font for toast (0.7x of default)
    import tkinter.font as tkfont
    try:
        base_size = tkfont.nametofont("TkDefaultFont").cget("size")
        toast_size = max(9, round(base_size * 0.7))  # At least 9, but 70% of base
    except:
        toast_size = 9
    
    label = tk.Label(
        toast,
        text=text,
        font=("TkDefaultFont", toast_size),
        bg="#EEEEEE",
        fg="#555555",
        padx=12,
        pady=6,
        relief="flat",
        borderwidth=0
    )
    label.pack()
    label.update_idletasks()

    toast.geometry(f"+{x}+{y}")
    try:
        toast.attributes('-alpha', 0.92)
    except tk.TclError:
        pass

    # помечаем этот тост как текущий активный
    root._active_toast = toast

    # 3) Показ + запуск таймера, который гарантированно уничтожит ИМЕННО ЭТОТ экземпляр
    def show_and_arm():
        if not toast.winfo_exists():  # на всякий случай
            return
        toast.deiconify()
        toast.lift()
        toast.update_idletasks()
        toast._shown_at = time.perf_counter()

        # привязываем коллбек к конкретному окну через аргумент по умолчанию
        # (никаких self.toast внутри — только локальная ссылка w)
        def safe_destroy(w=toast):
            if w.winfo_exists():
                try:
                    w.destroy()
                except tk.TclError:
                    pass

        # сохраняем id таймера на самом тосте, чтобы иметь возможность отменить его при следующем показе
        toast._after_id = toast.after(duration_ms, safe_destroy)

    toast.after_idle(show_and_arm)


def _make_inline_code_clickable(text_widget: tk.Text, code_start: str, code_end: str, code_text: str) -> None:
    """Make inline code clickable to copy"""
    try:
        # Create a unique tag for this inline code
        tag_name = f"clickable_inline_{id(code_text)}_{code_start.replace('.', '_')}"
        
        # Configure the tag (no background change, just clickable)
        text_widget.tag_configure(tag_name, foreground=None)
        
        # Apply the tag
        text_widget.tag_add(tag_name, code_start, code_end)
        text_widget.tag_raise(tag_name)
        
        # Bind click event
        def copy_on_click(event):
            try:
                text_widget.clipboard_clear()
                text_widget.clipboard_append(code_text)
                
                # Show toast near the click position
                x = event.x_root + 10  # Slightly to the right of cursor
                y = event.y_root - 10  # Slightly above cursor
                _show_copy_toast(text_widget, "✓ Copied", x, y)
                
            except Exception as e:
                logger.warning(f"Failed to copy inline code: {e}")
        
        text_widget.tag_bind(tag_name, "<Button-1>", copy_on_click)
        
    except Exception as e:
        logger.warning(f"Failed to make inline code clickable: {e}", exc_info=True)


def _add_copy_button(text_widget: tk.Text, block_start: str, block_end: str, code_start: str, code_end: str, code_text: str) -> None:
    """Make code block clickable to copy (no embedded widgets)"""
    try:
        # Create a unique tag for this specific code block
        tag_name = f"clickable_code_{id(code_text)}_{code_start.replace('.', '_')}"
        
        # Store original background
        original_bg = "#f5f5f5"
        hover_bg = "#e8e8e8"
        
        # Create hover tag for this block
        hover_tag = f"{tag_name}_hover"
        
        # Configure the tags
        text_widget.tag_configure(tag_name, background=original_bg)
        text_widget.tag_configure(hover_tag, background=hover_bg)
        
        # Apply the tag to the entire block (including internal padding)
        text_widget.tag_add(tag_name, block_start, block_end)
        
        # Raise priority so it's above md_code_block and code_block_internal_padding
        text_widget.tag_raise(tag_name)
        text_widget.tag_raise(hover_tag)
        
        # Bind click event to copy code
        def copy_on_click(event):
            try:
                text_widget.clipboard_clear()
                text_widget.clipboard_append(code_text.rstrip('\n'))
                
                # Show toast near the click position
                x = event.x_root + 10  # Slightly to the right of cursor
                y = event.y_root - 10  # Slightly above cursor
                _show_copy_toast(text_widget, "✓ Copied", x, y)
                
            except Exception as e:
                logger.warning(f"Failed to show toast: {e}")
        
        # Hover effects (apply to entire block including padding)
        def on_enter(event):
            text_widget.tag_add(hover_tag, block_start, block_end)
            text_widget.tag_raise(hover_tag)
        
        def on_leave(event):
            text_widget.tag_remove(hover_tag, block_start, block_end)
        
        text_widget.tag_bind(tag_name, "<Button-1>", copy_on_click)
        text_widget.tag_bind(tag_name, "<Enter>", on_enter)
        text_widget.tag_bind(tag_name, "<Leave>", on_leave)
        
    except Exception as e:
        logger.warning(f"Failed to make code block clickable: {e}", exc_info=True)


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


def render_markdown(text_widget: tk.Text, markdown_text: str, show_copy_button: bool = True, message_type: MessageType = MessageType.BOT) -> None:
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
    
    Args:
        text_widget: tk.Text widget to render in
        markdown_text: Markdown text to render
        show_copy_button: Whether to show Copy button for code blocks (default True)
        message_type: Type of message (BOT, USER, or POPUP) for styling
    """
    
    # Get dynamic font sizes based on current TkDefaultFont
    font_sizes = _get_font_sizes()
    font_size_heading = font_sizes['heading']
    font_size_normal = font_sizes['normal']
    font_size_code = font_sizes['code']
    
    # Determine which insert method to use (direct_insert for TweakableText, insert for regular Text)
    insert_method = getattr(text_widget, 'direct_insert', text_widget.insert)
    
    # Configure tags (always update to apply new settings)
    # Note: spacing1=0 because spacing is controlled by message tags (user_message/bot_message)
    # Note: inactiveselectbackground NOT supported for tags, only for Text widget itself
    # Note: Use unique tag names per message type to avoid color conflicts
    if message_type == MessageType.USER:
        margin_color = COLOR_USER_MESSAGE_BG
        tag_suffix = "_user"
    elif message_type == MessageType.POPUP:
        margin_color = "white"
        tag_suffix = "_popup"
    else:  # MessageType.BOT
        margin_color = COLOR_BOT_MESSAGE_BG
        tag_suffix = "_bot"
    
    # Configure tags with unique names per message type (use dynamic font sizes)
    text_widget.tag_configure("md_heading", font=(FONT_FAMILY_DEFAULT, font_size_heading, "bold"), spacing1=0, spacing3=0, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure("md_normal_text", font=(FONT_FAMILY_DEFAULT, font_size_normal), spacing1=0, spacing3=0, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure(f"md_code_block{tag_suffix}", font=(FONT_FAMILY_CODE, font_size_code), background=COLOR_CODE_BLOCK_BG, spacing1=0, spacing3=0, lmargin1=10, lmargin2=10, rmargin=10, lmargincolor=margin_color, rmargincolor=margin_color, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure("code_block_padding", font=(FONT_FAMILY_DEFAULT, 1), spacing1=6, spacing3=0, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Padding before code blocks
    text_widget.tag_configure(f"code_block_internal_padding{tag_suffix}", font=(FONT_FAMILY_DEFAULT, 1), background=COLOR_CODE_BLOCK_BG, spacing1=4, spacing3=0, lmargin1=10, lmargin2=10, rmargin=10, lmargincolor=margin_color, rmargincolor=margin_color, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Internal padding inside code blocks
    text_widget.tag_configure("md_inline_code", font=(FONT_FAMILY_CODE, font_size_code), background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure("md_bold", font=(FONT_FAMILY_DEFAULT, font_size_normal, "bold"), selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure("md_italic", font=(FONT_FAMILY_DEFAULT, font_size_normal, "italic"), selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    text_widget.tag_configure("md_list_item", lmargin1=20, lmargin2=30, spacing1=0, spacing3=0, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)
    
    # Syntax highlighting tags for code blocks (vibrant colors for visibility) - use dynamic font size
    text_widget.tag_configure("code_keyword", font=(FONT_FAMILY_CODE, font_size_code, "bold"), foreground=COLOR_KEYWORD, background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Blue Bold
    text_widget.tag_configure("code_string", font=(FONT_FAMILY_CODE, font_size_code), foreground=COLOR_STRING, background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Green
    text_widget.tag_configure("code_comment", font=(FONT_FAMILY_CODE, font_size_code, "italic"), foreground=COLOR_COMMENT, background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Gray Italic
    text_widget.tag_configure("code_number", font=(FONT_FAMILY_CODE, font_size_code), foreground=COLOR_NUMBER, background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Saddle Brown
    text_widget.tag_configure("code_builtin", font=(FONT_FAMILY_CODE, font_size_code), foreground=COLOR_BUILTIN, background=COLOR_CODE_BLOCK_BG, selectbackground=COLOR_SELECT_BG, selectforeground=COLOR_SELECT_FG)  # Purple
    
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
                    highlight_python_syntax(text_widget, code_start, code_end, tag_suffix)
                except Exception as e:
                    pass  # Fallback to plain inline code if highlighting fails
                
                # Make inline code clickable to copy
                _make_inline_code_clickable(text_widget, code_start, code_end, code_content)
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
            # Extract language hint (e.g., ```python or ```fix{lines:20-21})
            lang_full = stripped[3:].strip().lower()
            # Take only language name before { or whitespace
            lang = lang_full.split('{')[0].split()[0] if lang_full else ""
            
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
                # Add padding before code block
                insert_method("end", "\n", ("code_block_padding",))
                
                # Remember start of the entire block (including internal padding)
                block_start = text_widget.index("end-1c")
                
                # Add internal padding at top
                insert_method("end", "\n", (f"code_block_internal_padding{tag_suffix}",))
                
                code_text = "\n".join(code_lines) + "\n"
                start = text_widget.index("end-1c")
                insert_method("end", code_text)
                end = text_widget.index("end-1c")
                text_widget.tag_add(f"md_code_block{tag_suffix}", start, end)
                
                # Add internal padding at bottom
                insert_method("end", "\n", (f"code_block_internal_padding{tag_suffix}",))
                
                # Remember end of the entire block (including internal padding)
                block_end = text_widget.index("end-1c")
                
                # Add padding after code block
                insert_method("end", "\n", ("code_block_padding",))
                
                # Apply Python syntax highlighting if language is python or not specified or fix
                if not lang or lang in ("python", "py", "fix"):
                    try:
                        highlight_python_syntax(text_widget, start, end, tag_suffix)
                        # Raise priority of syntax tags to ensure colors are visible
                        for tag in ['code_keyword', 'code_string', 'code_comment', 'code_number', 'code_builtin']:
                            try:
                                text_widget.tag_raise(tag, f'md_code_block{tag_suffix}')
                            except:
                                pass
                    except Exception as e:
                        logger.warning(f"Syntax highlighting failed: {e}", exc_info=True)
                        pass  # Fallback to plain code block if highlighting fails
                
                # Add copy button at the end of code block (if enabled)
                # Pass the entire block range (including internal padding) for hover effects
                if show_copy_button:
                    try:
                        _add_copy_button(text_widget, block_start, block_end, start, end, code_text)
                    except Exception as e:
                        logger.warning(f"Failed to add copy button: {e}", exc_info=True)
            continue
        
        # Check for headings with #
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip()
            start = text_widget.index("end-1c")
            
            # Parse inline formatting (bold, italic, code) within heading
            insert_formatted_text(heading_text)
            insert_method("end", "\n")
            
            # Apply heading style to the entire line
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
                        # Add padding before code block
                        insert_method("end", "\n", ("code_block_padding",))
                        
                        # Remember start of the entire block (including internal padding)
                        block_start = text_widget.index("end-1c")
                        
                        # Add internal padding at top
                        insert_method("end", "\n", (f"code_block_internal_padding{tag_suffix}",))
                        
                        var_text = "\n".join(var_lines) + "\n"
                        start = text_widget.index("end-1c")
                        insert_method("end", var_text)
                        end = text_widget.index("end-1c")
                        text_widget.tag_add(f"md_code_block{tag_suffix}", start, end)
                        
                        # Add internal padding at bottom
                        insert_method("end", "\n", (f"code_block_internal_padding{tag_suffix}",))
                        
                        # Remember end of the entire block (including internal padding)
                        block_end = text_widget.index("end-1c")
                        
                        # Add padding after code block
                        insert_method("end", "\n", ("code_block_padding",))
                        
                        # Add copy button (if enabled)
                        if show_copy_button:
                            try:
                                _add_copy_button(text_widget, block_start, block_end, start, end, var_text)
                            except Exception as e:
                                logger.warning(f"Failed to add copy button: {e}", exc_info=True)
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

