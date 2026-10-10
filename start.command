#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "Setting up PaperTalk (one time only, about a minute)..."
  rm -rf .venv
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt
fi
(sleep 3 && open http://127.0.0.1:8000) &
.venv/bin/python run.py
