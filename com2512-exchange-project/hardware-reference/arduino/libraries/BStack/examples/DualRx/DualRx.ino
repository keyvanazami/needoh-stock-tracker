// dualrx.ino -- THE MEASUREMENT RIG for the fibre-vs-microwave comparison.
//
// The trap this avoids: comparing timestamps taken on two different Arduinos needs
// clock synchronisation, which will cost you a week. Instead ONE board holds BOTH
// inputs and times both arrivals against its own micros(). No sync, no drift.
//
// WIRING
//   D2  WIRE   <- the wired bus (through the gateways and the delay repeater)
//   D3  RADIO  <- 433 MHz OOK receiver data pin (direct, one hop)
//   D13 LED
//
// Both paths carry the SAME logical quote with the SAME sequence number, so this is
// also the A/B line-arbitration exercise: take whichever arrives first, discard the
// duplicate, and report the gap.
//
// AVR micros() resolves 4 us; the expected gap is tens of milliseconds, so there are
// thousands of ticks of margin.

#define PIN_WIRE  2
#define PIN_RADIO 3
#define PIN_LED   13

volatile uint32_t t_wire = 0, t_radio = 0;
volatile uint8_t  got_wire = 0, got_radio = 0;

uint32_t n_pairs = 0, n_radio_first = 0;
int32_t  sum_gap = 0, min_gap = 2147483647L, max_gap = -2147483648L;

// In the real build these ISRs sit on the framing decoder and fire on a complete,
// CRC-valid frame. Edge-triggered here so the rig can be bench-tested on its own.
void isrWire()  { if (!got_wire)  { t_wire  = micros(); got_wire  = 1; } }
void isrRadio() { if (!got_radio) { t_radio = micros(); got_radio = 1; } }

void setup() {
  pinMode(PIN_WIRE, INPUT); pinMode(PIN_RADIO, INPUT); pinMode(PIN_LED, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_WIRE),  isrWire,  FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_RADIO), isrRadio, FALLING);
  Serial.begin(115200);
  Serial.println(F("seq,wire_us,radio_us,gap_us,first"));
}

void loop() {
  if (!(got_wire && got_radio)) return;

  noInterrupts();
  uint32_t w = t_wire, r = t_radio;
  got_wire = got_radio = 0;
  interrupts();

  int32_t gap = (int32_t)(w - r);        // positive => radio arrived first
  n_pairs++;
  if (gap > 0) n_radio_first++;
  sum_gap += gap;
  if (gap < min_gap) min_gap = gap;
  if (gap > max_gap) max_gap = gap;

  Serial.print(n_pairs); Serial.print(',');
  Serial.print(w);       Serial.print(',');
  Serial.print(r);       Serial.print(',');
  Serial.print(gap);     Serial.print(',');
  Serial.println(gap > 0 ? F("RADIO") : F("wire"));

  if (n_pairs % 50 == 0) {
    Serial.print(F("# n=")); Serial.print(n_pairs);
    Serial.print(F(" mean_gap=")); Serial.print(sum_gap / (int32_t)n_pairs);
    Serial.print(F("us min=")); Serial.print(min_gap);
    Serial.print(F(" max=")); Serial.print(max_gap);
    Serial.print(F(" radio_first=")); Serial.print(100UL * n_radio_first / n_pairs);
    Serial.println(F("%"));
  }
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
}
