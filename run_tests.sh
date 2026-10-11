#!/usr/bin/env bash
# Every check, in the order that makes a failure easiest to read:
# structure first (is the XML shaped like Europass's?), then values (did
# anything get lost?), then the page geometry, then the whole app.
#
# Exit code is non-zero if any of them fails, so this can gate a deploy.
set -u
cd "$(dirname "$0")"

fail=0
run() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"
  shift
  if "$@"; then :; else fail=1; fi
}

run "Structure: does our XML match the official element paths?" python3 tools/xml_diff.py
run "Values: does a CV survive import -> export -> import?"      python3 fidelity.py
run "Templates: do the four layouts measure like the real ones?" python3 tools/template_check.py
run "Workflow: upload, edit, save, export, re-import"            python3 tools/e2e.py
run "Preview: does the editor match the PDF on screen?"         python3 tools/editor_check.py

if [ "$fail" -eq 0 ]; then
  printf '\n\033[32mAll checks passed.\033[0m\n'
else
  printf '\n\033[31mSomething failed - do not deploy.\033[0m\n'
fi
exit "$fail"
