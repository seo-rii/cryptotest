# Problem 6 optimization experiments

This directory preserves the original Python solver, alternative optimized
implementations, and the repeated benchmark used to select the final approach.
Every measured process must reproduce `d`, state `s2`, and `r3`; build time is
excluded, but process startup, input loading, precomputation, and the complete
attack are included.

## Implementations

- `solve_06_baseline.py`: the original right-to-left Jacobian Python solver.
- `solve_06_optimized.py`: the optimized Python implementation retained as an
  experiment snapshot. The final maintained copy is
  `../solve_06_prng.py`.
- `solve_06_gmp.cpp`: GMP field arithmetic plus OpenMP low-16-bit sharding.
- `deep_native_06.cpp`: fixed two-limb Montgomery arithmetic, POD Jacobian
  points, an affine fixed-`Q` comb table, and adaptive OpenMP scheduling. This
  is the fastest verified implementation on the measured host.
- `benchmark_06.py`: one or more discarded warm-ups, at least five interleaved
  samples, known-answer validation, median/MAD/percentiles, paired speedups,
  per-stage statistics, and optional JSON output across Python, GMP, and native
  implementations.
- `benchmark_deep_native_06.py`: native/GMP ablations, same-thread paired
  comparisons, optional original-Python timing, and native self-test preflight.

The main algorithmic changes are:

1. Convert the second telemetry row to a modular interval and use Euclidean
   `floor_sum` counts to locate the unique missing low value. This changes the
   instance's telemetry work from a `2^20` scan to
   `O(log(2^20) log n)` integer operations.
2. Evaluate only one of `(x,+y)` and `(x,-y)`: multiplication by `d` negates the
   points but leaves their affine x-coordinate equal.
3. Use width-5 wNAF for the fixed scalar `d` on arbitrary lifted points.
4. Precompute an 11-by-256 byte-comb table for the repeatedly used fixed base
   `Q`; one multiplication then needs at most 11 table additions.
5. In C++, split the remaining low-16-bit search into dynamic 64-candidate
   OpenMP chunks while sharing the read-only comb table.

## Reproduce

The dependency-free final Python implementation is:

```bash
python3 solutions/solve_06_prng.py --backend int --telemetry analytic
```

Run the full repeated matrix from the repository root:

```bash
python3 solutions/benchmark_06_prng.py \
  --warmup 1 --repetitions 5 \
  --output /tmp/challenge06-benchmark.json
```

The benchmark builds C++ into a temporary directory. It requires GMP, a C++20
compiler, and OpenMP for the C++ cases; the final Python `int` case has no
third-party dependency.

## Deep algorithm review

[`deep_review_06_algorithm.md`](deep_review_06_algorithm.md) records an
orthogonal review of the remaining state-recovery work.  Its candidate solver
and repeated runner are [`solve_06_algorithm_candidates.cpp`](solve_06_algorithm_candidates.cpp)
and [`benchmark_06_algorithm_candidates.py`](benchmark_06_algorithm_candidates.py).
They cover Brier--Joye X/Z-only ladders, Montgomery batch inversion, consecutive
cubic finite differences, a Legendre prefilter, wNAF widths 2--6, and block
sizes/scheduling.

On the 8-thread host, the GMP baseline measured 0.486286 s.  The best nominal
batch result was 0.475473 s (1.023x), but its 0.044612 s standard deviation was
larger than the difference.  X-only with deferred residue testing took
1.003282 s, while a Legendre-prefiltered X-only path still took 0.516119 s.
No candidate produced a repeatable algorithmic win, so the verified GMP path
remains the algorithmic control. The fixed-width native implementation below
keeps the same attack but removes the general-purpose arithmetic and object
layout costs.

## Deep native arithmetic and cache review

[`deep_review_06_micro.md`](deep_review_06_micro.md) documents the implementation,
ablation data, failure cases, and sources. The native path uses a 16-byte
two-limb Montgomery field element and a 48-byte allocation-free Jacobian point.
It batch-normalizes the fixed-`Q` byte-comb table to an aligned, shared affine
layout: `11 * 256 * 32 = 90,112` bytes, one third smaller than the equivalent
native Jacobian layout. Fixed-base multiplication then uses mixed additions,
while arbitrary lifted points use width-2 NAF without per-candidate tables.

The scheduler hands out monotone 64-candidate blocks so workers stop before
unassigned work beyond the best low bits. `adaptive` uses block batch inversion
with one thread, but uses a scalar per-candidate pipeline with two or more
threads; the latter avoids thread-local batch traffic once binary-GCD inversion
is cheap. AVX2 was reviewed but not implemented because it has no packed
64x64-to-128 integer product, and radix conversion plus lane compaction would
work against this branchy 88-bit workload.

Before timing, the runner checks 2,000 field vectors against independent
canonical arithmetic and 256 point/scalar vectors against an affine reference.
Every timed process also verifies `P=dQ`, `d`, `s2`, `r3`, and the recovered low
bits.

## Results on the available host

### Language/backend matrix

AMD EPYC 7B12 VM, 8 logical CPUs, Python 3.11.2, GCC/G++ 12.2.0; one discarded
warm-up followed by five complete measured runs:

| Implementation | Median | Ratio of medians | Paired median |
|---|---:|---:|---:|
| original Python | 14.298741 s | 1.00x | 1.00x |
| optimized Python `int` | 3.272242 s | 4.37x | 4.41x |
| optimized Python `gmpy2` | 3.000356 s | 4.77x | 4.61x |
| C++/GMP, 1 thread | 1.873220 s | 7.63x | 7.44x |
| C++/GMP/OpenMP, 8 threads | 0.447919 s | 31.92x | 30.75x |

An independent warm repeated microbenchmark measured telemetry alone at
1,453.475 ms for the original enumeration and 0.750 ms for analytic
`floor_sum`, a 1,938x stage-level improvement. Absolute times vary with shared
VM load, so the JSON keeps every raw sample rather than only this table.
An earlier independent full matrix measured the 8-thread solver at 0.445551 s,
which is consistent with the final repeated result.

### Native same-run comparison

The final native claim comes from a separate campaign that placed original
Python, GMP, and native processes in the same cyclic/reversed sequence. It used
one discarded warm-up and five verified samples per implementation.

| Implementation | Median | MAD | Ratio of medians |
|---|---:|---:|---:|
| original Python | 14.073190 s | 0.295610 s | 1.00x |
| C++/GMP, 1 thread | 1.971840 s | 0.048047 s | 7.14x vs Python |
| native adaptive, 1 thread | 0.362651 s | 0.009200 s | 38.81x vs Python; 5.44x vs GMP |
| C++/GMP, 8 threads | 0.436403 s | 0.007239 s | 32.25x vs Python |
| native adaptive, 8 threads | 0.085076 s | 0.006915 s | 165.42x vs Python; 5.13x vs GMP |

The same-round paired medians were 5.31x and 5.34x against the matching
one- and eight-thread GMP runs. The 8-thread native MAD was 8.13%, so absolute
times remain host-load sensitive; nevertheless its slowest sample was more
than four times faster than the fastest GMP sample in that campaign.

The value formerly printed as `s1` is correctly labeled `s2`: the point lifted
from `r0` is `s1 Q`, and multiplying it by `d` produces `s1 P`, whose affine
x-coordinate is the next state `s2`.
