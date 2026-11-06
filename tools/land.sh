#!/bin/sh
# Land a branch on the current branch (local main) only if the merged tree passes the host suite.
#
#   tools/with-lock -r land -- sh tools/land.sh BRANCH [MESSAGE]
#
# Stops before committing if the merge conflicts or the suite is red: the merge is aborted and the
# tree is left as it was. The suite runs after make clean, on the merged tree itself, so stale build
# output cannot make a green branch look red (or the reverse). The build comes first: without build/ the
# tests that need the kernel skip (77 of 299) and the gate proves less. See docs/process.md, "Landing".
set -eu

branch=${1:?usage: land.sh BRANCH [MESSAGE]}
msg=${2:-"Merge $branch"}

# CLAUDE.md: commits go out as sandmanbuzz only; refuse before anything is merged if the identity git
# would use (environment or config) is anything else.
for who in GIT_AUTHOR_IDENT GIT_COMMITTER_IDENT; do
    case "$(git var $who)" in
        *"<344811358+sandmanbuzz@users.noreply.github.com>"*) ;;
        *) echo "land: $who is not the sandmanbuzz identity; nothing merged" >&2; exit 1 ;;
    esac
done

if [ -n "$(git status --porcelain)" ]; then
    echo "land: working tree is not clean; nothing merged" >&2
    # Name each dirty file and its owner (best effort: the author of the last commit that touched it).
    git status --porcelain | while IFS= read -r line; do
        f=${line#???}
        f=${f##* -> }
        who=$(git log -1 --format=%an -- "$f" 2>/dev/null || true)
        echo "land:   $f  (${who:-uncommitted (no owner)})" >&2
    done
    exit 1
fi
if ! git rev-parse --verify --quiet "$branch^{commit}" >/dev/null; then
    echo "land: no such branch: $branch" >&2
    exit 1
fi

if git merge-base --is-ancestor "$branch" HEAD; then
    echo "land: $branch is already in $(git rev-parse --abbrev-ref HEAD); nothing to land"
    exit 0
fi

# Whatever fails after the merge starts (conflict, red suite, a failing commit such as a passphrase
# prompt with no agent), the merge is aborted, so the primary is never left mid-merge.
abort_if_merging() {
    if [ -f "$(git rev-parse --git-path MERGE_HEAD)" ]; then git merge --abort; fi
}
trap abort_if_merging EXIT

if ! git merge --no-ff --no-commit "$branch"; then
    echo "land: $branch does not merge cleanly; aborted, resolve on the branch and try again" >&2
    exit 1
fi

# make test-host skips the tests that need a built kernel (BUILT is set only when build/ exists), so build first.
if ! make clean >/dev/null 2>&1; then
    echo "land: make clean failed (build/ not writable?); aborted, nothing committed" >&2
    exit 1
fi
if ! make >/dev/null 2>&1 || ! make test-host; then
    echo "land: host suite is red on the merged tree; aborted, nothing committed" >&2
    exit 1
fi

git commit -q -m "$msg"
echo "land: committed $(git rev-parse --short HEAD) ($branch, host suite green on the merged tree)"
# The ledger row needs a commit of its own after the merge, so it is printed, not appended: landing stays
# exactly what it was. Run it from the primary after landing, then commit docs/size-ledger.tsv (docs/process.md).
echo "land: size ledger row (run now, then commit docs/size-ledger.tsv):"
echo "  make size | python3 tools/size_ledger.py --commit $(git rev-parse --short HEAD)"
