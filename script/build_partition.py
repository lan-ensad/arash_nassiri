"""
Pre-calcul d'une partition LED a partir d'un fichier video.

Lit le fichier image par image, applique le meme pipeline que main.py
(crop -> extract -> process), et stocke le resultat (couleurs LEDs uint8)
avec son timecode dans un sidecar .npz indexe par numero de frame.

Format de sortie (npz) :
- frames     : (T, N_LEDs, 3) uint8 -- exactement ce qui partirait sur l'UDP
- timecodes  : (T,) float32 -- horodatage de chaque frame en secondes (PTS)

La diffusion temps reel (machine differente, synchro OSC depuis Reaper)
charge ce fichier et indexe par timecode recu pour retrouver les LEDs.
"""

import argparse
import logging
import time
from pathlib import Path

import cv2
import numpy as np

import config
from zones import build_zones, ColorExtractor
from colors import process, LowResHistory
from source import open_source, compute_crop
from log_setup import setup_logging

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pre-calcul d'une partition LED a partir d'un fichier video.",
    )
    p.add_argument("--video", type=str,
                   help="chemin video (override config.video_path)")
    p.add_argument("--output", type=str,
                   help="chemin .npz de sortie (defaut : sidecar a cote du .mp4)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def _default_output(video_path: str) -> str:
    return str(Path(video_path).with_suffix(".npz"))


def main() -> None:
    args = _parse_args()
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.video is not None:
        import dataclasses
        config.CFG = dataclasses.replace(
            config.CFG, video_path=args.video, camera_index=None, loop=False,
        )
    else:
        import dataclasses
        config.CFG = dataclasses.replace(config.CFG, camera_index=None, loop=False)

    cfg = config.CFG
    cfg.validate()

    cap, source, live = open_source()
    if live:
        raise RuntimeError(
            "build_partition exige un fichier video (source live detectee)."
        )

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n_est = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    cx0, cy0, cx1, cy1 = compute_crop(src_w, src_h, cfg.target_aspect)
    w, h               = cx1 - cx0, cy1 - cy0
    crop_active        = (cx0, cy0, cx1, cy1) != (0, 0, src_w, src_h)

    out_path = args.output or _default_output(
        source if isinstance(source, str) else cfg.video_path
    )

    log.info("Source : %s", source)
    log.info("Video %dx%d @ %.3ffps -- %d frames estimees", src_w, src_h, fps, n_est)
    if crop_active:
        log.info("Crop %dx%d (aspect %.4f)", w, h, cfg.target_aspect)
    log.info("LEDs %d total (chaine A=%d, B=%d)",
             cfg.total_leds, cfg.chain_a_len, cfg.chain_b_len)
    log.info("Sortie : %s", out_path)

    zones     = build_zones(h, w)
    extractor = ColorExtractor(zones)
    history   = LowResHistory(cfg.low_res_window)
    prev      = None

    # Pre-allocation si n_est fiable, sinon liste dynamique.
    if n_est > 0:
        frames    = np.empty((n_est, cfg.total_leds, 3), dtype=np.uint8)
        timecodes = np.empty(n_est, dtype=np.float32)
    else:
        frames    = None
        timecodes = None
    frames_list:    list[np.ndarray] = []
    timecodes_list: list[float]      = []

    i = 0
    t_start = time.perf_counter()
    log_every = max(1, int(fps * 5)) if fps > 0 else 150

    while True:
        # CAP_PROP_POS_MSEC retourne le PTS du *prochain* frame avant cap.read,
        # donc lire la position avant pour avoir le timecode de la frame qui sort.
        t_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        ok, frame = cap.read()
        if not ok:
            break

        if crop_active:
            frame = frame[cy0:cy1, cx0:cx1]

        raw    = extractor.extract(frame)
        colors = process(raw, prev, history)
        prev   = raw

        if frames is not None and i < n_est:
            frames[i]    = colors
            timecodes[i] = t_ms / 1000.0
        else:
            frames_list.append(colors.copy())
            timecodes_list.append(t_ms / 1000.0)

        i += 1
        if i % log_every == 0:
            elapsed = time.perf_counter() - t_start
            rate    = i / elapsed if elapsed > 0 else 0.0
            if n_est > 0:
                log.info("Frame %d / ~%d (%.0f%% -- %.1f fps traitees)",
                         i, n_est, 100.0 * i / max(1, n_est), rate)
            else:
                log.info("Frame %d (%.1f fps traitees)", i, rate)

    cap.release()

    if frames is None:
        if not frames_list:
            raise RuntimeError("Aucune frame lue.")
        frames    = np.stack(frames_list, axis=0)
        timecodes = np.asarray(timecodes_list, dtype=np.float32)
    else:
        # n_est sur-estime parfois -- tronquer a la longueur reelle.
        frames    = frames[:i]
        timecodes = timecodes[:i]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, frames=frames, timecodes=timecodes)

    elapsed = time.perf_counter() - t_start
    size_mb = frames.nbytes / (1024 * 1024)
    log.info("Partition ecrite : %d frames, %.1f MB, %.1fs (%.1f fps)",
             i, size_mb, elapsed, i / elapsed if elapsed > 0 else 0.0)


if __name__ == "__main__":
    main()
