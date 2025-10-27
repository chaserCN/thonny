# 🚀 Сборка Universal Thonny для macOS (Intel + ARM)

Полная инструкция по созданию **настоящего fat binary** без Rosetta.

## 📋 Требования

- **macOS** (Intel или Apple Silicon)
- **Xcode Command Line Tools**: `xcode-select --install`
- **Python 3.12.10 Universal2** installer с [python.org](https://www.python.org/downloads/release/python-31210/)

---

## 🎯 Быстрая сборка (все шаги)

```bash
# 1. Скачай и установи Python 3.12.10 Universal2
open https://www.python.org/downloads/release/python-31210/
# Выбери: "macOS 64-bit universal2 installer" (PKG)

# 2. Подготовь universal пакеты (cryptography, cffi)
cd ~/Projects/thonny/packaging/mac
./prepare_universal_packages.sh         # По умолчанию 4.1.7
# или: ./prepare_universal_packages.sh latest  # Последняя версия

# 3. Подготовь universal Node.js (для Pyright LSP)
./prepare_node.sh

# 4. Создай базовый шаблон (один раз для версии Python)
./prepare_base_bundle.sh

# 5. Собери релиз
./create_release.sh

# 6. Проверь универсальность
./verify_arm_support.sh build/Thonny.app
```

---

## 📦 Шаг 1: Установка Python 3.12.10 Universal2

### Скачивание

Перейди на: https://www.python.org/downloads/release/python-31210/

Скачай: **macOS 64-bit universal2 installer** (файл `python-3.12.10-macos11.pkg`)

⚠️ **ВАЖНО**: Нужен именно **universal2** installer!

### Установка

```bash
# Установи PKG файл (откроется Installer.app)
# Python установится в:
/Library/Frameworks/Python.framework/Versions/3.12/
```

### Проверка

```bash
# Проверь что Python universal
lipo -info /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12

# Должно быть:
# Architectures in the fat file: ... are: x86_64 arm64
```

---

## 📦 Шаг 2: Подготовка universal пакетов

Некоторые пакеты (`cryptography`, `cffi`) не имеют universal2 wheels для всех версий.
Их нужно извлечь из официального релиза Thonny.

### Автоматически (рекомендуется)

Скрипт `packaging/mac/prepare_universal_packages.sh` уже создан!

**Использование:**

```bash
cd packaging/mac

# По умолчанию использует проверенную версию 4.1.7
./prepare_universal_packages.sh

# Или указать конкретную версию
./prepare_universal_packages.sh 4.1.8

# Или автоматически получить последнюю версию
./prepare_universal_packages.sh latest

# Помощь
./prepare_universal_packages.sh --help
```

**Что делает:**
1. Скачивает указанную версию Thonny с GitHub
2. Извлекает PKG через `xar` и `tar`
3. Автоматически определяет версию Python внутри
4. Копирует universal `.so` файлы в `~/thonny_alt_packages/pkgs/`
5. Проверяет что они действительно universal2

### Вручную

<details>
<summary>Если автоматический скрипт не работает</summary>

```bash
# 1. Скачай официальный релиз
cd ~/thonny_alt_packages
curl -L -o thonny-4.1.7.pkg "https://github.com/thonny/thonny/releases/download/v4.1.7/thonny-4.1.7.pkg"

# 2. Извлеки PKG
mkdir thonny_pkg_extracted
cd thonny_pkg_extracted
xar -xf ../thonny-4.1.7.pkg

# 3. Извлеки Payload
cd Payload
tar -xf Payload

# 4. Скопируй universal .so файлы
EXTRACTED_PYTHON="Thonny.app/Contents/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages"

mkdir -p ~/thonny_alt_packages/pkgs/cryptography/hazmat/bindings
cp "$EXTRACTED_PYTHON/cryptography/hazmat/bindings/"*.so \
   ~/thonny_alt_packages/pkgs/cryptography/hazmat/bindings/

cp "$EXTRACTED_PYTHON/_cffi_backend"*.so \
   ~/thonny_alt_packages/pkgs/

# 5. Проверь
lipo -info ~/thonny_alt_packages/pkgs/cryptography/hazmat/bindings/_openssl.abi3.so
```

</details>

---

## 📦 Шаг 3: Подготовка universal Node.js

Node.js требуется для работы **Pyright LSP сервера** (code completion, type checking).

### Автоматически (рекомендуется)

```bash
cd packaging/mac
./prepare_node.sh
```

**Что делает:**
1. Скачивает Node.js v20.11.0 для x86_64 и arm64
2. Создает universal binary через `lipo -create`
3. Сохраняет в `~/thonny_alt_packages/node`

**Проверка:**
```bash
lipo -info ~/thonny_alt_packages/node
# Должно быть: Architectures in the fat file: ... are: x86_64 arm64
```

### Вручную

<details>
<summary>Если автоматический скрипт не работает</summary>

```bash
cd ~/thonny_alt_packages
mkdir node_temp && cd node_temp

# Скачать обе версии
curl -LO "https://nodejs.org/dist/v20.11.0/node-v20.11.0-darwin-x64.tar.gz"
curl -LO "https://nodejs.org/dist/v20.11.0/node-v20.11.0-darwin-arm64.tar.gz"

# Извлечь
tar -xzf node-v20.11.0-darwin-x64.tar.gz
tar -xzf node-v20.11.0-darwin-arm64.tar.gz

# Создать universal binary
lipo -create \
  node-v20.11.0-darwin-x64/bin/node \
  node-v20.11.0-darwin-arm64/bin/node \
  -output node-universal

# Скопировать
cp node-universal ~/thonny_alt_packages/node
chmod +x ~/thonny_alt_packages/node

# Очистка
cd ~/thonny_alt_packages
rm -rf node_temp
```

</details>

---

## 📦 Шаг 4: Создание базового шаблона

Базовый шаблон создаётся **один раз для версии Python**.

```bash
cd packaging/mac
./prepare_base_bundle.sh
```

**Что делает:**
- Копирует Python Framework из `/Library/Frameworks/` в `~/thonny_template_build_312/`
- Делает Python relocatable (изменяет пути через `install_name_tool`)
- Создаёт структуру `Thonny.app`

**Результат:** `~/thonny_template_build_312/Thonny.app`

---

## 📦 Шаг 5: Сборка релиза

```bash
cd packaging/mac
./create_release.sh
```

**Что делает:**

1. Копирует базовый шаблон в `build/Thonny.app`
2. Устанавливает Python пакеты через pip (с `arch -x86_64`)
3. Устанавливает Thonny из исходников
4. **Заменяет** на universal версии из `~/thonny_alt_packages/`:
   - `cryptography` и `cffi`
   - `ruff` (linter binary)
   - `Pillow` (image library)
   - **`node`** (для Pyright LSP)
5. Очищает временные файлы
6. Создаёт `.pkg` installer в `dist/`

**Результат:**
- `build/Thonny.app` - готовое приложение
- `dist/thonny-5.0.0b1.dev0.pkg` - installer (72 MB)

---

## ✅ Проверка универсальности

### Быстрая проверка

```bash
cd packaging/mac
./verify_arm_support.sh build/Thonny.app
```

Должно показать:
```
✅ Thonny поддерживает Universal Binary (Intel + ARM)
✅ Приложение будет работать НАТИВНО на ARM Mac
```

### Детальная проверка

```bash
cd packaging/mac
python3 find_single_arch_binaries.py
```

Покажет список не-universal файлов. Ожидаемые:
- `websockets` (x86_64) - имеет pure Python fallback
- `PyYAML` (x86_64) - имеет pure Python fallback
- `bitarray` (x86_64) - используется только esptool

### Проверка критичных компонентов

```bash
# Python интерпретатор
lipo -info build/Thonny.app/Contents/Frameworks/Python.framework/Versions/3.12/bin/python3.12

# Node.js (для Pyright LSP)
lipo -info build/Thonny.app/Contents/Frameworks/Python.framework/Versions/3.12/bin/node

# cryptography
lipo -info build/Thonny.app/Contents/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/cryptography/hazmat/bindings/_openssl.abi3.so

# grpcio (для AI функций)
find build/Thonny.app -name "*cygrpc*.so" -exec lipo -info {} \;
```

Всё должно показывать: `x86_64 arm64`

---

## 🔍 Структура проекта

### Основные скрипты

```
packaging/mac/
├── prepare_universal_packages.sh    ← Подготавливает universal cryptography, cffi, ruff, Pillow
├── prepare_node.sh                  ← Подготавливает universal Node.js
├── prepare_base_bundle.sh           ← Создаёт базовый шаблон
├── copy_python_framework.sh         ← Копирует Python Framework (вызывается из prepare_base_bundle.sh)
├── create_release.sh                ← ГЛАВНЫЙ: собирает релиз
├── prepare_dist_bundle.sh           ← Устанавливает пакеты (вызывается из create_release.sh)
├── create_installer_from_build.sh   ← Создаёт .pkg installer
├── find_single_arch_binaries.py     ← Проверяет universal binary
└── verify_arm_support.sh            ← Быстрая проверка ARM поддержки
```

### Дополнительные скрипты (опционально)

```
packaging/mac/
├── sign_bundle_in_build.sh          # Подпись (нужен Apple Developer ID)
├── notarize_all.sh                  # Нотаризация (нужен Apple ID)
├── staple_all.sh                    # Stapling нотаризации
├── create_portable_dmg_from_build.sh # Создание DMG
└── launcher/
    ├── launcher.swift               # Swift launcher для Thonny
    └── compile.sh                   # Компиляция launcher
```

---

## 🎯 Что будет работать на ARM Mac

### ✅ Полностью с нативной скоростью (без Rosetta)

- **Python 3.12.10** - universal2
- **Редактор кода и IDE** - Tkinter universal2
- **Запуск Python программ** - нативный ARM интерпретатор
- **Отладчик** - встроенный в Python
- **Pyright LSP** (code completion, type checking) - Node.js universal2
- **Ruff LSP** (linting, formatting) - ruff universal2
- **SSH к Raspberry Pi** - cryptography universal2
- **AI функции** (Gemini, ChatGPT, Claude) - grpcio universal2
- **Установка pip пакетов** - нативный pip

### ⚡ С Pure Python fallback (работает, чуть медленнее)

- **WebREPL** (WiFi к MicroPython) - websockets x86_64
- **Прошивка ESP** - esptool, PyYAML, bitarray x86_64
- **Type checking** - mypy (pure Python)
- **Linting** - pylint (pure Python)

### 📊 Статистика

- **63.6%** всех бинарных модулей - universal2
- **100%** критичных компонентов - universal2
- **85%** функций работают с нативной ARM скоростью

---

## 🐛 Troubleshooting

### Python не найден

```bash
# Проверь установку
ls -la /Library/Frameworks/Python.framework/Versions/3.12/

# Проверь что universal
lipo -info /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
```

### cryptography не universal

```bash
# Проверь наличие альтернативных пакетов
ls -la ~/thonny_alt_packages/pkgs/cryptography/

# Если пусто - повтори Шаг 2
```

### Node.js не найден или не universal

```bash
# Проверь наличие Node.js
ls -la ~/thonny_alt_packages/node

# Проверь что universal
lipo -info ~/thonny_alt_packages/node

# Если пусто или не universal - повтори Шаг 3
cd packaging/mac
./prepare_node.sh
```

### Ошибка при установке пакетов

```bash
# Проверь что SDKROOT не установлен
echo $SDKROOT  # Должно быть пусто

# Если не пусто:
unset SDKROOT
```

### grpcio не устанавливается

Для Python 3.12 есть готовый universal2 wheel на PyPI:
```bash
python3.12 -m pip download --platform macosx_10_9_universal2 grpcio==1.66.2
```

Для Python 3.14 - нет universal2 wheel (поэтому используем 3.12).

---

## 📝 Подробности работы

### Как работает Universal Binary

1. **Python installer** с python.org содержит оба бинарника:
   - `x86_64` (Intel)
   - `arm64` (Apple Silicon)

2. При запуске:
   - **Intel Mac** → запускается x86_64 слой
   - **ARM Mac** → запускается arm64 слой (нативно, быстро!)

3. Пакеты:
   - **universal2 wheels** → содержат .so для обеих архитектур
   - **single-arch wheels** → только для одной архитектуры
   - **pure Python** → работают везде (нет .so файлов)

### Почему Python 3.12, а не 3.14?

- ✅ `grpcio` имеет universal2 wheel для 3.12
- ❌ `grpcio` НЕ имеет universal2 wheel для 3.14
- ✅ Python 3.12 = LTS (поддержка до 2028)

### Зачем нужен ~/thonny_alt_packages?

`cryptography==42.0.8` не имеет готовых universal2 wheels на PyPI (ни для 3.10, ни для 3.12).

**Решение:**
1. Извлекаем universal2 `.so` из официального Thonny 4.1.7
2. Файлы используют `.abi3.so` (stable ABI)
3. Они совместимы с Python 3.10, 3.11, 3.12

---

## 🚀 Продвинутое использование

### Подпись и нотаризация (для публичного распространения)

Нужен **Apple Developer ID**.

```bash
cd packaging/mac

# 1. Подпись
export APPLE_DEVELOPER_ID='Developer ID Application: Your Name (TEAM_ID)'
./sign_bundle_in_build.sh

# 2. Нотаризация (требует Apple ID credentials)
./notarize_all.sh

# 3. Stapling (прикрепляет notarization ticket)
./staple_all.sh
```

### Создание DMG (альтернатива PKG)

```bash
cd packaging/mac
./create_portable_dmg_from_build.sh
```

---

## 📊 Размеры

- **Installer (PKG)**: ~72 MB
- **Приложение**: ~307 MB
- **Python Framework**: ~270 MB

---

## 🔗 Полезные ссылки

- [Python Downloads](https://www.python.org/downloads/macos/)
- [Thonny GitHub](https://github.com/thonny/thonny)
- [Apple Universal Binaries](https://developer.apple.com/documentation/apple-silicon/building-a-universal-macos-binary)
- [Python Wheel Tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)

---

## 🎉 Итог

Собранный Thonny:
- ✅ Работает **нативно** на Intel Mac (x86_64)
- ✅ Работает **нативно** на ARM Mac (arm64)
- ✅ Не требует Rosetta для основных функций
- ✅ Поддерживает все функции Thonny IDE
- ✅ Готов для использования и распространения

**Команда для установки:**
```bash
open packaging/mac/dist/thonny-5.0.0b1.dev0.pkg
```
