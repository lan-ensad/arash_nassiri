# Script Python -- cote ordinateur

Capture video, extraction des couleurs peripheriques, envoi UDP vers l'ESP32.

## Prerequis

- Python 3.10+
- OpenCV + NumPy (voir `requirements.txt`)

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuration

Editer `config.py`. Les parametres essentiels :

### Source video (au choix)

- **Fichier local / URL** :
  ```python
  video_path   = "../test_videos/ambilight_test.mp4"
  camera_index = None
  ```
- **Carte de capture HDMI-USB / webcam** (Cam Link, etc.) :
  ```python
  camera_index = 0    # ou 1, 2... selon detection
  ```
  Si `camera_index` est defini, prend le pas sur `video_path`.

Pour identifier le bon index :
```bash
python list_cameras.py
```

Une carte de capture expose souvent 2+ `/dev/videoN` dont seule une produit des frames -- le script teste chacun.

### Reseau

```python
esp32_ip   = "<IP_ESP>"   # IP statique de l'ESP32 (doit correspondre au firmware)
esp32_port = 4210              # port UDP
dry_run    = False             # True = pas d'envoi UDP (test pipeline sans ESP32)
```

Pour tester la pipeline **sans materiel** : passer `esp32_ip = "127.0.0.1"` et lancer un listener dans un 2e terminal (voir Troubleshooting).

## Utilisation

### Mode dev (fenetre OpenCV + preview terminal)

```bash
python main.py
```

### Mode production (fullscreen, sans curseur)

Depuis la racine du projet :

```bash
sudo apt install unclutter       # une fois
../run.sh
```

`run.sh` lance `unclutter` (cache le curseur apres 0.3 s si `$DISPLAY` est defini) puis `main.py` via le venv.

### Demarrage automatique au boot

Voir la doc systemd dans la doc racine -- le script est typiquement lance via `../run.sh` par un service user avec lingering.

## Parametres configurables (config.py)

| Parametre | Defaut | Description |
|---|---|---|
| `video_path` | -- | Chemin vers le fichier video (ou URL rtsp://, http://, /dev/videoN) |
| `camera_index` | `0` | Index de webcam/capture. Si defini, prend le pas sur `video_path` |
| `camera_width` / `camera_height` | `1280 / 720` | Resolution forcee de la camera (None = native) |
| `camera_fps` | None | FPS demande a la camera (None = natif) |
| `target_fps` | 30 | FPS cible (utilise pour throttle la lecture fichier) |
| `loop` | False | Relit la video en boucle (ignore pour source live) |
| `fullscreen` | False | Fenetre plein ecran sans overlay des zones (mode prod) |
| `monitor_index` | None | Index de l'ecran de sortie. None = WM par defaut |
| `headless` | True | True = aucune fenetre OpenCV (gain CPU, pour prod avec affichage externe) |
| `esp32_ip` | `<IP_ESP>` | IP de l'ESP32 (ou `127.0.0.1` pour test loopback) |
| `esp32_port` | 4210 | Port UDP d'ecoute sur l'ESP32 |
| `dry_run` | False | True = pas d'envoi UDP (test du pipeline sans ESP32) |
| `terminal_preview` | True | Affichage ANSI truecolor des 2 chaines dans le terminal |
| `terminal_preview_hz` | 30 | Frequence max de refresh du preview terminal |
| `leds_top` / `right` / `bottom` / `left` | 0 / 150 / 220 / 150 | Nombre de LEDs par cote (leds_bottom doit etre pair) |
| `mirror` | False | Echange chaines A et B (installation miroir sans reflashage) |
| `depth_h` / `depth_w` | 0.08 | Profondeur de capture (fraction de l'image) |
| `smoothing` | 0.30 | Lissage temporel (0 = aucun, 0.5 = fort) |
| `saturation_boost` | 1.6 | Amplification de la saturation |
| `gamma` | 2.2 | Correction gamma pour WS2812 |
| `start_byte` / `end_byte` | `0xAA` / `0x55` | Magic bytes du protocole UDP |

## Pipeline de traitement couleur

1. **Extraction** (`zones.py`) : moyenne des pixels dans chaque zone peripherique (520 zones au total, profondeur 8% de l'image)
2. **Lissage temporel** (`colors.py`) : interpolation lineaire avec la trame precedente (reduit le scintillement)
3. **Boost saturation** (`colors.py`) : conversion HSV, amplification du canal S (couleurs plus vives)
4. **Correction gamma** (`colors.py`) : lookup table precalculee pour compenser la non-linearite des WS2812
5. **Envoi UDP** (`udp_sender.py`) : 2 paquets par frame (un par chaine), fire-and-forget

## Structure des fichiers

```
script/
├── main.py                Boucle principale : capture → traitement → envoi
├── config.py              Parametres (video, LEDs, reseau, couleur)
├── zones.py               Decoupage de l'image en zones peripheriques
├── colors.py              Lissage, boost saturation, correction gamma
├── udp_sender.py          Envoi des paquets UDP vers l'ESP32
├── terminal_preview.py    Preview ANSI truecolor dans le terminal (dev)
├── list_cameras.py        Liste les index webcam utilisables (diagnostic)
├── list_displays.py       Liste les ecrans / sorties video detectes (diagnostic)
└── requirements.txt       Dependances Python (opencv-python, numpy)
```

### Installation miroir (gauche/droite inverses)

Si le cablage physique est miroir par rapport au plan, activer `mirror = True` dans `config.py`. Les chaines A et B sont echangees au niveau UDP, pas besoin de reflasher l'ESP32.

Necessite `leds_left == leds_right` et `leds_bottom` pair (sinon exception au demarrage).

### Session Wayland vs X11

`monitor_index` peut etre ignore par le compositeur Wayland (les apps n'ont pas le droit de bouger leurs fenetres). Preferer une session X11/XWayland si la fenetre ne s'ouvre pas sur le bon ecran.
