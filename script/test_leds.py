"""Test des chaines A et B en parallele.

Balaye chaque LED de 0 jusqu'a la fin : on 100 ms, off, LED suivante.
Pause 2 s en fin de chaine, puis recommence.

Usage : depuis le dossier script/
    python3 test_leds.py
"""
import time
import numpy as np

from config import CFG
from udp_sender import UdpSender


ON_MS     = 100
PAUSE_S   = 2.0
COLOR_ON  = np.array([255, 255, 255], dtype=np.uint8)  # blanc

# Chaine(s) a tester : "A", "B" ou "BOTH"
CHAIN = "B"

def main():
    test_a = CHAIN in ("A", "BOTH")
    test_b = CHAIN in ("B", "BOTH")
    if not (test_a or test_b):
        raise ValueError(f"CHAIN doit etre 'A', 'B' ou 'BOTH' (recu : {CHAIN!r})")

    n_steps = max(
        CFG.chain_a_len if test_a else 0,
        CFG.chain_b_len if test_b else 0,
    )

    sender = UdpSender()
    colors = np.zeros((CFG.total_leds, 3), dtype=np.uint8)

    print(
        f"Test : chaine A={CFG.chain_a_len} LEDs, chaine B={CFG.chain_b_len} LEDs, "
        f"cible={CHAIN}, {n_steps} etapes"
    )
    print("Ctrl+C pour arreter.")

    try:
        while True:
            for i in range(n_steps):
                colors[:] = 0
                if test_a and i < CFG.chain_a_len:
                    colors[i] = COLOR_ON
                if test_b and i < CFG.chain_b_len:
                    colors[CFG.chain_a_len + i] = COLOR_ON
                sender.send(colors)
                time.sleep(ON_MS / 1000.0)

            colors[:] = 0
            sender.send(colors)
            time.sleep(PAUSE_S)

    except KeyboardInterrupt:
        colors[:] = 0
        sender.send(colors)
        sender.close()
        print("\nStop.")


if __name__ == "__main__":
    main()
