// arbitration.h -- CAN-style non-destructive bitwise arbitration on a wired-AND bus.
//
// Electrically: pin as INPUT (high-Z) = recessive 1, held up by one pull-up resistor.
//               pin as OUTPUT LOW     = dominant  0, overrides every other station.
// So the line is the AND of all drivers. A station that sends 1 and reads 0 has lost,
// stops transmitting immediately, and the winner's frame proceeds UNDAMAGED.
//
// Consequence the students must confront: the lowest id wins every contested slot,
// forever. That is a rigged market, and fixing it is the assignment.
#ifndef ARBITRATION_H
#define ARBITRATION_H

#include <stdint.h>

// Resolve one arbitration round in software (for tests and for the simulator).
// ids: candidate station ids; n: how many; width: bits arbitrated (usually 8).
// Returns the winning id.
static inline uint8_t arb_winner(const uint8_t* ids, uint8_t n, uint8_t width) {
  uint8_t alive[32]; uint8_t m = 0;
  for (uint8_t i = 0; i < n && m < 32; i++) alive[m++] = ids[i];
  for (int8_t bit = (int8_t)width - 1; bit >= 0 && m > 1; bit--) {
    uint8_t line = 1;
    for (uint8_t i = 0; i < m; i++) if (((alive[i] >> bit) & 1) == 0) { line = 0; break; }
    uint8_t k = 0;
    for (uint8_t i = 0; i < m; i++) if (((alive[i] >> bit) & 1) == line) alive[k++] = alive[i];
    m = k;
  }
  return m ? alive[0] : 0xFF;
}

#endif
