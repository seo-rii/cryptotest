# Challenge 7 Multi-Direction Run Log

> [!NOTE]
> Archived pre-solution run log.  The
> [final writeup](../../writeups/07_소인수분해.md) is the source of truth for
> the completed attack.  q-gap rows called `hard` or `proof` below are
> heuristic because their `beta=0.5` divisor-size precondition fails for the
> recovered smaller factor; dates, labels, and commands are preserved as run.

This log records exploratory attempts that are separate from the older
`solutions/try_07_*` scripts.

## 2026-06-05 Corrected PDF Checkpoint

Contest HQ published a corrected problem PDF, uploaded locally as
`cryptotest/problems/7_소인수분해.pdf`.  `N`, `e`, and `ct` are unchanged, but the
p-bit mask and `p & mask` changed.  The old PDF had 613 known p bits and 411
unknown bits across eight intervals; the corrected PDF has 672 known p bits
and 352 unknown bits across seven intervals:

```text
150..153   4 bits
265..348  84 bits
362..419  58 bits
600..668  69 bits
682..768  87 bits
784..829  46 bits
920..923   4 bits
```

The old `210..248` unknown block is now known, and the old `362..439` block is
shortened to `362..419`.  All old-mask learned clauses, low-C union coverage,
q-gap ledgers, and ranked candidates are instance-specific and must not be
loaded into corrected-PDF runs.

Code updates:

- `investigate_07_rsa_partial_bits.py` now uses the corrected `MASK` and
  `p & MASK`.
- `test_sat_cas_core.py` now expects the seven corrected unknown intervals and
  the corrected q-low frontier behavior.
- `q_gap_gateway_beam_search.py` no longer requires the removed `210:39`
  gateway block.  The corrected hard-line branch shape uses:

  ```text
  150:4,265:24,745:24,784:46,920:4
  ```

- `unknown_divisor_preflight.py` now derives variable blocks from the current
  instance instead of hardcoding the old eight-block shape.
- `two_sided_window_coppersmith.py` was added for p middle-window experiments.
  It verifies that all bits outside `[L,H)` are fixed by the PDF mask plus the
  candidate ranges before calling Sage.

Corrected-PDF smoke checks:

```bash
PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Result: `10/10` tests passed.

```bash
python3 cryptotest/solutions/investigate_07_rsa_partial_bits.py
```

Result: `known p bits: 672 / 1024`, `unknown p bits: 352`, with the seven
unknown intervals listed above.

Corrected q-gap first hard cube:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --include-cube-ranges \
  > tmp/ct07_corrected_pdf_qgap_first_cube_20260605.jsonl
```

Result: one q-gap Coppersmith call, `q_gap_bits=457`, hard-eligible
`no_roots`, no roots or factors.

Corrected independent drop test on that cube:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 265:8 \
  --q-gap-drop-window 920:4 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges \
  > tmp/ct07_corrected_pdf_qgap_first_cube_drops_20260605.jsonl
```

Result: 288 q-gap calls, two independent hard clauses, 12 dropped bits total.
The droppable windows were `150:4` and `265:8`; `920:4` is not a default drop
window because one completion pushes the q gap above the hard threshold.

Corrected diversified q-gap beam smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash \
  --diversity-salt corrected-qgap-20260605-a \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_corrected_pdf_gateway_hashA_top64_20260605.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_corrected_pdf_gateway_hashA_top64_20260605.json \
  --output-dir tmp/ct07_corrected_pdf_gateway_hashA_top64_parallel_20260605 \
  --candidate-start 1 --candidate-stop 64 --chunk-size 8 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 --no-pdf-check
```

Result: 64 candidates tested in about 221 seconds, all `q_gap_bits=456`,
`64/64 no_roots`, no roots or factors.

p-window sanity:

- `[265,769)` candidate top1 with `epsilon=0.005` timed out after 120 seconds.
- `[265,745)` candidate top1 now reaches Sage correctly, but timed out after
  30 seconds.  This path is a success oracle only for now; corrected q-gap is
  still the better broad pruning path.

## SAT+CAS

- Product-prefix BV/Z3 alone produced mostly `sat` or `unknown`; no hard
  product-prefix no-good was found in the sampled runs.
- Exact prefix enumeration was added for small free-prefix cases. It confirms
  consistency quickly but still did not prune the sampled cubes.
- Low-bit Coppersmith callback is the strongest sound oracle so far. With
  p[0..599] assigned by zeroing x0/x1/x2/x3, Sage returned no roots and the
  SAT loop learned hard no-good clauses. A 3-cube run produced
  `low_coppersmith_calls=3`, `low_coppersmith_hard_blocks=3`.
- The SAT events can now include the exact blocked cube ranges with
  `--include-cube-ranges`, which makes learned no-goods auditable.
- Low-Coppersmith no-root clauses now learn only the selected low-prefix
  literals below the Coppersmith trigger bound. A smoke run with selected bits
  from x0/x1/x2/x3 plus extra high bits x6/x7 had `selected_bits=217` but
  `learned_clause_literal_count=205`, so high-side verifier bits are no longer
  accidentally tied to a low-prefix no-good.
- A 4-cube low-Coppersmith batch over x0/x1/x2/x3 plus x6top8/x7 produced
  four `no_roots` callbacks and four hard blocks. Each learned clause still
  used exactly the 205 low-prefix selected bits, while the product-prefix check
  itself was `sat`.
- `sat_cas_batch_runner.py` is now available for bounded append-only JSONL
  runs. A one-cube verification wrote runner metadata plus the child cube
  result; the low-Coppersmith pass-through produced
  `low_coppersmith_hard_blocks=1` and `timed_out=false`.
- `sat_batch_analyzer.py` summarizes runner JSONL logs. On
  `/tmp/ct07_batch3_low.jsonl`, it reported 2 cube records, 2 low-Coppersmith
  calls, 2 low-Coppersmith hard blocks, no factored events, and learned scope
  `low_prefix_selected_bits: 2`.
- A pure low-prefix 2-cube batch over x0/x1/x2/x3 again returned two
  low-Coppersmith `no_roots` hard blocks. Without high-side x6/x7 in the cube,
  the derived q interval prefix fell to 100 bits, but the sound low-prefix
  no-good behavior stayed the same.
- Two additional low-prefix slices with `x0=1` and `x0=15` fixed also returned
  low-Coppersmith `no_roots` hard blocks. Since x0 was fixed outside the cube,
  learned clauses used 201 selected low-prefix literals instead of 205.
- `--prefix-core hensel` adds a Z3 bit/carry recurrence core. It is fast and
  decisive around the x1 boundary (`check_bits=218` and `272` both returned
  `sat` on sampled cubes), but at `check_bits=380` with 16 x2 bits fixed it
  returned `unknown` for 8 sampled cubes. This is still better-structured than
  raw BV multiplication, but not enough for hard pruning before the low
  Coppersmith trigger.
- A later `check_bits=380` Hensel run with 52 selected bits timed out at 60s
  after three sampled cubes; all three were `unknown` and only sample-block
  clauses were added.
- `deterministic_low_runner.py` removes Z3 model-order effects by enumerating
  selected low-prefix ranges directly. A smoke with top q-prefix high candidate
  `822:8=0x1,920:4=0x8` and the all-zero low prefix reproduced the sound
  low-Coppersmith hard block: product prefix was `sat`, Coppersmith returned
  no roots, and the learned clause scope had 205 deterministic low-selected
  literals. With full x6 fixed to `0x245521490bd` and x0/x7 treated as high
  candidates, two q-prefix-255 candidates also returned no roots; the learned
  clause literal count was 201 because x0 was fixed outside the low cube.
- `low_coppersmith_threshold_audit.py` checked whether lowering the univariate
  trigger below 600 bits could shrink no-good clauses. For the all-zero
  `x0,x1,x2,x3` low assignment, thresholds `440,512,513,560,600` were all fully
  assigned, with theorem margins `-72,0,1,48,88` bits respectively. The selected
  low literal count stayed 205 for every threshold because the same four low
  unknown ranges must be fixed before any threshold above 512 is contiguous.
  With `--run-oracle --low-bits-values 600`, Sage returned `no_roots` and only
  then the hard clause was eligible.

## Dynamic q Bits

Command:

```bash
python3 solutions/07_sat_cas_explore/dynamic_q_probe.py --max-cubes 16 --jsonl
```

Result: the default cube ranges kept `q_known_bits=418`,
`q_low_bits=218`, and `q_prefix_bits=200` for all 16 sampled cubes. This is
useful bookkeeping, but not yet a strong pruning source.

## Edge-Folded / Tail Verifier

The edge margin probe reproduces the known positive folded margin when x1 and
x6 are fully fixed:

```bash
python3 solutions/07_sat_cas_explore/edge_folded_margin.py \
  --fix-p-range 150:4:0 \
  --fix-p-range 210:39:0 \
  --fix-p-range 784:46:0 \
  --fix-p-range 920:4:0 \
  --json
```

Observed `primitive_margin=10.333333333333371`.

Short tail-plan run:

```bash
python3 solutions/cube_07_edge_driver.py ... --tail-plan-jsonl /tmp/ct07_short_plan.jsonl
python3 solutions/run_07_tail_plan.py --plan-jsonl /tmp/ct07_short_plan.jsonl \
  --out-jsonl /tmp/ct07_short_results.jsonl --parallel 4 --timeout 12
```

All 8 short tail probes returned `UNKNOWN`. Highest observed activity in the
short run was `x1_low=0xffff`, `x6_high=0x245521490bd`, `T=784`, with
`branches=7171`, `conflicts=582`. Treat this only as a ranking signal.

Dynamic-T top12 follow-up also returned only `UNKNOWN`. The highest activity
record was `T=768`, `x1_low=0xffff`, `x6_high=0x245521490bd`, `random_seed=2`,
with one extra `p[768] = 0` tail bit fixed: `branches=6966`,
`conflicts=350`.

The later 10-second tail push batch over `x1_low in {0xbbff,0x11ff,0x66ff,0xffff}`
and `x6_high=0x245521490bd` also returned only `UNKNOWN`; conflicts were lower
than the earlier short dynamic run.

After cloning `/tmp/crypto-attacks`, `solve_07_hybrid_coron.py` diagnose works
again. With only x6 fixed at `0x245521490bd`, primitive margin is still
`-67.67`, so Coron remains a verifier only after x1 is fully fixed.

`edge_rank_sweep.py` now sorts by larger primitive margin first. With
`x0=x7=0`, `x1 in {0,0xffff}`, and `x6 in {0,0x245521490bd}`, the tail-ranked
x6 value `0x245521490bd` also had the better folded-Coron verifier margin:
`primitive_margin=10.666...` versus `10.333...` for `x6=0`.

`edge_candidate_runner.py` turns explicit x0/x1/x6/x7 tuples into bounded
verifier records. It confirmed:

- `(x0,x1,x6,x7)=(0,0,0,0)`: `primitive_margin=10.333...`.
- `(0,0,0x245521490bd,0)`: `primitive_margin=10.666...`.

`solve_07_hybrid_coron.py` now accepts `--x1-value` and computes the folded
low/high boundaries from the remaining p-unknown mask. This makes the hybrid
diagnose path reproduce the edge verifier geometry. For
`x0=0,x1=0,x7=0,x6=0x245521490bd,s=46`, diagnose now reports
`low=265`, `p_hi=769`, `Xbits=504`, `Ybits=504`, and
`primitive_margin=10.67`. Without `--x1-value`, the same branch has
`low=210`, `Xbits=559`, and `primitive_margin=-62.67`.

The bounded actual Coron call now reaches the positive-margin branch. Initial
`k=6` runs with `--roots-method resultants` hit a crypto-attacks
`IndexError: list index out of range`; traceback showed the bug was in
`find_roots_resultants`, which assumed at least as many reconstructed
polynomials as variables. The positive branch at k=6 reconstructs no extra
polynomial, so the resultants method saw only `[p]`.

`solve_07_hybrid_coron.py` now monkey-patches a safe resultants wrapper that
returns no roots when `len(polynomials) < len(gens)`. After this, both direct
and projected k=6 resultants runs finish without exception and report no
factor. k=6 groebner also finishes without exception in about 5s. k=7 direct
Coron still ran until the 90s timeout. So the verifier bridge is fixed and the
spurious resultants crash is fixed; the remaining Coron bottleneck is producing
enough useful reconstructed polynomials at practical k.

`coron_failure_probe.py` records the lattice shape for this branch. For k=6 and
k=7 it found `delta=1`, max-norm monomial `[0,1]`, nonzero determinant, and
dimensionally consistent right-block reconstruction inputs (`13x13` for k=6,
`15x15` for k=7). This supports the conclusion that the earlier exception was
root-method input handling, not an empty right-block lattice.

`coron_reconstruction_sweep.py` now stops before root solving and counts the
actual reconstructed Coron polynomials. On the positive branch
`x0=0,x1=0,x6=0x245521490bd,x7=0,s=46,k=6`, both direct and projected variants
had the expected positive primitive margin and right-block shape, but
reconstructed 0 polynomials. The direct smoke row was `85x49` with a `13x13`
right block; projected had the same right block. This narrows the current
folded-Coron bottleneck to relation reconstruction, not branch geometry or
resultant handling.

`coron_grid_runner.py` wraps the reconstruction probe with per-row subprocess
timeouts. A default smoke grid over `s=45..46`, `k=5..6`, direct variant wrote
4 row records, had no timeouts or errors, and still had
`reconstructed_positive_rows=0`. The best primitive margin was the known
positive `10.666...` at `s=46`, so lowering k did not make reconstruction
produce usable relations.

`partial_x1_margin_sweep.py` and `partial_x1_coron_runner.py` tested whether
the full 39-bit x1 assignment can be relaxed. With x0, full x6, and x7 fixed,
x1 low widths `0,8,16,24,32` had primitive margins from about `-62.67` to
`-20.00`; even low width 38 stayed negative at `-12.00`. Only width 39 jumps
to `low_bits=265`, crosses the known `p[249..264]` gap, and reaches
`primitive_margin=10.666...`. The bounded actual reconstruction at full width
39 still returned 0 reconstructed polynomials.

`partial_x6_margin_sweep.py` gives the symmetric high-side result. With x0,
full x1, and x7 fixed, x6 high widths up to 45 remain negative; width 45 has
margin `-10.67`. Only full width 46 jumps over the known `p[769..783]` gap,
sets `high_start=769`, reaches `q_prefix_bits=255`, and gives the known
positive margin. So the folded-Coron verifier really requires both x1 and x6
to be completely fixed, not just almost fixed.

## Unknown-Divisor Lattice

The determinant preflight is useful as a ranking filter, but the current
script does not give a positive all-original-variable target:

- active `x0,x1,x2,x3,x4,x5,x6,x7`: best margin about `-675.95` bits.
- active `x0,x1,x6,x7`: best current margin about `-39.19` bits for
  `m<=5,t<=3`; the fixed `m=4,t=1` rerun was about `-144.67` bits.
- active `x0,x1,x2,x7`: best current margin about `-78.12` bits.
- active `x0,x1,x3,x7`: best current margin about `-71.97` bits.
- active `x0,x1,x2,x3,x7`: best current margin about `-330.75` bits.

This says the full 8-var unknown-divisor lattice is not a good next LLL target;
small subset probes are still useful for construction sanity, but not yet a
factor-recovery path.

Small basis construction check:

```bash
python3 solutions/07_sat_cas_explore/small_lz_lattice_probe.py \
  --active x0,x1,x6,x7 --anchor x0 --m 2 --t 1 --lll --json
```

Observed before scaling: 15x15 square basis, rank 15, `det_bits=20479`, and
`lll_first_norm_bits=1024`.

After adding variable-bound scaling, the same active subset produced:

- `m=2`: 15x15 full-rank, `lll_first_norm_bits=1024`.
- `m=3`: 35x35 full-rank, `lll_first_norm_bits=1021`.
- `m=4`: 70x70 full-rank, `lll_first_norm_bits=972`.

The `m=4` relation-size signal is below the 1024-bit divisor scale, so this
subset construction is worth extending when the omitted variables have been
fixed or otherwise absorbed. It still does not solve the original instance by
itself because omitted variables are not eliminated.

`weighted_lz_probe.py` adds a weighted-bit-budget column family to keep small
4-bit variables in the basis while limiting large variables. Verification
results:

- `budget=20,m=2,t=1`: 6x21 rectangular matrix, rank 6, LLL relation count 0.
- `budget=54,m=1,t=1`: 24x121 rectangular matrix, rank 24.
- `budget=54,m=2,t=1`: still 24 rows because complete `f^2` rows exceed the
  weighted budget; rank 24.

So the weighted family is a useful preflight knob, but the tested budgets did
not produce a usable relation.

`weighted_lz_sweep.py` now wraps small and weighted probes with timeouts and
ranking. A small-subset sweep at `m=4,t=1` produced relation-size signals below
1024 bits for several 4-variable projections:

- active `x0,x1,x2,x3`: first norm 910 bits, 45 relations under threshold.
- active `x0,x1,x2,x7`: first norm 954 bits, 44 relations under threshold.
- active `x0,x1,x3,x7`: first norm 1009 bits, 48 relations under threshold.

These are construction signals only; the omitted variables are not eliminated.
The same wrapper also showed weighted budgets 50 and 54 recovering only the
linear baseline relation at exactly 1024 bits, while budget 93 produced a large
rectangular rank signal without LLL under the chosen dimension cap.

A follow-up sweep at `m in {2,3}` showed the strongest cheap signal on the
low-side projection:

- active `x0,x1,x2,x3`, `m=3`: first norm 932 bits, 19 relations under threshold.
- active `x0,x1,x6,x7`, `m=3`: first norm 1021 bits, 18 relations.
- active `x0,x1,x2,x7`, `m=3`: first norm 1011 bits, 16 relations.

`lz_relation_audit.py` rebuilds the same small lattice and classifies short LLL
rows. For active `x0,x1,x2,x3`, `m=3`, all 19 rows under threshold were
classified as `higher_degree`, not linear baseline f-multiples or pure
N-multiples. This is still not a solve because the original omitted variables
remain unresolved, but it makes the projection signal less likely to be just a
trivial row.

`lz_relation_eval_probe.py` checked whether one of those higher-degree
relations gives extra pruning on sampled low-prefix assignments. For active
`x0,x1,x2,x3`, `m=3`, the selected degree-3 relation was
`identically_derived_mod_projection=true`; sample evaluation saw no extra
modular pruning and no integer zero. So the current small-projection relations
are useful diagnostics, but not yet a SAT oracle.

`lz_prune_search.py` wraps the single relation evaluator across bounded active
sets and m/t choices. A smoke over `x0,x1,x2` and `x0,x1,x6` at `m=2,t=1`
found relation rows, but both selected relations were projection-derived and
had `prune_score=0`: no sampled modular prune and no integer zero. This keeps
the current unknown-divisor relation track in diagnostic mode rather than a
sound SAT callback.

`lz_prune_grid.py` runs a timeout-bounded grid around the same evaluator. Its
default smoke over four active subsets at `m=2` completed four grid points with
no timeouts or errors; best prune score was 0, nonderived relation count was 0,
and `extra_modular_prune_seen` remained 0. This further confirms that the
current small LZ projections are not yet useful as pruning callbacks.

## Sumset / Shift Preflight

The support-growth proxy is conservative. It flags broad `cuso8` and
`liftT_proxy` shift families as expanding at shift-degree 2, while the existing
`sweep_07_liftT_branches.py` still gives concrete T=600/x6top8 candidates with
`G_terms=31`, `G_W=1246`, `Zbits=222`, `Ybits=222`. Prefer the concrete sweep
metrics when available; use the proxy to compare candidate shift families before
large reductions.

`liftT_actual_sumset.py` now accepts actual sweep rows or direct branch metrics
and builds a bounded synthetic support from those numbers. Recent signals:

- Sweep over `T in {600,608,784}` with x6top8 ranked T=784 first:
  `Zbits=38`, `Ybits=205`, `G_terms=82`, `G_W=1229`.
- Feeding those T=784 metrics to the actual-ish preflight still failed:
  shift-degree 1 had `growth_ratio=9.49` and `FAIL_EXPANDING`; shift-degree 2
  hit the support cap.
- Fallback T=600 with `G_terms=31` also failed expanding
  (`growth_ratio=4.54` at shift-degree 2).

This makes the liftT shift-family track a poor candidate for another large LLL
run until a much tighter shift restriction is found.

`sumset_shift_sweep.py` wraps these checks across T values, shift degrees, caps,
and inline metric rows. Using the concrete T=600 and T=784 metrics, every tested
row remained `FAIL`: T=600 had `growth_ratio=5.48` at shift-degree 1 and
`7.32` even at degree 0; T=784 had `growth_ratio=9.49` at shift-degree 1 and
`12.86` at degree 0.

After cloning `/tmp/cuso`, a capped one-branch cuso run was attempted:

```bash
PYTHONPATH=/tmp/cuso/src timeout 60 python3 solutions/solve_07_cuso.py \
  --branch --branch-low 0 --branch-high 0 --max-branches 1 \
  --max-multiplicity 1 --max-shifts 32 --no-intermediate --disable-recenter
```

It initialized the 6-variable branch and generated a multiplicity-1 ideal with
about a 1024-bit modulus, then hit the 60s timeout before any relation/factor
signal.

A stricter capped cuso rerun with `--max-shifts 8`, small-variable weight
factor 4, and graph slack 32 finished one branch in 11.5s and returned 0
candidate roots. The no-graph version with the same shift cap hit the 45s
timeout before a candidate signal.

## q-Interval Ranking

`q_interval_sweep.py` ranks fixed p-bit cubes by derived q-known gain. It
confirmed that high-side decisions are useful for q interval propagation even
when they are not part of the low-Coppersmith no-good:

- Fixing only small x0/x7 bits gives essentially low-bit gain only:
  `q_known_gain=1` for a 1-bit x0 plus 1-bit x7 smoke sweep.
- Enumerating `x6top8` plus x7 gives about 90-94 extra q prefix bits over the
  base mask.
- Fully fixing x6 to the tail-ranked value `0x245521490bd`, then sweeping x0/x7,
  gives `q_known_bits` up to 465 and `q_known_gain` up to 215. The best sampled
  x7 values were 0 and 4 at `q_prefix_bits=255`.

This supports using x6-side decisions early for q-prefix propagation, but still
keeping low-Coppersmith hard no-goods scoped only to low-prefix assignments.

`q_guided_low_batch.py` automates this split: rank high-side assignments with
`q_interval_sweep.py`, pass the best high ranges as fixed p bits, and run
low-prefix cubes through `sat_cas_batch_runner.py`. Smoke runs with one high
candidate and one low cube completed successfully for both an explicit x6-low
range and the default x6-top range. In both cases the analyzer reported one
low-Coppersmith call, one hard block, no factor, and learned scope
`low_prefix_selected_bits`.

`q_prefix_growth_search.py` adds a bounded, product-safe way to compare q-prefix
growth candidates. A 32-cube smoke over `822:8,920:4` ranked
`822:8=0x1,920:4=0x8` first with `q_prefix_bits=202` and `q_known_bits=352`.
When the full tail-ranked x6 value is fixed and x7 is swept, best candidates
reach `q_prefix_bits=255`. A top-4 q-guided low batch over the partial high
search then ran 8 low-prefix cubes: all 8 triggered low-Coppersmith no-root
hard blocks, all learned clauses stayed scoped to `low_prefix_selected_bits`,
and no factor event was observed.

`q_hensel_prefix_search.py` connects q-prefix ranking to prefix consistency
checks. On the default top-2 `822:8,920:4` candidates, Hensel checks at
272 and 320 bits returned `unknown` for all 4 records. With full x6 fixed and
the top x0/x7 q-prefix candidates (`q_prefix_bits=255`), the same 272/320-bit
Hensel checks also returned `unknown`. No early hard UNSAT block has been found
from q-prefix propagation alone.

`q_guided_batch_compare.py` compared three tiny deterministic strategies. With
one low cube per strategy, `partial_822_920` observed `q_prefix_bits=202`,
`full_x6_x0_x7` observed `q_prefix_bits=255`, and `no_high_guide` observed
`q_prefix_bits=100`. All three prefix checks were `sat`; all three called
low-Coppersmith once, got one no-root hard block, and found no factor. The full
x6 strategy learned 201 literals because x0 was outside the low cube; the other
two learned 205.

## Batch 10 Follow-Up

`q_prefix_tie_analyzer.py` inspected the full-x6 branch
`784:46:0x245521490bd` while sweeping x0 and x7. The 256 candidates collapsed
to four q-prefix groups:

- `q_prefix_bits=255`, `q_known_bits=465`: 48 candidates.
- `q_prefix_bits=254`, `q_known_bits=464`: 112 candidates.
- `q_prefix_bits=253`, `q_known_bits=463`: 48 candidates.
- `q_prefix_bits=252`, `q_known_bits=462`: 48 candidates.

The best group does not distinguish x0: all 16 `150:4` values appear exactly
three times. It does narrow x7 to `920:4` values `0x0`, `0x4`, and `0x8`,
with 16 candidates each. So full-x6 q-prefix ranking is a useful high-side
ordering signal, but not enough to shrink the low-Coppersmith clause scope.

`low_coppersmith_threshold_audit.py --low-bits-values 513,560,600
--run-oracle` tested the first all-low-zero cube with actual Sage
Coppersmith calls. All three thresholds had positive theorem margin and
returned `no_roots`, making them hard-clause eligible:

- 513 bits: margin +1 bit, selected low literals 205.
- 560 bits: margin +48 bits, selected low literals 205.
- 600 bits: margin +88 bits, selected low literals 205.

This means the sound low-bit oracle can trigger as soon as the contiguous
threshold crosses 512 bits. In this mask, however, lowering the trigger does
not reduce the selected literal count for the x0/x1/x2/x3 low cube because the
same four low ranges are needed to make the prefix contiguous.

The q-guided batch comparison was rerun after the threshold audit. With one
low cube per strategy, `full_x6_x0_x7` again reached `q_prefix_bits=255` and
learned a 201-literal low block, while `partial_822_920` reached 202 bits and
`no_high_guide` stayed at 100 bits. All three prefix checks were `sat`; each
strategy made one low-Coppersmith call, got one no-root hard block, and found
no factor.

`coron_lll_variant_probe.py` wraps the positive folded branch
`s=46,k=6` across direct/projected reconstruction and LLL deltas
0.75, 0.8, and 0.99. After fixing the stale `build_branch()` call sites to pass
empty `fixed_p_ranges`, all six rows completed with no timeout or process
error. Every row kept the expected positive primitive margin
`10.666...`, but `short_row_count=0` and
`reconstructed_polynomial_count=0` for every variant. This rules out simple
LLL-delta and direct/projected right-block changes as the missing Coron
relation source.

`lz_m3_grid_probe.py` focused the unknown-divisor relation track on m=3 for
three active subsets. It reproduced relation-count signals without pruning:

- `x0,x1,x2,x3`: 19 relations.
- `x0,x1,x6,x7`: 18 relations.
- `x0,x1,x2,x7`: 16 relations.

All three were still `projection_derived_no_extra_prune`, with
`best_prune_score=0` and `extra_prune_count=0`. The m=3 LZ projection signal
therefore remains diagnostic only, not a usable SAT oracle yet.

## Batch 11 Follow-Up

`coron_reconstruction_sweep.py` now accepts extra `--fix-p-range` options and
records those ranges in each row. This matters only for edge-contiguous ranges:
the folded x variable still models one middle block, so interior holes are not
a valid way to enforce arbitrary bits.

`coron_fixed_range_profiles.py` compared low-edge and high-edge extensions of
the positive folded branch. Metadata-only geometry showed:

- base x1+x6 branch: `Xbits=504`, `Ybits=504`, primitive margin `10.666...`.
- low-edge x2 fixed (`265:84`): `Xbits=407`, `Ybits=407`, margin `140.0`.
- low-edge x2+x3 fixed: `Xbits=169`, `Ybits=169`, margin `457.333...`.
- high-edge x5 fixed (`682:87`): `Xbits=404`, `Ybits=407`, margin `143.0`.
- high-edge x4+x5 fixed: `Xbits=175`, `Ybits=178`, margin `448.333...`.

Actual LLL reconstruction then succeeded for all four non-base edge profiles
tested with zero values: x2, x5, x2+x3, and x4+x5 each produced
`short_row_count=13` and `reconstructed_polynomial_count=13`. The x2=0 profile
with resultants root solving returned 0 roots, as expected for a likely wrong
branch. This is still not a factor, but it is a strong new verifier threshold:
SAT does not need both x2 and x5; fixing either x2 or x5 in addition to x1/x6
is already enough for folded Coron relation reconstruction to turn on.

`q_tie_guided_batch.py` connects full-x6 q-prefix tie groups directly to
deterministic low-prefix batches. A two-high-candidate smoke selected the top
q-prefix group (`q_prefix_bits=255`, `q_known_bits=465`) and ran one low cube
per candidate. Both prefix checks were `sat`; both made one low-Coppersmith
call and got one hard no-root block; no factor was found. The wrapper reports
a sound 205-literal no-good scope because the x0 bits from the high candidate
are part of the low-Coppersmith assignment, even though the child low runner
selected only the remaining 201 low-range bits.

`lz_depth_prune_probe.py` adds a guarded m/t depth layer for the LZ pruning
track. With default subsets and `m in {3,4}`, `max_dimension=80`, and two
samples, it planned six combinations. The three m=3 jobs repeated the known
relation counts (`19`, `18`, `16`) with `best_prune_score=0`,
`nonderived_count=0`, and `extra_prune_count=0`. The three m=4 jobs have
dimension 70, but were skipped as `skipped_unsupported_m` because the current
relation evaluator only implements m=2 and m=3. A separate guard check with a
lower dimension cap skipped m=4 before evaluator spawn, so the wrapper can now
separate dimension infeasibility from evaluator support.

## Batch 12 Follow-Up

`coron_reconstruction_sweep.py` now verifies roots when `--run-roots` is used:
for each x-root it reconstructs the candidate p and only reports a verified
factor if `N % p == 0`. `coron_edge_oracle.py` wraps this as a heuristic
success oracle. A smoke on the x2=0 profile produced 13 reconstructed
polynomials but 0 roots and 0 verified factors, so wrong edge branches are not
promoted to success.

`coron_edge_threshold_sweep.py` narrowed the folded-Coron trigger width. The
base x1+x6 branch has positive margin but still reconstructs 0 polynomials.
Actual LLL rows show that partial edge assignments are enough:

- x2 low-edge widths 8 and 16: positive margin, 0 reconstructed polynomials.
- x2 low-edge width 32: first reconstruction success, 13 short rows and
  13 reconstructed polynomials.
- x2 widths 48, 64, and 84: also reconstruct 13.
- x5 high-edge widths 8, 9, 16, and 32: positive margin, 0 reconstructed
  polynomials.
- x5 high-edge width 48: first reconstruction success, 13 short rows and
  13 reconstructed polynomials.
- x5 widths 64 and 87: also reconstruct 13.

This improves the SAT+CAS target: the folded Coron verifier no longer needs
full x2 or full x5. It needs x1, x6, x0/x7, and either a 32-bit low-edge x2
chunk or a 48-bit high-edge x5 chunk before it becomes a practical success
oracle.

`q_edge_rank_probe.py` ranked q-prefix growth for those edge chunks under the
full-x6, x0=0, x7=0 branch. The base has `q_prefix_bits=255` and
`q_known_bits=465`. x2 prefix chunks do not improve this ranking in bounded
samples, but x5 high-edge 9-bit candidates do: the best smoke candidate
`760:9=0x2` reached `q_prefix_bits=264`, `q_known_bits=474`, and interval
width 760 bits. So q-prefix ranking naturally prefers the same high-side x5
edge that can eventually trigger folded Coron reconstruction.

`lz_relation_eval_probe.py` was opened to m=4. The generator was already
generic; the previous limitation was just the argparse choice list and the
conservative wrapper allow-list. `lz_depth_prune_probe.py` now permits m=4.
A bounded m=4 run with three subsets and one sample produced:

- `x0,x1,x2,x3`: ok, 70x70, 45 candidate relation rows, still
  projection-derived, prune score 0.
- `x0,x1,x2,x7`: ok, 70x70, 44 candidate relation rows, still
  projection-derived, prune score 0.
- `x0,x1,x6,x7`: timed out at 30 seconds under this cap.

This keeps the LZ track in diagnostic mode: m=4 produces more relation rows,
but no non-projection pruning signal has appeared yet.

## Batch 13 Follow-Up

`coron_edge_candidate_loop.py` turns the batch12 edge thresholds into a bounded
semi-programmatic success loop. It builds candidate assignments that are strong
enough to trigger folded-Coron reconstruction, calls `coron_edge_oracle.py`,
and treats only verified factors as success. A smoke over two candidates ran:

- x2 low32 candidate `265:32:0x0`: primitive margin `53.333...`,
  13 reconstructed polynomials, 0 roots, 0 verified factors.
- q-ranked x5 high48 candidate `721:48:0x10000000000`
  (`760:9=0x2` with zero low suffix): primitive margin `74.0`,
  13 reconstructed polynomials, 0 roots, 0 verified factors.

This confirms the oracle loop wiring works: candidate branches can reach the
relation stage and still avoid false factor success. It also confirms that the
current sampled candidates are wrong branches.

The next SAT/CAS target is now concrete:

- low-side path: decide x0, x1, x6, x7, and x2 low-edge 32 bits, then call
  `coron_edge_oracle.py`.
- high-side path: use q-prefix ranking on x5 high bits, extend to a 48-bit
  x5 high-edge candidate, then call `coron_edge_oracle.py`.

In both paths, failed Coron runs remain soft diagnostics only; verified factors
are hard success, and low-Coppersmith no-root remains the only current hard
no-good source.

## Batch 14 Follow-Up

`coron_edge_candidate_loop.py` now accepts explicit x5 high-edge candidates
with `--x5-values`, can report candidate construction without oracle calls via
`--dry-run`, and can call `q_x5_beam_search.py` with `--x5-beam` to generate
48-bit high-edge x5 candidates from q-prefix growth.

`q_x5_beam_search.py` extends the batch12 9-bit x5 ranking into staged chunks
of 9, 8, 8, 8, 8, and 7 bits from the high edge. A smoke beam with width 2 and
8 child cubes per parent first selected `760:9:0x2`, then produced two final
48-bit candidates:

- `721:48:0x8180828300`: `q_prefix_bits=303`, `q_known_bits=513`, interval
  width 721 bits.
- `721:48:0x10000808085`: `q_prefix_bits=303`, `q_known_bits=513`, interval
  width 721 bits.

This improves the full-x6/x0/x7 base branch from `q_prefix_bits=255` and
`q_known_bits=465`, and improves the earlier single-stage x5 high9 candidate
from `q_prefix_bits=264` and `q_known_bits=474`. The candidate loop dry-run
correctly converts both beam outputs into `721:48` x5 high-edge candidates.

Actual folded-Coron oracle calls on the two q-beam candidates reconstructed
13 polynomials in each branch, but still found no roots and no verified factor:

- `721:48:0x8180828300`: primitive margin about `74.667`, 13 reconstructed
  polynomials, 0 roots, 0 verified factors.
- `721:48:0x10000808085`: primitive margin about `74.667`, 13 reconstructed
  polynomials, 0 roots, 0 verified factors.

So q-beam is now a better high-side ranking generator, but the two strongest
sampled x5 high48 branches are not the factor branch.

`x2_low_prefix_probe.py` checks whether x2 low-edge decisions can help before
the low-Coppersmith trigger. For x2 low32 values 0 and 1, the branch stayed at
the base `q_low_bits=210`, `q_prefix_bits=255`, and `q_known_bits=465`; the
513, 560, and 600-bit low-Coppersmith triggers were all false. Exact product
prefix checks were `sat` at 218 bits and `unknown` at 272 bits under a short
timeout. Adding a sampled `x1` low16 value improved q-low to 226 bits and
`q_known_bits` to 481, with the 272-bit prefix check becoming `sat`, but the
low-Coppersmith trigger was still false.

The low-side conclusion is that x2 low32 alone is not a useful q-prefix
ranking hook. That path needs SAT/product-prefix decisions involving x1 and the
remaining low ranges; high-side x5 remains the better q-prefix-guided Coron
candidate source for now.

## Batch 15 Follow-Up

`coron_edge_oracle.py` now accepts `--x7` and passes it to
`coron_reconstruction_sweep.py`. This is necessary for x7-swept branches:
adding `920:4:<value>` as an extra fixed range would otherwise conflict with
the default folded branch's `x7=0` guess.

`coron_edge_candidate_loop.py` now accepts q-beam x7+x5 candidates through
`--x5-x7-beam`. These candidates keep the x5 fixed range as the oracle
`--fix-p-range` and pass x7 separately through `--x7`, so the branch geometry
matches the folded-Coron model.

`q_x5_x7_beam_search.py` sweeps x7 and runs the same staged high-edge x5 beam
under each x7 branch. With beam width 2 and 8 child cubes per parent, every
x7 value 0..15 produced a best final x5 high48 candidate at
`q_prefix_bits=303`, `q_known_bits=513`, and interval width 721 bits. The
merged top candidates began:

- x7=`0xf`, x5=`721:48:0x81830083`.
- x7=`0x6`, x5=`721:48:0x83010004`.
- x7=`0x6`, x5=`721:48:0x83010305`.
- x7=`0xd`, x5=`721:48:0x280838080`.

Actual folded-Coron oracle calls on the merged top three all reconstructed
13 polynomials but found no roots and no verified factor:

- x7=`0xf`, x5=`721:48:0x81830083`: 13 reconstructed, 0 roots, 0 factors.
- x7=`0x6`, x5=`721:48:0x83010004`: 13 reconstructed, 0 roots, 0 factors.
- x7=`0x6`, x5=`721:48:0x83010305`: 13 reconstructed, 0 roots, 0 factors.

This means x7 sweeping increases candidate diversity, but at the current beam
width it does not improve the q-prefix ceiling beyond the fixed-x7 beam's
303/513 result. The sampled top branches are still wrong branches.

`low_x1_x2_beam_probe.py` explores the low-side path by fixing x2 low32 and
growing x1 low-prefix chunks. With default `x1_low_bits=16`, beam width 4, and
x2=`0`, the top retained branches reached `q_low_bits=226`,
`q_known_bits=481`, and stayed at `q_prefix_bits=255`. The 218-bit product
prefix check was `sat` from the first stage; the 272-bit check became `sat`
once 15 x1 low bits were assigned. The final top four candidates were simply
x1 low16 values `0x0`, `0x1`, `0x2`, and `0x3`.

The low-side result is useful but not decisive: x1 low bits improve q-low and
prefix consistency, but the branch remains far below the 513-bit contiguous
low-Coppersmith trigger. It should be treated as a product-prefix ranking tool,
not as a hard pruning oracle.

Pushing the same low-side beam to full x1 width (`x1_low_bits=39`, beam width
8, x2=`0`) raised the top retained branches to `q_low_bits=297` and
`q_known_bits=552`, while `q_prefix_bits` stayed at 255. Product-prefix checks
at 218, 272, and 320 bits were all `sat` for the retained top candidates. This
is a stronger consistency/ranking signal than the 16-bit x1 probe, but it is
still not the sound low-Coppersmith trigger because the contiguous p-low region
only reaches 297 bits in this partial low-side branch.

## Batch 16 Follow-Up

The x7+x5 q-beam was widened to beam width 4 and 16 child cubes per parent.
This produced many new x7+x5 high48 candidates, but the q-prefix ceiling did
not improve: every best x7 branch still topped out at `q_prefix_bits=303`,
`q_known_bits=513`, and interval width 721 bits. The merged top four were:

- x7=`0xa`, x5=`721:48:0x104030389`.
- x7=`0xa`, x5=`721:48:0x104078387`.
- x7=`0xd`, x5=`721:48:0x280838186`.
- x7=`0xd`, x5=`721:48:0x280838601`.

All four folded-Coron oracle calls reconstructed 13 polynomials and found
0 roots / 0 verified factors. This keeps the 48-bit x5+x7 path in candidate
ranking mode only.

`q_x5_extended_beam_search.py` continues the x5 high-edge beam beyond the
48-bit trigger. With x7 fixed to 0, beam width 4, and 16 child cubes per
parent:

- x5 high64 reached `q_prefix_bits=319`, `q_known_bits=529`.
- full x5 high87 reached `q_prefix_bits=355`, `q_known_bits=565`.

This is the strongest q-prefix growth observed so far on the high side.
However, the top four full-x5 candidates all failed as factors after the
folded-Coron oracle:

- `682:87:0x40c04141804040c140c1`: 13 reconstructed, 0 roots, 0 factors.
- `682:87:0x40c04141804040c140ce`: 13 reconstructed, 0 roots, 0 factors.
- `682:87:0x40c04141804040c14344`: 13 reconstructed, 0 roots, 0 factors.
- `682:87:0x40c04141804040c14349`: 13 reconstructed, 0 roots, 0 factors.

Sweeping x7 with the full-x5 extended beam did not raise the ceiling above
355/565. A nonzero x7 sample, x7=`0x1` with
`682:87:0x18000014041c00000c3`, also reconstructed 13 polynomials but found
0 roots and 0 verified factors.

`low_contiguous_sample_probe.py` samples full contiguous-low assignments over
x0+x1+x2+x3. The default all-zero low sample under the full-x6/x7=0 branch
gives `p_contiguous_low_bits=600`, `q_low_bits=600`,
`q_prefix_bits=255`, and `q_known_bits=855`. Product-prefix checks at 320 and
384 bits were `sat`. With `--run-oracle` and a 30s per-threshold timeout, the
Sage low-Coppersmith oracle returned `no_roots` at 513, 560, and 600 bits.
All three are hard-clause eligible, and the resulting sound no-good scope is
205 sampled low literals.

`lz_relation_value_ranker.py` wraps `lz_relation_eval_probe.py` to make the
value-evaluation limitation explicit. For `active=x0,x1,x2,x3`, `m=4`,
`t=1`, four samples completed in about 17s with 45 candidate relation rows,
rank 70, and the selected relation labelled `derived_no_extra_prune`.
`extra_prune_count=0` and `nonderived_count=0`. The evaluator exposes only
counters and preview bit sizes, so the ranker reports
`sampled_preview_bits_no_raw_values`; this confirms the current LZ relation
track still cannot be promoted to a SAT hard-pruning oracle.

## Batch 17 Follow-Up

`q_x5_extended_beam_search.py` now accepts `--x0` as well as `--x7`, and
`coron_edge_oracle.py` passes `--x0` through to
`coron_reconstruction_sweep.py`. `coron_edge_candidate_loop.py` also forwards
x0/x7 for extended-x5 candidates.

`q_x5_x0x7_extended_sweep.py` wraps the extended x5 beam over all x0/x7 nibble
branches. With full x5 width 87, beam width 2, and 8 child cubes per parent,
all 256 branches completed and produced 512 merged candidates. The ceiling
remained unchanged at `q_prefix_bits=355`, `q_known_bits=565`, and interval
width 669 bits. The top merged candidates all used x7=`0x7` and
`682:87:0x8080404041804002`, with x0 varying across the same score class.
The top branch x0=`0x0`, x7=`0x7` reconstructed 13 folded-Coron polynomials
but found 0 roots and 0 verified factors.

This shows x0 does not materially improve the high-side q-prefix ranking under
the current full-x5 beam. x7 selects different high87 values, but the ceiling
stays at 355/565.

`low_contiguous_rank_batch.py` ranks bounded full contiguous-low samples before
running Sage. The default 0/1 grid over x0+x1+x2+x3 emitted 16 candidates; all
had `p_contiguous_low_bits=600`, `q_low_bits=600`, `q_known_bits=855`, and
both 320/384-bit product-prefix checks `sat`, so the cheap rank is a complete
tie under that small grid. A nonzero sample, x0=`1`, x1=x2=x3=`0`, was then
sent through the 513-bit low-Coppersmith oracle and returned `no_roots`.
That branch is hard-clause eligible with the same 205-literal low no-good
scope as the all-zero sample.

## Batch 18 Follow-Up

`q_x5_extended_beam_search.py` now accepts optional full x1 values for
p[210..248]. `coron_edge_oracle.py` and `coron_edge_candidate_loop.py` pass
x1 through to the folded-Coron verifier, and `q_x5_x0x7_extended_sweep.py`
can now sweep x0/x1/x7 jointly. Candidate merging now keys on x1 as well, so
identical x5 ranges from different x1 branches stay distinct.

For x1=`0`, `1`, `2`, and `3` with x0=x7=`0`, full x5 width 87, beam width 4,
and 16 child cubes per parent, every branch selected the same top x5 range:

- `682:87:0x40c04141804040c140c1`
- `q_prefix_bits=355`, `q_known_bits=620`, `q_low_bits=265`, interval width
  669 bits.

Compared with leaving x1 unset, fixing x1 raises the q-known count from 565 to
620 and q-low from 210 to 265. It does not raise the q-prefix ceiling above
355.

The x0/x1/x7 wrapper was smoke-tested with x5 width 16 over x0=`0,1`,
x1=`none,0,1`, and x7=`0,1`; all 12 branches completed, and duplicate x5
ranges were preserved as separate x1 candidates.

Actual folded-Coron oracle checks still did not find a factor:

- x1=`0x2`, x7=`0x0`, x5=`682:87:0x40c04141804040c140c1`:
  primitive margin 144, 13 reconstructed polynomials, 0 roots, 0 factors.
- x1=`0x2`, x7=`0x7`, x5=`682:87:0x8080404041804002`:
  primitive margin 144, 13 reconstructed polynomials, 0 roots, 0 factors.

This keeps the high-side x1-aware q-ranking path as a candidate generator only.
The extra x1 information improves derived q bits, but the sampled branches
remain wrong for factor recovery.

## Batch 19 Follow-Up

The existing low-Coppersmith callback path in `semi_programmatic_sat.py` was
checked directly on full low assignments. With x6=`784:46:0x245521490bd`,
x7=`920:4:0`, cube ranges `150:4,210:39,265:84,362:78`, and
low-Coppersmith threshold 513, the selected cube bits cover all currently
unknown p bits in p[0..512]:

- base known low bits: 308
- selected unknown low bits: 205
- remaining unknown low bits: 0

Two-cube and three-cube semi-programmatic SAT runs completed without stalls.
Every sampled cube had product-prefix status `sat`, low-Coppersmith status
`no_roots`, `hard_clause_eligible=true`, and learned
`low_coppersmith_no_root`:

- 2 cubes: 2 low-Coppersmith calls, 2 hard blocks, 0 product hard blocks,
  0 soft blocks, 0 factors.
- 3 cubes: 3 low-Coppersmith calls, 3 hard blocks, 0 product hard blocks,
  0 soft blocks, 0 factors.

The learned clause scope in the SAT loop is `low_prefix_selected_bits`, with
205 literals. A deterministic replay with x1=`0x2`, full x5
`682:87:0x40c04141804040c140c1`, x6 top, and x7=`0` also produced 4/4
low-Coppersmith hard blocks. Since x1 was fixed outside the low cube, those
clauses had 166 selected low literals over x0+x2+x3. The x7=`0x7` top
high-side branch behaved the same: 2/2 low-Coppersmith hard blocks, no factor.

This confirms the sound low oracle is operational, but the learned clauses are
still exact-assignment exclusions. Product-prefix/Hensel checks are not
providing contradictions on these samples.

The unknown-divisor/TK-LZ preflight track was rechecked. The full eight-variable
model still has a strongly negative HM-style proxy margin:

- active x0..x7: best m=4,t=1, dimension 495, margin about -676 bits.

Projection subsets that keep small x0/x7 can show positive proxy margins:

- active x0,x1,x6,x7: best m=8,t=1, dimension 495, margin about +59 bits.
- active x0,x4,x6,x7: best m=7,t=1, dimension 330, margin about +11 bits.

However, bounded relation/prune checks over x0,x1,x6,x7 and x0,x4,x6,x7
found only projection-derived relations. A four-point m=2/3 prune grid had
best prune score 0, no non-derived relations, no extra modular prune hits, and
no hard-pruning signal. An m=4 ranker for x0,x1,x6,x7 found 48 relation rows,
but the best was again `derived_no_extra_prune`.

The sumset preflight for the current liftT shift family at T=600/784/830 and
shift degrees 1/2 returned `FAIL_EXPANDING` in all rows. This supports skipping
new LLL attempts for that shift family unless the support family changes.

## Batch 20 Follow-Up

`low_coppersmith_clause_minimize.py` was added to test whether sound
low-Coppersmith no-good clauses can be generalized. The script starts from a
fully assigned low prefix, removes one small bit window, exhaustively tries all
values for that window, and marks the window droppable only if every completion
still returns low-Coppersmith `no_roots` with positive theorem margin.

On the all-zero low assignment under x6=`784:46:0x245521490bd`, x7=`920:4:0`,
low bits 513:

- Baseline: `no_roots`, hard-clause eligible, 205 selected low literals.
- Dropping x0 window `150:4`: 16/16 completions returned `no_roots`, no
  factors, clause can shrink from 205 to 201 literals.
- Dropping x2 low window `265:4`: 16/16 completions returned `no_roots`, no
  factors, clause can shrink from 205 to 201 literals.
- Dropping x3 low window `362:4`: 16/16 completions returned `no_roots`, no
  factors, clause can shrink from 205 to 201 literals.

The same x0-window check was repeated with x1 fixed to `0x2`, full x5
`682:87:0x40c04141804040c140c1`, x6 top, and x7=`0`. Baseline was again
`no_roots`; all 16 x0 completions were `no_roots`, so that high-fixed low
clause can shrink from 166 to 162 literals.

This is not yet a large pruning gain, but it gives a sound way to generalize
low-Coppersmith hard clauses beyond exact full-low assignments. Larger windows
need batching or parallel execution because each 4-bit window costs 16 Sage
oracle calls.

## Batch 21 Follow-Up

`low_coppersmith_window_sweep.py` was added as a subprocess-parallel wrapper
around the clause minimizer. It runs one minimizer process per drop window and
summarizes whether each window is soundly droppable.

The wrapper was smoke-tested on an oversized window `210:8`; it preserved the
minimizer's guard and reported `skipped_too_many_completions` for 256
completions when `--max-completions=16`. A wrapper replay of the all-zero
`150:4` drop window returned `droppable_sound_no_root`, 16/16 `no_roots`, no
factors, and remaining literal count 201.

Additional bounded window experiments found the same single-window
generalization pattern:

- All-zero low assignment, x1 windows `210:4` and `214:4`: each had 16/16
  completions return `no_roots`, no factors, and can shrink 205 to 201
  literals.
- High-fixed branch x1=`0x2`, x5=`682:87:0x40c04141804040c140c1`, x6 top,
  x7=`0`, windows `265:4` and `362:4`: each had 16/16 completions return
  `no_roots`, no factors, and can shrink 166 to 162 literals.

The practical bottleneck is runtime. A single 4-bit window through the wrapper
took about 81s in one run, and two high-fixed windows in one command took about
113s. The soundness result is useful, but broader minimization needs either
parallel window sweeps, cached Sage setup, or a cheaper prefilter before
calling Coppersmith for every completion.

## Batch 22 Follow-Up

`semi_programmatic_sat.py` now has bounded low-Coppersmith clause minimization
options:

- `--low-coppersmith-drop-window START:WIDTH`
- `--low-coppersmith-minimize-max-completions N`

When a low-Coppersmith `no_roots` result is hard-clause eligible, the SAT loop
can try to drop selected low literals inside the requested window. It
exhaustively checks every completion of that window, and drops the literals
only if every completion independently returns hard-eligible `no_roots`.
Non-triggered, unavailable, factored, timeout, or other statuses keep the
original literals.

The option was tested directly in the SAT loop on the all-zero full-low cube
under x6=`784:46:0x245521490bd`, x7=`0`:

- Drop `150:2`: 4/4 completions returned `no_roots`; learned clause shrank
  from 205 to 203 literals. The summary reported 5 low-Coppersmith calls
  total: one baseline plus four completions.
- Drop `150:4`: 16/16 completions returned `no_roots`; learned clause shrank
  from 205 to 201 literals. The summary reported 17 low-Coppersmith calls.

The learned clause scope changes to `minimized_low_prefix_selected_bits`, and
the event records the dropped bit indices. No factor was found in these runs.

Separate bounded probes confirmed the same x0 window behavior: `150:2`,
`152:2`, and combined `150:4` were all soundly droppable on the all-zero
branch. This is now wired into the actual learned-clause path, not only a
standalone diagnostic.

## Batch 23 Follow-Up

The multi-window minimization path in `semi_programmatic_sat.py` was tightened
to preserve hard-clause soundness. Earlier single-window checks were sound, but
dropping several windows at once also requires checking all completions of the
union of already dropped bits and the next candidate window. The SAT loop now
uses that union-completion rule.

Two boundary runs on the all-zero full-low cube under x6=`784:46:0x245521490bd`,
x7=`0` verified the behavior:

- Drop windows `150:2`, then `152:2`, with max completions 4:
  - first window: 4/4 `no_roots`, dropped bits 150..151
  - second window: skipped as `skipped_union_too_many_completions`, because
    the union would require 16 completions
  - learned clause stayed at 203 literals
- Same windows with max completions 16:
  - first window: 4/4 `no_roots`
  - second window: union check over bits 150..153, 16/16 `no_roots`
  - learned clause shrank to 201 literals

This keeps minimized low-Coppersmith clauses sound even when multiple drop
windows are requested. The cost is explicit: the second run made 21
low-Coppersmith calls for one SAT cube.

## Batch 24 Follow-Up

`low_coppersmith_greedy_minimize.py` was added as a standalone greedy
minimizer for low-Coppersmith no-good clauses. It uses the same union-completion
discipline as the SAT loop: a new candidate window is accepted only after all
completions of the union of already dropped bits plus that window return
hard-eligible `no_roots`.

On the all-zero low assignment under x6=`784:46:0x245521490bd`, x7=`0`, with
candidate windows `150:2`, `152:2`, and `210:2`, max union completions 16:

- `150:2`: accepted, 4/4 `no_roots`, remaining literals 203.
- `152:2`: accepted after union check over bits 150..153, 16/16 `no_roots`,
  remaining literals 201.
- `210:2`: skipped because the proposed union would require 64 completions.

The greedy run made 21 low-Coppersmith calls and found no factors.

The same union-checked SAT-loop minimization was tested on the high-fixed
branch x1=`0x2`, x5=`682:87:0x40c04141804040c140c1`, x6 top, x7=`0`.
Drop windows `150:2` and `152:2` were both accepted after union checks; the
learned clause shrank from 166 to 162 literals. Product-prefix remained `sat`,
and no factor was found.

Prefix/Hensel checks were also re-run on the all-zero low cube with x6 top and
x7=`0`. For check bits 384, 448, and 512, both BV product-prefix and Hensel
prefix cores returned `sat`; no `unsat` pruning appeared. This keeps the
low-Coppersmith callback as the only currently productive hard-pruning oracle.

## Batch 25 Follow-Up

`sat_cas_batch_runner.py` now passes through minimized low-Coppersmith clause
options:

- `--low-coppersmith-drop-window`
- `--low-coppersmith-minimize-max-completions`

`sat_batch_analyzer.py` now reports minimized low-clause counts and total
dropped literals in addition to the existing hard-block counts.

A bounded two-cube batch was run with x6=`784:46:0x245521490bd`, x7=`0`,
full low cube ranges `150:4,210:39,265:84,362:78`, low bits 513, hard fail
enabled, and drop window `150:2` with max completions 4. Both cubes completed:

- cube 1: x0=`0`, low-Coppersmith `no_roots`, dropped bits 150..151,
  learned clause 203 literals.
- cube 2: x0=`4`, low-Coppersmith `no_roots`, dropped bits 150..151,
  learned clause 203 literals.

The analyzer summary reported 2 cubes, 10 low-Coppersmith calls, 2 hard
blocks, 2 minimized blocks, 4 total dropped literals, and 0 factored events.
Product-prefix stayed `sat` in both cube records.

## Batch 26 Follow-Up

`sat_batch_analyzer.py` now reports the telemetry needed to compare
minimized low-Coppersmith batches without opening each cube record:

- product-prefix and low-Coppersmith status histograms
- learned-clause type, scope, literal-count, and dropped-literal histograms
- low-Coppersmith minimization status/window histograms
- hot dropped-bit counts
- low-Coppersmith cache hits

`semi_programmatic_sat.py` now caches low-Coppersmith reports by low residue
inside a run. This preserves the hard-clause discipline, but avoids rerunning
the same Sage oracle when the original assignment or an earlier union
completion appears again in a later minimization check.

The x6=`784:46:0x245521490bd`, x7=`0`, full-low cube branch was extended:

- Four-cube run with drop window `150:2`, max completions 4:
  - all 4 cubes had product-prefix `sat`
  - all 4 had low-Coppersmith `no_roots`
  - all 4 learned minimized hard clauses with dropped bits 150..151
  - learned-clause length was 203 in every cube
  - 20 low-Coppersmith calls, 8 total dropped literals, 0 factors
- Two-cube union run with drop windows `150:2` and `152:2`, max completions
  16:
  - both windows were `droppable_sound_no_root` in both cubes
  - dropped bits were 150..153
  - learned-clause length was 201 in both cubes
  - before caching this cost 42 low-Coppersmith calls
  - after caching it cost 32 calls plus 10 cache hits, with the same clauses
  - 0 factors

Independent single-window sweeps on two low cubes also found that `210:2`,
`265:2`, and `362:2` are each soundly droppable on their own. Each tested
window had 4/4 completions return hard-eligible `no_roots`, shrinking 205
literals to 203 for that single window. These are not yet union proofs for
dropping several of those windows together.

The high-side x1-aware Coron branch was also rechecked on new bounded
q-prefix candidates. For x0=`0`, x1 in `{0,1}`, and x7 in `{1,2}`, the best
two candidates both had x7=`1`, x5=`682:87:0x40400000404040`, q-known 619
bits, q-low 265 bits, and q-prefix 354 bits at offset 670. The edge Coron
oracle reconstructed 13 polynomials for both x1=`0` and x1=`1`, but found
0 roots and 0 verified factors.

The TK/LZ/sumset side remains negative in bounded checks:

- full 8-variable unknown-divisor preflight best margin stayed about
  `-675.95` bits
- LZ depth probes on `x0,x1,x6,x7` and `x0,x4,x6,x7` produced relation
  counts, including 18 for `x0,x1,x6,x7` at m=3,t=1, but every row was
  `projection_derived_no_extra_prune`
- liftT sumset sweep for T=`600,784,830` and shift degrees `1,2` returned
  `FAIL_EXPANDING` for all 6 rows

Batch 26 therefore strengthens the current conclusion: the productive path is
still the SAT-loop low-Coppersmith hard oracle, especially with sound
minimized clauses. High-side Coron remains useful only as a success verifier,
and the current TK/LZ/sumset families still do not show a viable pruning
signal.

## Batch 27 Follow-Up

`low_coppersmith_greedy_minimize.py` now uses the same low-residue cache as the
SAT loop. This makes greedy union-proof probes report both actual
low-Coppersmith calls and cache hits, while preserving the rule that a window
is dropped only after every completion of the full proposed dropped-bit union
returns hard-eligible `no_roots`.

The all-zero full-low cube under x6=`784:46:0x245521490bd`, x7=`0` now has
two independent 6-bit union-drop proofs:

- Greedy order `150:2`, `152:2`, `210:2`:
  - all three windows were `droppable_sound_no_root`
  - union dropped bits 150..153 and 210..211
  - remaining low-prefix selected literals: 199
  - completion counts were 4, 16, and 64
  - low-Coppersmith calls/cache hits: 64/21
  - 0 factors
- Greedy order `210:2`, `265:2`, `362:2`:
  - all three windows were `droppable_sound_no_root`
  - union dropped bits 210..211, 265..266, and 362..363
  - remaining low-prefix selected literals: 199
  - completion counts were 4, 16, and 64
  - low-Coppersmith calls/cache hits: 64/21
  - 0 factors

The first 6-bit proof was also replayed through the actual SAT-loop learned
clause path. With drop windows `150:2`, `152:2`, and `210:2`, max completions
64, and one cube, the batch completed without timeout:

- product-prefix stayed `sat`
- low-Coppersmith returned hard-eligible `no_roots`
- all three minimization rows were `droppable_sound_no_root`
- the learned hard clause dropped 6 literals and had length 199
- low-Coppersmith calls/cache hits were 64/21
- 0 factored events

This shows that sound clause minimization is not limited to adjacent x0 bits:
small windows inside x1, x2, and x3 can also be union-dropped. The cost grows
with the union width, so 6 dropped bits is currently practical; larger unions
need either better window ordering, more caching across cubes, or parallelized
completion checks.

The high-side x1-aware q-prefix/Coron verifier path was checked on a disjoint
branch from Batch 26. For x0=`0`, x1 in `{2,3}`, and x7 in `{3,4,5}`, the top
two q-prefix candidates both had x7=`5`,
x5=`682:87:0x1c08001c0010040c004`, q-known 620 bits, q-low 265 bits, and
q-prefix 355 bits. The edge Coron oracle reconstructed 13 polynomials for
both x1=`2` and x1=`3`, but again found 0 roots and 0 verified factors.

Weighted LZ and alternate sumset preflights remained negative:

- weighted LZ on `x0,x2,x7` and `x0,x5,x7` completed 12/12 bounded runs, but
  had `lll_relation_count_under_threshold=0` and no integral unscaled
  relations
- alternate sumset families `cuso8` and `liftT_proxy` produced 24 non-viable
  rows: 22 `FAIL_EXPANDING` and 2 `FAIL_CAP`
- unknown-divisor preflight on `x0,x2,x5,x7` improved relative to full 8-var,
  but the best margin was still negative at about `-67.646` bits

The main actionable result from Batch 27 is therefore a stronger SAT+CAS
low-oracle clause-minimization path: verified 199-literal hard clauses are
available for at least two different 6-bit dropped unions on the all-zero low
cube. The other branches did not produce factor recovery or a new viable
lattice family.

## Batch 28 Follow-Up

`low_coppersmith_union_order_sweep.py` was added as a subprocess-parallel
wrapper around the greedy minimizer. It compares several candidate-window
orders while preserving the same soundness condition: a window is accepted only
after every completion of the full proposed dropped-bit union returns
hard-eligible `no_roots`.

The wrapper was smoke-tested on the two-window orders `150:2,152:2` and
`152:2,150:2`. Both orders dropped 4 literals, left 201 literals, made 16
actual low-Coppersmith calls, had 5 cache hits, and found 0 factors.

A bounded 6-order sweep then compared 3-window orders from the known
single-window candidates `150:2`, `152:2`, `210:2`, `265:2`, and `362:2` on
the all-zero full-low cube under x6=`784:46:0x245521490bd`, x7=`0`. All 6
orders completed without timeout and all reached 6 dropped literals:

- `150:2,152:2,210:2`
- `150:2,152:2,265:2`
- `150:2,152:2,362:2`
- `150:2,210:2,152:2`
- `150:2,210:2,265:2`
- `150:2,210:2,362:2`

Every row had all three windows marked `droppable_sound_no_root`, remaining
literal count 199, low-Coppersmith calls/cache hits 64/21, and 0 factors. The
wall time differed by order and scheduler contention, but the oracle work was
identical. This adds three new 6-bit union proofs beyond the two Batch 27
examples and makes order comparison reproducible.

The high-side x1-aware q-prefix/Coron verifier path was checked on another
disjoint branch. A sweep over x1 in `{4,5,6,7}` and x7 in `{6,7,8,9,10}`
covered 320 branches and 640 merged candidates. The top two had x7=`7`,
x5=`682:87:0x8080404041804002`, q-known 620 bits, q-low 265 bits, and
q-prefix 355 bits. Coron verification with both `base` and `x2` profiles
reconstructed 13 polynomials per profile, but found 0 roots and 0 verified
factors for x1=`4` and x1=`5`.

The TK/LZ side found one near-threshold but still negative preflight:

- unknown-divisor preflight on `x0,x1,x5,x7` had best margin about `-4.068`
  bits at m=7,t=1,dimension=330
- weighted LZ on `x0,x1,x7` and `x0,x6,x7` produced no LLL relation under the
  threshold and no integral unscaled relations
- LZ pruning on `x0,x1,x7`, m=2, samples 2 produced one relation, but it was
  projection-derived with prune score 0
- `linear8` sumset preflight remained `FAIL_EXPANDING` with growth ratio 3.0

Batch 28 therefore expands the SAT+CAS low-oracle evidence: 6-bit minimized
hard clauses are not isolated accidents of one order. The closest lattice
preflight so far is `x0,x1,x5,x7` at roughly -4 bits, which is worth tracking,
but it is still not a positive-margin attack.

## Batch 29 Follow-Up

The low-Coppersmith union proof was pushed from 6 dropped bits to 8 dropped
bits on the all-zero full-low cube under x6=`784:46:0x245521490bd`, x7=`0`.
The greedy order was `150:2`, `152:2`, `210:2`, and `265:2`, with max union
completions 256.

All four windows were `droppable_sound_no_root`:

- `150:2`: 4/4 completions hard-eligible `no_roots`
- `152:2`: 16/16 completions hard-eligible `no_roots`
- `210:2`: 64/64 completions hard-eligible `no_roots`
- `265:2`: 256/256 completions hard-eligible `no_roots`

The union dropped bits 150..153, 210..211, and 265..266. The remaining
low-prefix selected literal count is now 197 instead of 205. The run made 256
actual low-Coppersmith calls, had 85 cache hits, took about 566.5 seconds, and
found 0 factors. This gives a sound 197-literal low-Coppersmith no-good for
the all-zero branch, though the cost is high enough that 8-bit drops should be
used selectively unless completion checks are parallelized or cached across
branches.

The high-side q-prefix/Coron verifier path was checked on a new disjoint
range: x0=`0`, x1 in `{8..15}`, and x7 in `{11..15}`. The sweep covered 40
branches and 40 merged candidates. The top two candidates were x1=`8` and
x1=`9`, both with x7=`12`,
x5=`682:87:0x40400000004000c04002`, q-known 620 bits, q-low 265 bits, and
q-prefix 355 bits. Coron verification with both `base` and `x2` profiles
again reconstructed 13 polynomials per profile but found 0 roots and 0
verified factors.

The near-threshold LZ branch was also extended:

- unknown-divisor preflight on `x0,x1,x5,x7`, expanded through
  m<=9,t<=4,max-weight=160, stayed at the same best margin:
  about `-4.068` bits at m=7,t=1,dimension=330
- weighted LZ on `x0,x1,x5` with budget 90 produced one relation under the
  threshold at first norm 1024 bits, while budget 50 did not
- weighted `x0,x1,x5,x7` was full-rank but exceeded the LLL dimension cap
- LZ pruning on `x0,x1,x5,x7` and `x0,x1,x5` remained projection-derived
  with prune score 0 and no extra modular prune signal

Batch 29 therefore gives the strongest sound low-oracle minimization so far:
an 8-bit dropped union and a 197-literal hard clause candidate. The other
branches still do not recover a factor, but `x0,x1,x5` now has a weak
weighted-LZ relation signal that is worth auditing separately for whether it
can be made non-projection-derived.

## Batch 30 Follow-Up

The Batch 29 8-bit greedy low-Coppersmith proof was replayed through the
actual SAT-loop learned-clause path. The runner used the all-zero full-low
cube with x6=`784:46:0x245521490bd`, x7=`0`, low bits 513, hard fail enabled,
and drop windows `150:2`, `152:2`, `210:2`, and `265:2`, max completions 256.

The one-cube SAT run completed without timeout:

- product-prefix stayed `sat`
- low-Coppersmith returned hard-eligible `no_roots`
- all four minimization rows were `droppable_sound_no_root`
- dropped bits were 150..153, 210..211, and 265..266
- learned hard-clause length was 197
- low-Coppersmith calls/cache hits were 256/85
- 0 factored events

This confirms that the 8-bit union proof is not only a standalone greedy
diagnostic. It is wired into the actual learned no-good clause path and can
produce a sound 197-literal hard clause for that SAT cube.

The weak `x0,x1,x5` weighted-LZ relation from Batch 29 was audited further.
Budgets 80, 90, and 100 were checked at m=2,t=1:

- budget 80: no relation, first norm 2048 bits
- budget 90: one relation, first norm 1024 bits
- budget 100: one relation, first norm 1024 bits

The relation is a 4-term linear relation with constant, x0, x1, and x5 terms.
Its coefficient bit sizes were about 1024, 151, 211, and 683 bits. Relation
evaluation and pruning still classify it as projection-derived:

- category `linear_other`, max degree 1, term count 4
- `identically_derived_mod_projection=true`
- `integer_multiple_of_projection=false`
- no modular prune sample hits and no integer-zero sample hits
- `prune_score=0`
- `nonderived_relation_count=0`
- `nonderived_prune_signal_count=0`

So the relation is repeatable at budgets 90/100, but it is not currently a
useful non-projection-derived pruning relation.

## Batch 31 Follow-Up

`low_coppersmith_multicube_window_sweep.py` was added to compare
single-window low-Coppersmith drops across several selected low cubes. It
builds each low assignment from a base selected prefix plus one or more
variant ranges, then reuses `low_coppersmith_window_sweep.py` for the actual
soundness checks.

The wrapper was smoke-tested on x0=`0` and x0=`4` with windows `150:2` and
`210:2`; both windows were soundly droppable on both variants.

The main Batch 31 run checked x0 values `0,4,8,12` under the same high branch
x6=`784:46:0x245521490bd`, x7=`0`, with the full-low base assignment:

- `150:2`: 4/4 variants droppable, each with 4/4 `no_roots` completions
- `152:2`: 4/4 variants droppable, each with 4/4 `no_roots` completions
- `210:2`: 4/4 variants droppable, each with 4/4 `no_roots` completions
- `265:2`: 4/4 variants droppable, each with 4/4 `no_roots` completions
- `362:2`: 4/4 variants droppable, each with 4/4 `no_roots` completions

All 20 tested variant/window pairs completed without timeout and found 0
factors. This is useful operationally: these five 2-bit windows are not only
isolated all-zero artifacts. They are stable single-window drop candidates
across the first x0 variants tested, so they are reasonable default
minimization windows before attempting expensive larger unions.

The high-side q-prefix/Coron verifier path was checked with nonzero x0 values.
The sweep used x0 in `{1,2,3,4}`, x1 in `{0,2,8,9}`, and x7 in `{7,12}`. The
top two candidates had x0=`1`, x7=`7`,
x5=`682:87:0x8080404041804002`, q-known 620 bits, q-low 265 bits, and
q-prefix 355 bits. Coron verification with `base` and `x2` profiles
reconstructed 13 polynomials per profile for both x1=`0` and x1=`2`, but
found 0 roots and 0 verified factors.

The LZ side found a more interesting preflight candidate:

- `x0,x1,x4,x7` has positive preflight margin about `+21.7103` bits at
  m=8,t=1,dimension=495
- weighted LZ on that subset had no relation at budget 60, but one 5-term
  linear relation at budget 70 with first norm 1024 bits
- larger budgets 80/90/100 had columns 304/398/544 and were skipped under the
  small LLL cap used in this bounded probe
- `x0,x1,x5,x6` remained negative-margin at about `-63.4079`, though it
  showed one projection-style relation at budgets 90/100
- 3-variable prune grid over related projections had relation counts, including
  up to 15 for `x0,x1,x4` at m=3, but all were projection-derived with prune
  score 0 and no extra modular prune signal

Batch 31 therefore gives two follow-ups: for SAT+CAS, the known 2-bit
low-Coppersmith minimization windows look repeatable across several x0 cubes;
for lattice work, `x0,x1,x4,x7` is now the most promising unknown-divisor
preflight subset, although it still needs a non-projection relation before it
can prune.

## Batch 32 Follow-Up

`low_coppersmith_multicube_greedy_minimize.py` was added to move from
single-window multi-cube checks to union-checked multi-cube minimization. It
uses the same hard rule as the one-cube greedy minimizer: a candidate window is
accepted only if every completion of the already dropped bits plus the new
window returns hard-eligible `no_roots`. The difference is that the condition
must hold across every supplied variant cube.

A smoke run over x0 variants `0` and `4` accepted both x0 windows `150:2` and
`152:2`. It dropped bits 150..153 across both variants, leaving 201 common
selected literals. Cache reuse was visible: 40 total completion checks reduced
to 16 low-Coppersmith calls with 26 cache hits.

The main Batch 32 run checked x0 variants `0,4,8,12` under the same high
branch x6=`784:46:0x245521490bd`, x7=`0`, and the full-low base assignment.
The candidate order was `150:2`, `152:2`, `210:2`, `265:2`, `362:2`, with a
per-variant union completion cap of 256.

The first four windows were accepted across all four variants:

- `150:2`: 16/16 total completions returned hard-eligible `no_roots`
- `152:2`: 64/64 total completions returned hard-eligible `no_roots`
- `210:2`: 256/256 total completions returned hard-eligible `no_roots`
- `265:2`: 1024/1024 total completions returned hard-eligible `no_roots`
- `362:2`: skipped because it would require 1024 completions per variant

The accepted union dropped bits 150..153, 210..211, and 265..266 across all
four x0 variants. This leaves a 197-literal common no-good clause shape, not
just a one-cube artifact. The run made 256 distinct low-Coppersmith calls and
had 1108 cache hits, so once the dropped bits include the variant x0 bits the
four variants collapse heavily onto the same low-residue checks. No factor was
found.

The high-side q-prefix/Coron side was extended to more nonzero x0/x7 branches.
Two q-prefix sweeps checked 120 branches total and found top candidates with
the same ceiling as before: q-prefix 355 bits, q-known 620 bits, q-low 265
bits, width 669. Seven top candidates were then sent to the `base,x2` Coron
profiles. Each candidate reconstructed 26 polynomials total, so 182
polynomials were reconstructed overall, but there were 0 roots and 0 verified
factors. This keeps the high-side folded Coron path in verifier-only status.

The `x0,x1,x4,x7` unknown-divisor lead was also audited with modestly larger
caps. Preflight still reports a positive margin, about `+21.7103` bits at
m=8,t=1,dimension=495. Weighted LZ with budgets 80, 90, and 100 produced 13,
25, and 33 short rows under the threshold, respectively, but the leading
relation stayed the same 5-term linear baseline form over const, x7, x0, x1,
and x4. Direct evaluation at m=3 and m=4 found 35 and 70 candidate rows, but
all were projection-derived. A row-index scan over 105 rows reported
`nonderived_count=0`, `prune_hit_count=0`, and no timeouts. No factor was
found, so the positive preflight margin appears misleading for this subset
unless a different basis/shift family can produce a non-projection relation.

## Batch 33 Follow-Up

The multi-cube greedy minimizer was run once more with an alternative fourth
window order: `150:2`, `152:2`, `210:2`, `362:2`. The setup stayed the same as
Batch 32: x0 variants `0,4,8,12`, high branch
x6=`784:46:0x245521490bd`, x7=`0`, low-bits 513, and a per-variant union cap
of 256.

This alternative also accepted all four windows across every x0 variant:

- `150:2`: 16/16 total completions returned hard-eligible `no_roots`
- `152:2`: 64/64 total completions returned hard-eligible `no_roots`
- `210:2`: 256/256 total completions returned hard-eligible `no_roots`
- `362:2`: 1024/1024 total completions returned hard-eligible `no_roots`

The accepted union dropped bits 150..153, 210..211, and 362..363, again
leaving 197 common selected literals. The run made 256 distinct
low-Coppersmith calls and had 1108 cache hits, matching the Batch 32 call
profile. No factor was found. This means the 8-bit cross-variant hard
no-good minimization is not unique to the `265:2` fourth window; at least
`265:2` and `362:2` are stable fourth-window options after the shared
x0/x1-prefix drops.

The Sumset/lift-T preflight direction was revisited separately. `liftT_actual`
over T=`600,608,784,830`, degrees 0..5, and caps up to 100000 produced 0
PASS rows. The best non-capped actual row was T=600, degree=5 with growth
about `3.189853`, i.e. margin about `-0.939853` against the 2.25 cutoff, and
it was still `FAIL_DIM`. Concrete metric rows using the known T=600 support
size G_terms=31 got closest only under the optimistic `G_deg=2` assumption:
T=600, degree=5 had growth about `2.527778`, margin about `-0.277778`, and
status `FAIL_EXPANDING`. T=784 stayed worse.

The proxy/cuso checks also produced 0 actionable PASS rows. `cuso8` can show
an apparent positive margin at degree 5, growth about `2.142857`, but that row
is `FAIL_DIM` with shifted support size 3003. A synthetic sensitivity scan
showed PASS only when `G_terms` is reduced to 4 or 6 for T=600, which is far
from the actual-ish support sizes already seen, such as 31 for T=600 and 82
for T=784. So the current Sumset evidence does not justify another real
lattice reduction unless a new derivation drastically reduces effective
support.

## Batch 34 Follow-Up

`low_coppersmith_multicube_union_check.py` was added as a fixed-union checker
for the SAT+CAS low-Coppersmith path. Unlike the greedy minimizer, it takes a
complete set of drop windows and verifies that exact union. It deduplicates
completion cases across variants before calling the Sage low-Coppersmith
oracle, then runs those unique oracle cases in parallel.

A 4-bit smoke run over x0 variants `0,4,8,12` and windows `150:2,152:2`
confirmed the expected deduplication: 64 total completion checks collapsed to
16 unique oracle cases, all hard-eligible `no_roots`.

The main run checked the full 10-bit union:

- x0 variants: `0,4,8,12`
- high branch: x6=`784:46:0x245521490bd`, x7=`0`
- windows: `150:2`, `152:2`, `210:2`, `265:2`, `362:2`
- low-Coppersmith trigger: 513 low bits
- jobs: 4

Result:

- 4096/4096 total completions returned hard-eligible `no_roots`
- these collapsed to 1024 unique low-Coppersmith oracle cases
- dropped bits: 150..153, 210..211, 265..266, 362..363
- remaining common selected literals: 195
- roots returned: 0
- factor count: 0

This is the strongest SAT+CAS clause-minimization result so far: the
cross-variant hard no-good is now soundly reduced by 10 literals rather than
8. The next low-Coppersmith extension is 12 bits, but it will require 4096
unique oracle cases for the current variant set, so a sharded/resumable runner
is preferable before pushing it much further.

The union checker was then extended with `--completion-start` and
`--completion-count` so larger unions can be verified in shards. A 12-bit
candidate was tested by adding window `267:2` to the 10-bit union:
`150:2`, `152:2`, `210:2`, `265:2`, `267:2`, `362:2`.

The 12-bit proof was completed in four shards over completion ranges
0..1023, 1024..2047, 2048..3071, and 3072..4095. Each shard collapsed 4096
total checks to 1024 unique oracle cases, and every unique case returned
hard-eligible `no_roots`.

Aggregated result:

- 16384/16384 total completion checks returned hard-eligible `no_roots`
- 4096 unique low-Coppersmith oracle cases were checked across the shards
- dropped bits: 150..153, 210..211, 265..268, 362..363
- remaining common selected literals: 193
- roots returned: 0
- factor count: 0

So the current cross-variant low-Coppersmith no-good can be soundly reduced by
12 literals for x0 variants `0,4,8,12`. This is now a strong enough clause
shape to feed back into the semi-programmatic SAT loop; further 14-bit
extension is possible but will need either more shards or stronger caching.

The q-prefix/dynamic-q path was revisited in parallel. Full x0/x7 sweeps for
x1 in 4..7 and a beam-4 sample over x1 in `{0,5,10,15}` both stayed capped at
q-prefix 355, q-known 620, q-low 265. The tied top group under the current
x5/x1 branch had 48 candidates with the same 355/620/265 score. Dynamically
assigning more x2 low bits mechanically raised q-low and q-known, for example
p[265..280] gave q-low 281 and q-known 636, and p[265..296] gave q-low 297
and q-known 652, but the high-prefix ceiling remained 355 and product-prefix
checks at 320 bits stayed `unknown` without learned clauses or factors.

The unknown-divisor LZ alternative-subset search checked 52 four-variable
subsets containing x0 or x7, excluding already fully audited leads. Only two
positive-margin alternatives appeared:

- `x0,x1,x3,x7`: margin about `+8.6471` bits at m=7,t=1,dim=330
- `x0,x1,x2,x7`: margin about `+0.1700` bits at m=7,t=1,dim=330

Weighted LZ at budget 110 produced short rows for both subsets, but prune
grid and selected m=3/m=4 relation evaluation found no non-projection-derived
relations and no prune signal. No factor was found. This makes the current
LZ evidence consistent across several positive-margin subsets: short rows
exist, but they have not yet escaped projection-derived consequences.

## Batch 35 Follow-Up

The 12-bit low-Coppersmith union proof from Batch 34 was fed back into the
semi-programmatic SAT loop. `semi_programmatic_sat.py` now accepts
`--low-coppersmith-preverified-drop-window` for externally proved no-root
unions, and `--low-coppersmith-preverified-guard-p-range` to keep those
preverified drops sound. The guard ranges must already be fixed in the current
cube and must match the proof's kept-bit assignment before the preverified
drops are applied.

For the Batch 34 12-bit proof, the preverified drop windows are:

- `150:2`, `152:2`
- `210:2`
- `265:2`, `267:2`
- `362:2`

The proof guard used for the all-zero kept low cube is:

- `212:37:0`
- `269:80:0`
- `364:76:0`

A direct 2-cube SAT replay used cube ranges `150:4,210:39,265:84,362:78`,
fixed high branch x6=`784:46:0x245521490bd`, x7=`0`, and low-Coppersmith
bits 513. The first cube matched the guard and learned a 193-literal hard
clause:

- learned clause: `low_coppersmith_no_root`
- dropped literals: 12
- dropped bits: 150..153, 210..211, 265..268, 362..363
- product-prefix status: `sat`
- low-Coppersmith status: `no_roots`
- factor count: 0

The second cube changed x1 to value 4, so the guard did not match. It still
learned a sound low-Coppersmith hard clause, but without preverified
minimization:

- learned clause literal count: 205
- dropped literals: 0
- guard matched: false

This confirms that the Batch 34 proof is now usable inside the SAT loop while
remaining scoped to the exact proved kept-bit family. `sat_cas_batch_runner.py`
was also updated to pass the preverified drop and guard options through; a
1-cube runner smoke reproduced the 193-literal learned clause with one
completed run and no timeout.

The high-side Coron verifier was also checked on six additional top-tie
q-prefix candidates, including x7 values `0`, `5`, `7`, and `a`, and x5
ranges `682:87:0x8080404041804002` and
`682:87:0x820181c20002018148`. All candidates ran both `base` and `x2`
profiles successfully. Each candidate reconstructed 26 polynomials, for 156
total reconstructed polynomials, but again produced 0 roots and 0 verified
factors.

The next 14-bit low-Coppersmith extension was sampled in parallel. Starting
from the proved 12-bit union, first shards were checked for four extra
2-bit windows:

- `269:2`
- `271:2`
- `364:2`
- `212:2`

All four first shards returned hard-eligible `no_roots` with 0 roots/factors.
The best candidate is `269:2`, because it extends the already dropped x2 edge
from 265..268 to 265..270. It was pushed further than the others:

- `269:2`: 1536 completions per variant checked, 6144 total checks, 1536
  unique oracle cases, all hard-eligible `no_roots`
- `271:2`, `364:2`, `212:2`: 256 completions per variant checked each, all
  hard-eligible `no_roots`

No 14-bit candidate failed in the sampled shards and no factor was found.
This does not yet prove a 14-bit no-good, but it identifies `269:2` as the
next best shard target.

## Batch 36 Follow-Up

`low_coppersmith_union_shard_analyzer.py` was added to aggregate fixed-union
checker shard JSON outputs. It reports merged coverage ranges, missing
completion ranges, no-root status, factor counts, and total unique oracle
cases. This is useful for the 14-bit candidate because the full completion
space is 16384 values per variant.

The analyzer confirmed the initial `269:2` coverage:

- covered ranges: 0..1279 and 8192..8447
- covered completions per variant: 1536/16384
- coverage fraction: 9.375%
- all checked shards: hard-eligible `no_roots`
- roots/factors: 0

Additional 14-bit `269:2` sub-shards were checked. Large 1024-size shards
around 1280/4096/8448 were unstable in this session and produced zero-byte
JSON outputs, so they are not counted as evidence. Smaller 64-size sub-shards
were stable:

- 4096..4159: 64 unique oracle cases, all hard-eligible `no_roots`
- 12288..12351: 64 unique oracle cases, all hard-eligible `no_roots`
- 14336..14399: 64 unique oracle cases, all hard-eligible `no_roots`

Updated aggregate for 14-bit candidate `269:2`:

- covered ranges: 0..1279, 4096..4159, 8192..8447, 12288..12351, 14336..14399
- covered completions per variant: 1728/16384
- coverage fraction: 10.546875%
- total checked completion cases across variants: 6912
- unique oracle cases total: 1728
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The unchecked ranges are still large:

- 1280..4095
- 4160..8191
- 8448..12287
- 12352..14335
- 14400..16383

So `269:2` remains the best 14-bit candidate, but full proof will require many
more smaller shards or a more robust long-shard runner. The zero-byte shard
attempts are treated as infrastructure/runtime failures, not mathematical
counterexamples.

## Batch 37 Follow-Up

`low_coppersmith_union_shard_batch.py` was added as a small-shard wrapper around
`low_coppersmith_multicube_union_check.py`. It writes one JSON file per shard,
keeps a JSONL progress log, supports `--resume`, and now records timeout rows
instead of crashing on `subprocess.TimeoutExpired`. This is meant for the
14-bit low-Coppersmith union checks where 1024-size shards were unstable but
64-size shards usually completed.

`low_coppersmith_union_shard_analyzer.py` was also tightened to report both
checked and covered completion counts. This avoids over-counting when an
overlap shard exists, such as the one-value `12288:1` smoke file.

The 14-bit `269:2` candidate was extended again. The successful counted shards
now cover these completion ranges per variant:

- 0..1407
- 4096..4159
- 8192..8447
- 12288..12351
- 14336..14463
- 14592..14655
- 14720..14783
- 14848..14975

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 2176/16384
- coverage fraction: 13.28125%
- total checked completion cases across variants: 8704
- unique oracle cases total: 2176
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The successful local additions were 1280..1343 and 1344..1407. Attempts around
1408 and several high-side gaps still produced zero-byte outputs, so they are
not counted as oracle evidence.

A secondary 14-bit candidate, `212:2`, was checked on scattered 64-size shards.
Its aggregate coverage is still much weaker:

- covered completions per variant: 512/16384
- coverage fraction: 3.125%
- total checked completion cases across variants: 2048
- unique oracle cases total: 512
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

So `269:2` remains the best 14-bit extension target. Full proof is still
incomplete, but the current result expands the sound low-Coppersmith no-root
evidence without changing the SAT/CAS semantics.

## Batch 38 Follow-Up

Two parallel workers extended the `269:2` 14-bit candidate with additional
64-size shards. Running several shards concurrently again produced some
zero-byte first attempts, but rerunning the exact shard commands sequentially
completed cleanly. The final counted shard stderr files were all empty.

New successful ranges:

- 1536..1791
- 2048..2303

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 2688/16384
- coverage fraction: 16.40625%
- total checked completion cases across variants: 10752
- unique oracle cases total: 2688
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The current covered ranges are:

- 0..1407
- 1536..1791
- 2048..2303
- 4096..4159
- 8192..8447
- 12288..12351
- 14336..14463
- 14592..14655
- 14720..14783
- 14848..14975

This still does not prove the full 14-bit no-good, but it pushes the best
candidate to just over one sixth of the completion space. The recurring
zero-byte behavior appears to be a parallel Sage/runtime stability issue; only
nonzero JSON outputs with `all_completions_no_roots=true` are counted.

## Batch 39 Follow-Up

The low-side gaps for `269:2` were targeted with sequential 64-size shards.
Five of six requested shards completed with empty stderr and hard-eligible
`no_roots`:

- 1408..1471
- 1472..1535
- 1792..1855
- 1920..1983
- 1984..2047

The missing shard 1856..1919 failed twice with zero-byte stdout/stderr and is
not counted as evidence.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 3008/16384
- coverage fraction: 18.359375%
- total checked completion cases across variants: 12032
- unique oracle cases total: 3008
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The current low-side coverage is almost contiguous: 0..1855 and 1920..2303 are
proved, with only 1856..1919 missing before the 2304..4095 gap.

## Batch 40 Follow-Up

The previously missing 1856..1919 shard was rerun locally with lower parallelism
(`jobs=2`). It completed in 71.006 seconds with empty stderr:

- all completions: hard-eligible `no_roots`
- unique oracle cases: 64
- roots/factors: 0

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 3072/16384
- coverage fraction: 18.75%
- total checked completion cases across variants: 12288
- unique oracle cases total: 3072
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The low-side coverage is now contiguous for 0..2303. The next contiguous gap is
2304..4095; scattered later ranges remain as before.

## Batch 41 Follow-Up

The next gap, 2304..4095, was split across three workers plus one local shard
runner. All runs used 64-size shards with lower parallelism (`jobs=2`, with one
`jobs=1` retry on failure). This reduced but did not eliminate zero-byte
runtime failures.

Successful new ranges:

- 2304..2367
- 2432..2495
- 2624..2815
- 3008..3071
- 3136..3263
- 3328..3391
- 3456..3519
- 3584..3711

Zero-byte or signal-failed attempts, not counted as evidence:

- 2368..2431
- 2496..2623
- 2816..3007
- 3072..3135
- 3264..3327
- 3392..3455
- 3520..3583
- 3712..4095

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 3840/16384
- coverage fraction: 23.4375%
- total checked completion cases across variants: 15360
- unique oracle cases total: 3840
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix improved only to 0..2367 because 2368..2431 failed, but
several later pieces of the 2304..4095 gap were filled. The failure mode is
still execution instability rather than a mathematical counterexample: all
nonzero JSON outputs in this batch were `all_completions_no_roots=true`.

## Batch 42 Follow-Up

The most brittle `269:2` gaps were retried with 32-size shards and `jobs=1`.
This was materially more stable than 64-size retrying. The following previously
failed ranges were filled:

- 2368..2431
- 2496..2623
- 2816..3007

Some first attempts still produced empty output, but every requested 32-size
retry in these ranges eventually completed with empty stderr and
hard-eligible `no_roots`.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 4224/16384
- coverage fraction: 25.78125%
- total checked completion cases across variants: 16896
- unique oracle cases total: 4224
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..3071. Remaining early gaps are 3072..3135,
3264..3327, 3392..3455, 3520..3583, and 3712..4095.

The Hensel-tail direction was also rechecked with four short full-tail
shortlist probes. All returned `UNKNOWN` with no factor, but activity still
ranked `x6=0x245521490bd`, `x1low16=0x66ff`, `T=800`,
`decision-select=min` highest:

- probe 1: `T=800`, `x1low16=0x66ff`, select min,
  branches/sec 1739.90, conflicts/sec 1316.69
- probe 2: same but select max, conflicts/sec 624.45
- probe 3: `T=784`, `x1low16=0x77ff`, conflicts/sec 605.25
- probe 4: `x6=0x24552149098`, `x1low16=0xffff`, `T=784`,
  conflicts/sec 953.03

So the current Hensel-tail shortlist remains active but not decisive; it is
still a ranking signal, not a proof or verifier.

## Batch 43 Follow-Up

The remaining early `269:2` gaps were retried with 32-size `jobs=1` shards.
Most completed successfully. New filled ranges:

- 3072..3135
- 3264..3327
- 3392..3423
- 3520..3583
- 3712..3775
- 3840..3967
- 4000..4063

Still failing with zero-byte output after retry:

- 3424..3455
- 3776..3839
- 3968..3999
- 4064..4095

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 4704/16384
- coverage fraction: 28.7109375%
- total checked completion cases across variants: 18816
- unique oracle cases total: 4704
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..3423. The next local target is the stubborn
3424..3455 shard; after that, the remaining early gaps are 3776..3839,
3968..3999, and 4064..4095.

## Batch 44 Follow-Up

The stubborn `269:2` shard 3424..3455 was retried locally as a single 32-size
`jobs=1` run. This time it completed with empty stderr and hard-eligible
`no_roots`.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 4736/16384
- coverage fraction: 28.90625%
- total checked completion cases across variants: 18944
- unique oracle cases total: 4736
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..3775. The remaining early gaps are
3776..3839, 3968..3999, and 4064..4095; these are being split into 16-size
low-parallelism shards because the earlier 32-size attempts were brittle.

## Batch 45 Follow-Up

The remaining early `269:2` gaps were split into 16-size `jobs=1` shards:

- 3776..3839
- 3968..3999
- 4064..4095

All eight 16-size shards completed with empty stderr, hard-eligible
`no_roots`, and no roots or factors. No retry was needed.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 4864/16384
- coverage fraction: 29.6875%
- total checked completion cases across variants: 19456
- unique oracle cases total: 4864
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..4159. The next large unchecked gap is
4160..8191; later counted islands remain at 8192..8447, 12288..12351,
14336..14463, 14592..14655, 14720..14783, and 14848..14975.

## Batch 46 Follow-Up

The next `269:2` range 4160..4671 was split across four workers as 32-size
`jobs=1` shards, with one local retry at 4672..4703. Execution stability
regressed on the earliest part of the gap.

Successful new ranges:

- 4416..4511
- 4544..4671

Failed with zero-byte output after retry, not counted as evidence:

- 4160..4415
- 4512..4543
- 4672..4703

For 4544..4575, the direct 32-size shard failed once, but two 16-size
sub-shards completed and were combined into the same summary schema before
aggregation. The combined file was accepted by the analyzer and had
hard-eligible `no_roots`.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 5088/16384
- coverage fraction: 31.0546875%
- total checked completion cases across variants: 20352
- unique oracle cases total: 5088
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix remains 0..4159 because 4160..4415 did not produce
parseable evidence. Counted islands now include 4416..4511 and 4544..4671 in
addition to the previous high-side islands.

## Batch 47 Follow-Up

The failed 4160..4415 region was retried as 16-size `jobs=1` shards, split
across four workers. Unlike the earlier 32-size attempt, all sixteen 16-size
shards completed with empty stderr and hard-eligible `no_roots`. No 8-size
fallback was needed.

Successful new ranges:

- 4160..4223
- 4224..4287
- 4288..4351
- 4352..4415

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 5344/16384
- coverage fraction: 32.6171875%
- total checked completion cases across variants: 21376
- unique oracle cases total: 5344
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..4511. The next gap is only 4512..4543; if that
fills, the existing 4544..4671 island becomes part of the prefix.

## Batch 48 Follow-Up

The remaining 4512..4543 gap was retried locally as two 16-size `jobs=1`
shards. Both completed with empty stderr, hard-eligible `no_roots`, and no roots
or factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 5376/16384
- coverage fraction: 32.8125%
- total checked completion cases across variants: 21504
- unique oracle cases total: 5376
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..4671. The next unchecked prefix gap is
4672..8191.

## Batch 49 Follow-Up

The next prefix segment 4672..4927 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 4672..4735
- 4736..4799
- 4800..4863
- 4864..4927

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 5632/16384
- coverage fraction: 34.375%
- total checked completion cases across variants: 22528
- unique oracle cases total: 5632
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..4927. The next unchecked prefix gap is
4928..8191.

## Batch 50 Follow-Up

The next prefix segment 4928..5183 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 4928..4991
- 4992..5055
- 5056..5119
- 5120..5183

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 5888/16384
- coverage fraction: 35.9375%
- total checked completion cases across variants: 23552
- unique oracle cases total: 5888
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..5183. The next unchecked prefix gap is
5184..8191.

## Batch 51 Follow-Up

The next prefix segment 5184..5439 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 5184..5247
- 5248..5311
- 5312..5375
- 5376..5439

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 6144/16384
- coverage fraction: 37.5%
- total checked completion cases across variants: 24576
- unique oracle cases total: 6144
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..5439. The next unchecked prefix gap is
5440..8191.

## Batch 52 Follow-Up

The next prefix segment 5440..5695 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 5440..5503
- 5504..5567
- 5568..5631
- 5632..5695

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 6400/16384
- coverage fraction: 39.0625%
- total checked completion cases across variants: 25600
- unique oracle cases total: 6400
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..5695. The next unchecked prefix gap is
5696..8191.

## Batch 53 Follow-Up

The next prefix segment 5696..5951 was split into sixteen 16-size `jobs=1`
shards across four workers. Several first attempts produced zero-byte output,
but each requested 16-size retry completed with empty stderr, hard-eligible
`no_roots`, and no roots or factors.

Successful new ranges:

- 5696..5759
- 5760..5823
- 5824..5887
- 5888..5951

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 6656/16384
- coverage fraction: 40.625%
- total checked completion cases across variants: 26624
- unique oracle cases total: 6656
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..5951. The next unchecked prefix gap is
5952..8191.

## Batch 54 Follow-Up

The next prefix segment 5952..6207 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 5952..6015
- 6016..6079
- 6080..6143
- 6144..6207

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 6912/16384
- coverage fraction: 42.1875%
- total checked completion cases across variants: 27648
- unique oracle cases total: 6912
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..6207. The next unchecked prefix gap is
6208..8191.

## Batch 55 Follow-Up

The next prefix segment 6208..6463 was split into sixteen 16-size `jobs=1`
shards across four workers. All shards completed with empty stderr,
hard-eligible `no_roots`, and no roots or factors. No retry was needed.

Successful new ranges:

- 6208..6271
- 6272..6335
- 6336..6399
- 6400..6463

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 7168/16384
- coverage fraction: 43.75%
- total checked completion cases across variants: 28672
- unique oracle cases total: 7168
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..6463. The next unchecked prefix gap is
6464..8191.

## Batch 56 Follow-Up

The next prefix segment 6464..6719 was split into sixteen 16-size `jobs=1`
shards across four workers. Some first attempts produced zero-byte output, but
each requested retry completed with empty stderr, hard-eligible `no_roots`, and
no roots or factors.

Successful new ranges:

- 6464..6527
- 6528..6591
- 6592..6655
- 6656..6719

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 7424/16384
- coverage fraction: 45.3125%
- total checked completion cases across variants: 29696
- unique oracle cases total: 7424
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The contiguous prefix is now 0..6719. The next unchecked prefix gap is
6720..8191.

## Batch 57-62 Follow-Up

The remaining contiguous prefix gap 6720..8191 for the 14-bit `269:2`
candidate was split into 16-size `jobs=1` shards and executed as six batches:

- Batch 57: 6720..6975
- Batch 58: 6976..7231
- Batch 59: 7232..7487
- Batch 60: 7488..7743
- Batch 61: 7744..7999
- Batch 62: 8000..8191

All newly counted shards completed with empty stderr, hard-eligible
`no_roots`, zero returned roots, and no factors. Several stale zero-byte
`batch57` files existed from an earlier interrupted attempt, so those were not
counted; the accepted evidence comes from the rerun directories
`/tmp/ct07_batch57_269_gap*_runner` through
`/tmp/ct07_batch62_269_gap*_runner`.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 8896/16384
- coverage fraction: 54.296875%
- total checked completion cases across variants: 35584
- unique oracle cases total: 8896
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch62_14bit_269_nonoverlap_coverage.json`.

This closes the first large completion range: the merged prefix is now
0..8447, because the newly closed 6720..8191 segment connects the previous
0..6719 prefix with the prior 8192..8447 island. The next unchecked gap is
8448..12287.

## Batch 63-65 Follow-Up

The next `269:2` prefix segment 8448..9215 was split into 16-size `jobs=1`
shards and executed as three batches:

- Batch 63: 8448..8703
- Batch 64: 8704..8959
- Batch 65: 8960..9215

All newly counted shards completed with empty stderr, hard-eligible
`no_roots`, zero returned roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 9664/16384
- coverage fraction: 58.984375%
- total checked completion cases across variants: 38656
- unique oracle cases total: 9664
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch65_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..9215. The next unchecked gap is 9216..12287.

## Batch 66-67 Follow-Up

The next `269:2` prefix segment 9216..9727 was split into 16-size `jobs=1`
shards and executed as two batches:

- Batch 66: 9216..9471
- Batch 67: 9472..9727

All newly counted shards completed with empty stderr, hard-eligible
`no_roots`, zero returned roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 10176/16384
- coverage fraction: 62.109375%
- total checked completion cases across variants: 40704
- unique oracle cases total: 10176
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch67_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..9727. The next unchecked gap is 9728..12287.

## Batch 68-70 Follow-Up

The next `269:2` prefix segment 9728..10495 was split into 16-size `jobs=1`
shards and executed as three batches:

- Batch 68: 9728..9983
- Batch 69: 9984..10239
- Batch 70: 10240..10495

All newly counted shards completed with empty stderr, hard-eligible
`no_roots`, zero returned roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 10944/16384
- coverage fraction: 66.796875%
- total checked completion cases across variants: 43776
- unique oracle cases total: 10944
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch70_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..10495. The next unchecked gap is 10496..12287.

## Batch 71 Follow-Up

The next `269:2` prefix segment 10496..10751 was split into four parallel
64-size runners, each internally using 16-size `jobs=1` shards:

- Runner 10496: 10496..10559
- Runner 10560: 10560..10623
- Runner 10624: 10624..10687
- Runner 10688: 10688..10751

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 11200/16384
- coverage fraction: 68.359375%
- total checked completion cases across variants: 44800
- unique oracle cases total: 11200
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch71_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..10751. The next unchecked gap is 10752..12287.

## Batch 72-73 Follow-Up

The next `269:2` prefix segment 10752..11263 was split into 16-size `jobs=1`
shards and executed as two batches:

- Batch 72: 10752..11007
- Batch 73: 11008..11263

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 11712/16384
- coverage fraction: 71.484375%
- total checked completion cases across variants: 46848
- unique oracle cases total: 11712
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch73_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..11263. The next unchecked gap is 11264..12287.

## Batch 74-77 Follow-Up

The next `269:2` prefix segment 11264..12287 was split into 16-size `jobs=1`
shards and executed as four batches:

- Batch 74: 11264..11519
- Batch 75: 11520..11775
- Batch 76: 11776..12031
- Batch 77: 12032..12287

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 12736/16384
- coverage fraction: 77.734375%
- total checked completion cases across variants: 50944
- unique oracle cases total: 12736
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch77_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..12351. The next unchecked gap is 12352..14335.

## Batch 78-79 Follow-Up

The next `269:2` prefix segment 12352..12863 was split into 16-size `jobs=1`
shards and executed as two batches:

- Batch 78: 12352..12607
- Batch 79: 12608..12863

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 13248/16384
- coverage fraction: 80.859375%
- total checked completion cases across variants: 52992
- unique oracle cases total: 13248
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch79_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..12863. The next unchecked gap is 12864..14335.

## Batch 80-81 Follow-Up

The next `269:2` prefix segment 12864..13375 was split into 16-size `jobs=1`
shards and executed as two batches:

- Batch 80: 12864..13119
- Batch 81: 13120..13375

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 13760/16384
- coverage fraction: 83.984375%
- total checked completion cases across variants: 55040
- unique oracle cases total: 13760
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch81_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..13375. The next unchecked gap is 13376..14335.

## Batch 82-85 Follow-Up

The next `269:2` prefix segment 13376..14335 was split into 16-size `jobs=1`
shards and executed as four batches:

- Batch 82: 13376..13631
- Batch 83: 13632..13887
- Batch 84: 13888..14143
- Batch 85: 14144..14335

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Updated non-overlap aggregate for `269:2`:

- covered completions per variant: 14720/16384
- coverage fraction: 89.84375%
- total checked completion cases across variants: 58880
- unique oracle cases total: 14720
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The new aggregate file is
`/tmp/ct07_batch85_14bit_269_nonoverlap_coverage.json`.

The merged prefix is now 0..14463. The next unchecked gaps are
14464..14591, 14656..14719, 14784..14847, and 14976..16383.

## Batch 86-91 Follow-Up

The remaining `269:2` completion gaps were split into 16-size `jobs=1`
shards and executed as six batches:

- Batch 86: 14464..14591, 14656..14719, 14784..14847
- Batch 87: 14976..15231
- Batch 88: 15232..15487
- Batch 89: 15488..15743
- Batch 90: 15744..15999
- Batch 91: 16000..16383

All newly counted shards completed with hard-eligible `no_roots`, zero returned
roots, and no factors.

Final non-overlap aggregate for this `269:2` 14-bit union candidate:

- covered completions per variant: 16384/16384
- coverage fraction: 100%
- total checked completion cases across variants: 65536
- unique oracle cases total: 16384
- dropped literals: 14
- remaining common selected literals: 191
- all counted shards: hard-eligible `no_roots`
- roots/factors: 0

The final aggregate file is
`/tmp/ct07_batch91_14bit_269_nonoverlap_coverage.json`.

This closes the current high branch `x6=0x245521490bd`, `x7=0` with the
low all-zero union variants for this minimized 14-bit hard-clause candidate:
all 16384 completion assignments are no-root cases under the low-Coppersmith
oracle. This is not a factor recovery; it is a sound no-good result for this
candidate branch.

## Go Dynamic-T And Bit-Precise Skip Smoke

The Go Hensel-tail exporter now accepts the intermediate split points `T=816`
and `T=832`, in addition to `T=784`, `T=800`, and `T=848`. A single full-`x6`
tuple smoke with `x6=0x245521490bd`, `x1low32=0`, `x1high7=0`, `x2low7=0x7e`,
`--exact-tail-limbs 1`, and `--q-interval-bound` returned `SAT=0` for all five
split points:

- `T=784`: `UNSAT=1`, `382587` vars, `1712626` clauses
- `T=800`: `UNSAT=1`, `404219` vars, `1808615` clauses
- `T=816`: `UNSAT=1`, `425838` vars, `1904562` clauses
- `T=832`: `UNSAT=1`, `447446` vars, `2000481` clauses
- `T=848`: `UNSAT=1`, `469206` vars, `2096760` clauses

This supports the current heuristic: after full `x6` is fixed, try the lower
valid split first because the CNF grows monotonically with `T` in this smoke.

The exporter and Python runner also now accept `--skip-known-prefix-bits`, a
bit-precise carry seed for product-prefix CNF. This lets assumption sweeps skip
up to non-limb boundaries such as bit `242` or bit `265` when the relevant
base bits are already fixed.

With `T=784`, `arith_bits=272`, `skip_known_prefix_bits=242`,
`q_interval_bound=True`, fixed `x6=0x245521490bd`, and `x1low32=0`, the full
`x1high7 * x2low7` space (`128 * 128 = 16384`) returned `SAT=0`, `UNSAT=16384`.
The CNF size was `2646` vars / `6058` clauses.

The same small filter was then applied to five representative `x1low32` bases
under each of five full `x6` candidates:

- `x6` candidates:
  `0x24552149094`, `0x24552149097`, `0x24552149098`,
  `0x2455214909b`, `0x245521490bd`
- `x1low32` bases:
  `0xc4fd44ff`, `0xd08466ff`, `0x2cfd44ff`,
  `0x56fd44ff`, `0x20fd44ff`

For every pair, all `x1high7 * x2low7 = 16384` assumptions were UNSAT. The
aggregate is `25 * 16384 = 409600` assumptions with `SAT=0`, `UNSAT=409600`.
The generated CNFs were tiny compared with the earlier one-tail-limb
product-prefix oracle, ranging from `2620..2642` variables and `5923..6045`
clauses.

This is still not factor recovery, and it is not a proof over the full
`x1low32` space. It does show that the Go product-prefix path can cheaply close
large `x1high7/x2low7` slices after full `x6` is fixed, so the next broad search
should use this bit-precise skip filter before expensive `T>=800` oracle CNFs.

## Go Bit-Skip 54-Base Sweep

The bit-precise skip filter was then expanded from five representative
`x1low32` bases to the full 54-base representative set that had been tracked in
the earlier high32/high36/high40 experiments. The fixed full-`x6` candidates
were:

- `0x24552149094`
- `0x24552149097`
- `0x24552149098`
- `0x2455214909b`
- `0x245521490bd`

For each `x6` candidate and each representative `x1low32` base, the filter
checked the full `x1high7 * x2low7 = 128 * 128 = 16384` assumption space with:

- `T=784`
- `arith_bits=272`
- `skip_known_prefix_bits=242`
- `q_interval_bound=True`
- `branch_low=0`, `branch_high=0`

Every pair was UNSAT:

- pairs checked: `5 * 54 = 270`
- assumptions checked: `270 * 16384 = 4423680`
- SAT: `0`
- UNSAT: `4423680`
- CNF size range: `2620..2649` variables, `5923..6073` clauses

The aggregate summary file is
`/tmp/ct07_skip_bits_54bases_5x6_summary.json`.

This strongly lowers the priority of these five full-`x6` candidates under the
tracked representative `x1low32` bases. It still does not prove the candidates
globally false, because the `x1low32` space is much larger than the 54
representatives. The next useful step is to use the same tiny filter as the
first-stage scorer when generating new `x1low32` bases and more diverse `x6`
prefixes, instead of relying on CP-SAT conflict ranking alone.

## Go Bit-Skip Extra Bases And Full-Low24 Sweeps

The same bit-skip filter was expanded to the remaining plausible `x1low32`
values found in the writeups. One parsed value, `0x91548524`, was excluded
because it is an `x6` prefix rather than an `x1low32` base. The remaining 25
extra bases included the next-base and more-8466 families plus `0x00000000`.

For the same five full-`x6` candidates, every extra-base pair was UNSAT:

- extra bases per `x6`: `25`
- pairs checked: `5 * 25 = 125`
- assumptions checked: `125 * 16384 = 2048000`
- SAT: `0`
- UNSAT: `2048000`

Combining the 54-base and extra-base sweeps gives:

- bases per `x6`: `79`
- pairs checked: `5 * 79 = 395`
- assumptions checked: `395 * 16384 = 6471680`
- SAT: `0`
- UNSAT: `6471680`
- CNF size range: `2620..2649` variables, `5923..6073` clauses

The aggregate summary file is
`/tmp/ct07_skip_bits_79bases_5x6_summary.json`.

Three active low24 branches were then checked exhaustively over all 256
`x1low32` extensions:

- `x6=0x245521490bd`, `x1low24=0x8466ff`
- `x6=0x24552149098`, `x1low24=0x22ffff`
- `x6=0x24552149094`, `x1low24=0xfd44ff`

Each run checked `256 * 128 * 128 = 4194304` assumptions and every assignment
was UNSAT. Aggregate:

- active low24 branches checked: `3`
- assumptions checked: `12582912`
- SAT: `0`
- UNSAT: `12582912`
- CNF size ranges:
  - `0x8466ff`: `2617..2652` vars, `5932..6085` clauses
  - `0x22ffff`: `2619..2653` vars, `5909..6070` clauses
  - `0xfd44ff`: `2617..2651` vars, `5916..6063` clauses

The aggregate summary file is
`/tmp/ct07_skip_bits_full_low24_active_buckets_summary.json`.

No SAT survivors were produced, so there was no candidate to pass to the
stronger `T>=800` product-prefix oracle or folded Coron verifier. The useful
conclusion is negative: the current CP-SAT-ranked `x6` candidates and their
most active `x1low24` families are inconsistent with even the cheap 272-bit
product-prefix filter. The search should now regenerate more diverse `x6`
prefixes and `x1low32` bases with this Go filter in the loop from the start.

## Go Free-X1 Full-X6 Filter

The bit-skip filter was then strengthened from representative `x1low32` bases
to a fully free `x1`/`x2low7` check. The new runner mode is
`run_07_go_sat_filter.py --free-x1-filter`; it fixes one full 46-bit `x6`
candidate, leaves all 39 bits of `x1=p[210..248]` free, leaves
`x2low7=p[265..271]` free, and solves the generated Go CNF directly.

Command shape:

```bash
/tmp/cryptotest_sat_venv/bin/python cryptotest/solutions/run_07_go_sat_filter.py \
  --free-x1-filter \
  --summary-only \
  --summary-json /tmp/ct07_free_x1_filter_5x6_noq_summary.json \
  --T 784 \
  --arith-bits 272 \
  --skip-known-prefix-bits 210 \
  --x6-candidate 0x24552149094 \
  --x6-candidate 0x24552149097 \
  --x6-candidate 0x24552149098 \
  --x6-candidate 0x2455214909b \
  --x6-candidate 0x245521490bd \
  --branch-low 0 \
  --branch-high 0
```

The same command was repeated with `--q-interval-bound`; both versions closed
all five full-`x6` candidates:

- `x6` candidates: `0x24552149094`, `0x24552149097`, `0x24552149098`,
  `0x2455214909b`, `0x245521490bd`
- free variables in the filter: full `x1` and `x2low7`
- no q-bound result: SAT `0`, UNSAT `5`, vars `7140`, clauses `26416..26417`
- q-bound result: SAT `0`, UNSAT `5`, vars `7140`, clauses `26961..26986`
- summaries:
  - `/tmp/ct07_free_x1_filter_5x6_noq_summary.json`
  - `/tmp/ct07_free_x1_filter_5x6_qbound_summary.json`

This is stronger than the earlier 79-base and active-low24 sweeps. For
`branch_low=0`, `branch_high=0`, the five tracked full-`x6` candidates are not
merely inconsistent with selected representative `x1low32` bases; they are
inconsistent with the 272-bit product-prefix CNF even when `x1` and `x2low7`
are left unconstrained. The q-bound-free run shows that the contradiction is
not caused by the interval-bound add-on.

## Go Free-X1 X6-High Bucket Filter

The free-`x1` runner was extended again with
`--free-x1-x6high-filter`. This fixes only a high prefix of
`x6=p[784..829]` and leaves `x6low`, all of `x1`, and `x2low7` free. The split
`T` is chosen high enough that the remaining unknown `x6low` bits sit below the
split and the p/q tails above `T` are known.

First, the alternative full-`x6` candidates from the diversity queue were
checked with the original full-`x6` free-`x1` mode:

- branches: `x7=1,2,3,4,5,6`, with `x0=0`
- full-`x6` candidates checked: `20`
- filter: `T=784`, `arith_bits=272`, `skip_known_prefix_bits=210`
- SAT: `0`
- UNSAT: `20`

Then the corresponding high-prefix buckets were checked:

- tracked high36 buckets for `x7=0..6`: `7/7` UNSAT
- tracked high32 buckets for `x7=0..6`: `7/7` UNSAT
- `x7=0` prefix-depth checks:
  - high40 `0x915485242`, `T=800`: UNSAT
  - high36 `0x91548524`, `T=800`: UNSAT
  - high32 `0x9154852`, `T=800`: UNSAT
  - high28 `0x915485`, `T=816`: UNSAT
  - high24 `0x91548`, `T=816`: UNSAT
  - high20 `0x9154`, `T=832`: UNSAT
  - high16 `0x915`, `T=848`: UNSAT
- tracked high16 buckets for `x7=1..6`: `6/6` UNSAT
- `tail848` regenerated top16 high16 prefixes for `x7=0`: `16/16` UNSAT
- high16 `x7=0,x6high=0x915` over every `x0=0..15`: `16/16` UNSAT

The aggregate summary is `/tmp/ct07_free_x1_diversity_aggregate.json`.

These are still conditional prefix no-goods, not a factor recovery. The
important improvement is that the filter is no longer tied to representative
`x1low32` bases. It can now discard a full `x6` high-prefix bucket while
allowing `x6low`, `x1`, and `x2low7` to vary.

## Erratum: Skip-Prefix CNF Bug

The Go product-prefix encoder had a bug in `skip_known_prefix_bits` handling.
It correctly seeded the carry at the skipped boundary, but still enforced the
target bits for columns `0..skip-1`. Since `N` is odd, bit 0 could become an
empty clause whenever the low products were skipped. This made broad
bit-skip/product-prefix filters report trivial UNSAT.

Fix:

- `addArithmeticPrefixClauses` now starts the column reduction/enforcement loop
  at `skipBits`.
- `main_test.go` now checks that a skip-known-prefix model does not emit empty
  clauses.

Corrected sanity checks:

- No fixed `x6`, `T=848`, `arith_bits=272`, `skip_known_prefix_bits=210`:
  sampled `x7=0,1,4,15` all became SAT.
- The five tracked full-`x6` candidates with free `x1`/`x2low7` became SAT
  both without q interval bounds and with q interval bounds:
  - no q-bound: SAT `5`, UNSAT `0`, clauses `26313..26314`
  - q-bound: SAT `5`, UNSAT `0`, clauses `26858..26883`
- Two fixed shortlist tuples at `arith_bits=320`, `skip_known_prefix_limbs=16`
  are SAT:
  - `x1=0x60c68466ff`, `x2low7=0x7e`, `x6=0x245521490bd`
  - `x1=0x7ad08466ff`, `x2low7=0x11`, `x6=0x245521490bd`
- A corrected `arith_bits=800` recheck was started but intentionally
  terminated after long runtime; there is no corrected verdict yet.

Summary: previous UNSAT claims from Go product-prefix or bit-skip filters that
used `skip_known_prefix_bits` or `skip_known_prefix_limbs` before this fix must
not be used as no-good evidence. The affected JSONs remain useful only as a log
of the pre-fix experiment, not as proof.

Corrected summary file:
`/tmp/ct07_skip_prefix_fix_recheck_summary.json`.

## Post-Fix Go/CP-SAT Probe

After the skip-prefix fix, the same Go/PySAT path was re-run with stronger
cheap add-ons to see whether it can still rank or close the current full-`x6`
shortlist.

Full-`x6`, free-`x1/x2low7` sweep:

- candidates:
  `0x24552149094`, `0x24552149097`, `0x24552149098`,
  `0x2455214909b`, `0x245521490bd`
- `T = 784,800,816,832,848`
- `arith_bits = 320`
- `skip_known_prefix_bits = 210`
- `q_interval_bound = true`
- odd residue moduli: `3,5,7,11`

All five `T` values returned SAT `5`, UNSAT `0`. The representative SAT models
are not evidence for the real `x1`; they are only arbitrary survivors of a weak
320-bit product-prefix filter. Clause counts are about `347655..347834`, and
the example model projections are stable across `T`, which means changing `T`
alone is not providing useful pruning at this prefix strength.

CP-SAT build-only comparison for `x6=0x245521490bd`:

- `T=784`: lower product vars `240`, q prefix bits inside `T` `15`
- `T=800`: lower product vars `255`, q prefix bits inside `T` `31`
- `T=816`: lower product vars `271`, q prefix bits inside `T` `47`
- `T=832`: lower product vars `288`, q prefix bits inside `T` `63`
- `T=848`: lower product vars `306`, q prefix bits inside `T` `79`

This confirms that `T=784/800` are still the smaller corrected probes. `T=848`
adds more q prefix bits, but the lower product part grows at the same time.

Assumption-sweep cost check:

- `arith_bits=384`, `T=784`, full `x6`, fixed `x1low32`, full
  `x1high7*x2low7 = 16384` timed out at 180 seconds for the tested seeds.
- The same setup reduced to one fixed `x1high7` and all `x2low7` values
  finished, but both tested shards were SAT `128`, UNSAT `0`:
  - `x6=0x245521490bd`, `x1=0x6d5c92ae6e` high shard, all `x2low7`
  - `x6=0x24552149094`, `x1=0x166f09bd14` high shard, all `x2low7`

CP-SAT exact-tail tuple probes were also run with the weak SAT model tuples:

- `T=784`, `tail_limbs=64`, `x6=0x245521490bd`,
  `x1=0x6d5c92ae6e`, `x2low7=0x03`: UNKNOWN after 10s,
  conflicts/sec `244.89`
- `T=784`, `tail_limbs=64`, `x6=0x24552149094`,
  `x1=0x166f09bd14`, `x2low7=0x78`: UNKNOWN after 10s,
  conflicts/sec `226.79`
- `T=800`, `tail_limbs=64`, `x6=0x245521490bd`,
  `x1=0x6d5c92ae6e`, `x2low7=0x03`: UNKNOWN after 10s,
  conflicts/sec `417.62`

A 5s CP-SAT search comparison on `T=800`, `tail_limbs=32`,
`x6=0x245521490bd`, odd residues `3,5,7` showed fixed `p[210..248]`
decisions are still worth keeping for this cube:

- default search: conflicts/sec `395.52`
- `--decision-p-range 210:39`: conflicts/sec `547.76`

Current conclusion: the corrected Go product-prefix filter no longer gives the
strong pre-fix UNSAT closures. `arith_bits=320/384` is too weak to split the
current free-`x1` or single-`x1high7` shards, while broader `arith_bits=384`
sweeps are already too slow. The next useful engineering step is not another
large PySAT sweep, but a stronger exact-tail CNF/export path or smaller CP-SAT
cube scoring that keeps `T=784/800` and uses fixed p-edge decisions.

## Go Lowlift-Q265 CNF Check

The Go exporter now supports `lowlift_q_bits=265` / `--lowlift-q 265`.
For fixed `x0`, the lower inverse relation makes
`q[210..264] = Q0 + C*x1 (mod 2^55)`, where `x1=p[210..248]`. The exporter
encodes this affine relation directly as CNF clauses, and a regression test
checks that the helper emits clauses without empty-clause artifacts.

Validation and probes:

- `go test ./...` passes in `solutions/go_hensel_tail`.
- `python3 -m py_compile` passes for the Go runner and CP-SAT/cube drivers.
- `test_sat_cas_core.py` passes.
- Free `x1/x2low7`, five tracked full-`x6` candidates, `T=784`,
  `arith_bits=320`, `skip_known_prefix_bits=210`, `--lowlift-q 265`,
  q interval bound, and odd residues `3,5,7,11`: SAT `5`, UNSAT `0`.
- The same setup with `arith_bits=272`: SAT `5`, UNSAT `0`.
- Two fixed `x1high7` shards at `arith_bits=384`, all `x2low7`: each
  SAT `128`, UNSAT `0`.
- Adding a 16-bit tail window to the free-`x1` five-`x6` probe still returned
  SAT `5`, UNSAT `0`, with about `85k` variables and `405k` clauses.

Summary JSONs:

```text
/tmp/ct07_lowliftq265_free_x1_5x6_T784_ab320_qodd_summary.json
/tmp/ct07_lowliftq265_free_x1_5x6_T784_ab272_qodd_summary.json
/tmp/ct07_lowliftq265_shard_x2_T784_ab384_x6094_x1low2f375a87_x1hi47_qodd_summary.json
/tmp/ct07_lowliftq265_shard_x2_T784_ab384_x6bd_x1lowb183cdcc_x1hi09_qodd_summary.json
/tmp/ct07_lowliftq265_free_x1_5x6_T784_ab272_tw16_qodd_summary.json
```

This confirms that the affine q-middle constraint is wired into the fast Go/CNF
path, but by itself it is not a strong pruning condition. The next Go-side
target remains a true lower-column elimination / carry-vector tail equality,
not a larger weak product-prefix sweep.

## Go Lowlift-Q272 CNF Check

The Go exporter now also supports `lowlift_q_bits=272` / `--lowlift-q 272`.
This is the limb-aligned version of the same 2-adic inverse relation:
`q[0..271]` is encoded as a linear function of all currently unknown p bits
below bit 272. In the current masks that includes both `x1=p[210..248]` and
`x2low7=p[265..271]`, so it is more directly aligned with the
`x1high7*x2low7` assumption sweeps than the q-middle-only 265-bit lift.

Validation:

- `go test ./...` passes with a semantic q272 test. The test assigns
  `x1=0x123456789a`, `x2low7=0x55`, and the expected 272-bit q-low value, then
  checks that unit propagation is consistent. Flipping one q-low bit produces a
  propagation conflict.
- The Python runner now documents `--lowlift-q` as supporting `265` and `272`.

Free-`x1/x2low7` probes over the five tracked full-`x6` candidates:

- `T=784`, `arith_bits=272`, `skip_known_prefix_bits=210`,
  `--lowlift-q 272`, q interval bound, odd residues `3,5,7,11`:
  SAT `5`, UNSAT `0`; CNFs are about `62668` vars / `305k` clauses.
- Adding `tail_window_bits=16`, `tail_window_carry_bits=16`:
  SAT `5`, UNSAT `0`; CNFs are about `85.8k` vars / `407k` clauses.

Summary JSONs:

```text
/tmp/ct07_lowliftq272_free_x1_5x6_T784_ab272_qodd_summary.json
/tmp/ct07_lowliftq272_free_x1_5x6_T784_ab272_tw16_qodd_summary.json
```

The 272-bit lift is correctly wired and includes `x2low7`, but it still does
not close the free-`x1` candidate set. The useful next implementation remains a
real carry-vector connection from the eliminated lower Hensel recurrence into
the tail/product columns.

## Go Q272 No-Skip Prefix Carry Probe

To measure whether the existing product-prefix encoder can already provide a
usable exact lower-carry baseline, the five tracked full-`x6` candidates were
also checked without `skip_known_prefix_bits`. This forces the CNF to compute
the product from bit 0 upward instead of seeding a known carry at bit 210.

Runs:

- `T=784`, `arith_bits=272`, `skip_known_prefix_bits=0`,
  `--lowlift-q 272`, q interval bound, odd residues `3,5,7,11`:
  SAT `5`, UNSAT `0`; CNFs are about `63220` vars / `307k` clauses.
- Same setup with `arith_bits=320`:
  SAT `5`, UNSAT `0`; CNFs are about `75051` vars / `361k` clauses.

Summary JSONs:

```text
/tmp/ct07_lowliftq272_free_x1_5x6_T784_ab272_noskip_qodd_summary.json
/tmp/ct07_lowliftq272_free_x1_5x6_T784_ab320_noskip_qodd_summary.json
```

This shows that exact lower-prefix computation through bit 320 is still too
weak for the free-`x1/x2low7` full-`x6` probe. The next SAT-side work should
avoid broad free-`x1` sweeps and either add deeper, optimized exact-tail
carry-vector constraints or split into smaller `x1/x2` cubes before solving.

## Go Q272 No-Skip Small-Cube Probe

The next check fixed one full-`x6` candidate and one active `x1low32` base,
then split only the upper 7 bits of `x1` and the low 7 bits of `x2`.

Parameters:

```text
x6 = 0x245521490bd
x1low32 = 0xb183cdcc
x1high7 = 0x09
x2low7 = 0x00..0x7f
T = 784
skip_known_prefix_bits = 0
lowlift_q = 272
q_interval_bound = true
odd residues = 3,5,7,11
```

Results:

- `arith_bits=320`: SAT `128`, UNSAT `0`, CNF about `63698` vars /
  `307366` clauses.
- `arith_bits=384`: SAT `128`, UNSAT `0`, CNF about `83731` vars /
  `399725` clauses.
- The full `x1high7 * x2low7 = 16384` sweep at `arith_bits=320` timed out
  after 180s, so this path must be sharded rather than run as one broad
  assumption sweep.

Summary JSONs:

```text
/tmp/ct07_q272_noskip_ab320_x6bd_x1low_b183cdcc_x1hi09_allx2_summary.json
/tmp/ct07_q272_noskip_ab384_x6bd_x1low_b183cdcc_x1hi09_allx2_summary.json
```

This confirms the weaker free-cube result: even after fixing a plausible
`x1high7` shard and pushing the exact prefix to 384 bits, the current q272
no-skip product-prefix filter does not distinguish the 128 `x2low7` values.
The next useful SAT implementation is not a wider broad q272 prefix run, but a
real exact-tail carry-vector CNF or a much smaller/deeper cube strategy.

The same shard was pushed once more to `arith_bits=512`:

- `arith_bits=512`: SAT `128`, UNSAT `0`, CNF about `118028` vars /
  `559998` clauses, with `14` assumption literals per `x2low7` value.

Summary JSON:

```text
/tmp/ct07_q272_noskip_ab512_x6bd_x1low_b183cdcc_x1hi09_allx2_summary.json
```

This strengthens the negative result. Even an exact product-prefix through bit
512 does not split this fixed `x1high7` shard, so simply widening the q272
no-skip prefix is not a promising next pruning path.

As a cheaper endpoint sanity, the same shard was also tested at
`arith_bits=640` for just `x2low7=0x00` and `0x7f`:

- `arith_bits=640`: SAT `2`, UNSAT `0`, CNF about `215584` vars /
  `998039` clauses, with `14` assumption literals per tested endpoint.

Summary JSON:

```text
/tmp/ct07_q272_noskip_ab640_x6bd_x1low_b183cdcc_x1hi09_x2_00_7f_summary.json
```

This is not a full 128-value sweep, but it confirms that pushing the prefix
well past 512 bits still leaves even the two extreme `x2low7` endpoints
satisfiable. The next useful implementation target remains exact-tail
carry-vector encoding, not another broad prefix-width increase.

## Go Exact Carry-Column Prototype

The Go exporter now has a first exact carry-column encoder:

- Go input JSON: `exact_tail_carry_limbs`, `exact_carry_bits`
- Go argv: `--exact-tail-carry-limbs`, `--exact-carry-bits`
- Python runner args: `--exact-tail-carry-limbs`, `--exact-carry-bits`

For `exact_tail_carry_limbs=1`, the exporter encodes all lower columns plus the
first limb column above `T`. Each column reduces its product terms, constant
limb, and incoming carry vector with Boolean adders; bits `0..15` are tied to
the corresponding `N` limb, while bits `16..` are tied to the next column's
carry vector. A synthetic constant-times-variable toy product regression checks
that the correct assignment unit-propagates without contradiction and a one-bit
wrong assignment conflicts.

Verification:

```text
go test -run 'TestBuildTailModelExactTailCarryColumns|TestAddExactCarryColumnClausesToyProduct|TestLoadInputParsesPlanArgv' -count=1 -v
go test ./...
python3 -m py_compile cryptotest/solutions/run_07_go_sat_filter.py
```

A single problem-7 endpoint smoke was attempted:

```text
x6 = 0x245521490bd
x1low32 = 0xb183cdcc
x1high7 = 0x09
x2low7 = 0x00
T = 784
arith_bits = 0
exact_tail_carry_limbs = 1
exact_carry_bits = 32
lowlift_q = 272
q_interval_bound = true
odd residues = 3,5,7,11
```

The first assumption-base smoke did not finish within a 180s `timeout`, and no
summary JSON was emitted. To separate export cost from solve cost, the runner
now has `--build-only`, which generates the CNF and reads only the DIMACS
header. The same assumption-base endpoint still timed out in build-only mode, so
the broad `x1high7/x2low7` assumption base is too large for this naive encoder.

A fixed-tuple build was then tested with the same endpoint. This exposed that a
272-bit skipped prefix has a large carry-in (`264` bits), so `exact_carry_bits=32`
is invalid. After widening carry vectors and applying the known-prefix skip to
the exact carry encoder, fixed-tuple build-only results were:

```text
exact_carry_bits=320: vars=409595 clauses=1816286
exact_carry_bits=272: vars=404939 clauses=1802414
```

The encoder was then changed to compute a per-column carry width from simple
upper bounds instead of allocating the full cap for every carry vector. The same
fixed endpoint at `exact_carry_bits=272` became:

```text
vars=385511 clauses=1744108
```

This is smaller than the earlier fixed exact-carry CNF, but the optimized
`exact_carry_bits=272` fixed tuple still timed out in solve mode after 180s.
One more constant-folding pass was added for exact carry-column terms: fully
known low-low terms and fully known high-low coefficient terms are now folded
into the column constant instead of emitted as repeated `true` literals. The
same fixed endpoint became:

```text
vars=380675 clauses=1727237
```

This also timed out in solve mode after 180s.
So the new path is now measurable and can start after a known prefix, but it is
still a correctness scaffold and exactness guardrail rather than a fast pruning
path. The next code step is to reduce the exact carry-column CNF before using it
for broad sweeps, especially by avoiding wide high carry-vector variables when
their high bits are already forced by the known prefix and by combining this
with smaller fixed `x1/x2` cubes.

## Go Free-Mode T-Candidates

`run_07_go_sat_filter.py` now allows `--T-candidates` in the two direct
free-`x1` modes, not only in assumption sweeps:

- `--free-x1-filter`
- `--free-x1-x6high-filter`

For each fixed full-`x6` or `x6high` candidate, the runner builds one CNF per
valid `T`. If a candidate has unknown tail bits above a proposed `T`, that
case is recorded in `skipped_t` instead of aborting the whole sweep.

Smoke checks:

- full `x6=0x24552149094`, `--T-candidates 784,800`, `arith_bits=272`,
  `--lowlift-q 272`, q interval, odd residue `3`: both `T=784` and `T=800`
  solved SAT.
- `x6high=0x91548524`, `x6high_bits=36`, `--T-candidates 784,800` with the
  same weak filter: `T=784` was skipped because the fixed high boundary is
  bit 794, and `T=800` solved SAT.

Summary JSONs:

```text
/tmp/ct07_free_t_candidates_smoke.json
/tmp/ct07_free_x6high_t_candidates_smoke.json
```

This is a runner improvement rather than a new cryptanalytic cut: it makes the
next broad/free candidate generation cheaper to compare across dynamic
`T=784/800/816/832/848` before sending surviving cubes to a stronger exact-tail
carry-vector CNF.

## Go Odd-Residue Automaton Compression

The Go exporter now compresses odd-residue automata by folding known bits as
constant residue shifts and allocating automaton states only at unknown bit
positions. Fully known residue checks simplify away except for the shared
constant literal, while unknown-bit residue checks still add state variables and
clauses. The product-residue exclusion clauses now go through
`addSimplifiedClause`, so constant-satisfied exclusions are not emitted.

Regression coverage:

- fully known toy factors with odd residues add no automaton state variables;
- a toy factor with one unknown p bit does add residue automaton variables and
  clauses.

Representative smoke after compression:

- full `x6=0x24552149094`, `--T-candidates 784,800`, `arith_bits=272`,
  `--lowlift-q 272`, q interval, odd residue `3`: both T values remain SAT,
  while CNF size drops from about `15518/54398` and `15551/54430`
  vars/clauses to `12116/46452` and `12149/46484`.
- `x6high=0x91548524`, `x6high_bits=36`, same weak filter: `T=784` is still
  skipped at boundary 794 and `T=800` remains SAT, while CNF size drops from
  about `15551/54550` to `12254/46849`.

Summary JSONs:

```text
/tmp/ct07_free_t_candidates_residue_compressed_smoke.json
/tmp/ct07_free_x6high_t_candidates_residue_compressed_smoke.json
```

This does not recover the factor, but it lowers the cost of keeping odd
residue filters enabled in weak/free candidate-generation probes.

A broader direct free-`x1` sweep was then run over the five tracked full-`x6`
candidates and `T=784,800,816,832,848`:

```text
x6 candidates:
  0x24552149094
  0x24552149097
  0x24552149098
  0x2455214909b
  0x245521490bd
filter:
  arith_bits=272
  skip_known_prefix_bits=210
  lowlift_q=272
  q_interval_bound=true
  odd residues=3,5,7,11
```

All 25 candidate/T pairs remained SAT. CNF sizes were around `33.2k` variables
and `170k` clauses after residue compression. This confirms that the weak
free-`x1` filter is now cheap enough for queue scoring, but still not a pruning
oracle for these full-`x6` candidates. Stronger progress still requires exact
tail-carry propagation or deeper `x1/x2` cubes.

Summary JSON:

```text
/tmp/ct07_free_5x6_t_candidates_q272_residue_compressed_summary.json
```

## Exact Carry With Extra x2 Subcubes

`run_07_go_sat_filter.py` now accepts extra fixed p ranges with
`--fix-p-range START:WIDTH:VALUE`. This is useful for exact-carry probes where
fixing more of `x2=p[265..348]` lets the Go exporter constant-fold q-low and
column terms before CNF generation.

Representative fixed endpoint:

```text
x6=0x245521490bd
x1=0x9b183cdcc
x2low7=0x00
T=784
tail_limbs=1
arith_bits=0
exact_tail_carry_limbs=1
exact_carry_bits=272
lowlift_q=272
q interval bound
odd residues=3,5,7,11
```

The previous fully-known limb product fold left the no-extra endpoint at
`380675` vars / `1727237` clauses and the solve still timed out at 180s.
Adding fixed bits immediately shrinks and prunes the branch:

```text
x2[272..279]   = 0x00       -> 364643 vars / 1655853 clauses, UNSAT
x2[272..287]   = 0x0000     -> 344644 vars / 1568748 clauses, UNSAT
x2[272..303]   = 0x00000000 -> 310427 vars / 1417405 clauses, UNSAT
x2[272..303]   = 0xffffffff -> 329957 vars / 1508636 clauses, UNSAT
x2[272..303]   = 0x55555555 -> 321097 vars / 1467284 clauses, UNSAT
x2[272..303]   = 0xaaaaaaaa -> 320495 vars / 1464289 clauses, UNSAT
```

Additional 8-bit samples for the same `x1/x6` shard also closed quickly:

```text
x2low7=0x00, x2[272..279]=0xff -> 370359 vars / 1681769 clauses, UNSAT
x2low7=0x00, x2[272..279]=0x55 -> 368232 vars / 1671890 clauses, UNSAT
x2low7=0x00, x2[272..279]=0xaa -> 365070 vars / 1658240 clauses, UNSAT
x2low7=0x7f, x2[272..279]=0x00 -> 367310 vars / 1669033 clauses, UNSAT
x2low7=0x7f, x2[272..279]=0xff -> 375564 vars / 1705883 clauses, UNSAT
```

I also added direct-case `--assume-p-range START:WIDTH:all|V1,V2,...` for
comparison, but it is not useful for this exact-carry/q272 path: build-only on
the same endpoint remains `380675` vars / `1727237` clauses, and solving the
four representative assumptions `0x00,0xff,0x55,0xaa` timed out before the
first result. The reason is structural: assumptions do not let the exporter
promote q-low and product terms to constants, while `--fix-p-range` does.

The practical next SAT direction is therefore not a raw assumption sweep over
`p[272..279]`, but a cube-and-conquer pass that generates fixed `x2` subcubes
at exporter time and solves those in parallel.

The runner now also has direct-case `--fix-p-range-sweep` for this pattern. It
generates one exporter-time fixed CNF per value and can write aggregate JSON
with `--summary-json`.

Smoke checks:

```text
--fix-p-range-sweep 272:8:0x00,0x01
  build-only -> build_count=2
  solve      -> SAT 0, UNSAT 2
```

Then two sequential 8-value shards were run on the same fixed endpoint:

```text
x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
```

Four more 8-value shards were then launched in parallel:

```text
x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
```

The next 22 shards also closed:

```text
x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

So this endpoint now has a verified full 8-bit closure
`x2[272..279]=0x00..0xff`. Across all 256 values the result was SAT 0,
UNSAT 256. CNF sizes ranged from `363939` to `370359` variables and from
`1653067` to `1681769` clauses. This closes the fixed
`x6=0x245521490bd`, `x1=0x9b183cdcc`, `x2low7=0x00` endpoint at the next
8 x2 bits. The remaining search must move to other `x2low7`, `x1`, or `x6`
branches, or widen the fixed subcube depth.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2next8_00_01_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2next8_f8_ff_sweep_summary.json
```

The opposite `x2low7=0x7f` endpoint was then started with the same fixed
`x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry setup:

```text
x2low7=0x7f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x7f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

So the `x2low7=0x7f` endpoint now also has a verified full 8-bit closure
`x2[272..279]=0x00..0xff`. Across all 256 values the result was SAT 0,
UNSAT 256. CNF sizes were larger than the `x2low7=0x00` endpoint, ranging
from `367313` to `375927` variables and from `1669033` to `1707305`
clauses. This closes both sampled endpoints `x2low7=0x00` and `0x7f` at the
next 8 x2 bits under the same `x6/x1` exact-carry setup.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_7f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_7f_x2next8_f8_ff_sweep_summary.json
```

A midpoint endpoint was also started for the same fixed `x6/x1` pair:
`x2low7=0x3f`, `T=784`, q272 exact-carry, q interval, and odd residues
`3/5/7/11`. All 32 8-value shards closed:

```text
x2low7=0x3f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x3f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

This is now a full next-byte closure: all 256 values were UNSAT, with
aggregate SAT 0, UNSAT 256. CNF sizes ranged from `368578` to `376682`
variables and from `1674022` to `1710360` clauses.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_3f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_3f_x2next8_f8_ff_sweep_summary.json
```

A lower-quarter endpoint was then checked for the same fixed `x6/x1` pair:
`x2low7=0x1f`, `T=784`, q272 exact-carry, q interval, and odd residues
`3/5/7/11`. All 32 8-value shards closed:

```text
x2low7=0x1f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x1f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

This is now another full next-byte closure: all 256 values were UNSAT, with
aggregate SAT 0, UNSAT 256. CNF sizes ranged from `366022` to `374311`
variables and from `1663131` to `1699757` clauses. This gives another interior
point between the already-closed `x2low7=0x00` and `0x3f` endpoints for this
fixed shard, so sampled points `0x00`, `0x1f`, `0x3f`, and `0x7f` are all
closed at the next byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_1f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_1f_x2next8_f8_ff_sweep_summary.json
```

The upper-midpoint endpoint `x2low7=0x5f` was checked next under the same fixed
`x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry, q interval,
and odd-residue setup. All 32 8-value shards closed:

```text
x2low7=0x5f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x5f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

The aggregate result was SAT 0, UNSAT 256. CNF sizes ranged from `367210` to
`375805` variables and from `1668191` to `1706414` clauses. The sampled
fixed-shard endpoints now cover `x2low7=0x00`, `0x1f`, `0x3f`, `0x5f`, and
`0x7f`, each closed for the next full x2 byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_5f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_5f_x2next8_f8_ff_sweep_summary.json
```

The next binary-subdivision point `x2low7=0x0f` was then checked under the same
fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry,
q interval, and odd-residue setup. All 32 8-value shards closed:

```text
x2low7=0x0f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x0f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

The aggregate result was SAT 0, UNSAT 256. CNF sizes ranged from `366700` to
`375375` variables and from `1665978` to `1704481` clauses. The sampled
fixed-shard endpoints now cover `x2low7=0x00`, `0x0f`, `0x1f`, `0x3f`,
`0x5f`, and `0x7f`, each closed for the next full x2 byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_0f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_0f_x2next8_f8_ff_sweep_summary.json
```

The next binary-subdivision point `x2low7=0x2f` was then checked under the same
fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry,
q interval, and odd-residue setup. All 32 8-value shards closed:

```text
x2low7=0x2f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x2f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

The aggregate result was SAT 0, UNSAT 256. CNF sizes ranged from `368810` to
`376028` variables and from `1674932` to `1707324` clauses. The sampled
fixed-shard endpoints now cover `x2low7=0x00`, `0x0f`, `0x1f`, `0x2f`,
`0x3f`, `0x5f`, and `0x7f`, each closed for the next full x2 byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_2f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_2f_x2next8_f8_ff_sweep_summary.json
```

The next binary-subdivision point `x2low7=0x4f` was then checked under the same
fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry,
q interval, and odd-residue setup. All 32 8-value shards closed:

```text
x2low7=0x4f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x4f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

The aggregate result was SAT 0, UNSAT 256. CNF sizes ranged from `367579` to
`375110` variables and from `1669602` to `1703400` clauses. The sampled
fixed-shard endpoints now cover `x2low7=0x00`, `0x0f`, `0x1f`, `0x2f`,
`0x3f`, `0x4f`, `0x5f`, and `0x7f`, each closed for the next full x2 byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_4f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_4f_x2next8_f8_ff_sweep_summary.json
```

The remaining binary-subdivision point `x2low7=0x6f` was also checked under
the same fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272
exact-carry, q interval, and odd-residue setup. All 32 8-value shards closed:

```text
x2low7=0x6f, x2[272..279]=0x00..0x07 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x08..0x0f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x10..0x17 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x18..0x1f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x20..0x27 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x28..0x2f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x30..0x37 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x38..0x3f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x40..0x47 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x48..0x4f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x50..0x57 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x58..0x5f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x60..0x67 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x68..0x6f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x70..0x77 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x78..0x7f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x80..0x87 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x88..0x8f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x90..0x97 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0x98..0x9f -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xa0..0xa7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xa8..0xaf -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xb0..0xb7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xb8..0xbf -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xc0..0xc7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xc8..0xcf -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xd0..0xd7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xd8..0xdf -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xe0..0xe7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xe8..0xef -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xf0..0xf7 -> SAT 0, UNSAT 8
x2low7=0x6f, x2[272..279]=0xf8..0xff -> SAT 0, UNSAT 8
```

The aggregate result was SAT 0, UNSAT 256. CNF sizes ranged from `368670` to
`375186` variables and from `1674702` to `1703761` clauses. The sampled
fixed-shard endpoints now cover `x2low7=0x00`, `0x0f`, `0x1f`, `0x2f`,
`0x3f`, `0x4f`, `0x5f`, `0x6f`, and `0x7f`, each closed for the next full
x2 byte.

Summary JSONs:

```text
/tmp/ct07_exactcarry_x2low7_6f_x2next8_00_07_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_08_0f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_10_17_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_18_1f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_20_27_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_28_2f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_30_37_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_38_3f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_40_47_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_48_4f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_50_57_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_58_5f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_60_67_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_68_6f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_70_77_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_78_7f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_80_87_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_88_8f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_90_97_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_98_9f_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_a0_a7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_a8_af_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_b0_b7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_b8_bf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_c0_c7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_c8_cf_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_d0_d7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_d8_df_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_e0_e7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_e8_ef_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_f0_f7_sweep_summary.json
/tmp/ct07_exactcarry_x2low7_6f_x2next8_f8_ff_sweep_summary.json
```

A further left-side subdivision point, `x2low7=0x07`, was then checked under
the same fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272
exact-carry, q interval, and odd-residue setup. The full next-byte sweep also
closed:

```text
x2low7=0x07, x2[272..279]=0x00..0xff -> SAT 0, UNSAT 256
```

CNF sizes ranged from `367010` to `375600` variables and from `1667190` to
`1705384` clauses. The sampled fixed-shard points now cover `x2low7=0x00`,
`0x07`, `0x0f`, `0x1f`, `0x2f`, `0x3f`, `0x4f`, `0x5f`, `0x6f`, and `0x7f`,
each closed for the next full x2 byte. Summary JSONs match:

```text
/tmp/ct07_exactcarry_x2low7_07_x2next8_*_sweep_summary.json
```

The next left-side midpoint, `x2low7=0x17`, was then checked under the same
fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry,
q interval, and odd-residue setup. The full next-byte sweep also closed:

```text
x2low7=0x17, x2[272..279]=0x00..0xff -> SAT 0, UNSAT 256
```

CNF sizes ranged from `368173` to `374631` variables and from `1672149` to
`1700990` clauses. The sampled fixed-shard points now cover `x2low7=0x00`,
`0x07`, `0x0f`, `0x17`, `0x1f`, `0x2f`, `0x3f`, `0x4f`, `0x5f`, `0x6f`, and
`0x7f`, each closed for the next full x2 byte. Summary JSONs match:

```text
/tmp/ct07_exactcarry_x2low7_17_x2next8_*_sweep_summary.json
```

The next midpoint, `x2low7=0x27`, was then checked under the same fixed
`x6=0x245521490bd`, `x1=0x9b183cdcc`, `T=784`, q272 exact-carry, q interval,
and odd-residue setup. The full next-byte sweep also closed:

```text
x2low7=0x27, x2[272..279]=0x00..0xff -> SAT 0, UNSAT 256
```

CNF sizes ranged from `367380` to `375986` variables and from `1668852` to
`1707102` clauses. The sampled fixed-shard points now cover `x2low7=0x00`,
`0x07`, `0x0f`, `0x17`, `0x1f`, `0x27`, `0x2f`, `0x3f`, `0x4f`, `0x5f`,
`0x6f`, and `0x7f`, each closed for the next full x2 byte. Summary JSONs
match:

```text
/tmp/ct07_exactcarry_x2low7_27_x2next8_*_sweep_summary.json
```

## Lightweight Follow-up After x2low7=0x1f Closure

The guarded preverified low-Coppersmith callback path was replayed on two
semi-programmatic SAT cubes with the `x6=0x245521490bd`, `p[920..923]=0`
branch. The command used the previously proved 14-bit drop windows
`150:2,152:2,210:2,265:2,267:2,269:2,362:2`, with guards
`212:37:0`, `271:78:0`, and `364:76:0`.

Results:

```text
cube 1:
  ranges: 150:4=0, 210:39=0, 265:84=0, 362:78=0
  low-Coppersmith: no_roots, hard_clause_eligible=true
  guard matched: true
  dropped literals: 14
  learned clause literals: 191

cube 2:
  ranges: 150:4=0, 210:39=0x4, 265:84=0, 362:78=0
  low-Coppersmith: no_roots, hard_clause_eligible=true
  guard matched: false
  learned clause literals: 205

summary:
  low_coppersmith_calls=2
  low_coppersmith_hard_blocks=2
  low_coppersmith_minimized_blocks=1
  low_coppersmith_dropped_literals=14
```

This confirms the 14-bit preverified drop only fires under its guard, and
falls back to the full 205 selected literals when the `x1` guard is changed.
Output: `/tmp/ct07_batch92_sat_preverified_14bit_guarded_2cubes.jsonl`.

A follow-up clause-minimization audit was then run on the same two cubes with
dynamic drop windows `150:2` and `152:2`. This keeps the preverified 14-bit
guard intact, but asks the callback to prove additional low-prefix literals can
be removed when the guard misses:

```text
cube 1:
  guard matched: true
  preverified drops already removed all literals in 150:2 and 152:2
  learned clause literals: 191

cube 2:
  ranges: 150:4=0, 210:39=0x4, 265:84=0, 362:78=0
  guard matched: false
  dynamic drop 150:2: droppable_sound_no_root over 4 completions
  dynamic drop 152:2: droppable_sound_no_root over 16 completions
  learned clause literals: 201

summary:
  low_coppersmith_calls=17
  low_coppersmith_cache_hits=5
  low_coppersmith_hard_blocks=2
  low_coppersmith_minimized_blocks=2
  low_coppersmith_dropped_literals=18
```

This is a small but sound improvement for the first guard-miss branch: the
`x1=0x4` fallback cube can drop the four `x0` literals while remaining a hard
low-Coppersmith no-root clause. Output:
`/tmp/ct07_next_x1_fallback_x0_minimize_2cubes.jsonl`.

The same x0-drop check was then rerun across four `x1` variants
`210:39=0x0,0x4,0x8,0xc`. A first venv replay only returned `unavailable`
because that Python environment lacks Sage; the Sage-backed rerun was:

```text
variants:
  210:39=0x0 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x4 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x8 -> baseline no_roots, hard_clause_eligible=true
  210:39=0xc -> baseline no_roots, hard_clause_eligible=true

greedy windows:
  150:2 -> droppable_sound_no_root, 16/16 hard-eligible completions
  152:2 -> droppable_sound_no_root, 64/64 hard-eligible completions

summary:
  accepted_window_count=2
  dropped_bits=[150,151,152,153]
  remaining_common_literal_count=201
  low_coppersmith_calls=64
  low_coppersmith_cache_hits=20
  factored_variant_count=0
```

This promotes the x0-nibble drop from a single guard-miss check to a small
four-variant soundness audit. Output:
`/tmp/ct07_x1_variants_x0drop_greedy_4variants_sage.json`.

The LZ unknown-divisor pruning probe was also rerun on the previously positive
four-variable subsets:

```text
subsets:
  x0,x1,x4,x7
  x0,x1,x3,x7
  x0,x1,x2,x7
  x0,x1,x6,x7
m values: 3,4
t values: 1
jobs: 8 planned, 8 executed
status: ok 7, timeout 1
best relation count: 48 on x0,x1,x3,x7, m=4
extra_prune_count=0
nonderived_count=0
best_prune_score=0
best signal=projection_derived_no_extra_prune
```

So the LZ track still has relation rows but no non-projection-derived pruning
signal. Output: `/tmp/ct07_lz_depth_prune_probe_light_20260603.json`.

The two high-relation m=4 subsets were then audited row-by-row under a
90-dimensional cap:

```text
x0,x1,x3,x7:
  status=ok
  rows=70, rank=70, cols=70
  LLL rows under threshold=48
  inspected rows=48
  classification_counts={higher_degree: 48}

x0,x1,x2,x7:
  status=ok
  rows=70, rank=70, cols=70
  LLL rows under threshold=44
  inspected rows=44
  classification_counts={higher_degree: 44}
```

This audit confirms that the promising subsets still only produce many
higher-degree relation rows; it does not expose a pruning oracle. Outputs:
`/tmp/ct07_lz_relation_audit_x0x1x3x7_m4_20260603.json` and
`/tmp/ct07_lz_relation_audit_x0x1x2x7_m4_20260603.json`.

Finally, the Sumset shift preflight was run with concrete metric rows for
`T=600` and `T=784` against `liftT_actual`, `liftT_proxy`, and `cuso8`.
All 30 limited rows were classified as failures:

```text
signal_class counts:
  FAIL: 30

preflight_signal counts:
  FAIL_EXPANDING: 12
  FAIL_CAP: 9
  FAIL_DIM: 9

best capped rows:
  liftT_actual T=784 shift_degree=5 cap=5000 -> FAIL_CAP, growth_ratio=1.0
  liftT_actual T=830 shift_degree=5 cap=5000 -> FAIL_CAP, growth_ratio=1.0
```

This does not justify another real lattice reduction for these shift families.
Output: `/tmp/ct07_sumset_shift_sweep_light_20260603.json`.

The q272 exact-carry next-byte sweep was extended to the left-middle endpoint
`x2low7=0x17` under the same fixed shard:

```text
fixed:
  x6=0x245521490bd
  x1=0x9b183cdcc
  branch-low=0
  branch-high=0
constraints:
  T=784
  exact_tail_carry_limbs=1
  exact_carry_bits=272
  lowlift_q=272
  q_interval_bound=true
  odd residues=3,5,7,11
sweep:
  x2[272..279]=0x00..0xff
  files=32
  rows=256
  SAT=0
  UNSAT=256
  vars=368173..374631
  clauses=1672149..1700990
```

The fixed `x6=0x245521490bd`, `x1=0x9b183cdcc` shard now has eleven sampled
`x2low7` points closed through the next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x2f,0x3f,0x4f,0x5f,0x6f,0x7f`. The `0x17`
summary files are `/tmp/ct07_exactcarry_x2low7_17_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_17_x2next8_f8_ff_sweep_summary.json`.

The next midpoint `x2low7=0x27` was then fully checked under the same q272
exact-carry setup:

```text
x2low7=0x27, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=367380..375986
clauses=1668852..1707102
```

The fixed shard now has twelve sampled `x2low7` points closed through the next
byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x3f,0x4f,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_27_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_27_x2next8_f8_ff_sweep_summary.json`.

The next midpoint `x2low7=0x37` was also fully checked:

```text
x2low7=0x37, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=368244..375814
clauses=1672445..1706397
```

The fixed shard now has thirteen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x4f,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_37_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_37_x2next8_f8_ff_sweep_summary.json`.

The next midpoint `x2low7=0x47` was also fully checked:

```text
x2low7=0x47, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=366557..374823
clauses=1665079..1701978
```

The fixed shard now has fourteen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_47_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_47_x2next8_f8_ff_sweep_summary.json`.

The next midpoint `x2low7=0x57` was also fully checked:

```text
x2low7=0x57, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=367064..374486
clauses=1667632..1700730
```

The fixed shard now has fifteen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x57,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_57_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_57_x2next8_f8_ff_sweep_summary.json`.

A Sage-backed four-variant low-Coppersmith minimization audit was then run for
the x2-mid windows `267:2` and `269:2`, keeping the same fixed
`x6=0x245521490bd` high shard and testing `x1=0x0,0x4,0x8,0xc`:

```text
variants:
  210:39=0x0 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x4 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x8 -> baseline no_roots, hard_clause_eligible=true
  210:39=0xc -> baseline no_roots, hard_clause_eligible=true

greedy windows:
  267:2 -> droppable_sound_no_root, 16/16 hard-eligible completions
  269:2 -> droppable_sound_no_root, 64/64 hard-eligible completions

summary:
  accepted_window_count=2
  dropped_bits=[267,268,269,270]
  remaining_common_literal_count=201
  low_coppersmith_calls=64
  low_coppersmith_cache_hits=20
  factored_variant_count=0
  elapsed_seconds=145.477
```

This shows that the same four-literal minimization pattern is not limited to
the x0 nibble; a second bounded audit can soundly drop four x2-mid literals
across the tested `x1` variants. Output:
`/tmp/ct07_x1_variants_x2mid_drop_greedy_4variants_sage.json`.

An alternate high-side sentinel was smoke-tested before committing a full
next-byte sweep:

```text
fixed:
  x6=0x24552149094
  x1=0x9b183cdcc
constraints:
  T=784
  exact_tail_carry_limbs=1
  exact_carry_bits=272
  lowlift_q=272
  q_interval_bound=true
  odd residues=3,5,7,11
smoke points:
  x2low7=0x00, next byte 0x00/0xff -> SAT 0, UNSAT 2
  x2low7=0x3f, next byte 0x00/0xff -> SAT 0, UNSAT 2
  x2low7=0x7f, next byte 0x00/0xff -> SAT 0, UNSAT 2
CNF ranges:
  x2low7=0x00: 689753..700956 vars, 3127031..3177970 clauses
  x2low7=0x3f: 697258..712828 vars, 3161943..3232251 clauses
  x2low7=0x7f: 695101..711079 vars, 3153140..3224967 clauses
```

All six smoke probes were UNSAT, so this alternate `x6=0x24552149094` sentinel
does not currently justify a 256-value next-byte sweep. Outputs:
`/tmp/ct07_altx6_94_smoke_0x00.json`,
`/tmp/ct07_altx6_94_smoke_0x3f.json`, and
`/tmp/ct07_altx6_94_smoke_0x7f.json`.

The same four-variant low-Coppersmith minimization check was also applied to
the x1-low windows `210:2` and `212:2`:

```text
variants:
  210:39=0x0 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x4 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x8 -> baseline no_roots, hard_clause_eligible=true
  210:39=0xc -> baseline no_roots, hard_clause_eligible=true

greedy windows:
  210:2 -> droppable_sound_no_root, 16/16 hard-eligible completions
  212:2 -> droppable_sound_no_root, 64/64 hard-eligible completions

summary:
  accepted_window_count=2
  dropped_bits=[210,211,212,213]
  remaining_common_literal_count=201
  low_coppersmith_calls=16
  low_coppersmith_cache_hits=68
  factored_variant_count=0
  elapsed_seconds=37.059
```

This gives a third small sound minimization family: the tested `x1` branches
can drop four x1-low literals without losing hard no-root eligibility. Output:
`/tmp/ct07_x1_variants_x1low_drop_greedy_4variants_sage.json`.

The x3-low windows showed the same bounded four-variant pattern:

```text
variants:
  210:39=0x0 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x4 -> baseline no_roots, hard_clause_eligible=true
  210:39=0x8 -> baseline no_roots, hard_clause_eligible=true
  210:39=0xc -> baseline no_roots, hard_clause_eligible=true

greedy windows:
  362:2 -> droppable_sound_no_root, 16/16 hard-eligible completions
  364:2 -> droppable_sound_no_root, 64/64 hard-eligible completions

summary:
  accepted_window_count=2
  dropped_bits=[362,363,364,365]
  remaining_common_literal_count=201
  low_coppersmith_calls=64
  low_coppersmith_cache_hits=20
  factored_variant_count=0
  elapsed_seconds=150.856
```

This means all four low-C contiguous blocks tested so far have a small local
four-literal sound drop family under the same `x1=0,4,8,c` audit pattern:
`x0` bits 150..153, `x1` bits 210..213, `x2` bits 267..270, and `x3` bits
362..365. Output:
`/tmp/ct07_x1_variants_x3low_drop_greedy_4variants_sage.json`.

Several q-ranking probes were rerun for the fixed exact-carry shard
`x6=0x245521490bd`, `x1=0x9b183cdcc`, `x0=x7=0`:

```text
q_edge_rank_probe:
  base p_fixed=706, q_low=265, q_prefix=255, q_known=520
  x2_prefix8  -> best q_prefix=255, q_known=528
  x2_prefix16 -> best q_prefix=255, q_known=536
  x5_low8     -> best q_prefix=255, q_known=520
  x5_high9    -> best q_prefix=264, q_known=529
  x2x5_edges  -> best q_prefix=255, q_known=524

low_x1_x2_beam over x2 samples 0,1,0x7f,0xff,0x3fff,0x7fff,0xffff:
  final best q_low=297, q_prefix=255, q_known=552
  retained top candidates all had product-prefix 218:sat and 272:sat

full x5 high-edge beam with x1=0x9b183cdcc:
  best range=682:87:0x40c04141804040c140c1
  q_prefix=355, q_known=620, q_low=265
```

The q-ranking outcome is consistent with earlier high-side beams: x5 high-edge
bits are the only cheap source of q-prefix growth, but they still produce a
ranking signal rather than a factor. The top four full-x5 candidates were
passed to the folded-Coron success verifier with `profiles=base`, direct
variant, and resultants:

```text
682:87:0x40c04141804040c140c1 -> reconstructed 13, roots 0, factors 0
682:87:0x40c04141804040c140ce -> reconstructed 13, roots 0, factors 0
682:87:0x40c04141804040c14344 -> reconstructed 13, roots 0, factors 0
682:87:0x40c04141804040c14349 -> reconstructed 13, roots 0, factors 0
```

Outputs:
`/tmp/ct07_q_edge_rank_x1_b183cdcc_extended.json`,
`/tmp/ct07_low_x1_x2_beam_multi_x2_20260603.json`,
`/tmp/ct07_x5_full_beam_x1_b183cdcc_20260603.json`, and
`/tmp/ct07_coron_oracle_x1_b183cdcc_x5_top4_direct.jsonl`.

`exactcarry_x2next_sweep.py` was added as a safer wrapper for the repeated
q272 exact-carry next-byte sweeps. The script delegates to
`run_07_go_sat_filter.py`, but centralizes shard naming, `/tmp` prefix choice,
resume/skip checks, dry-run command inspection, and aggregate validation. It
was smoke-tested against the already complete `x2low7=0x37` artifact:

```text
python3 cryptotest/solutions/07_sat_cas_explore/exactcarry_x2next_sweep.py \
  --x2low7 0x37 \
  --prefix /tmp/ct07_exactcarry_x2low7_37_x2next8 \
  --aggregate-only --json

complete=true
files=32
rows=256
SAT=0
UNSAT=256
vars=368244..375814
clauses=1672445..1706397
```

The resume path was also checked on the first shard and correctly skipped the
existing `00..07` file while preserving the same aggregate result. A dry-run
for `x2low7=0x57` emitted the expected command shape with `T=784`,
`exact_tail_carry_limbs=1`, `exact_carry_bits=272`, `lowlift_q=272`,
`q_interval_bound=true`, odd residues `3,5,7,11`, fixed
`x6=0x245521490bd`, `branch-low=0`, and `branch-high=0`.

The next midpoint `x2low7=0x47` then completed under the same exact-carry
settings:

```text
x2low7=0x47, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=366557..374823
clauses=1665079..1701978
```

The fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`, `x0=x7=0` shard now has
fourteen sampled `x2low7` points closed through the next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_47_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_47_x2next8_f8_ff_sweep_summary.json`.

The next coarse-grid gap `x2low7=0x57` was then closed by the same runner:

```text
x2low7=0x57, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=367064..374486
clauses=1667632..1700730
```

The fixed shard now has fifteen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x57,0x5f,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_57_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_57_x2next8_f8_ff_sweep_summary.json`.

The next coarse-grid gap `x2low7=0x67` also completed:

```text
x2low7=0x67, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=369044..376797
clauses=1676118..1710869
```

The fixed shard now has sixteen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x57,0x5f,0x67,0x6f,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_67_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_67_x2next8_f8_ff_sweep_summary.json`.

The next upper-side midpoint `x2low7=0x77` also completed. The first pass
closed `0x00..0xdf`; the final four shards `0xe0..0xff` needed a resume retry
with a longer timeout:

```text
x2low7=0x77, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=367701..376326
clauses=1670461..1708781
```

The fixed shard now has seventeen sampled `x2low7` points closed through the
next byte:
`0x00,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x57,0x5f,0x67,0x6f,0x77,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_77_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_77_x2next8_f8_ff_sweep_summary.json`.

The first combined low-Coppersmith union check was then run, rather than
assuming that independent four-bit drops compose. The tested union dropped
`p[210..211]` and `p[267..268]` simultaneously across the same four
`x1=0,4,8,c` variants:

```text
drop_windows=210:2,267:2
variant_count=4
completion_count_per_variant=16
total_completion_checks=64
unique_oracle_cases=64
status_counts_unique={"no_roots":64}
hard_eligible_unique_count=64
not_triggered_count=0
all_completions_no_roots=true
factor_count=0
elapsed_seconds=90.901
```

This gives a small but sound combined proof for a four-literal union. It does
not yet prove that the separately observed x0/x1/x2/x3 four-bit families can
all be merged; the next realistic combined audit is the deduplicating
`x0+x1` eight-bit union, where the expected unique Sage calls are 256 rather
than the full 1024 completion checks.

That `x0+x1` eight-bit union was then checked exactly:

```text
drop_windows=150:2,152:2,210:2,212:2
variant_count=4
completion_count_per_variant=256
total_completion_checks=1024
unique_oracle_cases=256
deduped_completion_checks=768
status_counts_unique={"no_roots":256}
status_counts_total={"no_roots":1024}
hard_eligible_unique_count=256
hard_eligible_total_count=1024
not_triggered_count=0
roots_returned_unique_total=0
all_completions_no_roots=true
factor_count=0
dropped_bits=[150,151,152,153,210,211,212,213]
remaining_common_literal_count=197
elapsed_seconds=149.435
```

Output: `/tmp/ct07_union_x0_x1_8bit_exact.json`. This is the first direct
proof that two of the newly found four-bit families compose under the fixed
`x6=0x245521490bd`, `x7=0` guard and the same base-selected low assignment.
The obvious next combined proof is `x0+x1+x2` at 12 dropped bits; it should be
sharded, since it expands to 4096 completions per variant.

The LZ/TK side track also ran a cheap row-index spot scan on the two m=4
positive-margin subsets with many short rows. The goal was to see whether
non-leading rows escape the already observed projection-derived behavior:

```text
active=x0,x1,x3,x7 row=1  status=ok derived=true extra_prune=false projection_fail_prunes=false integer_zero=false
active=x0,x1,x3,x7 row=16 status=ok derived=true extra_prune=false projection_fail_prunes=false integer_zero=false
active=x0,x1,x2,x7 row=1  status=ok derived=true extra_prune=false projection_fail_prunes=false integer_zero=false
active=x0,x1,x2,x7 row=16 status=ok derived=true extra_prune=false projection_fail_prunes=false integer_zero=false
```

Output: `/tmp/ct07_lz_m4_row_index_spot_agent.jsonl`. This gives no useful
escape signal for the current m=4 LZ basis: changing only the relation row
index does not produce extra modular pruning or an integer-zero relation. The
next TK/LZ attempt should therefore change the basis/shift family rather than
spend more time scanning rows from this same construction.

The `x0+x1+x2` twelve-bit low-Coppersmith union proof also completed. This is
the full composition of the three four-bit drop families
`p[150..153]`, `p[210..213]`, and `p[267..270]` under the same fixed guard:

```text
drop_windows=150:2,152:2,210:2,212:2,267:2,269:2
variant_count=4
completion_count_per_variant=4096
covered_completion_count_per_variant=4096
coverage_fraction=1.0
input_shards=8
unique_oracle_cases_total=4096
total_completion_checks=16384
hard_eligible_total_count=16384
status_counts_total={"no_roots":16384}
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
remaining_common_literal_count=193
```

Output shards are in `/tmp/ct07_union_x0_x1_x2_12bit_pilot/`, with jsonl logs
`/tmp/ct07_union_x0_x1_x2_12bit_pilot.jsonl`,
`/tmp/ct07_union_x0_x1_x2_12bit_range1024_2048.jsonl`,
`/tmp/ct07_union_x0_x1_x2_12bit_range2048_3072.jsonl`, and
`/tmp/ct07_union_x0_x1_x2_12bit_range3072_4096.jsonl`. This soundly reduces
the learned no-good shape from 205 to 193 literals for this fixed guard. The
next natural composition test is adding the x3 four-bit family, but that would
expand to 65536 completions per variant and should be treated as a separate
sharded run.

The first `x0+x1+x2+x3` sixteen-bit low-Coppersmith union pilot was then
started in shards. This combines all four previously found four-bit drop
families:

```text
drop_windows=150:2,152:2,210:2,212:2,267:2,269:2,362:2,364:2
variant_count=4
completion_count_per_variant=65536
covered_completion_count_per_variant=13312
coverage_fraction=0.203125
input_shards=26
unique_oracle_cases_total=13312
total_completion_checks=53248
hard_eligible_total_count=53248
status_counts_total={"no_roots":53248}
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
remaining_common_literal_count=189
```

Output shards are in `/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/`, currently
covering completion ranges `0..512`, `512..1024`, `1024..1536`, and
`1536..2048`, `2048..2560`, `2560..3072`, `3072..3584`, `3584..4096`,
`4096..4608`, `4608..5120`, `5120..5632`, `5632..6144`, and
`6144..6656`, `6656..7168`, `7168..7680`, `7680..8192`, `8192..8704`,
`8704..9216`, `9216..9728`, `9728..10240`, `10240..10752`, and
`10752..11264`, `11264..11776`, `11776..12288`, `12288..12800`,
`12800..13312`.
The earlier `1024..1032` spot check is now subsumed by the full `1024..1536`
shard. This is not yet a full sixteen-bit proof, but it gives a clean positive
signal for continuing the sharded low-C union expansion; the next shard starts
at completion `13312`. The
new `4096..4608`, `4608..5120`, `5120..5632`, `5632..6144`, `6144..6656`,
`6656..7168`, `7168..7680`, and `7680..8192` shards took 369.8, 378.9, 363.2,
349.5, 398.9, 503.8, 468.2, and 527.2
seconds respectively; each had 512 unique oracle cases and 2048 total
completion checks, and all returned only hard-eligible `no_roots`. The
`7680..8192` shard was rerun with system Python after a stale `unavailable`
artifact had been produced by the wrong Python environment. The `8192..8704`
shard then added another 512 unique cases in 504.4 seconds, again all
hard-eligible `no_roots`; `8704..9216` added the next 512 cases in 419.5
seconds with the same all-`no_roots`, roots/factors 0 result, and `9216..9728`
added another 512 cases in 430.4 seconds with the same result. The next
`9728..10240` shard added another 512 cases in 392.9 seconds, again with
roots/factors 0 and all hard-eligible `no_roots`; `10240..10752` added another
512 cases in 333.8 seconds with the same result. The next two shards
`10752..11264` and `11264..11776` added another 1024 cases in 378.5 and 407.7
seconds respectively, again with roots/factors 0 and all hard-eligible
`no_roots`; `11776..12288` added another 512 cases in 374.4 seconds with the
same result, `12288..12800` added another 512 cases in 516.0 seconds with the
same result, and `12800..13312` added another 512 cases in 588.0 seconds with
the same result.

The lower off-grid exact-carry point `x2low7=0x03` also completed a full
next-byte sweep under the same fixed `x6=0x245521490bd`,
`x1=0x9b183cdcc`, `x0=x7=0`, q272 exact-carry setting:

```text
x2low7=0x03, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=368154..373187
clauses=1672183..1694677
missing=0
```

The fixed shard now has eighteen sampled `x2low7` points closed through the
next byte:
`0x00,0x03,0x07,0x0f,0x17,0x1f,0x27,0x2f,0x37,0x3f,0x47,0x4f,0x57,0x5f,0x67,0x6f,0x77,0x7f`.
Summary files are `/tmp/ct07_exactcarry_x2low7_03_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_x2low7_03_x2next8_f8_ff_sweep_summary.json`.

The free-`x1` direct SAT filter was also revisited with stronger odd residues
`3/5/7/11/13/17/19`. This exposed a small bug in `run_07_go_sat_filter.py`:
the free-`x1` exporter-success path could reach the solver before loading
`cnf` and `var_map`. The path was fixed and verified with `py_compile`.

The full five-`x6`, five-`T` strengthened filter then timed out at 1200s before
writing a row summary. A single build-only row for
`x6=0x245521490bd`, `T=784`, q272, q interval, and residues
`3/5/7/11/13/17/19` completed and measured the CNF at:

```text
vars=78068
clauses=615992
```

For comparison, the earlier `3/5/7/11` broad free filter was around 33k vars
and 170k clauses per row and still SAT for every candidate/T pair. The stronger
residue set is therefore not a good broad filter in the current direct form; it
needs either incremental residue staging, model-driven cubes, or a narrower
candidate set before solving.

Two exact-carry smoke probes were also run as branch-selection checks. First,
a finer left-side off-grid point `x2low7=0x0b` was checked at three next-byte
values under the same fixed `x6=0x245521490bd`, `x1=0x9b183cdcc`,
`x0=x7=0`, q272 exact-carry setting:

```text
x2low7=0x0b, x2[272..279] in {0x00,0x7f,0xff}
SAT=0
UNSAT=3
vars=368021..374957
clauses=1671385..1702600
factor=0
```

Output: `/tmp/ct07_exactcarry_x2low7_0b_x2next8_smoke.json`. This is only a
smoke check, not a full next-byte closure, but it found no survivor.

The same `x2low7=0x0b` point was then promoted to a full next-byte sweep and
closed:

```text
x2low7=0x0b, x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=367194..375376
clauses=1668164..1704231
missing=0
```

No SAT or factor row appeared in this full next-byte closure.

The next off-grid point `x2low7=0x13` was started under the same fixed
`x6=0x245521490bd`, `x1=0x9b183cdcc`, q272 exact-carry setting. The recorded
contiguous checkpoint is:

```text
x2low7=0x13, x2[272..279]=0x00..0xaf
files=22
rows=176
SAT=0
UNSAT=176
vars=368385..374096
clauses=1673008..1698705
missing=80
```

This checkpoint is still partial; the runner was continuing from `0xb0` when
this note was recorded.

The nearest unclosed off-grid point `x2low7=0x1b` was also launched under the
same wrapper with prefix `/tmp/ct07_exactcarry_x2low7_1b_x2next8`. Its current
contiguous checkpoint is:

```text
x2low7=0x1b, x2[272..279]=0x00..0x67
files=13
rows=104
SAT=0
UNSAT=104
vars=366490..373677
clauses=1664882..1696760
missing=152
```

This checkpoint is still partial; the runner was continuing from `0x68` when
this note was recorded.

Second, an alternate weak-model branch
`x6=0x24552149094`, `x1=0x166f09bd14`, `x2low7=0x78` was checked at four
next-byte values:

```text
x2[272..279] in {0x00,0x55,0xaa,0xff}
SAT=0
UNSAT=4
vars=366984..372659
clauses=1666632..1692392
factor=0
```

Outputs:
`/tmp/ct07_exactcarry_alt94_x1_166f_x2_78_endpoints.json` and
`/tmp/ct07_exactcarry_alt94_x1_166f_x2_78_midpoints.json`. This is a useful
signal for branch ranking, but not a proof for all 256 next-byte values.

The same alternate branch was then extended from point checks to a full
next-byte sweep:

```text
x6=0x24552149094
x1=0x166f09bd14
x2low7=0x78
x2[272..279]=0x00..0xff
files=32
rows=256
SAT=0
UNSAT=256
vars=366594..373052
clauses=1665106..1693947
missing=0
```

Output summaries are `/tmp/ct07_exactcarry_alt94_x1_166f_x2low78_x2next8_00_07_sweep_summary.json`
through `/tmp/ct07_exactcarry_alt94_x1_166f_x2low78_x2next8_f8_ff_sweep_summary.json`.
The remaining `0x40..0xff` runner produced 192/192 UNSAT rows, stderr 0 bytes,
and the full aggregate is
`/tmp/ct07_exactcarry_alt94_x1_166f_x2low78_x2next8_full_aggregate.json`.
This closes this alternate weak-model branch through the next byte under the
q272 exact-carry setup; no SAT or factor rows were produced.

The TK/LZ side track changed basis shape instead of continuing the old m=4
row-index scan. A three-variable `t=2` depth probe over
`x0,x1,x7; x0,x6,x7; x0,x4,x7; x0,x5,x7` with `m=2,3,4` completed all 12
jobs:

```text
planned=12
executed=12
ok=12
timeout=0
error=0
status=no_relation_under_threshold:12
nonderived_count=0
extra_prune_count=0
best_prune_score=0
best=x0,x5,x7 m=3 t=2 rows=20 dimension=20 rank=20
```

Output: `/tmp/ct07_lz_t2_threevar_depth_20260603.json`. This gives no LZ/TK
pruning signal for the tested 3-variable `t=2` family.

Finally, the `liftT_actual` sumset cap-resolution probe moved the previous
`FAIL_CAP` rows to uncapped `FAIL_DIM` at cap 100000:

```text
T=830 cap=100000 capped=false double_sumset_size=23186 growth_ratio=3.6768 preflight_signal=FAIL_DIM
T=784 cap=100000 capped=false double_sumset_size=30783 growth_ratio=4.8424 preflight_signal=FAIL_DIM
```

Output: `/tmp/ct07_sumset_liftT_actual_deg5_cap_resolve_20260603.json`.
This removes the main ambiguity for that shift family: it is not merely hitting
the old cap, and should not be promoted to an actual large LLL/BKZ build.

The q-Hensel prefix consistency track was also checked on a more fixed branch:

```text
fixed p ranges:
  150:4:0x0
  210:39:0x9b183cdcc
  682:87:0x40c04141804040c140c1
  784:46:0x245521490bd
  920:4:0x0
base_p_fixed_bits=793
base_q_known_bits=620
base_q_low_bits=265
base_q_prefix_start=669
base_q_prefix_bits=355
prefix_core=hensel
prefix_bits=384,448,512
timeout_ms=20000
status_counts={"unknown":3}
```

The per-prefix checks had p fixed bits inside prefix 278, 286, and 350
respectively, with q fixed bits inside prefix still 265. None proved
contradiction, and no candidate gained extra q bits. Output:
`/tmp/ct07_qhensel_x1b183_x5full_384_512_20260603.json`. This keeps the
current Hensel-prefix check in diagnostic/ranking mode rather than as a hard
learned-clause oracle.

Finally, a four-variable LZ `t=2` depth probe was run after the negative
three-variable pass. The tested subsets were
`x0,x1,x3,x7; x0,x1,x2,x7; x0,x1,x5,x7; x0,x1,x4,x7`, with `m=3,4`:

```text
planned=8
executed=8
timeout=0
error=0
status=no_relation_under_threshold:8
relation_count=0 for every subset/m
nonderived_count=0
extra_prune_count=0
best_prune_score=0
best=x0,x1,x2,x7 m=3 t=2 rows=35 dimension=35 rank=35
```

Output: `/tmp/ct07_lz_4var_t2_depth_20260603.json`. This is another negative
TK/LZ signal: increasing to these four-variable `t=2` families did not produce
even a threshold relation, so the next unknown-divisor attempt still needs a
different basis/shift design rather than deeper scans of this family.

The TK/LZ side then changed the depth parameter to `t=3` while keeping the
small `x0/x7` variables and adding high-side variables:

```text
active_subsets=x0,x5,x6,x7; x0,x4,x5,x7
m=2,3
t=3
planned=4
executed=4
timeout=0
error=0
status=no_relation_under_threshold:4
relation_count=0 for every subset/m
nonderived_count=0
extra_prune_count=0
best_prune_score=0
```

Output: `/tmp/ct07_lz_agent_t3_highside_depth_20260604.json`; stderr was 0
bytes. This also produced no non-projection or pruning signal.

The q/Hensel side was rechecked with smaller partial high-side candidates
instead of the previously fully fixed x5 branch. The base fixed branch was
`150:4:0x0`, `210:39:0x9b183cdcc`, `784:46:0x245521490bd`, `920:4:0x0`.
Candidate one-byte ranges at `600`, `682`, `742`, and `760` were ranked, and
the top four were all `760:8=0x0..0x3`:

```text
base_q_known_bits=520
base_q_low_bits=265
base_q_prefix_start=769
base_q_prefix_bits=255
top_candidate_q_known_bits=521
top_candidate_q_prefix_bits=256
prefix_bits=560,608
status_counts={"unknown":8}
```

Output:
`/tmp/ct07_q_sumset_agent_qhensel_partial_x4x5_560_608_20260604.json`;
stderr was 0 bytes. The one-bit q-prefix gain is too weak for a hard
learned-clause oracle.

Finally, the sumset preflight was rerun with alternate degree/T rows:

```text
families=liftT_actual,bilinear,linear8,cuso8,liftT_proxy
T=608,700,824
shift_degrees=3,6
rows=30
PASS=6
FAIL=24
```

All PASS rows were the toy `bilinear` family. Non-toy rows were
`FAIL_DIM=13` and `FAIL_EXPANDING=11`; the best non-toy `cuso8/linear8`
degree-6 rows had growth ratio 2.0 but still `FAIL_DIM` with shifted support
6435. Output: `/tmp/ct07_q_sumset_agent_sumset_alt_deg6_20260604.json`;
stderr was 0 bytes. This gives no actionable large-lattice viability signal.

The next continued pass kept the same separation between sound SAT/CAS
no-good generation and heuristic verifier/ranking signals.

The 16-bit `x0+x1+x2+x3` low-C union proof advanced by one more full shard.
Using the internal shard JSON files under
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/`, the aggregate is now:

```text
completion_count_per_variant=65536
covered_completion_count_per_variant=12800
checked_completion_count_per_variant=12800
coverage_fraction=0.1953125
input_shards=25
merged_ranges=0..12800
missing_ranges=12800..65536
unique_oracle_cases_total=12800
total_completion_checks=51200
hard_eligible_total_count=51200
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
remaining_common_literal_count=189
```

The new shard `12288..12800` took 516.0 seconds and had 512 unique oracle
cases / 2048 total completion checks, all hard-eligible `no_roots`; stderr was
0 bytes. The next contiguous expansion point is completion `12800`.

The SAT+CAS low-C callback was also tested on the fixed cube
`x1=0x9b183cdcc`, `x6=0x245521490bd`, `x7=0`, low cube values zero over
`x0/x2/x3`. The baseline product-prefix check remained SAT, but the low-C
oracle produced hard `no_roots` learned clauses:

```text
drop window 276:2 -> dropped_literals=2, learned_clause_literals=164
drop window 276:8 -> dropped_literals=8, learned_clause_literals=158
drop window 272:4 -> dropped_literals=4, learned_clause_literals=162
drop window 280:2 -> dropped_literals=2, learned_clause_literals=164
drop window 280:4 -> dropped_literals=4, learned_clause_literals=162
drop window 280:8 -> dropped_literals=8, learned_clause_literals=158
drop window 284:2 -> dropped_literals=2, learned_clause_literals=164
drop window 288:2 -> dropped_literals=2, learned_clause_literals=164
drop window 288:4 -> dropped_literals=4, learned_clause_literals=162
factored_events=[]
```

The `280:4` run required `--low-coppersmith-minimize-max-completions 16`; with
that bound it completed normally with 16 low-C calls, one cache hit, one hard
block, one minimized block, and stderr 0 bytes. The wider `280:8` and `276:8`
runs each required 256 completions and took 1036.8 and 1095.5 seconds
respectively; all completions were hard-eligible `no_roots`, giving separate
158-literal learned clauses with stderr 0 bytes. The neighboring `272:4` and
`288:4` windows were also sound 162-literal clauses. These prove separate
learned clauses, not a combined 12/16/20-bit drop. Outputs:
`/tmp/ct07_satcas_agent_20260604.x1_9b_drop280.analysis.json` and
`/tmp/ct07_satcas_dropwin_20260604_{272_4_max16,276_2,276_8_max256,280_4_max16,280_8_max256,284_2,288_2,288_4_max16}.analysis.json`.

The exact-carry next-byte runners continued on two off-grid `x2low7` values
under the same fixed `x1/x6/x0/x7` branch:

```text
x2low7=0x13, x2[272..279]=0x00..0xdf
  rows=224, sat=0, unsat=224
  vars=368385..374096
  clauses=1673008..1698705
  complete=false, next missing value=0xe0

x2low7=0x1b, x2[272..279]=0x00..0x9f
  rows=160, sat=0, unsat=160
  vars=366490..373946
  clauses=1664882..1698090
  complete=false, next missing value=0xa0
```

These are live-run checkpoints, not full closures; no SAT/factor row appeared.

The edge-folded Coron verifier threshold was rechecked with `x1=0x9b183cdcc`.
For both direct and projected threshold sweeps, primitive margin was already
positive at width 24, but relation reconstruction turned on later:

```text
x2 edge:
  width 24 margin 42.67 reconstructed 0
  width 28 margin 48.00 reconstructed 0
  width 32 margin 53.33 reconstructed 13
  width 36 margin 58.67 reconstructed 13

x5 edge:
  width 24 margin 42.67 reconstructed 0
  width 28 margin 47.67 reconstructed 0
  width 32 margin 52.33 reconstructed 0
  width 36 margin 58.67 reconstructed 13
```

Actual verifier calls still found no root/factor. The explicit `x2_low32`
values `0x13` and `0x1b` both had margin `53.33`, 13 short rows, 13
reconstructed polynomials, roots 0, verified factors 0. An `x2` width-36 zero
profile had margin `58.67`, 13 reconstructed polynomials, roots 0. A q-ranked
`x5` width-36 candidate `733:36:0x10000808` reached q-prefix 290 / q-known 555
and margin `58.33`, also roots 0 and verified factors 0. This confirms the
verifier threshold but gives no discriminating ranking signal. Outputs:
`/tmp/ct07_edge_coron_agent_20260604.x2low13_1b.json`,
`/tmp/ct07_edge_threshold_*_24_36_20260604.json`,
`/tmp/ct07_edge_oracle_x2_width36_zero_x1_9b_20260604.json`, and
`/tmp/ct07_edge_candidate_x5_extended36_x1_9b_20260604.json`.

A follow-up reconstruction-positive candidate expansion gave the same result.
The `x2_low32` values `0x13`, `0x1b`, and `0x0` were all `ok`, with margin
`53.33`, 13 short rows, 13 reconstructed polynomials, roots 0, verified factors
0. The x5 width-36 beam with four candidates produced:

```text
733:36:0x8080a  margin=58.67  reconstructed=13  roots=0 factors=0
733:36:0x180008 margin=58.67  reconstructed=13  roots=0 factors=0
733:36:0x80808  margin=58.33  reconstructed=13  roots=0 factors=0
733:36:0x8080b  margin=58.33  reconstructed=13  roots=0 factors=0
```

Outputs: `/tmp/ct07_edge_candidate_x2_low32_values_13_1b_0_20260604.json` and
`/tmp/ct07_edge_candidate_x5_extended36_{max4,beam4_max4}_x1_9b_20260604.json`;
all stderr files were 0 bytes. The current edge-Coron verifier still lacks a
root/factor hit and lacks a candidate ranking signal.

The TK/LZ unknown-divisor side changed active sets and anchors again. Weighted
LZ on `x0,x5,x6,x7` with anchors `x0,x7`, budgets `90,100`, `m=2,t=1` completed
4/4 runs and produced one relation under the 1024-bit threshold in each run,
but both projection audits classified the relation as
`projection_derived_no_extra_prune` with prune score 0. A further active-set
pass on `x0,x1,x6,x7`, `x0,x1,x5,x6,x7`, `x0,x1,x2,x3,x6,x7`, and the full
`x0..x7` set, checked with both x0 and x7 anchors, completed all eight runs;
each again had one projection-derived relation, `best_prune_score=0`,
`nonderived_relation_count=0`, and `extra_modular_prune_seen=0`. Outputs:
`/tmp/ct07_tklz_agent_20260604.summary.json` and
`/tmp/ct07_tklz_active_uncov_20260604.{grid_x0_m2,search_x7_m2}.json`. This
keeps TK/LZ in basis-design mode rather than as a usable pruning oracle.

The next continued pass advanced the same hard low-C union proof and checked
one q-ranked full-x5 verifier candidate.

The 16-bit `x0+x1+x2+x3` low-C union proof added the `13312..13824` shard:

```text
completion_count_per_variant=65536
covered_completion_count_per_variant=13824
checked_completion_count_per_variant=13824
coverage_fraction=0.2109375
input_shards=27
merged_ranges=0..13824
missing_ranges=13824..65536
unique_oracle_cases_total=13824
total_completion_checks=55296
hard_eligible_total_count=55296
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
remaining_common_literal_count=189
```

The new shard took 562.785 seconds and had 512 unique oracle cases / 2048 total
completion checks, all hard-eligible `no_roots`; roots/factors were 0 and the
JSONL record is
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range13312_13824.jsonl`. The next contiguous
shard `13824..14336` was launched with the same fixed ranges.

The live exact-carry next-byte sweeps also advanced:

```text
x2low7=0x13, x2[272..279]=0x00..0xcf
  files=26, rows=208, sat=0, unsat=208
  vars=368385..374096
  clauses=1673008..1698705
  complete=false, next missing value=0xd0

x2low7=0x1b, x2[272..279]=0x00..0x7f
  files=16, rows=128, sat=0, unsat=128
  vars=366490..373946
  clauses=1664882..1698090
  complete=false, next missing value=0x80
```

No SAT/factor row appeared in either partial sweep.

The q-ranked full-x5 high-edge beam with `x0=0`, `x1=0x9b183cdcc`, and `x7=0`
again selected `682:87:0x40c04141804040c140c1`, with `q_low_bits=265`,
`q_prefix_bits=355`, and `q_known_bits=620`. A direct folded-Coron verifier call
on that full-x5 candidate produced primitive margin 144.0, 13 short rows, and
13 reconstructed polynomials, but root count 0 and verified factor count 0.
Outputs: `/tmp/ct07_q_x5_full87_x1_9b_beam8_pp32_20260604.json` and
`/tmp/ct07_edge_oracle_fullx5_682_87_x1_9b_20260604.json`; stderr was 0 bytes.

A follow-up x0/x7 q-prefix sweep with fixed `x1=0x9b183cdcc`, all 16 x0
nibbles, and `x7 in {0,4,8}` also stayed at the same ceiling:
`q_prefix_bits=355`, `q_known_bits=620`, `q_low_bits=265`. The best ranked tie
was `x7=4` with full x5 `682:87:0x1c1c081800000400001`; all x0 nibbles tied
on the same q metrics. A direct folded-Coron verifier on `x0=0,x7=4` again
produced primitive margin 144.0, 13 short rows, and 13 reconstructed
polynomials, but root count 0 and verified factor count 0. Outputs:
`/tmp/ct07_q_x5_x0all_x7_0_4_8_x1_9b_w87_20260604.json` and
`/tmp/ct07_edge_oracle_fullx5_x7_4_x0_0_x1_9b_20260604.json`; stderr was 0
bytes.

After the exact-carry runners stopped, the final aggregate for this pass was:

```text
x2low7=0x13, x2[272..279]=0x00..0xff
  complete=true, files=32, rows=256
  sat=0, unsat=256
  vars=368385..375550
  clauses=1673008..1705175
  missing=0

x2low7=0x1b, x2[272..279]=0x00..0xaf
  complete=false, files=22, rows=176
  sat=0, unsat=176
  vars=366490..374055
  clauses=1664882..1698258
  missing=80, next missing value=0xb0
```

Thus `x2low7=0x13` joins the full next-byte exact-carry closures. The
`x2low7=0x1b` branch remains partial, but no SAT/factor row appeared.

The low-C 16-bit union proof also advanced again before this pass ended. The
latest aggregate over the internal shard JSON files is:

```text
completion_count_per_variant=65536
covered_completion_count_per_variant=14848
checked_completion_count_per_variant=14848
coverage_fraction=0.2265625
input_shards=29
merged_ranges=0..14848
missing_ranges=14848..65536
unique_oracle_cases_total=14848
total_completion_checks=59392
hard_eligible_total_count=59392
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
```

The final two shards in this pass were `13824..14336` and `14336..14848`;
they took 564.8 and 570.9 seconds respectively, each with 512 unique oracle
cases / 2048 total checks, all hard-eligible `no_roots`. The next contiguous
expansion point is completion `14848`.

Finally, the exact free-`x1` filter closed the nearby full-`x6` shortlist under
the q272 exact-carry model. The settings were `T=784`, `arith_bits=272`,
`skip_known_prefix_bits=208`, `--lowlift-q 272`, q interval bound, odd residues
`3/5/7/11`, `--exact-tail-carry-limbs 1`, `--exact-carry-bits 272`, and free
`x1`. All candidates were UNSAT:

```text
x6=0x245521490bd sat=false models=0 vars=518170 clauses=2329135
x6=0x24552149094 sat=false models=0 vars=518224 clauses=2329318
x6=0x24552149097 sat=false models=0 vars=518234 clauses=2329470
x6=0x24552149098 sat=false models=0 vars=518260 clauses=2329555
x6=0x2455214909b sat=false models=0 vars=518231 clauses=2329474
```

Outputs: `/tmp/ct07_free_x1_exactcarry1_x6bd_q272_20260604.stdout` and
`/tmp/ct07_free_x1_exactcarry1_x6near_q272_20260604.stdout`. This is a strong
negative signal for the current x1-free / full-x6 shortlist, but it still does
not recover `p`, `q`, or plaintext.

The next checkpoint changed priority from extending the same fixed-`x6bd`
branch to testing full-`x6` candidates with the stronger exact carry-column
free-`x1` filter.

The 16-bit `x0+x1+x2+x3` low-C union proof added two more 512-completion
shards, `13824..14336` and `14336..14848`. Both returned only hard-eligible
`no_roots`, with roots/factors 0. The updated aggregate is:

```text
completion_count_per_variant=65536
covered_completion_count_per_variant=14848
checked_completion_count_per_variant=14848
coverage_fraction=0.2265625
input_shards=29
merged_ranges=0..14848
missing_ranges=14848..65536
unique_oracle_cases_total=14848
total_completion_checks=59392
hard_eligible_total_count=59392
all_shards_no_roots=true
roots_returned_unique_total=0
factor_count_total=0
remaining_common_literal_count=189
```

The new shard JSONL records are
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range13824_14336.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range14336_14848.jsonl`; their elapsed
times were 564.768s and 570.890s respectively, and stderr was 0 bytes. No next
low-C union shard was launched after this checkpoint because the stronger
exact free-`x1` filter below made the fixed `x6=0x245521490bd` branch
redundant to continue.

The exact-carry next-byte sweep for off-grid `x2low7=0x13` fully closed under
the same fixed `x6=0x245521490bd`, `x1=0x9b183cdcc` branch:

```text
x2low7=0x13, x2[272..279]=0x00..0xff
files=32, rows=256, sat=0, unsat=256
vars=368385..375550
clauses=1673008..1705175
complete=true
```

The partially running `x2low7=0x1b` sweep had reached `0x00..0xaf` with
`rows=176`, SAT 0, UNSAT 176. The later `x2low7=0x23` off-grid runner was
started but then both remaining fixed-`x6bd` byte sweeps were stopped after the
direct free-`x1` exact filter proved the whole fixed-`x6bd` branch UNSAT.

The all-`x7` full-x5 q-prefix sweep also finished. With fixed
`x1=0x9b183cdcc`, all 16 x0 nibbles, all 16 x7 nibbles, and x5 width 87, all
256 branches built successfully. The q ceiling did not improve:

```text
q_low_bits=265
q_prefix_bits=355
q_known_bits=620
q_interval_width_bits=669
best x7=7, x0=0, x5=682:87:0x8080404041804002
```

The direct folded-Coron verifier on that best tie had primitive margin 144.0,
13 short rows, and 13 reconstructed polynomials, but root count 0 and verified
factor count 0. Outputs:
`/tmp/ct07_q_x5_x0all_x7all_x1_9b_w87_20260604.json` and
`/tmp/ct07_edge_oracle_fullx5_x7_7_x0_0_x1_9b_20260604.json`.

The important new pruning result is the exact carry-column free-`x1` filter.
For fixed full `x6=0x245521490bd`, free `x1`, free `x2low7`, `T=784`,
`arith_bits=272`, `skip_known_prefix_bits=208`, `--lowlift-q 272`, q interval,
odd residues `3,5,7,11`, and `--exact-tail-carry-limbs 1
--exact-carry-bits 272`, the direct PySAT solve returned UNSAT:

```text
x6=0x245521490bd
vars=518170
clauses=2329135
sat=false
model_count=0
```

Output: `/tmp/ct07_free_x1_exactcarry1_x6bd_q272_20260604.stdout`; stderr was
0 bytes. The sequential follow-up over the other nearby full-x6 candidates
also returned UNSAT for every candidate:

```text
x6=0x24552149094 vars=518224 clauses=2329318 sat=false model_count=0
x6=0x24552149097 vars=518234 clauses=2329470 sat=false model_count=0
x6=0x24552149098 vars=518260 clauses=2329555 sat=false model_count=0
x6=0x2455214909b vars=518231 clauses=2329474 sat=false model_count=0
```

Output: `/tmp/ct07_free_x1_exactcarry1_x6near_q272_20260604.stdout`; stderr was
0 bytes. This closes the five nearby full-x6 shortlist
`0x24552149094/097/098/09b/0bd` under the exact free-`x1/x2low7` filter.

The corrected exact q272 filter also closed the seven tracked high32 `x6`
bucket prefixes that had previously been tested only by the invalid pre-fix
skip-prefix path. Settings were `--free-x1-x6high-filter`, `T=800`,
`arith_bits=272`, `skip_known_prefix_bits=208`, `--lowlift-q 272`, q interval
bound, odd residues `3/5/7/11`, `--exact-tail-carry-limbs 1`,
`--exact-carry-bits 272`, `branch_low=0`, `branch_high=0`, and
`x6high_bits=32`. Each bucket leaves 14 low `x6` bits, all `x1`, and
`x2low7` free.

```text
x6high32=0x9154852 vars=546204 clauses=2455111 sat=false model_count=0
x6high32=0x40010   vars=546304 clauses=2455691 sat=false model_count=0
x6high32=0x40060   vars=546188 clauses=2455058 sat=false model_count=0
x6high32=0x50010   vars=546269 clauses=2455480 sat=false model_count=0
x6high32=0x90070   vars=546223 clauses=2455272 sat=false model_count=0
x6high32=0x5d55090 vars=546334 clauses=2455767 sat=false model_count=0
x6high32=0xcf49080 vars=546312 clauses=2455707 sat=false model_count=0
```

Outputs:
`/tmp/ct07_free_x1_exactcarry1_x6high32_9154852_q272_20260604.stdout` and
`/tmp/ct07_free_x1_exactcarry1_x6high32_x7rank_rest_q272_20260604.stdout`;
both stderr files were 0 bytes. This closes `7 * 2^14 = 114688` full `x6`
values under the corrected free-`x1/x2low7` exact-carry bucket filter, but it
is still a pruning result, not factor/plaintext recovery.

For the next bucket queue, fast-tail scoring was regenerated at high32 inside
the post-bug top16 high16 prefixes for `branch_low=0`, `branch_high=0`. A
single global top128 was tie-heavy and filled with high16 `0x0001`:
`/tmp/ct07_x6high32_fast_refine_top16high16_20260604.jsonl`. A diverse
per-high16 top8 set was therefore generated in
`/tmp/ct07_x6high32_fast_refine_diverse_top16high16_20260604.*.jsonl`. The top
candidate from each high16 prefix is:

```text
0x00010006 0x000b0004 0x00150001 0x001e0008
0x00280005 0x00320003 0x003c0000 0x00450006
0x004f0004 0x00590001 0x00620008 0x006c0005
0x00760002 0x00800000 0x00890006 0x00930004
```

Two exact q272 attempts over that fast-tail high32 queue were stopped before
they became a complete batch result. The first
`/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_q272_20260604.stdout` run
had 0-byte stdout/stderr after about 8 minutes and was stopped. The second
`/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_second_q272_20260604.stdout`
completed only the first row before it was stopped:

```text
x6high32=0x10010 vars=546209 clauses=2455164 sat=false model_count=0
```

A later chunked attempt completed two more rows before it was stopped:
`/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_chunk1_q272_20260604.stdout`.

```text
x6high32=0x280005 vars=546230 clauses=2455220 sat=false model_count=0
x6high32=0x320003 vars=546191 clauses=2455067 sat=false model_count=0
```

Therefore `0x10010`, `0x280005`, and `0x320003` are hard bucket-pruning results
from the fast-tail queue; the other fast-tail high32 buckets remain unclosed.

## 2026-06-04 parallel follow-up batch

Subagents covered three independent side tracks while the local path stayed on
SAT/exact-carry. All outputs were written under `/tmp`; no factor or plaintext
was recovered.

The low-C union proof was extended by one more 512-completion shard:

```text
new shard: 14848..15360
elapsed_seconds=399.614
unique_oracle_cases=512
total_completion_checks=2048
hard_eligible_total_count=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The aggregate is now:

```text
covered_completion_count_per_variant=15360/65536
coverage_fraction=0.234375
input_count=30
merged_ranges=[{"start":0,"stop":15360}]
missing_ranges=[{"start":15360,"stop":65536}]
total_completion_checks=61440
hard_eligible_total_count=61440
roots_returned_unique_total=0
factor_count_total=0
all_shards_no_roots=true
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range14848_15360.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard14848_512.json`.

The exact free-`x1/x2low7` q272 filter was also applied to six diversity
full-`x6` candidates that had only been product-prefix spot-checked before:

```text
x7=1 x6=0x10018000f   UNSAT vars=518172 clauses=2329123 models=0
x7=2 x6=0x14004100e   UNSAT vars=518145 clauses=2329007 models=0
x7=3 x6=0x100040818   UNSAT vars=518142 clauses=2329004 models=0
x7=4 x6=0x33d24200413 UNSAT vars=518174 clauses=2329132 models=0
x7=5 x6=0x17554242005 UNSAT vars=518126 clauses=2328963 models=0
x7=6 x6=0x2401c0c0a   UNSAT vars=518156 clauses=2329046 models=0
```

Aggregate:
`/tmp/ct07_x6_exact_next_diversity_20260604_summary.json` reports
`sat_total=0`, `unsat_total=6`, and `timeout_or_error_count=0`. This closes the
six branch-representative full-`x6` candidates under the corrected q272
exact-carry filter, but it is still candidate pruning rather than factor
recovery.

The corresponding high32 diversity prefixes for `x7=1..6` were checked in
build-only mode with `--free-x1-x6high-filter`, `T=800`, the same q272
exact-carry settings, and `x6high_bits=32`:

```text
x7=1 x6high=0x40060   build ok vars=546252 clauses=2455405
x7=2 x6high=0x50010   build ok vars=546276 clauses=2455486
x7=3 x6high=0x40010   build ok vars=546279 clauses=2455487
x7=4 x6high=0xcf49080 build ok vars=546329 clauses=2455766
x7=5 x6high=0x5d55090 build ok vars=546268 clauses=2455432
x7=6 x6high=0x90070   build ok vars=546318 clauses=2455682
```

Output: `/tmp/ct07_x6high32_exact_buildonly_diversity_20260604_summary.json`.
These rows only prove the exact-carry bucket CNFs are buildable at about 546k
vars / 2.455M clauses; they do not close the prefixes.

The TK/LZ unknown-divisor side track tried active set `x0,x2,x4,x6,x7`, anchor
`x0`, `m=2,3`, and `t=1,2`:

```text
planned/executed=4/4
timeout/error=0/0
m=2,t=1: relation_count=1, projection_derived_no_extra_prune
m=2,t=2: relation_count=0, no_relation_under_threshold
m=3,t=1: relation_count=1, projection_derived_no_extra_prune
m=3,t=2: relation_count=0, no_relation_under_threshold
nonderived_count=0
extra_prune_count=0
best_prune_score=0
```

Output: `/tmp/ct07_lz_x02467_t12_depth_20260604.json`; stderr was 0 bytes.
This active set should be deprioritized. The current TK/LZ basis family keeps
returning either projection-derived relations or no relation.

The edge-Coron/q-ranking side track tested a non-duplicate full-x5 branch
`x7=1`, `x0=0`, fixed `x1=0x9b183cdcc`, and x5 width 87. The best q-ranking
candidate was `682:87:0x1824042404200424082` with the same ceiling as earlier:

```text
q_low=265
q_prefix=355
q_known=620
interval_width_bits=669
```

Coron verification on that candidate had primitive margin 144.0, 13 short rows,
and 13 reconstructed polynomials, but `root_count=0` and
`verified_factor_count=0`. Outputs:
`/tmp/ct07_q_x5_x7_1_x0_0_x1_9b_w87_beam4_pp16_20260604.json` and
`/tmp/ct07_edge_oracle_fullx5_x7_1_x0_0_x1_9b_beam4_pp16_20260604.json`.

## 2026-06-04 fast-tail top16 closure batch

The fast-tail high32 queue from the previous section has now been fully closed
under the corrected exact q272 bucket filter. Settings were again
`--free-x1-x6high-filter`, `T=800`, `arith_bits=272`,
`skip_known_prefix_bits=208`, `--lowlift-q 272`, q interval, odd residues
`3/5/7/11`, `--exact-tail-carry-limbs 1`, `--exact-carry-bits 272`,
`branch_low=0`, `branch_high=0`, and `x6high_bits=32`.

```text
x6high32=0x00010006 vars=546188 clauses=2455056 sat=false model_count=0
x6high32=0x000b0004 vars=546235 clauses=2455233 sat=false model_count=0
x6high32=0x00150001 vars=546197 clauses=2455111 sat=false model_count=0
x6high32=0x001e0008 vars=546173 clauses=2455013 sat=false model_count=0
x6high32=0x00280005 vars=546230 clauses=2455220 sat=false model_count=0
x6high32=0x00320003 vars=546191 clauses=2455067 sat=false model_count=0
x6high32=0x003c0000 vars=546144 clauses=2454900 sat=false model_count=0
x6high32=0x00450006 vars=546231 clauses=2455245 sat=false model_count=0
x6high32=0x004f0004 vars=546181 clauses=2455029 sat=false model_count=0
x6high32=0x00590001 vars=546203 clauses=2455116 sat=false model_count=0
x6high32=0x00620008 vars=546156 clauses=2454950 sat=false model_count=0
x6high32=0x006c0005 vars=546178 clauses=2455022 sat=false model_count=0
x6high32=0x00760002 vars=546170 clauses=2454992 sat=false model_count=0
x6high32=0x00800000 vars=546211 clauses=2455140 sat=false model_count=0
x6high32=0x00890006 vars=546206 clauses=2455162 sat=false model_count=0
x6high32=0x00930004 vars=546168 clauses=2454973 sat=false model_count=0
```

This closes all 16 selected high32 buckets, i.e. `16 * 2^14 = 262144` full
`x6` values, with `x6low14`, all `x1`, and `x2low7` free. It is a strong queue
pruning result, not factor/plaintext recovery. Representative output files:

```text
/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_chunk0_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_second_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_chunk1_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_003c0000_retry1_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_fasttop16_chunk2_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_004f0004_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00590001_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00620008_retry2_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_006c0005_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00760002_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00800000_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00890006_q272_20260604.stdout
/tmp/ct07_free_x1_exactcarry1_x6high32_single_00930004_q272_20260604.stdout
```

The low-C union proof was also extended by one more shard:

```text
new shard: 15360..15872
elapsed_seconds=338.317
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The aggregate is now contiguous `0..15872`:

```text
covered_completion_count_per_variant=15872/65536
coverage_fraction=0.2421875
input_count=31
missing_ranges=[{"start":15872,"stop":65536}]
total_completion_checks=63488
unique_oracle_cases_total=15872
hard_eligible_total_count=63488
roots_returned_unique_total=0
factor_count_total=0
all_shards_no_roots=true
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range15360_15872.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard15360_512.json`.

The remaining q/CAS side probes were negative:

- Edge-Coron `x7=1` q-ranking ties
  `0x1824042404200424087`, `0x182404240420042408f`, and
  `0x182404240420042430a` all verified with primitive margin 144, 13
  reconstructed polynomials, `root_count=0`, and `verified_factor_count=0`.
  Outputs are `/tmp/ct07_edge_oracle_fullx5_x7_1_tie_*_20260604.json`.
- TK/LZ/Sumset preflight for active set `x0,x2,x4,x5,x7` had best HM-style
  proxy margin `-285.8877` bits at `m=6,t=1,dim=462`, active sum 248 bits,
  and monomial count 37. Depth probe `m=2,3`, `t=1,2` produced only
  projection-derived relation or no relation:
  `nonderived_count=0`, `extra_prune_count=0`, `best_prune_score=0`.
  Outputs:
  `/tmp/ct07_tklz_x02457_margin_20260604.json` and
  `/tmp/ct07_tklz_x02457_depth_20260604.json`.

## 2026-06-04 dynamic-q CNF audit and low-C 25% checkpoint

The next low-C union shard completed cleanly:

```text
new shard: 15872..16384
elapsed_seconds=376.253
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous hard no-root proof now covers exactly one quarter of the
16-bit completion space:

```text
covered_completion_count_per_variant=16384/65536
coverage_fraction=0.25
input_count=32
total_completion_checks=65536
unique_oracle_cases_total=16384
roots_returned_unique_total=0
factor_count_total=0
all_shards_no_roots=true
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range15872_16384.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard15872_512.json`.
The shard stderr was 0 bytes.

Two more edge/q-ranking full-x5 probes were tried with `x0=0`,
`x1=0x9b183cdcc`, and the fixed full `x6=0x245521490bd`. The q-prefix beam
again reached the same ceiling as the previous `x7=0/1/4/7` probes:

```text
x7=2 best x5=682:87:0x40c200c041814100c142 q_low=265 q_prefix=355 q_known=620 interval_width_bits=669
x7=3 best x5=682:87:0x40c14041c00101c20102 q_low=265 q_prefix=355 q_known=620 interval_width_bits=669
```

Folded-Coron verification remained negative:

```text
x7=2 primitive_margin=144.0 short_rows=13 reconstructed=13 root_count=0 verified_factor_count=0
x7=3 primitive_margin=144.0 short_rows=13 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_2_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_2_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_3_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_3_x0_0_x1_9b_beam4_pp16_20260604.json`.

A separate dynamic-q CNF audit script was added:
`dynamic_q_cnf_probe.py`. It derives q known bits independently from fixed p
ranges, maps the low q bits to `q_<bit>` variables in the Go exporter var-map,
and compares base solve with solve-under-q-assumptions. This was intended to
check whether an ISSAC-style dynamic q shared-bit hook could add pruning on the
current Go CNF path. The answer is no for this path: the Go exporter already
turns q low known bits into unit clauses and folds q high-prefix bits into the
constant high product.

Smoke/audit rows:

```text
x6high32=0x00010006 q_known=250 q_unit_assumptions=150 q_missing_var_count=100
base_sat=false base_elapsed=0.000038 q_assumption_sat=false q_assumption_elapsed=0.000059
x6high28=0x0001000  q_known=250 q_unit_assumptions=150 q_missing_var_count=100
q_assumption_sat=false q_assumption_elapsed=0.000064
```

The `q_missing_var_count=100` corresponds to q high-prefix bits above the low
limb split, not to missing constraints. Output files:
`/tmp/ct07_dynamic_q_cnf_probe_x6high32_00010006_compare_q272_20260604.json`,
`/tmp/ct07_dynamic_q_cnf_probe_x6high32_00010006_q272_20260604.json`, and
`/tmp/ct07_dynamic_q_cnf_probe_x6high28_0001000_q272_20260604.json`.

The useful remaining dynamic-q direction is therefore not this Go CNF path, but
the p-only `semi_programmatic_sat.py` loop: there, `derive_q_known_bits()` is
currently consumed only by product/Hensel prefix oracles, not by a q-variable
CDCL core. Newton's side audit also found that large mixed Hensel prefix
checks timeout quickly, so staged checks at 224/240/256 bits should be used
before trying 272+ bits.

The exact q272 bucket queue also advanced beyond the closed high32 top16. Four
rank2 high32 candidates, excluding the already closed top16 and `0x00010010`,
were checked under the same corrected settings:

```text
x6high32=0x000b000e vars=546236 clauses=2455231 sat=false model_count=0
x6high32=0x0015000b vars=546200 clauses=2455095 sat=false model_count=0
x6high32=0x001e0011 vars=546205 clauses=2455076 sat=false model_count=0
x6high32=0x0028000f vars=546197 clauses=2455048 sat=false model_count=0
```

Outputs:
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_000b000e_q272_20260604.stdout`,
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_0015000b_q272_20260604.stdout`,
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_001e0011_q272_20260604.stdout`, and
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_0028000f_q272_20260604.stdout`.
Each has a matching `.summary.json`, and stderr files were 0 bytes. This adds
`4 * 2^14 = 65536` full `x6` values to the corrected high32 closure set.
A later respawned rank2 job also closed `x6high32=0x0032000c`
(`546172` vars / `2454952` clauses, SAT false, model 0). After the high20
`0x320` parent prefix below was closed, this high32 row is kept as an audit row
rather than added to unique coverage.

For wider buckets, build-only checks showed the same q272 exact-carry CNF path
is constructible for the first four fast-tail prefixes at high28/high24/high20:

```text
high28 T=816: 0x1000/0xb000/0x15000/0x1e000 build ok, vars=572821..573005, clauses=2573127..2574098
high24 T=816: 0x100/0xb00/0x1500/0x1e00 build ok, vars=573365..573542, clauses=2575900..2576742
high20 T=832: 0x10/0xb0/0x150/0x1e0 build ok, vars=600734..600831, clauses=2697059..2697556
```

The first four fast-tail prefixes at all three widths were then solved under
the same corrected q272 exact-carry settings. Important counting caveat:
high28/high24 child-prefix rows are nested under their high20 parents, so they
are not disjoint coverage once the high20 parent is closed.

```text
high28 child audit: 0x1000/0xb000/0x15000/0x1e000 all sat=false, model_count=0
high24 child audit: 0x100/0xb00/0x1500/0x1e00 all sat=false, model_count=0
high20 top4: 0x10/0xb0/0x150/0x1e0 all sat=false, model_count=0, unique closes 4 * 2^26 = 268435456 full x6 values
x6high20=0x10 vars=600831 clauses=2697556 sat=false model_count=0
x6high20=0xb0 vars=600795 clauses=2697314 sat=false model_count=0
x6high20=0x150 vars=600734 clauses=2697059 sat=false model_count=0
x6high20=0x1e0 vars=600796 clauses=2697426 sat=false model_count=0
```

The rest of the fast-tail high20 parent prefixes from the high32 top16 queue
were then solved sequentially. Prefix `0x620` repeatedly left truncated normal
runner artifacts before summary write, so it was verified by direct complete Go
export plus streaming PySAT solve; the direct CNF had `600889` vars and
`2697749` clauses and the streaming solve loaded all declared clauses.

```text
x6high20=0x280 vars=600736 clauses=2697037 sat=false model_count=0
x6high20=0x320 vars=600756 clauses=2697106 sat=false model_count=0
x6high20=0x3c0 vars=600642 clauses=2696609 sat=false model_count=0
x6high20=0x450 vars=600836 clauses=2697544 sat=false model_count=0
x6high20=0x4f0 vars=600775 clauses=2697205 sat=false model_count=0
x6high20=0x590 vars=600778 clauses=2697226 sat=false model_count=0
x6high20=0x620 vars=600889 clauses=2697749 sat=false model_count=0
x6high20=0x6c0 vars=600632 clauses=2696607 sat=false model_count=0
x6high20=0x760 vars=600779 clauses=2697216 sat=false model_count=0
x6high20=0x800 vars=600709 clauses=2696989 sat=false model_count=0
x6high20=0x890 vars=600817 clauses=2697486 sat=false model_count=0
x6high20=0x930 vars=600865 clauses=2697572 sat=false model_count=0
```

Corrected aggregate: `/tmp/ct07_high20_top16_exact_closure_corrected_20260604.json`.
The high20 top16 unique closure is `16 * 2^26 = 1073741824` full `x6`
values. This supersedes the previous top8 aggregate and the nested
child-prefix additive total in `/tmp/ct07_wide_prefix_exact_closure_20260604.json`.
This is pruning only; no factor or plaintext has been recovered.

## 2026-06-04 parallel round: low-C, p-only Hensel, TK/LZ, and edge probes

The 16-bit `x0+x1+x2+x3` low-C union proof advanced by one more 512-completion
shard:

```text
new shard: 16384..16896
elapsed_seconds=318.139
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=16896/65536
coverage_fraction=0.2578125
input_count=33
unique_oracle_cases_total=16896
total_completion_checks=67584
all_counted_status=no_roots
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range16384_16896.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard16384_512.json`.
The shard stderr was 0 bytes.

The next non-overlapping high32 rank2 queue also closed four more buckets under
the corrected q272 exact-carry filter:

```text
x6high32=0x0032000c vars=546172 clauses=2454952 sat=false model_count=0
x6high32=0x003c000a vars=546225 clauses=2455198 sat=false model_count=0
x6high32=0x00450010 vars=546166 clauses=2454991 sat=false model_count=0
x6high32=0x004f000e vars=546198 clauses=2455101 sat=false model_count=0
```

Outputs are the corresponding
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_*_q272_20260604` files. The
`0x003c000a` solve used the `.nolimit` suffix, but it is the same base SAT
check without model enumeration. Stderr files were all 0 bytes. These rows are
useful queue-pruning evidence; unique coverage accounting should still prefer
the wider high20 closure when the high32 row lies under an already closed
high20 parent.

Two additional edge/q-ranking full-x5 probes were run with `x0=0`,
`x1=0x9b183cdcc`, and `x6=0x245521490bd`:

```text
x7=5 best x5=682:87:0x1c081c0c200004001c0 q_low=265 q_prefix=355 q_known=620 width_bits=669
x7=6 best x5=682:87:0x200c1c0c20001008087 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification again reconstructed 13 short polynomials with
primitive margin 144.0, but no roots or verified factors:

```text
x7=5 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x7=6 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_5_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_5_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_6_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_6_x0_0_x1_9b_beam4_pp16_20260604.json`.

The p-only SAT+CAS staged Hensel probe compared a high-side cube set against a
mixed low/high cube set. The mixed set is more promising for ranking because
it raises q-known bits substantially, but it still produced no hard UNSAT
clauses:

```text
mixed ranges=150:4,210:8,265:8,798:8,920:4
best fixed ranges=150:4:0x0,210:8:0x0,265:8:0x0,798:8:0x0,920:4:0x7
q_low/q_prefix/q_known=218/194/412
gain=+68/+94/+162
Hensel top2 at 224/240/256 bits: sat=2, unknown=4, unsat=0
same at timeout 2000ms: sat=2, unknown=4, unsat=0
semi_programmatic_sat check-bits=224: 32 cubes all sat

highside ranges=798:16,920:4
best fixed ranges=798:16:0x0,920:4:0x7
q_low/q_prefix/q_known=150/194/344
gain=+0/+94/+94
Hensel top2 at 224/240/256 bits: unknown=6, unsat=0
semi_programmatic_sat check-bits=224: 32 cubes all unknown
```

Summary output: `/tmp/ct07_p_only_staged_summary_with_t2000_20260604.json`.
This supports using the mixed low/high cube for future p-only SAT+CAS ranking,
but it is not yet a hard pruning oracle.

The TK/LZ unknown-divisor preflight tried active set `x0,x3,x5,x6,x7`.
It again lacked a useful relation:

```text
active_sum_bits=219
monomial_count=41
best_proxy_margin_bits=-256.6343898045509 at m=6,t=1,dim=462
depth statuses={"ok": 2, "no_relation_under_threshold": 2}
nonderived_count=0
extra_prune_count=0
best_prune_score=0
root_like_signal_count=0
```

Outputs:
`/tmp/ct07_tklz_x03567_margin_20260604.json`,
`/tmp/ct07_tklz_x03567_depth_20260604.json`, and
`/tmp/ct07_tklz_x03567_summary_20260604.json`. This active set should also be
deprioritized unless the basis family changes.

## 2026-06-04 parallel round 3: low-C 26.5%, high32 audit, x1-wide p-only, and edge x7=8/9

The 16-bit `x0+x1+x2+x3` low-C union proof advanced by another contiguous
512-completion shard:

```text
new shard: 16896..17408
elapsed_seconds=305.108
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=17408/65536
coverage_fraction=0.265625
input_count=34
unique_oracle_cases_total=17408
total_completion_checks=69632
all_counted_status=no_roots
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range16896_17408.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard16896_512.json`.
The shard stderr was 0 bytes.

The corrected q272 exact-carry high32 rank2 audit closed four more
non-overlapping queue entries:

```text
x6high32=0x0059000b vars=546200 clauses=2455129 sat=false model_count=0
x6high32=0x00620011 vars=546179 clauses=2455007 sat=false model_count=0
x6high32=0x006c000f vars=546233 clauses=2455232 sat=false model_count=0
x6high32=0x0076000c vars=546230 clauses=2455222 sat=false model_count=0
```

Outputs are the corresponding
`/tmp/ct07_free_x1_exactcarry1_x6high32_next_rank2_*_q272_20260604` files.
All stderr files were 0 bytes. These are useful audit/prioritization rows, but
unique coverage should still be counted through the already closed high20
parents when applicable.

Two more edge/q-ranking full-x5 probes were run with `x0=0`,
`x1=0x9b183cdcc`, and `x6=0x245521490bd`:

```text
x7=8 best x5=682:87:0x418141c140c081018004 q_low=265 q_prefix=355 q_known=620 width_bits=669
x7=9 best x5=682:87:0x41c08142020181810044 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification was reconstruction-positive but factor-negative:

```text
x7=8 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x7=9 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_8_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_8_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_9_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_9_x0_0_x1_9b_beam4_pp16_20260604.json`.

The p-only SAT+CAS q-growth probe widened the `x1` low-side cube. The best row
among the tested variants was `210:16`, which increases low-derived q bits but
does not create hard Hensel pruning:

```text
baseline ranges=150:4,210:8,265:8,798:8,920:4 q_low/q_prefix/q_known=218/194/412
x1wide12 ranges=150:4,210:12,265:8,798:8,920:4 q_low/q_prefix/q_known=222/194/416
x1wide16 ranges=150:4,210:16,265:8,798:8,920:4 q_low/q_prefix/q_known=226/194/420
x2wide12 ranges=150:4,210:8,265:12,798:8,920:4 q_low/q_prefix/q_known=218/194/412
```

For both `210:12` and `210:16`, staged Hensel top4 at 224/240/256/272 bits
gave the same result at 500 ms and 2000 ms:

```text
status_counts={"sat": 4, "unknown": 12, "unsat": 0}
prefix 224: sat 4
prefix 240: unknown 4
prefix 256: unknown 4
prefix 272: unknown 4
```

Summary output:
`/tmp/ct07_p_only_mixed_qhensel_deep_summary_20260604.json`. The q-growth is
useful for ranking, but this Hensel callback is still not a sound hard pruning
oracle at these widths.

The TK/LZ unknown-divisor preflight with `x1` included also stayed negative:

```text
active=x0,x1,x5,x6,x7 active_sum_bits=180 monomial_count=47 best_proxy_margin_bits=-217.293778450839
depth statuses={"ok": 2, "no_relation_under_threshold": 2}
nonderived_count=0 extra_prune_count=0 root_like_signal_count=0

active=x0,x1,x3,x6,x7 active_sum_bits=171 monomial_count=51 best_proxy_margin_bits=-208.2151758307516
depth statuses={"ok": 2, "no_relation_under_threshold": 2}
nonderived_count=0 extra_prune_count=0 root_like_signal_count=0
```

Summary output: `/tmp/ct07_tklz_x1_small_active_summary_20260604.json`. These
active sets should be deprioritized unless the TK/LZ basis family changes.

## 2026-06-04 parallel round 4: low-C 27.3%, high20 next4, x1wide20, and edge x7=10/11

The next low-C union shard also completed:

```text
new shard: 17408..17920
elapsed_seconds=302.527
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=17920/65536
coverage_fraction=0.2734375
first_missing_range=17920..65536
total_completion_checks=71680
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range17408_17920.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard17408_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_17920.json`.
JSON/JSONL parsed cleanly and stderr files were 0 bytes.

The corrected q272 exact-carry high20 closure advanced beyond the fast-tail
top16 parent prefixes. The next four high20 parents from
`/tmp/ct07_x6high16_fast_tail_top40_20260604.jsonl` were all UNSAT:

```text
x6high20=0x9d0 vars=600762 clauses=2697187 sat=false model_count=0
x6high20=0xa60 vars=600859 clauses=2697642 sat=false model_count=0
x6high20=0xb00 vars=600798 clauses=2697414 sat=false model_count=0
x6high20=0xba0 vars=600748 clauses=2697098 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4_exact_closure_20260604.json`.
This adds `4 * 2^26 = 268435456` full `x6` values of unique pruning coverage.
Together with the earlier high20 top16 closure, the high20 parent total is now
`20 * 2^26 = 1342177280` full `x6` values. This is still pruning evidence, not
factor recovery.

The p-only SAT+CAS q-growth probe widened the fixed `x1` low-side cube to
`210:20`. It improved q-known bits but still gave no hard contradiction:

```text
baseline mixed top q_low/q_prefix/q_known=218/194/412
prior x1wide16 top q_low/q_prefix/q_known=226/194/420
new x1wide20 top q_low/q_prefix/q_known=230/194/424
```

Staged Hensel top4 at 224/240/256/272 bits with a 2000 ms timeout:

```text
status_counts={"sat": 8, "unknown": 8, "unsat": 0}
prefix 224: sat 4
prefix 240: sat 4
prefix 256: unknown 4
prefix 272: unknown 4
```

Outputs:
`/tmp/ct07_p_only_qgrowth_mixed_x1w20_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w20_top4_224_272_t2000_20260604.json`.
This improves ranking over `x1wide16`, but does not yet produce a learned
hard no-good clause.

The edge/q-ranking full-x5 sweep continued with `x7=10,11` under `x0=0`,
`x1=0x9b183cdcc`, and `x6=0x245521490bd`:

```text
x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
x7=11 best x5=682:87:0x400100c0400140c18248 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification remained reconstruction-positive but factor-negative:

```text
x7=10 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x7=11 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_10_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_10_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_11_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_11_x0_0_x1_9b_beam4_pp16_20260604.json`.

## 2026-06-04 follow-up: high20 top24 exact closure

The corrected q272 exact-carry high20 closure was extended by the next four
ranked high20 parents after the already documented top16 plus next4 batch:

```text
x6high20=0xc40 vars=600733 clauses=2697021 sat=false model_count=0
x6high20=0xcd0 vars=600866 clauses=2697668 sat=false model_count=0
x6high20=0xd70 vars=600818 clauses=2697368 sat=false model_count=0
x6high20=0xe10 vars=600783 clauses=2697219 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4b_exact_closure_20260604.json`.
The combined top24 high20 aggregate is
`/tmp/ct07_high20_top24_exact_closure_20260604.json`.

This second next4 batch adds another `4 * 2^26 = 268435456` full `x6` values
of unique pruning coverage. Combining the corrected top16 plus both next4
batches gives `24 * 2^26 = 1610612736` full `x6` values closed at high20 parent
granularity. This remains pruning evidence only; no factor or plaintext was
recovered.

## 2026-06-04 follow-up: high20 top28 and x1wide24 p-only check

The next four ranked high20 parents from
`/tmp/ct07_x6high16_fast_tail_top40_20260604.jsonl` were also closed under the
same corrected q272 exact-carry settings:

```text
x6high20=0xeb0 vars=600721 clauses=2696878 sat=false model_count=0
x6high20=0xf40 vars=600766 clauses=2697320 sat=false model_count=0
x6high20=0xfe0 vars=600814 clauses=2697355 sat=false model_count=0
x6high20=0x1080 vars=600707 clauses=2696983 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4c_exact_closure_20260604.json`.
The combined top28 high20 aggregate is
`/tmp/ct07_high20_top28_exact_closure_20260604.json`.

This third next4 batch adds another `4 * 2^26 = 268435456` full `x6` values of
unique pruning coverage. Combining the corrected top16 plus three next4 batches
gives `28 * 2^26 = 1879048192` full `x6` values closed at high20 parent
granularity.

The p-only q-growth probe was also extended from `210:20` to `210:24`:

```text
x1wide20 top q_low/q_prefix/q_known=230/194/424
x1wide24 top q_low/q_prefix/q_known=234/194/428
```

Staged Hensel top4 at 224/240/256/272 bits with a 2000 ms timeout still gave no
hard contradiction:

```text
status_counts={"sat": 8, "unknown": 8}
prefix 224: sat 4
prefix 240: sat 4
prefix 256: unknown 4
prefix 272: unknown 4
```

Outputs:
`/tmp/ct07_p_only_qgrowth_mixed_x1w24_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w24_top4_224_272_t2000_20260604.json`.
This improves q-known ranking by another 4 bits over `x1wide20`, but it is not
a sound learned no-good clause yet. No factor or plaintext was recovered.

## 2026-06-04 parallel round 5: low-C 28.1%, edge x7=12/13, high20 top32, and x1wide28

The low-C union proof advanced by one more contiguous shard:

```text
new shard: 17920..18432
elapsed_seconds=292.771
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=18432/65536
coverage_fraction=0.28125
first_missing_range=18432..65536
input_count=36
total_completion_checks=73728
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range17920_18432.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard17920_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_18432.json`.
JSON/JSONL parsed cleanly and stderr files were 0 bytes.

The edge/q-ranking full-x5 sweep continued with `x7=12,13` under `x0=0`,
`x1=0x9b183cdcc`, and `x6=0x245521490bd`:

```text
x7=12 best x5=682:87:0x404200814001c0c04201 q_low=265 q_prefix=355 q_known=620 width_bits=669
x7=13 best x5=682:87:0x14041c0c0c041420203 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification remained reconstruction-positive but factor-negative:

```text
x7=12 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x7=13 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_12_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_12_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_13_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_13_x0_0_x1_9b_beam4_pp16_20260604.json`.

An additional high20 exact-carry batch completed after the top28 closure:

```text
x6high20=0x1110 vars=600836 clauses=2697559 sat=false model_count=0
x6high20=0x11b0 vars=600720 clauses=2696899 sat=false model_count=0
x6high20=0x1250 vars=600758 clauses=2697154 sat=false model_count=0
x6high20=0x12f0 vars=600851 clauses=2697503 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4d_exact_closure_20260604.json`.
The combined top32 high20 aggregate is
`/tmp/ct07_high20_top32_exact_closure_20260604.json`.

This fourth next4 batch adds another `4 * 2^26 = 268435456` full `x6` values
of unique pruning coverage. Combining the corrected top16 plus four next4
batches gives `32 * 2^26 = 2147483648` full `x6` values closed at high20
granularity.

The p-only q-growth probe was also extended from `210:24` to `210:28`:

```text
x1wide24 top q_low/q_prefix/q_known=234/194/428
x1wide28 top q_low/q_prefix/q_known=238/194/432
```

Staged Hensel top4 at 224/240/256/272 bits with a 2000 ms timeout still gave no
hard contradiction:

```text
status_counts={"sat": 8, "unknown": 8}
prefix 224: sat 4
prefix 240: sat 4
prefix 256: unknown 4
prefix 272: unknown 4
```

Outputs:
`/tmp/ct07_p_only_qgrowth_mixed_x1w28_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w28_top4_224_272_t2000_20260604.json`.
This improves q-known ranking by another 4 bits over `x1wide24`, but it is not
a sound learned no-good clause yet. No factor or plaintext was recovered.

## 2026-06-04 parallel round 6: low-C 28.9%, edge x7=14/15, high20 top40, and x1wide36

The low-C union proof advanced by one more contiguous shard:

```text
new shard: 18432..18944
elapsed_seconds=281.988
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=18944/65536
coverage_fraction=0.2890625
first_missing_range=18944..65536
input_count=37
total_completion_checks=75776
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range18432_18944.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard18432_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_18944.json`.
JSON/JSONL parsed cleanly and stderr files were 0 bytes.

The edge/q-ranking full-x5 sweep continued with `x7=14,15` under `x0=0`,
`x1=0x9b183cdcc`, and `x6=0x245521490bd`:

```text
x7=14 best x5=682:87:0x1c2410042014201c042 q_low=265 q_prefix=355 q_known=620 width_bits=669
x7=15 best x5=682:87:0x2000082018141000240 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification remained reconstruction-positive but factor-negative:

```text
x7=14 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x7=15 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x7_14_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x7_14_x0_0_x1_9b_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_15_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_15_x0_0_x1_9b_beam4_pp16_20260604.json`.

The next four high20 parents after the top32 closure also closed under the
same corrected q272 exact-carry settings:

```text
x6high20=0x1380 vars=600800 clauses=2697410 sat=false model_count=0
x6high20=0x1420 vars=600766 clauses=2697179 sat=false model_count=0
x6high20=0x14c0 vars=600734 clauses=2697066 sat=false model_count=0
x6high20=0x1550 vars=600845 clauses=2697614 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4e_exact_closure_20260604.json`.
This fifth next4 batch adds another `4 * 2^26 = 268435456` full `x6` values of
unique pruning coverage. Combining the corrected top16 plus five next4 batches
gives `36 * 2^26 = 2415919104` full `x6` values closed at high20 parent
granularity.

The final four parents in the current fast-tail top40 high20 queue also closed:

```text
x6high20=0x15f0 vars=600840 clauses=2697590 sat=false model_count=0
x6high20=0x1690 vars=600775 clauses=2697245 sat=false model_count=0
x6high20=0x1730 vars=600803 clauses=2697318 sat=false model_count=0
x6high20=0x17c0 vars=600791 clauses=2697401 sat=false model_count=0
```

Aggregate output: `/tmp/ct07_high20_next4f_exact_closure_20260604.json`.
The combined top40 aggregate is `/tmp/ct07_high20_top40_exact_closure_20260604.json`.
This sixth next4 batch adds another `4 * 2^26 = 268435456` full `x6` values of
unique pruning coverage. Combining the corrected top16 plus six next4 batches
gives `40 * 2^26 = 2684354560` full `x6` values closed at high20 parent
granularity.

The p-only q-growth probe was extended from `210:32` to `210:36`:

```text
x1wide32 top q_low/q_prefix/q_known=242/194/436
x1wide36 top q_low/q_prefix/q_known=246/194/440
```

Staged Hensel top4 at 224/240/256/272 bits with a 2000 ms timeout still gave no
hard contradiction, but the SAT frontier moved one prefix deeper:

```text
status_counts={"sat": 12, "unknown": 4}
prefix 224: sat 4
prefix 240: sat 4
prefix 256: sat 4
prefix 272: unknown 4
```

Outputs:
`/tmp/ct07_p_only_qgrowth_mixed_x1w36_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w36_top4_224_272_t2000_20260604.json`.
This improves q-known ranking by another 4 bits over `x1wide32`, but it still
does not yield a sound learned no-good clause. No factor or plaintext was
recovered.

## 2026-06-04 parallel round 7: low-C 29.7%, high20 top44, x1wide39 ceiling, and edge x7 coverage

The low-C union proof advanced by one more contiguous shard:

```text
new shard: 18944..19456
elapsed_seconds=367.289
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=19456/65536
coverage_fraction=0.296875
first_missing_range=19456..65536
input_count=38
total_completion_checks=77824
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range18944_19456.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard18944_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_19456.json`.
JSON/JSONL parsed cleanly and stderr files were 0 bytes.

The high20 exact-carry closure was extended beyond the previous fast-tail
top40 by first generating a top80 source:

```text
source=/tmp/ct07_x6high16_fast_tail_top80_20260604.jsonl
rows=80
first 40 fixed high16 values matched /tmp/ct07_x6high16_fast_tail_top40_20260604.jsonl
```

Ranks 41..44 map from high16 to high20 by `x6high20 = high16 << 4`, and all
four closed under the same corrected q272 exact-carry settings:

```text
rank=41 high16=0x0186 x6high20=0x1860 vars=600767 clauses=2697177 sat=false model_count=0
rank=42 high16=0x0190 x6high20=0x1900 vars=600704 clauses=2696911 sat=false model_count=0
rank=43 high16=0x019a x6high20=0x19a0 vars=600713 clauses=2696829 sat=false model_count=0
rank=44 high16=0x01a3 x6high20=0x1a30 vars=600899 clauses=2697804 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4g_exact_closure_20260604.json` and
`/tmp/ct07_high20_top44_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=44
sat=0
unsat=44
model_count_total=0
unique_closed_full_x6_values=44 * 2^26 = 2952790016
```

The p-only q-growth probe cannot be widened to `210:40:0`. That range extends
past x1 (`p[210..248]`) into `p[249]`, and `p[249]` is already known as `1`,
so `210:40:0` is an inconsistent fixed range rather than a useful oracle
result. The corrected maximum-width p-only check is `210:39:0`:

```text
x1wide36 top q_low/q_prefix/q_known=246/194/440
x1wide39 top q_low/q_prefix/q_known=273/194/467
```

Staged Hensel top4 at 224/240/256/272 bits with a 2000 ms timeout did not
produce a hard contradiction:

```text
status_counts={"sat": 16}
prefix 224: sat 4
prefix 240: sat 4
prefix 256: sat 4
prefix 272: sat 4
```

Outputs:
`/tmp/ct07_p_only_qgrowth_mixed_x1w39_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_top4_224_272_t2000_20260604.json`.
The q-known ranking improved sharply, but Hensel consistency stayed SAT through
272 bits, so this is ranking evidence rather than a learned no-good.

The direct edge/q-ranking coverage for the current naming was also completed
for previously missing `x7=0,4,7` under `x0=0`, `x1=0x9b183cdcc`, and
`x6=0x245521490bd`:

```text
x7=0 best x5=721:48:0x100050003 q_low=265 q_prefix=303 q_known=568 width_bits=721
x7=4 best x5=721:48:0x100060001 q_low=265 q_prefix=303 q_known=568 width_bits=721
x7=7 best x5=721:48:0x100050001 q_low=265 q_prefix=303 q_known=568 width_bits=721
```

Folded-Coron verification was reconstruction-positive but factor-negative for
the `x2` profile, while the paired `x5` profile was branch-infeasible:

```text
x7=0 x2 primitive_margin=204.0 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
x7=4 x2 primitive_margin=204.0 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
x7=7 x2 primitive_margin=204.0 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
```

Outputs:
`/tmp/ct07_q_x5_x7_missing_0_4_7_x0_0_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_q_x5_x7_{0,4,7}_x0_0_x1_9b_w87_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x7_{0,4,7}_x0_0_x1_9b_beam4_pp16_20260604.json`.
These three direct rows are weaker than the `q_known=620` ceiling seen for
many other x7 branches, so they mainly close a coverage gap.

A separate edge/q-ranking sweep also moved off the already exhausted `x0=0`
slice: `x0={1,2}`, fixed `x1=0x9b183cdcc`, all `x7=0..15`, full x5 width 87,
beam4, per-parent 16. The best merged branch still hit the same ceiling:

```text
x0=1 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620
x0=2 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620
```

Folded-Coron verification on both tied best branches was reconstruction-positive
but factor-negative:

```text
x0=1 x7=10 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
x0=2 x7=10 primitive_margin=144.0 reconstructed=13 root_count=0 verified_factor_count=0
```

Outputs:
`/tmp/ct07_q_x5_x0_1_2_x7_all_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x0_1_x7_10_x1_9b_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x0_2_x7_10_x1_9b_beam4_pp16_20260604.json`.
No factor or plaintext was recovered.

## 2026-06-05 q-gap persistent ledger and wide-drop measurements

The q middle-gap SAT/CAS path was exercised on the split hard frontier

```text
cube_ranges=150:4,210:39,265:24,745:24,784:46,920:4
check_bits=289
q_gap_max_bits=462
epsilon=0.02
min_hard_margin_bits=8.0
```

This is the full `x0 + x1 + x2_low24 + x5_high24 + x6 + x7`
hard-trigger shape.  No factor or plaintext was recovered in these runs.

Persistent ledger smoke:

```text
ledger=tmp/ct07_qgap_independent_runner_smoke_20260605.jsonl
total cubes=6
status=no_roots for all cubes
hard_blocks=6
q_gap_coppersmith_independent_drop_clauses=12
q_gap_coppersmith_independent_dropped_literals=48
q_gap_coppersmith_calls/cache_hits=194/4
roots/factors=0/0
model progression:
  x0=0, x1=0
  x0=0, x1=16
  x0=0, x1=48
  x0=0, x1=32
  x0=0, x1=80
  x0=0, x1=112
```

The self-loading ledger works: later child processes load earlier
`learned_clause_variants` and avoid already-closed subcubes.  The progression
is still solver-order driven rather than a clean numeric sweep, so ledgers must
be analyzed after short batches.

Independent wide-drop measurements on the all-zero split cube:

```text
drop window 210:8 (x1 low8), first bucket x1=0
output=tmp/ct07_qgap_split_independent_x1low8_workers8_20260605.jsonl
elapsed=878s
q_gap_coppersmith_calls=257
dropped bits=210..217
learned literal count=133
roots/factors=0/0

drop window 210:8 (x1 low8), second loaded bucket x1=256
output=tmp/ct07_qgap_split_independent_x1low8_after256_workers16_20260605.jsonl
elapsed=872s
q_gap_coppersmith_calls=257
dropped bits=210..217
learned literal count=133
roots/factors=0/0
```

Loading the x0 drop and both x1-low8 ledgers moved the next SAT model to
`x1=768`:

```text
output=tmp/ct07_qgap_split_load_x1low8_0_511_smoke_20260605.jsonl
loaded clauses/literals=4/540
next cube=150:4=0,210:39=768,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_bits=457
roots/factors=0/0
```

This proves the low8 clauses are being restored and used, but it also shows
the solver may jump between open x1 buckets.  Do not interpret this as a
contiguous enumeration of `x1`.

Worker-count observation:

```text
workers=8 x1-low8 elapsed=878s
workers=16 x1-low8 elapsed=872s
```

On this host, raising the independent q-gap minimization pool from 8 to 16 did
not improve this wide-drop workload.  Use about 8 workers for 256-completion
wide drops unless a later benchmark shows otherwise.

Other independent drop probes on the all-zero split cube:

```text
drop window 784:4 (x6 low4)
output=tmp/ct07_qgap_split_independent_x6low4_workers4_20260605.jsonl
elapsed=89s
result=not droppable under independent split-frontier check
q_gap_coppersmith_calls=16

drop windows 745:4 (x5 high4), 285:4 (x2 top4)
output=tmp/ct07_qgap_split_independent_x5high4_x2top4_workers4_20260605.jsonl
elapsed=137s
result=x2 top4 droppable, x5 high4 not droppable
dropped bits=285..288
q_gap_coppersmith_calls=32

drop windows 283:6 (x2 top6), 745:2 (x5 high2)
output=tmp/ct07_qgap_split_independent_x2top6_x5high2_workers8_20260605.jsonl
elapsed=274s
result=x2 top6 droppable, x5 high2 not droppable
dropped bits=283..288
q_gap_coppersmith_calls=68

drop windows 282:7 (x2 top7), 745:1 (x5 high1)
output=tmp/ct07_qgap_split_independent_x2top7_x5high1_workers8_20260605.jsonl
elapsed=470s
result=x2 top7 droppable, x5 high1 not droppable
dropped bits=282..288
q_gap_coppersmith_calls=130

drop window 281:8 (x2 top8)
output=tmp/ct07_qgap_split_independent_x2top8_workers8_20260605.jsonl
elapsed=866s
result=x2 top8 droppable
dropped bits=281..288
q_gap_coppersmith_calls=257
```

Important caveat: `x2 top8` is a learned-clause reduction after all 256 full
`x2_low24` completions have been checked.  It is not a valid reason to change
the base trigger to `265:16`.  A direct smoke with only `x2_low16+x5_high24`
skipped q-gap because the root gap exceeded the hard threshold:

```text
output=tmp/ct07_qgap_split_x2low16_frontier_smoke_20260605.jsonl
cube_ranges=150:4,210:39,265:16,745:24,784:46,920:4
q_gap_bits=465
q_gap_coppersmith_calls=0
q_gap_coppersmith_skips=1
learned_clause=sample_block_only
```

Current local conclusion:

```text
hard trigger remains: x2_low24 + x5_high24
best useful independent drops observed:
  x0 150:4
  x1 low4 or selected x1 low8 buckets
  x2 top8, after full completion verification
avoid as default drops:
  x6 low4 on split frontier
  x5 high1/high2/high4
wide 8-bit drops are expensive: about 14.5 minutes per 256-completion check
```

Follow-up productive wide run after loading the existing local ledgers:

```text
output=tmp/ct07_qgap_wide_next_after_ledgers_20260605.jsonl
loaded ledgers:
  tmp/ct07_qgap_split_independent_x0_x1_20260605.jsonl
  tmp/ct07_qgap_split_independent_x1low8_workers8_20260605.jsonl
  tmp/ct07_qgap_split_independent_x1low8_after256_workers16_20260605.jsonl
  tmp/ct07_qgap_split_independent_x2top8_workers8_20260605.jsonl
loaded clauses/literals=5/673
tested cube=150:4=0,210:39=768,265:24=0,745:24=0,784:46=0,920:4=0
elapsed=968s
q_gap_bits=457
q_gap_coppersmith_calls=289
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=3
q_gap_coppersmith_independent_dropped_literals=16
learned variants:
  drop 150:4 -> literal_count=137
  drop 210:4 -> literal_count=137
  drop 281:8 -> literal_count=133
roots/factors=0/0
```

This confirms that the same x0, x1-low4, and x2-top8 minimization pattern also
works at the `x1=768` bucket under the current model ordering.

Loading that new ledger moved the next model to `x1=784` and produced one more
unminimized q-gap hard block:

```text
output=tmp/ct07_qgap_load_after_wide_next_smoke_20260605.jsonl
loaded clauses/literals=8/1080
next cube=150:4=0,210:39=784,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

Do not use the smoke ledger above as a continuation input for minimization: it
contains an unminimized `x1=784` hard block.  Re-running the same model with
the minimized ledgers only closed `x1=784` with the same three independent
drop windows:

```text
output=tmp/ct07_qgap_wide_x1_784_20260605.jsonl
loaded clauses/literals=8/1080
tested cube=150:4=0,210:39=784,265:24=0,745:24=0,784:46=0,920:4=0
elapsed=944s
q_gap_bits=457
q_gap_coppersmith_calls=289
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=3
q_gap_coppersmith_independent_dropped_literals=16
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_literal_count=407
roots/factors=0/0
```

Loading that ledger moved the next model to `x1=800`:

```text
output=tmp/ct07_qgap_load_after_wide_x1_784_smoke_20260605.jsonl
loaded clauses/literals=11/1487
next cube=150:4=0,210:39=800,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

The next minimized run closed `x1=800` similarly:

```text
output=tmp/ct07_qgap_wide_x1_800_20260605.jsonl
loaded clauses/literals=11/1487
tested cube=150:4=0,210:39=800,265:24=0,745:24=0,784:46=0,920:4=0
elapsed=892s
q_gap_bits=457
q_gap_coppersmith_calls=289
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=3
q_gap_coppersmith_independent_dropped_literals=16
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_literal_count=407
roots/factors=0/0
```

Loading through `x1=800` moved the next model to `x1=816`:

```text
output=tmp/ct07_qgap_load_after_wide_x1_800_smoke_20260605.jsonl
loaded clauses/literals=14/1894
next cube=150:4=0,210:39=816,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

Current interpretation: the q-gap hard oracle is soundly closing these split
frontier cubes, but the current branch ordering is still walking `x1` in
16-step buckets.  To make this solve-oriented rather than bookkeeping-oriented,
the next improvement should generalize across larger `x1` regions or introduce
a hit-first/ranked gateway queue before continuing many more one-cube wide
runs.

Follow-up: wider `x1` low-bit minimization works.  Instead of continuing the
`x1=784 -> 800 -> 816` 16-step walk, I tested dropping all eight low bits of
`x1` on the current `x1=816` bucket:

```text
output=tmp/ct07_qgap_wide_x1_816_x1low8_probe_20260605.jsonl
loaded clauses/literals=14/1894
tested cube=150:4=0,210:39=816,265:24=0,745:24=0,784:46=0,920:4=0
drop windows=150:4,210:8,281:8
elapsed=1588s
q_gap_bits=457
q_gap_coppersmith_calls=529
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=3
q_gap_coppersmith_independent_dropped_literals=20
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_literal_count=403
roots/factors=0/0
```

Loading this ledger moved the model backward to the remaining `x1=512` bucket,
which means the `x1=768..1023` bucket was closed under the current other
gateway/diagonal choices:

```text
output=tmp/ct07_qgap_load_after_x1_816_x1low8_smoke_20260605.jsonl
loaded clauses/literals=17/2297
next cube=150:4=0,210:39=512,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

Then I reran only the useful `x1` low8 drop plus the cheap `x0` drop on
`x1=512`, leaving out the expensive `281:8` x2-top8 check:

```text
output=tmp/ct07_qgap_wide_x1_512_x1low8_only_20260605.jsonl
loaded clauses/literals=17/2297
tested cube=150:4=0,210:39=512,265:24=0,745:24=0,784:46=0,920:4=0
drop windows=150:4,210:8
elapsed=1197s
q_gap_bits=457
q_gap_coppersmith_calls=273
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=2
q_gap_coppersmith_independent_dropped_literals=12
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_literal_count=270
roots/factors=0/0
```

Loading through that ledger moves the next model to `x1=1024`:

```text
output=tmp/ct07_qgap_load_after_x1_512_x1low8_smoke_20260605.jsonl
loaded clauses/literals=19/2567
next cube=150:4=0,210:39=1024,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

This is a better proof-loop primitive than the previous `210:4` default:
`210:8` costs about 273 q-gap calls when paired only with `150:4`, but it
closes a full 256-value `x1` bucket under the current branch shape.  Do not
combine `210:8` and `281:8` by default; the combined probe cost 529 q-gap calls
and 1588 seconds.  Use `281:8` only when x2-top8 generalization is the explicit
goal.

Continuing with the cheaper `150:4 + 210:8` pattern closed the next bucket:

```text
output=tmp/ct07_qgap_wide_x1_1024_x1low8_20260605.jsonl
loaded clauses/literals=19/2567
tested cube=150:4=0,210:39=1024,265:24=0,745:24=0,784:46=0,920:4=0
drop windows=150:4,210:8
elapsed=1021s
q_gap_bits=457
q_gap_coppersmith_calls=273
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_independent_drop_clauses=2
q_gap_coppersmith_independent_dropped_literals=12
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_literal_count=270
roots/factors=0/0
```

Loading through this ledger moves the next model to `x1=1536`:

```text
output=tmp/ct07_qgap_load_after_x1_1024_x1low8_smoke_20260605.jsonl
loaded clauses/literals=21/2837
next cube=150:4=0,210:39=1536,265:24=0,745:24=0,784:46=0,920:4=0
q_gap_coppersmith_calls=1
q_gap_coppersmith_status=no_roots
learned_clause_scope=q_gap_selected_bits
learned_clause_literal_count=141
roots/factors=0/0
```

So the current hard-proof loop is advancing by 256-value `x1` buckets under
the fixed `x6=0,x5high24=0,x2low24=0,x0=0,x7=0` branch shape.  This is
mathematically valid pruning, but still not broad enough to expect a quick
factor unless the true gateway branch lies near this model order.

To test a broader hit-first path, I generated diversified q-gap gateway
candidates with hash tie-breaking instead of following the default SAT model
order.  Candidate shape:

```text
generator=q_gap_gateway_beam_search.py
beam_width=64
top=64 per salt
tie_policy=hash
frontier=x0+x7+x1 full+x6 full+x2_low24+x5_high24
q_gap_bits=456 for all retained candidates
```

Salt `qgap-hit-20260605-a`:

```text
candidate_json=tmp/ct07_qgap_gateway_hash_top64_20260605.json
unique candidates=64

first half:
  output_dir=tmp/ct07_qgap_gateway_hash_top32_parallel_abs_20260605
  candidates_tested=32
  elapsed=145.060s
  q_gap_distribution={456: 32}
  status_counts={no_roots: 32}
  hard_no_roots=32
  roots/factors=0/0

second half:
  output_dir=tmp/ct07_qgap_gateway_hash_33_64_parallel_abs_20260605
  candidates_tested=32
  elapsed=120.338s
  q_gap_distribution={456: 32}
  status_counts={no_roots: 32}
  hard_no_roots=32
  roots/factors=0/0
```

Salt `qgap-hit-20260605-b`:

```text
candidate_json=tmp/ct07_qgap_gateway_hashB_top64_20260605.json
output_dir=tmp/ct07_qgap_gateway_hashB_top64_parallel_abs_20260605
candidates_tested=64
elapsed=252.279s
q_gap_distribution={456: 64}
status_counts={no_roots: 64}
hard_no_roots=64
roots/factors=0/0
```

The two salt candidate sets had no duplicate fixed-range assignments:

```text
total diversified candidates=128
unique diversified candidates=128
duplicates=0
combined q-gap status=128 hard no_roots, 0 roots, 0 factors
```

Salt `qgap-hit-20260605-c` added a third diversified top-64 set:

```text
candidate_json=tmp/ct07_qgap_gateway_hashC_top64_20260605.json
output_dir=tmp/ct07_qgap_gateway_hashC_top64_parallel_abs_20260605
candidates_tested=64
elapsed=439.262s
q_gap_distribution={456: 64}
status_counts={no_roots: 64}
hard_no_roots=64
roots/factors=0/0
```

The diversified hit-first total is now:

```text
total diversified candidates=192
known unique among salts A/B=128
salt C checked separately=64
combined q-gap status=192 hard no_roots, 0 roots, 0 factors
```

This is useful negative signal for the q-gap hit-first strategy: the oracle is
fast enough to screen diversified gateway candidates, but these three top-64
hash beams did not hit the true factor.  Operational note: pass
`--candidate-json` as an absolute path to `run_q_gap_parallel.py`; the child
`branch_q_gap_coppersmith.py` runs under the `cryptotest` root, so relative
`tmp/...` paths are otherwise treated as missing and yield `candidates_tested=0`.

The persistent hard-ledger loop also continued with the cheaper
`150:4 + 210:8` independent drop set:

```text
outputs:
  tmp/ct07_qgap_wide_x1_1536_x1low8_20260605.jsonl
  tmp/ct07_qgap_wide_x1_1280_x1low8_20260605.jsonl
  tmp/ct07_qgap_wide_after_1280_batch4_x1low8_20260605.jsonl

tested x1 buckets:
  1536
  1280
  1792
  2048
  18432
  49152

per cube:
  q_gap_bits=457
  q_gap_coppersmith_status=no_roots
  product_prefix_status=sat
  roots/factors=0/0
  q_gap_coppersmith_calls=273
  independent drop clauses=2
  dropped bits=150..153 and 210..217
  learned variants literal counts=137 and 133

batch4 aggregate:
  q_gap_coppersmith_calls=1092
  q_gap_coppersmith_hard_blocks=4
  q_gap_coppersmith_independent_drop_clauses=8
  q_gap_coppersmith_independent_dropped_literals=48
```

Loading all hard-ledger files through
`tmp/ct07_qgap_wide_after_1280_batch4_x1low8_20260605.jsonl` gives:

```text
output=tmp/ct07_qgap_load_after_batch4_x1low8_smoke_20260605.jsonl
loaded clauses/literals=33/4457
next cube=150:4=0,210:39=3584,265:24=0,745:24=0,784:46=0,920:4=0
```

So the hard-ledger loop remains sound and accumulates clauses, but it is still
not a complete solve path by itself.  At this point there are 33 loaded hard
clauses under the current branch shape and no recovered factor.

## 2026-06-05 q-gap oracle timeout guard and epsilon check

`q_middle_gap_oracle.py`, `semi_programmatic_sat.py`,
`branch_q_gap_coppersmith.py`, `run_q_gap_parallel.py`, and
`sat_cas_batch_runner.py` now accept a q-gap oracle timeout:

```text
semi_programmatic_sat.py / sat_cas_batch_runner.py:
  --q-gap-oracle-timeout-seconds SECONDS

branch_q_gap_coppersmith.py / run_q_gap_parallel.py:
  --oracle-timeout-seconds SECONDS
```

The timeout is disabled by default.  When enabled, the q middle-gap
Coppersmith call runs in a child process so a slow Sage/NTL `small_roots`
call can be terminated without killing the whole SAT/CAS child.

Why this was added:

```text
test cube:
  cube_ranges=150:4,210:39,265:16,745:24,784:46,920:4
  check_bits=281
  q_gap_bits=465
  epsilon=0.005
  min_hard_margin_bits=8.0

ungarded run:
  output=tmp/ct07_qgap_split_x2low16_eps005_hard_smoke_20260605.jsonl
  status=manually terminated after about 10 minutes
  conclusion=not viable as a broad hard-pruning loop

timeout-guarded run:
  output=tmp/ct07_qgap_split_x2low16_eps005_timeout3_smoke_20260605.jsonl
  elapsed=3s
  q_gap_coppersmith_status=timeout
  hard_clause_bound_eligible=true
  no_root_hard_clause_eligible=false
  roots/factors=0/0
```

The guard prevents a slow low-epsilon attempt from producing an unsafe hard
clause.  Timeout is treated as unknown.

Batch runner passthrough smoke:

```text
output=tmp/ct07_qgap_runner_timeout_pass_smoke_20260605.jsonl
runs/completed/timeouts=1/1/0
child q_gap_coppersmith_status=timeout
runner preserved cube and summary records
```

Regression check on the normal hard line:

```text
output=tmp/ct07_qgap_split_eps002_timeout60_regression_20260605.jsonl
cube_ranges=150:4,210:39,265:24,745:24,784:46,920:4
epsilon=0.02
q_gap_bits=457
oracle_timeout_seconds=60
elapsed=13s
q_gap_coppersmith_status=no_roots
q_gap_coppersmith_hard_blocks=1
learned_clause_scope=q_gap_selected_bits
roots/factors=0/0
```

Operational conclusion:

```text
default hard-pruning path: keep epsilon=0.02 and no per-oracle timeout for throughput
risky low-epsilon diagnostics: use --q-gap-oracle-timeout-seconds
do not use epsilon=0.005 q_gap_bits=465 as a broad hard-pruning batch;
single-call cost already exceeded 10 minutes on the first tested cube
```

## 2026-06-05 q middle-gap Coppersmith integration

The q-low Coppersmith path was corrected into a q middle-gap oracle.  The new
polynomial uses both the derived q low bits and q high prefix:

```text
q = q_lo + 2^t * y + q_hi
X = 2^(q_prefix_start - t)
cache key = (t, q_prefix_start, q_lo, q_hi, epsilon)
```

This matters because the old q-low oracle recorded q-prefix data but did not
put it into the Coppersmith constant.

Saved q-growth/q-low candidates were smoke-tested with the corrected oracle:

```text
output dir: tmp/ct07_q_gap_parallel_20260605
candidates_tested=100
q_gap_distribution: 104=20, 120=80
status_counts: no_roots=100
hard_no_roots=100
roots/factors=0/0
status=no_factor
aggregate=tmp/ct07_q_gap_parallel_20260605/q_gap_parallel_aggregate.json
```

These exact saved branches are closed, but this is not a solve: the saved
candidate set was only a ranked sample.

The SAT loop now has q-gap Coppersmith triggers and hard no-root learning.  A
hard diagonal cube with `x0+x1+x2_low48+x6+x7` fixed produced
`q_gap_bits=457`, `effective_margin_bits=13.04`, and a hard `no_roots` clause.
The same first cube was used to test small sound minimization windows:

```text
drop x0 bits 150..153: droppable, 16 completions, all hard no_roots
drop x7 bits 920..923: droppable, 16 completions, all hard no_roots
drop x1 bits 210..213: droppable, 16 completions, all hard no_roots
drop x2 bits 309..312: droppable, 16 completions, all hard no_roots
drop x6 bits 784..787: droppable, 16 completions, all hard no_roots
learned literal count after each 4-bit drop: 137
roots/factors=0/0
```

Outputs:
`tmp/ct07_qgap_sat_hard_cube1_20260605.jsonl`,
`tmp/ct07_qgap_sat_hard_4cubes_20260605.jsonl`,
`tmp/ct07_qgap_sat_hard_cube1_drop_x0_20260605.jsonl`,
`tmp/ct07_qgap_sat_hard_cube1_drop_x7_20260605.jsonl`,
`tmp/ct07_qgap_sat_hard_cube1_drop_x1low4_20260605.jsonl`,
`tmp/ct07_qgap_sat_hard_cube1_drop_x2top4_20260605.jsonl`, and
`tmp/ct07_qgap_sat_hard_cube1_drop_x6low4_20260605.jsonl`.

`q_gap_gateway_beam_search.py` was added to generate gateway/diagonal
candidates for the hard q-gap line.  The first lexicographic beam was biased
toward zero-valued x1/x2 chunks, so a hash tie-break option was added for
diversity among candidates with identical q-gap score.  A diversified beam:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 \
  --tie-policy hash --diversity-salt 20260605-a --json \
  > tmp/ct07_qgap_gateway_beam_hash64_a_20260605.json
```

produced 64 candidates all on the hard line:

```text
q_gap_bits=456
q_low_bits=313
q_prefix_start=769
q_known_bits=568
```

The 64 candidates were checked in parallel:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_qgap_gateway_beam_hash64_a_20260605.json \
  --output-dir tmp/ct07_qgap_gateway_beam_hash64_a_qgap_20260605 \
  --candidate-start 1 --candidate-stop 64 \
  --chunk-size 4 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 \
  --timeout-seconds 900 --no-pdf-check --json
```

Result:

```text
candidates_tested=64
q_gap_distribution: 456=64
status_counts: no_roots=64
hard_no_roots=64
roots/factors=0/0
elapsed_seconds=185.319
summary=tmp/ct07_qgap_gateway_beam_hash64_a_qgap_20260605/q_gap_parallel_summary.json
```

This confirms the q-gap hard oracle and candidate plumbing, but the current
beam is still a hit-first/ranking generator.  It should not be interpreted as
meaningful coverage of the 135-149 bit hard frontier unless its no-root clauses
are fed back into a persistent SAT/CAS loop with a coverage ledger.

## 2026-06-05 persistent q-gap learner bridge

`semi_programmatic_sat.py` now accepts prior JSONL ledgers and reconstructs
hard learned clauses before asking Z3 for a model:

```text
--load-learned-jsonl PATH
--load-learned-limit N
--load-soft-blocks  # optional; off by default
```

Only hard clauses are loaded by default:

```text
product_prefix_unsat
low_coppersmith_no_root
q_gap_coppersmith_no_root
```

The loader requires `cube_ranges`, so future persistent runs must keep
`--include-cube-ranges` enabled.  For minimized clauses it removes
`learned_clause_dropped_bits` before rebuilding the blocking disjunction.  The
batch runner passes these options through, which means the same output JSONL
can be used as an append-only ledger and as the next child's loaded clause
source.

Smoke 1 loaded the previous first hard q-gap cube:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:48,784:46,920:4 \
  --check-bits 313 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --load-learned-jsonl tmp/ct07_qgap_sat_hard_cube1_20260605.jsonl \
  --include-cube-ranges \
  > tmp/ct07_qgap_sat_load_ledger_smoke_20260605.jsonl
```

Result:

```text
loaded clauses/literals: 1/141
first emitted cube changed from x0=0 to x0=1
new cube q_gap_bits=457
new cube status=no_roots, hard eligible
roots/factors=0/0
```

Smoke 2 used the batch runner with the output file also supplied as
`--load-learned-jsonl`:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/sat_cas_batch_runner.py \
  --output tmp/ct07_qgap_persistent_runner_smoke_20260605.jsonl \
  --max-cubes 1 --timeout-seconds 80 --runs-per-range 2 \
  --cube-ranges 150:4,210:39,265:48,784:46,920:4 \
  --check-bits 313 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --load-learned-jsonl tmp/ct07_qgap_persistent_runner_smoke_20260605.jsonl \
  --include-cube-ranges
```

Result:

```text
runner completed runs: 2/2
run 1 loaded clauses: 0
run 2 loaded clauses: 1
cube 1: x0=0, hard q-gap no_roots
cube 2: x0=1, hard q-gap no_roots
roots/factors=0/0
```

This turns q-gap no-root callbacks into resumable SAT clauses.  It is still not
a complete solve engine because the current cube order is model-order driven,
but it removes the previous loss of learned clauses between child processes.

`q_gap_gateway_beam_search.py` also now supports split diagonal frontiers with
`x5_high` chunks:

```text
--x2-low-bits A --x2-low-widths ...
--x5-high-bits B --x5-high-widths ...
```

A mixed hard frontier with `x2_low24+x5_high24` was generated and checked:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 \
  --tie-policy hash --diversity-salt 20260605-mix24 \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > tmp/ct07_qgap_gateway_beam_mix24_hash64_20260605.json

python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_qgap_gateway_beam_mix24_hash64_20260605.json \
  --output-dir tmp/ct07_qgap_gateway_beam_mix24_hash64_qgap_20260605 \
  --candidate-start 1 --candidate-stop 64 \
  --chunk-size 4 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 \
  --timeout-seconds 900 --no-pdf-check --json
```

Result:

```text
candidate shape: x0+x1+x6+x7+x2_low24+x5_high24
q_low_bits=289
q_prefix_start=745
q_gap_bits=456
q_known_bits=568
candidates_tested=64
status_counts: no_roots=64
hard_no_roots=64
roots/factors=0/0
elapsed_seconds=176.317
summary=tmp/ct07_qgap_gateway_beam_mix24_hash64_qgap_20260605/q_gap_parallel_summary.json
```

The mixed frontier is structurally better than the one-sided `x2_low48` beam
because it exercises both sides of the q gap, but this 64-candidate batch again
found no factor.

The split persistent runner template was also smoke-tested with two child runs:

```text
output=tmp/ct07_qgap_persistent_split_smoke_20260605.jsonl
cube_ranges=150:4,210:39,265:24,745:24,784:46,920:4
runner completed runs: 2/2
run 1 loaded clauses: 0
run 2 loaded clauses: 1
cube 1: x0=0, q_low=289, q_prefix_start=746, q_gap_bits=457, hard no_roots
cube 2: x0=1, q_low=289, q_prefix_start=746, q_gap_bits=457, hard no_roots
roots/factors=0/0
```

This verifies that the split diagonal template can be used as a resumable
ledger run.  It still walks the solver's model order unless additional
branch-ordering constraints or diversified range schedules are supplied.

Additional split q-gap minimization probes:

```text
base cube_ranges=150:4,210:39,265:24,745:24,784:46,920:4
base all-zero q_low=289, q_prefix_start=746, q_gap_bits=457

x0 drop:
  windows 150:2 and 152:2
  calls/cache_hits=16/5
  dropped bits=150..153
  learned literal count=137
  roots/factors=0/0
  output=tmp/ct07_qgap_split_drop_x0_20260605.jsonl

x7 drop:
  windows 920:2 and 922:2
  920:2 was not droppable because one completion pushed gap above max
  922:2 was droppable
  calls/cache_hits=6/2
  dropped bits=922..923
  learned literal count=139
  roots/factors=0/0
  output=tmp/ct07_qgap_split_drop_x7_20260605.jsonl

x1 low4 drop:
  windows 210:2 and 212:2
  calls/cache_hits=16/5
  dropped bits=210..213
  learned literal count=137
  roots/factors=0/0
  output=tmp/ct07_qgap_split_drop_x1low4_20260605.jsonl
```

A two-cube run with x0 drop enabled showed the expected widening effect:

```text
output=tmp/ct07_qgap_split_drop_x0_max2_20260605.jsonl
cube 1: x0=0, x1=0, hard no_roots, dropped x0 bits 150..153
cube 2: x0=0, x1=1, hard no_roots, dropped x0 bits 150..153
q_gap_coppersmith_calls/cache_hits=32/10
roots/factors=0/0
```

So after the first x0-dropped clause, the solver did not waste the second cube
on `x0=1`; it moved into x1 instead.

The same x1 low4 drop was checked after loading the x0-drop and initial
x1-low4 ledgers, so the active model was around `x1=16`:

```text
output=tmp/ct07_qgap_split_drop_x1low4_after16_20260605.jsonl
loaded clauses/literals=2/274
cube: x1=16
dropped bits=210..213
learned literal count=137
roots/factors=0/0
```

Loading the x0-drop, x1-low4-at-0, and x1-low4-at-16 ledgers together moved the
next model to `x1=48`:

```text
output=tmp/ct07_qgap_split_load_x1_0_31_smoke_20260605.jsonl
loaded clauses/literals=3/411
next cube: x0=0, x1=48
q_gap_bits=457
status=no_roots
roots/factors=0/0
```

This suggests a practical next loop: for each reached x1 bucket, learn an
x1-low4-dropped q-gap clause and periodically add x0-dropped clauses.  It is
still a branch killer, not a full proof of the x1 space.

## 2026-06-05 independent q-gap drop clauses

`semi_programmatic_sat.py` now supports:

```text
--q-gap-independent-drop-clauses
```

When this is enabled, each `--q-gap-drop-window` is verified against the
original cube independently.  If several windows are droppable, the script adds
one learned clause per droppable window and writes them under
`learned_clause_variants`.  The JSONL loader now understands these variants and
reconstructs every independent clause on resume.

This avoids the old cumulative-minimization problem where trying to drop x0
and x1-low4 together would require `2^8 = 256` completions.  With independent
clauses, x0 and x1-low4 cost `16 + 16` completions and produce two separate
137-literal clauses.

Single-cube smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:4 \
  --q-gap-minimize-max-completions 16 \
  --include-cube-ranges \
  > tmp/ct07_qgap_split_independent_x0_x1_20260605.jsonl
```

Result:

```text
cube: x0=0, x1=0
learned_clause_scope=independent_minimized_q_gap_selected_bits
learned_clause_count=2
variant 1: drop x0 bits 150..153, literal_count=137
variant 2: drop x1 low bits 210..213, literal_count=137
q_gap_coppersmith_calls/cache_hits=31/2
roots/factors=0/0
```

Loader smoke:

```text
input=tmp/ct07_qgap_split_independent_x0_x1_20260605.jsonl
loaded clauses/literals=2/274
next cube: x0=0, x1=16
roots/factors=0/0
```

Runner smoke using the same output JSONL as its load source:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/sat_cas_batch_runner.py \
  --output tmp/ct07_qgap_independent_runner_smoke_20260605.jsonl \
  --load-learned-jsonl tmp/ct07_qgap_independent_runner_smoke_20260605.jsonl \
  --max-cubes 1 --runs-per-range 2 --timeout-seconds 700 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:4 \
  --q-gap-minimize-max-completions 16 \
  --include-cube-ranges
```

Result:

```text
completed_runs=2/2
cube 1: x0=0, x1=0, variants=2
cube 2: x0=0, x1=16, variants=2
loaded clauses/literals on run 2=2/274
q_gap_coppersmith_calls/cache_hits=62/4
independent_drop_clauses=4
independent_dropped_literals=16
roots/factors=0/0
```

This is a real efficiency improvement over separate x0 and x1-low4 passes, but
the cost is still high: two child runs took long enough that a longer sweep
should not be launched without parallelizing the independent completion checks
or lowering the number of dynamic windows.

## 2026-06-05 q-gap minimization worker pool

`semi_programmatic_sat.py` now supports:

```text
--q-gap-minimize-workers N
```

For independent drop clauses, each drop-window completion set can be evaluated
through a process worker pool.  This path is intentionally restricted to
dynamic q-gap minimization; normal q-gap callbacks and the legacy cumulative
minimizer still behave as before.

Direct smoke:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:4 \
  --q-gap-minimize-max-completions 16 \
  --q-gap-minimize-workers 4 \
  --include-cube-ranges \
  > tmp/ct07_qgap_split_independent_x0_x1_workers4_20260605.jsonl
```

Result:

```text
elapsed wall time=144s
learned_clause_count=2
q_gap_coppersmith_calls/cache_hits=33/0
independent_drop_clauses=2
independent_dropped_literals=8
roots/factors=0/0
```

The equivalent serial independent smoke had taken about 6-9 minutes in prior
runs, depending on Sage timing.  The worker path repeats the same no-root
result and variant shape, but it does not share the parent-process cache, so
the q-gap call count is one higher.

Then the existing persistent ledger
`tmp/ct07_qgap_independent_runner_smoke_20260605.jsonl` was extended by one
workers=4 child run:

```text
previous serial child elapsed times: 413.251s and 447.762s
new workers=4 child elapsed time: 142.218s
ledger after append:
  cubes=3
  q_gap_coppersmith_independent_drop_clauses=6
  q_gap_coppersmith_independent_dropped_literals=24
  q_gap_coppersmith_calls/cache_hits=95/4
  roots/factors=0/0
model progression:
  cube 1: x0=0, x1=0
  cube 2: x0=0, x1=16
  cube 3: x0=0, x1=48
```

This confirms both resume behavior and the wall-time improvement.  It still
does not solve the instance; it only makes the q-gap hard-pruning loop more
usable.

## 2026-06-05 q middle-gap Coppersmith implementation and saved-candidate smoke

Updated the plan around the newer q middle-gap construction.  The important
fix is that q high-prefix bits are now part of the Coppersmith polynomial
constant:

```text
old q-low model: q = q0 + 2^t*y, X = 2^(1024-t)
new q-gap model: q = q_lo + 2^t*y + q_hi, X = 2^(q_prefix_start-t)
cache key: (q_low_bits, q_prefix_start, q_lo, q_hi, epsilon)
```

Implemented files:

```text
solutions/07_sat_cas_explore/q_middle_gap_oracle.py
solutions/07_sat_cas_explore/branch_q_gap_coppersmith.py
solutions/07_sat_cas_explore/run_q_gap_parallel.py
solutions/07_sat_cas_explore/run_updated_plan.py
```

Verification:

```text
python3 -m py_compile \
  cryptotest/solutions/07_sat_cas_explore/q_middle_gap_oracle.py \
  cryptotest/solutions/07_sat_cas_explore/branch_q_gap_coppersmith.py \
  cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  cryptotest/solutions/07_sat_cas_explore/run_updated_plan.py \
  cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py

PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Unit tests passed: `7/7`.

The original `/tmp` q-growth candidate JSON files referenced by
`branch_q_low_coppersmith_summary_20260604.json` were no longer present, so the
new q-gap probe was taught to parse the saved summary's
`all_fixed_ranges_text` rows.  A single first-candidate q-gap run showed:

```text
q_low_bits=608
q_prefix_start=728
q_gap_bits=120
effective_bound_bits=470.04
effective_margin_bits=350.04
hard_clause_bound_eligible=true
roots_returned=0
factor_count=0
elapsed_seconds ~= 65
```

The saved 100 candidates were then rechecked in 8 parallel chunks:

```text
output_dir=tmp/ct07_q_gap_parallel_20260605
workers=8 manual shell chunks
candidate ranges:
1..13, 14..26, 27..39, 40..52,
53..65, 66..78, 79..91, 92..100
```

Aggregate:

```text
candidates_tested=100
status_counts: no_roots=100
q_gap_distribution: 104=20, 120=80
roots_total=0
factors_total=0
hard_no_roots=100
status=no_factor
```

Aggregate output:
`tmp/ct07_q_gap_parallel_20260605/q_gap_parallel_aggregate.json`.

This result does not solve the challenge.  It does close the already saved
100 q-growth/q-low candidate branches under the corrected q-gap hard oracle.
The next solve driver should generate new gateway/diagonal branches instead of
continuing the old low-C/q272 manual queue.

## 2026-06-05 q-gap SAT loop and drop-window minimization

Added q middle-gap Coppersmith as a hard oracle inside
`semi_programmatic_sat.py` and exposed it through `sat_cas_batch_runner.py`.
The SAT loop can now:

```text
derive q low/high known bits for a cube
trigger q-gap if q_gap_bits <= --q-gap-max-bits
verify roots as factors
learn q_gap_coppersmith_no_root as a hard selected-bit block
optionally minimize the hard block by exhaustive q-gap drop-window completion
```

New/updated files:

```text
solutions/07_sat_cas_explore/semi_programmatic_sat.py
solutions/07_sat_cas_explore/sat_cas_batch_runner.py
solutions/07_sat_cas_explore/sat_batch_analyzer.py
```

Fast verification:

```text
python3 -m py_compile \
  cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  cryptotest/solutions/07_sat_cas_explore/sat_cas_batch_runner.py \
  cryptotest/solutions/07_sat_cas_explore/sat_batch_analyzer.py

PYTHONPATH=cryptotest/solutions/07_sat_cas_explore \
  python3 -m unittest cryptotest/solutions/07_sat_cas_explore/test_sat_cas_core.py
```

Unit tests passed: `7/7`.

Skip-trigger smoke:

```text
output=tmp/ct07_qgap_sat_skip_smoke2_20260605.jsonl
cubes=1
product_prefix_status: sat=1
q_gap_bits_hist: 714=1
q_gap_coppersmith_calls=0
q_gap_coppersmith_skips=1
learned_clause: sample_block_only=1
```

Hard-trigger cube smoke:

```bash
cd cryptotest/solutions/07_sat_cas_explore
python3 semi_programmatic_sat.py --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:48,784:46,920:4 \
  --check-bits 313 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail --include-cube-ranges \
  > /home/seorii/dev/hancomac/tmp/ct07_qgap_sat_hard_cube1_20260605.jsonl
```

Result:

```text
cube_ranges=150:4=0,210:39=0,265:48=0,784:46=0,920:4=0
product_prefix_status=sat
q_low_bits=313
q_prefix_bits=254
q_prefix_start=770
q_gap_bits=457
effective_margin_bits=13.04
roots_returned=0
factor_count=0
learned_clause=q_gap_coppersmith_no_root
learned_clause_literal_count=141
elapsed_seconds ~= 16.3
```

Four-cube runner smoke:

```text
output=tmp/ct07_qgap_sat_hard_4cubes_20260605.jsonl
cubes=4
product_prefix_status: sat=4
q_gap_bits_hist: 457=4
q_gap_coppersmith_calls=4
q_gap_coppersmith_status: no_roots=4
q_gap_coppersmith_hard_blocks=4
learned_clause_literal_count_hist: 141=4
factors=0
```

The first four cubes varied only x0 while keeping
`x1=x2_low48=x6=x7=0`, so the unminimized clause was too narrow.

q-gap drop-window minimization was then added and tested.

`x0` drop result:

```text
output=tmp/ct07_qgap_sat_hard_cube1_drop_x0_20260605.jsonl
drop windows: 150:2, 152:2
completion counts: 4 then 16
all completion statuses: no_roots
hard_eligible_completion_count: 4 then 16
dropped bits: 150,151,152,153
learned_clause_literal_count: 137
q_gap_coppersmith_calls=16
q_gap_coppersmith_cache_hits=5
factor_count=0
```

`x7` drop result:

```text
output=tmp/ct07_qgap_sat_hard_cube1_drop_x7_20260605.jsonl
drop windows: 920:2, 922:2
completion counts: 4 then 16
all completion statuses: no_roots
hard_eligible_completion_count: 4 then 16
dropped bits: 920,921,922,923
learned_clause_literal_count: 137
q_gap_coppersmith_calls=16
q_gap_coppersmith_cache_hits=5
factor_count=0
```

This proves that, at least for the first hard q-gap cube, x0 and x7 are
individually droppable under exhaustive q-gap completion.  The simultaneous
`x0+x7` drop would require 256 completions and should be treated as a long
minimization batch, not an interactive smoke test.

## 2026-06-04 parallel round 8: low-C 30.5%, high20 top48, deeper p-only Hensel, and x0=3/4 edge

The low-C union proof advanced by one more contiguous shard:

```text
new shard: 19456..19968
elapsed_seconds=330.735
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=19968/65536
coverage_fraction=0.3046875
first_missing_range=19968..65536
input_count=39
total_completion_checks=79872
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range19456_19968.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard19456_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_19968.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed the next four parents from the top80
ranking source:

```text
rank=45 high16=0x01ad x6high20=0x1ad0 vars=600754 clauses=2697112 sat=false model_count=0
rank=46 high16=0x01b7 x6high20=0x1b70 vars=600796 clauses=2697296 sat=false model_count=0
rank=47 high16=0x01c0 x6high20=0x1c00 vars=600827 clauses=2697507 sat=false model_count=0
rank=48 high16=0x01ca x6high20=0x1ca0 vars=600652 clauses=2696620 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4h_exact_closure_20260604.json` and
`/tmp/ct07_high20_top48_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=48
sat=0
unsat=48
model_count_total=0
unique_closed_full_x6_values=48 * 2^26 = 3221225472
```

The p-only SAT+CAS probe pushed the `x1wide39` candidates to deeper Hensel
prefixes and also tried a modestly wider x2 ranking range:

```text
same range set 265:8,798:8,920:4 at 288/304/320/336:
  status_counts={"unknown": 16}
  prefix 288/304/320/336: unknown 4 each

x2w12 range set 265:12,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=277/194/471
  status_counts={"sat": 2, "unknown": 14}
  prefix 288: sat 2, unknown 2
  prefix 304/320/336: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_hensel_x1w39_top4_288_336_t5000_20260604.json`,
`/tmp/ct07_p_only_qgrowth_x1w39_x2w12_4096_20260604.json`, and
`/tmp/ct07_p_only_hensel_x1w39_x2w12_top4_288_336_t5000_20260604.json`.
No UNSAT/hard contradiction or factor signal appeared. This confirms the
deeper Hensel checks are currently a ranking/timeout frontier, not a sound
learned-clause oracle.

The edge/q-ranking sweep continued with `x0={3,4}`, fixed
`x1=0x9b183cdcc`, all `x7=0..15`, full x5 width 87, beam4, per-parent 16.
Both x0 values again selected the same best branch:

```text
x0=3 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
x0=4 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification was reconstruction-positive but factor-negative for
the `x2` profile, while the paired `x5` profile was branch-infeasible:

```text
x0=3 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
x0=4 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
```

Outputs:
`/tmp/ct07_q_x5_x0_3_4_x7_all_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x0_3_x7_a_x1_9b_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x0_4_x7_a_x1_9b_beam4_pp16_20260604.json`.
No factor or plaintext was recovered.

## 2026-06-04 parallel round 9: low-C 31.25%, high20 top52, x2w16 p-only, and x0=5/6 edge

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 19968..20480
elapsed_seconds=287.542
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=20480/65536
coverage_fraction=0.3125
first_missing_range=20480..65536
input_count=40
total_completion_checks=81920
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range19968_20480.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard19968_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_20480.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 49..52 from the top80 ranking
source:

```text
rank=49 high16=0x01d4 x6high20=0x1d40 vars=600740 clauses=2697081 sat=false model_count=0
rank=50 high16=0x01de x6high20=0x1de0 vars=600765 clauses=2697174 sat=false model_count=0
rank=51 high16=0x01e7 x6high20=0x1e70 vars=600875 clauses=2697695 sat=false model_count=0
rank=52 high16=0x01f1 x6high20=0x1f10 vars=600777 clauses=2697187 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4i_exact_closure_20260604.json` and
`/tmp/ct07_high20_top52_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=52
sat=0
unsat=52
model_count_total=0
unique_closed_full_x6_values=52 * 2^26 = 3489660928
```

The p-only SAT+CAS probe widened x2 to 16 bits under full-zero `x1wide39`:

```text
range set 265:16,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=281/194/475
  top rows all have x2[265..280)=0 and p[920..923] in {0x7,0x8}

Hensel top4 at 280/288/296/304/320, timeout 5000ms:
  status_counts={"sat": 8, "unknown": 12}
  prefix 280: sat 4
  prefix 288: sat 4
  prefix 296/304/320: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w16_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w16_top4_280_320_t5000_20260604.json`.
The widened ranking improves q-known bits to 475, but still gives no UNSAT,
factor, or sound no-good signal.

The edge/q-ranking sweep continued with `x0={5,6}`, fixed
`x1=0x9b183cdcc`, all `x7=0..15`, full x5 width 87, beam4, per-parent 16.
Both x0 values again selected the same best branch:

```text
x0=5 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
x0=6 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification was reconstruction-positive but factor-negative for
the `x2` profile, while the paired `x5` profile was branch-infeasible:

```text
x0=5 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
x0=6 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
```

Outputs:
`/tmp/ct07_q_x5_x0_5_6_x7_all_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x0_5_x7_a_x1_9b_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x0_6_x7_a_x1_9b_beam4_pp16_20260604.json`.
No factor or plaintext was recovered.

## 2026-06-04 parallel round 10: low-C 32.03%, high20 top56, x2w20 p-only, and x0=7/8 edge

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 20480..20992
elapsed_seconds=287.821
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=20992/65536
coverage_fraction=0.3203125
first_missing_range=20992..65536
input_count=41
total_completion_checks=83968
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range20480_20992.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard20480_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_20992.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 53..56 from the top80 ranking
source:

```text
rank=53 high16=0x01fb x6high20=0x1fb0 vars=600788 clauses=2697270 sat=false model_count=0
rank=54 high16=0x0204 x6high20=0x2040 vars=600778 clauses=2697336 sat=false model_count=0
rank=55 high16=0x020e x6high20=0x20e0 vars=600883 clauses=2697712 sat=false model_count=0
rank=56 high16=0x0218 x6high20=0x2180 vars=600749 clauses=2697106 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4j_exact_closure_20260604.json` and
`/tmp/ct07_high20_top56_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=56
sat=0
unsat=56
model_count_total=0
unique_closed_full_x6_values=56 * 2^26 = 3758096384
```

The p-only SAT+CAS probe widened x2 to 20 bits under full-zero `x1wide39`:

```text
range set 265:20,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=285/194/479
  top rows all have x2[265..285)=0 and p[920..923] in {0x7,0x8}

Hensel top4 at 288/296/304/320/336, timeout 5000ms:
  status_counts={"sat": 8, "unknown": 12}
  prefix 288: sat 4
  prefix 296: sat 4
  prefix 304/320/336: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w20_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w20_top4_288_336_t5000_20260604.json`.
The widened ranking improves q-known bits to 479, but still gives no UNSAT,
factor, or sound no-good signal.

The edge/q-ranking sweep continued with `x0={7,8}`, fixed
`x1=0x9b183cdcc`, all `x7=0..15`, full x5 width 87, beam4, per-parent 16.
Both x0 values again selected the same best branch:

```text
x0=7 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
x0=8 x7=10 best x5=682:87:0x820181c20002018148 q_low=265 q_prefix=355 q_known=620 width_bits=669
```

Folded-Coron verification was reconstruction-positive but factor-negative for
the `x2` profile, while the paired `x5` profile was branch-infeasible:

```text
x0=7 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
x0=8 x7=10 x2 primitive_margin=273.33333333333337 reconstructed=13 root_count=0 verified_factor_count=0; x5 branch_infeasible
```

Outputs:
`/tmp/ct07_q_x5_x0_7_8_x7_all_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_edge_oracle_fullx5_x0_7_x7_0xa_x1_9b_beam4_pp16_20260604.json`, and
`/tmp/ct07_edge_oracle_fullx5_x0_8_x7_0xa_x1_9b_beam4_pp16_20260604.json`.
No factor or plaintext was recovered.

## 2026-06-04 parallel round 11: low-C 32.81%, high20 top60, x2w24 p-only, and mixed p/q lattice smoke

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 20992..21504
elapsed_seconds=293.006
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=21504/65536
coverage_fraction=0.328125
first_missing_range=21504..65536
input_count=42
total_completion_checks=86016
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range20992_21504.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard20992_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_21504.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 57..60 from the top80 ranking
source:

```text
rank=57 high16=0x0222 x6high20=0x2220 vars=600805 clauses=2697304 sat=false model_count=0
rank=58 high16=0x022b x6high20=0x22b0 vars=600878 clauses=2697737 sat=false model_count=0
rank=59 high16=0x0235 x6high20=0x2350 vars=600752 clauses=2697106 sat=false model_count=0
rank=60 high16=0x023f x6high20=0x23f0 vars=600842 clauses=2697469 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4k_exact_closure_20260604.json` and
`/tmp/ct07_high20_top60_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=60
sat=0
unsat=60
model_count_total=0
unique_closed_full_x6_values=60 * 2^26 = 4026531840
```

The p-only SAT+CAS probe widened x2 to 24 bits under full-zero `x1wide39`:

```text
range set 265:24,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=289/194/483
  top rows all have x2[265..289)=0 and vary only in x6 edge 798:4 and p[920..923]

Hensel top4 at 296/304/320/336/352, timeout 5000ms:
  status_counts={"sat": 4, "unknown": 16}
  prefix 296: sat 4
  prefix 304/320/336/352: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w24_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w24_top4_296_352_t5000_20260604.json`.
The widened ranking improves q-known bits to 483, but still gives no UNSAT,
factor, or sound no-good signal.

The TK/LZ side was audited before doing more depth scans. The current local
LZ/TK scripts all build rows from a single anchored p-projection and powers or
shifts of that projection, so positive-looking rows keep reducing to the same
`(projection, N)` ideal and provide no extra prune. A new standalone diagnostic
probe was added:

```text
cryptotest/solutions/07_sat_cas_explore/mixed_pq_lattice_probe.py
```

Its first smoke run used active p variables `x0,x7`, an automatically selected
q window, `m=1`, and shift degree 0:

```text
q_window=start 150 width 774
q_known=250 bits (low=150, prefix=100)
omitted_p_bits=403
omitted_q_bits=0
matrix rows=1 cols=10 rank=1
lll_status=ok
class_counts={"candidate": 1, "contains_q_terms": 1, "not_integer_projection_multiple": 1, "projection_derived": 1}
first row: contains_q_terms=true, projection_derived_mod_n=true, integer_multiple_of_projection=false
```

Output:
`/tmp/ct07_mixed_pq_smoke_x0x7_m1_s0_20260604_v2.json`.
This confirms the basis shape is no longer just an integer multiple of the
anchored projection, but the legacy modulo-N projection audit still classifies
the row as derived because `P*Q-N` reduces to `-N` after the p-projection. The
probe is therefore a basis-family smoke tool, not a sound pruning oracle. The
next useful mixed p/q step would need a separate exact-product sampled
evaluator rather than the old LZ projection-prune evaluator.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 12: low-C 33.59%, high20 top64, x2w28 p-only, and mixed p/q sample evaluator

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 21504..22016
elapsed_seconds=338.57
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=22016/65536
coverage_fraction=0.3359375
first_missing_range=22016..65536
input_count=43
total_completion_checks=88064
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range21504_22016.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard21504_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_22016.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 61..64 from the top80 ranking
source:

```text
rank=61 high16=0x0249 x6high20=0x2490 vars=600702 clauses=2696817 sat=false model_count=0
rank=62 high16=0x0252 x6high20=0x2520 vars=600827 clauses=2697483 sat=false model_count=0
rank=63 high16=0x025c x6high20=0x25c0 vars=600752 clauses=2697156 sat=false model_count=0
rank=64 high16=0x0266 x6high20=0x2660 vars=600752 clauses=2697098 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4l_exact_closure_20260604.json` and
`/tmp/ct07_high20_top64_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=64
sat=0
unsat=64
model_count_total=0
unique_closed_full_x6_values=64 * 2^26 = 4294967296
```

The p-only SAT+CAS probe widened x2 to 28 bits under full-zero `x1wide39`:

```text
range set 265:28,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=293/194/487
  top fixed ranges include x2[265..293)=0, x6 edge 798:4=0, p[920..923]=0x7

Hensel top4 at 304/320/336/352/368, timeout 5000ms:
  status_counts={"sat": 3, "unknown": 17}
  prefix 304: sat 3, unknown 1
  prefix 320/336/352/368: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w28_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w28_top4_304_368_t5000_20260604.json`.
The q-known frontier improved to 487 bits, but no UNSAT/hard contradiction or
factor signal appeared. This reinforces that the current Hensel callback is a
ranking/timeout frontier, not yet a no-good generator.

`mixed_pq_lattice_probe.py` now has a diagnostic exact-product sample evaluator:

```text
--evaluate-samples --samples N --seed S
```

The evaluator samples active p variables, derives a canonical q-window value by
Hensel inversion modulo the q-window, and checks whether a candidate relation
cuts assignments that already satisfy that product window. It is still marked
`sound_pruning_oracle=false` because omitted p/q bits remain.

Two smoke outputs were checked:

```text
/tmp/ct07_mixed_pq_eval_x0x7_m1_s0_samples8_20260604.json
  q_window=auto 150:774, rows/cols/rank=1/10/1
  classes={"candidate":1,"contains_q_terms":1,"not_integer_projection_multiple":1,"projection_derived":1}
  sample_counts={"product_mod_window_zero":8,"relation_mod_window_zero":8,"total":8}

/tmp/ct07_mixed_pq_eval_x0x7_q150w32_m1_s1_samples8_20260604_v2.json
  q_window=150:32, rows/cols/rank=4/20/4
  classes={"candidate":4,"contains_q_terms":4,"not_integer_projection_multiple":4,"projection_derived":4}
  first_sample_pruning_candidate=null
  first row sample_counts={"product_mod_window_zero":8,"relation_mod_window_zero":8,"total":8}
```

So the mixed p/q basis is structurally different from the old p-projection
basis, but the tested rows still behave like product-window multiples and do
not add sampled pruning. The next useful change is a richer mixed basis or a
different relation selection criterion, not another scan of the old LZ family.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 13: low-C 34.38%, high20 top68, x2w32 p-only, and richer mixed p/q smoke

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 22016..22528
elapsed_seconds=295.126
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=22528/65536
coverage_fraction=0.34375
first_missing_range=22528..65536
input_count=44
total_completion_checks=90112
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range22016_22528.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard22016_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_22528.json`.
JSON/JSONL parsed cleanly and shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 65..68 from the top80 ranking
source:

```text
rank=65 high16=0x026f x6high20=0x26f0 vars=600846 clauses=2697583 sat=false model_count=0
rank=66 high16=0x0279 x6high20=0x2790 vars=600711 clauses=2696852 sat=false model_count=0
rank=67 high16=0x0283 x6high20=0x2830 vars=600823 clauses=2697368 sat=false model_count=0
rank=68 high16=0x028d x6high20=0x28d0 vars=600799 clauses=2697305 sat=false model_count=0
```

The nearby `0x26e0` high20 run was also SAT false/model 0, but it is an
audit-only row from a mistyped candidate and is not counted in the top68
coverage total.

Aggregate outputs:
`/tmp/ct07_high20_next4m_exact_closure_20260604.json` and
`/tmp/ct07_high20_top68_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=68
sat=0
unsat=68
model_count_total=0
unique_closed_full_x6_values=68 * 2^26 = 4563402752
```

The p-only SAT+CAS probe widened x2 to 32 bits under full-zero `x1wide39`:

```text
range set 265:32,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=297/194/491
  top fixed ranges include x2[265..297)=0, x6 edge 798:4=0, p[920..923]=0x7

Hensel top4 at 304/320/336/352/368, timeout 5000ms:
  status_counts={"sat": 4, "unknown": 16}
  prefix 304: sat 4
  prefix 320/336/352/368: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w32_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w32_top4_304_368_t5000_20260604.json`.
The q-known frontier improved to 491 bits, but no UNSAT/hard contradiction or
factor signal appeared. As with x2w28, widening x2 now mostly exposes the
Hensel solver frontier at 320+ bits.

Two richer mixed p/q smoke tests also stayed negative:

```text
/tmp/ct07_mixed_pq_eval_x0x1x7_q150w32_m1_s1_samples16_20260604.json
  q_window=150:32, omitted_p_bits=364, omitted_q_bits=742
  rows/cols/rank=5/35/5
  classes={"candidate":5,"contains_q_terms":5,"not_integer_projection_multiple":5,"projection_derived":5}
  sample_counts={"product_mod_window_zero":16,"relation_mod_window_zero":16,"total":16}
  first_sample_pruning_candidate=null

/tmp/ct07_mixed_pq_eval_x0x7_q150w64_m1_s2_samples16_20260604.json
  q_window=150:64, omitted_p_bits=403, omitted_q_bits=710
  rows/cols/rank=10/35/10
  classes={"candidate":10,"contains_q_terms":10,"not_integer_projection_multiple":10,"projection_derived":10}
  sample_counts={"product_mod_window_zero":16,"relation_mod_window_zero":16,"total":16}
  first_sample_pruning_candidate=null
```

So adding `x1`, increasing q-window width, and increasing shift degree still
produces only product-window-following relations. This suggests the next mixed
p/q attempt should change row selection or add a second independent q/p window
rather than simply growing this single-`G` shift family.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 14: low-C 35.16%, high20 top72, and x2w36 p-only

The next low-C union shard also stayed negative:

```text
new shard: 22528..23040
elapsed_seconds=298.43
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=23040/65536
coverage_fraction=0.3515625
first_missing_range=23040..65536
input_count=45
total_completion_checks=92160
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range22528_23040.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard22528_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_23040.json`.
Shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 69..72:

```text
rank=69 high16=0x0296 x6high20=0x2960 vars=600849 clauses=2697561 sat=false model_count=0
rank=70 high16=0x02a0 x6high20=0x2a00 vars=600715 clauses=2697028 sat=false model_count=0
rank=71 high16=0x02aa x6high20=0x2aa0 vars=600824 clauses=2697392 sat=false model_count=0
rank=72 high16=0x02b3 x6high20=0x2b30 vars=600924 clauses=2697902 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4n_exact_closure_20260604.json` and
`/tmp/ct07_high20_top72_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=72
sat=0
unsat=72
model_count_total=0
unique_closed_full_x6_values=72 * 2^26 = 4831838208
```

The p-only SAT+CAS probe widened x2 to 36 bits:

```text
range set 265:36,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=301/194/495

Hensel top4 at 304/320/336/352/368, timeout 5000ms:
  status_counts={"sat": 4, "unknown": 16}
  prefix 304: sat 4
  prefix 320/336/352/368: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w36_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w36_top4_304_368_t5000_20260604.json`.
The q-known frontier improved to 495 bits, but the Hensel frontier stayed at
the same SAT/unknown split, so this is still not a hard pruning oracle.

`mixed_pq_lattice_probe.py` now accepts repeated `--q-window` options. The
single-window compatibility smoke stayed unchanged:

```text
/tmp/ct07_mixed_pq_compat_single_q150w32_m1_s1_samples8_20260604_v3.json
  q_windows=[150:32], rows/cols/rank=4/20/4
  q_gap_bits_inside_sample_modulus=0
  classes={"candidate":4,"contains_q_terms":4,"not_integer_projection_multiple":4,"projection_derived":4}
  sample_counts={"product_mod_window_zero":8,"relation_mod_window_zero":8,"total":8}
```

The two-window smoke used disjoint q windows `150:32` and `214:32`:

```text
/tmp/ct07_mixed_pq_multiq_x0x7_q150w32_q214w32_m1_s1_samples8_20260604_v3.json
  q_window_count=2, variables=["x0","x7","yq0","yq1"]
  q_gap_bits_inside_sample_modulus=32, q_gap_ranges=[182:32]
  rows/cols/rank=5/35/5
  classes={"candidate":5,"contains_q_terms":5,"not_integer_projection_multiple":5,"projection_derived":5,"sample_pruning_candidate":5,"sample_pruning_candidate_with_q_gap":5}
  first row sample_counts={"product_mod_window_zero":8,"relation_prunes_product_window":8,"total":8}
```

A follow-up q-window placement grid confirmed that this rejection is a q-gap
artifact, not a new sound pruning oracle. The gap-free adjacent case
`150:32 + 182:32` had `q_gap_bits_inside_sample_modulus=0` and no sampled
prune, while gap-bearing cases had only `sample_pruning_candidate_with_q_gap`:

```text
/tmp/ct07_mixed_pq_multiq_grid_x0x7_q150w32_q182w32_m1_s1_samples8_20260604_v3.json
  gap_bits=0, classes={"candidate":5,"contains_q_terms":5,"not_integer_projection_multiple":5,"projection_derived":5}
  sample_counts={"product_mod_window_zero":8,"relation_mod_window_zero":8,"total":8}

/tmp/ct07_mixed_pq_multiq_grid_x0x7_q150w32_q246w32_m1_s1_samples8_20260604_v3.json
  gap_bits=64, classes include "sample_pruning_candidate_with_q_gap":5

/tmp/ct07_mixed_pq_multiq_grid_x0x7_q150w32_q310w32_m1_s1_samples8_20260604_v3.json
  gap_bits=128, classes include "sample_pruning_candidate_with_q_gap":5

/tmp/ct07_mixed_pq_multiq_grid_x0x7_q150w16_q214w16_q310w16_m1_s1_samples8_20260604_v3.json
  gap_bits=128, classes include "sample_pruning_candidate_with_q_gap":6
```

So repeated q-window support is useful as a diagnostic, but the current
single-product relation still follows complete contiguous q coverage and only
appears to prune when the evaluator asks it to ignore q bits inside the checked
modulus. The next mixed p/q attempt should either include every q bit up to the
sampled modulus or introduce an exact completion/audit for the missing gap.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 15: low-C 35.94%, high20 top76, and x2w40 p-only

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 23040..23552
elapsed_seconds=330.948
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=23552/65536
coverage_fraction=0.359375
first_missing_range=23552..65536
input_count=46
total_completion_checks=94208
unique_oracle_cases_total=23552
hard_eligible_total_count=94208
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range23040_23552.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard23040_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_23552.json`.
Shard/analyzer stderr files were 0 bytes.

The high20 exact-carry closure consumed ranks 73..76:

```text
rank=73 high16=0x02bd x6high20=0x2bd0 vars=600857 clauses=2697599 sat=false model_count=0
rank=74 high16=0x02c7 x6high20=0x2c70 vars=600832 clauses=2697397 sat=false model_count=0
rank=75 high16=0x02d1 x6high20=0x2d10 vars=600762 clauses=2697146 sat=false model_count=0
rank=76 high16=0x02da x6high20=0x2da0 vars=600806 clauses=2697417 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4o_exact_closure_20260604.json` and
`/tmp/ct07_high20_top76_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=76
sat=0
unsat=76
model_count_total=0
unique_closed_full_x6_values=76 * 2^26 = 5100273664
```

The p-only SAT+CAS probe widened x2 to 40 bits:

```text
range set 265:40,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=305/194/499

Hensel top4 at 304/320/336/352/368/384, timeout 5000ms:
  status_counts={"sat": 5, "unknown": 19}
  prefix 304: sat 4
  prefix 320: unknown 4
  prefix 336: sat 1, unknown 3
  prefix 352/368/384: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w40_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w40_top4_304_384_t5000_20260604.json`.
The q-known frontier improved to 499 bits, but no UNSAT/hard contradiction or
factor signal appeared.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 16: low-C 36.72%, high20 top80, x2w44 p-only, and mixed/TK-LZ/Sumset audit

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 23552..24064
elapsed_seconds=503.877
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=24064/65536
coverage_fraction=0.3671875
first_missing_range=24064..65536
input_count=47
total_completion_checks=96256
unique_oracle_cases_total=24064
hard_eligible_total_count=96256
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range23552_24064.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard23552_512.json`,
and aggregate `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_24064.json`.
The batch, shard, and aggregate stderr files were all 0 bytes.

The high20 exact-carry closure consumed ranks 77..80 and finished the top80
source:

```text
rank=77 high16=0x02e4 x6high20=0x2e40 vars=600743 clauses=2697061 sat=false model_count=0
rank=78 high16=0x02ee x6high20=0x2ee0 vars=600774 clauses=2697194 sat=false model_count=0
rank=79 high16=0x02f8 x6high20=0x2f80 vars=600660 clauses=2696671 sat=false model_count=0
rank=80 high16=0x0301 x6high20=0x3010 vars=600841 clauses=2697565 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next4p_exact_closure_20260604.json` and
`/tmp/ct07_high20_top80_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=80
sat=0
unsat=80
model_count_total=0
unique_closed_full_x6_values=80 * 2^26 = 5368709120
```

The p-only SAT+CAS probe widened x2 to 44 bits under full-zero `x1wide39`:

```text
range set 265:44,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=309/194/503
  top fixed ranges include x2[265..309)=0, x6 edge 798:4=0, p[920..923]=0x7

Hensel top4 at 304/320/336/352/368/384/400, timeout 5000ms:
  status_counts={"sat": 7, "unknown": 21}
  prefix 304: sat 4
  prefix 320: sat 3, unknown 1
  prefix 336/352/368/384/400: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w44_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w44_top4_304_400_t5000_20260604.json`.
The q-known frontier improved to 503 bits, but still produced no UNSAT/hard
contradiction or factor signal.

The mixed p/q audit pushed the repeated-q-window family through gap-free
contiguous q coverage. All tested rows stayed projection-derived and followed
the product window; none produced sampled pruning:

```text
/tmp/ct07_mixed_pq_contig_x0x7_q150w96_single_m1_s1_samples8_20260604.json
  gap_bits=0, rows/cols/rank=4/20/4, sample_counts={"product_mod_window_zero":8,"relation_mod_window_zero":8,"total":8}

/tmp/ct07_mixed_pq_contig_x0x7_q150w128_single_m1_s2_samples8_20260604.json
  gap_bits=0, rows/cols/rank=10/35/10, sample prune=0

/tmp/ct07_mixed_pq_contig_x0x7_q150_182_214_m2_s1_samples8_20260604.json
  gap_bits=0, rows/cols/rank=12/252/12, sample prune=0

/tmp/ct07_mixed_pq_contig_x0x1x7_q150_182_214_m1_s2_samples8_20260604.json
  gap_bits=0, rows/cols/rank=28/210/28, sample prune=0
```

This strengthens the round14 conclusion: the apparent multi-q pruning was a
q-gap artifact, and the current single-product mixed p/q family does not give
an independent oracle when q coverage is contiguous.

The TK/LZ unknown-divisor audit also stayed negative while keeping the small
`x0/x7` variables inside the model:

```text
/tmp/ct07_tklz_preflight_all8_m10_t4_20260604.json
  active_sum_bits=411, small_variables_kept=true, best_margin_bits=-675.9520767837131

/tmp/ct07_tklz_preflight_low_edge6_m10_t4_20260604.json
  active_sum_bits=255, small_variables_kept=true, best_margin_bits=-410.38539312027046

/tmp/ct07_tklz_depth_low_edge_all8_m23_t12_20260604.json
  executed_job_count=12, nonderived_count=0, extra_prune_count=0, best_prune_score=0
```

Finally, the Sumset preflight did not identify a better shift family. The
static growth ratios for `linear8/cuso8` were `3.67, 3.0, 2.6, 2.33` for shift
degrees `1..4`; `liftT_proxy` was worse at `5.55, 4.63, 4.02, 3.58`. These are
diagnostic only, but they agree with the current lack of non-projection
relations.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 17: low-C 37.50%, high20 top96, and x2w48 p-only

The low-C union proof advanced by one more 512-completion shard:

```text
new shard: 24064..24576
elapsed_seconds=618.659
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=24576/65536
coverage_fraction=0.375
first_missing_range=24576..65536
input_shards=48
total_completion_checks=98304
unique_oracle_cases_total=24576
hard_eligible_total_count=98304
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range24064_24576.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard24064_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_24576.json`.
The range stderr and aggregate stderr files were zero bytes.

The corrected q272 exact-carry high20 closure advanced ranks 81..96 from a
reproduced top96 ranking source; the first 80 source rows matched the earlier
top80 source. All sixteen new parents were SAT false with model count 0:

```text
rank=81 high16=0x030b x6high20=0x30b0 vars=600802 clauses=2697318 sat=false model_count=0
rank=82 high16=0x0315 x6high20=0x3150 vars=600801 clauses=2697290 sat=false model_count=0
rank=83 high16=0x031e x6high20=0x31e0 vars=600894 clauses=2697735 sat=false model_count=0
rank=84 high16=0x0328 x6high20=0x3280 vars=600603 clauses=2696468 sat=false model_count=0
rank=85 high16=0x0332 x6high20=0x3320 vars=600763 clauses=2697126 sat=false model_count=0
rank=86 high16=0x033c x6high20=0x33c0 vars=600675 clauses=2696858 sat=false model_count=0
rank=87 high16=0x0345 x6high20=0x3450 vars=600810 clauses=2697440 sat=false model_count=0
rank=88 high16=0x034f x6high20=0x34f0 vars=600834 clauses=2697433 sat=false model_count=0
rank=89 high16=0x0359 x6high20=0x3590 vars=600744 clauses=2697084 sat=false model_count=0
rank=90 high16=0x0362 x6high20=0x3620 vars=600831 clauses=2697522 sat=false model_count=0
rank=91 high16=0x036c x6high20=0x36c0 vars=600792 clauses=2697410 sat=false model_count=0
rank=92 high16=0x0376 x6high20=0x3760 vars=600738 clauses=2697088 sat=false model_count=0
rank=93 high16=0x0380 x6high20=0x3800 vars=600719 clauses=2696989 sat=false model_count=0
rank=94 high16=0x0389 x6high20=0x3890 vars=600863 clauses=2697651 sat=false model_count=0
rank=95 high16=0x0393 x6high20=0x3930 vars=600827 clauses=2697388 sat=false model_count=0
rank=96 high16=0x039d x6high20=0x39d0 vars=600765 clauses=2697159 sat=false model_count=0
```

Aggregate outputs:
`/tmp/ct07_high20_next16_exact_closure_20260604.json` and
`/tmp/ct07_high20_top96_exact_closure_20260604.json`.
The combined high20 parent closure is now:

```text
candidate_count=96
sat=0
unsat=96
unknown=0
model_count_total=0
unique_closed_full_x6_values=96 * 2^26 = 6442450944
```

The p-only SAT+CAS probe widened x2 to 48 bits under full-zero `x1wide39`:

```text
range set 265:48,798:4,920:4:
  q-growth top q_low/q_prefix/q_known=313/194/507
  top fixed ranges include x2[265..313)=0, x6 edge 798:4=0, p[920..923]=0x7

Hensel top4 at 304/320/336/352/368/384/400/416, timeout 5000ms:
  status_counts={"sat": 8, "unknown": 24}
  prefix 304: sat 4
  prefix 320: sat 4
  prefix 336/352/368/384/400/416: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w48_4096_20260604.json` and
`/tmp/ct07_p_only_hensel_x1w39_x2w48_top4_304_416_t5000_20260604.json`.
The q-known frontier improved to 507 bits, but still produced no UNSAT/hard
contradiction or factor signal.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 18: low-C 39.84%, high20 top112, and x2w56 p-only

The low-C union proof advanced three more 512-completion shards:

```text
new shard: 24576..25088
elapsed_seconds=406.366
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0

new shard: 25088..25600
elapsed_seconds=274.313
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0

new shard: 25600..26112
elapsed_seconds=344.638
unique_oracle_cases=512
total_completion_checks=2048
status_counts_total={"no_roots": 2048}
roots/factors=0
```

The contiguous aggregate reached `26112/65536 = 0.3984375`, with 51 input
shards, total completion checks `104448`, unique oracle cases `26112`, and
roots/factors `0`. Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_25088.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_25600.json`, and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_26112.json`.

The corrected q272 exact-carry high20 closure was extended from top96 to
top112 using the broad `/tmp/ct07_x6high16_fast_tail_top120_20260604.jsonl`
source. I excluded the wrapped low-high16 rows from the limited top112/top128
sources. Ranks 97..112 were all UNSAT, with model count 0:

```text
x6high20 values:
0x3a70, 0x3b00, 0x3ba0, 0x3c40, 0x3cd0, 0x3d70, 0x3e10, 0x3eb0,
0x3f40, 0x3fe0, 0x4080, 0x4110, 0x41b0, 0x4250, 0x42f0, 0x4380
```

The combined high20 parent closure became:

```text
candidate_count=112
sat=0
unsat=112
unknown=0
model_count_total=0
unique_closed_full_x6_values=112 * 2^26 = 7516192768
```

Outputs:
`/tmp/ct07_high20_top112_exact_closure_20260604.json`.

The p-only q-growth/Hensel path was pushed from `x2w48` to `x2w52` and
`x2w56` under full-zero `x1wide39`:

```text
x2w52: q_low/q_prefix/q_known=317/194/511, Hensel status_counts={"sat": 8, "unknown": 28}
x2w56: q_low/q_prefix/q_known=321/194/515, Hensel status_counts={"sat": 9, "unknown": 31}
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w52_4096_20260604.json`,
`/tmp/ct07_p_only_hensel_x1w39_x2w52_top4_304_432_t5000_20260604.json`,
`/tmp/ct07_p_only_qgrowth_x1w39_x2w56_4096_20260604.json`, and
`/tmp/ct07_p_only_hensel_x1w39_x2w56_top4_304_448_t5000_20260604.json`.
The q-known frontier improved to 515 bits, but still produced no UNSAT/hard
contradiction.

Two local side diagnostics were also negative. The mixed p/q single-product
probe with `x0,x1,x7`, q-window `150:128`, `m=1`, shift degree 2 had
rows/cols/rank `15/70/15`, q-gap 0, and no sampled or sound pruning oracle
(`/tmp/ct07_mixed_pq_contig_x0x1x7_q150w128_single_m1_s2_samples16_20260604.json`).
The Sumset preflight over `linear8,cuso8,liftT_proxy`, shift degrees `1..5`,
returned 30 rows and all had `signal_class=FAIL`
(`/tmp/ct07_sumset_round18_linear_cuso_liftproxy_s1_5_20260604.json`).

No factor or plaintext was recovered.

## 2026-06-04 parallel round 19: low-C 40.625%, high20 top120, and x2w64 p-only

The low-C union proof advanced one more 512-completion shard:

```text
new shard: 26112..26624
elapsed_seconds=330.339
status_counts_total={"no_roots": 2048}
unique_oracle_cases=512
total_completion_checks=2048
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=26624/65536
coverage_fraction=0.40625
first_missing_range=26624..65536
input_shards=52
total_completion_checks=106496
unique_oracle_cases_total=26624
hard_eligible_total_count=106496
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range26112_26624.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard26112_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_26624.json`.
The shard stderr file was zero bytes, and the aggregate has no gaps or overlaps
through `0..26624`.

The corrected q272 exact-carry high20 closure was extended from top112 to
top120 using the broad `/tmp/ct07_x6high16_fast_tail_top120_20260604.jsonl`
source. These rows continue the true high16 frontier; I did not count the
wrapped low-high16 rows from the limited top128/top144 sources. Ranks 113..120
were all UNSAT:

```text
rank=113 high16=0x0442 x6high20=0x4420 vars=600760 clauses=2697155 sat=false model_count=0
rank=114 high16=0x044c x6high20=0x44c0 vars=600668 clauses=2696835 sat=false model_count=0
rank=115 high16=0x0456 x6high20=0x4560 vars=600714 clauses=2696851 sat=false model_count=0
rank=116 high16=0x045f x6high20=0x45f0 vars=600906 clauses=2697807 sat=false model_count=0
rank=117 high16=0x0469 x6high20=0x4690 vars=600719 clauses=2697032 sat=false model_count=0
rank=118 high16=0x0473 x6high20=0x4730 vars=600792 clauses=2697297 sat=false model_count=0
rank=119 high16=0x047c x6high20=0x47c0 vars=600810 clauses=2697450 sat=false model_count=0
rank=120 high16=0x0486 x6high20=0x4860 vars=600640 clauses=2696602 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=120
sat=0
unsat=120
unknown=0
model_count_total=0
unique_closed_full_x6_values=120 * 2^26 = 8053063680
```

Outputs:
`/tmp/ct07_high20_true_r113_120_exact_closure_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r113_120_exact_closure_20260604.json`, and
`/tmp/ct07_high20_top120_exact_closure_20260604.json`.

The p-only q-growth/Hensel path was pushed to `x2w60` and `x2w64`:

```text
x2w60 range set 265:60,798:4,920:4:
  top q_low/q_prefix/q_known=325/194/519
  best fixed ranges: 265:60=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 11, "unknown": 33}
  prefix 304: sat 4
  prefix 320: sat 4
  prefix 336: sat 3, unknown 1
  prefix 352/368/384/400/416/432/448/464: unknown 4 each

x2w64 range set 265:64,798:4,920:4:
  top q_low/q_prefix/q_known=329/194/523
  best fixed ranges: 265:64=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 12, "unknown": 36}
  prefix 304: sat 4
  prefix 320: sat 4
  prefix 336: sat 4
  prefix 352/368/384/400/416/432/448/464/480: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w60_4096_20260604.json`,
`/tmp/ct07_p_only_hensel_x1w39_x2w60_top4_304_464_t5000_20260604.json`,
`/tmp/ct07_p_only_qgrowth_x1w39_x2w64_4096_20260604.json`,
and `/tmp/ct07_p_only_hensel_x1w39_x2w64_top4_304_480_t5000_20260604.json`.
Again, larger q-known counts did not produce any UNSAT/hard contradiction.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 20: low-C 42.1875%, high20 top136, and x2w72 p-only

The low-C union proof advanced two more 512-completion shards:

```text
new shard: 26624..27136
elapsed_seconds=353.319
status_counts_total={"no_roots": 2048}
unique_oracle_cases=512
total_completion_checks=2048
roots/factors=0

new shard: 27136..27648
elapsed_seconds=382.901
status_counts_total={"no_roots": 2048}
unique_oracle_cases=512
total_completion_checks=2048
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=27648/65536
coverage_fraction=0.421875
first_missing_range=27648..65536
input_shards=54
total_completion_checks=110592
unique_oracle_cases_total=27648
hard_eligible_total_count=110592
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range26624_27136.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range27136_27648.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard26624_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard27136_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_27648.json`.
Both shard stderr files were zero bytes, and the aggregate has no gaps or
overlaps through `0..27648`.

The corrected q272 exact-carry high20 closure was extended from top120 to
top136 using a fresh broad `/tmp/ct07_x6high16_fast_tail_top136_20260604.jsonl`
source over the full 16-bit `x6_high` range. Its first 120 rows exactly match
the prior broad top120 source on `rank`, `x6_high`, `tail848_score`,
`tail_cp_sat_argv`, and `combo_index`. Ranks 121..136 were all UNSAT:

```text
rank=121 high16=0x0490 x6high20=0x4900 vars=600727 clauses=2697018 sat=false model_count=0
rank=122 high16=0x049a x6high20=0x49a0 vars=600766 clauses=2697125 sat=false model_count=0
rank=123 high16=0x04a3 x6high20=0x4a30 vars=600871 clauses=2697679 sat=false model_count=0
rank=124 high16=0x04ad x6high20=0x4ad0 vars=600773 clauses=2697200 sat=false model_count=0
rank=125 high16=0x04b7 x6high20=0x4b70 vars=600775 clauses=2697197 sat=false model_count=0
rank=126 high16=0x04c0 x6high20=0x4c00 vars=600766 clauses=2697303 sat=false model_count=0
rank=127 high16=0x04ca x6high20=0x4ca0 vars=600889 clauses=2697740 sat=false model_count=0
rank=128 high16=0x04d4 x6high20=0x4d40 vars=600743 clauses=2697099 sat=false model_count=0
rank=129 high16=0x04de x6high20=0x4de0 vars=600785 clauses=2697218 sat=false model_count=0
rank=130 high16=0x04e7 x6high20=0x4e70 vars=600874 clauses=2697718 sat=false model_count=0
rank=131 high16=0x04f1 x6high20=0x4f10 vars=600741 clauses=2697106 sat=false model_count=0
rank=132 high16=0x04fb x6high20=0x4fb0 vars=600832 clauses=2697436 sat=false model_count=0
rank=133 high16=0x0505 x6high20=0x5050 vars=600686 clauses=2696771 sat=false model_count=0
rank=134 high16=0x050e x6high20=0x50e0 vars=600841 clauses=2697530 sat=false model_count=0
rank=135 high16=0x0518 x6high20=0x5180 vars=600735 clauses=2697106 sat=false model_count=0
rank=136 high16=0x0522 x6high20=0x5220 vars=600750 clauses=2697111 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=136
sat=0
unsat=136
unknown=0
model_count_total=0
unique_closed_full_x6_values=136 * 2^26 = 9126805504
```

Outputs:
`/tmp/ct07_high20_true_r121_136_exact_closure_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r121_136_exact_closure_20260604.json`, and
`/tmp/ct07_high20_top136_exact_closure_20260604.json`.

The p-only q-growth/Hensel path was pushed to `x2w68` and `x2w72`:

```text
x2w68 range set 265:68,798:4,920:4:
  top q_low/q_prefix/q_known=333/194/527
  best fixed ranges: 265:68=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 12, "unknown": 40}
  prefix 304/320/336: sat 4 each
  prefix 352/368/384/400/416/432/448/464/480/496: unknown 4 each

x2w72 range set 265:72,798:4,920:4:
  top q_low/q_prefix/q_known=337/194/531
  best fixed ranges: 265:72=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 12, "unknown": 44}
  prefix 304/320/336: sat 4 each
  prefix 352/368/384/400/416/432/448/464/480/496/512: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w68_4096_20260604.json`,
`/tmp/ct07_p_only_hensel_x1w39_x2w68_top4_304_496_t5000_20260604.json`,
`/tmp/ct07_p_only_qgrowth_x1w39_x2w72_4096_20260604.json`,
and `/tmp/ct07_p_only_hensel_x1w39_x2w72_top4_304_512_t5000_20260604.json`.
The q-known frontier improved to 531 bits, but still produced no UNSAT/hard
contradiction.

The local mixed p/q and Sumset follow-ups remained negative:

```text
/tmp/ct07_mixed_pq_contig_x0x1x7_q150w192_single_m1_s2_samples16_20260604.json
  q_window=150:192
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=582

/tmp/ct07_sumset_round21_linear_cuso_liftproxy_s7_20260604.json
  rows=6
  all signal_class=FAIL
  degree-7 linear8/cuso8 growth_ratio=1.0 but capped at 5000
  liftT_proxy growth_ratio=1.19/1.69 and capped

/tmp/ct07_sumset_round22_linear_cuso_liftproxy_s8_20260604.json
  rows=6
  all signal_class=FAIL
  degree-8 linear8/cuso8 growth_ratio=1.0 but capped at 5000
  liftT_proxy growth_ratio=1.16 at T=600 and capped at T=784
```

No factor or plaintext was recovered.

## 2026-06-04 parallel round 21: low-C 42.96875%, high20 top152, and x2w80 p-only

The low-C union proof advanced one more 512-completion shard:

```text
new shard: 27648..28160
elapsed_seconds=397.526
status_counts_total={"no_roots": 2048}
unique_oracle_cases=512
total_completion_checks=2048
roots/factors=0
```

The contiguous aggregate is now:

```text
covered_completion_count_per_variant=28160/65536
coverage_fraction=0.4296875
first_missing_range=28160..65536
input_shards=55
total_completion_checks=112640
unique_oracle_cases_total=28160
hard_eligible_total_count=112640
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range27648_28160.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard27648_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_28160.json`.
The shard stderr file was zero bytes, and the aggregate has no gaps or overlaps
through `0..28160`.

The corrected q272 exact-carry high20 closure was extended from top136 to
top152 using a fresh broad `/tmp/ct07_x6high16_fast_tail_top152_20260604.jsonl`
source over the full 16-bit `x6_high` range. Its first 136 rows exactly match
the prior broad top136 source on `rank`, `x6_high`, `tail848_score`,
`tail_cp_sat_argv`, and `combo_index`. Ranks 137..152 were all UNSAT:

```text
rank=137 high16=0x052b x6high20=0x52b0 vars=600839 clauses=2697544 sat=false model_count=0
rank=138 high16=0x0535 x6high20=0x5350 vars=600704 clauses=2696813 sat=false model_count=0
rank=139 high16=0x053f x6high20=0x53f0 vars=600798 clauses=2697290 sat=false model_count=0
rank=140 high16=0x0549 x6high20=0x5490 vars=600756 clauses=2697140 sat=false model_count=0
rank=141 high16=0x0552 x6high20=0x5520 vars=600816 clauses=2697457 sat=false model_count=0
rank=142 high16=0x055c x6high20=0x55c0 vars=600693 clauses=2696921 sat=false model_count=0
rank=143 high16=0x0566 x6high20=0x5660 vars=600795 clauses=2697283 sat=false model_count=0
rank=144 high16=0x056f x6high20=0x56f0 vars=600896 clauses=2697812 sat=false model_count=0
rank=145 high16=0x0579 x6high20=0x5790 vars=600839 clauses=2697545 sat=false model_count=0
rank=146 high16=0x0583 x6high20=0x5830 vars=600809 clauses=2697330 sat=false model_count=0
rank=147 high16=0x058d x6high20=0x58d0 vars=600727 clauses=2697022 sat=false model_count=0
rank=148 high16=0x0596 x6high20=0x5960 vars=600809 clauses=2697459 sat=false model_count=0
rank=149 high16=0x05a0 x6high20=0x5a00 vars=600728 clauses=2696996 sat=false model_count=0
rank=150 high16=0x05aa x6high20=0x5aa0 vars=600772 clauses=2697202 sat=false model_count=0
rank=151 high16=0x05b4 x6high20=0x5b40 vars=600636 clauses=2696595 sat=false model_count=0
rank=152 high16=0x05bd x6high20=0x5bd0 vars=600848 clauses=2697593 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=152
sat=0
unsat=152
unknown=0
model_count_total=0
unique_closed_full_x6_values=152 * 2^26 = 10200547328
```

Outputs:
`/tmp/ct07_high20_true_r137_152_exact_closure_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r137_152_exact_closure_20260604.json`, and
`/tmp/ct07_high20_top152_exact_closure_20260604.json`.

The p-only q-growth/Hensel path was pushed to `x2w76` and `x2w80`:

```text
x2w76 range set 265:76,798:4,920:4:
  top q_low/q_prefix/q_known=341/194/535
  best fixed ranges: 265:76=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 15, "unknown": 45}
  prefix 304/320/336: sat 4 each
  prefix 352: sat 3, unknown 1
  prefix 368/384/400/416/432/448/464/480/496/512/528: unknown 4 each

x2w80 range set 265:80,798:4,920:4:
  top q_low/q_prefix/q_known=345/194/539
  best fixed ranges: 265:80=0x0, 798:4=0x0, 920:4=0x7
  Hensel status_counts={"sat": 16, "unknown": 48}
  prefix 304/320/336/352: sat 4 each
  prefix 368/384/400/416/432/448/464/480/496/512/528/544: unknown 4 each
```

Outputs:
`/tmp/ct07_p_only_qgrowth_x1w39_x2w76_4096_20260604.json`,
`/tmp/ct07_p_only_hensel_x1w39_x2w76_top4_304_528_t5000_20260604.json`,
`/tmp/ct07_p_only_qgrowth_x1w39_x2w80_4096_20260604.json`,
and `/tmp/ct07_p_only_hensel_x1w39_x2w80_top4_304_544_t5000_20260604.json`.
The q-known frontier improved to 539 bits, but still produced no UNSAT/hard
contradiction.

The local mixed p/q and Sumset follow-ups remained negative:

```text
/tmp/ct07_mixed_pq_contig_x0x1x7_q150w224_single_m1_s2_samples16_20260604.json
  q_window=150:224
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=550

/tmp/ct07_sumset_round23_linear_cuso_liftproxy_s9_20260604.json
  rows=6
  all signal_class=FAIL
  degree-9 linear8/cuso8 growth_ratio=1.0 but capped at 5000
```

No factor or plaintext was recovered.

## 2026-06-04 parallel round 24: low-C 43.75%, high20 top168, and x2w84 p-only

The next low-C union shard closed cleanly:

```text
new shard: 28160..28672
coverage: 28672/65536 = 0.4375
input_shards=56
total_completion_checks=114688
unique_oracle_cases=28672
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range28160_28672.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard28160_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_28672.json`.
The aggregate has no gaps or overlaps through `0..28672`; duplicate/retry
bookkeeping rows were excluded from the canonical count.

The corrected q272 exact-carry high20 closure advanced from top152 to top168
using a fresh full-range source:

```text
/tmp/ct07_x6high16_fast_tail_top168_20260604.jsonl
  first 152 rows match /tmp/ct07_x6high16_fast_tail_top152_20260604.jsonl

ranks 153..168:
  0x5c70, 0x5d10, 0x5da0, 0x5e40,
  0x5ee0, 0x5f80, 0x6010, 0x60b0,
  0x6150, 0x61e0, 0x6280, 0x6320,
  0x63c0, 0x6450, 0x64f0, 0x6590

SAT/UNSAT/UNKNOWN: 0/168/0
models/roots/factors: 0/0/0
vars range: 600603..600924
clauses range: 2696468..2697902
unique closed full-x6 values: 168 * 2^26 = 11274289152
```

Outputs:
`/tmp/ct07_high20_true_r153_168_exact_closure_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r153_168_exact_closure_20260604.json`, and
`/tmp/ct07_high20_top168_exact_closure_20260604.json`.

The p-only q-growth path reached the end of the valid zero x2 prefix:

```text
/tmp/ct07_p_only_qgrowth_x1w39_x2w84_4096_20260604.json
  best ranges: 265:84=0x0, 798:4=0x0, 920:4=0x7
  q_low/q_prefix/q_known=362/194/556

/tmp/ct07_p_only_qgrowth_x1w39_x2w88_4096_20260604.json
  0-byte failed run
  265:88=0 conflicts with already-known one bits p[349], p[351], p[352]
```

The fallback Hensel run on x2w84 remained non-pruning:

```text
/tmp/ct07_p_only_hensel_x1w39_x2w84_top4_304_560_t5000_20260604.json
  overall: sat=20, unknown=48, unsat=0
  prefix 304/320/336/352/368: sat 4 each
  prefix 384/400/416/432/448/464/480/496/512/528/544/560: unknown 4 each
```

The local non-SAT tracks were also negative:

```text
/tmp/ct07_mixed_pq_contig_x0x1x7_q150w256_single_m1_s2_samples16_20260604.json
  q_window=150:256
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=518

/tmp/ct07_sumset_round24_linear_cuso_liftproxy_s10_20260604.json
  rows=6
  all signal_class=FAIL
  all preflight_signal=FAIL_CAP
  degree-10 linear8/cuso8/liftT_proxy growth_ratio=1.0 but capped at 5000

/tmp/ct07_unknown_divisor_preflight_x012367_m14_t6_20260604.json
  active=x0,x1,x2,x3,x6,x7
  best TK/LZ proxy margin=-410.38539312027046 bits
```

No factor or plaintext was recovered.

## 2026-06-04 parallel round 25: low-C 44.53125%, high20 top184, and x3w8 p-only

The next low-C union shard closed cleanly:

```text
new shard: 28672..29184
elapsed_seconds=569.876
coverage: 29184/65536 = 0.4453125
input_shards=57
total_completion_checks=116736
hard_eligible_total_count=116736
unique_oracle_cases=29184
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range28672_29184.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard28672_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_29184.json`.
The aggregate has no gaps or overlaps through `0..29184`.

The corrected q272 exact-carry high20 closure advanced from top168 to top184
using `/tmp/ct07_x6high16_fast_tail_top184_20260604.jsonl`. Its first 168 rows
match `/tmp/ct07_x6high16_fast_tail_top168_20260604.jsonl`; the clean
rank-169..184 run used `/tmp/ct07_high20_true_r169_184_exact_closure_20260604_runs.jsonl`
and the cleaned retry log is
`/tmp/ct07_high20_true_r169_184_exact_closure_clean_20260604_runs.jsonl`.

```text
rank=169 high16=0x0663 x6high20=0x6630 vars=600709 clauses=2696853 sat=false model_count=0
rank=170 high16=0x066c x6high20=0x66c0 vars=600755 clauses=2697256 sat=false model_count=0
rank=171 high16=0x0676 x6high20=0x6760 vars=600806 clauses=2697325 sat=false model_count=0
rank=172 high16=0x0680 x6high20=0x6800 vars=600713 clauses=2697011 sat=false model_count=0
rank=173 high16=0x0689 x6high20=0x6890 vars=600814 clauses=2697508 sat=false model_count=0
rank=174 high16=0x0693 x6high20=0x6930 vars=600711 clauses=2696808 sat=false model_count=0
rank=175 high16=0x069d x6high20=0x69d0 vars=600723 clauses=2697004 sat=false model_count=0
rank=176 high16=0x06a7 x6high20=0x6a70 vars=600838 clauses=2697469 sat=false model_count=0
rank=177 high16=0x06b0 x6high20=0x6b00 vars=600817 clauses=2697483 sat=false model_count=0
rank=178 high16=0x06ba x6high20=0x6ba0 vars=600776 clauses=2697197 sat=false model_count=0
rank=179 high16=0x06c4 x6high20=0x6c40 vars=600729 clauses=2697052 sat=false model_count=0
rank=180 high16=0x06cd x6high20=0x6cd0 vars=600839 clauses=2697578 sat=false model_count=0
rank=181 high16=0x06d7 x6high20=0x6d70 vars=600849 clauses=2697596 sat=false model_count=0
rank=182 high16=0x06e1 x6high20=0x6e10 vars=600800 clauses=2697301 sat=false model_count=0
rank=183 high16=0x06eb x6high20=0x6eb0 vars=600811 clauses=2697365 sat=false model_count=0
rank=184 high16=0x06f4 x6high20=0x6f40 vars=600772 clauses=2697378 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=184
sat=0
unsat=184
unknown=0
model_count_total=0
root_count_total=0
factor_count_total=0
unique_closed_full_x6_values=184 * 2^26 = 12348030976
```

Output: `/tmp/ct07_high20_top184_exact_closure_20260604.json`.

The p-only q-growth branch kept the round24 x2w84 ceiling and added a small
x3 prefix. The top four x3w4 candidates had
`q_low/q_prefix/q_known=366/194/560`; the corresponding x3w8 run improved this
to `370/194/564` with no skipped inconsistent candidates:

```text
/tmp/ct07_p_only_qgrowth_x1w39_x2w84_x3w4_4096_20260604.json
  top4 q_low/q_prefix/q_known=366/194/560

/tmp/ct07_p_only_qgrowth_x1w39_x2w84_x3w8_4096_20260604.json
  top4 q_low/q_prefix/q_known=370/194/564
```

The x3w8 Hensel-tail exact check over prefixes `304..576` did not produce a
hard contradiction:

```text
/tmp/ct07_p_only_hensel_x1w39_x2w84_x3w8_top4_304_576_t5000_20260604.json
  sat=20
  unknown=52
  unsat=0
  roots/factors=0
```

The side preflights stayed negative or inconclusive:

```text
/tmp/ct07_mixed_pq_contig_x0x1x7_q150w288_single_m1_s2_samples16_20260604.json
  active_p=x0,x1,x7
  q_window=150:288
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=486

/tmp/ct07_unknown_divisor_preflight_x0123467_m14_t6_20260604.json
  active=x0,x1,x2,x3,x4,x6,x7
  best TK/LZ proxy margin=-556.3637166626786 bits
```

The Sumset degree-11 sidecars
`/tmp/ct07_sumset_round25_linear_cuso_liftproxy_s11_20260604.json` and
`/tmp/ct07_sumset_round25_linear_cuso_liftproxy_s11_cap3000_20260604.json`,
then the cap1000 and cap200 retries
`/tmp/ct07_sumset_round25_linear_cuso_liftproxy_s11_cap1000_20260604.json` and
`/tmp/ct07_sumset_round25_linear_cuso_liftproxy_s11_cap200_20260604.json`,
were stopped after producing zero-byte outputs, so they are not counted as
usable pruning or viability results.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 26: low-C 45.3125%, high20 top200, and x3w16 p-only growth

The next low-C union shard completed after a clean relaunch with a non-racing
JSONL path:

```text
new shard: 29184..29696
elapsed_seconds=312.915
coverage: 29696/65536 = 0.453125
input_shards=58
total_completion_checks=118784
hard_eligible_total_count=118784
unique_oracle_cases=29696
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range29184_29696_clean.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard29184_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_29696.json`.
The aggregate has no gaps or overlaps through `0..29696`.

The corrected q272 exact-carry high20 closure advanced from top184 to top200
using `/tmp/ct07_x6high16_fast_tail_top200_20260604.jsonl`. Its first 184 rows
match `/tmp/ct07_x6high16_fast_tail_top184_20260604.jsonl`; the rank-185..200
run used `/tmp/ct07_high20_true_r185_200_exact_closure_20260604_runs.jsonl`.

```text
rank=185 high16=0x06fe x6high20=0x6fe0 vars=600772 clauses=2697216 sat=false model_count=0
rank=186 high16=0x0708 x6high20=0x7080 vars=600683 clauses=2696887 sat=false model_count=0
rank=187 high16=0x0712 x6high20=0x7120 vars=600732 clauses=2696918 sat=false model_count=0
rank=188 high16=0x071b x6high20=0x71b0 vars=600902 clauses=2697838 sat=false model_count=0
rank=189 high16=0x0725 x6high20=0x7250 vars=600755 clauses=2697147 sat=false model_count=0
rank=190 high16=0x072f x6high20=0x72f0 vars=600805 clauses=2697306 sat=false model_count=0
rank=191 high16=0x0738 x6high20=0x7380 vars=600801 clauses=2697454 sat=false model_count=0
rank=192 high16=0x0742 x6high20=0x7420 vars=600635 clauses=2696579 sat=false model_count=0
rank=193 high16=0x074c x6high20=0x74c0 vars=600730 clauses=2697022 sat=false model_count=0
rank=194 high16=0x0756 x6high20=0x7560 vars=600758 clauses=2697151 sat=false model_count=0
rank=195 high16=0x075f x6high20=0x75f0 vars=600865 clauses=2697662 sat=false model_count=0
rank=196 high16=0x0769 x6high20=0x7690 vars=600766 clauses=2697194 sat=false model_count=0
rank=197 high16=0x0773 x6high20=0x7730 vars=600787 clauses=2697230 sat=false model_count=0
rank=198 high16=0x077c x6high20=0x77c0 vars=600746 clauses=2697235 sat=false model_count=0
rank=199 high16=0x0786 x6high20=0x7860 vars=600868 clauses=2697699 sat=false model_count=0
rank=200 high16=0x0790 x6high20=0x7900 vars=600733 clauses=2697062 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=200
sat=0
unsat=200
unknown=0
model_count_total=0
root_count_total=0
factor_count_total=0
unique_closed_full_x6_values=200 * 2^26 = 13421772800
```

Output: `/tmp/ct07_high20_top200_exact_closure_20260604.json`.

The p-only q-growth branch extended the round25 `x3w8` prefix. The top four
`370:4,798:4,920:4` candidates had `q_low/q_prefix/q_known=374/194/568`;
the `370:8,798:4,920:4` x3w16 candidates improved this to `378/194/572`.
High-side alternatives did not improve beyond the same values:

```text
/tmp/ct07_round26_qgrowth_x3next4_high798_920_20260604.json
  top4 q_low/q_prefix/q_known=374/194/568

/tmp/ct07_round26_qgrowth_x3next8_high798_920_20260604.json
  top4 q_low/q_prefix/q_known=378/194/572

/tmp/ct07_round26_qgrowth_x3next4_high_uncollided_20260604.json
  top rows q_low/q_prefix/q_known=374/194/568

/tmp/ct07_round26_qgrowth_x3w16_high_variants_20260604.json
  top rows q_low/q_prefix/q_known=378/194/572
```

The monolithic Hensel run
`/tmp/ct07_p_only_hensel_x1w39_x2w84_x3w12_top4_304_592_t5000_20260604.json`
was stopped as a zero-byte sidecar. The usable chunked Hensel evidence for
`370:4,798:4,920:4`, top4, prefixes `304..576`, and `t5000` is:

```text
/tmp/ct07_round26_hensel_x3next4_high798_920_top4_304_576_t5000_aggregate_20260604.json
  sat=23
  unknown=49
  unsat=0
  roots/factors=0
```

So the p-only q frontier improved by four more bits from x3w12 and another
four in x3w16 q-growth, but the exact Hensel callback still did not produce a
hard contradiction.

The local side preflights stayed negative or inconclusive:

```text
/tmp/ct07_round26_mixed_pq_contig_x0x1x7_q150w320_single_m1_s2_samples16_20260604.json
  q_window=150:320
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=454

/tmp/ct07_round26_mixed_pq_contig_x0x1x7_q150w352_single_m1_s2_samples16_20260604.json
  q_window=150:352
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=422

/tmp/ct07_round26_unknown_divisor_preflight_all8_m14_t6_w220_d3_20260604.json
  active=x0,x1,x2,x3,x4,x5,x6,x7
  best TK/LZ proxy margin=-675.9520767837131 bits

/tmp/ct07_round26_unknown_divisor_preflight_x0123567_m14_t6_w220_d3_20260604.json
  active=x0,x1,x2,x3,x5,x6,x7
  best TK/LZ proxy margin=-565.5303833293451 bits

/tmp/ct07_round26_unknown_divisor_preflight_x0123457_m14_t6_w220_d3_20260604.json
  active=x0,x1,x2,x3,x4,x5,x7
  best TK/LZ proxy margin=-577.2433462923082 bits
```

The Sumset degree-11/12 cap100/200 sweep and proxy run were both stopped after
zero-byte outputs, so they are not counted as usable viability results:
`/tmp/ct07_round26_sumset_linear_cuso_liftproxy_s11_s12_caps100_200_20260604.json`
and `/tmp/ct07_round26_sumset_proxy_s11_s12_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 27: low-C 46.09375%, high20 top216, and x3w20 p-only growth

One additional low-C union shard completed after the round26 summary:

```text
new shard: 29696..30208
coverage: 30208/65536 = 0.4609375
input_shards=59
total_completion_checks=120832
hard_eligible_total_count=120832
unique_oracle_cases=30208
overlap_completion_count_per_variant=0
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range29696_30208_round27.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard29696_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_30208.json`.
The aggregate has no gaps through `0..30208`; the remaining missing range is
`30208..65536`.

The corrected q272 exact-carry high20 closure advanced from top200 to top216
using `/tmp/ct07_x6high16_fast_tail_top216_20260604.jsonl`. Its first 200 rows
match `/tmp/ct07_x6high16_fast_tail_top200_20260604.jsonl`; the rank-201..216
run used `/tmp/ct07_high20_true_r201_216_exact_closure_20260604_runs.jsonl`.

```text
rank=201 high16=0x079a x6high20=0x79a0 vars=600758 clauses=2697124 sat=false model_count=0
rank=202 high16=0x07a3 x6high20=0x7a30 vars=600858 clauses=2697616 sat=false model_count=0
rank=203 high16=0x07ad x6high20=0x7ad0 vars=600733 clauses=2697033 sat=false model_count=0
rank=204 high16=0x07b7 x6high20=0x7b70 vars=600838 clauses=2697434 sat=false model_count=0
rank=205 high16=0x07c1 x6high20=0x7c10 vars=600689 clauses=2696783 sat=false model_count=0
rank=206 high16=0x07ca x6high20=0x7ca0 vars=600816 clauses=2697465 sat=false model_count=0
rank=207 high16=0x07d4 x6high20=0x7d40 vars=600734 clauses=2697093 sat=false model_count=0
rank=208 high16=0x07de x6high20=0x7de0 vars=600770 clauses=2697194 sat=false model_count=0
rank=209 high16=0x07e7 x6high20=0x7e70 vars=600842 clauses=2697553 sat=false model_count=0
rank=210 high16=0x07f1 x6high20=0x7f10 vars=600709 clauses=2696810 sat=false model_count=0
rank=211 high16=0x07fb x6high20=0x7fb0 vars=600810 clauses=2697334 sat=false model_count=0
rank=212 high16=0x0805 x6high20=0x8050 vars=600778 clauses=2697221 sat=false model_count=0
rank=213 high16=0x080e x6high20=0x80e0 vars=600830 clauses=2697503 sat=false model_count=0
rank=214 high16=0x0818 x6high20=0x8180 vars=600687 clauses=2696879 sat=false model_count=0
rank=215 high16=0x0822 x6high20=0x8220 vars=600796 clauses=2697292 sat=false model_count=0
rank=216 high16=0x082b x6high20=0x82b0 vars=600901 clauses=2697796 sat=false model_count=0
```

The combined high20 parent closure is now:

```text
candidate_count=216
sat=0
unsat=216
unknown=0
model_count_total=0
root_count_total=0
factor_count_total=0
unique_closed_full_x6_values=216 * 2^26 = 14495514624
```

Output: `/tmp/ct07_high20_top216_exact_closure_20260604.json`.

The p-only q-growth branch extended the x3 side from x3w16 to x3w20 with
`378:4,798:4,920:4` after the fixed x1/x2/x3 base
`150:4=0,210:39=0,265:84=0,362:16=0`. The top four candidates improved to:

```text
/tmp/ct07_round27_qgrowth_x3w20_high798_920_20260604.json
  top4 q_low/q_prefix/q_known=382/194/576
```

The chunked Hensel evidence for the same candidates, prefixes `304..576`, and
`t5000` is:

```text
/tmp/ct07_round27_hensel_x3w20_high798_920_top4_304_576_t5000_aggregate_20260604.json
  sat=24
  unknown=48
  unsat=0
  roots/factors=0
```

So x3w20 adds four more q-known bits beyond the round26 x3w16 frontier, but the
exact Hensel callback still does not yield a hard no-good.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 28: low-C 46.875%, high20 top216, and x3/high826 p-only

The next low-C union shard completed:

```text
new shard: 30208..30720
coverage: 30720/65536 = 0.46875
input_shards=60
total_completion_checks=122880
hard_eligible_total_count=122880
unique_oracle_cases=30720
overlap_completion_count_per_variant=0
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range30208_30720_round28.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard30208_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_30720.json`.
The aggregate has no gaps through `0..30720`; the remaining missing range is
`30720..65536`.

The corrected q272 exact-carry high20 closure was re-verified through top216.
The rank-201..216 batch remained all UNSAT:

```text
x6high20 values:
0x79a0 0x7a30 0x7ad0 0x7b70 0x7c10 0x7ca0 0x7d40 0x7de0
0x7e70 0x7f10 0x7fb0 0x8050 0x80e0 0x8180 0x8220 0x82b0

candidate_count=216
sat=0
unsat=216
unknown=0
model_count_total=0
root_count_total=0
factor_count_total=0
unique_closed_full_x6_values=216 * 2^26 = 14495514624
```

Outputs:
`/tmp/ct07_high20_true_r201_216_exact_closure_round28_20260604.json`,
`/tmp/ct07_high20_true_r201_216_exact_closure_round28_20260604_runs.jsonl`,
`/tmp/ct07_high20_top216_exact_closure_round28_20260604.json`, and
`/tmp/ct07_high20_top216_exact_closure_round28_20260604_verify.json`.

The p-only SAT+CAS q-growth branch changed the high-side selector from the
previous `798:4`/x3w20 sidecar to a base+x3/high826 layout. Valid scanned
families were:

```text
378:8,798:4,920:4
378:8,{784,792,802,810,818,826}:4,920:4
378:4,{784,792,802,810,818}:8,920:4
```

The best candidate is from `378:8,826:4,920:4`:

```text
best values: 378:8=0x0, 826:4=0x0, 920:4=0x8
q_low/q_prefix/q_known=386/198/584
gain=+8/+98/+106 over the base branch
```

The corresponding chunked Hensel evidence for top4 candidates, prefixes
`304..576`, and `t5000` was:

```text
sat=25
unknown=47
unsat=0
roots/factors=0
```

Outputs:
`/tmp/ct07_round28_qgrowth_base_x3w8_high798_920_top20_20260604.json`,
`/tmp/ct07_round28_qgrowth_base_x3w8_highalts_4bit_top20_20260604.json`,
`/tmp/ct07_round28_qgrowth_base_x3w4_highalts_8bit_top20_20260604.json`, and
`/tmp/ct07_round28_hensel_base_x3w8_high826_top4_304_576_t5000_aggregate_20260604.json`.
So this variant improves q-known to 584 bits, but the Hensel callback still
does not produce a hard contradiction.

Side preflights:

```text
/tmp/ct07_round28_mixed_pq_contig_x0x1x7_q150w384_single_m1_s2_samples16_20260604.json
  q_window=150:384
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=390

/tmp/ct07_round28_mixed_pq_contig_x0x1x7_q150w416_single_m1_s2_samples16_20260604.json
  q_window=150:416
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=358

/tmp/ct07_round28_unknown_divisor_preflight_x0123467_m16_t8_w260_d3_20260604.json
  active=x0,x1,x2,x3,x4,x6,x7
  best TK/LZ proxy margin=-556.3637166626786 bits

/tmp/ct07_round28_unknown_divisor_preflight_x0123567_m16_t8_w260_d3_20260604.json
  active=x0,x1,x2,x3,x5,x6,x7
  best TK/LZ proxy margin=-565.5303833293451 bits
```

The degree-10 Sumset proxy retry timed out after a zero-byte output:
`/tmp/ct07_round28_sumset_proxy_s10_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 29: low-C 47.65625%, high20 top232, and q-known 600

The next low-C union shard completed. A duplicate runner with the same JSONL
target was stopped during the run; the final aggregate below was verified from
the per-shard summary JSONs.

```text
new shard: 30720..31232
coverage: 31232/65536 = 0.4765625
input_shards=61
total_completion_checks=124928
hard_eligible_total_count=124928
unique_oracle_cases=31232
overlap_completion_count_per_variant=0
roots/factors=0
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range30720_31232_round29.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard30720_512_round29_shard30720_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_31232_round29.json`.
The aggregate has no gaps through `0..31232`; the remaining missing range is
`31232..65536`.

The corrected q272 exact-carry high20 closure advanced from top216 to top232.
The new source `/tmp/ct07_x6high16_fast_tail_top232_round29_20260604.jsonl`
matches the previous top216 source on the first 216 rows. Ranks 217..232 were
all UNSAT:

```text
x6high20 values:
0x8350 0x83f0 0x8490 0x8520 0x85c0 0x8660 0x8700 0x8790
0x8830 0x88d0 0x8960 0x8a00 0x8aa0 0x8b40 0x8bd0 0x8c70

candidate_count=232
sat=0
unsat=232
unknown=0
model_count_total=0
root_count_total=0
factor_count_total=0
unique_closed_full_x6_values=232 * 2^26 = 15569256448
```

Outputs:
`/tmp/ct07_high20_true_r217_232_exact_closure_round29_20260604_runs.jsonl`
and `/tmp/ct07_high20_top232_exact_closure_round29_20260604.json`.

The p-only SAT+CAS q-growth branch improved the round28 base
`q_low/q_prefix/q_known=386/198/584` by adding a low surrogate and high selector.
The best candidates all have `386:8=0x0` and `818:8=*`:

```text
top fixed ranges:
386:8=0x0, 818:8=0x5
386:8=0x0, 818:8=0xf
386:8=0x0, 818:8=0x18
386:8=0x0, 818:8=0x22

best q_low/q_prefix/q_known=394/206/600
gain over round28 base=+8/+8/+16
```

Valid full-cube selectors in this pass were `784:4/8`, `792:4/8`, `802:4/8`,
`810:4/8`, `818:4/8`, `822:4`, and low surrogate `386:4/8`. Invalid or
non-growing selectors were `822:8`, `830:4/8`, `378:4/8/12`, and `382:4/8`
because of overlap, known-mask collision, or no added information.

The Hensel pass was extended through top4 prefixes `304..608` with `t5000`.
The final aggregate was:

```text
sat=28
unknown=52
unsat=0
roots/factors=0
```

Outputs:
`/tmp/ct07_round29_qgrowth_after_high826_validity_20260604.json`,
`/tmp/ct07_round29_qgrowth_after_high826_low386_highscan_top40_20260604.json`,
`/tmp/ct07_round29_hensel_after_high826_top4_304_592_t5000_aggregate_20260604.json`,
and `/tmp/ct07_round29_hensel_base_x3w16_high818_822_top4_304_608_t5000_aggregate_20260604.json`.
So q-known reaches 600 bits, but the exact Hensel callback still does not yield
a hard no-good.

The edge-folded Coron verifier-only side probe covered `x0=3..7`, all `x7`,
fixed `x1=0x9b183cdcc`, fixed `x6=0x245521490bd`, and full `x5` beam4. The
best q-ranking tie is unchanged:

```text
x7=0xa
x5=682:87:0x820181c20002018148
q_low/q_prefix/q_known=265/355/620
q_interval_width_bits=669
```

Coron verifier results:

```text
base profile: primitive_margin=144.0, reconstructed=13, roots/factors=0
x2 profile: primitive_margin=273.33333333333337, reconstructed=13, roots/factors=0
x5 profile: branch_infeasible
```

Outputs:
`/tmp/ct07_round29_edge_qx5_x0_3_7_x7_all_x1_9b_w87_beam4_pp16_20260604.json`,
`/tmp/ct07_round29_edge_oracle_x0_3_7_x7_a_x1_9b_fullx5_820181c20002018148_summary_20260604.json`,
and `/tmp/ct07_round29_edge_oracle_x0_{3,4,5,6,7}_x7_a_x1_9b_fullx5_820181c20002018148_base_x2_x5_20260604.json`.

Side preflights:

```text
/tmp/ct07_round29_mixed_pq_contig_x0x1x7_q150w448_single_m1_s2_samples16_20260604.json
  q_window=150:448
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=326

/tmp/ct07_round29_mixed_pq_contig_x0x1x7_q150w480_single_m1_s2_samples16_20260604.json
  q_window=150:480
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=294

/tmp/ct07_round29_mixed_pq_contig_x0x1x6x7_q150w416_m1_s2_samples12_20260604.json
  active=x0,x1,x6,x7
  q_window=150:416
  rows/cols/rank=21/126/21
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round29_mixed_pq_contig_x0x1x7_q150w448_m2_s1_samples12_20260604.json
  q_window=150:448
  rows/cols/rank=10/126/10
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round29_unknown_divisor_preflight_all8_m16_t8_w260_d3_20260604.json
  active=x0,x1,x2,x3,x4,x5,x6,x7
  best TK/LZ proxy margin=-675.9520767837131 bits

/tmp/ct07_round29_unknown_divisor_preflight_x0123457_m16_t8_w260_d3_20260604.json
  active=x0,x1,x2,x3,x4,x5,x7
  best TK/LZ proxy margin=-577.2433462923082 bits

/tmp/ct07_round29_lz_depth_edge7_m23_t12_samples8_20260604.json
  executed_job_count=12
  nonderived_count=0
  extra_prune_count=0
  timeout_count=6
```

The Sumset split retry produced only a usable `liftT_proxy` cap100 result, and
that result was `FAIL_CAP`; the `linear8` and `cuso8` degree-10 cap100 files
timed out as zero-byte outputs:
`/tmp/ct07_round29_sumset_liftT_proxy_s10_cap100_20260604.json`,
`/tmp/ct07_round29_sumset_linear8_s10_cap100_20260604.json`, and
`/tmp/ct07_round29_sumset_cuso8_s10_cap100_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 30: low-C 48.4375%, high20 top248, and q-known 616

This round used four side agents with disjoint `/tmp` output scopes:
low-C union coverage, high20 exact closure, p-only q-growth/Hensel, and
edge-folded verifier sweeps. No repository source files were modified by the
agents.

The low-C union proof advanced one more 512-completion shard:

```text
new shard: 31232..31744
aggregate coverage: 31744/65536 = 0.484375
input_count: 62
total completion checks: 126976
hard-eligible checks: 126976
unique oracle cases: 31744
overlap: 0
roots/factors: 0
merged range: 0..31744
missing range: 31744..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range31232_31744_round30.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard31232_512_round30_shard31232_512.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_31744_round30.json`.

The corrected q272 exact-carry high20 closure was extended from top232 to
top248. The broad-source first232 rows matched the previous top232 source on
`rank/combo_index/x6_high/tail848_score/branch_low/branch_high`, so the new
ranks are additive:

```text
new x6high20 ranks 233..248:
0x8d10 0x8da0 0x8e40 0x8ee0 0x8f80 0x9010 0x90b0 0x9150
0x91f0 0x9280 0x9320 0x93c0 0x9450 0x94f0 0x9590 0x9630

new batch: SAT=0, UNSAT=16, UNKNOWN=0, model/root/factor=0/0/0
aggregate top248: SAT=0, UNSAT=248, UNKNOWN=0, model/root/factor=0/0/0
vars range: 600603..600924
clauses range: 2696468..2697902
unique closed full x6 values: 248 * 2^26 = 16642998272
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top248_round30_20260604.jsonl`,
`/tmp/ct07_high20_true_r233_248_exact_closure_round30_20260604_runs.jsonl`,
and `/tmp/ct07_high20_top248_exact_closure_round30_20260604.json`.

The p-only SAT+CAS q-growth branch extended the round29 q-known 600 state by
testing valid low/high continuation selectors. All 22 checked range sets were
valid, including `394:8,810:8`, `394:8,802:8`, `394:8,792:8`, and
`394:8,402:4`. The best range set was `394:8,810:8`:

```text
best q_low/q_prefix/q_known = 402/214/616
gain over round29 q-known 600 = +8/+8/+16

top4 fixed additions:
394:8=0x0, 810:8=0x0, 818:8=0x5
394:8=0x0, 810:8=0x4, 818:8=0x22
394:8=0x0, 810:8=0x7, 818:8=0xf
394:8=0x0, 810:8=0x7, 818:8=0x18
```

The Hensel callback sweep over top4 prefixes `304..640` step 16 with `t5000`
still did not produce a hard contradiction:

```text
check_count=88
sat=28
unknown=60
unsat=0
roots/factors=0
```

Outputs:
`/tmp/ct07_round30_qgrowth_after_q600_validity_20260604.json`,
`/tmp/ct07_round30_qgrowth_after_q600_low394_highscan_top40_20260604.json`,
and `/tmp/ct07_round30_hensel_after_q600_top4_304_640_t5000_aggregate_20260604.json`.

The edge-folded Coron verifier-only branch tested four nearby x1 candidates
`0x8b183cdcc`, `0x9b183cdcb`, `0x9b183cdcd`, and `0xab183cdcc` with fixed
`x6=0x245521490bd`, `x0=3..7`, all `x7`, and full `x5` width 87. All 320
q-ranking branches reached the same ceiling:

```text
base before x5: q_low/q_prefix/q_known=265/255/520
best after full x5: q_low/q_prefix/q_known=265/355/620
q_interval_width_bits=669
script best: x0=0x3, x7=0xa, x5=682:87:0x820181c20002018148
```

Oracle reinforcement used `x0=0x3` for all four x1 candidates and all 16 x7
values, plus the x0 tie set `0x3..0x7` at `x7=0xa`. All oracle rows had
`status=ok`, primitive margin `144.0`, reconstructed polynomial count `13`,
short row count `13`, and root/factor `0`. This remains a success detector
only; no hard UNSAT clause is claimed from Coron failures.

Outputs:
`/tmp/ct07_round30_edge_qx5_x1alts_sweep_20260604.json`,
`/tmp/ct07_round30_edge_qx5_x1alts_summary_20260604.json`,
`/tmp/ct07_round30_edge_oracle_x1alts_x0_3_allx7_20260604.json`,
`/tmp/ct07_round30_edge_oracle_x1alts_x0_3_7_x7_a_runmeta_20260604.json`,
and `/tmp/ct07_round30_edge_oracle_x1alts_summary_20260604.json`.

Side preflights also remained negative:

```text
/tmp/ct07_round30_mixed_pq_contig_x0x1x7_q150w512_single_m1_s2_samples16_20260604.json
  q_window=150:512
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=262

/tmp/ct07_round30_mixed_pq_contig_x0x1x7_q150w544_single_m1_s2_samples16_20260604.json
  q_window=150:544
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=230

/tmp/ct07_round30_mixed_pq_contig_x0x1x5x7_q150w480_m1_s2_samples12_20260604.json
  active=x0,x1,x5,x7
  q_window=150:480
  rows/cols/rank=21/126/21
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=294

/tmp/ct07_round30_unknown_divisor_preflight_x0123467_m18_t10_w300_d3_20260604.json
  active=x0,x1,x2,x3,x4,x6,x7
  active_sum_bits=324
  monomial_count=120
  best TK/LZ proxy margin=-556.3637166626786 bits

/tmp/ct07_round30_sumset_liftT_proxy_s9_cap100_20260604.json
  T=600 and T=784 liftT_proxy rows both FAIL_CAP
  shift_degree=9, shift_count=2002, cap=100
```

The companion `linear8` and `cuso8` degree-9 cap100 Sumset files timed out as
zero-byte outputs, so they are not counted as usable viability signals:
`/tmp/ct07_round30_sumset_linear8_s9_cap100_20260604.json` and
`/tmp/ct07_round30_sumset_cuso8_s9_cap100_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 31: low-C 49.21875%, high20 top264, and q-known 632

The next low-C union shard `31744..32256` completed with `status=ok`:

```text
new shard: 31744..32256
aggregate coverage: 32256/65536 = 0.4921875
input shards: 63
total completion checks: 129024
unique oracle cases: 32256
roots/factors=0/0
merged range: 0..32256
missing range: 32256..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range31744_32256_round31.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard31744_512_round31_shard31744_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_32256_round31.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_32256.json`.

The corrected q272 exact-carry high20 closure advanced from top248 to top264.
The new broad source kept the first 248 ranked `x6_high` values identical to
the round30 source under stable fields `rank`, `combo_index`, `x6_high`,
`tail848_score`, `branch_low`, and `branch_high`; only the embedded Python argv
path differed because this run used the SAT venv Python.

```text
new x6high20 ranks 249..264:
0x96c0 0x9760 0x9800 0x9890
0x9930 0x99d0 0x9a70 0x9b00
0x9ba0 0x9c40 0x9ce0 0x9d70
0x9e10 0x9eb0 0x9f40 0x9fe0

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top264: SAT=0, UNSAT=264, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=264 * 2^26 = 17716740096
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top264_round31_20260604.jsonl`,
`/tmp/ct07_high20_true_r249_264_exact_closure_round31_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r249_264_exact_closure_round31_20260604.json`,
and `/tmp/ct07_high20_top264_exact_closure_round31_20260604.json`.

The p-only q-prefix growth moved the round30 `q_low/q_prefix/q_known=402/214/616`
frontier by adding the next low boundary `402:8=0x0` and high boundary
`802:8=0x0`:

```text
best q_low/q_prefix/q_known=410/222/632
gain from round30 q616: +8/+8/+16
best fixed ranges:
150:4=0x0, 210:39=0x0, 265:84=0x0,
362:16=0x0, 378:8=0x0, 386:8=0x0,
394:8=0x0, 402:8=0x0,
802:8=0x0, 810:8=0x0, 818:8=0x5,
826:4=0x0, 920:4=0x8
```

The primary high-scan artifact enumerated 560192 cubes across four q616 bases
and eight range sets; a guarded wrapper independently enumerated 297984
boundary cubes and reached the same best q632 frontier without inconsistent
range skips. Outputs:
`/tmp/ct07_round31_qgrowth_after_q616_validity_20260604.json`,
`/tmp/ct07_round31_qgrowth_after_q616_low402_highscan_top40_20260604.json`,
and `/tmp/ct07_round31_qgrowth_after_q616_low402_high802_top40_20260604.json`.

The q632 Hensel diagnostic checked the first-base top4 qgrowth candidates from
`--ranges 402:8,802:8` over prefix widths `304..704`, 5000ms per check:

```text
candidate_count=4
check_count=104
status_counts:
sat=33
unknown=71
unsat=0
roots/factors=0
```

The deepest chunk `640..704` was slow but completed; all rows were SAT or
UNKNOWN, so no hard no-good was obtained. Output:
`/tmp/ct07_round31_hensel_after_q616_top4_304_704_t5000_aggregate_20260604.json`.

The edge-folded Coron verifier-only track extended the round30 x1-alt sweep to
`x0=0x8..0xc`, all `x7`, four nearby full `x1` candidates, fixed
`x6=0x245521490bd`, and width-87 `x5` beam ranking:

```text
branch_count=320
ok/failed=320/0
base q_low/q_prefix/q_known=265/255/520
full-x5 q_low/q_prefix/q_known=265/355/620
interval_width=669
q-metric tie count=320
script-best x0=0x8, x1=0x8b183cdcc, x7=0xa
script-best x5=682:87:0x820181c20002018148
```

The bounded base-profile Coron oracle then selected 23 rows and all completed
as verifier attempts only:

```text
oracle rows=23
primitive_margin=144.0
short/reconstructed=13/13
roots/factors=0/0
```

Outputs:
`/tmp/ct07_round31_edge_qx5_x1alts_x0_8_12_sweep_20260604.json`,
`/tmp/ct07_round31_edge_qx5_x1alts_x0_8_12_summary_20260604.json`,
and `/tmp/ct07_round31_edge_oracle_x1alts_x0_8_12_summary_20260604.json`.

The independent side preflights did not produce a new pruning or viability
signal:

```text
/tmp/ct07_round31_mixed_pq_contig_x0x1x7_q150w576_single_m1_s2_samples16_20260604.json
  active=x0,x1,x7
  q_window=150:576
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=198

/tmp/ct07_round31_mixed_pq_contig_x0x1x7_q150w608_single_m1_s2_samples16_20260604.json
  active=x0,x1,x7
  q_window=150:608
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=166

/tmp/ct07_round31_mixed_pq_contig_x0x1x5x7_q150w512_m1_s2_samples12_20260604.json
  active=x0,x1,x5,x7
  q_window=150:512
  rows/cols/rank=21/126/21
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false
  omitted_q_bits=262

/tmp/ct07_round31_unknown_divisor_preflight_x0123467_m20_t12_w320_d3_20260604.json
  active=x0,x1,x2,x3,x4,x6,x7
  active_sum_bits=324
  monomial_count=120
  best TK/LZ proxy margin=-556.3637166626786 bits

/tmp/ct07_round31_unknown_divisor_preflight_x0123567_m20_t12_w320_d3_20260604.json
  active=x0,x1,x2,x3,x5,x6,x7
  active_sum_bits=342
  monomial_count=120
  best TK/LZ proxy margin=-565.5303833293451 bits

/tmp/ct07_round31_sumset_liftT_proxy_s10_cap100_20260604.json
  T=600 and T=784 liftT_proxy rows both FAIL_CAP
  shift_degree=10
  shift_count=3003
  density=30.03
```

No factor or plaintext was recovered.

## 2026-06-04 parallel round 32: low-C 50% and high20 top280

The next low-C union shard `32256..32768` completed with `status=ok`:

```text
new shard: 32256..32768
elapsed_seconds=301.089
aggregate coverage: 32768/65536 = 0.5
input shards: 64
total completion checks: 131072
unique oracle cases: 32768
roots/factors=0/0
merged range: 0..32768
missing range: 32768..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range32256_32768_round32.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard32256_512_round32_shard32256_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_32768_round32.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_32768.json`.

The corrected q272 exact-carry high20 closure advanced from top264 to top280.
The new source kept the first 264 ranked rows identical to the round31 source
under stable fields `rank`, `combo_index`, `x6_high`, `tail848_score`,
`branch_low`, and `branch_high`.

```text
new x6high20 ranks 265..280:
0xa080 0xa120 0xa1b0 0xa250
0xa2f0 0xa380 0xa420 0xa4c0
0xa560 0xa5f0 0xa690 0xa730
0xa7d0 0xa860 0xa900 0xa9a0

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top280: SAT=0, UNSAT=280, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=280 * 2^26 = 18790481920
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top280_round32_20260604.jsonl`,
`/tmp/ct07_high20_true_r265_280_exact_closure_round32_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r265_280_exact_closure_round32_20260604.json`,
and `/tmp/ct07_high20_top280_exact_closure_round32_20260604.json`.

The p-only q-prefix growth also advanced the q632 frontier by another
low/high boundary pair:

```text
best q_low/q_prefix/q_known=418/230/648
gain from round31 q632: +8/+8/+16
total emitted/accepted cubes=577664/577664
skipped inconsistent cubes=0
best new fixed ranges include:
410:8=0x0
794:8=0x0
802:8=0x1d
```

Output:
`/tmp/ct07_round32_qgrowth_after_q632_low410_highscan_top40_20260604.json`.

The q648 Hensel diagnostic checked the top4 qgrowth candidates directly
(`source_round31_rank=4,3,1,2`) from `320..736`, step 16, 5000ms per check:

```text
candidate_count=4
check_count=108
status_counts:
sat=29
unknown=79
unsat=0
roots/factors=0
elapsed_seconds=868.9529867172241
```

All rows were SAT or UNKNOWN, so no hard no-good was obtained. Output:
`/tmp/ct07_round32_hensel_after_q632_top4_320_736_t5000_aggregate_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 33: low-C 50.78125%, high20 top296, and q-known 664

The next low-C union shard `32768..33280` completed with `status=ok`:

```text
new shard: 32768..33280
elapsed_seconds=355.056
aggregate coverage: 33280/65536 = 0.5078125
input shards: 65
total completion checks: 133120
unique oracle cases: 33280
roots/factors=0/0
merged range: 0..33280
missing range: 33280..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range32768_33280_round33.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard32768_512_round33_shard32768_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_33280_round33.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_33280.json`.

The corrected q272 exact-carry high20 closure advanced from top280 to top296.
The new source kept the first 280 ranked rows identical to the round32 source
under stable fields `rank`, `combo_index`, `x6_high`, `tail848_score`,
`branch_low`, and `branch_high`.

```text
new x6high20 ranks 281..296:
0xaa30 0xaad0 0xab70 0xac10
0xaca0 0xad40 0xade0 0xae70
0xaf10 0xafb0 0xb050 0xb0e0
0xb180 0xb220 0xb2c0 0xb350

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top296: SAT=0, UNSAT=296, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=296 * 2^26 = 19864223744
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top296_round33_20260604.jsonl`,
`/tmp/ct07_high20_true_r281_296_exact_closure_round33_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r281_296_exact_closure_round33_20260604.json`,
and `/tmp/ct07_high20_top296_exact_closure_round33_20260604.json`.

The p-only q-prefix growth advanced the q648 frontier by another low/high
boundary pair:

```text
best q_low/q_prefix/q_known=426/238/664
gain from round32 q648: +8/+8/+16
total emitted/accepted cubes=577664/577664
skipped inconsistent cubes=0
best new fixed ranges include:
418:8=0x0
786:8=0x0
794:8=0x6
802:8=0x9
```

Output:
`/tmp/ct07_round33_qgrowth_after_q648_low418_highscan_top40_20260604.json`.

The q664 Hensel diagnostic checked the top4 qgrowth candidates directly
from `336..768`, step 16, 5000ms per check:

```text
candidate_count=4
check_count=112
status_counts:
sat=28
unknown=84
unsat=0
roots/factors=0
elapsed_seconds=797.5366237163544
```

All rows were SAT or UNKNOWN, so no hard no-good was obtained. Output:
`/tmp/ct07_round33_hensel_after_q664_top4_336_768_t5000_aggregate_20260604.json`.

The side preflights again produced no pruning or viability signal:

```text
/tmp/ct07_round33_mixed_pq_contig_x0x1x7_q150w640_single_m1_s2_samples16_20260604.json
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round33_mixed_pq_contig_x0x1x7_q150w672_single_m1_s2_samples16_20260604.json
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round33_mixed_pq_contig_x0x1x5x7_q150w544_m1_s2_samples12_20260604.json
  rows/cols/rank=21/126/21
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round33_unknown_divisor_preflight_x0123467_m22_t14_w340_d3_20260604.json
  best TK/LZ proxy margin=-556.3637166626786 bits

/tmp/ct07_round33_unknown_divisor_preflight_x0123567_m22_t14_w340_d3_20260604.json
  best TK/LZ proxy margin=-565.5303833293451 bits

/tmp/ct07_round33_sumset_liftT_proxy_s11_cap100_20260604.json
  T=600 and T=784 liftT_proxy rows both FAIL_CAP
  shift_degree=11
```

No factor or plaintext was recovered.

## 2026-06-04 parallel round 34: low-C 51.5625%, high20 top312, and q-known 689

The next low-C union shard `33280..33792` completed with `status=ok`:

```text
new shard: 33280..33792
elapsed_seconds=447.012
aggregate coverage: 33792/65536 = 0.515625
input shards: 66
total completion checks: 135168
unique oracle cases: 33792
roots/factors=0/0
merged range: 0..33792
missing range: 33792..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range33280_33792_round34.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard33280_512_round34_shard33280_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_33792_round34.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_33792.json`.

The corrected q272 exact-carry high20 closure advanced from top296 to top312.
The new source kept the first 296 ranked rows identical to the round33 source
under stable fields `rank`, `combo_index`, `x6_high`, `tail848_score`,
`branch_low`, and `branch_high`.

```text
new x6high20 ranks 297..312:
0xb3f0 0xb490 0xb520 0xb5c0
0xb660 0xb700 0xb790 0xb830
0xb8d0 0xb960 0xba00 0xbaa0
0xbb40 0xbbd0 0xbc70 0xbd10

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top312: SAT=0, UNSAT=312, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=312 * 2^26 = 20937965568
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top312_round34_20260604.jsonl`,
`/tmp/ct07_high20_true_r297_312_exact_closure_round34_20260604.json`,
and `/tmp/ct07_high20_top312_exact_closure_round34_20260604.json`.

The p-only q-prefix growth moved beyond the q664 frontier. The reliable
four-base rerun is the `full4` artifact below; an older one-base helper also
wrote a same-prefix non-`full4` file and should not be used as the round34
aggregate.

```text
best q_low/q_prefix/q_known=434/255/689
gain from round33 q664: +8/+17/+25
total emitted/accepted cubes=577664/7640
skipped inconsistent cubes=570024
best new fixed ranges include:
426:8=0x0
778:8=0xce
```

Output:
`/tmp/ct07_round34_qgrowth_after_q664_low426_highscan_top40_full4_20260604.json`.

The q689 Hensel diagnostic checked the top4 qgrowth candidates directly
from `352..800`, step 16, 5000ms per check:

```text
candidate_count=4
check_count=116
status_counts:
sat=27
unknown=89
unsat=0
roots/factors=0
elapsed_seconds=944.1447668075562
```

All rows were SAT or UNKNOWN, so no hard no-good was obtained. Output:
`/tmp/ct07_round34_hensel_after_q689_top4_352_800_t5000_aggregate_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 35: low-C 52.34375%, high20 top328, and q-known 856

The next low-C union shard `33792..34304` completed with `status=ok`:

```text
new shard: 33792..34304
elapsed_seconds=349.129
aggregate coverage: 34304/65536 = 0.5234375
input shards: 67
total completion checks: 137216
hard-eligible total: 137216
unique oracle cases: 34304
roots/factors=0/0
merged range: 0..34304
missing range: 34304..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range33792_34304_round35.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard33792_512_round35_shard33792_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_34304_round35.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_34304.json`.

The corrected q272 exact-carry high20 closure advanced from top312 to top328.
The new source kept the first 312 ranked rows identical to the round34 source
under stable fields `rank`, `combo_index`, `x6_high`, `tail848_score`,
`branch_low`, and `branch_high`.

```text
new x6high20 ranks 313..328:
0xbda0 0xbe40 0xbee0 0xbf80
0xc010 0xc0b0 0xc150 0xc1f0
0xc280 0xc320 0xc3c0 0xc450
0xc4f0 0xc590 0xc630 0xc6c0

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top328: SAT=0, UNSAT=328, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=328 * 2^26 = 22011707392
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top328_round35_20260604.jsonl`,
`/tmp/ct07_high20_true_r313_328_exact_closure_round35_20260604.json`,
and `/tmp/ct07_high20_top328_exact_closure_round35_20260604.json`.

The p-only q-prefix growth had a larger-than-usual jump. From the reliable
round34 `full4` q689 frontier, the `full4` rerun moved the best candidate to:

```text
best q_low/q_prefix/q_known=600/256/856
gain from round34 q689: +167
total emitted/accepted cubes=577664/1616
skipped inconsistent cubes=576048
best new fixed range:
434:8=0x80
768:8=0xe2
```

Output:
`/tmp/ct07_round35_qgrowth_after_q689_low434_highscan_top40_full4_20260604.json`.

The q856 Hensel diagnostic used streamed per-check writes over the top4
qgrowth candidates at prefix bits `600,608,624,...,800`, with a 5000ms solver
timeout. An earlier wider non-streamed attempt stalled near the `832`-bit
frontier, so this round treats `832+` as a resource frontier rather than a
sound contradiction.

```text
candidate_count=4
check_count=56
status_counts:
sat=8
unknown=48
unsat=0
roots/factors=0
elapsed_seconds=467.42577719688416
```

All streamed rows were SAT or UNKNOWN, so no hard no-good was obtained.
Output:
`/tmp/ct07_round35_hensel_after_q856_top4_600_800_t5000_aggregate_20260604.json`.

The side preflights again produced no pruning or viability signal:

```text
/tmp/ct07_round35_mixed_pq_contig_x0x1x7_q150w768_single_m1_s2_samples16_20260604.json
  rows/cols/rank=15/70/15
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round35_mixed_pq_contig_x0x1x7_q150w800_single_m1_s2_samples16_20260604.json
  status=skipped_invalid_q_window
  reason: q window overlaps already-known q bits

/tmp/ct07_round35_mixed_pq_contig_x0x1x5x7_q150w608_m1_s2_samples12_20260604.json
  rows/cols/rank=21/126/21
  q_gap_bits_inside_sample_modulus=0
  sampled_pruning_oracle=false
  sound_pruning_oracle=false

/tmp/ct07_round35_unknown_divisor_preflight_x0123467_m26_t18_w380_d3_20260604.json
  monomials=120
  determinant_proxy_bits=14580
  best TK/LZ proxy margin=-556.3637166626786 bits

/tmp/ct07_round35_unknown_divisor_preflight_x0123567_m26_t18_w380_d3_20260604.json
  monomials=120
  determinant_proxy_bits=15390
  best TK/LZ proxy margin=-565.5303833293451 bits

/tmp/ct07_round35_sumset_liftT_proxy_s13_cap100_20260604.json
  T=600 liftT_proxy status=FAIL_CAP
  shift_degree=13
  shift_count=8568
```

The edge-folded verifier-only probe for `x0=0xd..0xf`, all `x7`, two `x1`
candidates, and fixed `x6=0x245521490bd` produced 96/96 edge-ok diagnostics,
primitive margin `9.666666666666629..10.666666666666629`, and q-prefix
`252..255`. Root/LLL recovery was not run and no failure was used as a hard
clause. Output:
`/tmp/ct07_round35_edge_verifier_x0_d_f_allx7_x1_9b183cdcc_8b183cdcc_x6_245521490bd_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 36: low-C 53.125%, high20 top344, and q-known 864

The next low-C union shard `34304..34816` completed with `status=ok`:

```text
new shard: 34304..34816
elapsed_seconds=291.748
aggregate coverage: 34816/65536 = 0.53125
input shards: 68
total completion checks: 139264
hard-eligible total: 139264
unique oracle cases: 34816
roots/factors=0/0
merged range: 0..34816
missing range: 34816..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range34304_34816_round36.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard34304_512_round36_shard34304_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_34816_round36.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_34816.json`.

The corrected q272 exact-carry high20 closure advanced from top328 to top344:

```text
new x6high20 ranks 329..344:
0xc760 0xc800 0xc890 0xc930
0xc9d0 0xca70 0xcb00 0xcba0
0xcc40 0xcce0 0xcd70 0xce10
0xceb0 0xcf40 0xcfe0 0xd080

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top344: SAT=0, UNSAT=344, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=344 * 2^26 = 23085449216
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top344_round36_20260604.jsonl`,
`/tmp/ct07_high20_true_r329_344_exact_closure_round36_20260604.json`,
and `/tmp/ct07_high20_top344_exact_closure_round36_20260604.json`.

The p-only q-prefix growth extended the q856 frontier by 8 more known bits:

```text
best q_low/q_prefix/q_known=600/264/864
gain over round35 q856: +8
total emitted/accepted cubes=17044752/2052
skipped inconsistent cubes=17042700
best new fixed ranges:
442:4=0x9
760:8=0x1
```

Output:
`/tmp/ct07_round36_qgrowth_after_q856_low442_highscan_top40_20260604.json`.

The q864 Hensel diagnostic used a guarded runner over the top4 qgrowth
candidates at prefix bits `600,616,632,...,792`, with 5000ms solver timeout
and an 8s process guard. Several high-prefix rows hit the process guard, but
the resumed run completed the planned 52 checks:

```text
candidate_count=4
check_count=52
expected_check_count=52
complete=true
status_counts:
sat=8
unknown=34
process_timeout=10
roots/factors=0/0
```

No UNSAT row was produced, and process timeouts are not contradictions. Output:
`/tmp/ct07_round36_hensel_after_q864_top4_600_800_t5000_guarded_aggregate_20260604.json`.

Side preflights again produced no pruning or viability signal: mixed p/q
`x0,x1,x5,x7 q150w640` had rows/cols/rank `21/126/21`,
`q_gap_bits_inside_sample_modulus=0`, and sampled/sound pruning false; mixed
`x0,x1,x7 q150w832/864` was skipped because the q windows overlap already-known
q bits. TK/LZ `x0123467/x0123567` remained negative at
`-556.3637166626786` and `-565.5303833293451` bits, Sumset liftT degree14 was
`FAIL_DIM`, and the edge verifier-only 96 rows were all edge-ok but did not run
LLL/root recovery.

Outputs:
`/tmp/ct07_round36_mixed_pq_contig_x0x1x5x7_q150w640_m1_s2_samples12_20260604.json`,
`/tmp/ct07_round36_mixed_pq_contig_x0x1x7_q150w832_single_m1_s2_samples16_20260604.json`,
`/tmp/ct07_round36_mixed_pq_contig_x0x1x7_q150w864_single_m1_s2_samples16_20260604.json`,
`/tmp/ct07_round36_unknown_divisor_preflight_x0123467_m28_t20_w400_d3_20260604.json`,
`/tmp/ct07_round36_unknown_divisor_preflight_x0123567_m28_t20_w400_d3_20260604.json`,
`/tmp/ct07_round36_sumset_liftT_proxy_s14_cap100_20260604.json`,
and `/tmp/ct07_round36_edge_verifier_x0_d_f_allx7_x1_9b183cdcc_8b183cdcc_x6_245521490bd_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 37: low-C 53.90625%, high20 top360, and q-known 880

The next low-C union shard `34816..35328` completed with `status=ok`.
The JSONL target contains two appended `shard_done` rows from reruns, so the
coverage below was verified from the per-shard JSONs and the aggregate:

```text
new shard: 34816..35328
aggregate coverage: 35328/65536 = 0.5390625
input shards: 69
total completion checks: 141312
hard-eligible total: 141312
unique oracle cases: 35328
roots/factors=0/0
merged range: 0..35328
missing range: 35328..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range34816_35328_round37.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard34816_512_round37_shard34816_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_35328_round37.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_35328.json`.

The corrected q272 exact-carry high20 closure advanced from top344 to top360.
The new broad source matched the first 344 rows under stable fields
`rank/combo_index/x6_high/tail848_score/branch_low/branch_high`.

```text
new x6high20 ranks 345..360:
0xd120 0xd1b0 0xd250 0xd2f0
0xd380 0xd420 0xd4c0 0xd560
0xd5f0 0xd690 0xd730 0xd7d0
0xd860 0xd900 0xd9a0 0xda30

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top360: SAT=0, UNSAT=360, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=360 * 2^26 = 24159191040
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top360_round37_20260604.jsonl`,
`/tmp/ct07_high20_true_r345_360_exact_closure_round37_20260604.json`,
and `/tmp/ct07_high20_top360_exact_closure_round37_20260604.json`.

The p-only q-prefix growth extended the q864 frontier by 16 more known bits:

```text
best q_low/q_prefix/q_known=600/280/880
gain over round36 q864: +16
total emitted/accepted/evaluated cubes=4815120/142425/142425
skipped inconsistent cubes=4672695
skipped internal range collisions=122880
best new fixed ranges:
446:4=0xc
744:8=0x0
752:8=0x73
```

Output:
`/tmp/ct07_round37_qgrowth_after_q864_low446_highscan_top40_20260604.json`.

The q880 Hensel diagnostic used a guarded runner over the top4 qgrowth
candidates at prefix bits `600,616,632,...,792`, with 5000ms solver timeout
and an 8s process guard:

```text
candidate_count=4
check_count=52
expected_check_count=52
complete=true
status_counts:
sat=7
unknown=31
process_timeout=14
roots/factors=0/0
```

No UNSAT row was produced, and process timeouts are not contradictions. Output:
`/tmp/ct07_round37_hensel_after_q880_top4_600_800_t5000_guarded_aggregate_20260604.json`.

A follow-up q-growth sidecar from the q880 frontier reached
`q_low/q_prefix/q_known=600/288/888` with best new ranges
`458:4=0x7`, `466:8=0x1`, and `736:8=0x1`; this q888 sidecar has not yet
been Hensel-checked. Output:
`/tmp/ct07_round38_qgrowth_after_q872_low458_highscan_top40_20260604.json`.

Side preflights again produced no pruning or factor signal: mixed p/q
`x0,x1,x5,x7 q150w672` had rows/cols/rank `21/126/21`,
`q_gap_bits_inside_sample_modulus=0`, and sampled/sound pruning false; TK/LZ
`x0123467/x0123567` remained negative at `-556.3637166626786` and
`-565.5303833293451` bits; liftT actual/symbolic proxies were `FAIL_CAP` and
`FAIL_DIM`; and the 8-row edge verifier-only sweep had root/factor `0/0`.

Outputs:
`/tmp/ct07_round37_mixed_pq_contig_x0x1x5x7_q150w672_m1_s2_samples12_20260604.json`,
`/tmp/ct07_round37_unknown_divisor_preflight_x0123467_m30_t22_w420_d3_20260604.json`,
`/tmp/ct07_round37_unknown_divisor_preflight_x0123567_m30_t22_w420_d3_20260604.json`,
`/tmp/ct07_round37_liftT_actual_proxy_T600_s15_cap100_20260604.json`,
`/tmp/ct07_round37_sumset_liftT_proxy_T600_s15_20260604.json`,
and `/tmp/ct07_round37_edge_verifier_x1alts_7b_bb_x0_d_e_x7_0_a_x6_245521490bd_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 38: low-C 54.6875%, high20 top376, and q-known 904

The next low-C union shard `35328..35840` completed with `status=ok`:

```text
new shard: 35328..35840
elapsed_seconds=282.743
aggregate coverage: 35840/65536 = 0.546875
input shards: 70
total completion checks: 143360
hard-eligible total: 143360
unique oracle cases: 35840
roots/factors=0/0
merged range: 0..35840
missing range: 35840..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range35328_35840_round38.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot/x0_x1_x2_x3_16bit_shard35328_512_round38_shard35328_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_35840_round38.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_35840.json`.

The corrected q272 exact-carry high20 closure advanced from top360 to top376:

```text
new x6high20 ranks 361..376:
0xdad0 0xdb70 0xdc10 0xdca0
0xdd40 0xdde0 0xde70 0xdf10
0xdfb0 0xe050 0xe0e0 0xe180
0xe220 0xe2c0 0xe350 0xe3f0

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top376: SAT=0, UNSAT=376, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=376 * 2^26 = 25232932864
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top376_round38_20260604.jsonl`,
`/tmp/ct07_high20_true_r361_376_exact_closure_round38_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r361_376_exact_closure_round38_20260604.json`,
and `/tmp/ct07_high20_top376_exact_closure_round38_20260604.json`.

The previously unverified q888 sidecar was Hensel-checked with the same guarded
top4 runner and prefix bits `600,616,632,...,792`:

```text
candidate_count=4
check_count=52
expected_check_count=52
complete=true
status_counts:
sat=8
unknown=29
process_timeout=15
roots/factors=0/0
```

No UNSAT row was produced. Outputs:
`/tmp/ct07_round38_hensel_after_q888_top4_600_800_t5000_guarded_aggregate_20260604.json`
and `/tmp/ct07_round38_hensel_after_q888_top4_600_800_t5000_guarded_runs_20260604.jsonl`.

A follow-up q-growth scan from q888 reached a new q904 frontier:

```text
base q_low/q_prefix/q_known=600/288/888
best q_low/q_prefix/q_known=600/304/904
total emitted/accepted/evaluated cubes=17171456/263681/263681
skipped inconsistent cubes=16907775
best new fixed ranges:
470:8=0x50
720:8=0x0
728:8=0x19
```

This q904 frontier was later Hensel-checked in round39. Output:
`/tmp/ct07_round38_qgrowth_after_q888_low470_highscan_top40_20260604.json`.

A second q904 q-growth sidecar from the same q888 base used ranges
`600:8=0x0` and `728:8=0x4`, giving `q_low/q_prefix/q_known=608/296/904`.
This q904 sidecar was Hensel-checked over top4 candidates at prefix bits
`608,624,640,...,800`:

```text
candidate_count=4
check_count=52
expected_check_count=52
complete=true
status_counts:
sat=4
unknown=36
process_timeout=12
roots/factors=0/0
```

No UNSAT row was produced. Outputs:
`/tmp/ct07_round39_qgrowth_after_q888_low600_high728_top40_20260604.json`,
`/tmp/ct07_round39_hensel_after_q904_top4_608_800_t5000_guarded_aggregate_20260604.json`,
and `/tmp/ct07_round39_hensel_after_q904_top4_608_800_t5000_guarded_runs_20260604.jsonl`.

Side preflights again produced no pruning or factor signal. Mixed p/q
`x0,x1,x5,x7 q150w704` had rows/cols/rank `21/126/21`, `lll=ok`, and
sampled/sound pruning false under the probe-local q-known mask. Because q150w704
overlaps q888-known bits, the q888-safe fallback window `q600w136` was also
checked; it had rows/cols/rank `21/126/21`, `lll=ok`, but only gap-contaminated
sample candidates and no valid pruning signal. TK/LZ `x0123467/x0123567` at
`m32/t24/w440/d3` remained negative at `-556.3637166626786` and
`-565.5303833293451` bits. The liftT actual proxy `T600/s16/cap100` failed by
cap, Sumset liftT `T600/s16` was `FAIL_DIM` with shifted/double support
`42419/80139`, and the 16-row edge verifier-only variant had 16/16 edge-ok but
root/factor `0/0`.

Outputs:
`/tmp/ct07_round38_side_preflight_summary_20260604.json`,
`/tmp/ct07_round38_mixed_pq_qwindow_decision_20260604.json`,
`/tmp/ct07_round38_mixed_pq_contig_x0x1x5x7_q150w704_m1_s2_samples12_20260604.json`,
`/tmp/ct07_round38_mixed_pq_contig_x0x1x5x7_q600w136_q888safe_m1_s2_samples12_20260604.json`,
`/tmp/ct07_round38_unknown_divisor_preflight_x0123467_m32_t24_w440_d3_20260604.json`,
`/tmp/ct07_round38_unknown_divisor_preflight_x0123567_m32_t24_w440_d3_20260604.json`,
`/tmp/ct07_round38_liftT_actual_proxy_T600_s16_cap100_20260604.json`,
`/tmp/ct07_round38_sumset_liftT_proxy_T600_s16_20260604.json`,
and `/tmp/ct07_round38_edge_verifier_x0x7alts_1_2_7_f_x1_60c68466ff_x6_245521490bd_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 39: low-C 55.46875%, high20 top392, and q-known 920

The next low-C union shard `35840..36352` completed with `status=ok`:

```text
new shard: 35840..36352
elapsed_seconds=345.294
aggregate coverage: 36352/65536 = 0.5546875
input shards: 71
total completion checks: 145408
hard-eligible total: 145408
unique oracle cases: 36352
roots/factors=0/0
merged range: 0..36352
missing range: 36352..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range35840_36352_round39.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot_round39_20260604/x0_x1_x2_x3_16bit_round39_shard35840_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_36352_round39.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_36352.json`.

The previously unverified low470/highscan q904 frontier from
`/tmp/ct07_round38_qgrowth_after_q888_low470_highscan_top40_20260604.json`
was Hensel-checked over top4 candidates at prefix bits
`600,616,632,...,792,800`:

```text
candidate_count=4
check_count=56
expected_check_count=56
complete=true
best q_low/q_prefix/q_known=600/304/904
status_counts:
sat=5
unknown=17
process_timeout=34
roots/factors=0/0
```

No UNSAT row was produced. Outputs:
`/tmp/ct07_round39_hensel_after_q904_low470_highscan_top4_600_800_t5000_guarded_aggregate_20260604.json`
and `/tmp/ct07_round39_hensel_after_q904_low470_highscan_top4_600_800_t5000_guarded_runs_20260604.jsonl`.

The corrected q272 exact-carry high20 closure advanced from top376 to top392:

```text
new x6high20 ranks 377..392:
0x0e490 0x0e520 0x0e5c0 0x0e660
0x0e700 0x0e790 0x0e830 0x0e8d0
0x0e960 0x0ea00 0x0eaa0 0x0eb40
0x0ebd0 0x0ec70 0x0ed10 0x0edb0

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top392: SAT=0, UNSAT=392, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=392 * 2^26 = 26306674688
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top392_round39_20260604.jsonl`,
`/tmp/ct07_high20_true_r377_392_exact_closure_round39_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r377_392_exact_closure_round39_20260604.json`,
and `/tmp/ct07_high20_top392_exact_closure_round39_20260604.json`.

A q904-base side q-growth scan over `608:8,720:8` reached a q920 frontier:

```text
base q_low/q_prefix/q_known=608/296/904
best q_low/q_prefix/q_known=616/304/920
emitted cubes=65536
top best new fixed ranges:
608:8=0x0
720:8=0x9
```

The guarded top4 Hensel check at prefix bits `616,632,648,...,800` completed:

```text
candidate_count=4
check_count=52
expected_check_count=52
complete=true
status_counts:
sat=4
unknown=35
process_timeout=13
roots/factors=0/0
```

No UNSAT row was produced. Outputs:
`/tmp/ct07_round39_side_qgrowth_q904base_r608_720_full65536_top20_20260604.json`,
`/tmp/ct07_round39_hensel_after_q920_top4_616_800_t5000_guarded_aggregate_20260604.json`,
and `/tmp/ct07_round39_hensel_after_q920_top4_616_800_t5000_guarded_runs_20260604.jsonl`.

The full 8-variable unknown-divisor preflight with small variables kept was
also negative:

```text
active variables=x0,x1,x2,x3,x4,x5,x6,x7
max_weight=520
max_degree=4
m_max/t_max=12/6
best proxy margin=-675.9520767837131 bits
best m/t/dimension=4/1/495
status=preflight_only_formula_not_claimed
```

Output:
`/tmp/ct07_round39_side_unknown_divisor_full8_w520_d4_m12_t6_20260604.json`.

No factor or plaintext was recovered.

## 2026-06-04 parallel round 40: low-C 56.25%, high20 top408, and q-known 936

The first round40 low-C launcher duplicated the same output path, so the
original paths were discarded and not used as evidence:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range36352_36864_round40.jsonl` and
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot_round40_20260604`. The retry shard
used unique paths and completed with `status=ok`:

```text
new shard: 36352..36864
elapsed_seconds=254.902
aggregate coverage: 36864/65536 = 0.5625
input shards: 72
overlap=0
total completion checks: 147456
hard-eligible total: 147456
unique oracle cases: 36864
roots/factors=0/0
merged range: 0..36864
missing range: 36864..65536
```

Outputs:
`/tmp/ct07_union_x0_x1_x2_x3_16bit_range36352_36864_round40_retry1.jsonl`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_pilot_round40_retry1_20260604/x0_x1_x2_x3_16bit_round40_retry1_shard36352_512.json`,
`/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_36864_round40_retry1.json`,
and `/tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_36864.json`.

The corrected q272 exact-carry high20 closure advanced from top392 to top408:

```text
new x6high20 ranks 393..408:
0x0ee40 0x0eee0 0x0ef80 0x0f010
0x0f0b0 0x0f150 0x0f1f0 0x0f280
0x0f320 0x0f3c0 0x0f450 0x0f4f0
0x0f590 0x0f630 0x0f6c0 0x0f760

new rows: SAT=0, UNSAT=16, UNKNOWN=0
aggregate top408: SAT=0, UNSAT=408, UNKNOWN=0
model/root/factor totals=0/0/0
unique closed full x6 values=408 * 2^26 = 27380416512
json_parse_verification=true
```

Outputs:
`/tmp/ct07_x6high16_fast_tail_top408_round40_20260604.jsonl`,
`/tmp/ct07_high20_true_r393_408_exact_closure_round40_20260604_runs.jsonl`,
`/tmp/ct07_high20_true_r393_408_exact_closure_round40_20260604.json`,
and `/tmp/ct07_high20_top408_exact_closure_round40_20260604.json`.

The q920 frontier was extended by q-growth scans. The best scan was
`616:8,712:8`:

```text
base q_low/q_prefix/q_known=616/304/920
best q_low/q_prefix/q_known=624/312/936
best q_prefix_start=712
best new fixed ranges:
616:8=0x0
712:8=0x4
other scanned range sets 616:8,704:8 and 624:8,712:8 reached q_known=928
```

Outputs:
`/tmp/ct07_round40_qgrowth_q920base_r616_712_full65536_top20_20260604.json`,
`/tmp/ct07_round40_qgrowth_q920base_r616_704_full65536_top20_20260604.json`,
and `/tmp/ct07_round40_qgrowth_q920base_r624_712_full65536_top20_20260604.json`.

Because low-C was active, the q936 Hensel check was intentionally kept to top2
candidates. It completed over prefix bits `624,640,656,...,800`:

```text
candidate_count=2
check_count=24
expected_check_count=24
complete=true
status_counts:
sat=2
unknown=15
process_timeout=7
roots/factors=0/0
```

No UNSAT row was produced. Outputs:
`/tmp/ct07_round40_hensel_after_q936_top2_624_800_t5000_guarded_direct_aggregate_20260604.json`
and `/tmp/ct07_round40_hensel_after_q936_top2_624_800_t5000_guarded_direct_runs_20260604.jsonl`.

Side probes again produced no hard-pruning or factor signal. TK/LZ preflights
with active sets `x0123467` and `x0123567`, `w540/d4/m14/t8`, remained at
negative margins `-556.3637166626786` and `-565.5303833293451` bits. The mixed
p/q probe `x0,x1,x2,x6,x7` with q-window `854:70` had rows/cols/rank
`28/210/28`, `lll=ok`, but only `sample_pruning_candidate_with_q_gap` rows and
no sound pruning oracle.

Outputs:
`/tmp/ct07_round40_side_unknown_divisor_x0123467_w540_d4_m14_t8_20260604.json`,
`/tmp/ct07_round40_side_unknown_divisor_x0123567_w540_d4_m14_t8_20260604.json`,
and `/tmp/ct07_round40_side_mixed_pq_x0x1x2x6x7_q854w70_m1_s2_samples10_20260604.json`.

No factor or plaintext was recovered.
