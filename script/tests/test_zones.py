"""Tests de la construction des zones (peripherique / low_res / full_coverage)."""
import dataclasses
import importlib
import pytest

import config


@pytest.fixture
def reload_zones():
    """
    Helper : remplace CFG, recharge zones, retourne le module recharge.
    Utile car build_zones lit CFG via la reference module-level.
    """
    original = config.CFG

    def _do(**kw):
        config.CFG = dataclasses.replace(original, **kw)
        import zones
        importlib.reload(zones)
        return zones

    yield _do
    config.CFG = original
    import zones
    importlib.reload(zones)


def test_chain_squares_total_matches(reload_zones):
    z = reload_zones(low_res=False, full_coverage=False)
    zones = z.build_zones(720, 1280)
    assert len(zones) == config.CFG.total_leds


def test_chain_squares_origin_at_bottom_center(reload_zones):
    """Avec shift=0, la 1re LED de chaque chaine est centree au bord bas."""
    z = reload_zones(low_res=False, full_coverage=False, chain_shift=0)
    zones = z.build_zones(720, 1280)
    a_first = zones[0]
    b_first = zones[config.CFG.chain_a_len]
    zs   = config.CFG.chain_zone_size
    half = zs // 2
    # Carre A : centre = (cx, h - half) -> x dans [cx-half, cx+half], y dans [h-zs, h].
    assert a_first[3] == 720  # bord bas
    assert a_first[0] <= 1280 // 2 <= a_first[2]
    # Carre B : meme position (les chaines partent du meme point au shift=0).
    assert b_first[3] == 720
    assert b_first[0] <= 1280 // 2 <= b_first[2]


def test_chain_squares_shift_offsets_first_zone(reload_zones):
    """chain_shift=k decale l'index 0 de k * zone_size pixels le long du chemin."""
    z = reload_zones(low_res=False, full_coverage=False, chain_shift=0)
    z0 = z.build_zones(720, 1280)
    z = reload_zones(low_res=False, full_coverage=False, chain_shift=5)
    z5 = z.build_zones(720, 1280)
    # La 1re LED A avec shift=5 doit etre identique a la 6e LED A avec shift=0.
    assert z5[0] == z0[5]
    # Idem chaine B.
    a_len = config.CFG.chain_a_len
    assert z5[a_len] == z0[a_len + 5]


def test_chain_squares_path_progresses_clockwise_for_a(reload_zones):
    """Chaine A : x decroit le long du bas, puis y decroit sur le cote gauche."""
    z = reload_zones(low_res=False, full_coverage=False, chain_shift=0)
    zones = z.build_zones(720, 1280)
    a_zones = zones[: config.CFG.chain_a_len]
    # Premier carre proche du centre bas, dernier carre plus haut/gauche.
    cx_first = (a_zones[0][0] + a_zones[0][2]) // 2
    cx_second = (a_zones[1][0] + a_zones[1][2]) // 2
    assert cx_second < cx_first  # progresse vers la gauche


def test_low_res_total_matches(reload_zones):
    z = reload_zones(low_res=True)
    zones = z.build_zones(720, 1280)
    assert len(zones) == config.CFG.total_leds
    # En mode low_res, 2 zones uniques seulement.
    assert len(set(zones)) == 2


def test_full_coverage_total_matches(reload_zones):
    z = reload_zones(low_res=False, full_coverage=True)
    zones = z.build_zones(720, 1280)
    assert len(zones) == config.CFG.total_leds
    # Toutes les zones doivent etre uniques en full coverage (cellules distinctes).
    assert len(set(zones)) == config.CFG.total_leds


def test_mirror_swaps_chains(reload_zones):
    """mirror=True echange les segments A et B du tableau de zones."""
    z = reload_zones(low_res=False, full_coverage=False, mirror=False)
    zones_normal = z.build_zones(720, 1280)

    z = reload_zones(low_res=False, full_coverage=False, mirror=True)
    zones_mirror = z.build_zones(720, 1280)

    a_len = config.CFG.chain_a_len
    # Chaine A miroir = chaine B normale, et inversement.
    assert zones_mirror[:a_len] == zones_normal[a_len:]
    assert zones_mirror[a_len:] == zones_normal[:a_len]


def test_flip_v_mirrors_y(reload_zones):
    """flip_v reflechit toutes les zones autour de l'axe horizontal."""
    z = reload_zones(low_res=False, full_coverage=False, flip_v=False)
    zn = z.build_zones(720, 1280)

    z = reload_zones(low_res=False, full_coverage=False, flip_v=True)
    zf = z.build_zones(720, 1280)

    h = 720
    expected = [(x1, h - y2, x2, h - y1) for (x1, y1, x2, y2) in zn]
    assert zf == expected


def test_zones_within_image(reload_zones):
    """Toutes les zones doivent etre contenues dans l'image."""
    for mode in [
        {"low_res": True},
        {"low_res": False, "full_coverage": False},
        {"low_res": False, "full_coverage": True},
    ]:
        z = reload_zones(**mode)
        for x1, y1, x2, y2 in z.build_zones(720, 1280):
            assert 0 <= x1 < x2 <= 1280
            assert 0 <= y1 < y2 <= 720
