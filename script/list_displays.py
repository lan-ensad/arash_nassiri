"""
Liste les ecrans / sorties video detectes pour choisir l'ecran d'affichage
de la fenetre ambilight (cf. futur `monitor_index` dans config.py).

Utilise `xrandr --listmonitors` (X11 / XWayland). Pour Wayland natif sans
XWayland, utiliser `wlr-randr` ou les outils du compositeur (gnome-monitor-config).

Usage : ./script/.venv/bin/python3 script/list_displays.py
"""

import re
import shutil
import subprocess


# Format attendu de xrandr --listmonitors :
#   Monitors: 2
#    0: +*HDMI-1 1920/508x1080/286+0+0  HDMI-1
#    1: +DP-1 2560/598x1440/336+1920+0  DP-1
_MONITOR_RE = re.compile(
    r"^\s*(?P<idx>\d+):\s+"
    r"(?P<flags>[+*]+)"
    r"(?P<name>\S+)\s+"
    r"(?P<w>\d+)/\d+"
    r"x"
    r"(?P<h>\d+)/\d+"
    r"\+(?P<x>\d+)"
    r"\+(?P<y>\d+)\s+"
    r"(?P<output>\S+)\s*$"
)


def parse_listmonitors(text: str) -> list[dict]:
    monitors = []
    for line in text.splitlines():
        m = _MONITOR_RE.match(line)
        if not m:
            continue
        monitors.append({
            "index":   int(m.group("idx")),
            "name":    m.group("name"),
            "width":   int(m.group("w")),
            "height":  int(m.group("h")),
            "x":       int(m.group("x")),
            "y":       int(m.group("y")),
            "primary": "*" in m.group("flags"),
            "output":  m.group("output"),
        })
    return monitors


def main() -> None:
    if not shutil.which("xrandr"):
        print("xrandr non trouve. Installer avec : sudo apt install x11-xserver-utils")
        print("(ou utiliser wlr-randr / outils compositeur sur Wayland natif)")
        return

    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], stderr=subprocess.STDOUT
        ).decode()
    except subprocess.CalledProcessError as e:
        print(f"xrandr a echoue : {e.output.decode() if e.output else e}")
        return

    monitors = parse_listmonitors(out)
    if not monitors:
        print("Aucun ecran detecte. Sortie brute de xrandr :\n")
        print(out)
        return

    print(f"{len(monitors)} ecran(s) detecte(s) :\n")
    print(f"  {'Index':<5}  {'Nom':<12}  {'Resolution':<12}  {'Position':<14}  {'Primaire':<8}  Sortie")
    print(f"  {'-'*5}  {'-'*12}  {'-'*12}  {'-'*14}  {'-'*8}  {'-'*12}")
    for m in monitors:
        res  = f"{m['width']}x{m['height']}"
        pos  = f"({m['x']}, {m['y']})"
        prim = "oui" if m["primary"] else ""
        print(f"  {m['index']:<5}  {m['name']:<12}  {res:<12}  {pos:<14}  {prim:<8}  {m['output']}")

    print()
    primary = next((m for m in monitors if m["primary"]), monitors[0])
    print(f"Ecran primaire : index {primary['index']} ({primary['name']})")
    if len(monitors) > 1:
        print(
            "Pour diffuser sur un autre ecran, definir l'index dans "
            "script/config.py (champ `monitor_index` — a ajouter si absent)."
        )


if __name__ == "__main__":
    main()
