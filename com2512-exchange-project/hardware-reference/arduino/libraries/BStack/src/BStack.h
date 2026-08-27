// BStack.h -- the shared bus driver every node uses. Arduino only.
//
// ELECTRICAL CONTRACT (get this wrong and nothing else works)
//   The bus is ONE wire plus ONE 4.7k pull-up to +5V, and a common ground.
//   A station drives it open-drain:
//       recessive 1  ->  pinMode(INPUT)              the pull-up holds the line high
//       dominant  0  ->  pinMode(OUTPUT), write LOW  this station pulls it low
//   No station may EVER drive the line HIGH. If two stations did, one driving
//   high and one low, you would short the supply through two output pins.
//   Because dominant always wins, the line reads as the AND of every driver --
//   which is what makes non-destructive bitwise arbitration possible.
#ifndef BSTACK_H
#define BSTACK_H

#include <Arduino.h>
#include "bframe.h"
#include "framerx.h"
#include "book.h"          // SIDE_BUY / SIDE_SELL and the order book

#ifndef BS_PIN
#define BS_PIN 4
#endif
#ifndef BS_BAUD
#define BS_BAUD 2400UL          // see the build guide: 2400 not 9600, deliberately
#endif

#define BS_BIT_US   (1000000UL / BS_BAUD)
#define BS_MAXTRIES 16

// Recessive bit-times inserted between winning arbitration and the first
// framed byte. The arbitration bits are RAW -- no start or stop bit -- so any
// byte-oriented reader (a logic analyser's UART decoder, and our own poll())
// latches onto the first dominant arbitration bit as if it were a start bit
// and then runs 10 bit-times, i.e. 2 bit-times past the end of arbitration.
// Without this gap that bogus byte swallows the beginning of the preamble and
// the reader spends several bytes regaining phase. Must stay BELOW the 4
// quiet bit-times waitIdle() requires, or another station would read the gap
// as a free bus and start transmitting on top of us.
#define BS_ARB_GAP_BITS 3

// Bit-times waitIdle() will wait for a quiet bus before declaring it jammed.
// The longest legal transmission is 73 bytes x 10 bit-times + 8 arbitration
// bits + the gap = about 741 bit-times, so this is ~2.7x the worst legitimate
// case: nothing well-behaved can hold the line this long. A bus wedged
// dominant -- a missing pull-up, a shorted driver, a floating D4 -- used to
// spin here forever, taking the sketch's serial output down with it. Real CAN
// has exactly this problem and answers it with error counters and a bus-off
// state; this is the same idea at student scale.
#define BS_STUCK_BITS 2000UL

class BStack {
 public:
  uint8_t  id = 0x21;
  uint16_t collisions = 0, sent = 0, giveups = 0, stuck = 0;
  FrameRx  rx;

  void begin(uint8_t station_id) {
    id = station_id;
    recessive();
    randomSeed((uint32_t)analogRead(A0) ^ station_id);
  }

  static inline void recessive() { pinMode(BS_PIN, INPUT); }
  static inline void dominant()  { pinMode(BS_PIN, OUTPUT); digitalWrite(BS_PIN, LOW); }
  static inline uint8_t sense()  { return (uint8_t)digitalRead(BS_PIN); }

  // Returns 1 when the bus has been quiet for 4 bit-times, 0 if it stayed
  // busy past BS_STUCK_BITS. Never blocks forever: a jammed bus must be
  // reportable, not fatal.
  uint8_t waitIdle() {
    uint8_t quiet = 0;
    uint32_t spent = 0;
    while (quiet < 4) {
      if (++spent > BS_STUCK_BITS) { stuck++; return 0; }
      quiet = sense() ? (uint8_t)(quiet + 1) : 0;
      delayMicroseconds(BS_BIT_US);
    }
    return 1;
  }

  inline uint8_t bitChecked(uint8_t b) {
    if (b) recessive(); else dominant();
    delayMicroseconds(BS_BIT_US / 2);
    uint8_t line = sense();
    delayMicroseconds(BS_BIT_US / 2);
    return !(b == 1 && line == 0);
  }
  // delayMicroseconds() takes a 16-bit unsigned int on AVR and is only accurate
  // below 16383 us. A 1023-slot backoff is 425568 us, which both overflows the
  // argument and exceeds the accurate range, so backoff has to be counted in
  // bit-times rather than handed over as one large microsecond value.
  static inline void delayBits(uint32_t bits) {
    while (bits--) delayMicroseconds(BS_BIT_US);
  }

  inline void bitRaw(uint8_t b) {
    if (b) recessive(); else dominant();
    delayMicroseconds(BS_BIT_US);
  }
  inline void byteOut(uint8_t v) {            // 8N1, LSB first
    bitRaw(0);
    for (uint8_t i = 0; i < 8; i++) bitRaw((uint8_t)((v >> i) & 1));
    bitRaw(1);
  }

  uint8_t send(const BFrame* f) {
    uint8_t wire[BF_OVERHEAD + BF_MAX_PAYLOAD];
    size_t n = bf_encode(f, wire, sizeof wire);
    if (!n) return 0;
    for (uint8_t attempt = 0; attempt < BS_MAXTRIES; attempt++) {
      if (!waitIdle()) { giveups++; return 0; }   // bus jammed dominant
      uint8_t won = 1;
      for (int8_t b = 7; b >= 0; b--)
        if (!bitChecked((uint8_t)((id >> b) & 1))) { won = 0; break; }
      if (!won) {
        recessive();
        collisions++;
        uint16_t slots = (uint16_t)random(1UL << (attempt < 10 ? attempt + 1 : 10));
        delayBits(slots);
        continue;
      }
      for (uint8_t g = 0; g < BS_ARB_GAP_BITS; g++) bitRaw(1);
      for (size_t i = 0; i < n; i++) byteOut(wire[i]);
      recessive();
      sent++;
      return 1;
    }
    giveups++;
    return 0;
  }

  // Physical-layer self-test. Drives each level and checks the line follows.
  //   bit 0 set: released the line and it did NOT go high -- no pull-up, the
  //              pull-up's rail is unpowered, D4 is floating, no common ground,
  //              or another node is holding the bus dominant.
  //   bit 1 set: drove the line low and it did NOT go low -- D4 is not
  //              connected to the bus wire at all.
  // Run it at boot, before any traffic. Retries so a station that happens to be
  // transmitting during the first attempt does not produce a false fault.
  uint8_t selfTest() {
    uint8_t faults = 3;
    for (uint8_t try_ = 0; try_ < 3 && faults; try_++) {
      faults = 0;
      recessive();
      delayBits(4);
      if (!sense()) faults |= 1;
      dominant();
      delayBits(4);
      if (sense()) faults |= 2;
      recessive();
      delayBits(8);
    }
    return faults;
  }

  uint8_t poll(BFrame* out) {
    if (sense()) return 0;
    delayMicroseconds(BS_BIT_US + BS_BIT_US / 2);
    uint8_t v = 0;
    for (uint8_t i = 0; i < 8; i++) {
      if (sense()) v |= (uint8_t)(1 << i);
      delayMicroseconds(BS_BIT_US);
    }
    return (uint8_t)rx.feed(v, out);
  }
};

#endif
