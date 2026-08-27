// radio_tx.ino -- the microwave path transmitter (433 MHz OOK, Manchester coded).
//
// WIRING: FS1000A transmitter -- DATA to D9, VCC to 5V, GND to GND.
//         A 17 cm straight wire soldered to ANT roughly quarter-wave at 433 MHz.
//
// WHY MANCHESTER: a cheap OOK receiver runs automatic gain control that drifts
// during a long run of one level, inventing bits out of noise. Manchester puts a
// transition in every bit, so the line stays DC balanced. It costs exactly 2x
// the bits -- which is why the radio byte budget is half the raw bit rate.
//
// SYNC: the frame delimiter is 0x00, a value Manchester coding can never produce
// (valid symbols are only 01 and 10, so only 16 of 256 byte values are reachable).
// A deliberate code violation as a delimiter is what Ethernet does too.

#include <manchester.h>
#include <bframe.h>

#define TX_PIN   9
#define RADIO_BAUD 2000UL
#define BIT_US   (1000000UL / RADIO_BAUD)
#define SYNC     0x00

uint16_t seq = 0;

void lineByte(uint8_t v) {
  for (int8_t i = 7; i >= 0; i--) {
    digitalWrite(TX_PIN, (v >> i) & 1);
    delayMicroseconds(BIT_US);
  }
}

void sendRadio(const uint8_t* data, uint8_t len) {
  for (uint8_t i = 0; i < 24; i++) { digitalWrite(TX_PIN, i & 1); delayMicroseconds(BIT_US); }
  lineByte(SYNC); lineByte(SYNC);          // code-violation delimiter
  lineByte(len);
  uint8_t enc[2];
  for (uint8_t i = 0; i < len; i++) { mn_encode(&data[i], 1, enc, 2); lineByte(enc[0]); lineByte(enc[1]); }
  uint16_t crc = bf_crc16(data, len);
  uint8_t cb[2] = { (uint8_t)(crc >> 8), (uint8_t)crc };
  for (uint8_t i = 0; i < 2; i++) { mn_encode(&cb[i], 1, enc, 2); lineByte(enc[0]); lineByte(enc[1]); }
  digitalWrite(TX_PIN, LOW);
}

void setup() { pinMode(TX_PIN, OUTPUT); digitalWrite(TX_PIN, LOW); Serial.begin(115200);
               Serial.println(F("radio TX up")); }

void loop() {
  // compressed top-of-book: seq(2) symbol(1) bid(2) ask(2) = 7 bytes,
  // inside the 12.5-byte budget available at 10 updates/second.
  uint8_t q[7];
  q[0]=(uint8_t)(seq>>8); q[1]=(uint8_t)seq; q[2]=0x00;
  q[3]=0x01; q[4]=0x2C; q[5]=0x01; q[6]=0x2D;
  sendRadio(q, sizeof q);
  seq++;
  if ((seq & 0x0F) == 0) { Serial.print(F("radio seq ")); Serial.println(seq); }
  delay(100);                                // 10 updates per second
}
