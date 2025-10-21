"""
AI Assistant for debugging - explains current step and predicts next step
"""
import logging
from typing import Iterator, Optional
from thonny import get_workbench
from thonny.assistance import Assistant, ChatContext, ChatMessage, ChatResponseChunk, Attachment
from thonny.plugins.debugger import get_current_debugger
from thonny.plugins.openai import OpenAIAssistant

logger = logging.getLogger(__name__)


class DebugAIAssistant(OpenAIAssistant):
    """
    Enhanced AI Assistant that can explain debugging steps
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
            
            context_parts.append(f"**Full Program Code:**")
            context_parts.append(f"File: {frame.filename}")
            context_parts.append(f"**Поточний рядок (який виконається ЗАРАЗ): {frame.lineno}** (помічено → нижче)")
            context_parts.append(f"```python")
            
            # Show entire program (up to 200 lines)
            max_lines = min(len(source_lines), 200)
            
            for i in range(max_lines):
                line_num = i + 1
                line = source_lines[i].rstrip()
                
                # Mark the current line with an arrow
                if line_num == frame.lineno:
                    prefix = "→ "  # Arrow for current line
                else:
                    prefix = "  "
                
                context_parts.append(f"{prefix}{line_num:3d} | {line}")
            
            if len(source_lines) > 200:
                context_parts.append(f"  ... ({len(source_lines) - 200} more lines)")
            
            context_parts.append(f"```")
            context_parts.append("")
        except Exception as e:
            # Fallback: show minimal info
            context_parts.append(f"**Current Location:**")
            context_parts.append(f"File: {frame.filename}")
            context_parts.append(f"Line: {frame.lineno}")
            context_parts.append("")
        
        # Local variables
        if frame.locals:
            context_parts.append(f"**Local Variables:**")
            for var_name, var_info in sorted(frame.locals.items()):
                if not var_name.startswith('__'):
                    # var_info is a ValueInfo object with 'repr' attribute
                    if hasattr(var_info, 'repr'):
                        var_repr = var_info.repr
                    elif isinstance(var_info, dict) and 'repr' in var_info:
                        var_repr = var_info['repr']
                    else:
                        var_repr = str(var_info)
                    context_parts.append(f"  {var_name} = {var_repr}")
            context_parts.append("")
        
        # Stack trace (if in function call)
        if len(msg.stack) > 1:
            context_parts.append(f"**Call Stack:**")
            for i, stack_frame in enumerate(reversed(msg.stack)):
                indent = "  " * i
                context_parts.append(f"{indent}→ {stack_frame.code_name} at {stack_frame.filename}:{stack_frame.lineno}")
            context_parts.append("")
        
        return "\n".join(context_parts)
    
    def complete_chat(self, context: ChatContext) -> Iterator[ChatResponseChunk]:
        """Enhanced completion with debug context"""
        from openai import OpenAI
        
        api_key = self._get_saved_api_key()
        if not api_key:
            yield ChatResponseChunk("Please configure OpenAI API key in Tools → Manage plug-ins", is_final=True, is_interal_error=True)
            return
        
        client = OpenAI(api_key=api_key)
        
        # Get the last user message
        last_message = context.messages[-1] if context.messages else None
        user_content = last_message.content if last_message else ""
        
        # Detect special debug commands
        prompt_override = None
        if "Що тут" in user_content or "🐛" in user_content:
            prompt_override = "Поясни що сталось на попередньому рядку і що станеться коли ми виконаємо поточний рядок (помічений →). Покажи поточні значення змінних."
        elif "Що далі" in user_content or "🔮" in user_content:
            prompt_override = "Поясни що станеться коли ми виконаємо поточний рядок (помічений →). Як зміняться змінні?"
        elif "Змінні" in user_content or "📊" in user_content:
            prompt_override = "Покажи всі поточні змінні та їх значення. Коротко поясни що кожна означає."
        
        # Build messages with debug context (localized)
        try:
            lang = get_workbench().get_option("ai.language", "uk")
        except Exception:
            lang = "uk"

        if lang == "ru":
            system_content = """Ты — помощник‑тренер по программированию для детей. Пиши РУССКИМ языком.

У тебя есть:
- ПОЛНЫЙ код программы
- "Currently executing line: X" — строка, которая выполнится СЕЙЧАС (ещё не выполнена!)
- Строка со стрелкой → — это строка, которую МЫ собираемся выполнить
- Текущие значения переменных (состояние ПЕРЕД выполнением текущей строки)
- История диалога

ВАЖНО: Если мы на строке X, значит:
- Строки 1...(X-1) уже выполнены
- Строка X ещё НЕ выполнена, она выполнится СЕЙЧАС
- Переменные показывают состояние ПОСЛЕ выполнения строки (X-1)

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО). КАЖДЫЙ РАЗДЕЛ — МАКС 2 ПРЕДЛОЖЕНИЯ:

**Что случилось:**
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
- БЕЗ складних термінів типу "функція", "метод", "ітератор"
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
Зараз виконається рядок 4 і створиться новий список mas1 з першого елемента mas.
```

Приклад ПОГАНОЇ відповіді (один масив тексту):
"На рядку 2 ми читаємо список чисел з вводу та перетворюємо їх у цілі числа. Зараз змінна mas буде порожньою..."

Форматування Markdown:
- **жирний** для заголовків секцій
                - `код` для коду"""

        messages = [
            {
                "role": "system",
                "content": system_content,
            }
        ]
        
        # Add debug context if available
        debug_ctx = self.get_debug_context()
        if debug_ctx:
            messages.append({
                "role": "system",
                "content": f"Current debugging context:\n{debug_ctx}"
            })
        
        # Add conversation history
        for msg in context.messages[:-1]:  # All except last
            messages.append({
                "role": msg.role,
                "content": self.format_message(msg)
            })
        
        # Add the last message (possibly with override)
        if last_message:
            content_to_send = prompt_override if prompt_override else self.format_message(last_message)
            messages.append({
                "role": last_message.role,
                "content": content_to_send
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

