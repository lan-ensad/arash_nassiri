"""
Fenetre OpenCV : creation, placement multi-moniteur (xrandr), fullscreen.
No-op si config.CFG.headless.
"""

import logging
import os
import shutil
import subprocess

import cv2
import numpy as np

import config
from list_displays import parse_listmonitors

log = logging.getLogger(__name__)


def _get_monitor(index: int) -> dict | None:
    if not shutil.which("xrandr"):
        log.warning("xrandr non trouve : monitor_index ignore (WM decidera de l'ecran).")
        return None
    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], stderr=subprocess.STDOUT
        ).decode()
    except subprocess.CalledProcessError:
        return None
    monitors = parse_listmonitors(out)
    return next((m for m in monitors if m["index"] == index), None)


class WindowManager:
    """
    Encapsule la fenetre OpenCV : creation, placement multi-moniteur,
    fullscreen. No-op si config.CFG.headless.
    """
    NAME = "ambilight"

    def __init__(self):
        self._monitor = None
        if config.CFG.headless:
            log.info("Mode headless : pas de fenetre OpenCV (gain de performance).")
            return

        cv2.namedWindow(self.NAME, cv2.WINDOW_NORMAL)

        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session == "wayland" and config.CFG.monitor_index is not None:
            log.warning(
                "Session Wayland detectee : monitor_index peut etre ignore "
                "par le compositeur. Preferer X11/XWayland."
            )

        if config.CFG.monitor_index is not None:
            self._monitor = _get_monitor(config.CFG.monitor_index)
            if self._monitor is not None:
                m = self._monitor
                log.info(
                    "Ecran : [%d] %s (%dx%d @ (%d, %d))",
                    m["index"], m["name"], m["width"], m["height"], m["x"], m["y"],
                )
            else:
                log.warning(
                    "Ecran index=%d introuvable -> position par defaut.",
                    config.CFG.monitor_index,
                )

        # Realiser la fenetre avec une frame vide pour que moveWindow ait un
        # effet avant le 1er imshow (sinon certains WM ignorent le placement).
        if self._monitor is not None:
            dummy = np.zeros(
                (self._monitor["height"], self._monitor["width"], 3), dtype=np.uint8
            )
            cv2.imshow(self.NAME, dummy)
            cv2.waitKey(1)
            self._place()
            cv2.waitKey(1)

    def _place(self) -> None:
        if self._monitor is None:
            return
        m = self._monitor
        cv2.resizeWindow(self.NAME, m["width"], m["height"])
        cv2.moveWindow(self.NAME, m["x"], m["y"])

    def apply_fullscreen(self) -> None:
        if not config.CFG.fullscreen or config.CFG.headless:
            return
        cv2.setWindowProperty(
            self.NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
        )
        # Re-positionne : certains WM recentrent au toggle fullscreen.
        self._place()

    def show(self, frame: np.ndarray) -> None:
        if not config.CFG.headless:
            cv2.imshow(self.NAME, frame)

    def close(self) -> None:
        if not config.CFG.headless:
            cv2.destroyAllWindows()
