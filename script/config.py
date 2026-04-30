from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    # --- source video ---
    # Priorite : si camera_index est defini, utilise ce flux camera (webcam, carte
    # de capture HDMI-USB, etc.). Sinon, lit video_path (fichier local, /dev/videoN,
    # URL rtsp://, http://, etc. que OpenCV/FFmpeg peut ouvrir).
    # video_path:   str         = "data/sample.mp4"
    video_path:   str         = "../test_videos/ambilight_test.mp4"
    # video_path:   str         = "test_images/white_1.png"
    camera_index: int | None  = None   # ex : 0 pour la 1re webcam. None = utilise video_path

    # --- resolution / fps camera (ignore si source = fichier) ---
    camera_width:  int   | None = 1920   # None = resolution native de la camera
    camera_height: int   | None = 1080
    camera_fps:    float | None = 30   # None = fps natif, sinon tentative de set

    # --- format de l'image (aspect ratio cible) ---
    # Force le ratio largeur/hauteur de la zone analysee. La source est
    # crop centree pour matcher : ratio cible < natif → bandes laterales
    # coupees, ratio cible > natif → bandes haut/bas coupees.
    # None = utiliser le ratio natif de la source.
    target_aspect: float | None = None

    # --- lecture ---
    target_fps: float = 30.0   # fps cible (utilise pour throttle la lecture fichier)
    loop:       bool  = False  # relire le fichier en boucle (ignore pour source live)
    fullscreen: bool  = False  # fenetre plein ecran sans overlay (mode prod)
    headless:   bool  = False  # True = pas de fenetre OpenCV (gain perf, affichage externe)

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

    # --- miroir vertical ---
    # True = miroir en Y de toutes les zones (cas ou l'ESP32 et la bande
    # "leds_bottom" sont montes en haut au lieu du bas). La geometrie est
    # reflechie : zone du bas → zone du haut, cotes inverses verticalement.
    flip_v: bool = False

    # --- profondeur de capture (fraction de l'image) ---
    depth_h: float = 0.1   # haut / bas
    depth_w: float = 0.15   # gauche / droite

    # --- mode full_coverage ---
    # True = remplace la geometrie peripherique par une grille uniforme
    # de zones carrees couvrant toute l'image. Chaque LED = une cellule.
    # Si zone_size > espacement de la grille, les zones se chevauchent
    # (lissage spatial). Necessite grid_cols * grid_rows == total LEDs
    # et grid_cols pair (split egal entre chaines A et B).
    # Avec leds_bottom=220 + leds_left=leds_right=150 → 520 LEDs total :
    # grille 26 x 20 = 520 (chaque chaine = 13 cols x 20 rows = 260).
    full_coverage: bool = False
    grid_cols:     int  = 26
    grid_rows:     int  = 20
    zone_size:     int  = 150    # cote du carre echantillonne, en pixels

    # --- mode low_res ---
    # True = 2 zones uniquement (1 par chaine). Chaque zone produit 1 couleur
    # repliquee sur l'integralite de sa chaine (pas de gradient le long du
    # ruban). Utile pour effet ambiance simple ou bicolore.
    # Prioritaire sur full_coverage (et sur le mode peripherique).
    low_res:      bool = False
    low_res_size: int  = 500    # cote du carre echantillonne, en pixels
    # Coin haut-gauche de la zone A (chaine A).
    low_res_a_xy: tuple[int, int]        = (0, 0)
    # Coin haut-gauche de la zone B (chaine B). None = auto-aligne a droite
    # (coin droit de la zone = bord droit image, soit (w - low_res_size, 0)).
    low_res_b_xy: tuple[int, int] | None = None

    # --- traitement couleur ---
    gamma:            float = 2.2   # correction gamma WS2812
    smoothing:        float = 0.1  # 0 = aucun, 0.5 = fort
    saturation_boost: float = 2.2   # 1.0 = aucun boost
    # Remontee non-lineaire des noirs (utile sur video sombre).
    # 1.0 = aucun, 2.0 = fort : 10→~50, 128→~180, 255→255.
    shadow_lift:      float = 1.0
    
    # Lissage spatial le long du ruban (par chaine).
    # Ecart maximum, par canal RGB (0..255), entre 2 LEDs voisines dans la
    # meme chaine. La LED suivante est rapprochee de la precedente si
    # l'ecart depasse la limite. 0 = desactive.
    # Utile en mode full_coverage ou low_res quand des LEDs voisines ont
    # des couleurs tres differentes (bords d'objets dans l'image).
    max_neighbor_delta: float = 150

    # Filtre colorimetrique applique en sortie de pipeline (juste avant
    # l'envoi UDP). Multiplicateur par canal (R, G, B) ; 1.0 = neutre.
    # Permet : white balance, compensation derive batch LED, teinte ambiante.
    # Exemples :
    #   (1.0, 0.9, 0.85)  -- attenue vert et bleu (LEDs qui tirent vers le bleu)
    #   (1.2, 1.0, 1.0)   -- boost rouge
    #   (1.0, 1.0, 1.0)   -- aucun effet (court-circuite)
    filter_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)

    # --- protocole UDP ---
    start_byte: int = 0xAA
    end_byte:   int = 0x55

CFG = Config()
