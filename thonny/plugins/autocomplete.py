import re
import tkinter as tk
from logging import getLogger
from tkinter import messagebox
from typing import List, Optional, Union, cast

from thonny import editor_helpers, get_runner, get_workbench, lsp_types
from thonny.codeview import CodeViewText, SyntaxText, get_syntax_options_for_tag
from thonny.editor_helpers import DocuBox, EditorInfoBox
from thonny.languages import tr
from thonny.lsp_types import CompletionItem, CompletionItemKind, CompletionParams, LspResponse, TextDocumentIdentifier
from thonny.misc_utils import running_on_mac_os
from thonny.shell import ShellText
from thonny.ui_utils import (
    alt_is_pressed_without_char,
    command_is_pressed,
    control_is_pressed,
    ems_to_pixels,
)

logger = getLogger(__name__)

"""
Completions get computed on the backend, therefore getting the completions is
asynchronous.
"""


def filter_garbage_completions(completions: list) -> list:
    """
    Filter out builtin interactive garbage and dunder names.
    
    These are variables that Python adds in REPL but shouldn't appear in autocomplete:
    - copyright, credits, exit, help, license, quit (interactive helpers)
    - Ellipsis, ellipsis, NotImplemented (rarely used builtins)
    - __name__, __file__, etc. (dunder names)
    - Keyword arguments like end=, sep=, file=, flush= (only useful inside function calls)
    """
    garbage_builtins = {
        # Interactive helpers
        'copyright', 'credits', 'exit', 'help', 'license', 'quit',
        # Rarely used builtins
        'Ellipsis', 'ellipsis', 'NotImplemented',
        # Exception aliases (OSError is the canonical name)
        'EnvironmentError', 'IOError', 'WindowsError',
    }
    
    filtered = []
    for comp in completions:
        # Check each filter condition
        if comp.label.startswith("__"):
            continue  # Filter dunders
        if comp.label in garbage_builtins:
            continue  # Filter garbage builtins
        # Filter keyword arguments (Variable with '=' suffix)
        if comp.kind and comp.kind == CompletionItemKind.Variable and comp.label.endswith("="):
            logger.info(f"🗑️  Filtering keyword arg: {comp.label}")
            continue
        if comp.textEdit is not None:
            continue  # TODO: support textEdit
        if comp.additionalTextEdits:
            continue  # TODO: support this
        
        filtered.append(comp)
    
    return filtered


# Popular Python functions ordered by priority for SCHOOL usage
POPULAR_FUNCTIONS_ORDER = [
    # Tier 1: Most used in school (everyday functions)
    'print', 'input', 'len', 'int', 'str', 'float', 'range',
    # Tier 2: Data structures & common operations
    'list', 'dict', 'set', 'tuple', 'max', 'min', 'sum', 
    # Tier 3: Math & utilities
    'abs', 'round', 'sorted', 'open', 'sqrt',
    # Tier 4: Type checking & advanced
    'isinstance', 'type', 'bool', 'any', 'all',
    # Tier 5: Functional programming (less common in school)
    'enumerate', 'zip', 'map', 'filter', 'format',
    # Tier 6: Advanced (rarely used in school)
    'getattr', 'hasattr', 'super', 'repr'
]


def get_popular_function_boost(label: str) -> tuple[int, str]:
    """
    Return boost value and reason for popular Python functions.
    
    Returns:
        (boost, reason) where boost is negative (higher priority) or 0 (no boost)
    """
    if label in POPULAR_FUNCTIONS_ORDER:
        position = POPULAR_FUNCTIONS_ORDER.index(label)
        boost = -(100 - position)  # -100 for print, -99 for input, etc.
        reason = f"popular function (#{position+1})"
        return (boost, reason)
    return (0, "")


def _infer_variable_types_with_parso(source_code: str, cursor_line: int = None) -> tuple[dict, set, set, str, set]:
    """
    Use parso (1 parse call!) to:
    1. Infer types for variables (list, dict, set, tuple)
    2. Extract ALL user-defined variable names
    3. Extract loop variables (for x in ...)
    4. Find current function (where cursor is)
    5. Extract user-defined function names
    
    Args:
        source_code: Python code to analyze
        cursor_line: 1-based line number where cursor is (optional)
    
    Returns: (var_types_dict, user_defined_vars_set, loop_vars_set, current_function_name, user_functions_set)
    """
    try:
        import parso
        from parso.python import tree
        
        logger.info(f"🔬 PARSO: Analyzing {len(source_code)} chars of code...")
        
        var_types = {}  # {var_name: type_hint}
        user_defined_vars = set()  # ALL variable names
        user_functions = set()  # User-defined function names
        current_function = ""  # Function where cursor is
        
        module = parso.parse(source_code)
        
        assignments_found = []  # For logging
        loop_vars_found = []  # For logging
        functions_found = []  # For logging
        
        def get_outermost_function_name(node):
            """Extract outermost function name from expression like list(map(...))"""
            if node.type == 'atom_expr' and hasattr(node, 'children') and len(node.children) >= 2:
                # atom_expr: list(...) or foo.bar(...)
                # children[0] = name, children[1] = trailer (the parentheses)
                first_child = node.children[0]
                if first_child.type == 'name':
                    return first_child.value
            elif node.type == 'power' and hasattr(node, 'children'):
                # power = name + trailer*
                if node.children[0].type == 'name':
                    return node.children[0].value
            elif node.type == 'name':
                return node.value
            return None
        
        def analyze_node(node):
            # Look for assignments: x = [...]
            if isinstance(node, tree.ExprStmt) and node.children[0].type == 'name':
                var_name = node.children[0].value
                user_defined_vars.add(var_name)  # Track ALL assignments (except in functions)
                
                # Check if it's simple assignment (x = ...)
                if len(node.children) >= 3 and node.children[1].value == '=':
                    value = node.children[2]
                    value_type = value.type
                    inferred_type = None
                    
                    # Check for literals by looking at first character
                    if hasattr(value, 'children') and value.children:
                        first_char = value.children[0].value if hasattr(value.children[0], 'value') else None
                        
                        # List literal: x = [1, 2, 3]
                        if first_char == '[':
                            var_types[var_name] = 'list'  # OVERWRITE if already exists (take latest)
                            inferred_type = 'list'
                        
                        # Dict or Set literal: x = {1: 2} or x = {1, 2}
                        elif first_char == '{':
                            # Check if it's dict (has ':') or set (no ':')
                            # Empty {} is always dict
                            if len(value.children) == 2:  # Just { and }
                                var_types[var_name] = 'dict'
                                inferred_type = 'dict'
                            else:
                                # Look for ':' to distinguish dict from set
                                has_colon = False
                                for child in value.children:
                                    if hasattr(child, 'value') and child.value == ':':
                                        has_colon = True
                                        break
                                    # Also check in nested children
                                    if hasattr(child, 'children'):
                                        for subchild in child.children:
                                            if hasattr(subchild, 'value') and subchild.value == ':':
                                                has_colon = True
                                                break
                                
                                if has_colon:
                                    var_types[var_name] = 'dict'
                                    inferred_type = 'dict'
                                else:
                                    var_types[var_name] = 'set'
                                    inferred_type = 'set'
                        
                        # Tuple literal: x = (1, 2)
                        elif first_char == '(':
                            var_types[var_name] = 'tuple'
                            inferred_type = 'tuple'
                    
                    # String literal: x = "hello" or x = 'hello'
                    if not inferred_type and value.type == 'string':
                        var_types[var_name] = 'str'
                        inferred_type = 'str'
                    
                    # Number literal: x = 42 or x = 3.14
                    if not inferred_type and value.type == 'number':
                        # Determine if int or float by checking for '.'
                        num_str = value.value
                        if '.' in num_str:
                            var_types[var_name] = 'float'
                            inferred_type = 'float'
                        else:
                            var_types[var_name] = 'int'
                            inferred_type = 'int'
                    
                    # Tuple from testlist (without parens): x = 1, 2
                    if not inferred_type and value.type == 'testlist':
                        var_types[var_name] = 'tuple'
                        inferred_type = 'tuple'
                    
                # Function calls: x = list(...), x = dict(...), even nested like list(map(...))
                if not inferred_type:
                    func_name = get_outermost_function_name(value)
                    if func_name and func_name in ('list', 'dict', 'set', 'tuple', 'range', 'enumerate', 
                                                   'zip', 'map', 'filter', 'reversed', 'sorted'):
                        var_types[var_name] = func_name
                        inferred_type = func_name
                    
                    # Track what we found (LATEST assignment wins)
                    if inferred_type:
                        # Remove old assignment if exists
                        assignments_found[:] = [a for a in assignments_found if not a.startswith(f"{var_name}=")]
                        assignments_found.append(f"{var_name}={inferred_type}")
            
            # Look for for-loop variables: for x in ...
            elif node.type == 'for_stmt' and hasattr(node, 'children') and len(node.children) >= 2:
                # for_stmt: 'for' exprlist 'in' testlist ':' suite
                if node.children[1].type == 'name':
                    loop_var = node.children[1].value
                    user_defined_vars.add(loop_var)
                    loop_vars_found.append(loop_var)
            
            # Look for function definitions: def func_name(...):
            elif node.type == 'funcdef' and hasattr(node, 'children') and len(node.children) >= 2:
                # funcdef: 'def' name parameters ':' suite
                if node.children[1].type == 'name':
                    func_name = node.children[1].value
                    user_functions.add(func_name)
                    functions_found.append(func_name)
                    
                    # Check if cursor is inside this function
                    nonlocal current_function
                    if cursor_line and hasattr(node, 'start_pos') and hasattr(node, 'end_pos'):
                        func_start_line = node.start_pos[0]
                        func_end_line = node.end_pos[0]
                        if func_start_line <= cursor_line <= func_end_line:
                            current_function = func_name
                            
                            # Extract function parameters if cursor is inside
                            # funcdef: children[2] = parameters
                            if len(node.children) >= 3 and node.children[2].type == 'parameters':
                                params_node = node.children[2]
                                # Extract parameter names (skip self, cls, *args, **kwargs)
                                def extract_params(params):
                                    """Recursively extract parameter names"""
                                    param_names = []
                                    if hasattr(params, 'children'):
                                        for child in params.children:
                                            if child.type == 'param' and hasattr(child, 'children'):
                                                # param has children: name [, '=', default_value]
                                                name_node = child.children[0]
                                                if name_node.type == 'name':
                                                    param_name = name_node.value
                                                    # Skip self, cls (common in methods)
                                                    if param_name not in ('self', 'cls'):
                                                        param_names.append(param_name)
                                            elif child.type == 'name':
                                                # Simple parameter without default
                                                param_name = child.value
                                                if param_name not in ('self', 'cls'):
                                                    param_names.append(param_name)
                                    return param_names
                                
                                param_names = extract_params(params_node)
                                for param_name in param_names:
                                    user_defined_vars.add(param_name)
                                    logger.info(f"   ✓ Function parameter: {param_name}")

            
            # Recursively process children
            if hasattr(node, 'children'):
                for child in node.children:
                    analyze_node(child)
        
        analyze_node(module)
        
        # Log results
        if assignments_found:
            logger.info(f"   ✓ Type inference: {', '.join(assignments_found)}")
        if loop_vars_found:
            logger.info(f"   ✓ Loop variables: {', '.join(loop_vars_found)}")
        if functions_found:
            logger.info(f"   ✓ User functions: {', '.join(functions_found)}")
        if current_function:
            logger.info(f"   📍 Cursor in function: {current_function}")
        
        other_vars = user_defined_vars - set(var_types.keys()) - set(loop_vars_found)
        if other_vars:
            logger.info(f"   ✓ Other assignments: {', '.join(sorted(other_vars))}")
        
        logger.info(f"   📊 Total: {len(user_defined_vars)} user-defined vars, {len(var_types)} with inferred types, {len(user_functions)} functions")
        
        loop_vars_set = set(loop_vars_found)
        return var_types, user_defined_vars, loop_vars_set, current_function, user_functions
        
    except Exception as e:
        logger.warning(f"Parso type inference failed: {e}")
        return {}, set(), set(), "", set()


def create_context_aware_sort_key(prefix: str, line_before_cursor: str, line_after_cursor: str, 
                                   source_code: str = None):
    """
    Factory function that creates a sort_key function for context-aware completion ranking.
    
    This enables fast local ranking (< 5ms) without AI, by analyzing:
    - Prefix matching (existing logic)
    - Context (for loops, imports, dot access, etc.)
    - Type information from LSP
    - Simple type inference via Parso (for small files)
    
    Args:
        prefix: The text user has typed so far
        line_before_cursor: Text from line start to cursor
        line_after_cursor: Text from cursor to line end
        source_code: Full source code (optional, for parso inference)
        
    Returns:
        A sort_key function that can be used with sorted()
    """
    logger.info(f"🔍 create_context_aware_sort_key: prefix={repr(prefix)}, line_before={repr(line_before_cursor)}")
    
    # Use parso (1 call!) to get types AND user-defined variables
    var_types = {}
    user_defined_vars = set()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🎯 CONTEXT-AWARE SORTING")
    logger.info(f"   Prefix: {prefix!r}")
    logger.info(f"   Line before: {line_before_cursor!r}")
    logger.info(f"   Line after: {line_after_cursor!r}")
    logger.info(f"   Source code length: {len(source_code) if source_code else 0} chars")
    
    # Calculate cursor line for function context detection
    cursor_line = None
    if source_code:
        lines_before = source_code[:source_code.rfind(line_before_cursor) + len(line_before_cursor)].split('\n')
        cursor_line = len(lines_before)
    
    if source_code and len(source_code) < 5000:  # Only for small files (< 5KB)
        var_types, user_defined_vars, loop_vars, current_function, user_functions = _infer_variable_types_with_parso(source_code, cursor_line)
        if user_defined_vars:
            logger.info(f"👤 User-defined vars: {sorted(user_defined_vars)}")
        if var_types:
            logger.info(f"🔬 Inferred types: {var_types}")
        if loop_vars:
            logger.info(f"🔁 Loop variables: {sorted(loop_vars)}")
        if user_functions:
            logger.info(f"🎯 User functions: {sorted(user_functions)}")
        if current_function:
            logger.info(f"📍 Current function: {current_function}")
    else:
        # Fallback for large files or when Parso unavailable
        var_types, user_defined_vars, loop_vars, current_function, user_functions = {}, set(), set(), "", set()
    
    logger.info(f"{'='*60}\n")
    
    def sort_key(completion: lsp_types.CompletionItem):
        sort_text = completion.sortText or completion.label
        label = completion.label
        kind = completion.kind
        detail = completion.detail or ""

        # Base prefix priority (DOMINANT factor - in thousands to override context_boost)
        # Context_boost range: -2000 to +300 (2300 units)
        # Prefix must be stronger to ensure matching items appear first!
        if not prefix:
            prefix_priority = 1000 if label.startswith("_") else 0
        elif label.startswith(prefix):
            # Check if user-defined (for Functions/Classes)
            # For variables, we check user_defined_vars in context boost
            # For functions/classes, sortText still works OK for now (LSP marks user-defined differently)
            is_user_defined_func = sort_text.startswith(('00.', '01.', '02.'))
            
            if kind and kind == CompletionItemKind.Variable:  # Variable - highest priority
                prefix_priority = -10000
            elif kind and kind in (CompletionItemKind.Function, CompletionItemKind.Class, CompletionItemKind.Module) and is_user_defined_func:  # User-defined Function/Class/Module
                prefix_priority = -8000
            elif kind and kind in (CompletionItemKind.Function, CompletionItemKind.Class, CompletionItemKind.Module):  # Builtin Function/Class
                prefix_priority = -6000
            else:
                prefix_priority = -5000  # Keywords and other builtins
        elif label.lower().startswith(prefix.lower()):
            prefix_priority = -2500  # Case-insensitive still very important
        else:
            prefix_priority = 0
        
        # Context-aware boost (NEW: makes autocomplete smarter!)
        context_boost = 0
        boost_reason = None  # For logging
        
        # GLOBAL: Boost most popular Python functions/classes (always helpful)
        if kind and kind in (CompletionItemKind.Function, CompletionItemKind.Class):  # Function or Class
            func_boost, func_reason = get_popular_function_boost(label)
            if func_boost != 0:
                context_boost += func_boost  # Add negative boost (higher priority)
                boost_reason = func_reason
        
        # 1. FOR LOOPS: boost iterables after "for x in "
        # BUT: skip if inside range() - that has its own context!
        is_inside_range = "range(" in line_before_cursor
        
        # Extract loop variable name from "for <var> in " to demote it
        # (prevents "for i in i" which is nonsensical)
        loop_var_name = None
        if " in " in line_before_cursor and not is_inside_range:
            # Try to extract: "for item in " -> "item"
            match = re.search(r'\bfor\s+(\w+)\s+in\s', line_before_cursor)
            if match:
                loop_var_name = match.group(1)
        
        if (" in " in line_before_cursor or line_before_cursor.strip().startswith("for ")) and not is_inside_range:
            # Check if this is a user-defined function (for Functions kind=3)
            is_user_function = (kind and kind == CompletionItemKind.Function and label in user_functions)
            
            if " in " in line_before_cursor:
                after_in = line_before_cursor.split(" in ")[-1].strip()
                # If cursor right after "in" or user started typing
                if len(after_in) <= len(prefix) + 3:
                    pass  # Context applies to all completions
            
            # DEMOTE the loop variable itself (for i in i is nonsensical!)
            if loop_var_name and label == loop_var_name and kind and kind == CompletionItemKind.Variable:
                context_boost += 2000  # Strong demotion - push to bottom
                boost_reason = f"for..in: demote loop var itself (for {loop_var_name} in {loop_var_name})"
                    
            # SPECIAL: range() is very common, but user-defined vars are more important!
            if label == "range":
                context_boost -= 900  # Strong boost, but below user vars (-1050+)
                boost_reason = f"for..in: range (common builtin)"
            elif is_user_function:
                # User-defined function - high priority but below user vars and range
                context_boost -= 800
                boost_reason = f"for..in: user function"
            # Very common iteration helpers
            elif label in ["enumerate", "sorted", "reversed"]:
                context_boost -= 700  # Very strong boost (after range)
                boost_reason = f"for..in: common iterator ({label})"
            # STRONG boost for other iterable-returning functions/classes
            elif label in ["zip", "map", "filter", 
                           "list", "tuple", "set", "dict", "keys", "values", "items"]:
                # These can be Class or Function in LSP - boost both!
                context_boost -= 500  # Very strong boost
                boost_reason = f"for..in: iterable {lsp_types.CompletionItemKind(kind).name if kind else ''}"
            
            # Boost variables/objects (STRONGEST for user-defined!)
            elif kind and kind == CompletionItemKind.Variable:  # Variable
                # Check if it's user-defined (exists in source code)
                is_user_defined = label in user_defined_vars
                detail_lower = detail.lower()
                
                # Check parso-inferred type
                parso_type = var_types.get(label, '')
                
                if is_user_defined:
                    # User-defined variable - check if it's iterable!
                    if parso_type in ('list', 'dict', 'set', 'tuple', 'range', 'enumerate', 'zip', 'map', 'filter', 'str'):
                        context_boost -= 1050  # HIGHER than user functions (-800) and range (-900)
                        boost_reason = f"for..in: local {parso_type}"
                    elif parso_type in ('int', 'float', 'bool'):
                        # Known non-iterable types
                        context_boost += 300  # Demote - not useful for iteration
                        boost_reason = f"for..in: demote {parso_type} (not iterable)"
                    elif label in loop_vars:
                        # Loop variable from outer loop (likely iterable in nested loops!)
                        context_boost -= 1200  # STRONGEST boost - outer loop vars are #1 in nested loops!
                        boost_reason = f"for..in: outer loop var (likely iterable)"
                    else:
                        # Unknown type - might be iterable, give small boost
                        context_boost -= 200  # Small boost for unknown user vars
                        boost_reason = f"for..in: user-defined var (unknown type)"
                elif parso_type in ('list', 'dict', 'set', 'tuple', 'range'):
                    # Parso knows it's iterable
                    context_boost -= 700
                    boost_reason = f"for..in: {parso_type} (parso)"
                elif any(t in detail_lower for t in ["list", "tuple", "set", "dict", "str", 
                                                       "iterator", "iterable", "sequence",
                                                       "range", "generator"]):
                    context_boost -= 600  # Strong boost for typed iterable variables
                    boost_reason = f"for..in: iterable var ({detail[:30]})"
                else:
                    # Still boost regular variables (they might be iterables)
                    context_boost -= 200
                    boost_reason = f"for..in: variable"
            
            # Demote keywords in "for...in" context (we want functions/variables, not keywords)
            elif kind and kind == CompletionItemKind.Keyword:  # Keyword
                context_boost += 300  # Push keywords down
                boost_reason = f"for..in: demote keyword"
            
            # Demote classes (we want instances/functions, not class constructors)
            elif kind and kind == CompletionItemKind.Class:  # Class
                context_boost += 100
                boost_reason = f"for..in: demote class"
        
        # 2. IMPORT statements: boost modules, demote non-modules
        line_stripped = line_before_cursor.strip()
        if line_stripped.startswith("import") or line_stripped.startswith("from"):
            # Check if it's actually an import statement (not "important" etc.)
            is_import = (line_stripped == "import" or line_stripped.startswith("import ") or 
                        line_stripped == "from" or line_stripped.startswith("from "))
            
            if is_import:
                # Check if "from MODULE import" context
                from_match = re.match(r'from\s+(\w+)\s+import', line_stripped)
                
                if from_match and kind and kind in (CompletionItemKind.Function, CompletionItemKind.Variable):  # Function/Variable from module
                    module_name = from_match.group(1)
                    
                    # Boost popular functions for specific modules
                    if module_name == 'random':
                        RANDOM_POPULAR = ['randint', 'choice', 'shuffle', 'random', 'seed', 'randrange', 'sample']
                        if label in RANDOM_POPULAR:
                            pos = RANDOM_POPULAR.index(label)
                            context_boost -= (1000 - pos * 10)
                            boost_reason = f"from random: popular #{pos+1}"
                    elif module_name == 'math':
                        MATH_POPULAR = ['sqrt', 'ceil', 'floor', 'pi', 'sin', 'cos', 'tan', 'pow', 'log']
                        if label in MATH_POPULAR:
                            pos = MATH_POPULAR.index(label)
                            context_boost -= (1000 - pos * 10)
                            boost_reason = f"from math: popular #{pos+1}"
                
                elif kind and kind == CompletionItemKind.Module:  # Module
                    # Popular modules for school (in priority order!)
                    POPULAR_MODULES_ORDER = [
                        'random', 'math', 'os', 'sys', 're',  # Top 5 for school
                        'time', 'datetime', 'collections', 'itertools', 
                        'json', 'csv', 'turtle'  # Also useful
                    ]
                    
                    if label in POPULAR_MODULES_ORDER:
                        position = POPULAR_MODULES_ORDER.index(label)
                        # Top modules get stronger boost: random=-1200, math=-1199, etc.
                        module_boost = -(1200 - position * 10)
                        context_boost += module_boost
                        boost_reason = f"import: popular module #{position+1}"
                    else:
                        context_boost -= 500  # Strong boost for all modules
                        boost_reason = "import: module"
                elif kind and kind in (CompletionItemKind.Class, CompletionItemKind.Function):  # Class or Function (but not in "from X import")
                    if not from_match:  # Only demote if NOT in "from X import"
                        context_boost += 200  # Demote classes and functions
                        boost_reason = "import: demote class/function"
                elif kind and kind == CompletionItemKind.Keyword:  # Keyword
                    context_boost += 300  # Strongly demote keywords
                    boost_reason = "import: demote keyword"
        
        # 3. BOOLEAN CONTEXTS (if, while, elif): boost variables/functions, demote keywords
        # Check if we're in a boolean condition (strip whitespace/newlines first!)
        line_clean = line_before_cursor.rstrip()
        boolean_keywords = ["if ", "while ", "elif ", "and ", "or ", "not "]
        is_boolean_context = any(line_clean.endswith(kw.rstrip()) for kw in boolean_keywords)
        
        if is_boolean_context:
            # Boolean context hierarchy:
            # 1. User variables (-2000) - ALWAYS highest, no collisions
            # 2. User functions (-1000 + alphabet)
            # 3. Built-in bool functions (-800 + popularity)
            # 4. Built-in non-bool functions (-600 + popularity)
            
            BOOLEAN_FUNCTIONS = {'len', 'isinstance', 'bool', 'any', 'all', 'hasattr'}
            
            if kind and kind == CompletionItemKind.Variable:  # Variable - highest priority in conditions
                is_user_defined = label in user_defined_vars
                if is_user_defined:
                    context_boost -= 2000  # STRONGEST boost - user vars are #1 priority!
                    boost_reason = "boolean: user-defined var"
                else:
                    context_boost -= 300  # Moderate boost for other variables
                    boost_reason = "boolean: variable"
            elif kind and kind == CompletionItemKind.Function:  # Function
                # Determine if user-defined from Parso analysis
                is_user_defined = label in user_functions
                is_boolean_func = label in BOOLEAN_FUNCTIONS
                
                if is_user_defined:
                    # ALL user functions: -1000 + alphabet (a→0, z→+25)
                    alpha_offset = ord(label[0].lower()) - ord('a') if label else 0
                    context_boost -= (1000 - alpha_offset)
                    boost_reason = f"boolean: user func (alpha)"
                elif is_boolean_func:
                    # Built-in bool function: -800 (fixed, popularity already added globally!)
                    context_boost -= 800
                    boost_reason = f"boolean: built-in bool func ({label})"
                else:
                    # Built-in non-bool function: -600 (popularity already added globally!)
                    context_boost -= 600
                    boost_reason = f"boolean: built-in func"
            elif kind and kind == CompletionItemKind.Keyword:  # Keyword - demote in boolean contexts
                # Don't show keywords like "class", "def", "import" after "if "
                context_boost += 400
                boost_reason = "boolean: demote keyword"
            elif kind and kind == CompletionItemKind.Class:  # Class constructors - also demote
                context_boost += 200
                boost_reason = "boolean: demote class"
        
        # 4. EXCEPT context: boost Exception classes VERY HIGH, demote others
        # Check if we're after 'except ' (with or without prefix)
        # Exception boost must be HIGHER than prefix to prioritize exceptions over non-exceptions
        if 'except ' in line_before_cursor[-20:] or line_clean.endswith('except'):
            if kind and kind == CompletionItemKind.Class:  # Class
                # Boost exception classes (names ending with Error or Exception)
                if label.endswith('Error') or label.endswith('Exception'):
                    context_boost -= 12000  # VERY strong boost - higher than any non-exception prefix!
                    boost_reason = "except: exception class"
                else:
                    context_boost -= 1000  # Moderate boost for other classes (might be custom exceptions)
                    boost_reason = "except: class"
            elif kind and kind == CompletionItemKind.Function:  # Function - don't show after except
                context_boost += 5000  # Strong demotion
                boost_reason = "except: demote function"
            elif kind and kind == CompletionItemKind.Variable:  # Variable
                context_boost += 3000  # Demote variables
                boost_reason = "except: demote variable"
            elif kind and kind == CompletionItemKind.Keyword:  # Keyword
                context_boost += 6000  # Strong demotion
                boost_reason = "except: demote keyword"
        
        # 5. After DOT: boost methods/properties over functions
        if line_before_cursor.rstrip().endswith("."):
            # Special: in "for ... in obj." context, prioritize iterable-returning methods
            if " in " in line_before_cursor:
                # Dict iterable methods (most common in for-loops)
                if label in ['items', 'keys', 'values']:
                    context_boost -= 800  # Very strong boost for dict iteration methods
                    boost_reason = f"for..in dot: {label} (dict iterator)"
                # String iterable-returning methods
                elif label in ['split', 'splitlines']:
                    context_boost -= 500
                    boost_reason = f"for..in dot: {label} (string iterator)"
            
            # Regular dot-access boost
            if kind and kind in (CompletionItemKind.Method, CompletionItemKind.Property):  # Method or Property
                context_boost -= 80
                boost_reason = "after dot: method/property"
            elif kind and kind == CompletionItemKind.Function:  # Function - lower priority after dot
                context_boost += 50
                boost_reason = "after dot: demote function"
        
        # 6. Start of line: boost keywords and statements
        if len(line_before_cursor.strip()) <= len(prefix):
            if kind and kind == CompletionItemKind.Keyword:  # Keyword
                if label in ["for", "if", "while", "def", "class", "return", "import"]:
                    context_boost -= 50
                    boost_reason = "line start: statement keyword"
        
        # 7. RETURN statements: boost user-defined variables and functions
        line_stripped_for_return = line_before_cursor.strip()
        is_in_return_context = (line_stripped_for_return == "return" or line_stripped_for_return.startswith("return "))
        if is_in_return_context:
            if kind and kind == CompletionItemKind.Variable:  # Variable
                if label in user_defined_vars:
                    context_boost -= 2000  # Highest priority - user vars to return
                    boost_reason = "return context: user-defined var"
                else:
                    context_boost -= 100  # Built-in vars less likely
                    boost_reason = "return context: builtin var"
            elif kind and kind == CompletionItemKind.Function:  # Function
                # Check if user-defined function from Parso analysis
                is_user_defined = label in user_functions
                is_current_function = (label == current_function)  # Don't boost recursion
                
                # Functions that return None (shouldn't be used in return)
                none_returning_funcs = {"print", "input", "help", "exit", "quit"}
                
                if is_user_defined and not is_current_function:
                    context_boost -= 1000  # High priority - calling own function
                    boost_reason = "return context: user-defined func"
                elif is_current_function:
                    # Recursion - don't boost (neutral)
                    boost_reason = "return context: same function (recursion)"
                elif label in none_returning_funcs:
                    context_boost += 800  # Strong demotion - these return None
                    boost_reason = f"return context: demote {label} (returns None)"
                else:
                    context_boost -= 500  # Built-in functions (len, sum, max, etc.)
                    boost_reason = "return context: built-in func"
            elif kind and kind == CompletionItemKind.Keyword:  # Keywords
                context_boost += 400  # Demote keywords
                boost_reason = "return context: demote keyword"
            elif kind and kind == CompletionItemKind.Class:  # Classes
                # Classes can be used in return (e.g., return str(x), return list())
                context_boost -= 300  # Moderate boost
                boost_reason = "return context: class"
        
        # 8. RANGE arguments: boost len() for range(len(data)) pattern
        is_in_range_context = "range(" in line_before_cursor
        is_in_len_context = "len(" in line_before_cursor
        
        if is_in_range_context:
            # Check if we're inside range(...) arguments
            # Examples: "range(", "range(len(", "range(0, ", "range(i, len("
            # Priority: len > int vars > math functions > everything else
            if kind and kind == CompletionItemKind.Function:  # Function
                if label == "len" and not is_in_len_context:
                    # Boost len in range, but NOT inside len itself (len(len(...)) is rare)
                    context_boost -= 2000  # Highest - len(data) is THE most common pattern
                    boost_reason = "range args: len for indexing"
                elif label == "len" and is_in_len_context:
                    context_boost += 500  # Demote len inside len (nested len is rare)
                    boost_reason = "len args: demote nested len"
                elif label == "range":
                    context_boost += 500  # Demote range inside range (nested range is rare)
                    boost_reason = "range args: demote nested range"
                elif label in user_functions:
                    context_boost -= 800  # User functions might return counts
                    boost_reason = "range args: user function"
                elif label in ("max", "min", "abs", "sum", "round"):
                    # Math functions often used: range(max(a, b)), range(abs(x))
                    context_boost -= 600
                    boost_reason = f"range args: math function ({label})"
                elif label in ("print", "input", "open"):
                    # I/O functions return None or useless in range
                    context_boost += 1000
                    boost_reason = f"range args: demote I/O ({label})"
            elif kind and kind == CompletionItemKind.Variable:  # Variable
                if label in user_defined_vars:
                    # Check variable type - lists/dicts can't be used directly in range()
                    var_type = var_types.get(label)
                    if var_type in ("list", "dict", "set", "tuple"):
                        # Demote collection types - range(list) is invalid
                        context_boost += 1000
                        boost_reason = f"range args: demote {var_type} (invalid)"
                    else:
                        # int/str/etc variables likely hold counts (n, count, size, x, y)
                        context_boost -= 1500
                        boost_reason = f"range args: {var_type or 'int'} var"
            elif kind and kind == CompletionItemKind.Class:  # Class (range is a Class in LSP!)
                if label == "range":
                    context_boost += 500  # Demote range inside range
                    boost_reason = "range args: demote nested range (class)"
                elif label == "int":
                    # int() is useful: range(int(x))
                    context_boost -= 400
                    boost_reason = "range args: int class"
        
        # Also handle len() context outside of range
        elif is_in_len_context:
            if kind and kind == CompletionItemKind.Function:  # Function
                if label == "len":
                    context_boost += 500  # Demote len inside len
                    boost_reason = "len args: demote nested len"
            elif kind and kind in (CompletionItemKind.Variable, CompletionItemKind.Constant):  # Variable or Constant
                if label in user_defined_vars:
                    # Check variable type - int/float/bool can't use len()
                    var_type = var_types.get(label)
                    if var_type in ("int", "float", "bool", "NoneType"):
                        # Demote non-sequences - len(5) is invalid
                        context_boost += 1000
                        boost_reason = f"len args: demote {var_type} (invalid)"
                    else:
                        # Sequences (list, str, dict, etc.) or unknown - boost
                        context_boost -= 800
                        boost_reason = f"len args: {var_type or 'iterable'} var"
        
        # 9. F-STRING interpolation: inside {}, boost variables, demote I/O functions
        is_in_fstring = False
        # Detect f"...{  or f'...{
        if re.search(r'f["\'].*\{(?:[^}]*)?$', line_before_cursor):
            is_in_fstring = True
            
            if kind and kind == CompletionItemKind.Variable:  # Variable - HIGHEST priority in f-strings
                if label in user_defined_vars:
                    context_boost -= 2000  # Very strong boost - this is THE use case
                    boost_reason = "f-string: user-defined var (main use case)"
                else:
                    context_boost -= 500  # Still boost other builtins vars (e, NotImplemented, Ellipsis)
                    boost_reason = "f-string: builtin var"
            
            # Formatting functions - useful in f-strings
            elif label in ["str", "int", "float", "round", "abs", "len"]:
                context_boost -= 200
                boost_reason = f"f-string: formatting ({label})"
            
            # I/O functions - USELESS in f-strings!
            elif label in ["print", "input", "open", "help", "eval", "exec"]:
                context_boost += 1500  # Strong demotion - makes no sense here
                boost_reason = f"f-string: demote I/O function ({label})"
            
            # Other builtins - mild demotion (might be useful but less common)
            elif kind and kind in (CompletionItemKind.Function, CompletionItemKind.Class):  # Function or Class
                context_boost += 300
                boost_reason = "f-string: demote other builtins"
        
        # 10. Inside popular function calls: demote built-in functions, boost variables
        # Check for print(, input(, int(, str(, etc. (but NOT len/range - they're handled above!)
        is_in_function_call = False
        if not is_in_fstring:  # Skip if already in f-string
            for func_name in ["print(", "input(", "int(", "str(", "float(", "list(", "dict(", "set(", "tuple(", "max(", "min(", "sum(", "abs(", "round("]:
                if line_before_cursor.rstrip().endswith(func_name):
                    is_in_function_call = True
                    break
        
        # Skip if already in range() or len() - they have their own special handling above
        if is_in_function_call and not is_in_range_context and not is_in_len_context:
            if kind and kind in (CompletionItemKind.Function, CompletionItemKind.Class):  # Function or Class - demote built-ins
                if label not in user_functions:  # Built-in function/class
                    # Extra strong demotion for I/O functions (print in print, input in print is weird)
                    if label == "print":
                        context_boost += 2000  # Push to bottom
                        boost_reason = "function call args: demote print in print"
                    elif label == "input" and "print(" in line_before_cursor:
                        context_boost += 800  # Strong demotion - input() in print() is unusual
                        boost_reason = "function call args: demote input in print"
                    else:
                        context_boost += 400  # Demote - inside function call, we want variables/literals
                        boost_reason = "function call args: demote built-in function/class"
            elif kind and kind == CompletionItemKind.Variable:  # Variable - boost
                if label in user_defined_vars:
                    context_boost -= 800
                    boost_reason = "function call args: boost user var"
            elif kind and kind == CompletionItemKind.Keyword:  # Keyword - very low priority in function args
                context_boost += 1500  # Strong demotion - keywords rarely needed as arguments
                boost_reason = "function call args: demote keyword"
        # 11. Inside expressions (after operators): prefer variables/functions over keywords
        # BUT: skip if in range() or return context (they have their own specific boosts)
        elif (any(op in line_before_cursor[-10:] for op in ["= ", "+ ", "- ", "* ", "/ ", "> ", "< ", "== ", "!= ", ">= ", "<= ", "(", "[", ","]) 
            and not is_in_range_context 
            and not is_in_return_context):
            if kind and kind == CompletionItemKind.Keyword:  # Keyword - lower priority in expressions
                context_boost += 30
                boost_reason = "in expression: demote keyword"
            elif kind and kind in (CompletionItemKind.Variable, CompletionItemKind.Constant):  # Variable or Constant
                if label in user_defined_vars:
                    context_boost -= 900
                    boost_reason = "in expression: user-defined var/constant"
                else:
                    context_boost -= 30
                    boost_reason = "in expression: builtin var"
            elif kind and kind == CompletionItemKind.Function:  # Function
                # Demote functions that return None (print) in comparisons/assignments
                # BUT: input is useful after = (gets user value), only demote in comparisons
                has_comparison = any(op in line_before_cursor[-10:] for op in ["> ", "< ", "== ", "!= ", ">= ", "<= "])
                has_assignment = "= " in line_before_cursor[-10:]
                # Check if inside function call (has opening parenthesis after =)
                in_function_call = has_assignment and "(" in line_before_cursor.split("= ")[-1]
                
                if label == "print" and (has_comparison or has_assignment):
                    context_boost += 800  # Strong demotion - returns None!
                    boost_reason = f"in expression: demote {label} (returns None)"
                elif label == "input" and (has_comparison or in_function_call):
                    context_boost += 800  # Demote in comparisons and inside function calls
                    boost_reason = f"in expression: demote {label} (not useful here)"
                else:
                    context_boost -= 30
                    boost_reason = "in expression: function"
        
        # Combined priority: base prefix matching + context boost
        final_priority = prefix_priority + context_boost
        
        # Check if this is a user-defined constant (UPPER_CASE variable)
        # Constants should appear AFTER local variables
        is_constant = 0
        if kind and kind in (CompletionItemKind.Variable, CompletionItemKind.Constant) and label in user_defined_vars:
            # Variable/Constant is user-defined - check if it's a constant (UPPER_CASE)
            if label.isupper() and len(label) > 1:  # MIN_GUESS_RANGE, MAX_VALUE, etc.
                is_constant = 1  # Constants after locals
            # else: is_constant = 0  # Local variables first
        
        # Log items with significant context boost
        if context_boost != 0 and abs(context_boost) >= 50:
            kind_name = lsp_types.CompletionItemKind(kind).name if kind else "Unknown"
            logger.info(f"   {'🔼' if context_boost < 0 else '🔽'} {label:20s} | boost={context_boost:+5d} | {boost_reason or 'no reason'} | kind={kind_name}")
        
        return (final_priority, is_constant, sort_text.lower(), label.lower(), label)
    
    return sort_key


class CompletionsDetailsBox(DocuBox):
    def __init__(self, completions_box: "CompletionsBox"):
        super().__init__()
        self._completions_box = completions_box

    def _get_related_box(self) -> Optional["EditorInfoBox"]:
        return self._completions_box


class CompletionsBox(EditorInfoBox):
    def __init__(self, completer: "Completer"):
        super().__init__()
        self._completer = completer
        self._listbox = tk.Listbox(
            self,
            font="EditorFont",
            activestyle="dotbox",
            exportselection=False,
            highlightthickness=0,
            borderwidth=0,
            height=5,
        )
        self._listbox.grid()
        self._tweaking_listbox_selection = False
        self._details_box: Optional[CompletionsDetailsBox] = None
        self._completions: List[lsp_types.CompletionItem] = []

        self._listbox.bind("<<ListboxSelect>>", self._on_select_item_via_event, True)

        # for cases when Listbox gets focus
        self.bind("<Return>", self._insert_current_selection)
        self.bind("<Tab>", self._insert_current_selection_replace_suffix)
        self.bind("<Double-Button-1>", self._insert_current_selection)

        self._update_theme()

    def present_completions(
        self, text: SyntaxText, completions: List[lsp_types.CompletionItem], skip_sorting: bool = False
    ) -> None:
        # Next events need to know this
        assert completions
        
        self._target_text_widget = text
        self._check_bind_for_keypress(text)

        prefix_start_index = self._find_completion_insertion_index()
        assert self._target_text_widget.compare(prefix_start_index, "<=", "insert")
        prefix = self._target_text_widget.get(prefix_start_index, "insert")
        
        # Get context for context-aware ranking
        try:
            line_before_cursor = text.get("insert linestart", "insert")
            line_after_cursor = text.get("insert", "insert lineend")
            # Get code BEFORE cursor for Parso (only variables above matter!)
            source_code = text.get("1.0", "insert")
            logger.info(f"📥 present_completions: prefix={repr(prefix)}, line_before={repr(line_before_cursor)}")
            logger.info(f"   ↳ source_code length: {len(source_code)} chars")
        except:
            line_before_cursor = ""
            line_after_cursor = ""
            source_code = ""

        # Use shared context-aware sorting logic
        sort_key = create_context_aware_sort_key(prefix, line_before_cursor, line_after_cursor, source_code)
        
        # Add missing user-defined variables (constants) that LSP doesn't return
        if source_code and len(source_code) < 5000:
            from thonny.plugins.autocomplete import _infer_variable_types_with_parso
            cursor_line = None
            if source_code:
                lines_before = source_code[:source_code.rfind(line_before_cursor) + len(line_before_cursor)].split('\n')
                cursor_line = len(lines_before)
            var_types, user_defined_vars, _, _, _ = _infer_variable_types_with_parso(source_code, cursor_line)
            
            if user_defined_vars:
                user_vars_in_completions = []
                user_vars_sort_texts = {}
                for comp in completions:
                    if comp.kind and comp.kind == CompletionItemKind.Variable and comp.label in user_defined_vars:
                        user_vars_in_completions.append(comp.label)
                        user_vars_sort_texts[comp.label] = comp.sortText or comp.label
                
                if user_vars_in_completions:
                    logger.info(f"✅ User vars in LSP response: {sorted(user_vars_in_completions)}")
                    logger.info(f"   sortText samples: {dict(list(user_vars_sort_texts.items())[:3])}")
                missing_vars = user_defined_vars - set(user_vars_in_completions)
                if missing_vars:
                    logger.info(f"❌ User vars NOT in LSP response: {sorted(missing_vars)}")
                    logger.info(f"➕ Adding {len(missing_vars)} missing user vars as synthetic completions")
                    
                    # Create synthetic CompletionItems for missing vars
                    for var_name in sorted(missing_vars):
                        # Create detail from inferred type
                        detail = var_types.get(var_name)
                        if detail:
                            detail = f": {detail}"
                        else:
                            detail = None
                        
                        synthetic_item = CompletionItem(
                            label=var_name,
                            kind=lsp_types.CompletionItemKind(6),  # Variable
                            sortText=f"09.9999.{var_name}",  # Same as LSP local vars, will be sorted by is_constant
                            detail=detail,
                            insertText=None,
                            textEdit=None,
                            additionalTextEdits=None,
                            insertTextFormat=None,
                            insertTextMode=None,
                            documentation=None,
                        )
                        completions.append(synthetic_item)
                    
                    logger.info(f"✅ Added synthetic completions: {sorted(missing_vars)}")

        if skip_sorting:
            # AI already sorted - don't re-sort!
            logger.info(f"🎯 Using AI-sorted order (skip_sorting=True)")
            sorted_completions = completions
        else:
            # Apply our sorting algorithm
            logger.info(f"🔄 Sorting {len(completions)} completions with context-aware algorithm...")
            sorted_completions = sorted(completions, key=sort_key)
            
            # Log top results for debugging
            if sorted_completions:
                logger.info(f"\n📊 TOP 10 RESULTS AFTER SORTING:")
                for i, comp in enumerate(sorted_completions[:10], 1):
                    kind_name = lsp_types.CompletionItemKind(comp.kind).name if comp.kind else "Unknown"
                    detail_str = f" | {comp.detail[:30]}..." if comp.detail and len(comp.detail) > 30 else f" | {comp.detail}" if comp.detail else ""
                    logger.info(f"   {i:2d}. {comp.label:20s} | {kind_name:12s}{detail_str}")
                logger.info(f"")
        
        if not prefix.startswith("__"):
            before_filter = len(sorted_completions)
            sorted_completions = filter_garbage_completions(sorted_completions)
            after_filter = len(sorted_completions)
            if before_filter != after_filter:
                logger.info(f"🗑️  Filtered garbage: {before_filter} → {after_filter} completions")
        self._completions = sorted_completions

        # broadcast logging info
        row, column = editor_helpers.get_cursor_position(text)
        if isinstance(text, ShellText):
            row -= text.get_current_line_ls_offset()
            column -= text.get_current_column_ls_offset()

        get_workbench().event_generate(
            "AutocompleteProposal",
            text_widget=text,
            row=row,
            column=column,
            proposal_count=len(sorted_completions),
        )

        # present
        if len(sorted_completions) == 0:
            self.hide()
            return

        self._listbox.delete(0, self._listbox.size())
        self._listbox.insert(0, *[c.label for c in sorted_completions])
        self._listbox.activate(0)
        self._listbox.selection_set(0)

        max_visible_items = 10
        self._listbox["height"] = min(len(sorted_completions), max_visible_items)

        _, _, _, list_row_height = self._listbox.bbox(0)
        # the measurement is not accurate, but good enough for deciding whether
        # the box should be above or below the current line.
        # Actual placement will be managed otherwise
        approx_box_height = round(list_row_height * (self._listbox["height"] + 0.5))

        name_start_index = self._find_completion_insertion_index()

        self._show_on_target_text(name_start_index, approx_box_height, "below")

        self._check_request_details()

    def _get_related_box(self) -> Optional["EditorInfoBox"]:
        return self._details_box

    def tweak_first_appearance(self):
        super().tweak_first_appearance()
        if running_on_mac_os():
            self.update()
            self._listbox.grid_remove()
            self._listbox.grid()

    def _get_current_completion_index(self):
        selected = self._listbox.curselection()
        if len(selected) == 0:
            return 0
        else:
            return selected[0]

    def _move_selection(self, delta):
        old_flag = self._tweaking_listbox_selection
        self._tweaking_listbox_selection = True
        try:
            index = self._get_current_completion_index()
            index += delta
            index = max(0, min(self._listbox.size() - 1, index))

            self._listbox.selection_clear(0, self._listbox.size() - 1)
            self._listbox.selection_set(index)
            self._listbox.see(index)
            self._listbox.activate(index)
            self._check_request_details()
        finally:
            self._tweaking_listbox_selection = old_flag

    def _update_theme(self, event=None):
        gutter_opts = get_syntax_options_for_tag("GUTTER")
        text_opts = get_syntax_options_for_tag("TEXT")
        self._listbox["background"] = gutter_opts["background"]
        self._listbox["foreground"] = text_opts["foreground"]

    def _on_select_item_via_event(self, event=None) -> None:
        if self._tweaking_listbox_selection:
            return

        self._check_request_details()

    def _check_request_details(self) -> None:
        if not self.winfo_ismapped():
            # can happen, see https://github.com/thonny/thonny/issues/2162
            return

        if (
            self._details_box
            and self._details_box.is_visible()
            or get_workbench().get_option("edit.automatic_completion_details")
        ):
            self.request_details()

    def _on_text_keypress(self, event=None):
        if not self.is_visible():
            return None

        if event.keysym in ["Up", "KP_Up"]:
            self._move_selection(-1)
            return "break"
        elif event.keysym in ["Down", "KP_Down"]:
            self._move_selection(1)
            return "break"
        elif event.keysym in ["Return", "KP_Enter"]:
            assert self._listbox.size() > 0
            self._insert_current_selection()
            return "break"
        elif event.keysym == "Tab":
            assert self._listbox.size() > 0
            self._insert_current_selection_replace_suffix()
            return "break"
        elif event.keysym in ["BackSpace", "Left", "Right", "KP_Left", "KP_Right"]:
            self.after_idle(
                lambda: self._completer.request_completions_for_text(self._target_text_widget)
            )
        elif (
            event.char
            and not _is_python_name_char(event.char)
            and event.char != "."
            and not control_is_pressed(event)
        ):
            self.hide(event)

        return None

    def _insert_current_selection(self, event=None):
        self._insert_completion(self._get_current_completion(), replace_suffix=False)

    def _insert_current_selection_replace_suffix(self, event=None):
        self._insert_completion(self._get_current_completion(), replace_suffix=True)

    def _get_current_completion(self) -> Optional[CompletionItem]:
        sel = self._listbox.curselection()
        if len(sel) != 1:
            return None

        return self._completions[sel[0]]

    def _get_insert_text(self, completion: CompletionItem) -> str:
        if completion.textEdit is not None:
            raise RuntimeError("TODO: handle textEdit")

        if completion.insertText is not None:
            if completion.insertTextFormat == lsp_types.InsertTextFormat.Snippet:
                raise RuntimeError("TODO support snippets")
            if completion.insertTextMode == lsp_types.InsertTextMode.AdjustIndentation:
                raise RuntimeError("TODO support adjust indentation")
            return completion.insertText
        else:
            assert completion.label is not None
            return completion.label

    def _insert_completion(self, completion: CompletionItem, replace_suffix: bool) -> None:
        insert_text = self._get_insert_text(completion)
        prefix_start_index = self._find_completion_insertion_index()
        typed_prefix = self._target_text_widget.get(prefix_start_index, "insert")

        get_workbench().event_generate(
            "AutocompleteInsertion",
            text_widget=self._target_text_widget,
            typed_prefix=typed_prefix,
            replace_suffix=replace_suffix,
            completed_name=insert_text,
        )

        # Before insertion need to delete prefix, because it may not be name's prefix
        # (eg. with different case or even more different with fuzzy completions)
        self._target_text_widget.direct_delete(prefix_start_index, "insert")
        self._target_text_widget.insert("insert", insert_text)

        if replace_suffix:
            did_replace_suffix = False
            while _is_python_name_char(self._target_text_widget.get("insert")):
                self._target_text_widget.direct_delete("insert")
                did_replace_suffix = True

            last_char_inserted = self._target_text_widget.get("insert -1 chars")
            if (
                did_replace_suffix
                and last_char_inserted in ["(", "="]
                and self._target_text_widget.get("insert") == last_char_inserted
            ):
                self._target_text_widget.direct_delete("insert")

        # Auto-add parentheses for functions, methods, and classes
        self._auto_add_parentheses(completion, insert_text)

        get_workbench().event_generate(
            "AutocompletionInserted",
            text_widget=self._target_text_widget,
            typed_prefix=typed_prefix,
            replace_suffix=replace_suffix,
            completed_name=insert_text,
        )

        self.hide()
        
        # Ensure focus returns to the text widget after mouse selection
        self._target_text_widget.focus_set()

    def _auto_add_parentheses(self, completion: CompletionItem, insert_text: str) -> None:
        """Automatically add parentheses for functions, methods, and classes."""
        # Check if this is a callable (function, method, or class)
        if completion.kind is None:
            return
        
        is_callable = completion.kind in (
            CompletionItemKind.Method,
            CompletionItemKind.Function,
            CompletionItemKind.Class
        )
        
        if not is_callable:
            return
        
        # Check if there's already a '(' after cursor - don't duplicate
        char_after = self._target_text_widget.get("insert")
        if char_after == "(":
            return
        
        # Special handling for input() - add prompt template
        if insert_text == "input":
            code_language = get_workbench().get_option("edit.code_language")
            
            # Localized prompt templates
            prompts = {
                "Ukrainian": "Введіть : ",
                "English": "Enter : ",
                "Russian": "Введите : "
            }
            prompt = prompts.get(code_language, "Enter : ")
            
            self._target_text_widget.insert("insert", f'("{prompt}")')
            # Move cursor before ": " - perfect spot to type what to enter
            self._target_text_widget.mark_set("insert", f"insert-{len(': ')  + 2}c")
            return
        
        # Functions that commonly take a string as first parameter
        # For these, add ("") with cursor between quotes
        string_first_functions = {
            "print", "open", "eval", "exec", 
            "compile", "__import__", "help"
        }
        
        if insert_text in string_first_functions:
            self._target_text_widget.insert("insert", '("")')
            # Move cursor between quotes: ("| ")
            self._target_text_widget.mark_set("insert", "insert-2c")
        else:
            # For all other callables, add () with cursor between parens
            self._target_text_widget.insert("insert", "()")
            # Move cursor between parens: (|)
            self._target_text_widget.mark_set("insert", "insert-1c")

    def _find_completion_insertion_index(self):
        line, col = map(int, self._target_text_widget.index("insert").split("."))
        while col > 0:
            char_at_left: str = self._target_text_widget.get(f"{line}.{col-1}")
            if not char_at_left.isidentifier():
                break
            col -= 1

        return f"{line}.{col}"

    def request_details(self) -> None:
        completion = self._get_current_completion()

        if not self._details_box:
            self._details_box = CompletionsDetailsBox(self)

        self._details_box.set_content(completion)

        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is not None:
            # TODO: cancel previous request
            ls_proxy.unbind_request_handler(self._handle_details_response)
            ls_proxy.request_resolve_completion_item(completion, self._handle_details_response)

        self._show_next_to_completions()

    def _show_next_to_completions(self):
        self._details_box._show_on_screen(
            self.winfo_rootx() + self.winfo_width() + ems_to_pixels(0.5), self.winfo_rooty()
        )

    def _handle_details_response(self, response: LspResponse[CompletionItem]) -> None:
        if not self.is_visible():
            return

        basic_completion = self._get_current_completion()
        detailed_completion = response.get_result_or_raise()
        logger.debug("Got completion details: %r", detailed_completion)
        if detailed_completion.data != basic_completion.data:
            return

        self._update_completion(details=detailed_completion)

        if not self._details_box:
            self._details_box = CompletionsDetailsBox(self)

        self._details_box.set_content(detailed_completion)

        self._show_next_to_completions()

    def _update_completion(self, details: CompletionItem) -> None:
        # logger.debug("Handling completion details %r", details)
        for i, comp in enumerate(self._completions):
            assert isinstance(comp, CompletionItem)
            if comp.data == details.data:
                comp.label = details.label
                comp.detail = details.detail
                comp.labelDetails = details.labelDetails
                comp.documentation = details.documentation

                sel = self._listbox.curselection()
                old_flag = self._tweaking_listbox_selection
                self._tweaking_listbox_selection = True
                try:
                    self._listbox.delete(i)
                    self._listbox.insert(i, comp.label)
                    if len(sel) == 1:
                        self._listbox.selection_set(sel[0])
                        self._listbox.activate(sel[0])
                    break
                finally:
                    self._tweaking_listbox_selection = old_flag
    
    def update_order_from_ai(self, reranked_labels: List[str], original_completions: List[CompletionItem]) -> None:
        """Update completion order based on AI reranking (called async from background thread result)"""
        try:
            # Create mapping from label to completion item
            label_to_item = {item.label: item for item in original_completions}
            
            # Build reordered list
            reordered = []
            seen = set()
            
            # Add reranked items first (in AI's preferred order)
            for label in reranked_labels:
                if label in label_to_item and label not in seen:
                    reordered.append(label_to_item[label])
                    seen.add(label)
            
            # Add remaining items that AI didn't rank
            for item in self._completions:
                if item.label not in seen:
                    reordered.append(item)
            
            logger.info(f"📤 Final order shown to user ({len(reordered)} items):")
            for i, comp in enumerate(reordered[:20]):  # Show first 20
                kind_name = lsp_types.CompletionItemKind(comp.kind).name if comp.kind else "Unknown"
                logger.info(f"  [{i:2d}] {comp.label:30s} | {kind_name:12s}")
            if len(reordered) > 20:
                logger.info(f"  ... and {len(reordered) - 20} more")
            logger.info(f"━" * 80)
            
            # Update internal list
            self._completions = reordered
            
            # Update listbox display
            old_flag = self._tweaking_listbox_selection
            self._tweaking_listbox_selection = True
            try:
                # Remember current selection
                sel = self._listbox.curselection()
                selected_label = None
                if len(sel) == 1:
                    selected_label = self._listbox.get(sel[0])
                
                # Rebuild listbox
                self._listbox.delete(0, self._listbox.size())
                self._listbox.insert(0, *[c.label for c in reordered])
                
                # Restore selection if possible
                if selected_label:
                    for i, comp in enumerate(reordered):
                        if comp.label == selected_label:
                            self._listbox.selection_set(i)
                            self._listbox.activate(i)
                            break
                else:
                    # Default to first item
                    self._listbox.selection_set(0)
                    self._listbox.activate(0)
                    
            finally:
                self._tweaking_listbox_selection = old_flag
                
        except Exception as e:
            logger.exception("Error updating completion order from AI")


class Completer:
    """
    Manages completion requests and responses.
    Delegates user interactions with completions to CompletionsBox.
    """

    def __init__(self):
        self._last_request_text: Optional[SyntaxText] = None
        self._latest_request_id: int = 0  # LSP request_id of the latest request
        self._request_snapshots: dict[int, str] = {}  # Map request_id -> line_before snapshot
        logger.debug("Creating Completer")
        self._completions_box: Optional[CompletionsBox] = None

        get_workbench().bind_class("EditorCodeViewText", "<Key>", self._on_keypress, True)
        get_workbench().bind_class("ShellText", "<Key>", self._on_keypress, True)
        
        # Hide completion box when editor loses focus (e.g., user switches to another window)
        get_workbench().bind_class("EditorCodeViewText", "<FocusOut>", self._on_focus_out, True)
        get_workbench().bind_class("ShellText", "<FocusOut>", self._on_focus_out, True)
        
        get_workbench().bind(
            "editor_autocomplete_response", self._handle_completions_response, True
        )
        get_workbench().bind("shell_autocomplete_response", self._handle_completions_response, True)

    def request_completions(self, event=None) -> None:
        if self._box_is_visible():
            self._completions_box.request_details()
            return

        text = editor_helpers.get_active_text_widget()
        if text:
            self.request_completions_for_text(text)
        else:
            get_workbench().bell()

    def _should_open_box_automatically(self, event):
        assert isinstance(event.widget, tk.Text)
        if not get_workbench().get_option("edit.automatic_completions"):
            return False

        # Don't autocomplete inside comments
        line_prefix = event.widget.get("insert linestart", "insert")
        if "#" in line_prefix:
            # not very precise (eg. when inside a string), but good enough
            return False

        return True

    def _box_is_visible(self):
        if not self._completions_box:
            return False

        return self._completions_box.is_visible()

    def _close_box(self):
        if self._completions_box:
            self._completions_box.hide()
    
    def _on_focus_out(self, event: tk.Event) -> None:
        """Hide completion box when editor loses focus (e.g., user switches to another window)"""
        logger.info(f"🔴 _on_focus_out: hiding completion box")
        self._close_box()

    def _on_keypress(self, event: tk.Event) -> None:
        logger.info(f"⌨️  _on_keypress: char={repr(event.char)}, keysym={event.keysym}")
        self.cancel_active_request()
        runner = get_runner()
        if not runner or runner.is_running():
            logger.info(f"   ↳ Skipped: runner not available or running")
            return

        if (
            control_is_pressed(event)
            or command_is_pressed(event)
            or alt_is_pressed_without_char(event)
        ):
            logger.info(f"   ↳ Skipped: modifier key pressed")
            return

        widget = event.widget
        if not widget or not isinstance(widget, SyntaxText):
            logger.info(f"   ↳ Skipped: not SyntaxText widget")
            return

        if not widget.is_python_text():
            logger.info(f"   ↳ Skipped: not Python text")
            return

        if widget.is_read_only():
            logger.info(f"   ↳ Skipped: read-only widget")
            return

        should_auto_open = self._should_open_box_automatically(event)
        logger.info(f"   ↳ _should_open_box_automatically={should_auto_open}, box_visible={self._box_is_visible()}")
        
        if not self._box_is_visible() and not should_auto_open:
            logger.info(f"   ↳ Not opening box: auto_open=False, visible=False")
            return

        if event.keysym == "Escape":
            # Closing is handled by the box itself
            logger.info(f"   ↳ Escape pressed")
            return

        if not event.char:
            # movement keypresses are handled by the box
            logger.info(f"   ↳ No char (movement key)")
            return

        is_python_char = _is_python_name_char(event.char)
        is_dot = self._is_start_of_an_attribute(event)
        logger.info(f"   ↳ char={repr(event.char)}, is_python_char={is_python_char}, is_dot={is_dot}, box_visible={self._box_is_visible()}")

        if (
            not self._box_is_visible()
            and not is_python_char
            and not is_dot
        ):
            # Special case: space after certain keywords should trigger completions
            if event.char == " ":
                line_before = widget.get("insert linestart", "insert")
                line_stripped = line_before.strip()  # Remove leading AND trailing whitespace
                logger.info(f"   ↳ SPACE pressed, line_before={repr(line_before)}, line_stripped={repr(line_stripped)}")
                
                # Check if we just typed space after keywords that need completions
                # - "for ... in" -> suggest iterables
                # - "if", "while", "elif" -> suggest boolean expressions (ONLY first space!)
                # - "except" -> suggest Exception classes
                # - "with" -> suggest context managers
                # - "import" -> suggest modules
                # - "from MODULE import" -> suggest module members
                # - "return" -> suggest variables/expressions
                
                # For boolean keywords (if/while/elif), only open after FIRST space
                # to avoid reopening during "while x < " or "if condition and "
                boolean_keywords_first_space = False
                for kw in ["if", "while", "elif"]:
                    # Check: "if " (just keyword + space, no more text yet)
                    if line_stripped == kw:
                        boolean_keywords_first_space = True
                        break
                
                # Check each condition separately for detailed logging
                ends_with_in = line_stripped.endswith(" in")
                is_boolean_first_space = boolean_keywords_first_space
                is_except = line_stripped == "except" or line_stripped.startswith("except ")
                is_with = line_stripped == "with" or line_stripped.startswith("with ")
                is_import = (line_stripped == "import" or line_stripped.startswith("import ") or 
                            line_stripped.endswith(" import"))
                is_return = line_stripped == "return" or line_stripped.startswith("return ")
                
                should_open = (ends_with_in or is_boolean_first_space or is_except or 
                              is_with or is_import or is_return)
                
                logger.info(f"   ↳ Space checks: for_in={ends_with_in}, bool={is_boolean_first_space}, "
                           f"except={is_except}, with={is_with}, import={is_import}, return={is_return}")
                logger.info(f"   ↳ should_open={should_open}")
            
                if should_open:
                    logger.info(f"   ↳ ✅ Opening box: space after keyword that needs completions")
                    # Continue to request completions
                else:
                    logger.info(f"   ↳ ❌ Not opening box: space (not after special keyword)")
                    return
            
            # Special case: '(' after certain functions should trigger completions
            elif event.char == "(":
                line_before = widget.get("insert linestart", "insert")
                line_stripped = line_before.strip()
                
                # Check if we just typed '(' after common functions that need arguments
                # Examples: "range(", "len(", "print(", "int(", "str("
                important_functions = ["range", "len", "print", "int", "str", "float", 
                                     "max", "min", "sum", "abs", "round", "sorted",
                                     "list", "dict", "set", "tuple", "open"]
                
                should_open = any(line_stripped.endswith(f"{func}(") for func in important_functions)
                
                if should_open:
                    logger.info(f"   ↳ Opening box: '(' after important function")
                    # Continue to request completions
                else:
                    logger.info(f"   ↳ Not opening box: '(' (not after important function)")
                    return
            
            # Special case: ',' inside function calls should trigger completions
            elif event.char == ",":
                line_before = widget.get("insert linestart", "insert")
                
                # Check if we're inside a function call (has unclosed '(')
                # Examples: "range(10,", "print(x,", "max(a, b,"
                open_parens = line_before.count("(")
                close_parens = line_before.count(")")
                
                if open_parens > close_parens:
                    logger.info(f"   ↳ Opening box: ',' inside function call")
                    # Continue to request completions
                else:
                    logger.info(f"   ↳ Not opening box: ',' (not inside function call)")
                    return
            
            # Special case: '{' in f-strings should trigger completions
            elif event.char == "{":
                line_before = widget.get("insert linestart", "insert")
                
                # Check if we're inside an f-string
                # Examples: f"text {", f'value: {", print(f"{
                if re.search(r'f["\'].*\{$', line_before):
                    logger.info(f"   ↳ Opening box: '{{' in f-string")
                    # Continue to request completions
                else:
                    logger.info(f"   ↳ Not opening box: '{{' (not in f-string)")
                    return
            
            else:
                # non-word chars are allowed only while the box is already open
                logger.info(f"   ↳ Not opening box: non-word char and box not visible")
                return

        # Log current line BEFORE after_idle
        try:
            line_before = widget.get("insert linestart", "insert")
            logger.info(f"   ↳ Will request completions. Current line before cursor: {repr(line_before)}")
        except:
            pass
        
        widget.after_idle(lambda: self.request_completions_for_text(widget))

    def _is_start_of_an_attribute(self, event: tk.Event) -> bool:
        if event.char != ".":
            return False

        text = cast(tk.Text, event.widget)
        preceding = text.get("insert -2 chars")
        if preceding.isnumeric():
            return False

        return True

    def cancel_active_request(self) -> None:
        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is not None:
            # TODO: actually cancel
            ls_proxy.unbind_request_handler(self._handle_completions_response)

    def request_completions_for_text(self, text: SyntaxText) -> None:
        # Log what we're requesting
        try:
            line_before = text.get("insert linestart", "insert")
            logger.info(f"📤 request_completions_for_text: line_before={repr(line_before)}")
            
            # Don't show completions on empty line (annoying!)
            if not line_before.strip():
                logger.info(f"   ↳ ❌ Empty line - not requesting completions")
                return
        except:
            pass
        
        ls_proxy = get_workbench().get_main_language_server_proxy()
        if ls_proxy is None:
            return

        ls_proxy.unbind_request_handler(self._handle_completions_response)
        # TODO: cancel last unhandled request

        if isinstance(text, ShellText):
            text.send_changes_to_language_server()
            uri = text.get_ls_uri()
            position = editor_helpers.get_cursor_ls_position(
                text, text.get_current_line_ls_offset(), text.get_current_column_ls_offset()
            )
        else:
            editor = get_workbench().get_editor_notebook().get_current_editor()
            if editor.get_text_widget() is not text:
                logger.warning("Unexpected completions request in %r", text)
                return

            editor.send_changes_to_primed_servers()
            uri = editor.get_uri()
            position = editor_helpers.get_cursor_ls_position(text)

        if uri is None:
            # TODO:
            return

        logger.info(f"   ↳ Sending LSP request at position line={position.line}, char={position.character}")
        self._last_request_text = text
        
        # Capture line_before snapshot BEFORE sending request
        request_line_before = text.get("insert linestart", "insert")
        
        # Send request to LSP and get its request_id
        lsp_request_id = ls_proxy.request_completion(
            CompletionParams(textDocument=TextDocumentIdentifier(uri=uri), position=position),
            self._handle_completions_response,
        )
        
        # Store snapshot for this request
        self._request_snapshots[lsp_request_id] = request_line_before
        # Remember the latest request ID
        self._latest_request_id = lsp_request_id
        logger.info(f"   ↳ LSP request #{lsp_request_id}, line_before: {repr(request_line_before)}")

    def _handle_completions_response(
        self,
        response: LspResponse[
            Union[List[lsp_types.CompletionItem], lsp_types.CompletionList, None]
        ],
    ) -> None:
        lsp_request_id = response._request_id
        logger.info(f"📥 Received LSP response #{lsp_request_id}")
        
        error = response.get_error()
        if error is not None:
            self._close_box()
            messagebox.showerror("Autocomplete error", error.message, master=get_workbench())
            return

        if not self._last_request_text:
            logger.warning("Completions response without _last_request_text")
            return
        
        # Check if response is stale (not the latest request)
        if lsp_request_id != self._latest_request_id:
            logger.info(f"⏭️  Ignoring stale LSP response #{lsp_request_id} (latest is #{self._latest_request_id})")
            # Clean up old snapshot
            self._request_snapshots.pop(lsp_request_id, None)
            return
        
        # Check if line_before changed since request (e.g., user pressed Backspace or Enter)
        request_line_before = self._request_snapshots.get(lsp_request_id, "")
        current_line_before = self._last_request_text.get("insert linestart", "insert")
        
        if current_line_before != request_line_before:
            logger.info(f"⏭️  Ignoring LSP response #{lsp_request_id}: line changed from {repr(request_line_before)} to {repr(current_line_before)}")
            # Clean up snapshot
            self._request_snapshots.pop(lsp_request_id, None)
            return
        
        # Clean up snapshot (no longer needed)
        self._request_snapshots.pop(lsp_request_id, None)
        logger.info(f"✅ LSP response #{lsp_request_id} is current")
        
        # Check if we should show completions for this context
        # Don't show for "for " - user is typing variable name
        # Don't show for "print(" - user is typing first argument, we don't want to clutter
        # BUT show after comma: print("asd", <-- here we want completions!
        line_before_stripped = self._last_request_text.get("insert linestart", "insert").strip()
        if line_before_stripped == "for":
            logger.info(f"🚫 Ignoring completions: cursor after 'for ' (user typing variable name)")
            self._close_box()
            return
        # Only ignore if EXACTLY "print(" - not after comma or other chars
        if line_before_stripped.endswith("print(") and line_before_stripped == "print(":
            logger.info(f"🚫 Ignoring completions: cursor after 'print(' (too cluttered)")
            self._close_box()
            return

        result = response.get_result_or_raise()
        if result is None:
            logger.info("None completions response")
            return

        completions: List[lsp_types.CompletionItem]
        if isinstance(result, list):
            completions = result
            is_incomplete = False
            item_defaults = None
        else:
            completions = result.items
            is_incomplete = result.isIncomplete
            item_defaults = result.itemDefaults

        assert not item_defaults

        if len(completions) == 0:
            # the user typed something which is not completable
            self._close_box()
            return
        else:
            # Log completion count
            logger.info(f"📥 LSP response #{lsp_request_id}: {len(completions)} completions")
            
            # Show completions
            logger.info(f"🎯 _handle_completions_response #{lsp_request_id}: showing {len(completions)} completions (normal path)")
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)

    def _rerank_completions_with_ai_async_and_show(self, completions: List[lsp_types.CompletionItem], text: SyntaxText) -> None:
        """Rerank completions using AI in background, then show (non-blocking - UI doesn't freeze!)"""
        import threading
        from thonny.plugins.base_assistant import get_ai_assistant
        
        # Mark AI request as in progress
        self._ai_request_in_progress = True
        logger.info(f"🔒 AI request started (blocking new requests)")
        
        # Get AI assistant
        assistant = get_ai_assistant()
        if not assistant:
            logger.info("No AI assistant available, showing completions immediately")
            self._ai_request_in_progress = False  # Release lock
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)  # Will apply our sorting
            return
        
        try:
            # Step 1: Apply our smart sorting (local variables first, etc.)
            prefix_start_index = text.tag_ranges("sel")
            if prefix_start_index:
                prefix_start_index = prefix_start_index[0]
            else:
                prefix_start_index = self._completions_box._find_completion_insertion_index() if self._completions_box else text.index("insert")
            
            prefix = text.get(prefix_start_index, "insert") if text.compare(prefix_start_index, "<=", "insert") else ""
            
            # Get context for context-aware ranking
            try:
                line_before_cursor = text.get("insert linestart", "insert")
                line_after_cursor = text.get("insert", "insert lineend")
                # Get code BEFORE cursor for Parso (only variables above matter!)
                source_code = text.get("1.0", "insert")
            except:
                line_before_cursor = ""
                line_after_cursor = ""
                source_code = ""
            
            # Use shared context-aware sorting logic
            logger.info(f"🔄 Applying context-aware sort to {len(completions)} completions (AI path)")
            sort_key = create_context_aware_sort_key(prefix, line_before_cursor, line_after_cursor, source_code)
            sorted_completions = sorted(completions, key=sort_key)
            
            logger.info(f"📋 Top 20 after context-aware sort:")
            for i, item in enumerate(sorted_completions[:20]):
                kind_name = lsp_types.CompletionItemKind(item.kind).name if item.kind else "Unknown"
                detail_str = f" ({item.detail[:20]}...)" if item.detail and len(item.detail) > 20 else f" ({item.detail})" if item.detail else ""
                logger.info(f"  [{i+1:2d}] {item.label:25s} | {kind_name:12s}{detail_str}")
            if len(sorted_completions) > 20:
                logger.info(f"  ... and {len(sorted_completions) - 20} more")
            logger.info(f"━" * 80)
            
            # Step 2: Take top 50 for AI reranking
            top_completions = sorted_completions[:50]
            
            # Extract labels and kinds
            labels = [item.label for item in top_completions]
            completion_kinds = {}
            for item in top_completions:
                if item.kind:
                    kind_name = lsp_types.CompletionItemKind(item.kind).name
                    completion_kinds[item.label] = kind_name
            
            logger.info(f"🤖 Sending top {len(labels)} to AI for reranking")
            
            # Step 3: Get reasonable context (last 100 lines or less)
            try:
                cursor_index = text.index("insert")
                cursor_line_num = int(cursor_index.split(".")[0])
                
                # Get last 100 lines (or from start if file is small)
                context_start_line = max(1, cursor_line_num - 100)
                code_context = text.get(f"{context_start_line}.0", cursor_index)
                cursor_line = text.get(f"{cursor_line_num}.0", cursor_index)
                
                logger.info(f"📝 Sending context: {len(code_context)} chars, lines {context_start_line}-{cursor_line_num}")
                logger.info(f"   Current line: '{cursor_line}' ← cursor here")
                
            except Exception as e:
                logger.warning(f"Failed to get full context: {e}")
                code_context = text.get("1.0", "end")
                cursor_line = ""
            
            # Remember current request to detect if it's stale
            request_text = text
            original_completions_list = sorted_completions
            
            # Step 4: Call AI in BACKGROUND THREAD (non-blocking!)
            logger.info(f"⏳ Starting AI request in background (UI не зависає!)...")
            
            def do_ai_reranking():
                try:
                    reranked_labels = assistant.rerank_completions(
                        code_context=code_context,
                        cursor_line=cursor_line,
                        completions=labels,
                        max_results=len(labels),  # Rerank ALL top-50
                        completion_kinds=completion_kinds
                    )
                    
                    logger.info(f"✅ AI returned {len(reranked_labels)} labels")
                    
                    # Step 5: Reorder based on AI ranking
                    label_to_item = {item.label: item for item in top_completions}
                    reordered = []
                    seen = set()
                    
                    for label in reranked_labels:
                        if label in label_to_item and label not in seen:
                            reordered.append(label_to_item[label])
                            seen.add(label)
                    
                    # Add any remaining from top-50 that AI didn't include
                    for item in top_completions:
                        if item.label not in seen:
                            reordered.append(item)
                    
                    # Add rest of completions (beyond top-50) at the end
                    for item in original_completions_list[50:]:
                        reordered.append(item)
                    
                    logger.info(f"📤 Final reranked list ({len(reordered)} items):")
                    for i, comp in enumerate(reordered[:20]):
                        kind_name = lsp_types.CompletionItemKind(comp.kind).name if comp.kind else "Unknown"
                        logger.info(f"  [{i:2d}] {comp.label:30s} | {kind_name:12s}")
                    if len(reordered) > 20:
                        logger.info(f"  ... and {len(reordered) - 20} more")
                    logger.info(f"━" * 80)
                    
                    # Show completions in UI thread
                    def show_completions():
                        try:
                            # Check if request is still valid (user didn't type more)
                            if self._last_request_text == request_text:
                                if not self._completions_box:
                                    self._completions_box = CompletionsBox(self)
                                # Pass skip_sorting=True so AI order is preserved!
                                self._completions_box.present_completions(request_text, reordered, skip_sorting=True)
                                logger.info(f"✅ Completions box shown to user (with AI sorting)")
                            else:
                                logger.info(f"⏭️  AI response ignored (user typed more, request stale)")
                        finally:
                            # Always release the lock
                            self._ai_request_in_progress = False
                            logger.info(f"🔓 AI request finished (accepting new requests)")
                    
                    # Schedule showing in UI thread
                    get_workbench().after(0, show_completions)
                    
                except Exception as e:
                    logger.exception(f"❌ AI reranking failed: {e}")
                    # Fallback: show original completions (pre-sorted by our algorithm)
                    def show_fallback():
                        try:
                            if self._last_request_text == request_text:
                                if not self._completions_box:
                                    self._completions_box = CompletionsBox(self)
                                # Original list is already sorted by our algorithm, skip re-sorting
                                self._completions_box.present_completions(request_text, original_completions_list, skip_sorting=True)
                        finally:
                            # Always release the lock
                            self._ai_request_in_progress = False
                            logger.info(f"🔓 AI request finished (error fallback, accepting new requests)")
                    get_workbench().after(0, show_fallback)
            
            # Start background thread
            thread = threading.Thread(target=do_ai_reranking, daemon=True)
            thread.start()
            # Return immediately - UI не зависає!
            
        except Exception as e:
            logger.exception(f"❌ AI reranking setup failed: {e}")
            # Release lock
            self._ai_request_in_progress = False
            logger.info(f"🔓 AI request failed to start (accepting new requests)")
            # Fallback: show completions immediately (without sorting - will be sorted by present_completions)
            if not self._completions_box:
                self._completions_box = CompletionsBox(self)
            self._completions_box.present_completions(self._last_request_text, completions)  # Let it sort naturally
    
    def _rerank_completions_with_ai_async(self, completions: List[lsp_types.CompletionItem], text: SyntaxText) -> None:
        """Rerank completions using AI in background (non-blocking)"""
        import threading
        from thonny.plugins.base_assistant import get_ai_assistant
        
        # Get AI assistant
        assistant = get_ai_assistant()
        if not assistant:
            return  # No AI available
        
        # Extract labels and kinds from completions
        labels = [item.label for item in completions]
        completion_kinds = {}
        for item in completions:
            if item.kind:
                kind_name = lsp_types.CompletionItemKind(item.kind).name
                completion_kinds[item.label] = kind_name
        
        logger.info(f"🤖 Starting AI reranking for {len(labels)} completions:")
        logger.info(f"   All labels: {labels}")
        logger.info(f"   With types: {completion_kinds}")
        
        # Get code context (10 lines before and after cursor)
        try:
            cursor_index = text.index("insert")
            cursor_line_num = int(cursor_index.split(".")[0])
            
            # Get surrounding lines
            start_line = max(1, cursor_line_num - 10)
            end_line = cursor_line_num + 10
            
            code_context = text.get(f"{start_line}.0", f"{end_line}.0")
            cursor_line = text.get(f"{cursor_line_num}.0", f"{cursor_line_num}.end")
            
            logger.info(f"📝 Code context (lines {start_line}-{end_line}, cursor at line {cursor_line_num}):")
            logger.info(f"━" * 80)
            logger.info(code_context)
            logger.info(f"   Current line: '{cursor_line}' ← cursor here")
            logger.info(f"━" * 80)
            
        except:
            # Fallback: use whole file
            code_context = text.get("1.0", "end")
            cursor_line = ""
            logger.info(f"⚠️  Failed to get cursor context, using whole file")
        
        # Remember current request to detect if it's stale
        request_text = text
        original_completions = completions
        
        def do_reranking():
            try:
                reranked_labels = assistant.rerank_completions(
                    code_context=code_context,
                    cursor_line=cursor_line,
                    completions=labels,
                    max_results=15,  # Limit to top 15
                    completion_kinds=completion_kinds  # Pass type information
                )
                
                # Update UI in main thread
                def update_ui():
                    # Check if completions box is still open and for the same text widget
                    if (self._completions_box and 
                        self._completions_box.winfo_exists() and 
                        self._last_request_text == request_text):
                        
                        logger.info(f"✅ AI returned {len(reranked_labels)} labels: {reranked_labels}")
                        self._completions_box.update_order_from_ai(reranked_labels, original_completions)
                    else:
                        logger.info(f"⏭️  AI response ignored (completions box closed or stale)")
                        logger.info(f"   Box exists: {self._completions_box is not None and self._completions_box.winfo_exists()}, Same text: {self._last_request_text == request_text}")
                
                # Schedule UI update in main thread
                if self._completions_box:
                    get_workbench().after(0, update_ui)
                    
            except Exception as e:
                logger.info(f"❌ AI reranking failed (async): {e}")
        
        # Start background thread (no join - truly async!)
        thread = threading.Thread(target=do_reranking, daemon=True)
        thread.start()
    
    def patched_perform_midline_tab(self, event):
        self.cancel_active_request()

        if not event or not isinstance(event.widget, SyntaxText):
            return
        text = event.widget

        if text.is_python_text():
            if isinstance(text, ShellText):
                option_name = "edit.tab_request_completions_in_shell"
            else:
                option_name = "edit.tab_request_completions_in_editors"

            if get_workbench().get_option(option_name):
                if not text.has_selection():
                    self.request_completions_for_text(text)
                    return "break"
                else:
                    return None

        return text.perform_dumb_tab(event)


def _is_python_name_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def load_plugin() -> None:
    completer = Completer()

    def can_complete():
        runner = get_runner()
        return runner and not runner.is_running()

    get_workbench().add_command(
        "autocomplete",
        "edit",
        tr("Auto-complete"),
        completer.request_completions,
        default_sequence="<Control-space>",
        tester=can_complete,
    )

    get_workbench().set_default("edit.tab_request_completions_in_editors", True)
    get_workbench().set_default("edit.tab_request_completions_in_shell", True)
    get_workbench().set_default("edit.automatic_completions", True)
    get_workbench().set_default("edit.automatic_completion_details", False)
    get_workbench().set_default("edit.code_language", "Ukrainian")

    CodeViewText.perform_midline_tab = completer.patched_perform_midline_tab
    ShellText.perform_midline_tab = completer.patched_perform_midline_tab
