#!/bin/zsh
# Levanta la tienda en http://localhost:8020  (panel: http://localhost:8020/admin)
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
python3 -m app.seed
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8020
