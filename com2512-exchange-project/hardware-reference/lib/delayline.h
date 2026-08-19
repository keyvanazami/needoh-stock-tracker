// delayline.h -- the calibrated delay repeater's core: a sampled circular bit buffer.
//
// WHY BITS AND NOT FRAMES: a store-and-forward repeater that buffers whole frames
// destroys the very thing this device exists to create. During real propagation the
// far end has NOT yet seen carrier, and that window is exactly when collisions occur.
// Buffer whole frames and collisions become impossible again.
//
// Sizing:  buffer_bits = delay_us * sample_rate_hz / 1e6
//          at 8 samples/bit and 2400 baud -> 19200 Hz, so 71.5 ms needs 1373 bits = 172 bytes.
#ifndef DELAYLINE_H
#define DELAYLINE_H

#include <stdint.h>

template <uint16_t BITS>
class DelayLine {
 public:
  DelayLine() { reset(1); }

  void reset(uint8_t idle_level) {
    head_ = 0; depth_ = BITS;
    uint8_t fill = idle_level ? 0xFF : 0x00;
    for (uint16_t i = 0; i < (BITS + 7) / 8; i++) buf_[i] = fill;
  }

  // Delay in samples. Clamped to the buffer; returns the value actually set.
  uint16_t set_depth(uint16_t samples) {
    depth_ = samples ? (samples < BITS ? samples : BITS) : 1;
    return depth_;
  }
  uint16_t depth() const { return depth_; }
  static uint16_t capacity() { return BITS; }

  // Call once per sample tick: push the sensed line level, get the level to drive out.
  inline uint8_t step(uint8_t in_level) {
    uint16_t tail = (uint16_t)((head_ + BITS - depth_) % BITS);
    uint8_t out = (uint8_t)((buf_[tail >> 3] >> (tail & 7)) & 1);
    if (in_level) buf_[head_ >> 3] |= (uint8_t)(1u << (head_ & 7));
    else          buf_[head_ >> 3] &= (uint8_t)~(1u << (head_ & 7));
    head_ = (uint16_t)((head_ + 1) % BITS);
    return out;
  }

 private:
  uint8_t  buf_[(BITS + 7) / 8];
  uint16_t head_;
  uint16_t depth_;
};

#endif
