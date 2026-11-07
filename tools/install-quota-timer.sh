#!/bin/sh
# Install (or remove) the user-level systemd timer that runs `claude-quota poll --quiet`.
# DRY RUN by default: prints what it would do and changes nothing. Pass --yes to act.
#
#   tools/install-quota-timer.sh [--yes]              install and enable the timer
#   tools/install-quota-timer.sh --uninstall [--yes]  disable it and remove the units
#
# Env: QUOTA_UNIT_DIR  where the units go (default $HOME/.config/systemd/user)
set -eu

yes=0
uninstall=0
for arg in "$@"; do
    case "$arg" in
        --yes) yes=1 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
case "$repo" in
    *[!A-Za-z0-9_./+-]*) echo "repo path has characters unsafe for a unit file: $repo" >&2; exit 2 ;;
esac
src="$here/systemd"
dest=${QUOTA_UNIT_DIR:-${HOME:?HOME not set}/.config/systemd/user}
units="claude-quota.service claude-quota.timer"

# run CMD...: print it; execute only with --yes
run() {
    echo "+ $*"
    if [ "$yes" = 1 ]; then "$@"; fi
}

render() { sed "s|@REPO@|$repo|g" "$src/$1"; }

if [ "$yes" = 0 ]; then
    echo "DRY RUN: nothing will be changed (pass --yes to act)"
fi

if [ "$uninstall" = 1 ]; then
    run systemctl --user disable --now claude-quota.timer
    for u in $units; do run rm -f "$dest/$u"; done
    run systemctl --user daemon-reload
    exit 0
fi

echo "units go to: $dest"
for u in $units; do
    echo "--- $u"
    render "$u"
done
echo "---"
run mkdir -p "$dest"
for u in $units; do
    echo "+ write $dest/$u"
    if [ "$yes" = 1 ]; then render "$u" > "$dest/$u"; fi
done
run systemctl --user daemon-reload
run systemctl --user enable --now claude-quota.timer
