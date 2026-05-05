#!/bin/bash
#
# Lance le lecteur de partition LED synchronise sur OSC.
#
# Usage :
#   ./run.sh           # mode prod : bind OSC sur 0.0.0.0 (toutes interfaces)
#   ./run.sh dev       # mode dev  : bind OSC sur 127.0.0.1 (Reaper local)
#
# Prerequis :
#   - Python venv dans script/.venv avec opencv-python + numpy + python-osc
#   - Partition .npz pre-calculee (cf. script/build_partition.py)
#   - dry_run = False dans script/config.py (sinon aucun paquet UDP envoye)
#   - Cote Reaper : Preferences > Control/OSC/Web > Add OSC > "Configure
#     device IP+port" avec l'IP affichee ci-dessous et le port OSC.
#
set -e

MODE="${1:-prod}"
case "$MODE" in
    dev)  OSC_HOST="127.0.0.1" ;;
    prod) OSC_HOST="0.0.0.0"   ;;
    *)
        echo "Mode inconnu : $MODE (attendu : dev | prod)" >&2
        exit 2
        ;;
esac

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
ls -1t "$LOG_FILE".* 2>/dev/null \
    | tail -n +$((MAX_LOG_BACKUPS + 1)) \
    | xargs -r rm -f

echo "=== Demarrage lecteur OSC : $(date -Iseconds) (mode $MODE) ==="

# Detection IP locale principale (interface vers la passerelle par defaut).
LOCAL_IP=$(ip route get 8.8.8.8 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
LOCAL_IP="${LOCAL_IP:-127.0.0.1}"

# Attente reseau en mode prod : sous systemd, network-online.target peut se
# declencher avant que l'ESP32 soit reellement joignable. Ping la passerelle
# par defaut pendant max 30s (non bloquant si pas de gateway connue).
if [ "$MODE" = "prod" ]; then
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
fi

echo "------------------------------------------------------------"
echo " Mode    : $MODE"
echo " OSC     : bind $OSC_HOST  -- Reaper doit emettre vers $LOCAL_IP"
echo "------------------------------------------------------------"

# PYTHONUNBUFFERED=1 : flush immediat de stdout -> logs temps reel
export PYTHONUNBUFFERED=1

# Lance depuis le dossier script/ pour que les chemins relatifs de config.py
# (ex : partition_path = "../test_videos/abl.npz") resolvent correctement.
cd "$PROJECT_ROOT/script"

if [ -x .venv/bin/python3 ]; then
    exec .venv/bin/python3 main.py --osc-host "$OSC_HOST"
else
    exec python3 main.py --osc-host "$OSC_HOST"
fi
