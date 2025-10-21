"""
AI Assistant for debugging - explains current step and predicts next step
"""
import logging
from typing import Iterator, Optional
from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, Attachment, ChatRole
from thonny.plugins.debugger import get_current_debugger
from thonny.plugins.openai import OpenAIAssistant
from thonny.plugins.debug_common import get_debug_context as common_debug_context, get_system_prompt

logger = logging.getLogger(__name__)


class DebugAIAssistant(OpenAIAssistant):
    """
    Enhanced AI Assistant that can explain debugging steps
    """
    
    def get_debug_context(self) -> Optional[str]:
        # Delegate to shared implementation
        return common_debug_context()
    
    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Enhanced completion with debug context"""
        from openai import OpenAI
        
        api_key = self._get_saved_api_key()
        if not api_key:
            yield ChatResponseChunk("Please configure OpenAI API key in Tools → Manage plug-ins", is_final=True, is_interal_error=True)
            return
        
        client = OpenAI(api_key=api_key)
        
        # Determine current debug session from the last debug-related message (scan from end)
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

        # Summarize old non-debug history (virtual system message) if too large
        def _messages_size(msgs: list[ChatMessage]) -> int:
            total = 0
            for m in msgs:
                total += len(m.content)
            return total

        # Split non-debug messages around the last debug session
        non_debug_msgs = [m for m in filtered_messages if not m.is_debug_related]
        debug_msgs = [m for m in filtered_messages if m.is_debug_related]

        # thresholds from options
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
            # Build a compact summary focusing on task intent and user goal
            first_user = next((m for m in non_debug_msgs if m.role == ChatRole.USER), None)
            last_assistant = next((m for m in reversed(non_debug_msgs) if m.role == ChatRole.ASSISTANT), None)

            first_user_text = (first_user.content[:800] + "…") if first_user and len(first_user.content) > 800 else (first_user.content if first_user else "")
            last_assistant_text = (last_assistant.content[:800] + "…") if last_assistant and len(last_assistant.content) > 800 else (last_assistant.content if last_assistant else "")

            lang = get_workbench().get_option("ai.language", "uk")
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
                "role": ChatRole.SYSTEM.to_openai(),
                "content": summary_text,
            })

            # Keep only the last few recent non-debug messages to preserve recency
            non_debug_msgs = non_debug_msgs[-10:]

            # Reassemble filtered_messages order: summarized prefix + trimmed non-debug + debug
            filtered_messages = non_debug_msgs + debug_msgs
        
        # Build messages with debug context (localized)
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"

        # Use shared system prompt
        system_content = get_system_prompt(lang)

        messages = [
            {
                "role": "system",
                "content": system_content,
            }
        ]
        
        # Add debug context if available
        debug_ctx = common_debug_context()
        if debug_ctx:
            messages.append({
                "role": "system",
                "content": f"Current debugging context:\n{debug_ctx}"
            })
        
        # Add conversation history (filtered + optional summarized prefix)
        for pref in summarized_prefix:
            messages.append(pref)

        for msg in filtered_messages[:-1]:  # All except last
            messages.append({
                "role": msg.role.to_openai(),
                "content": self.format_message(msg)
            })
        
        # Add the last message (from filtered list)
        if filtered_messages:
            messages.append({
                "role": filtered_messages[-1].role.to_openai(),
                "content": self.format_message(filtered_messages[-1])
            })
        
        # ===== ЛОГУВАННЯ: Що відсилаємо =====
        print("\n" + "="*80)
        print("📤 ВІДПРАВЛЯЄМО ДО ChatGPT")
        print("="*80)
        
        for i, msg in enumerate(messages):
            print(f"\nMessage {i+1} - {msg['role'].upper()}:")
            content = msg['content']
            print(f'"""\n{content}\n"""')
        
        # Stream response
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                stream=True,
            )
            
            # ===== ЛОГУВАННЯ: Що отримуємо =====
            full_response = ""
            
            for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                full_response += chunk_message
                yield ChatResponseChunk(chunk_message, is_final=False)
            
            # Логуємо повну відповідь
            print("\n" + "="*80)
            print("📥 ВІДПОВІДЬ ВІД ChatGPT")
            print("="*80)
            print(f'"""\n{full_response}\n"""')
            print("="*80 + "\n")
            
            yield ChatResponseChunk("", is_final=True)
            
        except Exception as e:
            yield ChatResponseChunk(f"Error: {str(e)}", is_final=True, is_interal_error=True)


def load_plugin():
    """Register the debug assistant"""
    get_workbench().add_assistant("DebugAI", DebugAIAssistant())

