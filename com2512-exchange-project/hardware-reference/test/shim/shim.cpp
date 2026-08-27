#include "Arduino.h"
FakeSerial Serial;
uint8_t TCCR1A=0, TCCR1B=0, TIMSK1=0;
uint16_t TCNT1=0, OCR1A=0;
