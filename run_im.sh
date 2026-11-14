#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect Python runtime (prefer conda environment if present)
if [ -x "/Users/bhargavreddy/miniconda3/bin/python" ]; then
    PYTHON="/Users/bhargavreddy/miniconda3/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    PYTHON="python"
fi

exec "$PYTHON" "$SCRIPT_DIR/run_im_pipeline.py" "$@"
