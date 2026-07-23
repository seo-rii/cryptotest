# Challenge 2 submission

Files:

- `contest.c`: final two-round-composed BMI2 implementation using the provided harness
- `run_contest.sh`: clean-checkout score build using the statement-permitted flags and vectors in the original problem ZIP
- `report.pdf`: required analysis, implementation, verification, and benchmark report
- `report.tex`: reproducible source for the PDF

From the repository root, the wrapper extracts the two provided vectors from the
tracked original ZIP into a temporary directory, builds there, runs both official
checks, and removes the generated files:

```bash
./submissions/02/run_contest.sh
```

The wrapper deliberately leaves neither the 154 KB vector file nor a generated
binary in the repository. A compatibility compile without the optional score
flags remains available with `gcc -O3 -Wall -Wextra submissions/02/contest.c`;
executing that binary directly requires the two official vectors in its working
directory.

The source is adaptive. Without global BMI2 it retains the local noinline BMI2
helper. With `-mbmi2`, that helper becomes `always_inline`; the larger inline
limit also carries the public wrapper into `main`'s timing loop. This removes
the repeated call/prologue and keeps four state words plus eight constants in
registers across timed calls without changing the permutation or hard-coding a
benchmark value.

The wrapper changes only the build flags and temporary location; it does not
modify the official test vectors, archive, harness I/O, or permutation. The
source itself remains compatible with the supplied plain `gcc -O3` command.

The repository-level reproducible reference comparison is:

```bash
python3 solutions/benchmark_02_permutation.py \
  --case default=submissions/02/contest.c \
  --case inline=submissions/02/contest.c --baseline default \
  --case-cflag inline=-mbmi2 \
  --case-cflag inline=-finline-limit=2000 \
  --audit-mode default=default-call-allowed \
  --audit-mode inline=full-inline-320 \
  --cpu auto --iterations 3000000 \
  --warmups 3 --samples 21 --random-cases 100000 \
  --json /tmp/challenge02-inline.json
```

The benchmark can compile the same source with different case-specific flags,
discards warm-up processes, interleaves measured runs, and reports raw samples,
median/MAD/percentiles, bootstrap intervals, and paired speedup. Before timing,
it links every candidate to an independent verifier and checks one and twenty
rounds on 100,000 random states and random add/XOR constants. Two refreshed
3,000,000-call campaigns measured paired medians **1.116x** and **1.118x**, with
bootstrap 95% intervals 1.110--1.143x and 1.095--1.140x. Raw results are
[`../../solutions/02_optimization/inline_results_02.json`](../../solutions/02_optimization/inline_results_02.json)
and
[`../../solutions/02_optimization/inline_results_02_cpu4.json`](../../solutions/02_optimization/inline_results_02_cpu4.json).

The deeper 18-candidate algorithm/frontend/cache review is in
[`../../solutions/02_optimization/deep_review_02.md`](../../solutions/02_optimization/deep_review_02.md).
It found no repeatable replacement for the submitted 1,267-byte full-unroll
arithmetic core. A 715-byte partial-unroll candidate won one early paired
session but lost later runs and was about 3.5% slower under the fast inline
flags. Conjugate SIMD, table decomposition, BSWAP/XOR rescheduling, manual
assembly, and compiler-pass variants are documented there as rejected
alternatives. Explicit 32/64/128-byte hot-loop alignment also failed to improve
the default; its raw samples are in
[`../../solutions/02_optimization/inline_alignment_results_02.json`](../../solutions/02_optimization/inline_alignment_results_02.json).
IRA-priority/native-tune complete-binary controls also had intervals crossing
1; their raw samples are in
[`../../solutions/02_optimization/inline_codegen_results_02.json`](../../solutions/02_optimization/inline_codegen_results_02.json).
The machine-audited score loop has 80 each of RORX/XOR/BSWAP/ADD-or-LEA and no
call, stack operation, or state/constant memory operand; the reproducible audit
is
[`../../solutions/02_optimization/inline_assembly_audit_02.json`](../../solutions/02_optimization/inline_assembly_audit_02.json).
A 292-byte-smaller portable ROL binary measured only 0.985x (CI 0.958--1.002x),
so BMI2 remains the score path.

The release check is now complete with the digest-pinned official GCC 13.3.0
image. Limits 700 and 2000 produce byte-identical complete binaries; each has a
1,216-byte, 322-instruction timed loop with no call, stack operation, or memory
operand. `-mtune=alderlake` changes the schedule, and adding IRA priority changes
it again to a 1,210-byte loop, so both are real 255H A/B candidates rather than
aliases. Neither is promoted without target measurements. Reproduce the exact
compiler/correctness/assembly checks with:

```bash
python3 solutions/02_optimization/reproduce_gcc133_02.py \
  --json /tmp/challenge02-gcc133.json
```

The structured result is
[`../../solutions/02_optimization/gcc133_codegen_results_02.json`](../../solutions/02_optimization/gcc133_codegen_results_02.json).
The 34-build static schedule matrix is reproducible with
[`screen_gcc133_schedules_02.py`](../../solutions/02_optimization/screen_gcc133_schedules_02.py),
and its [structured output](../../solutions/02_optimization/gcc133_schedule_screen_02.json)
plus [CPU 0](../../solutions/02_optimization/gcc133_schedule_results_02_cpu0.json)
and [CPU 4](../../solutions/02_optimization/gcc133_schedule_results_02_cpu4.json)
raw confirmation runs are retained. Exact constant-reordering controls can be
emitted by
[`analyze_constant_placement_02.py`](../../solutions/02_optimization/analyze_constant_placement_02.py);
their historical schema-4 raw samples are linked from the deep review.

A fifth-wave exact-GCC13 screen added target-only candidates without changing
the incumbent.  All 24 orders of the four independent chain assignments were
compiled under three profiles.  Order `2,1,0,3` reduced the approximate
generic/Alder LLVM-MCA result from 125.06/123.62 to 121.06 cycles and passed the
100,000-case random-state/random-constant gate.  A separate 106-flag screen
found `-fselective-scheduling2` and `-fno-schedule-insns2` streams at
120.06/120.07 estimated cycles versus 121.06 for Alder+IRA.  All 109 builds
passed exact assembly audits, and all nine shortlisted controls passed the
direct correctness gate.  The reproducible source-order and layout evidence is
[`gcc133_source_order_results_02.json`](../../solutions/02_optimization/gcc133_source_order_results_02.json)
and
[`gcc133_layout_screen_02.json`](../../solutions/02_optimization/gcc133_layout_screen_02.json).
These are static filters, not 255H measurements; AMD diagnostics disagreed by
CPU, so none is promoted.

A sixth wave adds a structurally different target-only candidate.  After two
rounds the word reversal cancels, so
[`contest_simd_avx2_lanewise.c`](../../solutions/02_optimization/contest_simd_avx2_lanewise.c)
places the four independent chains in four YMM lanes.  A reproducible
12-variant constant-residency screen reduced its exact GCC 13.3 timed loop from
124 instructions/587 bytes/two hot loads to **122 instructions/579 bytes/no hot
memory**.  The loop contains exactly 20 each of `VPSLLVQ`, `VPSRLVQ`, `VPOR`,
`VPXOR`, `VPSHUFB`, and `VPADDQ`, plus `SUB/JNE`.  The cleanup itself tied the
previous vector form at 1.0013x (paired 95% CI 0.9983--1.0039).

Against the scalar incumbent, two balanced AMD/GCC12 campaigns used six
discarded warm-ups, 32 samples, 3,000,000 calls per sample, and the direct
100,000-case random-state/random-constant gate.  CPU 1 measured 46.927/36.690 ns
and paired **1.275x** (CI 1.260--1.292); CPU 3 measured 45.938/36.724 ns and
paired **1.248x** (1.222--1.269).  In contrast, CPU 2 measured 34.354/36.569 ns
and paired **0.940x** (0.923--0.950), reversing the ordering.  The raw results are
[`avx2_confirm_02_cpu1.json`](../../solutions/02_optimization/avx2_confirm_02_cpu1.json)
and
[`avx2_confirm_02_cpu3.json`](../../solutions/02_optimization/avx2_confirm_02_cpu3.json).
Together they make AVX2 the leading 255H experiment, but not a submission
replacement: even this VM's physical affinities disagree, and its compiler and
microarchitecture differ from the judge.

The same pass also closed three alternatives.  A compact pair loop showed
1.035x in its first screen but only 1.0004x (CI 0.9855--1.0176) in a larger
confirmation.  Z3 and exhaustive bit-permutation searches found no shorter
two-round scalar expression in the stated rotate/XOR/byte-swap/add grammar.
Finally, 47 extra exact-GCC13 and 53 Clang 21 target/scheduler combinations
produced no stream better than the existing static proxy.  Reproduction and
scope limits are in the
[`SIMD screen`](../../solutions/02_optimization/simd_results_02.json),
[`superoptimization result`](../../solutions/02_optimization/two_round_superopt_results_02.json),
and [`toolchain screen`](../../solutions/02_optimization/255h_toolchain_screen_02.json).

A seventh pass tested the remaining split-width and measurement hypotheses.
Four two-XMM implementations passed the exact GCC 13.3 and 100,000-case gates,
but emitted 242--288 instructions, 30--50 hot memory operands, and at least
1.36x the current YMM static cycle estimate, so host timing and manifest
registration were skipped. A separate 113-build GCC/Clang screen found no GCC
source rewrite with fewer instructions or model cycles. The exact OR-to-XOR
rotate merge passed 100,000 cases under both compilers but only exchanged
mnemonics. Fully pinning the YMM allocation shortened encodings to 563 bytes,
but introduced two instructions and one hot reload, so it was also rejected.
Records are in
[`split_simd_results_02.json`](../../solutions/02_optimization/split_simd_results_02.json)
and
[`avx2_codegen_screen_02.json`](../../solutions/02_optimization/avx2_codegen_screen_02.json).

The CPU-affinity reversal was also reproduced with page-aligned same-process
AB/BA runners and wall, thread-CPU, and serialized-TSC timers. The three timer
ratios agreed within 0.000003, with no migration. Across CPU 1/2/3 the exact
binaries were identical and AVX2 medians varied only 0.78%, while scalar medians
varied 45.89%. This confirms that the AMD VM cannot select the 255H winner; the
raw diagnosis is
[`timing_stability_results_02.json`](../../solutions/02_optimization/timing_stability_results_02.json).

An eighth pass found a narrower register-allocation result. A bounded ten-case
inline-assembly screen pins only the changing value to `ymm0`, uses one scratch
for each rotate, and lets GCC allocate all constants. Exact GCC 13.3 emits
**122 instructions, 569 bytes, and no hot memory**, versus 122/579/0 for the
current YMM source. It is a distinct normalized stream from the equally sized
`-fira-region=one` result. The retained source passes the supplied default GCC
build, official vectors, and 100,000 random states/constants at one and twenty
rounds. See
[`avx2_inline_asm_alloc_results_02.json`](../../solutions/02_optimization/avx2_inline_asm_alloc_results_02.json).

Two six-warm-up, 32-sample, 3,000,000-call AMD campaigns did not turn the static
size win into a measured win: the new source's paired speedup was 0.999x
(95% CI 0.998--1.002) on CPU 1 and 1.000x (0.998--1.002) on CPU 3. A separate
phase-staggered two-XMM algorithm was exact and memory-free but expanded to 257
instructions/1,253 bytes; it measured only 0.758x and 0.756x, contradicting a
favorable Zen 2 LLVM-MCA proxy. Its negative record is
[`phase_staggered_results_02.json`](../../solutions/02_optimization/phase_staggered_results_02.json),
with raw campaigns in
[`eighth_wave_timing_02_cpu1.json`](../../solutions/02_optimization/eighth_wave_timing_02_cpu1.json)
and
[`eighth_wave_timing_02_cpu3.json`](../../solutions/02_optimization/eighth_wave_timing_02_cpu3.json).
Those runs use the hardened benchmark staging path, which preserves each
original source directory with `-iquote` so quoted relative includes retain
their meaning after the iteration-count rewrite.

Sixty-three additional GCC AVX backend flags plus two references all collapsed
to the two known normalized 122-instruction/579-byte streams. Their placement
was not identical: `(stream hash, loop-start mod 64)` gives eight classes at
generic offsets 0/8/24/40/48 and Alder offsets 8/16/48. One representative of
each class passed 100,000 random cases; the seven nonbaseline representatives
remain target-only because the static model cannot see frontend alignment.
Intel's official instruction packages give the AVX2 dependency chain a
conditional 100-cycle latency path, but the Skymont download is scoped as Xeon
6 E-core, the scalar comparison lacks exact `RORX64`/`LEA` rows, and no public
Lion Cove per-instruction table appeared in the Intel catalog pinned on
2026-07-23. Arrow Lake PerfMon also labels LP-E as Crestmont while Intel's
255H-specific ECI page calls the two LP-E cores additional Skymont cores, so
the Crestmont numbers are only a conditional sensitivity case. The reproducible records are
[`gcc133_avx_flags_results_02.json`](../../solutions/02_optimization/gcc133_avx_flags_results_02.json)
and
[`instruction_model_255h_02.json`](../../solutions/02_optimization/instruction_model_255h_02.json);
neither selects a 255H winner.

A ninth pass tightened both the candidate and the measurement contract.  The
benchmark had already verified candidates through their public one/twenty-round
functions and audited the measured assembly, but those checks did not prove
that timing `main` updated the state exactly the declared number of times.  A
deliberately halved timing loop passed both old gates and appeared **2.253x**
faster.  Schema 5 now computes an independent repeated-call final-state oracle
and requires every semantic preflight, warm-up, and measured process to report
that exact 256-bit state and iteration count.  It records the exact case set,
process counts, and canonical output hashes in a fail-closed JSON contract.
The halved loop, malformed iteration values, duplicated/missing output, and a
state/hash mismatch are permanent regressions.  Older schema-2--4 JSON remains
historical performance and assembly evidence, not evidence of this stronger
repeated-call property.

The same pass exploited commutativity in the VEX encoding.  Reversing the two
sources of `VPOR`, `VPXOR`, and `VPADDQ` keeps the dependency graph unchanged
but saves one byte on each of the twenty `VPOR` instructions.  Exact GCC 13.3
therefore emits **122 instructions, 549 bytes, and no hot memory**.  This reaches
the current `SUB`-counter lower bound of `20*27 + 3 + 6 = 549` bytes; the
target-only `use_incdec` control is 548 bytes.  A digest-pinned 34-case
flag/link screen passed all official vectors, 100,000 random states and random
constants at one/twenty rounds, and exact audits.  It collapsed to five
normalized streams and nine stream/alignment classes, all with unchanged
100.03/180.03 Alder/Zen-2 proxy cycles.  The reproducible source and result are
[`screen_avx2_commutative_layout_02.py`](../../solutions/02_optimization/screen_avx2_commutative_layout_02.py)
and
[`avx2_commutative_layout_results_02.json`](../../solutions/02_optimization/avx2_commutative_layout_results_02.json).

An independent algorithm screen explored the midpoint between a completely
unrolled vector loop and a tiny counted loop.  The retained block2 form handles
two round-pairs per body and repeats it five times.  Its static timed region is
only **136 bytes/30 instructions**; one call executes 133 modeled non-padding
instructions (134 including one alignment NOP) rather than the full-unroll's
122, has no hot memory, and retains the same modelled critical path.  Block1 is
75 bytes/18 static but 143 modeled non-padding instructions (144 with its NOP).
Block5 lowers that count to 131 (132 with its NOP) and Alder proxy
throughput from 22.2 to 21.8 cycles, but grows to 321 bytes/69 static
instructions; the slight model gain does not justify that footprint without
target evidence.  Exhausting all `24*24=576`
orders for the first two scalar stage-major chains produced no strict proxy
improvement below the tuned 120.06-cycle reference.  See
[`screen_avx2_pair_blocks_02.py`](../../solutions/02_optimization/screen_avx2_pair_blocks_02.py)
and
[`avx2_pair_block_results_02.json`](../../solutions/02_optimization/avx2_pair_block_results_02.json).

Finally, schema-5 campaigns compared the old 569-byte stream with the new
549-byte, 548-byte, aligned, and block2 candidates on CPU 1 and CPU 3.  Each
used six discarded warm-ups and 32 balanced samples of 3,000,000 calls, with
39 repeated-state-validated processes per candidate.  The 549-byte paired
medians were 1.000451x (95% CI 0.999294--1.001894) and 1.000466x
(0.998164--1.002395); block2 measured 0.999263x
(0.997061--1.001998) and 0.999278x (0.997635--1.002321).  Every new
candidate interval includes 1.  The footprint improvements are therefore
preserved as 255H target-only candidates while the scalar submission remains
the incumbent.  Raw campaigns are
[`ninth_wave_timing_02_cpu1.json`](../../solutions/02_optimization/ninth_wave_timing_02_cpu1.json)
and
[`ninth_wave_timing_02_cpu3.json`](../../solutions/02_optimization/ninth_wave_timing_02_cpu3.json).

These are historical schema-5 records from before the current protocol
fingerprint added total/average, child-CPU, and alternate-iteration checks, so a
new target confirmation must regenerate them with the current driver.

A tenth pass replaced the avoidable counted-loop frontend and exhaustively
screened quotient/remainder block sizes 1--10.  Three exact-GCC13 Pareto points
survived official vectors, 100,000 arbitrary-state/arbitrary-constant cases at
one/twenty rounds, and complete measured-loop audits:

| candidate | static loop | modeled non-padding instructions / call |
|---|---:|---:|
| counted block 2 | **122 B / 29 instructions** | 133 |
| block 3 plus tail 1 | **238 B / 53 instructions** | 129 |
| counted block 5 | **292 B / 65 instructions** | 127 |

All have zero hot memory and retain the full stream's `100.03/180.03`
Alder/Zen-2 dependency proxies.  Counted block 2 is strictly smaller than the
old 136 B/30-static form; block 3 is smaller and dynamically lighter than the
old 321 B/69-static block 5; the new block 5 trades another 54 bytes for two
fewer dynamic control instructions.  x86 `LOOP`, blocks 4 and 6--10 are retained
only as negative/dominated records.  The reproducible evidence is
[`tenth_avx2_counted_frontends_results_02.json`](../../solutions/02_optimization/tenth_avx2_counted_frontends_results_02.json).

The companion code-generation screen found exact ties for three high-state,
low-scratch VEX allocations and the `VPADDQ` rotate merge.  Moving XOR onto the
right-shift branch improves only the Zen-2 proxy (`180.03 -> 160.03`), not
either Intel proxy.  Forced same-register `ROL` reduces the scalar loop to
322 instructions/1,052 bytes, but worsens the Intel proxy from the `RORX`
incumbent's `121.06 cycles/402 µops` to `138.13/482`; `SHLD` was rejected at
its `3.03`-cycle serial latency probe.  These are static diagnostics, not 255H
measurements.  See
[`tenth_codegen_results_02.json`](../../solutions/02_optimization/tenth_codegen_results_02.json)
and
[`tenth_codegen_scalar_rotate_results_02.json`](../../solutions/02_optimization/tenth_codegen_scalar_rotate_results_02.json).

Current schema 5 also has executable regressions for three concrete bypasses.
It rejects work moved after the end clock through timed-region/child-CPU
coverage, a known final state written after a shortened loop through a fresh
nonce/campaign/source-bound alternate iteration challenge, and a falsified
printed average through total/average consistency while deriving nanoseconds
from total elapsed time.  POSIX child CPU accounting is mandatory for eligible
runs.  These checks defend the demonstrated measurement contract; they are not
cryptographic attestation of every arbitrary C program.

The counted candidates were compared directly with full549 on CPU 1 and CPU 3
using 3,000,000 calls, six warm-ups, and 32 balanced samples.  The
`full549/scalar` controls were `1.061x (1.041--1.120)` and
`1.032x (1.021--1.057)`.  CPU 1's block-3
signal was `1.005x (1.001--1.014)`, but that campaign was nonstationary, the
signal was not reproduced on CPU 3 (`1.001x, 0.997--1.004`), and it is below
the 1% promotion threshold.  Every other counted candidate interval included
one.  The scalar incumbent is unchanged; all three are target-only. The
tenth-pass raw records are
[`tenth_wave_timing_02_cpu1.json`](../../solutions/02_optimization/tenth_wave_timing_02_cpu1.json)
and
[`tenth_wave_timing_02_cpu3.json`](../../solutions/02_optimization/tenth_wave_timing_02_cpu3.json).
They predate the stationarity field and its protocol hash and are now
historical schema-5 records.

The current schema-5 protocol adds a raw-recomputed, four-fixed-block
stationarity gate. It requires at least 16 samples; an `N`-case screen uses a
multiple of `4*N`, while a two-case confirmation uses at least 40 and a
multiple of eight. Absolute block-median spread above 5%, paired-effect spread
above 2%, or a paired effect crossing both `0.995` and `1.005` makes that pair
diagnostic-only. The block boundaries and practical thresholds are fixed
before observing the data. This is motivated by
[Barrett et al.](https://arxiv.org/abs/1602.00602) and
[Kalibera/Jones](https://doi.org/10.1145/2464157.2464160), but is neither a
PELT reproduction nor their full hierarchical model. The autotuner recomputes
the record independently from raw samples and excludes only the affected pair.

Fresh 24-sample AMD/GCC 12 records are
[`stationarity_gate_timing_02_cpu1.json`](../../solutions/02_optimization/stationarity_gate_timing_02_cpu1.json)
and
[`stationarity_gate_timing_02_cpu3.json`](../../solutions/02_optimization/stationarity_gate_timing_02_cpu3.json).
CPU 1's full549 absolute spread is 2.3157%, and all four AVX pairs are
eligible, but their paired medians are only `0.999624--1.002591x` and every
95% interval includes one. The scalar control alone is diagnostic-only at
9.0577% absolute spread. CPU 3 is wholly diagnostic-only: full549 drifts
8.2770%, every AVX pair-effect spread is at least 2.2451%, and all but old
block2 also show material sign instability. Neither affinity promotes
anything, so the scalar score command above is unchanged.

The last local ISA pass also produced no submission replacement.
[`screen_eleventh_isa_synthesis_02.py`](../../solutions/02_optimization/screen_eleventh_isa_synthesis_02.py)
found no three-instruction solution for `BSWAP64` plus the four non-byte
rotates in its scoped AVX2 shift/shuffle/bitwise grammar. This is not a global
x86 lower bound: the script exhaustively enumerates the one-instruction and
parallel two-unary-plus-combine shapes, then structurally excludes the other
three-operation DAG topologies. Three exact split-shuffle controls pass the official vectors,
complete audits, and 100,000 arbitrary-state/constant cases at one and twenty
rounds, but grow the loop from 122 instructions/549 bytes to 142 instructions
and 669--689 bytes. Modular ADD carry blocks cross-round shuffle cancellation.
The exact scope and controls are in
[`eleventh_isa_synthesis_results_02.json`](../../solutions/02_optimization/eleventh_isa_synthesis_results_02.json).
LLVM 19.1.7 accepts `arrowlake`, but its
[`X86.td`](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/llvm/lib/Target/X86/X86.td)
maps it to `AlderlakePModel`; all six tested LLVM 19 labels give identical
metrics per stream. These
[llvm-mca](https://llvm.org/docs/CommandGuide/llvm-mca.html) results are not
255H model evidence.

From the repository root, the six-case campaign shape is:

```bash
python3 solutions/benchmark_02_permutation.py \
  --case scalar=submissions/02/contest.c \
  --case full549=solutions/02_optimization/contest_simd_avx2_inline_asm.c \
  --case old_block2=solutions/02_optimization/contest_simd_avx2_pair_block2.c \
  --case block2_counted=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --case block3_tail1=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --case block5_counted=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --baseline full549 \
  --case-cflag scalar=-mbmi2 \
  --case-cflag scalar=-finline-limit=2000 \
  --case-cflag full549=-mavx2 \
  --case-cflag full549=-DCH2_SIMD_INLINE \
  --case-cflag full549=-finline-limit=2000 \
  --case-cflag old_block2=-mavx2 \
  --case-cflag old_block2=-DCH2_SIMD_INLINE \
  --case-cflag old_block2=-finline-limit=2000 \
  --case-cflag block2_counted=-mavx2 \
  --case-cflag block2_counted=-DCH2_SIMD_INLINE \
  --case-cflag block2_counted=-DCH2_TENTH_BLOCK2 \
  --case-cflag block2_counted=-finline-limit=2000 \
  --case-cflag block3_tail1=-mavx2 \
  --case-cflag block3_tail1=-DCH2_SIMD_INLINE \
  --case-cflag block3_tail1=-finline-limit=2000 \
  --case-cflag block5_counted=-mavx2 \
  --case-cflag block5_counted=-DCH2_SIMD_INLINE \
  --case-cflag block5_counted=-DCH2_TENTH_BLOCK5 \
  --case-cflag block5_counted=-finline-limit=2000 \
  --audit-mode scalar=full-inline-320 \
  --audit-mode full549=avx2-inline-lanewise \
  --audit-mode old_block2=avx2-inline-pair-block2 \
  --audit-mode block2_counted=avx2-inline-pair-block2-counted \
  --audit-mode block3_tail1=avx2-inline-pair-block3-tail1 \
  --audit-mode block5_counted=avx2-inline-pair-block5-counted \
  --cpu 1 --iterations 3000000 --warmups 6 --samples 24 \
  --random-cases 100000 --campaign-id ch2-stationarity-cpu1-rerun-a \
  --json /tmp/challenge02-stationarity-cpu1.json
```

Use a fresh campaign id and output path for every run; change `--cpu 1` to
`--cpu 3` for the second affinity.  A new 255H decision still requires the
separate `probe -> screen -> confirm -> decide` workflow below rather than
treating these AMD campaigns as target measurements.

On the actual 255H, use
[`../../solutions/02_optimization/autotune_02_255h.py`](../../solutions/02_optimization/autotune_02_255h.py)
to probe P/E/LP-E topology, screen candidates, run two-session holdout
confirmation, and make a conservative decision. The incumbent score command
above remains the recommendation until that target-only gate reports a single
winner. Ambiguous topology, incomplete sessions, failed correctness/assembly
audits, or multiple qualifying candidates all keep the incumbent. Campaigns
also pin one canonical hash over the runner, audit, independent oracle/verifier,
official archive, Python, `objdump`, and `size` executables; changing any of them
requires a fresh probe, screen, and confirmation rather than mixing measurement
protocols. Fresh campaign ids plus canonical evidence and paired-sample hashes
reject renamed or whitespace-modified copies of an earlier run.  Nested
topology/cache records also fail closed, and an expanded balanced 15-case smoke
passed all 15 direct verifications and all 15 measured-binary audits.  Those
1,000-call smoke timings are tool regression evidence only.  The former
19-case manifest, including three partial-unroll controls and lane-wise
AVX2, passed 19/19 direct verifications and audits. After adding the distinct
`-fira-region=one` and single-scratch 569-byte streams, a 21-case smoke passed
21/21 direct verifications and measured-binary audits. Adding the seven
nonbaseline stream/alignment representatives produced a **28-case**
manifest; a fresh balanced smoke passed 28/28 direct verifications and 28/28
audits, with source-local `-iquote` context recorded for every case. Its
1,000-call provisional-host timings are integration evidence only.  The
549-byte commutative source replaces the old assembly entry; adding its
548-byte counter control and the old compact block2 produced the ninth-wave
30-case state.  The three counted block-2/3/5 Pareto points expand the current
schema-5 manifest to **33 cases**.  Current confirmation additionally requires
the repeated state, alternate challenge, total-derived timing, and child-CPU
coverage records, plus the independently recomputed stationarity record.
The documented local algorithmic/ISA, code-generation, cache/frontend, and
micro-optimization scopes are now closed. The only unresolved performance task
is an actual Core Ultra 7 255H `probe -> screen ->` two independent
`confirm` sessions `-> decide`; no global ISA-optimality claim is made.
