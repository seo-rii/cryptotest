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
- `audit_06_subgroup.py`: independent Sage audit of the curve, torsion,
  Frobenius/Miller trace identities, reciprocal coefficients, and full prefix.
- `generate_06_prac_schedule.py`: standard-library regeneration and byte-level
  audit of the fixed Lucas-PRAC schedule.

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
8. a hybrid 128/64-bit Jacobi test run directly on the Montgomery residue,
   deferring the square root to the exceptional NAF fallback;
9. an exact x-only cofactor-5 subgroup filter derived from a Frobenius/Tate
   trace over `Fp2`; it evaluates `H=(p+1)/100` with a fixed 115-byte
   Lucas-PRAC schedule and compares the result with the 11 traces of
   `mu_20`, replacing the former 170-product binary Lucas ladder with a
   124-product chain;
10. an exact reciprocal-polynomial trace: after cancelling the common
    `(x-gamma)^4` factor, Horner evaluation in `z=(x-alpha)^-1` needs five field
    products instead of the expanded formula's `6M+3S`;
11. direct in-place trace-input preparation: block scans compact the surviving
    inputs and batch-invert their denominators without staging separate x,
    curve-RHS, numerator, and denominator arrays;
12. a width-8 fixed-`Q` affine comb table and mixed Jacobian addition;
13. monotone OpenMP work assignment: block-64 at one thread, block-32 at two
    threads, and the scalar pipeline at three or more threads.

The fixed field element is 16 bytes, a Jacobian point is 48 bytes, and the
default read-only fixed table is 90,112 bytes.

## Correctness preflight

Before timing, the native self-test checks:

- 2,000 deterministic random field pairs;
- 64 boundary pairs around zero, `p`, and the 64-bit limb boundary;
- 256 point/scalar/table vectors against an affine reference, including signed
  carry, subgroup-order, and 88-bit scalar boundaries;
- 128 real curve lifts comparing Hamburg and NAF affine x-coordinates and
  comparing both scalar and batched subgroup tests with exact `[n]T=O`.

The same field vectors compare full-U128, hybrid-U64, Montgomery-residue,
canonical-input, Euclidean, and subtractive Jacobi variants with a
Fermat/Legendre reference. The subgroup preflight also checks known positive
and rational 5-torsion negative vectors, converts all 11 `mu_20` traces to
Montgomery form independently, and compares the fixed PRAC chain with the
binary Lucas oracle on every boundary and random field trace. The expanded and
reciprocal trace formulas are cross-checked on boundary and random values and
all 65,536 low bits of each of the three public prefixes. A
`-ftrivial-auto-var-init=pattern` build passes the same self-test and known
answer, guarding the write-before-read scan buffers.

Every timed JSON result also reports the selected field backend, curve model,
`d` multiplication, lift residue test, subgroup membership test, table
width/encoding, scan label and output indices, requested and actual threads,
schedule, inverse, and square-root method, plus requested/effective block size
and fixed-`Q` multiplication layout. It additionally identifies the subgroup
constant layout, batch layout, trace formula, Lucas bit scan/step, scan-buffer
initialization, and curve-constant layout. The solver rejects a smaller OpenMP
team, and the benchmark rejects metadata mismatches instead of timing an
accidentally inactive macro.

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

Regenerate the PRAC schedule and independently audit the subgroup mathematics:

```bash
python3 solutions/06_optimization/generate_06_prac_schedule.py --json
sage -python solutions/06_optimization/audit_06_subgroup.py --json
sage -python solutions/06_optimization/audit_06_subgroup.py \
  --samples 0 --full-prefix --json
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

Use the promotion runner for a small candidate. This example reproduces the
old binary-Lucas/separate-x-RHS baseline against the promoted default:

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label binary-xy --candidate-label prac20-direct \
  --baseline-define CH6_BINARY_SUBGROUP_LUCAS \
  --baseline-define CH6_XY_SUBGROUP_BATCH \
  --threads 1 --warmup-pairs 3 --pairs 40 \
  --output /tmp/ch6-prac20-direct.json
```

For the reciprocal trace ablation, use:

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label expanded-trace --candidate-label reciprocal-trace \
  --baseline-define CH6_EXPANDED_SUBGROUP_TRACE \
  --threads 1 --cpus 7 --baseline-schedule block \
  --candidate-schedule block --block-size 64 \
  --warmup-pairs 10 --pairs 40 --seed 1145324612 \
  --output /tmp/ch6-reciprocal-trace.json
```

The later three-product trace factorization can be isolated from its Horner
oracle with:

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label reciprocal-horner --candidate-label shifted-square \
  --baseline-define CH6_HORNER_SUBGROUP_TRACE \
  --threads 1 --cpus 7 --block-size 64 \
  --warmup-pairs 10 --pairs 40 --trials-per-pair 5 \
  --output /tmp/ch6-shifted-square.json
```

The block-recurrence square deferral can be compared with its eager oracle
without changing the cubic formula:

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label eager-x-square --candidate-label deferred-x-square \
  --baseline-define CH6_EAGER_BLOCK_X_SQUARE \
  --threads 1 --cpus 7 --block-size 64 \
  --warmup-pairs 10 --pairs 40 --trials-per-pair 5 \
  --output /tmp/ch6-eager-vs-deferred-square.json
```

Replace `--cpus 7` with an allowed idle CPU on another host.

The promotion protocol uses four chronological blocks, each with five AB and
five BA pairs, 5,000 deterministic bootstrap resamples within the eight
block-by-order strata, both order strata, and an absolute/effect stationarity
gate. `--trials-per-pair N` optionally runs `N` fresh-process adjacent AB or BA
trials and uses their median as one logical pair; every raw trial and logical
aggregate remains in the schema-3 report. It rejects identical build/runtime
configurations unless
`--null-calibration` is explicit. All runners clear inherited OpenMP thread and
affinity overrides, use the current affinity mask for `auto`, and record what
was cleared. The measured source is preserved beside the report as
`/tmp/ch6-prac20-direct.json.source.cpp`. Variant-specific compiler flags can
also be isolated with repeated `--baseline-cxxflag` and
`--candidate-cxxflag` options. The runner queries compiler predefines again
with each variant's flags, so ISA ablations such as `-mno-bmi2 -mno-adx` are
validated against their actual portable-backend metadata.

## Selection results

The stationarity-gated wins now include:

| candidate | paired median | bootstrap 95% CI | decision |
|---|---:|---:|---|
| shifted scan vs legacy scan | 1.3428x | 1.3336..1.3510 | adopted |
| Hamburg co-Z vs width-2 NAF | 1.1716x | 1.1682..1.1764 | adopted |
| Jacobi lift vs square-root lift, 1T | 1.0819x | 1.0769..1.0842 | adopted |
| adaptive block-32 vs scalar-64, 2T | 1.2121x | 1.2051..1.2163 | adopted |
| binary/xy vs Lucas-PRAC/direct, 1T run 1 | 1.0345x | 1.0271..1.0448 | adopted |
| binary/xy vs Lucas-PRAC/direct, 1T run 2 | 1.0311x | 1.0268..1.0376 | reproduced |

The subgroup-chain promotion is deliberately a combined change. For
`E=(p+1)/5=20H`, the fixed chain computes `L_H` in `118M+6S=124` field
products and accepts exactly the 11 values `z+z^-1` for `z` in `mu_20`.
The binary baseline needs `85M+85S=170` products. Direct fraction preparation
also reduces GCC 12's raw batch-function prologue allocation from `0x38a8` to
`0x1180`, about 10 KiB, although that layout alone was timing parity at
`1.0007x` (CI
`0.9912..1.0082`). Two independent combined campaigns passed every promotion
gate at `1.0345x` and `1.0311x`. A later final-default-source run remained
positive at `1.0382x` (CI `1.0248..1.0537`) but failed stationarity during a
host-load shift; it is recorded as a noisy confirmation, not a third PASS.
An additional post-audit run on source SHA-256
`840999f697112a17c7ebe6809351b4971b1a713d021e4c356334e3c4462ae073`
had median `1.0289x` but CI `0.9791..1.0878`; absolute block spreads of
53.8%/72.1% and a sign-changing effect made it diagnostic-only as well.
The later source SHA-256
`a97d24e5d6a581da586c0df48beb64abdeb6ab60273f2cdd00a352b74aa8df16`
differs only in stronger self-test fixtures for positive index 255,
zero-denominator compaction, and multi-lane tails; the timed path is unchanged.
The 8-thread diagnostic median was `1.0381x`, but its CI
`0.9070..1.1621` and stationarity both failed on the saturated shared VM.

The next algebraic trace simplification is independently checked by Sage.
Symbolic expansion proves
`U-V=(x-gamma)^4(x-alpha)^5`; after cancelling the common fourth power,
the trace is a degree-5 polynomial in `(x-alpha)^-1`. This changes the trace
from nine field products (`6M+3S`) to five and reduces the whole subgroup check
at that stage to approximately `132m+I` per block or `129+I` per scalar
candidate. A CPU-7-pinned
one-thread run after ten warm-up pairs measured 40 balanced pairs at
`1.0270x` (bootstrap CI `1.0027..1.0360`), but failed the chronological
stationarity gate. The timing is therefore diagnostic, while the default is
based on the exact operation reduction plus symbolic and exhaustive
equivalence checks. `CH6_EXPANDED_SUBGROUP_TRACE` preserves the former formula
as an ablation and independent oracle.

That reciprocal quintic factors further. For
`z=(x-alpha)^-1`, the checked-in constants satisfy

```text
r = lambda*z
tau = 2 + r*((r+h)^2+k)^2
```

with `lambda^5` equal to the leading coefficient. The final binary-GCD
conversion uses `lambda*R^2` instead of `R^2`, so the scale is free in
Montgomery form. Trace evaluation is therefore `2S+1M`, the three-product
multiplicative-degree lower bound, rather than Horner's `5M`. Batch inversion
also skips its first forward and final two reverse endpoint products, changing
normalization plus trace from `8m+I` to `6m-3+I` for `m` active inputs.

A pinned cycle microbenchmark measured Horner/factorized speedups of `1.269x`,
`1.304x`, and `1.313x` for `m=32,128,256`. The full one-thread solver measured
`1.0077x` with bootstrap CI `1.0043..1.0149`; shared-host absolute-time
stationarity failed and the effect is below the 2% promotion threshold, so
this is not presented as a promotion PASS. The default is instead supported
by the exact product reduction, Sage factorization oracle, scaled-inverse
cross-check, and full KAT. `CH6_HORNER_SUBGROUP_TRACE` and
`CH6_EXCLUSIVE_BATCH_PREFIX` preserve the previous hot paths.

The new cofactor-5 filter was compared in frozen source snapshot SHA-256
`5f169154d1c3b681a496169b6f4ec456a5a55c41c5986bf1ae27b5e1e90005a8`,
with only `CH6_NO_SUBGROUP_FILTER` changed. At one thread the external medians
were `0.085280/0.044124 s`, with paired `1.9444x` and bootstrap CI
`1.9113..1.9687`; at two threads they were `0.053521/0.030619 s`, with paired
`1.7448x` and CI `1.7161..1.7904`. Every chronological effect block was above
`1.71x`, but the shared host was simultaneously saturated and both runs failed
the strict absolute/effect stationarity gate. The exhaustive subgroup
equivalence check and the large, structurally expected reduction justify the
default, while these timings remain diagnostic rather than portable
absolute-speed claims.

The maintained source subsequently removed duplicate `PreparedLift` storage
and reuses its precomputed x-square. Its full correctness suite was rerun, but
that exact no-filter/filter ablation was not repeated on the saturated host.

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
did not beat block 64 before the subgroup filter (`0.9948x`, CI
`0.9093..1.0473`). With the filter, block 256 was a promising `1.0365x`
(CI `1.0173..1.0503`) but missed stationarity. The later forward-cubic
recurrence plus block-256 candidate reproduced the direction twice at
`1.0485x` (CI `1.0347..1.0667`) and `1.0455x`
(CI `1.0336..1.0510`), but both campaigns still missed the strict
chronological gate. The recurrence remains the arithmetic default, while
block 64 remains the automatic one-thread policy.

The recurrence supplies `rhs` without needing `x^2`. The final path therefore
delays that square until after the subgroup filter instead of computing it
immediately after Jacobi. On the exact solution prefix this removes 6,166 field
squares: 7,713 curve-valid lifts enter the filter and only 1,547 reach Hamburg.
The noisy five-trial logical-pair campaign measured `1.0042x` with CI
`0.9749..1.0280` and failed stationarity, so it is not a promotion PASS. The
default is retained for the exact operation deletion and full self-test/KAT;
`CH6_EAGER_BLOCK_X_SQUARE` preserves the eager oracle.

Specialized square,
direct U128 add, a straight-line sqrt chain, w9, field-multiply `noinline`,
Hamburg inline, elliptic-point scalar PRAC, and GLV/endomorphism variants were
also rejected or kept diagnostic-only. This elliptic-point PRAC experiment is
separate from the adopted Lucas-recurrence PRAC chain.

The Lucas follow-up also rejected binary two-lane interleaving (`1.0180x`, CI
`1.0015..1.0316`), the fused large-switch PRAC interpreter (`0.9880x`), and
PRAC two-lane interleaving (`0.9941x`). The compact PRAC interpreter alone was
promising at `1.0180x` (CI `1.0117..1.0286`) but remained below the 2% gate
and failed stationarity; only its direct-fraction combination reproduced a
promotion-grade win. A branchless binary step reduced the Lucas symbol from
`0x579` to `0x44c` bytes but lost at `0.9770x` (CI
`0.9609..0.9914`). The U64 exponent-bit stream reached `1.0068x` (CI
`1.0001..1.0191`) but missed the threshold and stationarity, so the default
keeps the former U128 bit scan. Final-source block-256 (`1.0183x`) and LTO
(`1.0083x`) likewise stayed below the promotion rule.

A further search checked the incumbent seed's complete
`+/-5,000,000` neighborhood and ten million uniformly sampled seeds. No valid
schedule below 124 products was found. Allowing PRAC rule 6 produced a
112-byte schedule with the same `119M+5S=124` cost; it reached only `1.0060x`
end-to-end with a parity-containing CI. Projective denominator-free Lucas
recurrences were also rejected by exact counts: they need about 383 products
per candidate, and common-denominator variants remain around 255 products per
candidate, versus roughly 130 plus one shared block inversion now.
Weighted 125-product schedules shortened the interpreter to 109--113 steps,
and a dedicated `0x03,0x83*40` prefix removed 41 dispatches, but their combined
full-solver result was only `1.0127x` (CI `0.9807..1.0418`) with failed
stationarity. Whole-schedule RLE was substantially slower because larger code
and helper calls introduced spills.

Stack-only cleanups were measured separately rather than assumed faster.
Removing the unused reciprocal numerator, shrinking the deferred-sqrt
`PreparedLift`, and combining both reduced the evaluator frame by 4,096,
6,160, and 10,256 bytes, but their paired results were `0.9996x`, `1.0051x`,
and `1.0033x`; none had a decisive CI. Branchless final REDC (`0.6702x` in its
primitive benchmark), a CIOS Montgomery kernel (about `0.694x`), manual Horner
unrolling, and forced inlining also lost or remained indistinguishable.
Four-lane scheduling sped up the isolated three-product trace by
`1.029--1.060x`, but trace plus the 124-product PRAC stayed within
`0.995--1.007x`. GCC flattening and specialized-square variants likewise made
the isolated trace `1.04--1.12x` faster while the full solver stayed at parity
or regressed, so the compact three-call GCC code remains the default.

The hybrid Jacobi kernel itself reduced a dedicated Jacobi microbenchmark from
`0.08616 s` for full U128 Euclidean reduction to `0.05543 s`; using the
Montgomery residue directly was another 2.7% faster than first converting to
canonical form. In a noisy complete no-subgroup-filter campaign, however, the
paired result was only `1.0013x` with CI `0.9699..1.0315`; it is retained as a
verified low-level simplification, not counted as an end-to-end win.

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
