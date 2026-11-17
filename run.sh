#!/bin/bash
# Launch the Bigwell's Leaguern Analytics dashboard.
# Usage: ./run.sh
set -e
cd "$(dirname "$0")"
uv run streamlit run dashboard/app.py
