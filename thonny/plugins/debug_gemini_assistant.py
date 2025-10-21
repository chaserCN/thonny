"""
AI Assistant for debugging using Gemini - explains current step and predicts next step
"""
import logging
from typing import Iterator, Optional
from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, Attachment, ChatRole
from thonny.plugins.debugger import get_current_debugger
from thonny.plugins.gemini import GeminiAssistant
from thonny.plugins.debug_common import get_debug_context as common_debug_context, get_system_prompt

logger = logging.getLogger(__name__)


class DebugGeminiAssistant(GeminiAssistant):
    """
    Enhanced Gemini AI Assistant that can explain debugging steps
    """
    
    def get_debug_context(self) -> Optional[str]:
        # Delegate to shared implementation
        return common_debug_context()
    
    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Enhanced chat completion with debug context"""
        import google.generativeai as genai
        
        api_key = self._get_saved_api_key()
        if not api_key:
            yield ChatResponseChunk("Please configure Gemini API key in Tools → Manage plug-ins", is_final=True, is_interal_error=True)
            return
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        lang = get_workbench().get_option("ai.language", "uk")
        
        # Get debug context
        debug_context = common_debug_context()
        
        # Get current debug session ID from the last debug-related message (scan from end)
        last_message = context.messages[-1] if context.messages else None
        current_debug_session_id = None
        for m in reversed(context.messages):
            if getattr(m, "is_debug_related", False):
                current_debug_session_id = m.debug_session_id
                break
        
        # Filter messages: keep non-debug and current debug session only
        filtered_messages = [
            msg for msg in context.messages
            if not msg.is_debug_related or msg.debug_session_id == current_debug_session_id
        ]

        # Summarize old non-debug history (virtual system->user message for Gemini) if too large
        def _messages_size(msgs: list[ChatMessage]) -> int:
            total = 0
            for m in msgs:
                total += len(m.content)
            return total

        non_debug_msgs = [m for m in filtered_messages if not m.is_debug_related]
        debug_msgs = [m for m in filtered_messages if m.is_debug_related]

        try:
            SUMMARY_MAX_MSGS = int(get_workbench().get_option("ai.summary_max_msgs", 25))
        except Exception:
            SUMMARY_MAX_MSGS = 25
        try:
            SUMMARY_MAX_CHARS = int(get_workbench().get_option("ai.summary_max_chars", 10000))
        except Exception:
            SUMMARY_MAX_CHARS = 10000

        summarized_prefix: list[dict] = []
        if len(non_debug_msgs) > SUMMARY_MAX_MSGS or _messages_size(non_debug_msgs) > SUMMARY_MAX_CHARS:
            first_user = next((m for m in non_debug_msgs if m.role == ChatRole.USER), None)
            last_assistant = next((m for m in reversed(non_debug_msgs) if m.role == ChatRole.ASSISTANT), None)

            first_user_text = (first_user.content[:800] + "…") if first_user and len(first_user.content) > 800 else (first_user.content if first_user else "")
            last_assistant_text = (last_assistant.content[:800] + "…") if last_assistant and len(last_assistant.content) > 800 else (last_assistant.content if last_assistant else "")

            if lang == "ru":
                summary_intro = "КРАТКАЯ СВОДКА КОНТЕКСТА (для модели, не выводить пользователю):"
                task_phrase = "Задача пользователя:"
                progress_phrase = "Текущий прогресс:"
                focus_phrase = "Сфокусируй ответы на выполнении задачи пользователя."
            else:
                summary_intro = "КОРОТКА ПІДСУМКОВА ДОВІДКА (для моделі, не показувати користувачу):"
                task_phrase = "Завдання користувача:"
                progress_phrase = "Поточний прогрес:"
                focus_phrase = "Сфокусуй відповіді на виконанні завдання користувача."

            summary_text = (
                f"{summary_intro}\n\n"
                f"{task_phrase}\n{first_user_text}\n\n"
                f"{progress_phrase}\n{last_assistant_text}\n\n"
                f"{focus_phrase}"
            )

            summarized_prefix.append({
                "role": "user",  # Gemini doesn't support system; use as user-context
                "parts": [summary_text],
            })

            non_debug_msgs = non_debug_msgs[-10:]
            filtered_messages = non_debug_msgs + debug_msgs
        
        # Detect special debug commands and override prompt
        user_content = last_message.content if last_message else ""
        prompt_override = None
         
        # Build system prompt based on language (shared)
        system_content = get_system_prompt(lang)
        
        # Build messages
        history = []
        
        # Add system message as first user message (Gemini doesn't support system role)
        history.append({
            "role": "user",
            "parts": [system_content]
        })
        # Remove model ack to reduce noise
        
        # Add summarized prefix if present
        for pref in summarized_prefix:
            history.append(pref)

        # Add chat history (filtered)
        for msg in filtered_messages[:-1]:
            role = msg.role.to_gemini()
            content = self.format_message(msg)
            
            # Add debug context to assistant messages if available
            if msg.role == ChatRole.ASSISTANT and debug_context:
                content = f"{debug_context}\n\n{content}"
            
            history.append({
                "role": role,
                "parts": [content]
            })
        
        # Prepare final user message
        final_content_parts = []
        
        if debug_context:
            final_content_parts.append(debug_context)
            final_content_parts.append("")
        
        if prompt_override:
            final_content_parts.append(prompt_override)
        elif filtered_messages:
            final_content_parts.append(self.format_message(filtered_messages[-1]))
        
        final_prompt = "\n".join(final_content_parts)
        
        # Log sent message
        print("=" * 80)
        print("📤 ВІДПРАВЛЯЄМО GEMINI:" if lang == "uk" else "📤 ОТПРАВЛЯЕМ GEMINI:")
        print("-" * 80)
        print(f'"""\n{final_prompt}\n"""')
        print("=" * 80)
        
        # Start chat with history
        chat = model.start_chat(history=history)
        
        # Stream response
        response = chat.send_message(final_prompt, stream=True)
        
        full_response = ""
        for chunk in response:
            if chunk.text:
                full_response += chunk.text
                yield ChatResponseChunk(chunk.text, is_final=False)
        
        # Log received message
        print("=" * 80)
        print("📥 ОТРИМАЛИ ВІД GEMINI:" if lang == "uk" else "📥 ПОЛУЧИЛИ ОТ GEMINI:")
        print("-" * 80)
        print(f'"""\n{full_response}\n"""')
        print("=" * 80)
        
        yield ChatResponseChunk("", is_final=True)

    def cancel_completion(self) -> None:
        pass


def load_plugin():
    get_workbench().add_assistant("DebugGemini", DebugGeminiAssistant())

