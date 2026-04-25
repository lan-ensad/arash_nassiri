import cv2
import numpy as np
from config import CFG


Zone = tuple[int, int, int, int]  # x1, y1, x2, y2


def build_zones(h: int, w: int) -> list[Zone]:
    """
    L'ESP32 est monte au milieu du bas. Deux chaines de LEDs partent de ce
    point central vers l'exterieur, pour reduire la longueur du fil data.

    Chaine A (gauche) : demi-bas milieu→gauche, puis cote gauche bas→haut
    Chaine B (droite) : demi-bas milieu→droite, puis cote droit  bas→haut

    La trame serie contient Chaine A puis Chaine B, dans l'ordre DIN→DOUT.
    """
    dh = max(1, int(h * CFG.depth_h))
    dw = max(1, int(w * CFG.depth_w))

    half_bottom = CFG.leds_bottom // 2  # 110 LEDs par demi-bas
    zones: list[Zone] = []

    # Les bornes de zones sont calculees en float puis arrondies, pour que
    # les N zones couvrent exactement [0, w] (ou [0, h]) quelle que soit la
    # resolution : la zone i va de round(i * dim / N) a round((i+1) * dim / N).

    def col_bounds(col: int) -> tuple[int, int]:
        return (
            round(col * w / CFG.leds_bottom),
            round((col + 1) * w / CFG.leds_bottom),
        )

    def row_bounds_side(i: int, total: int) -> tuple[int, int]:
        """
        i=0  → tranche la plus basse (juste au-dessus de la bande du bas)
        i=N-1 → tranche la plus haute (y proche de 0)
        Ordre bas→haut pour suivre le sens DIN→DOUT le long du cote.

        On limite a [0, h - dh] pour ne PAS chevaucher la bande du bas :
        sinon la zone bottom-most du cote recouvre les zones bottom du coin,
        ce qui (a) biaise l'extraction couleur dans le coin et (b) cree une
        "ombre" visible dans draw_zones (la zone du cote est dessinee apres
        et masque le coin des rectangles du bas).
        """
        inv = total - 1 - i
        available_h = h - dh
        return (
            round(inv * available_h / total),
            round((inv + 1) * available_h / total),
        )

    # --- Chaine A : demi-bas gauche (milieu → gauche) ---
    # i=0 → colonne juste a gauche du milieu ; i=half_bottom-1 → extreme gauche
    for i in range(half_bottom):
        col = half_bottom - 1 - i
        x1, x2 = col_bounds(col)
        zones.append((x1, h - dh, x2, h))  # bas de l'image

    # --- Chaine A : cote gauche (bas → haut) ---
    for i in range(CFG.leds_left):
        y1, y2 = row_bounds_side(i, CFG.leds_left)
        zones.append((0, y1, dw, y2))

    # --- Chaine B : demi-bas droite (milieu → droite) ---
    for i in range(CFG.leds_bottom - half_bottom):
        col = half_bottom + i
        x1, x2 = col_bounds(col)
        zones.append((x1, h - dh, x2, h))

    # --- Chaine B : cote droit (bas → haut) ---
    for i in range(CFG.leds_right):
        y1, y2 = row_bounds_side(i, CFG.leds_right)
        zones.append((w - dw, y1, w, y2))

    return zones


def extract_colors(frame: np.ndarray, zones: list[Zone]) -> np.ndarray:
    """
    Retourne un array (N, 3) float32 RGB [0..255]
    pour chaque zone via moyenne de pixels.
    """
    result = np.empty((len(zones), 3), dtype=np.float32)
    for i, (x1, y1, x2, y2) in enumerate(zones):
        region = frame[y1:y2, x1:x2]  # BGR
        mean   = region.mean(axis=(0, 1))
        result[i] = (mean[2], mean[1], mean[0])  # BGR → RGB
    return result


def draw_zones(frame: np.ndarray, zones: list[Zone], colors: np.ndarray) -> None:
    """
    Superpose chaque zone sur l'image avec la couleur LED finale (preview
    "color picker"). Modifie frame en place.

    colors : (N, 3) uint8 RGB (typiquement la sortie du pipeline process()).
    """
    for (x1, y1, x2, y2), rgb in zip(zones, colors):
        bgr = (int(rgb[2]), int(rgb[1]), int(rgb[0]))  # RGB → BGR pour OpenCV
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), bgr, thickness=cv2.FILLED)
        # Bordure noire fine pour distinguer les LEDs voisines
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), (0, 0, 0), thickness=1)
