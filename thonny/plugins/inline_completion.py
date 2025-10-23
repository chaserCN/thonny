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
        logger.info("Initializing InlineCompleter")
        self._current_suggestion: Optional[str] = None
        self._suggestion_start_index: Optional[str] = None
        self._active_text_widget: Optional[CodeViewText] = None
        self._debounce_timer: Optional[threading.Timer] = None
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.5  # 500ms between requests
        
        # Bind to editor events
        logger.info("Binding to EditorCodeViewText events...")
        get_workbench().bind_class("EditorCodeViewText", "<Key>", self._on_keypress, True)
        get_workbench().bind_class("EditorCodeViewText", "<Tab>", self._on_tab, True)
        get_workbench().bind_class("EditorCodeViewText", "<Escape>", self._on_escape, True)
        logger.info("Event bindings completed")
        
        # Configure ghost text tag
        self._setup_ghost_text_tag()
    
    def _setup_ghost_text_tag(self):
        """Configure the visual style for ghost text suggestions"""
        # Will be applied to each text widget when needed
        pass
    
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
        
        # Clear current suggestion on most keypresses
        if event.keysym not in ("Shift_L", "Shift_R", "Control_L", "Control_R", 
                                "Alt_L", "Alt_R", "Meta_L", "Meta_R"):
            self._clear_suggestion(widget)
        
        # Don't trigger on special keys
        if event.keysym in ("Tab", "Return", "Escape", "BackSpace", "Delete"):
            return None
        
        # Debounce: wait for typing to pause
        if self._debounce_timer:
            self._debounce_timer.cancel()
        
        logger.debug(f"Starting debounce timer for widget {widget}")
        self._debounce_timer = threading.Timer(
            0.3,  # 300ms delay after last keypress
            lambda: self._request_suggestion(widget)
        )
        self._debounce_timer.start()
        
        return None
    
    def _on_tab(self, event: tk.Event) -> Optional[str]:
        """Handle Tab key to accept suggestion"""
        widget = event.widget
        if not isinstance(widget, CodeViewText):
            return None
        
        if self._current_suggestion and self._active_text_widget == widget:
            # Accept the suggestion
            self._accept_suggestion(widget)
            return "break"  # Prevent default Tab behavior
        
        return None  # Allow default Tab behavior
    
    def _on_escape(self, event: tk.Event) -> Optional[str]:
        """Handle Escape to dismiss suggestion"""
        widget = event.widget
        if not isinstance(widget, CodeViewText):
            return None
        
        if self._current_suggestion and self._active_text_widget == widget:
            self._clear_suggestion(widget)
            return "break"
        
        return None
    
    def _request_suggestion(self, widget: CodeViewText):
        """Request inline completion from Gemini"""
        logger.info("_request_suggestion called")
        
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
            
            logger.info(f"Requesting completion for: '{line_prefix}' (context: {len(context)} chars)")
            
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
        logger.info("_fetch_suggestion: Starting API request")
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
                # Use fast model for inline completion
                model_name = get_workbench().get_option("ai.inline_completion_model", "gemini-2.0-flash-exp")
                logger.info(f"Using model: {model_name}")
                model = genai.GenerativeModel(model_name)
                
                logger.debug("Sending request to Gemini...")
                response = model.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.2,  # Low temperature for more predictable completions
                        'max_output_tokens': 100,
                    }
                )
                
                raw_suggestion = response.text.strip()
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
        if not raw:
            return ""
        
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
            line = line.strip()
            
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
        
        return result_lines[0] if result_lines else ""
    
    def _build_completion_prompt(self, context: str, line_prefix: str) -> str:
        """Build prompt for inline code completion"""
        return f"""You are a code completion AI. Complete the Python code after the cursor position.

RULES:
- Return ONLY the text to insert after the cursor
- NO explanations, NO markdown, NO code blocks
- Complete the current line or suggest next line if current is finished
- Keep completions SHORT (one line preferred)
- Match the coding style

CODE:
```python
{context}█
```

The cursor (█) is after: `{line_prefix}`

COMPLETE THE CODE (return only the text after cursor):"""
    
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
        if not self._current_suggestion or not self._suggestion_start_index:
            return
        
        try:
            # Remove ghost text tag
            end_index = f"{self._suggestion_start_index}+{len(self._current_suggestion)}c"
            widget.tag_remove("ghost_text", self._suggestion_start_index, end_index)
            
            # Move cursor to end of suggestion
            widget.mark_set("insert", end_index)
            widget.see("insert")
            
            # Clear state
            self._current_suggestion = None
            self._suggestion_start_index = None
            self._active_text_widget = None
            
        except tk.TclError as e:
            logger.debug(f"Failed to accept suggestion: {e}")
    
    def _clear_suggestion(self, widget: CodeViewText):
        """Clear the current ghost text suggestion"""
        if not self._current_suggestion or not self._suggestion_start_index:
            return
        
        try:
            # Remove ghost text
            end_index = f"{self._suggestion_start_index}+{len(self._current_suggestion)}c"
            widget.delete(self._suggestion_start_index, end_index)
            
            # Clear state
            self._current_suggestion = None
            self._suggestion_start_index = None
            self._active_text_widget = None
            
        except tk.TclError:
            pass


def load_plugin():
    """Initialize inline completion plugin"""
    logger.info("=== Loading inline completion plugin ===")
    
    completer = InlineCompleter()
    
    # Add settings
    get_workbench().set_default("edit.inline_completions_enabled", True)
    get_workbench().set_default("ai.inline_completion_model", "gemini-2.0-flash-exp")
    
    logger.info(f"Inline completion plugin loaded successfully, enabled={get_workbench().get_option('edit.inline_completions_enabled', True)}")

