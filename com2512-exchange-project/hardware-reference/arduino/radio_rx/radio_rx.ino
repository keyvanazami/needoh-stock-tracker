// radio_rx.ino -- the microwave path receiver.
// WIRING: XY-MK-5V receiver -- DATA to D2, VCC to 5V, GND to GND, 17 cm antenna wire.
// Note the receiver outputs continuous noise when no carrier is present; the
// sync hunt below is what keeps that noise out of the decoder.

#include <manchester.h>
#include <bframe.h>

#define RX_PIN 2
#define RADIO_BAUD 2000UL
#define BIT_US (1000000UL / RADIO_BAUD)
#define SYNC   0x00

uint32_t ok = 0, bad = 0;

uint8_t lineByte() {
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++) { v = (uint8_t)(v << 1 | digitalRead(RX_PIN)); delayMicroseconds(BIT_US); }
  return v;
}

void setup() { pinMode(RX_PIN, INPUT); Serial.begin(115200); Serial.println(F("radio RX up")); }

void loop() {
  // hunt for two SYNC bytes back to back
  static uint8_t prev = 0xFF;
  uint8_t b = lineByte();
  if (!(prev == SYNC && b == SYNC)) { prev = b; return; }
  prev = 0xFF;

  uint8_t len = lineByte();
  if (len == 0 || len > 32) { bad++; return; }

  uint8_t enc[2], data[32];
  for (uint8_t i = 0; i < len; i++) {
    enc[0] = lineByte(); enc[1] = lineByte();
    if (!mn_decode(enc, 2, &data[i], 1)) { bad++; return; }   // invalid symbol
  }
  uint8_t cb[2];
  for (uint8_t i = 0; i < 2; i++) {
    enc[0] = lineByte(); enc[1] = lineByte();
    if (!mn_decode(enc, 2, &cb[i], 1)) { bad++; return; }
  }
  uint16_t want = (uint16_t)(cb[0] << 8 | cb[1]);
  if (bf_crc16(data, len) != want) { bad++; return; }

  ok++;
  uint16_t seq = (uint16_t)(data[0] << 8 | data[1]);
  Serial.print(F("seq ")); Serial.print(seq);
  Serial.print(F(" bid ")); Serial.print((uint16_t)(data[3] << 8 | data[4]));
  Serial.print(F(" ask ")); Serial.print((uint16_t)(data[5] << 8 | data[6]));
  Serial.print(F("  ok ")); Serial.print(ok);
  Serial.print(F(" bad ")); Serial.println(bad);
}
