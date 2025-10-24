"""
Utilities for creating AI explanation popups.
Shared between CodeViewText and CodeView classes.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from thonny import get_workbench
from thonny.languages import tr


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
        state="normal"
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

