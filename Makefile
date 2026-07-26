PYTHON ?= python3
CC = gcc
CXX = g++
BUILD_DIR ?= /tmp/cryptotest-build

BENCH02_CPU ?= auto
BENCH02_ITERATIONS ?= 3000000
BENCH02_WARMUPS ?= 6
BENCH02_SAMPLES ?= 32
BENCH02_RANDOM_CASES ?= 100000
BENCH02_OUTPUT ?= /tmp/cryptotest-bench-02.json

BENCH06_THREADS ?= 1
BENCH06_SCHEDULES ?= adaptive
BENCH06_BLOCK_SIZE ?= 64
BENCH06_WARMUP ?= 1
BENCH06_REPETITIONS ?= 7
BENCH06_OUTPUT ?= /tmp/cryptotest-bench-06.json

.PHONY: test check-02 bench-02 check-06 bench-06

test:
	$(PYTHON) -m pytest -q

check-02:
	$(PYTHON) -m pytest -q \
		solutions/02_optimization/test_benchmark_02_permutation.py \
		solutions/02_optimization/test_challenge02_loop_audit.py
	./submissions/02/run_contest.sh

bench-02:
	$(PYTHON) solutions/benchmark_02_permutation.py \
		--compiler $(CC) \
		--case scalar=submissions/02/contest.c \
		--case avx2=solutions/02_optimization/contest_simd_avx2_lanewise.c \
		--baseline scalar \
		--extra-cflag=-mbmi2 \
		--extra-cflag=-finline-limit=2000 \
		--case-cflag avx2=-mavx2 \
		--audit-mode scalar=full-inline-320 \
		--audit-mode avx2=avx2-inline-lanewise \
		--cpu $(BENCH02_CPU) \
		--iterations $(BENCH02_ITERATIONS) \
		--warmups $(BENCH02_WARMUPS) \
		--samples $(BENCH02_SAMPLES) \
		--random-cases $(BENCH02_RANDOM_CASES) \
		--json $(BENCH02_OUTPUT)

check-06:
	mkdir -p $(BUILD_DIR)
	$(PYTHON) solutions/solve_06_prng.py \
		--backend int --telemetry analytic --json
	$(CXX) -O3 -DNDEBUG -march=native -std=c++20 -fopenmp -Wall -Wextra \
		solutions/06_optimization/deep_native_06.cpp \
		-o $(BUILD_DIR)/deep_native_06
	$(BUILD_DIR)/deep_native_06 --self-test --json
	$(BUILD_DIR)/deep_native_06 --threads 1 --json
	$(CXX) -O1 -g -fno-omit-frame-pointer \
		-fsanitize=undefined -fno-sanitize-recover=undefined \
		-DCH6_PORTABLE_ARITHMETIC -std=c++20 -fopenmp -Wall -Wextra \
		solutions/06_optimization/deep_native_06.cpp \
		-o $(BUILD_DIR)/deep_native_06_ubsan
	UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
		$(BUILD_DIR)/deep_native_06_ubsan --self-test --json
	UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
		$(BUILD_DIR)/deep_native_06_ubsan --threads 1 --json

bench-06:
	$(PYTHON) solutions/06_optimization/benchmark_deep_native_06.py \
		--compiler $(CXX) \
		--threads $(BENCH06_THREADS) \
		--native-schedules $(BENCH06_SCHEDULES) \
		--block-size $(BENCH06_BLOCK_SIZE) \
		--warmup $(BENCH06_WARMUP) \
		--repetitions $(BENCH06_REPETITIONS) \
		--output $(BENCH06_OUTPUT)
