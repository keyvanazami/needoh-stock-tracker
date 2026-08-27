// risetime.ino -- measure the bus's dominant-to-recessive rise time on D4.
//
// This is the one physical number the whole bus depends on. An open-drain
// station cannot drive the line high; it releases the line and the pull-up
// charges the wire's capacitance through R. Arbitration reads the line back
// half a bit-time after releasing it, so if the line has not crossed the
// input threshold by then, a station loses a bit it should have won -- with
// no other station on the wire at all.
//
// Budget at 2400 baud: half a bit-time = 208 us. A healthy 4.7k pull-up on a
// breadboard rises in single-digit microseconds, so a healthy bus passes by
// four orders of magnitude. There is no grey zone here: you either see ~5 us
// or you see something badly wrong.
//
// Run this with NOTHING else driving the bus. Only the pull-up and this board.

#define PIN 4
#define BUDGET_US 208UL          // half a bit-time at 2400 baud
#define TIMEOUT_US 50000UL

uint32_t worst = 0, best = 0xFFFFFFFF, sum = 0, runs = 0, timeouts = 0;

void setup() {
  Serial.begin(115200);
  Serial.println(F("bus rise-time test on D4"));
  Serial.println(F("nothing else may be driving the bus -- pull-up and this board only"));
  Serial.print(F("budget: ")); Serial.print(BUDGET_US); Serial.println(F(" us (half a bit-time at 2400 baud)"));
}

// One measurement: hold the line dominant, release it, time the rise.
uint32_t measureOnce() {
  pinMode(PIN, OUTPUT); digitalWrite(PIN, LOW);   // dominant
  delayMicroseconds(2000);                        // fully discharged
  noInterrupts();
  uint32_t t0 = micros();
  pinMode(PIN, INPUT);                            // release: pull-up takes over
  while (!digitalRead(PIN)) {
    if (micros() - t0 > TIMEOUT_US) { interrupts(); return TIMEOUT_US + 1; }
  }
  uint32_t dt = micros() - t0;
  interrupts();
  return dt;
}

void loop() {
  uint32_t dt = measureOnce();
  runs++;
  if (dt > TIMEOUT_US) {
    timeouts++;
    Serial.println(F("NEVER ROSE (>50 ms) -- the line has no path to +5 V."
                     " Missing pull-up, wrong row, or an unpowered rail."));
  } else {
    if (dt > worst) worst = dt;
    if (dt < best)  best = dt;
    sum += dt;
  }

  if (runs % 20 == 0) {
    uint32_t good = runs - timeouts;
    Serial.print(F("n=")); Serial.print(runs);
    if (good) {
      Serial.print(F("  best ")); Serial.print(best);
      Serial.print(F(" us  mean ")); Serial.print(sum / good);
      Serial.print(F(" us  worst ")); Serial.print(worst);
    }
    Serial.print(F(" us  timeouts ")); Serial.print(timeouts);
    if (timeouts) {
      Serial.println(F("  -> FAIL: no pull-up path"));
    } else if (worst > BUDGET_US) {
      Serial.println(F("  -> FAIL: slower than half a bit-time."
                       " Pull-up too large (check the colour bands: 4k7 is"
                       " yellow-violet-RED, 47k is orange, 470k is yellow)"
                       " or the bus wire is too long."));
    } else if (worst > BUDGET_US / 8) {
      Serial.println(F("  -> MARGINAL: under budget but far slower than a"
                       " 4k7 breadboard bus should be."));
    } else {
      Serial.println(F("  -> PASS"));
    }
  }
  delay(50);
}
