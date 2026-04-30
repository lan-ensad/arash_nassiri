from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    # --- source video ---
    # Priorite : si camera_index est defini, utilise ce flux camera (webcam, carte
    # de capture HDMI-USB, etc.). Sinon, lit video_path (fichier local, /dev/videoN,
    # URL rtsp://, http://, etc. que OpenCV/FFmpeg peut ouvrir).
    # video_path:   str         = "data/sample.mp4"
    video_path:   str         = "../test_videos/ambilight_test.mp4"
    camera_index: int | None  = None   # ex : 0 pour la 1re webcam. None = utilise video_path

    # --- resolution / fps camera (ignore si source = fichier) ---
    camera_width:  int   | None = None   # None = resolution native de la camera
    camera_height: int   | None = None
    camera_fps:    float | None = 30   # None = fps natif, sinon tentative de set

    # --- lecture ---
    target_fps: float = 30.0   # fps cible (utilise pour throttle la lecture fichier)
    loop:       bool  = True  # relire le fichier en boucle (ignore pour source live)
    fullscreen: bool  = False  # fenetre plein ecran sans overlay (mode prod)
    headless:   bool  = False   # True = pas de fenetre OpenCV (gain perf, affichage externe)

    # --- ecran de sortie ---
    # Index de l'ecran (cf. `python3 script/list_displays.py`). None = WM par defaut.
    monitor_index: int | None = None

    # --- reseau (ESP32 en WiFi sur un reseau ferme) ---
    # Doit correspondre a LOCAL_IP_BYTES dans Firmware/src/wifi_config.h
    esp32_ip:   str  = "192.168.8.50"   # IP statique de l'ESP32 (placeholder, a adapter)
    # esp32_ip:   str  = "127.0.0.1"
    esp32_port: int  = 4210             # port UDP d'ecoute sur l'ESP32
    dry_run:    bool = False             # True = pas d'envoi UDP (test sans ESP32)

    # --- preview terminal (dev) ---
    terminal_preview:     bool  = False  # afficher les chaines en ANSI truecolor dans le terminal
    terminal_preview_hz:  float = 30.0   # frequence max de refresh du preview terminal

    # --- rubans (nb de LEDs par cote) ---
    # Le bas est alimente par 2 chaines partant du milieu vers l'exterieur,
    # pour reduire la longueur du fil data ESP32 → level shifter → 1er pixel.
    # leds_bottom doit etre pair pour une repartition symetrique 110/110.
    leds_top:    int = 0     # pas de ruban en haut
    leds_right:  int = 150   # droite (2.50 m x 60 px/m) -- chaine B
    leds_bottom: int = 220   # bas (3.67 m x 60 px/m) -- 110 par chaine
    leds_left:   int = 150   # gauche (2.50 m x 60 px/m) -- chaine A

    # --- mirror ---
    # True = echange chaines A et B (pour compenser une installation miroir
    # ou une inversion de cablage D9/D10 sans avoir a reflasher l'ESP32).
    # Necessite leds_left == leds_right et leds_bottom pair.
    mirror: bool = False

    # --- profondeur de capture (fraction de l'image) ---
    depth_h: float = 0.08   # haut / bas
    depth_w: float = 0.08   # gauche / droite

    # --- traitement couleur ---
    gamma:            float = 2.2   # correction gamma WS2812
    smoothing:        float = 0.30  # 0 = aucun, 0.5 = fort
    saturation_boost: float = 1.6   # 1.0 = aucun boost
    # Remontee non-lineaire des noirs (utile sur video sombre).
    # 1.0 = aucun, 2.0 = fort : 10→~50, 128→~180, 255→255.
    shadow_lift:      float = 1.0

    # --- protocole UDP ---
    start_byte: int = 0xAA
    end_byte:   int = 0x55


CFG = Config()
