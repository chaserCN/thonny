"""
Highlights diagnostics (errors/warnings) in the editor with squiggly underlines.
Shows tooltips with translations via Gemini on hover.
"""
import tkinter as tk
from logging import getLogger
from typing import Dict, List, Optional, Union
from dataclasses import dataclass

from thonny import get_workbench
from thonny.editors import Editor
from thonny.lsp_proxy import LanguageServerProxy
from thonny.lsp_types import (
    Diagnostic, 
    DiagnosticSeverity, 
    PublishDiagnosticsParams,
    LspResponse,
    DocumentDiagnosticReport,
)
from thonny.plugins.tooltip_state_machine import (
    TooltipStateMachine,
    TooltipEvent,
    TooltipAction,
)

logger = getLogger(__name__)


class DiagnosticTooltip:
    """Tooltip that shows diagnostic message with optional AI translation"""
    
    def __init__(self, text_widget: tk.Text, hover_delay_ms: int = 1500):
        self.text_widget = text_widget
        self.tooltip_window = None
        self._translation_cache = {}  # message -> translation
        self._cache_timestamps = {}  # message -> timestamp
        self._hover_timer = None  # Timer for hover delay
        self._pending_requests = set()  # Set of message hashes currently being requested
        self._menu_open = False  # Flag to prevent tooltip during menu
        self._menu_timer = None  # Timer to reset menu flag
        self._current_language = None  # Track current language to detect changes
        
        # Track mouse motion to prevent tooltip when error appears under static mouse
        self._last_mouse_motion_time = 0  # Time of last mouse motion event
        self._mouse_moved_recently = False  # True if mouse moved in last 500ms
        
        # State machine manages tooltip lifecycle
        self.state_machine = TooltipStateMachine(hover_delay_ms=hover_delay_ms)
        # Give state machine access to cache and pending requests
        self.state_machine.set_cache(self._translation_cache)
        self.state_machine.set_pending_requests(self._pending_requests)
        
        # Clear cache when text is modified
        self.text_widget.bind("<<Modified>>", self._on_text_modified, add=True)
        self.text_widget.bind("<<TextChange>>", self._on_text_modified, add=True)
        self._last_text_length = len(self.text_widget.get("1.0", "end"))
        
        # Track mouse motion globally on text widget
        self.text_widget.bind("<Motion>", self._on_mouse_motion, add=True)
        
        # Hide tooltip when context menu appears
        self.text_widget.bind("<<ContextMenuShowing>>", self._on_context_menu_showing, add=True)
        # Reset menu flag when clicking back in editor
        self.text_widget.bind("<Button-1>", self._on_left_click, add=True)
    
    def _on_mouse_motion(self, event) -> None:
        """Track mouse motion to distinguish real hover from error appearing under cursor"""
        import time
        self._last_mouse_motion_time = time.time()
        self._mouse_moved_recently = True
    
    def _on_text_modified(self, event=None) -> None:
        """Clear translation cache when code is modified"""
        try:
            current_length = len(self.text_widget.get("1.0", "end"))
            if current_length != self._last_text_length:
                if self._translation_cache:
                    self._translation_cache.clear()
                    self._cache_timestamps.clear()
                # Clear pending requests (they are now stale)
                self._pending_requests.clear()
                self._last_text_length = current_length
                
                # Notify state machine
                actions = self.state_machine.handle_event(TooltipEvent.TEXT_CHANGED)
                self._execute_actions(actions)
        except tk.TclError:
            pass  # Widget might be destroyed
    
    def _on_context_menu_showing(self, event=None) -> None:
        """Handle <<ContextMenuShowing>> event from codeview"""
        # Set flag FIRST to prevent tooltip from showing while menu is open
        self._menu_open = True
        # Then hide any existing tooltip and cancel timers
        self.hide()
        # Cancel any pending menu timer
        if self._menu_timer:
            self.text_widget.after_cancel(self._menu_timer)
        # Auto-reset flag after 3 seconds (in case menu is dismissed without clicking)
        self._menu_timer = self.text_widget.after(3000, self._reset_menu_flag)
    
    def _on_left_click(self, event=None) -> None:
        """Reset menu flag when clicking back in editor"""
        self._reset_menu_flag()
    
    def _reset_menu_flag(self) -> None:
        """Reset the menu open flag"""
        self._menu_open = False
        if self._menu_timer:
            try:
                self.text_widget.after_cancel(self._menu_timer)
            except:
                pass
            self._menu_timer = None
        
    def show(self, event, diagnostic: Diagnostic) -> None:
        """Show tooltip with diagnostic message (entry point from mouse hover)"""
        import time
        
        # Check if mouse moved recently (within 500ms)
        # This prevents tooltip when error appears under static mouse cursor
        time_since_motion = time.time() - self._last_mouse_motion_time
        if time_since_motion > 0.5:  # 500ms threshold
            # Mouse hasn't moved - likely error appeared under cursor, not real hover
            logger.debug(f"Ignoring tooltip show: no recent mouse motion ({time_since_motion:.2f}s ago)")
            return
        
        # Build full message with source and line number
        message = diagnostic.message
        line_number = diagnostic.range.start.line + 1 if diagnostic.range else 0
        if diagnostic.source:
            full_message = f"[{diagnostic.source}] L{line_number}: {message}"
        else:
            full_message = f"L{line_number}: {message}"
        
        request_id = hash(full_message)
        
        # Send MOUSE_ENTER event to state machine
        actions = self.state_machine.handle_event(TooltipEvent.MOUSE_ENTER, {
            'message': full_message,
            'event': event,
            'severity': diagnostic.severity,
            'diagnostic': diagnostic,
            'request_id': request_id
        })
        
        self._execute_actions(actions)
    
    def hide(self) -> None:
        """Hide tooltip (entry point from mouse leave)"""
        actions = self.state_machine.handle_event(TooltipEvent.MOUSE_LEAVE)
        self._execute_actions(actions)
    
    def _execute_actions(self, actions: list[TooltipAction]) -> None:
        """Execute actions returned by state machine"""
        for action in actions:
            if action.name == 'show_tooltip':
                self._show_tooltip_ui(action.data['translation'], action.data['context'])
            elif action.name == 'hide_tooltip':
                self._hide_tooltip_ui()
            elif action.name == 'start_timer':
                self._start_hover_timer(action.data['delay_ms'])
            elif action.name == 'cancel_timer':
                self._cancel_hover_timer()
            elif action.name == 'request_translation':
                self._request_translation(
                    action.data['message'],
                    action.data['severity'],
                    action.data['diagnostic'],
                    action.data['request_id'],
                    action.data['cache_generation']
                )
    
    def _start_hover_timer(self, delay_ms: int) -> None:
        """Start timer for hover delay"""
        self._cancel_hover_timer()
        self._hover_timer = self.text_widget.after(delay_ms, self._on_hover_timer_expired)
    
    def _cancel_hover_timer(self) -> None:
        """Cancel hover delay timer"""
        if self._hover_timer:
            self.text_widget.after_cancel(self._hover_timer)
            self._hover_timer = None
    
    def _on_hover_timer_expired(self) -> None:
        """Called when hover delay expires"""
        actions = self.state_machine.handle_event(TooltipEvent.TIMER_EXPIRED)
        self._execute_actions(actions)
    
    def _request_translation(self, message: str, severity, diagnostic: Diagnostic, request_id: int, cache_generation: int) -> None:
        """Request translation from current AI assistant"""
        import time
        from thonny import get_workbench
        
        # Check if language changed and clear cache if needed
        try:
            current_lang = get_workbench().get_option("ai.language", "uk")
            if self._current_language != current_lang:
                # Language changed, clear cache
                if self._translation_cache:
                    self._translation_cache.clear()
                    self._cache_timestamps.clear()
                    self._pending_requests.clear()
                self._current_language = current_lang
        except Exception:
            pass
        
        # Check cache first (should already be checked by state machine, but double-check)
        if message in self._translation_cache:
            cached_value = self._translation_cache[message]
            # If cached as None, it means previous request failed - don't retry
            if cached_value is None:
                return
            actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_READY, {
                'request_id': request_id,
                'translation': cached_value,
                'cache_generation': cache_generation
            })
            self._execute_actions(actions)
            return
        
        # Dedupe: check if already requesting this message
        if message in self._pending_requests:
            return  # Already requesting, skip duplicate
        
        # Mark as pending
        self._pending_requests.add(message)
        
        try:
            from thonny.plugins.base_assistant import get_ai_assistant
            from thonny.lsp_types import DiagnosticSeverity
            
            # Get current AI assistant
            assistant = get_ai_assistant()
            if not assistant:
                # No assistant, cache failure to prevent retries
                self._translation_cache[message] = None
                self._cache_timestamps[message] = time.time()
                self._pending_requests.discard(message)  # Remove from pending
                actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_ERROR, {
                    'request_id': request_id,
                    'cache_generation': cache_generation
                })
                self._execute_actions(actions)
                return
            
            # Get model name for timing log
            try:
                model = get_workbench().get_option("ai.model", "gpt")
            except:
                model = "gpt"
            
            # Get current editor code
            editor = get_workbench().get_editor_notebook().get_current_editor()
            program_code = editor.get_content() if editor else ""
            
            # Clean diagnostic message (remove [Source] prefix)
            import re
            clean_diagnostic = re.sub(r'^\[.*?\]\s*', '', message)
            
            # Get line number from diagnostic range (1-based for display)
            line_number = diagnostic.range.start.line + 1 if diagnostic and diagnostic.range else None
            
            # Convert severity to human-readable string
            severity = severity or DiagnosticSeverity.Error
            if severity == DiagnosticSeverity.Error:
                severity_str = "error"
            elif severity == DiagnosticSeverity.Warning:
                severity_str = "warning"
            elif severity == DiagnosticSeverity.Information:
                severity_str = "info"
            else:  # Hint
                severity_str = "hint"
            
            def do_translation():
                try:
                    # Use assistant's explain_diagnostic method (fast model - flash/haiku/mini)
                    translation = assistant.explain_diagnostic(program_code, clean_diagnostic, severity_str, line_number)
                    
                    # Cache with timestamp
                    self._translation_cache[message] = translation
                    self._cache_timestamps[message] = time.time()
                    
                    # Notify state machine in main thread
                    def on_success():
                        self._pending_requests.discard(message)  # Remove from pending
                        
                        # Don't show tooltip if menu is open
                        if self._menu_open:
                            return
                        
                        # Verify this is still the current diagnostic (not stale)
                        current_msg = self.state_machine.context.message if self.state_machine.context else None
                        
                        if current_msg != message:
                            # Stale response - cache it but don't show
                            return
                        
                        actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_READY, {
                            'request_id': request_id,
                            'translation': translation,
                            'cache_generation': cache_generation
                        })
                        self._execute_actions(actions)
                    self.text_widget.after(0, on_success)
                    
                except Exception as e:
                    logger.exception(f"[Tooltip] {model} translation failed for request {request_id}")
                    
                    # Cache failure as None to prevent retries
                    self._translation_cache[message] = None
                    self._cache_timestamps[message] = time.time()
                    
                    # Just clean up, don't show anything
                    def on_error():
                        self._pending_requests.discard(message)  # Remove from pending
                        actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_ERROR, {
                            'request_id': request_id,
                            'cache_generation': cache_generation
                        })
                        self._execute_actions(actions)
                    self.text_widget.after(0, on_error)
            
            # Run in background thread
            import threading
            threading.Thread(target=do_translation, daemon=True).start()
            
        except ImportError:
            # Cache failure to prevent retries
            self._translation_cache[message] = None
            self._cache_timestamps[message] = time.time()
            self._pending_requests.discard(message)  # Remove from pending
            actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_ERROR, {
                'request_id': request_id,
                'cache_generation': cache_generation
            })
            self._execute_actions(actions)
        except Exception as e:
            logger.exception("Failed to request translation")
            # Cache failure to prevent retries
            self._translation_cache[message] = None
            self._cache_timestamps[message] = time.time()
            self._pending_requests.discard(message)  # Remove from pending
            actions = self.state_machine.handle_event(TooltipEvent.TRANSLATION_ERROR, {
                'request_id': request_id,
                'cache_generation': cache_generation
            })
            self._execute_actions(actions)
    
    def _show_tooltip_ui(self, translation: str, context) -> None:
        """Create and show tooltip window with translation"""
        if not context or not context.event:
            return
        
        # Don't show tooltip if context menu is open
        if self._menu_open:
            return
        # Create tooltip window
        self.tooltip_window = tw = tk.Toplevel(self.text_widget)
        tw.wm_overrideredirect(True)
        tw.configure(background="#d0d0d0")  # Light gray background for window
        
        # Position near cursor
        event = context.event
        tw.wm_geometry(f"+{event.x_root + 15}+{event.y_root + 15}")
        
        # Main frame with light gray border
        main_frame = tk.Frame(tw, background="#d0d0d0")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Inner frame for white background (creates border effect with thicker padding)
        inner_frame = tk.Frame(main_frame, background="white")
        inner_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # Text widget for markdown rendering
        text_widget = tk.Text(
            inner_frame,
            wrap=tk.WORD,
            width=40,  # ~300px with 14pt font
            height=1,  # Start with 1 line, will be updated
            background="white",
            foreground="black",
            font=("TkDefaultFont", 14),
            padx=10,
            pady=8,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0  # Remove focus border (black border)
        )
        text_widget.pack()
        
        # Render markdown
        from thonny.markdown_utils import render_markdown, MessageType
        render_markdown(text_widget, translation, show_copy_button=False, message_type=MessageType.POPUP)
        
        # Make text widget read-only
        text_widget.config(state=tk.DISABLED)
        
        # Calculate height precisely using display lines (includes wrapping and formatting)
        text_widget.update_idletasks()
        
        # Count actual display lines (Tk's count returns tuple)
        count_result = text_widget.count("1.0", "end", "displaylines")
        display_lines = int(count_result[0]) if count_result else 1
        
        # Add generous buffer for markdown formatting (headers, bold text)
        content_lines_with_buffer = display_lines + 4
        
        # Calculate max height (50% of screen)
        screen_height = tw.winfo_screenheight()
        # Estimate: 25px per line
        max_lines = max(10, int(screen_height * 0.5 / 25))
        
        # Set text widget height in lines
        display_height = max(3, min(content_lines_with_buffer, max_lines))
        text_widget.config(height=display_height)
        
    def _hide_tooltip_ui(self) -> None:
        """Destroy tooltip window"""
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


@dataclass
class DiagnosticInfo:
    diagnostic: Diagnostic
    ls_proxy: LanguageServerProxy


class DiagnosticHighlighter:
    def __init__(self):
        self._diagnostics_per_uri: Dict[str, List[DiagnosticInfo]] = {}
        self._tooltips_per_editor: Dict[str, DiagnosticTooltip] = {}
        self._text_change_timers: Dict[str, any] = {}  # uri -> timer_id for debounce
        self._last_rendered_diagnostics: Dict[str, List[DiagnosticInfo]] = {}  # uri -> last rendered diagnostics
        self._tag_to_diagnostic_per_uri: Dict[str, Dict[str, Diagnostic]] = {}  # uri -> {tag -> diagnostic}
        
        # Connect to existing language servers
        for ls_proxy in get_workbench().get_initialized_ls_proxies():
            self._connect_to_language_server(ls_proxy)
        
        # Listen for new language servers
        get_workbench().bind("LanguageServerInitialized", self._connect_to_language_server, True)
        get_workbench().bind("LanguageServerInvalidated", self._disconnect_from_language_server, True)
        
        # Update highlights when editor switches
        get_workbench().bind("<<NotebookTabChanged>>", self._on_editor_changed, True)
        get_workbench().bind("EditorTextCreated", self._on_editor_created, True)
    
    def _request_diagnostics_for_uri(self, uri: str, ls_proxy: LanguageServerProxy) -> None:
        """Request pull-based diagnostics for a specific URI"""
        from thonny.lsp_types import DocumentDiagnosticParams, TextDocumentIdentifier
        import time
        
        request_time = time.time()
        
        def handle(params: PublishDiagnosticsParams) -> None:
            self._handle_diagnostics(params, ls_proxy)
        
        def handle_diagnostic_response(
            response: LspResponse[Union[DocumentDiagnosticReport, None]], 
            uri=uri, 
            ls=ls_proxy
        ):
            # Ruff returns diagnostics in response, convert to PublishDiagnostics format
            try:
                elapsed = time.time() - request_time
                result = response.get_result_or_raise()
                # Extract diagnostics from result
                diagnostics = []
                if result:
                    if hasattr(result, 'items'):
                        diagnostics = result.items
                    elif hasattr(result, 'relatedDocuments'):
                        # Full document diagnostic report
                        diagnostics = result.items if hasattr(result, 'items') else []
                    elif isinstance(result, list):
                        diagnostics = result
                
                # Convert to publishDiagnostics format
                publish_params = PublishDiagnosticsParams(
                    uri=uri,
                    diagnostics=diagnostics
                )
                # Call in main thread
                get_workbench().after(0, lambda: handle(publish_params))
            except Exception as e:
                logger.debug(f"Pull diagnostics failed for {uri}: {e}")
        
        try:
            params = DocumentDiagnosticParams(
                textDocument=TextDocumentIdentifier(uri=uri)
            )
            ls_proxy.request_text_document_diagnostic(params, handle_diagnostic_response)
        except Exception as e:
            logger.debug(f"Failed to request diagnostics for {uri}: {e}")
    
    def _connect_to_language_server(self, ls_proxy: LanguageServerProxy) -> None:
        
        def handle(params: PublishDiagnosticsParams) -> None:
            self._handle_diagnostics(params, ls_proxy)
        
        ls_proxy.bind_publish_diagnostics(handle)
        
        # Store ls_proxy for later use
        if not hasattr(self, '_ls_proxies'):
            self._ls_proxies = []
        self._ls_proxies.append(ls_proxy)
        
        # For LSP 3.17 servers (like Ruff) that use pull-based diagnostics,
        # request diagnostics for all open Python files immediately and retry 2 times
        # (in case workspace is still indexing)
        def request_diagnostics_for_open_files(retry_count=0, max_retries=2):
            try:
                notebook = get_workbench().get_editor_notebook()
                for editor in notebook.get_all_editors():
                    uri = editor.get_uri()
                    if uri and editor.get_language_id() in ls_proxy.get_supported_language_ids():
                        self._request_diagnostics_for_uri(uri, ls_proxy)
                
                # Retry only 2 times (total 3 requests) to handle slow workspace indexing
                if retry_count < max_retries:
                    delay = 1000  # 1s between retries
                    get_workbench().after(delay, lambda: request_diagnostics_for_open_files(retry_count + 1, max_retries))
            except Exception as e:
                logger.exception("Failed to request diagnostics for open files")
        
        # Request diagnostics immediately and retry 2 times
        get_workbench().after(100, request_diagnostics_for_open_files)
    
    def _disconnect_from_language_server(self, ls_proxy: LanguageServerProxy) -> None:
        logger.info("Disconnecting diagnostic highlighter from ls_proxy %s", ls_proxy)
        
        # Remove from stored proxies
        if hasattr(self, '_ls_proxies') and ls_proxy in self._ls_proxies:
            self._ls_proxies.remove(ls_proxy)
        
        # Clear diagnostics from this server
        uris_to_update = []
        for uri, diagnostics in list(self._diagnostics_per_uri.items()):
            # Remove diagnostics from this proxy
            self._diagnostics_per_uri[uri] = [
                d for d in diagnostics if type(d.ls_proxy) is not type(ls_proxy)
            ]
            uris_to_update.append(uri)
        
        # Update editors
        for uri in uris_to_update:
            self._update_editor_highlights(uri)
    
    def _handle_diagnostics(self, params: PublishDiagnosticsParams, ls_proxy: LanguageServerProxy) -> None:
        uri = params.uri
        
        # Remove old diagnostics from same server
        current_diagnostics = self._diagnostics_per_uri.get(uri, [])
        self._diagnostics_per_uri[uri] = [
            d for d in current_diagnostics if type(d.ls_proxy) is not type(ls_proxy)
        ] + [DiagnosticInfo(diagnostic, ls_proxy) for diagnostic in params.diagnostics]
        
        # Update editor highlights
        self._update_editor_highlights(uri)
    
    def _diagnostics_changed(self, uri: str, new_diagnostics: List[DiagnosticInfo]) -> bool:
        """Check if diagnostics changed compared to last render"""
        if uri not in self._last_rendered_diagnostics:
            return True  # First time rendering
        
        old_diagnostics = self._last_rendered_diagnostics[uri]
        
        # Quick check: different count
        if len(old_diagnostics) != len(new_diagnostics):
            return True
        
        # Create sets of diagnostic keys for comparison (order-independent)
        def diagnostic_key(diag_info):
            d = diag_info.diagnostic
            return (
                d.message,
                d.severity,
                d.source,
                d.range.start.line,
                d.range.start.character,
                d.range.end.line,
                d.range.end.character
            )
        
        old_keys = set(diagnostic_key(d) for d in old_diagnostics)
        new_keys = set(diagnostic_key(d) for d in new_diagnostics)
        
        return old_keys != new_keys  # True if different
    
    def _update_editor_highlights(self, uri: str) -> None:
        """Update diagnostic highlights in the editor for given URI"""
        editor = self._find_editor_by_uri(uri)
        if not editor:
            return
        
        # Get current diagnostics
        diagnostics = self._diagnostics_per_uri.get(uri, [])
        
        # Check if diagnostics actually changed
        if not self._diagnostics_changed(uri, diagnostics):
            return  # No changes, skip re-rendering
        
        # Store for next comparison
        self._last_rendered_diagnostics[uri] = diagnostics.copy()
        
        # Diagnostics changed → clear tooltip cache to avoid showing stale tooltips
        if uri in self._tooltips_per_editor:
            tooltip = self._tooltips_per_editor[uri]
            tooltip._translation_cache.clear()
            tooltip._cache_timestamps.clear()
            tooltip._pending_requests.clear()
            # Notify state machine
            actions = tooltip.state_machine.handle_event(TooltipEvent.TEXT_CHANGED)
            tooltip._execute_actions(actions)
        
        # Clear old translation cache entries (older than 3 minutes)
        if uri in self._tooltips_per_editor:
            import time
            tooltip = self._tooltips_per_editor[uri]
            current_time = time.time()
            cache_timeout = 180  # 3 minutes in seconds
            
            # Remove entries older than 3 minutes
            expired_keys = [
                key for key, timestamp in tooltip._cache_timestamps.items()
                if current_time - timestamp > cache_timeout
            ]
            for key in expired_keys:
                tooltip._translation_cache.pop(key, None)
                tooltip._cache_timestamps.pop(key, None)
        
        text = editor.get_text_widget()
        
        # Clear existing diagnostic tags (base styling tags)
        text.tag_remove("diagnostic_error", "1.0", "end")
        text.tag_remove("diagnostic_warning", "1.0", "end")
        text.tag_remove("diagnostic_info", "1.0", "end")
        text.tag_remove("diagnostic_hint", "1.0", "end")
        
        # Clear all unique diagnostic tags (diag_*)
        for tag in text.tag_names():
            if tag.startswith("diag_"):
                text.tag_delete(tag)
        
        # Clear tag mapping for this URI
        self._tag_to_diagnostic_per_uri[uri] = {}
        
        # Add new tags
        diagnostics = self._diagnostics_per_uri.get(uri, [])
        for diag_info in diagnostics:
            diagnostic = diag_info.diagnostic
            range_obj = diagnostic.range
            
            # Convert LSP positions (0-based) to Tk index (1-based)
            start_line = range_obj.start.line + 1
            start_char = range_obj.start.character
            end_line = range_obj.end.line + 1
            end_char = range_obj.end.character
            
            # Limit highlighting for very large ranges (e.g., unclosed brackets)
            # Pyright sometimes highlights from error position to end of file
            lines_span = end_line - start_line
            
            # Calculate character span (if same line, use actual difference; otherwise it's multi-line)
            if start_line == end_line:
                chars_span = end_char - start_char
            else:
                # Multi-line range - definitely large
                chars_span = 999999
            
            # If range spans multiple lines or is very long (>100 chars), limit to end of current line
            if lines_span > 0 or chars_span > 100:
                end_line = start_line
                # Limit to end of line
                try:
                    line_end_col = len(text.get(f"{start_line}.0", f"{start_line}.end"))
                    end_char = line_end_col
                except:
                    end_char = start_char + 1
            
            start_index = f"{start_line}.{start_char}"
            end_index = f"{end_line}.{end_char}"
            
            # Choose base tag for styling based on severity
            severity = diagnostic.severity or DiagnosticSeverity.Error
            if severity == DiagnosticSeverity.Error:
                base_tag = "diagnostic_error"
            elif severity == DiagnosticSeverity.Warning:
                base_tag = "diagnostic_warning"
            elif severity == DiagnosticSeverity.Information:
                base_tag = "diagnostic_info"
            else:  # Hint
                base_tag = "diagnostic_hint"
            
            # Create unique tag for this specific diagnostic (for event binding)
            unique_tag = f"diag_{id(diagnostic)}"
            
            # Store mapping for priority checking
            self._tag_to_diagnostic_per_uri[uri][unique_tag] = diagnostic
            
            try:
                # Add both tags: base for styling, unique for events
                text.tag_add(base_tag, start_index, end_index)
                text.tag_add(unique_tag, start_index, end_index)
                
                # Choose highlight colors based on severity (hover only, no default background)
                if severity == DiagnosticSeverity.Error:
                    hover_bg = "#ffe6cc"  # Soft orange on hover (friendly, not scary)
                    default_bg = ""  # No background by default
                elif severity == DiagnosticSeverity.Warning:
                    hover_bg = "#f0f0f0"  # Light gray on hover
                    default_bg = ""  # No background by default
                elif severity == DiagnosticSeverity.Information:
                    hover_bg = "#e6f2ff"  # Light blue on hover
                    default_bg = ""  # No background by default
                else:  # Hint
                    hover_bg = "#f5f5f5"  # Very light gray on hover
                    default_bg = ""  # No background by default
                
                # Bind events to unique tag so each diagnostic has its own handler
                # Use simple show() instead of _show_tooltip to respect the specific diagnostic from this tag
                text.tag_bind(unique_tag, "<Enter>", lambda e, t=unique_tag, bg=hover_bg, d=diagnostic, ed=editor: self._on_diagnostic_enter(e, t, bg, d, ed))
                text.tag_bind(unique_tag, "<Motion>", lambda e, t=unique_tag, d=diagnostic, ed=editor: self._on_diagnostic_motion(e, t, d, ed))
                text.tag_bind(unique_tag, "<Leave>", lambda e, t=unique_tag, def_bg=default_bg, ed=editor: self._unhighlight_diagnostic(e, t, def_bg, ed))
            except tk.TclError as e:
                logger.warning(f"Could not add diagnostic tag: {e}")
        
        # After adding all tags, raise them in priority order (least to most important)
        # This ensures that more important diagnostics are "on top" and receive events first
        # We raise tags from lowest to highest priority, so the last raised will be on top
        # Priority order (raise from lowest to highest):
        # 8. Pyright hint (lowest priority, raised first)
        # 7. Ruff hint
        # 6. Pyright info
        # 5. Ruff info
        # 4. Pyright warning
        # 3. Ruff warning
        # 2. Pyright error
        # 1. Ruff error (highest priority, raised last, will be on top)
        
        priority_order = [
            (DiagnosticSeverity.Hint, True),       # 8. Pyright hint (raised first)
            (DiagnosticSeverity.Hint, False),      # 7. Ruff hint
            (DiagnosticSeverity.Information, True),  # 6. Pyright info
            (DiagnosticSeverity.Information, False), # 5. Ruff info
            (DiagnosticSeverity.Warning, True),    # 4. Pyright warning
            (DiagnosticSeverity.Warning, False),   # 3. Ruff warning
            (DiagnosticSeverity.Error, True),      # 2. Pyright error
            (DiagnosticSeverity.Error, False),     # 1. Ruff error (raised last, on top)
        ]
        
        # Raise tags in priority order (least to most important)
        for target_severity, is_pyright in priority_order:
            for diag_info in diagnostics:
                diagnostic = diag_info.diagnostic
                severity = diagnostic.severity or DiagnosticSeverity.Error
                source = (diagnostic.source or "").lower()
                is_diag_pyright = "pyright" in source or "basedpyright" in source
                
                if severity == target_severity and is_diag_pyright == is_pyright:
                    unique_tag = f"diag_{id(diagnostic)}"
                    try:
                        text.tag_raise(unique_tag)
                    except tk.TclError:
                        pass
    
    def _find_editor_by_uri(self, uri: str) -> Optional[Editor]:
        """Find editor by URI"""
        notebook = get_workbench().get_editor_notebook()
        for editor in notebook.get_all_editors():
            if editor.get_uri() == uri:
                return editor
        return None
    
    def _on_editor_changed(self, event=None) -> None:
        """Update highlights when switching editors"""
        editor = get_workbench().get_editor_notebook().get_current_editor()
        if editor:
            uri = editor.get_uri()
            self._update_editor_highlights(uri)
    
    def _on_editor_created(self, event=None) -> None:
        """Update highlights when editor is created"""
        if hasattr(event, 'text_widget'):
            # Configure tags on new editor
            self._configure_diagnostic_tags(event.text_widget)
            
            # Request diagnostics for this editor from all language servers
            if hasattr(self, '_ls_proxies'):
                editor = get_workbench().get_editor_notebook().get_current_editor()
                if editor:
                    uri = editor.get_uri()
                    if uri:
                        for ls_proxy in self._ls_proxies:
                            if editor.get_language_id() in ls_proxy.get_supported_language_ids():
                                # Request diagnostics with a small delay to let editor fully initialize
                                get_workbench().after(50, lambda u=uri, ls=ls_proxy: self._request_diagnostics_for_uri(u, ls))
    
    def _configure_diagnostic_tags(self, text: tk.Text) -> None:
        """Configure visual style for diagnostic tags"""
        # Hint: light gray underline, no background - lowest priority
        text.tag_configure("diagnostic_hint", underline=True, underlinefg="#cccccc")
        text.tag_raise("diagnostic_hint")
        
        # Info: blue underline, no background
        text.tag_configure("diagnostic_info", underline=True, underlinefg="#6699cc")
        text.tag_raise("diagnostic_info")
        
        # Warning: light gray underline, no background (less aggressive than orange)
        text.tag_configure("diagnostic_warning", underline=True, underlinefg="#bbbbbb")
        text.tag_raise("diagnostic_warning")
        
        # Error: orange underline, no background (less scary than red) - highest priority
        text.tag_configure("diagnostic_error", underline=True, underlinefg="#ff9933")
        text.tag_raise("diagnostic_error")
    
    def _highlight_diagnostic(self, event, tag: str, background: str) -> None:
        """Add background highlight when mouse enters diagnostic"""
        editor = get_workbench().get_editor_notebook().get_current_editor()
        if editor:
            text = editor.get_text_widget()
            text.tag_configure(tag, background=background)
    
    def _unhighlight_diagnostic(self, event, tag: str, default_bg: str, editor: Editor) -> None:
        """Restore default background when mouse leaves diagnostic"""
        text = editor.get_text_widget()
        if default_bg:
            text.tag_configure(tag, background=default_bg)
        else:
            # Remove background entirely by setting to empty string
            text.tag_configure(tag, background="")
        self._hide_tooltip(event, editor)
    
    def _get_tooltip_for_editor(self, editor: Editor) -> DiagnosticTooltip:
        """Get or create tooltip for editor"""
        uri = editor.get_uri()
        if uri not in self._tooltips_per_editor:
            self._tooltips_per_editor[uri] = DiagnosticTooltip(editor.get_text_widget())
        return self._tooltips_per_editor[uri]
    
    def _on_diagnostic_enter(self, event, unique_tag: str, bg: str, diagnostic: Diagnostic, editor: Editor) -> None:
        """Handle mouse entering diagnostic - only process if this is the topmost diagnostic"""
        text = editor.get_text_widget()
        
        # Get all tags at mouse position
        try:
            tags_at_pos = text.tag_names(f"@{event.x},{event.y}")
        except:
            return
        
        # Find all diagnostic unique tags at this position
        diag_tags = [t for t in tags_at_pos if t.startswith("diag_")]
        
        # Find the highest priority diagnostic among all overlapping
        from thonny.lsp_types import DiagnosticSeverity
        uri = editor.get_uri()
        tag_map = self._tag_to_diagnostic_per_uri.get(uri, {})
        
        # Build list of (tag, diagnostic, priority_score) for all overlapping
        overlapping_diagnostics = []
        for tag in diag_tags:
            diag = tag_map.get(tag)
            if diag:
                sev = diag.severity or DiagnosticSeverity.Error
                source = (diag.source or "").lower()
                
                # Calculate priority score: Error(1) > Warning(2) > Info(3) > Hint(4)
                # Within same severity: Ruff(0) > Pyright(1)
                severity_score = {
                    DiagnosticSeverity.Error: 1,
                    DiagnosticSeverity.Warning: 2,
                    DiagnosticSeverity.Information: 3,
                    DiagnosticSeverity.Hint: 4
                }.get(sev, 5)
                
                source_score = 0 if "ruff" in source else 1
                
                # Lower score = higher priority
                priority_score = (severity_score, source_score)
                overlapping_diagnostics.append((tag, diag, priority_score))
        
        # Sort by priority (lowest score first = highest priority)
        overlapping_diagnostics.sort(key=lambda x: x[2])
        
        # Check if our diagnostic is the highest priority
        if overlapping_diagnostics and overlapping_diagnostics[0][0] != unique_tag:
            return  # Ignore, not highest priority
        
        # Our diagnostic is highest priority - process normally
        self._highlight_diagnostic(event, unique_tag, bg)
        self._get_tooltip_for_editor(editor).show(event, diagnostic)
    
    def _on_diagnostic_motion(self, event, unique_tag: str, diagnostic: Diagnostic, editor: Editor) -> None:
        """Handle mouse motion inside diagnostic - only process if this is the highest priority diagnostic"""
        text = editor.get_text_widget()
        
        # Get all tags at mouse position
        try:
            tags_at_pos = text.tag_names(f"@{event.x},{event.y}")
        except:
            return
        
        # Find all diagnostic unique tags at this position
        diag_tags = [t for t in tags_at_pos if t.startswith("diag_")]
        
        # Check if our diagnostic is the highest priority (same logic as _on_diagnostic_enter)
        from thonny.lsp_types import DiagnosticSeverity
        uri = editor.get_uri()
        tag_map = self._tag_to_diagnostic_per_uri.get(uri, {})
        
        # Find highest priority among overlapping
        highest_priority_score = None
        highest_tag = None
        
        for tag in diag_tags:
            diag = tag_map.get(tag)
            if diag:
                sev = diag.severity or DiagnosticSeverity.Error
                source = (diag.source or "").lower()
                
                severity_score = {
                    DiagnosticSeverity.Error: 1,
                    DiagnosticSeverity.Warning: 2,
                    DiagnosticSeverity.Information: 3,
                    DiagnosticSeverity.Hint: 4
                }.get(sev, 5)
                
                source_score = 0 if "ruff" in source else 1
                priority_score = (severity_score, source_score)
                
                if highest_priority_score is None or priority_score < highest_priority_score:
                    highest_priority_score = priority_score
                    highest_tag = tag
        
        # If our tag is not the highest priority - ignore
        if highest_tag != unique_tag:
            return
        
        # Our tag is highest priority - process normally
        self._on_tooltip_motion(event, diagnostic, editor)
    
    def _on_tooltip_motion(self, event, diagnostic: Diagnostic, editor: Editor) -> None:
        """Handle mouse motion inside diagnostic - restart hover timer or switch diagnostic"""
        tooltip = self._get_tooltip_for_editor(editor)
        
        # Build message to check if diagnostic changed
        message = diagnostic.message
        line_number = diagnostic.range.start.line + 1 if diagnostic.range else 0
        if diagnostic.source:
            full_message = f"[{diagnostic.source}] L{line_number}: {message}"
        else:
            full_message = f"L{line_number}: {message}"
        
        # Check if this is a different diagnostic than current
        current_msg = tooltip.state_machine.context.message if tooltip.state_machine.context else None
        
        if current_msg != full_message:
            # Different diagnostic - treat as new MOUSE_ENTER
            tooltip.show(event, diagnostic)
        else:
            # Same diagnostic - just handle motion (restart timer if hovering)
            actions = tooltip.state_machine.handle_event(TooltipEvent.MOUSE_MOTION)
            tooltip._execute_actions(actions)
    
    def _hide_tooltip(self, event, editor: Editor) -> None:
        """Hide tooltip"""
        tooltip = self._get_tooltip_for_editor(editor)
        tooltip.hide()


def load_plugin() -> None:
    """Load the diagnostic highlighter plugin"""
    # Create singleton instance
    if not hasattr(get_workbench(), '_diagnostic_highlighter'):
        get_workbench()._diagnostic_highlighter = DiagnosticHighlighter()

