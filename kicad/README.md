# Electronique -- Ambilight

Ce dossier contient le schema KiCad et toute la documentation electronique du projet (matiere, cablage, calculs, precautions).

Pour la partie logicielle (script Python + firmware ESP32) voir le [readme.md](../readme.md) a la racine.

## Vue d'ensemble

```
                                Mean Well LRS150F-5
                               ┌──────────────────┐
                       AC IN ──┤ L   N   ⏚        │
                               │                  │
                               │   +5V    GND     │
                               └───┬───────┬──────┘
                                   │       │
                              1000uF cap   │
                                   │       │
          ┌────────────────────────┼───────┼────────────────────────┐
          │  RAIL 5V (16AWG)       │       │  RAIL GND (16AWG)      │
          │                        │       │                        │
          │    ┌───────────────────┼───────┼──────────┐             │
          ▼    ▼                   ▼       ▼          ▼             ▼
     INJECTION 1              INJECTION 2        INJECTION 3
    (extremite gauche,        (milieu du bas,    (extremite droite,
     en haut du cote)         pres de l'ESP)     en haut du cote)
      100uF cap                100uF cap          100uF cap

    ┌─────────────────────────────────┬─────────────────────────────────┐
    │          CHAINE A (260 LEDs)    │          CHAINE B (260 LEDs)    │
    │  ┌────────────┬────────────┐    │    ┌────────────┬────────────┐  │
    │  │  GAUCHE    │  1/2 BAS   │    │    │  1/2 BAS   │  DROITE    │  │
    │  │  (150)     │  gauche    │    │    │  droite    │  (150)     │  │
    │  │  bas→haut  │  (110)     │    │    │  (110)     │  bas→haut  │  │
    │  │            │  gauche ←  │◄DIN│DIN►│  → droite  │            │  │
    │  │   DOUT ←── │ ← ─────────│    │    │────────── →│ ──► DOUT   │  │
    │  └────────────┴────────────┘    │    └────────────┴────────────┘  │
    └─────────────────────────────────┴─────────────────────────────────┘
                                 ▲       ▲
                    330 ohm ─────┤       ├──── 330 ohm
                                 │       │
                         data 5V │       │ data 5V (< 30 cm, 22AWG)
                          pin 4  │       │ pin 10
                    ┌────────────┴───────┴─────────────┐
                    │  SN74HCT14N (hex Schmitt inv.)   │
                    │                                  │
                    │  Chaine A : pin 1 → pin 2,       │
                    │             pin 3 → pin 4        │
                    │  Chaine B : pin 13 → pin 12,     │
                    │             pin 11 → pin 10      │
                    │                                  │
                    │  VCC = pin 14 (+5V) + 100nF      │
                    │  GND = pin 7                     │
                    │  entrees NC (5, 9) → GND         │
                    └──────▲──────────────▲────────────┘
                           │ pin 1        │ pin 13
                           │ data A 3.3V  │ data B 3.3V
                    ┌──────┴──────────────┴────────────┐
                    │  XIAO ESP32-C6                   │
                    │     D9 ─(chaine A gauche)        │
                    │    D10 ─(chaine B droite)        │
                    │    USB ← 5V (alim seule,         │
                    │          chargeur ou powerbank)  │
                    │    WiFi ◄─── UDP (port 4210)     │
                    └─────────────────────▲────────────┘
                                          │ reseau WiFi ferme dedie
                                          │
                                   ┌──────┴───────┐
                                   │  PC (Python) │
                                   │  udp_sender  │
                                   └──────────────┘
```

## Dimensionnement

### Installation

| Cote | Longueur |
|---|---|
| Bas | 368 cm |
| Droite | 250 cm |
| Gauche | 250 cm |
| **Total** | **868 cm = 8.68 m** |

### LEDs

Densite du ruban : **60 pixels/m**

| Cote | Longueur | LEDs |
|---|---|---|
| Bas | 3.67 m | 3.67 x 60 = **220** (110 + 110, symetrique) |
| Droite | 2.50 m | 2.50 x 60 = **150** |
| Gauche | 2.50 m | 2.50 x 60 = **150** |
| **Total** | **8.67 m** | **520 LEDs** |

Le bas est ramene de 221 a **220 LEDs** pour une **repartition symetrique** (110 par demi-cote). Le gain physique est de 1,67 cm, negligeable visuellement.

### Repartition en 2 chaines

L'ESP32 est positionne au **milieu du bas**. Deux chaines de LEDs partent de ce point central vers l'exterieur, pilotees chacune par un GPIO different :

| Chaine | GPIO | Trajet | LEDs |
|---|---|---|---|
| **A** (gauche) | D9 | demi-bas milieu → gauche, puis cote gauche bas → haut | 110 + 150 = **260** |
| **B** (droite) | D10 | demi-bas milieu → droite, puis cote droit bas → haut | 110 + 150 = **260** |

Avantages vs une seule chaine de 521 LEDs :
- Fil data 10 fois plus court (< 30 cm au lieu de ~1,85 m vers un coin)
- Rafraichissement LED plus rapide (2 chaines en parallele, ~260 LEDs chacune au lieu de 521)
- Ligne data moins sensible aux perturbations

### Puissance

Chaque LED WS2812 consomme au maximum 60 mA a 5 V (20 mA par canal R, G, B a pleine intensite).

| Scenario | Courant par LED | Courant total | Puissance (5 V) |
|---|---|---|---|
| Maximum (blanc 100%) | 60 mA | 520 x 60 mA = **31.2 A** | **156.0 W** |
| Utilisation typique ambilight (~30%) | ~20 mA | 520 x 20 mA = **10.4 A** | **52.0 W** |

**Alimentation choisie** : 1x Mean Well LRS150F-5 -- 5 V / 30 A (150 W).

> 30 A couvre le maximum theorique (31.2 A) a ~96%. En pratique l'ambilight ne
> depasse jamais le blanc pur simultane sur toutes les LEDs ; le budget typique
> (~10 A) laisse une large marge. Si un contenu pousse ponctuellement au-dela,
> la LRS150F-5 tolere des pics courts a 110% (33 A).

## Cablage de l'ESP32-C6

| Broche ESP32-C6 | Connexion | Note |
|---|---|---|
| USB-C ou pad 5V | 5 V depuis la PSU via Wago ou regulateur | Alim seule — les donnees passent par WiFi |
| D9 | Level shifter IN chaine A (pin 1) | Signal data chaine A (gauche, 260 LEDs) |
| D10 | Level shifter IN chaine B (pin 13) | Signal data chaine B (droite, 260 LEDs) |
| GND | GND commun (PSU + level shifter) | **Obligatoire** |
| WiFi (integre) | Reseau ferme dedie | Reception UDP du PC |

> **Decouplage ESP32** : placer 22 uF electrolytique + 100 nF ceramique en parallele sur le rail 5 V au plus pres du VBUS, pour filtrer le bruit HF genere par les 520 LEDs qui commutent a 800 kHz.

## Cablage du level shifter SN74HCT14N

Boitier DIP-14 (6 inverseurs Schmitt trigger independants). On utilise **4 portes** (2 cascades de 2 inverseurs), une cascade par chaine. 2 portes restent inutilisees.

```
           ┌───U───┐
    1A  ──1┤       ├14──  VCC (+5 V)
    1Y  ──2┤       ├13──  6A  ← D10 (chaine B, 3.3V)
    2A  ──3┤       ├12──  6Y
    2Y  ──4┤       ├11──  5A
    3A  ──5┤       ├10──  5Y  → 330 ohm → chaine B DIN (5V)
    3Y  ──6┤       ├9──── 4A  (NC → GND)
    GND ──7┤       ├8──── 4Y  (NC)
           └───────┘
```

### Chaine A (gauche) -- cascade inverseurs 1 et 2

| Broche | Role | Connexion |
|---|---|---|
| 1 (1A) | Entree inverseur 1 | Signal 3.3 V depuis ESP32 **D9** |
| 2 (1Y) | Sortie inverseur 1 | Relier a la broche 3 |
| 3 (2A) | Entree inverseur 2 | Relier a la broche 2 |
| 4 (2Y) | Sortie inverseur 2 (5 V) | Resistance 330 ohm puis DIN chaine A |

### Chaine B (droite) -- cascade inverseurs 6 et 5

| Broche | Role | Connexion |
|---|---|---|
| 13 (6A) | Entree inverseur 6 | Signal 3.3 V depuis ESP32 **D10** |
| 12 (6Y) | Sortie inverseur 6 | Relier a la broche 11 |
| 11 (5A) | Entree inverseur 5 | Relier a la broche 12 |
| 10 (5Y) | Sortie inverseur 5 (5 V) | Resistance 330 ohm puis DIN chaine B |

### Portes inutilisees (inverseurs 3 et 4)

| Broche | Role | Connexion |
|---|---|---|
| 5 (3A), 9 (4A) | Entrees inutilisees | **Obligatoire : relier a GND** |
| 6 (3Y), 8 (4Y) | Sorties inutilisees | Laisser en l'air |

### Alimentation

| Broche | Connexion |
|---|---|
| 14 (VCC) | +5 V depuis la PSU |
| 7 (GND) | GND commun avec PSU et ESP32 |


**Decouplage** : condensateur 100 nF ceramique (marquage "104") entre broche 14 et broche 7, **au plus pres du chip** (pattes < 5 mm).

## Fichiers KiCad

Le projet KiCad complet est dans [ambilight_kicad/](ambilight_kicad/).
