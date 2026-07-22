# Challenge 2 submission

Files:

- `contest.c`: final two-round-composed BMI2 implementation using the provided harness
- `run_contest.sh`: reproducible score build using the statement-permitted flags
- `report.pdf`: required analysis, implementation, verification, and benchmark report
- `report.tex`: reproducible source for the PDF

To run the submitted harness, place the provided `testvector.txt` and `testvector_20round.txt` beside `contest.c`, then run:

```bash
cd submissions/02
# Compatibility build from the supplied command:
gcc -O3 -Wall -Wextra -o contest contest.c
./contest

# Faster score-facing build allowed by the statement:
./run_contest.sh
cd ../..
```

The source is adaptive. Without global BMI2 it retains the local noinline BMI2
helper. With `-mbmi2`, that helper becomes `always_inline`; the larger inline
limit also carries the public wrapper into `main`'s timing loop. This removes
the repeated call/prologue and keeps four state words plus eight constants in
registers across timed calls without changing the permutation or hard-coding a
benchmark value.

The wrapper changes only the build flags; it does not modify the official test
vectors, harness I/O, or permutation. The source itself remains compatible with
the supplied plain `gcc -O3` command.

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
their schema-4 raw samples are linked from the deep review.

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
registration were skipped. A separate 112-build GCC/Clang screen found no GCC
source rewrite with fewer instructions or model cycles. The exact OR-to-XOR
rotate merge passed 100,000 cases under both compilers but only exchanged
mnemonics. Records are in
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
1,000-call smoke timings are tool regression evidence only.  The current
19-case manifest, including three partial-unroll controls and lane-wise AVX2,
also passed 19/19 direct verifications and 19/19 measured-binary audits; its
AVX2 loop was exactly 122 instructions, 579 bytes, and memory-free.
