#!/usr/bin/env bash
# Every check CI runs: the manifest checks, then each plugin's own tests (scripts/test_*.py).
set -uo pipefail
cd "$(dirname "$0")/.."

status=0
python3 scripts/validate.py || status=1

out=$(mktemp)
trap 'rm -f "$out"' EXIT
for t in plugins/*/scripts/test_*.py; do
  [ -e "$t" ] || continue
  if python3 -W ignore::ResourceWarning "$t" >"$out" 2>&1; then
    echo "ok    $t ($(grep -Eo 'Ran [0-9]+ tests?' "$out"))"
  else
    cat "$out"
    echo "FAIL  $t"
    status=1
  fi
done
exit $status
