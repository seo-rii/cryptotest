# Challenge 7 Integrated Exploration Plan

This is the control document for problem 7.  Keep detailed command logs in
`RUN_LOG.md` and the long Korean writeup; keep this file short enough to decide
what to run next.

## Corrected PDF Override

Contest HQ published a corrected problem PDF on 2026-06-05.  The corrected
local file is `cryptotest/problems/7_소인수분해.pdf`.  `N`, `e`, and `ct` are
unchanged, but the p-bit mask and `p & mask` changed.  Treat every pre-existing
old-mask learned clause, q-gap ledger, low-C union coverage number, and ranked
candidate file as invalid for corrected-PDF proof accounting unless it is
explicitly regenerated under the corrected constants.

Corrected p unknown intervals are now:

```text
150..153   4 bits
265..348  84 bits
362..419  58 bits
600..668  69 bits
682..768  87 bits
784..829  46 bits
920..923   4 bits
```

The instance is now `672/1024` p bits known and `352` p bits unknown.  The old
`210..248` block is known, and the old `362..439` block shrank to `362..419`.

## Current Snapshot

As of the latest structured checkpoint in `RUN_LOG.md`:

- No factor or plaintext has been recovered.
- The active instance is the corrected PDF shape: 672 known p bits and 352
  unknown p bits across seven intervals.
- Current conclusion: the corrected instance is materially easier, but no
  current branch queue is complete enough to claim an ETA to factorization.
  The best broad pruning path is q middle-gap Coppersmith under corrected
  constants; p middle-window Coppersmith is currently too slow near 480-504 bit
  windows for broad use.
- Corrected q-gap should use the branch shape
  `150:4,265:24,745:24,784:46,920:4` first.  It reaches hard-line gaps around
  456-457 bits without the removed old `210:39` block.  The first corrected
  cube gave a hard-eligible `no_roots`; independent minimization dropped
  `150:4` and `265:8`, but not `920:4`.
- A diversified corrected q-gap top64 smoke (`hash` tie policy) tested 64
  candidates with `q_gap_bits=456`; all returned hard-eligible `no_roots`, with
  no roots or factors.  This proves the corrected oracle plumbing, not the
  whole search space.
- Corrected p two-sided windows are available as success oracles.  `[265,769)`
  timed out after 120 seconds on a top candidate, and `[265,745)` timed out
  after 30 seconds on a top candidate after fixing the outside-bit validation
  bug.  Do not make p-window the main broad enumeration path yet.
- Low-Coppersmith no-root checks are still important, but the old
  `low_bits=513` proof accounting is no longer accepted as hard pruning.  With
  `epsilon=0.02`, univariate low-bit Coppersmith only has an effective root
  budget of roughly `(0.25 - epsilon) * nbits`, so `low_bits=513` leaves about
  511 unknown p bits and is outside the safe bound.  Treat the existing
  `36864/65536 = 56.25%` low-C union coverage as heuristic/ranking evidence
  until it is rerun under a safe low-bit threshold.
- The new hard low-C target is `low_bits=600` or stronger.  When
  `x0+x1+x2+x3` is fixed in the old numbering, p bits `0..599` are contiguous.
  Under the corrected numbering this should be re-derived from the current
  unknown interval list before any new low-C batch is trusted.
- New primary idea: replace the q-low Coppersmith probe with q middle-gap
  Coppersmith.  Existing candidates already derive both q low bits and a q
  high prefix, but `branch_q_low_coppersmith.py` only used:

  ```text
  q = q0 + 2^t * y
  X = 2^(1024-t)
  ```

  The corrected oracle must use:

  ```text
  q = q_lo + 2^t * y + q_hi
  X = 2^(q_prefix_start-t)
  ```

  Cache keys must include `(t, q_prefix_start, q_lo, q_hi)`, not only
  `(t, q0)`.
- The previous two-sided middle-window p Coppersmith idea remains useful as a
  fallback and success oracle.  Instead of forcing the low 600 p bits to be
  contiguous, fix selected outside chunks and leave one large middle interval
  `[L,H)` as the univariate root:

  ```text
  p = p_low + 2^L * y + p_high
  ```

  This changes the construction rather than only sweeping old parameters.  It
  can turn several scattered unknown p chunks into one contiguous Coppersmith
  root, then verify the recovered p against the full p-bit mask.  Root hits are
  hard successes; no-root results are hard pruning only when the middle window
  length is inside the same epsilon-aware root bound with safety margin.
- Historical old-mask note: the saved 100 q-low/q-growth candidates were
  rechecked with the q-gap oracle before the PDF correction.  That changed
  typical root bounds from `2^408..2^424` to about `2^104..2^120`, because
  their q high prefix was already known.  Result:

  ```text
  candidates_tested=100
  q_gap_distribution: 104=20, 120=80
  status_counts: no_roots=100
  roots/factors=0/0
  hard_no_roots=100
  aggregate=tmp/ct07_q_gap_parallel_20260605/q_gap_parallel_aggregate.json
  ```

  These exact branches are old-mask historical evidence only.  The next q-gap
  work must generate corrected gateway/diagonal branches, not replay old
  candidates.

Older implementation notes below this point may refer to the old eight-block
numbering.  Before running any command copied from those notes, re-derive the
fixed ranges under the corrected seven-interval instance.
- The q-gap oracle is now wired into the SAT loop with a hard trigger and
  clause learning.  A diagonal cube with `x0+x1+x2_low48+x6+x7` fixed reached
  `q_gap_bits=457` and `effective_margin_bits=13.04`, so `no_roots` is a hard
  clause under `epsilon=0.02`.  Small 4-bit minimization probes on x0, x7,
  x1-low, x2-top, and x6-low all passed on the first all-zero cube, reducing
  the learned clause from 141 to 137 literals each time.  This validates the
  minimizer, but it is local evidence for one cube, not a general dropped-bit
  theorem.
- `q_gap_gateway_beam_search.py` generates hard-line gateway/diagonal
  candidates.  The first lexicographic beam was too biased toward zero chunks,
  so it now supports `--tie-policy hash --diversity-salt ...` to diversify
  candidates with identical q-gap score.  A 64-candidate diversified beam all
  had `q_gap_bits=456`, `q_low_bits=313`, and `q_prefix_start=769`; the
  parallel q-gap run returned `64/64` hard-eligible `no_roots`, with no roots
  or factors.  This proves the plumbing, not the whole branch space.
- q-gap hard clauses are now persistent across child runs.  The SAT loop can
  load prior JSONL ledgers with `--load-learned-jsonl`, reconstruct hard
  clauses from `cube_ranges`, remove any `learned_clause_dropped_bits`, and
  seed Z3 before the next model.  A two-child batch using the output JSONL as
  its own load source skipped the first all-zero cube on the second child
  (`x0=0` then `x0=1`), proving that clauses now survive process boundaries.
- The q-gap beam generator now supports split diagonal frontiers, not only
  one-sided `x2_low` fixing.  A mixed `x2_low24+x5_high24` beam produced
  `64/64` hard-line candidates with `q_gap_bits=456`, `q_low_bits=289`, and
  `q_prefix_start=745`; the parallel oracle returned `64/64 no_roots`, no
  roots or factors.  This is better branch-shape coverage, but still only a
  ranked sample.
- Split-frontier minimization now has local evidence.  For the all-zero
  `x0+x1+x2_low24+x5_high24+x6+x7` cube, dropping all four x0 bits is sound,
  dropping x1 low4 is sound, and dropping x7 only worked for bits `922..923`
  because `920..921` can push the q gap above the hard threshold.  A two-cube
  run with x0 drop moved from `x1=0` to `x1=1` without enumerating `x0=1`.
  Loading x0-drop plus two x1-low4 bucket clauses moved the next model to
  `x1=48`.  This is useful but still local; do not promote it to a global x1
  theorem.
- The SAT loop now has `--q-gap-independent-drop-clauses`, which verifies each
  drop window against the original cube and emits one learned clause variant
  per droppable window.  This lets one cube generate both the x0-dropped and
  x1-low4-dropped q-gap clauses with `16 + 16` completions instead of either
  running two separate passes or attempting a cumulative `2^8` union.  The
  loader restores every `learned_clause_variants` entry from the JSONL ledger.
- `--q-gap-minimize-workers N` parallelizes independent q-gap drop completion
  checks with subprocess workers.  On the split x0+x1-low4 smoke, workers=4
  reduced one child from the previous 413-448 second range to about 142
  seconds while producing the same two independent no-root clauses.
- The corrected q272 exact-carry high20 filter has closed the top408 ranked
  x6 high20 parents.  This removes `408 * 2^26 = 27380416512` full x6 values
  in that ranked queue, with model/root/factor counts `0/0/0`.
- p-only q-growth has reached a q-known frontier of `936` on sampled candidates,
  but guarded Hensel checks over those candidates produced only `sat`,
  `unknown`, and process timeouts.  There is no hard contradiction from this
  path yet.
- TK/LZ, mixed p/q lattice probes, and liftT/sumset probes remain diagnostic
  only.  Recent preflights show negative margins or projection-derived
  relations with no extra pruning.

Do not count nested prefix closures twice.  If a high20 parent is closed, its
high24/high28/high32 child checks are evidence for ranking and implementation
sanity, not additional unique search-space coverage.

## Oracle Discipline

Use only these as hard conclusions:

- Verified factor: `N % p == 0`, followed by RSA decryption.
- Exact SAT/CNF contradiction from a sound product/carry model.
- q middle-gap Coppersmith root that verifies as a divisor of `N` and whose
  complementary p satisfies the original p-bit mask.
- q middle-gap Coppersmith `no_roots` only if the gap root range is inside the
  epsilon-aware Coppersmith bound:

  ```text
  q_gap_bits = q_prefix_start - q_low_bits
  effective_bound_bits = (0.25 - epsilon) * n_bit_length - 1.0
  effective_margin_bits = effective_bound_bits - q_gap_bits
  hard_clause_eligible = effective_margin_bits >= 8.0
  ```

  With `epsilon=0.02`, hard pruning should target roughly
  `q_gap_bits <= 462`.  Gateway-only branches around `q_gap_bits=504` are
  hit-first/ranking only, not hard no-root clauses.
- Two-sided middle-window Coppersmith root that verifies as a divisor of `N`
  and satisfies the original full p-bit mask.
- Two-sided middle-window Coppersmith `no_roots` only if the whole root range
  `2^(H-L)` is within the effective bound:

  ```text
  middle_bits = H - L
  effective_bound_bits = (0.25 - epsilon) * n_bit_length - 1.0
  effective_margin_bits = effective_bound_bits - middle_bits
  hard_clause_eligible = effective_margin_bits >= 8.0
  ```

  If this margin is thin or negative, use the oracle only as hit-first search
  or ranking evidence, not as a learned hard block.
- Low-Coppersmith `no_roots` only when the effective Coppersmith margin includes
  epsilon and a safety buffer.  Track:

  ```text
  unknown_bits = p_bits - low_bits
  effective_bound_bits = (0.25 - epsilon) * n_bit_length - 1.0
  effective_margin_bits = effective_bound_bits - unknown_bits
  hard_clause_eligible = effective_margin_bits >= 8.0
  ```

  Promote only exact fixed low assignments or exhaustively verified dropped-bit
  unions that pass this effective-margin test.

Everything else is ranking or diagnostics:

- CP-SAT conflict/activity.
- `low_bits=513` Coppersmith `no_roots` with `epsilon=0.02`.
- q-prefix/q-known growth.
- Hensel prefix `sat`/`unknown`.
- folded-Coron reconstructed polynomial counts without a verified factor.
- TK/LZ projection relations unless they produce non-projection pruning on
  sampled assignments and then pass a separate soundness check.
- weak tail-window filters unless cross-checked by product-prefix or exact
  carry-vector CNF.

## How The Directions Fit Together

The useful loop is:

1. Generate candidate branches.
   Use q-growth, fast-tail ranking, and p-only SAT+CAS probes to propose x6,
   x5, x1, x2, x7, and boundary fixed ranges.  Keep diversity across x6
   prefixes and x1/x5 bases; previous CP-SAT activity queues often died under
   exact SAT filters.

2. Run cheap ranking checks.
   q-prefix growth and Hensel prefix checks are good for ordering work, but
   they should not remove a branch.  Prefer small top-k batches and record the
   q-low/q-prefix/q-known triple for every candidate.

3. Apply hard pruning.
   First try the q middle-gap oracle on candidate assignments, because it uses
   the q high prefix that the old q-low probe recorded but discarded.  Use p
   two-sided windows as a fallback success oracle, low-Coppersmith only at
   `low_bits=600` or another threshold with positive effective margin, and
   q272 exact-carry CNF for x6-prefix buckets or fixed x2 subcubes.  Promote a
   pruning result only if the proof scope is explicit and disjoint from
   already-counted coverage.

4. Escalate surviving branches.
   If a branch survives exact-carry or produces a SAT model, run stronger
   product-prefix width, exact-tail carry-vector CNF, and folded-Coron factor
   verification.  Coron output is success only when it verifies a divisor of
   `N`.

5. Update one aggregate per axis.
   Keep separate aggregates for low-C union coverage, high20/high32 x6-prefix
   closure, q-growth/Hensel diagnostics, and exact-carry fixed-subcube
   closures.

## Pause Checkpoint: Need A Different Solve Path

Do not interpret the current low-C union as an ETA to factorization.  It is a
hard oracle for one fixed branch shape:

```text
x6 = 0x245521490bd
x7 = 0
x0..x3 16-bit dropped-window union
```

If the full `65536` completions all return hard-eligible `no_roots`, the result
is valuable proof coverage for that branch, but not a proof that the instance
is solved.  The remaining raw branch space is far too large for manual sweeps:
`x6` alone has `2^46` full assignments and `2^20` high20 parent prefixes.
The top408 high20 closures cover only about `0.039%` of the high20 parent
space.  Therefore exhaustive high20 or full-x6 enumeration is not a viable
primary plan.

The next primary direction should be one of the following, in this order:

1. Implement and test the q middle-gap Coppersmith oracle.  This fixes the
   q-low probe's main omission: q high prefix information must be part of the
   polynomial constant, shrinking the root from `2^(1024-t)` to
   `2^(q_prefix_start-t)`.
2. Run q-gap hard no-roots through the persistent SAT/CAS learner rather than
   one-shot beams.  The current hard q-gap branch cost is still about
   `x0+x1+x6+x7+diagonal48 = 141` selected p bits; random or lexicographic
   beams will not hit the true branch reliably.  The solver now can accumulate
   q-gap learned clauses and resume from its JSONL ledger, so the next long run
   should use that path.
3. Move branch ordering to gateway blocks: `x0`, `x7`, then complete `x1`
   and `x6`; add diagonal `x2_low a + x5_high b` bits when hard q-gap pruning
   is needed.  Keep hash-diversified tie-breaking or another diversity guard
   whenever the q-gap score is flat.  Prefer split diagonals such as
   `24+24`, `32+16`, and `16+32` over only `48+0` unless a ranking signal
   points strongly to one side.
4. Keep p two-sided windows and residual HM4 as fallback success oracles after
   a gateway assignment exists.
5. Build the integrated SAT+CAS learner that owns the remaining search space.
   SAT must generate branches, low-C/q272 must return sound blocking clauses,
   and the loop must keep a coverage ledger.  This is the only current path
   that can turn branch killers into a complete method.
6. Strengthen exact carry/product modeling so the SAT side learns more without
   needing large manual branch batches.  Prioritize q272/q-prefix assumptions,
   exporter-time fixed subcubes, and carry-column relation reuse.
7. Try another genuinely new algebraic approach only if it changes the
   construction, not another parameter sweep of the same TK/LZ/Coron families.
   A useful candidate must show a positive determinant margin or
   non-projection pruning on planted/sampled tests before any long lattice run.

The current low-C `65536` completion run may be finished as a clean hard-proof
artifact, but after that the manual low-C/high20 campaign should pause unless
the integrated loop can consume its clauses automatically.

## Updated Phases

Commands below assume the current working directory is `cryptotest/`.

### Phase A: Fix proof discipline first

Before spending more CPU time, separate hard proof accounting from ranking.

Immediate changes:

- Stop counting `low_bits=513` low-C `no_roots` as hard coverage.
- Keep the existing 513-bit union evidence as heuristic/ranking history only.
- Update low-C oracle reports to include `low_bits`, `epsilon`,
  `unknown_bits`, `effective_bound_bits`, `effective_margin_bits`,
  `oracle_status`, and `hard_clause_eligible`.
- Change the hard eligibility gate in code to use the effective-margin formula
  above.  The old `n_bit_length / 4 - unknown_bits` check ignores epsilon and
  is too optimistic.

Useful thresholds with `epsilon=0.02`:

| low_bits | unknown_bits | hard-pruning status |
| ---: | ---: | --- |
| 513 | 511 | unsafe; heuristic only |
| 554 | 470 | borderline |
| 560 | 464 | possible but thin margin |
| 600 | 424 | preferred hard target |
| 608 | 416 | safer |
| 616 | 408 | safer |

### Phase B: q middle-gap Coppersmith

This is the new primary direction.  The oracle fixes q bits below `t` and q
bits above `s = q_prefix_start`, then leaves only the middle gap as the root:

```text
q = q_lo + 2^t * y + q_hi
0 <= y < 2^(s-t)
```

Implementation requirements:

- Create/use `q_middle_gap_oracle.py`.
- Replace q-low-only root bounds with `q_gap_bits = q_prefix_start - q_low_bits`.
- Use cache key `(q_low_bits, q_prefix_start, q_lo, q_hi, epsilon)`.
- Verify every returned root by `N % q == 0`, `p = N // q`, and
  `(p & full_mask) == known`.
- Report `q_low_bits`, `q_prefix_start`, `q_gap_bits`, `epsilon`,
  `effective_bound_bits`, `effective_margin_bits`, `hard_clause_eligible`,
  `status`, `roots_returned`, and factor rows.

Immediate smoke test:

```bash
python3 solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --output-dir tmp/ct07_q_gap_existing_candidates_YYYYMMDD \
  --max-gap-bits 520 --epsilon 0.02 --min-hard-margin-bits 8.0 \
  --chunk-size 10 --workers 4 --no-pdf-check
```

The saved 100 q-low candidates should mostly have `q_gap_bits` around `104` or
`120`.  A factor would immediately solve the challenge.  If no factor appears,
their no-root rows are hard-eligible under the q-gap bound, but only for those
exact candidate branches.

Gateway branch plan:

```text
x0 full
x7 full
x1 full  # q-low gateway; exposes p[210..264] and pushes q_low to 265
x6 full  # q-high gateway; pulls q_prefix_start toward 769
```

That base gateway fixes only `x0+x1+x6+x7 = 93` hidden p bits and gives a
near-bound q gap around `504`.  Use it as hit-first only with low epsilon, not
as hard no-root pruning.

Hard q-gap line:

```text
base gateway + x2 low a bits + x5 high b bits
a + b in {42, 48, 56}
```

`a+b=42` is the first hard-pruning line at about `q_gap_bits=462`; `a+b=48` is
the default hard target; `a+b=56` is the safety line if minimization is weak.
This avoids forcing all of `x3` and `x4` during branch ordering.

Current SAT-loop status:

- `semi_programmatic_sat.py` can now call q middle-gap Coppersmith and learn
  hard `q_gap_coppersmith_no_root` blocks.
- Smoke cube `x0+x1+x2_low48+x6+x7 = 0` produced `q_gap_bits=457`,
  `effective_margin_bits=13.04`, no roots, and a hard block.
- q-gap drop-window minimization is implemented.  On that smoke cube, dropping
  all x0 bits or all x7 bits separately was sound:

  ```text
  x0 drop windows 150:2,152:2 -> 16 completions all hard no_roots
  x7 drop windows 920:2,922:2 -> 16 completions all hard no_roots
  clause size 141 -> 137 in each individual test
  ```

Next long-run candidate:

```bash
cd cryptotest/solutions/07_sat_cas_explore
python3 sat_cas_batch_runner.py \
  --output /home/seorii/dev/hancomac/tmp/ct07_qgap_sat_hard_x2low48_BATCH.jsonl \
  --max-cubes 16 --timeout-seconds 1800 \
  --cube-ranges 150:4,210:39,265:48,784:46,920:4 \
  --check-bits 313 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-drop-window 150:2 --q-gap-drop-window 152:2 \
  --q-gap-minimize-max-completions 16 \
  --include-cube-ranges
```

Run a separate x7-drop batch or a higher-cost x0+x7 combined drop only if the
x0-drop batch keeps producing broad hard blocks and no factor.

### Phase C: Two-sided middle-window p Coppersmith fallback

This remains a useful construction but is now lower priority than q-gap.  The
oracle fixes the p bits outside a
middle window and leaves the entire middle interval as one root:

```text
p = low_part + 2^L * y + high_part
0 <= y < 2^(H-L)
```

The important implementation rule is to ignore known p bits inside `[L,H)` when
building the polynomial constant.  Put only `[0,L)` and `[H,1024)` into
`low_part | high_part`; after a root is returned, reconstruct p and verify both
`N % p == 0` and `(p & full_mask) == known`.

Create `two_sided_window_coppersmith.py` with:

- direct oracle mode for one outside assignment and one window;
- toy/planted RSA generator with the same mask shape;
- batch mode over candidate fixed ranges;
- JSON reports containing `L`, `H`, `middle_bits`, `epsilon`,
  `effective_bound_bits`, `effective_margin_bits`, `hard_clause_eligible`,
  `status`, `roots_returned`, `factor_count`, and elapsed time.

Window candidates:

| middle window `[L,H)` | middle bits | outside hidden p bits to fix | fixed hidden bits | current classification |
| ---: | ---: | --- | ---: | --- |
| `[265,769)` | 504 | `x0`, `x1`, `x6`, `x7` | 93 | hit-first only; outside `epsilon=0.02` and still thin at `epsilon=0.005` |
| `[265,745)` | 480 | `x0`, `x1`, `x5[745..768]`, `x6`, `x7` | 117 | promising at `epsilon=0.01`; heuristic at `epsilon=0.02` |
| `[362,830)` | 468 | `x0`, `x1`, `x2`, `x7` | 131 | cleanest SAT target; hard no-root only with lower epsilon or validated thin-margin policy |
| `[210,669)` | 459 | `x0`, `x5`, `x6`, `x7` | 141 | best `epsilon=0.02` hard candidate under the 8-bit margin rule |
| `[400,830)` | 430 | `x0`, `x1`, `x2`, `x3[362..399]`, `x7` | 169 | safest bound; higher outside search cost |

Validation order:

1. Toy/planted tests for all windows at `epsilon=0.02`, `0.01`, and `0.005`.
2. Real-instance hit-first run over existing q-growth, high20/q272, x5/x6 beam,
   and exact-carry candidate artifacts.  Try windows in this order:
   `[362,830)`, `[210,669)`, `[265,745)`, `[265,769)`.
3. If root appears, verify divisor and decrypt.
4. If no roots appear, record hard pruning only for windows whose
   `hard_clause_eligible=true`; otherwise record timing/ranking only.

SAT loop plan for `[362,830)`:

1. SAT or beam proposes outside values for `x0`, `x1`, `x2`, and `x7`.
2. Run the two-sided oracle.
3. On verified factor, stop.
4. On hard-eligible no-root, learn the outside-assignment blocking clause.
5. Try 8/12/16-bit drop-window generalization over outside literals.  Promote
   the minimized clause only after every completion returns hard-eligible
   `no_roots`.

`[210,669)` should be run as a high-side hit-first search first: reuse existing
`x5/x6/x7` q-prefix beams, attach the 16 possible `x0` values, and call the
oracle.  Treat no-root as hard only when the margin report permits it.

Follow-up lattice direction:

Once a promising outside branch is identified, revisit a 4-variable lattice
instead of the old 8-variable TK/LZ/HM sweeps.  For example, under the
`[362,830)` outside fix:

```text
p = known + 2^362*x3 + 2^600*x4 + 2^682*x5 + 2^784*x6
```

Run determinant-margin and planted preflights before any long LLL/BKZ job.
This is a construction change because variable count drops from 8 to 4 and the
outside branch raises the effective known-bit ratio.

### Phase D: Finish low-C union at 600 bits as proof artifact

Re-run the `x0+x1+x2+x3` low-C union with `--low-bits 600`.  This is now the
legacy hard-pruning work, not the primary solve strategy.  Do not continue the
513-bit union as a proof unless it is explicitly labelled heuristic.

Use unique output paths for every retry.  The round40 duplicate-path mistake is
the example to avoid.

Default dry-run coordinator:

```bash
python3 solutions/07_sat_cas_explore/run_updated_plan.py
```

This only prints the commands.  To execute the long-running pieces, pass
`--execute`; use `--parallel-heavy` only when the machine can run the low-C
shard batch and exact-carry jobs at the same time.

Equivalent direct shard template:

```bash
python3 solutions/07_sat_cas_explore/low_coppersmith_union_shard_batch.py \
  --output-dir tmp/ct07_union_x0_x1_x2_x3_16bit_pilot_roundNN_YYYYMMDD \
  --output-jsonl tmp/ct07_union_x0_x1_x2_x3_16bit_rangeSTART_STOP_roundNN.jsonl \
  --label x0_x1_x2_x3_16bit_roundNN \
  --completion-start START --completion-stop STOP --chunk-size 512 \
  --timeout-seconds 900 --jobs 4 \
  --fix-p-range 784:46:0x245521490bd \
  --fix-p-range 920:4:0 \
  --base-selected-p-range 150:4:0 \
  --base-selected-p-range 210:39:0 \
  --base-selected-p-range 265:84:0 \
  --base-selected-p-range 362:78:0 \
  --variant-p-range 150:4:0 \
  --variant-p-range 150:4:4 \
  --variant-p-range 150:4:8 \
  --variant-p-range 150:4:12 \
  --drop-window 150:2 --drop-window 152:2 \
  --drop-window 210:2 --drop-window 212:2 \
  --drop-window 267:2 --drop-window 269:2 \
  --drop-window 362:2 --drop-window 364:2 \
  --low-bits 600 --epsilon 0.02 --min-hard-margin-bits 8.0
```

After each shard, aggregate only vetted shard files.  Do not use a broad glob if
it can match discarded retries or duplicate-output paths.

```bash
python3 solutions/07_sat_cas_explore/low_coppersmith_union_shard_analyzer.py \
  --json tmp/ct07_union_x0_x1_x2_x3_16bit_range0_512.jsonl \
  ... \
  tmp/ct07_union_x0_x1_x2_x3_16bit_rangeSTART_STOP_roundNN.jsonl \
  > tmp/ct07_union_x0_x1_x2_x3_16bit_aggregate_after_STOP.json
```

Acceptance criteria:

- `all_shards_no_roots=true`
- roots/factors `0`
- `effective_margin_bits >= 8.0` for every promoted no-root
- no missing coverage below the intended stop
- aggregate paths reference only clean, non-duplicated shard outputs

Once this reaches full coverage, wire the resulting low no-good shape into the
SAT loop as a preverified guard.  For guard misses, keep the dynamic minimizer
fallback, but require the same effective-margin gate before learning a hard
clause.

### Phase E: Continue q272 exact-carry as a high-value branch killer

Continue the corrected q272 exact-carry x6-prefix closure, but treat it as a
ranked branch killer rather than an exhaustive x6 proof engine.  Advance the
high20 ranked queue beyond top408 in disjoint parent prefixes, first toward
top800 or top1200.  Count unique coverage only at the high20 parent level.
Stop or re-rank if yield drops.

Representative safe settings:

```bash
python3 solutions/run_07_go_sat_filter.py \
  --free-x1-x6high-filter \
  --branch-low 0 --branch-high 0 \
  --T 800 --arith-bits 272 \
  --skip-known-prefix-bits 208 \
  --lowlift-q 272 --q-interval-bound \
  --odd-residue-prime 3 --odd-residue-prime 5 \
  --odd-residue-prime 7 --odd-residue-prime 11 \
  --exact-tail-carry-limbs 1 --exact-carry-bits 272 \
  --x6high-bits 20 \
  --x6high-candidate 0x... \
  --summary-json tmp/ct07_high20_rSTART_STOP_exact_closure_YYYYMMDD.json \
  --summary-only
```

Escalate only if a parent is SAT or times out in a reproducible way.  For SAT,
enumerate a small model projection and send it to exact-tail or folded-Coron
verification.

### Phase F: Integrate SAT+CAS loop

The scripts are currently too distributed.  The next implementation target is a
single loop with this discipline:

1. SAT or beam completes q-gap gateway blocks `x0`, `x7`, `x1`, and `x6`.
2. If `q_gap_bits <= 504`, call q-gap as success-only.
3. If diagonal `x2_low + x5_high` bits reduce `q_gap_bits <= 462`, call q-gap
   as hard-pruning eligible.
4. If q-gap returns a root, verify `N % q == 0`, recover p, and decrypt.
5. If q-gap returns `no_roots` with safe effective margin, learn a hard block.
6. If p low 600 bits are complete, call legacy low-C.
7. If low-C returns a root, verify `N % p == 0`.
8. If low-C returns `no_roots` with safe effective margin, learn a hard block.
9. If an x6 high20 candidate appears, call q272 exact-carry CNF.
10. If q272 CNF is UNSAT, learn an exact hard block.
11. Use q-growth only for branch ordering.

Current q-gap command templates:

```bash
python3 solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 \
  --tie-policy hash --diversity-salt YYYYMMDD-a --json \
  > tmp/ct07_qgap_gateway_beam_hash64_a_YYYYMMDD.json

python3 solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json tmp/ct07_qgap_gateway_beam_hash64_a_YYYYMMDD.json \
  --output-dir tmp/ct07_qgap_gateway_beam_hash64_a_qgap_YYYYMMDD \
  --candidate-start 1 --candidate-stop 64 \
  --chunk-size 4 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 \
  --timeout-seconds 900 --no-pdf-check --json
```

These templates are useful for smoke and ranking batches.  They are not a
complete search on their own because each hard-line candidate still fixes 141
hidden p bits.  Use them to feed or audit the persistent SAT/CAS learner, not
as an ETA-based exhaustive run.

Persistent q-gap SAT runner template from the workspace root:

```bash
LEDGER=tmp/ct07_qgap_persistent_$(date +%Y%m%d_%H%M%S).jsonl
python3 cryptotest/solutions/07_sat_cas_explore/sat_cas_batch_runner.py \
  --output "$LEDGER" \
  --load-learned-jsonl "$LEDGER" \
  --max-cubes 1 --runs-per-range 200 --timeout-seconds 90 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith \
  --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 \
  --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:4 \
  --q-gap-minimize-max-completions 16 \
  --q-gap-minimize-workers 4 \
  --include-cube-ranges
```

This template uses the split `x2_low24+x5_high24` hard frontier.  The base
trigger must still include the full `265:24` range: directly lowering it to
`265:16` produced `q_gap_bits=465` and skipped the hard q-gap oracle.  The
`281:8` window is only safe after all 256 full completions have been verified
for that cube.

Do not switch the main hard-pruning loop to `epsilon=0.005` just to make
`q_gap_bits=465` hard-eligible.  A single `x2_low16+x5_high24` smoke exceeded
10 minutes before manual termination.  The q-gap code now has
`--q-gap-oracle-timeout-seconds`, but use it for risky diagnostics only; keep
the default `epsilon=0.02` path unguarded for throughput unless a run starts
hanging.

For a selected wide-drop run with `281:8`, raise the completion cap to 256:

```bash
LEDGER=tmp/ct07_qgap_wide_$(date +%Y%m%d_%H%M%S).jsonl
python3 cryptotest/solutions/07_sat_cas_explore/sat_cas_batch_runner.py \
  --output "$LEDGER" \
  --load-learned-jsonl "$LEDGER" \
  --max-cubes 1 --runs-per-range 40 --timeout-seconds 1200 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith \
  --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 \
  --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:4 \
  --q-gap-drop-window 281:8 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --include-cube-ranges
```

It is still model-order driven, so inspect the ledger after short batches and
re-rank if the clauses merely walk a tiny counter-like region.  Analyzer:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/sat_batch_analyzer.py "$LEDGER" --json
```

For short manual batches, useful minimization windows on the split frontier are:

```text
safe local x0 drop: --q-gap-drop-window 150:4
safe local x1 low4 drop: --q-gap-drop-window 210:4
safe local x2 top8 drop after full completion verification: --q-gap-drop-window 281:8
partial x7 drop only: --q-gap-drop-window 922:2
avoid treating 920:2 as safe globally; one tested completion exceeded q-gap max
avoid x5 high1/high2/high4 as default drops; all failed on the all-zero split cube
avoid x6 low4 as a split-frontier independent drop; it failed on the all-zero split cube
```

The current best manual loop is:

1. Load the existing ledger.
2. Run one cube with independent x0 and x1-low4 drops for a cheap learned
   ledger.
3. On promising or repeated bucket shapes, add the `281:8` x2-top8 drop; this
   costs about 257 q-gap calls and measured about 866 seconds with 8 workers.
4. Re-run the analyzer and confirm the next cube actually moved to a new
   bucket.

The latest local continuation ledger set is:

```text
tmp/ct07_qgap_split_independent_x0_x1_20260605.jsonl
tmp/ct07_qgap_split_independent_x1low8_workers8_20260605.jsonl
tmp/ct07_qgap_split_independent_x1low8_after256_workers16_20260605.jsonl
tmp/ct07_qgap_split_independent_x2top8_workers8_20260605.jsonl
tmp/ct07_qgap_wide_next_after_ledgers_20260605.jsonl
tmp/ct07_qgap_wide_x1_784_20260605.jsonl
tmp/ct07_qgap_wide_x1_800_20260605.jsonl
tmp/ct07_qgap_wide_x1_816_x1low8_probe_20260605.jsonl
tmp/ct07_qgap_wide_x1_512_x1low8_only_20260605.jsonl
tmp/ct07_qgap_wide_x1_1024_x1low8_20260605.jsonl
```

Loading these moves past the already-closed `x1=0`, `x1=256`, `x1=768`,
`x1=784`, `x1=800`, `x1=816`, `x1=512`, and `x1=1024` buckets under the
current model ordering.  With these ledgers loaded, the next model is:

```text
150:4=0,210:39=1536,265:24=0,745:24=0,784:46=0,920:4=0
```

Do not load these smoke ledgers for minimization continuations:

```text
tmp/ct07_qgap_load_after_wide_next_smoke_20260605.jsonl
tmp/ct07_qgap_load_after_wide_x1_784_smoke_20260605.jsonl
tmp/ct07_qgap_load_after_wide_x1_800_smoke_20260605.jsonl
tmp/ct07_qgap_load_after_x1_816_x1low8_smoke_20260605.jsonl
tmp/ct07_qgap_load_after_x1_512_x1low8_smoke_20260605.jsonl
tmp/ct07_qgap_load_after_x1_1024_x1low8_smoke_20260605.jsonl
```

They contain one-cube unminimized `q_gap_selected_bits` hard blocks used only
to confirm the next SAT model.

Manual next-cube command template:

```bash
OUT=tmp/ct07_qgap_wide_x1_1536_x1low8_$(date +%Y%m%d_%H%M%S).jsonl
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:24,745:24,784:46,920:4 \
  --check-bits 289 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 462 \
  --q-gap-epsilon 0.02 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-hard-fail \
  --q-gap-independent-drop-clauses \
  --q-gap-drop-window 150:4 \
  --q-gap-drop-window 210:8 \
  --q-gap-minimize-max-completions 256 \
  --q-gap-minimize-workers 8 \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_split_independent_x0_x1_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_split_independent_x1low8_workers8_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_split_independent_x1low8_after256_workers16_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_split_independent_x2top8_workers8_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_next_after_ledgers_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_x1_784_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_x1_800_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_x1_816_x1low8_probe_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_x1_512_x1low8_only_20260605.jsonl \
  --load-learned-jsonl /home/seorii/dev/hancomac/tmp/ct07_qgap_wide_x1_1024_x1low8_20260605.jsonl \
  --include-cube-ranges \
  > "$OUT"
python3 cryptotest/solutions/07_sat_cas_explore/sat_batch_analyzer.py "$OUT" --json
```

This is still CPU-heavy.  The current independent x0+x1-low4 run costs about
32 q-gap Coppersmith calls per cube and took about 142 seconds with 4 workers.
The x1-low8 and x2-top8 wide drops both cost about 257 q-gap calls and measured
about 14.5 minutes; `x1=784` and `x1=800` took `944s` and `892s` respectively
with the 8-worker `150:4`, `210:4`, `281:8` drop set.  The better current
default is `150:4` plus `210:8`: it costs 273 q-gap calls per cube and has now
closed the following hard-ledger buckets under the current branch shape:

```text
x1 = 512, 1024, 1536, 1280, 1792, 2048, 18432, 49152
```

Every row returned hard-eligible `no_roots`, no roots, and no factors.  Loading
all current hard ledgers through
`tmp/ct07_qgap_wide_after_1280_batch4_x1low8_20260605.jsonl` gives
`loaded clauses/literals=33/4457` and moves the next model to:

```text
150:4=0,210:39=3584,265:24=0,745:24=0,784:46=0,920:4=0
```

The combined
`150:4`, `210:8`, `281:8` probe at `x1=816` cost 529 q-gap calls and `1588s`,
so do not combine `210:8` and `281:8` unless x2-top8 generalization is the
explicit target.  Raising x1-low8 from 8 workers to 16 workers did not improve
wall time (`878s` vs `872s`), so use 8 workers as the default for wide drops on
this host.  For unattended runs, prefer small ledger chunks first, then inspect
whether the model progression is moving across x1/x2 buckets or getting stuck
in another small region.

Important current limitation: the q-gap hard oracle is working, and `210:8`
now avoids the worst 16-step `x1` walk.  However, the loop is still driven by
the default SAT model order under one fixed `x6/x5/x2` branch shape.  Continuing
this exact loop will produce valid proof ledger, but it is not yet a broad
hit-first solve path.  The next solve-oriented improvement should either:

1. add a stronger `x1` generalization/minimization window after planted checks,
2. use a ranked gateway queue over `x1/x6` rather than the default SAT model
   order, or
3. run q-gap as a hit-first oracle over diversified gateway branches before
   spending more wall time on exhaustive hard-ledger bookkeeping.

Diversified gateway hit-first status:

```text
tmp/ct07_qgap_gateway_hash_top64_20260605.json
tmp/ct07_qgap_gateway_hashB_top64_20260605.json
tmp/ct07_qgap_gateway_hashC_top64_20260605.json
tmp/ct07_qgap_gateway_hash_top32_parallel_abs_20260605/q_gap_parallel_summary.json
tmp/ct07_qgap_gateway_hash_33_64_parallel_abs_20260605/q_gap_parallel_summary.json
tmp/ct07_qgap_gateway_hashB_top64_parallel_abs_20260605/q_gap_parallel_summary.json
tmp/ct07_qgap_gateway_hashC_top64_parallel_abs_20260605/q_gap_parallel_summary.json
```

These cover three hash-tie salts, 192 checked gateway/diagonal candidates, all
with `q_gap_bits=456`.  Result: `192/192` hard `no_roots`, no returned roots,
and no factor.  The hit-first path remains viable because it is much cheaper
than hard minimization, but the first three top-64 hash beams were negative.
When running more, pass absolute paths to `--candidate-json`; relative
`tmp/...` paths are missing inside the child process.

Next useful hit-first command pattern:

```bash
SALT=qgap-hit-$(date +%Y%m%d_%H%M%S)
CAND=/home/seorii/dev/hancomac/tmp/ct07_qgap_gateway_${SALT}_top64.json
OUT=/home/seorii/dev/hancomac/tmp/ct07_qgap_gateway_${SALT}_parallel
python3 cryptotest/solutions/07_sat_cas_explore/q_gap_gateway_beam_search.py \
  --beam-width 64 --top 64 --tie-policy hash --diversity-salt "$SALT" \
  --x2-low-bits 24 --x2-low-widths 8,8,8 \
  --x5-high-bits 24 --x5-high-widths 8,8,8 \
  --json > "$CAND"
python3 cryptotest/solutions/07_sat_cas_explore/run_q_gap_parallel.py \
  --candidate-json "$CAND" \
  --output-dir "$OUT" \
  --candidate-start 1 --candidate-stop 64 --chunk-size 4 --workers 8 \
  --max-gap-bits 462 --epsilon 0.02 --min-hard-margin-bits 8.0 \
  --timeout-seconds 1800 --no-pdf-check --json
```

For low-epsilon diagnostics, always guard the oracle:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/semi_programmatic_sat.py \
  --jsonl --max-cubes 1 \
  --cube-ranges 150:4,210:39,265:16,745:24,784:46,920:4 \
  --check-bits 281 --timeout-ms 1000 --enumerate-p-free-limit 24 \
  --run-q-gap-coppersmith --q-gap-max-bits 465 \
  --q-gap-epsilon 0.005 --q-gap-min-hard-margin-bits 8.0 \
  --q-gap-oracle-timeout-seconds 30 \
  --q-gap-hard-fail \
  --include-cube-ranges
```

Timeout means unknown, not a proof.  Do not learn a hard clause from a timeout.

### Phase G: Keep q-growth as a feeder, not a proof

q-growth has produced useful frontiers (`q_known=936`), but Hensel did not
produce UNSAT.  Continue q-growth only when it feeds a stronger hard oracle:

- a new exact-carry fixed CNF branch,
- a smaller low-C proof scope,
- or a folded-Coron verified-factor attempt.

Avoid spending long batches on Hensel prefix checks that only repeat
`sat/unknown/timeout` at nearby bit widths.

### Phase H: Use exporter-time fixing for x2 subcubes

For exact-carry fixed-subcube work, prefer `--fix-p-range-sweep` over PySAT
assumptions when the fixed p bits affect q-low or carry constants.  Existing
results show exporter-time fixing shrinks the CNF and closes branches that
assumption-only sweeps leave as timeouts.

Good use case:

```bash
python3 solutions/run_07_go_sat_filter.py \
  --x6 0x245521490bd \
  --x1 0x9b183cdcc \
  --x2low7 0x.. \
  --T 784 --arith-bits 272 \
  --skip-known-prefix-bits 208 \
  --lowlift-q 272 --q-interval-bound \
  --odd-residue-prime 3 --odd-residue-prime 5 \
  --odd-residue-prime 7 --odd-residue-prime 11 \
  --exact-tail-carry-limbs 1 --exact-carry-bits 272 \
  --fix-p-range-sweep 272:8:all \
  --summary-json tmp/ct07_exactcarry_x2low7_XX_x2next8_summary.json \
  --summary-only
```

Do not lift sampled endpoint closures to a whole x2low7 range without a full
range proof.

### Phase I: Pause unproductive lattice probes

Do not spend more time on the current TK/LZ row scans, cuso prefix windows, or
liftT/sumset shift families unless the basis or shift family changes.  Recent
results are consistently projection-derived, negative-margin, or expanding.
The next lattice attempt should have a new construction and a clear preflight
threshold before any large LLL/BKZ run.

The standalone Herrmann-May/Lu-Zhang/Coron direction is lower priority because
the instance has about 59.9% known p bits and 8 unknown blocks.  That is below
the comfortable regime for the usual arbitrary-bit lattice approaches, and the
current probes already show negative margins or no non-projection pruning.

## Documentation Rules

- `RUN_LOG.md`: append exact experiment outcomes and output paths.
- `EXPLORATION_PLAN.md`: update only when priorities or proof discipline
  change.
- `writeups/07_소인수분해.md`: keep as the human narrative and final writeup,
  not as the primary queue manager.
- `tmp/` outputs: include enough path detail in `RUN_LOG.md` to audit the
  evidence later.
