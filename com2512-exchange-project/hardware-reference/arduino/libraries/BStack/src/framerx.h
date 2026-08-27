// framerx.h -- byte-at-a-time frame receiver. Portable: host and AVR.
//
// This is the single piece of the link layer that is most often written wrongly.
// A receiver cannot assume it starts listening at a frame boundary: it may join
// mid-frame, mid-byte, or during line noise. It must therefore hunt for the
// preamble, confirm the SFD, and only then trust a length field -- and if the
// CRC fails it must resynchronise rather than consume the next frame as body.
#ifndef FRAMERX_H
#define FRAMERX_H

#include "bframe.h"

class FrameRx {
 public:
  FrameRx() { reset(); }

  void reset() { st_ = HUNT; idx_ = 0; need_ = 0; }

  // Statistics worth grading students on.
  uint16_t frames_ok = 0, crc_errors = 0, resyncs = 0, oversize = 0;

  // Feed one received byte. Returns 1 when *out holds a complete, CRC-valid frame.
  int feed(uint8_t b, BFrame* out) {
    switch (st_) {
      case HUNT:                                   // waiting for preamble
        if (b == BF_PREAMBLE) st_ = PRE;
        return 0;

      case PRE:                                    // saw >=1 preamble byte
        if (b == BF_PREAMBLE) return 0;            // more preamble, stay
        if (b == BF_SFD) { st_ = HDR; idx_ = 0; return 0; }
        st_ = HUNT; resyncs++;                     // garbage: resynchronise
        return 0;

      case HDR:
        buf_[idx_++] = b;
        if (idx_ < BF_HDR_LEN) return 0;
        if (buf_[0] > BF_MAX_PAYLOAD) {            // length field we cannot trust
          oversize++; resyncs++; reset(); return 0;
        }
        need_ = (uint16_t)buf_[0] + BF_CRC_LEN;
        if (need_ == BF_CRC_LEN) { st_ = BODY; }   // zero-length payload still has a CRC
        else st_ = BODY;
        return 0;

      case BODY:
        buf_[idx_++] = b;
        if (idx_ < (uint16_t)BF_HDR_LEN + need_) return 0;
        {
          int ok = bf_decode_body(buf_, idx_, out);
          reset();
          if (ok) { frames_ok++; return 1; }
          crc_errors++; resyncs++;
          return 0;
        }
    }
    return 0;
  }

 private:
  enum State { HUNT, PRE, HDR, BODY } st_;
  uint8_t  buf_[BF_HDR_LEN + BF_MAX_PAYLOAD + BF_CRC_LEN];
  uint16_t idx_, need_;
};

#endif
