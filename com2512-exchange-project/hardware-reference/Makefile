CXXFLAGS = -std=c++17 -Wall -Wextra -O2 -I lib
all: test vectors
test:
	@g++ $(CXXFLAGS) test/test_host.cpp lib/bframe.cpp lib/manchester.cpp -o /tmp/bstack_test
	@/tmp/bstack_test
vectors:
	@echo "see vectors/acceptance.txt"
clean:
	@rm -f /tmp/bstack_test
.PHONY: all test vectors clean
