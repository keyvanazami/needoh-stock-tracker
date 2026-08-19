// repeater.ino -- THE CALIBRATED DELAY REPEATER.  Build this first; everything measures against it.
//
// It is a bit-level delay line, not a store-and-forward relay. It samples the input
// line at 8x the bus bit rate and drives the output with the level from D microseconds
// ago. Because it delays BITS, a station at the far end has not yet seen carrier while
// a frame is in flight -- which is precisely the window in which collisions happen.
// A frame-buffering repeater serialises the bus and makes collisions impossible.
//
// WIRING (Arduino Nano / Uno, ATmega328P @ 16 MHz)
//   D2  IN   <- bus segment A   (INPUT, external pull-up on the bus)
//   D3  OUT  -> bus segment B   (open-drain: INPUT for recessive, OUTPUT LOW for dominant)
//   D13 LED  activity
// Serial 115200 for the command interface.
//
// COMMANDS (type into the serial monitor)
//   d <us>     set delay in microseconds        e.g.  d 71500
//   j <us>     set peak-to-peak uniform jitter  e.g.  j 20000
//   s          status
//   c          calibration pulse (emit a known edge; measure IN->OUT on the analyser)
//
// SIZING: buffer_bits = delay_us * SAMPLE_HZ / 1e6
//   at 2400 baud -> SAMPLE_HZ 19200 -> 71.5 ms needs 1373 bits = 172 bytes.  Fits easily.
//   at 9600 baud -> SAMPLE_HZ 76800 -> only 208 CPU cycles per ISR. Feasible but tight.
// Run the bus at 2400 baud unless you have a reason not to.

#include "delayline.h"

#define PIN_IN   2
#define PIN_OUT  3
#define PIN_LED  13

static const uint32_t SAMPLE_HZ = 19200UL;      // 8 x 2400 baud
static const uint16_t LINE_BITS = 3000;         // 3000 bits @19200Hz = 156 ms max delay

DelayLine<LINE_BITS> line;

volatile uint16_t g_depth      = 1;
volatile uint16_t g_jitter_amp = 0;             // in samples, peak-to-peak
volatile uint32_t g_samples    = 0;

static inline void drive(uint8_t level) {
  // open-drain: never drive high, only pull low
  if (level) { pinMode(PIN_OUT, INPUT); }
  else       { pinMode(PIN_OUT, OUTPUT); digitalWrite(PIN_OUT, LOW); }
}

ISR(TIMER1_COMPA_vect) {
  uint8_t in  = (uint8_t)digitalRead(PIN_IN);
  uint8_t out = line.step(in);
  drive(out);
  g_samples++;

  if (g_jitter_amp) {
    // re-randomise the depth occasionally: models a jittery long-haul path.
    // This is what makes Chapter 3's EstimatedRTT / DevRTT observable.
    if ((g_samples & 0x3F) == 0) {
      int16_t d = (int16_t)g_depth + (int16_t)(random(g_jitter_amp) - g_jitter_amp / 2);
      if (d < 1) d = 1;
      line.set_depth((uint16_t)d);
    }
  }
}

static void set_delay_us(uint32_t us) {
  uint32_t samples = (uint32_t)((us * (uint64_t)SAMPLE_HZ) / 1000000UL);
  if (samples < 1) samples = 1;
  noInterrupts();
  g_depth = line.set_depth((uint16_t)samples);
  interrupts();
  Serial.print(F("delay = ")); Serial.print((uint32_t)g_depth * 1000000UL / SAMPLE_HZ);
  Serial.print(F(" us  (")); Serial.print(g_depth); Serial.print(F("/"));
  Serial.print(line.capacity()); Serial.println(F(" samples)"));
  if (samples > line.capacity())
    Serial.println(F("!! CLAMPED -- requested delay exceeds buffer. Lower the baud rate."));
}

void setup() {
  pinMode(PIN_IN, INPUT);
  pinMode(PIN_LED, OUTPUT);
  drive(1);
  line.reset(1);
  Serial.begin(115200);

  // Timer1 CTC at SAMPLE_HZ
  noInterrupts();
  TCCR1A = 0; TCCR1B = 0; TCNT1 = 0;
  OCR1A  = (uint16_t)(16000000UL / SAMPLE_HZ - 1);   // prescaler 1
  TCCR1B |= (1 << WGM12) | (1 << CS10);
  TIMSK1 |= (1 << OCIE1A);
  interrupts();

  Serial.println(F("B-Stack delay repeater ready."));
  Serial.print(F("sample rate ")); Serial.print(SAMPLE_HZ);
  Serial.print(F(" Hz, max delay "));
  Serial.print((uint32_t)LINE_BITS * 1000000UL / SAMPLE_HZ); Serial.println(F(" us"));
  set_delay_us(0);
}

void loop() {
  if (!Serial.available()) return;
  char c = Serial.read();
  if (c == 'd')      set_delay_us(Serial.parseInt());
  else if (c == 'j') { g_jitter_amp = (uint16_t)((Serial.parseInt() * (uint64_t)SAMPLE_HZ) / 1000000UL);
                       Serial.print(F("jitter = ")); Serial.print(g_jitter_amp); Serial.println(F(" samples p-p")); }
  else if (c == 's') { Serial.print(F("depth ")); Serial.print(g_depth);
                       Serial.print(F(" samples, ")); Serial.print(g_samples); Serial.println(F(" ticks")); }
  else if (c == 'c') { // calibration pulse: hold dominant for exactly 10 ms
                       Serial.println(F("CAL: driving dominant 10 ms -- measure IN->OUT skew"));
                       digitalWrite(PIN_LED, HIGH); pinMode(PIN_OUT, OUTPUT); digitalWrite(PIN_OUT, LOW);
                       delay(10); drive(1); digitalWrite(PIN_LED, LOW); }
}
