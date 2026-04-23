#!/bin/bash
#
# Lance l'ambilight en mode production (fullscreen, sans curseur).
#
# Prerequis :
#   - Python venv dans script/.venv avec opencv-python + numpy installes
#   - unclutter installe  (sudo apt install unclutter)
#   - Firmware flashe et ESP32 connecte au reseau WiFi ferme
#   - dry_run = False dans script/config.py (sinon aucun paquet UDP envoye)
#
set -e

cd "$(dirname "$0")"

# Lance unclutter uniquement en session graphique (headless = pas de curseur a cacher)
if [ -n "$DISPLAY" ] && command -v unclutter > /dev/null; then
    unclutter -idle 0.3 -root &
    UNCLUTTER_PID=$!
    trap 'kill $UNCLUTTER_PID 2>/dev/null || true' EXIT
elif [ -n "$DISPLAY" ]; then
    echo "Attention : unclutter non installe → curseur visible en fullscreen."
    echo "Installer avec : sudo apt install unclutter"
fi

# Lance le script ambilight (utilise le venv s'il existe)
if [ -x script/.venv/bin/python3 ]; then
    exec script/.venv/bin/python3 script/main.py
else
    exec python3 script/main.py
fi
