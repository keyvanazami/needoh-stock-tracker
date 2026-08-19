# B-Stack hardware core — instructor reference build

Portable C++ that compiles unchanged for AVR and for the host, plus the three
Arduino sketches the course depends on.

    make test          # 19 assertions, runs natively, no hardware needed

## What is here

| path | what it is |
|---|---|
| `lib/bframe.*`      | frame format + CRC-16/CCITT-FALSE. Check value `crc16("123456789") == 0x29B1` |
| `lib/manchester.*`  | Manchester line coding for the radio path, with code-violation sync |
| `lib/delayline.h`   | the repeater core: a sampled circular **bit** buffer |
| `lib/arbitration.h` | wired-AND bitwise arbitration, in software for tests |
| `test/test_host.cpp`| 19 host assertions covering all of the above |
| `vectors/acceptance.txt` | byte-exact vectors your build must reproduce |
| `arduino/repeater/` | **build this first** — the calibrated delay instrument |
| `arduino/busnode/`  | a station on the pit: carrier sense, arbitration, backoff |
| `arduino/dualrx/`   | the wire-vs-radio measurement rig (no clock sync needed) |

## Two things that are easy to get wrong

1. **The repeater must delay bits, not frames.** A store-and-forward relay serialises
   the bus and makes collisions impossible — destroying the exact phenomenon the
   device exists to create.
2. **Run the bus at 2400 baud, not 9600.** At 9600 the sampling ISR has only 208 CPU
   cycles; at 2400 it has 833, and the delay range grows from 167 ms to 667 ms.

The Arduino sketches need the AVR toolchain to compile; the `lib/` core is tested
on the host and is shared by both.
