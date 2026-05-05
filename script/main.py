"""
Lecteur de partition LED synchronise sur OSC.

- Charge un sidecar .npz produit par build_partition.py (frames + timecodes).
- Lance un serveur OSC UDP qui ecoute le timecode envoye par Reaper.
- A chaque message OSC, indexe la partition par timecode et envoie les
  couleurs LEDs correspondantes a l'ESP32 via UDP.

Cote Reaper :
- Preferences > Control/OSC/Web > Add > OSC.
- Mode "Configure device IP+port" : IP de cette machine + port (defaut 9000).
- Activer le feedback de timecode raw (cf. config.osc_time_address).

Cote LEDs : meme protocole UDP que main.py historique (cf. udp_sender.py).
"""

import argparse
import dataclasses
import logging
import socket
import threading
from pathlib import Path

import numpy as np
from pythonosc import dispatcher as osc_dispatcher
from pythonosc import osc_server

import config
from udp_sender import UdpSender
from log_setup import setup_logging

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lecteur de partition LED synchronise sur OSC (Reaper)."
    )
    p.add_argument("--partition", type=str,
                   help="chemin .npz (override config.partition_path)")
    p.add_argument("--osc-host", type=str,
                   help="IP de bind du serveur OSC (defaut config.osc_host)")
    p.add_argument("--osc-port", type=int,
                   help="port de bind du serveur OSC (defaut config.osc_port)")
    p.add_argument("--osc-address", type=str,
                   help="adresse OSC du timecode (defaut config.osc_time_address)")
    p.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None,
                   help="pas d'envoi UDP vers l'ESP32")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="active les logs DEBUG")
    return p.parse_args()


def _apply_overrides(args: argparse.Namespace) -> None:
    overrides: dict = {}
    if args.partition is not None:
        overrides["partition_path"] = args.partition
    if args.osc_host is not None:
        overrides["osc_host"] = args.osc_host
    if args.osc_port is not None:
        overrides["osc_port"] = args.osc_port
    if args.osc_address is not None:
        overrides["osc_time_address"] = args.osc_address
    if args.dry_run is not None:
        overrides["dry_run"] = args.dry_run
    if overrides:
        config.CFG = dataclasses.replace(config.CFG, **overrides)
        log.debug("Overrides CLI appliques : %s", overrides)


def _local_ip() -> str:
    """
    Detecte l'IP locale principale (interface vers la passerelle par defaut).
    Pas d'envoi reel : connect UDP cree juste une route, pas de paquet.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _load_partition(path: str) -> tuple[np.ndarray, np.ndarray]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Partition introuvable : {p}. Generer d'abord avec "
            f"`python3 build_partition.py --video <fichier.mp4>`."
        )
    data = np.load(p)
    frames    = data["frames"]
    timecodes = data["timecodes"]
    if frames.ndim != 3 or frames.shape[2] != 3 or frames.dtype != np.uint8:
        raise ValueError(
            f"Format inattendu pour frames : shape={frames.shape}, "
            f"dtype={frames.dtype} (attendu (T, N, 3) uint8)."
        )
    if timecodes.ndim != 1 or timecodes.shape[0] != frames.shape[0]:
        raise ValueError(
            f"Format inattendu pour timecodes : shape={timecodes.shape} "
            f"(attendu ({frames.shape[0]},))."
        )
    n_leds = frames.shape[1]
    if n_leds != config.CFG.total_leds:
        raise ValueError(
            f"Partition produite pour {n_leds} LEDs, config courante = "
            f"{config.CFG.total_leds}. Regenerer la partition avec la meme "
            f"config (geometrie LEDs)."
        )
    return frames, timecodes


def _coerce_time(args: tuple) -> float | None:
    """
    Convertit le payload OSC en secondes (float). Reaper envoie typiquement
    un float raw, mais peut envoyer un string formate ("h:mm:ss.fff") selon
    la config feedback. Retourne None si non parsable.
    """
    if not args:
        return None
    v = args[0]
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            pass
        # Format "h:mm:ss.fff" ou "mm:ss.fff"
        parts = v.split(":")
        try:
            parts_f = [float(x) for x in parts]
        except ValueError:
            return None
        total = 0.0
        for x in parts_f:
            total = total * 60.0 + x
        return total
    return None


class PartitionPlayer:
    """
    Etat de lecture : partition chargee + dernier index envoye + sender UDP.
    Thread-safe via _lock (callback OSC vs cleanup).
    """
    def __init__(self, frames: np.ndarray, timecodes: np.ndarray,
                 sender: UdpSender):
        self.frames    = frames
        self.timecodes = timecodes
        self.sender    = sender
        self._last_idx = -1
        self._lock     = threading.Lock()
        # Stats simples pour log periodique.
        self._osc_count = 0

    def on_time(self, address: str, *args) -> None:
        t = _coerce_time(args)
        if t is None:
            log.warning("OSC %s : payload non parsable %r", address, args)
            return
        # searchsorted side="right" - 1 -> dernier frame avec timecode <= t.
        idx = int(np.searchsorted(self.timecodes, t, side="right")) - 1
        if idx < 0:
            idx = 0
        elif idx >= len(self.frames):
            idx = len(self.frames) - 1

        with self._lock:
            if idx == self._last_idx:
                return
            self._last_idx = idx
            self.sender.send(self.frames[idx])
            self._osc_count += 1
            if self._osc_count == 1 or self._osc_count % 300 == 0:
                log.info("OSC #%d : t=%.3fs -> frame %d/%d",
                         self._osc_count, t, idx, len(self.frames))


def main() -> None:
    args = _parse_args()
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
    _apply_overrides(args)
    cfg = config.CFG
    cfg.validate()

    frames, timecodes = _load_partition(cfg.partition_path)
    duration = float(timecodes[-1] - timecodes[0]) if len(timecodes) else 0.0
    log.info("Partition chargee : %s", cfg.partition_path)
    log.info("  %d frames, %d LEDs, duree %.2fs",
             len(frames), frames.shape[1], duration)

    sender = UdpSender()
    player = PartitionPlayer(frames, timecodes, sender)

    disp = osc_dispatcher.Dispatcher()
    disp.map(cfg.osc_time_address, player.on_time)

    # Log "no match" en debug pour aider la mise au point cote Reaper.
    def _unmatched(address: str, *args):
        log.debug("OSC non mappe : %s %r", address, args)
    disp.set_default_handler(_unmatched)

    server = osc_server.ThreadingOSCUDPServer((cfg.osc_host, cfg.osc_port), disp)

    bind_ip = cfg.osc_host
    local_ip = _local_ip()
    if bind_ip in ("0.0.0.0", "::"):
        reaper_target = f"{local_ip}:{cfg.osc_port}"
    else:
        reaper_target = f"{bind_ip}:{cfg.osc_port}"
    log.info("Serveur OSC : bind %s:%d (adresse %s)",
             bind_ip, cfg.osc_port, cfg.osc_time_address)
    log.info("Reaper doit emettre vers %s (machine locale : %s)",
             reaper_target, local_ip)
    log.info("Controles : [Ctrl+C] pour arreter")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        sender.close()
        log.info("Arret propre.")


if __name__ == "__main__":
    main()
