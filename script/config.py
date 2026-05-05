from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    # --- source video ---
    # Priorite : si camera_index est defini, utilise ce flux camera (webcam, carte
    # de capture HDMI-USB, etc.). Sinon, lit video_path (fichier local, /dev/videoN,
    # URL rtsp://, http://, etc. que OpenCV/FFmpeg peut ouvrir).
    video_path:   str         = "../test_videos/abl.mp4"
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
    esp32_ip:   str  = "192.168.8.50"   # IP statique de l'ESP32
    esp32_port: int  = 4210             # port UDP d'ecoute sur l'ESP32
    dry_run:    bool = False             # True = pas d'envoi UDP (test sans ESP32)

    # --- preview terminal (dev) ---
    terminal_preview:     bool  = True  # afficher les chaines en ANSI truecolor dans le terminal
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
    zone_size:     int  = 150    # cote du carre full_coverage, en pixels

    # --- mode chain_squares (par defaut quand low_res et full_coverage sont False) ---
    # Chaque LED = 1 carre de cote chain_zone_size, place sur un chemin en
    # serpentin. Origine = centre du bord bas. Chaine A part vers la gauche,
    # longe le cote gauche, atteint le centre haut. Si le nombre de LEDs
    # depasse ce premier passage, le chemin redescend vers le centre bas en
    # repassant par le cote, decale de chain_zone_size vers l'interieur ; les
    # passages suivants alternent ainsi en s'enfoncant dans l'image. Chaine B
    # en miroir cote droit. Pas entre LEDs voisines = chain_zone_size (carres
    # jointifs le long du chemin).
    chain_zone_size: int = 11
    # Decalage de l'index 0 le long du chemin (en nombre de LEDs). Permet
    # d'ignorer N LEDs en debut de chaine si elles ne sont pas physiquement
    # visibles : chain_shift=5 -> l'index 0 demarre a la position 5 du chemin,
    # la fin progresse d'autant vers le haut centre.
    chain_shift: int = 5

    # --- mode low_res ---
    # True = 2 zones uniquement (1 par chaine). Chaque zone produit 1 couleur
    # repliquee sur l'integralite de sa chaine (pas de gradient le long du
    # ruban). Utile pour effet ambiance simple ou bicolore.
    # Prioritaire sur full_coverage (et sur le mode peripherique).
    low_res:      bool = False
    low_res_size: int  = 750    # cote du carre echantillonne, en pixels
    # Coin haut-gauche de la zone A (chaine A).
    low_res_a_xy: tuple[int, int]        = (0, 0)
    # Coin haut-gauche de la zone B (chaine B). None = auto-aligne a droite
    # (coin droit de la zone = bord droit image, soit (w - low_res_size, 0)).
    low_res_b_xy: tuple[int, int] | None = None
    # Moyenne glissante sur les N dernieres frames (lissage temporel doux).
    # 1 = aucune moyenne (frame courante). 15-30 = lissage doux a 30fps.
    low_res_window: int = 1
    # Seuil de snap : si la nouvelle couleur differe de la moyenne en cours
    # de plus que ce delta (norme L2 RGB, 0..441), l'historique est vide et
    # la nouvelle valeur est adoptee immediatement → preserve la reactivite
    # sur changement de scene. 0 = snap desactive.
    low_res_snap_delta: float = 150.0

    # --- traitement couleur ---
    gamma:            float = 2.2   # correction gamma WS2812
    smoothing:        float = 0.1  # 0 = aucun, 0.5 = fort
    saturation_boost: float = 0.3   # 1.0 = aucun boost
    # Rotation globale de teinte, en degres (-180..+180). Compense un color
    # cast en amont (decodage YUV→RGB Rec.601 vs Rec.709, lampes ambiantes).
    # Exemples :
    #   +10  -- compense un cast cyan (rotation vers le rouge)
    #   -15  -- compense un cast magenta (rotation vers le vert)
    # 0 = aucun effet (court-circuite).
    hue_shift:        float = 0.0
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

    # --- geometrie derivee (source unique de verite) ---
    @property
    def chain_a_len(self) -> int:
        return self.leds_bottom // 2 + self.leds_left

    @property
    def chain_b_len(self) -> int:
        return (self.leds_bottom - self.leds_bottom // 2) + self.leds_right

    @property
    def total_leds(self) -> int:
        return self.chain_a_len + self.chain_b_len

    def validate(self) -> None:
        """Verifie la coherence de la config. Echec rapide au demarrage."""
        if self.leds_bottom % 2 != 0:
            raise ValueError(
                f"leds_bottom ({self.leds_bottom}) doit etre pair pour une "
                "repartition symetrique entre les deux chaines."
            )
        if self.mirror and self.chain_a_len != self.chain_b_len:
            raise ValueError(
                f"mirror=True impose chaine A et B de meme longueur "
                f"(A={self.chain_a_len}, B={self.chain_b_len}). "
                "Verifier leds_left == leds_right."
            )
        if self.full_coverage:
            cols, rows = self.grid_cols, self.grid_rows
            if cols * rows != self.total_leds:
                raise ValueError(
                    f"full_coverage : grid_cols * grid_rows = {cols*rows} "
                    f"doit egaler le total des LEDs ({self.total_leds})."
                )
            if cols % 2 != 0:
                raise ValueError(
                    f"full_coverage : grid_cols ({cols}) doit etre pair."
                )
            if (cols // 2) * rows != self.chain_a_len:
                raise ValueError(
                    f"full_coverage : (grid_cols/2) * grid_rows = "
                    f"{(cols // 2) * rows} doit egaler chain_a_len "
                    f"({self.chain_a_len})."
                )

CFG = Config()
