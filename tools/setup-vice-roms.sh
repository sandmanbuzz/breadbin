#!/bin/sh
# Fetch the C64 and 1541 ROMs that VICE needs to run the system tests.
#
# Distro VICE packages ship without ROMs. This downloads the ones VICE itself
# distributes from its source mirror. They are Commodore firmware: you are
# responsible for using them within their licence, and nothing here puts them
# in the repo.
#
#   tools/setup-vice-roms.sh [VICE_DATA_DIR]     (default /usr/share/vice)
#
# Then run the system tests headless:
#   xvfb-run -a make test
set -eu

DEST="${1:-/usr/share/vice}"
BASE="https://raw.githubusercontent.com/VICE-Team/svn-mirror/main/vice/data"

mkdir -p "$DEST/C64" "$DEST/DRIVES"
for f in \
    C64/kernal-901227-03.bin \
    C64/basic-901226-01.bin \
    C64/chargen-901225-01.bin \
    DRIVES/dos1541-325302-01+901229-05.bin \
    DRIVES/dos1541ii-251968-03.bin
do
    echo "fetching $f"
    curl -fsSL -o "$DEST/$f" "$BASE/$f"
done
echo "ROMs installed under $DEST"
