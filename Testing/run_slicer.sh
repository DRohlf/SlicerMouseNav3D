#!/usr/bin/env bash
# Runs every Testing/slicer/selftest_*.py in Slicer 5.12.4 and prints "<file>: <last log line>".
# ONLY=Testing/slicer/<file>.py runs one file. SLICER_EXE=<path to Slicer executable> picks the Slicer to use; the
# default is where the author's Slicer 5.12.4 is installed (the Windows per-user install under AppData\Local, run from
# Git Bash).
cd "$(dirname "$0")/.." || exit 1
SLICER="${SLICER_EXE:-$HOME/AppData/Local/slicer.org/3D Slicer 5.12.4/Slicer.exe}"
mkdir -p Testing/slicer/out
status=0
for f in ${ONLY:-Testing/slicer/selftest_*.py}; do
  name="$(basename "$f" .py)"
  log="Testing/slicer/out/$name.log"
  rm -f "$log"
  timeout 900 "$SLICER" --no-splash --python-script "$(cygpath -w "$PWD/$f" 2>/dev/null || echo "$PWD/$f")" >/dev/null 2>&1
  last="$(tail -n 1 "$log" 2>/dev/null || echo 'no log')"
  echo "$f: $last"
  [ "$last" = "OVERALL: PASS" ] || status=1
done
exit $status
