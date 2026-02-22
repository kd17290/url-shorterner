#!/usr/bin/env bash
# One-time setup: install pre-commit hooks that mirror the CI pipeline.
# Usage: bash scripts/setup-hooks.sh

set -euo pipefail

echo "=== Installing pre-commit ==="
python3 -m pip install pre-commit

echo "=== Installing git hooks ==="
pre-commit install

echo "=== Running hooks on all files (first-time validation) ==="
pre-commit run --all-files || true

echo ""
echo "✅ Done! Hooks will now run automatically on every 'git commit'."
echo ""
echo "Optional: run pyright manually before pushing (slow, not in hook):"
echo "  pyright"
