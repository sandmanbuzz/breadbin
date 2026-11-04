#!/bin/sh
# Land a branch on the current branch (local main) only if the merged tree passes the host suite.
#
#   tools/with-lock -r land -- sh tools/land.sh BRANCH [MESSAGE]
#
# Stops before committing if the merge conflicts or the suite is red: the merge is aborted and the
# tree is left as it was. The suite runs after make clean, on the merged tree itself, so stale build
# output cannot make a green branch look red (or the reverse). See docs/process.md, "Landing".
set -eu

branch=${1:?usage: land.sh BRANCH [MESSAGE]}
msg=${2:-"Merge $branch"}

if [ -n "$(git status --porcelain)" ]; then
    echo "land: working tree is not clean; nothing merged" >&2
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

make clean >/dev/null 2>&1 || true
if ! make test-host; then
    echo "land: host suite is red on the merged tree; aborted, nothing committed" >&2
    exit 1
fi

git commit -q -m "$msg"
echo "land: committed $(git rev-parse --short HEAD) ($branch, host suite green on the merged tree)"
