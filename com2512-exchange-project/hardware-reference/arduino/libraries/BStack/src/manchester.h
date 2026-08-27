// manchester.h -- Manchester line coding for the 433 MHz OOK radio path.
//
// IEEE 802.3 convention:  bit 0 -> 1,0   (high then low)
//                         bit 1 -> 0,1   (low then high)
// Every bit carries a mid-bit transition, so the receiver can recover its clock
// and the line stays DC-balanced -- both mandatory on a cheap OOK receiver whose
// automatic gain control drifts on long runs of the same level.
//
// Cost: exactly 2x the bits. That doubling is why the radio feed's byte budget
// is half what the raw bitrate suggests.
#ifndef MANCHESTER_H
#define MANCHESTER_H

#include <stdint.h>
#include <stddef.h>

// Encode len bytes into out (needs 2*len bytes). Returns bytes written.
size_t mn_encode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap);

// Decode 2*n Manchester bytes back into n bytes.
// Returns bytes written, or 0 if any symbol is invalid (00 or 11 = collision/noise).
size_t mn_decode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap);

// Number of raw line bits needed to send len bytes Manchester-coded.
static inline size_t mn_line_bits(size_t len) { return len * 8 * 2; }

#endif
