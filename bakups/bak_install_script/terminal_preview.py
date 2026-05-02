import shutil
import sys
import time
import numpy as np
from config import CFG


_RESET = "\x1b[0m"


class TerminalPreview:
    """
    Affiche les 2 chaines dans le terminal avec des blocs ANSI truecolor,
    mis a jour en place (cursor-up). Utile pour dev/test en dry_run.
    """

    def __init__(self, throttle_hz: float = 10.0):
        self._chain_a_len = CFG.leds_bottom // 2 + CFG.leds_left
        self._chain_b_len = (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right
        self._min_interval = 1.0 / throttle_hz
        self._last_t = 0.0
        self._printed_once = False
        self._last_frame_t = time.perf_counter()
        self._ema_fps = 0.0

    # --------------------------------------------------------
    def _blocks(self, colors: np.ndarray, width: int) -> str:
        """Sous-echantillonne `colors` a `width` blocs et retourne la chaine ANSI."""
        n = len(colors)
        if n == 0 or width <= 0:
            return ""
        # Moyenne par tranche pour preserver les transitions fines
        parts = []
        for i in range(width):
            s = int(round(i * n / width))
            e = int(round((i + 1) * n / width))
            if e <= s:
                e = s + 1
            c = colors[s:e].mean(axis=0)
            r = max(0, min(255, int(c[0])))
            g = max(0, min(255, int(c[1])))
            b = max(0, min(255, int(c[2])))
            parts.append(f"\x1b[48;2;{r};{g};{b}m ")
        return "".join(parts) + _RESET

    # --------------------------------------------------------
    def draw(self, colors: np.ndarray) -> None:
        now = time.perf_counter()
        if now - self._last_t < self._min_interval:
            return
        self._last_t = now

        # FPS lisse (EMA) pour affichage
        dt = now - self._last_frame_t
        self._last_frame_t = now
        if dt > 0:
            inst = 1.0 / dt
            self._ema_fps = inst if self._ema_fps == 0 else 0.2 * inst + 0.8 * self._ema_fps

        cols   = shutil.get_terminal_size((120, 24)).columns
        prefix = 20  # longueur de "Chaine X (xxx): "
        width  = max(20, cols - prefix - 1)

        a = colors[: self._chain_a_len]
        b = colors[self._chain_a_len : self._chain_a_len + self._chain_b_len]

        line_a  = f"Chaine A ({self._chain_a_len:3d}): {self._blocks(a, width)}"
        line_b  = f"Chaine B ({self._chain_b_len:3d}): {self._blocks(b, width)}"
        line_st = f"Preview   ~{self._ema_fps:5.1f} fps (throttle {1/self._min_interval:.0f} Hz)"

        out = []
        if self._printed_once:
            out.append("\x1b[3A")  # remonte de 3 lignes
        else:
            self._printed_once = True

        out.append("\x1b[2K" + line_a + "\n")
        out.append("\x1b[2K" + line_b + "\n")
        out.append("\x1b[2K" + line_st + "\n")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # --------------------------------------------------------
    def close(self) -> None:
        if self._printed_once:
            sys.stdout.write("\n")
            sys.stdout.flush()
