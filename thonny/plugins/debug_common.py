"""
Common utilities for debug AI assistants (OpenAI and Gemini)
"""
from typing import Optional
from thonny import get_workbench
from thonny.plugins.debugger import get_current_debugger


def get_debug_context_from_msg(msg) -> Optional[str]:
    """Get debugging context from a specific DebuggerResponse message
    
    This function should be used to capture context at a specific moment,
    avoiding race conditions when debugger state changes.
    """
    if not msg or not hasattr(msg, 'stack'):
        return None
        
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
        file_label = "Файл"  # Localized label for both uk/ru
        context_parts.append(f"{file_label}: {frame.filename}")
        
        # Show both previous and current line info
        prev_line = frame.lineno - 1 if frame.lineno > 1 else None
        
        if lang == "uk":
            if prev_line:
                context_parts.append(f"**Попередній рядок (щойно виконаний): {prev_line}**")
            context_parts.append(f"**ПОТОЧНИЙ рядок (виконається ЗАРАЗ): {frame.lineno}** ← помічено → нижче")
        else: # ru
            if prev_line:
                context_parts.append(f"**Предыдущая строка (только что выполнена): {prev_line}**")
            context_parts.append(f"**ТЕКУЩАЯ строка (выполнится СЕЙЧАС): {frame.lineno}** ← помечена → ниже")
        
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
    if frame.globals or frame.locals:
        lang = get_workbench().get_option("ai.language", "uk")
        if lang == "uk":
            context_parts.append(f"\n**Поточні змінні (стан ПЕРЕД виконанням рядка {frame.lineno}):**")
        else: # ru
            context_parts.append(f"\n**Текущие переменные (состояние ПЕРЕД выполнением строки {frame.lineno}):**")
        
        # Combine globals and locals
        all_vars = {}
        if frame.globals:
            all_vars.update(frame.globals)
        if frame.locals:
            all_vars.update(frame.locals)
        
        # Filter out internal Python variables
        display_vars = {
            k: v for k, v in all_vars.items() 
            if not k.startswith('__')
        }

        # Determine order of appearance in source up to current line
        ordered_names: list[str] = []
        try:
            import io
            import tokenize as _tokenize

            # Read source again (already loaded above). Use only lines before current line
            lines_before_current = []
            try:
                import tokenize
                with tokenize.open(frame.filename) as fp:
                    all_lines = fp.readlines()
                lines_before_current = all_lines[: max(0, frame.lineno - 1)]
            except Exception:
                lines_before_current = []

            seen = set()
            if lines_before_current and display_vars:
                names_set = set(display_vars.keys())
                src = "".join(lines_before_current)
                for tok in _tokenize.generate_tokens(io.StringIO(src).readline):
                    if tok.type == _tokenize.NAME:
                        name = tok.string
                        if name in names_set and name not in seen:
                            ordered_names.append(name)
                            seen.add(name)
                        # small optimization: break if all found
                        if len(seen) == len(names_set):
                            break
        except Exception:
            # Fallback to no ordering info on error
            ordered_names = []

        if display_vars:
            # Names seen in source first, then the rest in insertion order
            remaining_names = [n for n in display_vars.keys() if n not in set(ordered_names)]
            final_names = ordered_names + remaining_names

            for var_name in final_names:
                var_info = display_vars[var_name]
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


def get_system_prompt(lang: str = "uk") -> str:
    """Get system prompt for debug AI assistant based on language"""
    
    if lang == "ru":
        return """Ты — помощник-тренер по программированию для детей. Пиши на РУССКОМ языке.

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
    else:  # uk
        return """Ти — помічник-тренер з програмування для дітей. Пиши УКРАЇНСЬКОЮ мовою.

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


def get_debug_context() -> Optional[str]:
    """Get current debugging context from debugger's last message
    
    DEPRECATED: This reads from debugger._last_progress_message which may
    change during execution. Prefer get_debug_context_from_msg() for
    capturing context at a specific moment.
    """
    debugger = get_current_debugger()
    if not debugger or not debugger._last_progress_message:
        return None
    
    return get_debug_context_from_msg(debugger._last_progress_message)

