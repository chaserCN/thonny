"""
Utilities for creating AI explanation popups.
Shared between CodeViewText and CodeView classes.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from thonny import get_workbench
from thonny.languages import tr
from thonny.ui_utils import lookup_style_option


def get_ai_assistant():
    """Get configured AI assistant, return None if unavailable"""
    try:
        model = get_workbench().get_option("ai.model", "gpt")
    except:
        model = "gpt"
    
    assistants = get_workbench().assistants
    if model == "gpt":
        assistant = assistants.get("openai")
    elif model == "gemini":
        assistant = assistants.get("gemini")
    elif model == "claude":
        assistant = assistants.get("claude")
    else:
        assistant = assistants.get("openai")
    
    if not assistant:
        messagebox.showerror("AI Error", tr("AI assistant unavailable. Check API key settings."))
        return None
    
    if not assistant.get_ready():
        return None
    
    return assistant


def get_localization(context: str) -> dict:
    """
    Get localized strings for popup context.
    
    Args:
        context: One of 'token', 'selection', 'line'
        
    Returns:
        dict with localized strings
    """
    try:
        lang = get_workbench().get_option("ai.language", "uk")
    except:
        lang = "uk"
    
    if context == "token":
        if lang == "ru":
            return {
                "title": "Объяснение: {token}",
                "code_line_label": "Строка кода:",
                "token_label": "Элемент:",
                "explanation_label": "Объяснение:",
                "loading": "⏳ *Запрашиваю AI для объяснения...*",
                "error_label": "Ошибка:",
            }
        else:  # uk
            return {
                "title": "Пояснення: {token}",
                "code_line_label": "Рядок коду:",
                "token_label": "Елемент:",
                "explanation_label": "Пояснення:",
                "loading": "⏳ *Запитую AI для пояснення...*",
                "error_label": "Помилка:",
            }
    
    elif context == "selection":
        if lang == "ru":
            return {
                "title": "Объяснение выделенного кода",
                "code_label": "Выделенный код:",
                "explanation_label": "Объяснение:",
                "loading": "⏳ *Запрашиваю AI для объяснения...*",
                "error_label": "Ошибка:",
            }
        else:  # uk
            return {
                "title": "Пояснення виділеного коду",
                "code_label": "Виділений код:",
                "explanation_label": "Пояснення:",
                "loading": "⏳ *Запитую AI для пояснення...*",
                "error_label": "Помилка:",
            }
    
    elif context == "line":
        if lang == "ru":
            return {
                "title": "Строка {line_num}: Пояснение",
                "code_line_label": "Строка кода:",
                "explanation_label": "Пояснение:",
                "loading": "⏳ *Запрашиваю AI для пояснения...*",
                "error_label": "Ошибка:",
            }
        else:  # uk
            return {
                "title": "Рядок {line_num}: Пояснення",
                "code_line_label": "Рядок коду:",
                "explanation_label": "Пояснення:",
                "loading": "⏳ *Запитую AI для пояснення...*",
                "error_label": "Помилка:",
            }
    
    return {}


def get_program_context(text_widget, parent_widget=None):
    """
    Get program context: debug info with variables if available, or formatted code otherwise.
    
    Args:
        text_widget: The Text widget containing the code (could be CodeViewText or self.text from CodeView)
        parent_widget: Optional parent widget to get filename from
    """
    from thonny.plugins.debug_common import get_debug_context, format_code_context
    
    # Try to get debug context first (includes variable values)
    program_context = None
    try:
        program_context = get_debug_context()
    except:
        pass
    
    # If not in debug mode, format the code
    if not program_context:
        full_code = text_widget.get("1.0", "end-1c")
        try:
            # Try to get filename from parent or text widget
            if parent_widget and hasattr(parent_widget, 'get_filename'):
                filename = parent_widget.get_filename() or "program.py"
            elif hasattr(text_widget, 'master') and hasattr(text_widget.master, 'get_filename'):
                filename = text_widget.master.get_filename() or "program.py"
            else:
                filename = "program.py"
            program_context = format_code_context(full_code, filename)
        except:
            program_context = format_code_context(full_code)
    
    return program_context


def create_explanation_popup(
    parent,
    title: str,
    width: int,
    height: int,
    loading_markdown: str,
    request_func,
    format_result_func,
    error_label: str,
    position_mode: str = "center",
    line_num: int = None,
):
    """
    Generic popup creator for all explanation types.
    
    Args:
        parent: Parent widget (CodeViewText or CodeView instance)
        title: Popup window title
        width: Window width
        height: Window height
        loading_markdown: Markdown text to show while loading
        request_func: Function to call in thread to get explanation (should return string)
        format_result_func: Function to format result as markdown (takes explanation string)
        error_label: Label for error messages
        position_mode: "center" or "below_line"
        line_num: Line number (required if position_mode="below_line")
    """
    from thonny.markdown_utils import render_markdown
    
    # Create popup dialog
    popup = tk.Toplevel(parent)
    popup.title(title)
    popup.withdraw()
    popup.transient(parent.winfo_toplevel())
    popup.geometry(f"{width}x{height}")
    
    # Calculate position
    root = parent.winfo_toplevel()
    root_x = root.winfo_rootx()
    root_w = root.winfo_width()
    root_h = root.winfo_height()
    
    # Center horizontally
    popup_x = root_x + (root_w - width) // 2
    
    if position_mode == "below_line" and line_num is not None:
        # Position below the line
        line_index = f"{line_num}.0"
        try:
            # Get text widget from parent (CodeView has self.text, CodeViewText is self)
            text_widget = getattr(parent, 'text', parent)
            dline_info = text_widget.dlineinfo(line_index)
            if dline_info:
                line_y = dline_info[1] + text_widget.winfo_rooty()
                line_height = dline_info[3]
                popup_y = line_y + line_height + 8
            else:
                # Fallback to center
                popup_y = root.winfo_rooty() + (root_h - height) // 2
        except:
            # Fallback to center
            popup_y = root.winfo_rooty() + (root_h - height) // 2
    else:
        # Center vertically
        popup_y = root.winfo_rooty() + (root_h - height) // 2
    
    # Screen boundaries check
    screen_width = popup.winfo_screenwidth()
    screen_height = popup.winfo_screenheight()
    if popup_x < 0:
        popup_x = 0
    elif popup_x + width > screen_width:
        popup_x = screen_width - width
    if popup_y < 0:
        popup_y = 0
    elif popup_y + height > screen_height:
        # If doesn't fit below, try above
        if position_mode == "below_line" and line_num is not None:
            try:
                text_widget = getattr(parent, 'text', parent)
                dline_info = text_widget.dlineinfo(f"{line_num}.0")
                if dline_info:
                    line_y = dline_info[1] + text_widget.winfo_rooty()
                    popup_y = max(0, line_y - height - 8)
                else:
                    popup_y = screen_height - height
            except:
                popup_y = screen_height - height
        else:
            popup_y = screen_height - height
    
    popup.geometry(f"{width}x{height}+{popup_x}+{popup_y}")
    popup.deiconify()
    
    # Create Text widget
    text_frame = tk.Frame(popup)
    text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    explanation_text = tk.Text(
        text_frame,
        wrap=tk.WORD,
        font="TkDefaultFont",
        background="white",
        foreground="black",
        state="normal",
        selectbackground="#4A90E2",  # Blue selection background
        selectforeground="white"      # White selection text
    )
    
    scrollbar = ttk.Scrollbar(text_frame, command=explanation_text.yview)
    explanation_text.configure(yscrollcommand=scrollbar.set)
    
    explanation_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    # Enable copy shortcuts
    explanation_text.bind("<Control-c>", lambda e: explanation_text.event_generate("<<Copy>>"))
    explanation_text.bind("<Command-c>", lambda e: explanation_text.event_generate("<<Copy>>"))
    explanation_text.bind("<Control-a>", lambda e: explanation_text.tag_add("sel", "1.0", "end"))
    explanation_text.bind("<Command-a>", lambda e: explanation_text.tag_add("sel", "1.0", "end"))
    
    # Show loading message
    render_markdown(explanation_text, loading_markdown, show_copy_button=False)
    
    # Get AI explanation in thread
    def get_explanation():
        try:
            explanation = request_func()
            
            def update_ui():
                if not popup.winfo_exists():
                    return
                
                explanation_text.delete("1.0", "end")
                md_content = format_result_func(explanation)
                render_markdown(explanation_text, md_content, show_copy_button=False)
            
            popup.after(0, update_ui)
        except Exception as e:
            def show_error(error=e):
                if not popup.winfo_exists():
                    return
                
                explanation_text.delete("1.0", "end")
                error_md = f"**{error_label}**\n\n{str(error)}"
                render_markdown(explanation_text, error_md, show_copy_button=False)
            popup.after(0, show_error)
    
    threading.Thread(target=get_explanation, daemon=True).start()


def _calculate_diff_ranges(old_text: str, new_text: str) -> list:
    """
    Calculate character ranges to highlight based on diff.
    
    Returns:
        List of tuples: [(start_pos, end_pos, tag_name), ...]
        where tag_name is 'diff_delete' (red background for all changes)
    """
    import difflib
    from thonny.assistance import logger
    
    logger.info(f"Diff calculation:")
    logger.info(f"  Old: {repr(old_text)}")
    logger.info(f"  New: {repr(new_text)}")
    
    ranges = []
    
    # Special handling for indent changes (whitespace at the beginning)
    old_indent = len(old_text) - len(old_text.lstrip(' \t'))
    new_indent = len(new_text) - len(new_text.lstrip(' \t'))
    
    if old_indent != new_indent:
        # Indent changed - always highlight with red (wrong indent)
        logger.info(f"  Indent change: {old_indent} → {new_indent}")
        
        if old_indent > new_indent:
            # Removing indent - highlight extra spaces (from new_indent to old_indent)
            ranges.append((new_indent, old_indent, 'diff_delete'))
            logger.info(f"  → DELETE range: [{new_indent}:{old_indent}] (red)")
        else:
            # Adding indent - highlight 2 chars: last space + first char after indent
            # Shows "insert spaces between these two"
            if old_indent > 0 and old_indent < len(old_text):
                ranges.append((old_indent - 1, old_indent + 1, 'diff_delete'))
                logger.info(f"  → INSERT indicator: [{old_indent - 1}:{old_indent + 1}] (red - space + char)")
            else:
                # Fallback - highlight 2 chars at indent position
                end_pos = min(old_indent + 2, len(old_text))
                ranges.append((old_indent, end_pos, 'diff_delete'))
                logger.info(f"  → INSERT indicator: [{old_indent}:{end_pos}] (red - 2 chars)")
        
        return ranges  # For indent-only changes, don't run generic diff
    
    # Use SequenceMatcher for character-level diff (uses LCS internally)
    matcher = difflib.SequenceMatcher(None, old_text, new_text)
    
    current_pos = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_part = old_text[i1:i2]
        new_part = new_text[j1:j2]
        logger.info(f"  Op: {tag}, old[{i1}:{i2}]={repr(old_part)}, new[{j1}:{j2}]={repr(new_part)}")
        
        if tag == 'equal':
            # Unchanged - just advance position
            current_pos += i2 - i1
            
        elif tag == 'delete':
            # Deleted characters - mark for red highlighting
            ranges.append((current_pos, current_pos + (i2 - i1), 'diff_delete'))
            current_pos += i2 - i1
            
        elif tag == 'insert':
            # Inserted characters - highlight 2 chars: one before and one after insertion point
            # This shows "insert between these two chars"
            if current_pos > 0 and current_pos < len(old_text):
                # Highlight previous char + next char
                ranges.append((current_pos - 1, current_pos + 1, 'diff_delete'))
            elif current_pos == 0 and len(old_text) >= 2:
                # Insert at beginning - highlight first 2 chars
                ranges.append((0, 2, 'diff_delete'))
            elif current_pos > 0:
                # Insert at end - highlight last 2 chars
                ranges.append((max(0, current_pos - 2), current_pos, 'diff_delete'))
            # Don't advance current_pos (insertion is in new text, not old)
            
        elif tag == 'replace':
            # Replaced characters - mark old as red
            ranges.append((current_pos, current_pos + (i2 - i1), 'diff_delete'))
            current_pos += i2 - i1
    
    logger.info(f"  Calculated {len(ranges)} ranges: {ranges}")
    return ranges


def _apply_diff_highlighting(text_widget, start_index, end_index, old_text, new_text):
    """
    Apply character-level diff highlighting.
    
    Uses _calculate_diff_ranges() to compute what to highlight,
    then applies the tags to the text widget.
    
    All changes are highlighted in red (unified style for children).
    """
    from thonny.assistance import logger
    
    # Configure tag style - only red for all changes
    text_widget.tag_configure("diff_delete", background="#FFCCCC", foreground="#CC0000")
    
    # Calculate which ranges to highlight
    ranges = _calculate_diff_ranges(old_text, new_text)
    
    # Apply highlighting for each range
    for start_pos, end_pos, tag_name in ranges:
        pos1 = f"{start_index} + {start_pos}c"
        pos2 = f"{start_index} + {end_pos}c"
        text_widget.tag_add(tag_name, pos1, pos2)
        logger.info(f"  Applied {tag_name}: {pos1} → {pos2}")
    
    if not ranges:
        logger.info("  No changes to highlight")


def create_fix_popup(parent, fix: dict, text_widget, editor):
    """
    Create popup for code fix suggestion.
    
    Args:
        parent: Parent widget
        fix: Dict with 'start_line', 'end_line', 'new', 'reason'
        text_widget: Text widget to apply fix to
        editor: Editor widget for positioning and timing
        
    Returns:
        popup: The created Toplevel window (or None if not created)
    """
    from thonny.markdown_utils import render_markdown
    from thonny.assistance import logger
    
    # Check if reason exists, if not - don't show popup
    if not fix.get('reason') or not fix['reason'].strip():
        logger.warning("Fix suggestion has no reason, skipping popup")
        return None
    
    start_line = fix['start_line']
    end_line = fix['end_line']
    
    # Get old code from editor for diff comparison
    start_index = f"{start_line}.0"
    end_index = f"{end_line}.end"
    old_code = text_widget.get(start_index, end_index)
    new_code = fix['new']
    
    # Apply character-level diff highlighting
    _apply_diff_highlighting(text_widget, start_index, end_index, old_code, new_code)
    
    # Scroll to this line
    text_widget.see(start_index)
    
    # Create Toplevel window (popup) - similar to explain popup
    popup = tk.Toplevel(editor)
    popup.title("💡 Исправление / Виправлення")
    popup.transient(editor)
    popup.overrideredirect(True)  # Remove title bar
    
    # Position popup
    popup_width = 500
    popup_height = 400
    gap = 10  # Gap between line and popup
    
    try:
        bbox = text_widget.bbox(start_index)
        if bbox:
            line_x = text_widget.winfo_rootx() + bbox[0]
            line_y = text_widget.winfo_rooty() + bbox[1]
            line_height = bbox[3]
            
            screen_height = popup.winfo_screenheight()
            
            # Try to place below the line first
            y_below = line_y + line_height + gap
            
            if y_below + popup_height <= screen_height:
                # Fits below - use it
                x = line_x
                y = y_below
            else:
                # Doesn't fit below - place above the line
                y_above = line_y - popup_height - gap
                if y_above >= 0:
                    # Fits above
                    x = line_x
                    y = y_above
                else:
                    # Doesn't fit above either - place to the right
                    x = text_widget.winfo_rootx() + text_widget.winfo_width() - popup_width - 20
                    y = max(0, line_y)
            
            popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
    except:
        popup.geometry(f"{popup_width}x{popup_height}")
    
    # Make popup draggable
    drag_data = {"x": 0, "y": 0, "dragging": False}
    
    def start_drag(event):
        # Only start drag if clicking on gray background Frame (not on Text or Button widgets)
        if isinstance(event.widget, tk.Frame):
            drag_data["x"] = event.x
            drag_data["y"] = event.y
            drag_data["dragging"] = True
            popup.configure(cursor="fleur")  # Change cursor to "move" icon
    
    def do_drag(event):
        if drag_data["dragging"]:
            x = popup.winfo_x() + (event.x - drag_data["x"])
            y = popup.winfo_y() + (event.y - drag_data["y"])
            popup.geometry(f"+{x}+{y}")
    
    def stop_drag(event):
        drag_data["dragging"] = False
        popup.configure(cursor="")  # Reset cursor
    
    # Main container - Thonny gray background
    main_frame = tk.Frame(popup, bg=lookup_style_option("TFrame", "background", "gray"), cursor="fleur")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Bind drag events to main frame (drag from gray background)
    main_frame.bind("<Button-1>", start_drag)
    main_frame.bind("<B1-Motion>", do_drag)
    main_frame.bind("<ButtonRelease-1>", stop_drag)
    
    # Create and pack button frame at BOTTOM first (even though buttons not created yet)
    # This ensures text_frame doesn't take all space
    btn_frame = tk.Frame(main_frame, bg=lookup_style_option("TFrame", "background", "gray"), cursor="fleur")
    btn_frame.pack(side=tk.BOTTOM, pady=10)
    
    # Make btn_frame draggable too
    btn_frame.bind("<Button-1>", start_drag)
    btn_frame.bind("<B1-Motion>", do_drag)
    btn_frame.bind("<ButtonRelease-1>", stop_drag)
    
    # Text widget with scrollbar (single widget for all content)
    text_frame = tk.Frame(main_frame, bg=lookup_style_option("TFrame", "background", "gray"), cursor="fleur")
    text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
    
    # Make text_frame draggable too (for padding areas)
    text_frame.bind("<Button-1>", start_drag)
    text_frame.bind("<B1-Motion>", do_drag)
    text_frame.bind("<ButtonRelease-1>", stop_drag)
    
    content_text = tk.Text(
        text_frame,
        wrap=tk.WORD,
        font="TkDefaultFont",
        background="white",
        foreground="black",
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        selectbackground="#4A90E2",  # Blue selection background
        selectforeground="white"      # White selection text
    )
    
    scrollbar = ttk.Scrollbar(text_frame, command=content_text.yview)
    content_text.configure(yscrollcommand=scrollbar.set)
    
    content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    # Enable copy shortcuts
    content_text.bind("<Control-c>", lambda e: content_text.event_generate("<<Copy>>"))
    content_text.bind("<Command-c>", lambda e: content_text.event_generate("<<Copy>>"))
    
    # Get language
    try:
        lang = get_workbench().get_option("ai.language", "uk")
    except Exception:
        lang = "uk"
    
    # Build markdown content: CODE FIRST, then explanation
    label_text = "Правильний код:" if lang == "uk" else "Правильный код:"
    markdown_content = f"**{label_text}**\n\n```python\n{fix['new']}\n```\n\n{fix['reason']}"
    
    # Render everything through markdown
    render_markdown(content_text, markdown_content, show_copy_button=False)
    
    # Fix code block margin colors for white background (not blue chat bubble)
    content_text.tag_configure("md_code_block", lmargincolor="white", rmargincolor="white")
    content_text.tag_configure("code_block_internal_padding", lmargincolor="white", rmargincolor="white")
    
    # Define button functions
    def apply_fix():
        """Apply the fix to editor."""
        from thonny.assistance import logger
        popup._closing = True  # Mark as closing
        try:
            # Use fix code exactly as AI provided it (with correct indentation)
            fixed_code = fix['new']
            
            # Delete old lines (use direct_delete if available for Thonny's editor)
            if hasattr(text_widget, 'direct_delete'):
                text_widget.direct_delete(start_index, end_index)
            else:
                text_widget.delete(start_index, end_index)
            
            # Insert new code (use direct_insert if available)
            if hasattr(text_widget, 'direct_insert'):
                text_widget.direct_insert(start_index, fixed_code)
            else:
                text_widget.insert(start_index, fixed_code)
            # Remove diff highlights
            text_widget.tag_remove("diff_delete", "1.0", "end")
            text_widget.tag_remove("diff_insert_marker", "1.0", "end")
            
            # Calculate new end position after insertion
            new_end_index = text_widget.index(f"{start_index} + {len(fixed_code)}c")
            
            # Flash green to show success with fade effect
            text_widget.tag_add("fix_success", start_index, new_end_index)
            text_widget.tag_configure("fix_success", background="#A5D6A7")  # Medium green
            
            # Fade out green highlight
            def fade_out(step=0):
                # Check if text_widget still exists before continuing
                if not text_widget.winfo_exists():
                    return
                    
                if step < 5:
                    # Gradually lighten the green
                    colors = ["#A5D6A7", "#B9E3BB", "#CEF0CF", "#E3F7E3", "#F1FBF1"]
                    text_widget.tag_configure("fix_success", background=colors[step])
                    text_widget.after(300, lambda: fade_out(step + 1))
                else:
                    text_widget.tag_remove("fix_success", "1.0", "end")
            
            fade_out()
            
            # Close popup first, THEN return focus
            popup.destroy()
            
            # Small delay to ensure popup is fully destroyed before returning focus
            def restore_focus():
                try:
                    # Force editor widget to accept input again
                    text_widget.focus_force()
                    text_widget.mark_set("insert", new_end_index)
                    text_widget.see("insert")
                    # Trigger a click event to fully activate the widget
                    text_widget.event_generate("<Button-1>", x=0, y=0)
                    text_widget.event_generate("<ButtonRelease-1>", x=0, y=0)
                    logger.info("Focus restored to editor after fix")
                except Exception as e:
                    logger.error(f"Failed to restore focus: {e}")
            
            # Use text_widget's after() to ensure proper timing
            text_widget.after(100, restore_focus)
        except Exception as e:
            logger.error(f"Failed to apply fix: {e}")
            popup._closing = True
            popup.destroy()
            # Still try to return focus
            def restore_focus_error():
                try:
                    text_widget.focus_force()
                    text_widget.event_generate("<Button-1>", x=0, y=0)
                    text_widget.event_generate("<ButtonRelease-1>", x=0, y=0)
                except:
                    pass
            text_widget.after(100, restore_focus_error)
    
    def cancel_fix():
        """Cancel and close popup."""
        from thonny.assistance import logger
        popup._closing = True  # Mark as closing
        # Remove diff highlights
        text_widget.tag_remove("diff_delete", "1.0", "end")
        text_widget.tag_remove("diff_insert_marker", "1.0", "end")
        popup.destroy()
        
        # Return focus to editor with delay
        def restore_focus():
            try:
                text_widget.focus_force()
                # Trigger a click event to fully activate
                text_widget.event_generate("<Button-1>", x=0, y=0)
                text_widget.event_generate("<ButtonRelease-1>", x=0, y=0)
                logger.info("Focus restored to editor after cancel")
            except Exception as e:
                logger.error(f"Failed to restore focus in cancel: {e}")
        
        text_widget.after(100, restore_focus)
    
    # Simple buttons with ttk (Thonny style)
    apply_text = "Застосувати" if lang == "uk" else "Применить"
    apply_btn = ttk.Button(
        btn_frame,
        text=apply_text,
        command=apply_fix,
        width=12
    )
    apply_btn.pack(side=tk.LEFT, padx=(0, 5))
    
    cancel_text = "Скасувати" if lang == "uk" else "Отмена"
    cancel_btn = ttk.Button(
        btn_frame,
        text=cancel_text,
        command=cancel_fix,
        width=12
    )
    cancel_btn.pack(side=tk.LEFT)
    
    # Close popup when clicking outside (but not if clicking on buttons)
    popup._closing = False  # Flag to prevent multiple close calls
    
    # Don't auto-close on focus out - it's annoying when switching apps
    # User can close with Escape or Cancel button
    
    # Close on Escape
    popup.bind("<Escape>", lambda e: cancel_fix())
    
    # Close popup if editor is closed
    def on_editor_destroy(event=None):
        if popup.winfo_exists():
            try:
                # Remove diff highlights
                text_widget.tag_remove("diff_delete", "1.0", "end")
                text_widget.tag_remove("diff_insert_marker", "1.0", "end")
                popup.destroy()
            except:
                pass
    
    editor.bind("<Destroy>", on_editor_destroy, add=True)
    
    # Focus popup
    popup.focus_set()
    
    return popup

