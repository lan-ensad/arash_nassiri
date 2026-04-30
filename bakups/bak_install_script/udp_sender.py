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
        self._chain_a_len = CFG.leds_bottom // 2 + CFG.leds_left
        self._chain_b_len = (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right
        self._total       = self._chain_a_len + self._chain_b_len
        self._seq         = 0

        if CFG.mirror and self._chain_a_len != self._chain_b_len:
            raise ValueError(
                f"mirror=True impose chaine A et B de meme longueur "
                f"(A={self._chain_a_len}, B={self._chain_b_len}). "
                "Verifier que leds_left == leds_right et que leds_bottom est pair."
            )

        if CFG.dry_run:
            self._sock = None
            print(
                f"Mode dry-run : pas d'envoi UDP "
                f"({self._chain_a_len + self._chain_b_len} LEDs, "
                f"2 paquets/frame ignores)"
            )
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
        self._addr = (CFG.esp32_ip, CFG.esp32_port)
        pkt_a = _HEADER.size + self._chain_a_len * 3 + 1
        pkt_b = _HEADER.size + self._chain_b_len * 3 + 1
        print(f"UDP : cible {self._addr[0]}:{self._addr[1]}")
        print(f"Paquets : chaine A = {pkt_a} o, chaine B = {pkt_b} o (par frame)")
        if CFG.mirror:
            print("Mirror : chaines A et B echangees (compensation installation miroir)")

    def send(self, colors: np.ndarray) -> None:
        """colors : (N, 3) uint8, ordre chaine A puis chaine B."""
        if self._sock is None:
            return

        self._seq = (self._seq + 1) & 0xFFFF
        if CFG.mirror:
            data_a = colors[self._chain_a_len : self._total].tobytes()
            data_b = colors[: self._chain_a_len].tobytes()
        else:
            data_a = colors[: self._chain_a_len].tobytes()
            data_b = colors[self._chain_a_len : self._total].tobytes()

        tail = bytes([CFG.end_byte])
        pkt_a = _HEADER.pack(CFG.start_byte, 0, self._seq) + data_a + tail
        pkt_b = _HEADER.pack(CFG.start_byte, 1, self._seq) + data_b + tail

        self._sock.sendto(pkt_a, self._addr)
        self._sock.sendto(pkt_b, self._addr)

    def close(self) -> None:
        if self._sock is None:
            return
        self._sock.close()
