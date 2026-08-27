// Minimal Arduino API shim -- lets the sketches be compile-checked on a host.
// It is NOT an emulator: it exists to catch missing includes, undefined symbols
// and type errors before anyone plugs in a board.
#ifndef ARDUINO_H_SHIM
#define ARDUINO_H_SHIM
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define LOW 0
#define HIGH 1
#define A0 14
#define FALLING 2
#define RISING 3

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int  digitalRead(uint8_t) { return 1; }
inline int  analogRead(uint8_t) { return 0; }
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned int) {}
inline unsigned long millis() { return 0; }
inline unsigned long micros() { return 0; }
inline long random(long hi) { return hi ? (rand() % hi) : 0; }
inline long random(long lo, long hi) { return lo + (hi > lo ? rand() % (hi - lo) : 0); }
inline void randomSeed(unsigned long) {}
inline uint8_t digitalPinToInterrupt(uint8_t p) { return p; }
inline void attachInterrupt(uint8_t, void (*)(), int) {}
inline void interrupts() {}
inline void noInterrupts() {}

#define F(x) (x)
struct FakeSerial {
  void begin(unsigned long) {}
  void print(const char*) {} void print(int) {} void print(unsigned int) {}
  void print(long) {} void print(unsigned long) {} void print(char) {}
  void print(int, int) {} void print(unsigned int, int) {}
  void println(const char*) {} void println(int) {} void println(unsigned int) {}
  void println(long) {} void println(unsigned long) {}
  void println(int, int) {} void println(unsigned int, int) {} void println() {}
  int available() { return 0; }
  int read() { return -1; }
  long parseInt() { return 0; }
};
extern FakeSerial Serial;
#define HEX 16

// AVR timer registers used by the repeater sketch
extern uint8_t TCCR1A, TCCR1B, TIMSK1;
extern uint16_t TCNT1, OCR1A;
#define WGM12 3
#define CS10  0
#define OCIE1A 1
#define ISR(v) void v##_handler()
#define TIMER1_COMPA_vect TIMER1_COMPA
#endif
