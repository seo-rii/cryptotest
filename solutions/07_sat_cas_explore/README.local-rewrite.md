> [!NOTE]
> **해결됨.** 최종 구현은 [`solve_07_grouped_hm_flatter.cpp`](../solve_07_grouped_hm_flatter.cpp),
> 완결된 설명과 검증 결과는 [7번 소인수분해 writeup](../../writeups/07_소인수분해.md)에 있다.
> 아래 내용은 해결 이전의 역사적 탐색 기록으로 보존한다.

> [!WARNING]
> 이 디렉터리의 q-gap 출력에서 `hard`, `proof`, `hard_no_root`로 기록된 값은
> 모두 휴리스틱이다. 당시 oracle은 `beta=0.5`를 사용했지만 최종 복원된 작은
> 소인수 `q`는 `q^2 < N`이어서 Sage `small_roots`의
> `q >= N^beta` 전제를 만족하지 않는다. 양의 margin이나 모든 completion의
> 전수검사는 이 전제를 복구하지 않는다. 반면 큰 소인수 `p`를 대상으로 한
> low600 결과는 `p^2 > N`, Sage backend, bound·margin gate와 completion
> 검사를 모두 만족한 경우에만 조건부 hard evidence로 해석할 수 있다.

# Challenge 7 historical SAT/CAS workspace

This directory preserves the last SAT/CAS workspace used before the final
grouped Herrmann--May solution.  The preceding exploration snapshot is kept in
`../07_sat_cas_explore.old`.

Commands below are preserved as they were run from the workspace directory
containing `cryptotest/`.  When running from this repository root, remove the
leading `cryptotest/` component.

Most referenced `tmp/` ledgers and generated candidate files were intentionally
excluded from Git.  Commands that consume those files document experiment
provenance; only commands whose inputs are present or regenerated first are
standalone reproductions.

Do not load old-mask learned clauses, old q-gap candidate JSON files, or old
low-Coppersmith ledgers into this workspace; their bit-range metadata is not
compatible with the experiments recorded here.

The p unknown intervals used here, indexed from the least significant bit, are:

```text
150..153   4 bits
265..348  84 bits
362..419  58 bits
600..668  69 bits
682..768  87 bits
784..829  46 bits
920..923   4 bits
```

At the final pre-solution checkpoint on 2026-07-05, the plan was to freeze the
x7-focused q-gap loop and move the next experiments to
`soinsu/rsa_partial_leak_assets` and literature-backed SAT/CAS tracks:

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

Historical experiment-lane names:

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

The q middle-gap Coppersmith frontier historically labelled `hard-line` used:

```text
150:4,265:24,745:24,784:46,920:4
```

This gives q gaps around 456--457 bits and passed the old effective-margin gate
with `epsilon=0.02` and an 8-bit safety margin.  That gate did not enforce
`q >= N^beta`, so these rows are heuristic candidate-ranking evidence rather
than branch exclusions.

## Smoke

```bash
PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

## Generate Candidates

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-fresh-a \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_fresh_gateway_hashA_top64.json
```

The option names `x2-low` and `x5-high` are historical; trust the emitted
`fixed_ranges` start/width values.  In this workspace they correspond to low
bits starting at `265` and high-side bits ending at `769`.

## Run q-gap Batch

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_fresh_gateway_hashA_top64.json \
  --output-dir tmp/ct07_fresh_gateway_hashA_top64_parallel \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Root hits are final only after verifying `N % q == 0` and that the complementary
`p` matches the supplied mask.  A q-gap `no-root` is not a hard clause here:
the reported margin omits the failed divisor-size precondition described at the
top of this document.

## Run full-x1/full-x5 Drop Loop

This branch shape fixes `150:4,265:84,784:46,920:4`, giving q gaps around
407--408 bits.  It was slower per cube but had a much larger reported margin.

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 4 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_second_cube_drops.jsonl
```

The loop writes `loop_summary.json` under `tmp/ct07_fresh_fullx1x5_drop_loop_*`.
Run with `--dry-run --json` to inspect the child command without starting Sage.
The default q-gap epsilon is `0.04`; the observed 408-bit-gap cubes passed the
old margin gate but remain heuristic for the same divisor-size reason.

The loop has two drop modes.  `independent` checks each drop window separately.
`cumulative` checks the growing union of windows and can produce a shorter
heuristic clause record when the completion count remains small:

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

This checked every completion for a combined `150:4 + 920:4` drop on the
all-zero cube and produced a 130-literal clause record from 138 selected
literals.  Because the underlying q-gap oracle is heuristic, the minimized
clause is heuristic too.

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

This path produced 116-literal heuristic clause records from 124 selected
literals when the combined edge completion sweep passed.

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

## Run Resumable 16-bit Completion Sweep

Use `run_q_gap_union_shards.py` for multi-hour cumulative completion sweeps.  It
writes one JSON file per shard and can resume completed shards.  The script and
some output fields retain the historical word `proof`, but the result is not a
sound branch proof:

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

The tracked `265:8 + 273:8` union sweep in
`tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028` is complete.  All 128 shards
returned no root, covering `65536 / 65536` completions with no factor.  It
wrote `learned_clause.jsonl`, a 108-literal heuristic clause record that drops
the 16 bits `265..280` from the selected 124-bit high32 cube.  Exhausting the
completion set validates the minimization procedure, not the q-gap oracle's
missing beta precondition.

After loading that union clause and the earlier `x0=1` ledger, the follow-up
loop in `tmp/ct07_fresh_hi32_after_union_x0_2_5_independent_265_273_eps0028`
recorded four more one-cube q-gap `no-root` checks with no factor:

```text
150:4 = 2, 3, 7, 5
265:84 = 0
798:32 = 0
920:4 = 0
```

Each cube had `q_gap_bits=437` and generated two independent 116-literal
heuristic drop-clause records for `265:8` and `273:8`.  Loading all ledgers
available at that checkpoint made the next sample cube
`150:4=4, 265:84=0, 798:32=0, 920:4=0`.

The subsequent high32/all-zero x0-front runs in
`tmp/ct07_fresh_hi32_after_union_x0_4plus_independent_265_273_eps0028`,
`tmp/ct07_fresh_hi32_after_union_x0_14plus_independent_265_273_eps0028`, and
`tmp/ct07_fresh_hi32_after_union_x0_9_8_independent_265_273_eps0028` closed the
remaining `150:4` values for `265:84=0, 798:32=0, 920:4=0`, with no factor.
Loading all high32 ledgers now moves the sample to
`150:4=8, 265:84=65536, 798:32=0, 920:4=0`, so that shape has started walking
the `265:84` space and is no longer the best immediate line.

At that checkpoint the q-gap 408 medium-drop line was the more active one.  The
batch in
`tmp/ct07_fresh_fullx1x5_drop_loop_midset_after1794_iter5_eps004` closed
`265:84 = 1292, 1028, 1542, 3337, 2317` with heuristic `no-root` and no factor.  The
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
`tmp/ct07_fresh_gateway_hashC_top128_parallel` checked 128
`q_gap_bits=456` candidates on a path historically labelled `hard-line`, with
no factor.  The next q-gap 408 SAT-ledger
continuation in `tmp/ct07_fresh_fullx1x5_drop_loop_midset_after5911_iter10_eps004`
closed ten more `q_gap_bits=408` cubes:

```text
265:84 = 5911, 4891, 5407, 4381, 4630
265:84 = 6675, 6165, 4116, 5145, 5658
```

After loading those ledgers, the next q-gap 408 sample is
`150:4=0, 265:84=7196, 784:46=0, 920:4=0`.

The p-window `[362,830)` success oracle was tested on that next q-gap408 sample
with `epsilon=0.005` and a 120 second timeout.  It timed out, so it was not
suitable for broad automatic batching.  The full seven-variable
unknown-divisor lattice preflight also still has a strongly negative proxy
margin.

The next q-gap 408 continuation in
`tmp/ct07_fresh_fullx1x5_drop_loop_midset_after7196_iter10_eps004` closed ten
more heuristic `no-root` cubes:

```text
265:84 = 7196, 7710, 14370, 14625, 15392
265:84 = 15652, 10533, 11564, 11304, 10281
```

After loading those ledgers, the next q-gap 408 sample is
`150:4=0, 265:84=12589, 784:46=0, 920:4=0`.

## Run Low600 Batch

This is the older fully fixed low600 p-Coppersmith line.  Fixing
`150:4,265:84,362:58` makes `p[0..600)` contiguous.  Unlike the q-gap line, it
targets the recovered larger factor `p`, for which `p^2 > N`.  With Sage's
univariate backend, `epsilon=0.02`, the recorded bound and an 8-bit safety gate,
the hard no-root margin is about 46 bits.  These ledgers are sound supporting
evidence only under those backend, bound, margin and completion assumptions;
they were not a practical route to covering the full branch space.
The preferred replacement is a partial-low600 cuso oracle that fixes only
58-84 low bits and leaves the rest plus `z600 = p[600..1023]` as variables.

The available seed ledgers are:

```text
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_probe.jsonl
tmp/ct07_fresh_low600_nodrop_iter20_eps002/low600_drop_x0_iter5.jsonl
tmp/ct07_fresh_low600_drop_x0_runner_smoke_eps002/iteration_0001.jsonl
```

A bounded 12-hour continuation was configured as follows:

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
`tmp/ct07_fresh_low600_drop_x0_x1low4_cumulative_probe_eps002` checked all
`256/256` combined completions as hard `no-root` under the low600 conditions
above, with no factor, and moved the next
sample to `150:4=0,265:84=59,362:58=0`.  It took about 451 seconds with
8 workers.  This was the preferred longer-run mode at that checkpoint:

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

The runner also accepts `--max-new-shards` or `--max-seconds` for bounded
batches.  Completed shards carry an internal `proof_key`; resume refuses to mix
shards produced with different oracle parameters.  The field only protects
resume consistency; soundness still depends on the oracle conditions above.
