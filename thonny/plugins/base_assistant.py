from abc import abstractmethod
from typing import Iterator, List, Optional

from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, ChatRole, CodeViewContext, TokenContext, SelectionContext
from thonny.prompts import PromptType, get_prompt


class BaseAIAssistant(Assistant):
    """Base class for AI assistants with common logic"""
    
    @abstractmethod
    def _get_saved_api_key(self) -> Optional[str]:
        """Get saved API key from storage"""
        pass
    
    @abstractmethod
    def _request_new_api_key(self) -> None:
        """Show dialog to request new API key"""
        pass
    
    @abstractmethod
    def _prepare_messages(self, messages: List[ChatMessage]) -> List[dict]:
        """Convert ChatMessage list to API-specific format"""
        pass
    
    @abstractmethod
    def _send_to_api(self, system_prompt: str, messages: List[dict]) -> Iterator[ChatResponseChunk]:
        """Send request to API and stream response"""
        pass
    
    def get_ready(self) -> bool:
        """Check if API key is configured, request if not"""
        if self._get_saved_api_key() is None:
            self._request_new_api_key()
        return self._get_saved_api_key() is not None
    
    def _get_language(self) -> str:
        """Get current language setting from workbench"""
        try:
            return get_workbench().get_option("ai.language", "uk")
        except Exception:
            return "uk"
    
    def _complete_normal(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Normal mode: user text with optional image (history already compressed in chat.py)"""
        
        # Get appropriate prompt based on whether image is present
        lang = self._get_language()
        
        if context.has_image_in_last_message():
            system_prompt = get_prompt(PromptType.SYSTEM_NORMAL_WITH_IMAGE, lang)
        else:
            system_prompt = get_prompt(PromptType.SYSTEM_NORMAL, lang)
        
        # Use messages from context (already compressed in chat.py)
        messages_to_send = list(context.messages)
        
        # Add current message (new user message) with context
        if context.current_message:
            # Build context prefix for current message
            context_prefix = ""
            if context.program_context:
                context_prefix += f"**Current context:**\n{context.program_context}\n\n"
            if context.active_file_selection:
                context_prefix += f"Selected code:\n```python\n{context.active_file_selection}\n```\n\n"
            
            # Create modified current message with context
            from thonny.assistance import ChatMessage
            current_with_context = ChatMessage(
                role=context.current_message.role,
                content=context_prefix + context.current_message.content,
                attachments=context.current_message.attachments,
                image=context.current_message.image
            )
            messages_to_send = messages_to_send + [current_with_context]
        
        print_request_info("NORMAL", system_prompt, messages_to_send)
        
        # Prepare messages (API-specific format)
        prepared_messages = self._prepare_messages(messages_to_send)
        
        # Send to API
        return self._send_to_api(system_prompt, prepared_messages)
    
    def _complete_debug_step(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Debug mode: step with explanation, NO history summarization"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        # Get debug prompt (DON'T CHANGE)
        lang = self._get_language()
        system_prompt = get_prompt(PromptType.SYSTEM_DEBUG, lang)
        
        # Add current message with program_context
        # (Debug context already contains all needed info, no need for selected text)
        messages = list(context.messages)
        if context.current_message:
            from thonny.assistance import ChatMessage
            context_prefix = context.program_context + "\n\n" if context.program_context else ""
            current_with_context = ChatMessage(
                role=context.current_message.role,
                content=context_prefix + context.current_message.content,
                attachments=context.current_message.attachments,
                image=context.current_message.image
            )
            messages = messages + [current_with_context]
        
        print_request_info("DEBUG STEP", system_prompt, messages)
        
        # NO summarization for debug
        # Prepare all messages as-is
        prepared_messages = self._prepare_messages(messages)
        
        # Send to API
        return self._send_to_api(system_prompt, prepared_messages)

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Main entry point - routes to normal or debug mode"""
        from logging import getLogger
        
        # Check API key is configured
        if not self.get_ready():
            # API key not configured, return error
            yield ChatResponseChunk("API key not configured", is_final=False)
            yield ChatResponseChunk("", is_final=True)
            return
        
        # Check if this is a debug step explanation request
        # Use current_message (new message), not last from history
        current_message = context.current_message
        is_debug_step = current_message and current_message.is_debug_related if current_message else False
        
        if is_debug_step:
            yield from self._complete_debug_step(context)
        else:
            yield from self._complete_normal(context)

    def cancel_completion(self) -> None:
        """Cancel current completion (default: do nothing)"""
        pass
    
    def get_history_summary(self, messages: List[ChatMessage]) -> str:
        """
        Get AI summary of conversation history
        
        Args:
            messages: List of messages to summarize
            
        Returns:
            Summary text from AI
        """
        from logging import getLogger
        logger = getLogger(__name__)
        
        # Build conversation text
        conversation_text = ""
        for msg in messages:
            role_label = "User" if msg.role == ChatRole.USER else "Assistant"
            # Truncate very long messages
            content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            conversation_text += f"{role_label}: {content}\n\n"
        
        # Get language
        lang = self._get_language()
        
        # Get summary prompt with conversation text
        summary_prompt = get_prompt(
            PromptType.SUMMARY_REQUEST,
            lang,
            conversation_text=conversation_text
        )
        
        # System prompt for summarization
        system_prompt = get_prompt(PromptType.SYSTEM_NORMAL, lang)
        
        # Create single message
        from thonny.assistance import ChatMessage
        summary_message = ChatMessage(ChatRole.USER, summary_prompt, [])
        messages = self._prepare_messages([summary_message])
        
        logger.info(f"Requesting AI summary for {len(messages)} messages")
        
        # Call API synchronously
        response_parts = []
        try:
            for chunk in self._send_to_api(system_prompt, messages):
                if chunk.content:
                    response_parts.append(chunk.content)
                if chunk.is_final:
                    break
        except Exception as e:
            logger.exception("Error getting AI summary")
            raise
        
        summary = "".join(response_parts)
        logger.info(f"Received AI summary: {len(summary)} chars")
        
        return summary
    
    def explain_line(self, context: CodeViewContext) -> str:
        """
        Request AI explanation for a specific line of code
        
        Args:
            context: CodeViewContext with line info and full code
            
        Returns:
            AI explanation as string
        """
        from logging import getLogger
        from thonny.assistance import ChatMessage, ChatRole
        
        logger = getLogger(__name__)
        
        # Get language preference
        lang = self._get_language()
        
        # Get system prompt (instructions only)
        system_prompt = get_prompt(PromptType.SYSTEM_LINE_EXPLANATION, lang)
        
        # Build user prompt with all context (data)
        # Note: program_context always contains either debug context or formatted code
        user_prompt = get_prompt(
            PromptType.USER_EXPLAIN_LINE_WITH_CONTEXT,
            lang,
            full_code="",  # Code is now in program_context
            line_num=context.line_num,
            line_content=context.line_content,
            execution_io=context.program_context
        )
        
        # Prepare single message
        user_message = ChatMessage(ChatRole.USER, user_prompt, [])
        
        print_request_info("EXPLAIN LINE", system_prompt, [user_message])
        
        messages = self._prepare_messages([user_message])

        # Call API directly (no need for complete_chat overhead)
        response_parts = []
        try:
            for chunk in self._send_to_api(system_prompt, messages):
                if chunk.content:
                    response_parts.append(chunk.content)
                    
        except Exception as e:
            logger.exception("Ошибка при запросе объяснения строки")
            return f"Помилка при запиті до AI: {str(e)}"
        
        result = "".join(response_parts) if response_parts else "Немає відповіді від AI"
        
        return result
    
    def explain_token(self, context: TokenContext) -> str:
        """
        Request AI explanation for a specific token/element in code
        
        Args:
            context: TokenContext with token info and full code
            
        Returns:
            AI explanation as string
        """
        from logging import getLogger
        from thonny.assistance import ChatMessage, ChatRole
        
        logger = getLogger(__name__)
        
        # Get language preference
        lang = self._get_language()
        
        # Get system prompt (instructions only)
        system_prompt = get_prompt(PromptType.SYSTEM_TOKEN_EXPLANATION, lang)
        
        # Build user prompt with all context (data)
        user_prompt = get_prompt(
            PromptType.USER_EXPLAIN_TOKEN,
            lang,
            line_num=context.line_num,
            line_content=context.line_content,
            token=context.token,
            token_description=context.token_description,
            program_context=context.program_context
        )
        
        # Prepare single message
        user_message = ChatMessage(ChatRole.USER, user_prompt, [])
        
        print_request_info("EXPLAIN TOKEN", system_prompt, [user_message])
        
        messages = self._prepare_messages([user_message])

        # Call API directly (no need for complete_chat overhead)
        response_parts = []
        try:
            for chunk in self._send_to_api(system_prompt, messages):
                if chunk.content:
                    response_parts.append(chunk.content)
                    
        except Exception as e:
            logger.exception("Error requesting token explanation")
            if lang == "ru":
                return f"Ошибка при запросе к AI: {str(e)}"
            else:
                return f"Помилка при запиті до AI: {str(e)}"
        
        result = "".join(response_parts) if response_parts else ("Нет ответа от AI" if lang == "ru" else "Немає відповіді від AI")
        
        return result
    
    def explain_selection(self, context: SelectionContext) -> str:
        """
        Request AI explanation for selected code fragment
        
        Args:
            context: SelectionContext with selected code and full program
            
        Returns:
            AI explanation as string
        """
        from logging import getLogger
        from thonny.assistance import ChatMessage, ChatRole
        
        logger = getLogger(__name__)
        
        # Get language preference
        lang = self._get_language()
        
        # Get system prompt (instructions only)
        system_prompt = get_prompt(PromptType.SYSTEM_SELECTION_EXPLANATION, lang)
        
        # Build user prompt with all context (data)
        user_prompt = get_prompt(
            PromptType.USER_EXPLAIN_SELECTION,
            lang,
            selected_code=context.selected_code,
            start_line=context.start_line,
            end_line=context.end_line,
            program_context=context.program_context
        )
        
        # Prepare single message
        user_message = ChatMessage(ChatRole.USER, user_prompt, [])
        
        print_request_info("EXPLAIN SELECTION", system_prompt, [user_message])
        
        messages = self._prepare_messages([user_message])

        # Call API directly
        response_parts = []
        try:
            for chunk in self._send_to_api(system_prompt, messages):
                if chunk.content:
                    response_parts.append(chunk.content)
                    
        except Exception as e:
            logger.exception("Error requesting selection explanation")
            if lang == "ru":
                return f"Ошибка при запросе к AI: {str(e)}"
            else:
                return f"Помилка при запиті до AI: {str(e)}"
        
        result = "".join(response_parts) if response_parts else ("Нет ответа от AI" if lang == "ru" else "Немає відповіді від AI")
        
        return result

def print_request_info(request_type: str, system_prompt: str, messages: List[ChatMessage]):
    print("=" * 80)
    print(f"{request_type} MODE REQUEST")
    print("=" * 80)
    print("SYSTEM PROMPT:")
    print("-" * 80)
    print(system_prompt)
    print("-" * 80)
    print("USER MESSAGES:")
    print("-" * 80)
    for msg in messages:
        print(f"[{msg.role.value}]: {msg.content}")
    print("-" * 80)
