# Ambilight -- Arash Nassiri

Systeme ambilight temps reel : un script Python analyse les bords d'une video, extrait les couleurs dominantes et les envoie en **UDP via WiFi** a un microcontroleur Seeed XIAO ESP32-C6 qui pilote **2 chaines** de 260 LEDs WS2812 (520 LEDs au total, 8.67 m, 60 pixels/m).

L'ESP32 et l'ordinateur de diffusion sont connectes sur un **reseau WiFi ferme** dedie. L'ESP32 est monte au milieu du bas ; les 2 chaines partent de ce point central vers la gauche et la droite, pour minimiser la longueur du fil data.

## Architecture

```
Source video (fichier ou capture HDMI via Cam Link)
    │
    ▼
Script Python (PC)  ──►  analyse des bords  ──►  traitement couleur  ──►  UDP (WiFi)
                         (zones.py)               (colors.py)             (udp_sender.py)
                                                                               │
                                                                               ▼
                                                                 Reseau WiFi ferme
                                                                               │
                                                                               ▼
                                                                      Firmware ESP32-C6
                                                                      (NeoPixelBus → WS2812)
                                                                               │
                                                                               ▼
                                                                      2 chaines de 260 LEDs
                                                                      (A = gauche, B = droite)
```

## Disposition physique

Vu depuis la position du spectateur, **face a l'ecran** :

```
         ┌─────────────────────────────────────────────────────┐
         │                     (haut : pas de ruban)           │
         │                                                     │
         │                                                     │
      ▲  │                                                     │  ▲
      │  │                                                     │  │
  150 │  │                                                     │  │ 150
  LEDs│  │                    [  E C R A N  ]                  │  │ LEDs
      │  │                                                     │  │
      │  │                                                     │  │
      │  └──────────┐                              ┌───────────┘  │
      │             │                              │              │
      └─ CHAINE A ──┤                              ├── CHAINE B ──┘
     (cote gauche)  │                              │   (cote droit)
                    │       ┌──────────────┐       │
      ◄─────────────┤       │  ESP32 + PCB │       ├─────────────►
       110 LEDs     └───────┤              ├───────┘    110 LEDs
       demi-bas             │    milieu    │            demi-bas
       gauche               └──────┬───────┘             droit
                                   │
                                   ▼
                            Alimentation 5 V
```

- **Chaine A** (260 LEDs) : cote **GAUCHE** du spectateur + demi-bas gauche
- **Chaine B** (260 LEDs) : cote **DROIT** du spectateur + demi-bas droit

Pour chaque chaine, le flux data part de l'ESP32, remonte le demi-bas (110 LEDs) puis le cote vertical (150 LEDs, du bas vers le haut).

## Chiffres cles

- **520 LEDs** WS2812 (2 chaines de 260, densite 60 px/m)
- **Alimentation** Mean Well LRS150F-5 (5 V / 30 A)
- **ESP32-C6** sortie D9 = chaine A (gauche), D10 = chaine B (droite)
- **Level shifter** SN74HCT14N (3.3 V → 5 V) entre ESP32 et rubans
- **Protocole** UDP port 4210, 2 paquets/frame (785 o chacun), ~47 KB/s a 30 fps

## Structure du projet

```
arash_nassiri/
├── readme.md               Ce fichier -- documentation generale
│
├── Firmware/               Firmware ESP32-C6 (PlatformIO)
│   └── README.md           → Installation, flashage, protocole UDP, troubleshooting firmware
│
├── script/                 Script Python (cote ordinateur)
│   └── README.md           → Installation, configuration, utilisation, troubleshooting soft
│
├── kicad/                  Electronique (schema + BOM + cablage)
│   ├── README.md           → Dimensionnement, BOM, cablage, precautions electriques
│   └── ambilight_kicad/    Projet KiCad
│
├── test_videos/            Videos de test (generees par ffmpeg)
├── run.sh                  Lancement production (fullscreen + unclutter)
└── _devis/                 Documents administratifs (devis, factures)
```

## Documentation par composant

| Composant | Documentation | Concerne |
|---|---|---|
| Electronique | [kicad/README.md](kicad/README.md) | Dimensionnement, BOM, cablage, SN74HCT14N, alimentation |
| Firmware ESP32 | [Firmware/README.md](Firmware/README.md) | PlatformIO, WiFi, flashage, protocole UDP |
| Script Python | [script/README.md](script/README.md) | OpenCV, source video, pipeline couleur, parametres |

## Demarrage rapide

Ordre recommande pour une premiere mise en route :

1. **Electronique** : lire [kicad/README.md](kicad/README.md), fabriquer / cabler la partie power + level shifter + rubans
2. **Firmware** : remplir `Firmware/src/wifi_config.h` puis flasher (voir [Firmware/README.md](Firmware/README.md))
3. **Script Python** : installer le venv et configurer `script/config.py` (voir [script/README.md](script/README.md))
4. **Lancer** : `./run.sh` depuis la racine (ou configurer le service systemd, section suivante)

Pour **tester le pipeline Python sans materiel** (loopback UDP) : voir la section Troubleshooting dans [script/README.md](script/README.md).

## Lancement automatique au boot (service systemd user)

Pour une installation permanente. Recommande quand la source video est externe (Cam Link) et `headless = True` dans `script/config.py` -- aucune session graphique requise.

**1. Creer le service** dans `~/.config/systemd/user/ambilight.service` :

```ini
[Unit]
Description=Ambilight video capture and UDP send
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/arash_nassiri
ExecStart=/path/to/arash_nassiri/run.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

> Adapter `WorkingDirectory` et `ExecStart` au chemin reel du projet.

**2. Activer et demarrer** :

```bash
mkdir -p ~/.config/systemd/user
# (copier ambilight.service dans ce dossier)
systemctl --user daemon-reload
systemctl --user enable --now ambilight.service
```

**3. Permettre le demarrage sans login utilisateur** (lingering) :

```bash
sudo loginctl enable-linger $USER
```

Sans cette ligne, le service ne demarre qu'apres connexion interactive.

**4. Verifier / operer** :

```bash
systemctl --user status ambilight.service
journalctl --user -u ambilight.service -f    # logs live
systemctl --user restart ambilight.service
systemctl --user stop    ambilight.service
```

**Prerequis systeme** :
- Utilisateur dans le groupe `video` pour acceder a la capture :
  ```bash
  sudo usermod -aG video $USER
  # logout/login pour que le groupe prenne effet
  ```
- `dry_run = False` dans `script/config.py`
- IP ESP32 coherente entre `script/config.py` (`esp32_ip`) et `Firmware/src/wifi_config.h` (`LOCAL_IP_BYTES`)

**Attente WiFi au boot** : si le reseau met du temps a monter, ajouter dans `run.sh` avant le lancement Python :

```bash
for i in {1..30}; do ping -c 1 -W 1 192.168.8.1 >/dev/null 2>&1 && break; sleep 1; done
```

## Reseau WiFi ferme

PC et ESP32 sur un reseau WiFi dedie (routeur/AP dedie ou hotspot du PC). Aucun trafic Internet ni autre appareil -- isolation garantit :
- Latence predictible (pas de contention)
- IP statique possible pour l'ESP32

**Config par defaut** :

| Parametre | Valeur | Fichier |
|---|---|---|
| IP ESP32 | <IP\> | `script/config.py` + `Firmware/src/wifi_config.h` |
| Hostname ESP32 | `esp_ambilight` | `Firmware/src/wifi_config.h` |
| Port UDP | `4210` | `Firmware/src/wifi_config.h` |
| SSID / password | <SSID + PASS\> | `Firmware/src/wifi_config.h` |
