#!/bin/bash
# ci.sh — Local pre-push CI verification
# Mirrors .github/workflows/ci.yml steps:
#   1. Contract tests  (pytest tests/contracts/ -q)
#   2. Unit tests       (pytest tests/unit/ -q)
#   3. Lint             (ruff check src/)
#
# Usage: ./scripts/ci.sh
# Exits 0 if all gates pass, 1 otherwise.

set -e
cd "$(git rev-parse --show-toplevel)"

echo "═══════════════════════════════════════════"
echo "  CI Pipeline — Contract + Unit + Lint"
echo "═══════════════════════════════════════════"
echo ""

# ── Contract tests ──────────────────────────
echo "── 1. Contract Tests ──"
python -m pytest tests/contracts/ -q --no-header || {
    echo ""
    echo "❌ CONTRACT TESTS FAILED"
    exit 1
}
echo "   ✅ Contract tests passed"
echo ""

# ── Unit tests ──────────────────────────────
echo "── 2. Unit Tests ──"
python -m pytest tests/unit/ -q --no-header || {
    echo ""
    echo "❌ UNIT TESTS FAILED"
    exit 1
}
echo "   ✅ Unit tests passed"
echo ""

# ── Lint ────────────────────────────────────
echo "── 3. Lint (ruff) ──"
ruff check src/ || {
    echo ""
    echo "❌ LINT FAILED"
    exit 1
}
echo "   ✅ Lint passed"
echo ""

echo "═══════════════════════════════════════════"
echo "  ✅ All CI gates passed"
echo "═══════════════════════════════════════════"
