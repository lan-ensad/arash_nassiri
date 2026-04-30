import time

import cv2

from config import CFG
from zones import build_zones, ColorExtractor, draw_zones
from colors import process, LowResHistory
from udp_sender import UdpSender
from terminal_preview import TerminalPreview
from source import open_source, compute_crop, compute_skip_ratio
from window import WindowManager
from fps_monitor import FpsMonitor


def main() -> None:
    CFG.validate()
    cap, source, live = open_source()

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps        = CFG.target_fps if CFG.target_fps else native_fps
    src_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    delay      = 1.0 / fps

    cx0, cy0, cx1, cy1 = compute_crop(src_w, src_h, CFG.target_aspect)
    w, h               = cx1 - cx0, cy1 - cy0
    crop_active        = (cx0, cy0, cx1, cy1) != (0, 0, src_w, src_h)

    src_desc = f"camera index {source}" if isinstance(source, int) else str(source)
    kind     = "live" if live else "fichier"
    print(f"Source  : [{kind}] {src_desc}")
    print(f"Video   : {src_w}x{src_h} @ {native_fps:.2f}fps natif -> cible {fps:.2f}fps")
    if crop_active:
        print(f"Crop    : {w}x{h} (aspect cible {CFG.target_aspect:.4f}, "
              f"offset x={cx0} y={cy0})")
    print(f"LEDs    : {CFG.total_leds} total (bas {CFG.leds_bottom} / "
          f"droite {CFG.leds_right} / gauche {CFG.leds_left})")
    print(f"Chaines : A (gauche) = {CFG.chain_a_len} LEDs, B (droite) = "
          f"{CFG.chain_b_len} LEDs")
    if CFG.mirror:
        print("Mirror  : chaines A et B echangees (compensation cablage miroir)")

    zones     = build_zones(h, w)
    extractor = ColorExtractor(zones)
    history   = LowResHistory(CFG.low_res_window)
    sender    = UdpSender()
    preview   = TerminalPreview(CFG.terminal_preview_hz) if CFG.terminal_preview else None
    window    = WindowManager()
    fps_mon   = FpsMonitor() if preview is None else None
    prev      = None

    skip_ratio = compute_skip_ratio(live, native_fps, CFG.target_fps)
    if skip_ratio > 1:
        print(f"Decimation : capture {native_fps:.1f}fps -> traite 1/{skip_ratio} "
              f"(soit ~{native_fps/skip_ratio:.1f}fps)")
    skip_counter = 0

    if CFG.headless:
        print("Controles : [Ctrl+C] dans ce terminal pour arreter")
    else:
        print("Controles : [q] ou [Echap] dans la fenetre, ou [Ctrl+C] dans ce terminal")

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
                if CFG.loop:
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

            if not CFG.headless:
                if not CFG.fullscreen:
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
        print("Arret propre.")


if __name__ == "__main__":
    main()
