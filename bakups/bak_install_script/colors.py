from collections import deque

import cv2
import numpy as np
from config import CFG


# Table de gamma precalculee une seule fois
_GAMMA_TABLE = np.array(
    [int((i / 255.0) ** CFG.gamma * 255 + 0.5) for i in range(256)],
    dtype=np.uint8,
)


def smooth(current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    if previous is None:
        return current
    return current * (1.0 - CFG.smoothing) + previous * CFG.smoothing


def apply_hue_shift(colors: np.ndarray) -> np.ndarray:
    """
    Rotation globale de la teinte, en degres. Compense un color cast en
    amont (mauvaise matrice YUV→RGB, lampes ambiantes...). Travaille en
    HSV : seul le canal H est decale, S et V intacts.

    OpenCV encode H sur [0..179] (180° = 360°), donc on divise par 2 le
    decalage en degres avant addition modulo 180.
    """
    if CFG.hue_shift == 0.0:
        return colors
    img = colors.astype(np.uint8).reshape(1, -1, 3)
    bgr = img[:, :, ::-1]  # RGB → BGR
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[:, :, 0] = (hsv[:, :, 0] + int(round(CFG.hue_shift / 2))) % 180
    bgr2 = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    rgb  = bgr2[:, :, ::-1]
    return rgb.reshape(-1, 3).astype(np.float32)


def boost_saturation(colors: np.ndarray) -> np.ndarray:
    """
    colors : (N, 3) float32 RGB [0..255]
    Retourne le meme tableau avec la saturation boostee.
    """
    if CFG.saturation_boost == 1.0:
        return colors

    # Conversion en image HSV via OpenCV
    img = colors.astype(np.uint8).reshape(1, -1, 3)
    img_bgr = img[:, :, ::-1]  # RGB → BGR
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * CFG.saturation_boost, 0, 255)
    bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    rgb = bgr[:, :, ::-1]  # BGR → RGB
    return rgb.reshape(-1, 3).astype(np.float32)


def apply_shadow_lift(colors: np.ndarray) -> np.ndarray:
    """
    Remontee non-lineaire des noirs : out = 255 * (in/255) ** (1/shadow_lift).
    Boost les zones sombres sans cramer les zones claires (255 reste 255).
    """
    if CFG.shadow_lift == 1.0:
        return colors
    norm = colors.clip(0, 255) / 255.0
    return np.power(norm, 1.0 / CFG.shadow_lift) * 255.0


def apply_gamma(colors: np.ndarray) -> np.ndarray:
    """Correction gamma via lookup table."""
    return _GAMMA_TABLE[colors.clip(0, 255).astype(np.uint8)]


# Historique des 2 couleurs uniques en mode low_res (chaine A et B).
# State module-level : conserve entre les appels successifs a process().
_low_res_hist_a: deque = deque(maxlen=1)
_low_res_hist_b: deque = deque(maxlen=1)


def low_res_moving_avg(colors: np.ndarray) -> np.ndarray:
    """
    Moyenne glissante sur N frames pour le mode low_res, avec snap sur grand
    delta. Lisse les micro-variations sans introduire de lag exponentiel ;
    le snap purge l'historique sur un changement franc → reactivite preservee.

    Court-circuit si low_res inactif ou window <= 1.
    """
    global _low_res_hist_a, _low_res_hist_b

    if not CFG.low_res or CFG.low_res_window <= 1:
        return colors

    n = CFG.low_res_window
    if _low_res_hist_a.maxlen != n:
        _low_res_hist_a = deque(_low_res_hist_a, maxlen=n)
        _low_res_hist_b = deque(_low_res_hist_b, maxlen=n)

    chain_a_len = CFG.leds_bottom // 2 + CFG.leds_left

    # En mode low_res, toutes les LEDs de la chaine ont la meme couleur :
    # on peut prendre la 1re LED de chaque chaine comme representative.
    color_a = colors[0].astype(np.float32, copy=True)
    color_b = colors[chain_a_len].astype(np.float32, copy=True)

    # Snap : si l'ecart depasse le seuil, purger l'historique.
    snap = CFG.low_res_snap_delta
    if snap > 0:
        if _low_res_hist_a and np.linalg.norm(color_a - _low_res_hist_a[-1]) > snap:
            _low_res_hist_a.clear()
        if _low_res_hist_b and np.linalg.norm(color_b - _low_res_hist_b[-1]) > snap:
            _low_res_hist_b.clear()

    _low_res_hist_a.append(color_a)
    _low_res_hist_b.append(color_b)

    avg_a = np.mean(np.stack(_low_res_hist_a), axis=0)
    avg_b = np.mean(np.stack(_low_res_hist_b), axis=0)

    out = colors.astype(np.float32, copy=True)
    out[:chain_a_len] = avg_a
    out[chain_a_len:] = avg_b
    return out


def smooth_neighbor(colors: np.ndarray) -> np.ndarray:
    """
    Lissage spatial le long du ruban : limite l'ecart de couleur entre 2 LEDs
    voisines dans la meme chaine a CFG.max_neighbor_delta (par canal RGB).
    Si l'ecart depasse la limite, la LED suivante est rapprochee de la
    precedente. Sens DIN→DOUT, chaines A et B traitees independamment.
    """
    if CFG.max_neighbor_delta <= 0:
        return colors

    half_bottom = CFG.leds_bottom // 2
    chain_a_len = half_bottom + CFG.leds_left
    chain_b_len = (CFG.leds_bottom - half_bottom) + CFG.leds_right
    md          = float(CFG.max_neighbor_delta)

    out = colors.astype(np.float32, copy=True)

    # Forward pass dans chaine A : LED 0 → chain_a_len-1
    for i in range(1, chain_a_len):
        diff   = out[i] - out[i - 1]
        out[i] = out[i - 1] + np.clip(diff, -md, md)

    # Forward pass dans chaine B : LED chain_a_len → fin (independante)
    for i in range(chain_a_len + 1, chain_a_len + chain_b_len):
        diff   = out[i] - out[i - 1]
        out[i] = out[i - 1] + np.clip(diff, -md, md)

    return out


def apply_filter(colors: np.ndarray) -> np.ndarray:
    """
    Filtre colorimetrique multiplicatif par canal RGB. Applique en sortie,
    apres gamma : compensation derive batch LED, balance des blancs, teinte.
    (1.0, 1.0, 1.0) = neutre, court-circuit.
    """
    fr, fg, fb = CFG.filter_rgb
    if (fr, fg, fb) == (1.0, 1.0, 1.0):
        return colors
    out = colors.astype(np.float32, copy=True)
    out[:, 0] *= fr
    out[:, 1] *= fg
    out[:, 2] *= fb
    return np.clip(out, 0, 255).astype(np.uint8)


def process(current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    """Pipeline complet : lissage temporel → moyenne glissante low_res →
    hue shift → saturation → shadow lift → lissage spatial → gamma →
    filtre RGB → uint8."""
    c = smooth(current, previous)
    c = low_res_moving_avg(c)
    c = apply_hue_shift(c)
    c = boost_saturation(c)
    c = apply_shadow_lift(c)
    c = smooth_neighbor(c)
    c = apply_gamma(c)
    return apply_filter(c)