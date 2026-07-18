# Problem 2 optimization experiments

This directory is isolated from the existing submission and solution files. It
contains a correctness oracle, eight implementation candidates, and a benchmark
driver designed to avoid two common sources of misleading results:

- every candidate is warmed up before measurement;
- candidates are built into separate binaries, then measured in randomized
  three-sample blocks, so large unrolled functions do not perturb one another's
  instruction/µop-cache layout;
- the process is pinned to one allowed CPU by default;
- the report uses the median and median absolute deviation (MAD), rather than a
  single run or the arithmetic mean;
- every timed result is preceded by all 1,000 supplied one-round vectors, the
  supplied 20-round vector, and randomized differential tests.

## Run

The target-relevant run is:

```bash
python3 solutions/02_optimization/run_benchmarks.py \
  --profile native \
  --iterations 7000000 \
  --warmup-iterations 30000000 \
  --repeats 21 \
  --random-cases 100000
```

Use `--cpu N` to select a particular logical CPU and `--output result.txt` to
retain all metadata and raw samples. `--profile portable` removes
`-march=native`. `--mode combined` is quicker, but is deliberately not the
default: experiments showed that co-locating multiple ~1 KiB unrolled functions
can materially change scalar timing through code layout alone.

## Candidates

- `current_submission`: one state-writing helper in each of 20 iterations,
  matching the current `submissions/02/contest.c` structure.
- `register_loop`: the existing solution strategy, holding four words and eight
  constants in scalar registers for all 20 rounds.
- `paired_loop`: two rounds at a time; GCC recognizes the four independent word
  chains and emits AVX2 automatically under the native profile.
- `paired_loop_scalar`: the same recurrence with GCC vectorization disabled.
- `paired_unrolled`: the paired recurrence explicitly expanded ten times; GCC
  may emit AVX2.
- `paired_unrolled_scalar`: a fully unrolled scalar implementation.
- `paired_unrolled_bmi2`: the same scalar implementation with a local BMI2
  target attribute, ensuring non-destructive `RORX` even under the supplied
  default `gcc -O3` command.
- `avx2_single`: one AVX2 register holding the single 256-bit state.
- `avx2_batch4`: four independent states transposed across AVX2 lanes. It is
  correctness-tested and measured in combined mode, but is not compatible with
  the contest's fixed one-state timing API.

The two-round identity is:

```text
x0 <- T3(T0(x0))   x1 <- T2(T1(x1))
x2 <- T1(T2(x2))   x3 <- T0(T3(x3))
```

where `Ti` is rotate, XOR, byte-swap, and add for source word `i`. Reversal of
the four words cancels after two rounds, so no cross-word moves are needed inside
the ten-iteration recurrence.

## Measured result on the available host

Environment: AMD EPYC 7B12 VM, GCC 12.2.0, `-O3 -march=native`, logical CPU 2,
2,000,000 calls per sample, 300,000-call warmup, five randomized blocks of three
samples (15 total), and 100,000 randomized differential cases.

| Candidate | Median ns / 20 rounds | MAD ns | vs current submission | vs register loop |
|---|---:|---:|---:|---:|
| current submission | 41.894 | 2.834 | 1.000x | 0.970x |
| register loop | 40.655 | 3.083 | 1.031x | 1.000x |
| paired AVX2 loop | 39.718 | 0.131 | 1.055x | 1.024x |
| paired scalar loop | 37.751 | 2.649 | 1.110x | 1.077x |
| paired AVX2 unrolled | 39.417 | 0.086 | 1.063x | 1.031x |
| paired scalar unrolled | 36.824 | 2.617 | 1.138x | 1.104x |
| paired scalar unrolled + BMI2 | **36.249** | 3.195 | **1.156x** | **1.122x** |
| AVX2 single state | 73.630 | 0.266 | 0.569x | 0.552x |

All candidates passed the supplied vectors and 100,000 randomized differential
cases. Scalar samples varied more than vector samples on the shared VM; this is
why raw samples, MAD, and target-machine reruns matter.

The repository-level `solutions/benchmark_02_permutation.py` performs the
second, score-facing check. It compiles the preserved pre-optimization
`contest_before.c` and final `submissions/02/contest.c` as separate complete
contest programs, lengthens only the supplied timing loop, discards three
warm-up processes, and interleaves 15 or more measured processes. In a
10,000,000-call, 15-sample run the old/new medians were 36.799/34.669 ns and
the median paired speedup was 1.068x (paired bootstrap 95% interval
1.008x--1.105x). A separate noisier 20,000,000-call run measured 1.019x with
an interval of 0.991x--1.082x. Both raw campaigns are relevant: the shared VM
cannot settle a small Intel-target performance difference, so the final
Core Ultra 7 255H rerun remains necessary.

## Deep algorithm and frontend/cache review

[`deep_review_02.md`](deep_review_02.md) extends the first candidate sweep with
18 isolated binaries covering partial unroll factors, code alignment,
embedded constants, forced inlining, wrapper layout, AVX2, and deliberately
serialized dependency chains.  The matching runner is
[`run_deep_review_02.py`](run_deep_review_02.py), and
[`deep_results_02.txt`](deep_results_02.txt) retains every paired raw sample.

The 1,267-byte full-unroll helper has no hot-body spills and keeps all four
state words plus eight constants in registers.  A smaller 715-byte
`unroll5_bmi2` candidate was 1.0867x faster in one session, but repeated at
0.9712x under the same flags and 0.9214x with `-march=native`.  This reversal
shows that the remaining difference is dominated by frontend/code-layout and
shared-host effects rather than a portable reduction in work.  Alignment,
literal constants, forced inline, and the SIMD variants did not produce a
repeatable improvement.  The full-unroll implementation therefore remains the
default; only full-unroll versus `unroll5_bmi2` needs target-machine A/B testing.

## Recommendation and constraint compliance

`recommended_submission_fragment.c` is the strongest scalar candidate. It
uses no fixed input or output, only the fixed recovered permutation parameters,
and obeys the statement's edit policy by adding an external helper and invoking
it from the permitted 20-round-loop location. The `r = 19` assignment exits the
supplied redundant loop after the helper has computed all 20 rounds.

Do not choose the final submission solely from the AMD result. The judge uses an
Intel Core Ultra 7 255H with GCC 13.3.0. Benchmark both
`paired_unrolled_bmi2` and `paired_loop` on that CPU: the former won here, while
the latter had exceptionally stable timing and may have a different latency
balance on Intel. The direct one-state AVX2 implementation should not be used;
its seven-instruction dependent round path was consistently much slower.
