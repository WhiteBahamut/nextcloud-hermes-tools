#!/usr/bin/env bash
# Deterministic security-invariant run for the nc-security-audit agent.
# Read-only, stdlib only, no installs, no network. Run from anywhere:
#
#     bash .omp/agents/nc-security-audit/scripts/run_all.sh
#
# check_security_invariants.py prints one ok/FAIL line per check plus a final
# PASS/FAIL line; the exit code propagates.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$HERE/check_security_invariants.py"
