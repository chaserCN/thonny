# 🔍 LSP можливості в Thonny

## Порівняння Ruff vs Pyright

| LSP можливість | Ruff | Pyright (basedpyright) | Використовується в Thonny |
|----------------|------|------------------------|---------------------------|
| **📝 Діагностика (Diagnostics)** | ✅ Лінтинг (стиль коду, помилки) | ✅ Перевірка типів | ✅ **ТАК** (`diagnostic_highlighter.py`) |
| **💡 Автодоповнення (Completion)** | ❌ | ✅ | ✅ **ТАК** (`autocomplete.py`) |
| **📖 Підказки (Hover)** | ❌ | ✅ | ✅ **ТАК** (вбудовано в codeview) |
| **📌 Підпис функції (SignatureHelp)** | ❌ | ✅ | ✅ **ТАК** (`calltip.py`) |
| **🔗 Перехід до визначення (Definition)** | ❌ | ✅ | ✅ **ТАК** (`goto_definition.py`) |
| **✨ Підсвічування входжень (DocumentHighlight)** | ❌ | ✅ | ✅ **ТАК** (`highlight_names.py`) |
| **🔍 Пошук посилань (References)** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |
| **♻️ Перейменування (Rename)** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |
| **📋 Символи документа (DocumentSymbol)** | ❌ | ✅ | ✅ **ТАК** (в outline view) |
| **🔧 Швидкі виправлення (CodeAction)** | ✅ "Fix" + "Organize imports" | ✅ "QuickFix" + "Organize imports" | ❌ НІ (не реалізовано в Thonny) |
| **🎨 Форматування (Formatting)** | ✅ (Ruff format) | ❌ | ❌ НІ (не реалізовано в Thonny) |
| **🌈 Семантичні токени (SemanticTokens)** | ❌ | ✅ | ❌ НІ (Thonny має свій підсвічувач синтаксису) |
| **🔎 Декларації (Declaration)** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |
| **🎯 Визначення типу (TypeDefinition)** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |
| **🏗️ Ієрархія викликів (CallHierarchy)** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |
| **💭 Inlay Hints** | ❌ | ✅ | ❌ НІ (не реалізовано в Thonny) |

---

## Детальний опис використаних можливостей

### ✅ Що працює зараз

#### 1. **Діагностика (Diagnostics)**
- **Від Ruff**: Лінтинг коду (E402, F401, тощо)
- **Від Pyright**: Перевірка типів (type errors, missing imports)
- **Файл**: `thonny/plugins/diagnostic_highlighter.py`
- **Поведінка**: Підкреслення помилок червоним/жовтим + tooltip з описом

#### 2. **Автодоповнення (Completion)**
- **Від Pyright**: Підказки методів, змінних, параметрів
- **Файл**: `thonny/plugins/autocomplete.py`
- **Тригери**: `.`, `[`, `"`, `'`, або Ctrl+Space
- **Поведінка**: Випадаючий список з документацією

#### 3. **Підпис функції (SignatureHelp)**
- **Від Pyright**: Показує параметри функції при введенні `(`
- **Файл**: `thonny/plugins/calltip.py`
- **Тригери**: `(`, `,`, `)`
- **Поведінка**: Спливаюча підказка з параметрами

#### 4. **Перехід до визначення (GoTo Definition)**
- **Від Pyright**: Cmd+Click (macOS) або Ctrl+Click (Windows/Linux)
- **Файл**: `thonny/plugins/goto_definition.py`
- **Поведінка**: Відкриває файл з визначенням функції/класу

#### 5. **Підсвічування входжень (DocumentHighlight)**
- **Від Pyright**: Підсвічує всі входження змінної при кліку
- **Файл**: `thonny/plugins/highlight_names.py`
- **Поведінка**: Жовті рамки навколо однакових імен

#### 6. **Символи документа (DocumentSymbol)**
- **Від Pyright**: Список класів/функцій/методів
- **Використання**: Outline view (бічна панель)

---

## 🚀 Що можна додати в майбутньому

### Високий пріоритет

#### 1. **Швидкі виправлення (CodeAction)** 🔥
**Ruff пропонує**:
- Auto-fix для лінтинг помилок
- Organize imports (сортування та видалення невикористаних)

**Pyright пропонує**:
- Quick fixes для type errors
- Add missing imports

**Як додати**:
```python
# В новому файлі thonny/plugins/code_actions.py
ls_proxy.request_code_action(
    CodeActionParams(...),
    handler
)
```

#### 2. **Форматування коду (Formatting)** 🎨
**Ruff може**:
- Форматувати код (як Black, але швидше)
- Можна додати в меню "Tools > Format Code"

**Як додати**:
```python
ls_proxy.request_formatting(
    DocumentFormattingParams(...),
    handler
)
```

### Середній пріоритет

#### 3. **Пошук посилань (Find References)** 🔍
- Показати всі місця, де використовується змінна/функція
- Корисно для рефакторингу

#### 4. **Перейменування (Rename)** ♻️
- Перейменувати змінну у всіх місцях одночасно
- Pyright підтримує це

### Низький пріоритет

#### 5. **Inlay Hints** 💭
- Показувати типи змінних inline
- Може бути корисно для навчання

---

## 🎯 Поточна конфігурація

### Pyright (basedpyright 1.32.1)
```python
{
    "analysis": {
        "diagnosticMode": "openFilesOnly",  # Тільки відкриті файли
        "autoSearchPaths": False,           # Не шукати автоматично
        "autoImportCompletions": False,     # Не сканувати пакети
        "useLibraryCodeForTypes": False,    # Не використовувати код бібліотек
        "extraPaths": []                    # Порожній список шляхів
    }
}
```

**Результат**: ~110-120 MB пам'яті, стабільно ✅

### Ruff (увімкнений)
```python
# Просто запускається як: python -m ruff server
# Конфігурація читається з pyproject.toml
```

**Результат**: Швидка діагностика, мінімальне споживання ресурсів ✅

---

## 📊 Статистика використання

| Компонент | Пам'ять | Функції | Стан |
|-----------|---------|---------|------|
| **Pyright** | ~110-120 MB | Типи, автодоповнення, підсвічування | ✅ Працює |
| **Ruff** | ~20-30 MB | Діагностика (лінтинг) | ✅ Працює |
| **Разом** | ~130-150 MB | Повний LSP досвід | ✅ Стабільно |

---

## 🔗 Корисні посилання

- [Basedpyright GitHub](https://github.com/DetachHead/basedpyright)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [LSP Specification](https://microsoft.github.io/language-server-protocol/)
- [Thonny Plugins](https://github.com/thonny/thonny/tree/master/thonny/plugins)

