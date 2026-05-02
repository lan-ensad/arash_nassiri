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

    Si CFG.flip_v est True, un miroir vertical est applique a toutes les
    zones (cas ou l'ESP32 et la bande horizontale sont montes en haut au
    lieu du bas) : la geometrie reste identique, simplement reflechie.

    Si CFG.full_coverage est True, mode alternatif : grille uniforme de
    zones carrees couvrant toute l'image (voir _build_zones_full_coverage).

    Si CFG.low_res est True (prioritaire sur full_coverage), mode 2 zones :
    1 carre par chaine, couleur unique repliquee sur tous les LEDs de la
    chaine (voir _build_zones_low_res).
    """
    if CFG.low_res:
        return _build_zones_low_res(h, w)
    if CFG.full_coverage:
        return _build_zones_full_coverage(h, w)

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

    # Miroir vertical si l'ESP32 + bande sont montes en haut au lieu du bas.
    # Reflechir les zones plutot que reconstruire toute la geometrie : le
    # mapping LED → zone reste coherent car la chaine entiere est miroir.
    if CFG.flip_v:
        zones = [(x1, h - y2, x2, h - y1) for (x1, y1, x2, y2) in zones]

    return zones


def _build_zones_low_res(h: int, w: int) -> list[Zone]:
    """
    Mode low_res : 2 zones carrees uniques. La zone A est dupliquee sur toute
    la chaine A (chain_a_len LEDs), idem pour B. Chaque chaine affiche donc
    une couleur unie, tiree de l'echantillon de sa zone.

    - low_res_a_xy : coin haut-gauche de la zone A (defaut (0, 0)).
    - low_res_b_xy : coin haut-gauche de la zone B. None → auto-aligne a
      droite (coin droit = bord droit image).
    - low_res_size : cote des deux carres en pixels.

    Les zones sont clippees aux bords de l'image. Pas de chevauchement
    significatif si les positions sont sensees (default = 2 coins opposes).
    """
    size = CFG.low_res_size

    # Zone A
    ax, ay = CFG.low_res_a_xy
    zone_a = (
        max(0, ax),
        max(0, ay),
        min(w, ax + size),
        min(h, ay + size),
    )

    # Zone B : None = aligne a droite
    if CFG.low_res_b_xy is None:
        bx, by = w - size, 0
    else:
        bx, by = CFG.low_res_b_xy
    zone_b = (
        max(0, bx),
        max(0, by),
        min(w, bx + size),
        min(h, by + size),
    )

    chain_a_len = CFG.leds_bottom // 2 + CFG.leds_left
    chain_b_len = (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right

    # Duplication : chaque LED de la chaine pointe vers la meme zone source.
    # extract_colors recalcule la moyenne pour chaque entree (overhead
    # negligeable a 2 zones uniques sur ce volume).
    return [zone_a] * chain_a_len + [zone_b] * chain_b_len


def _build_zones_full_coverage(h: int, w: int) -> list[Zone]:
    """
    Mode full coverage : grille uniforme de zones carrees couvrant toute
    l'image. Chaque LED = une cellule. Si zone_size > espacement, les
    zones se chevauchent (lissage spatial).

    Mapping LED → cellule (split α + serpentin par colonnes) :
    - Chaine A = moitie gauche (cols mid-1 → 0).
      Col mid-1 (proche du milieu) : LEDs 0..rows-1 en bas→haut.
      Col mid-2 : LEDs suivantes en haut→bas.
      Alternance jusqu'a la col 0.
    - Chaine B = moitie droite (cols mid → cols-1), meme logique :
      col mid bas→haut, col mid+1 haut→bas, etc.

    Si CFG.flip_v, miroir Y final (comme le mode peripherique).
    """
    cols = CFG.grid_cols
    rows = CFG.grid_rows
    zs   = CFG.zone_size

    # Validation : la grille doit matcher exactement le total des LEDs
    # cote Python (= cote firmware tant que c'est aligne).
    chain_a_len = CFG.leds_bottom // 2 + CFG.leds_left
    chain_b_len = (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right
    total_leds  = chain_a_len + chain_b_len

    if cols * rows != total_leds:
        raise ValueError(
            f"full_coverage : grid_cols * grid_rows = {cols*rows} "
            f"doit egaler le total des LEDs ({total_leds})."
        )
    if cols % 2 != 0:
        raise ValueError(
            f"full_coverage : grid_cols ({cols}) doit etre pair "
            f"pour repartir egalement entre chaines A et B."
        )
    if (cols // 2) * rows != chain_a_len:
        raise ValueError(
            f"full_coverage : (grid_cols/2) * grid_rows = "
            f"{(cols // 2) * rows} doit egaler chain_a_len ({chain_a_len})."
        )

    half_cols = cols // 2

    def cell_center(col: int, row: int) -> tuple[int, int]:
        return (
            round((col + 0.5) * w / cols),
            round((row + 0.5) * h / rows),
        )

    def square_zone(cx: int, cy: int) -> Zone:
        # Carre de cote zs centre sur (cx, cy), clippe aux bords de l'image.
        half_lo = zs // 2
        half_hi = zs - half_lo  # garantit zs = half_lo + half_hi pour zs impair
        return (
            max(0, cx - half_lo),
            max(0, cy - half_lo),
            min(w, cx + half_hi),
            min(h, cy + half_hi),
        )

    zones: list[Zone] = []

    # --- Chaine A : cols half_cols-1 → 0 (du milieu vers la gauche) ---
    for k in range(half_cols):
        col = half_cols - 1 - k
        for r in range(rows):
            # k pair (col proche du milieu) : bas→haut
            # k impair                      : haut→bas
            row    = (rows - 1 - r) if (k % 2 == 0) else r
            cx, cy = cell_center(col, row)
            zones.append(square_zone(cx, cy))

    # --- Chaine B : cols half_cols → cols-1 (du milieu vers la droite) ---
    for k in range(cols - half_cols):
        col = half_cols + k
        for r in range(rows):
            row    = (rows - 1 - r) if (k % 2 == 0) else r
            cx, cy = cell_center(col, row)
            zones.append(square_zone(cx, cy))

    if CFG.flip_v:
        zones = [(x1, h - y2, x2, h - y1) for (x1, y1, x2, y2) in zones]

    return zones


def extract_colors(frame: np.ndarray, zones: list[Zone]) -> np.ndarray:
    """
    Retourne un array (N, 3) float32 RGB [0..255]
    pour chaque zone via moyenne de pixels.

    Cache les zones identiques (cles tuple hashable) pour eviter de recalculer
    une zone deja vue dans la meme frame. Critique en mode low_res (2 zones
    repliquees x260) ou tout autre mode avec duplicats. Aucun overhead
    significatif quand toutes les zones sont uniques.
    """
    cache: dict[Zone, tuple] = {}
    result = np.empty((len(zones), 3), dtype=np.float32)
    for i, zone in enumerate(zones):
        rgb = cache.get(zone)
        if rgb is None:
            x1, y1, x2, y2 = zone
            region = frame[y1:y2, x1:x2]  # BGR
            mean   = region.mean(axis=(0, 1))
            rgb    = (mean[2], mean[1], mean[0])  # BGR → RGB
            cache[zone] = rgb
        result[i] = rgb
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
