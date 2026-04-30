"""Eteint toutes les LEDs des deux chaines puis quitte.

Usage : depuis le dossier script/
    python3 leds_off.py
"""
import numpy as np

from config import CFG
from udp_sender import UdpSender


def main():
    sender = UdpSender()
    colors = np.zeros((CFG.total_leds, 3), dtype=np.uint8)

    # Envoi redondant : en UDP un paquet peut se perdre, insister un peu.
    for _ in range(5):
        sender.send(colors)

    sender.close()
    print(f"Off : {CFG.total_leds} LEDs eteintes.")


if __name__ == "__main__":
    main()
