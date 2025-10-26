#!/bin/bash
# Скрипт для проверки поддержки ARM на собранном Thonny
set -e

echo "=========================================="
echo "🔍 Проверка ARM поддержки Thonny"
echo "=========================================="
echo ""

APP_PATH="${1:-build/Thonny.app}"

if [ ! -d "$APP_PATH" ]; then
    echo "❌ Приложение не найдено: $APP_PATH"
    echo "Использование: $0 [путь_к_Thonny.app]"
    exit 1
fi

PYTHON_PATH="$APP_PATH/Contents/Frameworks/Python.framework/Versions/3.12"

echo "Проверяемое приложение: $APP_PATH"
echo ""

# Проверка основных компонентов
echo "1️⃣  Python интерпретатор:"
if lipo -info "$PYTHON_PATH/bin/python3.12" | grep -q "arm64"; then
    echo "   ✅ Поддерживает ARM64"
else
    echo "   ❌ НЕ поддерживает ARM64"
    exit 1
fi

echo ""
echo "2️⃣  Критичные пакеты:"

# cryptography
if [ -f "$PYTHON_PATH/lib/python3.12/site-packages/cryptography/hazmat/bindings/_openssl.abi3.so" ]; then
    if lipo -info "$PYTHON_PATH/lib/python3.12/site-packages/cryptography/hazmat/bindings/_openssl.abi3.so" | grep -q "arm64"; then
        echo "   ✅ cryptography - ARM64"
    else
        echo "   ❌ cryptography - только x86_64"
    fi
else
    echo "   ⚠️  cryptography не найден"
fi

# grpcio
GRPC_SO=$(find "$PYTHON_PATH/lib/python3.12/site-packages/grpc" -name "*.so" | head -1)
if [ -n "$GRPC_SO" ]; then
    if lipo -info "$GRPC_SO" | grep -q "arm64"; then
        echo "   ✅ grpcio - ARM64"
    else
        echo "   ❌ grpcio - только x86_64"
    fi
else
    echo "   ⚠️  grpcio не найден"
fi

echo ""
echo "3️⃣  Версия Python:"
"$PYTHON_PATH/bin/python3.12" --version

echo ""
echo "=========================================="
echo "📊 Итог проверки:"
echo "=========================================="

# Финальная проверка
if lipo -info "$PYTHON_PATH/bin/python3.12" | grep -q "x86_64 arm64"; then
    echo "✅ Thonny поддерживает Universal Binary (Intel + ARM)"
    echo "✅ Приложение будет работать НАТИВНО на ARM Mac"
    echo ""
    echo "Можно устанавливать на:"
    echo "  • Intel Mac (x86_64)"
    echo "  • Apple Silicon Mac (arm64)"
    exit 0
else
    echo "❌ Приложение НЕ universal"
    exit 1
fi

