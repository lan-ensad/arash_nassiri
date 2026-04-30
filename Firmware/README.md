# Firmware ESP32-C6

Reception des paquets UDP depuis le PC et pilotage des 2 chaines de LEDs WS2812 via NeoPixelBus (RMT).

## Prerequis

- [PlatformIO](https://platformio.org/) (extension VS Code ou CLI `pio`)
- Seeed XIAO ESP32-C6 branche en USB-C

## Configuration WiFi

Remplir les placeholders dans `src/wifi_config.h` avant de flasher :

```c
#define WIFI_SSID      "ambilight_net"       // SSID du reseau ferme
#define WIFI_PASSWORD  "mot_de_passe"

#define LOCAL_IP_BYTES    <IP_ESP>          // IP statique de l'ESP32 (format octets : a, b, c, d)
#define GATEWAY_IP_BYTES  <IP_ROUTEUR>      // IP du routeur/AP (format octets)
#define SUBNET_BYTES      255, 255, 255, 0
#define DNS_IP_BYTES      <IP_ROUTEUR>      // typiquement = gateway

#define UDP_PORT          4210
```

`LOCAL_IP_BYTES` doit correspondre a `esp32_ip` dans `script/config.py`.

## Flashage

### USB (premier flash, et recuperation)

```bash
pio run --target upload
pio device monitor    # optionnel : logs WiFi/UDP au boot
```

### OTA (flash sans fil via WiFi)

Le firmware embarque ArduinoOTA : a partir du moment ou il a ete flashe une
fois en USB, les flashs suivants peuvent se faire via le reseau.

**Pre-requis machine hote** : autoriser l'ESP32 a initier des connexions
TCP entrantes (sinon UFW/firewall bloque le retour TCP de l'OTA et `espota`
fait `Authenticating...OK` puis `No response from device`) :

```bash
sudo ufw allow from 192.168.8.50    # IP de l'ESP32 (LOCAL_IP_BYTES)
```

**Flash OTA** :

```bash
pio run -e seeed_xiao_esp32c6_ota -t upload
```

L'environnement `seeed_xiao_esp32c6_ota` defini dans `platformio.ini`
contient `--host_ip=192.168.8.202` (IP de la machine hote sur le subnet
192.168.8.x). Mettre a jour cette valeur si l'IP de la machine change
(DHCP) -- une reservation DHCP cote routeur est plus robuste a terme.

## Indicateurs visuels au boot

La 1re LED de chaque chaine sert d'indicateur :

| Couleur | Etat |
|---|---|
| **Jaune** | Connexion WiFi en cours |
| **Verte** (500 ms) | Connexion etablie, UDP en ecoute |
| **Noir** | En attente des paquets du PC |

## Protocole UDP

**2 paquets UDP par frame** (un par chaine), envoyes en rafale par le PC. Chaque paquet fait 785 octets :

| Octet | Contenu |
|---|---|
| 0 | `0xAA` (magic start) |
| 1 | `chain_id` (0 = chaine A gauche, 1 = chaine B droite) |
| 2 -- 3 | `seq_num` (uint16 big-endian) |
| 4 -- 783 | R, G, B pour chaque LED (260 x 3 = 780 octets) |
| 784 | `0x55` (magic end) |

**Taille totale par frame** : 2 x 785 = **1570 octets/frame** (vs MTU 1500 → aucune fragmentation IP au niveau paquet individuel).

**Bande passante a 30 fps** : 47 KB/s = ~376 kbps. Tres confortable meme en 2,4 GHz.

**Gestion cote firmware** (voir `src/main.cpp`) :
- `seq_num` : le firmware ignore les paquets dont le seq est plus ancien que le dernier recu (protection contre reordering UDP, rare en LAN)
- **Magic bytes** : `0xAA` / `0x55` verifies, sinon paquet ignore
- `chain_id 0 ou 1` : route le RGB data vers `stripA` (D9) ou `stripB` (D10). Chaque chaine est rafraichie des que son paquet arrive (pas de sync inter-chaines)
- `MAX_BRIGHTNESS` (defaut 230, soit ~90%) : applique une limite globale de luminosite pour proteger l'alimentation

## Pins utilises

| GPIO | Role |
|---|---|
| D9 | Signal data chaine A (gauche, 260 LEDs) |
| D10 | Signal data chaine B (droite, 260 LEDs) |

Voir [kicad/README.md](../kicad/README.md) pour le cablage complet (level shifter SN74HCT14N, resistances 330 ohm, decouplage).

## Structure des fichiers

```
Firmware/
├── platformio.ini              Configuration PlatformIO (board, framework, libs)
├── src/
│   ├── main.cpp                Reception UDP + pilotage NeoPixel (2 chaines)
│   └── wifi_config.h           Credentials WiFi + IP statique (a remplir)
├── include/                    Headers additionnels (vide par defaut)
├── lib/                        Bibliotheques locales (vide par defaut)
└── test/                       Tests (vide par defaut)
```

## Troubleshooting

### Freezes periodiques (~500 ms toutes les 2-3 s)

**Cause** : WiFi power-save du ESP32-C6 -- il wake seulement aux beacons DTIM, les paquets UDP s'accumulent sur l'AP puis sont livres en rafale.

**Fix** (deja applique dans `src/main.cpp`) : apres `WiFi.begin(...)`, desactiver le modem-sleep :
```cpp
WiFi.setSleep(false);
```

Si les freezes persistent malgre ce fix :

- **Canal WiFi encombre** -- force un canal libre (1, 6 ou 11) sur l'AP
- **Inactivite WiFi** -- ajouter apres `udp.begin(UDP_PORT)` :
  ```cpp
  esp_wifi_set_inactive_time(WIFI_IF_STA, 10);
  ```

### Aucun paquet recu (1re LED reste noire apres boot)

Verifier dans l'ordre :

1. **WiFi connecte** ? La 1re LED doit passer par jaune puis verte au boot. Si elle reste jaune, le WiFi n'a pas connecte : verifier SSID/password dans `wifi_config.h`.
2. **IP coherente** ? `LOCAL_IP_BYTES` doit etre dans le sous-reseau du routeur (pas de conflit avec un autre appareil). `esp32_ip` cote Python doit etre identique.
3. **Paquets envoyes par le PC** ? Cote PC :
   ```bash
   sudo tcpdump -i any -n 'udp port 4210'
   ```
   Doit montrer des paquets sortants du PC toutes les 33 ms (~30 fps).
4. **PC et ESP32 sur le meme reseau WiFi** ? Si le PC est en ethernet et l'ESP32 en WiFi, le routeur doit faire le pont entre les deux interfaces.

### LEDs erratiques / clignotent au hasard

Probleme electronique (GND, level shifter, longueur data). Voir [kicad/README.md](../kicad/README.md).

### Reduire la luminosite pour proteger l'alim

Dans `src/main.cpp`, ajuster :
```cpp
#define MAX_BRIGHTNESS  230   // 255 = aucune limite, 192 = 75%, 128 = 50%
```

Avec 520 LEDs et une PSU 30 A :
- 255 (100%) → 31.2 A max (depasse legerement le nominal de la PSU)
- 230 (~90%) → 28 A max (marge de securite)
- 192 (~75%) → 23 A max (tres confortable)

Un reflashage est necessaire apres modification.
