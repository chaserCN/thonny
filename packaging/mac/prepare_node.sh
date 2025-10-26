#!/bin/bash
set -e

echo "=========================================="
echo "📦 Подготовка universal Node.js для Thonny"
echo "=========================================="
echo ""

NODE_VERSION="v20.11.0"
THONNY_ALT="$HOME/thonny_alt_packages"
NODE_DIR="$THONNY_ALT/node_temp"

mkdir -p "$NODE_DIR"
cd "$NODE_DIR"

echo "📥 Скачивание Node.js $NODE_VERSION..."
echo ""

# Скачать x86_64
if [ ! -f "node-${NODE_VERSION}-darwin-x64.tar.gz" ]; then
    echo "  Скачиваем x86_64 версию..."
    curl -LO "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-darwin-x64.tar.gz"
else
    echo "  ✅ x86_64 версия уже скачана"
fi

# Скачать arm64
if [ ! -f "node-${NODE_VERSION}-darwin-arm64.tar.gz" ]; then
    echo "  Скачиваем arm64 версию..."
    curl -LO "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-darwin-arm64.tar.gz"
else
    echo "  ✅ arm64 версия уже скачана"
fi

echo ""
echo "📂 Извлечение..."

# Извлечь x86_64
if [ ! -f "node-x86_64" ]; then
    tar -xzf "node-${NODE_VERSION}-darwin-x64.tar.gz"
    cp "node-${NODE_VERSION}-darwin-x64/bin/node" "node-x86_64"
    echo "  ✅ Извлечён node x86_64"
fi

# Извлечь arm64
if [ ! -f "node-arm64" ]; then
    tar -xzf "node-${NODE_VERSION}-darwin-arm64.tar.gz"
    cp "node-${NODE_VERSION}-darwin-arm64/bin/node" "node-arm64"
    echo "  ✅ Извлечён node arm64"
fi

echo ""
echo "🔧 Создание universal binary..."

# Создать universal binary
lipo -create "node-x86_64" "node-arm64" -output "node-universal"

echo ""
echo "✅ Проверка:"
lipo -info "node-universal"

# Копировать в thonny_alt_packages
cp "node-universal" "$THONNY_ALT/node"
chmod +x "$THONNY_ALT/node"

# Очистка
cd "$THONNY_ALT"
rm -rf "$NODE_DIR"

echo ""
echo "=========================================="
echo "✅ Node.js готов!"
echo "=========================================="
echo ""
echo "Расположение: $THONNY_ALT/node"
echo "Размер: $(du -h "$THONNY_ALT/node" | cut -f1)"
echo ""
echo "Теперь можно запускать ./create_release.sh"
echo ""

