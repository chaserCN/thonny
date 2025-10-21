#!/usr/bin/env python3
"""Simple markdown renderer for tkinter with adjustable spacing"""
import tkinter as tk
import re

def render_markdown(text_widget, markdown_text, spacing_heading=2, spacing_code=8, spacing_text=8):
    """Render markdown in tk.Text widget with customizable spacing"""
    
    # Configure tags
    text_widget.tag_configure(
        "heading", 
        font=("TkDefaultFont", 10, "bold"), 
        spacing1=0, 
        spacing3=spacing_heading
    )
    text_widget.tag_configure(
        "normal_text", 
        font=("TkDefaultFont", 10), 
        spacing1=0, 
        spacing3=spacing_text
    )
    text_widget.tag_configure(
        "code_block", 
        font=("TkFixedFont", 9), 
        background="#f5f5f5", 
        spacing1=0, 
        spacing3=spacing_code,
        lmargin1=10,
        lmargin2=10
    )
    text_widget.tag_configure(
        "inline_code", 
        font=("TkFixedFont", 9), 
        background="#f5f5f5"
    )
    text_widget.tag_configure(
        "bold",
        font=("TkDefaultFont", 10, "bold")
    )
    text_widget.tag_configure(
        "italic",
        font=("TkDefaultFont", 10, "italic")
    )
    text_widget.tag_configure(
        "list_item",
        lmargin1=20,
        lmargin2=30,
        spacing1=0,
        spacing3=2
    )
    
    lines = markdown_text.split("\n")
    i = 0
    
    def insert_formatted_text(text):
        """Insert text with inline formatting (bold, italic, code)"""
        # Order matters: handle code first to avoid interfering with ** and *
        parts = re.split(r'(`[^`]+`)', text)
        
        for part in parts:
            if part.startswith("`") and part.endswith("`"):
                # Inline code
                code_content = part[1:-1]
                code_start = text_widget.index("end-1c")
                text_widget.insert("end", code_content)
                text_widget.tag_add("inline_code", code_start, text_widget.index("end-1c"))
            else:
                # Handle bold and italic
                # Bold: **text**
                subparts = re.split(r'(\*\*[^*]+\*\*)', part)
                for subpart in subparts:
                    if subpart.startswith("**") and subpart.endswith("**"):
                        bold_text = subpart[2:-2]
                        bold_start = text_widget.index("end-1c")
                        text_widget.insert("end", bold_text)
                        text_widget.tag_add("bold", bold_start, text_widget.index("end-1c"))
                    else:
                        # Handle italic: *text* (but not ** which is already handled)
                        italic_parts = re.split(r'(\*[^*]+\*)', subpart)
                        for italic_part in italic_parts:
                            if italic_part.startswith("*") and italic_part.endswith("*") and not italic_part.startswith("**"):
                                italic_text = italic_part[1:-1]
                                italic_start = text_widget.index("end-1c")
                                text_widget.insert("end", italic_text)
                                text_widget.tag_add("italic", italic_start, text_widget.index("end-1c"))
                            else:
                                text_widget.insert("end", italic_part)
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Handle empty lines - preserve them
        if not stripped:
            text_widget.insert("end", "\n")
            i += 1
            continue
        
        # Check for code block: ```
        if stripped.startswith("```"):
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
                text_widget.insert("end", code_text)
                text_widget.tag_add("code_block", start, text_widget.index("end-1c"))
            continue
        
        # Check for headings with #
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip() + "\n"
            start = text_widget.index("end-1c")
            text_widget.insert("end", heading_text)
            text_widget.tag_add("heading", start, text_widget.index("end-1c"))
            i += 1
            continue
        
        # Check for bold heading: **text:** (entire line)
        if stripped.startswith("**") and stripped.endswith("**"):
            heading_text = stripped.strip("*") + "\n"
            start = text_widget.index("end-1c")
            text_widget.insert("end", heading_text)
            text_widget.tag_add("heading", start, text_widget.index("end-1c"))
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
                        text_widget.insert("end", var_text)
                        text_widget.tag_add("code_block", start, text_widget.index("end-1c"))
            continue
        
        # Check for list items: - or * or numbers 1.
        list_match = re.match(r'^(\s*)([-*]|\d+\.)\s+(.*)$', stripped)
        if list_match:
            bullet = list_match.group(2)
            content = list_match.group(3)
            
            line_start = text_widget.index("end-1c")
            text_widget.insert("end", "• " if bullet in ['-', '*'] else f"{bullet} ")
            insert_formatted_text(content)
            text_widget.insert("end", "\n")
            text_widget.tag_add("list_item", line_start, text_widget.index("end-1c"))
            i += 1
            continue
        
        # Regular line - handle inline formatting
        if stripped:
            line_start = text_widget.index("end-1c")
            insert_formatted_text(line)
            text_widget.insert("end", "\n")
            # Tag the whole line as normal_text for spacing
            text_widget.tag_add("normal_text", line_start, text_widget.index("end-1c"))
        
        i += 1


def main():
    root = tk.Tk()
    root.title("Markdown Spacing Test")
    root.geometry("800x600")
    
    # Test markdown from AI - comprehensive example
    markdown = """**Что произошло:**
Программа попросила ввести число для "n=" и запомнила его как 3.

**Текущее состояние:**
n = 3

**Что дальше:**
Сейчас выполнится: `mas=list(map(int,input().split()))`
Программа ждёт, когда ты введёшь несколько чисел через пробел, и сохранит их в список под названием `mas`.

## Дополнительные примеры

Это **жирный текст** и это *курсив*.

Список с пунктами:
- Первый пункт с `inline code`
- Второй пункт с **жирным**
- Третий пункт

Нумерованный список:
1. Первый элемент
2. Второй элемент
3. Третий элемент

Пример кода:
```python
def hello():
    print("Hello, world!")
```

Обычный текст после кода."""
    
    # Controls frame
    controls = tk.Frame(root)
    controls.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
    
    tk.Label(controls, text="spacing_heading:").pack(side=tk.LEFT)
    heading_var = tk.IntVar(value=2)
    heading_spin = tk.Spinbox(controls, from_=0, to=50, textvariable=heading_var, width=5)
    heading_spin.pack(side=tk.LEFT, padx=5)
    
    tk.Label(controls, text="spacing_code:").pack(side=tk.LEFT)
    code_var = tk.IntVar(value=8)
    code_spin = tk.Spinbox(controls, from_=0, to=50, textvariable=code_var, width=5)
    code_spin.pack(side=tk.LEFT, padx=5)
    
    tk.Label(controls, text="spacing_text:").pack(side=tk.LEFT)
    text_var = tk.IntVar(value=8)
    text_spin = tk.Spinbox(controls, from_=0, to=50, textvariable=text_var, width=5)
    text_spin.pack(side=tk.LEFT, padx=5)
    
    # Text widget
    txt = tk.Text(root, wrap=tk.WORD, background="white", foreground="black")
    txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    def update():
        txt.delete("1.0", "end")
        render_markdown(
            txt, 
            markdown,
            spacing_heading=heading_var.get(),
            spacing_code=code_var.get(),
            spacing_text=text_var.get()
        )
    
    update_btn = tk.Button(controls, text="Обновить", command=update)
    update_btn.pack(side=tk.LEFT, padx=10)
    
    # Initial render
    update()
    
    root.mainloop()


if __name__ == "__main__":
    main()

