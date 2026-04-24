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

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/ambilight.log"
MAX_LOG_BYTES=10485760   # 10 Mo
MAX_LOG_BACKUPS=5

# Rotation basique a chaque demarrage : si le log courant depasse la taille
# max, renommer avec timestamp et ne garder que les N derniers backups.
mkdir -p "$LOG_DIR"
if [ -f "$LOG_FILE" ]; then
    size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$size" -gt "$MAX_LOG_BYTES" ]; then
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d-%H%M%S)"
    fi
fi
# Suppression des plus vieux backups (on garde les MAX_LOG_BACKUPS plus recents)
ls -1t "$LOG_FILE".* 2>/dev/null \
    | tail -n +$((MAX_LOG_BACKUPS + 1)) \
    | xargs -r rm -f

echo "=== Demarrage ambilight : $(date -Iseconds) ==="

# Attente reseau : sous systemd, network-online.target peut se declencher
# avant que l'ESP32 soit reellement joignable. Ping la passerelle par defaut
# pendant max 30s (non bloquant si pas de gateway connue).
gw=$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')
if [ -n "$gw" ]; then
    for i in $(seq 1 30); do
        if ping -c 1 -W 1 "$gw" >/dev/null 2>&1; then
            echo "Reseau OK (gateway $gw joignable apres ${i}s)."
            break
        fi
        sleep 1
    done
fi

# Lance unclutter uniquement en session graphique (headless = pas de curseur a cacher)
if [ -n "$DISPLAY" ] && command -v unclutter > /dev/null; then
    unclutter -idle 0.3 -root &
    UNCLUTTER_PID=$!
    trap 'kill $UNCLUTTER_PID 2>/dev/null || true' EXIT
elif [ -n "$DISPLAY" ]; then
    echo "Attention : unclutter non installe → curseur visible en fullscreen."
    echo "Installer avec : sudo apt install unclutter"
fi

# PYTHONUNBUFFERED=1 : flush immediat de stdout → logs temps reel
export PYTHONUNBUFFERED=1

# Lance depuis le dossier script/ pour que les chemins relatifs de config.py
# (ex : video_path = "data/sample.mp4") resolvent correctement (coherent avec
# le mode dev ou main.py est lance depuis script/).
cd "$PROJECT_ROOT/script"

if [ -x .venv/bin/python3 ]; then
    exec .venv/bin/python3 main.py
else
    exec python3 main.py
fi
