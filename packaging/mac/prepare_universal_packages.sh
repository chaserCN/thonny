#!/bin/bash
set -e

# Показать help
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Использование: $0 [version]"
    echo ""
    echo "Извлекает universal пакеты (cryptography, cffi) из официального релиза Thonny"
    echo ""
    echo "Примеры:"
    echo "  $0           # Использовать версию 4.1.7 (по умолчанию, проверенная)"
    echo "  $0 4.1.8     # Использовать конкретную версию"
    echo "  $0 latest    # Автоматически получить последнюю версию с GitHub"
    echo ""
    exit 0
fi

echo "=========================================="
echo "📦 Подготовка universal пакетов для Thonny"
echo "=========================================="
echo ""

# Версия Thonny для извлечения пакетов
VERSION="${1:-4.1.7}"

# Если указано "latest" - получить последнюю версию
if [ "$VERSION" = "latest" ]; then
    echo "🔍 Получаем последнюю версию Thonny с GitHub..."
    VERSION=$(curl -s https://api.github.com/repos/thonny/thonny/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
    echo "✅ Последняя версия: $VERSION"
    echo ""
fi

THONNY_ALT="$HOME/thonny_alt_packages"
PKGS_DIR="$THONNY_ALT/pkgs"

# Создай директории
mkdir -p "$THONNY_ALT"
cd "$THONNY_ALT"

# Скачай официальный Thonny
PKG_FILE="thonny-${VERSION}.pkg"
if [ ! -f "$PKG_FILE" ]; then
    echo "⬇️  Скачиваем официальный Thonny $VERSION (это займёт минуту)..."
    curl -L -o "$PKG_FILE" "https://github.com/thonny/thonny/releases/download/v${VERSION}/thonny-${VERSION}.pkg"
    echo "✅ Скачивание завершено"
else
    echo "✅ Thonny $VERSION уже скачан"
fi

echo ""

# Извлеки PKG
EXTRACT_DIR="thonny_pkg_extracted_${VERSION}"
if [ ! -d "$EXTRACT_DIR" ]; then
    echo "📂 Извлекаем PKG (это займёт пару минут)..."
    mkdir -p "$EXTRACT_DIR"
    cd "$EXTRACT_DIR"
    xar -xf "../$PKG_FILE"
    echo "   Извлекаем Payload..."
    cd Payload
    tar -xf Payload
    cd ../..
    echo "✅ Извлечение завершено"
else
    echo "✅ PKG уже извлечён"
fi

echo ""

# Найди версию Python в извлечённом Thonny
echo "🔍 Определяем версию Python в Thonny $VERSION..."
PYTHON_VERSIONS=$(ls "$EXTRACT_DIR/Payload/Thonny.app/Contents/Frameworks/Python.framework/Versions/" | grep -E '^[0-9]+\.[0-9]+$')
PYTHON_VER=$(echo "$PYTHON_VERSIONS" | tail -1)

if [ -z "$PYTHON_VER" ]; then
    echo "❌ Не найдена версия Python в извлечённом Thonny"
    exit 1
fi

echo "✅ Найден Python $PYTHON_VER"
echo ""

# Найди и скопируй universal файлы
echo "📦 Копируем universal пакеты..."
EXTRACTED_PYTHON="$EXTRACT_DIR/Payload/Thonny.app/Contents/Frameworks/Python.framework/Versions/$PYTHON_VER/lib/python$PYTHON_VER/site-packages"

if [ ! -d "$EXTRACTED_PYTHON" ]; then
    echo "❌ Ошибка: не найден путь $EXTRACTED_PYTHON"
    exit 1
fi

mkdir -p "$PKGS_DIR/cryptography/hazmat/bindings"

# cryptography (использует stable ABI .abi3.so - совместим с Python 3.12)
echo "   Копируем cryptography..."
cp "$EXTRACTED_PYTHON/cryptography/hazmat/bindings/_"*.so "$PKGS_DIR/cryptography/hazmat/bindings/" 2>/dev/null || {
    echo "❌ Ошибка при копировании cryptography"
    exit 1
}

# cffi
echo "   Копируем cffi..."
cp "$EXTRACTED_PYTHON/_cffi_backend"*.so "$PKGS_DIR/" 2>/dev/null || {
    echo "❌ Ошибка при копировании cffi"
    exit 1
}

echo ""
echo "=========================================="
echo "✅ Universal пакеты готовы!"
echo "=========================================="
echo ""
echo "Файлы cryptography:"
ls -lh "$PKGS_DIR/cryptography/hazmat/bindings/" | grep ".so"
echo ""
echo "Файлы cffi:"
ls -lh "$PKGS_DIR/"*.so 2>/dev/null || true
echo ""
echo "Проверка архитектуры cryptography:"
CRYPTO_SO=$(find "$PKGS_DIR/cryptography" -name "_openssl*.so" | head -1)
if [ -f "$CRYPTO_SO" ]; then
    lipo -info "$CRYPTO_SO"
    echo ""
    echo "✅ Готово! Теперь можно запускать ./prepare_base_bundle.sh"
else
    echo "⚠️  Внимание: не найден файл _openssl.so"
    echo "   Проверьте содержимое $PKGS_DIR/cryptography/"
fi
echo ""

