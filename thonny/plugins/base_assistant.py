from abc import abstractmethod
from typing import Iterator, List, Optional

from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, ChatRole


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
    
    @abstractmethod
    def _get_summary_role(self) -> str:
        """Get the role for summary messages (OpenAI='system', Gemini='user')"""
        pass
    
    def get_ready(self) -> bool:
        """Check if API key is configured, request if not"""
        if self._get_saved_api_key() is None:
            self._request_new_api_key()
        return self._get_saved_api_key() is not None
    
    def _get_normal_system_prompt(self, context: ChatContext) -> str:
        """Get system prompt for normal (non-debug) requests"""
        prompt = """You are a helpful programming coach.

**When user sends an image:**
1. First, describe in detail what you see in the image (code, diagrams, errors, etc.)
2. Then answer the user's question

Format:
**What I see in the image:**
[detailed description]

**Answer:**
[your response]"""
        
        return prompt
    
    def _get_debug_system_prompt(self) -> str:
        """Get system prompt for debug step explanations (DON'T CHANGE)"""
        from thonny.plugins.debug_common import get_system_prompt
        
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"
        
        return get_system_prompt(lang)
    
    def _get_line_explanation_system_prompt(self, lang: str = "uk") -> str:
        """Get system prompt for line-by-line code explanation (popup)"""
        if lang == "ru":
            return """Ты — помощник для детей. Объясни строку кода КРАТКО и ПРОСТО.

Формат (максимум 5-6 предложений):
1. **Что делает:** одна фраза общего смысла
2. **Как работает:** 2-3 коротких пункта о порядке выполнения
3. **Пример:** один простой пример

ПРАВИЛА:
- Пиши КОРОТКО для детей 10-12 лет
- БЕЗ сложных терминов (индекс → номер, оператор → команда)
- НЕ используй местоимения (он, его, этот и т.д.) - ВСЕГДА показывай код в обратных кавычках
- Будь конкретным - указывай что именно получается
- Последний пункт "Как работает" начинай с "Таким образом..."
- Пиши на РУССКОМ языке

Пример ХОРОШЕГО формата для mas1=[mas[0]]:
**Как работает:**
- Создается новая переменная mas1
- `mas[0]` берет первое число из списка mas (например, из списка [15, 20, 25] берется число 15)
- `[mas[0]]` создает новый список из этого числа (получается список чисел [15])
- Таким образом mas1 получает список чисел [15] с одним элементом - первым числом из mas

Пример ХОРОШЕГО для mas=list(map(int,input().split())):
**Как работает:**
- `input()` читает введенную строку (например, строку "5 10 15")
- `.split()` делит строку на список строк по пробелам (получается список строк ["5", "10", "15"])
- `map(int, ...)` превращает каждую строку "5", "10", "15" в число
- `list(...)` собирает все числа в один список (получается список чисел [5, 10, 15])
- Таким образом mas получает список чисел [5, 10, 15]

ВАЖНО - ВСЕГДА:
- Указывай ТИП И ЗНАЧЕНИЕ в формате: тип + значение (например, "число 10", "список чисел [5, 10]")
- НЕ пиши "10 – это число" или "[10] – это список", пиши "число 10" или "список чисел [10]"
- Если создается новая переменная - ПЕРВЫМ пунктом напиши "Создается новая переменная имя_переменной"
- ИСПОЛЬЗУЙ реальные значения переменных из контекста программы в примерах (если переменная mas = [15, 20, 25], пиши конкретно "из списка [15, 20, 25]", а не "например из списка [10, 20, 30]")
- Показывай примеры промежуточных результатов в скобках
- НЕ используй "такой", "такую часть", "это" - пиши конкретно что именно
- Каждая операция/функция - отдельный пункт списка
- "Таким образом..." ТОЛЬКО в последнем пункте, который объясняет итоговый результат"""
        else:  # uk
            return """Ти — помічник для дітей. Поясни рядок коду КОРОТКО і ПРОСТО.

Формат (максимум 5-6 речень):
1. **Що робить:** одна фраза загального змісту
2. **Як працює:** 2-3 короткі пункти про порядок виконання
3. **Приклад:** один простий приклад

ПРАВИЛА:
- Пиши КОРОТКО для дітей 10-12 років
- БЕЗ складних термінів (індекс → номер, оператор → команда)
- НЕ використовуй займенники (він, його, цей тощо) - ЗАВЖДИ показуй код у зворотних лапках
- Будь конкретним - вказуй що саме виходить
- Останній пункт "Як працює" починай з "Таким чином..."
- Пиши УКРАЇНСЬКОЮ мовою

Приклад ХОРОШОГО формату для mas1=[mas[0]]:
**Як працює:**
- Створюється нова змінна mas1
- `mas[0]` бере перше число зі списку mas (наприклад, зі списку [15, 20, 25] береться число 15)
- `[mas[0]]` створює новий список з цього числа (виходить список чисел [15])
- Таким чином mas1 отримує список чисел [15] з одним елементом - першим числом зі списку mas

Приклад ХОРОШОГО для mas=list(map(int,input().split())):
**Як працює:**
- `input()` читає введену строку (наприклад, строку "5 10 15")
- `.split()` ділить строку на список строк за пробілами (виходить список строк ["5", "10", "15"])
- `map(int, ...)` перетворює кожну строку "5", "10", "15" на число
- `list(...)` збирає всі числа в один список (виходить список чисел [5, 10, 15])
- Таким чином mas отримує список чисел [5, 10, 15]

ВАЖЛИВО - ЗАВЖДИ:
- Вказуй ТИП І ЗНАЧЕННЯ у форматі: тип + значення (наприклад, "число 10", "список чисел [5, 10]")
- НЕ пиши "10 – це число" або "[10] – це список", пиши "число 10" або "список чисел [10]"
- Якщо створюється нова змінна - ПЕРШИМ пунктом напиши "Створюється нова змінна імя_змінної"
- ВИКОРИСТОВУЙ реальні значення змінних з контексту програми в прикладах (якщо змінна mas = [15, 20, 25], пиши конкретно "зі списку [15, 20, 25]", а не "наприклад зі списку [10, 20, 30]")
- Показуй приклади проміжних результатів у дужках
- НЕ використовуй "такий", "таку частину", "це" - пиши конкретно що саме
- Кожна операція/функція - окремий пункт списку
- "Таким чином..." ТІЛЬКИ в останньому пункті, який пояснює підсумковий результат"""
    
    def _add_context_to_prompt(self, base_prompt: str, context: ChatContext) -> str:
        """Add file/debug context to base prompt"""
        system_content = base_prompt
        
        # Add file context
        if context.file_contents_by_path:
            system_content += "\n\n**Current context:**"
            
            # Check for current file content (without specific path)
            if 'current_file' in context.file_contents_by_path:
                system_content += f"\n\nFull program code:"
                system_content += f"\n```python\n{context.file_contents_by_path['current_file']}\n```"
            
            if context.active_file_selection:
                system_content += f"\n\nSelected code:\n```python\n{context.active_file_selection}\n```"
        
        # Add debug context if debugger is active
        if context.execution_io:
            system_content += f"\n\n**Debug context (program is paused):**\n{context.execution_io}"
        
        return system_content
    
    def _summarize_if_needed(self, messages: List[ChatMessage]) -> tuple[List[dict], List[ChatMessage]]:
        """Summarize history if too large. Returns (summary_prefix, filtered_messages)"""
        def _messages_size(msgs) -> int:
            total = 0
            for m in msgs:
                total += len(m.content)
            return total
        
        try:
            SUMMARY_MAX_MSGS = int(get_workbench().get_option("ai.summary_max_msgs", 25))
        except Exception:
            SUMMARY_MAX_MSGS = 25
        try:
            SUMMARY_MAX_CHARS = int(get_workbench().get_option("ai.summary_max_chars", 10000))
        except Exception:
            SUMMARY_MAX_CHARS = 10000

        summary_prefix = []
        
        if len(messages) > SUMMARY_MAX_MSGS or _messages_size(messages) > SUMMARY_MAX_CHARS:
            # Build a compact summary
            first_user = next((m for m in messages if m.role == ChatRole.USER), None)
            last_assistant = next((m for m in reversed(messages) if m.role == ChatRole.ASSISTANT), None)

            first_user_text = (first_user.content[:800] + "…") if first_user and len(first_user.content) > 800 else (first_user.content if first_user else "")
            last_assistant_text = (last_assistant.content[:800] + "…") if last_assistant and len(last_assistant.content) > 800 else (last_assistant.content if last_assistant else "")

            summary_text = (
                "BRIEF CONTEXT SUMMARY (for model, do not show to user):\n\n"
                f"User's task:\n{first_user_text}\n\n"
                f"Current progress:\n{last_assistant_text}\n\n"
                "Focus responses on completing the user's task."
            )

            # Use API-specific role for summary
            summary_role = self._get_summary_role()
            
            if summary_role == "system":
                # OpenAI format
                summary_prefix.append({
                    "role": "system",
                    "content": summary_text,
                })
            else:
                # Gemini format
                summary_prefix.append({
                    "role": "user",
                    "parts": [summary_text],
                })

            # Keep only the last few recent messages
            messages = messages[-10:]
        
        return summary_prefix, messages
    
    def _complete_normal(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Normal mode: user text with optional image, with history summarization"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        logger.info("=" * 80)
        logger.info("NORMAL MODE REQUEST")
        logger.info("=" * 80)
        
        # Get base prompt (use override if provided, e.g., for line explanation popup)
        if context.system_prompt_override:
            base_prompt = context.system_prompt_override
        else:
            base_prompt = self._get_normal_system_prompt(context)
        
        # ALWAYS add file/debug context (even with override)
        system_prompt = self._add_context_to_prompt(base_prompt, context)
        
        # Log system prompt with context
        logger.info("SYSTEM PROMPT (with context):")
        logger.info("-" * 80)
        logger.info(system_prompt)
        logger.info("-" * 80)
        
        # Summarize history if needed
        summary_prefix, filtered_messages = self._summarize_if_needed(context.messages)
        
        # Log user messages
        logger.info("USER MESSAGES:")
        logger.info("-" * 80)
        for msg in filtered_messages:
            logger.info(f"[{msg.role.value}]: {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}")
        logger.info("-" * 80)
        
        # Prepare messages (API-specific format)
        prepared_messages = self._prepare_messages(filtered_messages)
        
        # Add summary prefix if present
        all_messages = summary_prefix + prepared_messages
        
        # Send to API
        return self._send_to_api(system_prompt, all_messages)
    
    def _complete_debug_step(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Debug mode: step with explanation, NO history summarization"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        logger.info("=" * 80)
        logger.info("DEBUG MODE REQUEST")
        logger.info("=" * 80)
        
        # Get debug prompt (DON'T CHANGE)
        base_prompt = self._get_debug_system_prompt()
        
        # Add debug context (execution_io already contains all needed context)
        system_prompt = self._add_context_to_prompt(base_prompt, context)
        
        # Log system prompt with context
        logger.info("SYSTEM PROMPT (with context):")
        logger.info("-" * 80)
        logger.info(system_prompt)
        logger.info("-" * 80)
        
        # Log user messages
        logger.info("USER MESSAGES:")
        logger.info("-" * 80)
        for msg in context.messages:
            logger.info(f"[{msg.role.value}]: {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}")
        logger.info("-" * 80)
        
        # NO summarization for debug
        # Prepare all messages as-is
        prepared_messages = self._prepare_messages(context.messages)
        
        # Send to API
        return self._send_to_api(system_prompt, prepared_messages)

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Main entry point - routes to normal or debug mode"""
        # Check if this is a debug step explanation request
        last_message = context.messages[-1] if context.messages else None
        is_debug_step = last_message and last_message.is_debug_related if last_message else False
        
        if is_debug_step:
            return self._complete_debug_step(context)
        else:
            return self._complete_normal(context)

    def cancel_completion(self) -> None:
        """Cancel current completion (default: do nothing)"""
        pass
    
    def explain_line(self, line_num: int, line_content: str, full_code: str, debug_vars: Optional[dict] = None, lang: str = "uk") -> str:
        """
        Request AI explanation for a specific line of code
        
        Args:
            line_num: Line number in the code
            line_content: The actual line of code to explain
            full_code: Full program code for context
            debug_vars: Optional dict of current variables (if in debug mode)
            lang: Language for explanation ("ru" or "uk")
            
        Returns:
            AI explanation as string
        """
        from logging import getLogger
        from thonny.assistance import ChatContext, ChatMessage, ChatRole
        
        logger = getLogger(__name__)
        
        # Get system prompt
        system_prompt = self._get_line_explanation_system_prompt(lang)
        
        # Create simple user question (context will be added by base_assistant)
        if lang == "ru":
            user_prompt = f"""**Строка для объяснения (номер {line_num}):**
```python
{line_content}
```

Объясни подробно эту строку используя контекст всей программы."""
        else:  # uk
            user_prompt = f"""**Рядок для пояснення (номер {line_num}):**
```python
{line_content}
```

Поясни детально цей рядок використовуючи контекст всієї програми."""
        
        response_parts = []
        try:
            # Create context with custom system prompt
            context = ChatContext(
                messages=[ChatMessage(ChatRole.USER, user_prompt, [])],
                file_contents_by_path={'current_file': full_code},
                system_prompt_override=system_prompt  # Use custom popup prompt
            )
            
            # Call assistant (will use BaseAIAssistant infrastructure)
            # Logging happens in _complete_normal()
            for chunk in self.complete_chat(context):
                if chunk.content:
                    response_parts.append(chunk.content)
                    
        except Exception as e:
            logger.exception("Ошибка при запросе объяснения строки")
            return f"Помилка при запиті до AI: {str(e)}"
        
        result = "".join(response_parts) if response_parts else "Немає відповіді від AI"
        
        return result

