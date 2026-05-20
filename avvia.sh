#!/bin/bash
cd "$(dirname "$0")"

# Carica variabili locali da .env (se esiste)
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "Avvio Gestionale Marginalità..."
open http://localhost:5001
python3 app.py
