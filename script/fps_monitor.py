"""
Mesure du FPS sur fenetre glissante. Log uniquement les transitions par
rapport au baseline auto-calibre (max FPS observe). Silencieux en regime
nominal.
"""

import time


class FpsMonitor:
    def __init__(self, window: float = 1.0, drop_threshold: float = 0.80):
        self._count    = 0
        self._t0       = time.perf_counter()
        self._window   = window
        self._thresh   = drop_threshold
        self._baseline = 0.0
        self._in_drop  = False

    def tick(self) -> None:
        self._count += 1
        now = time.perf_counter()
        dt  = now - self._t0
        if dt < self._window:
            return
        fps = self._count / dt
        if fps > self._baseline:
            self._baseline = fps
        is_low = self._baseline > 0 and fps < self._baseline * self._thresh
        if is_low and not self._in_drop:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] FPS chute : {fps:5.1f} (baseline {self._baseline:5.1f})")
            self._in_drop = True
        elif not is_low and self._in_drop:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{ts}] FPS retabli : {fps:5.1f} (baseline {self._baseline:5.1f})")
            self._in_drop = False
        self._count = 0
        self._t0    = now
