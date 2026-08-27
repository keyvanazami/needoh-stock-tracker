# B-Stack hardware core — instructor reference build

Portable C++ that compiles unchanged for AVR and for the host, plus the three
Arduino sketches the course depends on.

    tar -xzf bstack-hardware-kit.tar.gz
    cd bstack-hw               # the archive extracts to this folder
    make                       # 37 assertions + compile-check all 7 sketches

    make doctor        # what's present, which compiler, which make
    make test          # host assertions only
    make sketches      # compile every sketch against an Arduino shim

Paths are resolved relative to the Makefile, not your shell's current directory,
so `make -C /path/to/bstack-hw test` works from anywhere. If files are missing,
`make` names them and stops rather than emitting compiler errors.

## What is here

| path | what it is |
|---|---|
| `lib/bframe.*`      | frame format + CRC-16/CCITT-FALSE. Check value `crc16("123456789") == 0x29B1` |
| `lib/manchester.*`  | Manchester line coding for the radio path, with code-violation sync |
| `lib/delayline.h`   | the repeater core: a sampled circular **bit** buffer |
| `lib/arbitration.h` | wired-AND bitwise arbitration, in software for tests |
| `test/test_host.cpp`| 19 host assertions covering all of the above |
| `vectors/acceptance.txt` | byte-exact vectors your build must reproduce |
| `arduino/libraries/BStack/` | the Arduino library, in 1.5 format: `src/` + `examples/` |
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

## Installing the Arduino library

Copy `arduino/libraries/BStack` into your Arduino `libraries/` folder, then **restart the IDE**
— it scans for libraries only at startup.

Two packaging rules the IDE enforces, and both are easy to get wrong:

* Sources must live in `src/` whenever `library.properties` is present. Headers at the folder
  root are the older 1.0 format and are ignored once a `library.properties` exists.
* The library appears under **File → Examples** only if an `examples/` folder exists, with one
  sub-folder per sketch, each named identically to its `.ino` file.

If it still does not appear, check the folder is not nested one level too deep
(`libraries/BStack/BStack/` after unzipping). `library.properties` must sit directly inside
`libraries/BStack/`.

Run `make sketches` to compile-check everything on your laptop before touching hardware.
