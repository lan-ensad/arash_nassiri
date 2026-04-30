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


def apply_gamma(colors: np.ndarray) -> np.ndarray:
    """Correction gamma via lookup table."""
    return _GAMMA_TABLE[colors.clip(0, 255).astype(np.uint8)]


def process(current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    """Pipeline complet : lissage → saturation → gamma → uint8."""
    c = smooth(current, previous)
    c = boost_saturation(c)
    return apply_gamma(c)