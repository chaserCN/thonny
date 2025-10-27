#!/bin/bash
set -e

# Note that pip is run in x86_64 mode, so only Intel packages may get installed at first
# This is later amended (look for thonny_alt_packages)

VERSION=$1
shift
req_files="$@"

PREFIX=$HOME/thonny_template_build_312
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# prepare working folder #########################################################
rm -rf build
mkdir -p build


# copy template #################################################
cp -R -H $PREFIX/Thonny.app build

# update template (might have changed after last create_base_bundle.sh) #####################
cp $SCRIPT_DIR/Thonny.app.initial_template/Contents/MacOS/* \
    build/Thonny.app/Contents/MacOS
cp $SCRIPT_DIR/Thonny.app.initial_template/Contents/Resources/* \
    build/Thonny.app/Contents/Resources
cp $SCRIPT_DIR/Thonny.app.initial_template/Contents/Info.plist \
    build/Thonny.app/Contents

FRAMEWORKS=build/Thonny.app/Contents/Frameworks
PYTHON_CURRENT=$FRAMEWORKS/Python.framework/Versions/3.12

# install #####################################################
export MACOSX_DEPLOYMENT_TARGET=10.9
# export SDKROOT=~/MacOSX10.9.sdk  # Not needed for modern builds

echo "Using $PYTHON_CURRENT/bin/python3.12"
arch -x86_64 $PYTHON_CURRENT/bin/python3.12 -s -m pip install --no-cache-dir wheel

for req_file in $req_files
do
	echo "installing from $req_file"
	arch -x86_64 $PYTHON_CURRENT/bin/python3.12  -s -m pip install --no-binary mypy --no-binary lxml -r $req_file
done
arch -x86_64 $PYTHON_CURRENT/bin/python3.12 -s -m pip install --no-cache-dir certifi
arch -x86_64 $PYTHON_CURRENT/bin/python3.12 -s -m pip install --pre --no-cache-dir "thonny==${VERSION}"
#$PYTHON_CURRENT/bin/python3.12 -s -m pip install ../setuptools/thonny-4.1.0b1.dev0-py3-none-any.whl

rm $PYTHON_CURRENT/bin/thonny # because Thonny is not supposed to run from there

# make the packages more universal
# assuming $HOME/thonny_alt_packages/pkgs contains compatible universal2 version of cryptography
# and arm64 version of cffi
if [ -d "$HOME/thonny_alt_packages/pkgs" ]; then
    echo "Copying alternative universal packages..."
    cp $HOME/thonny_alt_packages/pkgs/cryptography/hazmat/bindings/*.so \
      $PYTHON_CURRENT/lib/python3.12/site-packages/cryptography/hazmat/bindings 2>/dev/null || true
    
    cp $HOME/thonny_alt_packages/pkgs/_cffi_backend.cpython-312-darwin.so \
      $PYTHON_CURRENT/lib/python3.12/site-packages/_cffi_backend.cpython-312-darwin-arm46.so 2>/dev/null || true
    
    # Copy universal2 ruff
    if [ -f "$HOME/thonny_alt_packages/pkgs/ruff/ruff" ]; then
        echo "  Copying universal2 ruff..."
        cp -f "$HOME/thonny_alt_packages/pkgs/ruff/ruff" "$PYTHON_CURRENT/bin/ruff"
        chmod +x "$PYTHON_CURRENT/bin/ruff"
        # Copy Python files
        cp -r "$HOME/thonny_alt_packages/pkgs/ruff"/*.py "$PYTHON_CURRENT/lib/python3.12/site-packages/ruff/" 2>/dev/null || true
    fi
    
    # Copy universal2 Pillow (PIL)
    if [ -d "$HOME/thonny_alt_packages/pkgs/PIL" ]; then
        echo "  Copying universal2 Pillow..."
        rm -rf "$PYTHON_CURRENT/lib/python3.12/site-packages/PIL"
        cp -r "$HOME/thonny_alt_packages/pkgs/PIL" "$PYTHON_CURRENT/lib/python3.12/site-packages/"
    fi
    
    # Copy universal2 Node.js (required for Pyright LSP)
    if [ -f "$HOME/thonny_alt_packages/node" ]; then
        echo "  Copying universal2 Node.js..."
        cp -f "$HOME/thonny_alt_packages/node" "$PYTHON_CURRENT/bin/node"
        chmod +x "$PYTHON_CURRENT/bin/node"
        # Verify it's universal
        echo "  Verifying Node.js architecture:"
        lipo -info "$PYTHON_CURRENT/bin/node" || echo "  Warning: lipo check failed"
    else
        echo "  Warning: Universal Node.js not found at $HOME/thonny_alt_packages/node"
        echo "  Pyright LSP will not work! Run ./prepare_node.sh first."
    fi
else
    echo "Warning: $HOME/thonny_alt_packages/pkgs not found, relying on pip-installed packages..."
fi

# save some space ###################################################
rm -rf $FRAMEWORKS/Tcl.framework/Versions/8.6/Tcl_debug
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Tk_debug
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Resources/Scripts/demos
rm -rf $FRAMEWORKS/Tcl.framework/Versions/8.6/Resources/Documentation
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Resources/Documentation

rm -rf $PYTHON_CURRENT/Resources/English.lproj/Documentation

rm -rf $PYTHON_CURRENT/share

rm -rf $PYTHON_CURRENT/lib/python3.12/test
rm -rf $PYTHON_CURRENT/lib/python3.12/distutils/test
rm -rf $PYTHON_CURRENT/lib/python3.12/lib2to3/test
rm -rf $PYTHON_CURRENT/lib/python3.12/unittest/test

rm -rf $PYTHON_CURRENT/lib/python3.12/idlelib
rm -rf $PYTHON_CURRENT/bin/idle3
rm -rf $PYTHON_CURRENT/bin/idle3.12

rm -rf $PYTHON_CURRENT/lib/python3.12/site-packages/pylint/test
rm -rf $PYTHON_CURRENT/lib/python3.12/site-packages/mypy/test

find $PYTHON_CURRENT/lib -name '*.pyc' -delete
find $PYTHON_CURRENT/lib -name '*.exe' -delete

# for some reason the notarizer doesn't like txt files in these packages
find $PYTHON_CURRENT/lib/python3.12/site-packages/lxml -name '*.txt' -delete       || true
find $PYTHON_CURRENT/lib/python3.12/site-packages/matplotlib -name '*.txt' -delete || true


# create link to Python.app interpreter
cd build/Thonny.app/Contents/MacOS
ln -s ../Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python Python
cd $SCRIPT_DIR


# copy the token signifying Thonny-private Python
cp thonny_python.ini $PYTHON_CURRENT/bin 

./make_scripts_relocatable.py "$PYTHON_CURRENT/bin" 




# set version info ##############################################################
sed -i '' "s/VERSION/$VERSION/" build/Thonny.app/Contents/Info.plist



