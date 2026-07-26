# Problem 6 optimization experiments

This directory contains the maintained native attack, historical Python/GMP
controls, rejected algorithm candidates, and two levels of repeated benchmark.
Every timed process must reproduce `d`, `r3`, `P=dQ`, and the state and lift bits
for its declared scan window:

| scan | state | lift low | lift/filter outputs |
|---|---|---:|---|
| legacy | `s2=0x638d9d631ab436da51e640` | `0x5338` | `r0/r1` |
| shifted default | `s3=0x948173253ad6d120a3f562` | `0x3cea` | `r1/r2` |

Both paths predict the same required
`r3=0x2443c8daf1a9d52b09`.

## Implementations

- `solve_06_baseline.py`: original right-to-left Jacobian Python solver.
- `solve_06_optimized.py`: optimized Python experiment; the maintained
  dependency-free solver is `../solve_06_prng.py`.
- `solve_06_gmp.cpp`: GMP/OpenMP control using the legacy scan.
- `solve_06_algorithm_candidates.cpp`: Brier--Joye, batch inversion, finite
  difference, Legendre, and wNAF experiments.
- `deep_native_06.cpp`: fastest maintained native implementation.
- `benchmark_06.py`: broad language/backend screening, exposed at
  `../benchmark_06_prng.py`.
- `benchmark_deep_native_06.py`: broad GMP/native/thread/scheduler screening.
- `benchmark_06_promotion.py`: frozen-source, CPU-pinned adjacent AB/BA
  promotion test for exactly two native variants.

## Final native stack

The default `deep_native_06.cpp` combines:

1. analytic `floor_sum` telemetry recovery instead of a `2^20` scan;
2. a shifted `r1` lift and `r2` filter, reducing this instance's sequential
   prefix from 21,305 to 15,595 candidates (26.8%);
3. one lift sign because `X([d]R)=X([d](-R))`;
4. BMI2/ADX 2-by-2 Montgomery REDC and branchless carry/borrow arithmetic on
   supported x86-64 CPUs;
5. an unrolled `unsigned __int128` fallback on other targets;
6. an isomorphic `a=-3` curve for the arbitrary-point scan;
7. Hamburg's co-Z short-Weierstrass ladder for the recovered fixed `d`, with a
   complete width-2 NAF fallback for exceptional inputs;
8. an 88-bit Jacobi residue test, deferring the square root to the exceptional
   NAF fallback instead of exponentiating for every lift;
9. a width-8 fixed-`Q` affine comb table and mixed Jacobian addition;
10. monotone OpenMP work assignment: block-64 at one thread, block-32 at two
    threads, and the scalar pipeline at three or more threads.

The fixed field element is 16 bytes, a Jacobian point is 48 bytes, and the
default read-only fixed table is 90,112 bytes.

## Correctness preflight

Before timing, the native self-test checks:

- 2,000 deterministic random field pairs;
- 64 boundary pairs around zero, `p`, and the 64-bit limb boundary;
- 256 point/scalar/table vectors against an affine reference, including signed
  carry, subgroup-order, and 88-bit scalar boundaries;
- 128 real curve lifts comparing Hamburg and NAF affine x-coordinates.

The same field vectors compare Euclidean and subtractive Jacobi results with a
Fermat/Legendre reference.

Every timed JSON result also reports the selected field backend, curve model,
`d` multiplication, lift residue test, table width/encoding, scan label and
output indices, requested and actual threads, schedule, inverse, and
square-root method, plus requested/effective block size and fixed-`Q`
multiplication layout. The solver rejects a smaller OpenMP team, and the benchmark
rejects metadata mismatches instead of timing an accidentally inactive macro.

## Reproduce

The dependency-free answer path is:

```bash
python3 solutions/solve_06_prng.py --backend int --telemetry analytic
```

Build and run the native path:

```bash
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06
/tmp/deep_native_06 --self-test --json
/tmp/deep_native_06 --threads 1 --json
/tmp/deep_native_06 --threads 8 --json
```

The portable path does not require BMI2/ADX:

```bash
g++ -O3 -DNDEBUG -std=c++20 -fopenmp \
  -DCH6_PORTABLE_ARITHMETIC \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06_portable
/tmp/deep_native_06_portable --self-test --json
```

Use the broad matrix to screen large effects:

```bash
python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 7 --threads 1,8 \
  --native-schedules adaptive \
  --output /tmp/ch6-broad.json
```

Use the promotion runner for a small candidate. This example isolates the
NAF/Hamburg change by forcing the same square-root lift in both builds:

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label naf --candidate-label hamburg \
  --baseline-define CH6_NAF_D_MULTIPLICATION \
  --candidate-define CH6_SQRT_LIFT \
  --threads 1 --warmup-pairs 2 --pairs 40 \
  --output /tmp/ch6-hamburg.json
```

The promotion protocol uses four chronological blocks, each with five AB and
five BA pairs, 5,000 deterministic bootstrap resamples within the eight
block-by-order strata, both order strata, and an absolute/effect stationarity
gate. It rejects identical build/runtime configurations unless
`--null-calibration` is explicit. All runners clear inherited OpenMP thread and
affinity overrides, use the current affinity mask for `auto`, and record what
was cleared. The measured source is preserved beside the report as
`/tmp/ch6-hamburg.json.source.cpp`.

## Selection results

The stationarity-gated wins now include:

| candidate | paired median | bootstrap 95% CI | decision |
|---|---:|---:|---|
| shifted scan vs legacy scan | 1.3428x | 1.3336..1.3510 | adopted |
| Hamburg co-Z vs width-2 NAF | 1.1716x | 1.1682..1.1764 | adopted |
| Jacobi lift vs square-root lift, 1T | 1.0819x | 1.0769..1.0842 | adopted |
| adaptive block-32 vs scalar-64, 2T | 1.2121x | 1.2051..1.2163 | adopted |

After ten warm-up pairs, the pre-Jacobi source comparison of the complete
legacy stack (generic carry, legacy scan, original curve, NAF) against the
then-default stack measured `0.283205 s` versus `0.076114 s`. Its paired median was
`3.7126x` (CI `3.7106..3.7251`); both order strata and all four stationarity
blocks passed. It is historical combined evidence, not a current-stack number.

A balanced signed-w9 table reduced the table to 82,560 bytes but reached only
`1.0065x` (CI `1.0035..1.0094`), below the 2% promotion threshold. Row-batched
affine fixed-`Q` multiplication lost at `0.9351x`, and subtractive Jacobi was
statistical parity at `1.0072x` with a parity-containing CI. A w4 fixed table
lost to w8 (`0.9483x`, CI `0.9243..0.9737`), and block 128
did not beat block 64 (`0.9948x`, CI `0.9093..1.0473`). Specialized square,
direct U128 add, a straight-line sqrt chain, w9, field-multiply `noinline`,
Hamburg inline, PRAC, and GLV/endomorphism variants were also rejected or kept
diagnostic-only.

A saved generic-carry/BMI2 holdout showed a large `2.9808x` paired median and
all pairs favored BMI2/ADX, but the shared host's chronological block spread
failed the stationarity gate. It is therefore evidence of direction, not a
portable absolute-speed claim.

The isomorphic `a=-3` scan similarly measured `1.1022x` with bootstrap CI
`1.0320..1.1274`, but failed stationarity after a VM phase change. It remains
the verified default with an original-curve compile-time fallback, while that
timing is explicitly diagnostic-only rather than a promotion-grade PASS.

## Detailed records

- [`deep_review_06_algorithm.md`](deep_review_06_algorithm.md): shifted scan,
  Hamburg, and the earlier rejected GMP algorithm candidates.
- [`deep_review_06_micro.md`](deep_review_06_micro.md): arithmetic, cache,
  scheduler, ablations, measurement limits, and references.
- [`../../writeups/06_PRNG.md`](../../writeups/06_PRNG.md): complete attack and
  contest-facing explanation.

Generated binaries, JSON reports, and frozen source snapshots belong under
`/tmp`; they are deliberately not committed.
