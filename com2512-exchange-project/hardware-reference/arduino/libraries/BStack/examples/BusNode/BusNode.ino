// busnode.ino -- a station on the wired-AND pit: carrier sense, bitwise arbitration,
// collision detect, binary exponential backoff, CRC-checked framing.
//
// WIRING: one shared wire, ONE 4.7k pull-up to +5V for the whole bus, common ground.
//   D4  BUS   open-drain: INPUT = recessive 1, OUTPUT LOW = dominant 0
//   D13 LED   transmit activity
// Every station reads the line while driving it. Sent recessive, read dominant => lost.
//
// The bus is the AND of all drivers, so the LOWEST station id wins every contested
// slot, non-destructively -- the winner's frame is undamaged. That is deterministic
// and completely unfair, which is the point: fixing it is the assignment.

#include "bframe.h"

#define PIN_BUS 4
#define PIN_LED 13

static const uint32_t BAUD      = 2400;
static const uint32_t BIT_US    = 1000000UL / BAUD;     // 416 us
static const uint8_t  MAX_TRIES = 16;

uint8_t  STATION_ID = 0x21;      // set per board; lower = higher priority
uint16_t g_collisions = 0, g_sent = 0, g_giveups = 0;

static inline void recessive() { pinMode(PIN_BUS, INPUT); }
static inline void dominant()  { pinMode(PIN_BUS, OUTPUT); digitalWrite(PIN_BUS, LOW); }
static inline uint8_t sense()  { return (uint8_t)digitalRead(PIN_BUS); }

// drive one bit and read the line back mid-bit; returns 0 if we lost arbitration
static inline uint8_t send_bit_checked(uint8_t bit) {
  if (bit) recessive(); else dominant();
  delayMicroseconds(BIT_US / 2);
  uint8_t line = sense();
  delayMicroseconds(BIT_US / 2);
  return !(bit == 1 && line == 0);       // sent recessive, saw dominant => lost
}

static inline void send_bit(uint8_t bit) {
  if (bit) recessive(); else dominant();
  delayMicroseconds(BIT_US);
}

// wait for the line to be idle for a full interframe gap
static void wait_idle() {
  uint8_t quiet = 0;
  while (quiet < 4) {                     // 4 bit times of continuous idle
    if (sense() == 1) quiet++; else quiet = 0;
    delayMicroseconds(BIT_US);
  }
}

// Returns 1 if the frame went out, 0 if we gave up after MAX_TRIES.
uint8_t bus_send(const BFrame* f) {
  uint8_t wire[BF_OVERHEAD + BF_MAX_PAYLOAD];
  size_t n = bf_encode(f, wire, sizeof wire);
  if (!n) return 0;

  for (uint8_t attempt = 0; attempt < MAX_TRIES; attempt++) {
    wait_idle();
    digitalWrite(PIN_LED, HIGH);

    // ---- arbitration phase: send the station id MSB-first, checking each bit ----
    uint8_t won = 1;
    for (int8_t b = 7; b >= 0; b--)
      if (!send_bit_checked((uint8_t)((STATION_ID >> b) & 1))) { won = 0; break; }

    if (!won) {
      recessive();
      digitalWrite(PIN_LED, LOW);
      g_collisions++;
      // binary exponential backoff, capped at 2^10 slots
      uint16_t slots = (uint16_t)random(1UL << (attempt < 10 ? attempt + 1 : 10));
      delayMicroseconds(slots * BIT_US);
      continue;
    }

    // ---- we own the bus: send the frame ----
    for (size_t i = 0; i < n; i++) {
      send_bit(0);                                   // start bit
      for (uint8_t b = 0; b < 8; b++) send_bit((uint8_t)((wire[i] >> b) & 1));
      send_bit(1);                                   // stop bit
    }
    recessive();
    digitalWrite(PIN_LED, LOW);
    g_sent++;
    return 1;
  }
  g_giveups++;
  return 0;
}

void setup() {
  recessive();
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  randomSeed(analogRead(A0) ^ STATION_ID);
  Serial.print(F("bus node id 0x")); Serial.println(STATION_ID, HEX);
}

void loop() {
  BFrame f{};
  f.src = STATION_ID; f.dst = BF_BROADCAST; f.type = BF_T_QUOTE; f.len = 8;
  // quote: symbol index, bid px, bid sz, ask px  (compressed -- see the radio budget)
  f.payload[0] = 0x00; f.payload[1] = 0x01;
  f.payload[2] = 0x01; f.payload[3] = 0x2C;
  f.payload[4] = 0x00; f.payload[5] = 0x64;
  f.payload[6] = 0x01; f.payload[7] = 0x2D;
  bus_send(&f);

  if ((g_sent & 0x1F) == 0) {
    Serial.print(F("sent ")); Serial.print(g_sent);
    Serial.print(F("  collisions ")); Serial.print(g_collisions);
    Serial.print(F("  giveups ")); Serial.println(g_giveups);
  }
  delay(50);
}
