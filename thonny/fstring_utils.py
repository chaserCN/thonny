"""
Utilities for parsing f-string interpolations.
Used for syntax highlighting and testing.
"""


def parse_fstring_interpolations(fstring_text):
    r"""
    Parse f-string to find all interpolation blocks {...}.
    Returns list of (start, end, code_content) tuples.
    
    Correctly handles:
    - {{escaped}} - skipped (literal braces)
    - {x} - simple interpolation
    - {{'key': x}} - dict literal in interpolation
    - {data['key']} - nested braces in code
    
    Args:
        fstring_text: The f-string content WITHOUT the 'f' prefix
                      (both single-line and multi-line strings supported)
    
    Returns:
        List of tuples (start, end, code_content) where:
        - start: index of opening { (inclusive)
        - end: index after closing } (exclusive)
        - code_content: the Python code inside {...}
    
    Example:
        >>> parse_fstring_interpolations('"Name: {name}"')
        [(7, 13, 'name')]
        >>> parse_fstring_interpolations('"{data[\'key\']}"')
        [(1, 14, "data['key']")]
    """
    interpolations = []
    i = 0
    while i < len(fstring_text):
        if fstring_text[i] == '{':
            # Check if this is escaped: {{
            if i + 1 < len(fstring_text) and fstring_text[i + 1] == '{':
                i += 2  # Skip both braces
                continue
            
            # This is start of interpolation
            interp_start = i
            i += 1
            brace_depth = 1  # Track nested braces like {data['key']}
            code_start = i
            
            # Find matching closing brace
            while i < len(fstring_text) and brace_depth > 0:
                if fstring_text[i] == '{':
                    brace_depth += 1
                elif fstring_text[i] == '}':
                    # Inside interpolation, } always closes brace
                    # (escaped }} only exists OUTSIDE interpolation)
                    brace_depth -= 1
                i += 1
            
            interp_end = i
            code_content = fstring_text[code_start:interp_end - 1]
            interpolations.append((interp_start, interp_end, code_content))
        
        elif fstring_text[i] == '}':
            # Check if this is escaped: }}
            if i + 1 < len(fstring_text) and fstring_text[i + 1] == '}':
                i += 2  # Skip both braces
                continue
            i += 1
        else:
            i += 1
    
    return interpolations

