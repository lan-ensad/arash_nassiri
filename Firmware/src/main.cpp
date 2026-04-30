#include <ArduinoOTA.h>
#include <NeoPixelBus.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "wifi_config.h"

// --- Config LEDs (doit correspondre a config.py) ---
// L'ESP32 est monte au milieu du bas. Deux chaines partent de ce point
// central vers l'exterieur pour reduire la longueur du fil data.
//   Chaine A (gauche) : demi-bas gauche (110) + cote gauche (150) = 260
//   Chaine B (droite) : demi-bas droite (110) + cote droit  (150) = 260
#define LEDS_BOTTOM     220
#define LEDS_RIGHT      150
#define LEDS_LEFT       150
#define HALF_BOTTOM     (LEDS_BOTTOM / 2)
#define LEDS_CHAIN_A    (HALF_BOTTOM + LEDS_LEFT)                  // 260
#define LEDS_CHAIN_B    ((LEDS_BOTTOM - HALF_BOTTOM) + LEDS_RIGHT) // 260

#define DATA_PIN_A      D3    // chaine A → J1 (cote gauche, GPIO21)
#define DATA_PIN_B      D2    // chaine B → J2 (cote droit, GPIO2)

// --- Protocole UDP (doit correspondre a udp_sender.py) ---
//   octet 0      : 0xAA (magic start)
//   octet 1      : chain_id (0 = A, 1 = B)
//   octets 2-3   : seq_num (uint16 big-endian)
//   octets 4..N  : RGB data (n_leds x 3)
//   octet N+1    : 0x55 (magic end)
#define START_BYTE      0xAA
#define END_BYTE        0x55
#define HEADER_LEN      4

#define PACKET_LEN_A    (HEADER_LEN + LEDS_CHAIN_A * 3 + 1)  // 785
#define PACKET_LEN_B    (HEADER_LEN + LEDS_CHAIN_B * 3 + 1)  // 785
#define MAX_PACKET_LEN  800

// --- Limite de luminosite (protection alimentation) ---
// 255 = aucune limite, 192 = 75% (~23A max), 128 = 50% (~15.6A max)
#define MAX_BRIGHTNESS  255

// --- Objets globaux ---
NeoPixelBus<NeoGrbFeature, NeoEsp32BitBangWs2812xMethod> stripA(LEDS_CHAIN_A, DATA_PIN_A);
NeoPixelBus<NeoGrbFeature, NeoEsp32BitBangWs2812xMethod> stripB(LEDS_CHAIN_B, DATA_PIN_B);

WiFiUDP udp;
uint8_t packet_buf[MAX_PACKET_LEN];

uint16_t last_seq_a = 0;
uint16_t last_seq_b = 0;
bool     seq_a_init = false;
bool     seq_b_init = false;

// Reset du tracking de sequence apres ce delai de silence : permet de repartir
// proprement quand le sender est arrete puis relance (seq cote Python repart a 0).
#define SESSION_TIMEOUT_MS  500
uint32_t last_packet_ms = 0;

// Flag pose pendant un flash OTA : suspend la reception UDP + Show() pour
// liberer le CPU et eviter que les interrupts off du bit-bang WS2812
// parasitent la reception du firmware.
volatile bool ota_in_progress = false;

// -----------------------------------------------------------
// Boot indicator sur la 1re LED des deux chaines
static void show_boot_indicator(RgbColor color) {
    stripA.SetPixelColor(0, color);
    stripB.SetPixelColor(0, color);
    stripA.Show();
    stripB.Show();
}

// -----------------------------------------------------------
// Ecriture d'une chaine a partir du buffer RGB (applique MAX_BRIGHTNESS)
// Template pour servir les 2 canaux RMT avec le meme code.
template <typename TStrip>
static void apply_chain(TStrip& strip, int n_leds, const uint8_t* rgb_data) {
    for (int i = 0; i < n_leds; i++) {
        uint8_t r = (uint16_t)rgb_data[i * 3 + 0] * MAX_BRIGHTNESS / 255;
        uint8_t g = (uint16_t)rgb_data[i * 3 + 1] * MAX_BRIGHTNESS / 255;
        uint8_t b = (uint16_t)rgb_data[i * 3 + 2] * MAX_BRIGHTNESS / 255;
        strip.SetPixelColor(i, RgbColor(r, g, b));
    }
}

// -----------------------------------------------------------
// Gere le wraparound 16 bits : diff signe > 0 → plus recent
static bool seq_is_newer(uint16_t seq, uint16_t last) {
    return (int16_t)(seq - last) > 0;
}

// -----------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(100);

    stripA.Begin();
    stripB.Begin();
    stripA.ClearTo(RgbColor(0, 0, 0));
    stripB.ClearTo(RgbColor(0, 0, 0));
    stripA.Show();
    stripB.Show();

    // Indicateur boot : 1re LED jaune pendant connexion WiFi
    show_boot_indicator(RgbColor(64, 64, 0));

    WiFi.mode(WIFI_STA);
    WiFi.setHostname(WIFI_HOSTNAME);
    WiFi.config(
        IPAddress(LOCAL_IP_BYTES),
        IPAddress(GATEWAY_IP_BYTES),
        IPAddress(SUBNET_BYTES),
        IPAddress(DNS_IP_BYTES)
    );
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    WiFi.setSleep(false);  // desactive modem-sleep : sinon freezes ~500ms tous les 2-3s

    Serial.print("WiFi : connexion a ");
    Serial.println(WIFI_SSID);

    // Garde-fou : si la connexion ne vient pas dans la limite, on reboote.
    // Couvre routeur cassé, credentials errones, conflit d'IP, etc.
    const uint32_t connect_start       = millis();
    const uint32_t CONNECT_TIMEOUT_MS  = 90000;

    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - connect_start > CONNECT_TIMEOUT_MS) {
            Serial.println();
            Serial.println("WiFi : timeout, reboot");
            delay(100);
            ESP.restart();
        }
        delay(250);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("WiFi connecte. IP : ");
    Serial.print(WiFi.localIP());
    Serial.print(" (hostname : ");
    Serial.print(WIFI_HOSTNAME);
    Serial.println(")");

    // Indicateur connexion OK : 1re LED verte 500 ms puis noir
    show_boot_indicator(RgbColor(0, 64, 0));
    delay(500);
    stripA.ClearTo(RgbColor(0, 0, 0));
    stripB.ClearTo(RgbColor(0, 0, 0));
    stripA.Show();
    stripB.Show();

    udp.begin(UDP_PORT);
    Serial.print("UDP : ecoute sur le port ");
    Serial.println(UDP_PORT);

    // --- ArduinoOTA (flash sans fil) ---
    ArduinoOTA.setHostname(WIFI_HOSTNAME);
    ArduinoOTA.setPassword("ambilight");
    ArduinoOTA.onStart([]() {
        ota_in_progress = true;
        // Eteindre les rubans : les Show() bit-bang desactivent les
        // interrupts et perturbent la reception du firmware OTA.
        stripA.ClearTo(RgbColor(0, 0, 0));
        stripB.ClearTo(RgbColor(0, 0, 0));
        stripA.Show();
        stripB.Show();
        Serial.println("OTA: start");
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("OTA: end (reboot)");
    });
    ArduinoOTA.onError([](ota_error_t e) {
        ota_in_progress = false;
        Serial.printf("OTA: error %u\n", e);
    });
    ArduinoOTA.begin();
    Serial.println("OTA pret");
}

// -----------------------------------------------------------
void loop() {
    ArduinoOTA.handle();
    if (ota_in_progress) return;  // suspendre tout pendant le flash

    int packet_size = udp.parsePacket();
    if (packet_size <= 0) return;

    if (packet_size > MAX_PACKET_LEN) {
        udp.flush();
        return;
    }

    int read = udp.read(packet_buf, packet_size);
    if (read < HEADER_LEN + 1) return;

    // Verification magic bytes
    if (packet_buf[0] != START_BYTE) return;
    if (packet_buf[read - 1] != END_BYTE) return;

    uint32_t now = millis();
    if (now - last_packet_ms > SESSION_TIMEOUT_MS) {
        seq_a_init = false;
        seq_b_init = false;
    }
    last_packet_ms = now;

    uint8_t  chain_id = packet_buf[1];
    uint16_t seq      = ((uint16_t)packet_buf[2] << 8) | packet_buf[3];

    if (chain_id == 0) {
        if (read != PACKET_LEN_A) return;
        if (seq_a_init && !seq_is_newer(seq, last_seq_a)) return;
        last_seq_a = seq;
        seq_a_init = true;

        apply_chain(stripA, LEDS_CHAIN_A, packet_buf + HEADER_LEN);
        stripA.Show();
    } else if (chain_id == 1) {
        if (read != PACKET_LEN_B) return;
        if (seq_b_init && !seq_is_newer(seq, last_seq_b)) return;
        last_seq_b = seq;
        seq_b_init = true;

        apply_chain(stripB, LEDS_CHAIN_B, packet_buf + HEADER_LEN);
        stripB.Show();
    }
}
