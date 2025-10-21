import tkinter as tk
import re


def markdown_to_rst(markdown_text: str) -> str:
    """Convert limited Markdown to RST - copied from ChatView for testing"""
    lines = markdown_text.split("\n")
    rst_lines: list[str] = []

    in_fenced_code = False
    fenced_code_lines: list[str] = []
    previous_was_bullet = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Handle fenced code blocks
        if stripped.startswith("```"):
            if not in_fenced_code:
                in_fenced_code = True
                fenced_code_lines = []
            else:
                # close fenced block → RST literal block
                in_fenced_code = False
                # Ensure exactly one empty line before ::
                if len(rst_lines) > 0 and rst_lines[-1].strip() != "":
                    rst_lines.append("")
                rst_lines.append("::")
                rst_lines.append("")  # required by RST literal block
                for cl in fenced_code_lines:
                    rst_lines.append("    " + cl)
                rst_lines.append("")  # trailing empty line to close the block
            i += 1
            continue

        if in_fenced_code:
            fenced_code_lines.append(line)
            i += 1
            continue

        # Convert inline code
        line = re.sub(r"`([^`]+)`", r"``\1``", line)

        # Simple Markdown headings (# → bold)
        if line.startswith('# '):
            line = '**' + line[2:] + '**'
        elif line.startswith('## '):
            line = '**' + line[3:] + '**'
        elif line.startswith('### '):
            line = '**' + line[4:] + '**'

        # Generic detection of variable assignment blocks to preserve line breaks
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*.+$', stripped):
            # Collect contiguous variable assignment lines
            var_lines: list[str] = [line.rstrip()]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                nxs = nxt.strip()
                if nxs == "":
                    # allow a single blank inside block to be ignored
                    i += 1
                    continue
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*.+$', nxs):
                    break
                var_lines.append(nxt.rstrip())
                i += 1

            # Emit as a compact literal block.
            # Check if previous line is the heading "Текущее состояние:" or "Поточний стан:"
            prev = rst_lines[-1].strip() if rst_lines else ""
            if prev.startswith('**Текущее состояние:**') or prev.startswith('**Поточний стан:**'):
                # Append :: to the heading line (inline literal block marker)
                rst_lines[-1] = rst_lines[-1] + '::'
                rst_lines.append("")  # Required by RST
            else:
                # Insert blank line, then :: on separate line
                rst_lines.append("")
                rst_lines.append("::")
                rst_lines.append("")
            
            for vl in var_lines:
                rst_lines.append("    " + vl)
            rst_lines.append("")
            continue

        # Ensure a real line break after the "Сейчас/Зараз выполнится:" line
        if re.match(r'^(Сейчас|Зараз)\s+(выполнится|виконається):', stripped):
            rst_lines.append(line)
            rst_lines.append("")
            i += 1
            continue

        # List handling (bullet and numbered): ensure a blank line before first item
        is_list_item = (stripped.startswith('- ') or stripped.startswith('* ') or
                       re.match(r'^\d+\)', stripped))
        
        if is_list_item:
            if len(rst_lines) > 0 and rst_lines[-1].strip() != "" and not previous_was_bullet:
                rst_lines.append("")
            
            # Convert bullet markers to RST-friendly form
            if stripped.startswith('- ') or stripped.startswith('* '):
                indent = len(line) - len(stripped)
                line = (" " * indent) + "* " + stripped[2:]

            rst_lines.append(line)
            previous_was_bullet = True
            i += 1
            continue

        previous_was_bullet = False

        # Default: keep line as-is (RST will wrap normal paragraphs)
        # But collapse excessive empty lines (AI sometimes emits many) to max one
        if stripped == "" and len(rst_lines) > 0 and rst_lines[-1].strip() == "":
            i += 1
            continue
        rst_lines.append(line)
        i += 1

    return "\n".join(rst_lines)


def main() -> None:
    # Sample markdown from the user
    md = """**Что произошло:**
Программа попросила ввести число для "n=" и запомнила его как 3.

**Текущее состояние:**
n = 3

**Что дальше:**
Сейчас выполнится: `mas=list(map(int,input().split()))`
Программа ждёт, когда ты введёшь несколько чисел через пробел, и сохранит их в список под названием `mas`.
"""

    # Initialize Tk first
    root = tk.Tk()
    root.title("Debug Message Formatting Test (Direct Tags)")
    root.geometry("700x500")

    # Create simple Text widget
    txt = tk.Text(root, wrap=tk.WORD, background="white", foreground="black")
    txt.pack(fill=tk.BOTH, expand=True)
    
    # Configure tags directly
    txt.tag_configure("debug_heading", font=("TkDefaultFont", 10, "bold"), spacing1=0, spacing3=2)
    txt.tag_configure("debug_text", font=("TkDefaultFont", 10), spacing1=0, spacing3=8)
    txt.tag_configure("debug_code", font=("TkFixedFont", 9), background="#f5f5f5", spacing1=0, spacing3=8)
    txt.tag_configure("debug_inline_code", font=("TkFixedFont", 9), background="#f5f5f5")
    
    # Simple test: insert text with different spacing tags
    import re
    
    # Test 1: Heading
    start = txt.index("end-1c")
    txt.insert("end", "Что произошло:\n")
    txt.tag_add("debug_heading", start, txt.index("end-1c"))
    
    # Test 2: Normal text
    txt.insert("end", "Программа попросила ввести число.\n")
    
    # Test 3: Heading
    start = txt.index("end-1c")
    txt.insert("end", "Текущее состояние:\n")
    txt.tag_add("debug_heading", start, txt.index("end-1c"))
    
    # Test 4: Code block (variables)
    start = txt.index("end-1c")
    txt.insert("end", "n = 3\n")
    txt.tag_add("debug_code", start, txt.index("end-1c"))
    
    # Test 5: Heading
    start = txt.index("end-1c")
    txt.insert("end", "Что дальше:\n")
    txt.tag_add("debug_heading", start, txt.index("end-1c"))
    
    # Test 6: Text with inline code
    txt.insert("end", "Сейчас выполнится: ")
    start = txt.index("end-1c")
    txt.insert("end", "mas=list(...)")
    txt.tag_add("debug_inline_code", start, txt.index("end-1c"))
    txt.insert("end", "\n")
    txt.insert("end", "Программа ждёт ввода.\n")

    root.mainloop()


if __name__ == "__main__":
    main()
