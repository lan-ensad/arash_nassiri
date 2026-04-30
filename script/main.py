import argparse
import dataclasses
import logging
import time

import cv2

import config
from zones import build_zones, ColorExtractor, draw_zones
from colors import process, LowResHistory
from udp_sender import UdpSender
from terminal_preview import TerminalPreview
from source import open_source, compute_crop, compute_skip_ratio
from window import WindowManager
from fps_monitor import FpsMonitor
from log_setup import setup_logging

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """
    CLI minimal pour les overrides courants. Les flags non specifies
    laissent CFG inchange. Pour modifier les autres champs (gamma,
    saturation, geometrie LEDs...), editer config.py directement.
    """
    p = argparse.ArgumentParser(
        description="Ambilight UDP : capture video -> couleurs LEDs -> ESP32."
    )
    p.add_argument("--video", type=str, help="chemin video / URL (ignore camera)")
    p.add_argument("--camera", type=int, help="index camera (0, 1, ...)")
    p.add_argument("--target-fps", type=float)
    p.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None,
                   help="pas d'envoi UDP")
    p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=None,
                   help="pas de fenetre OpenCV")
    p.add_argument("--fullscreen", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--mirror", action=argparse.BooleanOptionalAction, default=None,
                   help="echange chaine A/B")
    p.add_argument("--low-res", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--full-coverage", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--loop", action=argparse.BooleanOptionalAction, default=None,
                   help="reboucle la lecture fichier")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="active les logs DEBUG")
    return p.parse_args()


def _apply_overrides(args: argparse.Namespace) -> None:
    """Applique les overrides CLI sur CFG (frozen -> dataclasses.replace)."""
    overrides = {}
    if args.video is not None:
        overrides["video_path"]   = args.video
        overrides["camera_index"] = None
    if args.camera is not None:
        overrides["camera_index"] = args.camera
    if args.target_fps is not None:
        overrides["target_fps"]   = args.target_fps
    for name in ("dry_run", "headless", "fullscreen", "mirror", "low_res",
                 "loop"):
        v = getattr(args, name)
        if v is not None:
            overrides[name] = v
    if args.full_coverage is not None:
        overrides["full_coverage"] = args.full_coverage

    if overrides:
        config.CFG = dataclasses.replace(config.CFG, **overrides)
        log.debug("Overrides CLI appliques : %s", overrides)


def main() -> None:
    args = _parse_args()
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
    _apply_overrides(args)
    cfg = config.CFG  # rebind apres _apply_overrides
    cfg.validate()

    cap, source, live = open_source()

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps        = cfg.target_fps if cfg.target_fps else native_fps
    src_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    delay      = 1.0 / fps

    cx0, cy0, cx1, cy1 = compute_crop(src_w, src_h, cfg.target_aspect)
    w, h               = cx1 - cx0, cy1 - cy0
    crop_active        = (cx0, cy0, cx1, cy1) != (0, 0, src_w, src_h)

    src_desc = f"camera index {source}" if isinstance(source, int) else str(source)
    log.info("Source [%s] %s", "live" if live else "fichier", src_desc)
    log.info("Video %dx%d @ %.2ffps natif -> cible %.2ffps",
             src_w, src_h, native_fps, fps)
    if crop_active:
        log.info("Crop %dx%d (aspect cible %.4f, offset x=%d y=%d)",
                 w, h, cfg.target_aspect, cx0, cy0)
    log.info("LEDs %d total (bas %d / droite %d / gauche %d)",
             cfg.total_leds, cfg.leds_bottom, cfg.leds_right, cfg.leds_left)
    log.info("Chaines : A (gauche) = %d LEDs, B (droite) = %d LEDs",
             cfg.chain_a_len, cfg.chain_b_len)
    if cfg.mirror:
        log.info("Mirror : chaines A et B echangees")

    zones     = build_zones(h, w)
    extractor = ColorExtractor(zones)
    history   = LowResHistory(cfg.low_res_window)
    sender    = UdpSender()
    preview   = TerminalPreview(cfg.terminal_preview_hz) if cfg.terminal_preview else None
    window    = WindowManager()
    fps_mon   = FpsMonitor() if preview is None else None
    prev      = None

    skip_ratio = compute_skip_ratio(live, native_fps, cfg.target_fps)
    if skip_ratio > 1:
        log.info("Decimation : capture %.1ffps -> traite 1/%d (~%.1ffps)",
                 native_fps, skip_ratio, native_fps / skip_ratio)
    skip_counter = 0

    if cfg.headless:
        log.info("Controles : [Ctrl+C] dans ce terminal pour arreter")
    else:
        log.info("Controles : [q]/[Echap] dans la fenetre, ou [Ctrl+C] dans ce terminal")

    first_frame  = True
    just_rewound = False

    try:
        while True:
            t0 = time.perf_counter()
            ok, frame = cap.read()

            if not ok:
                if live:
                    time.sleep(0.05)
                    continue
                if cfg.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    prev = None  # reset lissage temporel au rebouclage
                    just_rewound = True
                    continue
                break

            # Decimation : consommer toutes les frames (vide buffer V4L2),
            # mais n'en traiter qu'une sur skip_ratio.
            if skip_ratio > 1:
                skip_counter += 1
                if skip_counter % skip_ratio != 0:
                    continue

            if crop_active:
                frame = frame[cy0:cy1, cx0:cx1]

            raw    = extractor.extract(frame)
            colors = process(raw, prev, history)
            prev   = raw  # lissage sur les couleurs brutes (avant gamma)

            sender.send(colors)

            if preview is not None:
                preview.draw(colors)

            if not cfg.headless:
                if not cfg.fullscreen:
                    draw_zones(frame, zones, colors)
                window.show(frame)

                # Fullscreen apres le 1er imshow et apres chaque rewind
                # (certains WM resize au rebouclage du decoder).
                if first_frame or just_rewound:
                    window.apply_fullscreen()
                    first_frame  = False
                    just_rewound = False

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    break

            if fps_mon is not None:
                fps_mon.tick()

            # Throttle uniquement pour les fichiers (sinon lecture > temps reel).
            # Sur source live : consommer des qu'une frame est prete pour ne
            # pas accumuler de retard dans les buffers V4L2/ffmpeg.
            if not live:
                elapsed = time.perf_counter() - t0
                time.sleep(max(0.0, delay - elapsed))

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        window.close()
        sender.close()
        if preview is not None:
            preview.close()
        log.info("Arret propre.")


if __name__ == "__main__":
    main()
