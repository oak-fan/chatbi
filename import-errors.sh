#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT_DIR/backend"
.venv/bin/python scripts/import_bird_dev_error.py --user-id "$@"
