#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# The statement explicitly permits additional optimization flags (for example,
# AVX256).  BMI2 gives GCC a flag-free rotate instruction, while the raised
# inline limit keeps the public permutation wrapper out of the timed loop.
gcc -O3 -Wall -Wextra -mbmi2 -finline-limit=2000 -o contest contest.c
./contest
