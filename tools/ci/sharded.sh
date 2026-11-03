#!/bin/bash
# The VICE suite in parallel: one tools/ci/run.sh container per shard (tools/ci/shards.txt).
#   tools/ci/sharded.sh [--rev REV] [--out DIR] [--stagger SECS] [--no-outer-lock] [--expect N]
#   tools/ci/sharded.sh --check        # host-only: every VICE test is in exactly one shard
# Exit 0 only if every shard exits 0, ran tests, skipped none, and the tests run add up to the
# count discovered at REV. The whole run holds every vice slot (with-lock -x), so nothing else
# VICE runs meanwhile; the result is a timing-clean pass/fail, and a failing shard counts as red
# until its cause is known (there is no retry). A serial run (`BREADBIN_CI_EXCLUSIVE=1 run.sh test`)
# stays the reference until three sharded runs in a row give the same pass/fail set (docs/ci.md).
set -u

repo=$(cd "$(dirname "$0")/../.." && pwd)
rev=HEAD; out=; stagger=5; outer=1; expect=; check=0; vdir=
while [ $# -gt 0 ]; do
    case $1 in
        --rev) rev=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --stagger) stagger=$2; shift 2 ;;
        --no-outer-lock) outer=0; shift ;;
        --expect) expect=$2; shift 2 ;;
        --check) check=1; shift ;;
        --verdict) vdir=$2; shift 2 ;;
        *) echo "usage: $0 [--check] [--verdict DIR --expect N] [--rev REV] [--out DIR] [--stagger S] [--no-outer-lock] [--expect N]" >&2; exit 2 ;;
    esac
done


# verdict DIR EXPECT: judge a finished run from its files (DIR/names, NAME.log .rc .start .end, t0).
# Red on: a non-zero shard, a shard with no "Ran N tests" line, any skip, or a total that differs
# from EXPECT. Writes DIR/merged.log (failure sections first). Used by the run and by --verdict.
verdict() {
    local out=$1 expect=$2 n log rc wall ran cnt secs note fail=0 total=0 names=() t0e
    mapfile -t names < "$out/names"
    printf '%-26s %4s %6s %8s %10s %s\n' shard rc tests wall_s unittest_s note
    for n in "${names[@]}"; do
        log=$out/$n.log
        rc=$(cat "$out/$n.rc" 2>/dev/null || echo 99)
        wall=$(( $(cat "$out/$n.end" 2>/dev/null || date +%s) - $(cat "$out/$n.start" 2>/dev/null || date +%s) ))
        ran=$(sed -nE 's/^[0-9.]+ Ran ([0-9]+) tests? in ([0-9.]+)s$/\1 \2/p' "$log" 2>/dev/null | tail -1)
        cnt=${ran%% *}; secs=${ran#* }; note=
        [ "$rc" = 0 ] || { note="rc=$rc"; fail=1; }
        [ -n "$ran" ] || { note="$note no-Ran-line"; fail=1; cnt=0; secs=-; }
        if grep -qE ' \.\.\. skipped|skipped=' "$log" 2>/dev/null; then note="$note SKIPS"; fail=1; fi
        total=$(( total + cnt ))
        printf '%-26s %4s %6s %8s %10s %s\n' "$n" "$rc" "$cnt" "$wall" "$secs" "$note"
    done
    t0e=$(cat "$out/t0" 2>/dev/null || date +%s)
    echo "sharded: $total tests run, $expect expected; wall $(( $(date +%s) - t0e ))s"
    [ "$total" = "$expect" ] || { echo "sharded: test count mismatch" >&2; fail=1; }
    {
        for n in "${names[@]}"; do
            sed -nE '/^[0-9.]+ ={70}$/,/^[0-9.]+ Ran /p' "$out/$n.log" 2>/dev/null | sed "s/^/[$n] /"
        done
        for n in "${names[@]}"; do sed "s/^/[$n] /" "$out/$n.log" 2>/dev/null; done
    } > "$out/merged.log"
    echo "sharded: merged log $out/merged.log"
    [ $fail = 0 ] && echo "sharded: PASS" || echo "sharded: FAIL"
    return $fail
}

slots=${BREADBIN_VICE_SLOTS:-6}
if [ -n "$vdir" ]; then
    [ -n "$expect" ] || { echo "--verdict needs --expect N" >&2; exit 2; }
    verdict "$vdir" "$expect"; exit $?
fi
if [ $check = 1 ]; then
    exec python3 -I "$repo/tools/ci/shards.py" check "$slots"
fi

# Take the whole vice pool once and re-enter; each shard's own with-lock call passes through.
if [ $outer = 1 ] && [ -z "${SHARDED_INNER:-}" ]; then
    export SHARDED_INNER=1
    exec "$repo/tools/with-lock" -x -- "$0" --rev "$rev" ${out:+--out "$out"} \
        --stagger "$stagger" ${expect:+--expect "$expect"}
fi

sha=$(git -C "$repo" rev-parse --verify "$rev^{commit}") || exit 2
out=${out:-$(mktemp -d "${TMPDIR:-/tmp}/shards.XXXXXX")}
mkdir -p "$out"
# One snapshot of the tree for every shard (run.sh copies its parent at container start).
snap=$(mktemp -d "${TMPDIR:-/tmp}/shard-tree.XXXXXX")
sampler=
trap '[ -n "$sampler" ] && kill $sampler 2>/dev/null; rm -rf "$snap"' EXIT
git -C "$repo" archive "$sha" | tar -x -C "$snap" || exit 2
echo "sharded: commit $sha, logs in $out"

# Preflight: no image build or ROM fetch inside the shards (the unlocked race in run.sh).
podman image exists "${BREADBIN_CI_IMAGE:-breadbin-ci}" \
    || { echo "sharded: image missing; run tools/ci/run.sh test-host once first (docs/ci.md)" >&2; exit 2; }
[ -f "${BREADBIN_CI_ROMS:-$HOME/.cache/breadbin-ci/roms}/C64/kernal-901227-03.bin" ] \
    || { echo "sharded: ROM dir empty; run tools/setup-vice-roms.sh first" >&2; exit 2; }

# Coverage of THIS revision, not the working tree.
cov=$(python3 -I "$snap/tools/ci/shards.py" check "$slots") || { echo "$cov" >&2; echo "sharded: shard list does not cover the tests" >&2; exit 2; }
expect=${expect:-$(echo "$cov" | sed -n 's/^count //p')}

stamp() { while IFS= read -r l; do printf '%s %s\n' "$(date +%s.%N)" "$l"; done; }

# Fail fast: build and host tests once, no slot, before any VICE starts.
t0=$(date +%s)
"$snap/tools/ci/run.sh" all test-host 2>&1 | stamp > "$out/host.log"
hrc=${PIPESTATUS[0]}
echo "sharded: host tests rc=$hrc in $(( $(date +%s) - t0 ))s"
[ "$hrc" = 0 ] || { tail -40 "$out/host.log"; exit 1; }

# Load samples, to classify a failure as contention or real without a blind re-run.
( while :; do printf '%s %s | %s\n' "$(date +%s)" "$(head -1 /proc/pressure/cpu 2>/dev/null)" \
      "$(cut -d' ' -f1-3 /proc/loadavg)"; sleep 2; done ) > "$out/pressure.log" &
sampler=$!

declare -A pid
names=(); : > "$out/names"; date +%s > "$out/t0"
while IFS=$'\t' read -r name specs; do
    names+=("$name")
    echo "$name" >> "$out/names"; date +%s > "$out/$name.start"
    # shellcheck disable=SC2086  # specs are plain test names, split on purpose
    ( "$snap/tools/ci/run.sh" test-only T="$specs" 2>&1 | stamp > "$out/$name.log"
      echo "${PIPESTATUS[0]}" > "$out/$name.rc"
      date +%s > "$out/$name.end" ) &
    pid[$name]=$!
    sleep "$stagger"      # six cold boots and tar copies at once are the worst moment for the harness
done < <(python3 -I "$snap/tools/ci/shards.py" list)
for n in "${names[@]}"; do wait "${pid[$n]}"; done
kill $sampler 2>/dev/null; sampler=

verdict "$out" "$expect"
exit $?
