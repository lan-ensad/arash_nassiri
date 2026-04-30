"""
Ouverture et selection de la source video (camera ou fichier/image/URL).
Inclut le calcul du crop centre selon aspect ratio cible et la decimation
des sources live trop rapides.
"""

import cv2
import glob

from config import CFG


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def _is_live_source(source) -> bool:
    if isinstance(source, int):
        return True
    if isinstance(source, str):
        return (
            source.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://"))
            or source.startswith("/dev/video")
        )
    return False


def _is_image_source(source) -> bool:
    return isinstance(source, str) and source.lower().endswith(_IMAGE_EXTS)


class _StaticImageSource:
    """Adapter qui mime cv2.VideoCapture pour une image statique."""
    def __init__(self, path: str):
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError(f"Impossible de lire l'image : {path}")
        self._frame = img

    def read(self):
        # Copie defensive : draw_zones modifie en place.
        return True, self._frame.copy()

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:  return float(self._frame.shape[1])
        if prop == cv2.CAP_PROP_FRAME_HEIGHT: return float(self._frame.shape[0])
        return 0.0

    def set(self, prop, value): return True
    def release(self): pass
    def isOpened(self): return True


def _list_video_devices() -> list[str]:
    return sorted(glob.glob("/dev/video*"))


def open_source() -> tuple[cv2.VideoCapture, object, bool]:
    """Ouvre la source selon CFG. Retourne (cap, source, is_live)."""
    if CFG.camera_index is not None:
        devices = _list_video_devices()
        if devices:
            print(f"Devices video detectes : {', '.join(devices)}")
        source = CFG.camera_index
        cap    = cv2.VideoCapture(source)
        # MJPG = format natif Cam Link ; doit etre set AVANT width/height,
        # sinon le pilote peut renegocier en YUYV (latence + bande passante USB).
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Buffer minimal cote V4L2 : evite l'accumulation de frames.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if CFG.camera_width:  cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CFG.camera_width)
        if CFG.camera_height: cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG.camera_height)
        if CFG.camera_fps:    cap.set(cv2.CAP_PROP_FPS,          CFG.camera_fps)
    else:
        source = CFG.video_path
        if _is_image_source(source):
            cap = _StaticImageSource(source)
        else:
            cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la source : {source}")
    return cap, source, _is_live_source(source)


def compute_crop(src_w: int, src_h: int,
                 target_aspect: float | None) -> tuple[int, int, int, int]:
    """
    Crop centre pour matcher target_aspect (largeur/hauteur).
    target_aspect=None -> pas de crop.
    """
    if target_aspect is None:
        return 0, 0, src_w, src_h

    src_aspect = src_w / src_h
    if abs(src_aspect - target_aspect) < 1e-3:
        return 0, 0, src_w, src_h

    if src_aspect > target_aspect:
        out_w = int(round(src_h * target_aspect))
        x0    = (src_w - out_w) // 2
        return x0, 0, x0 + out_w, src_h
    out_h = int(round(src_w / target_aspect))
    y0    = (src_h - out_h) // 2
    return 0, y0, src_w, y0 + out_h


def compute_skip_ratio(live: bool, native_fps: float, target_fps: float) -> int:
    """Decimation source live : si camera > target_fps * 1.2, traite 1/N frames."""
    if not live or not target_fps or native_fps <= target_fps * 1.2:
        return 1
    return max(1, round(native_fps / target_fps))
