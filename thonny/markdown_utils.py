"""Markdown rendering utilities for Thonny UI"""
import re
import tkinter as tk


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
    
    # Configure tags if not already done
    if "md_heading" not in text_widget.tag_names():
        text_widget.tag_configure("md_heading", font=("TkDefaultFont", 10, "bold"), spacing1=0, spacing3=2)
        text_widget.tag_configure("md_normal_text", font=("TkDefaultFont", 10), spacing1=0, spacing3=8)
        text_widget.tag_configure("md_code_block", font=("TkFixedFont", 9), background="#f5f5f5", spacing1=0, spacing3=8, lmargin1=10, lmargin2=10, selectbackground="#4A90E2", selectforeground="white")
        text_widget.tag_configure("md_inline_code", font=("TkFixedFont", 9), background="#f5f5f5", selectbackground="#4A90E2", selectforeground="white")
        text_widget.tag_configure("md_bold", font=("TkDefaultFont", 10, "bold"))
        text_widget.tag_configure("md_italic", font=("TkDefaultFont", 10, "italic"))
        text_widget.tag_configure("md_list_item", lmargin1=20, lmargin2=30, spacing1=0, spacing3=2)
    
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
                text_widget.tag_add("md_inline_code", code_start, text_widget.index("end-1c"))
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
                text_widget.tag_add("md_code_block", start, text_widget.index("end-1c"))
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

