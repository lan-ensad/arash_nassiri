"""
Liste les cameras / devices video utilisables comme `camera_index` dans config.py.

Pour chaque /dev/videoN detecte, tente d'ouvrir le flux avec OpenCV et lit une
frame pour verifier que le device est reellement capturable (les cartes UVC
exposent souvent plusieurs /dev/videoN dont certains sont des endpoints
metadata-only, non lisibles).

Usage : ./script/.venv/bin/python3 script/list_cameras.py
"""

import os
# Silence les logs cv2/ffmpeg/v4l2 pendant les probes qui echouent (bruit stderr).
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2
import glob
import re
import shutil
import subprocess

try:
    cv2.setLogLevel(0)  # 0 = SILENT sur les builds recents
except AttributeError:
    pass


def device_name(dev: str) -> str:
    """Nom lisible du device via v4l2-ctl si disponible, sinon vide."""
    if not shutil.which("v4l2-ctl"):
        return ""
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "--device", dev, "--info"],
            stderr=subprocess.DEVNULL, timeout=1,
        ).decode()
        for line in out.splitlines():
            if "Card type" in line:
                return line.split(":", 1)[1].strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return ""


def probe(index: int) -> dict | None:
    """Ouvre l'index, lit une frame, retourne {w, h, fps} si OK sinon None."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return None
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        return None
    info = {
        "w":   int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "h":   int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS) or 0.0,
    }
    cap.release()
    return info


def main() -> None:
    devices = sorted(glob.glob("/dev/video*"))
    if not devices:
        print("Aucun /dev/video* detecte. Connecter une webcam ou une carte de capture.")
        return

    print(f"{len(devices)} device(s) detecte(s) :\n")
    print(f"  {'Index':<5}  {'Device':<14}  {'Lisible':<8}  {'Resolution':<12}  {'FPS':<6}  Nom")
    print(f"  {'-'*5}  {'-'*14}  {'-'*8}  {'-'*12}  {'-'*6}  {'-'*40}")

    usable: list[int] = []
    for dev in devices:
        m = re.search(r"video(\d+)$", dev)
        if not m:
            continue
        idx  = int(m.group(1))
        name = device_name(dev)
        info = probe(idx)

        if info is None:
            readable = "non"
            res      = "-"
            fps      = "-"
        else:
            readable = "oui"
            res      = f"{info['w']}x{info['h']}"
            fps      = f"{info['fps']:.1f}"
            usable.append(idx)

        print(f"  {idx:<5}  {dev:<14}  {readable:<8}  {res:<12}  {fps:<6}  {name}")

    print()
    if usable:
        print(f"camera_index utilisables : {usable}")
        print(f"Copier dans script/config.py : camera_index: int | None = {usable[0]}")
    else:
        print("Aucun device n'a renvoye de frame. Verifier droits /dev/video* et connexion.")


if __name__ == "__main__":
    main()
