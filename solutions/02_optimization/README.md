# Problem 2 optimization experiments

This directory contains the original scalar candidate matrix plus the later
GCC 13.3, source-order, SIMD, autotuning, split-width, code-generation, and
timing-stability experiments.  Every promoted or retained target candidate is
paired with an independent correctness oracle and an exact measured-binary
audit.  The benchmark drivers are designed to avoid common sources of
misleading results:

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

- `current_submission` (historical internal name): one state-writing helper in
  each of 20 iterations, preserving the pre-optimization submission structure.
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

| Candidate | Median ns / 20 rounds | MAD ns | vs pre-opt submission | vs register loop |
|---|---:|---:|---:|---:|
| `current_submission` (historical pre-opt name) | 41.894 | 2.834 | 1.000x | 0.970x |
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
arithmetic core.

## Adaptive cross-call inlining and second-wave review

The current source keeps the local noinline BMI2 helper under the supplied
plain `gcc -O3` command.  When compiled with global BMI2 enabled, its attribute
changes to `always_inline`; a larger inline threshold then carries the same
320-operation core through the public wrapper and into `main`'s timing loop:

```bash
gcc -O3 -Wall -Wextra -mbmi2 -finline-limit=2000 \
  -o contest submissions/02/contest.c
```

This is not a new permutation or a hard-coded output. It removes the repeated
call boundary, four callee-saved push/pop pairs, four state loads/stores, and
eight constant loads from the timed recurrence. The state and constants remain
in registers across outer calls. `-mbmi2` alone only merges the private core
into the public function and did not improve timing; the public-to-`main`
boundary must disappear as well.

Two 3,000,000-call campaigns used three discarded warm-up processes, 21
interleaved samples, CPU affinity, and the correctness gate before timing:

| CPU | default median | inline median | paired median | bootstrap 95% CI |
|---:|---:|---:|---:|---:|
| 0 | 44.467 ns | 39.859 ns | **1.116x** | 1.110--1.143x |
| 4 | 45.924 ns | 40.801 ns | **1.118x** | 1.095--1.140x |

The raw JSON is in [`inline_results_02.json`](inline_results_02.json) and
[`inline_results_02_cpu4.json`](inline_results_02_cpu4.json). A three-stage
default/`-mbmi2`/outer-inline ablation is in the older schema-2
[`inline_stages_results_02.json`](inline_stages_results_02.json). The two main
inline files are schema 3: they link each candidate to an independent verifier
and compare one and twenty rounds for 100,000 random states and random add/XOR
constants before timing. With `--audit-mode`, current schema 4 additionally
audits each named case's exact performance executable against its timed-loop
contract before warm-up. GCC 12 emitted
byte-identical binaries for inline limits 700 and 2000.
The digest-pinned GCC 13.3.0 reproduction now confirms the same equality for the
complete binaries and the fully inlined timing loop.

[`audit_inline_02.py`](audit_inline_02.py) makes the assembly check executable
rather than visual. Its saved
[`inline_assembly_audit_02.json`](inline_assembly_audit_02.json) reports a
1,216-byte, 322-instruction score loop containing exactly 80 each of `RORX`,
XOR, `BSWAP`, and ADD/LEA, with no call, push/pop, or state/constant memory
operand. Limits 700 and 2000 have the same normalized loop hash.

Explicit 32/64/128-byte alignment moved the inlined loop entry as requested but
measured paired 1.006x, 0.991x, and 0.990x, with every bootstrap interval
touching or crossing 1. The default 16-byte loop alignment is retained; raw
samples are in
[`inline_alignment_results_02.json`](inline_alignment_results_02.json).

The complete inline binary also rejected extra tuning: IRA priority measured
paired 1.016x (CI 0.951--1.038x), native tune 0.985x (0.946--1.010x), and their
combination 0.970x (0.958--1.014x). They changed the generated binaries but did
not beat the simpler score build. Raw samples are in
[`inline_codegen_results_02.json`](inline_codegen_results_02.json).

## Third-wave operation and backend search

The smaller portable forced-inline control replaced 80 non-destructive `RORX`
instructions with destructive `ROL`/`ROR`. It reduced complete text from 7,537
to 7,245 bytes and the timed loop from 1,216 to 1,060 bytes, but added a move and
measured paired **0.985x** (95% CI 0.958--1.002x). Smaller code therefore did
not beat BMI2; raw samples are in
[`inline_rol_results_02.json`](inline_rol_results_02.json).

[`analyze_transform_lower_bound_02.py`](analyze_transform_lower_bound_02.py)
checks two possible algebraic reductions. For the four actual transforms, the
identity `(x xor C)+A = (x+B) xor E` is already impossible in 5-, 3-, 10-, and
4-bit projections. A 64-bit identity would have to survive every such
projection. Folding XOR's top bit into ADD applies to two constants, but their
remaining XOR masks are nonzero, so no instruction disappears. The four
two-round linear bit permutations also match neither one rotate nor one
rotate/byte-swap composition. Exact fallback forms were slower: post-BSWAP XOR
0.980x, top-bit fold 0.983x, arithmetic-XOR 0.620x, and 32-bit halves 0.251x.
The deterministic result is saved in
[`transform_lower_bound_02.json`](transform_lower_bound_02.json).

A separate complete-binary screen compiled 120 GCC/link combinations and found
26 distinct hot-loop streams. LTO, whole-program, semantic-interposition, and
section-GC variants left the 1,216-byte loop byte-identical. An initial IRA
1.0217x result disappeared when loop offsets were controlled: four IRA layouts
measured 0.985--0.995x and every interval crossed 1. PGO and scheduler variants
also failed to win. `-mtune=alderlake` remains a judge-only A/B candidate: one
AMD codegen campaign measured 1.0148x (CI 1.0001--1.0207x), but the host is not
the 255H and the available Arrow-Lake LLVM model is only an Alder-Lake port
approximation. It is not part of the default score command.

## Exact GCC 13.3 and fourth-wave search

[`reproduce_gcc133_02.py`](reproduce_gcc133_02.py) runs the source in the
digest-pinned official `gcc:13.3.0` image, checks the unmodified complete binary,
then directly verifies every candidate on 100,000 random states and random
ADD/XOR constants. The saved
[`gcc133_codegen_results_02.json`](gcc133_codegen_results_02.json) records:

| GCC 13.3 build | text | timed loop | calls / memory | result |
|---|---:|---:|---:|---|
| default `-O3` | 5,972 B | 31 B / 6 insn | 1 / 0 | compatibility path |
| BMI2 inline 700 or 2000 | 7,246 B | 1,216 B / 322 insn | 0 / 0 | binaries identical |
| above + `-mtune=alderlake` | 7,246 B | 1,216 B / 322 insn | 0 / 0 | different schedule |
| above + Alder tune + IRA priority | 7,199 B | 1,210 B / 322 insn | 0 / 0 | third schedule |

All six correctness-smoke candidates passed the supplied vectors and the direct
100,000-case 1/20-round gate. GCC 13.3 gives `alderlake`, `raptorlake`, and
`meteorlake` the same complete binary for this source, while `-mtune=arrowlake`
is not supported by this release. Keeping the documented name `alderlake` is
therefore sufficient.

A 34-configuration GCC 13.3 scheduler/allocator screen produced 32 valid builds
and eight distinct loop streams. It is reproduced by
[`screen_gcc133_schedules_02.py`](screen_gcc133_schedules_02.py), with all flags,
hashes and static metrics in
[`gcc133_schedule_screen_02.json`](gcc133_schedule_screen_02.json). LLVM-MCA
16's Alder/Raptor/Meteor models
predicted 125.06 cycles for generic, 123.62 for Alder tune, and 121.06 for Alder
tune plus IRA priority; all have the same 320 core operations. These are only
approximate port/latency screens, not measurements of Lion Cove or Skymont.
Digest-pinned GCC 13.3 confirmation on the available AMD host compared the last
two builds with 5,000,000 calls, six discarded warmups, and 40 samples:

| affinity | Alder / Alder+IRA paired median | bootstrap 95% CI |
|---:|---:|---:|
| CPU 0 | 1.011x | 1.001--1.015x |
| CPU 4 | 1.008x | 0.998--1.025x |

The inconsistent intervals and wrong microarchitecture prevent promotion, but
the distinct 1,210-byte code stream is retained as a high-priority target-only
candidate. The schema-4 raw samples and exact measured-binary audits are
[`gcc133_schedule_results_02_cpu0.json`](gcc133_schedule_results_02_cpu0.json)
and [`gcc133_schedule_results_02_cpu4.json`](gcc133_schedule_results_02_cpu4.json).

```bash
python3 solutions/02_optimization/screen_gcc133_schedules_02.py \
  --json /tmp/challenge02-gcc133-schedule-screen.json
```

The constant/coordinate axis was also closed more tightly. Moving XOR after
BSWAP or before rotate is an exact identity for arbitrary state and constants;
100,000-case direct tests passed. Fresh schema-4, 24-sample campaigns on CPU
0/4 measured post-BSWAP at 0.959x/0.963x and pre-rotate at 0.965x/0.960x; all
four 95% intervals stayed below 1. Both alternatives still contain 320 core
operations. Forcing constants into memory creates 160 hot memory operands and
grows the loop from 1,216 to 2,015 bytes. Two 21-sample campaigns measured
0.979x (CI 0.964--0.992x) and 0.988x (0.969--1.002x), so it also has no winning
evidence. Raw exact-binary runs are in
[`constant_reordering_results_02_cpu0.json`](constant_reordering_results_02_cpu0.json),
[`constant_reordering_results_02_cpu4.json`](constant_reordering_results_02_cpu4.json),
[`constant_memory_results_02_cpu0.json`](constant_memory_results_02_cpu0.json),
and [`constant_memory_results_02_cpu4.json`](constant_memory_results_02_cpu4.json).
Literal specialization fails the random-constant contract and does not reduce the core.
[`analyze_constant_placement_02.py`](analyze_constant_placement_02.py) proves for
the supplied constants that the original, byte-swapped, inverse-rotated, and
top-bit-folded masks all miss x86-64's sign-extended `imm32` form and that no
remaining XOR is `{0,2^63}`. Its deterministic output is
[`constant_placement_analysis_02.json`](constant_placement_analysis_02.json).
The same script can emit byte-identical copies of the three measured controls:

```bash
python3 solutions/02_optimization/analyze_constant_placement_02.py \
  --json /tmp/ch2-constants/analysis.json \
  --emit-dir /tmp/ch2-constants/candidates

python3 solutions/benchmark_02_permutation.py \
  --case baseline=submissions/02/contest.c \
  --case post_bswap=/tmp/ch2-constants/candidates/post_bswap.c \
  --case pre_rotate=/tmp/ch2-constants/candidates/pre_rotate.c \
  --baseline baseline --extra-cflag=-mbmi2 \
  --extra-cflag=-finline-limit=2000 \
  --audit-mode baseline=full-inline-320 \
  --audit-mode post_bswap=full-inline-320 \
  --audit-mode pre_rotate=full-inline-320 \
  --cpu 0 --iterations 3000000 --warmups 3 --samples 24 \
  --random-cases 100000 --json /tmp/ch2-constants/reordering.json
```

## Fifth-wave source ordering and backend layout screen

The four assignments in one two-round macro are independent, so their C source
order may be permuted without changing the function.  The digest-pinned GCC
13.3 screen in
[`screen_gcc133_source_orders_02.py`](screen_gcc133_source_orders_02.py)
compiled all 24 orders under generic, Alder, and Alder+IRA profiles.  Order
`2,1,0,3`, retained as
[`contest_source_order_2103.c`](contest_source_order_2103.c), was the unique
static winner for generic and Alder code generation:

| GCC 13.3 profile | original order | order `2,1,0,3` |
|---|---:|---:|
| generic | 125.06 cycles | **121.06 cycles** |
| `-mtune=alderlake` | 123.62 cycles | **121.06 cycles** |
| Alder + IRA priority | 121.06 cycles | 121.06 cycles |

The generic/Alder loop shrank from 1,216 to 1,211 bytes while retaining 322
instructions and all 320 core operations.  All three top-profile binaries had
no call, push/pop, spill, or hot memory operand and passed the neutral verifier
on 100,000 random states and random constants at one and twenty rounds.  Local
state/constant declaration permutations were byte-identical controls.  Full
hashes, rankings, exact audits, and the pinned image digest are in
[`gcc133_source_order_results_02.json`](gcc133_source_order_results_02.json).

A separate
[`screen_gcc133_layout_02.py`](screen_gcc133_layout_02.py) run compiled and
audited 106 stable GCC/link flag candidates, yielding nine distinct loop
streams.  Its shortlist plus three source-order cross-products all passed the
supplied vectors and the same 100,000-case direct gate.  On LLVM-MCA 16's
approximate Alder model, the strongest new streams were:

| Alder+IRA extension | estimated cycles | loop effect |
|---|---:|---|
| incumbent | 121.06 | 1,210 B, 322 insn |
| `-fselective-scheduling2` | **120.06** | distinct stream |
| `-fno-schedule-insns2` | **120.07** | distinct stream |
| `-fno-sched-critical-path-heuristic` | 120.14 | distinct stream |
| `-falign-loops=64` / `-flto` | 121.06 | same stream, different placement |

Combining order `2,1,0,3` with the first two flags produced the same
120.06/120.07 estimates, so the static improvements do not stack.  Diagnostic
AMD measurements disagreed by CPU and selective scheduling was slower there;
neither fact predicts Lion Cove or Skymont.  The complete structured evidence
is [`gcc133_layout_screen_02.json`](gcc133_layout_screen_02.json).  These
variants are screen/confirm candidates only; the incumbent source and score
command remain unchanged until two independent 255H sessions pass the guarded
decision rule.  This use of LLVM-MCA follows its role as a scheduling-model
diagnostic, whose accuracy is limited by the model rather than a hardware
measurement ([official LLVM guide](https://llvm.org/docs/CommandGuide/llvm-mca.html)).

```bash
python3 solutions/02_optimization/screen_gcc133_source_orders_02.py \
  --json /tmp/challenge02-gcc133-source-orders.json
python3 solutions/02_optimization/screen_gcc133_layout_02.py \
  --json /tmp/challenge02-gcc133-layout.json
```

## Sixth-wave lane-wise AVX2 and negative algebraic search

The earlier SIMD candidates either put one state through a longer dependent
vector path or required four independent API calls.  The new
[`contest_simd_avx2_lanewise.c`](contest_simd_avx2_lanewise.c) instead uses the
two-round reversal cancellation directly: the four independent scalar chains
become four YMM lanes.  Ten unrolled two-round blocks each issue two lane-wise
rotates, XORs, byte shuffles, and additions.  Exact GCC 13.3 and host GCC 12
therefore emit 20 each of `VPSLLVQ`, `VPSRLVQ`, `VPOR`, `VPXOR`, `VPSHUFB`, and
`VPADDQ`, followed only by the outer `SUB/JNE` pair.

A twelve-variant constant-residency screen found one small but deterministic
code-generation improvement.  Passing the two forward constant vectors through
an inline, non-volatile tied-register identity makes GCC keep them outside the
timed loop.  The loop changes from 124 instructions, 587 bytes, and two hot
loads to **122 instructions, 579 bytes, and zero hot memory operands**.  A direct
CPU-2 current/final comparison was statistically tied at 1.0013x (paired 95%
CI 0.9983--1.0039), so this is a machine-code cleanup rather than a claimed
stand-alone timing win.

The final vector candidate was then compared with the scalar incumbent using
six discarded warm-up processes, 32 balanced samples, 3,000,000 calls per
sample, and the 100,000-case random-state/random-constant gate:

| AMD affinity | scalar median | AVX2 median | paired speedup | paired 95% CI |
|---:|---:|---:|---:|---:|
| CPU 1 | 46.927 ns | 36.690 ns | **1.275x** | 1.260--1.292x |
| CPU 2 | 34.354 ns | 36.569 ns | **0.940x** | 0.923--0.950x |
| CPU 3 | 45.938 ns | 36.724 ns | **1.248x** | 1.222--1.269x |

The CPU-2 reversal is important: three physical-core affinities on the same
reported AMD VM do not even agree on scalar versus AVX2 ordering.  This is
direct evidence that the VM's affinity/frequency environment cannot stand in
for a Core Ultra 7 255H measurement.
Earlier CPU-0/4 samples are retained only as same-physical-core diagnostics.
The exact raw campaigns are
[`avx2_confirm_02_cpu1.json`](avx2_confirm_02_cpu1.json) and
[`avx2_confirm_02_cpu3.json`](avx2_confirm_02_cpu3.json); the complete SIMD
screen, including the rejected SSE2 design and the direct current/final
ablation, is generated by [`screen_simd_02.py`](screen_simd_02.py) into
[`simd_results_02.json`](simd_results_02.json).  SSE2 needs a much larger
781-instruction loop and measured about 0.40x, so it is rejected.

Two independent negative searches bound what remains on the scalar path.
[`analyze_two_round_superopt_02.py`](analyze_two_round_superopt_02.py) models one
stage as `BSWAP64(ROL64(x,r) xor k)+a`.  Z3 proves every length-three template
over rotate/XOR/byte-swap/add unsatisfiable for each distinct stage, and all 32
ways to delete one operation from the four existing eight-operation pair chains
remain unsatisfiable even when constants are resynthesized.  An exhaustive
linear search enumerates 4,223 rotate/byte-swap syntaxes (632 distinct bit
permutations) of length at most three and finds no two-round skeleton.  These are
local lower bounds for the stated grammar, not a global proof over arbitrary
x86 programs.  The full witnesses and code-generation audit are in
[`two_round_superopt_results_02.json`](two_round_superopt_results_02.json).

[`screen_255h_toolchains_02.py`](screen_255h_toolchains_02.py) also tests 47
additional exact-GCC13 schedules and 53 Clang 21 target/scheduler combinations
without collecting host timing.  No GCC stream beats the existing 120.06-cycle
Alder proxy.  Clang's spill-free Arrow Lake `ilpmax`/`ilpmin` stream is 1,208
bytes but scores 133.79 on that same approximate model, and LLVM-MCA 16 has no
Lion Cove or Skymont model.  The 100-build audit, shortlist verification, target
name support, and model limits are preserved in
[`255h_toolchain_screen_02.json`](255h_toolchain_screen_02.json).  Consequently
the scalar source remains the incumbent, while the 122-instruction AVX2 source
is now the highest-priority target-only algorithmic candidate.

## Seventh-wave split SIMD, code generation, and timing diagnosis

The four-lane YMM design has one long vector dependency chain, so a final SIMD
experiment split it into two independent 128-bit groups.  Four layouts cover
contiguous lanes, reversal-orbit pairs, serialized live ranges, and explicit
lane recomputation.  All passed the exact GCC 13.3 audit, official vectors, and
100,000 random states with random constants.  None reached host timing:
[`screen_split_simd_02.py`](screen_split_simd_02.py) reports 242--288 timed-loop
instructions, 1,303--1,509 bytes, 30--50 hot memory operands, and
1.36--2.35 times the current YMM LLVM-MCA estimate.  The sources and complete
negative record are retained in the `contest_simd_avx2_split*.c` files and
[`split_simd_results_02.json`](split_simd_results_02.json), but are not added to
the 255H manifest.

[`screen_avx2_codegen_02.py`](screen_avx2_codegen_02.py) then screened exact GCC
13.3 and Clang 21 target, scheduler, register-allocation, alignment, and source
expression variants.  Of 113 attempted builds, 100 passed the exact complete
loop audit; 14 Pareto/source controls also passed the 100,000-case direct gate.
GCC's `-fira-region=one` only shortened the loop from 579 to 569 bytes while
leaving 122 instructions and both static cycle estimates unchanged.  Clang
made a 548-byte loop with the same instruction count and estimates, but the
judge compiler is GCC 13.3.  Replacing rotate's `VPOR` with `VPXOR` is exact
because the complementary shifts have disjoint set-bit positions; GCC and
Clang both verified it, yet it merely changed 20 `VPOR` to `VPXOR` with no
byte, instruction, memory, or model-cycle improvement.  A first attempt to pin
all live YMM registers did reduce encoding size to 563 bytes, but GCC inserted
one constant reload and one reverse-permute per iteration, producing 124
instructions and one hot memory operand.  It passed the same direct correctness
gate but failed the performance audit.  No source rewrite from this screen was
promoted; all code-generation evidence is in
[`avx2_codegen_screen_02.json`](avx2_codegen_screen_02.json).

A source-only attempt to force immediate `RORX` through inline assembly also
passed 100,000 random cases, but the supplied default GCC command still left a
public wrapper call (25-byte, eight-instruction timed loop).  Raising the inline
limit was still necessary, so duplicating the source around inline assembly did
not replace the existing score flags.

Finally, [`benchmark_timing_stability_02.py`](benchmark_timing_stability_02.py)
and its page-aligned C helper separate process layout and timer effects from the
CPU-2 reversal.  A fresh process-isolated run measured scalar/AVX2 speedup
0.8768x (95% CI 0.859--0.891); the same-process AB/BA control measured 0.9225x
(0.8845--0.9290).  Wall time, thread CPU time, and invariant-TSC ratios agreed
within 0.000003 and no migration or `TSC_AUX` change occurred.  Across CPUs
1/2/3 the exact binaries and normalized loops are identical; AVX2 medians vary
only 0.78%, while scalar medians vary 45.89%.  This localizes the sign reversal
to shared-host scalar throughput rather than source or timer choice.  SMT
sibling load is correlated with the result, but unavailable APERF/MPERF,
cpufreq, and performance counters prevent a causal frequency/SMT conclusion.
The full 32-sample, six-warm-up record is
[`timing_stability_results_02.json`](timing_stability_results_02.json) and is
explicitly not evidence about the 255H.

## Eighth-wave register allocation, phase staggering, and target model

The fixed-register failure suggested that the useful idea was compact low
register encoding, not wholesale pinning.  A bounded ten-variant search in
[`screen_avx2_inline_asm_alloc_02.py`](screen_avx2_inline_asm_alloc_02.py)
tested allocator-chosen operands, partial pinning, one/two scratch registers,
and encoding-aware low/high layouts under exact GCC 13.3.  Pinning only the
changing state to `ymm0`, using one destructive shift plus one scratch, and
leaving all constants to GCC produced a strict static winner:

| exact timed loop | instructions | bytes | hot memory | Alder/Zen proxy |
|---|---:|---:|---:|---:|
| current lane-wise AVX2 | 122 | 579 | 0 | 100.03 / 180.03 |
| single-scratch inline assembly | 122 | **569** | 0 | 100.03 / 180.03 |

The generated stream differs from the 569-byte `-fira-region=one` stream even
though their aggregate metrics tie.  The retained
[`contest_simd_avx2_inline_asm.c`](contest_simd_avx2_inline_asm.c) passes the
supplied default build, all official vectors, and 100,000 random states and
random constants at one and twenty rounds.  Eight other assembly allocations
were rejected at 124 instructions with one or two hot loads.  Full data and
source hashes are in
[`avx2_inline_asm_alloc_results_02.json`](avx2_inline_asm_alloc_results_02.json).

Two AMD/GCC 12 campaigns then compared the current YMM loop, the 569-byte
source, and a new phase-staggered construction.  Each used six discarded
warm-ups, 32 balanced samples, 3,000,000 calls per sample, direct 100,000-case
verification, and exact measured-binary audits:

| affinity | inline-asm speedup, current/asm (95% CI) | phase speedup, current/phase (95% CI) |
|---|---:|---:|
| CPU 1 | 0.999x (0.998--1.002) | 0.758x (0.754--0.764) |
| CPU 3 | 1.000x (0.998--1.002) | 0.756x (0.751--0.764) |

Thus the smaller inline-assembly stream is a statistical tie on this host, not
a local promotion.  The phase construction packs `[x0,T3(x3)]` and
`[x1,T2(x2)]`, applies 19 shared immediate-rotate stages, and finishes one lane
per orbit.  It is algebraically exact and memory-free, but duplicates the
stream to 257 instructions/1,253 bytes.  LLVM-MCA predicted 116.04 cycles on
the Alder proxy and a favorable 143.05 versus 180.03 on the Zen 2 proxy; the
two real AMD campaigns decisively contradicted the latter.  The source and
negative record remain in
[`contest_simd_avx2_phase_staggered.c`](contest_simd_avx2_phase_staggered.c) and
[`phase_staggered_results_02.json`](phase_staggered_results_02.json), but the
candidate is not registered for 255H promotion.  Raw timing is in
[`eighth_wave_timing_02_cpu1.json`](eighth_wave_timing_02_cpu1.json) and
[`eighth_wave_timing_02_cpu3.json`](eighth_wave_timing_02_cpu3.json).
The first staging attempt also exposed that a copied candidate with a quoted
relative include lost its original source-directory context.  The shared
benchmark driver now adds that directory with `-iquote` to both verifier-object
and performance builds, records the context flags in schema 4, and the two raw
campaigns above were rerun through the corrected path.

An independent 65-case exact-GCC13 AVX backend screen covered preferred vector
width, split loads/stores, VEX/vzeroupper controls, move/store width caps, cost
models, and partial/AVX tuning controls.  All 65 loops passed audit and reduced
to only the two already-known generic/Alder normalized streams, both 122
instructions, 579 bytes, and 100.03/180.03 proxy cycles.  Loop placement was
not equivalent, however: `(stream hash, start mod 64)` yields eight classes
(generic offsets 0/8/24/40/48 and Alder offsets 8/16/48).  One representative
of every class passed the 100,000-case gate.  LLVM-MCA cannot see this frontend
layout effect; an earlier explicit-alignment AMD sweep found no significant
winner, while offsets 24/40/48 and every 255H core type remain unmeasured.
Seven nonbaseline layout representatives are therefore target-only manifest
candidates rather than local promotions.  See
[`gcc133_avx_flags_results_02.json`](gcc133_avx_flags_results_02.json).

Finally,
[`analyze_255h_instruction_model_02.py`](analyze_255h_instruction_model_02.py)
reproduces an instruction-level sensitivity model from Intel's official
Skymont and Crestmont packages.  Their selected AVX2 rows give the 20-round YMM
dependency chain a 100-cycle latency path.  The Skymont download is named Xeon
6 E-core, so transferring it to the client 255H remains conditional.  The
scalar 80-cycle scenario is also conditional because the tables omit the exact
`RORX r64` and six `LEA` rows.  In addition, two official Intel pages conflict:
Arrow Lake PerfMon labels LP-E as Crestmont, while Intel's 255H-specific ECI
page calls its two LP-E cores additional Skymont cores.  The Crestmont result is
therefore only a PerfMon-mapping sensitivity case.  No Lion Cove
per-instruction table appeared in the Intel catalog pinned on 2026-07-23.
Isolated throughput rows also omit mixed-port, frontend, frequency, and
whole-loop effects.  The hashes, exact selected rows, source conflict, topology
inference, and structured gaps are recorded in
[`instruction_model_255h_02.json`](instruction_model_255h_02.json); the model
therefore does not choose a winner.  The two distinct 569-byte candidates and
seven nonbaseline AVX2 stream/alignment representatives are in the target-only
manifest.  Its fresh 28-case integration smoke passed 28/28 direct checks and
28/28 measured-binary audits.

## Core-aware 255H decision tool

[`autotune_02_255h.py`](autotune_02_255h.py) and
[`autotune_02_candidates.json`](autotune_02_candidates.json) turn the remaining
target measurement into a guarded workflow:

```bash
python3 solutions/02_optimization/autotune_02_255h.py probe \
  --compiler /path/to/gcc-13.3.0 --out /tmp/ch2-255h/topology.json

python3 solutions/02_optimization/autotune_02_255h.py screen \
  --topology /tmp/ch2-255h/topology.json --session screen-a \
  --out-dir /tmp/ch2-255h/screen-a

python3 solutions/02_optimization/autotune_02_255h.py confirm \
  --screen /tmp/ch2-255h/screen-a/index.json \
  --compiler /path/to/gcc-13.3.0 --session confirm-a \
  --out-dir /tmp/ch2-255h/confirm-a

# Run this in a genuinely separate time window.
python3 solutions/02_optimization/autotune_02_255h.py confirm \
  --screen /tmp/ch2-255h/screen-a/index.json \
  --compiler /path/to/gcc-13.3.0 --session confirm-b \
  --out-dir /tmp/ch2-255h/confirm-b

python3 solutions/02_optimization/autotune_02_255h.py decide \
  --screen /tmp/ch2-255h/screen-a/index.json \
  --confirm /tmp/ch2-255h/confirm-a/index.json \
  --confirm /tmp/ch2-255h/confirm-b/index.json \
  --out /tmp/ch2-255h/decision.json
```

`probe` pins a CPUID helper to every allowed CPU. It distinguishes P from Atom
cores directly and labels the two LP-E cores only when at least two independent
topology/frequency/capacity signals agree; ambiguity remains provisional.
`screen` is candidate reduction only. `confirm` runs incumbent/candidate pairs
on two physical representatives of each requested core type, and `decide`
requires two distinct sessions, exact compiler/source/manifest hashes,
correctness and measured-binary assembly gates. A replacement needs paired
median `>= 1.010` and adjusted lower bound `> 1.005` on every P campaign without
regressing E/LP-E safety. Missing topology, sessions, or artifacts can never
silently select a flag. If more than one candidate qualifies, `decide` keeps the
incumbent and requests a direct head-to-head instead of choosing arbitrarily.
It also rejects a renamed session that reuses the same benchmark path or SHA-256,
so two labels cannot masquerade as two independent sessions. Every run also has
a fresh 128-bit campaign id in both index and benchmark JSON. Canonical evidence
and paired-sample hashes catch a copied result even if its JSON whitespace,
filename, or nonce is changed.

Each index and schema-4 benchmark now carries one canonical measurement-protocol
fingerprint: the autotuner and benchmark drivers, timed-loop audit, independent
oracle and candidate verifier, official problem archive, Python executable, and
the actual `objdump`/`size` binaries are all SHA-256 pinned. `confirm` refuses a stale `screen`, and `decide` refuses
sessions made by different or since-modified protocol code; `screen` likewise
requires a probe from the current protocol. The correctness
record must explicitly cover random states and random ADD/XOR constants at both
one and twenty rounds; the runner parses the verifier's exact count, seed, round,
constant, and PASS lines. The reference verifier translation unit is compiled
once with fixed neutral flags, candidate flags touch only the candidate object
and final link, and any verifier-only candidate override is ineligible. Source
bytes are snapshotted once and both original and rewritten-performance hashes
are retained, closing a hash/compile time-of-check gap.
Nested topology records are also validated down to every cache-list element;
malformed input exits with a scoped user error rather than a traceback.

An initial eight-case end-to-end integration screen found one manifest-only error:
the non-eligible `portable_rol` control declared `portable-inline-320` without
the `-finline-limit=2000` needed to inline it. The manifest now carries that
flag; the smoke screen then produced the expected 1,060-byte/323-instruction
portable loop and all eight exact-binary audits passed.  After adding the fifth-wave
source/backend candidates, a balanced 15-case integration screen passed all 15
direct verifications and all 15 exact-binary audits.  Its 1,000-call timings
are only tool regression tests, not performance evidence.  Two deliberately
undersized confirmation sessions on AMD/GCC 12 also left `inline_2000` selected
and enumerated every missing 255H/GCC13/sample/warm-up/random-case gate.
After the partial-unroll controls and lane-wise AVX2 candidate were added, a
balanced 19-case smoke passed 19/19 direct verifications and measured-binary
audits.  Adding the distinct `-fira-region=one` and single-scratch 569-byte
streams produced a 21-case smoke that passed 21/21 checks and audits.  The
seven nonbaseline stream/alignment representatives then expanded the current
manifest to **28 cases**; a fresh balanced smoke passed 28/28 direct checks and
28/28 audits, with source-local `-iquote` context recorded for all 28.  This
provisional AMD/GCC12 run used 1,000 calls only and is integration evidence,
not performance evidence.

The same fast flags were also applied to full unroll, pair loop, and
`unroll5_bmi2`; medians were 37.279, 38.618, and 38.727 ns, respectively. Full
unroll therefore stays ahead after the call-boundary gain. Further alternatives
were correctness-tested but rejected: BSWAP/XOR commutation had the same
instruction count and a layout-sensitive false win; conjugacy-based two-lane
SIMD measured about 0.845x; byte tables failed mixed-derivative separability
checks; manual assembly/compiler scheduling did not produce a portable stable
gain. [`analyze_table_decomposition_02.py`](analyze_table_decomposition_02.py)
reproduces the influence, mixed-derivative, and restricted-ANF evidence.

```bash
python3 solutions/02_optimization/analyze_table_decomposition_02.py
```

The repeated comparison can be reproduced without duplicating the source:

```bash
python3 solutions/benchmark_02_permutation.py \
  --case default=submissions/02/contest.c \
  --case inline=submissions/02/contest.c --baseline default \
  --case-cflag inline=-mbmi2 \
  --case-cflag inline=-finline-limit=2000 \
  --audit-mode default=default-call-allowed \
  --audit-mode inline=full-inline-320 \
  --cpu auto --iterations 3000000 --warmups 3 --samples 21 \
  --random-cases 100000 --json /tmp/challenge02-inline.json
```

The eighth-wave three-way campaign uses the same driver with six discarded
warm-ups and 32 balanced samples. Change `--cpu 1` to `--cpu 3` for the second
stored affinity:

```bash
python3 solutions/benchmark_02_permutation.py \
  --case current=solutions/02_optimization/contest_simd_avx2_lanewise.c \
  --case inline_asm=solutions/02_optimization/contest_simd_avx2_inline_asm.c \
  --case phase=solutions/02_optimization/contest_simd_avx2_phase_staggered.c \
  --baseline current \
  --case-cflag current=-mavx2 \
  --case-cflag current=-DCH2_SIMD_INLINE \
  --case-cflag current=-finline-limit=2000 \
  --case-cflag inline_asm=-mavx2 \
  --case-cflag inline_asm=-DCH2_SIMD_INLINE \
  --case-cflag inline_asm=-finline-limit=2000 \
  --case-cflag phase=-mavx2 --case-cflag phase=-mbmi2 \
  --case-cflag phase=-DCH2_SIMD_INLINE \
  --case-cflag phase=-finline-limit=2000 \
  --audit-mode current=avx2-inline-lanewise \
  --audit-mode inline_asm=avx2-inline-lanewise \
  --audit-mode phase=report-only \
  --cpu 1 --iterations 3000000 --warmups 6 --samples 32 \
  --random-cases 100000 --json /tmp/challenge02-eighth-cpu1.json
```

## Recommendation and constraint compliance

`recommended_submission_fragment.c` is the strongest scalar candidate. It
uses no fixed input or output, only the fixed recovered permutation parameters,
and obeys the statement's edit policy by adding an external helper and invoking
it from the permitted 20-round-loop location. The `r = 19` assignment exits the
supplied redundant loop after the helper has computed all 20 rounds. The same
file supports both the default compatibility build and the faster adaptive
inline build.

Do not choose the final submission solely from AMD measurements or LLVM-MCA.
The exact GCC 13.3 call-removal and 700/2000 equality are already established;
what remains unknown is the performance ordering on Core Ultra 7 255H. Use the
core-aware tool to A/B `-mtune=alderlake`, its IRA-priority combination,
source order `2,1,0,3`, the selective/no-post-reload scheduler streams, and the
two distinct 569-byte AVX2 streams and seven nonbaseline stream/alignment
representatives, plus the diagnostic native tune. Keep a
source/flag only if it passes two independent sessions
and every required P/E/LP-E gate. Until then, the simpler
`-mbmi2 -finline-limit=2000` build remains the score recommendation. The direct
one-state and conjugate SIMD implementations should not be used because their
longer dependent paths were consistently slower.  The new four-lane two-round
AVX2 implementation is different and belongs in the 255H head-to-head, but the
contradictory CPU-1/2/3 ordering prevents promotion from this VM alone.  The
single-scratch source also remains target-only because both new AMD campaigns
were statistical ties.
