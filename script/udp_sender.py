import socket
import struct
import numpy as np
from config import CFG


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

        if CFG.dry_run:
            self._sock = None
            print(
                f"Mode dry-run : pas d'envoi UDP ({CFG.total_leds} LEDs, "
                "2 paquets/frame ignores)"
            )
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
        self._addr = (CFG.esp32_ip, CFG.esp32_port)
        pkt_a = _HEADER.size + CFG.chain_a_len * 3 + 1
        pkt_b = _HEADER.size + CFG.chain_b_len * 3 + 1
        print(f"UDP : cible {self._addr[0]}:{self._addr[1]}")
        print(f"Paquets : chaine A = {pkt_a} o, chaine B = {pkt_b} o (par frame)")

    def send(self, colors: np.ndarray) -> None:
        """colors : (N, 3) uint8, ordre chaine A puis chaine B (deja swap si mirror)."""
        if self._sock is None:
            return

        self._seq = (self._seq + 1) & 0xFFFF
        data_a = colors[: CFG.chain_a_len].tobytes()
        data_b = colors[CFG.chain_a_len : CFG.total_leds].tobytes()

        tail = bytes([CFG.end_byte])
        pkt_a = _HEADER.pack(CFG.start_byte, 0, self._seq) + data_a + tail
        pkt_b = _HEADER.pack(CFG.start_byte, 1, self._seq) + data_b + tail

        self._sock.sendto(pkt_a, self._addr)
        self._sock.sendto(pkt_b, self._addr)

    def close(self) -> None:
        if self._sock is None:
            return
        self._sock.close()
