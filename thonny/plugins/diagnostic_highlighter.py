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
        self._request_id = 0  # Track current request
        self._debounce_timer = None  # Debounce timer for Gemini requests
        self._current_request_message = None  # Message currently being requested (to avoid duplicates)
        self._current_shown_message = None  # Message currently shown in tooltip
        
    def show(self, event, diagnostic: Diagnostic) -> None:
        """Show tooltip with diagnostic message"""
        self.current_diagnostic = diagnostic
        message = diagnostic.message
        if diagnostic.source:
            full_message = f"[{diagnostic.source}] {message}"
        else:
            full_message = message
        
        # OPTIMIZATION 1: If tooltip already shows this exact message, do nothing
        if self.tooltip_window and self._current_shown_message == full_message:
            return
        
        # Hide old tooltip if showing different message
        if self.tooltip_window:
            self.hide()
        
        # Cancel previous debounce timer if any
        if self._debounce_timer:
            self.text_widget.after_cancel(self._debounce_timer)
            self._debounce_timer = None
        
        # Increment request ID to invalidate old requests
        self._request_id += 1
        current_request_id = self._request_id
        
        # Store event, message and severity for later
        self._pending_event = event
        self._pending_message = full_message
        self._pending_severity = diagnostic.severity
        
        # OPTIMIZATION 2: If in cache, show immediately without debounce
        if full_message in self._translation_cache:
            self._current_shown_message = full_message
            self._show_translation(self._translation_cache[full_message], current_request_id)
            return
        
        # OPTIMIZATION 3: If request already in progress for this message, don't start new one
        if self._current_request_message == full_message:
            return
        
        # Debounce: start translation only after 300ms of no mouse movement
        def delayed_translation():
            self._debounce_timer = None
            self._current_request_message = full_message  # Mark as in progress
            self._request_translation(full_message, diagnostic.severity, current_request_id)
        
        self._debounce_timer = self.text_widget.after(300, delayed_translation)
    
    def _request_translation(self, message: str, severity, request_id: int) -> None:
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
                    translation = assistant.explain_diagnostic(program_code, clean_diagnostic, severity_str)
                    
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
        # Check if this request is still current
        if request_id != self._request_id:
            return
        
        if not hasattr(self, '_pending_event') or not self._pending_event:
            return
        
        # Remember what message is shown
        self._current_shown_message = self._pending_message
        
        # Create tooltip window only when translation is ready
        self.tooltip_window = tw = tk.Toplevel(self.text_widget)
        tw.wm_overrideredirect(True)
        
        # Position near cursor
        event = self._pending_event
        tw.wm_geometry(f"+{event.x_root + 15}+{event.y_root + 15}")
        
        # Main frame with border
        main_frame = tk.Frame(tw, background="white", relief=tk.SOLID, borderwidth=2)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Text widget for markdown rendering
        from tkinter import scrolledtext
        text_widget = tk.Text(
            main_frame,
            wrap=tk.WORD,
            width=60,
            height=5,
            background="white",
            foreground="black",
            font=("TkDefaultFont", 11),
            padx=10,
            pady=8,
            relief=tk.FLAT,
            borderwidth=0
        )
        text_widget.pack(fill=tk.BOTH, expand=True)
        
        # Render markdown
        from thonny.markdown_utils import render_markdown, MessageType
        render_markdown(text_widget, translation, show_copy_button=False, message_type=MessageType.BOT)
        
        # Make text widget read-only
        text_widget.config(state=tk.DISABLED)
        
        # Clear pending
        self._pending_event = None
        self._pending_message = None
    
    def hide(self) -> None:
        """Hide tooltip"""
        # Cancel debounce timer if any
        if self._debounce_timer:
            self.text_widget.after_cancel(self._debounce_timer)
            self._debounce_timer = None
        
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
        
        def handle(params: PublishDiagnosticsParams) -> None:
            self._handle_diagnostics(params, ls_proxy)
        
        def handle_diagnostic_response(
            response: LspResponse[Union[DocumentDiagnosticReport, None]], 
            uri=uri, 
            ls=ls_proxy
        ):
            # Ruff returns diagnostics in response, convert to PublishDiagnostics format
            try:
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
        logger.info("Connecting diagnostic highlighter to ls_proxy %s", ls_proxy)
        
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
                text.tag_bind(unique_tag, "<Enter>", lambda e, t=unique_tag, bg=hover_bg: self._highlight_diagnostic(e, t, bg))
                text.tag_bind(unique_tag, "<Motion>", lambda e, d=diagnostic, ed=editor: self._show_tooltip(e, d, ed))
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
            self._update_editor_highlights(editor.get_uri())
    
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
        # Error: red underline (keeps text color)
        text.tag_configure("diagnostic_error", underline=True, underlinefg="red")
        text.tag_raise("diagnostic_error")
        
        # Warning: orange underline (keeps text color)
        text.tag_configure("diagnostic_warning", underline=True, underlinefg="orange")
        text.tag_raise("diagnostic_warning")
        
        # Info: blue underline (keeps text color)
        text.tag_configure("diagnostic_info", underline=True, underlinefg="blue")
        text.tag_raise("diagnostic_info")
        
        # Hint: gray underline (keeps text color)
        text.tag_configure("diagnostic_hint", underline=True, underlinefg="gray")
        text.tag_raise("diagnostic_hint")
    
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
    
    def _show_tooltip(self, event, diagnostic: Diagnostic, editor: Editor) -> None:
        """Show tooltip with diagnostic message and AI explanation"""
        tooltip = self._get_tooltip_for_editor(editor)
        tooltip.show(event, diagnostic)
    
    def _hide_tooltip(self, event, editor: Editor) -> None:
        """Hide tooltip"""
        tooltip = self._get_tooltip_for_editor(editor)
        tooltip.hide()


def load_plugin() -> None:
    """Load the diagnostic highlighter plugin"""
    # Create singleton instance
    if not hasattr(get_workbench(), '_diagnostic_highlighter'):
        get_workbench()._diagnostic_highlighter = DiagnosticHighlighter()

