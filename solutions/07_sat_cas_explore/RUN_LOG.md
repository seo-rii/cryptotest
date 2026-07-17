# Challenge 7 Corrected-PDF Run Log

This log starts after moving the previous exploration directory to
`07_sat_cas_explore.old`.

## 2026-06-05 Fresh Workspace

- Corrected p known bits: `672 / 1024`.
- Corrected p unknown bits: `352`.
- Unknown intervals:

  ```text
  150..153   4 bits
  265..348  84 bits
  362..419  58 bits
  600..668  69 bits
  682..768  87 bits
  784..829  46 bits
  920..923   4 bits
  ```

- Previous directory preserved at `cryptotest/solutions/07_sat_cas_explore.old`.
- Fresh directory contains only the corrected q-gap/SAT core files needed for
  the next search pass.

Verification:

```bash
PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Result: `10/10` tests passed.

## Fresh q-gap Batch Smoke

The first fresh run exposed a path bug: `run_q_gap_parallel.py` loaded the
candidate JSON from the caller cwd, but child `branch_q_gap_coppersmith.py`
processes ran under `cryptotest/`, so relative `tmp/...` paths were treated as
`cryptotest/tmp/...` and loaded zero candidates.  The runner now resolves
candidate JSON paths to absolute paths before passing them to child processes.

Verification after the fix:

```bash
python3 -m py_compile cryptotest/solutions/07_sat_cas_explore/*.py

PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Result: compile succeeded and `10/10` tests passed.

Corrected split-frontier hash A:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-a \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_fresh_gateway_hashA_top64.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_gateway_hashA_top64.json \
  --output-dir tmp/ct07_fresh_gateway_hashA_top64_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Result: 64 candidates, `q_gap_bits=456` for all, `64/64 no_roots`,
`64/64` hard no-root eligible, no roots or factors, about 196.2 seconds.

Corrected split-frontier hash B:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-b \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_fresh_gateway_hashB_top64.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_gateway_hashB_top64.json \
  --output-dir tmp/ct07_fresh_gateway_hashB_top64_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Result: 64 candidates, `q_gap_bits=456` for all, `64/64 no_roots`,
`64/64` hard no-root eligible, no roots or factors, about 196.9 seconds.

Corrected low42 frontier:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-low42-a \
  --x2-low-bits 42 --x2-low-widths 7,7,7,7,7,7 \
  --x5-high-bits 0 --x5-high-widths none \
  --json > tmp/ct07_fresh_gateway_low42_hashA_top64.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_gateway_low42_hashA_top64.json \
  --output-dir tmp/ct07_fresh_gateway_low42_hashA_top64_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Result: 64 candidates, `q_gap_bits=462` for all, `64/64 no_roots`,
`64/64` hard no-root eligible, no roots or factors, about 184.8 seconds.

These batches confirm the fresh corrected-PDF q-gap plumbing and close 192
ranked hard-line candidates.  They do not solve the instance.

## Full x1 / Full x5 q-gap 407 Probe

Window scan showed that p-window `[265,769)` contains 298 hidden bits and
leaves only `x0 + x5 + x6 = 54` hidden bits outside, but univariate p-window
Sage calls near 480-504 middle bits are too slow for broad use.  The next
best corrected branch shape fixes full `265:84`, full `784:46`, plus the two
4-bit edge chunks:

```text
150:4,265:84,784:46,920:4
```

This makes q low bits reach 362 and q high prefix start around 769-770, giving
q-gap about 407-408 bits.

Candidate generation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-fullx1x5-a \
  --x2-low-bits 84 --x2-low-widths 12,12,12,12,12,12,12 \
  --x5-high-bits 0 --x5-high-widths none \
  --json > tmp/ct07_fresh_fullx1x5_hashA_top64.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_fullx1x5_hashA_top64.json \
  --output-dir tmp/ct07_fresh_fullx1x5_hashA_top64_qgap_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Result: 64 candidates, all hard no-root, no roots or factors.

p-window `[362,830)` on the same candidate style is not currently practical:
top4 with `epsilon=0.005` and 60-second per-candidate timeout produced
`4/4 timeout`, no factors.

Independent drop test for the all-zero cube:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:84,784:46,920:4 \
  --check-bits 362 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 920:4 \
  --q-gap-drop-window 784:6 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges \
  > tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl
```

Result: q-gap status `no_roots`, `q_gap_bits=408`,
`effective_margin_bits=62.04`, and all three drop windows passed:

```text
drop 150:4 -> learned literal count 134
drop 920:4 -> learned literal count 134
drop 784:6 -> learned literal count 132
```

The second cube, loaded from the first ledger, moved to `265:84=1` and produced
the same three independent drop clauses.  Loading both ledgers moved the next
model to `265:84=3`, so the clauses are actively skipping SAT space.

`run_fullx1x5_drop_loop.py` now wraps this one-cube-at-a-time process.  Dry-run
verification confirms it writes under workspace `tmp/` and passes absolute
ledger paths to child processes.

Actual one-iteration loop after loading the first two ledgers:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 1 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_second_cube_drops.jsonl \
  --output-dir tmp/ct07_fresh_fullx1x5_drop_loop_after2_iter1 \
  --json
```

Result: no factor, one cube closed in about 493 seconds.  The cube was
`150:4=0,265:84=3,784:46=0,920:4=0`; q-gap was 408, q-gap oracle time about
21.6 seconds, and all three independent drop windows passed again.

Optimization: for q-gap 408, `epsilon=0.04` still has effective hard margin
about 21.08 bits, above the 8-bit hard threshold.  The same third cube with
drop minimization fell from about 493 seconds to about 12.8 seconds; the base
q-gap oracle fell from about 21.6 seconds to about 1.5 seconds.  Therefore
`run_fullx1x5_drop_loop.py` now defaults to `--q-gap-epsilon 0.04`.

Byte-level independent drops on the all-zero cube:

```text
265:8, 273:8, 281:8, 289:8, 297:8, 305:8,
313:8, 321:8, 329:8, 337:8,
784:8, 792:8, 800:8, 808:8, 816:8, 824:6
```

Every tested window was independently droppable with `epsilon=0.04`; every
completion returned hard-eligible `no_roots`.  Loading the all-zero byte-drop
ledgers plus the edge-drop ledger moved the next SAT model to `265:84=257`.

Medium drop-set loop:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 3 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --drop-window 784:8 \
  --drop-window 792:8 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_265_784_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_273_792_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_281_289_800_808_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_remaining_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_after_allzero_bytes_iter1_midset_eps004/iteration_0001.jsonl \
  --output-dir tmp/ct07_fresh_fullx1x5_drop_loop_midset_after257_iter3_eps004 \
  --json
```

Result: no factor.  Three cubes closed in about 363 seconds, average about
121 seconds per cube.  The cube values progressed:

```text
265:84 = 520
265:84 = 778
265:84 = 1794
```

Every cube again returned hard q-gap no-root and all six medium drop windows
passed.

Outside-only hit-first q-gap test:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-outside54-a \
  --x2-low-bits 0 --x2-low-widths none \
  --x5-high-bits 0 --x5-high-widths none \
  --json > tmp/ct07_fresh_outside54_hashA_top64.json

python3 cryptotest/solutions/07_sat_cas_explore/branch_q_gap_coppersmith.py \
  --candidate-json tmp/ct07_fresh_outside54_hashA_top64.json \
  --candidate-start 1 --candidate-stop 1 \
  --summary-json tmp/ct07_fresh_outside54_hashA_top1_qgap504.json \
  --max-gap-bits 512 --epsilon 0.003 --min-hard-margin-bits 999 \
  --oracle-timeout-seconds 90 --no-pdf-check
```

Result: the top candidate had `q_gap_bits=504` and timed out after 90 seconds.
This keeps outside-only `[265,769)` q-gap as a theoretical hit-first idea, not
a practical broad runner.

CP-SAT limb baseline on the corrected all-zero edge branch:

```bash
python3 cryptotest/solutions/try_07_cp_sat_limb.py \
  --branch-low 0 --branch-high 0 \
  --time-limit 30 --workers 8 \
  --decision-p-range 265:84 \
  --decision-p-range 784:46
```

Result: `UNKNOWN`, wall time about 66 seconds, 3553 branches, 14 conflicts.
Direct CP-SAT is not currently a solve path without much stronger extra
constraints or branch hints.

## Cumulative q-gap Drop Parallelization

`semi_programmatic_sat.py` now runs cumulative q-gap drop completion checks with
`ProcessPoolExecutor` when `--q-gap-minimize-workers > 1`.  The previous
parallel path only covered independent drop clauses.

Smoke test:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:84,784:46,920:4 \
  --check-bits 362 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.04 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 920:4 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges \
  > tmp/ct07_fresh_fullx1x5_allzero_cumulative_x0_x7_eps004.jsonl
```

Result: no factor.  The all-zero full-x1/full-x5 cube returned hard q-gap
`no_roots` with `q_gap_bits=408`.  Cumulative minimization proved both edge
windows droppable:

```text
150:4 completion count 16:  all hard no_roots
150:4 + 920:4 completion count 256:  all hard no_roots
```

The learned hard clause scope was `minimized_q_gap_selected_bits` with 130
literals, dropping 8 selected edge bits.  Total q-gap oracle calls were 273.

`run_fullx1x5_drop_loop.py` now exposes this with `--drop-mode cumulative`.
Runner smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --drop-mode cumulative \
  --iterations 1 \
  --q-gap-minimize-max-completions 256 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --output-dir tmp/ct07_fresh_fullx1x5_cumulative_runner_smoke_x0_x7_eps004 \
  --json
```

Result: no factor, one cube closed in about 31.6 seconds.  `loop_summary.json`
recorded the same 130-literal cumulative clause and no stderr output.

Follow-up cumulative loop:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --drop-mode cumulative \
  --iterations 4 \
  --q-gap-minimize-max-completions 256 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_cumulative_runner_smoke_x0_x7_eps004/iteration_0001.jsonl \
  --output-dir tmp/ct07_fresh_fullx1x5_cumulative_after_smoke_iter4_eps004 \
  --json
```

Result: no factor.  Four more cubes closed in about 137.6 seconds.  The cube
values progressed:

```text
265:84 = 1
265:84 = 2
265:84 = 3
265:84 = 7
```

Each cube returned hard q-gap `no_roots`, dropped the same combined 8 edge
bits, and recorded a 130-literal learned clause.  All stderr files were empty.

`epsilon=0.045` and `epsilon=0.046` were also sanity-checked on the base
q-gap 408 cube.  Both stayed hard-eligible, but `0.046` leaves only about
8.79 bits of effective margin and the runtime gain over `0.04` was negligible.
Keep the runner default at `0.04`.

## High32 q-gap 437 Path

A smaller search surface than full-x1/full-x5 is possible by fixing only the
high 32 bits of the `784..829` unknown block:

```text
150:4,265:84,798:32,920:4
```

This selects 124 hidden p bits.  With q-gap edge completions over `150:4` and
`920:4`, the maximum observed q-gap is 440.  Therefore `epsilon=0.0305` keeps
the hard margin above 8 bits for the whole edge-drop union.

Base/runtime probes:

```text
hi16: selected 108, base gap 453, epsilon 0.0220, elapsed 10.49s
hi24: selected 116, base gap 445, epsilon 0.0235, elapsed  7.26s
hi32: selected 124, base gap 437, epsilon 0.0305, elapsed  3.10s
```

The hi32 cumulative edge check:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --check-bits 362 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 440 \
  --q-gap-epsilon 0.0305 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 920:4 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges \
  > tmp/ct07_fresh_x0x1x5hi32x6_cumulative_edges_eps00305_max440.jsonl
```

Result: no factor.  The all-zero hi32 cube returned hard q-gap `no_roots`;
both edge windows were cumulatively droppable, producing a 116-literal hard
clause from 124 selected literals.  Total q-gap oracle calls: 273.

`run_fullx1x5_drop_loop.py` now accepts `--cube-ranges`, so the hi32 path can
be run through the same ledger loop:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --drop-mode cumulative \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --iterations 2 \
  --q-gap-max-bits 446 \
  --q-gap-epsilon 0.028 \
  --q-gap-minimize-max-completions 256 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_cumulative_edges_eps0028_max446.jsonl \
  --output-dir tmp/ct07_fresh_x0x1x5hi32x6_cumulative_after_smoke_iter2_eps0028 \
  --json
```

Result: no factor.  Two follow-up cubes closed:

```text
265:84 = 1, 798:32 = 0
265:84 = 2, 798:32 = 0
```

Each produced a 116-literal hard clause with the 8 edge bits dropped.

A 16-worker smoke on the optimized `epsilon=0.0305, max_gap=440` setting closed
one follow-up cube in about 108 seconds.  It did not improve materially over
8 workers on this host.

## High32 Independent Byte Drops

For the hi32 all-zero cube, the following independent byte windows were tested
with `q_gap_max_bits=445`, `epsilon=0.028`, 8 workers, and 256 completions per
window:

```text
265:8, 273:8, 281:8, 289:8
798:8, 806:8, 814:8, 822:8
```

All eight windows were `droppable_sound_no_root`.  The generated ledgers are:

```text
tmp/ct07_fresh_x0x1x5hi32x6_independent_265_798_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_273_806_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_281_814_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_289_822_eps0028_max445.jsonl
```

Each ledger contains two 116-literal independent hard clauses.  Loading those
four ledgers plus the cumulative edge ledger adds 9 hard clauses / 1044
literals.  The next SAT model moves to:

```text
150:4 = 0
265:84 = 257
798:32 = 0
920:4 = 0
```

This confirms the clauses are active, but independent byte clauses do not give
a large contiguous jump.  The next high-value proof is a cumulative 16-bit
union, for example `265:8 + 273:8`, which costs 65536 q-gap completions:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --check-bits 362 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-drop-window 265:8 \
  --q-gap-drop-window 273:8 \
  --q-gap-minimize-max-completions 65536 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges \
  > tmp/ct07_fresh_x0x1x5hi32x6_cumulative_265_273_eps0028_max445.jsonl
```

This is a multi-hour proof job.  It is more valuable than piling up many more
single-byte independent clauses because it would remove a full 16-bit face from
the selected cube in one hard clause.

`run_q_gap_union_shards.py` was added to make this job resumable.  It writes one
`shard_XXXXXX.json` file per shard and writes a `learned_clause.jsonl` only
after all shards pass.

First shard smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --shard-stop 1 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --json
```

Result: partial proof, no factor.  Shard 0 passed:

```text
completion range: 0..512
status_counts: no_roots=512
hard_eligible_completion_count: 512
elapsed: 196.35 seconds
```

Resume smoke against the same output directory skipped the existing shard in
about 1 ms.  At this measured speed, the full 128-shard proof is about 7 hours.

Second shard:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --shard-stop 2 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --json
```

Result: partial proof, no factor.  Shard 0 was skipped and shard 1 passed.
Current coverage:

```text
hard no-root completions: 1024 / 65536
status_counts: no_roots=1024
missing shards: 126
```

`run_q_gap_union_shards.py` now supports bounded runs:

```text
--max-new-shards N
--max-seconds T
```

This lets long proofs run in controlled batches without manually calculating
`--shard-stop`.

Bounded follow-up:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 2 \
  --json
```

Result: partial proof, no factor.  Shards 2 and 3 passed:

```text
hard no-root completions: 2048 / 65536
status_counts: no_roots=2048
missing shards: 124
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 4 through 7 passed:

```text
hard no-root completions: 4096 / 65536
status_counts: no_roots=4096
missing shards: 120
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 8 through 11 passed:

```text
hard no-root completions: 6144 / 65536
status_counts: no_roots=6144
missing shards: 116
```

Safety update: `run_q_gap_union_shards.py` now records a proof key in each
shard and refuses to resume if completed shards or `parameters.json` do not
match the current cube/drop/q-gap parameters.  The existing shards `0..11` were
migrated to the current proof key, and a resume smoke skipped them correctly.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 12 through 15 passed:

```text
hard no-root completions: 8192 / 65536
status_counts: no_roots=8192
missing shards: 112
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 8 \
  --json
```

Result: partial proof, no factor.  Shards 16 through 23 passed:

```text
hard no-root completions: 12288 / 65536
status_counts: no_roots=12288
missing shards: 104
```

Shard runtimes in this batch ranged from about 197s to 262s.  Four-shard
batches are easier to monitor if the machine is shared.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 24 through 27 passed:

```text
hard no-root completions: 14336 / 65536
status_counts: no_roots=14336
missing shards: 100
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 28 through 31 passed:

```text
hard no-root completions: 16384 / 65536
coverage: 25%
status_counts: no_roots=16384
missing shards: 96
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 32 through 35 passed:

```text
hard no-root completions: 18432 / 65536
coverage: 28.125%
status_counts: no_roots=18432
missing shards: 92
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 36 through 39 passed:

```text
hard no-root completions: 20480 / 65536
coverage: 31.25%
status_counts: no_roots=20480
missing shards: 88
```

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 40 through 43 passed:

```text
hard no-root completions: 22528 / 65536
coverage: 34.375%
status_counts: no_roots=22528
missing shards: 84
```

Shard runtimes in this batch were about 181 to 184 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 44 through 47 passed:

```text
hard no-root completions: 24576 / 65536
coverage: 37.5%
status_counts: no_roots=24576
missing shards: 80
```

Shard runtimes in this batch were about 180 to 186 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 48 through 51 passed:

```text
hard no-root completions: 26624 / 65536
coverage: 40.625%
status_counts: no_roots=26624
missing shards: 76
```

Shard runtimes in this batch were about 180 to 269 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 52 through 55 passed:

```text
hard no-root completions: 28672 / 65536
coverage: 43.75%
status_counts: no_roots=28672
missing shards: 72
```

Shard runtimes in this batch were about 222 to 269 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 56 through 59 passed:

```text
hard no-root completions: 30720 / 65536
coverage: 46.875%
status_counts: no_roots=30720
missing shards: 68
```

Shard runtimes in this batch were about 209 to 255 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 60 through 63 passed:

```text
hard no-root completions: 32768 / 65536
coverage: 50%
status_counts: no_roots=32768
missing shards: 64
```

Shard runtimes in this batch were about 202 to 239 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 64 through 67 passed:

```text
hard no-root completions: 34816 / 65536
coverage: 53.125%
status_counts: no_roots=34816
missing shards: 60
```

Shard runtimes in this batch were about 213 to 249 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 68 through 71 passed:

```text
hard no-root completions: 36864 / 65536
coverage: 56.25%
status_counts: no_roots=36864
missing shards: 56
```

Shard runtimes in this batch were about 257 to 311 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 72 through 75 passed:

```text
hard no-root completions: 38912 / 65536
coverage: 59.375%
status_counts: no_roots=38912
missing shards: 52
```

Shard runtimes in this batch were about 251 to 314 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 76 through 79 passed:

```text
hard no-root completions: 40960 / 65536
coverage: 62.5%
status_counts: no_roots=40960
missing shards: 48
```

Shard runtimes in this batch were about 332 to 403 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 80 through 83 passed:

```text
hard no-root completions: 43008 / 65536
coverage: 65.625%
status_counts: no_roots=43008
missing shards: 44
```

Shard runtimes in this batch were about 219 to 263 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 84 through 87 passed:

```text
hard no-root completions: 45056 / 65536
coverage: 68.75%
status_counts: no_roots=45056
missing shards: 40
```

Shard runtimes in this batch were about 213 to 260 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 88 through 91 passed:

```text
hard no-root completions: 47104 / 65536
coverage: 71.875%
status_counts: no_roots=47104
missing shards: 36
```

Shard runtimes in this batch were about 184 to 219 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 92 through 95 passed:

```text
hard no-root completions: 49152 / 65536
coverage: 75%
status_counts: no_roots=49152
missing shards: 32
```

Shard runtimes in this batch were about 207 to 251 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 96 through 99 passed:

```text
hard no-root completions: 51200 / 65536
coverage: 78.125%
status_counts: no_roots=51200
missing shards: 28
```

Shard runtimes in this batch were about 200 to 241 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 4 \
  --json
```

Result: partial proof, no factor.  Shards 100 through 103 passed:

```text
hard no-root completions: 53248 / 65536
coverage: 81.25%
status_counts: no_roots=53248
missing shards: 24
```

Shard runtimes in this batch were about 185 to 250 seconds, and no factor was
reported.

Next bounded batch:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_union_shards.py \
  --cube-range 150:4:0 \
  --cube-range 265:84:0 \
  --cube-range 798:32:0 \
  --cube-range 920:4:0 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --shard-size 512 \
  --workers 8 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --output-dir tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028 \
  --resume \
  --max-new-shards 24 \
  --json
```

Result: full proof, no factor.  Shards 104 through 127 passed:

```text
hard no-root completions: 65536 / 65536
coverage: 100%
status_counts: no_roots=65536
missing shards: 0
failed shards: 0
```

The final batch took about 4736 seconds wall-clock.  New shard runtimes were
about 180 to 248 seconds, and no factor was reported.  The runner wrote:

```text
tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028/learned_clause.jsonl
```

This learned clause is a 108-literal hard `q_gap_coppersmith_no_root` clause
for the selected high32 cube, after dropping the 16 bits `265..280`.

Follow-up SAT-ledger run after loading the completed union clause and the
previous `x0=1` independent-drop ledger:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --output-dir tmp/ct07_fresh_hi32_after_union_x0_2_5_independent_265_273_eps0028 \
  --iterations 4 \
  --workers 8 \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --check-bits 608 \
  --timeout-ms 60000 \
  --q-gap-max-bits 445 \
  --q-gap-epsilon 0.028 \
  --min-hard-margin-bits 8 \
  --drop-mode independent \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --q-gap-minimize-max-completions 256 \
  --resume-jsonl tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028/learned_clause.jsonl \
  --resume-jsonl tmp/ct07_fresh_hi32_after_union_x0_1_independent_265_273_eps0028/iteration_0001.jsonl \
  --json
```

Result: no factor.  The loop completed 4 one-cube iterations in about
1001 seconds.  The selected `150:4` values were `2`, `3`, `7`, and `5`, all
with `265:84=0`, `798:32=0`, and `920:4=0`.  Each cube had `q_gap_bits=437`,
returned hard `no_roots`, and produced two independent 116-literal clauses by
dropping `265:8` and `273:8` separately.  Each minimization checked 256
hard-eligible completions per byte window.

Loading all current ledgers produces the next sample cube:

```text
150:4=4, 265:84=0, 798:32=0, 920:4=0
```

This is still unsolved; no factor has appeared in the completed q-gap ledgers.

Continued high32/all-zero x0-front follow-up:

```text
tmp/ct07_fresh_hi32_after_union_x0_4plus_independent_265_273_eps0028
tmp/ct07_fresh_hi32_after_union_x0_14plus_independent_265_273_eps0028
tmp/ct07_fresh_hi32_after_union_x0_9_8_independent_265_273_eps0028
```

Result: no factor.  These three follow-up loops closed the remaining
`150:4` values for the same `265:84=0, 798:32=0, 920:4=0` high32 branch:

```text
4, 6, 15, 11
14, 10, 12, 13
9, 8
```

Together with the previous union/ledger rows, this closes `150:4 = 0..15` for
`265:84=0, 798:32=0, 920:4=0`.  Every cube had `q_gap_bits=437`, returned
hard `no_roots`, and produced two independent 116-literal drop clauses for
`265:8` and `273:8`.  Loading all these ledgers moves the next high32 sample to:

```text
150:4=8, 265:84=65536, 798:32=0, 920:4=0
```

This shows that the low x0 front is closed, but continuing the same shape would
now walk the `265:84` space.  That is lower priority than the q-gap 408
medium-drop shape.

Continued the q-gap 408 medium-drop line with:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 5 \
  --workers 8 \
  --cube-ranges 150:4,265:84,784:46,920:4 \
  --check-bits 362 \
  --timeout-ms 60000 \
  --q-gap-max-bits 462 \
  --q-gap-epsilon 0.04 \
  --min-hard-margin-bits 8 \
  --drop-mode independent \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --drop-window 265:8 \
  --drop-window 273:8 \
  --drop-window 784:8 \
  --drop-window 792:8 \
  --q-gap-minimize-max-completions 256 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_265_784_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_273_792_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_281_289_800_808_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_allzero_bigdrop_remaining_eps004.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_after_allzero_bytes_iter1_midset_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_midset_after257_iter3_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_midset_after257_iter3_eps004/iteration_0002.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_midset_after257_iter3_eps004/iteration_0003.jsonl \
  --output-dir tmp/ct07_fresh_fullx1x5_drop_loop_midset_after1794_iter5_eps004 \
  --json
```

Result: no factor.  Five more q-gap 408 hard-no-root cubes closed in about
531 seconds:

```text
265:84 = 1292
265:84 = 1028
265:84 = 1542
265:84 = 3337
265:84 = 2317
```

Every cube again produced six independent medium-drop clauses with total
learned literal count 788.  Loading these ledgers moves the next q-gap 408
sample to:

```text
150:4=0, 265:84=3088, 784:46=0, 920:4=0
```

Continued the same q-gap 408 medium-drop line with:

```text
tmp/ct07_fresh_fullx1x5_drop_loop_midset_after3088_iter10_eps004
```

Result: no factor.  Ten more q-gap 408 hard-no-root cubes closed in about
1065 seconds:

```text
265:84 = 3088
265:84 = 2072
265:84 = 2830
265:84 = 2567
265:84 = 3587
265:84 = 3851
265:84 = 6405
265:84 = 6927
265:84 = 7953
265:84 = 7442
```

Every cube again had `q_gap_bits=408` and produced six independent medium-drop
clauses with total learned literal count 788.  Loading the q-gap 408 ledgers
now gives:

```text
loaded_learned_clauses=133
loaded_learned_literals=17454
next sample: 150:4=0, 265:84=5911, 784:46=0, 920:4=0
```

Generated a diversified q-gap hard-line candidate set:

```text
tmp/ct07_fresh_gateway_hashC_top128.json
tmp/ct07_fresh_gateway_hashC_top128_parallel
```

Result: no factor.  All 128 candidates had `q_gap_bits=456`, returned
`no_roots`, and were hard eligible under `epsilon=0.02`.

Then continued the q-gap 408 medium-drop SAT-ledger line:

```text
tmp/ct07_fresh_fullx1x5_drop_loop_midset_after5911_iter10_eps004
```

Result: no factor.  Ten more q-gap 408 hard-no-root cubes closed in about
1064 seconds:

```text
265:84 = 5911
265:84 = 4891
265:84 = 5407
265:84 = 4381
265:84 = 4630
265:84 = 6675
265:84 = 6165
265:84 = 4116
265:84 = 5145
265:84 = 5658
```

Every cube had `q_gap_bits=408` and produced six independent medium-drop
clauses with total learned literal count 788.  Loading the q-gap 408 ledgers
now gives:

```text
loaded_learned_clauses=193
loaded_learned_literals=25334
next sample: 150:4=0, 265:84=7196, 784:46=0, 920:4=0
```

Checked alternate p-window `[362,830)` success oracle on the current next
q-gap408 sample:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/two_sided_window_coppersmith.py \
  --window 362:830 \
  --fix-p-range 150:4:0 \
  --fix-p-range 265:84:7196 \
  --fix-p-range 920:4:0 \
  --epsilon 0.005 \
  --oracle-timeout-seconds 120 \
  --json
```

Result: timeout after 120 seconds, no factor.  The window has `middle_bits=468`;
it is a plausible success oracle when the outside bits are correct, but it is
too slow for broad automatic batching in the current Sage configuration.

Ran a corrected full-mask unknown-divisor preflight with all seven unknown
blocks active.  Best recorded HM/LZ-like determinant proxy margin was still
strongly negative, so direct all-variable lattice remains lower priority than
q-gap hard pruning.

Continued the q-gap 408 medium-drop SAT-ledger line:

```text
tmp/ct07_fresh_fullx1x5_drop_loop_midset_after7196_iter10_eps004
```

Result: no factor.  Ten more q-gap 408 hard-no-root cubes closed in about
1071 seconds:

```text
265:84 = 7196
265:84 = 7710
265:84 = 14370
265:84 = 14625
265:84 = 15392
265:84 = 15652
265:84 = 10533
265:84 = 11564
265:84 = 11304
265:84 = 10281
```

Every cube had `q_gap_bits=408` and produced six independent medium-drop
clauses with total learned literal count 788.  Loading the q-gap 408 ledgers
now gives:

```text
loaded_learned_clauses=253
loaded_learned_literals=33214
next sample: 150:4=0, 265:84=12589, 784:46=0, 920:4=0
```

## Low600 p-Coppersmith Line

The corrected mask has a stronger low-side path than the earlier q-gap408
continuation.  Fixing these three ranges makes p[0..600) fully known:

```text
150:4
265:84
362:58
```

For `low_bits=600`, `epsilon=0.02`, and an 8-bit hard margin threshold, the
oracle reports:

```text
unknown_bits=424
effective_bound_bits=470.04
effective_margin_bits=46.04
hard_clause_eligible=true
```

Initial logs:

```text
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_probe.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_iter5.jsonl
```

Result: no factor.  The no-drop file closed 20 hard low-Coppersmith no-root
cubes.  The x0-drop probe and five follow-up cubes proved `150:4` droppable:
each selected `(265:84,362:58)` assignment had all 16 x0 completions return
hard no-root, producing 142-literal minimized low-prefix clauses.

`semi_programmatic_sat.py` now supports
`--low-coppersmith-minimize-workers` so low-C drop completion checks can use
multiple Sage processes.  `run_low600_drop_loop.py` wraps the current preferred
loop.

Runner smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_low600_drop_loop.py \
  --iterations 1 --workers 8 \
  --output-dir tmp/ct07_fresh_low600_drop_x0_runner_smoke_eps002 \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600.jsonl \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_probe.jsonl \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_iter5.jsonl
```

Result: no factor.  It closed the next cube
`150:4=0,265:84=3,362:58=0` in about 35.3 seconds with 8 workers.  The run
loaded 26 learned clauses / 3772 literals, made 17 low-Coppersmith calls,
verified 16 x0 completions as hard no-root, and produced another 142-literal
minimized low-prefix clause.

Use this as the next bounded continuation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_low600_drop_loop.py \
  --iterations 1200 \
  --max-seconds 43200 \
  --workers 8 \
  --output-dir tmp/ct07_fresh_low600_drop_x0_12h_eps002 \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600.jsonl \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_probe.jsonl \
  --resume-jsonl tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_iter5.jsonl \
  --resume-jsonl tmp/ct07_fresh_low600_drop_x0_runner_smoke_eps002/iteration_0001.jsonl
```

At the smoke speed, 12 hours is roughly 1200 low600 x0-drop cubes.  Actual
throughput can vary because each cube launches Sage workers.

Follow-up low600 batch:

```text
tmp/ct07_fresh_low600_drop_x0_after3_iter100_eps002
```

The batch was intentionally stopped after 15 completed iterations to test
larger drops.  Result: no factor.  The 15 completed ledgers are valid hard
no-root clauses; `iteration_0016.jsonl` is only a partial load record and
should not be used as a resume ledger.  The completed x1 values included
`4,5,6,7,8,9,10,11,12,13,14,15,24,26,27`.

An x1-low-nibble probe with an incorrect `seq -w` ledger list still produced a
sound clause, but loaded only 27 clauses because the iteration filenames were
misformatted.  The corrected probe:

```text
tmp/ct07_fresh_low600_drop_x1low4_probe_after24_corrected_eps002.jsonl
```

loaded 43 clauses with `file_errors=0` and proved `265:4` droppable for the
current front `150:4=0,265:84=25,362:58=0`: all 16 completions returned hard
no-root, with no factor.

A short x1-low-nibble-only batch:

```text
tmp/ct07_fresh_low600_drop_x1low4_after24_iter20_eps002
```

was stopped while iteration 4 had already produced a valid JSONL row but before
`loop_summary.json` was updated.  Result: no factor.  Valid ledgers
`iteration_0001..0004` close `x0=1,2,3,6` for `265:84=25`, but this showed
that x1-low-only clauses still walk x0 one value at a time.

The stronger low600 cumulative probe:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_low600_drop_loop.py \
  --iterations 1 \
  --workers 8 \
  --drop-window 150:4 \
  --drop-window 265:4 \
  --low-coppersmith-minimize-max-completions 256 \
  --output-dir tmp/ct07_fresh_low600_drop_x0_x1low4_cumulative_probe_eps002 \
  ...
```

Result: no factor.  It proved `150:4 + 265:4` droppable for
`150:4=6,265:84=25,362:58=0`: `16/16` x0 completions and then `256/256`
combined completions were hard no-root.  The learned clause dropped 8 bits and
kept 138 literals.  Runtime was about 451 seconds with 8 workers and
`low_coppersmith_calls=273`.

After loading that cumulative clause, the next low600 sample moved to:

```text
150:4=0, 265:84=59, 362:58=0
```

This is a better next long-run shape than x0-only.  The cost is about
7.5 minutes per cumulative 8-bit proof, but each proof closes a 256-completion
block and advances the x1 frontier much more aggressively.

Recommended next bounded continuation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_low600_drop_loop.py \
  --iterations 96 \
  --max-seconds 43200 \
  --workers 8 \
  --drop-window 150:4 \
  --drop-window 265:4 \
  --low-coppersmith-minimize-max-completions 256 \
  --output-dir tmp/ct07_fresh_low600_drop_x0_x1low4_12h_eps002 \
  --resume-list tmp/ct07_fresh_low600_resume_after_cumulative_eps002.txt
```

The resume manifest lists all current valid low600 hard ledgers and explicitly
excludes the partial `iteration_0016.jsonl`.

## 2026-06-06 Corrected q-gap 456 restart

The attempted low600 cumulative continuation
`tmp/ct07_fresh_low600_drop_x0_x1low4_after59_iter2_eps002` was stopped after
about 5.5 hours because the first iteration never advanced past the
`loaded_learned_clauses` line.  It produced no valid cube row and must not be
loaded as proof evidence.

For the corrected mask, the old `x1` gateway is no longer hidden: fixing
`150:4` and `920:4` already extends q low to 265 and gives q high prefix around
830/831.  Adding full `x6=784:46` plus either `x2_low48` or `x5_high48` gives a
hard q middle-gap oracle with `q_gap_bits=456` and epsilon `0.02`.

Generated two corrected beam files:

```text
tmp/ct07_corrected_qgap_beams/x2low48_top64.json
tmp/ct07_corrected_qgap_beams/x5high48_top64.json
```

Smoke tests on the first candidate of each beam completed in about 13 seconds
each, both hard no-root and no factor.  The full top128 run:

```text
tmp/ct07_corrected_qgap_top128_parallel_eps002/q_gap_parallel_summary.json
```

checked 128 candidates in 369.1 seconds with 8 workers.  Result: no factor,
`128/128` hard no-root, `q_gap_distribution={"456": 128}`, no roots returned.
This is now the better controlled continuation than the stalled low600
cumulative drop line.

A wider hash-diversified beam was generated with beam width/top `512` for both
`x2_low48` and `x5_high48`:

```text
tmp/ct07_corrected_qgap_beams/x2low48_top512_hashw512.json
tmp/ct07_corrected_qgap_beams/x5high48_top512_hashw512.json
tmp/ct07_corrected_qgap_beams/qgap456_top512x2_top512x5_new_after_top128.json
```

The merged file contains 1024 new candidate branches after excluding the prior
top128 result.  A first 256-candidate continuation was run without per-oracle
timeout children, leaving only the chunk-level timeout:

```text
tmp/ct07_corrected_qgap_new256_parallel_eps002_nochildtimeout/q_gap_parallel_summary.json
```

Result: no factor, `256/256` hard no-root, `q_gap_distribution={"456": 256}`,
no roots returned.  Runtime was 784.4 seconds with 8 workers.  Combined with
the previous top128, the corrected q-gap 456 line has checked 384 candidates,
all hard no-root and no factor.

A direct full-size Z3 bit-vector multiplication sanity check using corrected
p-mask constraints and the base derived q low/high bits also did not solve:
`p_known_bits=672`, `q_known_bits=250`, `q_low_bits=150`,
`q_prefix_bits=100`; result was `unknown` after about 63 seconds.  This
confirms the direct BV formulation is not an immediate solve path.

Residual lattice preflight improved under corrected ranges.  All 7 active
unknown blocks remain strongly negative, but the gateway-style residual
`x2,x3,x4` model (corrected names: `362:58`, `600:69`, `682:87`) has a positive
proxy margin around `+84.9` bits for the current HM-like estimator.  That is
not a proof of solvability, but it makes a corrected residual-lattice fallback
worth implementing if q-gap can produce stronger branch ranking.

## 2026-06-06 Residual HM driver and cumulative x0+x7 q-gap drop

Added `branch_partial_coppersmith.py`, a candidate-JSON driver around
`tmp/crypto-attacks` `factorize_p`.  It rebuilds a `PartialInteger` from the
corrected p mask plus candidate fixed ranges, runs selected `(m,t)` attempts,
and verifies/decrypts if a factor is returned.

Smoke results on the first corrected q-gap 456 candidate:

```text
tmp/ct07_corrected_partial_coppersmith_smoke_m1/summary.json
tmp/ct07_corrected_partial_coppersmith_smoke_m2_timeout/summary.json
```

The candidate has 774 fixed p bits and four remaining unknown blocks
`[36,58,69,87]`.  `m=1,t=1` failed in about 1 second.  `m=2,t=1` is not a
cheap broad-batch filter: a manual run took about 35 seconds on the same false
candidate, and `m=3,t=1` hit the 600-second timeout.  Use this driver only for
short smoke tests or highly ranked finalists, not for blind q-gap batches.

A direct corrected 7-variable `crypto-attacks factorize_p` smoke also did not
solve: `m=2,t=1`, `m=3,t=1`, and `m=3,t=2` failed quickly; `m=4,t=1` failed
after about 340 seconds; `m=4,t=2` hit the 1200-second command timeout.  This
keeps the all-variable HM path below the q-gap/SAT-ledger priority.

The older `run_fullx1x5_drop_loop.py` now accepts `--resume-list` files, so
large learned-ledger sets no longer need huge command lines.

A new q-gap 408 cumulative minimization probe used the existing full-x1/full-x5
ledger set and tested dropping `150:4` and `920:4` together:

```text
tmp/ct07_fresh_fullx1x5_cumulative_drop_x0_x7_probe_eps004/iteration_0001.jsonl
```

Result: no factor.  The cube was hard q-gap no-root with `q_gap_bits=408`,
`epsilon=0.04`.  All `16/16` completions after dropping `150:4` and then
`256/256` combined completions after also dropping `920:4` were hard no-root.
The learned clause drops 8 bits and keeps 130 literals.  This is stronger than
the previous independent drop mode, which could drop x0 or x7 separately but
did not prove the pair jointly removable.

A 3-iteration continuation:

```text
tmp/ct07_fresh_fullx1x5_cumulative_drop_x0_x7_after_probe_iter3_eps004/loop_summary.json
```

also found no factor.  It closed three more full-x1/full-x5 q-gap 408 cubes,
all with the same 8 dropped bits and 130-literal hard clauses:

```text
265:84 = 768, 512, 1024
784:46 = 0
```

The three iterations took 108.6 seconds total with 8 workers.  This cumulative
`x0+x7` drop line is now the best SAT-ledger continuation among the existing
q-gap 408 paths because it generalizes over both edge nibbles at once while
remaining much cheaper than the earlier medium byte-drop set.

A 20-iteration continuation:

```text
tmp/ct07_fresh_fullx1x5_cumulative_drop_x0_x7_iter20_eps004/loop_summary.json
tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt
```

also found no factor.  It closed 20 more q-gap 408 cubes in 636.6 seconds.
Every row was hard no-root, every row proved the same cumulative `150:4` plus
`920:4` drop, and every learned clause kept 130 literals after dropping 8 edge
nibble bits.  The closed `265:84` representatives were:

```text
1536, 1280, 1792, 3584, 3840, 2560, 2816, 2048, 3072, 2304,
3328, 4864, 4608, 4352, 4096, 6656, 6144, 6400, 6912, 5632
```

All used `784:46 = 0` as the representative high-side assignment.  The
cumulative resume manifest now contains the probe, 3-iteration continuation,
and these 20 ledgers, and all listed JSONL paths exist.  A dry-run with both
resume manifests succeeded:

```bash
--resume-list tmp/ct07_fullx1x5_resume_all_jsonl.txt
--resume-list tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt
```

## 2026-06-06 Edge-bruteforced coarse HM sweeps

Added `edge_partial_coppersmith_sweep.py` to sweep the two corrected 4-bit edge
unknowns `150:4` and `920:4` while running `crypto-attacks` `factorize_p` on
different partial-p models.  It verifies and decrypts if a factor is returned.

Exact 5-variable model with only the two edge nibbles fixed:

```text
tmp/ct07_corrected_edge_sweep_full_m2_t1/summary.json
```

Result: no factor.  All 256 edge assignments with `m=2,t=1` completed in about
10.5 seconds.  A single `m=3,t=1` edge sample timed out at 300 seconds, so this
exact 5-variable model is not a broad sweep candidate at higher m.

Two coarsened 2-variable models were then tested across all 256 edge
assignments:

```text
middle_x5:     unknown [265,769) as 504 bits plus x5=784:46
x1_middle362: x1=265:84 plus unknown [362,830) as 468 bits
```

The full sweeps:

```text
tmp/ct07_corrected_edge_sweep_middle_x5_m1_8_t1_2/summary.json
tmp/ct07_corrected_edge_sweep_x1_middle362_m1_8_t1_2/summary.json
tmp/ct07_corrected_edge_sweep_middle_x5_m10_t1_2/summary.json
tmp/ct07_corrected_edge_sweep_x1_middle362_m10_t1_2/summary.json
```

all found no factor.  The `m=1..8, t=1..2` grids each covered 4096
edge/model-parameter tasks; the `m=10, t=1..2` extensions each covered 512
more tasks.  Higher m is not attractive for broad search: false-edge samples
around `m=12` took tens of seconds, `m=14` took about 73-106 seconds, and
`m=16` was too slow for a full edge sweep.

Conclusion: edge-bruteforced coarse HM is a useful checked negative direction,
but it did not solve the corrected instance.  Keep the q-gap/SAT-ledger path
as primary unless a new lattice construction uses the internal known bits
without only coarsening them away.

## 2026-06-06 Folded p/q Coron candidate checks

Added `branch_pq_coron.py`, a folded p/q bivariate Coron driver.  For any
branch candidate, it builds one middle unknown for p between its contiguous
known low/high regions and one middle unknown for q between the derived q-low
and q-prefix regions, then runs `crypto-attacks` `factorize_pq` for selected
Coron `k` values.  It verifies/decrypts if a factor is returned.

False-branch sampling showed that edge+x5 branches have p/q gaps around
`504/505` bits; `k<=6` is quick, but `k=8` already ran for several minutes on a
false branch and was stopped.  For q-gap 456 candidates the folded gaps are
`456/456`; `k<=4` is fast, while `k=5` was already too slow for broad use and
was stopped after several minutes.

The useful broad check was therefore `k=1..4` on q-gap 456 candidates:

```text
tmp/ct07_corrected_pq_coron_top1_k1_4/summary.json
tmp/ct07_corrected_pq_coron_new64_k1_4/summary.json
tmp/ct07_corrected_pq_coron_new1024_k1_4/summary.json
```

Results: no factor.  The full `new1024` run checked all 1024 candidates from
`tmp/ct07_corrected_qgap_beams/qgap456_top512x2_top512x5_new_after_top128.json`
in 444.0 seconds.  Every candidate had folded p/q bounds `[456] / [456]`, and
all returned no factor for `k=1,2,3,4`.

Conclusion: folded p/q Coron is now available as a fast finalist cross-check at
small `k`, but it did not find a factor in the current q-gap 456 candidate pool.
Do not spend broad time on `k>=5` unless a branch is already very strongly
ranked.

## 2026-06-06 Hybrid q-gap 408 drop clauses

Added hybrid q-gap minimization support to `semi_programmatic_sat.py` and
`run_fullx1x5_drop_loop.py`.  The new mode keeps the successful cumulative
edge-nibble drop:

```text
150:4 + 920:4
```

and also verifies selected byte windows independently on the same q-gap 408
cube.  This creates multiple learned-clause variants from one Coppersmith
batch while preserving hard-clause discipline.

The first probe used the cumulative edge group plus only `265:8`:

```text
tmp/ct07_hybrid_drop_probe_edge_x2low8_eps004/loop_summary.json
```

Result: no factor.  Runtime was 55.3 seconds.  The cube had `q_gap_bits=408`
and produced two hard learned-clause variants:

```text
cumulative: 150:4 + 920:4, 8 dropped bits, 130 kept literals
independent: 265:8,       8 dropped bits, 130 kept literals
```

All 16 first-edge completions, all 256 combined-edge completions, and all 256
`265:8` completions were hard-eligible no-root results.

A full default hybrid probe then used:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

Output:

```text
tmp/ct07_hybrid_drop_probe_full_default_eps004/loop_summary.json
```

Result: no factor.  Runtime was 130.0 seconds.  It made 1297 q-gap
Coppersmith calls and produced five learned-clause variants, each dropping
8 selected bits and keeping 130 literals:

```text
1 cumulative edge clause
4 independent byte-drop clauses
```

Every completion in every tested window was hard-eligible no-root.  This is
strictly stronger per cube than the previous cumulative-edge-only run, at
about 3-4x the per-cube runtime.  The next broad batch should use this hybrid
mode when the aim is faster SAT-space contraction rather than raw cube count.

A five-cube continuation:

```text
tmp/ct07_hybrid_drop_iter5_after_probes_eps004/loop_summary.json
tmp/ct07_hybrid_drop_after_probes_iter5_jsonl.txt
```

also found no factor.  It ran for 656.3 seconds total.  Each of the five cubes
had `q_gap_bits=408`, made 1297 q-gap Coppersmith calls, and produced the same
five hard learned-clause variants:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

The additional closed `265:84` representatives were:

```text
8192, 10240, 6144, 5120, 14336
```

all with `784:46 = 0`.  This brings the verified hybrid q-gap 408 evidence to
seven post-implementation cubes including the two probes.  No solver process
was left running after the batch.

The wrapper now exposes `--q-gap-oracle-timeout-seconds`.  The default remains
`0` to preserve prior behavior.  Use a nonzero value only when a long batch
gets stuck on a small number of slow Sage calls; a timeout completion is not a
hard no-root and therefore prevents the corresponding generalized drop clause.

JM low-lift diagnostics were also checked on corrected constants using
`tmp/crypto-attacks`:

```text
python3 cryptotest/solutions/solve_07_jm_lowlift.py \
  --crypto-attacks tmp/crypto-attacks \
  --branch-low 0 --branch-high 0 --diagnose-only
```

The corrected model reduced the stale `210:39` run to a constant and the old
`362:78` run to the actual `362:58` unknown span.  The variable bounds were:

```text
u2=84, u3=58, u4=69, u5=87, b=46, Y=567
```

with 12 terms, degree 2, and `Wbits=1591`.  Small `m=1` and `m=2` attempts on
the false `x0=0,x7=0` branch failed inside `crypto-attacks` root extraction
with `IndexError`; `ext_u2` took 57.5 seconds and `ext_b` took 85.8 seconds
before the same failure.  This is not useful broad search evidence, and this
JM low-lift path should stay diagnostic unless the polynomial/root extraction
is fixed or a planted test proves a viable parameter set.

## 2026-06-06 CP-SAT tail edge-free probe

Added optional edge-branch freeing to the corrected CP-SAT exact-tail
prototype:

```text
cryptotest/solutions/try_07_hensel_tail_cp_sat.py
  --free-branch-low
  --free-branch-high
```

The default behavior still fixes `p[150..153]` and `p[920..923]` from
`--branch-low` and `--branch-high`.  With `T=928`, `--free-branch-high` keeps
`x7` inside the lower exact-tail model instead of splitting it into 16 separate
runs.  A build-only check for `x0=0, x7=free` produced:

```text
T=928, tail_limbs=70, q_low=265, q_prefix_start=924
p unknown bools in T: 348
q fixed bits in T: 269
q variable limbs: 42
tail low-low product vars: 888
final carry zero enforced: true
```

For comparison, fixed `x7=0` at the same `T=928` has stronger q high prefix
data (`q_prefix_start=832`, `q fixed bits in T=361`, `q variable limbs=36`)
but covers only one of the 16 x7 values.

Added a resumable sweep runner:

```text
cryptotest/solutions/run_07_tail_cp_sat_edge_sweep.py
```

It sweeps selected `x0` nibbles with `x7` free, writes one log per run, appends
`manifest.jsonl`, stops immediately if a factor/plaintext is emitted, and
supports `--resume`.

Smoke logs:

```text
tmp/ct07_tail_cpsat_free_x7_smoke
tmp/ct07_tail_cpsat_free_x7_decision_x7_smoke
tmp/ct07_tail_cpsat_free_x7_x0_0_3_seed7_probe
```

Results so far:

```text
x0 in {0,1,2,3}, x7 free, seed 7, time_limit=10
runs: 4
status: all UNKNOWN
factor: none
total CP-SAT wall time: 59.15s
average CP-SAT wall time: 14.79s
branches: 154009
conflicts: 8156
```

The first `x0=0` run took about 29 seconds despite the nominal 10-second
CP-SAT limit; the other three returned in about 10 seconds each.  An explicit
`--decision-p-range 920:4` probe was slower (about 33 seconds on `x0=0`), so
do not use it by default.

This CP-SAT path has not solved the instance.  Its current value is operational:
it can cover all 256 edge-nibble assignments as 16 `x0` models when searching
for a direct feasible tail solution.  It is not a hard proof/pruning engine
unless CP-SAT proves `INFEASIBLE`; the observed statuses are only `UNKNOWN`.

A full shallow seed-7 pass was then run:

```text
tmp/ct07_tail_cpsat_free_x7_full_seed7_t10
```

Command shape:

```text
T=928, x0=0..15, x7 free, seed=7, time_limit=10, workers=8
compact q limbs, 6 small-prime filters, 6 odd-residue filters
```

Result:

```text
runs: 16
status: all UNKNOWN
factor: none
total CP-SAT wall time: 195.58s
average CP-SAT wall time: 12.22s
max CP-SAT wall time: 20.77s
branches: 247599
conflicts: 14095
```

This covers all `x0+x7` edge nibbles in a shallow direct solve attempt.  It did
not find a factor, and because every status was `UNKNOWN`, it does not close
any branch.

The sweep runner now forwards `--lowlift-q`.  Three full shallow seed-7 passes
were compared:

```text
baseline:      total wall 195.58s, branches 247599, conflicts 14095
lowlift q265: total wall 172.09s, branches 141533, conflicts 4459
lowlift q272: total wall 172.06s, branches 175560, conflicts 19799
```

All 48 shallow runs returned `UNKNOWN` and no factor.  The `q265` low-lift
variant was the lightest of the three on branch/conflict count, despite using
q bit BoolVars instead of compact q limbs.

A deeper multi-seed direct-hit probe was then run with `q265` low-lift:

```text
tmp/ct07_tail_cpsat_free_x7_full_seeds7_13_23_t30_lowlift265
```

Command shape:

```text
T=928, x0=0..15, x7 free, seeds=7,13,23, time_limit=30, workers=8
lowlift-q=265, compact q limbs disabled
```

Result:

```text
runs: 48
status: all UNKNOWN
factor: none
total CP-SAT wall time: 1504.11s
average CP-SAT wall time: 31.34s
max CP-SAT wall time: 37.96s
branches: 852177
conflicts: 77505
```

This still produced no feasible factor candidate and no `INFEASIBLE` branch
closures.  Treat CP-SAT tail probing as a cheap secondary direct-solve oracle;
do not spend the main search budget here unless a stronger exact-tail
constraint or branching strategy is added.

## 2026-06-06 Guarded q-gap cube assumptions

Added guarded cube-assumption support to `semi_programmatic_sat.py`:

```text
--cube-assume-p-range START:WIDTH:VALUE
```

These are temporary Z3 assumptions used only for cube selection.  The assumed
bits are also included in the emitted `cube_ranges`, so any learned q-gap
no-root clause remains guarded by the bits that made the branch true.  This is
safer than using `--fix-p-range` for x6 diversification, because fixed ranges
were not previously represented in learned clause records.

`run_fullx1x5_drop_loop.py` now forwards static assumptions and also supports
iteration cycles:

```text
--cube-assume-p-range 784:4:0xf
--cube-assume-p-range-cycle 784:4:0x1,0x2,0xf
```

Smoke check:

```text
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:8,784:4,920:4 \
  --cube-assume-p-range 784:4:0xf \
  --include-cube-ranges
```

emitted `cube_ranges` with `784:4 = 0xf`, confirming the guard is present.

A real hybrid q-gap probe was then run:

```text
tmp/ct07_hybrid_drop_assume_x6low4_f_probe_eps004
```

Command shape:

```text
resume prior q-gap ledgers
drop-mode hybrid
cube-assume-p-range 784:4:0xf
q-gap epsilon 0.04, max bits 462
```

Result:

```text
factor: none
runtime: 152.46s
q_gap_bits: 409
q_gap_status: no_roots
q_gap hard blocks: 1
q_gap calls: 1297
learned variants: 5
loaded learned clauses: 382
```

The closed cube had:

```text
150:4 = 1
265:84 = 0
784:46 = 15
920:4 = 0
```

and produced the same five hard learned-clause variants as the default hybrid
probe:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

Each tested completion set was hard-eligible no-root.  This confirms x6
diversification can be done safely by assumption, but the observed `q_gap_bits`
rose from 408 to 409 and runtime was a bit slower than the default hybrid
probe.  Use cycles for coverage diversity, not because they are faster.

Then ran a five-iteration guarded x6 low-nibble cycle:

```text
tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004
```

Command shape:

```text
resume prior q-gap ledgers plus the 784:4=0xf probe
drop-mode hybrid
cube-assume-p-range-cycle 784:4:0x1,0x2,0x3,0x4,0x5
q-gap epsilon 0.04, max bits 462
```

Result:

```text
factor: none
iterations: 5
total elapsed: 720.79s
average elapsed: 144.16s
total q-gap calls: 6485
```

Per-iteration summary:

```text
assumption  cube ranges                              q_gap  status    variants
784:4=1     150:4=2, 265:84=0, 784:46=1, 920:4=0    408    no_roots  5
784:4=2     150:4=3, 265:84=0, 784:46=2, 920:4=0    409    no_roots  5
784:4=3     150:4=4, 265:84=0, 784:46=3, 920:4=0    412    no_roots  5
784:4=4     150:4=6, 265:84=0, 784:46=4, 920:4=0    407    no_roots  5
784:4=5     150:4=5, 265:84=0, 784:46=5, 920:4=0    408    no_roots  5
```

All five cubes produced the same five hybrid hard learned-clause variants:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

No factor was found.  This batch confirms that guarded assumptions can force
nonzero x6 low-nibble coverage and still produce hard q-gap clauses.  It also
shows the branch still prefers `265:84 = 0`; the next branch-diversity target
should include x2 bytes or use a ranker rather than only cycling x6.

Next ran a five-iteration guarded x2 low-byte cycle:

```text
tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004
```

Command shape:

```text
resume prior q-gap ledgers, x6low4 0xf probe, and x6low4 1..5 cycle
drop-mode hybrid
cube-assume-p-range-cycle 265:8:0x1,0x2,0x3,0x4,0x5
q-gap epsilon 0.04, max bits 462
```

Result:

```text
factor: none
iterations: 5
total elapsed: 781.90s
average elapsed: 156.38s
total q-gap calls: 6485
```

Per-iteration summary:

```text
assumption  cube ranges                                q_gap  status    variants
265:8=1     150:4=1, 265:84=513, 784:46=0, 920:4=0    408    no_roots  5
265:8=2     150:4=1, 265:84=258, 784:46=0, 920:4=0    408    no_roots  5
265:8=3     150:4=2, 265:84=259, 784:46=0, 920:4=0    408    no_roots  5
265:8=4     150:4=3, 265:84=260, 784:46=0, 920:4=0    408    no_roots  5
265:8=5     150:4=4, 265:84=261, 784:46=0, 920:4=0    408    no_roots  5
```

All five cubes again produced the same five hybrid hard learned-clause
variants:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

No factor was found.  This confirms x2 low-byte diversification is also safe
and productive for hard ledgers.  It also shows the branch reverts to
`784:46 = 0`, so the next coverage batch should cycle x2 and x6 together, or
replace manual cycles with a q-gap/product-prefix ranker.

Then ran the combined x2 low-byte plus x6 low-nibble cycle:

```text
tmp/ct07_hybrid_drop_x2low8_x6low4_cycle_eps004
```

Command shape:

```text
resume prior q-gap ledgers, x6low4 0xf probe, x6low4 1..5 cycle,
and x2low8 1..5 cycle
drop-mode hybrid
cube-assume-p-range-cycle 265:8:0x6,0x7,0x8,0x9,0xa
cube-assume-p-range-cycle 784:4:0x6,0x7,0x8,0x9,0xa
q-gap epsilon 0.04, max bits 462
```

Result:

```text
factor: none
iterations: 5
total elapsed: 696.48s
average elapsed: 139.30s
total q-gap calls: 6485
```

Per-iteration summary:

```text
assumptions              cube ranges                              q_gap  status    variants
265:8=6 + 784:4=6       150:4=2, 265:84=6, 784:46=6, 920:4=0     407    no_roots  5
265:8=7 + 784:4=7       150:4=2, 265:84=7, 784:46=7, 920:4=0     409    no_roots  5
265:8=8 + 784:4=8       150:4=2, 265:84=8, 784:46=8, 920:4=0     410    no_roots  5
265:8=9 + 784:4=9       150:4=2, 265:84=9, 784:46=9, 920:4=0     408    no_roots  5
265:8=10 + 784:4=10     150:4=2, 265:84=10, 784:46=10, 920:4=0   408    no_roots  5
```

All five cubes produced the same five hybrid hard learned-clause variants:

```text
cumulative: 150:4 + 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

No factor was found.  This confirms simultaneous guarded assumptions work and
are slightly faster than the separate x2-only cycle, but the branch still stays
near small literal representatives.  The next useful step is not simply more
manual cycles; build a q-gap/product-prefix ranker or use diagonal cycles that
are selected by an actual score.

Added a q-gap assumption-pair ranker and fast hit-first runner:

```text
cryptotest/solutions/07_sat_cas_explore/rank_q_gap_assumption_pairs.py
cryptotest/solutions/07_sat_cas_explore/run_ranked_q_gap_hits.py
```

The ranker loads the hard learned JSONL ledgers once, checks candidate
`(265:8, 784:4)` assumptions with Z3, evaluates the actual full cube chosen by
the model, and ranks by product-prefix status, q-gap size, q-known bits,
interval width, and prior pair novelty.  The hit runner then calls the q-gap
Coppersmith oracle once per ranked pair before doing any expensive clause
minimization.

First generated:

```text
tmp/ct07_ranked_qgap_pairs_top128_after_cycles.json
```

Then ran the top 128 ranked hit-first probes in two batches:

```text
tmp/ct07_ranked_qgap_hits_top16_after_cycles
tmp/ct07_ranked_qgap_hits_rank17_128_after_cycles
```

Result:

```text
factor: none
records: 128
total elapsed: 510.41s
average elapsed: about 3.99s
q-gap calls: 128
q-gap distribution: 407 -> 128
x6 distribution: 0x4 -> 64, 0x6 -> 64
```

This showed the raw ranker was too concentrated on the best q-gap line.  Added
diversity caps to the ranker and generated:

```text
tmp/ct07_ranked_qgap_pairs_diverse64_after_top128_hits.json
```

using `--max-per-x6-value 4 --max-per-x2-value 2`, with the 128 hit-first
JSONLs loaded so those pairs were excluded.  Then ran:

```text
tmp/ct07_ranked_qgap_hits_diverse64_after_top128
```

Result:

```text
factor: none
records: 64
total elapsed: 298.50s
average elapsed: 4.66s
q-gap calls: 64
q-gap distribution: 407 -> 8, 408 -> 28, 409 -> 16, 410 -> 8, 412 -> 4
x6 distribution: every nibble 0x0..0xf appeared exactly 4 times
```

Combined ranked hit-first evidence is now:

```text
factor: none
ranked q-gap hit probes: 192
q-gap Coppersmith calls: 192
```

These hit-first no-roots are hard q-gap clauses for the exact full selected
cubes, but they are not minimized.  The result weakens the case for more
unminimized q-gap 407/408 sweeps as a hit strategy.  Next useful work should
either run hybrid minimization only for selected representatives, or improve
the ranker with a stronger signal than q-gap width alone.

Added a faster direct q-gap runner:

```text
cryptotest/solutions/07_sat_cas_explore/run_ranked_q_gap_direct.py
```

This consumes the full `cube_ranges` already emitted by the ranker and calls
the q-gap Coppersmith oracle directly, in parallel, without re-running
`semi_programmatic_sat.py` or reloading all learned ledgers for every row.  It
can also emit JSONL cube records compatible with `--load-learned-jsonl`.

Smoke result:

```text
tmp/ct07_ranked_qgap_direct_diverse64_smoke.json
records: 8
factor: none
elapsed: 2.10s
status: no_roots for all 8
```

Then created:

```text
tmp/ct07_ranked_qgap_hits_top192_jsonl.txt
```

from the earlier 192 subprocess hit-first JSONLs, generated the next top 512
ranked rows after excluding those, and ran:

```text
tmp/ct07_ranked_qgap_direct_after_top192_top512.json
tmp/ct07_ranked_qgap_direct_after_top192_top512.jsonl
```

Result:

```text
factor: none
records: 512
elapsed: 57.43s
status: no_roots for all 512
q-gap distribution: 407 -> 374, 408 -> 138
```

Finally generated the remaining ranked rows after excluding the previous 704
hit-first records:

```text
tmp/ct07_ranked_qgap_pairs_after_704_all_remaining.json
```

and ran:

```text
tmp/ct07_ranked_qgap_direct_after_704_all_remaining.json
tmp/ct07_ranked_qgap_direct_after_704_all_remaining.jsonl
```

Result:

```text
factor: none
records: 3341
elapsed: 340.40s
status: no_roots for all 3341
q-gap distribution: 408 -> 1582, 409 -> 1005, 410 -> 503, 412 -> 251
```

Combined ranked one-model q-gap coverage is now:

```text
factor: none
records: 4045
status: no_roots for all 4045
summed elapsed: 1207.18s
q-gap distribution: 407 -> 510, 408 -> 1748, 409 -> 1021, 410 -> 511, 412 -> 255
x6 distribution: near-complete balance across 0x0..0xf
```

This is not a proof that the instance is unsolved under all pairs.  It means
the first SAT-selected full edge cube for every currently satisfiable
`(265:8, 784:4)` pair failed q-gap Coppersmith.  The emitted JSONLs are useful
hard ledgers for moving the SAT solver to second/third models per pair.

## No-Drop Next-Model Probe After Direct Ledgers

`run_fullx1x5_drop_loop.py --drop-mode none` was added so the loop can skip
minimization and add only the full selected q-gap no-root clause.  This is
intended for fast layer advancement after the direct ranked ledgers.

Probe:

```text
tmp/ct07_qgap_nodrop_after_direct4045_probe
iterations: 3
factor: none
elapsed: 74.66s
loaded clauses at first iteration: 4427
```

The three next SAT-selected full edge cubes were:

```text
150:4=8,  265:84=10496, 784:46=0, 920:4=0 -> q_gap=408, no_roots
150:4=10, 265:84=10496, 784:46=0, 920:4=0 -> q_gap=408, no_roots
150:4=9,  265:84=10496, 784:46=0, 920:4=0 -> q_gap=408, no_roots
```

Each call was hard-eligible, emitted a full 138-literal q-gap selected-bits
clause, and returned no roots.  This confirms that the first-model layer is
not the only layer available; the SAT+ledger loop can continue producing
second/third models, but no factor has been recovered yet.

## Include-Seen Next-Model Direct Layers

After the 4045 first-model hard ledgers and the 3 no-drop next-model ledgers,
the ranker was rerun with `--include-seen-pairs` so it would ask Z3 for the
next full edge model under already-seen `(265:8, 784:4)` pairs.

First include-seen batch:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4048_top256.json
loaded clauses: 4430
sat pairs: 4095 / 4096

tmp/ct07_ranked_qgap_direct_include_seen_after4048_top256.json
records: 256
factor: none
elapsed: 73.00s
status: no_roots for all 256
q-gap distribution: 407 -> 32, 408 -> 112, 409 -> 64, 410 -> 32, 412 -> 16
x6_low4 distribution: exactly 16 per value
```

Second include-seen batch:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4304_top512.json
loaded clauses: 4686
sat pairs: 4095 / 4096

tmp/ct07_ranked_qgap_direct_include_seen_after4304_top512.json
records: 512
factor: none
elapsed: 165.39s
status: no_roots for all 512
q-gap distribution: 407 -> 64, 408 -> 224, 409 -> 128, 410 -> 64, 412 -> 32
x6_low4 distribution: exactly 32 per value
```

New direct/no-drop progress in this pass:

```text
additional hard no-root cubes: 771
factor: none
q-gap distribution: 407 -> 96, 408 -> 339, 409 -> 192, 410 -> 96, 412 -> 48
```

The include-seen ranker remains useful as a layer-advancement tool, but full
no-drop clauses are still very local.  The next useful check is small, targeted
minimization rather than only accumulating more full 138-literal clauses.

## Post-4816 Minimization Probe

The current q-gap ledgers were collected in:

```text
tmp/ct07_current_qgap_ledgers_after4816.txt
```

A full hybrid minimization attempt on representative pair
`265:8=0x00, 784:4=0x4` was started at:

```text
tmp/ct07_hybrid_after4816_x2_00_x6_4_probe
```

It was manually stopped after several minutes because it had only loaded
clauses and had not emitted a cube result.  That partial JSONL is not used as
a hard ledger.

The same representative pair was then tested with only edge drop windows:

```text
tmp/ct07_edge_drop_after4816_x2_00_x6_4_probe
factor: none
elapsed: 32.50s
q_gap_bits: 407
q-gap oracle calls: 17
loaded clauses: 5198
```

Result:

```text
selected cube: 150:4=4, 265:84=0, 784:46=4, 920:4=0
learned scope: minimized_q_gap_selected_bits
learned literals: 134
dropped bits: 150,151,152,153
```

So `x0` can be soundly dropped for this representative.  Dropping `x7` in the
same cumulative clause would require 256 completions and was skipped by the
current cap of 64.  This suggests the next minimization pass should use
edge-only or small-window clauses first, and reserve full hybrid byte-window
minimization for a few high-repetition representatives only.

## Edge-Minimization Queue

Added:

```text
run_edge_minimization_queue.py
```

The queue consumes a rank JSON, runs `run_fullx1x5_drop_loop.py` once per
ranked representative with edge-only cumulative minimization, and appends each
successful JSONL to the ledger list for later queue items.

First batch:

```text
tmp/ct07_edge_min_queue_after4817_top4_rank2
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4304_top512.json
start rank: 2
records: 4
factor: none
elapsed: 175.24s
```

All four representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 2: x2_low8=0x06, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x10, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x10, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x11, x6_low4=0x4 -> q_gap=407, learned literals=134
dropped bits for all four: 150,151,152,153
q-gap calls per representative: 17
```

The updated manifest is:

```text
tmp/ct07_current_qgap_ledgers_after4821_edge_queue.txt
ledgers: 316
```

Reranking with this manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4821_edge_top256.json
loaded clauses: 5203
sat pairs: 4095 / 4096
```

The top rank shifted away from the newly edge-minimized representatives to
later `x2_low8` values, starting at `0x2f` with `x6_low4` in `{0x4,0x6}`.
This confirms that edge-minimized clauses are being loaded and changing the
next SAT-selected layer, although the overall pair-level space remains broad.

`run_edge_minimization_queue.py` now also supports `--manifest-output`, so a
longer queue can keep writing the cumulative ledger manifest after each
completed representative.  That avoids losing the resume list if the queue is
stopped between items.

Second batch:

```text
tmp/ct07_edge_min_queue_after4821_top6_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4821_edge_top256.json
start rank: 1
records: 6
factor: none
elapsed: 208.69s
manifest: tmp/ct07_current_qgap_ledgers_after4827_edge_queue.txt
ledgers: 322
```

All six representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x2f, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x2f, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x30, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x30, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x31, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x31, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all six: 150,151,152,153
q-gap calls per representative: 17
```

This brings the edge-minimized queue evidence to 11 representatives total:
one manual probe, four from the first queue batch, and six from the second
queue batch.  Every completed representative has generalized over the `x0`
nibble, and no factor has been recovered.

Reranking with the 322-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4827_edge_top256.json
loaded ledger files: 322
candidate clause records: 5214
clauses added: 5209
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The top layer shifted again to `x2_low8` values beginning at `0x32`, still
mostly paired with `x6_low4` in `{0x4,0x6}` at `q_gap_bits=407`.

Third edge queue batch:

```text
tmp/ct07_edge_min_queue_after4827_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4827_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 284.52s
manifest: tmp/ct07_current_qgap_ledgers_after4835_edge_queue.txt
ledgers: 330
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x32, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x32, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x33, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x33, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x34, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x34, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x35, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x35, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

The edge-minimized evidence is now 19 representatives total: one manual probe
plus 4, 6, and 8 queue items.  Every completed representative generalized over
the `x0` nibble, and no factor has been recovered.

Reranking with the 330-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4835_edge_top256.json
loaded ledger files: 330
candidate clause records: 5222
clauses added: 5217
evaluated pairs: 4096
SAT pairs: 4095
unknown pairs: 1
```

The next top layer moved to `x2_low8=0x36..` with the same `{0x4,0x6}`
`x6_low4` pair at `q_gap_bits=407`.

Fourth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4835_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4835_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 309.51s
manifest: tmp/ct07_current_qgap_ledgers_after4843_edge_queue.txt
ledgers: 338
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x36, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x36, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x37, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x37, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x38, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x38, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x39, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x39, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

The edge-minimized evidence is now 27 representatives total: one manual probe
plus 4, 6, 8, and 8 queue items.  Every completed representative generalized
over the `x0` nibble, and no factor has been recovered.

Reranking with the 338-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4843_edge_top256.json
loaded ledger files: 338
candidate clause records: 5230
clauses added: 5225
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The next top layer moved to `x2_low8=0x3a..` with `x6_low4` still in
`{0x4,0x6}` at `q_gap_bits=407`.

Fifth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4843_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4843_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 320.93s
manifest: tmp/ct07_current_qgap_ledgers_after4851_edge_queue.txt
ledgers: 346
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x3a, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x3a, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x3b, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x3b, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x3c, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x3c, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x3d, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x3d, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

The edge-minimized evidence is now 35 representatives total: one manual probe
plus 4, 6, 8, 8, and 8 queue items.  Every completed representative
generalized over the `x0` nibble, and no factor has been recovered.

Reranking with the 346-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4851_edge_top256.json
loaded ledger files: 346
candidate clause records: 5238
clauses added: 5233
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The next top layer moved to `x2_low8=0x3e..` with the same `{0x4,0x6}`
`x6_low4` pair at `q_gap_bits=407`.

Sixth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4851_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4851_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 326.47s
manifest: tmp/ct07_current_qgap_ledgers_after4859_edge_queue.txt
ledgers: 354
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x3e, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x3e, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x3f, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x3f, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x40, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x40, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x41, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x41, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

The edge-minimized evidence is now 43 representatives total: one manual probe
plus 4, 6, 8, 8, 8, and 8 queue items.  Every completed representative
generalized over the `x0` nibble, and no factor has been recovered.

Reranking with the 354-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4859_edge_top256.json
loaded ledger files: 354
candidate clause records: 5246
clauses added: 5241
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The next top layer moved to `x2_low8=0x42..` with `x6_low4` still in
`{0x4,0x6}` at `q_gap_bits=407`.  This confirms that the latest edge clauses
are loaded and continue moving the frontier; no factor/plaintext has been
recovered.

Seventh edge queue batch:

```text
tmp/ct07_edge_min_queue_after4859_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4859_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 279.89s
manifest: tmp/ct07_current_qgap_ledgers_after4867_edge_queue.txt
ledgers: 362
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x42, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x42, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x43, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x43, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x44, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x44, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x45, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x45, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

Reranking with the 362-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4867_edge_top256.json
loaded ledger files: 362
candidate clause records: 5254
clauses added: 5249
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The next top layer moved to `x2_low8=0x46..` with `x6_low4` still in
`{0x4,0x6}` at `q_gap_bits=407`.

Eighth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4867_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4867_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 270.55s
manifest: tmp/ct07_current_qgap_ledgers_after4875_edge_queue.txt
ledgers: 370
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x46, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x46, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x47, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x47, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x48, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x48, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x49, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x49, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

Reranking with the 370-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4875_edge_top256.json
loaded ledger files: 370
candidate clause records: 5262
clauses added: 5257
evaluated pairs: 4096
SAT pairs: 4046
unknown pairs: 50
```

The edge-minimized evidence is now 59 representatives total: one manual probe
plus 4, 6, and seven 8-item queue batches.  Every completed representative
generalized over the `x0` nibble, and no factor has been recovered.  The latest
rerank shows the first meaningful drop in evaluated SAT pairs, from 4094 to
4046, while the next top layer remains `x2_low8=0x4a..0x4d`,
`x6_low4={0x4,0x6}`, `q_gap_bits=407`.

Ninth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4875_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4875_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 288.25s
manifest: tmp/ct07_current_qgap_ledgers_after4883_edge_queue.txt
ledgers: 378
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x4a, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x4a, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x4b, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x4b, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x4c, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x4c, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x4d, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x4d, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

Reranking with the 378-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4883_edge_top256.json
loaded ledger files: 378
candidate clause records: 5270
clauses added: 5265
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The previous 370-ledger `4046` SAT count did not persist after this rerank, so
that should be treated as a rank/check interaction rather than a stable global
space reduction.  The top layer continued walking forward to
`x2_low8=0x4e..0x51`, `x6_low4={0x4,0x6}`, `q_gap_bits=407`.

Tenth edge queue batch:

```text
tmp/ct07_edge_min_queue_after4883_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4883_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 260.25s
manifest: tmp/ct07_current_qgap_ledgers_after4891_edge_queue.txt
ledgers: 386
```

All eight representatives were hard q-gap no-root and soundly dropped `x0`:

```text
rank 1: x2_low8=0x4e, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 2: x2_low8=0x4e, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 3: x2_low8=0x4f, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 4: x2_low8=0x4f, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 5: x2_low8=0x50, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 6: x2_low8=0x50, x6_low4=0x6 -> q_gap=407, learned literals=134
rank 7: x2_low8=0x51, x6_low4=0x4 -> q_gap=407, learned literals=134
rank 8: x2_low8=0x51, x6_low4=0x6 -> q_gap=407, learned literals=134
dropped bits for all eight: 150,151,152,153
q-gap calls per representative: 17
```

Reranking with the 386-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4891_edge_top256.json
loaded ledger files: 386
candidate clause records: 5278
clauses added: 5273
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The edge-minimized evidence is now 75 representatives total: one manual probe,
then queue batches of 4, 6, and nine 8-item batches.  No factor/plaintext has
been recovered.  The latest top layer is `x2_low8=0x52..0x55` with
`x6_low4={0x4,0x6}` at `q_gap_bits=407`.

Eleventh x0-only edge queue batch:

```text
tmp/ct07_edge_min_queue_after4891_top8_rank1
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4891_edge_top256.json
start rank: 1
records: 8
factor: none
elapsed: 285.80s
manifest: tmp/ct07_current_qgap_ledgers_after4899_edge_queue.txt
ledgers: 394
```

All eight representatives were hard q-gap no-root and dropped only `x0`:

```text
rank 1: x2_low8=0x52, x6_low4=0x4 -> q_gap=407, calls=17, learned literals=134
rank 2: x2_low8=0x52, x6_low4=0x6 -> q_gap=407, calls=17, learned literals=134
rank 3: x2_low8=0x53, x6_low4=0x4 -> q_gap=407, calls=17, learned literals=134
rank 4: x2_low8=0x53, x6_low4=0x6 -> q_gap=407, calls=17, learned literals=134
rank 5: x2_low8=0x54, x6_low4=0x4 -> q_gap=407, calls=17, learned literals=134
rank 6: x2_low8=0x54, x6_low4=0x6 -> q_gap=407, calls=17, learned literals=134
rank 7: x2_low8=0x55, x6_low4=0x4 -> q_gap=407, calls=17, learned literals=134
rank 8: x2_low8=0x55, x6_low4=0x6 -> q_gap=407, calls=17, learned literals=134
dropped bits for all eight: 150,151,152,153
```

Reranking with the 394-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4899_edge_top256.json
loaded ledger files: 394
candidate clause records: 5286
clauses added: 5281
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

This confirms the x0-only queue is now mostly moving the top layer without a
stable global reduction.  The next top layer moved to `x2_low8=0x56..0x59`,
`x6_low4={0x4,0x6}`, `q_gap_bits=407`.

Small x0+x7 cumulative drop probe:

```text
tmp/ct07_edge_x0_x7_drop_probe_after4899_top2
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4899_edge_top256.json
records: 2
factor: none
elapsed: 221.95s
manifest: tmp/ct07_current_qgap_ledgers_after4901_x0_x7_probe.txt
ledgers: 396
```

Both representatives dropped both edge nibbles:

```text
rank 1: x2_low8=0x56, x6_low4=0x4 -> q_gap=407, calls=273, learned literals=130
rank 2: x2_low8=0x56, x6_low4=0x6 -> q_gap=407, calls=273, learned literals=130
dropped bits for both: 150,151,152,153,920,921,922,923
```

Reranking with the 396-ledger x0+x7 probe manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4901_x0_x7_top256.json
loaded ledger files: 396
candidate clause records: 5288
clauses added: 5283
evaluated pairs: 4096
SAT pairs: 4089
unknown pairs: 7
```

This is the first stable improvement after the x0-only plateau: only two
stronger edge clauses reduced SAT-ranked pairs from 4094 to 4089.

Follow-up x0+x7 cumulative drop batch:

```text
tmp/ct07_edge_x0_x7_drop_after4901_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4901_x0_x7_top256.json
records: 4
factor: none
elapsed: 466.93s
manifest: tmp/ct07_current_qgap_ledgers_after4905_x0_x7.txt
ledgers: 400
```

All four representatives again dropped both edge nibbles:

```text
rank 1: x2_low8=0x57, x6_low4=0x4 -> q_gap=407, calls=273, learned literals=130
rank 2: x2_low8=0x57, x6_low4=0x6 -> q_gap=407, calls=273, learned literals=130
rank 3: x2_low8=0x58, x6_low4=0x4 -> q_gap=407, calls=273, learned literals=130
rank 4: x2_low8=0x58, x6_low4=0x6 -> q_gap=407, calls=273, learned literals=130
dropped bits for all four: 150,151,152,153,920,921,922,923
```

Reranking with the 400-ledger x0+x7 manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4905_x0_x7_top256.json
loaded ledger files: 400
candidate clause records: 5292
clauses added: 5287
evaluated pairs: 4096
SAT pairs: 4063
unknown pairs: 33
```

The current best strategy should switch from x0-only to x0+x7 cumulative edge
minimization despite the higher cost.  Each representative costs about 273
q-gap calls instead of 17, but the resulting 130-literal clauses are actually
shrinking the ranked SAT frontier.  No factor/plaintext has been recovered.

### 2026-06-06 after4909/4912 hybrid q-gap probe

Continued from:

```text
tmp/ct07_current_qgap_ledgers_after4909_x0_x7.txt
ledgers: 404
tmp/ct07_ranked_qgap_pairs_include_seen_after4909_x0_x7_top256.json
loaded clauses: 5291
ranked SAT pairs: 4093
unknown pairs: 3
top layer: x2_low8=0x5b.., x6_low4={0x4,0x6}, q_gap=407
```

First, a single default hybrid q-gap minimization probe was run against the
top-ranked pair:

```text
tmp/ct07_hybrid_probe_after4909_rank1
assumptions: 265:8=0x5b, 784:4=0x4
factor: none
elapsed: 467.37s
q-gap calls: 1297
q-gap bits: 407
hard blocks: 1
learned clauses: 5
learned literals: 650
```

The five learned variants were:

```text
cumulative drop: 150:4 + 920:4 -> 130 literals
independent drop: 265:8 -> 130 literals
independent drop: 273:8 -> 130 literals
independent drop: 784:8 -> 130 literals
independent drop: 792:8 -> 130 literals
```

Reranking with this one extra hybrid ledger produced:

```text
tmp/ct07_current_qgap_ledgers_after4910_hybrid_rank1.txt
ledgers: 405
tmp/ct07_ranked_qgap_pairs_include_seen_after4910_hybrid_rank1_top256.json
loaded clauses: 5296
ranked SAT pairs: 3916
unknown pairs: 180
top layer: x2_low8=0x5b/0x5c/..., x6_low4={0x4,0x6}, q_gap=407
```

This was a strong positive signal for hybrid minimization, so the ranked queue
runner was extended to support `--drop-mode hybrid`, preserving its existing
cumulative default.  A two-item hybrid queue was then run from the after4910
rank file:

```text
tmp/ct07_hybrid_queue_after4910_top2
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4910_hybrid_rank1_top256.json
records: 2
factor: none
elapsed: 955.48s
manifest: tmp/ct07_current_qgap_ledgers_after4912_hybrid_top2.txt
ledgers: 407
```

Both queued representatives produced the same five hard variants:

```text
rank 1: x2_low8=0x5b, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650
rank 2: x2_low8=0x5c, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650
```

Reranking after these two additional hybrid ledgers produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4912_hybrid_top2_top256.json
loaded clauses: 5306
ranked SAT pairs: 4094
unknown pairs: 2
top layer: x2_low8=0x5c/0x5d/..., x6_low4={0x4,0x6}, q_gap=407
```

The `ranked SAT pairs` count is not a monotonic proof metric.  Adding hard
clauses can change which representative cube the ranker finds for the same
coarse `(x2_low8, x6_low4)` pair, and Z3 timeouts can also move records between
`unknown` and `sat`.  The reliable evidence is:

```text
1. The added ledgers are hard q-gap Coppersmith no-root clauses.
2. The top frontier moved from (0x5b,0x4) to (0x5c,0x6).
3. Hybrid minimization closes one ranked representative at about 1297 q-gap calls and 7.5-8.5 minutes.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 x0/x7 + x2/x3 nibble q-gap minimization probe

After 7680 full-cube scored-free q-gap direct checks, a one-cube hybrid
minimization probe was run on the stronger pwindow420 selected cube:

```text
output:
  tmp/ct07_pwindow420_minprobe_x0x7_x2x3nib_seed20260607
cube ranges:
  150:4,265:84,362:58,920:4
drop mode:
  hybrid
cumulative drop windows:
  150:4
  920:4
independent drop windows:
  265:4
  269:4
  362:4
  366:4
workers:
  8
q-gap epsilon:
  0.04
q-gap max bits:
  462
q-gap oracle timeout:
  120s
q-gap minimization max completions:
  256
resume manifests:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
elapsed:
  364.51s
exit:
  2, no factor
```

The run loaded 486 learned-ledger files and 27,542 hard clauses.  The sampled
cube had `q_low_bits=600`, `q_prefix_start=832`, `q_gap_bits=232`, and a large
hard margin.  The direct oracle returned no roots and no factor.

The useful result is that the no-root proof generalized:

```text
learned clause variants:
  cumulative 150:4 + 920:4:
    256/256 completions no_roots, 8 dropped literals, 142-literal clause
  independent 265:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 269:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 362:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 366:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
```

This JSONL was added to the scored q-gap manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Interpretation:

```text
1. The scored-free direct coverage remains 7680 full candidates, all hard
   q-gap no-roots, with no factor/plaintext.
2. The active pwindow420 scored manifest now has 18 JSONLs: 17 direct scored
   ledgers plus this one minimization ledger.
3. The minimization probe is more valuable than another plain direct batch:
   one representative produced 5 reusable generalized clauses.
4. The next bounded search should spend a small number of iterations on this
   hybrid minimization line, with more x2/x3 nibble windows, before returning
   to unminimized direct q-gap sweeps.
```

### 2026-06-07 pwindow420 expanded x2/x3 nibble minimization loop

The next one-iteration minimization loop reused the manifest that already
included the first pwindow420 minimization probe, then expanded the independent
x2/x3 nibble windows:

```text
output:
  tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more_seed20260607
iterations:
  1
cube ranges:
  150:4,265:84,362:58,920:4
cumulative drop windows:
  150:4
  920:4
independent drop windows:
  265:4
  269:4
  273:4
  277:4
  362:4
  366:4
  370:4
  374:4
workers:
  8
elapsed:
  457.50s
exit:
  2, no factor
```

It loaded 487 learned-ledger files and 27,547 hard clauses.  The selected cube
was:

```text
150:4 value 0xa
265:84 value 0x2600
362:58 value 0x0
920:4 value 0x0
q_low_bits: 600
q_prefix_start: 832
q_gap_bits: 232
direct q-gap status: no_roots
roots returned: 0
```

The direct Coppersmith call itself took about 2.35s; total time was dominated
by the 401 q-gap calls used for minimization.

All requested drops succeeded:

```text
learned clause variants:
  cumulative 150:4 + 920:4:
    256/256 completions no_roots, 8 dropped literals, 142-literal clause
  independent 265:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 269:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 273:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 277:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 362:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 366:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 370:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
  independent 374:4:
    16/16 completions no_roots, 4 dropped literals, 146-literal clause
```

This JSONL was also appended to:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Interpretation:

```text
1. No factor/plaintext has been recovered.
2. The active scored q-gap manifest now has 19 JSONLs: 17 direct ledgers and
   2 minimization ledgers.
3. The pwindow420 minimization line is currently productive: two
   representatives produced 14 generalized hard clauses total.
4. The next run should continue the same shape in 1-iteration chunks, but
   consider adding the next nibble windows only if the 401-call cost remains
   acceptable.
```

### 2026-06-07 pwindow420 third x2/x3 nibble minimization loop

A third one-iteration pwindow420 minimization loop was run with the same drop
shape, after appending the previous two pwindow420 minimization ledgers to the
manifest:

```text
output:
  tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more2_seed20260607
iterations:
  1
cube ranges:
  150:4,265:84,362:58,920:4
cumulative drop windows:
  150:4
  920:4
independent drop windows:
  265:4
  269:4
  273:4
  277:4
  362:4
  366:4
  370:4
  374:4
workers:
  8
elapsed:
  484.90s
exit:
  2, no factor
```

The run loaded 27,556 hard clauses and selected:

```text
150:4 value 0x8
265:84 value 0x2400
362:58 value 0x0
920:4 value 0x0
q_low_bits: 600
q_prefix_start: 832
q_gap_bits: 232
direct q-gap status: no_roots
roots returned: 0
```

It again made 401 q-gap calls and learned nine variants:

```text
  cumulative 150:4 + 920:4:
    256/256 completions no_roots, 142-literal clause
  independent 265:4,269:4,273:4,277:4:
    each 16/16 completions no_roots, each 146-literal clause
  independent 362:4,366:4,370:4,374:4:
    each 16/16 completions no_roots, each 146-literal clause
```

This JSONL was appended to:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Interpretation:

```text
1. No factor/plaintext has been recovered.
2. The active scored q-gap manifest now has 20 JSONLs: 17 direct ledgers and
   3 minimization ledgers.
3. The pwindow420 minimization line has now closed 3 representatives and
   produced 23 generalized hard clauses total.
4. Same-shape minimization remains productive but costs about 7.5-8.1 minutes
   per representative; the next work should either continue it in small chunks
   or build a cheaper sampler/ranker that targets new x0/x2 prefixes directly.
```

### 2026-06-07 manifest-output support for q-gap minimization loops

`run_fullx1x5_drop_loop.py` now supports:

```text
--manifest-output PATH
```

When this option is set, the runner writes the active learned-ledger manifest
after each completed iteration.  This keeps long pwindow420 minimization chunks
restartable without manually appending each `iteration_*.jsonl` to the manifest.
Paths are written relative to the workspace when possible.

Use this for the next pwindow420 minimization continuation:

```text
--manifest-output tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

### 2026-06-06 after4912/4916 hybrid top4 continuation

The recommended four-item hybrid queue from the after4912 rank file completed:

```text
tmp/ct07_hybrid_queue_after4912_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4912_hybrid_top2_top256.json
records: 4
factor: none
elapsed: 1922.01s
manifest: tmp/ct07_current_qgap_ledgers_after4916_hybrid_top4.txt
ledgers: 411
```

All four representatives returned hard q-gap no-root results with the same
five-variant hybrid clause pattern:

```text
rank 1: x2_low8=0x5c, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=461.75s
rank 2: x2_low8=0x5d, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=494.32s
rank 3: x2_low8=0x5d, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=510.26s
rank 4: x2_low8=0x5e, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=455.30s
```

Reranking with the 411-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4916_hybrid_top4_top256.json
loaded ledger files: 411
candidate clause records: 5331
clauses added: 5326
cube records: 5028
duplicate clauses: 5
literals added: 731800
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
top layer: x2_low8=0x5e/0x5f/0x60..., x6_low4={0x4,0x6}, q_gap=407
```

Interpretation:

```text
1. The hybrid top4 queue added 20 hard q-gap no-root clauses and no factor.
2. The top frontier advanced from x2_low8=0x5c to x2_low8=0x5e.
3. Cost remains stable: about 1297 q-gap calls and 455-510 seconds per representative.
4. The SAT-pair count remains a weak/non-monotonic signal; top-frontier movement and hard ledger count remain the useful operational metrics.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 diverse edge completion sampler

Added `sample_diverse_edge_completions.py`, a SAT-ledger sampler that takes a
ranked `(x2_low8,x6_low4)` frontier and requests multiple distinct full
`x0+x2+x6+x7` edge completions per low pair.  After each sampled full selected
cube it adds a local blocking clause, so repeated samples under the same low
pair are different full edge assignments.  The output is usable both by
`run_ranked_q_gap_direct.py` (`top`) and by residual partial-p candidate loaders
(`results` with `all_fixed_ranges_text`).

End-to-end smoke:

```text
tmp/ct07_diverse_edge_after4956_smoke_pairs2_k3.json
  source pairs: 2
  samples: 6
  source cube excluded: yes

tmp/ct07_qgap_direct_diverse_edge_after4956_smoke_pairs2_k3.json
  records: 6
  status: no factor
  q-gap statuses: no_roots=6
```

Main diverse q-gap sweeps:

```text
Cycle 1, top128 pairs, 4 alternates per pair:
  candidates:
    tmp/ct07_diverse_edge_after4956_top128_k4_excluding_source.json
    source pairs: 128
    sampled records: 512
    sampler elapsed: 17.71s
  q-gap direct:
    tmp/ct07_qgap_direct_diverse_edge_after4956_top128_k4_excluding_source.json
    records: 512
    elapsed: 197.76s
    status: no factor
    q-gap statuses: no_roots=512

Cycle 1, top512 pairs, 4 alternates per pair:
  candidates:
    tmp/ct07_diverse_edge_after4956_top512_k4_excluding_source.json
    source pairs: 512
    sampled records: 2048
    sampler elapsed: 102.43s
  q-gap direct:
    tmp/ct07_qgap_direct_diverse_edge_after4956_top512_k4_excluding_source.json
    records: 2048
    elapsed: 732.85s
    status: no factor
    q-gap statuses: no_roots=2048

Cycle 2, top128 pairs after loading direct no-root ledgers:
  manifest:
    tmp/ct07_current_qgap_ledgers_after_direct_diverse_20260607.txt
  candidates:
    tmp/ct07_diverse_edge_after_direct_diverse_top128_k4_cycle2.json
    source pairs: 128
    sampled records: 512
    sampler elapsed: 43.77s
  q-gap direct:
    tmp/ct07_qgap_direct_diverse_edge_after_direct_diverse_top128_k4_cycle2.json
    records: 512
    elapsed: 187.07s
    status: no factor
    q-gap statuses: no_roots=512

Cycle 3, all 4090 SAT low pairs, 1 new alternate per pair:
  manifest:
    tmp/ct07_current_qgap_ledgers_after_direct_diverse_cycle2_20260607.txt
  candidates:
    tmp/ct07_diverse_edge_after_direct_diverse_allpairs_k1_cycle3.json
    source pairs: 4090
    sampled records: 4090
    sampler elapsed: 302.35s
  q-gap direct:
    tmp/ct07_qgap_direct_diverse_edge_after_direct_diverse_allpairs_k1_cycle3.json
    records: 4090
    elapsed: 1654.62s
    status: no factor
    q-gap statuses: no_roots=4090
```

Notes:

```text
1. The top128 cycle-1 run is a subset of the later top512 cycle-1 run; count it
   as an early smoke, not as additional unique coverage.
2. Unique broad coverage now includes the original after4956 one-model pass
   (4090 full cubes), top512 four-alternate pass (2048 full cubes), top128
   cycle-2 four-alternate pass (512 full cubes), and all-pair cycle-3
   one-alternate pass (4090 full cubes).
3. Every checked full edge cube returned q-gap no_roots.  Because these are
   full-cube q-gap checks inside the hard bound margin, they are useful hard
   no-good clauses for those exact sampled full edge assignments.
4. This is still not a proof over all full edge completions.  It shows that
   the current SAT/model distribution keeps landing in dead q-gap branches.
5. No factor/plaintext has been recovered.
```

Operational conclusion: the diverse sampler is working and is much better than
one representative per low pair.  However, blind expansion of the same sampler
is now showing diminishing returns.  The next useful change should alter the
model distribution, for example by adding a randomized/phase-diverse Z3 model
sampler, using exact carry objectives to bias selected bits, or moving the
search driver to a different frontier than `(x2_low8,x6_low4)`.

### 2026-06-07 deep-prefix scorer and after4956 full-model direct sweep

Added `rank_deep_prefix_candidates.py`, a bounded exact Hensel-prefix rescoring
driver for saved rank JSONs.  It reads `top`/`results`/`items` candidate files,
reconstructs branch fixed ranges, runs `z3_hensel_prefix_status` at selected
prefix depths, and writes both a full scored summary and a partial-p-compatible
candidate file.

Deep-prefix probes showed that this is not currently a strong branch scorer:

```text
tmp/ct07_deep_prefix_balanced_after4956_top4_smoke.json
  prefixes: 430,500,600
  candidates: 4
  elapsed: 70.64s
  result: all unknown

tmp/ct07_deep_prefix_balanced_after4956_top16_370_390_410.json
  prefixes: 370,390,410
  candidates: 16
  elapsed: 52.68s
  prefix 370: sat=15, unknown=1
  prefix 390: unknown=16
  prefix 410: unknown=16

tmp/ct07_deep_prefix_balanced_after4956_top1_600_timeout30000.json
  prefix: 600
  timeout: 30000ms
  elapsed: 37.33s
  result: unknown
```

Interpretation: Hensel-prefix scoring is exact when it returns `unsat`, but it
does not currently return useful `unsat` decisions at the depths that matter.
At 390+ bits it mostly turns into a timeout/unknown signal, so it should not be
used as a primary search driver.

Residual partial-p probes on the deep-prefix candidate file also did not hit:

```text
tmp/ct07_partial_p_deep_prefix_after4956_top16_m3_5_t1-4_w8_timeout120.json
  candidates: 16
  parameters: m=3,5 and t=1..4, workers=8, timeout=120s
  status: no factor
  elapsed: 533.07s
  notable: m=5,t=1 timed out for all 16 candidates; m=5,t=2 averaged 94.11s

tmp/ct07_partial_p_deep_prefix_after4956_top8_m5_t5-8_w8_timeout90.json
  candidates: 8
  parameters: m=5 and t=5..8, workers=8, timeout=90s
  status: no factor
  elapsed: 94.21s
```

A direct CP-SAT exact-tail check was also run on the current balanced top1
branch with `T=848`, full tail limbs, 12 workers, and a 60s limit:

```text
fixed p ranges:
  150:4=0x0
  265:84=0x207
  784:46=0x17
  920:4=0x0
q low known bits: 362
q prefix start: 770
p unknown bools in T: 214
q fixed bits in T: 440
status: UNKNOWN
wall time: 60.26s
branches: 89518
conflicts: 4774
```

This CP-SAT result is not pruning evidence; it only says the exact-tail model
did not solve that one branch within 60 seconds.

The q-gap direct runner was then updated to use `as_completed`-style streaming
rather than ordered `executor.map`, and now supports `--max-seconds`.  This is
important because the previous ordered runner could spend a long time blocked
behind one slow early rank and produce no partial JSONL output.

After that, every after4956 SAT model completion from the `(x2_low8,x6_low4)`
pair ranker was checked once with q-gap Coppersmith:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4956_all_model.json
  evaluated pairs: 4096
  SAT model completions: 4090
  unknown pairs: 6

tmp/ct07_qgap_direct_after4956_all_model_stream_30m.json
tmp/ct07_qgap_direct_after4956_all_model_stream_30m.jsonl
  records requested/completed: 4090
  workers: 16
  elapsed: 1604.36s
  status: no factor
  q-gap statuses: no_roots=4090
```

Interpretation:

```text
1. The current after4956 learned ledger plus one Z3 model completion per
   (x2_low8,x6_low4) pair does not contain the solution.
2. This is not a proof over the full branch space, because each low pair can
   still have many full x2/x6/x0/x7 completions and the ranker samples only one.
3. The next useful direction is not another q-gap minimization top4 batch or
   another single-model direct pass.  It needs a diverse completion sampler:
   for selected low pairs, ask the SAT ledger for multiple distinct full edge
   completions, block each sampled full cube, and run streaming q-gap direct on
   those completions.
4. Deep Hensel, residual partial-p, and one-branch CP-SAT have not produced a
   factor; keep them as finalist/sanity probes, not the main engine.
5. No factor/plaintext has been recovered.
```

### 2026-06-06 after4916/4920 hybrid top4 continuation

The next four-item hybrid queue from the after4916 rank file completed:

```text
tmp/ct07_hybrid_queue_after4916_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4916_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1958.49s
manifest: tmp/ct07_current_qgap_ledgers_after4920_hybrid_top4.txt
ledgers: 415
```

All four representatives again returned hard q-gap no-root results with five
learned variants each:

```text
rank 1: x2_low8=0x5e, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=446.65s
rank 2: x2_low8=0x5f, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=496.02s
rank 3: x2_low8=0x5f, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=499.17s
rank 4: x2_low8=0x60, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=516.12s
```

Reranking with the 415-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4920_hybrid_top4_top256.json
loaded ledger files: 415
candidate clause records: 5351
clauses added: 5346
cube records: 5032
duplicate clauses: 5
literals added: 734400
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
top layer: x2_low8=0x60/0x61/0x62..., x6_low4={0x4,0x6}, q_gap=407
```

The top8 ranked full-cube representatives were then converted into
`tmp/ct07_ranked_after4920_top8_partial_candidates.json` and tested with
`branch_partial_coppersmith.py` as a success-only residual 3-block oracle:

```text
summary: tmp/ct07_partial_p_after4920_top8_m2_3_t1_2_timeout45.json
candidates tested: 8
remaining unknown p blocks per candidate: [58, 69, 87]
parameters: m=2..3, t=1..2, timeout=45s per attempt
status: no factor
elapsed: 235.77s
attempt status counts:
  (m=2,t=1): 6 no_factor, 2 error
  (m=2,t=2): 8 no_factor
  (m=3,t=1): 8 no_factor
  (m=3,t=2): 8 no_factor
```

Interpretation:

```text
1. Hybrid q-gap hard pruning is still stable, but it is advancing the same q_gap=407 frontier rather than producing a direct hit.
2. The frontier moved from x2_low8=0x5e to x2_low8=0x60 over four more representatives.
3. Residual 3-block partial-p Coppersmith did not factor the current top8 representatives under small parameters.
4. No factor/plaintext has been recovered.
```

### 2026-06-06 after4920/4924 hybrid top4 continuation

The next four-item hybrid queue from the after4920 rank file completed:

```text
tmp/ct07_hybrid_queue_after4920_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4920_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1959.09s
manifest: tmp/ct07_current_qgap_ledgers_after4924_hybrid_top4.txt
ledgers: 419
```

All four representatives returned hard q-gap no-root results with five learned
variants each:

```text
rank 1: x2_low8=0x60, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=510.82s
rank 2: x2_low8=0x61, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=484.56s
rank 3: x2_low8=0x61, x6_low4=0x6 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=494.38s
rank 4: x2_low8=0x62, x6_low4=0x4 -> no roots, q_gap=407, calls=1297, clauses=5, literals=650, elapsed=468.83s
```

Reranking with the 419-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4924_hybrid_top4_top256.json
loaded ledger files: 419
candidate clause records: 5371
clauses added: 5366
cube records: 5036
duplicate clauses: 5
literals added: 737000
evaluated pairs: 4096
SAT pairs: 4093
unknown pairs: 3
top layer: x2_low8=0x62/0x63/0x64..., x6_low4={0x4,0x6}, q_gap=407
```

Stronger residual partial-p success-only probes were also tried on the
after4920 top-ranked full-cube candidates:

```text
tmp/ct07_partial_p_after4920_top1_m4_t1_timeout240.json
candidate limit: 1
parameters: m=4, t=1, timeout=240s
status: no factor
elapsed: 20.00s

tmp/ct07_partial_p_after4920_top1_m4_5_t2_3_timeout240.json
candidate limit: 1
parameters: m=4..5, t=2..3, timeout=240s
status: no factor
elapsed: 56.81s
```

Two broader success-only probes were interrupted manually because they did not
produce incremental summaries quickly enough:

```text
partial-p top1, m=6..8, t=1..3, timeout=300s per attempt
folded p/q Coron top8, k=1..4, timeout=60s per attempt
```

Interpretation:

```text
1. The q-gap hard ledger has advanced from 415 to 419 representatives and from 5346 to 5366 loaded hard clauses.
2. The same q_gap=407 frontier remains active; the next ranked layer starts at x2_low8=0x62/0x63 with x6_low4=0x4/0x6.
3. Current throughput is stable at about 7.8-8.5 minutes per representative, or about 32-33 minutes per top4 batch on 12 workers.
4. Partial-p/Coron success-only probes have not produced a factor, and their no-factor/timeout outcomes are not hard pruning evidence.
5. No factor/plaintext has been recovered.
```

### 2026-06-06 after4924/4928 and after4928/4932 hybrid continuations

Two more four-item hybrid q-gap queues completed:

```text
tmp/ct07_hybrid_queue_after4924_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4924_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1990.94s
manifest: tmp/ct07_current_qgap_ledgers_after4928_hybrid_top4.txt
ledgers: 423

tmp/ct07_hybrid_queue_after4928_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4928_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1878.14s
manifest: tmp/ct07_current_qgap_ledgers_after4932_hybrid_top4.txt
ledgers: 427
```

All eight representatives returned hard q-gap no-root results.  Each
representative used `q_gap=407`, made 1297 q-gap calls, and learned five hard
clauses with 650 total learned literals:

```text
after4928 ranks:
  x2_low8=0x62, x6_low4=0x6, elapsed=501.97s
  x2_low8=0x63, x6_low4=0x4, elapsed=525.96s
  x2_low8=0x63, x6_low4=0x6, elapsed=524.10s
  x2_low8=0x64, x6_low4=0x4, elapsed=438.54s

after4932 ranks:
  x2_low8=0x64, x6_low4=0x6, elapsed=469.14s
  x2_low8=0x65, x6_low4=0x4, elapsed=477.61s
  x2_low8=0x65, x6_low4=0x6, elapsed=468.98s
  x2_low8=0x66, x6_low4=0x4, elapsed=461.99s
```

Reranking with the 427-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4932_hybrid_top4_top256.json
loaded ledger files: 427
candidate clause records: 5411
clauses added: 5406
cube records: 5044
duplicate clauses: 5
literals added: 742200
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
top layer: x6=0x80000000c/0x80000000e, small x2 values, q_gap=407
```

The after4928 and after4932 top8 ranked full-cube representatives were also
tested with `branch_partial_coppersmith.py` as a success-only residual 3-block
oracle:

```text
tmp/ct07_ranked_after4928_top8_partial_candidates.json
tmp/ct07_partial_p_after4928_top8_m4_t1_timeout180.json
candidates: 8
parameters: m=4, t=1, timeout=180s per attempt
status: no factor
elapsed: 162.07s

tmp/ct07_ranked_after4932_top8_partial_candidates.json
tmp/ct07_partial_p_after4932_top8_m4_t1_timeout180.json
candidates: 8
parameters: m=4, t=1, timeout=180s per attempt
status: no factor
elapsed: 177.78s
```

Interpretation:

```text
1. The hard q-gap ledger advanced from 419 to 427 representatives and from 5366 to 5406 loaded hard clauses.
2. The low x6_low4={0x4,0x6} layer around x2_low8=0x62..0x66 has been closed at the current representative granularity.
3. The latest top frontier pivoted to a different q_gap=407 layer with x6 high bits set: x6=0x80000000c/0x80000000e and small x2 values.
4. The new residual partial-p top8 probes did not factor; these remain success-only signals, not hard pruning evidence.
5. No factor/plaintext has been recovered.
```

### 2026-06-06 after4932/4936 and after4936/4940 hybrid continuations

Two more four-item hybrid q-gap queues completed:

```text
tmp/ct07_hybrid_queue_after4932_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4932_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1850.54s
manifest: tmp/ct07_current_qgap_ledgers_after4936_hybrid_top4.txt
ledgers: 431

tmp/ct07_hybrid_queue_after4936_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4936_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1835.77s
manifest: tmp/ct07_current_qgap_ledgers_after4940_hybrid_top4.txt
ledgers: 435
```

All eight representatives returned hard q-gap no-root results.  Each
representative made 1297 q-gap calls and learned five hard clauses:

```text
after4936 ranks:
  x2=0x8,  x6=0x80000000c, q_gap=409, elapsed=476.82s
  x2=0xc,  x6=0x80000000c, q_gap=409, elapsed=456.06s
  x2=0xe,  x6=0x80000000c, q_gap=409, elapsed=456.15s
  x2=0xf,  x6=0x80000000c, q_gap=409, elapsed=461.07s

after4940 ranks:
  x2=0x166,   x6=0x6, q_gap=407, elapsed=496.84s
  x2=0x167,   x6=0x4, q_gap=407, elapsed=458.50s
  x2=0x167,   x6=0x6, q_gap=407, elapsed=454.73s
  x2=0x40068, x6=0x4, q_gap=407, elapsed=425.16s
```

Reranking with the 435-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4940_hybrid_top4_top256.json
loaded ledger files: 435
candidate clause records: 5451
clauses added: 5446
cube records: 5052
duplicate clauses: 5
literals added: 747400
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
top layer: x6=0x80000000c/0x80000000e, small x2 values, q_gap=407
```

The after4936 and after4940 top8 ranked full-cube representatives were tested
with residual partial-p Coppersmith as success-only probes:

```text
tmp/ct07_ranked_after4936_top8_partial_candidates.json
tmp/ct07_partial_p_after4936_top8_m4_t1_timeout180.json
candidates: 8
parameters: m=4, t=1, timeout=180s per attempt
status: no factor
elapsed: 167.00s

tmp/ct07_ranked_after4940_top8_partial_candidates.json
tmp/ct07_partial_p_after4940_top8_m4_t1_timeout180.json
candidates: 8
parameters: m=4, t=1, timeout=180s per attempt
status: no factor
elapsed: 159.27s
```

Interpretation:

```text
1. The hard q-gap ledger advanced from 427 to 435 representatives and from 5406 to 5446 loaded hard clauses.
2. The frontier alternated between the high-side x6=0x80000000c/e layer and the low x6={0x4,0x6} layer; both remain q-gap hard-eligible.
3. No factor was found by the hard q-gap oracle or the latest residual partial-p success-only probes.
4. The next hard-pruning chunk should start from tmp/ct07_ranked_qgap_pairs_include_seen_after4940_hybrid_top4_top256.json.
5. No factor/plaintext has been recovered.
```

### 2026-06-06 after4940/4944 hybrid continuation and parallel partial-p probe

The next four-item hybrid q-gap queue completed from the after4940 frontier:

```text
tmp/ct07_hybrid_queue_after4940_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4940_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 2220.59s
manifest: tmp/ct07_current_qgap_ledgers_after4944_hybrid_top4.txt
ledgers: 439
```

All four representatives returned hard q-gap no-root results.  Each
representative made 1297 q-gap calls and learned five hard clauses:

```text
after4944 ranks:
  x2=0x8,  x6=0xe, q_gap=408, elapsed=558.14s
  x2=0xf,  x6=0xe, q_gap=408, elapsed=497.46s
  x2=0x10, x6=0xc, q_gap=409, elapsed=644.34s
  x2=0x11, x6=0xe, q_gap=408, elapsed=520.18s
```

Reranking with the 439-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4944_hybrid_top4_top256.json
loaded ledger files: 439
candidate clause records: 5471
clauses added: 5466
cube records: 5056
duplicate clauses: 5
literals added: 750000
evaluated pairs: 4096
SAT pairs: 4093
unknown pairs: 3
top layer: x6=0x4/0x6, x2 around 0x40068..0x4006e, q_gap=407
```

The residual partial-p success-only probe was widened.  First, the after4940
top64 ranked full-cube representatives were tested with the old sequential
runner:

```text
tmp/ct07_ranked_after4940_top64_partial_candidates.json
tmp/ct07_partial_p_after4940_top64_m4_t1_timeout180.json
candidates: 64
parameters: m=4, t=1, timeout=180s per attempt
status: no factor
elapsed: 2726.79s
```

Then `branch_partial_coppersmith.py` was updated with `--workers` and optional
streaming `--jsonl`, and the after4944 top128 were tested with 8 workers:

```text
tmp/ct07_ranked_after4944_top128_partial_candidates.json
tmp/ct07_partial_p_after4944_top128_m4_t1_w8_timeout180.json
tmp/ct07_partial_p_after4944_top128_m4_t1_w8_timeout180.jsonl
candidates: 128
parameters: m=4, t=1, workers=8, timeout=180s per attempt
status: no factor
elapsed: 566.09s
```

Interpretation:

```text
1. The hard q-gap ledger advanced from 435 to 439 representatives and from 5446 to 5466 loaded hard clauses.
2. The latest frontier returned to the low x6={0x4,0x6} layer near x2=0x40068.., still q_gap=407 and hard-eligible.
3. Sequential top64 and parallel top128 residual partial-p probes did not factor; these remain success-only negative signals.
4. The new parallel partial-p runner makes broader top-ranked residual probes practical and should be used for future top256/top512 success-only sweeps.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 after4948/4952 q-gap continuation and residual probes

The after4944 top128 residual partial-p success-only probe was extended across
more `t` values with the parallel runner:

```text
candidate source:
  tmp/ct07_ranked_after4944_top128_partial_candidates.json

tmp/ct07_partial_p_after4944_top128_m4_t2_w8_timeout180.json
  candidates: 128
  parameters: m=4, t=2, workers=8, timeout=180s per attempt
  status: no factor
  elapsed: 65.04s

tmp/ct07_partial_p_after4944_top128_m4_t3_w8_timeout180.json
  candidates: 128
  parameters: m=4, t=3, workers=8, timeout=180s per attempt
  status: no factor
  elapsed: 48.04s

tmp/ct07_partial_p_after4944_top128_m4_t4_w8_timeout180.json
  candidates: 128
  parameters: m=4, t=4, workers=8, timeout=180s per attempt
  status: no factor
  elapsed: 54.71s
```

A smoke check of `m=5,t=1` on two candidates took 180.14s and did not factor,
so the wider run stayed with `m=4`.

The next four-item hybrid q-gap queue completed from the after4944 frontier:

```text
tmp/ct07_hybrid_queue_after4944_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4944_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 1914.80s
manifest: tmp/ct07_current_qgap_ledgers_after4948_hybrid_top4.txt
ledgers: 443

records:
  #1 q_gap=407, q_gap_calls=1297, clauses=5, literals=650, elapsed=429.75s
  #2 q_gap=407, q_gap_calls=1297, clauses=5, literals=650, elapsed=441.55s
  #3 q_gap=407, q_gap_calls=1297, clauses=5, literals=650, elapsed=461.35s
  #4 q_gap=407, q_gap_calls=1297, clauses=5, literals=650, elapsed=581.76s
```

Reranking with the 443-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4948_hybrid_top4_top256.json
candidate clause records: 5491
clauses added: 5486
cube records: 5060
duplicate clauses: 5
literals added: 752600
evaluated pairs: 4096
SAT pairs: 4031
unknown pairs: 65
top layer: x2 low byte 0x09/0x0a/0x0b/0x0c..., x6 low nibble 0xf/0x2, q_gap=407
```

The after4948 top128 rank rows were converted to partial-p candidate JSON with
`all_fixed_ranges_text`:

```text
tmp/ct07_ranked_after4948_top128_partial_candidates.json
tmp/ct07_partial_p_after4948_top128_m4_t1-4_w8_timeout180.json
tmp/ct07_partial_p_after4948_top128_m4_t1-4_w8_timeout180.jsonl
candidates: 128
parameters: m=4, t=1..4, workers=8, timeout=180s per attempt
status: no factor
elapsed: 1048.53s
```

Another four-item hybrid q-gap queue completed from the after4948 frontier:

```text
tmp/ct07_hybrid_queue_after4948_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4948_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 2408.00s
manifest: tmp/ct07_current_qgap_ledgers_after4952_hybrid_top4.txt
ledgers: 447

records:
  #1 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=578.53s
  #2 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=598.95s
  #3 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=608.90s
  #4 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=620.98s
```

Reranking with the 447-ledger manifest produced:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4952_hybrid_top4_top256.json
candidate clause records: 5511
clauses added: 5506
cube records: 5064
duplicate clauses: 5
literals added: 755200
evaluated pairs: 4096
SAT pairs: 4093
unknown pairs: 3
top layer: x6=0x20000007 with varied x2 low byte, q_gap=407
```

Interpretation:

```text
1. The hard q-gap ledger advanced from 439 to 447 representatives and from 5466 to 5506 loaded hard clauses.
2. The after4948 top4 layer was slower and had q_gap=409, but still produced the same five 650-literal hard clauses per representative.
3. Parallel residual partial-p did not factor after4944 or after4948 top-ranked candidates; these are success-only negative signals.
4. The frontier continues to move between thin q_gap=407/409 layers rather than finding the factor.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 after4952/4956 q-gap continuation and balanced scorer

The planned one-more hard-pruning chunk completed from the after4952 frontier:

```text
tmp/ct07_hybrid_queue_after4952_top4
rank input: tmp/ct07_ranked_qgap_pairs_include_seen_after4952_hybrid_top4_top256.json
records: 4
factor: none
elapsed: 2403.19s
manifest: tmp/ct07_current_qgap_ledgers_after4956_hybrid_top4.txt
ledgers: 451

records:
  #1 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=619.77s
  #2 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=571.22s
  #3 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=623.07s
  #4 q_gap=409, q_gap_calls=1297, clauses=5, literals=650, elapsed=588.48s
```

The normal rerank with the 451-ledger manifest produced another narrow
q-gap-first frontier:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4956_hybrid_top4_top256.json
candidate clause records: 5531
clauses added: 5526
cube records: 5068
duplicate clauses: 5
literals added: 757800
evaluated pairs: 4096
SAT pairs: 4088
unknown pairs: 8
top layer: x2 low byte around 0x6a..0x74, x6 low nibble 0x4/0x6, q_gap=407
```

At this point the previous plan's stop condition was met: another top4 q-gap
chunk only added the same five 650-literal clauses per representative and did
not produce a hit.  The ranker was updated with:

```text
rank_q_gap_assumption_pairs.py
  --prefix-core {bv,hensel}
  --score-mode {legacy,balanced}
  --balanced-score-candidate-limit
  --score-hybrid-cumulative-drop-window
  --score-hybrid-independent-drop-window
  --score-max-completions

balanced score fields:
  score_q_gap_bits
  score_q_known_bits_min
  score_q_interval_width_bits_max
  score_q_gap_effective_margin_bits_min
  score_q_gap_completion_count
  residual_partial_unknown_bits
  residual_partial_unknown_blocks
  residual_partial_product_bound_bits
```

Balanced reranking against after4956 used the default hybrid drop model
(`150:4,920:4` cumulative; `265:8,273:8,784:8,792:8` independent) for the top
512 legacy-ranked SAT rows:

```text
tmp/ct07_ranked_qgap_pairs_balanced_after4956_top256.json
score_mode: balanced
loaded hard clauses: 5526
SAT pairs: 4092
unknown pairs: 4
top layer: q_gap=408, predicted hybrid-drop score_q_gap=415
residual partial-p blocks: [58, 69, 87], 214 unknown bits
```

The balanced top256 was checked with direct q-gap Coppersmith:

```text
tmp/ct07_balanced_after4956_qgap_direct_top256.json
tmp/ct07_balanced_after4956_qgap_direct_top256.jsonl
candidates: 256
status: no factor
elapsed: 86.66s
status counts: no_roots=256
q_gap distribution: 407 -> 48, 408 -> 176, 409 -> 16, 410 -> 16
```

The balanced top128 was then checked with residual partial-p Coppersmith:

```text
tmp/ct07_ranked_balanced_after4956_top128_partial_candidates.json
tmp/ct07_partial_p_balanced_after4956_top128_m4_t1-4_w8_timeout180.json
tmp/ct07_partial_p_balanced_after4956_top128_m4_t1-4_w8_timeout180.jsonl
candidates: 128
parameters: m=4, t=1..4, workers=8, timeout=180s per attempt
status: no factor
elapsed: 969.22s
```

Interpretation:

```text
1. The hard q-gap ledger advanced from 447 to 451 representatives and from 5506 to 5526 loaded hard clauses.
2. Repeating q-gap top4 again only produced the same five hard clauses per representative and no factor.
3. Balanced scoring now accounts for expected hybrid drop q-gap cost and residual partial-p cost fields, but the first balanced direct and partial-p hit probes still found no factor.
4. Continuing blind q-gap queue widening is no longer the best use of time; the next useful work needs a stronger branch scorer or a new oracle that differentiates among the residual [58,69,87] block candidates.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 alternate frontiers, random-diverse sampling, and pwindow420 residual partial-p

The sampler now supports temporary random assumptions over selected edge bits:

```text
sample_diverse_edge_completions.py
  --random-assumption-bits
  --random-assumption-retries
  --random-seed
  --no-random-fallback
```

This lets the SAT model query move away from the nearest completion after a
local blocking clause.  The random assumptions are recorded per sample and are
not used as learned clauses.

Alternate q-gap frontier checks:

```text
tmp/ct07_ranked_qgap_pairs_altfrontier_x2low8_x6high4_after4956_top512.json
  ranking: 4092 SAT / 4 unknown
  top layer: q_gap=408, q_low=362, q_prefix_start=770

tmp/ct07_qgap_direct_altfrontier_x2low8_x6high4_after4956_top512.json
  512/512 no_roots, no factor, elapsed 196.71s

tmp/ct07_diverse_edge_altfrontier_x2low8_x6high4_after4956_top128_k4.json
tmp/ct07_qgap_direct_altfrontier_x2low8_x6high4_after4956_top128_k4.json
  512/512 no_roots, no factor, elapsed 198.00s

tmp/ct07_ranked_qgap_pairs_altfrontier_x2mid8_x6low4_after4956_top512.json
  ranking: 4084 SAT / 12 unknown
  top layer: q_gap=407, q_low=362, q_prefix_start=769

tmp/ct07_qgap_direct_altfrontier_x2mid8_x6low4_after4956_top512.json
  512/512 no_roots, no factor, elapsed 177.19s

tmp/ct07_diverse_edge_altfrontier_x2mid8_x6low4_random24_after4956_top128_k4.json
tmp/ct07_qgap_direct_altfrontier_x2mid8_x6low4_random24_after4956_top128_k4.json
  512/512 no_roots, no factor, elapsed 243.26s
```

The q-gap oracle is still sound and fast, but these frontiers did not change the
hit distribution enough.  They added useful sampled no-goods, not a factor.

The p two-sided univariate windows were also checked as success oracles:

```text
[362,830):
  required outside bits: x0 + x2 + x7
  middle bits: 468
  result: first candidate exceeded the 120s timeout; stopped as too slow

[420,830):
  required outside bits: x0 + x2 + x3 + x7
  middle bits: 410
  result: candidates still ran near the 60s timeout; stopped as too slow
```

The same `[420,830)` outside assignments are useful for residual partial-p
Coppersmith because the remaining p unknowns are only `x4+x5+x6`:

```text
tmp/ct07_pwindow420_edge_samples_x2mid8_x6low4_random24_top16_k2.json
tmp/ct07_partial_p_pwindow420_x2mid8_x6low4_random24_top16_k2_m2-4_t1-4_timeout60.json
  candidates: 32
  residual unknown blocks: [69,87,46] = 202 bits
  status: no factor
  parameter note: m=4,t=1 timed out on all 32 candidates

tmp/ct07_pwindow420_edge_samples_x2mid8_x6low4_random24_top64_k2.json
tmp/ct07_partial_p_pwindow420_x2mid8_x6low4_random24_top64_k2_m2-3_t1-4_timeout45.json
  candidates: 128
  status: no factor

tmp/ct07_partial_p_pwindow420_x2mid8_x6low4_random24_top64_k2_m4_t2-4_timeout45.json
  candidates: 128
  status: no factor
```

Interpretation:

```text
1. `x2_low8+x6_high4` and `x2_mid8+x6_low4` both produce viable hard q-gap candidates, but their direct and diverse sampled completions all died.
2. Random assumptions successfully alter the model distribution without breaking SAT sampling, but the first 512 random-diverse q-gap probes still did not hit.
3. Univariate p-window Coppersmith is too slow at 468 and 410 middle bits in this environment.
4. Residual partial-p on `[420,830)` candidates is operational and much faster than univariate p-window, but the first 128 candidates did not factor.
5. No factor/plaintext has been recovered.
```

Follow-up synthetic x3 frontier:

```text
tmp/ct07_synthetic_frontier_x2mid8_x3low8_seed20260610_top512.json
  synthetic pair fields:
    x2_value -> p[305:313)
    x6_value -> p[362:370), i.e. x3_low8 for the generic sampler

tmp/ct07_pwindow420_edge_samples_synthetic_x2mid8_x3low8_random24_top128_k1.json
  selected cube: 150:4,265:84,362:58,920:4
  assumptions: x2_mid8 + x3_low8
  samples: 128 SAT models

tmp/ct07_partial_p_pwindow420_synthetic_x2mid8_x3low8_random24_top128_k1_m2-3_t1-4_timeout45.json
  candidates: 128
  status: no factor
  elapsed: 349.89s

tmp/ct07_partial_p_pwindow420_synthetic_x2mid8_x3low8_random24_top128_k1_m4_t2-4_timeout45.json
  candidates: 128
  status: no factor
  elapsed: 277.11s
```

This explicitly varied x3_low8 rather than letting the q-gap frontier choose x3
implicitly.  It did not factor, but it confirms the residual partial-p pipeline
can test x3-driven distributions without needing q-gap-hard candidates.

### 2026-06-07 explicit x0/x7 frontiers and pwindow420 q-gap trigger

The sampler was generalized to accept arbitrary per-row assumption ranges:

```text
sample_diverse_edge_completions.py
  row format:
    assumption_ranges:
      - {label, start, width, value}

New generator:
  cryptotest/solutions/07_sat_cas_explore/make_synthetic_assumption_frontier.py
```

This removed the old two-field `x2_value/x6_value` limitation and allowed
explicit `x0/x7` edge coverage together with chosen x2/x3 chunks.

A key observation from the first smoke test:

```text
selected cube: 150:4,265:84,362:58,920:4
fixed outside p-window [420,830): x0+x2+x3+x7

q-known derived from those samples:
  q_low_bits = 600
  q_prefix_start = about 830..836
  q_gap_bits = 230..236
```

So these candidates should run through q-middle-gap Coppersmith before residual
partial-p.  The q-gap oracle is hard-eligible with a very large margin here.

Existing pwindow420 samples were rechecked with q-gap direct:

```text
tmp/ct07_edge_explicit_existing_pwindow420_top64_k2_qgap_direct.json
  source: tmp/ct07_pwindow420_edge_samples_x2mid8_x6low4_random24_top64_k2.json
  candidates: 128
  status: 128/128 no_roots, no factor

tmp/ct07_edge_explicit_existing_synthetic_x3low_top128_qgap_direct.json
  source: tmp/ct07_pwindow420_edge_samples_synthetic_x2mid8_x3low8_random24_top128_k1.json
  candidates: 128
  status: 128/128 no_roots, no factor
```

Explicit `x0/x7` frontiers with `x2_mid8 = 0` were then checked:

```text
tmp/ct07_edge_explicit_x0x7_x2mid00_x3low00_40_frontier512.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3low00_40_random24_samples512.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3low00_40_random24_qgap_direct512.json
  assumptions: x3_low8 in {0x00,0x40}, x0=all, x7=all
  candidates: 512
  status: 512/512 no_roots, no factor

tmp/ct07_edge_explicit_x0x7_x2mid00_x3low80_c0_frontier512.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3low80_c0_random24_samples512.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3low80_c0_random24_qgap_direct512.json
  assumptions: x3_low8 in {0x80,0xc0}, x0=all, x7=all
  candidates: 512
  status: 512/512 no_roots, no factor

combined x3_low8 coarse coverage:
  candidates: 1024
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64
```

Explicit `x3_mid8` and `x3_high8` quarter frontiers were also checked:

```text
tmp/ct07_edge_explicit_x0x7_x2mid00_x3mid_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3mid_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3mid_quarters_random24_qgap_direct1024.json
  assumptions: x3_mid8 in {0x00,0x40,0x80,0xc0}, x0=all, x7=all
  candidates: 1024
  status: 1024/1024 no_roots, no factor

tmp/ct07_edge_explicit_x0x7_x2mid00_x3high_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3high_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid00_x3high_quarters_random24_qgap_direct1024.json
  assumptions: x3_high8 in {0x00,0x40,0x80,0xc0}, x0=all, x7=all
  candidates: 1024
  status: 1024/1024 no_roots, no factor

per 1024-candidate x3_mid/high batch:
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64
```

Interpretation:

```text
1. The arbitrary-assumption sampler is working and can explicitly cover x0/x7.
2. Fixing x0+x2+x3+x7 turns on a much stronger q-gap oracle than the older x2+x6 style branches: gap about 230..236 instead of about 407..409.
3. The first 3328 pwindow420 q-gap candidates checked in this mode all died:
   128 existing + 128 existing synthetic + 1024 x3_low coarse + 1024 x3_mid coarse + 1024 x3_high coarse.
4. Residual partial-p should now be fallback only; q-gap direct is the first oracle for this selected cube.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 x2_mid8=0x40 explicit edge continuation

The next x2 coarse value was checked with the same selected cube and explicit
edge coverage:

```text
selected cube: 150:4,265:84,362:58,920:4
fixed coarse x2 chunk: x2_mid8 = p[305:313) = 0x40
edge coverage: x0=all, x7=all
random assumptions per sample: 24 selected bits
q oracle: q-middle-gap Coppersmith, epsilon=0.04, workers=8
```

Results:

```text
tmp/ct07_edge_explicit_x0x7_x2mid40_x3low_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3low_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3low_quarters_random24_qgap_direct1024.json
  assumptions: x3_low8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2mid40_x3mid_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3mid_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3mid_quarters_random24_qgap_direct1024.json
  assumptions: x3_mid8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2mid40_x3high_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3high_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid40_x3high_quarters_random24_qgap_direct1024.json
  assumptions: x3_high8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64
```

Interpretation:

```text
1. x2_mid8=0x40 behaved like x2_mid8=0: all sampled coarse x3/edge candidates are hard q-gap no-roots.
2. Total explicit pwindow420 q-gap candidates checked in this mode is now 6400:
   previous 3328 + 3072 for x2_mid8=0x40.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 x2_mid8=0x80 explicit edge continuation

The next x2 coarse value was checked with the same selected cube and explicit
edge coverage:

```text
selected cube: 150:4,265:84,362:58,920:4
fixed coarse x2 chunk: x2_mid8 = p[305:313) = 0x80
edge coverage: x0=all, x7=all
random assumptions per sample: 24 selected bits
q oracle: q-middle-gap Coppersmith, epsilon=0.04, workers=8
```

Results:

```text
tmp/ct07_edge_explicit_x0x7_x2mid80_x3low_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3low_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3low_quarters_random24_qgap_direct1024.json
  assumptions: x3_low8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2mid80_x3mid_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3mid_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3mid_quarters_random24_qgap_direct1024.json
  assumptions: x3_mid8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2mid80_x3high_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3high_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2mid80_x3high_quarters_random24_qgap_direct1024.json
  assumptions: x3_high8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64
```

Interpretation:

```text
1. x2_mid8=0x80 also behaved like the previous coarse values: all sampled
   coarse x3/edge candidates are hard q-gap no-roots.
2. Total explicit pwindow420 q-gap candidates checked in this mode is now 9472:
   previous 6400 + 3072 for x2_mid8=0x80.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 x2_mid8=0xc0 explicit edge continuation

The last planned x2_mid8 coarse value was checked with the same selected cube
and explicit edge coverage:

```text
selected cube: 150:4,265:84,362:58,920:4
fixed coarse x2 chunk: x2_mid8 = p[305:313) = 0xc0
edge coverage: x0=all, x7=all
random assumptions per sample: 24 selected bits
q oracle: q-middle-gap Coppersmith, epsilon=0.04, workers=8
```

Results:

```text
tmp/ct07_edge_explicit_x0x7_x2midc0_x3low_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3low_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3low_quarters_random24_qgap_direct1024.json
  assumptions: x3_low8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2midc0_x3mid_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3mid_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3mid_quarters_random24_qgap_direct1024.json
  assumptions: x3_mid8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64

tmp/ct07_edge_explicit_x0x7_x2midc0_x3high_quarters_frontier1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3high_quarters_random24_samples1024.json
tmp/ct07_edge_explicit_x0x7_x2midc0_x3high_quarters_random24_qgap_direct1024.json
  assumptions: x3_high8 in {0x00,0x40,0x80,0xc0}
  candidates: 1024
  status: 1024/1024 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:128, 231:384, 232:256, 233:128, 234:64, 236:64
```

Interpretation:

```text
1. x2_mid8 coarse quarter coverage is complete for {0x00,0x40,0x80,0xc0}.
2. Total explicit pwindow420 q-gap candidates checked in this mode is now 12544:
   previous 9472 + 3072 for x2_mid8=0xc0.
3. All checked candidates were hard q-gap no-roots; no factor/plaintext has
   been recovered.
4. Before rerunning this selected cube, convert the new q-gap JSONLs into the
   active ledger and move to a scorer over the remaining candidates.
```

Ledger manifest:

```text
tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  files: 15
  cube records: 12544
  clauses added in loader smoke test: 12544
  duplicates: 0
  parse_errors: 0
  file_errors: 0
```

### 2026-06-07 pwindow420 free sampling with scorer

After adding the explicit pwindow420 q-gap ledgers, a free selected-cube sampler
was tried:

```text
frontier: tmp/ct07_pwindow420_free_frontier_20260607.json
selected cube: 150:4,265:84,362:58,920:4
loaded ledgers:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
```

Results:

```text
tmp/ct07_pwindow420_free_random32_samples1024.json
  random assumptions: 32 selected bits
  solver timeout: 1000ms
  status: unknown before first sample
  records: 0

tmp/ct07_pwindow420_free_random64_t10s_samples256.json
  random assumptions: 64 selected bits
  solver timeout: 10000ms
  status: 256/256 sat samples generated

tmp/ct07_pwindow420_scored_free_random64_t10s_top256.json
  scorer: score_selected_cube_samples.py
  retained: 256/256

tmp/ct07_pwindow420_scored_free_random64_t10s_qgap_direct256.json
  status: 256/256 no_roots, no factor
  q_low_bits: 600 for all
  q_gap distribution: 230:37, 231:51, 232:131, 233:10, 234:25, 236:2

tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  files: 1
  current scorer-ledger content:
    tmp/ct07_pwindow420_scored_free_random64_t10s_qgap_direct256.jsonl
```

Interpretation:

```text
1. The scorer path is working and can feed run_ranked_q_gap_direct.py.
2. With the current 19k learned clauses, selected-cube free sampling needs a
   longer SAT timeout than 1000ms.  The successful setting was random64 with
   10000ms.
3. The first scored free batch also produced only hard q-gap no-roots.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 scored loop smoke

Added a loop runner:

```text
cryptotest/solutions/07_sat_cas_explore/run_pwindow420_scored_batches.py
```

It performs:

```text
sample_diverse_edge_completions.py
-> score_selected_cube_samples.py
-> run_ranked_q_gap_direct.py
-> append q-gap JSONL to active manifest
```

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_iter2
iterations: 2
batch size: 256
random assumptions: 64 selected bits
solver timeout: 10000ms
workers: 8
loaded ledgers:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Results:

```text
iteration 1:
  samples: 256/256 sat
  q-gap direct: 256/256 no_roots, no factor
  q_gap distribution: 230:30, 231:50, 232:143, 233:5, 234:27, 236:1
  elapsed: 383.17s

iteration 2:
  samples: 256/256 sat
  q-gap direct: 256/256 no_roots, no factor
  q_gap distribution: 230:25, 231:52, 232:138, 233:13, 234:27, 236:1
  elapsed: 423.16s

total loop:
  elapsed: 806.37s
  status: no_factor
  active manifest lines after loop: 472
```

Updated scorer-ledger manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  now includes:
    tmp/ct07_pwindow420_scored_free_random64_t10s_qgap_direct256.jsonl
    tmp/ct07_pwindow420_scored_loop_20260607_iter2/iteration_0001_qgap_direct.jsonl
    tmp/ct07_pwindow420_scored_loop_20260607_iter2/iteration_0002_qgap_direct.jsonl
```

Interpretation:

```text
1. The loop automation works and each iteration correctly feeds the newly
   learned q-gap JSONL into the next active manifest.
2. The first two automated scored batches added 512 more hard q-gap no-roots.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 scored loop batch512

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter1
iterations: 1
batch size: 512
random assumptions: 64 selected bits
solver timeout: 10000ms
workers: 8
loaded ledgers:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Results:

```text
samples: 512/512 sat
q-gap direct: 512/512 no_roots, no factor
q_gap distribution: 230:53, 231:120, 232:276, 233:14, 234:43, 236:6
elapsed: 662.36s
active manifest lines after loop: 473
```

Updated scorer-ledger manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  now includes 4 scored q-gap JSONLs:
    initial scored random64/t10s batch
    loop iter2 iteration 1
    loop iter2 iteration 2
    batch512 iteration 1
```

Interpretation:

```text
1. batch_size=512 is viable and was faster per candidate than the 2x256 smoke
   loop on this run.
2. The additional 512 candidates also all died as hard q-gap no-roots.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 scored loop batch512 iter2b

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter2b
iterations: 2
batch size: 512
random assumptions: 64 selected bits
solver timeout: 10000ms
workers: 8
loaded ledgers:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Results:

```text
iteration 1:
  samples: 512/512 sat
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:49, 231:103, 232:281, 233:20, 234:59
  elapsed: 703.07s

iteration 2:
  samples: 512/512 sat
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:58, 231:126, 232:268, 233:10, 234:47, 236:3
  elapsed: 664.58s

total loop:
  elapsed: 1367.69s
  status: no_factor
  active manifest lines after loop: 475
```

Updated scorer-ledger manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  now includes 6 scored q-gap JSONLs:
    initial scored random64/t10s batch
    loop iter2 iteration 1
    loop iter2 iteration 2
    batch512 iteration 1
    batch512 iter2b iteration 1
    batch512 iter2b iteration 2
```

Interpretation:

```text
1. The additional 1024 scored free candidates also all died as hard q-gap
   no-roots.
2. Cumulative scored-free q-gap direct checks are now 2048 candidates:
   256 initial + 512 loop smoke + 512 batch512 + 1024 iter2b.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 scored loop batch512 iter2c

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter2c
iterations: 2
batch size: 512
random assumptions: 64 selected bits
solver timeout: 10000ms
workers: 8
loaded ledgers:
  tmp/ct07_current_qgap_ledgers_after4956_plus_altfrontier_direct_20260607.txt
  tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
```

Results:

```text
iteration 1:
  samples: 512/512 sat
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:53, 231:99, 232:278, 233:20, 234:60, 236:2

iteration 2:
  samples: 512/512 sat
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:74, 231:116, 232:255, 233:14, 234:51, 236:2

total loop:
  elapsed: 1438.92s
  status: no_factor
```

Updated scorer-ledger manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  now includes 8 scored q-gap JSONLs:
    initial scored random64/t10s batch
    loop iter2 iteration 1
    loop iter2 iteration 2
    batch512 iteration 1
    batch512 iter2b iteration 1
    batch512 iter2b iteration 2
    batch512 iter2c iteration 1
    batch512 iter2c iteration 2
```

Interpretation:

```text
1. Another 1024 scored free candidates all died as hard q-gap no-roots.
2. Cumulative scored-free q-gap direct checks are now 3072 candidates:
   256 initial + 512 loop smoke + 512 batch512 + 1024 iter2b + 1024 iter2c.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 parallel sampling smoke and batch512

Code update:

```text
run_pwindow420_scored_batches.py
  added --sample-shards
  added --sample-workers
```

The runner can now split the SAT sample stage into independent shards, merge
unique selected-cube samples, then run the existing scorer and q-gap direct
steps unchanged.

Smoke:

```text
tmp/ct07_pwindow420_parallel_sampling_smoke_light_20260607
batch size: 8
sample shards/workers: 4/4
q-gap direct: 8/8 no_roots, no factor
elapsed: 4.56s
```

Real batch:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter1
iterations: 1
batch size: 512
sample shards/workers: 4/4
random assumptions: 64 selected bits
solver timeout: 10000ms
q-gap workers: 8
```

Results:

```text
samples:
  shard 1: 128/128
  shard 2: 128/128
  shard 3: 128/128
  shard 4: 128/128
  merged: 512 unique samples

q-gap direct:
  512/512 no_roots, no factor
  q_gap distribution: 230:56, 231:123, 232:265, 233:20, 234:46, 236:2

total loop:
  elapsed: 471.88s
  status: no_factor
```

Interpretation:

```text
1. Parallel sampling reduced the batch512 wall time materially:
   previous batch512 iterations were about 664-703s each, this one was 471.88s.
2. The new 512 candidates also all died as hard q-gap no-roots.
3. Cumulative scored-free q-gap direct checks are now 3584 candidates:
   3072 previous + 512 parallel4 batch.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 parallel4 iter2 and parallel8 check

Parallel8 check:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel8_iter1
sample shards/workers: 8/8
result: stopped manually before any sample JSONL records were produced
reason: after about 3.5 minutes, all 8 sample workers were still in the first
  SAT sample search with no output; this was worse than the 4-shard behavior.
```

Interpretation:

```text
Do not use sample_shards=8 for this current sampler/ledger load unless the
sampler is redesigned.  sample_shards=4 remains the practical setting.
```

Parallel4 batch:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter2
iterations: 1
batch size: 512
sample shards/workers: 4/4
random assumptions: 64 selected bits
solver timeout: 10000ms
q-gap workers: 8
```

Results:

```text
samples:
  shard 1: 128/128
  shard 2: 128/128
  shard 3: 128/128
  shard 4: 128/128
  merged: 512 unique samples

q-gap direct:
  512/512 no_roots, no factor
  q_gap distribution: 230:52, 231:108, 232:287, 233:11, 234:47, 236:7

total loop:
  elapsed: 549.28s
  status: no_factor
```

Interpretation:

```text
1. This adds another 512 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 4096 candidates:
   3584 previous + 512 parallel4 iter2.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 parallel4 iter3-4

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter3_4
iterations: 2
batch size: 512
sample shards/workers: 4/4
random assumptions: 64 selected bits
solver timeout: 10000ms
q-gap workers: 8
```

Results:

```text
iteration 1:
  samples: 4 shards x 128, merged 512
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:72, 231:117, 232:265, 233:12, 234:43, 236:3
  elapsed: 567.36s

iteration 2:
  samples: 4 shards x 128, merged 512
  q-gap direct: 512/512 no_roots, no factor
  q_gap distribution: 230:57, 231:107, 232:276, 233:14, 234:54, 236:4
  elapsed: 536.82s

total loop:
  elapsed: 1104.22s
  status: no_factor
```

Interpretation:

```text
1. This adds another 1024 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 5120 candidates:
   4096 previous + 1024 parallel4 iter3-4.
3. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 diversified x0/x7 cap batch

Code update:

```text
run_pwindow420_scored_batches.py now forwards scorer cap options:
  --score-max-per-x0
  --score-max-per-x7
  --score-max-per-x2mid
  --score-max-per-x3low
  --score-max-per-x3mid
  --score-max-per-x3high
```

Rationale:

```text
Recent scored batches were strongly skewed toward x0=0 and x7=0, with q_gap
mostly 232.  Existing scorer caps were available in score_selected_cube_samples.py
but were not exposed by the batch runner.
```

Probe:

```text
existing 512-sample batch, x0/x7 cap 64:
  retained: 329/512

existing 512-sample batch, x0/x7 cap 48:
  retained: 294/512

existing 512-sample batch, x0/x7 cap 64 and x2/x3 byte caps 32:
  retained: 295/512
```

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap64_batch768
iterations: 1
batch size: 768
sample shards/workers: 4/4
random assumptions: 64 selected bits
score caps:
  x0: 64
  x7: 64
q-gap workers: 8
```

Results:

```text
samples: 768
retained after score caps: 403
q-gap direct: 403/403 no_roots, no factor
q_gap distribution: 230:69, 231:134, 232:127, 233:20, 234:49, 236:4
elapsed: 536.54s
```

Selector effect:

```text
x0 top counts after cap:
  0:64, 8:64, 2:59, 1:57, 4:51
x7 top counts after cap:
  8:64, 1:64, 0:64, 4:51, 2:49
```

Interpretation:

```text
1. The cap worked: x0/x7 no longer collapse mostly to 0.
2. q_gap distribution shifted from mostly 232 to a more balanced 231/232 mix.
3. This adds 403 hard q-gap no-root candidates.
4. Cumulative scored-free q-gap direct checks are now 5523 candidates:
   5120 previous + 403 diversified cap batch.
5. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 diversified x0/x7 cap batch1024

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap64_batch1024
iterations: 1
batch size: 1024
sample shards/workers: 4/4
random assumptions: 64 selected bits
score caps:
  x0: 64
  x7: 64
q-gap workers: 8
```

Results:

```text
samples: 1024
retained after score caps: 434
q-gap direct: 434/434 no_roots, no factor
q_gap distribution: 230:72, 231:151, 232:153, 233:18, 234:40
elapsed: 597.43s
```

Selector effect:

```text
x0 top counts after cap:
  8:64, 4:64, 0:64, 2:64, 1:60
x7 top counts after cap:
  8:64, 1:64, 0:64, 4:64, 2:40
```

Interpretation:

```text
1. This adds 434 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 5957 candidates:
   5523 previous + 434 diversified cap batch1024.
3. Batch1024 only retained 31 more candidates than batch768 under x0/x7 cap64,
   so batch768 is the better capped setting unless the cap is relaxed.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 diversified x0/x7 cap96 batch1024

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_batch1024
iterations: 1
batch size: 1024
sample shards/workers: 4/4
random assumptions: 64 selected bits
score caps:
  x0: 96
  x7: 96
q-gap workers: 8
```

Results:

```text
samples: 1024
retained after score caps: 585
q-gap direct: 585/585 no_roots, no factor
q_gap distribution: 230:105, 231:191, 232:190, 233:27, 234:69, 236:3
all retained candidates: hard eligible
roots returned: 0
elapsed: 749.45s
```

Selector effect:

```text
x0 top counts after cap:
  0:96, 2:84, 1:83, 8:82, 4:78
x7 top counts after cap:
  0:96, 8:96, 4:75, 1:74, 2:69
```

Interpretation:

```text
1. This adds 585 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 6542 candidates:
   5957 previous + 585 cap96 batch1024.
3. Cap96 improves retained yield over cap64 batch1024 by 151 candidates
   at the same sample size, but it reintroduces x0/x7 values at the cap.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 diversified x0/x7 cap96 batch1024 seed20262600

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_batch1024_seed20262600
iterations: 1
batch size: 1024
sample shards/workers: 4/4
random assumptions: 64 selected bits
random seed base: 20262600
score caps:
  x0: 96
  x7: 96
q-gap workers: 8
```

Results:

```text
samples: 1024
retained after score caps: 586
q-gap direct: 586/586 no_roots, no factor
q_gap distribution: 230:101, 231:201, 232:184, 233:23, 234:71, 236:6
all retained candidates: hard eligible
roots returned: 0
elapsed: 713.92s
```

Selector effect:

```text
x0 top counts after cap:
  0:96, 1:84, 2:84, 4:78, 8:73
x7 top counts after cap:
  0:96, 8:96, 1:86, 2:71, 4:68
```

Interpretation:

```text
1. This adds 586 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 7128 candidates:
   6542 previous + 586 cap96 seed20262600 batch.
3. Cap96 retained yield is stable across two seeds: 585 and 586 retained
   rows from 1024 samples.
4. No factor/plaintext has been recovered.
```

### 2026-06-07 pwindow420 x0/x7 cap96 with x2/x3 cap probe and run

Probe on existing sample:

```text
sample source:
  tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_batch1024_seed20262600/iteration_0001_samples.json

x0/x7 cap96 only:
  retained: 586

x0/x7 cap96 + x2mid/x3low/x3mid/x3high cap80:
  retained: 557

x0/x7 cap96 + x2mid/x3low/x3mid/x3high cap64:
  retained: 518

x0/x7 cap80 only:
  retained: 541
```

Run:

```text
tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_x2x3cap80_batch1024_seed20263600
iterations: 1
batch size: 1024
sample shards/workers: 4/4
random assumptions: 64 selected bits
random seed base: 20263600
score caps:
  x0: 96
  x7: 96
  x2mid: 80
  x3low: 80
  x3mid: 80
  x3high: 80
q-gap workers: 8
```

Results:

```text
samples: 1024
retained after score caps: 552
q-gap direct: 552/552 no_roots, no factor
q_gap distribution: 230:102, 231:185, 232:178, 233:23, 234:59, 236:5
all retained candidates: hard eligible
roots returned: 0
elapsed: 723.93s
```

Selector effect:

```text
x0 top counts after cap:
  0:96, 1:88, 2:77, 4:68, 8:66
x7 top counts after cap:
  0:96, 1:96, 8:96, 4:62, 2:59
x2mid top count after cap:
  0:80
x3low top count after cap:
  0:73
x3mid top count after cap:
  0:72
x3high top count after cap:
  0:80
```

Interpretation:

```text
1. This adds 552 hard q-gap no-root candidates.
2. Cumulative scored-free q-gap direct checks are now 7680 candidates:
   7128 previous + 552 x2/x3 cap80 batch.
3. x2/x3 cap80 costs about 5-6% retained yield compared with cap96-only
   probe results, while reducing selector concentration across the x2/x3
   byte-family buckets.
4. No factor/plaintext has been recovered.
```

### 2026-06-08 latest pwindow420 minimization status

Fourth pwindow420 minimization continuation:

```text
output:
  tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more3_seed20260608
command shape:
  run_fullx1x5_drop_loop.py
  cube_ranges = 150:4,265:84,362:58,920:4
  drop_mode = hybrid
  cumulative drop windows = 150:4, 920:4
  independent drop windows = 265:4,269:4,273:4,277:4,362:4,366:4,370:4,374:4
  workers = 8
  q_gap_epsilon = 0.04
  q_gap_max_bits = 462
  q_gap_oracle_timeout_seconds = 120
  q_gap_minimize_max_completions = 256
elapsed:
  449.21s
exit:
  2, no factor
```

Result:

```text
selected cube:
  150:4 value 0x9
  265:84 value 0x2500
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  9
q-gap calls:
  401
loaded hard clauses:
  27565
```

All minimization drops succeeded again:

```text
cumulative:
  150:4 + 920:4 -> 142-literal hard clause
independent:
  265:4,269:4,273:4,277:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4 -> 146-literal hard clauses
```

Current pwindow420 status:

```text
direct scored q-gap coverage:
  7680 candidates, all hard no_roots, no factor
pwindow420 minimization coverage:
  4 representatives
  32 generalized hard clauses
active pwindow420 manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  21 JSONLs = 17 direct ledgers + 4 minimization ledgers
factor/plaintext:
  not recovered
```

Implementation note:

```text
run_fullx1x5_drop_loop.py --manifest-output was corrected to append only newly
produced iteration JSONLs.  The first real run briefly expanded the focused
pwindow420 manifest with the full combined resume-ledger list; that was repaired
back to the intended 21-line manifest.
```

Fifth pwindow420 minimization continuation, after fixing `--manifest-output`:

```text
output:
  tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more4_seed20260608
elapsed:
  425.17s
exit:
  2, no factor
selected cube:
  150:4 value 0xb
  265:84 value 0x3700
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  9
q-gap calls:
  401
loaded hard clauses:
  27574
```

The corrected manifest append behavior was verified:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  22 JSONLs = 17 direct ledgers + 5 minimization ledgers
```

Updated current pwindow420 status:

```text
direct scored q-gap coverage:
  7680 candidates, all hard no_roots, no factor
pwindow420 minimization coverage:
  5 representatives
  41 generalized hard clauses
factor/plaintext:
  not recovered
```

Sixth pwindow420 minimization continuation, with wider x2/x3 nibble windows:

```text
output:
  tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_expanded_seed20260608
elapsed:
  450.56s
exit:
  2, no factor
selected cube:
  150:4 value 0x8
  265:84 value 0x3500
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27583
```

All expanded minimization drops succeeded:

```text
cumulative:
  150:4 + 920:4 -> 142-literal hard clause
independent:
  265:4,269:4,273:4,277:4,281:4,285:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4,378:4,382:4 -> 146-literal hard clauses
```

Seventh pwindow420 minimization continuation, testing x2 low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x2low8_cumulative_seed20260608
elapsed:
  525.74s
exit:
  2, no factor
selected cube:
  150:4 value 0xa
  265:84 value 0x3400
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27596
```

The x2 low-8 cumulative drop succeeded:

```text
cumulative:
  265:4 + 269:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  273:4,277:4,281:4,285:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4,378:4,382:4 -> 146-literal hard clauses
```

Eighth pwindow420 minimization continuation, testing x3 low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x3low8_cumulative_seed20260608
elapsed:
  about 526s
exit:
  2, no factor
selected cube:
  150:4 value 0x9
  265:84 value 0x3600
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27609
```

The x3 low-8 cumulative drop succeeded:

```text
cumulative:
  362:4 + 366:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  265:4,269:4,273:4,277:4,281:4,285:4 -> 146-literal hard clauses
  370:4,374:4,378:4,382:4 -> 146-literal hard clauses
```

Updated current pwindow420 status:

```text
direct scored q-gap coverage:
  7680 candidates, all hard no_roots, no factor
pwindow420 minimization coverage:
  8 representatives
  80 generalized hard clauses
active pwindow420 manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  25 JSONLs = 17 direct ledgers + 8 minimization ledgers
factor/plaintext:
  not recovered
```

Ninth pwindow420 minimization continuation, testing x2 second low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x2mid8_cumulative_seed20260608
exit:
  2, no factor
selected cube:
  150:4 value 0xb
  265:84 value 0x2200
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27622
```

The x2 second low-8 cumulative drop succeeded:

```text
cumulative:
  273:4 + 277:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  265:4,269:4,281:4,285:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4,378:4,382:4 -> 146-literal hard clauses
```

Tenth pwindow420 minimization continuation, testing x3 second low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x3mid8_cumulative_seed20260608
exit:
  2, no factor
selected cube:
  150:4 value 0xf
  265:84 value 0x2300
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27635
```

The x3 second low-8 cumulative drop succeeded:

```text
cumulative:
  370:4 + 374:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  265:4,269:4,273:4,277:4,281:4,285:4 -> 146-literal hard clauses
  362:4,366:4,378:4,382:4 -> 146-literal hard clauses
```

Updated current pwindow420 status:

```text
direct scored q-gap coverage:
  7680 candidates, all hard no_roots, no factor
pwindow420 minimization coverage:
  10 representatives
  106 generalized hard clauses
active pwindow420 manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  27 JSONLs = 17 direct ledgers + 10 minimization ledgers
factor/plaintext:
  not recovered
```

Eleventh pwindow420 minimization continuation, testing x2 third low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x2high8_cumulative_seed20260608
exit:
  2, no factor
selected cube:
  150:4 value 0xd
  265:84 value 0x3300
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27648
```

The x2 third low-8 cumulative drop succeeded:

```text
cumulative:
  281:4 + 285:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  265:4,269:4,273:4,277:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4,378:4,382:4 -> 146-literal hard clauses
```

Twelfth pwindow420 minimization continuation, testing x3 third low-8 cumulative drop:

```text
output:
  tmp/ct07_pwindow420_minloop_x3high8_cumulative_seed20260608
exit:
  2, no factor
selected cube:
  150:4 value 0xf
  265:84 value 0x3200
  362:58 value 0x0
  920:4 value 0x0
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned variants:
  13
q-gap calls:
  465
loaded hard clauses:
  27661
```

The x3 third low-8 cumulative drop succeeded:

```text
cumulative:
  378:4 + 382:4 -> 142-literal hard clause
independent:
  150:4,920:4 -> 146-literal hard clauses
  265:4,269:4,273:4,277:4,281:4,285:4 -> 146-literal hard clauses
  362:4,366:4,370:4,374:4 -> 146-literal hard clauses
```

Updated current pwindow420 status:

```text
direct scored q-gap coverage:
  7680 candidates, all hard no_roots, no factor
pwindow420 minimization coverage:
  12 representatives
  132 generalized hard clauses
active pwindow420 manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  29 JSONLs = 17 direct ledgers + 12 minimization ledgers
factor/plaintext:
  not recovered
```

Pwindow420 x2 12-bit union proof:

```text
output:
  tmp/ct07_pwindow420_union12_x2low12_seed20260608
cube:
  150:4 value 0xf
  265:84 value 0x3200
  362:58 value 0x0
  920:4 value 0x0
drop windows:
  265:4
  269:4
  273:4
completion count:
  4096
shards:
  8 shards, shard size 512
status:
  proved
status counts:
  no_roots = 4096
hard eligible completions:
  4096 / 4096
oracle calls:
  4096
factor/plaintext:
  not recovered
```

The first shard was run as a timing preflight and took 254.81s.  The remaining
seven shards completed in 1864.99s.  The combined proof took about 35.3 minutes
of wall time and wrote a compact hard learned clause:

```text
tmp/ct07_pwindow420_union12_x2low12_seed20260608/learned_clause.jsonl
learned clause:
  q_gap_coppersmith_no_root
scope:
  minimized_q_gap_selected_bits
literal count:
  138
dropped literal count:
  12
dropped bits:
  265..276
```

The active pwindow420 manifest now includes the union learned clause:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  30 JSONLs = 17 direct ledgers + 12 minimization ledgers + 1 union learned clause
current hard clause count represented by this pwindow420 line:
  133 generalized hard clauses
factor/plaintext:
  not recovered
```

Pwindow420 x3 12-bit union proof:

```text
output:
  tmp/ct07_pwindow420_union12_x3low12_seed20260608
cube:
  150:4 value 0xf
  265:84 value 0x3200
  362:58 value 0x0
  920:4 value 0x0
drop windows:
  362:4
  366:4
  370:4
completion count:
  4096
shards:
  8 shards, shard size 512
elapsed:
  2234.62s
status:
  proved
status counts:
  no_roots = 4096
hard eligible completions:
  4096 / 4096
oracle calls:
  4096
factor/plaintext:
  not recovered
```

The proof wrote a compact hard learned clause:

```text
tmp/ct07_pwindow420_union12_x3low12_seed20260608/learned_clause.jsonl
learned clause:
  q_gap_coppersmith_no_root
scope:
  minimized_q_gap_selected_bits
literal count:
  138
dropped literal count:
  12
dropped bits:
  362..373
```

The active pwindow420 manifest now includes both 12-bit union learned clauses:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  31 JSONLs = 17 direct ledgers + 12 minimization ledgers + 2 union learned clauses
current hard clause count represented by this pwindow420 line:
  134 generalized hard clauses
factor/plaintext:
  not recovered
```

Post-union pwindow420 SAT selection check:

```text
loaded manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
loaded files:
  31
loaded learned clauses:
  8070
selected cube:
  150:4 value 0x0
  265:84 value 0x0
  362:58 value 0x0
  920:4 value 0x0
product prefix:
  sat at check_bits=362
q_low_bits:
  600
q_prefix_start:
  832
```

This means the two 12-bit union clauses are valid and loaded, but they do not
by themselves move SAT selection away from the local all-zero representative.
I ran a direct q-gap check on that representative with minimization disabled:

```text
output:
  tmp/ct07_pwindow420_after_union12_direct_nextcube_seed20260608
exit:
  2, no factor
q_gap_bits:
  232
direct q-gap:
  no_roots, roots_returned=0
learned scope:
  q_gap_selected_bits
learned literal count:
  150
q-gap calls:
  1
loaded hard clauses:
  8070
```

The active pwindow420 manifest now includes this direct q-gap hard clause:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  32 JSONLs = 17 direct ledgers + 12 minimization ledgers + 2 union learned clauses + 1 post-union direct ledger
current hard clause count represented by this pwindow420 line:
  135 generalized/direct hard clauses
factor/plaintext:
  not recovered
```

Diversified pwindow420 hit-first q-gap batches after the 12-bit union proofs:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20260680
parameters:
  batch_size = 1024
  sample_shards = 8
  sample_workers = 8
  workers = 8
  random_assumption_bits = 64
  score caps = x0<=96, x7<=96, x2/x3 buckets<=80
elapsed:
  461.63s
sample:
  1024 sat
scored:
  557 retained
q-gap direct:
  557 / 557 no_roots
factor/plaintext:
  not recovered
```

Second cap96/cap80 seed:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20261680
elapsed:
  502.80s
sample:
  1024 sat
scored:
  569 retained
q-gap direct:
  569 / 569 no_roots
factor/plaintext:
  not recovered
```

The two cap96/cap80 batches had zero duplicate full pwindow420 cubes between
them, so this path is still covering fresh candidates.

Third, tighter cap64/cap64 seed:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap64_x2x3cap64_seed20262680
elapsed:
  340.67s
sample:
  384 sat, 5 unknown
scored:
  248 retained
q-gap direct:
  248 / 248 no_roots
factor/plaintext:
  not recovered
```

The cap64/cap64 setting gave better diversity pressure but much lower retained
throughput.  For hit-first coverage, cap96/cap80 is currently the better
default.

Fourth cap96/cap80 seed:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20263680
elapsed:
  475.32s
sample:
  1024 sat
scored:
  560 retained
q-gap direct:
  560 / 560 no_roots
factor/plaintext:
  not recovered
```

Additional cap96/cap80 seeds:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20264680
elapsed:
  470.94s
sample:
  1024 sat
scored:
  542 retained
q-gap direct:
  542 / 542 no_roots
factor/plaintext:
  not recovered
```

Seed `20265680` initially failed to sample under the 1000ms SAT timeout:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20265680
status:
  sample_empty
sample status:
  unknown = 8
elapsed:
  159.98s
```

The same seed with `solver_timeout_ms=5000` and `random_assumption_retries=64`
worked:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20265680_t5000
elapsed:
  516.25s
sample:
  1024 sat
scored:
  584 retained
q-gap direct:
  584 / 584 no_roots
factor/plaintext:
  not recovered
```

The five cap96/cap80 after-union batches have zero duplicate full pwindow420
cubes among them:

```text
counts:
  557, 569, 560, 542, 584
union:
  2812
duplicates:
  0
```

Two-iteration cap96/cap80 run with the stable t5000 sampling settings:

```text
output:
  tmp/ct07_pwindow420_scored_after_union12_diverse_cap96_x2x3cap80_seed20266680_iter2_t5000
parameters:
  solver_timeout_ms = 5000
  random_assumption_retries = 64
elapsed:
  1042.47s
iteration 1:
  sample = 1024 sat
  scored = 569 retained
  q-gap direct = 569 / 569 no_roots
iteration 2:
  sample = 1024 sat
  scored = 532 retained
  q-gap direct = 532 / 532 no_roots
factor/plaintext:
  not recovered
```

The seven cap96/cap80 after-union q-gap batches still have zero duplicate full
pwindow420 cubes:

```text
counts:
  557, 569, 560, 542, 584, 569, 532
union:
  3913
duplicates:
  0
```

Updated active pwindow420 manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  40 JSONLs
  12112 cube records
  12232 loadable hard clauses, counting learned-clause variants
  q-gap no_roots observed in manifest cube rows: 12110
  factors observed in manifest cube rows: 0
factor/plaintext:
  not recovered
```

## 2026-06-08 pwindow420 SAT-Selected and Guarded Direct Closure

After the two completed 12-bit union proofs and seven cap96/cap80
post-union batches, the active pwindow420 manifest was extended with direct
q-gap closures selected by the SAT loop.

SAT-selected direct closure from the 40-ledger manifest:

```text
output:
  tmp/ct07_pwindow420_satselected_direct_after_40ledgers_seed20260608
parameters:
  cube_ranges = 150:4,265:84,362:58,920:4
  drop_mode = none
  q_gap_epsilon = 0.04
  q_gap_max_bits = 462
  q_gap_oracle_timeout_seconds = 120
elapsed:
  688.04s
iterations:
  8
result:
  8 / 8 q-gap hard no_roots
  factor/plaintext not recovered
```

The follow-up SAT diagnostic still selected the local basin:

```text
loaded learned clauses: 12240
next cubes:
  x0=14, x2=8,   x3=0, x7=0
  x0=0,  x2=8,   x3=0, x7=0
  x0=8,  x2=8,   x3=0, x7=0
  x0=8,  x2=16,  x3=0, x7=0
  x0=12, x2=16,  x3=0, x7=0
  x0=12, x2=32,  x3=0, x7=0
  x0=12, x2=64,  x3=0, x7=0
  x0=12, x2=256, x3=0, x7=0
```

Guarded diagonal closure was then run to force exploration away from that
basin:

```text
output:
  tmp/ct07_pwindow420_guarded_x7_x3_x2low_diag_after_48ledgers_seed20260608
assumption cycles:
  920:4 = 1..8
  362:4 = 1..8
  265:8 = 1..8
elapsed:
  733.44s
iterations:
  8
result:
  8 / 8 q-gap hard no_roots
  q_gap_bits = 230..234
  factor/plaintext not recovered
```

Closed guarded cubes:

```text
x0=0, x2=1, x3=1, x7=1
x0=0, x2=2, x3=2, x7=2
x0=0, x2=3, x3=3, x7=3
x0=0, x2=4, x3=4, x7=4
x0=0, x2=5, x3=5, x7=5
x0=0, x2=6, x3=6, x7=6
x0=0, x2=7, x3=7, x7=7
x0=0, x2=8, x3=8, x7=8
```

Updated active pwindow420 manifest after the guarded run:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  56 JSONLs
  12128 cube records
  12248 loadable hard clauses, counting learned-clause variants
  q-gap no_roots observed in manifest cube rows: 12126
  factors observed in manifest cube rows: 0
factor/plaintext:
  not recovered
```

The follow-up SAT diagnostic still returned to the same local shape:

```text
loaded learned clauses: 12248
next cubes:
  x0=14, x2=8,   x3=0, x7=0
  x0=0,  x2=8,   x3=0, x7=0
  x0=8,  x2=8,   x3=0, x7=0
  x0=8,  x2=16,  x3=0, x7=0
  x0=12, x2=16,  x3=0, x7=0
  x0=12, x2=32,  x3=0, x7=0
  x0=12, x2=64,  x3=0, x7=0
  x0=12, x2=256, x3=0, x7=0
```

Ranker diagnostics:

```text
tmp/ct07_pwindow420_rank_x3low4_x7_after56.json
  evaluated new pairs: 23
  skipped seen pairs: 233
  sat records: 0
  status of new pairs: unknown

tmp/ct07_pwindow420_rank_x2low8_x7_after56.json
  not written
  reason: 4096-pair full ranker remained CPU-bound after about 6 minutes and
          was stopped
```

Interpretation: pwindow420 q-gap direct closure remains a sound hard oracle,
but it is now primarily proof-accounting work.  Manual forced cycles can add
valid clauses, but they do not materially improve hit-first odds.  The next
useful change is a cheaper cached/subsampled pwindow420 ranker or a different
selector objective; repeatedly closing the same SAT-local basin is lower
priority.

## 2026-06-08 Projection Novelty Frontier

`build_projection_frontier.py` was added to avoid an expensive all-pairs Z3
ranker.  It reads the active learned-ledger manifest, counts compact
pwindow420 projections, and emits a `sample_diverse_edge_completions.py`
frontier over projection keys with low or zero prior coverage.

Default projection:

```text
150:4   x0
265:8   x2low8
362:4   x3low4
920:4   x7
```

First novelty frontier:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/build_projection_frontier.py \
  --manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
  --output tmp/ct07_pwindow420_projection_frontier_x0_x2low8_x3low4_x7_seed20260608.json \
  --top 96 --candidate-pool 8192 --max-seen-count 0 \
  --prefer-unseen --seed 20260608 --json
```

Result:

```text
projection space: 1048576
unique seen projection keys before the run: 8865
frontier rows: 96 unseen projection keys
```

Sampling and q-gap direct:

```text
sample:
  tmp/ct07_pwindow420_projection_frontier_sample64_seed20260608.json
  64 / 64 SAT samples
  elapsed 16.41s
q-gap:
  tmp/ct07_pwindow420_projection_frontier_sample64_qgap_direct_seed20260608.json
  64 / 64 hard no_roots
  q_gap_bits in {230,231,232,233,234,236}
  elapsed 58.14s
factor/plaintext:
  not recovered
```

Second novelty frontier after adding the first 64 q-gap clauses:

```text
frontier:
  tmp/ct07_pwindow420_projection_frontier_x0_x2low8_x3low4_x7_seed20260609.json
  128 unseen projection keys from a 16384-key random candidate pool
sample:
  tmp/ct07_pwindow420_projection_frontier_sample128_seed20260609.json
  128 / 128 SAT samples
  elapsed 33.37s
q-gap:
  tmp/ct07_pwindow420_projection_frontier_sample128_qgap_direct_seed20260609.json
  128 / 128 hard no_roots
  q_gap_bits in {230,231,232,233,234,236}
  elapsed 57.54s
factor/plaintext:
  not recovered
```

Updated active pwindow420 manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  58 JSONLs
  12320 cube records
  12440 loadable hard clauses, counting learned-clause variants
  q-gap no_roots observed in manifest cube rows: 12318
  factors observed in manifest cube rows: 0
factor/plaintext:
  not recovered
```

Default SAT diagnostic after the two novelty batches still returns to the
same local shape:

```text
loaded learned clauses: 12440
next cubes:
  x0=14, x2=8,  x3=0, x7=0
  x0=0,  x2=8,  x3=0, x7=0
  x0=8,  x2=8,  x3=0, x7=0
  x0=8,  x2=16, x3=0, x7=0
```

Interpretation: projection novelty sampling is much cheaper than the stopped
4096-pair Z3 ranker and successfully avoids the local projection basin.  It is
still a hit-first coverage sampler, not proof compression.  The default SAT
model should not be used as the main selector without an additional novelty or
objective layer.

## 2026-06-08 Projection Frontier Batch Runner

`run_projection_frontier_batches.py` now wraps the projection novelty flow:

```text
build_projection_frontier.py
-> sample_diverse_edge_completions.py
-> run_ranked_q_gap_direct.py
-> append q-gap JSONL to the active manifest
```

The first smoke attempt showed why stage timeouts are needed:

```text
output:
  tmp/ct07_projection_frontier_runner_smoke_seed20260610
result:
  stopped manually during sampling
reason:
  one sample_diverse_edge_completions.py process ran for more than 145s on a
  hard unseen projection
```

The runner now starts child commands in their own process group and supports:

```text
--frontier-timeout-seconds
--sample-timeout-seconds
--qgap-timeout-seconds
```

Successful smoke with lighter sampling:

```text
output:
  tmp/ct07_projection_frontier_runner_smoke2_seed20260612
parameters:
  max_total = 32
  solver_timeout_ms = 1000
  random_assumption_bits = 32
  random_assumption_retries = 8
elapsed:
  111.59s
sample:
  32 / 32 SAT
q-gap:
  32 / 32 hard no_roots
factor/plaintext:
  not recovered
```

Operational 128-candidate batch:

```text
output:
  tmp/ct07_projection_frontier_runner_batch128_seed20260620
parameters:
  frontier_top = 160
  candidate_pool = 24576
  top_pairs = 64
  samples_per_pair = 2
  max_total = 128
  solver_timeout_ms = 1000
  random_assumption_bits = 32
  random_assumption_retries = 8
elapsed:
  188.88s
sample:
  128 / 128 SAT
q-gap:
  128 / 128 hard no_roots
  q_gap_bits in {230,231,232,233,234,236}
factor/plaintext:
  not recovered
```

Updated active pwindow420 manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  60 JSONLs
  q-gap ledgers added by the runner:
    tmp/ct07_projection_frontier_runner_smoke2_seed20260612/iteration_0001_qgap.jsonl
    tmp/ct07_projection_frontier_runner_batch128_seed20260620/iteration_0001_qgap.jsonl
factor/plaintext:
  not recovered
```

Use the runner for future bounded novelty batches.  Prefer
`solver_timeout_ms=1000`, `random_assumption_bits=32`, and
`random_assumption_retries=8` unless a specific frontier is known to sample
quickly.  The slower 5000ms/64-bit sampling mode can still work, but it is less
predictable after the manifest grows.

## 2026-06-08 full-x1/full-x5 Projection Novelty Probe

Deep product-prefix scoring was tested on existing pwindow420 samples before
adding another ranker layer:

```text
check_bits=600: 16 / 16 SAT, about 0.01s total
check_bits=620: 16 / 16 SAT, about 0.015s total
check_bits=624:  8 /  8 SAT, essentially immediate
check_bits>=628: all tested rows returned unknown under 20-500ms timeouts
```

This is not useful as a pwindow420 ranking signal: below 628 bits it is too
weak, and at or above 628 bits it becomes timeout-heavy without distinguishing
candidate quality.

The projection novelty runner was then applied to the lower-cost
full-x1/full-x5 q-gap shape:

```text
cube ranges:
  150:4,265:84,784:46,920:4
projection:
  150:4   x0
  265:8   x2low8
  784:8   x6low8
  920:4   x7
```

Smoke:

```text
output:
  tmp/ct07_fullx1x5_projection_runner_smoke_seed20260630
elapsed:
  14.63s
sample:
  32 / 32 SAT
q-gap:
  32 / 32 hard no_roots
  q_gap_bits in {407,408,409,410,411,412,413}
factor/plaintext:
  not recovered
```

256-candidate batch:

```text
output:
  tmp/ct07_fullx1x5_projection_runner_batch256_seed20260631
elapsed:
  115.84s
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
  q_gap_bits in {407,408,409,410,411,412,413,414,415,416}
factor/plaintext:
  not recovered
```

Updated full-x1/full-x5 manifest:

```text
tmp/ct07_fullx1x5_resume_all_jsonl.txt
  83 JSONLs
  369 cube records
  619 loadable hard clauses, counting learned-clause variants
  factors observed in manifest cube rows: 0
```

Interpretation: this shape fixes 138 hidden bits instead of pwindow420's 150,
so it is a better hit-first target per candidate.  q-gap calls are more
expensive because the gap is about 407-416 bits, but the runner still processed
256 candidates in under two minutes on 8 workers.  This is now a useful
parallel hit-first line alongside pwindow420 projection novelty sampling.

## 2026-06-08 full-x1/full-x5 Projection Minimization Probe

A projection-frontier full-x1/full-x5 sample from
`tmp/ct07_fullx1x5_projection_runner_batch256_seed20260631` was used for a
q-gap minimization probe.

Fixed sample:

```text
150:4   = 15
265:84  = 377835688817235066421405
784:46  = 32770
920:4   = 0
```

Command shape:

```text
cube ranges:
  150:4,265:84,784:46,920:4
cumulative drops:
  150:4, 920:4
independent drops:
  784:8, 792:8
q_gap:
  epsilon = 0.04
  max_gap_bits = 462
  oracle_timeout_seconds = 120
workers:
  8
```

Result:

```text
output:
  tmp/ct07_fullx1x5_projection_minimize_sample1_seed20260631.jsonl
base q_gap_bits:
  409
q-gap calls:
  785
factor/plaintext:
  not recovered
```

All requested drops were hard no-root:

```text
150:4 cumulative step:
  16 / 16 no_roots
150:4 + 920:4 cumulative union:
  256 / 256 no_roots
784:8 independent:
  256 / 256 no_roots
792:8 independent:
  256 / 256 no_roots
```

Learned variants:

```text
cumulative x0+x7 drop:
  130 literals, 8 dropped bits
independent 784:8 drop:
  130 literals, 8 dropped bits
independent 792:8 drop:
  130 literals, 8 dropped bits
```

Updated full-x1/full-x5 manifest:

```text
tmp/ct07_fullx1x5_resume_all_jsonl.txt
  84 JSONLs
  370 cube records
  622 loadable hard clauses, counting learned-clause variants
  factors observed in manifest cube rows: 0
```

Interpretation: minimization works on projection-frontier samples and produces
useful generalized hard clauses, but it is much more expensive than direct
hit-first q-gap batches.  Use it selectively on ranked representatives, not on
every sample.  A better next automation would pick one representative per
projection cluster for minimization after a larger direct-hit batch.

## 2026-06-08 no-x7 low600 q-gap line

The corrected mask has another useful hard q-gap shape:

```text
cube ranges:
  150:4,265:84,362:58
fixed hidden bits:
  146
free hidden bits deliberately left outside the clause:
  x7 = 920:4
q known state:
  q_low_bits = 600
  q_prefix_start = 924
  q_gap_bits = 324
```

This is better than treating `x7` as part of the pwindow420 cube when the goal
is hard q-gap pruning: one no-root clause over `x0+x2+x3` blocks all 16 `x7`
completions for that low600 branch.

Smoke batch:

```text
output:
  tmp/ct07_nox7_low600_projection_runner_smoke_seed20260640
sample:
  64 / 64 SAT
q-gap:
  64 / 64 hard no_roots
  q_gap_bits = 324
factor/plaintext:
  not recovered
```

Larger batch:

```text
output:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260641
elapsed:
  254.38s
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
  q_gap_bits = 324
  q-gap stage elapsed 98.57s on 8 workers
factor/plaintext:
  not recovered
```

Comparison shape `x0+x5+x6+x7`:

```text
output:
  tmp/ct07_x0x5x6x7_projection_runner_smoke_seed20260642
cube ranges:
  150:4,682:87,784:46,920:4
fixed hidden bits:
  141
sample:
  64 / 64 SAT
q-gap:
  64 / 64 hard no_roots
  q_gap_bits in 404..410
  q-gap stage elapsed 21.58s on 8 workers
factor/plaintext:
  not recovered
```

Current focused manifest after these runs and the x0-only drop probe:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  64 JSONLs
  12865 cube records
  12985 loadable hard clauses, counting learned-clause variants
  factors observed in manifest cube rows: 0

shape histogram:
  150:4,265:84,362:58,920:4    12480
  150:4,265:84,362:58            321
  150:4,682:87,784:46,920:4       64
```

Minimization probe:

```text
output:
  tmp/ct07_nox7_low600_qgap_drop_x0only_seed20260644
drop:
  150:4
q-gap calls:
  17
result:
  16 / 16 drop completions hard no_roots
  learned one 142-literal variant
factor/plaintext:
  not recovered
```

A broader probe with independent byte drops at `265:8`, `273:8`, `362:8`, and
`370:8` was stopped after about ten minutes.  It had only emitted the learned
clause load report and produced no usable clause.  Do not run multi-byte
minimization on this shape without a tighter per-window timeout or a smaller
representative set.

Interpretation: no-x7 low600 is now the preferred hard q-gap branch killer.
It has a much smaller gap than full-x1/full-x5 and blocks all x7 completions,
but direct batches still remove one 146-bit branch at a time.  Use direct
projection batches for cheap coverage and occasional `150:4` drop probes for
small generalization; avoid broad byte-drop minimization until the minimizer can
budget each window separately.

## 2026-06-08 Representative no-x7 low600 Minimization Runner

Added:

```text
cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py
```

Purpose: consume existing q-gap JSONL cube ledgers, choose representative
no-root cube records, force each selected cube with `--cube-assume-p-range`,
and run q-gap minimization directly through `semi_programmatic_sat.py`.

Important implementation detail: this runner intentionally does not load prior
learned clauses.  For a representative cube, the source full-clause usually
already blocks the exact cube and would make the forced SAT instance unsat.
The minimization proof only depends on q-gap no-root checks over the forced
cube and its drop completions.

First representative minimization run:

```text
source:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260641/iteration_0001_qgap.jsonl
output:
  tmp/ct07_nox7_low600_rep_min_x0_seed20260645
records:
  4
elapsed:
  35.88s
q-gap calls:
  68
result:
  4 / 4 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Second representative minimization run:

```text
source:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260641/iteration_0001_qgap.jsonl
output:
  tmp/ct07_nox7_low600_rep_min_x0_seed20260646
records:
  12
elapsed:
  183.42s
q-gap calls:
  204
result:
  12 / 12 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Follow-up no-x7 direct batch after these variants:

```text
output:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260647
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
  q_gap_bits = 324
elapsed:
  244.56s total
  63.20s sampling
  102.32s q-gap
loaded clauses:
  13001 clauses
  1947558 literals
factor/plaintext:
  not recovered
```

Third representative minimization run:

```text
source:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260647/iteration_0001_qgap.jsonl
output:
  tmp/ct07_nox7_low600_rep_min_x0_seed20260648
records:
  8
elapsed:
  84.69s
q-gap calls:
  136
result:
  8 / 8 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  89 JSONLs
  13145 cube records
  13265 loadable hard clauses, counting learned-clause variants
  157 variant clauses across 37 variant records
  factors observed in manifest cube rows: 0

shape histogram:
  150:4,265:84,362:58,920:4    12480
  150:4,265:84,362:58            601
  150:4,682:87,784:46,920:4       64
```

Interpretation: representative minimization is now cheap enough for routine
use.  It avoids the 1.9M-literal SAT load cost and converts selected no-x7
low600 full clauses into clauses that block all `x0` completions for the same
`x2+x3` branch.  This should be alternated with direct no-x7 batches.

## 2026-06-08 Continued no-x7 low600 Cycle

Additional representative minimization on the previous direct batch:

```text
source:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260647/iteration_0001_qgap.jsonl
output:
  tmp/ct07_nox7_low600_rep_min_x0_seed20260649
records:
  24
elapsed:
  318.64s
q-gap calls:
  408
result:
  24 / 24 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Fresh no-x7 direct batch after those variants:

```text
output:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260650
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
  q_gap_bits = 324
elapsed:
  270.83s total
  56.20s sampling
  115.01s q-gap
loaded clauses:
  13289 clauses
  1989478 literals
factor/plaintext:
  not recovered
```

Representative minimization on the fresh batch:

```text
source:
  tmp/ct07_nox7_low600_projection_runner_batch256_seed20260650/iteration_0001_qgap.jsonl
output:
  tmp/ct07_nox7_low600_rep_min_x0_seed20260651
records:
  8
elapsed:
  76.68s
q-gap calls:
  136
result:
  8 / 8 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  122 JSONLs
  13433 cube records
  13553 loadable hard clauses, counting learned-clause variants
  189 variant clauses across 69 variant records
  factors observed in manifest cube rows: 0

shape histogram:
  150:4,265:84,362:58,920:4    12480
  150:4,265:84,362:58            889
  150:4,682:87,784:46,920:4       64
```

Interpretation: the alternating routine is stable, but it has not produced a
factor.  Direct no-x7 batches remain around 4-5 minutes per 256 candidates with
8 workers.  Representative x0-drop minimization remains reliable, but it is
still a coverage process over a very large `x2+x3` branch space.

## 2026-06-08 Variant-aware Projection Frontier

Updated:

```text
cryptotest/solutions/07_sat_cas_explore/build_projection_frontier.py
```

The frontier builder now expands `learned_clause_variants[*].dropped_bits` as
wildcards in the projection count.  This matters for the no-x7 low600 line:
an x0-drop learned variant blocks all 16 `x0` completions for the same `x2+x3`
branch, but the old frontier counter only counted the original cube's one x0
value.  That made already-generalized regions look less covered than they
really were.

Smoke check:

```text
output:
  tmp/ct07_variant_aware_frontier_check_seed20260652.json
projection:
  150:4, 265:8, 362:4
manifest:
  tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
result:
  unique_seen_projection_keys = 6796
  counted_projection_key_instances = 15559
  variant_projection_key_instances = 2261
  variant_records = 69
  variant_expansion_limit_fallback_exact = 0
```

Variant-aware direct batch:

```text
output:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
elapsed:
  251.80s total
  67.49s sampling
  99.51s q-gap
loaded clauses:
  13553 clauses
  2027990 literals
factor/plaintext:
  not recovered
```

Representative minimization on that batch:

```text
output:
  tmp/ct07_nox7_low600_variant_frontier_rep_min_x0_seed20260653
records:
  8
elapsed:
  94.36s
q-gap calls:
  136
result:
  8 / 8 minimized
  every learned variant drops 150:4
  every learned variant has 142 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  131 JSONLs
  13697 cube records
  13817 loadable hard clauses, counting learned-clause variants
  197 variant clauses across 77 variant records
  factors observed in manifest cube rows: 0

shape histogram:
  150:4,265:84,362:58,920:4    12480
  150:4,265:84,362:58           1153
  150:4,682:87,784:46,920:4       64
```

Interpretation: this fixes an accounting weakness in the novelty frontier.
It does not change oracle soundness, but it should reduce wasted sampling in
regions already covered by dropped-bit learned clauses.

## 2026-06-08 Cumulative Second-drop Probe

Updated:

```text
cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py
```

The representative minimization runner now supports:

```text
--drop-mode independent
--drop-mode cumulative
--drop-mode hybrid
```

This allows cumulative-only probes without also emitting independent drop
clauses.  The cumulative path is needed to test whether a second 4-bit window
can be dropped after the already reliable `150:4` x0 drop.

Probe 1: x0 + x2 low nibble.

```text
output:
  tmp/ct07_nox7_cumulative_x0_x2low4_seed20260654
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652/iteration_0001_qgap.jsonl
windows:
  150:4
  265:4
records:
  2
elapsed:
  251.15s
q-gap calls:
  273 per representative
result:
  2 / 2 cumulative minimized
  every learned variant drops 8 bits
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Probe 2: x0 + x3 low nibble.

```text
output:
  tmp/ct07_nox7_cumulative_x0_x3low4_seed20260655
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652/iteration_0001_qgap.jsonl
windows:
  150:4
  362:4
records:
  2
elapsed:
  250.46s
q-gap calls:
  273 per representative
result:
  2 / 2 cumulative minimized
  every learned variant drops 8 bits
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  135 JSONLs
  13701 cube records
  13821 loadable hard clauses, counting learned-clause variants
  201 variant clauses across 81 variant records
  factors observed in manifest cube rows: 0

variant literal histogram:
  138 literals:   4
  142 literals:  77
  146 literals: 120
```

Interpretation: a second 4-bit cumulative drop is feasible, at least for the
low nibbles of x2 and x3.  It is much more expensive than x0-only
minimization, but it produces stronger 138-literal clauses and should be used
selectively on representatives from fresh variant-aware batches.

## 2026-06-08 Continued Cumulative-drop Cycle

Additional cumulative x0+x2low4 validation:

```text
output:
  tmp/ct07_nox7_cumulative_x0_x2low4_more_seed20260656
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652/iteration_0001_qgap.jsonl
windows:
  150:4
  265:4
records:
  2
elapsed:
  290.97s
q-gap calls:
  546 total
result:
  2 / 2 cumulative minimized
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Additional cumulative x0+x3low4 validation:

```text
output:
  tmp/ct07_nox7_cumulative_x0_x3low4_more_seed20260657
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652/iteration_0001_qgap.jsonl
windows:
  150:4
  362:4
records:
  2
elapsed:
  244.70s
q-gap calls:
  546 total
result:
  2 / 2 cumulative minimized
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Variant-aware no-x7 direct batch after those variants:

```text
output:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260658
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
elapsed:
  293.84s total
  75.61s sampling
  97.06s q-gap
frontier accounting:
  unique_seen_projection_keys = 8474
  counted_projection_key_instances = 17991
  variant_projection_key_instances = 4437
  variant_records = 85
factor/plaintext:
  not recovered
```

Cumulative x0+x2low4 minimization on the fresh batch:

```text
output:
  tmp/ct07_nox7_cumulative_x0_x2low4_seed20260659
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260658/iteration_0001_qgap.jsonl
records:
  2
elapsed:
  238.32s
q-gap calls:
  546 total
result:
  2 / 2 cumulative minimized
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  142 JSONLs
  13963 cube records
  14083 loadable hard clauses, counting learned-clause variants
  207 variant clauses across 87 variant records
  factors observed in manifest cube rows: 0

variant literal histogram:
  138 literals:  10
  142 literals:  77
  146 literals: 120
```

Interpretation: cumulative x0+second-nibble minimization is repeatable.  It is
expensive enough that it should remain representative-only, but it now has
enough successful samples to use as the preferred strengthening step after a
fresh no-x7 direct batch.

## 2026-06-08 Continued Cumulative Cycle 2

Fresh-batch cumulative x0+x3low4 minimization:

```text
output:
  tmp/ct07_nox7_cumulative_x0_x3low4_seed20260660
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260658/iteration_0001_qgap.jsonl
records:
  2
elapsed:
  315.78s
q-gap calls:
  546 total
result:
  2 / 2 cumulative minimized
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Variant-aware no-x7 direct batch:

```text
output:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260661
sample:
  256 / 256 SAT
q-gap:
  256 / 256 hard no_roots
elapsed:
  254.45s total
  70.34s sampling
  97.00s q-gap
frontier accounting:
  unique_seen_projection_keys = 9426
  counted_projection_key_instances = 19271
  variant_projection_key_instances = 5461
  variant_records = 89
factor/plaintext:
  not recovered
```

Fresh-batch cumulative x0+x2low4 minimization:

```text
output:
  tmp/ct07_nox7_cumulative_x0_x2low4_seed20260662
source:
  tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260661/iteration_0001_qgap.jsonl
records:
  2
elapsed:
  271.75s
q-gap calls:
  546 total
result:
  2 / 2 cumulative minimized
  every learned variant has 138 literals
  factor/plaintext not recovered
```

Current focused manifest:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  147 JSONLs
  14223 cube records
  14343 loadable hard clauses, counting learned-clause variants
  211 variant clauses across 91 variant records
  factors observed in manifest cube rows: 0

variant literal histogram:
  138 literals:  14
  142 literals:  77
  146 literals: 120
```

Interpretation: the cumulative second-drop path remains repeatable across fresh
batches, but no factor signal has appeared.  Direct no-x7 q-gap batches remain
the hit-first line; cumulative representative minimization is the strengthening
line after each batch.

## 2026-06-08 no-x7 cycle runner

`run_nox7_cumulative_cycle.py` now wraps the current manual routine:

```text
1. run one no-x7 projection-frontier direct q-gap batch
2. append the direct q-gap JSONL to the active focused manifest
3. run representative cumulative x0+x2low4 minimization
4. optionally run representative cumulative x0+x3low4 minimization
5. write one cycle_summary.json with all child commands and summaries
```

The default no-x7 cube shape is still:

```text
150:4,265:84,362:58
```

Smoke command:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_nox7_cumulative_cycle.py \
  --output-dir tmp/ct07_nox7_cumulative_cycle_smoke_seed20260663 \
  --seed-base 20260663 \
  --direct-max-total 32 \
  --frontier-top 64 \
  --candidate-pool 4096 \
  --top-pairs 16 \
  --samples-per-pair 2 \
  --x2-cumulative-top 1 \
  --x3-cumulative-top 0 \
  --direct-command-timeout-seconds 1200 \
  --direct-qgap-timeout-seconds 900 \
  --cumulative-command-timeout-seconds 900 \
  --cumulative-item-timeout-seconds 420 \
  --json
```

Result:

```text
output:
  tmp/ct07_nox7_cumulative_cycle_smoke_seed20260663
direct:
  32 / 32 SAT
  32 / 32 q-gap hard no_roots
cumulative x0+x2low4:
  1 representative
  273 q-gap calls
  138-literal learned clause
factor/plaintext:
  not recovered
elapsed:
  288.42s
```

The smoke appended both the direct JSONL and the representative minimization
JSONL to the active focused manifest:

```text
tmp/ct07_nox7_cumulative_cycle_smoke_seed20260663/iteration_0001/direct/iteration_0001_qgap.jsonl
tmp/ct07_nox7_cumulative_cycle_smoke_seed20260663/iteration_0001/cumulative_x2low4/item_0001_line_000001/minimization.jsonl
```

Current focused manifest after the smoke:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  149 JSONLs
  14256 cube records
  10257 unique no-x7 projection keys seen
  6229 variant projection key instances
  92 variant records
  factors observed in manifest cube rows: 0
```

Use this runner for the next long continuation instead of manually chaining the
two lower-level commands.

## 2026-06-08 full no-x7 cycle continuation

Full-size one-iteration continuation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_nox7_cumulative_cycle.py \
  --output-dir tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1 \
  --seed-base 20260664 \
  --iterations 1 \
  --direct-max-total 256 \
  --frontier-top 320 \
  --candidate-pool 32768 \
  --top-pairs 128 \
  --samples-per-pair 2 \
  --x2-cumulative-top 2 \
  --x3-cumulative-top 2 \
  --workers 8 \
  --direct-command-timeout-seconds 2400 \
  --direct-qgap-timeout-seconds 1200 \
  --cumulative-command-timeout-seconds 1800 \
  --cumulative-item-timeout-seconds 420 \
  --json
```

Result:

```text
output:
  tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1
elapsed:
  754.62s
direct:
  256 / 256 SAT
  256 / 256 q-gap hard no_roots
cumulative x0+x2low4:
  2 representatives
  546 q-gap calls
  2 / 2 cumulative minimized
  every learned variant has 138 literals
cumulative x0+x3low4:
  2 representatives
  546 q-gap calls
  2 / 2 cumulative minimized
  every learned variant has 138 literals
factor/plaintext:
  not recovered
```

The run appended these five ledgers to the active focused manifest:

```text
tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/direct/iteration_0001_qgap.jsonl
tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/cumulative_x2low4/item_0001_line_000001/minimization.jsonl
tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/cumulative_x2low4/item_0002_line_000002/minimization.jsonl
tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/cumulative_x3low4/item_0001_line_000001/minimization.jsonl
tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/cumulative_x3low4/item_0002_line_000002/minimization.jsonl
```

Current focused manifest after the continuation:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  154 JSONLs
  14516 cube records
  11234 unique no-x7 projection keys seen
  7253 variant projection key instances
  96 variant records
  216 variant clauses
  factors observed in manifest cube rows: 0
```

Interpretation: the automated cycle is behaving as expected.  One full
iteration costs about 12.6 minutes on 8 workers and adds one direct batch plus
four strong 138-literal cumulative variants.  No factor signal has appeared, so
the next useful work is either a longer cycle run or a stronger representative
generalization than the current two 4-bit cumulative drops.

## 2026-06-08 triple-drop cost probe and direct continuation

Triple cumulative drop probe:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py \
  --source-jsonl tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1/iteration_0001/direct/iteration_0001_qgap.jsonl \
  --output-dir tmp/ct07_nox7_triple_cumulative_x0_x2_x3_seed20260665 \
  --append-manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
  --top 1 \
  --projection 150:4:x0 \
  --projection 265:8:x2low8 \
  --projection 362:4:x3low4 \
  --drop-mode cumulative \
  --cumulative-drop-window 150:4 \
  --cumulative-drop-window 265:4 \
  --cumulative-drop-window 362:4 \
  --q-gap-minimize-max-completions 4096 \
  --workers 8 \
  --item-timeout-seconds 3600 \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --json
```

Result:

```text
output:
  tmp/ct07_nox7_triple_cumulative_x0_x2_x3_seed20260665
status:
  manually stopped after more than 30 minutes
files:
  command.json only, plus empty stdout.jsonl
manifest:
  not appended
factor/plaintext:
  not recovered
```

Interpretation: a third 4-bit cumulative drop is too expensive as a routine
strengthening step.  Because no completed hard proof was produced, it must not
be counted as coverage or a hard clause.  Keep three-window drops as rare
targeted proof experiments only, and prefer the current two-window cumulative
line for routine strengthening.

Direct-only no-x7 continuation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_nox7_cumulative_cycle.py \
  --output-dir tmp/ct07_nox7_direct_cycle_seed20260665_iter1 \
  --seed-base 20260665 \
  --iterations 1 \
  --direct-max-total 256 \
  --frontier-top 320 \
  --candidate-pool 32768 \
  --top-pairs 128 \
  --samples-per-pair 2 \
  --x2-cumulative-top 0 \
  --x3-cumulative-top 0 \
  --workers 8 \
  --direct-command-timeout-seconds 2400 \
  --direct-qgap-timeout-seconds 1200 \
  --json
```

Result:

```text
output:
  tmp/ct07_nox7_direct_cycle_seed20260665_iter1
elapsed:
  354.34s
direct:
  256 / 256 SAT
  256 / 256 q-gap hard no_roots
factor/plaintext:
  not recovered
```

Current focused manifest after the direct continuation:

```text
tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
  155 JSONLs
  14772 cube records
  11362 unique no-x7 projection keys seen
  7253 variant projection key instances
  96 variant records
  216 variant clauses
  factors observed in manifest cube rows: 0
```

## 2026-06-09 ranked q-gap and no-x7 continuation

Completed the outstanding `after14066` ranked q-gap top2048 run and direct
checked the second half:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after14066_limit10500_top2048.json
  loaded clauses: 10500
  ranked_records: 4095
  sat_records: 4095
  status_counts: {"sat": 4095, "unknown": 1}
  q_gap_bits in top: 407 -> 512, 408 -> 1536

tmp/ct07_ranked_qgap_direct_after14066_limit10500_rank1025_2048_w8_sageonly.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 596.22s
  factor/plaintext: not recovered
```

A later `top4095` ranker with the default 250ms solver timeout produced no
usable candidates:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after14066_limit10500_top4095.json
  evaluated_records: 4096
  status_counts: {"unknown": 4096}
  top rows: 0
```

This is not coverage.  Large top-k rankers at this ledger size need the
explicit 1000ms solver timeout or a compacted ledger.

A partial x2-range ranker also failed for the same reason:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after14066_limit10500_x2_9d_ff_top1024.json
  x2_values: 0x9d..0xff
  evaluated_records: 1584
  status_counts: {"unknown": 1584}
  top rows: 0
```

This is not coverage and should not be direct-checked.

Added `build_compacted_ranker_ledger.py` to create a row-level compacted JSONL
that the existing learned-clause loader can consume directly.  The first
compaction pass used the current ranked q-gap ledger set plus the latest
`after14066` direct ledgers:

```text
tmp/ct07_compacted_ranker_after16090_max12000_pair2.jsonl
  input files: 322
  candidate hard rows: 16470
  selected rows: 8186
  selected x2/x6 pairs: 4094
  max per pair: 2
```

This preserves almost the entire seen x2/x6 pair frontier while thinning
repeated direct clauses.  Use it as a ranker input for future compacted-order
experiments; it does not by itself add new mathematical coverage.

The same x2/x6 pair frontier is now close to exhausted, so a no-x7 direct-only
branch-shape cycle was run.  The first attempt without
`--skip-sampler-learned-clauses` stalled in the sampler while reloading the
large learned ledger and was terminated before any q-gap rows were produced.
The rerun with sampler learned-clause reload skipped completed:

```text
tmp/ct07_nox7_direct_cycle_seed20260666_iter1_skip_sampler
  elapsed: 122.42s
  direct q-gap rows: 256
  status_counts: {"no_roots": 256}
  factor/plaintext: not recovered
```

Then a small cumulative minimization probe reused that direct JSONL:

```text
tmp/ct07_nox7_cumulative_probe_seed20260666_from_skip_direct_x2x3_top1
  elapsed: 308.75s
  cumulative_x2low4: no_factor, one 138-literal hard no-root variant
  cumulative_x3low4: no_factor, one 138-literal hard no-root variant
  factor/plaintext: not recovered
```

One additional no-x7 skip-sampler direct/cumulative cycle:

```text
tmp/ct07_nox7_cycle_seed20260667_direct_x2x3_top1_skip_sampler
  elapsed: 432.22s
  direct q-gap rows: 256
  direct status_counts: {"no_roots": 256}
  cumulative_x2low4: no_factor, one 138-literal hard no-root variant
  cumulative_x3low4: no_factor, one 138-literal hard no-root variant
  factor/plaintext: not recovered
```

Two larger no-x7 skip-sampler cycles with 512 direct probes and top2
cumulative x2/x3 minimization also completed:

```text
tmp/ct07_nox7_cycle_seed20260668_direct512_x2x3_top2_skip_sampler
  elapsed: 878.08s
  direct q-gap rows: 512
  direct status_counts: {"no_roots": 512}
  cumulative_x2low4: no_factor, two 138-literal hard no-root variants
  cumulative_x3low4: no_factor, two 138-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_nox7_cycle_seed20260669_direct512_x2x3_top2_skip_sampler
  elapsed: 1062.51s
  direct q-gap rows: 512
  direct status_counts: {"no_roots": 512}
  direct q_gap_bits: 324 for all cube rows
  direct learned clause literals: 146 for all cube rows
  cumulative_x2low4: no_factor, two 138-literal hard no-root variants
    elapsed: 425.14s
  cumulative_x3low4: no_factor, two 138-literal hard no-root variants
    elapsed: 264.65s
  factor/plaintext: not recovered
```

Interpretation: same-pair ranked q-gap should stop being the default broad
search line.  The no-x7 line has now added 1536 recent direct hard no-root
cube rows plus 10 recent cumulative 138-literal hard variants without a factor.
Continue with no-x7/direct-plus-small-cumulative cycles using
`--skip-sampler-learned-clauses`, but watch yield: this is still hard pruning
evidence, not a complete coverage proof.  Only run a compacted-ledger ranker
variant if it changes the x2/x6 assumption ranges or branch shape.  Do not
count the terminated non-skip sampler run as coverage.

A 12-hour-bounded no-x7 continuation was started, but the top-level runner
terminated early during iteration 2 x3 cumulative post-processing.  The valid
completed child ledgers were recovered and appended manually:

```text
tmp/ct07_nox7_cycle_12h_seed20260670_direct512_x2x3_top2_skip_sampler
  intended: 36 iterations, 12h max
  actual completed direct rows:
    iteration 1: 512 hard no_roots, q_gap_bits=324, no factor
    iteration 2: 512 hard no_roots, q_gap_bits=324, no factor
  recovered cumulative ledgers:
    iteration 1 x2low4: two 138-literal hard no-root variants
    iteration 1 x3low4: two 138-literal hard no-root variants
    iteration 2 x2low4: two 138-literal hard no-root variants
    iteration 2 x3low4: two 138-literal hard no-root variants
  factor/plaintext: not recovered
  note: top-level cycle_summary.json is stale and must not be treated as a
        completed 12h run summary.
```

The active manifest was updated to include the two recovered iteration 2
x3low4 minimization JSONLs.  Recovery validation checked that both JSONLs have
`q_gap_coppersmith.status=no_roots`,
`no_root_hard_clause_eligible=true`, `q_gap_bits=324`, and no factors.

A separate x7-focused line was also run against a small focus manifest.  This
shape fixes `150:4,265:84,362:58,920:4`, so it spends four more hidden bits
than no-x7 but gives a much smaller q-gap:

```text
tmp/ct07_x7_direct_probe_seed20260680_max64
  direct q-gap rows: 64
  status_counts: {"no_roots": 64}
  q_gap_bits: 230..236
  direct learned clause literals: 150
  factor/plaintext: not recovered

tmp/ct07_x7_edge_min_seed20260680_top1
  source: first x7 direct probe
  cumulative drop windows: 150:4, then 920:4
  completions checked: 16 + 256
  result: one 142-literal hard no-root variant
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260682_max512
  elapsed: 435.20s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 65
    231: 194
    232: 133
    233: 53
    234: 31
    236: 36
  direct learned clause literals: 150
  factor/plaintext: not recovered
```

Interpretation: x7 focus is now a high-value branch killer.  It should be
paired with representative independent nibble-drop minimization rather than
treated as a pure hit-first direct batch.  Cumulative `x0+x7` is not the
default after the latest timeout-only attempts.  The focus manifest is
`tmp/ct07_x7_focus_manifest_20260609.txt`.

Follow-up x7 focus independent minimization:

```text
tmp/ct07_x7_independent_min_seed20260682_top4
  source: tmp/ct07_x7_direct_focus_seed20260682_max512/iteration_0001_qgap.jsonl
  records_completed: 4
  elapsed: 245.95s
  status: no_factor
  per representative:
    q_gap_bits: 230, 231, 232, or 236
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260682_next4
  source: same direct batch, start-index 5, top 4
  records_completed: 4
  elapsed: 260.13s
  status: no_factor
  q_gap_bits: 231, 232, or 234
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered
```

An attempted cumulative `x0+x7` top4 run at
`tmp/ct07_x7_edge_min_seed20260682_top4` stopped before producing a cube JSONL;
do not count that directory as coverage.  A top1 retry at
`tmp/ct07_x7_edge_min_seed20260682_top1_retry` timed out after 180 seconds with
an empty `minimization.jsonl`; do not count it either.

The x7 focus manifest now contains 11 JSONL ledgers: the 64-row direct probe,
one cumulative top1 minimization, the 512-row focus direct batch, and eight
independent minimization ledgers from `top4 + next4`.

Additional x7 focus continuation:

```text
tmp/ct07_x7_direct_focus_seed20260684_max512
  elapsed: 619.88s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 63
    231: 191
    232: 116
    233: 69
    234: 27
    236: 46
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260684_top4
  source: seed20260684 direct batch
  records_completed: 4
  elapsed: 160.93s
  status: no_factor
  q_gap_bits: 230, 231, or 236
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260683_max512
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 61
    231: 190
    232: 119
    233: 70
    234: 37
    236: 35
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260683_top4
  source: seed20260683 direct batch
  records_completed: 4
  elapsed: 157.30s
  status: no_factor
  q_gap_bits: 234 or 236
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260685_max512
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 64
    231: 183
    232: 134
    233: 68
    234: 25
    236: 38
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260685_top4
  source: seed20260685 direct batch
  records_completed: 4
  elapsed: 86.21s
  status: no_factor
  q_gap_bits: 232 for all four representatives
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260686_max512
  elapsed: 458.15s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 66
    231: 196
    232: 115
    233: 63
    234: 38
    236: 34
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260686_top4
  source: seed20260686 direct batch
  records_completed: 4
  elapsed: 142.27s
  status: no_factor
  q_gap_bits: 231 or 232
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260687_max512
  elapsed: 510.85s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 79
    231: 171
    232: 126
    233: 71
    234: 31
    236: 34
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260687_top4
  source: seed20260687 direct batch
  records_completed: 4
  elapsed: 137.12s
  status: no_factor
  q_gap_bits: 230 or 233
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260688_max512
  elapsed: 477.96s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 60
    231: 203
    232: 124
    233: 65
    234: 37
    236: 23
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260688_top4
  source: seed20260688 direct batch
  records_completed: 4
  elapsed: 160.91s
  status: no_factor
  q_gap_bits: 230, 231, or 233
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260689_max512
  stopped before producing samples or q-gap JSONL
  manifest append: none
  coverage: none

tmp/ct07_x7_direct_focus_seed20260689_skip_sampler_max512
  elapsed: 334.11s
  note: retried with --skip-sampler-learned-clauses after the non-skip runner
        stopped before sample output
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 63
    231: 220
    232: 104
    233: 67
    234: 36
    236: 22
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260689_skip_sampler_top4
  source: seed20260689 skip-sampler direct batch
  records_completed: 4
  elapsed: 133.74s
  status: no_factor
  q_gap_bits: 231 or 232
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260690_skip_sampler_max512
  elapsed: 519.27s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 68
    231: 190
    232: 130
    233: 51
    234: 33
    236: 40
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260690_skip_sampler_top4
  source: seed20260690 skip-sampler direct batch
  records_completed: 4
  elapsed: 150.52s
  status: no_factor
  q_gap_bits: 231 or 232
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered

tmp/ct07_x7_direct_focus_seed20260691_skip_sampler_max512
  elapsed: 311.86s
  direct q-gap rows: 512
  status_counts: {"no_roots": 512}
  q_gap_bits distribution:
    230: 67
    231: 194
    232: 123
    233: 62
    234: 34
    236: 32
  factor/plaintext: not recovered

tmp/ct07_x7_independent_min_seed20260691_skip_sampler_top4
  source: seed20260691 skip-sampler direct batch
  records_completed: 4
  elapsed: 131.74s
  status: no_factor
  q_gap_bits: 231, 232, or 233
  per representative:
    independent drops proved: 150:4, 920:4, 265:4, 362:4
    learned variants: four 146-literal hard no-root variants
  factor/plaintext: not recovered
```

The x7 focus manifest now contains 56 JSONL ledgers and 5229 cube rows, all
with q-gap `no_roots` and no factors.  The repeated direct batches and 44
total independent-minimized representatives all agree on the
same useful pattern: q-gap 230..236, hard no-root, and all four nibble drops
sound for representative branches.  The latest direct run also showed that
`--skip-sampler-learned-clauses` is preferable once the x7 focus manifest has
grown to this size.  Still no factor/plaintext.

A concurrently running full-x1/full-x5 projection batch also completed:

```text
tmp/ct07_fullx1x5_projection_runner_seed20260691
  manifest: tmp/ct07_fullx1x5_resume_all_jsonl.txt
  elapsed: 220.03s
  direct q-gap rows: 256
  status_counts: {"no_roots": 256}
  q_gap_bits distribution:
    407: 32
    408: 114
    409: 55
    410: 23
    411: 13
    412: 7
    413: 5
    414: 4
    415: 3
  manifest ledgers after append: 85
  factor/plaintext: not recovered
```

## 2026-06-08 ranked q-gap direct continuation

The full-x1/full-x5 drop loop was hardened before continuing:

- child runs now use a process group and optional per-iteration timeout;
- incomplete iterations without a cube row are not appended to active ledgers
  or manifests;
- `--load-learned-limit` is forwarded to `semi_programmatic_sat.py`;
- summary output records valid completed iterations separately from attempted
  iterations.

Verification:

```bash
python3 -m py_compile cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py

PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Result: compile succeeded and `13/13` tests passed.

The guarded rerun correctly rejected an incomplete killed iteration:

```text
tmp/ct07_hybrid_drop_guarded_1h_eps004
  attempted iterations: 1
  valid iterations: 0
  stopped_reason: incomplete_iteration
  manifest append: none
```

Limited learned-clause smoke attempts at 400, 360, and 320 loaded clauses did
not produce a cube before being stopped.  They should not be counted as proof
coverage.

The productive continuation was the ranked direct q-gap line.  It uses learned
ledger limits to obtain fresh SAT-ranked hard q-gap candidates, then runs
`run_ranked_q_gap_direct.py` directly on the resulting top candidates.

Direct sweep after the `after4956` ranker:

```text
tmp/ct07_ranked_qgap_direct_after4956_all_model_top4090.json
  records_completed: 4090 / 4090
  status_counts: {"no_roots": 4090}
  elapsed: 1937.67s
  factor/plaintext: not recovered
```

Full-ledger ranker after those 4090 clauses loaded 9579 learned clauses and
1,319,382 literals, but all 4096 evaluated records were `unknown` at the
250ms SAT check budget.  That is an operational limit: loading every current
ledger makes the ranking layer too heavy.

Limited-ledger ranker at 6500 learned clauses:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after9046_limit6500_top1024.json
  ranked_records: 4095
  sat_records: 4095
  q_gap_bits in top: 407 -> 385, 408 -> 639

tmp/ct07_ranked_qgap_direct_after9046_limit6500_top1024.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 409.55s
  factor/plaintext: not recovered
```

Ordered limited-ledger ranker at 7500 learned clauses:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after10070_limit7500_top1024.json
  ranked_records: 4096
  sat_records: 4096
  q_gap_bits in top: 407 -> 512, 408 -> 512

tmp/ct07_ranked_qgap_direct_after10070_limit7500_top1024.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 532.64s
  factor/plaintext: not recovered
```

Interpretation: q-gap direct remains fast and hard-sound on these 407/408-bit
gaps, but the SAT ranker must be fed a bounded, ordered ledger prefix.  Do not
switch back to full-ledger ranking unless the learned clauses are compacted or
selected by usefulness first.

Further ordered limited-ledger continuations:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after11094_limit8500_top1024.json
  loaded clauses: 8500
  ranked_records: 4094
  sat_records: 4094
  status_counts: {"sat": 4094, "unknown": 2}
  q_gap_bits in top: 407 -> 512, 408 -> 512

tmp/ct07_ranked_qgap_direct_after11094_limit8500_top1024_sageonly.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 497.51s
  factor/plaintext: not recovered

tmp/ct07_ranked_qgap_pairs_include_seen_after12118_limit9500_top1024.json
  loaded clauses: 9500
  ranked_records: 4096
  sat_records: 4096
  status_counts: {"sat": 4096}
  q_gap_bits in top: 407 -> 462, 408 -> 562

tmp/ct07_ranked_qgap_direct_after12118_limit9500_top1024_sageonly.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 1040.01s
  factor/plaintext: not recovered
```

An attempted 10000/10500 raise on the `after13142` ordered list produced no
ranker JSON and empty stdout logs, but a parallel ordered list named
`after13042` did complete at limit 10000:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after13042_limit10000_top1024.json
  loaded clauses: 10000
  ranked_records: 4096
  sat_records: 4096
  status_counts: {"sat": 4096}
  q_gap_bits in top: 407 -> 512, 408 -> 512

tmp/ct07_ranked_qgap_direct_after13042_limit10000_top1024_sageonly.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 570.80s
  factor/plaintext: not recovered
```

Treat 10000 as reachable only for selected ledger orders, not as a generally
safe ceiling.

The next selected order, `after14066`, did complete at limit 10500:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after14066_limit10500_top1024.json
  loaded clauses: 10500
  ranked_records: 4084
  sat_records: 4084
  status_counts: {"sat": 4084, "unknown": 12}
  q_gap_bits in top: 407 -> 510, 408 -> 514

tmp/ct07_ranked_qgap_direct_after14066_limit10500_top1024_retry_w8_sageonly.json
  records_completed: 1024 / 1024
  status_counts: {"no_roots": 1024}
  elapsed: 672.52s
  factor/plaintext: not recovered
```

Duplicate accounting across the major ranked direct ledgers:

```text
after4956 bulk top4090:                 4090 unique rows
after9046 limit6500 top1024:            1024 rows, 1 overlap with prior
after10070 limit7500 top1024:           1024 rows, 0 overlap with prior
after11094 limit8500 top1024:           1024 rows, 16 overlaps with prior
after12118 limit9500 top1024:           1024 rows, 0 overlap with prior
after13042 limit10000 top1024:          1024 rows, 1 overlap with prior
after14066 limit10500 top1024:          1024 rows, 9 overlaps with prior
exclude-seen limit9500 top2:            2 rows, 0 overlap with prior
combined unique direct hard no-roots:   10209
```

An exclude-seen ranker at the stable 9500 limit found only two unseen pairs:

```text
tmp/ct07_ranked_qgap_pairs_exclude_seen_after13142_limit9500_top1024.json
  top rows: 2
  skipped_seen_pair: 4094
  q_gap_bits: 409, 412

tmp/ct07_ranked_qgap_direct_exclude_seen_after13142_limit9500_top2_sageonly.json
  records_completed: 2 / 2
  status_counts: {"no_roots": 2}
  factor/plaintext: not recovered
```

Interpretation: within the current ordered 9500-clause view, the ranker has
almost exhausted the unseen pair frontier.  The next step should not be another
simple ranked-direct batch with the same clause order.  Add clause compaction
or move to a different branch shape.

## 2026-06-14 low600 continuation after batch12

The active state was reconstructed from the latest 2026-06-13 artifacts rather
than the older tail of this log.  The latest useful low600 resume artifact was:

```text
tmp/ct07_low600_compacted_subsumed_after_batch12_20260613.jsonl
  selected_records: 339
  selected_pairs: 339
  status_counts: {"low_coppersmith_no_root": 339}
  factor/plaintext: not recovered
```

The incomplete probe at
`tmp/ct07_low600_x0_x1low4_cumulative_timeout120_after_batch12_probe_w2_20260613`
contained only a `loaded_learned_clauses` row and no cube/summary, so it is not
counted as proof coverage.

While retrying the same cumulative `x0+x1low4` line, the low-Coppersmith worker
processes continued past the intended per-oracle timeout.  The runner process
was stopped and `semi_programmatic_sat.py` was hardened so parallel
low-Coppersmith minimization now runs in worker waves, terminates overdue wave
processes, records timeout completions, and stops a drop-window as soon as a
non-hard completion makes the drop not sound.

Verification:

```bash
python3 -m py_compile cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py
PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Result: compile succeeded and `15/15` tests passed.

Timeout guard smoke:

```text
tmp/ct07_low600_timeout_guard_smoke_20260614
  elapsed: 29.93s
  status: no_factor
  first cube low_coppersmith_status: timeout
  learned_clause: sample_block_only
  leftover semi_programmatic processes: none
```

The real batch12 cumulative `x0+x1low4` retry still did not produce a cube row
within the bounded run:

```text
tmp/ct07_low600_x0_x1low4_cumulative_timeout120_after_batch12_retry2_w4_20260614
  max_seconds: 600
  status: no_factor
  returncode: -15
  timed_out: true
  cube row: none
  factor/plaintext: not recovered
```

Do not count this retry as a hard clause.  It confirms that the cumulative
second-drop path after batch12 is still operationally too expensive for routine
coverage.

The productive continuation was the cheaper x0-only low600 path:

```text
tmp/ct07_low600_x0only_after_batch12_timeout120_batch13_w2_iter4_20260614
  iterations_completed: 4 / 4
  elapsed: 445.82s
  records:
    265:84 = 4272, 4256, 5280, 5296
  every row:
    low_coppersmith_status: no_roots
    learned_clause: low_coppersmith_no_root
    learned_clause_literal_count: 142
    dropped bits: 150..153
    minimization: 16/16 hard no_roots for x0
  factor/plaintext: not recovered
```

The next compacted resume ledger was built from batch12 plus those four new
rows:

```text
tmp/ct07_low600_compacted_subsumed_after_batch13_20260614.jsonl
  selected_records: 343
  selected_pairs: 343
  status_counts: {"low_coppersmith_no_root": 343}
  source_counts:
    batch12 compacted ledger: 339
    batch13 x0-only rows: 4
```

Next low600 step: continue x0-only batches from
`tmp/ct07_low600_compacted_subsumed_after_batch13_20260614.jsonl` when cheap
supporting coverage is useful.  Only retry `x0+x1low4` if there is a narrower
target or a cheaper prefilter; broad cumulative retries are not producing cube
rows under the current bounds.

## 2026-06-14 low600 batch14 x0-only continuation

Continued the cheap low600 p-Coppersmith line from the batch13 compacted resume
ledger:

```text
input resume:
  tmp/ct07_low600_compacted_subsumed_after_batch13_20260614.jsonl
  selected_records: 343
  status_counts: {"low_coppersmith_no_root": 343}

run:
  tmp/ct07_low600_x0only_after_batch13_timeout120_batch14_w2_iter4_20260614
  iterations_completed: 4 / 4
  elapsed: 461.32s
  workers: 2
  oracle timeout: 120s
```

All four new rows were sound x0-only low600 hard clauses:

```text
265:84 values: 560, 528, 592, 624
every row:
  low_coppersmith_status: no_roots
  learned_clause: low_coppersmith_no_root
  learned_clause_literal_count: 142
  dropped bits: 150..153
  minimization: 16/16 hard no_roots for x0
  factors: none
```

The next compacted resume ledger was built from batch13 plus these four rows:

```text
tmp/ct07_low600_compacted_subsumed_after_batch14_20260614.jsonl
  selected_records: 347
  selected_pairs: 347
  status_counts: {"low_coppersmith_no_root": 347}
  source_counts:
    batch13 compacted ledger: 343
    batch14 x0-only rows: 4
```

Factor/plaintext is still not recovered.  Continue x0-only from
`tmp/ct07_low600_compacted_subsumed_after_batch14_20260614.jsonl` if adding
more low600 support clauses is the next available work.

## 2026-06-14 low600 batch15 x0-only continuation

Continued the same low600 x0-only path from the batch14 compacted resume
ledger:

```text
input resume:
  tmp/ct07_low600_compacted_subsumed_after_batch14_20260614.jsonl
  selected_records: 347
  status_counts: {"low_coppersmith_no_root": 347}

run:
  tmp/ct07_low600_x0only_after_batch14_timeout120_batch15_w2_iter4_20260614
  iterations_completed: 4 / 4
  elapsed: 370.83s
  workers: 2
  oracle timeout: 120s
```

All four new rows were again sound x0-only low600 hard clauses:

```text
265:84 values: 688, 752, 544, 672
every row:
  low_coppersmith_status: no_roots
  learned_clause: low_coppersmith_no_root
  learned_clause_literal_count: 142
  dropped bits: 150..153
  minimization: 16/16 hard no_roots for x0
  factors: none
```

The next compacted resume ledger:

```text
tmp/ct07_low600_compacted_subsumed_after_batch15_20260614.jsonl
  selected_records: 351
  selected_pairs: 351
  status_counts: {"low_coppersmith_no_root": 351}
  source_counts:
    batch14 compacted ledger: 347
    batch15 x0-only rows: 4
```

Factor/plaintext is still not recovered.  Continue from
`tmp/ct07_low600_compacted_subsumed_after_batch15_20260614.jsonl` for the next
low600 x0-only batch.

## 2026-06-14 low600 batch16 x0-only continuation

Continued from the batch15 compacted resume ledger:

```text
input resume:
  tmp/ct07_low600_compacted_subsumed_after_batch15_20260614.jsonl
  selected_records: 351
  status_counts: {"low_coppersmith_no_root": 351}

run:
  tmp/ct07_low600_x0only_after_batch15_timeout120_batch16_w2_iter4_20260614
  iterations_completed: 4 / 4
  elapsed: 410.02s
  workers: 2
  oracle timeout: 120s
```

All four new rows were sound x0-only low600 hard clauses:

```text
265:84 values: 512, 576, 608, 736
every row:
  low_coppersmith_status: no_roots
  learned_clause: low_coppersmith_no_root
  learned_clause_literal_count: 142
  dropped bits: 150..153
  minimization: 16/16 hard no_roots for x0
  factors: none
```

The next compacted resume ledger:

```text
tmp/ct07_low600_compacted_subsumed_after_batch16_20260614.jsonl
  selected_records: 355
  selected_pairs: 355
  status_counts: {"low_coppersmith_no_root": 355}
  source_counts:
    batch15 compacted ledger: 351
    batch16 x0-only rows: 4
```

Factor/plaintext is still not recovered.  Continue from
`tmp/ct07_low600_compacted_subsumed_after_batch16_20260614.jsonl` for the next
low600 x0-only batch.

## 2026-06-14 x7 focus seed-base 20260692 direct and top4 minimization

Resumed the higher-priority x7 focus line from
`tmp/ct07_x7_focus_manifest_20260609.txt`:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260692_skip_sampler_max512
  internal seed: 20260693
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 334.55s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 69
    231: 177
    232: 139
    233: 60
    234: 40
    236: 27
  factors: none
```

Then ran representative independent nibble-drop minimization on the top four
records:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260692_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 142.21s
  factors: none

per representative:
  q_gap_bits: 236, 234, 233, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 62 JSONL ledgers and 5777 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
this line with the next 512-row x7 focus direct batch, then top4 representative
independent minimization, while the q-gap range remains 230-236.

## 2026-06-14 x7 focus seed-base 20260693 direct and top4 minimization

Continued the x7 focus line from the 62-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260693_skip_sampler_max512
  internal seed: 20260694
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 353.91s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 66
    231: 205
    232: 121
    233: 57
    234: 34
    236: 29
  factors: none
```

Representative independent nibble-drop minimization also completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260693_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 284.65s
  factors: none

per representative:
  q_gap_bits: 230, 231, 230, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 67 JSONL ledgers and 6293 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260694` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260694 direct and top4 minimization

Continued the x7 focus line from the 67-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260694_skip_sampler_max512
  internal seed: 20260695
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 407.23s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 64
    231: 195
    232: 135
    233: 60
    234: 35
    236: 23
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260694_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 175.34s
  factors: none

per representative:
  q_gap_bits: 231, 232, 232, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 72 JSONL ledgers and 6809 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260695` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260695 direct and top4 minimization

Continued the x7 focus line from the 72-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260695_skip_sampler_max512
  internal seed: 20260696
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 367.14s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 79
    231: 185
    232: 121
    233: 61
    234: 30
    236: 36
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260695_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 253.47s
  factors: none

per representative:
  q_gap_bits: 231, 234, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 77 JSONL ledgers and 7325 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260696` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260696 direct and top4 minimization

Continued the x7 focus line from the 77-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260696_skip_sampler_max512
  internal seed: 20260697
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 430.68s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 72
    231: 185
    232: 125
    233: 54
    234: 34
    236: 42
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260696_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 196.29s
  factors: none

per representative:
  q_gap_bits: 231, 232, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 82 JSONL ledgers and 7841 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260697` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260697 direct and top4 minimization

Continued the x7 focus line from the 82-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260697_skip_sampler_max512
  internal seed: 20260698
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 478.76s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 77
    231: 196
    232: 123
    233: 57
    234: 33
    236: 26
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260697_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 202.52s
  factors: none

per representative:
  q_gap_bits: 232, 231, 233, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 87 JSONL ledgers and 8357 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260698` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260698 direct and top4 minimization

Continued the x7 focus line from the 87-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260698_skip_sampler_max512
  internal seed: 20260699
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 398.95s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 184
    232: 125
    233: 71
    234: 35
    236: 29
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260698_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 183.02s
  factors: none

per representative:
  q_gap_bits: 231, 230, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 92 JSONL ledgers and 8873 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260699` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260699 direct and top4 minimization

Continued the x7 focus line from the 92-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260699_skip_sampler_max512
  internal seed: 20260700
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 413.13s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 193
    232: 145
    233: 54
    234: 28
    236: 24
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260699_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 197.96s
  factors: none

per representative:
  q_gap_bits: 234, 230, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 97 JSONL ledgers and 9389 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260700` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260700 direct and top4 minimization

Continued the x7 focus line from the 97-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260700_skip_sampler_max512
  internal seed: 20260701
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 449.03s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 64
    231: 205
    232: 119
    233: 62
    234: 28
    236: 34
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260700_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 302.54s
  factors: none

per representative:
  q_gap_bits: 231, 234, 231, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 102 JSONL ledgers and 9905 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260701` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260701 direct and top4 minimization

Continued the x7 focus line from the 102-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260701_skip_sampler_max512
  internal seed: 20260702
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 467.15s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 60
    231: 202
    232: 130
    233: 62
    234: 27
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260701_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 205.21s
  factors: none

per representative:
  q_gap_bits: 233, 231, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 107 JSONL ledgers and 10421 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260702` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260702 direct and top4 minimization

Continued the x7 focus line from the 107-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260702_skip_sampler_max512
  internal seed: 20260703
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 610.86s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 64
    231: 177
    232: 141
    233: 56
    234: 37
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260702_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 457.58s
  factors: none

per representative:
  q_gap_bits: 231, 233, 233, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 112 JSONL ledgers and 10937 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260703` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260703 direct and top4 minimization

Continued the x7 focus line from the 112-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260703_skip_sampler_max512
  internal seed: 20260704
  frontier records: 1280
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 545.75s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 61
    231: 179
    232: 138
    233: 69
    234: 34
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260703_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 240.56s
  factors: none

per representative:
  q_gap_bits: 232, 231, 232, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 117 JSONL ledgers and 11453 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260704` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260704 direct and top4 minimization

Continued the x7 focus line from the 117-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260704_skip_sampler_max512
  internal seed: 20260705
  frontier records: 1280
  frontier unique seen projection keys: 17108
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 434.59s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 67
    231: 184
    232: 139
    233: 59
    234: 26
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260704_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 228.55s
  factors: none

per representative:
  q_gap_bits: 230, 231, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 122 JSONL ledgers and 11969 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260705` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260705 direct and top4 minimization

Continued the x7 focus line from the 122-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260705_skip_sampler_max512
  internal seed: 20260706
  frontier records: 1280
  frontier unique seen projection keys: 17852
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 330.06s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 72
    231: 186
    232: 123
    233: 71
    234: 30
    236: 30
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260705_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 204.19s
  factors: none

per representative:
  q_gap_bits: 231, 232, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 127 JSONL ledgers and 12485 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260706` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260706 direct and top4 minimization

Continued the x7 focus line from the 127-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260706_skip_sampler_max512
  internal seed: 20260707
  frontier records: 1280
  frontier unique seen projection keys: 18599
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 301.74s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 69
    231: 191
    232: 131
    233: 54
    234: 33
    236: 34
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260706_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 162.47s
  factors: none

per representative:
  q_gap_bits: 232, 232, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 132 JSONL ledgers and 13001 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260707` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260707 direct and top4 minimization

Continued the x7 focus line from the 132-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260707_skip_sampler_max512
  internal seed: 20260708
  frontier records: 1280
  frontier unique seen projection keys: 19350
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 291.66s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 62
    231: 198
    232: 133
    233: 60
    234: 36
    236: 23
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260707_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 163.90s
  factors: none

per representative:
  q_gap_bits: 232, 236, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 137 JSONL ledgers and 13517 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260708` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260708 direct and top4 minimization

Continued the x7 focus line from the 137-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260708_skip_sampler_max512
  internal seed: 20260709
  frontier records: 1280
  frontier unique seen projection keys: 20097
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 298.94s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 64
    231: 207
    232: 134
    233: 53
    234: 26
    236: 28
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260708_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 178.52s
  factors: none

per representative:
  q_gap_bits: 233, 236, 231, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 142 JSONL ledgers and 14033 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260709` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260709 direct and top4 minimization

Continued the x7 focus line from the 142-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260709_skip_sampler_max512
  internal seed: 20260710
  frontier records: 1280
  frontier unique seen projection keys: 20845
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 256.48s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 180
    232: 134
    233: 61
    234: 33
    236: 36
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260709_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 180.54s
  factors: none

per representative:
  q_gap_bits: 232, 233, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 147 JSONL ledgers and 14549 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260710` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260710 direct and top4 minimization

Continued the x7 focus line from the 147-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260710_skip_sampler_max512
  internal seed: 20260711
  frontier records: 1280
  frontier unique seen projection keys: 21593
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 288.20s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 56
    231: 201
    232: 130
    233: 62
    234: 37
    236: 26
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260710_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 184.62s
  factors: none

per representative:
  q_gap_bits: 232, 231, 230, 234
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 152 JSONL ledgers and 15065 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260711` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260711 direct and top4 minimization

Continued the x7 focus line from the 152-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260711_skip_sampler_max512
  internal seed: 20260712
  frontier records: 1280
  frontier unique seen projection keys: 22337
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 269.07s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 72
    231: 188
    232: 139
    233: 52
    234: 31
    236: 30
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260711_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 159.76s
  factors: none

per representative:
  q_gap_bits: 232, 232, 234, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 157 JSONL ledgers and 15581 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260712` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260712 direct and top4 minimization

Continued the x7 focus line from the 157-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260712_skip_sampler_max512
  internal seed: 20260713
  frontier records: 1280
  frontier unique seen projection keys: 23087
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 268.09s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 66
    231: 194
    232: 125
    233: 62
    234: 40
    236: 25
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260712_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 149.74s
  factors: none

per representative:
  q_gap_bits: 233, 230, 232, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 162 JSONL ledgers and 16097 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260713` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260713 direct and top4 minimization

Continued the x7 focus line from the 162-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260713_skip_sampler_max512
  internal seed: 20260714
  frontier records: 1280
  frontier unique seen projection keys: 23839
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 282.36s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 184
    232: 134
    233: 57
    234: 32
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260713_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 140.13s
  factors: none

per representative:
  q_gap_bits: 232, 231, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 167 JSONL ledgers and 16613 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260714` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260714 direct and top4 minimization

Continued the x7 focus line from the 167-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260714_skip_sampler_max512
  internal seed: 20260715
  frontier records: 1280
  frontier unique seen projection keys: 24585
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 343.50s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 65
    231: 186
    232: 132
    233: 55
    234: 33
    236: 41
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260714_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 232.12s
  factors: none

per representative:
  q_gap_bits: 231, 231, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 172 JSONL ledgers and 17129 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260715` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260715 direct and top4 minimization

Continued the x7 focus line from the 172-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260715_skip_sampler_max512
  internal seed: 20260716
  frontier records: 1280
  frontier unique seen projection keys: 25337
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 238.84s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 50
    231: 199
    232: 135
    233: 52
    234: 39
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260715_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 156.67s
  factors: none

per representative:
  q_gap_bits: 232, 231, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 177 JSONL ledgers and 17645 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260716` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260716 direct and top4 minimization

Continued the x7 focus line from the 177-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260716_skip_sampler_max512
  internal seed: 20260717
  frontier records: 1280
  frontier unique seen projection keys: 26082
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 361.33s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 50
    231: 198
    232: 142
    233: 63
    234: 32
    236: 27
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260716_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 199.92s
  factors: none

per representative:
  q_gap_bits: 232, 230, 233, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 182 JSONL ledgers and 18161 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260717` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260717 direct and top4 minimization

Continued the x7 focus line from the 182-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260717_skip_sampler_max512
  internal seed: 20260718
  frontier records: 1280
  frontier unique seen projection keys: 26831
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 432.68s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 61
    231: 212
    232: 118
    233: 50
    234: 34
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260717_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 195.74s
  factors: none

per representative:
  q_gap_bits: 231, 232, 231, 233
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 187 JSONL ledgers and 18677 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260718` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-14 x7 focus seed-base 20260718 direct and top4 minimization

Continued the x7 focus line from the 187-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260718_skip_sampler_max512
  internal seed: 20260719
  frontier records: 1280
  frontier unique seen projection keys: 27579
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 353.70s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 45
    231: 215
    232: 112
    233: 62
    234: 37
    236: 41
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260718_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 157.41s
  factors: none

per representative:
  q_gap_bits: 231, 236, 233, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 192 JSONL ledgers and 19193 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260719` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260719 direct and top4 minimization

Continued the x7 focus line from the 192-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260719_skip_sampler_max512
  internal seed: 20260720
  frontier records: 1280
  frontier unique seen projection keys: 28326
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 618.63s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 57
    231: 209
    232: 115
    233: 64
    234: 35
    236: 32
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260719_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 349.18s
  factors: none

per representative:
  q_gap_bits: 231, 236, 232, 234
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 197 JSONL ledgers and 19709 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260720` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260720 direct and top4 minimization

Continued the x7 focus line from the 197-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260720_skip_sampler_max512
  internal seed: 20260721
  frontier records: 1280
  frontier unique seen projection keys: 29073
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 630.69s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 69
    231: 182
    232: 125
    233: 74
    234: 34
    236: 28
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260720_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 368.82s
  factors: none

per representative:
  q_gap_bits: 233, 233, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 202 JSONL ledgers and 20225 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260721` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260721 direct and top4 minimization

Continued the x7 focus line from the 202-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260721_skip_sampler_max512
  internal seed: 20260722
  frontier records: 1280
  frontier unique seen projection keys: 29819
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 382.35s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 65
    231: 201
    232: 116
    233: 64
    234: 28
    236: 38
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260721_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 146.15s
  factors: none

per representative:
  q_gap_bits: 236, 231, 233, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 207 JSONL ledgers and 20741 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260722` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260722 direct and top4 minimization

Continued the x7 focus line from the 207-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260722_skip_sampler_max512
  internal seed: 20260723
  frontier records: 1280
  frontier unique seen projection keys: 30566
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 379.59s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 63
    231: 197
    232: 135
    233: 56
    234: 29
    236: 32
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260722_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 174.75s
  factors: none

per representative:
  q_gap_bits: 231, 231, 236, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 212 JSONL ledgers and 21257 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260723` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260723 direct and top4 minimization

Continued the x7 focus line from the 212-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260723_skip_sampler_max512
  internal seed: 20260724
  frontier records: 1280
  frontier unique seen projection keys: 31312
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 384.38s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 67
    231: 187
    232: 133
    233: 72
    234: 19
    236: 34
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260723_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 160.62s
  factors: none

per representative:
  q_gap_bits: 232, 231, 231, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 217 JSONL ledgers and 21773 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260724` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260724 direct and top4 minimization

Continued the x7 focus line from the 217-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260724_skip_sampler_max512
  internal seed: 20260725
  frontier records: 1280
  frontier unique seen projection keys: 32056
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 304.63s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 49
    231: 193
    232: 136
    233: 73
    234: 30
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260724_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 167.67s
  factors: none

per representative:
  q_gap_bits: 232, 232, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 222 JSONL ledgers and 22289 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260725` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260725 direct and top4 minimization

Continued the x7 focus line from the 222-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260725_skip_sampler_max512
  internal seed: 20260726
  frontier records: 1280
  frontier unique seen projection keys: 32802
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 303.24s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 62
    231: 190
    232: 135
    233: 62
    234: 29
    236: 34
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260725_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 144.72s
  factors: none

per representative:
  q_gap_bits: 232, 231, 230, 236
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 227 JSONL ledgers and 22805 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260726` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260726 direct and top4 minimization

Continued the x7 focus line from the 227-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260726_skip_sampler_max512
  internal seed: 20260727
  frontier records: 1280
  frontier unique seen projection keys: 33550
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 308.57s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 67
    231: 185
    232: 131
    233: 61
    234: 30
    236: 38
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260726_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 153.87s
  factors: none

per representative:
  q_gap_bits: 236, 231, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 232 JSONL ledgers and 23321 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260727` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260727 direct and top4 minimization

Continued the x7 focus line from the 232-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260727_skip_sampler_max512
  internal seed: 20260728
  frontier records: 1280
  frontier unique seen projection keys: 34295
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 316.77s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 197
    232: 136
    233: 50
    234: 34
    236: 27
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260727_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 133.64s
  factors: none

per representative:
  q_gap_bits: 231, 232, 232, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 237 JSONL ledgers and 23837 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260728` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260728 direct and top4 minimization

Continued the x7 focus line from the 237-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260728_skip_sampler_max512
  internal seed: 20260729
  frontier records: 1280
  frontier unique seen projection keys: 35040
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 293.35s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 56
    231: 210
    232: 122
    233: 60
    234: 35
    236: 29
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260728_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 148.00s
  factors: none

per representative:
  q_gap_bits: 233, 231, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 242 JSONL ledgers and 24353 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260729` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260729 direct and top4 minimization

Continued the x7 focus line from the 242-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260729_skip_sampler_max512
  internal seed: 20260730
  frontier records: 1280
  frontier unique seen projection keys: 35779
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 307.00s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 70
    231: 184
    232: 129
    233: 61
    234: 31
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260729_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 136.70s
  factors: none

per representative:
  q_gap_bits: 231, 231, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 247 JSONL ledgers and 24869 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260730` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260730 direct and top4 minimization

Continued the x7 focus line from the 247-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260730_skip_sampler_max512
  internal seed: 20260731
  frontier records: 1280
  frontier unique seen projection keys: 36524
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 367.27s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 58
    231: 200
    232: 130
    233: 60
    234: 36
    236: 28
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260730_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 149.81s
  factors: none

per representative:
  q_gap_bits: 233, 232, 233, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 252 JSONL ledgers and 25385 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260731` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260731 direct and top4 minimization

Continued the x7 focus line from the 252-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260731_skip_sampler_max512
  internal seed: 20260732
  frontier records: 1280
  frontier unique seen projection keys: 37273
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 368.47s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 55
    231: 191
    232: 130
    233: 70
    234: 28
    236: 38
  factors: none
```

The first minimization attempt failed while writing stderr because the root
filesystem had no free space.  The manifest-referenced direct JSONL ledgers
were preserved, generated direct sidecars were removed, manifest integrity was
rechecked with zero missing ledgers, and the minimization output directory was
rerun cleanly.

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260731_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 147.50s
  factors: none

per representative:
  q_gap_bits: 231, 231, 233, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 257 JSONL ledgers and 25901 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260732` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260732 direct and top4 minimization

Continued the x7 focus line from the 257-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260732_skip_sampler_max512
  internal seed: 20260733
  frontier records: 1280
  frontier unique seen projection keys: 38016
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 301.66s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 72
    231: 212
    232: 117
    233: 57
    234: 33
    236: 21
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260732_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 144.58s
  factors: none

per representative:
  q_gap_bits: 230, 232, 234, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 262 JSONL ledgers and 26417 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260733` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260733 direct and top4 minimization

Continued the x7 focus line from the 262-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260733_skip_sampler_max512
  internal seed: 20260734
  frontier records: 1280
  frontier unique seen projection keys: 38763
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 500.94s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 71
    231: 172
    232: 124
    233: 81
    234: 42
    236: 22
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260733_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 166.79s
  factors: none

per representative:
  q_gap_bits: 234, 231, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 267 JSONL ledgers and 26933 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260734` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260734 direct and top4 minimization

Continued the x7 focus line from the 267-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260734_skip_sampler_max512
  internal seed: 20260735
  frontier records: 1280
  frontier unique seen projection keys: 39509
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 305.76s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 60
    231: 207
    232: 109
    233: 72
    234: 32
    236: 32
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260734_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 136.54s
  factors: none

per representative:
  q_gap_bits: 236, 234, 232, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 272 JSONL ledgers and 27449 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260735` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260735 direct and top4 minimization

Continued the x7 focus line from the 272-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260735_skip_sampler_max512
  internal seed: 20260736
  frontier records: 1280
  frontier unique seen projection keys: 40249
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 355.06s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 73
    231: 191
    232: 120
    233: 63
    234: 34
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260735_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 161.07s
  factors: none

per representative:
  q_gap_bits: 231, 234, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 277 JSONL ledgers and 27965 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260736` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260736 direct and top4 minimization

Continued the x7 focus line from the 277-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260736_skip_sampler_max512
  internal seed: 20260737
  frontier records: 1280
  frontier unique seen projection keys: 40997
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 291.03s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 58
    231: 194
    232: 133
    233: 59
    234: 35
    236: 33
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260736_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 123.97s
  factors: none

per representative:
  q_gap_bits: 232, 231, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 282 JSONL ledgers and 28481 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260737` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260737 direct and top4 minimization

Continued the x7 focus line from the 282-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260737_skip_sampler_max512
  internal seed: 20260738
  frontier records: 1280
  frontier unique seen projection keys: 41743
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 290.30s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 66
    231: 188
    232: 124
    233: 67
    234: 35
    236: 32
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260737_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 281.40s
  factors: none

per representative:
  q_gap_bits: 231, 232, 233, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 287 JSONL ledgers and 28997 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260738` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260738 direct and top4 minimization

Continued the x7 focus line from the 287-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260738_skip_sampler_max512
  internal seed: 20260739
  frontier records: 1280
  frontier unique seen projection keys: 42490
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 286.40s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 52
    231: 188
    232: 139
    233: 63
    234: 29
    236: 41
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260738_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 124.66s
  factors: none

per representative:
  q_gap_bits: 236, 231, 231, 236
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 292 JSONL ledgers and 29513 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260739` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260739 direct and top4 minimization

Continued the x7 focus line from the 292-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260739_skip_sampler_max512
  internal seed: 20260740
  frontier records: 1280
  frontier unique seen projection keys: 43230
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 272.35s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 71
    231: 197
    232: 123
    233: 66
    234: 30
    236: 25
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260739_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 216.90s
  factors: none

per representative:
  q_gap_bits: 232, 232, 233, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 297 JSONL ledgers and 30029 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260740` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260740 direct and top4 minimization

Continued the x7 focus line from the 297-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260740_skip_sampler_max512
  internal seed: 20260741
  frontier records: 1280
  frontier unique seen projection keys: 43975
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 240.81s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 61
    231: 200
    232: 121
    233: 65
    234: 26
    236: 39
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260740_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 131.09s
  factors: none

per representative:
  q_gap_bits: 231, 236, 231, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 302 JSONL ledgers and 30545 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260741` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260741 direct and top4 minimization

Continued the x7 focus line from the 302-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260741_skip_sampler_max512
  internal seed: 20260742
  frontier records: 1280
  frontier unique seen projection keys: 44718
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 346.37s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 59
    231: 186
    232: 129
    233: 76
    234: 33
    236: 29
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260741_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 200.52s
  factors: none

per representative:
  q_gap_bits: 232, 230, 236, 234
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 307 JSONL ledgers and 31061 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260742` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260742 direct and top4 minimization

Continued the x7 focus line from the 307-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260742_skip_sampler_max512
  internal seed: 20260743
  frontier records: 1280
  frontier unique seen projection keys: 45462
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 339.44s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 63
    231: 209
    232: 124
    233: 54
    234: 23
    236: 39
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260742_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 197.17s
  factors: none

per representative:
  q_gap_bits: 231, 231, 233, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 312 JSONL ledgers and 31577 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260743` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260743 direct and top4 minimization

Continued the x7 focus line from the 312-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260743_skip_sampler_max512
  internal seed: 20260744
  frontier records: 1280
  frontier unique seen projection keys: 46206
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 337.31s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 61
    231: 188
    232: 136
    233: 66
    234: 27
    236: 34
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260743_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 179.07s
  factors: none

per representative:
  q_gap_bits: 230, 232, 233, 236
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 317 JSONL ledgers and 32093 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260744` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260744 direct and top4 minimization

Continued the x7 focus line from the 317-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260744_skip_sampler_max512
  internal seed: 20260745
  frontier records: 1280
  frontier unique seen projection keys: 46941
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 362.20s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 62
    231: 176
    232: 140
    233: 57
    234: 51
    236: 26
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260744_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 158.76s
  factors: none

per representative:
  q_gap_bits: 231, 231, 231, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 322 JSONL ledgers and 32609 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260745` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260745 direct and top4 minimization

Continued the x7 focus line from the 322-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260745_skip_sampler_max512
  internal seed: 20260746
  frontier records: 1280
  frontier unique seen projection keys: 47686
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 290.50s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 61
    231: 195
    232: 136
    233: 51
    234: 36
    236: 33
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260745_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 145.94s
  factors: none

per representative:
  q_gap_bits: 230, 232, 230, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 327 JSONL ledgers and 33125 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260746` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260746 direct and top4 minimization

Continued the x7 focus line from the 327-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260746_skip_sampler_max512
  internal seed: 20260747
  frontier records: 1280
  frontier unique seen projection keys: 48429
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 420.62s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 60
    231: 189
    232: 124
    233: 68
    234: 40
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260746_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 136.17s
  factors: none

per representative:
  q_gap_bits: 233, 232, 233, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 332 JSONL ledgers and 33641 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260747` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260747 direct and top4 minimization

Continued the x7 focus line from the 332-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260747_skip_sampler_max512
  internal seed: 20260748
  frontier records: 1280
  frontier unique seen projection keys: 49175
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 301.77s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 77
    231: 179
    232: 132
    233: 62
    234: 30
    236: 32
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260747_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 140.43s
  factors: none

per representative:
  q_gap_bits: 230, 233, 234, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 337 JSONL ledgers and 34157 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260748` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260748 direct and top4 minimization

Continued the x7 focus line from the 337-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260748_skip_sampler_max512
  internal seed: 20260749
  frontier records: 1280
  frontier unique seen projection keys: 49919
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 363.09s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 70
    231: 194
    232: 122
    233: 57
    234: 34
    236: 35
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260748_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 140.34s
  factors: none

per representative:
  q_gap_bits: 232, 233, 232, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 342 JSONL ledgers and 34673 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260749` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260749 direct and top4 minimization

Continued the x7 focus line from the 342-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260749_skip_sampler_max512
  internal seed: 20260750
  frontier records: 1280
  frontier unique seen projection keys: 50659
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 319.44s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 58
    231: 182
    232: 132
    233: 77
    234: 38
    236: 25
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260749_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 153.80s
  factors: none

per representative:
  q_gap_bits: 231, 231, 232, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 347 JSONL ledgers and 35189 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260750` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260750 direct and top4 minimization

Continued the x7 focus line from the 347-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260750_skip_sampler_max512
  internal seed: 20260751
  frontier records: 1280
  frontier unique seen projection keys: 51392
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 307.49s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 69
    231: 188
    232: 110
    233: 70
    234: 37
    236: 38
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260750_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 128.87s
  factors: none

per representative:
  q_gap_bits: 234, 232, 230, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 352 JSONL ledgers and 35705 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260751` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260751 direct and top4 minimization

Continued the x7 focus line from the 352-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260751_skip_sampler_max512
  internal seed: 20260752
  frontier records: 1280
  frontier unique seen projection keys: 52130
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 302.83s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 65
    231: 206
    232: 140
    233: 44
    234: 27
    236: 30
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260751_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 157.72s
  factors: none

per representative:
  q_gap_bits: 231, 231, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 357 JSONL ledgers and 36221 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260752` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260752 direct and top4 minimization

Continued the x7 focus line from the 357-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260752_skip_sampler_max512
  internal seed: 20260753
  frontier records: 1280
  frontier unique seen projection keys: 52871
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 284.26s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 66
    231: 188
    232: 116
    233: 68
    234: 31
    236: 43
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260752_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 120.24s
  factors: none

per representative:
  q_gap_bits: 236, 233, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 362 JSONL ledgers and 36737 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260753` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260753 direct and top4 minimization

Continued the x7 focus line from the 362-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260753_skip_sampler_max512
  internal seed: 20260754
  frontier records: 1280
  frontier unique seen projection keys: 53612
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 331.29s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 58
    231: 189
    232: 142
    233: 63
    234: 32
    236: 28
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260753_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 229.06s
  factors: none

per representative:
  q_gap_bits: 231, 230, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 367 JSONL ledgers and 37253 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260754` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-15 x7 focus seed-base 20260754 direct and top4 minimization

Continued the x7 focus line from the 367-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260754_skip_sampler_max512
  internal seed: 20260755
  frontier records: 1280
  frontier unique seen projection keys: 54354
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 244.60s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 75
    231: 191
    232: 128
    233: 49
    234: 33
    236: 36
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260754_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 138.87s
  factors: none

per representative:
  q_gap_bits: 236, 233, 232, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 372 JSONL ledgers and 37769 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260755` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260755 direct rerun and top4 minimization

Continued the x7 focus line from the 372-ledger manifest.  The first direct
output directory, `tmp/ct07_x7_direct_focus_seed20260755_skip_sampler_max512`,
was interrupted after 290 q-gap cube rows and was not appended to the manifest.
Reran the same seed in a fresh output directory and used only the completed
rerun ledger:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260755_skip_sampler_max512_rerun
  internal seed: 20260756
  frontier records: 1280
  frontier unique seen projection keys: 55089
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 575.63s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 55
    231: 190
    232: 136
    233: 61
    234: 33
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260755_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 319.63s
  factors: none

per representative:
  q_gap_bits: 231, 232, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 377 JSONL ledgers and 38285 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260756` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260756 direct and top4 minimization

Continued the x7 focus line from the 377-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260756_skip_sampler_max512
  internal seed: 20260757
  frontier records: 1280
  frontier unique seen projection keys: 55838
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 865.85s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 69
    231: 183
    232: 111
    233: 72
    234: 42
    236: 35
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260756_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 287.03s
  factors: none

per representative:
  q_gap_bits: 231, 233, 232, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 382 JSONL ledgers and 38801 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260757` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260757 direct and top4 minimization

Continued the x7 focus line from the 382-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260757_skip_sampler_max512
  internal seed: 20260758
  frontier records: 1280
  frontier unique seen projection keys: 56574
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 519.61s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 71
    231: 181
    232: 120
    233: 77
    234: 27
    236: 36
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260757_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 264.48s
  factors: none

per representative:
  q_gap_bits: 234, 233, 233, 230
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 387 JSONL ledgers and 39317 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260758` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260758 direct and top4 minimization

Continued the x7 focus line from the 387-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260758_skip_sampler_max512
  internal seed: 20260759
  frontier records: 1280
  frontier unique seen projection keys: 57304
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 390.14s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 64
    231: 209
    232: 120
    233: 62
    234: 33
    236: 24
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260758_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 205.61s
  factors: none

per representative:
  q_gap_bits: 236, 230, 232, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 392 JSONL ledgers and 39833 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260759` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260759 direct and top4 minimization

Continued the x7 focus line from the 392-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260759_skip_sampler_max512
  internal seed: 20260760
  frontier records: 1280
  frontier unique seen projection keys: 58043
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 481.74s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 58
    231: 195
    232: 126
    233: 68
    234: 28
    236: 37
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260759_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 377.99s
  factors: none

per representative:
  q_gap_bits: 233, 236, 230, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 397 JSONL ledgers and 40349 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260760` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260760 direct and top4 minimization

Continued the x7 focus line from the 397-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260760_skip_sampler_max512
  internal seed: 20260761
  frontier records: 1280
  frontier unique seen projection keys: 58789
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 436.21s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 59
    231: 201
    232: 136
    233: 63
    234: 22
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260760_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 272.21s
  factors: none

per representative:
  q_gap_bits: 231, 234, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 402 JSONL ledgers and 40865 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260761` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-19 x7 focus seed-base 20260761 direct and top4 minimization

Continued the x7 focus line from the 402-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260761_skip_sampler_max512
  internal seed: 20260762
  frontier records: 1280
  frontier unique seen projection keys: 59531
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 861.95s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 68
    231: 193
    232: 119
    233: 69
    234: 33
    236: 30
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260761_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 328.55s
  factors: none

per representative:
  q_gap_bits: 232, 231, 231, 236
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 407 JSONL ledgers and 41381 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260762` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-20 x7 focus seed-base 20260762 direct and top4 minimization

Continued the x7 focus line from the 407-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260762_skip_sampler_max512
  internal seed: 20260763
  frontier records: 1280
  frontier unique seen projection keys: 60267
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 539.65s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 76
    231: 180
    232: 118
    233: 74
    234: 29
    236: 35
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260762_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 427.63s
  factors: none

per representative:
  q_gap_bits: 231, 234, 233, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 412 JSONL ledgers and 41897 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260763` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-20 x7 focus seed-base 20260763 direct and top4 minimization

Continued the x7 focus line from the 412-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260763_skip_sampler_max512
  internal seed: 20260764
  frontier records: 1280
  frontier unique seen projection keys: 61005
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 532.79s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 65
    231: 192
    232: 123
    233: 73
    234: 28
    236: 31
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260763_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 229.03s
  factors: none

per representative:
  q_gap_bits: 231, 230, 232, 234
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 417 JSONL ledgers and 42413 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260764` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-20 x7 focus seed-base 20260764 direct and top4 minimization

Continued the x7 focus line from the 417-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260764_skip_sampler_max512
  internal seed: 20260765
  frontier records: 1280
  frontier unique seen projection keys: 61750
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 422.44s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 56
    231: 179
    232: 128
    233: 64
    234: 42
    236: 43
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260764_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 284.55s
  factors: none

per representative:
  q_gap_bits: 231, 231, 232, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 422 JSONL ledgers and 42929 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260765` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-20 x7 focus seed-base 20260765 direct and top4 minimization

Continued the x7 focus line from the 422-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260765_skip_sampler_max512
  internal seed: 20260766
  frontier records: 1280
  frontier unique seen projection keys: 62492
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 597.94s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 63
    231: 198
    232: 120
    233: 54
    234: 36
    236: 41
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260765_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 256.58s
  factors: none

per representative:
  q_gap_bits: 232, 234, 230, 232
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 427 JSONL ledgers and 43445 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260766` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-06-20 x7 focus seed-base 20260766 direct and top4 minimization

Continued the x7 focus line from the 427-ledger manifest:

```text
direct run:
  tmp/ct07_x7_direct_focus_seed20260766_skip_sampler_max512
  internal seed: 20260767
  frontier records: 1280
  frontier unique seen projection keys: 63235
  sampled SAT records: 512
  q-gap records: 512
  elapsed: 414.38s
  status_counts: {"no_roots": 512}
  q_gap_bits:
    230: 62
    231: 189
    232: 128
    233: 63
    234: 37
    236: 33
  factors: none
```

Representative independent nibble-drop minimization completed:

```text
minimization:
  tmp/ct07_x7_independent_min_seed20260766_skip_sampler_top4
  records_completed: 4 / 4
  elapsed: 218.71s
  factors: none

per representative:
  q_gap_bits: 234, 231, 231, 231
  independent drops:
    150:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    920:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    265:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
    362:4 -> droppable_sound_no_root, 16/16 completions, 146 literals
```

The x7 focus manifest now contains 432 JSONL ledgers and 43961 cube rows.  All
manifest cube rows are q-gap `no_roots`; no factor has been recovered.  Continue
with `seed-base 20260767` for the next 512-row x7 focus direct batch if this
line remains the top priority.

## 2026-07-05 decision: freeze q-gap default loop

Do not continue the x7-focused low600 q-gap loop with `seed-base 20260767` by
default.  The current x7 focus ledger total is 432 JSONL ledgers and 43961
q-gap `no_roots` cube rows with no recovered factor.  Repeated top4 independent
minimization keeps proving `150:4`, `920:4`, `265:4`, and `362:4` droppable,
yielding 146-literal sound no-root variants, but this is branch exclusion rather
than evidence of convergence to `p` or `q`.

Next work should move back to `soinsu/rsa_partial_leak_assets` and run the
Sage+cuso paths on a machine with Sage, cuso, flatter, and msolve:

```text
1. Smoke grouped `--mode cuso` and split `--mode cuso-split`.
2. Sweep grouped 2-variable cuso over candidates 0..256.
3. Sweep split exact-block cuso with `--cuso-split-brute-small-edges`.
4. Only return to SAT/q-gap after cuso logs motivate a new ranker, shape, or
   hybrid strategy.
```

## 2026-07-05 plan update: partial low600 cuso broad clauses

Updated the continuation plan with a new broad-pruning oracle:
`ct07_partial_low600_cuso_broad_clause`.

Rationale: the previous x7/q-gap focus fixes the full low600 unknown set
`150:4,265:84,362:58` plus `920:4`, then learns 146-literal branch-exclusion
rows.  That makes each oracle call narrow.  A partial low600 p-Coppersmith
oracle should instead fix only part of the low600 unknowns and keep the
remaining low holes plus `z600 = p[600..1023]` as cuso variables:

```text
Shape B:
  fixed:    150:4, 362:58
  variable: 265:84, z600:424
  clause size: 62
  variable mass: 508 bits

Shape C:
  fixed:    265:84
  variable: 150:4, 362:58, z600:424
  clause size: 84
  variable mass: 486 bits

Shape A:
  fixed:    362:58
  variable: 150:4, 265:84, z600:424
  clause size: 58
  variable mass: 512 bits
```

Priority order after q-gap freeze:

```text
1. Smoke existing grouped and split cuso modes in soinsu.
2. Add a partial_low600 cuso oracle under rsa_partial_leak_assets.
3. Smoke Shape B, then Shape C, then Shape A.
4. Validate cuso root/no-root behavior on planted/toy instances.
5. Promote only sound no-root results to SAT hard clauses.
6. Use heuristic no-root results only for ranking until soundness is established.
7. Run mixed cuso shape search across grouped/exact/partial models.
```

Classification rule for the new oracle:

```text
factor       verified p recovered
candidate    roots returned but no factor verified
soft_no_root cuso returned no roots, but incompleteness risk remains
hard_no_root soundness gate passed; safe to translate fixed bits into a clause
```

Do not add cuso multivariate `no roots` results directly to the SAT ledger until
the soundness gate is explicit.  The intended SAT integration is an outer loop
that adds a learned clause immediately after a sound broad no-root result,
rather than another offline JSONL-only sampling ledger.

## 2026-07-05 plan update: literature-backed experiment tracks

Expanded the plan from a single partial-low600 oracle into four named research
tracks:

```text
A. ct07_programmatic_low600_sat_cas
   Ajani-Bright-style solver-in-loop Coppersmith.
   Use a PySAT outer loop first:
     solve -> choose 58-84 fixed low bits -> partial_low600 oracle
     -> factor / hard_no_root / soft_no_root / candidate
     -> solver.add_clause(...) only for hard_no_root.

B. ct07_cuso_mixed_shape_search
   cuso automatic shift-selection over grouped, exact, mixed, and partial
   shapes.  Score elapsed time, cuso backend logs, roots count, candidate/factor
   hits, and planted no-root reliability.

C. ct07_focus_group_hm
   Local HM/fpylll rescue line.  Build smaller planted instances with the same
   mask geometry, inspect which input shifts contribute to useful output rows,
   keep algebraically independent rows that vanish at the true root, and prune
   unused shifts before scaling.

D. ct07_cocert_clause_minimization
   Ledger repair line.  Treat each no-root as a co-certificate and optimize for
   branch coverage per clause.  Prefer 58-84 literal broad clauses over
   146-literal full-cube exclusions.
```

Immediate priority order:

```text
1. Prove the external Sage+cuso environment with grouped and split smoke runs.
2. Implement partial_low600 cuso relation builder and Shape B/C/A smoke tests.
3. Validate no-root soundness on planted/toy instances.
4. Start ct07_programmatic_low600_sat_cas only after hard_no_root criteria are explicit.
5. Run ct07_cuso_mixed_shape_search as the parallel cuso exploration lane.
6. Use ct07_focus_group_hm only when improving local fallback lattice parameters.
7. Use ct07_cocert_clause_minimization to measure clause coverage and prevent
   another narrow offline JSONL ledger loop.
```

Scope notes:

```text
Heninger-Shacham:
  useful for low-bit prefix search discipline, not directly applicable because
  this challenge leaks p bits only, not q/d/dp/dq.

Herrmann-May / Howgrave-Graham / Coppersmith:
  baseline theory for unknown-divisor partial-bit factoring, but naive
  many-chunk multivariate HM remains expensive.

Implicit factorization / ACD and small-d partial-information lines:
  low priority for this single-modulus, e=65537, partial-p leak instance.
```
