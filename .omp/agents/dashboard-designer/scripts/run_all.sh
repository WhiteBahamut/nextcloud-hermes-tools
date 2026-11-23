#!/usr/bin/env bash
# Deterministic dashboard-bundle invariant run for the dashboard-designer agent.
# Read-only, stdlib only, no installs, no network. Run from anywhere:
#
#     bash .omp/agents/dashboard-designer/scripts/run_all.sh
#
# Layers: (1) check_dashboard_bundle.py bundle invariants, (2) node --check on
# dashboard/dist/index.js when node exists, (3) the WCAG contrast guard
# tests/test_dashboard_contrast.py when .venv exists. Any layer failure exits
# non-zero with a final FAIL line.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
fail=0

echo "== layer 1: bundle invariants =="
"${PYTHON:-python3}" "$HERE/check_dashboard_bundle.py" || fail=1

echo "== layer 2: node --check dashboard/dist/index.js =="
if command -v node >/dev/null 2>&1; then
  if node --check "$ROOT/dashboard/dist/index.js"; then
    echo "  ok node --check"
  else
    echo "  FAIL node --check"
    fail=1
  fi
else
  echo "  skip (node not available)"
fi

echo "== layer 3: contrast guard tests/test_dashboard_contrast.py =="
if [ -x "$ROOT/.venv/bin/python" ]; then
  "$ROOT/.venv/bin/python" -m pytest "$ROOT/tests/test_dashboard_contrast.py" -q || fail=1
else
  echo "  skip (no .venv)"
fi

if [ "$fail" -ne 0 ]; then
  echo "FAIL dashboard-designer-run"
  exit 1
fi
echo "PASS dashboard-designer-run"
