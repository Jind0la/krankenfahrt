#!/bin/bash
# Pre-commit hook: Guards against broken imports and contract violations.
# Runs on every commit. Must pass before code can be pushed.
#
# Three gates:
#   1. Contract imports: all service modules must be importable  
#   2. Unit tests: must pass (fast, isolated)
#   3. Lint: ruff check (if available)

set -e
cd "$(git rev-parse --show-toplevel)"

echo "🔒 KTF Pre-Commit: Contract Gate..."
python -m pytest tests/contracts/ -q --no-header 2>&1 || {
    echo "❌ CONTRACT FAILED: Service module import broken. Fix before commit."
    exit 1
}

echo "🔒 KTF Pre-Commit: Unit Tests..."
python -m pytest tests/unit/ -q --no-header 2>&1 || {
    echo "❌ UNIT TESTS FAILED. Fix before commit."
    exit 1
}

if command -v ruff &> /dev/null; then
    echo "🔒 KTF Pre-Commit: Lint..."
    ruff check src/ 2>&1 || {
        echo "❌ LINT FAILED."
        exit 1
    }
fi

echo "✅ All gates passed."
