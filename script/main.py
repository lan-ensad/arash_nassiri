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


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


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


def _is_image_source(source) -> bool:
    """True si la source est un fichier image statique."""
    return isinstance(source, str) and source.lower().endswith(_IMAGE_EXTS)


class _StaticImageSource:
    """
    Adapter qui mime l'API cv2.VideoCapture pour une image PNG/JPG statique.
    read() retourne toujours la meme frame (copie defensive : draw_zones
    modifie la frame en place, sinon les overlays s'accumulent).
    """
    def __init__(self, path: str):
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError(f"Impossible de lire l'image : {path}")
        self._frame = img

    def read(self):
        return True, self._frame.copy()

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:  return float(self._frame.shape[1])
        if prop == cv2.CAP_PROP_FRAME_HEIGHT: return float(self._frame.shape[0])
        if prop == cv2.CAP_PROP_FPS:          return 0.0
        return 0.0

    def set(self, prop, value):
        return True

    def release(self):
        pass

    def isOpened(self):
        return True


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


def _compute_crop(src_w: int, src_h: int, target_aspect: float | None) -> tuple[int, int, int, int]:
    """
    Calcule un crop centre pour que la zone retenue ait l'aspect ratio cible
    (largeur/hauteur). Retourne (x0, y0, x1, y1) en coordonnees pixel sur la
    frame source. target_aspect=None → pas de crop (renvoie l'image entiere).

    - target_aspect < ratio natif : la source est trop large → bandes laterales coupees.
    - target_aspect > ratio natif : la source est trop haute → bandes haut/bas coupees.
    """
    if target_aspect is None:
        return 0, 0, src_w, src_h

    src_aspect = src_w / src_h
    if abs(src_aspect - target_aspect) < 1e-3:
        return 0, 0, src_w, src_h

    if src_aspect > target_aspect:
        # source trop large → reduire la largeur
        out_w = int(round(src_h * target_aspect))
        x0    = (src_w - out_w) // 2
        return x0, 0, x0 + out_w, src_h
    else:
        # source trop haute → reduire la hauteur
        out_h = int(round(src_w / target_aspect))
        y0    = (src_h - out_h) // 2
        return 0, y0, src_w, y0 + out_h


def _open_source() -> tuple[cv2.VideoCapture, object, bool]:
    """Ouvre la source (camera ou fichier) et retourne (cap, source, is_live)."""
    if CFG.camera_index is not None:
        devices = _list_video_devices()
        if devices:
            print(f"Devices video detectes : {', '.join(devices)}")
        source = CFG.camera_index
        cap    = cv2.VideoCapture(source)
        # MJPG = format natif Cam Link ; doit etre set AVANT width/height
        # sinon le pilote peut renegocier en YUYV (latence + bande passante USB).
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Buffer minimal cote V4L2 : evite l'accumulation de frames si le script
        # consomme moins vite que la camera ne produit (cause typique de >1s de retard).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if CFG.camera_width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CFG.camera_width)
        if CFG.camera_height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG.camera_height)
        if CFG.camera_fps:
            cap.set(cv2.CAP_PROP_FPS, CFG.camera_fps)
    else:
        source = CFG.video_path
        if _is_image_source(source):
            cap = _StaticImageSource(source)
        else:
            cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la source : {source}")
    return cap, source, _is_live_source(source)


def main() -> None:
    cap, source, live = _open_source()

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps        = CFG.target_fps if CFG.target_fps else native_fps
    src_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    delay      = 1.0 / fps

    # Crop centre selon l'aspect ratio cible (None = aspect natif).
    crop_x0, crop_y0, crop_x1, crop_y1 = _compute_crop(src_w, src_h, CFG.target_aspect)
    w = crop_x1 - crop_x0
    h = crop_y1 - crop_y0

    total_leds  = (
        CFG.leds_top + CFG.leds_right + CFG.leds_bottom + CFG.leds_left
    )
    half_bottom = CFG.leds_bottom // 2
    chain_a     = half_bottom + CFG.leds_left
    chain_b     = (CFG.leds_bottom - half_bottom) + CFG.leds_right

    src_desc = f"camera index {source}" if isinstance(source, int) else str(source)
    kind     = "live" if live else "fichier"
    print(f"Source  : [{kind}] {src_desc}")
    print(f"Video   : {src_w}x{src_h} @ {native_fps:.2f}fps natif → cible {fps:.2f}fps")
    if CFG.target_aspect is not None and (w, h) != (src_w, src_h):
        print(f"Crop    : {w}x{h} (aspect cible {CFG.target_aspect:.4f}, "
              f"offset x={crop_x0} y={crop_y0})")
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

    # Compteur FPS : log uniquement sur transition (chute / retablissement) pour
    # ne pas polluer le log en regime nominal. Baseline = max FPS observe (auto-
    # calibre, evite de coder en dur target_fps qui n'est pas toujours respecte
    # par la camera).
    fps_count             = 0
    fps_t0                = time.perf_counter()
    fps_log_dt            = 1.0    # fenetre de mesure
    fps_baseline          = 0.0    # max FPS observe depuis le demarrage
    fps_drop_threshold    = 0.80   # alerte si fps < 80% du baseline
    fps_low_state         = False  # True = on est actuellement en chute

    # --- Decimation source live ---
    # Si la camera debite plus vite que target_fps (ex : Cam Link a 60fps qui
    # ignore cap.set(FPS, 30)), on consomme toutes les frames pour vider le
    # buffer V4L2, mais on n'en traite qu'une sur N.
    skip_ratio = 1
    if live and CFG.target_fps and native_fps > CFG.target_fps * 1.2:
        skip_ratio = max(1, round(native_fps / CFG.target_fps))
        print(f"Decimation : capture {native_fps:.1f}fps → traite 1/{skip_ratio} "
              f"(soit ≈ {native_fps/skip_ratio:.1f}fps)")
    skip_counter = 0

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

            # Decimation : si camera plus rapide que target_fps, on consomme
            # toutes les frames mais on n'en traite qu'une sur skip_ratio.
            if skip_ratio > 1:
                skip_counter += 1
                if skip_counter % skip_ratio != 0:
                    continue

            # Crop centre sur l'aspect ratio cible. No-op si target_aspect=None
            # ou si la source a deja le bon ratio.
            if (crop_x0, crop_y0) != (0, 0) or (crop_x1, crop_y1) != (src_w, src_h):
                frame = frame[crop_y0:crop_y1, crop_x0:crop_x1]

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

            # FPS : log uniquement sur transition (chute > 20% sous le baseline,
            # ou retablissement). Pas de log en regime nominal -> log lisible.
            # Skip si le preview terminal est actif (il affiche deja son propre FPS).
            if preview is None:
                fps_count += 1
                now = time.perf_counter()
                if now - fps_t0 >= fps_log_dt:
                    fps_measured = fps_count / (now - fps_t0)
                    if fps_measured > fps_baseline:
                        fps_baseline = fps_measured
                    is_low = (
                        fps_baseline > 0
                        and fps_measured < fps_baseline * fps_drop_threshold
                    )
                    if is_low and not fps_low_state:
                        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                        print(f"[{ts}] FPS chute : {fps_measured:5.1f} "
                              f"(baseline {fps_baseline:5.1f})")
                        fps_low_state = True
                    elif not is_low and fps_low_state:
                        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                        print(f"[{ts}] FPS retabli : {fps_measured:5.1f} "
                              f"(baseline {fps_baseline:5.1f})")
                        fps_low_state = False
                    fps_count = 0
                    fps_t0    = now

            elapsed = time.perf_counter() - t0
            # Throttle uniquement pour les fichiers (sinon lecture > temps reel).
            # Sur source live (camera, Cam Link) : consommer des qu'une frame est
            # prete, pour ne pas accumuler de retard dans les buffers V4L2/ffmpeg.
            if not live:
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