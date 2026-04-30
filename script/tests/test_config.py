"""Tests de Config.validate() : chaque branche d'erreur."""
import dataclasses
import pytest

from config import CFG


def _replace(**kw):
    return dataclasses.replace(CFG, **kw)


def test_valid_default():
    """La config par defaut doit etre valide."""
    CFG.validate()  # ne leve pas


def test_leds_bottom_must_be_even():
    cfg = _replace(leds_bottom=221)
    with pytest.raises(ValueError, match="leds_bottom"):
        cfg.validate()


def test_mirror_requires_equal_chain_lengths():
    cfg = _replace(mirror=True, leds_left=100, leds_right=150)
    with pytest.raises(ValueError, match="mirror"):
        cfg.validate()


def test_mirror_ok_with_equal_chains():
    cfg = _replace(mirror=True, leds_left=150, leds_right=150)
    cfg.validate()


def test_full_coverage_grid_total_mismatch():
    cfg = _replace(full_coverage=True, low_res=False, grid_cols=10, grid_rows=10)
    with pytest.raises(ValueError, match="grid_cols \\* grid_rows"):
        cfg.validate()


def test_full_coverage_odd_cols():
    cfg = _replace(
        full_coverage=True, low_res=False,
        grid_cols=21, grid_rows=520 // 21 + 1,
    )
    # 21 impair -> echec sur la 1re check (total mismatch) ou sur le pair check.
    # On s'assure juste qu'une ValueError saute.
    with pytest.raises(ValueError):
        cfg.validate()


def test_derived_lengths():
    """Coherence des proprietes derivees."""
    assert CFG.chain_a_len == CFG.leds_bottom // 2 + CFG.leds_left
    assert CFG.chain_b_len == (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right
    assert CFG.total_leds == CFG.chain_a_len + CFG.chain_b_len
