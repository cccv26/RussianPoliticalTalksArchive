#!/bin/bash
# Run transcript fetcher locally and commit results to GitHub
# Usage:
#   ./run_local.sh                          # both channels, 30 videos each
#   ./run_local.sh --channel FedorKrasheninnikov --max-results 300

set -e  # stop on any error

# ── Check uv is installed ─────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env"
fi

# ── Load secrets from .env file ──────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and fill in your keys."
    exit 1
fi
export $(grep -v '^#' .env | xargs)

# ── Parse args ───────────────────────────────────────────────────────────────
CHANNEL=""
MAX_RESULTS=30

while [[ $# -gt 0 ]]; do
    case $1 in
        --channel)      CHANNEL="$2";     shift 2 ;;
        --max-results)  MAX_RESULTS="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Sync dependencies ─────────────────────────────────────────────────────────
uv sync

# ── Run the fetcher ──────────────────────────────────────────────────────────
if [ -n "$CHANNEL" ]; then
    echo "=== Fetching: $CHANNEL (max $MAX_RESULTS) ==="
    uv run python fetch_transcripts.py --channel "$CHANNEL" --max-results "$MAX_RESULTS"
else
    echo "=== Fetching: FedorKrasheninnikov (max $MAX_RESULTS) ==="
    uv run python fetch_transcripts.py --channel FedorKrasheninnikov --max-results "$MAX_RESULTS"

    echo ""
    echo "=== Fetching: BaunovTube (max $MAX_RESULTS) ==="
    uv run python fetch_transcripts.py --channel BaunovTube --max-results "$MAX_RESULTS"
fi

# ── Commit and push ──────────────────────────────────────────────────────────
echo ""
echo "=== Committing results ==="

git add -A

if git diff --cached --quiet; then
    echo "Nothing new to commit."
else
    TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
    git commit -m "chore: fetch transcripts [$TIMESTAMP]"
    git push
    echo "✓ Pushed to GitHub"
fi
