# Challenge 2 submission

Files:

- `contest.c`: final two-round-composed BMI2 implementation using the provided harness
- `report.pdf`: required analysis, implementation, verification, and benchmark report
- `report.tex`: reproducible source for the PDF

To run the submitted harness, place the provided `testvector.txt` and `testvector_20round.txt` beside `contest.c`, then run:

```bash
gcc -O3 -Wall -Wextra -o contest contest.c
./contest
```

The repository-level reproducible reference comparison is:

```bash
python3 solutions/benchmark_02_permutation.py \
  --cpu 2 --iterations 10000000 \
  --warmups 3 --samples 15 --random-cases 100000 \
  --json /tmp/challenge02-benchmark.json
```

The benchmark compares the preserved pre-optimization complete contest source
with this final source, discards warm-up processes, interleaves measured runs,
and reports raw samples, median/MAD/percentiles, bootstrap intervals, and paired
speedup. The local contest-shaped paired median was 1.068x in the primary run;
the final Intel Core Ultra 7 255H should rerun the same protocol because the
shared AMD VM showed several-percent campaign-to-campaign variation.

The deeper 18-candidate algorithm/frontend/cache review is in
[`../../solutions/02_optimization/deep_review_02.md`](../../solutions/02_optimization/deep_review_02.md).
It found no repeatable replacement for the submitted 1,267-byte full-unroll
helper. A 715-byte partial-unroll candidate won one paired session but lost the
immediate repeat and the native-profile run, so it remains a target-only A/B
candidate rather than the default submission.
