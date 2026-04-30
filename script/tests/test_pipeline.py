"""Tests du pipeline colors.process : contrat dtype et court-circuits."""
import dataclasses
import importlib
import numpy as np
import pytest

import config


@pytest.fixture
def reload_colors():
    """
    Recharge colors apres modification de CFG. Necessaire car _GAMMA_TABLE
    est calculee a l'import en lisant CFG.gamma.
    """
    original = config.CFG

    def _do(**kw):
        config.CFG = dataclasses.replace(original, **kw)
        import colors
        importlib.reload(colors)
        return colors

    yield _do
    config.CFG = original
    import colors
    importlib.reload(colors)


def _input_colors(n=520):
    rng = np.random.default_rng(seed=7)
    return rng.uniform(0, 255, (n, 3)).astype(np.float32)


def test_pipeline_returns_uint8(reload_colors):
    """Contrat : sortie toujours uint8 (N, 3)."""
    colors = reload_colors()
    n = config.CFG.total_leds
    inp = _input_colors(n)
    history = colors.LowResHistory(config.CFG.low_res_window)
    out = colors.process(inp, None, history)
    assert out.dtype == np.uint8
    assert out.shape == (n, 3)


def test_pipeline_idempotent_with_neutral_config(reload_colors):
    """
    Avec gamma=1.0, smoothing=0, hue_shift=0, saturation_boost=1, shadow_lift=1,
    max_neighbor_delta=0, filter_rgb=(1,1,1), low_res inactif -> sortie = round(input).
    """
    colors = reload_colors(
        gamma=1.0, smoothing=0.0, hue_shift=0.0,
        saturation_boost=1.0, shadow_lift=1.0,
        max_neighbor_delta=0, filter_rgb=(1.0, 1.0, 1.0),
        low_res=False,
    )
    n = config.CFG.total_leds
    inp = _input_colors(n)
    history = colors.LowResHistory(1)
    out = colors.process(inp, None, history)
    expected = np.clip(inp, 0, 255).astype(np.uint8)
    # Tolerance d'un cran (round-half rules entre np et le LUT gamma identite).
    assert np.abs(out.astype(np.int16) - expected.astype(np.int16)).max() <= 1


def test_smoothing_returns_average(reload_colors):
    """smooth(c, prev) = c*(1-s) + prev*s."""
    colors = reload_colors(smoothing=0.5, gamma=1.0)
    a = np.full((10, 3), 100.0, dtype=np.float32)
    b = np.full((10, 3), 200.0, dtype=np.float32)
    out = colors.smooth(b, a)
    assert np.allclose(out, 150.0)


def test_low_res_history_snap(reload_colors):
    """Snap : si delta > seuil, l'historique est vide et la nouvelle valeur adoptee."""
    colors = reload_colors()
    h = colors.LowResHistory(window=5)
    a1 = np.array([100, 100, 100], dtype=np.float32)
    a2 = np.array([100, 100, 100], dtype=np.float32)
    avg_a, _ = h.update(a1, a1, window=5, snap_delta=50.0)
    avg_a, _ = h.update(a2, a2, window=5, snap_delta=50.0)
    assert np.allclose(avg_a, 100.0)
    # Saut large -> snap, historique purge -> avg = nouvelle valeur seule
    a3 = np.array([255, 0, 0], dtype=np.float32)
    avg_a, _ = h.update(a3, a3, window=5, snap_delta=50.0)
    assert np.allclose(avg_a, a3)


def test_filter_rgb_neutral_shortcut(reload_colors):
    """filter_rgb=(1,1,1) ne touche pas les valeurs."""
    colors = reload_colors(filter_rgb=(1.0, 1.0, 1.0))
    inp = np.array([[10, 20, 30], [40, 50, 60]], dtype=np.uint8)
    out = colors.apply_filter_u8(inp)
    assert np.array_equal(out, inp)


def test_filter_rgb_multiplies(reload_colors):
    colors = reload_colors(filter_rgb=(2.0, 1.0, 0.5))
    inp = np.array([[100, 100, 100]], dtype=np.uint8)
    out = colors.apply_filter_u8(inp)
    assert out[0, 0] == 200
    assert out[0, 1] == 100
    assert out[0, 2] == 50
