import cv2
import glob
import numpy as np
import os
import shutil
import subprocess
import time

from config import CFG
from zones import build_zones, extract_colors, draw_zones
from colors import process
from udp_sender import UdpSender
from terminal_preview import TerminalPreview
from list_displays import parse_listmonitors


def _is_live_source(source) -> bool:
    """True si la source est un flux live (camera, URL reseau)."""
    if isinstance(source, int):
        return True
    if isinstance(source, str):
        return (
            source.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://"))
            or source.startswith("/dev/video")
        )
    return False


def _list_video_devices() -> list[str]:
    """Liste les devices video detectes sur le systeme (/dev/video*)."""
    return sorted(glob.glob("/dev/video*"))


def _get_monitor(index: int) -> dict | None:
    """Recupere la geometrie d'un moniteur via xrandr. None si introuvable."""
    if not shutil.which("xrandr"):
        print("xrandr non trouve : monitor_index ignore (WM decidera de l'ecran).")
        return None
    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], stderr=subprocess.STDOUT
        ).decode()
    except subprocess.CalledProcessError:
        return None
    monitors = parse_listmonitors(out)
    if not monitors:
        return None
    for m in monitors:
        if m["index"] == index:
            return m
    return None


def _open_source() -> tuple[cv2.VideoCapture, object, bool]:
    """Ouvre la source (camera ou fichier) et retourne (cap, source, is_live)."""
    if CFG.camera_index is not None:
        devices = _list_video_devices()
        if devices:
            print(f"Devices video detectes : {', '.join(devices)}")
        source = CFG.camera_index
        cap    = cv2.VideoCapture(source)
        if CFG.camera_width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CFG.camera_width)
        if CFG.camera_height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG.camera_height)
        if CFG.camera_fps:
            cap.set(cv2.CAP_PROP_FPS, CFG.camera_fps)
    else:
        source = CFG.video_path
        cap    = cv2.VideoCapture(source)

    if not cap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la source : {source}")
    return cap, source, _is_live_source(source)


def main() -> None:
    cap, source, live = _open_source()

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps        = CFG.target_fps if CFG.target_fps else native_fps
    w          = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h          = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    delay      = 1.0 / fps

    total_leds  = (
        CFG.leds_top + CFG.leds_right + CFG.leds_bottom + CFG.leds_left
    )
    half_bottom = CFG.leds_bottom // 2
    chain_a     = half_bottom + CFG.leds_left
    chain_b     = (CFG.leds_bottom - half_bottom) + CFG.leds_right

    src_desc = f"camera index {source}" if isinstance(source, int) else str(source)
    kind     = "live" if live else "fichier"
    print(f"Source  : [{kind}] {src_desc}")
    print(f"Video   : {w}x{h} @ {native_fps:.2f}fps natif → cible {fps:.2f}fps")
    print(f"LEDs    : {total_leds} total (bas {CFG.leds_bottom} / droite {CFG.leds_right} / gauche {CFG.leds_left})")
    print(f"Chaines : A (gauche) = {chain_a} LEDs, B (droite) = {chain_b} LEDs")

    zones   = build_zones(h, w)
    sender  = UdpSender()
    preview = TerminalPreview(CFG.terminal_preview_hz) if CFG.terminal_preview else None
    prev    = None

    target_monitor = None

    if not CFG.headless:
        cv2.namedWindow("ambilight", cv2.WINDOW_NORMAL)

        # Detection session (Wayland natif ne permet pas aux apps de bouger leurs fenetres)
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session == "wayland" and CFG.monitor_index is not None:
            print("ATTENTION : session Wayland detectee. monitor_index peut etre ignore")
            print("            par le compositeur. Preferer une session X11/XWayland.")

        # Resolution de la cible
        if CFG.monitor_index is not None:
            target_monitor = _get_monitor(CFG.monitor_index)
            if target_monitor is not None:
                print(
                    f"Ecran   : [{target_monitor['index']}] {target_monitor['name']} "
                    f"({target_monitor['width']}x{target_monitor['height']} "
                    f"@ ({target_monitor['x']}, {target_monitor['y']}))"
                )
            else:
                print(f"Ecran index={CFG.monitor_index} introuvable → position par defaut.")

        # Realise la fenetre avec une frame vide pour que moveWindow ait un effet
        # avant le 1er imshow "reel" (sinon certains WM ignorent le placement).
        if target_monitor is not None:
            dummy = np.zeros((target_monitor["height"], target_monitor["width"], 3), dtype=np.uint8)
            cv2.imshow("ambilight", dummy)
            cv2.waitKey(1)
            cv2.resizeWindow("ambilight", target_monitor["width"], target_monitor["height"])
            cv2.moveWindow("ambilight", target_monitor["x"], target_monitor["y"])
            cv2.waitKey(1)
    else:
        print("Mode headless : pas de fenetre OpenCV (gain de performance).")

    def place_window_on_target():
        """Redimensionne + positionne la fenetre sur le moniteur cible."""
        if target_monitor is None:
            return
        cv2.resizeWindow("ambilight", target_monitor["width"], target_monitor["height"])
        cv2.moveWindow("ambilight", target_monitor["x"], target_monitor["y"])

    def apply_fullscreen():
        if CFG.fullscreen and not CFG.headless:
            cv2.setWindowProperty("ambilight", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            # Re-positionne apres fullscreen (certains WM recentrent la fenetre
            # sur l'ecran primaire au moment du toggle fullscreen)
            place_window_on_target()

    first_frame   = True
    just_rewound  = False

    # Compteur FPS independant du terminal_preview (utile quand preview off)
    fps_count   = 0
    fps_t0      = time.perf_counter()
    fps_log_dt  = 1.0  # intervalle de log en secondes

    try:
        if CFG.headless:
            print("Controles : [Ctrl+C] dans ce terminal pour arreter")
        else:
            print("Controles : [q] ou [Echap] dans la fenetre video, ou [Ctrl+C] dans ce terminal")
        while True:
            t0 = time.perf_counter()

            ok, frame = cap.read()
            if not ok:
                if live:
                    # Source live : retry apres une courte pause (camera temporairement
                    # indisponible, frame perdue, etc.). Ctrl+C pour sortir.
                    time.sleep(0.05)
                    continue
                if CFG.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    prev = None  # reset lissage temporel au rebouclage
                    just_rewound = True
                    continue
                break

            raw     = extract_colors(frame, zones)
            colors  = process(raw, prev)
            prev    = raw  # lissage sur les couleurs brutes (avant gamma)

            sender.send(colors)

            if preview is not None:
                preview.draw(colors)

            if not CFG.headless:
                if not CFG.fullscreen:
                    draw_zones(frame, zones, colors)
                cv2.imshow("ambilight", frame)

                # Fullscreen doit etre applique APRES le 1er imshow (la fenetre
                # n'est realisee qu'a ce moment-la) et re-applique apres chaque
                # rewind car certains WM resize la fenetre quand le decoder reboucle.
                if first_frame or just_rewound:
                    apply_fullscreen()
                    first_frame  = False
                    just_rewound = False

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:  # q ou Echap
                    break

            # Log FPS 1x/s (seulement si le preview terminal est desactive,
            # sinon le preview affiche deja son propre FPS)
            if preview is None:
                fps_count += 1
                now = time.perf_counter()
                if now - fps_t0 >= fps_log_dt:
                    fps_measured = fps_count / (now - fps_t0)
                    print(f"FPS : {fps_measured:5.1f}")
                    fps_count = 0
                    fps_t0    = now

            elapsed = time.perf_counter() - t0
            time.sleep(max(0.0, delay - elapsed))

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if not CFG.headless:
            cv2.destroyAllWindows()
        sender.close()
        if preview is not None:
            preview.close()
        print("Arret propre.")


if __name__ == "__main__":
    main()