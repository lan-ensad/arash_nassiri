"""Eteint toutes les LEDs des deux chaines puis quitte.

Usage : depuis le dossier script/
    python3 leds_off.py
"""
import numpy as np

from config import CFG
from udp_sender import UdpSender


def main():
    chain_a = CFG.leds_bottom // 2 + CFG.leds_left
    chain_b = (CFG.leds_bottom - CFG.leds_bottom // 2) + CFG.leds_right
    total   = chain_a + chain_b

    sender = UdpSender()
    colors = np.zeros((total, 3), dtype=np.uint8)

    # Envoi redondant : en UDP un paquet peut se perdre, on insiste un peu.
    for _ in range(5):
        sender.send(colors)

    sender.close()
    print(f"Off : {total} LEDs eteintes.")


if __name__ == "__main__":
    main()
