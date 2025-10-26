#!/bin/bash
set -e

echo "=========================================="
echo "🔨 Создание universal2 пакетов: ruff и Pillow"
echo "=========================================="
echo ""

THONNY_ALT="$HOME/thonny_alt_packages"
PKGS_DIR="$THONNY_ALT/pkgs"
WORK_DIR="$THONNY_ALT/build_universal"

# Версии пакетов
RUFF_VERSION="0.14.2"
PILLOW_VERSION="12.0.0"
PYTHON_VERSION="312"  # 3.12

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

echo "📦 Скачиваем wheels для x86_64 и arm64..."
echo ""

# === RUFF ===
echo "⬇️  Ruff $RUFF_VERSION..."
pip download --no-deps \
    --platform macosx_10_12_x86_64 \
    --python-version $PYTHON_VERSION \
    --only-binary=:all: \
    ruff==$RUFF_VERSION \
    -d . 2>&1 | grep -v "Requirement already satisfied"

pip download --no-deps \
    --platform macosx_11_0_arm64 \
    --python-version $PYTHON_VERSION \
    --only-binary=:all: \
    ruff==$RUFF_VERSION \
    -d . 2>&1 | grep -v "Requirement already satisfied"

echo "✅ Ruff wheels скачаны"
echo ""

# === PILLOW ===
echo "⬇️  Pillow $PILLOW_VERSION..."
pip download --no-deps \
    --platform macosx_10_13_x86_64 \
    --python-version $PYTHON_VERSION \
    --only-binary=:all: \
    Pillow==$PILLOW_VERSION \
    -d . 2>&1 | grep -v "Requirement already satisfied"

pip download --no-deps \
    --platform macosx_11_0_arm64 \
    --python-version $PYTHON_VERSION \
    --only-binary=:all: \
    Pillow==$PILLOW_VERSION \
    -d . 2>&1 | grep -v "Requirement already satisfied"

echo "✅ Pillow wheels скачаны"
echo ""

# Извлечь wheels
echo "📂 Извлекаем wheels..."
mkdir -p ruff_x86_64 ruff_arm64 pillow_x86_64 pillow_arm64

unzip -q "ruff-${RUFF_VERSION}-py3-none-macosx_10_12_x86_64.whl" -d ruff_x86_64
unzip -q "ruff-${RUFF_VERSION}-py3-none-macosx_11_0_arm64.whl" -d ruff_arm64
unzip -q "pillow-${PILLOW_VERSION}-cp${PYTHON_VERSION}-cp${PYTHON_VERSION}-macosx_10_13_x86_64.whl" -d pillow_x86_64
unzip -q "pillow-${PILLOW_VERSION}-cp${PYTHON_VERSION}-cp${PYTHON_VERSION}-macosx_11_0_arm64.whl" -d pillow_arm64

echo "✅ Wheels извлечены"
echo ""

# === Создать universal2 RUFF ===
echo "🔨 Создаём universal2 ruff..."
mkdir -p "$PKGS_DIR/ruff"

# Объединить бинарник ruff
RUFF_X86="ruff_x86_64/ruff-${RUFF_VERSION}.data/scripts/ruff"
RUFF_ARM="ruff_arm64/ruff-${RUFF_VERSION}.data/scripts/ruff"
RUFF_UNIVERSAL="$PKGS_DIR/ruff/ruff"

if [ -f "$RUFF_X86" ] && [ -f "$RUFF_ARM" ]; then
    lipo -create "$RUFF_X86" "$RUFF_ARM" -output "$RUFF_UNIVERSAL"
    chmod +x "$RUFF_UNIVERSAL"
    echo "   ✅ ruff binary: $(lipo -info "$RUFF_UNIVERSAL")"
else
    echo "   ❌ Не найдены бинарники ruff"
    exit 1
fi

# Копировать Python файлы (они одинаковые для обеих архитектур)
cp -r ruff_x86_64/ruff/* "$PKGS_DIR/ruff/" 2>/dev/null || true

echo "✅ Ruff universal2 готов"
echo ""

# === Создать universal2 PILLOW ===
echo "🔨 Создаём universal2 Pillow (это займёт минуту - 34 файла)..."
mkdir -p "$PKGS_DIR/PIL"
mkdir -p "$PKGS_DIR/PIL/.dylibs"

# Копировать Python файлы (одинаковые)
cp -r pillow_x86_64/PIL/*.py "$PKGS_DIR/PIL/" 2>/dev/null || true
cp -r pillow_x86_64/PIL/resources "$PKGS_DIR/PIL/" 2>/dev/null || true

# Объединить все .so файлы
echo "   Объединяем .so файлы..."
for so_x86 in pillow_x86_64/PIL/*.so; do
    if [ -f "$so_x86" ]; then
        so_name=$(basename "$so_x86")
        so_arm="pillow_arm64/PIL/$so_name"
        so_universal="$PKGS_DIR/PIL/$so_name"
        
        if [ -f "$so_arm" ]; then
            lipo -create "$so_x86" "$so_arm" -output "$so_universal"
            echo "      ✓ $so_name"
        else
            echo "      ⚠️  $so_name: нет arm64 версии, копируем x86_64"
            cp "$so_x86" "$so_universal"
        fi
    fi
done

# Объединить все .dylib файлы
echo "   Объединяем .dylib файлы..."
for dylib_x86 in pillow_x86_64/PIL/.dylibs/*.dylib; do
    if [ -f "$dylib_x86" ]; then
        dylib_name=$(basename "$dylib_x86")
        dylib_arm="pillow_arm64/PIL/.dylibs/$dylib_name"
        dylib_universal="$PKGS_DIR/PIL/.dylibs/$dylib_name"
        
        if [ -f "$dylib_arm" ]; then
            lipo -create "$dylib_x86" "$dylib_arm" -output "$dylib_universal"
            echo "      ✓ $dylib_name"
        else
            echo "      ⚠️  $dylib_name: нет arm64 версии, копируем x86_64"
            cp "$dylib_x86" "$dylib_universal"
        fi
    fi
done

echo "✅ Pillow universal2 готов"
echo ""

# Проверка
echo "=========================================="
echo "✅ Universal2 пакеты готовы!"
echo "=========================================="
echo ""
echo "📍 Расположение: $PKGS_DIR"
echo ""
echo "Проверка ruff:"
lipo -info "$PKGS_DIR/ruff/ruff"
echo ""
echo "Проверка Pillow (примеры .so и .dylib):"
lipo -info "$PKGS_DIR/PIL/_imaging.cpython-312-darwin.so" 2>/dev/null || echo "   ⚠️  _imaging.so не найден"
lipo -info "$PKGS_DIR/PIL/.dylibs/libjpeg.62.4.0.dylib" 2>/dev/null || echo "   ⚠️  libjpeg не найден"
echo ""
echo "✅ Готово! Теперь можно запускать сборку bundle"
echo ""

