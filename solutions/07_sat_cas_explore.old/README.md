# Challenge 7 SAT+CAS Exploration

This folder is intentionally separate from the existing `solutions/try_07_*`
and lattice scripts.  It explores the 2026-06-01 direction change: use a SAT
cube loop with external CAS/oracle checks, and learn only sound no-good clauses.

Start with `EXPLORATION_PLAN.md` for the current integrated strategy.  This
README lists the tooling; `RUN_LOG.md` keeps detailed experiment evidence.

## Files

- `EXPLORATION_PLAN.md`: concise control document for the current hard oracles,
  ranking-only directions, and next exploration loop.
- `sat_cas_core.py`: loads the challenge constants, applies fixed p-bit ranges,
  derives q low bits and q interval high-prefix bits, and exposes an exact
  Z3 product-prefix oracle.
- `semi_programmatic_sat.py`: enumerates priority p-bit cubes, calls the exact
  product-prefix oracle, and blocks cubes.  Product-prefix `unsat` is a hard
  learned no-good.  Low-Coppersmith `no_roots` can optionally be generalized
  by exhaustively validated drop windows before the hard clause is learned;
  preverified drop windows from a separate exhaustive union checker can also
  be applied without repeating the expensive completion proof when their guard
  p-ranges match the current cube. Repeated low-residue oracle checks are
  cached inside each run.
  Non-contradictory cubes are blocked only as sampling cubes.
- `sat_cas_batch_runner.py`: bounded subprocess runner for repeated
  `semi_programmatic_sat.py` cube batches; preserves child JSONL records,
  timeout metadata, and minimized low-Coppersmith clause options.
- `run_updated_plan.py`: dry-run-first coordinator for the updated plan. It
  emits or runs the Phase A margin audit, 600-bit low-C union shards, optional
  high20 q272 exact-carry jobs, and an optional SAT-loop smoke stage.
- `sat_batch_analyzer.py`: compact analyzer for batch-runner JSONL output,
  including hard-block counts, minimized low-clause counts, dropped literal
  totals, low-Coppersmith cache hits, status histograms, learned-clause
  histograms, dropped-bit hot spots, and factored events.
- `deterministic_low_runner.py`: enumerates low-prefix cubes in ordinal order
  instead of relying on solver model order, then audits prefix and
  low-Coppersmith oracle results.
- `low_coppersmith_oracle.py`: optional Sage univariate Coppersmith hook for
  contiguous p low bits, for example p[0..599]. It reports epsilon-aware
  effective margin and only marks no-root results hard-eligible when the
  configured safety margin is satisfied.
- `low_coppersmith_threshold_audit.py`: audits low-bit trigger thresholds,
  theorem margin, selected literal counts, and optional oracle status.
- `edge_folded_margin.py`: computes the edge-folded bivariate margin for a
  fixed assignment and reports it as a verifier/ranking hook.  Failure is never
  a hard clause.
- `dynamic_q_probe.py`: measures how many q bits are implied by p interval
  assignments.
- `q_prefix_growth_search.py`: bounded search for fixed p-bit ranges that
  maximize interval-derived q prefix growth.
- `q_prefix_tie_analyzer.py`: groups q-prefix candidates by derived q prefix
  and known-bit count, then reports value histograms for the best tie group.
- `q_tie_guided_batch.py`: selects high candidates from full-x6 q-prefix tie
  groups and runs bounded deterministic low-prefix SAT/CAS batches.
- `q_edge_rank_probe.py`: ranks q-prefix growth for x2/x5 edge chunks under
  the folded-Coron verifier branch.
- `q_x5_beam_search.py`: extends x5 high-edge q-prefix ranking into a staged
  beam search that emits 48-bit x5 candidates strong enough for the folded
  Coron edge oracle.
- `q_x5_extended_beam_search.py`: continues the same x5 high-edge beam past
  the 48-bit Coron trigger to 64-bit or full 87-bit x5 candidates, with
  optional x0/x1/x7 selection.
- `q_x5_x0x7_extended_sweep.py`: sweeps x0, optional full-x1 values, and x7
  around the extended x5 beam and ranks the merged full-x5 candidates.
- `q_x5_x7_beam_search.py`: sweeps x7 while running the staged x5 high-edge
  beam, then ranks combined x7+x5 candidates by q-prefix strength.
- `x2_low_prefix_probe.py`: diagnoses x2 low-edge candidates by measuring
  q-low/q-prefix growth, low-Coppersmith trigger readiness, and exact
  product-prefix consistency.
- `low_x1_x2_beam_probe.py`: grows x1 low-prefix chunks together with x2
  low32 candidates and ranks the retained low-side branches by q-derived and
  exact product-prefix signals.
- `low_contiguous_sample_probe.py`: samples full x0+x1+x2+x3 contiguous-low
  assignments, audits sound low-Coppersmith trigger readiness, and can run the
  Sage low-bit oracle with a timeout guard.
- `low_contiguous_rank_batch.py`: ranks bounded full contiguous-low samples by
  q-low/q-known/product-prefix signals before optional low-Coppersmith oracle
  calls.
- `low_coppersmith_clause_minimize.py`: exhaustively varies small windows
  inside a full low-Coppersmith no-good to test whether those literals can be
  soundly dropped from a learned clause.
- `low_coppersmith_window_sweep.py`: subprocess-parallel wrapper around the
  minimizer for ranking several candidate drop windows.
- `low_coppersmith_multicube_window_sweep.py`: compares single-window
  low-Coppersmith drops across several selected low cubes by reusing the
  window sweep subprocess.
- `low_coppersmith_multicube_greedy_minimize.py`: greedy union-checked
  low-Coppersmith minimizer across several selected low cubes, accepting a
  dropped literal window only when every completion in every variant remains a
  hard-eligible `no_roots` result.
- `low_coppersmith_multicube_union_check.py`: parallel fixed-union checker
  that deduplicates completion cases across low-cube variants before running
  the low-Coppersmith oracle; supports completion-space shards for larger
  unions.
- `low_coppersmith_union_shard_analyzer.py`: aggregates fixed-union checker
  shard JSON outputs, reports covered/missing completion ranges, and totals
  hard-eligible no-root/factor counts.
- `low_coppersmith_union_shard_batch.py`: resumable wrapper that runs
  fixed-union checker completion shards in smaller chunks and writes per-shard
  JSON plus JSONL progress records.
- `low_coppersmith_greedy_minimize.py`: standalone greedy minimizer that tries
  several drop windows while rechecking the union of already dropped bits and
  the next window before accepting more dropped literals; repeated
  low-residue oracle checks are cached inside each run.
- `low_coppersmith_union_order_sweep.py`: subprocess-parallel wrapper around
  the greedy minimizer for comparing several candidate-window orders under
  the same union-completion soundness rule.
- `q_hensel_prefix_search.py`: combines q-prefix ranking with BV/Hensel prefix
  consistency checks before the low-Coppersmith trigger.
- `q_guided_batch_compare.py`: compares tiny q-guided deterministic low-prefix
  batches across high-side strategies.
- `edge_rank_sweep.py`: ranks small x1/x6 edge samples by folded margin.
- `partial_x1_margin_sweep.py`: measures folded margin when only selected x1
  low/high/split bits are fixed.
- `partial_x6_margin_sweep.py`: measures folded margin when only selected x6
  high bits are fixed.
- `partial_x1_coron_runner.py`: combines partial-x1 margin checks with bounded
  actual Coron reconstruction when x1 is fully fixed.
- `coron_reconstruction_sweep.py`: counts reconstructed Coron polynomials for
  positive-margin folded branches before invoking root solving; supports extra
  edge fixed p-ranges for verifier-threshold probes.
- `coron_grid_runner.py`: subprocess grid runner for Coron reconstruction
  sweeps with per-row timeouts.
- `coron_fixed_range_profiles.py`: compares low-edge/high-edge fixed p-range
  profiles for the folded Coron verifier.
- `coron_edge_oracle.py`: heuristic success oracle that runs folded Coron
  reconstruction, root solving, and verified factor checks for edge profiles;
  supports explicit `--x0`, `--x1`, and `--x7` branches.
- `coron_edge_candidate_loop.py`: bounded candidate loop that feeds x2 low32,
  explicit x5 high48, q-beam x5 high48, q-beam x7+x5, or extended x5
  assignments into the Coron edge oracle; extended-x5 candidates forward
  x0/x1/x7, and `--dry-run` reports the candidate set without oracle calls.
- `coron_edge_threshold_sweep.py`: sweeps partial x2/x5 edge widths to find
  actual reconstruction thresholds.
- `coron_lll_variant_probe.py`: bounded wrapper around the s=46,k=6 folded
  Coron reconstruction row across LLL delta and direct/projected variants.
- `unknown_divisor_preflight.py`: estimates HM/Lu-Zhang determinant margins for
  active unknown-divisor variable subsets.
- `small_lz_lattice_probe.py`: builds a small HM/Lu-Zhang-style basis for
  active subsets and checks rank/LLL sanity.
- `lz_prune_search.py`: runs bounded relation-evaluation candidates and ranks
  whether they produce nontrivial sampled pruning.
- `lz_prune_grid.py`: runs a timeout-bounded grid of LZ pruning candidates and
  summarizes whether any non-projection-derived pruning signal appears.
- `lz_m3_grid_probe.py`: focused m=3 wrapper for the active LZ projection
  subsets that previously showed relation-count signals.
- `lz_depth_prune_probe.py`: guarded m/t depth wrapper for LZ pruning probes,
  including dimension and evaluator-support skips.
- `lz_relation_value_ranker.py`: wraps the LZ relation evaluator and ranks the
  selected relation by sampled value metadata, explicitly reporting when raw
  value evaluation is unavailable.
- `sumset_preflight.py`: compares shift-family support growth before expensive
  LLL runs.
- `mixed_pq_lattice_probe.py`: diagnostic smoke probe that adds one or more
  explicit q-window variables to a small `P*Q-N` lattice family and can
  evaluate sampled canonical q-window assignments; repeated `--q-window`
  values are supported, and the report flags q-gap bits inside the sampled
  modulus, but this is not a sound pruning oracle.
- `RUN_LOG.md`: records the current experimental outcomes.
- `test_sat_cas_core.py`: lightweight regression checks for the shared helpers.

## Example Commands

Run a small semi-programmatic SAT sample:

```bash
python3 solutions/07_sat_cas_explore/semi_programmatic_sat.py --max-cubes 8 --jsonl
```

Preview the updated plan without starting any search:

```bash
python3 solutions/07_sat_cas_explore/run_updated_plan.py
```

Trigger the low-bit oracle only after supplying enough low p bits:

```bash
python3 solutions/07_sat_cas_explore/low_coppersmith_oracle.py \
  --fix-p-range 150:4:0 \
  --fix-p-range 210:39:0 \
  --fix-p-range 265:84:0 \
  --fix-p-range 362:78:0 \
  --json
```

Probe the edge-folded margin after fixing x0, x1, x6, and x7:

```bash
python3 solutions/07_sat_cas_explore/edge_folded_margin.py \
  --fix-p-range 150:4:0 \
  --fix-p-range 210:39:0 \
  --fix-p-range 784:46:0 \
  --fix-p-range 920:4:0 \
  --json
```

Compare unknown-divisor active subsets:

```bash
python3 solutions/07_sat_cas_explore/unknown_divisor_preflight.py \
  --active x0,x1,x6,x7 --m-max 10 --t-max 3 --json
```

Build a small HM/Lu-Zhang-style basis:

```bash
python3 solutions/07_sat_cas_explore/small_lz_lattice_probe.py \
  --active x0,x1,x6,x7 --anchor x0 --m 2 --t 1 --lll --json
```

## Clause Discipline

Only exact contradictions become hard no-good clauses in this folder.  The Z3
product-prefix oracle can return `unsat`, `sat`, or `unknown`; only `unsat`
blocks the cube as a learned contradiction.  Coppersmith no-root results are
kept out of the hard stream unless `--low-coppersmith-hard-fail` is explicitly
enabled and the epsilon-aware effective margin meets the configured safety
threshold.  With the default `epsilon=0.02` and
`min_hard_margin_bits=8.0`, `low_bits=513` is diagnostic only and
`low_bits=600` is the current p-low hard target.  Minimized low-Coppersmith
clauses require every dropped-window completion to independently return
hard-eligible `no_roots`; when multiple windows are requested, the union of
already dropped bits and the next window is checked before dropping more
literals.  Edge-folded Coron is a success/ranking hook only.
