# Two builds of the same source.
#
#   pricer         compiler defaults for floating-point contraction. GCC
#                  defaults to -ffp-contract=fast for C++ in every -std,
#                  including the -std=c++17 used here; Clang 14+ defaults to
#                  -ffp-contract=on. Either fuses a*b+c on arm64, where FMA is
#                  in the base ISA. On x86-64 at the default x86-64-v2 target
#                  there is no FMA instruction to fuse into.
#   pricer-strict  -ffp-contract=off: multiply and add are always rounded
#                  separately, on every architecture.
#
# Comparing the two binaries on one host shows whether contraction changed
# any result there. Comparing pricer-strict across hosts isolates what the
# math library contributes.
#
# Override the compiler or add a CPU target as needed, for example:
#   make CXX=clang++
#   make EXTRA="-mcpu=neoverse-512tvb"

CXX      ?= g++
EXTRA    ?=
CXXFLAGS := -std=c++17 -O3 -pthread -Wall $(EXTRA)

DEFAULT_FLAGS := $(CXXFLAGS)
STRICT_FLAGS  := $(CXXFLAGS) -ffp-contract=off

all: pricer pricer-strict

pricer: pricer.cpp
	$(CXX) $(DEFAULT_FLAGS) -DBUILD_FLAGS='"$(DEFAULT_FLAGS)"' $< -o $@

pricer-strict: pricer.cpp
	$(CXX) $(STRICT_FLAGS) -DBUILD_FLAGS='"$(STRICT_FLAGS)"' $< -o $@

clean:
	rm -f pricer pricer-strict *.bin

.PHONY: all clean
