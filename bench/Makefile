CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
lookup_bench: lookup_bench.c
	$(CC) $(CFLAGS) $< -o $@
clean:
	rm -f lookup_bench
.PHONY: clean
