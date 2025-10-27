"""
State machine for managing diagnostic tooltip lifecycle.

States:
    IDLE: No tooltip activity
    HOVERING: Mouse over diagnostic, waiting for delay
    REQUESTING: AI translation in progress
    SHOWING: Tooltip is visible

Events:
    MOUSE_ENTER: Mouse entered diagnostic area
    MOUSE_LEAVE: Mouse left diagnostic area
    TIMER_EXPIRED: Hover delay completed
    TRANSLATION_READY: AI translation received
    TRANSLATION_ERROR: AI translation failed
    TEXT_CHANGED: Editor text was modified
"""

from enum import Enum, auto
from typing import Optional, Callable, Any
from dataclasses import dataclass
from logging import getLogger

logger = getLogger(__name__)


class TooltipState(Enum):
    """States for tooltip display lifecycle"""
    IDLE = auto()
    HOVERING = auto()  # Mouse inside, translation cached, waiting for 300ms timer
    WAITING_FOR_AI = auto()  # Mouse inside, AI request in progress (no timer)
    SHOWING = auto()  # Tooltip visible


class TooltipEvent(Enum):
    """Events that trigger state transitions"""
    MOUSE_ENTER = auto()
    MOUSE_MOTION = auto()  # Mouse moved inside diagnostic area
    MOUSE_LEAVE = auto()
    TIMER_EXPIRED = auto()  # 300ms hover delay completed
    TRANSLATION_READY = auto()
    TRANSLATION_ERROR = auto()
    TEXT_CHANGED = auto()


@dataclass
class TooltipAction:
    """Action to be executed as result of state transition"""
    name: str
    data: Optional[dict] = None


@dataclass
class TooltipContext:
    """Context data for current tooltip"""
    message: str
    event: Any  # tk.Event
    severity: Any  # DiagnosticSeverity
    diagnostic: Any  # Diagnostic
    request_id: int
    cache_generation: int  # To detect if cache was cleared during request


class TooltipStateMachine:
    """
    State machine for managing tooltip display lifecycle.
    
    Separates state management from UI logic, making the code easier to understand
    and maintain. The machine receives events and returns actions to execute.
    """
    
    def __init__(self, hover_delay_ms: int = 300):
        self.state = TooltipState.IDLE
        self.hover_delay_ms = hover_delay_ms
        self.context: Optional[TooltipContext] = None
        # External cache reference (managed by DiagnosticTooltip)
        self._cache_ref: Optional[dict] = None
        # Cache generation - incremented when cache is cleared
        self._cache_generation = 0
        
    def handle_event(self, event: TooltipEvent, data: Optional[dict] = None) -> list[TooltipAction]:
        """
        Handle an event and return list of actions to execute.
        
        Args:
            event: Event that occurred
            data: Optional event data (message, diagnostic, translation, etc.)
            
        Returns:
            List of actions to execute
        """
        old_state = self.state
        actions = []
        
        if event == TooltipEvent.MOUSE_ENTER:
            actions = self._handle_mouse_enter(data)
        elif event == TooltipEvent.MOUSE_MOTION:
            actions = self._handle_mouse_motion()
        elif event == TooltipEvent.MOUSE_LEAVE:
            actions = self._handle_mouse_leave()
        elif event == TooltipEvent.TIMER_EXPIRED:
            actions = self._handle_timer_expired()
        elif event == TooltipEvent.TRANSLATION_READY:
            actions = self._handle_translation_ready(data)
        elif event == TooltipEvent.TRANSLATION_ERROR:
            actions = self._handle_translation_error(data)
        elif event == TooltipEvent.TEXT_CHANGED:
            actions = self._handle_text_changed()
        
        return actions
    
    def _handle_mouse_enter(self, data: Optional[dict]) -> list[TooltipAction]:
        """Handle mouse entering diagnostic area"""
        if not data:
            return []
        
        message = data.get('message')
        request_id = data.get('request_id')
        
        # If already processing this exact message (not IDLE), do nothing
        if self.state != TooltipState.IDLE and self.context and self.context.message == message:
            return []
        
        # Store context with current cache generation
        self.context = TooltipContext(
            message=message,
            event=data.get('event'),
            severity=data.get('severity'),
            diagnostic=data.get('diagnostic'),
            request_id=request_id,
            cache_generation=self._cache_generation
        )
        
        # Check if we have cached translation
        cached = self._get_cached_translation(message)
        
        if cached:
            # HAS CACHE: Start timer, wait for mouse to stop moving
            self.state = TooltipState.HOVERING
            return [
                TooltipAction('cancel_timer'),  # Cancel any pending timer
                TooltipAction('hide_tooltip'),  # Hide old tooltip if any
                TooltipAction('start_timer', {'delay_ms': self.hover_delay_ms})
            ]
        else:
            # NO CACHE: Start AI request immediately (no timer needed, AI takes ~2s)
            self.state = TooltipState.WAITING_FOR_AI
            return [
                TooltipAction('cancel_timer'),  # Cancel any pending timer
                TooltipAction('hide_tooltip'),  # Hide old tooltip if any
                TooltipAction('request_translation', {
                    'message': self.context.message,
                    'severity': self.context.severity,
                    'diagnostic': self.context.diagnostic,
                    'request_id': self.context.request_id,
                    'cache_generation': self.context.cache_generation
                })
            ]
    
    def _handle_mouse_motion(self) -> list[TooltipAction]:
        """Handle mouse movement inside diagnostic area - restart timer"""
        # Only restart timer if we're hovering (waiting for mouse to stop)
        if self.state != TooltipState.HOVERING:
            return []
        
        # Restart timer - mouse is still moving
        return [TooltipAction('start_timer', {'delay_ms': self.hover_delay_ms})]
    
    def _handle_mouse_leave(self) -> list[TooltipAction]:
        """Handle mouse leaving diagnostic area"""
        if self.state == TooltipState.IDLE:
            return []
        
        # Cancel everything and return to idle
        old_state = self.state
        self.state = TooltipState.IDLE
        self.context = None
        
        actions = [TooltipAction('cancel_timer')]
        
        # If tooltip was showing, hide it
        if old_state == TooltipState.SHOWING:
            actions.append(TooltipAction('hide_tooltip'))
        
        # If hovering, AI request may still be running in background
        # (will be cached when ready, but not shown)
        return actions
    
    def _handle_timer_expired(self) -> list[TooltipAction]:
        """Handle 300ms timer expiration - mouse stopped moving"""
        # Only act if we're still hovering
        if self.state != TooltipState.HOVERING or not self.context:
            return []
        
        # At this point, translation MUST be in cache (we only start timer if cached)
        cached = self._get_cached_translation(self.context.message)
        
        if not cached:
            # Should never happen - we only enter HOVERING state if cached
            return []
        
        # Show cached translation
        self.state = TooltipState.SHOWING
        return [
            TooltipAction('show_tooltip', {'translation': cached, 'context': self.context})
        ]
    
    def _handle_translation_ready(self, data: Optional[dict]) -> list[TooltipAction]:
        """Handle AI translation received"""
        if not data:
            return []
        
        request_id = data.get('request_id')
        translation = data.get('translation')
        cache_generation = data.get('cache_generation')
        
        # Check if cache was cleared during request (stale response)
        if cache_generation is not None and cache_generation != self._cache_generation:
            return []
        
        # Check if this response is for current context
        if self.context and request_id != self.context.request_id:
            return []
        
        # Cache translation (always cache, even if tooltip not shown)
        if translation and self.context:
            self._cache_translation(self.context.message, translation)
        
        # Show tooltip only if mouse is still inside (WAITING_FOR_AI)
        if self.state == TooltipState.WAITING_FOR_AI:
            # Mouse still inside, waiting for AI → show tooltip
            self.state = TooltipState.SHOWING
            return [
                TooltipAction('show_tooltip', {'translation': translation, 'context': self.context})
            ]
        else:
            # Mouse left or state changed → just cache, don't show
            return []
    
    def _handle_translation_error(self, data: Optional[dict]) -> list[TooltipAction]:
        """Handle AI translation error"""
        # Only show tooltip if mouse is still inside
        if self.state != TooltipState.WAITING_FOR_AI or not self.context:
            return []
        
        request_id = data.get('request_id') if data else None
        fallback = data.get('fallback') if data else self.context.message
        cache_generation = data.get('cache_generation') if data else None
        
        # Check if cache was cleared during request
        if cache_generation is not None and cache_generation != self._cache_generation:
            return []
        
        # Check if this error is for current context
        if request_id and request_id != self.context.request_id:
            return []
        
        # Show fallback message
        self.state = TooltipState.SHOWING
        return [
            TooltipAction('show_tooltip', {'translation': fallback, 'context': self.context})
        ]
    
    def _handle_text_changed(self) -> list[TooltipAction]:
        """Handle editor text change (clears cache)"""
        # Increment generation to invalidate in-flight AI requests
        self._cache_generation += 1
        self._clear_cache()
        
        # If showing tooltip, hide it
        if self.state == TooltipState.SHOWING:
            self.state = TooltipState.IDLE
            self.context = None
            return [TooltipAction('hide_tooltip')]
        
        # If waiting for AI, just clear state
        # (AI response will be ignored due to generation mismatch)
        if self.state == TooltipState.WAITING_FOR_AI:
            self.state = TooltipState.IDLE
            self.context = None
        
        return []
    
    # Cache management (delegates to external cache)
    def set_cache(self, cache_dict: dict) -> None:
        """Set reference to external cache dictionary"""
        self._cache_ref = cache_dict
    
    def _cache_translation(self, message: str, translation: str) -> None:
        """Cache translation for message (delegates to external cache)"""
        if self._cache_ref is not None:
            self._cache_ref[message] = translation
    
    def _get_cached_translation(self, message: str) -> Optional[str]:
        """Get cached translation for message (delegates to external cache)"""
        if self._cache_ref is not None:
            return self._cache_ref.get(message)
        return None
    
    def _clear_cache(self) -> None:
        """Clear translation cache (delegates to external cache)"""
        if self._cache_ref is not None:
            self._cache_ref.clear()

