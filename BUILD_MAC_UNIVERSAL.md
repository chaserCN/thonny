# Сборка Universal Thonny для macOS (Intel + ARM)

## Краткая инструкция

### 1. Установка Python (один раз)

Скачай и установи **Python 3.12 Universal** с python.org:
```bash
# Скачай "macOS 64-bit universal2 installer" (PKG)
open https://www.python.org/downloads/macos/
```

⚠️ **ВАЖНО:** Нужен именно **universal2** installer, который содержит x86_64 + arm64!

Установится в: `/Library/Frameworks/Python.framework/Versions/3.12/`

### 2. Создание базового шаблона (один раз)

```bash
cd packaging/mac
./prepare_base_bundle.sh
```

Создаёт: `~/thonny_template_build_312/Thonny.app` - базовый шаблон с Python Framework

### 3. Сборка релиза (каждый релиз)

```bash
cd packaging/mac
./create_release.sh
```

Результат: `dist/thonny-<version>.pkg` - готовый installer

### 4. Проверка Universal Binary

```bash
cd packaging/mac
python3 find_single_arch_binaries.py
```

Если вывод пустой → всё universal! ✅

Или вручную:
```bash
file build/Thonny.app/Contents/MacOS/thonny
# Должно быть: Mach-O universal binary with 2 architectures: [x86_64:...] [arm64:...]

lipo -info build/Thonny.app/Contents/MacOS/thonny
# Должно быть: Architectures in the fat file: ... are: x86_64 arm64
```

---

## Подпись и нотаризация (для публичного распространения)

```bash
# Экспортируй Apple Developer ID
export APPLE_DEVELOPER_ID='Developer ID Application: Your Name (TEAM_ID)'

# Подпись
./sign_bundle_in_build.sh

# Нотаризация (нужны Apple ID credentials)
./notarize_all.sh

# Stapling
./staple_all.sh
```

---

## Структура проекта

```
packaging/mac/
├── prepare_base_bundle.sh       # Создаёт базовый шаблон
├── create_release.sh            # Создаёт релиз
├── copy_python_framework.sh     # Копирует Python Framework
├── sign_bundle_in_build.sh      # Подписывает bundle
├── notarize_all.sh              # Нотаризует в Apple
├── staple_all.sh                # Прикрепляет notarization ticket
├── find_single_arch_binaries.py # Проверяет universal binary
└── launcher/
    ├── launcher.swift           # Swift launcher
    └── compile.sh               # Компилирует launcher как universal
```

---

## Как работает Universal Binary

1. **Python installer с python.org** уже содержит оба бинарника:
   - `x86_64` (Intel)
   - `arm64` (Apple Silicon)

2. При копировании Framework оба бинарника сохраняются

3. При запуске:
   - На Intel Mac → запускается x86_64 слой
   - На ARM Mac → запускается arm64 слой (native, быстрее)
   - Под Rosetta 2 → запускается x86_64 слой (эмуляция)

---

## Важные детали

### Python пакеты
- pip устанавливает wheel файлы для обеих архитектур (если доступны)
- Если пакет не имеет universal wheel → установится только для текущей архитектуры

### Tkinter
- Официальный Python installer включает Tcl/Tk 8.6 как universal binary
- Скрипт `copy_python_framework.sh` обновляет пути с помощью `install_name_tool`

### Pygments и другие зависимости
- Pure Python пакеты → работают на обеих архитектурах
- C-extensions → должны иметь universal wheels

---

## Требования

- **macOS 10.13+** (для сборки)
- **Xcode Command Line Tools**:
  ```bash
  xcode-select --install
  ```
- **Python 3.12 Universal installer** с python.org
- **(Опционально) Apple Developer ID** для подписи и нотаризации

---

## Troubleshooting

### Проблема: Некоторые бинарники single-arch

```bash
python3 find_single_arch_binaries.py
# Показывает файлы, которые не universal
```

**Решение:**
- Проверь, что Python installer был universal2
- Проверь, что pip пакеты установлены с universal wheels
- Для C-extensions может понадобиться пересборка

### Проблема: Bundle не запускается

```bash
# Проверь подпись
codesign -dv --verbose=4 build/Thonny.app

# Проверь зависимости
otool -L build/Thonny.app/Contents/MacOS/thonny
```

---

## Версия Thonny

Текущая версия: `5.0.0b1.dev0`

Версия указана в: `thonny/VERSION`

---

## Быстрая команда (всё в одну строку)

```bash
# Полная сборка с нуля
cd packaging/mac && \
./prepare_base_bundle.sh && \
./create_release.sh && \
python3 find_single_arch_binaries.py && \
open dist/
```

---

## Ссылки

- [Python.org Downloads](https://www.python.org/downloads/macos/)
- [Apple Notarization Guide](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Thonny Website](https://thonny.org)

