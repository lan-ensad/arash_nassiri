import cv2
import numpy as np
from config import CFG


Zone = tuple[int, int, int, int]  # x1, y1, x2, y2


# ---------------------------------------------------------------------------
# Construction des zones (peripherique / full_coverage / low_res)
# ---------------------------------------------------------------------------
def build_zones(h: int, w: int) -> list[Zone]:
    """
    Construit la liste des zones d'echantillonnage selon le mode.

    Ordre de la liste : chaine A (chain_a_len entrees) puis chaine B
    (chain_b_len entrees), dans le sens DIN -> DOUT le long du ruban.

    Modes :
    - low_res        : 2 zones carrees uniques, dupliquees sur chaque chaine
                       (prioritaire sur full_coverage).
    - full_coverage  : grille uniforme de zones carrees couvrant l'image.
    - peripherique   : bandes le long du bas + cotes (mode ambilight standard).

    Transformations finales :
    - flip_v : miroir vertical (cas ESP32 monte en haut au lieu du bas).
    - mirror : echange chaine A <-> chaine B (compense un cablage miroir).
    """
    if CFG.low_res:
        zones = _build_zones_low_res(h, w)
    elif CFG.full_coverage:
        zones = _build_zones_full_coverage(h, w)
    else:
        zones = _build_zones_perimeter(h, w)

    if CFG.flip_v:
        zones = [(x1, h - y2, x2, h - y1) for (x1, y1, x2, y2) in zones]

    if CFG.mirror:
        # Swap des moitiees A et B (longueurs egales validees par CFG.validate()).
        zones = zones[CFG.chain_a_len :] + zones[: CFG.chain_a_len]

    return zones


def _build_zones_perimeter(h: int, w: int) -> list[Zone]:
    """
    Mode ambilight standard : bandes au bas + cotes.
    Chaine A : demi-bas milieu->gauche, puis cote gauche bas->haut.
    Chaine B : demi-bas milieu->droite, puis cote droit  bas->haut.

    Les cotes evitent la zone du bas (y dans [0, h - dh]) pour ne pas
    chevaucher la bande horizontale dans les coins.
    """
    dh = max(1, int(h * CFG.depth_h))
    dw = max(1, int(w * CFG.depth_w))
    half_bottom = CFG.leds_bottom // 2

    def col_bounds(col: int) -> tuple[int, int]:
        return (
            round(col * w / CFG.leds_bottom),
            round((col + 1) * w / CFG.leds_bottom),
        )

    def row_bounds_side(i: int, total: int) -> tuple[int, int]:
        # i=0 -> tranche la plus basse (juste au-dessus de la bande du bas).
        inv = total - 1 - i
        avail = h - dh
        return (
            round(inv * avail / total),
            round((inv + 1) * avail / total),
        )

    zones: list[Zone] = []

    # Chaine A : demi-bas gauche (milieu -> gauche)
    for i in range(half_bottom):
        col = half_bottom - 1 - i
        x1, x2 = col_bounds(col)
        zones.append((x1, h - dh, x2, h))

    # Chaine A : cote gauche (bas -> haut)
    for i in range(CFG.leds_left):
        y1, y2 = row_bounds_side(i, CFG.leds_left)
        zones.append((0, y1, dw, y2))

    # Chaine B : demi-bas droite (milieu -> droite)
    for i in range(CFG.leds_bottom - half_bottom):
        col = half_bottom + i
        x1, x2 = col_bounds(col)
        zones.append((x1, h - dh, x2, h))

    # Chaine B : cote droit (bas -> haut)
    for i in range(CFG.leds_right):
        y1, y2 = row_bounds_side(i, CFG.leds_right)
        zones.append((w - dw, y1, w, y2))

    return zones


def _build_zones_low_res(h: int, w: int) -> list[Zone]:
    """
    2 zones carrees uniques, repliquees sur l'integralite de chaque chaine.
    low_res_a_xy = coin haut-gauche zone A. low_res_b_xy=None -> aligne a droite.
    """
    size = CFG.low_res_size

    ax, ay = CFG.low_res_a_xy
    zone_a = (max(0, ax), max(0, ay), min(w, ax + size), min(h, ay + size))

    if CFG.low_res_b_xy is None:
        bx, by = w - size, 0
    else:
        bx, by = CFG.low_res_b_xy
    zone_b = (max(0, bx), max(0, by), min(w, bx + size), min(h, by + size))

    return [zone_a] * CFG.chain_a_len + [zone_b] * CFG.chain_b_len


def _build_zones_full_coverage(h: int, w: int) -> list[Zone]:
    """
    Grille uniforme de zones carrees (cote = zone_size) couvrant toute
    l'image. Si zone_size > espacement, les zones se chevauchent (lissage
    spatial). Mapping LED -> cellule : split + serpentin par colonnes.
    Validation des dimensions assuree par CFG.validate().
    """
    cols, rows, zs = CFG.grid_cols, CFG.grid_rows, CFG.zone_size
    half_cols = cols // 2

    def cell_center(col: int, row: int) -> tuple[int, int]:
        return (
            round((col + 0.5) * w / cols),
            round((row + 0.5) * h / rows),
        )

    def square_zone(cx: int, cy: int) -> Zone:
        half_lo = zs // 2
        half_hi = zs - half_lo
        return (
            max(0, cx - half_lo),
            max(0, cy - half_lo),
            min(w, cx + half_hi),
            min(h, cy + half_hi),
        )

    zones: list[Zone] = []

    # Chaine A : cols half_cols-1 -> 0 (du milieu vers la gauche)
    for k in range(half_cols):
        col = half_cols - 1 - k
        for r in range(rows):
            row    = (rows - 1 - r) if (k % 2 == 0) else r
            cx, cy = cell_center(col, row)
            zones.append(square_zone(cx, cy))

    # Chaine B : cols half_cols -> cols-1 (du milieu vers la droite)
    for k in range(cols - half_cols):
        col = half_cols + k
        for r in range(rows):
            row    = (rows - 1 - r) if (k % 2 == 0) else r
            cx, cy = cell_center(col, row)
            zones.append(square_zone(cx, cy))

    return zones


# ---------------------------------------------------------------------------
# Extraction couleur via image integrale
# ---------------------------------------------------------------------------
class ColorExtractor:
    """
    Extrait la couleur moyenne de chaque zone via l'image integrale OpenCV
    (O(1) par zone apres construction). Deduplique automatiquement les
    zones identiques (critique en mode low_res : 2 uniques x ~260 LEDs).

    Construit une fois par session : pre-calcule les coordonnees uniques.
    """
    def __init__(self, zones: list[Zone]):
        self._n = len(zones)
        if self._n == 0:
            self._uniq = np.zeros((0, 4), dtype=np.int32)
            self._inv  = np.zeros(0, dtype=np.int64)
            self._area = np.zeros((0, 1), dtype=np.float32)
            return

        # Deduplication : conserve l'ordre d'apparition pour l'index inverse.
        uniq_idx: dict[Zone, int] = {}
        inv = np.empty(self._n, dtype=np.int64)
        for i, z in enumerate(zones):
            j = uniq_idx.get(z)
            if j is None:
                j = len(uniq_idx)
                uniq_idx[z] = j
            inv[i] = j

        self._uniq = np.array(list(uniq_idx.keys()), dtype=np.int32)
        self._inv  = inv
        w = (self._uniq[:, 2] - self._uniq[:, 0]).clip(min=1)
        h = (self._uniq[:, 3] - self._uniq[:, 1]).clip(min=1)
        self._area = (w * h).astype(np.float32).reshape(-1, 1)

    def extract(self, frame: np.ndarray) -> np.ndarray:
        """Retourne (N, 3) float32 RGB [0..255]."""
        if self._n == 0:
            return np.empty((0, 3), dtype=np.float32)

        # cv2.integral : retourne (H+1, W+1, C) int32 ou int64 ; S[y, x]
        # = somme cumulee de frame[:y, :x] -> formule rectangle en O(1).
        S = cv2.integral(frame)

        x1 = self._uniq[:, 0]; y1 = self._uniq[:, 1]
        x2 = self._uniq[:, 2]; y2 = self._uniq[:, 3]

        sums = S[y2, x2] - S[y1, x2] - S[y2, x1] + S[y1, x1]  # (M, 3) BGR
        means_bgr = sums.astype(np.float32) / self._area
        means_rgb = means_bgr[:, ::-1]  # BGR -> RGB

        return means_rgb[self._inv]


# ---------------------------------------------------------------------------
# Preview (overlay zones colorees)
# ---------------------------------------------------------------------------
def draw_zones(frame: np.ndarray, zones: list[Zone], colors: np.ndarray) -> None:
    """
    Superpose chaque zone sur l'image avec la couleur LED finale.
    Modifie frame en place. colors : (N, 3) uint8 RGB.
    """
    for (x1, y1, x2, y2), rgb in zip(zones, colors):
        bgr = (int(rgb[2]), int(rgb[1]), int(rgb[0]))
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), bgr, thickness=cv2.FILLED)
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), (0, 0, 0), thickness=1)
