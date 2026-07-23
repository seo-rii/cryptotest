#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="$script_dir/../../problems/2_암호구현.zip"

if [[ ! -f "$archive" ]]; then
    printf 'missing official archive: %s\n' "$archive" >&2
    exit 1
fi

workdir="$(mktemp -d "${TMPDIR:-/tmp}/cryptotest-02.XXXXXX")"
cleanup() {
    find "$workdir" -mindepth 1 -maxdepth 1 -type f -delete
    rmdir "$workdir"
}
trap cleanup EXIT

unzip -j -q "$archive" \
    'code/testvector.txt' \
    'code/testvector_20round.txt' \
    -d "$workdir"

# The statement explicitly permits additional optimization flags (for example,
# AVX256).  BMI2 gives GCC a flag-free rotate instruction, while the raised
# inline limit keeps the public permutation wrapper out of the timed loop.
gcc -O3 -Wall -Wextra -mbmi2 -finline-limit=2000 \
    -o "$workdir/contest" "$script_dir/contest.c"

cd "$workdir"
./contest
