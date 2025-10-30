"""
Inline code completion using Gemini Flash
Shows ghost text suggestions that can be accepted with Tab
"""
import logging
import threading
import time
import tkinter as tk
from typing import Optional

from thonny import get_workbench
from thonny.codeview import CodeViewText
from thonny.plugins.gemini import GeminiAssistant

logger = logging.getLogger(__name__)


class InlineCompleter:
    """Manages inline code completions with ghost text"""
    
    def __init__(self):
        self._current_suggestion: Optional[str] = None
        self._suggestion_start_index: Optional[str] = None
        self._active_text_widget: Optional[CodeViewText] = None
        self._debounce_timer: Optional[threading.Timer] = None
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.5  # 500ms between requests
        
        # Use empty string binding tag to run before class bindings
        get_workbench().bind_class("EditorCodeViewText", "<KeyPress>", self._on_keypress_before, False)
        get_workbench().bind_class("EditorCodeViewText", "<Key>", self._on_keypress, True)
        get_workbench().bind_class("EditorCodeViewText", "<Escape>", self._on_escape, True)
        get_workbench().bind_class("EditorCodeViewText", "<Button-1>", self._on_mouse_click, True)
        get_workbench().bind_class("EditorCodeViewText", "<FocusOut>", self._on_focus_out, True)
        
        # Patch perform_midline_tab to handle Tab key
        self._patch_tab_handler()
        
        # Configure ghost text tag
        self._setup_ghost_text_tag()
    
    def _setup_ghost_text_tag(self):
        """Configure the visual style for ghost text suggestions"""
        # Will be applied to each text widget when needed
        pass
    
    def _patch_tab_handler(self):
        """Patch Tab methods to handle inline completions"""
        
        # Save original methods
        original_perform_midline_tab = CodeViewText.perform_midline_tab
        original_perform_smart_tab = CodeViewText.perform_smart_tab
        original_perform_dumb_tab = CodeViewText.perform_dumb_tab
        
        # Helper to check and accept suggestion
        completer_self = self  # Capture self in closure
        
        def check_and_accept_suggestion(text_widget, method_name):
            
            # Check if this widget has an active suggestion
            if completer_self._current_suggestion and completer_self._active_text_widget == text_widget:
                completer_self._accept_suggestion(text_widget)
                return "break"
            return None
        
        # Patch all three Tab handlers (these are instance methods, so first arg is self=text_widget)
        def patched_perform_midline_tab(text_widget_self, event=None):
            result = check_and_accept_suggestion(text_widget_self, "perform_midline_tab")
            if result == "break":
                return result
            return original_perform_midline_tab(text_widget_self, event)
        
        def patched_perform_smart_tab(text_widget_self, event=None):
            result = check_and_accept_suggestion(text_widget_self, "perform_smart_tab")
            if result == "break":
                return result
            return original_perform_smart_tab(text_widget_self, event)
        
        def patched_perform_dumb_tab(text_widget_self, event=None):
            result = check_and_accept_suggestion(text_widget_self, "perform_dumb_tab")
            if result == "break":
                return result
            return original_perform_dumb_tab(text_widget_self, event)
        
        # Replace methods
        CodeViewText.perform_midline_tab = patched_perform_midline_tab
        CodeViewText.perform_smart_tab = patched_perform_smart_tab
        CodeViewText.perform_dumb_tab = patched_perform_dumb_tab
    
    def _on_keypress_before(self, event: tk.Event) -> Optional[str]:
        """Handle keypress BEFORE text insertion - clear ghost text"""
        widget = event.widget
        if not isinstance(widget, CodeViewText):
            return None
        
        # Clear ghost text before any key that inserts text
        # (but not for modifier keys)
        if event.keysym not in ("Shift_L", "Shift_R", "Control_L", "Control_R", 
                                "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                                "Tab", "Escape", "Up", "Down", "Left", "Right", 
                                "Home", "End", "Page_Up", "Page_Down"):
            self._clear_suggestion(widget)
        
        return None  # Allow event to continue
    
    def _on_keypress(self, event: tk.Event) -> Optional[str]:
        """Handle keypress events to trigger suggestions"""
        enabled = get_workbench().get_option("edit.inline_completions_enabled", True)
        logger.debug(f"Keypress: {event.keysym}, inline_completions_enabled={enabled}")
        
        if not enabled:
            return None
        
        widget = event.widget
        if not isinstance(widget, CodeViewText):
            logger.debug(f"Not CodeViewText: {type(widget)}")
            return None
        
        # Ghost text already cleared in _on_keypress_before
        
        # Don't trigger on some special keys (but Return/BackSpace/Delete are OK)
        if event.keysym in ("Tab", "Escape", 
                           "Up", "Down", "Left", "Right", "Home", "End", 
                           "Page_Up", "Page_Down"):
            # But for arrow keys, if we end up on empty line, trigger after delay
            if event.keysym in ("Up", "Down", "Left", "Right"):
                widget.after(1000, lambda: self._check_empty_line(widget))
            return None
        
        # Debounce: wait for typing to pause
        if self._debounce_timer:
            self._debounce_timer.cancel()
        
        # Longer delay for empty lines (suggest next line) vs typing
        try:
            cursor_pos = widget.index("insert")
            line_start = widget.index("insert linestart")
            line_prefix = widget.get(line_start, cursor_pos).strip()
            
            # Empty line or just whitespace = suggest next line (longer delay)
            if not line_prefix:
                delay = 1.0  # 1 second for empty line
                logger.debug(f"Empty line, using {delay}s delay")
            else:
                delay = 0.3  # 300ms when typing
                logger.debug(f"Typing detected, using {delay}s delay")
        except:
            delay = 0.3
        
        logger.debug(f"Starting debounce timer for widget {widget}")
        self._debounce_timer = threading.Timer(
            delay,
            lambda: self._request_suggestion(widget)
        )
        self._debounce_timer.start()
        
        return None
    
    def _on_escape(self, event: tk.Event) -> Optional[str]:
        """Handle Escape to dismiss suggestion"""
        widget = event.widget
        if not isinstance(widget, CodeViewText):
            return None
        
        if self._current_suggestion and self._active_text_widget == widget:
            self._clear_suggestion(widget)
            return "break"
        
        return None
    
    def _on_mouse_click(self, event: tk.Event) -> Optional[str]:
        """Handle mouse click to dismiss suggestion"""
        widget = event.widget
        if isinstance(widget, CodeViewText):
            self._clear_suggestion(widget)
            # After click, if on empty line, suggest after 1 second
            widget.after(1000, lambda: self._check_empty_line(widget))
        return None
    
    def _check_empty_line(self, widget: CodeViewText):
        """Check if current line is empty and trigger suggestion if so"""
        try:
            cursor_pos = widget.index("insert")
            line_start = widget.index("insert linestart")
            line_prefix = widget.get(line_start, cursor_pos).strip()
            
            # If line is empty/whitespace and no current suggestion, request one
            if not line_prefix and not self._current_suggestion:
                logger.debug("Empty line detected, requesting suggestion...")
                self._request_suggestion(widget)
        except:
            pass
    
    def _on_focus_out(self, event: tk.Event) -> Optional[str]:
        """Handle focus out to dismiss suggestion"""
        widget = event.widget
        if isinstance(widget, CodeViewText):
            self._clear_suggestion(widget)
        return None
    
    def _request_suggestion(self, widget: CodeViewText):
        """Request inline completion from Gemini"""
        
        # Rate limiting
        now = time.time()
        if now - self._last_request_time < self._min_request_interval:
            logger.debug(f"Rate limited: {now - self._last_request_time:.2f}s < {self._min_request_interval}s")
            return
        
        self._last_request_time = now
        
        # Get context
        try:
            cursor_pos = widget.index("insert")
            line_start = widget.index("insert linestart")
            line_prefix = widget.get(line_start, cursor_pos)
            
            # Don't suggest in comments or strings (simple heuristic)
            if "#" in line_prefix or '"' in line_prefix or "'" in line_prefix:
                logger.debug(f"Skipping: comment or string detected in '{line_prefix}'")
                return
            
            # Get more context (previous lines)
            start_line = max(1, int(cursor_pos.split('.')[0]) - 10)
            context_start = f"{start_line}.0"
            context = widget.get(context_start, cursor_pos)
            
            # Request completion in background thread
            threading.Thread(
                target=self._fetch_suggestion,
                args=(widget, cursor_pos, context, line_prefix),
                daemon=True
            ).start()
            
        except tk.TclError:
            pass
    
    def _fetch_suggestion(self, widget: CodeViewText, cursor_pos: str, 
                         context: str, line_prefix: str):
        """Fetch suggestion from Gemini API (runs in background thread)"""
        try:
            # Get API key
            api_key = get_workbench().get_secret("gemini_api_key")
            if not api_key:
                logger.warning("No Gemini API key configured for inline completion")
                return
            
            logger.debug(f"API key found: {api_key[:10]}...")
            
            # Build prompt for code completion
            prompt = self._build_completion_prompt(context, line_prefix)
            
            # Use Gemini API directly (avoid importing heavy dependencies)
            try:
                import google.generativeai as genai
                
                genai.configure(api_key=api_key)
                # Use fast model for inline completion (Flash-Lite has 4000 RPM!)
                model_name = get_workbench().get_option("ai.inline_completion_model", "gemini-2.0-flash")
                model = genai.GenerativeModel(model_name)
                
                logger.debug("Sending request to Gemini...")
                response = model.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.2,  # Low temperature for more predictable completions
                        'max_output_tokens': 100,
                    }
                )
                
                # Check if response has candidates
                if not response.candidates:
                    logger.warning("Gemini returned no candidates (may be blocked by safety filters)")
                    return
                
                try:
                    raw_suggestion = response.text.strip()
                except ValueError as e:
                    logger.warning(f"Could not get response text: {e}")
                    return
                
                logger.info(f"Got raw suggestion: '{raw_suggestion[:100]}'")
                
                # Clean up the suggestion
                suggestion = self._clean_suggestion(raw_suggestion)
                logger.info(f"Cleaned suggestion: '{suggestion[:50]}...'")
                
                if suggestion:
                    # Schedule UI update on main thread
                    widget.after(0, lambda: self._show_suggestion(widget, cursor_pos, suggestion))
                else:
                    logger.debug("Empty suggestion after cleaning, skipping")
                
            except ImportError as e:
                logger.error(f"google-generativeai package not installed! Run: pip install google-generativeai. Error: {e}")
            except Exception as api_error:
                logger.error(f"Gemini API error: {api_error}", exc_info=True)
            
        except Exception as e:
            logger.error(f"Failed to fetch inline completion: {e}", exc_info=True)
    
    def _clean_suggestion(self, raw: str) -> str:
        """Clean up AI response to get pure code suggestion"""
        # Ensure raw is a string
        if not raw:
            return ""
        
        raw = str(raw)  # Convert to string if it's a Tcl object
        
        # Remove markdown code blocks
        if "```" in raw:
            # Extract code between ```python and ``` or ``` and ```
            parts = raw.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Odd indices are code blocks
                    code = part.strip()
                    if code.startswith("python\n"):
                        code = code[7:]
                    return code.strip()
        
        # Split by lines and take meaningful content
        lines = raw.split('\n')
        result_lines = []
        
        for line in lines:
            line = str(line).strip()  # Convert to string and strip
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip explanatory text (heuristics)
            if line.startswith(('Note:', 'Explanation:', 'This', 'The', '**', '#')):
                continue
            
            # Take code-like lines
            result_lines.append(line)
            
            # For inline completion, usually just one line is enough
            if len(result_lines) >= 1:
                break
        
        suggestion = str(result_lines[0]) if result_lines else ""
        
        # Remove surrounding quotes if present
        if suggestion:
            # Remove outer quotes: "code" or 'code'
            if (suggestion.startswith('"') and suggestion.endswith('"')) or \
               (suggestion.startswith("'") and suggestion.endswith("'")):
                suggestion = suggestion[1:-1]
        
        return str(suggestion)
    
    def _build_completion_prompt(self, context: str, line_prefix: str) -> str:
        """Build prompt for inline code completion"""
        # Ensure parameters are strings
        context = str(context)
        line_prefix = str(line_prefix)
        
        # Check if we're suggesting next line or completing current line
        if not line_prefix.strip():
            task = "Suggest the NEXT LINE of code that should come after the cursor"
        else:
            task = "Complete the current line of code"
        
        return f"""You are a code completion AI. {task}.

RULES:
- Return ONLY the code to insert (one line)
- NO explanations, NO markdown, NO code blocks, NO quotes around code
- Keep it SHORT and SIMPLE
- Match the coding style and indentation

CODE:
```python
{context}█
```

The cursor (█) is at the end of line. Return ONLY the code to insert:"""
    
    def _show_suggestion(self, widget: CodeViewText, cursor_pos: str, suggestion: str):
        """Show ghost text suggestion in the editor (main thread)"""
        logger.info(f"_show_suggestion called with: '{suggestion}'")
        try:
            # Verify cursor hasn't moved
            current_pos = widget.index("insert")
            if current_pos != cursor_pos:
                logger.debug(f"Cursor moved: {cursor_pos} -> {current_pos}, skipping suggestion")
                return
            
            # Configure ghost text tag if not already done
            if "ghost_text" not in widget.tag_names():
                widget.tag_configure("ghost_text", foreground="gray60")
            
            # Clear any previous suggestion
            self._clear_suggestion(widget)
            
            # Suggestion is already cleaned by _clean_suggestion
            # Just verify it's not empty
            if not suggestion:
                logger.debug("Empty suggestion, skipping")
                return
            
            # Store suggestion state
            self._current_suggestion = suggestion
            self._suggestion_start_index = cursor_pos
            self._active_text_widget = widget
            
            # Insert ghost text at cursor
            logger.info(f"Inserting ghost text: '{suggestion}' at {cursor_pos}")
            widget.insert(cursor_pos, suggestion, "ghost_text")
            
            # Move cursor back to original position
            widget.mark_set("insert", cursor_pos)
            widget.see("insert")
            logger.info("Ghost text displayed successfully")
            
        except tk.TclError as e:
            logger.debug(f"Failed to show suggestion: {e}")
    
    def _accept_suggestion(self, widget: CodeViewText):
        """Accept the current suggestion"""
        logger.info(f"_accept_suggestion called: suggestion='{self._current_suggestion}', start={self._suggestion_start_index}")
        
        if not self._current_suggestion or not self._suggestion_start_index:
            logger.warning("No suggestion to accept!")
            return
        
        try:
            # Remove ghost text tag (keep the text, just remove the tag)
            end_index = f"{self._suggestion_start_index}+{len(self._current_suggestion)}c"
            logger.debug(f"Removing ghost_text tag from {self._suggestion_start_index} to {end_index}")
            widget.tag_remove("ghost_text", self._suggestion_start_index, end_index)
            
            # Move cursor to end of suggestion
            logger.debug(f"Moving cursor to {end_index}")
            widget.mark_set("insert", end_index)
            widget.see("insert")
            
            # Clear state
            logger.info("Suggestion accepted successfully")
            self._current_suggestion = None
            self._suggestion_start_index = None
            self._active_text_widget = None
            
        except tk.TclError as e:
            logger.error(f"Failed to accept suggestion: {e}", exc_info=True)
    
    def _clear_suggestion(self, widget: CodeViewText):
        """Clear the current ghost text suggestion"""
        if not self._current_suggestion or not self._suggestion_start_index:
            return
        
        try:
            # Find all text with ghost_text tag and remove it
            ranges = widget.tag_ranges("ghost_text")
            if ranges:
                # Remove in reverse order to maintain indices
                for i in range(len(ranges)-1, -1, -2):
                    if i > 0:
                        # Convert Tcl objects to strings
                        start = str(ranges[i-1])
                        end = str(ranges[i])
                        widget.delete(start, end)
            
            # Clear state
            self._current_suggestion = None
            self._suggestion_start_index = None
            self._active_text_widget = None
            
        except tk.TclError:
            pass


# ВРЕМЕННО ЗАКОММЕНТИРОВАНО - задача требует доработки
# def load_plugin():
#     """Initialize inline completion plugin"""
#     logger.info("=== Loading inline completion plugin ===")
#     
#     completer = InlineCompleter()
#     
#     # Add settings
#     get_workbench().set_default("edit.inline_completions_enabled", True)
#     get_workbench().set_default("ai.inline_completion_model", "gemini-2.0-flash")  # 2000 RPM
#     
#     logger.info(f"Inline completion plugin loaded successfully, enabled={get_workbench().get_option('edit.inline_completions_enabled', True)}")

