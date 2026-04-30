"""Equivalence numerique ColorExtractor (image integrale) vs region.mean()."""
import numpy as np
import pytest

from zones import build_zones, ColorExtractor


@pytest.fixture
def frame():
    rng = np.random.default_rng(seed=42)
    return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)


def _ref_means(frame, zones):
    """Reference : moyenne par boucle Python + np.mean (BGR -> RGB)."""
    out = np.empty((len(zones), 3), dtype=np.float32)
    for i, (x1, y1, x2, y2) in enumerate(zones):
        m = frame[y1:y2, x1:x2].mean(axis=(0, 1))
        out[i] = (m[2], m[1], m[0])
    return out


def test_extractor_matches_naive_mean(frame):
    """L'image integrale doit donner exactement les memes moyennes (a epsilon flottant pres)."""
    zones = build_zones(720, 1280)
    ex = ColorExtractor(zones)
    got = ex.extract(frame)
    ref = _ref_means(frame, zones)
    assert np.abs(got - ref).max() < 1e-3


def test_extractor_dedup_low_res(frame):
    """En mode low_res les zones sont dupliquees ; meme couleur dans toute la chaine."""
    from config import CFG
    if not CFG.low_res:
        pytest.skip("CFG.low_res=False par defaut, skip")
    zones = build_zones(720, 1280)
    ex = ColorExtractor(zones)
    out = ex.extract(frame)
    a = out[: CFG.chain_a_len]
    b = out[CFG.chain_a_len :]
    # Toutes les LEDs d'une chaine ont la meme couleur extraite.
    assert np.all(a == a[0])
    assert np.all(b == b[0])


def test_extractor_empty():
    """Pas de zones -> tableau vide, pas de crash."""
    ex = ColorExtractor([])
    out = ex.extract(np.zeros((10, 10, 3), dtype=np.uint8))
    assert out.shape == (0, 3)
