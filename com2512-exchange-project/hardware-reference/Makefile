# B-Stack reference kit.
#
# Every path below is resolved relative to THIS Makefile, not to your current
# directory, so `make` works no matter where you invoke it from:
#     make -C ~/yu_networking/project/bstack-hw test
#     cd anywhere && make -f /path/to/bstack-hw/Makefile test
ROOT := $(patsubst %/,%,$(dir $(realpath $(lastword $(MAKEFILE_LIST)))))

CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O2
INC       = -I$(ROOT)/lib
LIB       = $(ROOT)/arduino/libraries/BStack
SKETCHES  = venue trader repeater busnode dualrx radio_tx radio_rx
OUT      := $(shell printf '%s' "$${TMPDIR:-/tmp}" | sed 's:/*$$::')

all: check test sketches

# ---------------------------------------------------------------- diagnostics
REQUIRED = lib/bframe.h lib/bframe.cpp lib/framerx.h lib/book.h \
           lib/manchester.h lib/manchester.cpp lib/delayline.h lib/arbitration.h \
           test/test_host.cpp test/test_new.cpp test/shim/Arduino.h \
           arduino/libraries/BStack/library.properties \
           arduino/libraries/BStack/src/BStack.h

check:
	@echo "kit root: $(ROOT)"
	@missing=0; for f in $(REQUIRED); do \
	  if [ ! -f "$(ROOT)/$$f" ]; then echo "  MISSING  $$f"; missing=1; fi; \
	done; \
	if [ $$missing -eq 1 ]; then \
	  echo; \
	  echo "The kit tree is incomplete. The archive extracts to a folder named"; \
	  echo "'bstack-hw' containing lib/, test/ and arduino/. Run make from there:"; \
	  echo "    tar -xzf bstack-hardware-kit.tar.gz"; \
	  echo "    cd bstack-hw && make"; \
	  exit 1; \
	else echo "  all $(words $(REQUIRED)) required files present"; fi

doctor: check
	@echo "compiler: $$($(CXX) --version 2>/dev/null | head -1)"
	@echo "make    : $$(make --version 2>/dev/null | head -1)"
	@echo "sketches: $(words $(SKETCHES))"

# --------------------------------------------------------------------- tests
test: check
	@$(CXX) $(CXXFLAGS) $(INC) $(ROOT)/test/test_host.cpp $(ROOT)/lib/bframe.cpp \
	   $(ROOT)/lib/manchester.cpp -o $(OUT)/bs_t1 && $(OUT)/bs_t1
	@echo
	@$(CXX) $(CXXFLAGS) $(INC) $(ROOT)/test/test_new.cpp $(ROOT)/lib/bframe.cpp \
	   -o $(OUT)/bs_t2 && $(OUT)/bs_t2

# Compile-check every sketch against a minimal Arduino shim. No board, no AVR
# toolchain -- catches missing includes and undefined symbols.
sketches: check
	@echo
	@echo "=== sketch compile check ==="
	@fail=0; for d in $(SKETCHES); do \
	  printf "  %-14s " "$$d.ino"; \
	  cp $(ROOT)/arduino/$$d/$$d.ino $(OUT)/sk_$$d.cpp; \
	  if $(CXX) -std=c++17 -fsyntax-only -I$(ROOT)/test/shim -I$(LIB)/src \
	       -include Arduino.h $(OUT)/sk_$$d.cpp 2>$(OUT)/e_$$d; then echo OK; \
	  else echo FAILED; sed 's/^/      /' $(OUT)/e_$$d | head -4; fail=1; fi; \
	done; \
	if [ $$fail -eq 0 ]; then echo "  all $(words $(SKETCHES)) sketches compile"; else exit 1; fi

sync-examples:
	@for p in Venue:venue Trader:trader Repeater:repeater BusNode:busnode \
	          DualRx:dualrx RadioTx:radio_tx RadioRx:radio_rx; do \
	  ex=$${p%%:*}; src=$${p##*:}; mkdir -p $(LIB)/examples/$$ex; \
	  cp $(ROOT)/arduino/$$src/$$src.ino $(LIB)/examples/$$ex/$$ex.ino; \
	done; echo "examples synced"

clean:
	@rm -f $(OUT)/bs_t1 $(OUT)/bs_t2 $(OUT)/sk_*.cpp $(OUT)/e_*
.PHONY: all check doctor test sketches sync-examples clean
