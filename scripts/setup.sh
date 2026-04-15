#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing dependencies with uv..."
uv sync

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env"
echo "  2. Fill in your API credentials in .env"
echo "  3. uv run cli notion-ping          # verify Notion connection"
echo "  4. uv run cli fetch --space <KEY>   # fetch sample pages"
echo "  5. uv run pytest                    # run tests"
