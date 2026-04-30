from collections import deque

import cv2
import numpy as np
from config import CFG


# Table de gamma precalculee une fois (CFG.gamma est immuable apres init).
_GAMMA_TABLE = np.array(
    [int((i / 255.0) ** CFG.gamma * 255 + 0.5) for i in range(256)],
    dtype=np.uint8,
)


# ---------------------------------------------------------------------------
# Etat persistant : historique low_res par chaine (lissage temporel + snap).
# ---------------------------------------------------------------------------
class LowResHistory:
    """
    Historique des couleurs uniques low_res pour chacune des 2 chaines.
    Encapsule l'etat module-level d'origine pour rendre process() testable.
    """
    def __init__(self, window: int):
        self._a: deque = deque(maxlen=window)
        self._b: deque = deque(maxlen=window)

    def update(self, color_a: np.ndarray, color_b: np.ndarray,
               window: int, snap_delta: float) -> tuple[np.ndarray, np.ndarray]:
        if self._a.maxlen != window:
            self._a = deque(self._a, maxlen=window)
            self._b = deque(self._b, maxlen=window)

        if snap_delta > 0:
            if self._a and np.linalg.norm(color_a - self._a[-1]) > snap_delta:
                self._a.clear()
            if self._b and np.linalg.norm(color_b - self._b[-1]) > snap_delta:
                self._b.clear()

        self._a.append(color_a)
        self._b.append(color_b)
        return (
            np.mean(np.stack(self._a), axis=0),
            np.mean(np.stack(self._b), axis=0),
        )


# ---------------------------------------------------------------------------
# Etapes du pipeline. Contrat : entree/sortie en float32 (N, 3) [0..255]
# sauf pour la conversion finale en uint8 effectuee dans process().
# ---------------------------------------------------------------------------
def smooth(current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    if previous is None:
        return current
    return current * (1.0 - CFG.smoothing) + previous * CFG.smoothing


def low_res_moving_avg(colors: np.ndarray, history: LowResHistory) -> np.ndarray:
    """Moyenne glissante sur N frames pour le mode low_res, avec snap."""
    if not CFG.low_res or CFG.low_res_window <= 1:
        return colors

    # Toutes les LEDs d'une chaine ont la meme couleur en mode low_res :
    # la 1re LED de chaque chaine est representative.
    color_a = colors[0].copy()
    color_b = colors[CFG.chain_a_len].copy()

    avg_a, avg_b = history.update(
        color_a, color_b, CFG.low_res_window, CFG.low_res_snap_delta,
    )

    out = colors.copy()
    out[: CFG.chain_a_len] = avg_a
    out[CFG.chain_a_len :] = avg_b
    return out


def apply_hue_shift(colors: np.ndarray) -> np.ndarray:
    """
    Rotation globale de la teinte, en degres. OpenCV encode H sur [0..179]
    (180 = 360), d'ou la division par 2 du decalage avant addition modulo 180.
    """
    if CFG.hue_shift == 0.0:
        return colors
    img = colors.clip(0, 255).astype(np.uint8).reshape(1, -1, 3)
    bgr = img[:, :, ::-1]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[:, :, 0] = (hsv[:, :, 0] + int(round(CFG.hue_shift / 2))) % 180
    bgr2 = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    rgb  = bgr2[:, :, ::-1]
    return rgb.reshape(-1, 3).astype(np.float32)


def boost_saturation(colors: np.ndarray) -> np.ndarray:
    if CFG.saturation_boost == 1.0:
        return colors
    img = colors.clip(0, 255).astype(np.uint8).reshape(1, -1, 3)
    bgr = img[:, :, ::-1]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * CFG.saturation_boost, 0, 255)
    bgr2 = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    rgb  = bgr2[:, :, ::-1]
    return rgb.reshape(-1, 3).astype(np.float32)


def apply_shadow_lift(colors: np.ndarray) -> np.ndarray:
    """out = 255 * (in/255) ** (1/shadow_lift). Boost les noirs sans cramer."""
    if CFG.shadow_lift == 1.0:
        return colors
    norm = colors.clip(0, 255) / 255.0
    return (np.power(norm, 1.0 / CFG.shadow_lift) * 255.0).astype(np.float32)


def smooth_neighbor(colors: np.ndarray) -> np.ndarray:
    """
    Lissage spatial le long du ruban : limite l'ecart entre 2 LEDs voisines
    de la meme chaine a CFG.max_neighbor_delta. Sens DIN→DOUT, chaines
    independantes.
    """
    if CFG.max_neighbor_delta <= 0:
        return colors

    a_len = CFG.chain_a_len
    b_len = CFG.chain_b_len
    md    = float(CFG.max_neighbor_delta)
    out   = colors.copy()

    for i in range(1, a_len):
        diff   = out[i] - out[i - 1]
        out[i] = out[i - 1] + np.clip(diff, -md, md)

    for i in range(a_len + 1, a_len + b_len):
        diff   = out[i] - out[i - 1]
        out[i] = out[i - 1] + np.clip(diff, -md, md)

    return out


def apply_gamma_u8(colors: np.ndarray) -> np.ndarray:
    """Correction gamma via lookup table. float32 -> uint8."""
    return _GAMMA_TABLE[colors.clip(0, 255).astype(np.uint8)]


def apply_filter_u8(colors_u8: np.ndarray) -> np.ndarray:
    """Filtre RGB multiplicatif. uint8 -> uint8."""
    fr, fg, fb = CFG.filter_rgb
    if (fr, fg, fb) == (1.0, 1.0, 1.0):
        return colors_u8
    out = colors_u8.astype(np.float32)
    out[:, 0] *= fr
    out[:, 1] *= fg
    out[:, 2] *= fb
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------
def process(current: np.ndarray, previous: np.ndarray | None,
            history: LowResHistory) -> np.ndarray:
    """
    Pipeline complet. Entree float32 (N, 3) [0..255], sortie uint8 (N, 3).
    Etapes : lissage temporel -> moyenne low_res -> hue shift -> saturation
    -> shadow lift -> lissage spatial -> gamma -> filtre RGB.
    """
    c = current.astype(np.float32, copy=False)
    c = smooth(c, previous)
    c = low_res_moving_avg(c, history)
    c = apply_hue_shift(c)
    c = boost_saturation(c)
    c = apply_shadow_lift(c)
    c = smooth_neighbor(c)
    c = apply_gamma_u8(c)
    return apply_filter_u8(c)
