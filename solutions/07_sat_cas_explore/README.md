> [!NOTE]
> **해결됨.** 최종 구현은 [`solve_07_grouped_hm_flatter.cpp`](../solve_07_grouped_hm_flatter.cpp),
> 완결된 설명과 검증 결과는 [7번 소인수분해 writeup](../../writeups/07_소인수분해.md)에 있다.
> 아래 내용은 해결 이전의 역사적 탐색 기록으로 보존한다.

# Challenge 7 Corrected-PDF Workspace

This directory is the fresh workspace for the corrected problem 7 PDF uploaded
on 2026-06-05.  The previous exploration directory is preserved as
`../07_sat_cas_explore.old`.

Do not load old-mask learned clauses, old q-gap candidate JSON files, or old
low-Coppersmith ledgers into this workspace.  The corrected PDF keeps `N`, `e`,
and `ct`, but changes the p-bit mask and `p & mask`.

Corrected unknown p intervals, least-significant-bit indexed:

```text
150..153   4 bits
265..348  84 bits
362..419  58 bits
600..668  69 bits
682..768  87 bits
784..829  46 bits
920..923   4 bits
```

The current primary path is no longer another q-gap ledger batch.  As of
2026-07-05, freeze the x7-focused q-gap default loop and move the next work to
`soinsu/rsa_partial_leak_assets` and the literature-backed SAT/CAS tracks:

```text
1. Smoke grouped `--mode cuso` and split `--mode cuso-split`.
2. Add `ct07_partial_low600_cuso_broad_clause`.
3. Smoke partial low600 shapes B, C, and A, with planted soundness checks.
4. Start `ct07_programmatic_low600_sat_cas` after hard_no_root is defined.
5. Run `ct07_cuso_mixed_shape_search` across grouped/exact/mixed shapes.
6. Keep `ct07_focus_group_hm` and `ct07_cocert_clause_minimization` as fallback
   lattice and ledger-repair tracks.
7. Keep q-gap batches as fallback/reproduction paths.
```

Named experiment lanes:

```text
ct07_programmatic_low600_sat_cas:
  Ajani-Bright-style solver loop; Coppersmith no-root becomes an immediate
  learned clause only after the soundness gate passes.

ct07_cuso_mixed_shape_search:
  cuso automatic shift-selection over grouped 2-var, exact 5-var, low-exact
  high-grouped, low-grouped high-exact, and partial-low600 shapes.

ct07_focus_group_hm:
  downscaled planted local-HM experiments to identify useful lattice shifts and
  prune fallback fpylll bases.

ct07_cocert_clause_minimization:
  co-certificate view of no-root rows; optimize branch coverage per clause
  instead of ledger row count.
```

The old q middle-gap Coppersmith hard-line frontier used:

```text
150:4,265:24,745:24,784:46,920:4
```

This gives q gaps around 456-457 bits, which is hard-eligible with
`epsilon=0.02` and an 8-bit safety margin, but it is no longer the default
continuation without a changed ranker or branch shape.

## Smoke

```bash
PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

## Generate Corrected Candidates

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-a \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_fresh_gateway_hashA_top64.json
```

The option names `x2-low` and `x5-high` are historical; trust the emitted
`fixed_ranges` start/width values.  In this corrected workspace they correspond
to low bits starting at `265` and high-side bits ending at `769`.

## Run q-gap Batch

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_gateway_hashA_top64.json \
  --output-dir tmp/ct07_fresh_gateway_hashA_top64_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Root hits are final only after verifying `N % q == 0` and the complementary p
matches the corrected p mask.  No-root results are hard clauses only when the
reported effective q-gap margin is at least 8 bits.

## Run full-x1/full-x5 Drop Loop

This branch shape fixes `150:4,265:84,784:46,920:4`, giving q gaps around
407-408 bits.  It is slower per cube but has a much larger hard margin.

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 4 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_second_cube_drops.jsonl
```

The loop writes `loop_summary.json` under `tmp/ct07_fresh_fullx1x5_drop_loop_*`.
Run with `--dry-run --json` to inspect the child command without starting Sage.
The default q-gap epsilon is `0.04`, which is still hard-eligible for the
observed q-gap 408 cubes.

The loop has two drop modes.  `independent` is the default and verifies each
drop window separately.  `cumulative` verifies the growing union of windows and
can produce a stronger single clause when the union completion count remains
small:

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

This verified a combined `150:4 + 920:4` drop on the all-zero cube, producing a
130-literal hard clause from the 138 selected literals.

The configurable `--cube-ranges` option can run the newer high32 q-gap path.
This fixes only the high 32 bits of the `784..829` unknown block instead of the
whole 46-bit block:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --drop-mode cumulative \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --iterations 4 \
  --workers 8 \
  --q-gap-max-bits 440 \
  --q-gap-epsilon 0.0305 \
  --q-gap-minimize-max-completions 256 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_cumulative_edges_eps00305_max440.jsonl
```

This path produces 116-literal hard clauses from 124 selected literals when the
combined edge drop passes.

Additional hi32 all-zero independent byte-drop ledgers:

```text
tmp/ct07_fresh_x0x1x5hi32x6_independent_265_798_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_273_806_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_281_814_eps0028_max445.jsonl
tmp/ct07_fresh_x0x1x5hi32x6_independent_289_822_eps0028_max445.jsonl
```

Load them with the edge ledger when continuing hi32 SAT exploration:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --drop-mode cumulative \
  --cube-ranges 150:4,265:84,798:32,920:4 \
  --iterations 20 \
  --workers 8 \
  --q-gap-max-bits 440 \
  --q-gap-epsilon 0.0305 \
  --q-gap-minimize-max-completions 256 \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_cumulative_edges_eps00305_max440.jsonl \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_independent_265_798_eps0028_max445.jsonl \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_independent_273_806_eps0028_max445.jsonl \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_independent_281_814_eps0028_max445.jsonl \
  --resume-jsonl tmp/ct07_fresh_x0x1x5hi32x6_independent_289_822_eps0028_max445.jsonl
```

For stronger byte-level pruning, pass explicit drop windows:

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
  --resume-jsonl tmp/ct07_fresh_fullx1x5_drop_loop_after_allzero_bytes_iter1_midset_eps004/iteration_0001.jsonl
```

## Run Resumable 16-bit Union Proof

Use `run_q_gap_union_shards.py` for multi-hour cumulative drop proofs.  It
writes one JSON file per shard and can resume completed shards:

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
  --output-dir tmp/ct07_fresh_hi32_union_265_273_eps0028 \
  --resume \
  --max-new-shards 8 \
  --json
```

The tracked `265:8 + 273:8` union proof in
`tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028` is complete.  All 128 shards
passed, covering `65536 / 65536` hard no-root completions with no factor.  It
wrote `learned_clause.jsonl`, a 108-literal hard clause that drops the 16 bits
`265..280` from the selected 124-bit high32 cube.

After loading that union clause and the earlier `x0=1` ledger, the follow-up
loop in `tmp/ct07_fresh_hi32_after_union_x0_2_5_independent_265_273_eps0028`
closed four more one-cube hard q-gap checks with no factor:

```text
150:4 = 2, 3, 7, 5
265:84 = 0
798:32 = 0
920:4 = 0
```

Each cube had `q_gap_bits=437` and generated two independent 116-literal
drop clauses for `265:8` and `273:8`.  Loading all current ledgers makes the
next sample cube `150:4=4, 265:84=0, 798:32=0, 920:4=0`.

The subsequent high32/all-zero x0-front runs in
`tmp/ct07_fresh_hi32_after_union_x0_4plus_independent_265_273_eps0028`,
`tmp/ct07_fresh_hi32_after_union_x0_14plus_independent_265_273_eps0028`, and
`tmp/ct07_fresh_hi32_after_union_x0_9_8_independent_265_273_eps0028` closed the
remaining `150:4` values for `265:84=0, 798:32=0, 920:4=0`, with no factor.
Loading all high32 ledgers now moves the sample to
`150:4=8, 265:84=65536, 798:32=0, 920:4=0`, so that shape has started walking
the `265:84` space and is no longer the best immediate line.

The q-gap 408 medium-drop line is currently more useful.  The latest batch in
`tmp/ct07_fresh_fullx1x5_drop_loop_midset_after1794_iter5_eps004` closed
`265:84 = 1292, 1028, 1542, 3337, 2317` with hard no-root and no factor.  The
next sample on that line is `150:4=0, 265:84=3088, 784:46=0, 920:4=0`.

The continuation in
`tmp/ct07_fresh_fullx1x5_drop_loop_midset_after3088_iter10_eps004` closed ten
more q-gap 408 cubes with no factor:

```text
265:84 = 3088, 2072, 2830, 2567, 3587
265:84 = 3851, 6405, 6927, 7953, 7442
```

After loading those ledgers, the next q-gap 408 sample is
`150:4=0, 265:84=5911, 784:46=0, 920:4=0`.

An additional diversified gateway batch in
`tmp/ct07_fresh_gateway_hashC_top128_parallel` checked 128 hard-line
`q_gap_bits=456` candidates with no factor.  The next q-gap 408 SAT-ledger
continuation in `tmp/ct07_fresh_fullx1x5_drop_loop_midset_after5911_iter10_eps004`
closed ten more `q_gap_bits=408` cubes:

```text
265:84 = 5911, 4891, 5407, 4381, 4630
265:84 = 6675, 6165, 4116, 5145, 5658
```

After loading those ledgers, the next q-gap 408 sample is
`150:4=0, 265:84=7196, 784:46=0, 920:4=0`.

The p-window `[362,830)` success oracle was tested on that next q-gap408 sample
with `epsilon=0.005` and a 120 second timeout.  It timed out, so it is not
currently suitable for broad automatic batching.  The full seven-variable
unknown-divisor lattice preflight also still has a strongly negative proxy
margin.

The next q-gap 408 continuation in
`tmp/ct07_fresh_fullx1x5_drop_loop_midset_after7196_iter10_eps004` closed ten
more hard-no-root cubes:

```text
265:84 = 7196, 7710, 14370, 14625, 15392
265:84 = 15652, 10533, 11564, 11304, 10281
```

After loading those ledgers, the next q-gap 408 sample is
`150:4=0, 265:84=12589, 784:46=0, 920:4=0`.

## Run Low600 Batch

This is the older fully fixed low600 p-Coppersmith line.  In the corrected
mask, fixing `150:4,265:84,362:58` makes p[0..600) contiguous.  With
`epsilon=0.02`, the hard no-root margin is about 46 bits.  Keep these ledgers as
sound supporting evidence, but do not use this as the next broad default batch.
The preferred replacement is a partial-low600 cuso oracle that fixes only
58-84 low bits and leaves the rest plus `z600 = p[600..1023]` as variables.

The available seed ledgers are:

```text
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_probe.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_iter5.jsonl
tmp/ct07_fresh_low600_drop_x0_runner_smoke_eps002/iteration_0001.jsonl
```

Run a bounded 12-hour continuation with:

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

The runner writes `iteration_*.jsonl`, `iteration_*.stderr`, and
`loop_summary.json` under the selected output directory.  It exits with status
`0` if a factor is found and `2` if the bounded batch finishes without a
factor.

The stronger low600 mode is the cumulative 8-bit drop:

```text
drop windows: 150:4, 265:4
max completions: 256
```

The probe in
`tmp/ct07_fresh_low600_drop_x0_x1low4_cumulative_probe_eps002` proved all
`256/256` combined completions hard no-root, with no factor, and moved the next
sample to `150:4=0,265:84=59,362:58=0`.  It took about 451 seconds with
8 workers.  Prefer this mode for longer runs when wall time is available:

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

Use `--max-new-shards` or `--max-seconds` for future bounded batches.  Completed
shards carry a proof key, and resume refuses to mix shards from different proof
parameters.
