"""
Genere 4 images PNG de couleurs unies pour tester la diffusion ambilight :
blanc, rouge, vert, blanc.

Usage :
    python3 script/gen_test_images.py

Les images sont ecrites dans test_images/ a la racine du projet.
Pour les utiliser comme source, pointer CFG.video_path dessus :
    video_path: str = "test_images/red.png"
"""
import os
import cv2
import numpy as np


OUT_DIR = "test_images"
W, H    = 1920, 1080

# (nom de fichier, BGR) -- OpenCV imwrite attend du BGR
PALETTE = [
    ("white_1.png", (255, 255, 255)),
    ("red.png",     (0,   0,   255)),
    ("green.png",   (0,   255, 0)),
    ("white_2.png", (255, 255, 255)),
]


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, bgr in PALETTE:
        img  = np.full((H, W, 3), bgr, dtype=np.uint8)
        path = os.path.join(OUT_DIR, name)
        cv2.imwrite(path, img)
        print(f"ecrit : {path} ({W}x{H}, BGR={bgr})")


if __name__ == "__main__":
    main()
