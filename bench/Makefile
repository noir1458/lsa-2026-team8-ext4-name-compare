CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
all: lookup_bench cpu_state
lookup_bench: lookup_bench.c
	$(CC) $(CFLAGS) $< -o $@
cpu_state: cpu_state.c
	$(CC) $(CFLAGS) $< -o $@
clean:
	rm -f lookup_bench cpu_state
.PHONY: all clean
