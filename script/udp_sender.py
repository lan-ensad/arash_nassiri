import logging
import socket
import struct
import numpy as np
import config

log = logging.getLogger(__name__)


# Format du paquet UDP (un par chaine) :
#   octet 0      : 0xAA (magic start)
#   octet 1      : chain_id (0 = A gauche, 1 = B droite)
#   octets 2-3   : seq_num (uint16 big-endian)
#   octets 4..N  : RGB data (n_leds x 3)
#   octet N+1    : 0x55 (magic end)
_HEADER = struct.Struct(">BBH")  # start, chain_id, seq


class UdpSender:
    def __init__(self):
        self._seq = 0

        if config.CFG.dry_run:
            self._sock = None
            log.info(
                "Mode dry-run : pas d'envoi UDP (%d LEDs, 2 paquets/frame ignores)",
                config.CFG.total_leds,
            )
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
        self._addr = (config.CFG.esp32_ip, config.CFG.esp32_port)
        pkt_a = _HEADER.size + config.CFG.chain_a_len * 3 + 1
        pkt_b = _HEADER.size + config.CFG.chain_b_len * 3 + 1
        log.info("UDP cible %s:%d", self._addr[0], self._addr[1])
        log.info("Paquets : chaine A = %d o, chaine B = %d o (par frame)", pkt_a, pkt_b)

    def send(self, colors: np.ndarray) -> None:
        """colors : (N, 3) uint8, ordre chaine A puis chaine B (deja swap si mirror)."""
        if self._sock is None:
            return

        self._seq = (self._seq + 1) & 0xFFFF
        data_a = colors[: config.CFG.chain_a_len].tobytes()
        data_b = colors[config.CFG.chain_a_len : config.CFG.total_leds].tobytes()

        tail = bytes([config.CFG.end_byte])
        pkt_a = _HEADER.pack(config.CFG.start_byte, 0, self._seq) + data_a + tail
        pkt_b = _HEADER.pack(config.CFG.start_byte, 1, self._seq) + data_b + tail

        self._sock.sendto(pkt_a, self._addr)
        self._sock.sendto(pkt_b, self._addr)

    def close(self) -> None:
        if self._sock is None:
            return
        self._sock.close()
