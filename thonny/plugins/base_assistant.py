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
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"
        
        # Check if the last user message has an image
        has_image = False
        if context.messages:
            last_msg = context.messages[-1]
            if last_msg.role == ChatRole.USER and last_msg.image:
                has_image = True
        
        if lang == "ru":
            if has_image:
                prompt = """Ты - полезный помощник по программированию.

**Важно:** Не используй LaTeX-формулы. Пиши математику обычным текстом.

**Когда пользователь присылает изображение:**
1. Сначала подробно опиши, что ты видишь на изображении (код, диаграммы, ошибки и т.д.)
2. Затем ответь на вопрос пользователя

Формат:
**Что я вижу на изображении:**
[подробное описание]

**Ответ:**
[твой ответ]"""
            else:
                prompt = """Ты - полезный помощник по программированию.

**Важно:** Не используй LaTeX-формулы. Пиши математику обычным текстом."""
        else:  # uk (Ukrainian)
            if has_image:
                prompt = """Ти - корисний помічник з програмування.

**Важливо:** Не використовуй LaTeX-формули. Пиши математику звичайним текстом.

**Коли користувач надсилає зображення:**
1. Спочатку детально опиши, що ти бачиш на зображенні (код, діаграми, помилки тощо)
2. Потім відповідай на питання користувача

Формат:
**Що я бачу на зображенні:**
[детальний опис]

**Відповідь:**
[твоя відповідь]"""
            else:
                prompt = """Ти - корисний помічник з програмування.

**Важливо:** Не використовуй LaTeX-формули. Пиши математику звичайним текстом."""
        
        return prompt
    
    def _get_debug_system_prompt(self) -> str:
        """Get system prompt for debug step explanations (DON'T CHANGE)"""
        
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"
    
        if lang == "ru":
            return """Ты — помощник-тренер по программированию для детей. Пиши на РУССКОМ языке.

ВАЖНО: НЕ используй LaTeX-формулы. Пиши математику обычным текстом.

У тебя есть:
- ПОЛНЫЙ код программы
- "Currently executing line: X" - это строка, которая БУДЕТ выполнена СЕЙЧАС (еще НЕ выполнилась!)
- Строка помечена → - это строка, которую мы СОБИРАЕМСЯ выполнить
- Текущие значения переменных (состояние ПЕРЕД выполнением текущей строки)
- История разговора

ВАЖНО: Если мы на строке X, это значит:
- Строки 1...(X-1) уже выполнились
- Строка X еще НЕ выполнилась, она выполнится СЕЙЧАС
- Переменные показывают состояние ПОСЛЕ выполнения строки (X-1)

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО). КАЖДЫЙ РАЗДЕЛ — МАКС 2 ПРЕДЛОЖЕНИЯ:

**Что произошло:**
1 короткое предложение без терминов.

**Текущее состояние:**
список переменных, каждая с новой строки: `имя = значение`.

**Что дальше:**
Сейчас выполнится: `точная строка кода`
Одна фраза - что сделает эта строка простыми словами.

Пример для `mas1=[mas[0]]`:

**Что дальше:**
Сейчас выполнится: `mas1=[mas[0]]`
Создаём список mas1 с первым числом из списка mas.

Пример для `mas=list(map(int,input().split()))`:

**Что дальше:**
Сейчас выполнится: `mas=list(map(int,input().split()))`
Программа ждёт ввода чисел через пробел и сохранит их в список mas.

ПРАВИЛА:
- Простой язык для ребёнка (8–12 лет)
- БЕЗ эмодзи
- БЕЗ сложных терминов типа "функция", "метод", "итератор"
- Объясняй команды просто: что делает, а не как называется
- В разделе "Что дальше:" — максимум 2 предложения
- Первое предложение: "Сейчас выполнится: `код`"
- Второе предложение: краткое объяснение что делает эта строка простыми словами
- ОБЯЗАТЕЛЬНО для if/for/while: напиши ЧТО сработает и ПОЧЕМУ (с конкретными значениями переменных)

Примеры для условий:

**Что дальше:**
Сейчас выполнится: `if mas[i] > mas[i+1]:`
Проверяем условие: mas[0] > mas[1], то есть 15 > 3, это правда — значит зайдём внутрь if.

**Что дальше:**
Сейчас выполнится: `for i in range(n):`
Начинаем цикл от 0 до 4 (потому что n = 5), первая итерация с i = 0.

**Что дальше:**
Сейчас выполнится: `while i < n:`
Проверяем: i < n, то есть 2 < 5, это правда — продолжаем цикл.
"""
        else:  # uk
            return """Ти — помічник-тренер з програмування для дітей. Пиши УКРАЇНСЬКОЮ мовою.

ВАЖЛИВО: НЕ використовуй LaTeX-формули. Пиши математику звичайним текстом.

У тебе є:
- ПОВНИЙ код програми
- "Currently executing line: X" - це рядок який БУДЕ виконано ЗАРАЗ (ще НЕ виконався!)
- Рядок помічено → - це рядок який ми ЗБИРАЄМОСЬ виконати
- Поточні значення змінних (стан ПЕРЕД виконанням поточного рядка)
- Історія розмови

ВАЖЛИВО: Якщо ми на рядку X, це значить:
- Рядки 1...(X-1) вже виконались
- Рядок X ще НЕ виконався, він виконається ЗАРАЗ
- Змінні показують стан ПІСЛЯ виконання рядка (X-1)

ФОРМАТ ВІДПОВІДІ (ОБОВ'ЯЗКОВО). КОЖЕН РОЗДІЛ — МАКС 2 РЕЧЕННЯ:

**Що сталось:**
1 коротке речення без термінів.

**Поточний стан:**
список змінних, кожна з нового рядка: `ім'я = значення`.

**Що далі:**
Зараз виконається: `точний рядок коду`
Одна фраза - що зробить цей рядок простими словами.

Приклад для `mas1=[mas[0]]`:

**Що далі:**
Зараз виконається: `mas1=[mas[0]]`
Створюємо список mas1 з першим числом зі списку mas.

Приклад для `mas=list(map(int,input().split()))`:

**Що далі:**
Зараз виконається: `mas=list(map(int,input().split()))`
Програма чекає введення чисел через пробіл і збереже їх у список mas.

ПРАВИЛА:
- Проста мова для дитини (8-12 років)
- БЕЗ емодзі
- БЕЗ складних термінів типа "функція", "метод", "ітератор"
- Пояснюй команди просто: що робить, а не як називається
- В розділі "Що далі:" — максимум 2 речення
- Перше речення: "Зараз виконається: `код`"
- Друге речення: коротке пояснення що робить цей рядок простими словами
- ОБОВ'ЯЗКОВО для if/for/while: напиши ЩО спрацює і ЧОМУ (з конкретними значеннями змінних)

Приклади для умов:

**Що далі:**
Зараз виконається: `if mas[i] > mas[i+1]:`
Перевіряємо умову: mas[0] > mas[1], тобто 15 > 3, це правда — значить зайдемо всередину if.

**Що далі:**
Зараз виконається: `for i in range(n):`
Починаємо цикл від 0 до 4 (бо n = 5), перша ітерація з i = 0.

**Що далі:**
Зараз виконається: `while i < n:`
Перевіряємо: i < n, тобто 2 < 5, це правда — продовжуємо цикл.

Приклад ДОБРОЇ відповіді (коли поточний рядок 4):
```
**Що сталось:**
На попередніх рядках 1-2 ми прочитали число n і список чисел mas.

**Поточний стан:**
n = 5
mas = [10, 15, 3, 8, 20]

**Що далі:**
Зараз виконається: `mas1=[mas[0]]`
Створюємо список mas1 з першим числом зі списку mas.
```

Приклад ПОГАНОЇ відповіді (один масив тексту):
"""

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
- НЕ используй LaTeX-формулы (пиши математику обычным текстом)

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
- НЕ використовуй LaTeX-формули (пиши математику звичайним текстом)

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
        logger.info(f"NORMAL MODE REQUEST (assistant: {self.__class__.__name__})")
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
        
        print(all_messages)
        # Send to API
        return self._send_to_api(system_prompt, all_messages)
    
    def _complete_debug_step(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Debug mode: step with explanation, NO history summarization"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        print("=" * 80)
        print("DEBUG MODE REQUEST")
        print("=" * 80)
        
        # Get debug prompt (DON'T CHANGE)
        system_prompt = self._get_debug_system_prompt()
        
        # Add debug context (execution_io already contains all needed context)
        #system_prompt = self._add_context_to_prompt(system_prompt, context)
        
        # Log system prompt with context
        print("SYSTEM PROMPT (with context):")
        print("-" * 80)
        print(system_prompt)
        print("-" * 80)
        
        # Log user messages
        print("USER MESSAGES:")
        print("-" * 80)
        for msg in context.messages:
            print(f"[{msg.role.value}]: {msg.content}")
        print("-" * 80)
        
        # NO summarization for debug
        # Prepare all messages as-is
        prepared_messages = self._prepare_messages(context.messages)
        
        # Send to API
        return self._send_to_api(system_prompt, prepared_messages)

    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Main entry point - routes to normal or debug mode"""
        from logging import getLogger
        logger = getLogger(__name__)
        
        logger.info(f"=" * 80)
        logger.info(f"COMPLETE_CHAT called for assistant: {self.__class__.__name__}")
        logger.info(f"=" * 80)
        
        # Check API key is configured
        if not self.get_ready():
            # API key not configured, return error
            yield ChatResponseChunk("API key not configured", is_final=False)
            yield ChatResponseChunk("", is_final=True)
            return
        
        # Check if this is a debug step explanation request
        last_message = context.messages[-1] if context.messages else None
        is_debug_step = last_message and last_message.is_debug_related if last_message else False
        
        if is_debug_step:
            yield from self._complete_debug_step(context)
        else:
            yield from self._complete_normal(context)

    def cancel_completion(self) -> None:
        """Cancel current completion (default: do nothing)"""
        pass
    
    def explain_line(self, line_num: int, line_content: str, full_code: str, debugger_msg = None, lang: str = "uk") -> str:
        """
        Request AI explanation for a specific line of code
        
        Args:
            line_num: Line number in the code
            line_content: The actual line of code to explain
            full_code: Full program code for context
            debugger_msg: Optional DebuggerResponse message (if in debug mode)
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
            # Get debug context if in debug mode
            execution_io = None
            if debugger_msg:
                from thonny.plugins.debug_common import get_debug_context_from_msg
                execution_io = get_debug_context_from_msg(debugger_msg)
            
            # Create context with custom system prompt
            context = ChatContext(
                messages=[ChatMessage(ChatRole.USER, user_prompt, [])],
                file_contents_by_path={'current_file': full_code},
                execution_io=execution_io,  # Add debug context if available
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

