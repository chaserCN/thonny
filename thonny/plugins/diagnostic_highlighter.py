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

logger = getLogger(__name__)


class DiagnosticTooltip:
    """Tooltip that shows diagnostic message with optional Gemini translation"""
    
    def __init__(self, text_widget: tk.Text):
        self.text_widget = text_widget
        self.tooltip_window = None
        self.current_diagnostic = None
        self._translation_cache = {}
        self._cache_timestamps = {}  # Track when each cache entry was created
        self._current_request_message = None  # Message currently being requested (to avoid duplicates)
        self._current_shown_message = None  # Message currently shown in tooltip
        self._pending_message = None  # Pending message for tooltip
        self._pending_event = None  # Pending event for tooltip
        self._pending_severity = None  # Pending severity for tooltip
        self._current_request_id = None  # Current request ID (hash of message)
        self._is_showing = False  # Flag: tooltip in process of showing (prevents overlapping shows)
        
        # Clear cache when text is modified
        self.text_widget.bind("<<Modified>>", self._on_text_modified, add=True)
    
    def _on_text_modified(self, event=None) -> None:
        """Clear translation cache when code is modified"""
        if self._translation_cache:
            self._translation_cache.clear()
            self._cache_timestamps.clear()
        
    def show(self, event, diagnostic: Diagnostic) -> None:
        """Show tooltip with diagnostic message"""
        # PROTECTION: Multiple tags can trigger <Enter> event for the same position
        # Block duplicate calls while tooltip is being shown
        if self._is_showing:
            logger.info("[Tooltip] Already showing, ignoring")
            return
        
        logger.info("[Tooltip] Starting to show tooltip")
        self._is_showing = True  # Lock: prevents duplicate calls during show process
        
        self.current_diagnostic = diagnostic
        message = diagnostic.message
        if diagnostic.source:
            full_message = f"[{diagnostic.source}] {message}"
        else:
            full_message = message
        
        # OPTIMIZATION 1: If tooltip already shows this exact message, do nothing
        if self.tooltip_window and self._current_shown_message == full_message:
            logger.info("[Tooltip] Already showing same message, keeping tooltip")
            self._is_showing = False  # Unlock: same message, no action needed
            return
        
        # Hide old tooltip if showing different message
        if self.tooltip_window:
            self.hide()
            # Re-lock: hide() unlocks, but we're continuing to show new tooltip
            self._is_showing = True
        
        # Use hash of message as request ID (stable, tied to message content)
        current_request_id = hash(full_message)
        self._current_request_id = current_request_id
        
        # IMPORTANT: Store event, message and severity BEFORE any async operations
        self._pending_event = event
        self._pending_message = full_message
        self._pending_severity = diagnostic.severity
        
        # OPTIMIZATION 2: If in cache, show immediately (no debounce needed)
        if full_message in self._translation_cache:
            self._current_shown_message = full_message
            self._show_translation(self._translation_cache[full_message], current_request_id)
            return
        
        # NOT in cache: request AI immediately (no debounce) since response will take time anyway
        # OPTIMIZATION 3: If request already in progress for this message, don't start new one
        if self._current_request_message == full_message:
            logger.info("[Tooltip] Request already in progress, skipping")
            self._is_showing = False  # Unlock: AI request ongoing, will complete async
            return
        
        logger.info(f"[Tooltip] Starting NEW AI request for: {full_message[:60]}...")
        
        # Start AI translation immediately for uncached messages
        self._current_request_message = full_message  # Mark as in progress
        self._request_translation(full_message, diagnostic.severity, diagnostic, current_request_id)
    
    def _request_translation(self, message: str, severity, diagnostic: Diagnostic, request_id: int) -> None:
        """Request translation from current AI assistant"""
        # Check cache first
        if message in self._translation_cache:
            self._show_translation(self._translation_cache[message], request_id)
            return
        
        try:
            import time
            from thonny.plugins.base_assistant import get_ai_assistant
            from thonny.lsp_types import DiagnosticSeverity
            
            # Get current AI assistant
            assistant = get_ai_assistant()
            if not assistant:
                self._show_translation(message, request_id)  # Show original diagnostic if no assistant
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
                    start_time = time.time()
                    
                    # Use assistant's explain_diagnostic method (fast model - flash/haiku/mini)
                    translation = assistant.explain_diagnostic(program_code, clean_diagnostic, severity_str, line_number)
                    
                    elapsed = time.time() - start_time
                    logger.info(f"[Tooltip] {model} responded in {elapsed:.2f}s")
                    
                    # Cache with timestamp
                    self._translation_cache[message] = translation
                    self._cache_timestamps[message] = time.time()
                    
                    # Update UI in main thread
                    def show_and_clear():
                        self._show_translation(translation, request_id)
                        if self._current_request_message == message:
                            self._current_request_message = None
                    self.text_widget.after(0, show_and_clear)
                    
                except Exception as e:
                    elapsed = time.time() - start_time if 'start_time' in locals() else 0
                    logger.exception(f"[Tooltip] ❌ {model} translation failed after {elapsed:.2f}s for request {request_id}")
                    
                    # Fallback to original message
                    def show_error_and_clear():
                        self._show_translation(f"ℹ️ {clean_diagnostic}", request_id)
                        if self._current_request_message == message:
                            self._current_request_message = None
                    self.text_widget.after(0, show_error_and_clear)
            
            # Run in background thread
            import threading
            threading.Thread(target=do_translation, daemon=True).start()
            
        except ImportError:
            self._show_translation("⚠️ AI assistant not available", request_id)
        except Exception as e:
            logger.exception("Failed to request translation")
            self._show_translation(message, request_id)  # Show original diagnostic message on error
    
    def _show_translation(self, translation: str, request_id: int) -> None:
        """Show tooltip with translation"""
        # Check if this request is still current (compare with current request ID)
        if request_id != self._current_request_id:
            self._is_showing = False  # Unlock: stale request, user moved to another diagnostic
            return
        
        if not hasattr(self, '_pending_event') or not self._pending_event:
            self._is_showing = False  # Unlock: no event data, cannot show tooltip
            return
        
        # Remember what message is shown
        self._current_shown_message = self._pending_message
        
        # Create tooltip window only when translation is ready
        self.tooltip_window = tw = tk.Toplevel(self.text_widget)
        tw.wm_overrideredirect(True)
        tw.configure(background="#d0d0d0")  # Light gray background for window
        
        # Position near cursor
        event = self._pending_event
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
        
        # Clear pending
        self._pending_event = None
        self._pending_message = None
        
        # Unlock: tooltip successfully created and displayed
        self._is_showing = False
    
    def hide(self) -> None:
        """Hide tooltip"""
        # Invalidate any pending AI requests by clearing current request ID
        self._current_request_id = None
        
        # Clear pending data
        self._pending_event = None
        self._pending_message = None
        
        # Unlock: tooltip hidden, ready for new shows
        self._is_showing = False
        
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
            self.current_diagnostic = None
            self._current_shown_message = None  # Clear shown message tracking


@dataclass
class DiagnosticInfo:
    diagnostic: Diagnostic
    ls_proxy: LanguageServerProxy


class DiagnosticHighlighter:
    def __init__(self):
        self._diagnostics_per_uri: Dict[str, List[DiagnosticInfo]] = {}
        self._tooltips_per_editor: Dict[str, DiagnosticTooltip] = {}
        self._tooltip_debounce_timer = None  # Debounce timer to prevent tooltips right after autocomplete
        self._tooltip_enabled = True  # Flag to temporarily disable tooltips
        
        # Connect to existing language servers
        for ls_proxy in get_workbench().get_initialized_ls_proxies():
            self._connect_to_language_server(ls_proxy)
        
        # Listen for new language servers
        get_workbench().bind("LanguageServerInitialized", self._connect_to_language_server, True)
        get_workbench().bind("LanguageServerInvalidated", self._disconnect_from_language_server, True)
        
        # Update highlights when editor switches
        get_workbench().bind("<<NotebookTabChanged>>", self._on_editor_changed, True)
        get_workbench().bind("EditorTextCreated", self._on_editor_created, True)
        
        # Temporarily disable tooltips when autocomplete is used
        get_workbench().bind("AutocompletionInserted", self._on_autocomplete_inserted, True)
    
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
        # request diagnostics for all open Python files immediately and retry
        # if workspace is not ready yet (Ruff might take time to index large directories)
        def request_diagnostics_for_open_files(retry_count=0, max_retries=5):
            try:
                notebook = get_workbench().get_editor_notebook()
                requested_any = False
                for editor in notebook.get_all_editors():
                    uri = editor.get_uri()
                    if uri and editor.get_language_id() in ls_proxy.get_supported_language_ids():
                        self._request_diagnostics_for_uri(uri, ls_proxy)
                        requested_any = True
                
                # If we requested diagnostics but this is not the last retry,
                # schedule another request in case workspace wasn't ready
                if requested_any and retry_count < max_retries:
                    delay = 2000 if retry_count == 0 else 5000  # 2s first retry, then 5s
                    get_workbench().after(delay, lambda: request_diagnostics_for_open_files(retry_count + 1, max_retries))
            except Exception as e:
                logger.exception("Failed to request diagnostics for open files")
        
        # Request diagnostics immediately (no delay) and retry a few times
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
    
    def _update_editor_highlights(self, uri: str) -> None:
        """Update diagnostic highlights in the editor for given URI"""
        editor = self._find_editor_by_uri(uri)
        if not editor:
            return
        
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
            
            try:
                # Add both tags: base for styling, unique for events
                text.tag_add(base_tag, start_index, end_index)
                text.tag_add(unique_tag, start_index, end_index)
                
                # Choose highlight color based on severity
                if severity == DiagnosticSeverity.Error:
                    hover_bg = "#ffe0e0"  # Light red
                elif severity == DiagnosticSeverity.Warning:
                    hover_bg = "#ffe6cc"  # Light orange
                elif severity == DiagnosticSeverity.Information:
                    hover_bg = "#e6f2ff"  # Light blue
                else:  # Hint
                    hover_bg = "#f0f0f0"  # Light gray
                
                # Bind events to unique tag so each diagnostic has its own handler
                # Use <Enter> instead of <Motion> to avoid hundreds of calls when mouse moves
                text.tag_bind(unique_tag, "<Enter>", lambda e, t=unique_tag, bg=hover_bg, d=diagnostic, ed=editor: (self._highlight_diagnostic(e, t, bg), self._show_tooltip(e, d, ed)))
                text.tag_bind(unique_tag, "<Leave>", lambda e, t=unique_tag, ed=editor: self._unhighlight_diagnostic(e, t, ed))
            except tk.TclError as e:
                logger.warning(f"Could not add diagnostic tag: {e}")
    
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
        # Hint: gray underline (keeps text color) - lowest priority
        text.tag_configure("diagnostic_hint", underline=True, underlinefg="gray")
        text.tag_raise("diagnostic_hint")
        
        # Info: blue underline (keeps text color)
        text.tag_configure("diagnostic_info", underline=True, underlinefg="blue")
        text.tag_raise("diagnostic_info")
        
        # Warning: orange underline (keeps text color)
        text.tag_configure("diagnostic_warning", underline=True, underlinefg="orange")
        text.tag_raise("diagnostic_warning")
        
        # Error: red underline (keeps text color) - highest priority
        text.tag_configure("diagnostic_error", underline=True, underlinefg="red")
        text.tag_raise("diagnostic_error")
    
    def _highlight_diagnostic(self, event, tag: str, background: str) -> None:
        """Add background highlight when mouse enters diagnostic"""
        editor = get_workbench().get_editor_notebook().get_current_editor()
        if editor:
            text = editor.get_text_widget()
            text.tag_configure(tag, background=background)
    
    def _unhighlight_diagnostic(self, event, tag: str, editor: Editor) -> None:
        """Remove background highlight when mouse leaves diagnostic"""
        text = editor.get_text_widget()
        text.tag_configure(tag, background="")
        self._hide_tooltip(event, editor)
    
    def _get_tooltip_for_editor(self, editor: Editor) -> DiagnosticTooltip:
        """Get or create tooltip for editor"""
        uri = editor.get_uri()
        if uri not in self._tooltips_per_editor:
            self._tooltips_per_editor[uri] = DiagnosticTooltip(editor.get_text_widget())
        return self._tooltips_per_editor[uri]
    
    def _on_autocomplete_inserted(self, event=None) -> None:
        """Temporarily disable tooltips after autocomplete to prevent immediate tooltip on mouse"""
        self._tooltip_enabled = False
        
        # Cancel previous debounce timer if any
        if self._tooltip_debounce_timer:
            get_workbench().after_cancel(self._tooltip_debounce_timer)
        
        # Re-enable tooltips after 500ms
        def enable_tooltips():
            self._tooltip_enabled = True
            self._tooltip_debounce_timer = None
        
        self._tooltip_debounce_timer = get_workbench().after(500, enable_tooltips)
    
    def _show_tooltip(self, event, diagnostic: Diagnostic, editor: Editor) -> None:
        """Show tooltip with diagnostic message and AI explanation"""
        logger.info(f"[Tooltip] _show_tooltip called: enabled={self._tooltip_enabled}, source={diagnostic.source}, message={diagnostic.message[:50]}")
        
        # Don't show tooltip if temporarily disabled (e.g. right after autocomplete)
        if not self._tooltip_enabled:
            logger.info("[Tooltip] Tooltips disabled, skipping")
            return
        
        # Get cursor position from event
        text = editor.get_text_widget()
        try:
            cursor_index = text.index(f"@{event.x},{event.y}")
            cursor_line, cursor_char = map(int, cursor_index.split('.'))
            cursor_pos = (cursor_line - 1, cursor_char)  # Convert to 0-based LSP position
        except Exception as e:
            # Fallback if cursor position can't be determined
            tooltip = self._get_tooltip_for_editor(editor)
            tooltip.show(event, diagnostic)
            return
        
        # Find all diagnostics at this cursor position
        uri = editor.get_uri()
        if not uri:
            tooltip = self._get_tooltip_for_editor(editor)
            tooltip.show(event, diagnostic)
            return
        
        diagnostics_at_cursor = []
        for diag_info in self._diagnostics_per_uri.get(uri, []):
            d = diag_info.diagnostic
            d_start = (d.range.start.line, d.range.start.character)
            d_end = (d.range.end.line, d.range.end.character)
            
            # Check if cursor is inside this diagnostic's range
            if d_start <= cursor_pos < d_end:
                diagnostics_at_cursor.append(d)
        
        if not diagnostics_at_cursor:
            # No diagnostics found, show the one passed
            tooltip = self._get_tooltip_for_editor(editor)
            tooltip.show(event, diagnostic)
            return
        
        # Select diagnostic with highest priority
        # Priority (lower number = higher priority):
        # 1. Pyright error (highest)
        # 2. Ruff error
        # 3. Pyright warning
        # 4. Ruff warning
        # 5. Pyright info
        # 6. Ruff info
        # 7. Pyright hint (lowest)
        # 8. Ruff hint
        def combined_priority(d: Diagnostic) -> int:
            severity = d.severity or DiagnosticSeverity.Error
            source = (d.source or "").lower()
            is_pyright = "pyright" in source or "basedpyright" in source
            
            # Base priority by severity
            if severity == DiagnosticSeverity.Error:
                base = 1 if is_pyright else 2
            elif severity == DiagnosticSeverity.Warning:
                base = 3 if is_pyright else 4
            elif severity == DiagnosticSeverity.Information:
                base = 5 if is_pyright else 6
            else:  # Hint
                base = 7 if is_pyright else 8
            
            return base
        
        best_diagnostic = min(diagnostics_at_cursor, key=combined_priority)
        priority = combined_priority(best_diagnostic)
        logger.info(f"[Tooltip] Best diagnostic selected: priority={priority}, severity={best_diagnostic.severity}, source={best_diagnostic.source}")
        
        # If the best diagnostic is the same message as currently being shown, avoid duplicate processing
        # (multiple tags can trigger for the same diagnostic)
        tooltip = self._get_tooltip_for_editor(editor)
        best_message = f"[{best_diagnostic.source}] {best_diagnostic.message}" if best_diagnostic.source else best_diagnostic.message
        if tooltip._is_showing and tooltip._pending_message == best_message:
            logger.info(f"[Tooltip] Already processing same message, skipping")
            return  # Already showing this message
        
        logger.info(f"[Tooltip] Calling tooltip.show() with best_diagnostic")
        tooltip.show(event, best_diagnostic)
    
    def _hide_tooltip(self, event, editor: Editor) -> None:
        """Hide tooltip"""
        tooltip = self._get_tooltip_for_editor(editor)
        tooltip.hide()


def load_plugin() -> None:
    """Load the diagnostic highlighter plugin"""
    # Create singleton instance
    if not hasattr(get_workbench(), '_diagnostic_highlighter'):
        get_workbench()._diagnostic_highlighter = DiagnosticHighlighter()

