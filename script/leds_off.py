"""Eteint toutes les LEDs des deux chaines puis quitte.

Usage : depuis le dossier script/
    python3 leds_off.py
"""
import logging

import numpy as np

import config
from log_setup import setup_logging
from udp_sender import UdpSender

log = logging.getLogger(__name__)


def main():
    setup_logging()
    sender = UdpSender()
    colors = np.zeros((config.CFG.total_leds, 3), dtype=np.uint8)

    # Envoi redondant : en UDP un paquet peut se perdre, insister un peu.
    for _ in range(5):
        sender.send(colors)

    sender.close()
    log.info("Off : %d LEDs eteintes.", config.CFG.total_leds)


if __name__ == "__main__":
    main()
