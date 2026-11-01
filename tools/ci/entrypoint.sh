#!/bin/sh
# Container entrypoint: install the mounted ROMs, copy the (read-only) repo to a private
# work tree, run make under a virtual display.
set -eu
if [ -d /roms ]; then
    for sub in C64 DRIVES; do
        [ -d "/roms/$sub" ] && { mkdir -p "/usr/share/vice/$sub"; cp -R "/roms/$sub/." "/usr/share/vice/$sub/"; }
    done
fi
if [ -d /src ]; then
    # private copy: concurrent runs must not share build/ or each other's files
    mkdir -p /work
    tar -C /src --exclude=./build --exclude=./.git -cf - . | tar -C /work -xf -
fi
cd /work
xvfb-run -a -s "-screen 0 1280x1024x24" make "$@"
exit $?
