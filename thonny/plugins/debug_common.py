"""
Common utilities for debug AI assistants (OpenAI and Gemini)
"""
from typing import Optional
from thonny import get_workbench
from thonny.plugins.debugger import get_current_debugger


def get_debug_context_from_msg(msg) -> Optional[str]:
    """Get debugging context from a specific DebuggerResponse message
    
    This function should be used to capture context at a specific moment,
    avoiding race conditions when debugger state changes.
    """
    if not msg or not hasattr(msg, 'stack'):
        return None
        
    if not msg.stack:
        return None
        
    # Get current frame (top of stack)
    frame = msg.stack[-1]
    
    context_parts = []
    
    # Full program code with current line marked
    try:
        import tokenize
        with tokenize.open(frame.filename) as fp:
            source_lines = fp.readlines()
        
        lang = get_workbench().get_option("ai.language", "uk")
        
        context_parts.append(f"**Full Program Code:**")
        file_label = "Файл"  # Localized label for both uk/ru
        context_parts.append(f"{file_label}: {frame.filename}")
        
        # Show both previous and current line info
        prev_line = frame.lineno - 1 if frame.lineno > 1 else None
        
        if lang == "uk":
            if prev_line:
                context_parts.append(f"**Попередній рядок (щойно виконаний): {prev_line}**")
            context_parts.append(f"**ПОТОЧНИЙ рядок (виконається ЗАРАЗ): {frame.lineno}** ← помічено → нижче")
        else: # ru
            if prev_line:
                context_parts.append(f"**Предыдущая строка (только что выполнена): {prev_line}**")
            context_parts.append(f"**ТЕКУЩАЯ строка (выполнится СЕЙЧАС): {frame.lineno}** ← помечена → ниже")
        
        context_parts.append(f"```python")
        
        # Show entire program (up to 200 lines)
        max_lines = min(len(source_lines), 200)
        
        for i in range(max_lines):
            line_num = i + 1
            line = source_lines[i].rstrip()
            
            if line_num == frame.lineno:
                context_parts.append(f"→ {line_num:4d} | {line}")
            else:
                context_parts.append(f"  {line_num:4d} | {line}")
        
        if len(source_lines) > max_lines:
            context_parts.append(f"... ({len(source_lines) - max_lines} more lines)")
        
        context_parts.append("```")
    except Exception as e:
        context_parts.append(f"(Could not read source code: {e})")
    
    # Variables
    if frame.globals or frame.locals:
        lang = get_workbench().get_option("ai.language", "uk")
        if lang == "uk":
            context_parts.append(f"\n**Поточні змінні (стан ПЕРЕД виконанням рядка {frame.lineno}):**")
        else: # ru
            context_parts.append(f"\n**Текущие переменные (состояние ПЕРЕД выполнением строки {frame.lineno}):**")
        
        # Combine globals and locals
        all_vars = {}
        if frame.globals:
            all_vars.update(frame.globals)
        if frame.locals:
            all_vars.update(frame.locals)
        
        # Filter out internal Python variables
        display_vars = {
            k: v for k, v in all_vars.items() 
            if not k.startswith('__')
        }

        # Determine order of appearance in source up to current line
        ordered_names: list[str] = []
        try:
            import io
            import tokenize as _tokenize

            # Read source again (already loaded above). Use only lines before current line
            lines_before_current = []
            try:
                import tokenize
                with tokenize.open(frame.filename) as fp:
                    all_lines = fp.readlines()
                lines_before_current = all_lines[: max(0, frame.lineno - 1)]
            except Exception:
                lines_before_current = []

            seen = set()
            if lines_before_current and display_vars:
                names_set = set(display_vars.keys())
                src = "".join(lines_before_current)
                for tok in _tokenize.generate_tokens(io.StringIO(src).readline):
                    if tok.type == _tokenize.NAME:
                        name = tok.string
                        if name in names_set and name not in seen:
                            ordered_names.append(name)
                            seen.add(name)
                        # small optimization: break if all found
                        if len(seen) == len(names_set):
                            break
        except Exception:
            # Fallback to no ordering info on error
            ordered_names = []

        if display_vars:
            # Names seen in source first, then the rest in insertion order
            remaining_names = [n for n in display_vars.keys() if n not in set(ordered_names)]
            final_names = ordered_names + remaining_names

            for var_name in final_names:
                var_info = display_vars[var_name]
                # Extract repr from ValueInfo or dict
                if hasattr(var_info, 'repr'):
                    var_repr = var_info.repr
                elif isinstance(var_info, dict) and 'repr' in var_info:
                    var_repr = var_info['repr']
                else:
                    var_repr = str(var_info)
                context_parts.append(f"  {var_name} = {var_repr}")
        else:
            if lang == "uk":
                context_parts.append("  (немає змінних)")
            else: # ru
                context_parts.append("  (нет переменных)")
    
    return "\n".join(context_parts)

def format_code_context(full_code: str, filename: str = "program.py") -> str:
    """Format code context for non-debug mode
    
    Args:
        full_code: The full program code
        filename: Optional filename for display
        
    Returns:
        Formatted code context similar to debug context but without execution state
    """
    context_parts = []
    
    context_parts.append(f"**Full Program Code:**")
    context_parts.append(f"Файл: {filename}")
    context_parts.append(f"```python")
    
    # Add line numbers to code
    lines = full_code.split('\n')
    for i, line in enumerate(lines, 1):
        context_parts.append(f"  {i:4d} | {line}")
    
    context_parts.append("```")
    
    return "\n".join(context_parts)


def get_debug_context() -> Optional[str]:
    """Get current debugging context from debugger's last message
    
    DEPRECATED: This reads from debugger._last_progress_message which may
    change during execution. Prefer get_debug_context_from_msg() for
    capturing context at a specific moment.
    """
    debugger = get_current_debugger()
    if not debugger or not debugger._last_progress_message:
        return None
    
    return get_debug_context_from_msg(debugger._last_progress_message)

