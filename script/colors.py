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
    """Pipeline complet : lissage temporel → saturation → shadow lift →
    lissage spatial → gamma → filtre RGB → uint8."""
    c = smooth(current, previous)
    c = boost_saturation(c)
    c = apply_shadow_lift(c)
    c = smooth_neighbor(c)
    c = apply_gamma(c)
    return apply_filter(c)