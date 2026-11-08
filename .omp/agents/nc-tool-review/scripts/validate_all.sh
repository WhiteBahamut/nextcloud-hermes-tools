#!/usr/bin/env bash
# Layer 1-3 deterministic validation of the nc_* APIs — entrypoint for the
# nc-tool-review agent. Run from anywhere:
#
#     bash .omp/agents/nc-tool-review/scripts/validate_all.sh
#
# Layers (all offline once .cache/ + .venv-check/ exist; pins are sha256-locked in
# lib/upstream_lock.json — see lib/upstream_pins.json):
#   fetch        lib/fetch_upstream.py — verify/fill the pinned upstream cache
#   hermes-contract  check_hermes_contract.py — plugin vs pinned Hermes loader source
#   nextcloud-docs   check_nextcloud_docs.py — endpoint inventory vs pinned NC docs/specs
#   ocs-spec         validate_ocs_spec.py — every nc_* request vs pinned OpenAPI spec
#   dav-fixtures     check_dav_fixtures.py — upstream multistatus/OCS fixtures vs src/dav.py
#
# Prints one PASS/FAIL line per check (FAIL adds indented detail) and exits non-zero
# if any check fails. Deterministic: with an intact cache/lock/venv, repeated runs
# produce byte-identical output (no timestamps, no network).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
PY="${PYTHON:-python3}"
VENV="$HERE/.venv-check"
CACHE="$HERE/.cache"
FAILED=0

run() {  # run <label> <cmd...>
  local label="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "PASS $label"
  else
    echo "FAIL $label"
    printf '%s\n' "$out" | sed 's/^/    /'
    FAILED=1
  fi
}

echo "== layer 0: pinned upstream fetch =="
run fetch "$PY" "$HERE/lib/fetch_upstream.py"

echo "== layer 1: static contract checks (stdlib) =="
run hermes-contract "$PY" "$HERE/check_hermes_contract.py"
run nextcloud-docs "$PY" "$HERE/check_nextcloud_docs.py"

echo "== layer 2: OCS OpenAPI spec validation (scratch venv) =="
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$CACHE"
  "$PY" -m venv "$VENV" >"$CACHE/venv-create.log" 2>&1 || { echo "FAIL venv-create"; cat "$CACHE/venv-create.log"; exit 1; }
  "$PY" -c 'import json,sys; m=json.load(open(sys.argv[1]))["meta"]["pip"]; [print(f"{k}=={v}") for k,v in sorted(m.items())]' \
    "$HERE/lib/upstream_pins.json" > "$CACHE/pip-requirements.txt"
  HTTPX_PIN="$("$ROOT/.venv/bin/pip" show httpx 2>/dev/null | awk '/^Version:/{print $2}')"
  [ -n "$HTTPX_PIN" ] && echo "httpx==$HTTPX_PIN" >> "$CACHE/pip-requirements.txt"
  "$VENV/bin/pip" install -q -r "$CACHE/pip-requirements.txt" >"$CACHE/pip-install.log" 2>&1 \
    || { echo "FAIL venv-pip-install (log: $CACHE/pip-install.log)"; tail -5 "$CACHE/pip-install.log" | sed 's/^/    /'; exit 1; }
fi
run ocs-spec "$VENV/bin/python" "$HERE/validate_ocs_spec.py"

echo "== layer 3: upstream parser fixtures (stdlib) =="
run dav-fixtures "$PY" "$HERE/check_dav_fixtures.py"

if [ "$FAILED" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "SOME CHECKS FAILED"
fi
exit "$FAILED"
