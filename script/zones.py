import logging

import cv2
import numpy as np
import config


Zone = tuple[int, int, int, int]  # x1, y1, x2, y2

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Construction des zones (chain_squares / full_coverage / low_res)
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
    - chain_squares  : chaine de carrees jointifs sur le perimetre, partant
                       du centre bas (mode par defaut).

    Transformations finales :
    - flip_v : miroir vertical (cas ESP32 monte en haut au lieu du bas).
    - mirror : echange chaine A <-> chaine B (compense un cablage miroir).
    """
    if config.CFG.low_res:
        zones = _build_zones_low_res(h, w)
    elif config.CFG.full_coverage:
        zones = _build_zones_full_coverage(h, w)
    else:
        zones = _build_zones_chain_squares(h, w)

    if config.CFG.flip_v:
        zones = [(x1, h - y2, x2, h - y1) for (x1, y1, x2, y2) in zones]

    if config.CFG.mirror:
        # Swap des moitiees A et B (longueurs egales validees par config.CFG.validate()).
        zones = zones[config.CFG.chain_a_len :] + zones[: config.CFG.chain_a_len]

    return zones


def _build_zones_chain_squares(h: int, w: int) -> list[Zone]:
    """
    Chaine de carres jointifs en serpentin. Chaque LED = 1 carre de cote
    chain_zone_size centre sur un point du chemin.

    Chemin (chaine A) : centre_bas -> coin bas-gauche -> coin haut-gauche
    -> centre_haut. Si le nombre de LEDs depasse ce premier passage, le
    chemin redescend vers le centre_bas en repassant par le cote, decale
    de chain_zone_size vers l'interieur. Les passages alternent ensuite
    montee/descente, en s'enfoncant de zs a chaque demi-tour, jusqu'a
    saturation de l'image. Chaine B en miroir (cote droit).

    Si le serpentin lui-meme est sature (image trop petite pour le nombre
    de LEDs), les LEDs en exces sont clippees a la fin du chemin (warning).
    Les carres sont clippes aux bords de l'image dans les coins.
    """
    zs    = config.CFG.chain_zone_size
    shift = config.CFG.chain_shift
    half  = zs // 2
    cx    = w // 2

    polyline_a = _chain_polyline(h, w, zs, half, cx, side="left")
    polyline_b = _chain_polyline(h, w, zs, half, cx, side="right")
    total_a = _polyline_length(polyline_a)
    total_b = _polyline_length(polyline_b)

    def square_at(cx_p: int, cy_p: int) -> Zone:
        return (
            max(0, cx_p - half),
            max(0, cy_p - half),
            min(w, cx_p + (zs - half)),
            min(h, cy_p + (zs - half)),
        )

    # Verification du debordement (warning, pas erreur : clippage doux ensuite).
    needed_a = (shift + config.CFG.chain_a_len - 1) * zs
    needed_b = (shift + config.CFG.chain_b_len - 1) * zs
    if needed_a > total_a or needed_b > total_b:
        excess = max(needed_a - total_a, needed_b - total_b)
        log.warning(
            "chain_squares : serpentin %dpx insuffisant pour %d LEDs + shift %d "
            "@ chain_zone_size=%d (deborde de %dpx, LEDs en exces clippees "
            "a la fin du chemin). Reduire chain_zone_size, chain_shift, ou "
            "agrandir l'image.",
            min(total_a, total_b), max(config.CFG.chain_a_len, config.CFG.chain_b_len),
            shift, zs, excess,
        )

    zones: list[Zone] = []
    for i in range(config.CFG.chain_a_len):
        s = (shift + i) * zs
        zones.append(square_at(*_walk_polyline(polyline_a, s)))
    for i in range(config.CFG.chain_b_len):
        s = (shift + i) * zs
        zones.append(square_at(*_walk_polyline(polyline_b, s)))

    return zones


def _chain_polyline(
    h: int, w: int, zs: int, half: int, cx: int, side: str,
) -> list[tuple[int, int]]:
    """
    Polyligne du serpentin chaine A (side='left') ou chaine B (side='right').

    Demarre au centre bas, longe le cote, atteint le centre haut. Si l'image
    le permet, repart vers le centre bas par le meme cote inset de zs, et
    ainsi de suite jusqu'a saturation (corner se rapproche du centre ou
    fenetre verticale fermee).
    """
    pts: list[tuple[int, int]] = [(cx, h - half)]
    loop = 0
    while True:
        inset = loop * zs
        if side == "left":
            x_corner = half + inset
            inside_x = x_corner < cx
        else:
            x_corner = w - half - inset
            inside_x = x_corner > cx
        y_top = half + inset
        y_bot = h - half - inset
        if not inside_x or y_top >= y_bot:
            break

        if loop % 2 == 0:
            # Aller : centre_bas -> coin bas -> coin haut -> centre_haut.
            pts.append((x_corner, y_bot))
            pts.append((x_corner, y_top))
            pts.append((cx, y_top))
            next_y = y_top + zs
            if next_y >= y_bot:
                break
            pts.append((cx, next_y))   # transition vers la couche inset suivante
        else:
            # Retour : centre_haut -> coin haut -> coin bas -> centre_bas.
            pts.append((x_corner, y_top))
            pts.append((x_corner, y_bot))
            pts.append((cx, y_bot))
            next_y = y_bot - zs
            if next_y <= y_top:
                break
            pts.append((cx, next_y))
        loop += 1
    return pts


def _polyline_length(pts: list[tuple[int, int]]) -> int:
    total = 0
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        total += abs(x1 - x0) + abs(y1 - y0)  # segments axis-aligned
    return total


def _walk_polyline(pts: list[tuple[int, int]], s: float) -> tuple[int, int]:
    """Position sur la polyligne a l'arc-length s. Clippe aux extremites."""
    if not pts:
        return (0, 0)
    s = max(0.0, s)
    cum = 0.0
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg_len = abs(x1 - x0) + abs(y1 - y0)
        if seg_len <= 0:
            continue
        if s <= cum + seg_len:
            t = (s - cum) / seg_len
            return (round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t))
        cum += seg_len
    return pts[-1]


def _build_zones_low_res(h: int, w: int) -> list[Zone]:
    """
    2 zones carrees uniques, repliquees sur l'integralite de chaque chaine.
    low_res_a_xy = coin haut-gauche zone A. low_res_b_xy=None -> aligne a droite.
    """
    size = config.CFG.low_res_size

    ax, ay = config.CFG.low_res_a_xy
    zone_a = (max(0, ax), max(0, ay), min(w, ax + size), min(h, ay + size))

    if config.CFG.low_res_b_xy is None:
        bx, by = w - size, 0
    else:
        bx, by = config.CFG.low_res_b_xy
    zone_b = (max(0, bx), max(0, by), min(w, bx + size), min(h, by + size))

    return [zone_a] * config.CFG.chain_a_len + [zone_b] * config.CFG.chain_b_len


def _build_zones_full_coverage(h: int, w: int) -> list[Zone]:
    """
    Grille uniforme de zones carrees (cote = zone_size) couvrant toute
    l'image. Si zone_size > espacement, les zones se chevauchent (lissage
    spatial). Mapping LED -> cellule : split + serpentin par colonnes.
    Validation des dimensions assuree par config.CFG.validate().
    """
    cols, rows, zs = config.CFG.grid_cols, config.CFG.grid_rows, config.CFG.zone_size
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
