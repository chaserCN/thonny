"""
AI Assistant for debugging using Gemini - explains current step and predicts next step
"""
import logging
from typing import Iterator, Optional
from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, Attachment
from thonny.plugins.debugger import get_current_debugger
from thonny.plugins.gemini import GeminiAssistant

logger = logging.getLogger(__name__)


class DebugGeminiAssistant(GeminiAssistant):
    """
    Enhanced Gemini AI Assistant that can explain debugging steps
    """
    
    def get_debug_context(self) -> Optional[str]:
        """Get current debugging context: variables, current line, stack"""
        debugger = get_current_debugger()
        if not debugger or not debugger._last_progress_message:
            return None
            
        msg = debugger._last_progress_message
        if not msg.stack:
            return None
            
        # Get current frame (top of stack)
        frame = msg.stack[-1]
        
        context_parts = []
        
        # Full program code with current line marked
        try:
            import tokenize
            with tokenize.open(frame.filename) as fp:
                source_lines = fp.readlines()
            
            lang = get_workbench().get_option("ai.language", "uk")
            
            context_parts.append(f"**Full Program Code:**")
            context_parts.append(f"File: {frame.filename}")
            
            if lang == "uk":
                context_parts.append(f"**Поточний рядок (який виконається ЗАРАЗ): {frame.lineno}** (помічено → нижче)")
            else: # ru
                context_parts.append(f"**Текущая строка (которая выполнится СЕЙЧАС): {frame.lineno}** (помечена → ниже)")
            
            context_parts.append(f"```python")
            
            # Show entire program (up to 200 lines)
            max_lines = min(len(source_lines), 200)
            
            for i in range(max_lines):
                line_num = i + 1
                line = source_lines[i].rstrip()
                
                if line_num == frame.lineno:
                    context_parts.append(f"→ {line_num:4d} | {line}")
                else:
                    context_parts.append(f"  {line_num:4d} | {line}")
            
            if len(source_lines) > max_lines:
                context_parts.append(f"... ({len(source_lines) - max_lines} more lines)")
            
            context_parts.append("```")
        except Exception as e:
            context_parts.append(f"(Could not read source code: {e})")
        
        # Variables
        if msg.globals or msg.locals:
            if lang == "uk":
                context_parts.append(f"\n**Поточні змінні (стан ПЕРЕД виконанням рядка {frame.lineno}):**")
            else: # ru
                context_parts.append(f"\n**Текущие переменные (состояние ПЕРЕД выполнением строки {frame.lineno}):**")
            
            # Combine globals and locals
            all_vars = {}
            if msg.globals:
                all_vars.update(msg.globals)
            if msg.locals:
                all_vars.update(msg.locals)
            
            # Filter out internal Python variables
            display_vars = {
                k: v for k, v in all_vars.items() 
                if not k.startswith('__')
            }
            
            if display_vars:
                for var_name, var_info in sorted(display_vars.items()):
                    # Extract repr from ValueInfo or dict
                    if hasattr(var_info, 'repr'):
                        var_repr = var_info.repr
                    elif isinstance(var_info, dict) and 'repr' in var_info:
                        var_repr = var_info['repr']
                    else:
                        var_repr = str(var_info)
                    
                    context_parts.append(f"  {var_name} = {var_repr}")
            else:
                if lang == "uk":
                    context_parts.append("  (немає змінних)")
                else: # ru
                    context_parts.append("  (нет переменных)")
        
        return "\n".join(context_parts)
    
    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Enhanced chat completion with debug context"""
        import google.generativeai as genai
        
        genai.configure(api_key=self._get_saved_api_key())
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        lang = get_workbench().get_option("ai.language", "uk")
        
        # Get debug context
        debug_context = self.get_debug_context()
        
        # Detect special debug commands and override prompt
        user_content = context.messages[-1].content if context.messages else ""
        prompt_override = None
        
        if lang == "uk":
            if "Що тут" in user_content or "🐛" in user_content:
                prompt_override = "Поясни що сталось на попередньому рядку і що станеться коли ми виконаємо поточний рядок (помічений →). Покажи поточні значення змінних."
            elif "Що далі" in user_content or "🔮" in user_content:
                prompt_override = "Поясни що станеться коли ми виконаємо поточний рядок (помічений →). Як зміняться змінні?"
            elif "Змінні" in user_content or "📊" in user_content:
                prompt_override = "Покажи всі поточні змінні та їх значення. Коротко поясни що кожна означає."
        else: # ru
            if "Что здесь" in user_content or "🐛" in user_content:
                prompt_override = "Объясни, что произошло на предыдущей строке и что произойдет, когда выполнится текущая строка (помечена →). Покажи текущие значения переменных."
            elif "Что дальше" in user_content or "🔮" in user_content:
                prompt_override = "Объясни, что произойдет, когда выполнится текущая строка (помечена →). Как изменятся переменные?"
            elif "Переменные" in user_content or "📊" in user_content:
                prompt_override = "Покажи все текущие переменные и их значения. Кратко объясни, что каждая означает."
        
        # Build system prompt based on language
        if lang == "ru":
            system_content = """Ты — помощник-тренер по программированию для детей. Пиши на РУССКОМ языке.

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

Разбор:
- короткий пункт 1
- короткий пункт 2
- короткий пункт 3

Итог: одна итоговая фраза.

Пример для `mas1=[mas[0]]`:

Сейчас выполнится: `mas1=[mas[0]]`

Разбор:
- mas1 — имя для нового списка
- [mas[0]] — берём первое число из списка mas и создаём новый список
- mas[0] — это первое число в списке mas

Итог: создаём список mas1 с одним числом из списка mas

Пример для `mas=list(map(int,input().split()))`:

Сейчас выполнится: `mas=list(map(int,input().split()))`

Разбор:
- input() — ждём, когда пользователь введёт что-то с клавиатуры
- split() — разделяет введённый текст на кусочки по пробелам
- int — превращает каждый кусочек текста в число
- list(...) — собирает все числа в список mas

Итог: программа ждёт ввода чисел через пробел и сохранит их в список mas

ПРАВИЛА:
- Простой язык для ребёнка (8–12 лет)
- БЕЗ эмодзи
- БЕЗ сложных терминов типа "функция", "метод", "итератор"
- Объясняй команды просто: что делает, а не как называется
- Каждый раздел — максимум 2 коротких предложения (или список до 3 пунктов)
- Если в строке есть квадратные скобки, обязательно добавь пункт:
  - `[]` — создаёт новый список
  - `[x]` — список с одним элементом `x`
  - `[a, b]` — список из элементов `a` и `b`

УНИВЕРСАЛЬНО (токены/лексемы):
- Разбивай следующую строку кода на маленькие части (токены)
- Кратко объясняй 2–3 ключевых токена из строки:
  - `()` — вызов функции или группировка
  - `[]` — создание списка или доступ по индексу
  - `{}` — словарь или множество
  - `=` — присваиваем значение
  - `:` — двоеточие (в срезах, после if/for/def)
  - `.` — обращение к методу или свойству
"""
        else:
            system_content = """Ти — помічник-тренер з програмування для дітей. Пиши УКРАЇНСЬКОЮ мовою.

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

Розбір:
- короткий пункт 1
- короткий пункт 2
- короткий пункт 3

Отже: одна підсумкова фраза.

Приклад для `mas1=[mas[0]]`:

Зараз виконається: `mas1=[mas[0]]`

Розбір:
- mas1 — ім'я для нового списку
- [mas[0]] — беремо перше число зі списку mas і створюємо новий список
- mas[0] — це перше число у списку mas

Отже: створюємо список mas1 з одним числом зі списку mas

Приклад для `mas=list(map(int,input().split()))`:

Зараз виконається: `mas=list(map(int,input().split()))`

Розбір:
- input() — чекаємо, поки користувач введе щось з клавіатури
- split() — розділяє введений текст на шматочки по пробілах
- int — перетворює кожен шматочок тексту на число
- list(...) — збирає всі числа у список mas

Отже: програма чекає введення чисел через пробіл і збереже їх у список mas

ПРАВИЛА:
- Проста мова для дитини (8-12 років)
- БЕЗ емодзі
- БЕЗ складних термінів типа "функція", "метод", "ітератор"
- Пояснюй команди просто: що робить, а не як називається
- Кожна секція — максимум 2 короткі речення (або список до 3 пунктів)
- Не використовуй «;», пиши кожен пункт з нового рядка
- Якщо в рядку є квадратні дужки, обов'язково додай пункт:
  - `[]` — створює новий список
  - `[x]` — список з одним елементом `x`
  - `[a, b]` — список з елементів `a` та `b`

УНІВЕРСАЛЬНО (токени/лексеми):
- Розбивай наступний рядок коду на маленькі частини (токени)
- Коротко пояснюй 2–3 ключові токени з рядка:
  - `()` — виклик функції або групування
  - `[]` — створення списку або доступ за індексом
  - `{}` — словник або множина
  - `=` — присвоюємо значення
  - `:` — двокрапка (у зрізах, після if/for/def)
  - `.` — звернення до методу або властивості

Приклад ДОБРОЇ відповіді (коли поточний рядок 4):
```
**Що сталось:**
На попередніх рядках 1-2 ми прочитали число n і список чисел mas.

**Поточний стан:**
n = 5
mas = [10, 15, 3, 8, 20]

**Що далі:**
Зараз виконається: `mas1=[mas[0]]`

Розбір:
- mas1 — ім'я для нового списку
- [mas[0]] — беремо перше число зі списку mas і створюємо новий список
- mas[0] — це перше число у списку mas

Отже: створюємо список mas1 з одним числом зі списку mas
```

Приклад ПОГАНОЇ відповіді (один масив тексту):
"""
        
        # Build messages
        history = []
        
        # Add system message as first user message (Gemini doesn't support system role)
        history.append({
            "role": "user",
            "parts": [system_content]
        })
        history.append({
            "role": "model",
            "parts": ["Зрозумів! Готовий пояснювати код для дітей." if lang == "uk" else "Понял! Готов объяснять код для детей."]
        })
        
        # Add chat history
        for msg in context.messages[:-1]:
            role = "user" if msg.role == "user" else "model"
            content = self.format_message(msg)
            
            # Add debug context to assistant messages if available
            if msg.role == "assistant" and debug_context:
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
        else:
            final_content_parts.append(self.format_message(context.messages[-1]))
        
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

