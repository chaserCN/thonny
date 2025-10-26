#!/bin/bash
set -e
# https://github.com/lektor/lektor/blob/master/gui/bin/make-python-framework-relocatable

# Take from env
# LOCAL_FRAMEWORKS=$HOME/thonny_template_build_312/Thonny.app/Contents/Frameworks

VERSION=3.12 # Also look below for removing older versions from the copy
ORIGINAL_FRAMEWORK_PATH=/Library/Frameworks/Python.framework
NEW_FRAMEWORK_PATH=$LOCAL_FRAMEWORKS/Python.framework

rm -rf $NEW_FRAMEWORK_PATH
mkdir -p $NEW_FRAMEWORK_PATH

cp -R $ORIGINAL_FRAMEWORK_PATH/* $NEW_FRAMEWORK_PATH

rm -rf $NEW_FRAMEWORK_PATH/Versions/3.9
rm -rf $NEW_FRAMEWORK_PATH/Versions/3.10
rm -rf $NEW_FRAMEWORK_PATH/Versions/3.11
rm -rf $NEW_FRAMEWORK_PATH/Versions/3.13


BIN_EXE=$NEW_FRAMEWORK_PATH/Versions/$VERSION/bin/python$VERSION

# delete everything in bin except python3.12
#find $NEW_FRAMEWORK_PATH/Versions/$VERSION/bin -type f -maxdepth 1 ! -name python$VERSION -delete

# Make main binaries and libraries relocatable
BUNDLE_EXE=$NEW_FRAMEWORK_PATH/Versions/$VERSION/Resources/Python.app/Contents/MacOS/Python
ORIG_MAIN_LIB=$ORIGINAL_FRAMEWORK_PATH/Versions/$VERSION/Python
NEW_MAIN_LIB=$NEW_FRAMEWORK_PATH/Versions/$VERSION/Python
MAIN_LIB_LOCAL_NAME=@rpath/Python.framework/Versions/$VERSION/Python

chmod u+w $NEW_MAIN_LIB $BIN_EXE $BUNDLE_EXE

install_name_tool -change $ORIG_MAIN_LIB $MAIN_LIB_LOCAL_NAME $BIN_EXE 
install_name_tool -add_rpath @executable_path/../../../../ $BIN_EXE

install_name_tool -id @rpath/Python.framework/Versions/$VERSION/Python $NEW_MAIN_LIB


install_name_tool -change $ORIG_MAIN_LIB $MAIN_LIB_LOCAL_NAME $BUNDLE_EXE
install_name_tool -add_rpath @executable_path/../../../../../../../ $BUNDLE_EXE

# update tkinter links (Python 3.12 uses Frameworks instead of lib dylibs, so these may not exist)
if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtcl8.6.dylib" ]; then
    chmod 0755 $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtcl8.6.dylib
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libtcl8.6.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libtcl8.6.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtcl8.6.dylib
fi

if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtk8.6.dylib" ]; then
    chmod 0755 $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtk8.6.dylib
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libtk8.6.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libtk8.6.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libtk8.6.dylib
fi

# Find the correct _tkinter module (version may vary)
TKINTER_SO=$(find $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/python3.12/lib-dynload -name "_tkinter*.so" | head -1)
if [ -n "$TKINTER_SO" ] && [ -f "$TKINTER_SO" ]; then
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libtcl8.6.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libtcl8.6.dylib \
        "$TKINTER_SO" 2>/dev/null || true

    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libtk8.6.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libtk8.6.dylib \
        "$TKINTER_SO" 2>/dev/null || true
fi

# update libcrypto and libssl links (may not exist in Python 3.12)
if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib" ]; then
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib
fi

if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libssl.1.1.dylib" ]; then
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libssl.1.1.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libssl.1.1.dylib
    
    if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib" ]; then
        install_name_tool -change \
            /Library/Frameworks/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib \
            @rpath/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib \
            $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libssl.1.1.dylib
    fi
fi

SSL_SO=$(find $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/python3.12/lib-dynload -name "_ssl*.so" | head -1)
if [ -n "$SSL_SO" ] && [ -f "$SSL_SO" ]; then
    if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib" ]; then
        install_name_tool -change \
            /Library/Frameworks/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib \
            @rpath/Python.framework/Versions/3.12/lib/libcrypto.1.1.dylib \
            "$SSL_SO" 2>/dev/null || true
    fi
    
    if [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libssl.1.1.dylib" ]; then
        install_name_tool -change \
            /Library/Frameworks/Python.framework/Versions/3.12/lib/libssl.1.1.dylib \
            @rpath/Python.framework/Versions/3.12/lib/libssl.1.1.dylib \
            "$SSL_SO" 2>/dev/null || true
    fi
fi

# update curses links (wrap in checks)
[ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libncursesw.5.dylib" ] && \
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libncursesw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libncursesw.5.dylib || true

[ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libformw.5.dylib" ] && \
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libformw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libformw.5.dylib && \
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libformw.5.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libformw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libformw.5.dylib || true

[ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libmenuw.5.dylib" ] && \
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libmenuw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libmenuw.5.dylib && \
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libmenuw.5.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libmenuw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libmenuw.5.dylib || true

[ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libpanelw.5.dylib" ] && \
    install_name_tool -id \
        @rpath/Python.framework/Versions/3.12/lib/libpanelw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libpanelw.5.dylib && \
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libpanelw.5.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libpanelw.5.dylib \
        $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libpanelw.5.dylib || true

CURSES_SO=$(find $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/python3.12/lib-dynload -name "_curses.*.so" | head -1)
[ -n "$CURSES_SO" ] && [ -f "$CURSES_SO" ] && [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libncursesw.5.dylib" ] && \
    install_name_tool -change \
        /Library/Frameworks/Python.framework/Versions/3.12/lib/libncursesw.5.dylib \
        @rpath/Python.framework/Versions/3.12/lib/libncursesw.5.dylib \
        "$CURSES_SO" 2>/dev/null || true

CURSES_PANEL_SO=$(find $LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/python3.12/lib-dynload -name "_curses_panel*.so" | head -1)
if [ -n "$CURSES_PANEL_SO" ] && [ -f "$CURSES_PANEL_SO" ]; then
    [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libncursesw.5.dylib" ] && \
        install_name_tool -change \
            /Library/Frameworks/Python.framework/Versions/3.12/lib/libncursesw.5.dylib \
            @rpath/Python.framework/Versions/3.12/lib/libncursesw.5.dylib \
            "$CURSES_PANEL_SO" 2>/dev/null || true
    
    [ -f "$LOCAL_FRAMEWORKS/Python.framework/Versions/3.12/lib/libpanelw.5.dylib" ] && \
        install_name_tool -change \
            /Library/Frameworks/Python.framework/Versions/3.12/lib/libpanelw.5.dylib \
            @rpath/Python.framework/Versions/3.12/lib/libpanelw.5.dylib \
            "$CURSES_PANEL_SO" 2>/dev/null || true
fi


# copy the token signifying Thonny-private Python
cp thonny_python.ini $NEW_FRAMEWORK_PATH/Versions/$VERSION/bin 

# create link to Current version (required by codesign)
cd $LOCAL_FRAMEWORKS/Python.framework/Versions
rm Current
ln -s $VERSION Current
