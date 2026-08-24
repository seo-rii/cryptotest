# Challenge 7 historical SAT/CAS plan

> [!NOTE]
> This is a pre-solution control document, not the current project plan.  The
> completed attack and verification are in the
> [final writeup](../../writeups/07_소인수분해.md).  Words such as `current`,
> `next`, and `recommended` below describe the checkpoint at which an entry was
> written.
>
> [!WARNING]
> Every q-gap row historically labelled `hard`, `proof`, or `hard_no_root` is
> heuristic.  Those runs used `beta=0.5`, while the recovered smaller factor
> satisfies `q^2 < N`; reported margin and exhaustive completion sweeps do not
> repair the missing `q >= N^beta` precondition.  The low600 `p` oracle is a
> separate case and is conditionally sound only under the Sage backend,
> divisor-size, bound, margin, and completion checks stated in the final
> writeup.

The preceding exploration snapshot is preserved as
`../07_sat_cas_explore.old`; its ledgers use incompatible bit-range metadata.

## Final Pre-Solution Priority

1. Freeze the x7-focused low600 q-gap default loop.  It fixes
   `150:4,265:84,362:58,920:4` and repeatedly produced direct rows with
   `q_gap_bits=230..236`, but as of 2026-06-20 the x7 focus manifest has
   432 JSONL ledgers and 43961 q-gap no-root cube rows with no factors.  The
   repeated 146-literal independent drops were then treated as branch-exclusion
   evidence, but are now only heuristic q-gap records.  They did not show
   convergence toward `p` or `q`.
2. Keep the existing `soinsu/rsa_partial_leak_assets` Sage+cuso smoke as the
   environment gate: grouped `--mode cuso` and split exact-block
   `--mode cuso-split --cuso-split-brute-small-edges` must run on a machine with
   Sage, cuso, flatter, and msolve before interpreting deeper failures.
3. Promote `ct07_partial_low600_cuso_broad_clause` as the next new experimental
   line.  Instead of fixing all `150:4,265:84,362:58` low600 unknown bits and
   learning one 146-literal branch exclusion, fix only a 58-84 bit low segment
   and leave the remaining low holes plus `z600 = p[600..1023]` as cuso
   variables.  One sound no-root could then cover `2^60..2^90` completions.
4. First smoke the partial-low600 shapes in this order:

   ```text
   B: fixed 150:4 + 362:58; variables 265:84 + z600:424; 62 literals, 508-bit variable mass
   C: fixed 265:84; variables 150:4 + 362:58 + z600:424; 84 literals, 486-bit variable mass
   A: fixed 362:58; variables 150:4 + 265:84 + z600:424; 58 literals, 512-bit variable mass
   D: fixed-budget sweeps such as 265:64+362:8 and 265:48+362:16
   ```

   The goal is not only an immediate factor hit; it is to find the smallest
   fixed low-bit budget for which cuso gives stable root/no-root behavior while
   preserving the true branch on planted tests.
5. Treat multivariate cuso no-root as `soft_no_root` until a soundness gate is
   passed.  A result may become a hard SAT clause only after stronger checking,
   planted/toy true-branch retention, or another deterministic oracle shows that
   the true branch would not be cut.  Classify outputs as `factor`,
   `candidate`, `soft_no_root`, or `hard_no_root`.
6. Promote `ct07_programmatic_low600_sat_cas` as the first Ajani-Bright-style
   solver-in-loop experiment once the oracle has a soundness gate.  Start with a
   PySAT outer loop, not a full CDCL user propagator: get a SAT model, select a
   58-84 bit fixed-low shape, call partial-low600 cuso, add the negated fixed
   bits as a clause only for `hard_no_root`, and ask the solver for the next
   model.  Track factor hits, learned clause count, median clause length,
   repeated projection reduction, and estimated completions eliminated per
   oracle call.
7. Run `ct07_cuso_mixed_shape_search` over grouped/exact/partial block choices:

   ```text
   S0: [265:155], [600:230]
   S1: [265:84], [362:58], [600:69], [682:87], [784:46]
   S2: [265:84], [362:58], [600:230]
   S3: [265:155], [600:69], [682:87], [784:46]
   S4: partial low600 with fixed 58-84 low bits and z600:424
   ```

   Score by elapsed time, cuso backend logs, roots count, candidate/factor hits,
   and no-root reliability on planted/toy instances.
8. Add `ct07_focus_group_hm` as the local/fallback lattice rescue line.  Build
   downscaled planted instances with the same mask geometry, log the
   change-of-basis contribution of input shifts, keep output rows that vanish at
   the true root, test algebraic independence beyond the shortest rows, and
   prune unused shifts before scaling parameters.
9. Add `ct07_cocert_clause_minimization` as the ledger-structure repair line.
   Reframe each oracle result as a co-certificate whose value is the number of
   SAT candidates it excludes.  Prefer 58-84 literal broad clauses over
   146-literal full-cube exclusions, and route accepted certificates into the
   solver loop instead of leaving them as offline JSONL rows.
10. Keep Heninger-Shacham-style low-bit branch discipline as a search-order hint,
   not a separate solver: grow low-bit prefixes systematically and call
   Coppersmith once the prefix enters a useful partial-low600 shape.
11. Keep the no-x7 low600 q-gap line, same-pair ranked q-gap line, full-x1/full-x5
   q-gap 407-408 line, high32 line, and byte-drop variants as fallback or
   reproduction paths.  Revisit them only with a changed ranker, branch shape,
   or a partial-low600 result that motivates a specific follow-up.
12. Keep the older fully fixed low600 p-Coppersmith ledgers as conditional
   supporting evidence, not as the next broad batch.  Under the low600
   preconditions they exclude branches, but the 146-literal clauses did not
   produce useful convergence by themselves.
13. Treat p two-sided Coppersmith and residual partial-p/Coron/HM attempts as
   success-only for now.  No-root or timeout results from these probes must not
   become hard clauses unless a qualifying low600 check or another separately
   validated sound oracle proves the exclusion.

## Literature-Backed Experiment Map

The plan was organized by applicability to this instance:

```text
A. Ajani-Bright 2024:
   programmatic SAT+Coppersmith; solver learns from oracle calls immediately.
   Project experiment: ct07_programmatic_low600_sat_cas.

B. cuso / Solving Multivariate Coppersmith Problems with Known Moduli:
   automatic shift selection for unknown-divisor models with known multiples.
   Project experiment: ct07_cuso_mixed_shape_search.

C. Miller-Narayanan-Venkatesan 2017 focus groups:
   downscaled planted lattices reveal which shifts actually contribute useful
   rows; use this to prune local HM/fpylll fallback lattices.
   Project experiment: ct07_focus_group_hm.

D. Kirchweger-Peitl-Szeider 2023 co-certificate learning:
   external checker output becomes a clause learned by the SAT backend.
   Project experiment: ct07_cocert_clause_minimization.
```

Lower-priority background:

```text
Heninger-Shacham 2009:
  use as low-bit prefix search discipline only; this instance lacks q/d/dp/dq
  leakage, so it is not a direct branch-and-prune private-key reconstruction.

Herrmann-May 2008 and Howgrave-Graham/Coppersmith:
  retain as the mathematical baseline for unknown-divisor partial-bit factoring,
  while remembering that many arbitrary chunks make naive multivariate HM
  expensive.

Generalized implicit factorization / ACD and small-d partial-information work:
  deprioritize because this is a single-modulus partial-p leak with e=65537,
  not shared-prime/multiple-modulus or small-private-exponent RSA.
```

## Evidence at That Checkpoint

Early q-gap batches produced 192 `no-root` rows that the old tooling labelled
`hard-line`:

```text
split hash A: 64 candidates, gap 456, 64 no-roots, no factor
split hash B: 64 candidates, gap 456, 64 no-roots, no factor
low42 hash A: 64 candidates, gap 462, 64 no-roots, no factor
```

This confirms the runner plumbing, but the failed beta precondition means the
rows do not close branches.  They were also far too little sampled coverage to
support a solve ETA.  The preferred plan at that checkpoint was:

1. confirm the `soinsu/rsa_partial_leak_assets` cuso environment with grouped
   and split smoke runs,
2. implement and smoke `ct07_partial_low600_cuso_broad_clause`,
3. validate cuso root/no-root behavior on planted/toy instances before adding
   any hard SAT clauses,
4. turn sound broad no-roots into `ct07_programmatic_low600_sat_cas` learned
   clauses,
5. run `ct07_cuso_mixed_shape_search` in parallel with the oracle work, and
6. keep `ct07_focus_group_hm` and `ct07_cocert_clause_minimization` as the
   fallback lattice and ledger-repair tracks.

The most useful new SAT-ledger shape is:

```text
150:4,265:84,784:46,920:4
```

It gives q-gap about 407--408 bits and a large reported margin.  The first two
cubes returned heuristic `no-root`; the old loop recorded independent drops of
`150:4`, `920:4`, and `784:6`.  Loading those records moved the next model to
`265:84=3`.  The checkpoint used `run_fullx1x5_drop_loop.py` for further
one-cube-at-a-time exploration:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 4 \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_first_cube_drops.jsonl \
  --resume-jsonl tmp/ct07_fresh_fullx1x5_second_cube_drops.jsonl
```

For q-gap 408, `epsilon=0.04` kept about 21 bits in the old effective-margin
field and made the loop roughly 35--40x faster than `epsilon=0.02`; it did not
repair the beta precondition.

`run_fullx1x5_drop_loop.py` supports two drop modes:

```text
--drop-mode independent  # one heuristic clause record per drop window
--drop-mode cumulative   # tests the growing union of drop windows
```

The cumulative smoke test checked every completion after dropping `150:4` and
then `920:4`.  It produced one 130-literal heuristic clause record from the 138
selected literals, using 273 q-gap oracle calls and 8 workers.

The newer high32 shape is:

```text
150:4, 265:84, 798:32, 920:4
```

Use `q_gap_max_bits=440`, `epsilon=0.0305`, and cumulative edge drops
`150:4, 920:4`.  The all-zero completion sweep produced a 116-literal heuristic
clause record from 124 selected literals.  One follow-up cube with 16 workers
took about 108 seconds, so 8 workers was the better setting on that host.

For the same hi32 all-zero cube, every tested completion of these independent
byte windows also returned q-gap `no-root`:

```text
265:8, 273:8, 281:8, 289:8
798:8, 806:8, 814:8, 822:8
```

They are heuristic clause records and did not move the SAT model very far by
themselves.  The first substantial 16-bit cumulative completion sweep,
`265:8 + 273:8`, completed in
`tmp/ct07_fresh_hi32_union_265_273_shard0_eps0028`: all 128 shards passed,
covering `65536 / 65536` `no-root` completions with no factor.  The produced
`learned_clause.jsonl` is a 108-literal heuristic clause record for the high32
cube.  Exhausting completions does not repair the oracle's missing precondition.

The next comparable completion-sweep target was the high-side union
`798:8 + 806:8`, or a SAT-ledger run that loads the new `learned_clause.jsonl`
and asks for the next
high32 cube before spending another multi-hour sweep.  The plan used
`run_q_gap_union_shards.py` rather than a monolithic `semi_programmatic_sat.py`
call for 16-bit unions.  Its internal `proof_key` only prevents mixing shards
from different q-gap parameters.

That SAT-ledger follow-up recorded four more q-gap `no-root` cubes after the
completed `265:8 + 273:8` heuristic union record and the earlier `x0=1` ledger.
The tested `150:4` values were `2`, `3`, `7`, and `5`; all used
`265:84=0`, `798:32=0`, and `920:4=0`.  Each cube had `q_gap_bits=437`,
generated two independent heuristic byte-drop records for `265:8` and `273:8`,
and found no factor.  Loading all ledgers available then selected `150:4=4` as
the next sample cube, so the low x0 front was not exhausted yet.

The later high32 follow-ups tested that low x0 front fully for
`265:84=0, 798:32=0, 920:4=0`: all `150:4 = 0..15` returned heuristic
`no-root`, with no factor.  The next high32 sample moved to `265:84=65536`, so
the shape had started walking x1 space and was deprioritized.

The stronger medium drop set used at that checkpoint was:

```text
150:4, 920:4, 265:8, 273:8, 784:8, 792:8
```

It cost about 1057 q-gap calls per cube and ran around 2 minutes/cube with
8 workers.  It skipped much farther than the small default
set.  A 3-iteration run after all-zero byte-drop ledgers moved through
`265:84 = 520, 778, 1794`, with every completion sweep returning `no-root`.

A later 5-iteration continuation on this q-gap 408 medium-drop line recorded
`265:84 = 1292, 1028, 1542, 3337, 2317`, again all heuristic `no-root` and no factor.
The next 10-iteration continuation recorded
`265:84 = 3088, 2072, 2830, 2567, 3587, 3851, 6405, 6927, 7953, 7442`, again
all heuristic `no-root` and no factor.  The next sample was `265:84=5911`.  This
was the preferred near-term SAT-ledger line because it advanced the x2
frontier much faster than the high32 x1-walk.

A diversified q-gap batch historically labelled `hard-line`
`tmp/ct07_fresh_gateway_hashC_top128_parallel` checked 128 more
`q_gap_bits=456` candidates with no factor.  A further q-gap 408 SAT-ledger
continuation recorded
`265:84 = 5911, 4891, 5407, 4381, 4630, 6675, 6165, 4116, 5145, 5658`, again
all heuristic `no-root` and no factor.  The next sample was `265:84=7196`.

The p-window `[362,830)` oracle was not a good broad batch primitive: one
sample timed out at 120 seconds with `epsilon=0.005`.  The seven-variable
unknown-divisor lattice preflight also remained negative-margin.  Another q-gap
408 continuation recorded
`265:84 = 7196, 7710, 14370, 14625, 15392, 15652, 10533, 11564, 11304, 10281`,
again all heuristic `no-root` and no factor.  The next sample was `265:84=12589`.

The plan did not spend a broad batch on outside-only q-gap 504.  It fixes
`150:4,784:46,920:4`, which is attractive because the outside guess cost is
54 bits, but the top candidate with `epsilon=0.003` timed out after 90 seconds.
Use it only if a much stronger outside-branch ranker appears.

Direct OR-Tools CP-SAT was also not a primary path.  An all-zero edge branch
with p decision priority on `265:84` and `784:46` returned
`UNKNOWN` after about 66 seconds.

The low600 cumulative line was not chosen as the next primary batch.  Its first
post-cumulative continuation stalled for more than 5 hours before producing a
valid cube row.  Existing low600 ledgers were conditional branch-exclusion
evidence under the stated backend, bound, margin, and completion assumptions,
but were not a practical broad search.

The q-gap 456 hit-first line remained useful as a root-hit and ranking probe,
but its `no-root` result was not a sound branch oracle:

```text
base fixed: 150:4, 920:4
high side:  784:46
extra:      either x2_low48 or x5_high48
q gap:      456
epsilon:    0.02
```

On this mask, fixing `150:4` and `920:4` opens the low-q
frontier to 265 bits and gives the high-q prefix near 830/831.  Full `x6` plus
48 bits from one side gives the recorded q-gap shape.  The first 128 ranked
candidates across `x2_low48` and `x5_high48` were checked in 369 seconds:
all `128/128` returned heuristic `no-root`, with no factor.  The plan proposed
expanding this search with larger diversified beams and then adding
clause/minimization accounting around the same q-gap condition.

The first wider continuation checked 256 additional hash-diversified q-gap 456
candidates in 784 seconds, again all heuristic `no-root` and no factor.  That
brought the q-gap 456 sample to 384 branches with no hit.  This showed that
hash-diversified hit-first sampling was not enough by itself: the 102-bit
frontier was too large unless another exact ranker, SAT loop, or residual
lattice narrowed the branch first.

The chosen SAT-ledger continuation at that checkpoint was the q-gap 408
full-x1/full-x5 line with cumulative edge-nibble minimization:

```text
cube ranges: 150:4, 265:84, 784:46, 920:4
drop mode:   cumulative
drop windows:150:4, 920:4
q gap:       408
epsilon:     0.04
```

The probe, 3-iteration continuation, and 20-iteration continuation checked
every completion after dropping `150:4` and `920:4` together for each tested
cube.  Each heuristic record drops 8 bits and keeps 130 literals, with
`256/256` combined completions returning `no-root`.  This minimized more
literals than the earlier independent-drop records and ran around 30--50
seconds per cube with 8 workers.  The cumulative resume manifest was:

```text
tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt
```

Historical bounded continuation:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 120 \
  --max-seconds 43200 \
  --workers 8 \
  --output-dir tmp/ct07_fresh_fullx1x5_cumulative_drop_x0_x7_12h_eps004 \
  --resume-list tmp/ct07_fullx1x5_resume_all_jsonl.txt \
  --resume-list tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt \
  --drop-mode cumulative \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-minimize-max-completions 256 \
  --json
```

The residual HM drivers exist now, but they are not broad-batch replacements
for q-gap.  On a false q-gap 456 candidate with remaining bounds
`[36,58,69,87]`, `m=2,t=1` took about 35 seconds and `m=3,t=1` timed out at
600 seconds.  Edge-bruteforced coarsened 2-variable HM was also checked:
`middle_x5` and `x1_middle362` both failed for all edge assignments with
`m=1..8,t=1..2` and again with `m=10,t=1..2`.  Higher m is too slow for broad
edge sweeps.  Use these HM scripts only on highly ranked finalists or when a
new construction preserves more internal known bits than the current coarse
models.

Immediate next priorities:

## 2026-06-08 update: ranked q-gap direct is the active line

The current best continuation is no longer the monolithic full-x1/full-x5 drop
loop with every ledger loaded.  That path is still mathematically sound, but
the full learned-clause set has become too heavy for the SAT model-selection
step.  A full-ledger ranker after the `after4956` direct sweep loaded 9579
clauses / 1,319,382 literals and returned only `unknown` records at the 250ms
SAT budget.

Use ordered limited-ledger ranking instead:

```text
base ledgers
latest small/targeted q-gap ledgers
newest ranked direct ledger
older bulk direct ledger
```

Then cap learned-clause loading and run direct q-gap over the top ranked
candidates.  Confirmed working limits:

```text
load limit 6500:
  1024 direct candidates checked
  q_gap_bits: 407/408
  all hard no_roots, no factor

load limit 7500:
  1024 direct candidates checked
  q_gap_bits: 407/408
  all hard no_roots, no factor

load limit 8500:
  1024 direct candidates checked
  q_gap_bits: 407/408
  all hard no_roots, no factor

load limit 9500:
  1024 direct candidates checked
  q_gap_bits: 407/408
  all hard no_roots, no factor

load limit 10000:
  one ordered list, after13042, completed and checked 1024 direct candidates
  q_gap_bits: 407/408
  all hard no_roots, no factor

load limit 10500:
  one ordered list, after14066, completed and checked 1024 direct candidates
  q_gap_bits: 407/408
  all hard no_roots, no factor
```

Another ordered list, after13142, failed at 10000/10500 without a ranker JSON.
So 10000+ remains order-sensitive.  Count only completed rank/direct summaries
as coverage.

Next ranked-direct step:

```text
1. Do not raise load-learned-limit above 10500 blindly, and do not assume every
   ledger order can reach 10000+.
2. Add a clause-selection/compaction pass before the next broad ranker:
   prefer recent 407/408 q-gap clauses, keep cumulative-drop clauses, and cap
   low-yield bulk direct clauses.
3. Re-run the ranker at 9500 with a different ordered subset or diversity salt,
   then direct-check only genuinely new top candidates.
4. If a compacted 9500 run still repeats the same x2/x6 fronts, switch to a
   different branch shape rather than spending more Coppersmith calls on near
   duplicates.
```

The first exclude-seen 9500 run found only two unseen pairs, and both direct
checks returned hard `no_roots`.  The current ordered 9500-clause view is
therefore nearly exhausted for this pair ranker.  The next useful engineering
task is one of:

```text
1. Clause compaction:
   keep cumulative/drop clauses and recent 407/408 q-gap clauses, but thin the
   older bulk direct clauses so the ranker can load a wider and less repetitive
   subset under the same 9500 ceiling.

2. New branch shape:
   move away from the current x2/x6 pair frontier and try another hard q-gap
   projection, for example a no-x7 or high-side-biased shape already supported
   by run_nox7_cumulative_cycle.py.

3. Finalist oracle:
   use residual HM / p-window only on a very small set of top finalists.  Do
   not promote those no-root results to hard clauses.
```

2026-06-09 update:

```text
ranked q-gap same-pair line:
  after14066 top2048 is direct-checked through rank 2048.
  all 2048 rows were hard no_roots, no factor.
  same x2/x6 pair frontier should no longer be the default broad line.

compacted ledger:
  tmp/ct07_compacted_ranker_after16090_max12000_pair2.jsonl
  selected 8186 hard rows across 4094 x2/x6 pairs.
  Use it to test altered ranker orders or assumption ranges.

no-x7 line:
  direct-only skip-sampler seed20260666 added 256 hard no_roots.
  x2low4 and x3low4 top1 cumulative probes each produced one 138-literal
  hard no-root variant.
  seed20260667 repeated the same pattern: 256 hard no_roots plus one x2low4
  and one x3low4 cumulative 138-literal hard variant, with no factor.
  seed20260668 used the larger 512-direct/top2 cycle: 512 hard no_roots plus
  two x2low4 and two x3low4 cumulative 138-literal hard variants, no factor.
  seed20260669 repeated the 512-direct/top2 cycle: 512 hard no_roots at
  q_gap_bits=324, two x2low4 and two x3low4 cumulative 138-literal hard
  variants, no factor.
  seed20260670 12h-bounded run stopped early during iteration 2 x3
  post-processing, but completed/recovered two 512-direct iterations and eight
  cumulative 138-literal hard variants, no factor.  Treat it as partial
  recovered coverage, not a completed long-run summary.

x7 focus line:
  tmp/ct07_x7_focus_manifest_20260609.txt
  seed20260680 max64 direct: 64 hard no_roots, q_gap_bits=230..236, no factor.
  seed20260680 top1 cumulative x0+x7 minimization: one 142-literal hard
  no-root variant, no factor.
  seed20260682 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor.
  seed20260682 top4 independent minimization: each representative proved
  independent drops for 150:4, 920:4, 265:4, and 362:4, producing four
  146-literal hard variants per representative, no factor.
  seed20260682 next4 independent minimization repeated the same result for
  representatives 5-8, no factor.  The focus manifest now has 11 JSONL ledgers.
  seed20260682 top4 cumulative x0+x7 attempt stopped before a cube JSONL, and
  a top1 retry timed out after 180s with an empty JSONL.  Neither is coverage.
  seed20260684 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor; top4 independent minimization again proved 150:4, 920:4, 265:4,
  and 362:4 for all four representatives.
  seed20260683 max512 direct, launched concurrently by an external runner:
  512 hard no_roots, q_gap_bits=230..236, no factor; top4 independent
  minimization again proved the same four nibble drops.  The focus manifest now
  has 21 JSONL ledgers.
  seed20260685 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor.  Top4 independent minimization again proved 150:4, 920:4, 265:4,
  and 362:4 for all four representatives.  The focus manifest now has 26 JSONL
  ledgers.
  seed20260686 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor.  Top4 independent minimization again proved the same four nibble
  drops.  The focus manifest now has 31 JSONL ledgers.
  seed20260687 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor.  Top4 independent minimization again proved 150:4, 920:4,
  265:4, and 362:4 for all four representatives.  The focus manifest now has
  36 JSONL ledgers.
  seed20260688 max512 direct: 512 hard no_roots, q_gap_bits=230..236,
  no factor.  Top4 independent minimization again proved the same four nibble
  drops.  The focus manifest now has 41 JSONL ledgers and 3681 cube rows, all
  q-gap no_roots with no factors.
  seed20260689 non-skip direct stopped before sample/q-gap output and is not
  coverage.  Retrying as seed20260689 skip-sampler direct completed 512 hard
  no_roots at q_gap_bits=230..236, no factor; top4 independent minimization
  again proved all four nibble drops.  The focus manifest now has 46 JSONL
  ledgers and 4197 cube rows, all q-gap no_roots with no factors.
  A concurrently running full-x1/full-x5 projection batch
  `tmp/ct07_fullx1x5_projection_runner_seed20260691` also completed: 256 hard
  no_roots at q_gap_bits=407..415, no factor, and appended its direct ledger to
  `tmp/ct07_fullx1x5_resume_all_jsonl.txt`, which now has 85 ledgers.
  seed20260690 skip-sampler direct completed another 512 hard no_roots at
  q_gap_bits=230..236, no factor; top4 independent minimization again proved
  all four nibble drops.  The focus manifest now has 51 JSONL ledgers and 4713
  cube rows, all q-gap no_roots with no factors.
  seed20260691 skip-sampler direct completed another 512 hard no_roots at
  q_gap_bits=230..236, no factor; top4 independent minimization again proved
  all four nibble drops.  The focus manifest now has 56 JSONL ledgers and 5229
  cube rows, all q-gap no_roots with no factors.
  seed20260692 learned-probe max32 added 32 hard no_roots at q_gap_bits=230..236,
  no factor.
  seed-base 20260692 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260693 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 62 JSONL ledgers and 5777
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260693 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260694 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 67 JSONL ledgers and 6293 cube
  rows, all q-gap no_roots with no factors.
  seed-base 20260694 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260695 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 72 JSONL ledgers and 6809
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260695 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260696 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 77 JSONL ledgers and 7325 cube
  rows, all q-gap no_roots with no factors.
  seed-base 20260696 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260697 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 82 JSONL ledgers and 7841
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260697 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260698 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 87 JSONL ledgers and 8357 cube
  rows, all q-gap no_roots with no factors.
  seed-base 20260698 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260699 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 92 JSONL ledgers and 8873
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260699 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260700 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 97 JSONL ledgers and 9389 cube
  rows, all q-gap no_roots with no factors.
  seed-base 20260700 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260701 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 102 JSONL ledgers and 9905
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260701 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260702 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 107 JSONL ledgers and 10421
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260702 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260703 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 112 JSONL ledgers and
  10937 cube rows, all q-gap no_roots with no factors.
  seed-base 20260703 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260704 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 117 JSONL ledgers and 11453
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260704 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260705 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 122 JSONL ledgers and
  11969 cube rows, all q-gap no_roots with no factors.
  seed-base 20260705 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260706 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 127 JSONL ledgers and 12485
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260706 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260707 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 132 JSONL ledgers and
  13001 cube rows, all q-gap no_roots with no factors.
  seed-base 20260707 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260708 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 137 JSONL ledgers and 13517
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260708 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260709 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 142 JSONL ledgers and
  14033 cube rows, all q-gap no_roots with no factors.
  seed-base 20260709 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260710 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 147 JSONL ledgers and 14549
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260710 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260711 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 152 JSONL ledgers and
  15065 cube rows, all q-gap no_roots with no factors.
  seed-base 20260711 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260712 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 157 JSONL ledgers and 15581
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260712 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260713 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 162 JSONL ledgers and
  16097 cube rows, all q-gap no_roots with no factors.
  seed-base 20260713 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260714 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 167 JSONL ledgers and 16613
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260714 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260715 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 172 JSONL ledgers and
  17129 cube rows, all q-gap no_roots with no factors.
  seed-base 20260715 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260716 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 177 JSONL ledgers and 17645
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260716 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260717 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 182 JSONL ledgers and
  18161 cube rows, all q-gap no_roots with no factors.
  seed-base 20260717 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260718 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 187 JSONL ledgers and 18677
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260718 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260719 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 192 JSONL ledgers and
  19193 cube rows, all q-gap no_roots with no factors.
  seed-base 20260719 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260720 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 197 JSONL ledgers and 19709
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260720 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260721 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 202 JSONL ledgers and
  20225 cube rows, all q-gap no_roots with no factors.
  seed-base 20260721 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260722 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 207 JSONL ledgers and 20741
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260722 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260723 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 212 JSONL ledgers and
  21257 cube rows, all q-gap no_roots with no factors.
  seed-base 20260723 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260724 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 217 JSONL ledgers and 21773
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260724 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260725 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 222 JSONL ledgers and
  22289 cube rows, all q-gap no_roots with no factors.
  seed-base 20260725 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260726 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 227 JSONL ledgers and 22805
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260726 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260727 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 232 JSONL ledgers and
  23321 cube rows, all q-gap no_roots with no factors.
  seed-base 20260727 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260728 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 237 JSONL ledgers and 23837
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260728 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260729 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 242 JSONL ledgers and
  24353 cube rows, all q-gap no_roots with no factors.
  seed-base 20260729 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260730 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 247 JSONL ledgers and 24869
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260730 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260731 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 252 JSONL ledgers and
  25385 cube rows, all q-gap no_roots with no factors.
  seed-base 20260731 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260732 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 257 JSONL ledgers and 25901
  cube rows, all q-gap no_roots with no factors.  The direct JSONL ledgers were
  preserved while generated direct sidecars were cleaned to recover disk space.
  seed-base 20260732 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260733 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 262 JSONL ledgers and
  26417 cube rows, all q-gap no_roots with no factors.
  seed-base 20260733 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260734 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 267 JSONL ledgers and 26933
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260734 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260735 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 272 JSONL ledgers and
  27449 cube rows, all q-gap no_roots with no factors.
  seed-base 20260735 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260736 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 277 JSONL ledgers and 27965
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260736 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260737 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 282 JSONL ledgers and
  28481 cube rows, all q-gap no_roots with no factors.
  seed-base 20260737 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260738 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 287 JSONL ledgers and 28997
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260738 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260739 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 292 JSONL ledgers and
  29513 cube rows, all q-gap no_roots with no factors.
  seed-base 20260739 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260740 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved the same four nibble drops for all four
  representatives.  The focus manifest now has 297 JSONL ledgers and 30029
  cube rows, all q-gap no_roots with no factors.
  seed-base 20260740 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260741 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 302 JSONL ledgers and
  30545 cube rows, all q-gap no_roots with no factors.
  seed-base 20260741 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260742 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 307 JSONL ledgers and
  31061 cube rows, all q-gap no_roots with no factors.
  seed-base 20260742 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260743 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 312 JSONL ledgers and
  31577 cube rows, all q-gap no_roots with no factors.
  seed-base 20260743 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260744 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 317 JSONL ledgers and
  32093 cube rows, all q-gap no_roots with no factors.
  seed-base 20260744 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260745 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 322 JSONL ledgers and
  32609 cube rows, all q-gap no_roots with no factors.
  seed-base 20260745 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260746 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 327 JSONL ledgers and
  33125 cube rows, all q-gap no_roots with no factors.
  seed-base 20260746 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260747 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 332 JSONL ledgers and
  33641 cube rows, all q-gap no_roots with no factors.
  seed-base 20260747 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260748 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 337 JSONL ledgers and
  34157 cube rows, all q-gap no_roots with no factors.
  seed-base 20260748 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260749 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 342 JSONL ledgers and
  34673 cube rows, all q-gap no_roots with no factors.
  seed-base 20260749 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260750 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 347 JSONL ledgers and
  35189 cube rows, all q-gap no_roots with no factors.
  seed-base 20260750 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260751 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 352 JSONL ledgers and
  35705 cube rows, all q-gap no_roots with no factors.
  seed-base 20260751 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260752 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 357 JSONL ledgers and
  36221 cube rows, all q-gap no_roots with no factors.
  seed-base 20260752 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260753 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 362 JSONL ledgers and
  36737 cube rows, all q-gap no_roots with no factors.
  seed-base 20260753 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260754 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 367 JSONL ledgers and
  37253 cube rows, all q-gap no_roots with no factors.
  seed-base 20260754 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260755 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 372 JSONL ledgers and
  37769 cube rows, all q-gap no_roots with no factors.
  seed-base 20260755 skip-sampler direct was rerun after a partial 290-row
  interrupt, and the rerun completed another 512 hard no_roots with internal
  seed 20260756 at q_gap_bits=230..236, no factor; top4 independent
  minimization again proved 150:4, 920:4, 265:4, and 362:4 for all four
  representatives.  The focus manifest now has 377 JSONL ledgers and 38285 cube
  rows, all q-gap no_roots with no factors.
  seed-base 20260756 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260757 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 382 JSONL ledgers and
  38801 cube rows, all q-gap no_roots with no factors.
  seed-base 20260757 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260758 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 387 JSONL ledgers and
  39317 cube rows, all q-gap no_roots with no factors.
  seed-base 20260758 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260759 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 392 JSONL ledgers and
  39833 cube rows, all q-gap no_roots with no factors.
  seed-base 20260759 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260760 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 397 JSONL ledgers and
  40349 cube rows, all q-gap no_roots with no factors.
  seed-base 20260760 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260761 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 402 JSONL ledgers and
  40865 cube rows, all q-gap no_roots with no factors.
  seed-base 20260761 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260762 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 407 JSONL ledgers and
  41381 cube rows, all q-gap no_roots with no factors.
  seed-base 20260762 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260763 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 412 JSONL ledgers and
  41897 cube rows, all q-gap no_roots with no factors.
  seed-base 20260763 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260764 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 417 JSONL ledgers and
  42413 cube rows, all q-gap no_roots with no factors.
  seed-base 20260764 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260765 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 422 JSONL ledgers and
  42929 cube rows, all q-gap no_roots with no factors.
  seed-base 20260765 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260766 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 427 JSONL ledgers and
  43445 cube rows, all q-gap no_roots with no factors.
  seed-base 20260766 skip-sampler direct completed another 512 hard no_roots
  with internal seed 20260767 at q_gap_bits=230..236, no factor; top4
  independent minimization again proved 150:4, 920:4, 265:4, and 362:4 for all
  four representatives.  The focus manifest now has 432 JSONL ledgers and
  43961 cube rows, all q-gap no_roots with no factors.
```

Near-term priority is now the `soinsu/rsa_partial_leak_assets` Sage+cuso path,
plus the literature-backed solver-loop experiments, ahead of any further blind
q-gap ledger batching.  First smoke grouped 2-variable `--mode cuso` and exact
split-block `--mode cuso-split --cuso-split-brute-small-edges` to prove the
external environment.  Then implement `ct07_partial_low600_cuso_broad_clause`
and test fixed-low shapes B, C, A, and adaptive fixed-budget variants.  If the
soundness gate passes, move into `ct07_programmatic_low600_sat_cas` so the SAT
solver learns broad clauses immediately.  In parallel, run
`ct07_cuso_mixed_shape_search`; keep `ct07_focus_group_hm` for local/fallback
lattice pruning and `ct07_cocert_clause_minimization` for turning ledger rows
into broader co-certificate clauses.  Do not run another same-pair `rank_q_gap`
batch by default.
The recent no-x7 total from seeds 20260666-20260670 is 2560 direct hard no-root
cube rows plus 18 cumulative 138-literal hard variants, still with no factor.
Only revisit same-pair ranking if the compacted ledger is paired with a changed
assumption range, score mode, or branch shape.  If using `rank_q_gap` near the
10500-clause ledger size, always set `--solver-timeout-ms 1000`; default 250ms
produced all-unknown outputs in both top4095 and partial x2-range probes.

Do not count stopped or killed loop attempts as proof.  Only completed JSONL
rows with a cube record and q-gap `no_roots` under the hard-margin threshold
are ledger evidence.  The current guarded runner enforces this for
`run_fullx1x5_drop_loop.py`, but manually stopped smoke directories still need
to be ignored in accounting.

Frozen x7 focus continuation command, for reproduction only:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_projection_frontier_batches.py \
  --iterations 1 \
  --output-dir tmp/ct07_x7_direct_focus_seed20260767_skip_sampler_max512 \
  --manifest tmp/ct07_x7_focus_manifest_20260609.txt \
  --seed-base 20260767 \
  --cube-ranges 150:4,265:84,362:58,920:4 \
  --frontier-top 1280 \
  --candidate-pool 131072 \
  --top-pairs 512 \
  --samples-per-pair 1 \
  --max-total 512 \
  --workers 8 \
  --solver-timeout-ms 1000 \
  --random-assumption-bits 32 \
  --random-assumption-retries 8 \
  --frontier-timeout-seconds 120 \
  --sample-timeout-seconds 600 \
  --qgap-timeout-seconds 1800 \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --oracle-timeout-seconds 120 \
  --skip-sampler-learned-clauses \
  --projection 150:4:x0 \
  --projection 265:8:x2low8 \
  --projection 362:4:x3low4 \
  --projection 920:4:x7 \
  --json

python3 cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py \
  --source-jsonl tmp/ct07_x7_direct_focus_seed20260767_skip_sampler_max512/iteration_0001_qgap.jsonl \
  --output-dir tmp/ct07_x7_independent_min_seed20260767_skip_sampler_top4 \
  --append-manifest tmp/ct07_x7_focus_manifest_20260609.txt \
  --start-index 1 \
  --top 4 \
  --cube-ranges 150:4,265:84,362:58,920:4 \
  --shape 150:4,265:84,362:58,920:4 \
  --projection 150:4:x0 \
  --projection 265:8:x2low8 \
  --projection 362:4:x3low4 \
  --projection 920:4:x7 \
  --drop-mode independent \
  --drop-window 150:4 \
  --drop-window 920:4 \
  --drop-window 265:4 \
  --drop-window 362:4 \
  --q-gap-minimize-max-completions 256 \
  --workers 8 \
  --item-timeout-seconds 300 \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --json
```

The next useful x7 focus step is one more 512-row direct batch using the focus
manifest, followed by top4 independent minimization.  If a minimization runner
is interrupted, recover only non-empty JSONLs whose cube row proves q-gap
`no_roots`, `no_root_hard_clause_eligible=true`, no factors, and all requested
drop windows `droppable_sound_no_root`.  This line should stay in its own focus
manifest until it is clear whether the x7 clauses improve the no-x7 frontier.

Repeated top4 independent runs already succeeded for `150:4`, `920:4`,
`265:4`, and `362:4`.  The cumulative top4 `x0+x7` attempt stopped without a
JSONL and the top1 retry timed out at 180s, so cumulative x7 focus minimization
is not the next default.  Prefer independent nibble drops, or retry cumulative
only with a specific reason and a longer guarded timeout.

1. Run x7 focus representative independent nibble-drop minimization on the
   next direct batch.
2. Alternate x7 focus 512-row direct batches with small representative
   minimization while q-gap stays in the 230-236 range.
3. Use no-x7 direct-plus-small-cumulative cycles as the broad fallback when
   x7 focus starts repeating the same projection keys.
4. Keep q-gap 456 and q-gap 408 lines as validation/ranker comparison paths,
   not as the default blind coverage lines.
5. Use `branch_partial_coppersmith.py`, `edge_partial_coppersmith_sweep.py`,
   `branch_pq_coron.py`, and direct full-size BV/Z3 only as finalist success
   oracles unless a planted test shows a cheaper residual parameter set.

## Completion Criteria

The problem is solved only when a script verifies a nontrivial factor of `N`,
the complementary factor, corrected p-mask consistency, and RSA decryption.
No amount of hard no-root branch coverage by itself is a complete solve.

## Recommended Hybrid q-gap 408 Continuation

The current best broad SAT-ledger command is:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 120 \
  --max-seconds 43200 \
  --workers 8 \
  --output-dir tmp/ct07_hybrid_drop_full_default_12h_eps004 \
  --resume-list tmp/ct07_fullx1x5_resume_all_jsonl.txt \
  --resume-list tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_edge_x2low8_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_full_default_eps004/iteration_0001.jsonl \
  --resume-list tmp/ct07_hybrid_drop_after_probes_iter5_jsonl.txt \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-minimize-max-completions 256 \
  --json
```

The default hybrid windows are:

```text
cumulative: 150:4, 920:4
independent: 265:8, 273:8, 784:8, 792:8
```

Expected speed from the first full probe is roughly 2-3 minutes per cube with
8 workers, yielding about 200-350 cubes in a 12-hour run depending on system
load.  Use `--workers 12` only if the machine has spare CPU and memory; each
cube launches many short Sage/Coppersmith calls.

The five-cube follow-up after the probes closed five more cubes in 656.3
seconds, so the measured average is about 131 seconds per cube on this machine.
For unattended runs where occasional slow Sage calls are a problem, add:

```bash
  --q-gap-oracle-timeout-seconds 180
```

Do not set this too aggressively: timeout completions are treated as unknown,
not as hard no-root, so they can reduce learned-clause yield.

JM low-lift is not the current primary path.  It correctly sees the corrected
mask as bounds `[84,58,69,87,46,Y567]`, but small `m=1/2` probes currently fail
inside `crypto-attacks` with `IndexError` and the extended probes are slow.
Only revisit it with a planted regression or a fixed root-extraction path.

## CP-SAT Tail Edge-Free Probe

There is now a second operational probe path:

```bash
python3 cryptotest/solutions/run_07_tail_cp_sat_edge_sweep.py \
  --output-dir tmp/ct07_tail_cpsat_free_x7_full_seed7 \
  --branch-lows 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15 \
  --seeds 7 \
  --time-limit 10 \
  --workers 8 \
  --resume \
  --json
```

This runs the `T=928` exact-tail CP-SAT model with `x7` left free, so the 256
edge-nibble combinations are covered by 16 `x0` models instead of 256
`x0,x7` models.  The four-branch smoke probe:

```text
tmp/ct07_tail_cpsat_free_x7_x0_0_3_seed7_probe
```

returned `UNKNOWN` for all four branches and no factor.  A full shallow
seed-7 pass has also been completed:

```text
tmp/ct07_tail_cpsat_free_x7_full_seed7_t10
```

It covered all 16 `x0` values with `x7` free.  All runs returned `UNKNOWN`, no
factor was found, and the total CP-SAT wall time was 195.58 seconds
(`12.22s` average, `20.77s` max).  Shallow comparisons showed `--lowlift-q 265`
as the cheapest variant:

```text
baseline:      195.58s total, 247599 branches, 14095 conflicts
lowlift q265: 172.09s total, 141533 branches, 4459 conflicts
lowlift q272: 172.06s total, 175560 branches, 19799 conflicts
```

A deeper direct-hit pass was also run:

```text
tmp/ct07_tail_cpsat_free_x7_full_seeds7_13_23_t30_lowlift265
```

It used `x0=0..15`, `x7` free, seeds `7,13,23`, `time_limit=30`, and
`--lowlift-q 265 --no-compact-q-limbs`.  All 48 runs returned `UNKNOWN`, no
factor was found, and the total CP-SAT wall time was 1504.11 seconds.  This
confirms the runner is cheap enough for occasional probing, but CP-SAT direct
hit is not currently the primary path.

Use this as a direct solve probe, not as proof accounting.  Only `FEASIBLE` or
`OPTIMAL` with verified `p | N` solves the instance, and only `INFEASIBLE`
would be a hard branch closure.  Current statuses are `UNKNOWN`.

If a longer CP-SAT pass is desired, use `--lowlift-q 265 --no-compact-q-limbs`
first.  Do not add `--decision-p-range 920:4`; that explicit x7 decision probe
was slower in the smoke test.  The main budget should return to hybrid q-gap
408 SAT-ledger work or to a stronger branch ranker.

## Guarded q-gap Diversification

The q-gap SAT-ledger runner now supports guarded cube assumptions.  Use this
when the default Z3 model keeps returning similar x6 values:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 15 \
  --workers 8 \
  --output-dir tmp/ct07_hybrid_drop_x6low4_cycle_eps004 \
  --resume-list tmp/ct07_fullx1x5_resume_all_jsonl.txt \
  --resume-list tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_edge_x2low8_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_full_default_eps004/iteration_0001.jsonl \
  --resume-list tmp/ct07_hybrid_drop_after_probes_iter5_jsonl.txt \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-minimize-max-completions 256 \
  --cube-assume-p-range-cycle 784:4:0x1,0x2,0x3,0x4,0x5,0x6,0x7,0x8,0x9,0xa,0xb,0xc,0xd,0xe,0xf \
  --json
```

The assumption is temporary during `solver.check`, but the assumed bits are
included in `cube_ranges`, so loaded learned clauses stay guarded.  A probe
with `--cube-assume-p-range 784:4:0xf` closed one hard q-gap cube:

```text
tmp/ct07_hybrid_drop_assume_x6low4_f_probe_eps004
q_gap_bits=409, no factor, 5 learned variants, 152.46s
```

A five-iteration cycle over `784:4=1..5` was also completed:

```text
tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004
iterations: 5
factor: none
q_gap_bits: 407..412
learned variants: 5 per cube
total elapsed: 720.79s
```

This is useful for coverage diversity.  It is not faster than the default
hybrid path, so alternate it with normal hybrid batches rather than replacing
them entirely.  Also note that all five cycle cubes still had `265:84 = 0`;
the next diversification step should cycle or rank x2 byte windows, or use a
proper q-gap/product-prefix ranker instead of only forcing x6.

A matching x2 low-byte cycle was then run:

```text
tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004
iterations: 5
factor: none
q_gap_bits: all 408
learned variants: 5 per cube
total elapsed: 781.90s
```

This successfully forced nonzero `265:8` assumptions and generated hard
q-gap clauses, but every cube went back to `784:46 = 0`.  The next bounded
diversity batch should therefore combine both dimensions:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py \
  --iterations 5 \
  --workers 8 \
  --output-dir tmp/ct07_hybrid_drop_x2low8_x6low4_cycle_eps004 \
  --resume-list tmp/ct07_fullx1x5_resume_all_jsonl.txt \
  --resume-list tmp/ct07_fullx1x5_resume_cumulative_x0_x7_iter20_jsonl.txt \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_edge_x2low8_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_probe_full_default_eps004/iteration_0001.jsonl \
  --resume-list tmp/ct07_hybrid_drop_after_probes_iter5_jsonl.txt \
  --resume-jsonl tmp/ct07_hybrid_drop_assume_x6low4_f_probe_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004/iteration_0002.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004/iteration_0003.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004/iteration_0004.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x6low4_cycle_1_5_eps004/iteration_0005.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004/iteration_0001.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004/iteration_0002.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004/iteration_0003.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004/iteration_0004.jsonl \
  --resume-jsonl tmp/ct07_hybrid_drop_x2low8_cycle_1_5_eps004/iteration_0005.jsonl \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --q-gap-minimize-max-completions 256 \
  --cube-assume-p-range-cycle 265:8:0x6,0x7,0x8,0x9,0xa \
  --cube-assume-p-range-cycle 784:4:0x6,0x7,0x8,0x9,0xa \
  --json
```

This is still coverage work, not a guarantee of quick factor recovery.  A
ranker remains the better long-term improvement if manual cycles continue to
close branches without moving toward a factor.

The combined batch above has now been completed:

```text
tmp/ct07_hybrid_drop_x2low8_x6low4_cycle_eps004
iterations: 5
factor: none
q_gap_bits: 407, 409, 410, 408, 408
learned variants: 5 per cube
total elapsed: 696.48s
average elapsed: 139.30s
total q-gap calls: 6485
```

The closed guarded cubes were:

```text
265:8=6  + 784:4=6   -> 150:4=2, 265:84=6,  784:46=6,  920:4=0
265:8=7  + 784:4=7   -> 150:4=2, 265:84=7,  784:46=7,  920:4=0
265:8=8  + 784:4=8   -> 150:4=2, 265:84=8,  784:46=8,  920:4=0
265:8=9  + 784:4=9   -> 150:4=2, 265:84=9,  784:46=9,  920:4=0
265:8=10 + 784:4=10  -> 150:4=2, 265:84=10, 784:46=10, 920:4=0
```

All were hard-eligible q-gap no-root closures, but no factor was found.  Manual
guarded cycles are therefore validated as proof-accounting work, not as a
strong hit-first strategy.  The next improvement should be a ranker that
chooses `(x2_low_byte, x6_low_nibble)` pairs using q-gap width, product-prefix
pressure, q-prefix interval quality, and clause novelty.

That ranker has now been implemented:

```text
rank_q_gap_assumption_pairs.py
run_ranked_q_gap_hits.py
```

It produced two hit-first sweeps:

```text
tmp/ct07_ranked_qgap_hits_top16_after_cycles
tmp/ct07_ranked_qgap_hits_rank17_128_after_cycles
```

for the raw top 128 ranked pairs, and:

```text
tmp/ct07_ranked_qgap_hits_diverse64_after_top128
```

for a diversified top 64 with `--max-per-x6-value 4 --max-per-x2-value 2`.

Current ranked hit-first outcome:

```text
factor: none
raw ranked probes: 128, all q_gap=407
diverse probes: 64, q_gap in {407,408,409,410,412}
total ranked q-gap calls: 192
```

Interpretation:

```text
q-gap width alone is not a good enough hit-first signal.
The raw ranker collapses to x6=0x4/0x6.
Diversity caps fix coverage, but still did not produce a factor in 64 probes.
```

Next priority is to avoid spending large time on more unminimized low-q-gap
hits.  Use the ranker output as feeder data, but add one of these stronger
signals before the next broad run:

```text
1. product-prefix conflict depth / alternative model count for each pair
2. q-prefix interval-center score against N / p-interval geometry
3. learned-clause novelty across full selected literals, not just x2/x6 pair
4. a small hybrid-minimization sample on diverse representatives only
```

For proof accounting, the immediate bounded next run is not another 64-hit
sweep.  Pick about 4 to 8 representatives from the diversified rank file and
run hybrid minimization to see whether those full no-root clauses generalize
as well as the previous manual cycles.

Update after direct runner:

```text
run_ranked_q_gap_direct.py
```

now runs q-gap Coppersmith directly on ranker `cube_ranges` in parallel and can
emit compatible hard-clause JSONL.  It was used to complete one-model q-gap
coverage over all currently ranked pairs:

```text
previous subprocess hit-first: 192 records
direct after top192: 512 records
direct remaining: 3341 records
combined: 4045 records
factor: none
all statuses: no_roots
```

The direct JSONLs are:

```text
tmp/ct07_ranked_qgap_direct_after_top192_top512.jsonl
tmp/ct07_ranked_qgap_direct_after_704_all_remaining.jsonl
```

Next priority changes again.  Do not spend more time on first-model pair
ranking; that layer has been exhausted.  The next SAT/CAS step is to load the
4045 direct no-root cubes and ask Z3 for second/third full edge models under
the same pair space.  To keep it bounded, add a no-minimization q-gap ledger
runner or extend `run_fullx1x5_drop_loop.py` with a no-drop mode, then run
small batches before deciding whether hybrid minimization is worth applying.

That no-minimization path now exists:

```text
run_fullx1x5_drop_loop.py --drop-mode none
```

Small probe after loading the 4045 direct ranked hard ledgers:

```text
tmp/ct07_qgap_nodrop_after_direct4045_probe
iterations: 3
factor: none
elapsed: 74.66s
q_gap_bits: 408 for all 3
status: no_roots for all 3
```

The current plan is therefore:

```text
1. Stop first-model pair ranking; it has been exhausted for the current ranker.
2. Use no-drop q-gap ledger batches to advance SAT to second/third models.
3. Watch whether the solver keeps clustering on the same 265:84 and 784:46 values.
4. If clustering persists, add explicit diversification assumptions or a model-blocking
   ranker over full selected edge cubes.
5. Apply hybrid minimization only to representative cubes that repeat across layers.
```

This is still not a factor.  It is a disciplined way to continue proof
accounting without paying the 1000+ oracle-call cost of full hybrid
minimization for every cube.

Update after include-seen layer runs:

```text
tmp/ct07_ranked_qgap_direct_include_seen_after4048_top256.json
tmp/ct07_ranked_qgap_direct_include_seen_after4304_top512.json
```

Together with the 3 no-drop next-model probes, these add:

```text
additional hard no-root cubes: 771
factor: none
```

The include-seen ranker still leaves `4095 / 4096` assumption pairs SAT after
loading the current ledgers, so this is not close to exhaustive proof.  It is
useful for generating balanced next-layer cubes, especially because the direct
runs distributed `x6_low4` evenly across all 16 values.

However, full no-drop clauses remain too local.  A full hybrid minimization
attempt after 4816 ledgers was too expensive and was stopped before producing
a cube result.  A smaller edge-only minimization on representative
`265:8=0x00, 784:4=0x4` completed in 32.50s and soundly dropped all four
`x0` bits:

```text
tmp/ct07_edge_drop_after4816_x2_00_x6_4_probe
selected cube: 150:4=4, 265:84=0, 784:46=4, 920:4=0
learned literals: 134
dropped bits: 150,151,152,153
```

Next plan:

```text
1. Use include-seen rank/direct batches for broad layer advancement only in bounded chunks.
2. Prefer edge-only minimization (`150:4`, optionally `920:4` with higher cap) on repeated representatives.
3. Do not run full hybrid byte-window minimization by default; it is currently too expensive.
4. Add the edge-minimized ledger to the next manifest before further ranking.
5. If edge drops repeatedly succeed, build a small automated edge-minimization queue over top repeated pairs.
```

The edge-minimization queue now exists:

```text
run_edge_minimization_queue.py
```

First batch outcome:

```text
tmp/ct07_edge_min_queue_after4817_top4_rank2
records: 4
factor: none
all four dropped x0 bits 150..153
learned literals per representative: 134
```

After adding those ledgers:

```text
tmp/ct07_current_qgap_ledgers_after4821_edge_queue.txt
tmp/ct07_ranked_qgap_pairs_include_seen_after4821_edge_top256.json
```

the ranker still reports `4095 / 4096` SAT pairs, but the top layer shifted to
new `x2_low8` values.  This makes the next concrete loop:

```text
1. Continue edge-minimization queue in small batches from the latest rank JSON.
2. Periodically rerank after each batch of 4 to 8 generalized clauses.
3. Run direct q-gap only when a new rank layer is broad enough to justify closing many full cubes.
4. Revisit x7 dropping with `--q-gap-minimize-max-completions 256` only for a few representatives,
   because it costs about 16x more oracle calls than x0-only dropping.
```

Update after the next six representatives:

```text
tmp/ct07_edge_min_queue_after4821_top6_rank1
records: 6
factor: none
all six dropped x0 bits 150..153
learned literals per representative: 134
manifest: tmp/ct07_current_qgap_ledgers_after4827_edge_queue.txt
manifest ledgers: 322
```

`run_edge_minimization_queue.py --manifest-output` should be used for future
multi-item queues so the cumulative ledger list is updated as work finishes.
The edge-minimized evidence is now 11 total representatives including the
manual probe, and all of them dropped `x0` successfully.  Continue in batches
of 4 to 8, then rerank from the latest manifest before choosing the next
representative set.

Update after reranking the 322-ledger manifest and closing eight more
representatives:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4827_edge_top256.json
loaded ledger files: 322
clauses added: 5209
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2

tmp/ct07_edge_min_queue_after4827_top8_rank1
records: 8
factor: none
all eight dropped x0 bits 150..153
learned literals per representative: 134
manifest: tmp/ct07_current_qgap_ledgers_after4835_edge_queue.txt
manifest ledgers: 330
```

The next concrete action is another rerank from
`tmp/ct07_current_qgap_ledgers_after4835_edge_queue.txt`.  If the top layer
continues walking consecutive `x2_low8` values with `x6_low4` in `{0x4,0x6}`,
keep the edge queue going in 8-item batches.  If the pair count stops moving
or the ranker repeats already generalized regions, add a second cheap drop
target before broadening the queue:

```text
preferred cheap add-on: x7 drop 920:4 with completion cap 256 on a few reps
fallback: direct q-gap close for a wider include-seen layer
avoid by default: full hybrid byte-window minimization
```

Update after continuing the edge queue through the 370-ledger manifest:

```text
tmp/ct07_ranked_qgap_pairs_include_seen_after4875_edge_top256.json
loaded ledger files: 370
clauses added: 5257
evaluated pairs: 4096
SAT pairs: 4046
unknown pairs: 50

edge-minimized representatives:
manual probe: 1
queue batches: 4 + 6 + 8 + 8 + 8 + 8 + 8 + 8
total representatives: 59
factor: none
all representatives dropped x0 bits 150..153
learned literals per representative: 134
latest manifest: tmp/ct07_current_qgap_ledgers_after4875_edge_queue.txt
latest manifest ledgers: 370
```

The edge queue is still behaving consistently: every completed representative
has generalized over `x0`, and the top layer keeps moving forward.  The 370-ledger
rerank also reduced SAT-ranked pairs from 4094 to 4046, which is stronger than
the previous batches that only moved the frontier.  The latest top layer is
`x2_low8=0x4a..0x4d` with `x6_low4={0x4,0x6}` at `q_gap_bits=407`.
The next bounded step is:

```text
1. Run another 8-item edge queue from tmp/ct07_ranked_qgap_pairs_include_seen_after4875_edge_top256.json.
2. If the q_gap=407 layer continues moving, keep batching in small 8-item chunks.
3. If the frontier repeats or per-representative time rises sharply, test a small x7-drop batch with cap 256 before more full cubes.
```

Update after two more 8-item edge batches and reranks:

```text
tmp/ct07_edge_min_queue_after4875_top8_rank1
records: 8
factor: none
all eight dropped x0 bits 150..153
learned literals per representative: 134
manifest: tmp/ct07_current_qgap_ledgers_after4883_edge_queue.txt
manifest ledgers: 378

tmp/ct07_ranked_qgap_pairs_include_seen_after4883_edge_top256.json
loaded ledger files: 378
clauses added: 5265
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2

tmp/ct07_edge_min_queue_after4883_top8_rank1
records: 8
factor: none
all eight dropped x0 bits 150..153
learned literals per representative: 134
manifest: tmp/ct07_current_qgap_ledgers_after4891_edge_queue.txt
manifest ledgers: 386

tmp/ct07_ranked_qgap_pairs_include_seen_after4891_edge_top256.json
loaded ledger files: 386
clauses added: 5273
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The edge-minimized evidence is now 75 representatives total: one manual probe,
then queue batches of 4, 6, and nine 8-item batches.  Every completed
representative has generalized over `x0`, no factor/plaintext has been
recovered, and the latest top layer is:

```text
x2_low8=0x52..0x55
x6_low4={0x4,0x6}
q_gap_bits=407
latest manifest: tmp/ct07_current_qgap_ledgers_after4891_edge_queue.txt
latest rank: tmp/ct07_ranked_qgap_pairs_include_seen_after4891_edge_top256.json
```

The temporary 370-ledger drop to `4046` SAT pairs did not persist in the next
two reranks, so do not treat it as stable proof-space collapse.  The useful
signal is weaker but consistent: the generalized clauses keep moving the
frontier forward through consecutive `x2_low8` layers.

Next bounded step:

```text
1. Continue one more 8-item edge queue from tmp/ct07_ranked_qgap_pairs_include_seen_after4891_edge_top256.json.
2. If it again only walks the x2 byte while leaving SAT pairs at 4094, run a small x7-drop probe with completion cap 256 on 2 to 4 top representatives.
3. Keep direct q-gap full-cube closure as a fallback only after a rank layer broadens or repeats.
```

Update after the next x0-only edge batch and x0+x7 probes:

```text
tmp/ct07_edge_min_queue_after4891_top8_rank1
records: 8
factor: none
all eight dropped x0 bits 150..153
learned literals per representative: 134
manifest: tmp/ct07_current_qgap_ledgers_after4899_edge_queue.txt
manifest ledgers: 394

tmp/ct07_ranked_qgap_pairs_include_seen_after4899_edge_top256.json
loaded ledger files: 394
clauses added: 5281
evaluated pairs: 4096
SAT pairs: 4094
unknown pairs: 2
```

The x0-only queue again only moved the `q_gap=407` top layer, this time to
`x2_low8=0x56..0x59`, without reducing the global SAT count.  The planned
x7-drop probe was therefore run.

```text
tmp/ct07_edge_x0_x7_drop_probe_after4899_top2
records: 2
factor: none
both representatives dropped x0 bits 150..153 and x7 bits 920..923
learned literals per representative: 130
q-gap calls per representative: 273
manifest: tmp/ct07_current_qgap_ledgers_after4901_x0_x7_probe.txt
manifest ledgers: 396

tmp/ct07_ranked_qgap_pairs_include_seen_after4901_x0_x7_top256.json
loaded ledger files: 396
clauses added: 5283
evaluated pairs: 4096
SAT pairs: 4089
unknown pairs: 7
```

That was a stable improvement, so four more x0+x7 representatives were closed:

```text
tmp/ct07_edge_x0_x7_drop_after4901_top4
records: 4
factor: none
all four dropped x0 bits 150..153 and x7 bits 920..923
learned literals per representative: 130
q-gap calls per representative: 273
manifest: tmp/ct07_current_qgap_ledgers_after4905_x0_x7.txt
manifest ledgers: 400

tmp/ct07_ranked_qgap_pairs_include_seen_after4905_x0_x7_top256.json
loaded ledger files: 400
clauses added: 5287
evaluated pairs: 4096
SAT pairs: 4063
unknown pairs: 33
```

Current interpretation:

```text
x0-only edge clauses:
  cheap, about 17 q-gap calls per representative
  learned literal count 134
  now mostly move the frontier without stable SAT reduction

x0+x7 edge clauses:
  more expensive, about 273 q-gap calls per representative
  learned literal count 130
  currently reduce the ranked SAT frontier: 4094 -> 4089 -> 4063
```

Next bounded step:

```text
1. Continue from tmp/ct07_ranked_qgap_pairs_include_seen_after4905_x0_x7_top256.json.
2. Use x0+x7 cumulative drop batches, not x0-only, in chunks of 4 first.
3. If the next x0+x7 batch still reduces SAT by a meaningful amount, raise chunk size to 6 or 8.
4. If x0+x7 reduction stalls, test a third small edge/window only after checking q-gap call cost:
   candidate: x6 low nibble 784:4 only if completion cap stays manageable.
```

Update after the after4909/4912 hybrid tests:

```text
New code:
  run_edge_minimization_queue.py now accepts --drop-mode hybrid and forwards
  hybrid cumulative/independent window options to run_fullx1x5_drop_loop.py.

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4912_hybrid_top2.txt
  ledgers: 407
  loaded hard clauses in rerank: 5306
  factor/plaintext: not found

Hybrid cost/effect:
  one ranked representative costs about 1297 q-gap calls
  observed wall time: 451-503 seconds per representative
  each successful hybrid representative adds five 130-literal hard clauses:
    cumulative 150:4+920:4
    independent 265:8
    independent 273:8
    independent 784:8
    independent 792:8

Metric discipline:
  ranked SAT pair count is no longer a monotonic proof metric.
  The ranker can select a different representative cube for a coarse pair after
  hard clauses are added, and timeout/sat transitions can change the count.
  Use hard ledger count, factor/no-factor, q-gap call cost, and top-frontier
  movement as the main operational metrics.
```

Recommended next run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4912_hybrid_top2_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4912_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4916_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4912_hybrid_top2.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Expected runtime is about 30-35 minutes for four ranked representatives at the
current speed.  Stop immediately if a factor appears.  If the top-frontier keeps
advancing but the same coarse layer persists, continue in small chunks of 4-8.
If the runtime per representative rises above about 12 minutes without new
learned variants, reduce hybrid windows to only cumulative `150:4,920:4` plus
one independent byte window at a time.

Update after the after4912/4916 hybrid top4 run:

```text
Latest completed run:
  tmp/ct07_hybrid_queue_after4912_top4
  records: 4
  factor/plaintext: not found
  elapsed: 1922.01s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4916_hybrid_top4.txt
  ledgers: 411

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4916_hybrid_top4_top256.json
  loaded hard clauses: 5326
  evaluated pairs: 4096
  SAT pairs: 4094
  unknown pairs: 2
  top frontier: x2_low8=0x5e, x6_low4=0x6, q_gap=407

Observed cost:
  1297 q-gap calls per representative
  455-510 seconds per representative
```

Recommended next run from the updated frontier:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4916_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4916_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4920_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4916_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Expected runtime is still about 30-35 minutes for four ranked representatives.
If this next batch only advances the same x2/x6 frontier without producing a
factor, keep using small batches but treat it as a hard-pruning sweep, not as a
near-term solve guarantee.

Update after the after4916/4920 hybrid top4 run:

```text
Latest completed run:
  tmp/ct07_hybrid_queue_after4916_top4
  records: 4
  factor/plaintext: not found
  elapsed: 1958.49s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4920_hybrid_top4.txt
  ledgers: 415

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4920_hybrid_top4_top256.json
  loaded hard clauses: 5346
  evaluated pairs: 4096
  SAT pairs: 4094
  unknown pairs: 2
  top frontier: x2_low8=0x60, x6_low4=0x6, q_gap=407

Residual success-only probe:
  tmp/ct07_ranked_after4920_top8_partial_candidates.json
  tmp/ct07_partial_p_after4920_top8_m2_3_t1_2_timeout45.json
  top8 partial-p Coppersmith, unknown blocks [58,69,87]
  m=2..3, t=1..2, 45s timeout per attempt
  factor/plaintext: not found
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4920_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4920_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4924_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4920_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Expected runtime remains about 32-35 minutes for four representatives.  The
hard-pruning sweep is useful for proof accounting, but the last two top4 batches
only moved the same `q_gap=407` frontier by two x2-low8 steps each.  Do not treat
this as a direct solve guarantee; pair it periodically with success-only probes
on top-ranked full cubes or with a stronger residual 3-block lattice attempt.

Update after the after4920/4924 hybrid top4 run:

```text
Latest completed run:
  tmp/ct07_hybrid_queue_after4920_top4
  records: 4
  factor/plaintext: not found
  elapsed: 1959.09s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4924_hybrid_top4.txt
  ledgers: 419

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4924_hybrid_top4_top256.json
  loaded hard clauses: 5366
  evaluated pairs: 4096
  SAT pairs: 4093
  unknown pairs: 3
  top frontier: x2_low8=0x62, x6_low4=0x6, q_gap=407

Success-only residual probes:
  tmp/ct07_partial_p_after4920_top1_m4_t1_timeout240.json
  tmp/ct07_partial_p_after4920_top1_m4_5_t2_3_timeout240.json
  factor/plaintext: not found
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4924_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4924_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4928_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4924_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Expected runtime remains about 32-35 minutes for four representatives.  The
frontier movement is real hard-pruning evidence, but it is still a sweep over a
large branch space.  If several more top4 batches continue to move only the same
`x2_low8/x6_low4` layer without a hit, spend the next engineering block on a
streaming success-only residual lattice runner before widening q-gap batches.

Update after the after4924/4928 and after4928/4932 hybrid top4 runs:

```text
Latest completed runs:
  tmp/ct07_hybrid_queue_after4924_top4
  tmp/ct07_hybrid_queue_after4928_top4
  records: 8 total
  factor/plaintext: not found
  elapsed: 1990.94s + 1878.14s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4932_hybrid_top4.txt
  ledgers: 427

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4932_hybrid_top4_top256.json
  loaded hard clauses: 5406
  evaluated pairs: 4096
  SAT pairs: 4094
  unknown pairs: 2
  top frontier: x6=0x80000000c/0x80000000e, small x2 values, q_gap=407

Success-only residual probes:
  tmp/ct07_partial_p_after4928_top8_m4_t1_timeout180.json
  tmp/ct07_partial_p_after4932_top8_m4_t1_timeout180.json
  factor/plaintext: not found
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4932_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4932_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4936_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4932_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

This next run probes a different `q_gap=407` frontier from the prior low
`x6_low4={0x4,0x6}` sweep, because the current top rows have the high-side
representatives `x6=0x80000000c/0x80000000e`.  Keep it to top4 chunks and rerank
after each chunk; the frontier is moving, but it is still not a solve guarantee.

Update after the after4932/4936 and after4936/4940 hybrid top4 runs:

```text
Latest completed runs:
  tmp/ct07_hybrid_queue_after4932_top4
  tmp/ct07_hybrid_queue_after4936_top4
  records: 8 total
  factor/plaintext: not found
  elapsed: 1850.54s + 1835.77s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4940_hybrid_top4.txt
  ledgers: 435

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4940_hybrid_top4_top256.json
  loaded hard clauses: 5446
  evaluated pairs: 4096
  SAT pairs: 4094
  unknown pairs: 2
  top frontier: x6=0x80000000c/0x80000000e, small x2 values, q_gap=407

Success-only residual probes:
  tmp/ct07_partial_p_after4936_top8_m4_t1_timeout180.json
  tmp/ct07_partial_p_after4940_top8_m4_t1_timeout180.json
  factor/plaintext: not found
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4940_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4940_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4944_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4940_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Expected runtime remains about 30-35 minutes for four representatives on the
current machine.  The hard ledger continues to grow cleanly, but the latest
frontier has cycled between nearby `q_gap=407` layers without a factor hit.
Treat the next top4 chunk as accounting and frontier refinement; if it again
only adds five-clause no-root ledgers per representative, switch the next work
block to a stronger streaming residual 3-block success oracle instead of simply
widening the q-gap queue.

Update after the after4940/4944 hybrid top4 run and the parallel partial-p
runner update:

```text
Latest completed hard-pruning run:
  tmp/ct07_hybrid_queue_after4940_top4
  records: 4
  factor/plaintext: not found
  elapsed: 2220.59s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4944_hybrid_top4.txt
  ledgers: 439

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4944_hybrid_top4_top256.json
  loaded hard clauses: 5466
  evaluated pairs: 4096
  SAT pairs: 4093
  unknown pairs: 3
  top frontier: x6=0x4/0x6, x2 around 0x40068..0x4006e, q_gap=407

Success-only residual probes:
  tmp/ct07_partial_p_after4940_top64_m4_t1_timeout180.json
  tmp/ct07_partial_p_after4944_top128_m4_t1_w8_timeout180.json
  factor/plaintext: not found

Runner update:
  branch_partial_coppersmith.py now supports --workers and streaming --jsonl.
  after4944 top128, m=4,t=1,workers=8 finished in 566.09s.
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4944_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4944_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4948_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4944_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Recommended next success-only run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/branch_partial_coppersmith.py \
  --candidate-json tmp/ct07_ranked_after4944_top128_partial_candidates.json \
  --summary-json tmp/ct07_partial_p_after4944_top128_m4_t2_w8_timeout180.json \
  --jsonl tmp/ct07_partial_p_after4944_top128_m4_t2_w8_timeout180.jsonl \
  --limit 128 \
  --m-values 4 \
  --t-values 2 \
  --attempt-timeout-seconds 180 \
  --workers 8 \
  --json
```

Use the next q-gap top4 for hard accounting, but do not expect it to solve by
itself.  The more useful near-term solve path is to use the parallel partial-p
runner for parameter diversity on the current top-ranked residual 3-block
candidates, then periodically rerank from the growing hard ledger.

Update after the after4948/4952 continuation:

```text
Latest completed hard-pruning runs:
  tmp/ct07_hybrid_queue_after4944_top4
  tmp/ct07_hybrid_queue_after4948_top4
  records: 8 total
  factor/plaintext: not found
  elapsed: 1914.80s + 2408.00s

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4952_hybrid_top4.txt
  ledgers: 447

Latest rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4952_hybrid_top4_top256.json
  loaded hard clauses: 5506
  evaluated pairs: 4096
  SAT pairs: 4093
  unknown pairs: 3
  top frontier: x6=0x20000007 with varied x2 low byte, q_gap=407

Success-only residual probes:
  tmp/ct07_partial_p_after4944_top128_m4_t2_w8_timeout180.json
  tmp/ct07_partial_p_after4944_top128_m4_t3_w8_timeout180.json
  tmp/ct07_partial_p_after4944_top128_m4_t4_w8_timeout180.json
  tmp/ct07_partial_p_after4948_top128_m4_t1-4_w8_timeout180.json
  factor/plaintext: not found
```

Recommended next hard-pruning run:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/run_edge_minimization_queue.py \
  tmp/ct07_ranked_qgap_pairs_include_seen_after4952_hybrid_top4_top256.json \
  --output-dir tmp/ct07_hybrid_queue_after4952_top4 \
  --manifest-output tmp/ct07_current_qgap_ledgers_after4956_hybrid_top4.txt \
  --resume-list tmp/ct07_current_qgap_ledgers_after4952_hybrid_top4.txt \
  --start-index 1 --top 4 --workers 12 \
  --drop-mode hybrid \
  --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
  --q-gap-oracle-timeout-seconds 120 \
  --q-gap-minimize-max-completions 256 \
  --json
```

Recommended next rerank:

```bash
python3 cryptotest/solutions/07_sat_cas_explore/rank_q_gap_assumption_pairs.py \
  --resume-list tmp/ct07_current_qgap_ledgers_after4956_hybrid_top4.txt \
  --output tmp/ct07_ranked_qgap_pairs_include_seen_after4956_hybrid_top4_top256.json \
  --top 256 \
  --q-gap-epsilon 0.04 \
  --q-gap-max-bits 462 \
  --cube-ranges 150:4,265:84,784:46,920:4 \
  --x2-assume-range 265:8 \
  --x6-assume-range 784:4 \
  --x2-values all \
  --x6-values all \
  --include-seen-pairs \
  --max-per-x2-value 2 \
  --max-per-x6-value 16
```

Use one more top4 chunk only as bounded hard accounting.  The last two q-gap
chunks added clean hard clauses, but neither q-gap nor residual partial-p has
shown a hit signal.  If the after4956 rerank again lands on another narrow
`q_gap=407/409` layer with the same five-clause yield, stop widening this queue
and implement a stronger branch scorer before spending another multi-hour run.
The scorer should combine exact product-prefix/carry data, q-gap width, and
residual partial-p model cost rather than ranking mainly by q-gap size and pair
novelty.

Update after the after4952/4956 continuation and scorer change:

```text
Latest completed hard-pruning run:
  tmp/ct07_hybrid_queue_after4952_top4
  records: 4
  factor/plaintext: not found
  elapsed: 2403.19s
  q_gap: 409 for all four representatives
  learned clauses: five 650-literal hard clauses per representative

Latest hard ledger state:
  tmp/ct07_current_qgap_ledgers_after4956_hybrid_top4.txt
  ledgers: 451

Latest legacy rerank:
  tmp/ct07_ranked_qgap_pairs_include_seen_after4956_hybrid_top4_top256.json
  loaded hard clauses: 5526
  SAT pairs: 4088
  unknown pairs: 8
  top frontier: x2 low byte around 0x6a..0x74, x6 low nibble 0x4/0x6, q_gap=407

Balanced scorer:
  rank_q_gap_assumption_pairs.py now supports --prefix-core and --score-mode balanced.
  balanced mode estimates hybrid drop q-gap cost and records residual partial-p cost fields.

Latest balanced rerank:
  tmp/ct07_ranked_qgap_pairs_balanced_after4956_top256.json
  score_mode: balanced
  SAT pairs: 4092
  unknown pairs: 4
  top frontier: q_gap=408, predicted hybrid-drop score_q_gap=415
  residual partial-p blocks: [58, 69, 87], 214 unknown bits

Balanced success-only probes:
  tmp/ct07_balanced_after4956_qgap_direct_top256.json
  tmp/ct07_partial_p_balanced_after4956_top128_m4_t1-4_w8_timeout180.json
  factor/plaintext: not found
```

Do not launch another blind q-gap top4 queue from the legacy frontier.  The
hard ledger is still sound, but three recent chunks show the same pattern:
clean clauses, no hit, and a frontier that simply moves to another narrow
q-gap layer.

Next recommended work:

```text
1. Use balanced rank files as the candidate source, not the legacy q-gap-first rank.
2. Add a second-stage scorer for the residual [58,69,87] unknown blocks.
   The scorer should estimate which cubes are friendlier to the partial-p
   lattice, not just which cubes give smaller q-gap.
3. Try a bounded exact prefix/carry deep-score only on the balanced top layer,
   for example top64 with --prefix-core hensel and a larger check_bits.
   Treat unknown/timeouts as ranking signals only, not hard clauses.
4. Keep direct q-gap and residual partial-p probes as hit-first checks after
   each new scorer, but avoid spending another multi-hour minimization run
   until the scorer changes the candidate distribution materially.
```

Update after the deep-prefix scorer and full after4956 model sweep:

```text
Deep-prefix scorer:
  script: cryptotest/solutions/07_sat_cas_explore/rank_deep_prefix_candidates.py
  top4 at 430/500/600: all unknown, 70.64s
  top16 at 370/390/410: prefix 370 mostly sat, 390+ all unknown, 52.68s
  top1 at 600 with 30000ms timeout: unknown, 37.33s

Residual partial-p follow-ups:
  tmp/ct07_partial_p_deep_prefix_after4956_top16_m3_5_t1-4_w8_timeout120.json
  tmp/ct07_partial_p_deep_prefix_after4956_top8_m5_t5-8_w8_timeout90.json
  factor/plaintext: not found

Full after4956 one-model q-gap direct sweep:
  rank file: tmp/ct07_ranked_qgap_pairs_include_seen_after4956_all_model.json
  SAT model completions: 4090
  direct output: tmp/ct07_qgap_direct_after4956_all_model_stream_30m.json
  status: no factor
  q-gap no_roots: 4090/4090
  elapsed: 1604.36s
```

This changes the next step.  The q-gap oracle itself is still valuable, but the
current ranker only asks Z3 for one full edge completion per
`(x2_low8,x6_low4)` pair.  The full-model sweep shows that those single
representatives do not hit.  It does **not** prove the low-pair space dead,
because many alternate full `x0+x2+x6+x7` completions remain under the same
low pair.

New next recommended work:

```text
1. Implement a diverse edge-completion sampler.
   Input: after4956 ledger, selected low-pair frontier, selected_bits
   = 150:4,265:84,784:46,920:4.
   For each low pair, request K different SAT models by adding a blocking
   clause over the previous full selected_bits cube after each sample.

2. Run streaming q-gap direct on those sampled completions.
   Use the updated run_ranked_q_gap_direct.py with --max-seconds and JSONL
   streaming.  Stop early on a factor; otherwise record no_roots as hit-first
   evidence only, not global proof.

3. Prioritize pair diversity before more hard minimization.
   Recent hard q-gap batches add sound clauses, but they are too local: five
   large clauses per representative and no hit.  Sample breadth across alternate
   full completions is now more informative than another blind top4 queue.

4. Keep deep Hensel, residual partial-p, folded p/q Coron, and CP-SAT as
   finalist probes.  Current runs returned unknown/no-factor and should not
   drive broad search without a new candidate distribution.
```

Update after implementing the diverse edge-completion sampler:

```text
New sampler:
  cryptotest/solutions/07_sat_cas_explore/sample_diverse_edge_completions.py

What it does:
  For each ranked (x2_low8,x6_low4) pair, query the after4956 SAT ledger for
  multiple full selected_bits models over 150:4,265:84,784:46,920:4.
  After each sampled full edge cube, add a local blocking clause so the next
  sample under that low pair is genuinely different.

Completed q-gap direct probes:
  original one-model pass:
    tmp/ct07_qgap_direct_after4956_all_model_stream_30m.json
    4090/4090 no_roots, no factor

  top512 diverse cycle 1:
    tmp/ct07_qgap_direct_diverse_edge_after4956_top512_k4_excluding_source.json
    2048/2048 no_roots, no factor

  top128 diverse cycle 2:
    tmp/ct07_qgap_direct_diverse_edge_after_direct_diverse_top128_k4_cycle2.json
    512/512 no_roots, no factor

  all-pair diverse cycle 3:
    tmp/ct07_qgap_direct_diverse_edge_after_direct_diverse_allpairs_k1_cycle3.json
    4090/4090 no_roots, no factor
```

The sampler confirms that the previous bottleneck was real: one full model per
low pair was too narrow.  But the first broad diverse cycles still did not find
the factor.  Do not keep only increasing `samples-per-pair` blindly; that will
mostly add exact hard no-good clauses for sampled full cubes, not a new search
signal.

Next recommended direction:

```text
1. Add model-distribution control to the sampler.
   Options:
     - randomize selected-bit polarity/order by adding temporary soft XOR-like
       constraints or random assumptions over non-gateway selected bits;
     - alternate min/max objectives over compact edge chunks;
     - sample from different pair orderings, not only q_gap-first rank.

2. Add a second frontier, not just x2_low8/x6_low4.
   Candidate frontiers:
     - x2_low8 + x6_high8
     - x2_mid8 + x6_low4
     - x0/x7 edge nibbles plus x2_low8/x6_low4
   The purpose is to force Z3 into different full edge completions rather than
   small local variants around the same q-gap-dead manifold.

3. Keep loading q-gap direct JSONL as hard exact clauses.
   The direct no_root results are useful as exact sampled no-goods, but broad
   reranking over all 4096 pairs became too slow after adding thousands of
   large clauses.  Prefer targeted sampling with the expanded manifest.

4. Only run residual partial-p/CP-SAT on candidates that survive a changed
   distribution.  Running them on q-gap no_root cubes is wasted, since those
   full edge assignments are already exact dead branches.
```

Update after alternate q-gap frontiers and pwindow420 residual partial-p:

```text
Completed alternate q-gap probes:
  x2_low8 + x6_high4:
    top512 direct: 512/512 no_roots, no factor
    top128 k4 diverse: 512/512 no_roots, no factor

  x2_mid8 + x6_low4:
    top512 direct: 512/512 no_roots, no factor
    top128 k4 random24 diverse: 512/512 no_roots, no factor

Sampler improvement:
  sample_diverse_edge_completions.py now supports random temporary assumptions
  over selected bits.  This is useful for changing model distribution, but the
  first random-diverse q-gap batch still found no factor.

p-window check:
  [362,830) and [420,830) univariate p-window Coppersmith are too slow for a
  broad sweep with the current Sage parameters.  They should not be the main
  hit-first oracle unless a faster lattice configuration is found.

Residual partial-p check:
  [420,830) outside assignments fix x0+x2+x3+x7 and leave only x4+x5+x6,
  i.e. unknown blocks [69,87,46] = 202 bits.
  crypto-attacks partial-p is operational on this shape, but:
    32 candidates with m=2..4,t=1..4: no factor
    128 candidates with m=2..3,t=1..4: no factor
    128 candidates with m=4,t=2..4: no factor
```

Revised next direction:

```text
1. Stop spending broad time on univariate p-window `[362,830)`/`[420,830)`.
   They are informative construction tests, but too slow as a queue.

2. Keep q-gap direct as an exact sampled no-good oracle, but do not simply
   widen the same frontiers.  The tested alternate frontiers still land in
   q-gap-dead manifolds.

3. Use `[420,830)` residual partial-p as the next success oracle, but improve
   candidate distribution before running more lattice attempts:
     - add frontiers that explicitly vary x3 chunks, not only x2/x6;
     - sample x0/x7 edge nibbles more deliberately instead of letting Z3
       choose mostly 0;
     - rank candidates by residual partial-p shape and q-prefix consistency,
       not just q_gap bits.

4. Candidate frontier to try next:
     selected cube: 150:4,265:84,362:58,920:4
     assumptions:
       x2_mid8 or x2_high8
       x3_low8 / x3_mid8 / x3_high8
       x0+x7 nibbles as explicit small frontier
     oracle:
       branch_partial_coppersmith.py with residual [69,87,46],
       first m=2..3,t=1..4, then m=4,t=2..4.

5. Treat all partial-p no-factor results as success-only negative signals.
   They are not hard learned clauses unless independently proven for the exact
   lattice parameter regime.
```

Synthetic x3 frontier result:

```text
selected cube: 150:4,265:84,362:58,920:4
assumptions:
  x2_mid8 = p[305:313)
  x3_low8 = p[362:370)

sample:
  tmp/ct07_pwindow420_edge_samples_synthetic_x2mid8_x3low8_random24_top128_k1.json
  128 SAT models

partial-p:
  m=2..3,t=1..4: 128/128 no factor
  m=4,t=2..4: 128/128 no factor
```

This confirms that explicitly varying x3_low8 is easy with the generic sampler,
but the first synthetic grid/random mix was not enough.  The next useful
iteration should not just increase K; it should change how x0/x7 and x3 are
covered:

```text
1. Build a small explicit x0/x7 frontier.
   The latest pwindow420 samples still overrepresent x0=0 and x7=0.  Enumerate
   the 16x16 edge nibbles for a smaller set of x2/x3 assumptions, then run the
   same residual partial-p oracle.

2. Try x3_high8 and x3_mid8 synthetic frontiers.
   x3_low8 coverage alone did not hit; use the same selected cube but move the
   second assumption range to 382:8 and 412:8.

3. Add a lightweight scorer before lattice:
   For each sampled x0+x2+x3+x7 candidate, derive q_low and product-prefix
   consistency up to 420 bits if feasible.  Prioritize candidates that leave
   the narrowest q interval even though q-gap is not hard without x6.
```

Update after arbitrary assumption frontiers:

```text
Code:
  sample_diverse_edge_completions.py now accepts per-row assumption_ranges.
  make_synthetic_assumption_frontier.py generates synthetic rows like:
    {label,start,width,value}

Important correction:
  For selected cube 150:4,265:84,362:58,920:4, q-gap direct is available.
  Fixing x0+x2+x3+x7 gives:
    q_low_bits = 600
    q_gap_bits = about 230..236
  This is much stronger than residual partial-p and should run first.

Completed explicit x0/x7 q-gap probes:
  existing pwindow420 samples: 128/128 no_roots
  existing synthetic x3low samples: 128/128 no_roots
  x2_mid8=0, x3_low8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0, x3_mid8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0, x3_high8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x40, x3_low8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x40, x3_mid8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x40, x3_high8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x80, x3_low8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x80, x3_mid8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0x80, x3_high8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0xc0, x3_low8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0xc0, x3_mid8 quarters, x0/x7 all: 1024/1024 no_roots
  x2_mid8=0xc0, x3_high8 quarters, x0/x7 all: 1024/1024 no_roots
```

Revised next direction:

```text
1. Promote pwindow420 q-gap direct to the primary hit oracle.
   The selected cube is:
     150:4,265:84,362:58,920:4
   This fixes q_low=600 and gives q_gap around 230..236.

2. The first explicit edge pass over x2_mid8 coarse quarters is complete.
   Completed coarse values:
     x2_mid8 in {0x00,0x40,0x80,0xc0}
   Covered for each:
     x0=all, x7=all
     x3_low8/x3_mid8/x3_high8 quarter values in {0x00,0x40,0x80,0xc0}
   Result:
     all sampled candidates were hard q-gap no-roots.

3. The explicit pwindow420 q-gap direct JSONLs have been put into a separate
   ledger manifest:
     tmp/ct07_pwindow420_explicit_qgap_ledgers_20260607.txt
   Loader smoke test:
     12544 clauses added, 0 duplicates, 0 parse/file errors.

4. The selected-cube scorer is implemented:
     cryptotest/solutions/07_sat_cas_explore/score_selected_cube_samples.py
   First free scored batch:
     random32, timeout 1000ms: unknown before first sample
     random64, timeout 10000ms: 256 sat samples
     scored q-gap direct: 256/256 no_roots, no factor
   New scored-batch ledger manifest:
     tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt

5. The scored free batch loop is implemented:
     cryptotest/solutions/07_sat_cas_explore/run_pwindow420_scored_batches.py
   Smoke run:
     tmp/ct07_pwindow420_scored_loop_20260607_iter2
     iteration 1: 256/256 q-gap no_roots
     iteration 2: 256/256 q-gap no_roots
     no factor
   Follow-up batch512 run:
     tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter1
     iteration 1: 512/512 q-gap no_roots
     no factor
   Follow-up batch512 iter2b run:
     tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter2b
     iteration 1: 512/512 q-gap no_roots
     iteration 2: 512/512 q-gap no_roots
     no factor
   Follow-up batch512 iter2c run:
     tmp/ct07_pwindow420_scored_loop_20260607_batch512_iter2c
     iteration 1: 512/512 q-gap no_roots
     iteration 2: 512/512 q-gap no_roots
     no factor
   Parallel sampling update:
     run_pwindow420_scored_batches.py now supports --sample-shards and
     --sample-workers.
     smoke tmp/ct07_pwindow420_parallel_sampling_smoke_light_20260607:
       8/8 q-gap no_roots, no factor
     batch512 parallel4:
       tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter1
       samples: 4 shards x 128, merged 512 unique samples
       q-gap direct: 512/512 no_roots, no factor
       elapsed: 471.88s
     parallel8 check:
       tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel8_iter1
       stopped before sample output after about 3.5 minutes
       conclusion: 8 shards is worse for the current sampler/ledger load
     batch512 parallel4 iter2:
       tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter2
       samples: 4 shards x 128, merged 512 unique samples
       q-gap direct: 512/512 no_roots, no factor
       elapsed: 549.28s
     batch512 parallel4 iter3-4:
       tmp/ct07_pwindow420_scored_loop_20260607_batch512_parallel4_iter3_4
       iteration 1: 512/512 q-gap no_roots
       iteration 2: 512/512 q-gap no_roots
       no factor
       elapsed: 1104.22s
   Diversified scorer update:
     run_pwindow420_scored_batches.py now forwards scorer caps:
       --score-max-per-x0
       --score-max-per-x7
       --score-max-per-x2mid
       --score-max-per-x3low
       --score-max-per-x3mid
       --score-max-per-x3high
     tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap64_batch768
       batch size: 768
       score caps: x0 <= 64, x7 <= 64
       retained after caps: 403
       q-gap direct: 403/403 no_roots, no factor
       q_gap distribution: 230:69, 231:134, 232:127, 233:20, 234:49, 236:4
       elapsed: 536.54s
     tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap64_batch1024
       batch size: 1024
       score caps: x0 <= 64, x7 <= 64
       retained after caps: 434
       q-gap direct: 434/434 no_roots, no factor
       q_gap distribution: 230:72, 231:151, 232:153, 233:18, 234:40
       elapsed: 597.43s
       note: only +31 retained vs batch768, so batch768 is more efficient
     tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_batch1024
       batch size: 1024
       score caps: x0 <= 96, x7 <= 96
       retained after caps: 585
       q-gap direct: 585/585 no_roots, no factor
       q_gap distribution: 230:105, 231:191, 232:190, 233:27, 234:69, 236:3
       all retained candidates hard eligible, roots returned: 0
       elapsed: 749.45s
       note: +151 retained vs cap64 batch1024, but x0/x7 again hit the cap
     tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_batch1024_seed20262600
       batch size: 1024
       score caps: x0 <= 96, x7 <= 96
       retained after caps: 586
       q-gap direct: 586/586 no_roots, no factor
       q_gap distribution: 230:101, 231:201, 232:184, 233:23, 234:71, 236:6
       all retained candidates hard eligible, roots returned: 0
       elapsed: 713.92s
       note: cap96 retained yield is stable across two seeds
     cap probe on seed20262600 samples:
       x0/x7 cap96 only retained 586
       x0/x7 cap96 + x2/x3 cap80 retained 557
       x0/x7 cap96 + x2/x3 cap64 retained 518
       x0/x7 cap80 only retained 541
     tmp/ct07_pwindow420_scored_loop_20260607_diverse_x0x7cap96_x2x3cap80_batch1024_seed20263600
       batch size: 1024
       score caps: x0 <= 96, x7 <= 96, x2mid/x3low/x3mid/x3high <= 80
       retained after caps: 552
       q-gap direct: 552/552 no_roots, no factor
       q_gap distribution: 230:102, 231:185, 232:178, 233:23, 234:59, 236:5
       all retained candidates hard eligible, roots returned: 0
       elapsed: 723.93s
       note: x2/x3 cap80 has small retained-yield cost and improves diversity
   The scored-batch ledger manifest now includes 40 q-gap JSONLs.  Across
   those files it has 12112 cube records and 12232 loadable hard clauses when
   learned-clause variants are counted separately.  No factor/plaintext has
   been recovered.

6. Next bounded step:
   Do not simply continue unminimized loop batches as the default.  The latest
   direct coverage is 7680 candidates, all hard no_roots, no factor, and the
   selector is mostly proving local full cubes.  The next better step is a
   pwindow420 hybrid q-gap minimization loop that prefers grouped cumulative
   drops over more single-nibble repetitions:
     run_fullx1x5_drop_loop.py
     cube_ranges = 150:4,265:84,362:58,920:4
     drop_mode = hybrid
     workers = 8
     q_gap_epsilon = 0.04
     q_gap_max_bits = 462
     q_gap_oracle_timeout_seconds = 120
     q_gap_minimize_max_completions = 256
   Use the current scorer manifest:
     tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
   Also pass:
     --manifest-output tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
   so long chunks are restartable without manual manifest edits.
   Proven useful cumulative groups:
     150:4 + 920:4
     265:4 + 269:4
     273:4 + 277:4
     281:4 + 285:4
     362:4 + 366:4
     370:4 + 374:4
     378:4 + 382:4
   All planned two-nibble x2/x3 grouped drops have now succeeded on at least
   one representative each.  The first 12-bit union proof also succeeded:
     265:4 + 269:4 + 273:4 -> proved over 4096 / 4096 completions
   The mirrored x3 12-bit union proof also succeeded:
     362:4 + 366:4 + 370:4 -> proved over 4096 / 4096 completions
   A post-union SAT selection check loaded all 31 previous ledgers and still
   selected the all-zero pwindow420 representative:
     150:4=0, 265:84=0, 362:58=0, 920:4=0
   A direct q-gap check on that representative produced a 150-literal hard
   no-root clause with no factor and was appended to the manifest.  This is a
   useful clause, but it also shows that proof compression alone is not moving
   selection fast enough.

   Three diversified hit-first q-gap batches were then run:
     cap96/cap80 seed20260680: 557 / 557 no_roots, no factor
     cap96/cap80 seed20261680: 569 / 569 no_roots, no factor
     cap64/cap64 seed20262680: 248 / 248 no_roots, no factor
     cap96/cap80 seed20263680: 560 / 560 no_roots, no factor
     cap96/cap80 seed20264680: 542 / 542 no_roots, no factor
     cap96/cap80 seed20265680_t5000: 584 / 584 no_roots, no factor
     cap96/cap80 seed20266680_t5000 iteration 1: 569 / 569 no_roots, no factor
     cap96/cap80 seed20266680_t5000 iteration 2: 532 / 532 no_roots, no factor
   The two cap96/cap80 batches had zero duplicate full pwindow420 cubes between
   the first two; after seven cap96/cap80 batches, the union is still 3913
   unique full pwindow420 cubes with zero duplicates.  Cap64/cap64 cut
   throughput too aggressively.  Current default for hit-first coverage should
   be cap96/cap80 with fresh seeds.  As the learned set grows, sampling may need
   `solver_timeout_ms=5000` and `random_assumption_retries=64`; seed20265680
   was empty at 1000ms but worked at 5000ms, and the two-iteration t5000 run
   completed cleanly.
   Use `run_q_gap_union_shards.py` for 12-bit or larger drops so progress is
   shard-resumable.  The completed x2 proof took about 35.3 minutes total, and
   the completed x3 proof took about 37.2 minutes.  Stop immediately on
   factor/plaintext.

7. Fallback direct diversification step:
   Use batch_size around 768 with x0/x7 caps when the uncapped scorer keeps
   over-selecting x0=0 or x7=0.  Cap64 keeps diversity tight but wastes many
   samples at batch1024; cap96 retains more useful candidates at the same
   sample size and should be the next default when prioritizing throughput.
   Do not add x2/x3 byte caps yet; probes kept too few rows for the extra
   sample cost.  If using cap64, prefer batch768.  If using cap96, batch1024
   is acceptable but inspect selector saturation after each run.  Two cap96
   seeds retained 585 and 586 candidates from 1024 samples, so cap96 batch1024
   is the current best bounded throughput setting.  For better diversity with
   only modest yield loss, use x0/x7 cap96 plus x2mid/x3low/x3mid/x3high cap80.
```

8. Latest minimization signal:
   tmp/ct07_pwindow420_minprobe_x0x7_x2x3nib_seed20260607/iteration_0001.jsonl
   closed one pwindow420 representative with q_gap_bits=232 and learned five
   hard variants:
     cumulative drop 150:4 + 920:4 -> 142 literals
     independent drop 265:4 -> 146 literals
     independent drop 269:4 -> 146 literals
     independent drop 362:4 -> 146 literals
     independent drop 366:4 -> 146 literals
   tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more_seed20260607/iteration_0001.jsonl
   closed the next pwindow420 representative with q_gap_bits=232 and learned
   nine hard variants:
     cumulative drop 150:4 + 920:4 -> 142 literals
     independent drop 265:4 -> 146 literals
     independent drop 269:4 -> 146 literals
     independent drop 273:4 -> 146 literals
     independent drop 277:4 -> 146 literals
     independent drop 362:4 -> 146 literals
     independent drop 366:4 -> 146 literals
     independent drop 370:4 -> 146 literals
     independent drop 374:4 -> 146 literals
   tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more2_seed20260607/iteration_0001.jsonl
   closed the third pwindow420 representative with q_gap_bits=232 and learned
   the same nine hard variants.
   tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more3_seed20260608/iteration_0001.jsonl
   closed the fourth pwindow420 representative with q_gap_bits=232 and learned
   the same nine hard variants.
   tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_more4_seed20260608/iteration_0001.jsonl
   closed the fifth pwindow420 representative with q_gap_bits=232 and learned
   the same nine hard variants.
   tmp/ct07_pwindow420_minloop_x0x7_x2x3nib_expanded_seed20260608/iteration_0001.jsonl
   closed the sixth representative with q_gap_bits=232 and learned thirteen
   hard variants:
     cumulative drop 150:4 + 920:4 -> 142 literals
     independent drops 265:4,269:4,273:4,277:4,281:4,285:4 -> 146 literals each
     independent drops 362:4,366:4,370:4,374:4,378:4,382:4 -> 146 literals each
   tmp/ct07_pwindow420_minloop_x2low8_cumulative_seed20260608/iteration_0001.jsonl
   closed the seventh representative with q_gap_bits=232 and proved the
   cumulative x2 low-8 drop:
     cumulative drop 265:4 + 269:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_minloop_x3low8_cumulative_seed20260608/iteration_0001.jsonl
   closed the eighth representative with q_gap_bits=232 and proved the
   cumulative x3 low-8 drop:
     cumulative drop 362:4 + 366:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_minloop_x2mid8_cumulative_seed20260608/iteration_0001.jsonl
   closed the ninth representative with q_gap_bits=232 and proved the next x2
   two-nibble cumulative drop:
     cumulative drop 273:4 + 277:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_minloop_x3mid8_cumulative_seed20260608/iteration_0001.jsonl
   closed the tenth representative with q_gap_bits=232 and proved the next x3
   two-nibble cumulative drop:
     cumulative drop 370:4 + 374:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_minloop_x2high8_cumulative_seed20260608/iteration_0001.jsonl
   closed the eleventh representative with q_gap_bits=232 and proved the final
   planned x2 two-nibble cumulative drop:
     cumulative drop 281:4 + 285:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_minloop_x3high8_cumulative_seed20260608/iteration_0001.jsonl
   closed the twelfth representative with q_gap_bits=232 and proved the final
   planned x3 two-nibble cumulative drop:
     cumulative drop 378:4 + 382:4 -> 142 literals
     twelve independent 4-bit drops -> 146 literals each
   tmp/ct07_pwindow420_union12_x2low12_seed20260608/learned_clause.jsonl
   proves a 12-bit x2 union drop for the selected pwindow420 cube:
     drop 265:4 + 269:4 + 273:4
     4096 / 4096 completions hard no_roots
     learned clause literal count 138, dropped bits 265..276
   tmp/ct07_pwindow420_union12_x3low12_seed20260608/learned_clause.jsonl
   proves a 12-bit x3 union drop for the same selected pwindow420 cube:
     drop 362:4 + 366:4 + 370:4
     4096 / 4096 completions hard no_roots
     learned clause literal count 138, dropped bits 362..373
   Total pwindow420 minimization evidence is now twelve representatives, two
   completed 12-bit union proofs, one post-union direct q-gap closure, and
   eight diversified direct q-gap batches.  The current manifest has 12232
   loadable hard clauses and no factor/plaintext yet.  The next improvement
   should continue diversified cap96/cap80 hit-first direct q-gap sampling with
   fresh seeds, or change the cube-selection heuristic so SAT does not keep
   revisiting the same local basin.  More proof compression on the same basin
   is lower priority.
   `run_fullx1x5_drop_loop.py --manifest-output` should be used for future
   pwindow420 minimization chunks so each completed iteration is appended to
   the active manifest automatically.  The option now appends only newly
   produced iteration JSONLs; it must not rewrite the focused manifest with the
   full combined resume-ledger list.

9. Latest pwindow420 direct-closure status:
   The active focused manifest is now:
     tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
   It contains 56 JSONL paths, 12128 cube records, and 12248 loadable hard
   clauses when learned-clause variants are counted.  No factor/plaintext has
   been recovered.

   The SAT-selected direct closure after the 40-ledger manifest closed eight
   q-gap hard no-root cubes in
   tmp/ct07_pwindow420_satselected_direct_after_40ledgers_seed20260608.
   A guarded diagonal run then forced:
     920:4 = 1..8
     362:4 = 1..8
     265:8 = 1..8
   and closed eight more hard no-root cubes in
   tmp/ct07_pwindow420_guarded_x7_x3_x2low_diag_after_48ledgers_seed20260608.
   Those guarded cubes had q_gap_bits 230..234 and all were hard-eligible
   no_roots.  They did not produce a factor.

   The important negative signal is that default SAT selection still returns
   to the local basin after these closures:
     x3 = 0
     x7 = 0
     x2 in small low-byte / power-like values
   More unranked direct q-gap closure on this basin is now low priority.

   Ranker diagnostics:
     tmp/ct07_pwindow420_rank_x3low4_x7_after56.json
       233 of 256 x3_low4/x7 pairs were already seen
       the remaining 23 returned unknown under the 100ms solver timeout
       no new sat-ranked pair was produced
     x2_low8/x7 all-pairs ranking over 4096 pairs was stopped after about
       6 minutes because it was too CPU-heavy at the current clause count

   Next useful work:
     build a cheaper cached/subsampled pwindow420 ranker, or change the SAT
     selector objective so it favors branch novelty and product-prefix pressure
     rather than the default low-valued model.  Manual forced cycles should be
     used only as bounded coverage probes.

10. Projection novelty sampler:
   `build_projection_frontier.py` is now the cheapest working replacement for
   the stopped all-pairs pwindow420 ranker.  It does not call Z3.  It reads the
   active manifest, counts compact projection keys, and emits a rank JSON with
   underseen assumptions for `sample_diverse_edge_completions.py`.

   Default projection:
     150:4   x0
     265:8   x2low8
     362:4   x3low4
     920:4   x7

   Two novelty batches have completed:
     seed20260608: 64 / 64 SAT samples, then 64 / 64 q-gap hard no_roots
     seed20260609: 128 / 128 SAT samples, then 128 / 128 q-gap hard no_roots
   No factor/plaintext was recovered.  The second run updated the active
   manifest to 58 JSONLs, 12320 cube records, and 12440 loadable hard clauses.

   This sampler is fast enough for repeated bounded hit-first coverage:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/build_projection_frontier.py \
     --manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --output tmp/ct07_pwindow420_projection_frontier_next.json \
     --top 128 --candidate-pool 16384 --max-seen-count 0 \
     --prefer-unseen --seed <fresh-seed> --json

   python3 cryptotest/solutions/07_sat_cas_explore/sample_diverse_edge_completions.py \
     tmp/ct07_pwindow420_projection_frontier_next.json \
     --output tmp/ct07_pwindow420_projection_frontier_next_samples.json \
     --jsonl-output tmp/ct07_pwindow420_projection_frontier_next_samples.jsonl \
     --top-pairs 64 --samples-per-pair 2 --max-total 128 \
     --cube-ranges 150:4,265:84,362:58,920:4 \
     --solver-timeout-ms 5000 \
     --random-assumption-bits 64 --random-assumption-retries 16 \
     --random-seed <fresh-seed> \
     --resume-list tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --json

   python3 cryptotest/solutions/07_sat_cas_explore/run_ranked_q_gap_direct.py \
     tmp/ct07_pwindow420_projection_frontier_next_samples.json \
     --output tmp/ct07_pwindow420_projection_frontier_next_qgap.json \
     --jsonl-output tmp/ct07_pwindow420_projection_frontier_next_qgap.jsonl \
     --top 128 --workers 8 \
     --q-gap-epsilon 0.04 --q-gap-max-bits 462 \
     --oracle-timeout-seconds 120 --json
   ```

   Append only successful q-gap JSONLs to the active manifest.  Rebuild the
   frontier after each appended batch so new projections remain unseen or
   underseen.  This remains hit-first coverage, not a complete solve strategy:
   default SAT diagnostics still return to `x3=0, x7=0` after novelty batches,
   so any default-SAT direct closure should stay lower priority unless it adds
   stronger minimization.

11. Projection novelty batch runner:
   `run_projection_frontier_batches.py` now automates the three-command
   projection novelty flow and appends each successful q-gap JSONL to the
   active manifest.  It also has per-stage timeouts; keep those enabled because
   some unseen projections make the Z3 sampling stage expensive.

   The current stable bounded command shape is:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_projection_frontier_batches.py \
     --iterations 1 \
     --output-dir tmp/ct07_projection_frontier_runner_next \
     --manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --seed-base <fresh-seed> \
     --frontier-top 160 \
     --candidate-pool 24576 \
     --top-pairs 64 \
     --samples-per-pair 2 \
     --max-total 128 \
     --workers 8 \
     --solver-timeout-ms 1000 \
     --random-assumption-bits 32 \
     --random-assumption-retries 8 \
     --frontier-timeout-seconds 60 \
     --sample-timeout-seconds 900 \
     --qgap-timeout-seconds 900 \
     --q-gap-epsilon 0.04 \
     --q-gap-max-bits 462 \
     --oracle-timeout-seconds 120 \
     --json
   ```

   Latest runner results:
     smoke2 seed20260612: 32 / 32 SAT, 32 / 32 q-gap hard no_roots
     batch128 seed20260620: 128 / 128 SAT, 128 / 128 q-gap hard no_roots
   No factor/plaintext was recovered.  The active focused manifest is now 60
   JSONLs after those two runner-added q-gap ledgers.  A previous smoke without
   stage timeouts was stopped manually during sampling after a child process
   ran for more than 145 seconds; do not use the runner without timeouts.

   This runner is now the preferred bounded hit-first coverage path.  It is
   still not an exhaustion proof.  If several more batches produce only
   no_roots, the next real improvement should be stronger projection selection
   or clause minimization over projection-frontier samples, not just a larger
   random pool.

12. full-x1/full-x5 projection novelty line:
   Deep product-prefix scoring on pwindow420 samples is not currently useful.
   It is trivially SAT through 624 bits and becomes `unknown` under short
   timeouts at 628 bits or higher.  Do not spend more runtime on this scoring
   layer unless the prefix model is replaced with a stronger exact carry
   encoding.

   The better near-term hit-first line is the lower-fixed-bit q-gap shape:

   ```text
   cube ranges:
     150:4,265:84,784:46,920:4
   projection:
     150:4   x0
     265:8   x2low8
     784:8   x6low8
     920:4   x7
   ```

   It fixes 138 hidden bits, compared with pwindow420's 150 hidden bits.  The
   q-gap is larger, around 407-416 bits, but still hard-eligible with
   `epsilon=0.04`.

   Latest results:

   ```text
   tmp/ct07_fullx1x5_projection_runner_smoke_seed20260630
     32 / 32 SAT samples
     32 / 32 q-gap hard no_roots
     factor not recovered

   tmp/ct07_fullx1x5_projection_runner_batch256_seed20260631
     256 / 256 SAT samples
     256 / 256 q-gap hard no_roots
     elapsed 115.84s
     factor not recovered
   ```

   Active full-x1/full-x5 manifest:

   ```text
   tmp/ct07_fullx1x5_resume_all_jsonl.txt
     83 JSONLs
     369 cube records
     619 loadable hard clauses
     factors: 0
   ```

   Recommended bounded continuation:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_projection_frontier_batches.py \
     --iterations 1 \
     --output-dir tmp/ct07_fullx1x5_projection_runner_next \
     --manifest tmp/ct07_fullx1x5_resume_all_jsonl.txt \
     --seed-base <fresh-seed> \
     --cube-ranges 150:4,265:84,784:46,920:4 \
     --projection 150:4:x0 \
     --projection 265:8:x2low8 \
     --projection 784:8:x6low8 \
     --projection 920:4:x7 \
     --frontier-top 320 \
     --candidate-pool 32768 \
     --top-pairs 128 \
     --samples-per-pair 2 \
     --max-total 256 \
     --workers 8 \
     --solver-timeout-ms 1000 \
     --random-assumption-bits 32 \
     --random-assumption-retries 8 \
     --frontier-timeout-seconds 60 \
     --sample-timeout-seconds 900 \
     --qgap-timeout-seconds 1800 \
     --q-gap-epsilon 0.04 \
     --q-gap-max-bits 462 \
     --oracle-timeout-seconds 120 \
     --json
   ```

   This line should be alternated with pwindow420 novelty batches.  If both
   continue returning only no_roots, prioritize a projection-frontier
   minimization experiment over simply increasing batch size.

13. full-x1/full-x5 projection minimization:
   A first minimization probe on one full-x1/full-x5 projection sample passed.

   ```text
   sample:
     150:4   = 15
     265:84  = 377835688817235066421405
     784:46  = 32770
     920:4   = 0
   output:
     tmp/ct07_fullx1x5_projection_minimize_sample1_seed20260631.jsonl
   base q_gap_bits:
     409
   q-gap calls:
     785
   result:
     no factor
     cumulative 150:4 + 920:4 drop passed
     independent 784:8 drop passed
     independent 792:8 drop passed
   ```

   Learned variants:
     cumulative x0+x7: 130 literals, 8 dropped bits
     independent 784:8: 130 literals, 8 dropped bits
     independent 792:8: 130 literals, 8 dropped bits

   The full-x1/full-x5 manifest is now:

   ```text
   tmp/ct07_fullx1x5_resume_all_jsonl.txt
     84 JSONLs
     370 cube records
     622 loadable hard clauses
     factors: 0
   ```

   This proves that projection-frontier samples can be generalized.  It is not
   cheap enough to run on every direct sample: one representative with three
   variants required 785 q-gap calls.  Use minimization selectively:

   ```text
   1. Run one or more full-x1/full-x5 projection novelty direct batches.
   2. Cluster the no-root samples by low projection or q_gap_bits.
   3. Pick one representative from each cluster.
   4. Run cumulative x0+x7 and independent x6-byte drops only on those reps.
   5. Append successful minimization ledgers to the full-x1/full-x5 manifest.
   ```

   A useful next script would automate representative selection from
   `run_projection_frontier_batches.py` outputs and emit the corresponding
   `semi_programmatic_sat.py` minimization commands.

14. no-x7 low600 q-gap line:
   A better hard q-gap shape was found after enumerating full-block
   combinations:

   ```text
   cube ranges:
     150:4,265:84,362:58
   hidden bits fixed:
     146
   q known state:
     q_low_bits = 600
     q_prefix_start = 924
     q_gap_bits = 324
   ```

   This leaves `x7` free and therefore blocks all 16 `x7` completions whenever
   the `x0+x2+x3` branch is q-gap no-root.  It is a better hard branch killer
   than pwindow420's `150:4,265:84,362:58,920:4` cube, which fixes 150 hidden
   bits and only gets a slightly smaller q-gap.

   Latest results:

   ```text
   tmp/ct07_nox7_low600_projection_runner_smoke_seed20260640
     64 / 64 SAT samples
     64 / 64 q-gap hard no_roots
     q_gap_bits = 324
     factor not recovered

   tmp/ct07_nox7_low600_projection_runner_batch256_seed20260641
     256 / 256 SAT samples
     256 / 256 q-gap hard no_roots
     q_gap_bits = 324
     elapsed 254.38s
     factor not recovered
   ```

   Active focused manifest:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     64 JSONLs
     12865 cube records
     12985 loadable hard clauses
     factors: 0
   ```

   Recommended bounded continuation:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_projection_frontier_batches.py \
     --iterations 1 \
     --output-dir tmp/ct07_nox7_low600_projection_runner_next \
     --manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --seed-base <fresh-seed> \
     --cube-ranges 150:4,265:84,362:58 \
     --projection 150:4:x0 \
     --projection 265:8:x2low8 \
     --projection 362:4:x3low4 \
     --frontier-top 320 \
     --candidate-pool 32768 \
     --top-pairs 128 \
     --samples-per-pair 2 \
     --max-total 256 \
     --workers 8 \
     --solver-timeout-ms 1000 \
     --random-assumption-bits 32 \
     --random-assumption-retries 8 \
     --frontier-timeout-seconds 60 \
     --sample-timeout-seconds 900 \
     --qgap-timeout-seconds 1200 \
     --q-gap-epsilon 0.04 \
     --q-gap-max-bits 462 \
     --oracle-timeout-seconds 120 \
     --json
   ```

   Use this as the main hard q-gap batch line.  It is still a coverage search,
   not an exhaustion proof over the 146-bit branch space.

15. no-x7 low600 minimization:
   One small minimization probe succeeded:

   ```text
   output:
     tmp/ct07_nox7_low600_qgap_drop_x0only_seed20260644
   drop:
     150:4
   q-gap calls:
     17
   result:
     16 / 16 no_roots
     one 142-literal learned variant
     factor not recovered
   ```

   A broader independent byte-drop probe over `265:8`, `273:8`, `362:8`, and
   `370:8` was stopped after about ten minutes and produced no usable clause.
   The expensive part is not only q-gap; loading about 1.9M learned literals
   into the SAT process now dominates short minimization probes.

   Current rule:

   ```text
   safe to run selectively:
     x0-only 150:4 drop

   avoid for now:
     multi-byte no-x7 low600 drop probes
     cumulative windows that exceed 16 or 256 completions
   ```

   If minimization is revisited, add a runner-level per-window timeout and
   representative selection first.  Do not put broad byte minimization in the
   default exploration loop.

16. x0+x5+x6+x7 comparison line:
   A smoke run checked the alternative full-block shape:

   ```text
   cube ranges:
     150:4,682:87,784:46,920:4
   hidden bits fixed:
     141
   q_gap_bits:
     404..410 in the smoke sample
   output:
     tmp/ct07_x0x5x6x7_projection_runner_smoke_seed20260642
   result:
     64 / 64 SAT
     64 / 64 hard no_roots
     factor not recovered
   ```

   Keep this as a secondary comparison path.  It fixes fewer bits than
   no-x7 low600 but has a larger q-gap and does not currently produce a
   stronger learned-clause shape.  Run it only when the no-x7 queue appears
   saturated or when a high-side ranking signal becomes available.

17. representative no-x7 minimization automation:
   Added a dedicated runner:

   ```text
   cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py
   ```

   This runner reads q-gap JSONL ledgers, picks representative cube records,
   forces their exact `cube_ranges` with `--cube-assume-p-range`, and runs
   q-gap minimization directly through `semi_programmatic_sat.py`.  It does not
   load previous learned clauses, because the source full-clause would usually
   block the exact representative cube before minimization can run.

   Verified results:

   ```text
   tmp/ct07_nox7_low600_rep_min_x0_seed20260645
     4 representatives
     4 / 4 x0-drop minimized
     35.88s
     factor not recovered

   tmp/ct07_nox7_low600_rep_min_x0_seed20260646
     12 representatives
     12 / 12 x0-drop minimized
     183.42s
     factor not recovered

   tmp/ct07_nox7_low600_rep_min_x0_seed20260648
     8 representatives
     8 / 8 x0-drop minimized
     84.69s
     factor not recovered
   ```

   Each successful representative produces one 142-literal variant that drops
   the full `150:4` block.  This is much cheaper than the earlier x0-only probe
   that loaded all prior learned clauses.

   Recommended routine:

   ```text
   1. Run one no-x7 low600 direct projection batch.
   2. Run representative x0-drop minimization over 8 to 32 unique projection
      representatives from that batch.
   3. Append the minimization JSONLs to
      tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt.
   4. Repeat with a fresh seed.
   ```

   Command template:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py \
     --source-jsonl <batch-output>/iteration_0001_qgap.jsonl \
     --output-dir tmp/ct07_nox7_low600_rep_min_x0_next \
     --append-manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --top 16 \
     --projection 150:4:x0 \
     --projection 265:8:x2low8 \
     --projection 362:4:x3low4 \
     --drop-window 150:4 \
     --workers 8 \
     --item-timeout-seconds 240 \
     --json
   ```

   Current focused manifest after the latest direct batch and representative
   minimization runs:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     122 JSONLs
     13433 cube records
     13553 loadable hard clauses
     189 variant clauses across 69 variant records
     factors: 0
   ```

   Do not treat this as exhaustive coverage.  It is a stronger accounting path
   for the no-x7 low600 line, but the remaining branch space is still huge.

   Latest continuation:

   ```text
   tmp/ct07_nox7_low600_rep_min_x0_seed20260649
     24 representatives
     24 / 24 x0-drop minimized
     318.64s
     factor not recovered

   tmp/ct07_nox7_low600_projection_runner_batch256_seed20260650
     256 / 256 SAT
     256 / 256 q-gap hard no_roots
     270.83s
     factor not recovered

   tmp/ct07_nox7_low600_rep_min_x0_seed20260651
     8 representatives
     8 / 8 x0-drop minimized
     76.68s
     factor not recovered
   ```

   Operational note: the routine is stable, but it remains a broad coverage
   search.  If several more cycles produce no factor, improve representative
   selection or add a second cheap drop dimension before simply increasing
   direct batch count.

18. variant-aware projection frontier:
   `build_projection_frontier.py` now treats dropped bits in
   `learned_clause_variants` as wildcards when counting seen projection keys.
   This is required for correct novelty accounting after x0-drop
   minimization: a 142-literal no-x7 variant has dropped all four x0 bits, so
   it should count as covering all 16 x0 projection values for its fixed
   `x2+x3` projection.

   Verification run:

   ```text
   tmp/ct07_variant_aware_frontier_check_seed20260652.json
     unique_seen_projection_keys = 6796
     counted_projection_key_instances = 15559
     variant_projection_key_instances = 2261
     variant_records = 69
     fallback_exact = 0
   ```

   First variant-aware direct batch:

   ```text
   tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260652
     256 / 256 SAT
     256 / 256 q-gap hard no_roots
     251.80s
     factor not recovered
   ```

   Representative minimization on that batch:

   ```text
   tmp/ct07_nox7_low600_variant_frontier_rep_min_x0_seed20260653
     8 representatives
     8 / 8 x0-drop minimized
     94.36s
     factor not recovered
   ```

   Current focused manifest:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     131 JSONLs
     13697 cube records
     13817 loadable hard clauses
     197 variant clauses across 77 variant records
     factors: 0
   ```

   Keep this variant-aware frontier behavior enabled for all future no-x7
   batches.  The next useful improvement is likely a second cheap
   representative drop dimension, not reverting to exact-cube projection
   counting.

19. cumulative second-drop probes:
   `run_cube_representative_minimization.py` now supports explicit drop modes:

   ```text
   independent
   cumulative
   hybrid
   ```

   Cumulative-only mode is useful because `semi_programmatic_sat.py` can test
   a growing union of dropped windows and emit one stronger generalized clause.

   Verified probes:

   ```text
   tmp/ct07_nox7_cumulative_x0_x2low4_seed20260654
     windows: 150:4, 265:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered

   tmp/ct07_nox7_cumulative_x0_x3low4_seed20260655
     windows: 150:4, 362:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered
   ```

   Current focused manifest:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     135 JSONLs
     13701 cube records
     13821 loadable hard clauses
     201 variant clauses across 81 variant records
     factors: 0
   ```

   Recommended use:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_cube_representative_minimization.py \
     --source-jsonl <fresh-batch>/iteration_0001_qgap.jsonl \
     --output-dir tmp/ct07_nox7_cumulative_x0_x2low4_next \
     --append-manifest tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt \
     --top 2 \
     --projection 150:4:x0 \
     --projection 265:8:x2low8 \
     --projection 362:4:x3low4 \
     --drop-mode cumulative \
     --cumulative-drop-window 150:4 \
     --cumulative-drop-window 265:4 \
     --q-gap-minimize-max-completions 256 \
     --workers 8 \
     --item-timeout-seconds 360 \
     --json
   ```

   Use cumulative second-drop selectively, not on every representative.  Each
   representative costs 273 q-gap calls, but success gives a 138-literal
   clause instead of the current 142-literal x0-only clause.

   Latest continuation:

   ```text
   tmp/ct07_nox7_cumulative_x0_x2low4_more_seed20260656
     windows: 150:4, 265:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered

   tmp/ct07_nox7_cumulative_x0_x3low4_more_seed20260657
     windows: 150:4, 362:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered

   tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260658
     256 / 256 SAT
     256 / 256 q-gap hard no_roots
     293.84s
     factor not recovered

   tmp/ct07_nox7_cumulative_x0_x2low4_seed20260659
     windows: 150:4, 265:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered
   ```

   Current focused manifest:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     142 JSONLs
     13963 cube records
     14083 loadable hard clauses
     207 variant clauses across 87 variant records
     138-literal variants: 10
     factors: 0
   ```

   Updated routine:

   ```text
   1. Run one variant-aware no-x7 direct batch.
   2. Run cumulative x0+x2low4 on 2 fresh representatives.
   3. Run cumulative x0+x3low4 on 2 fresh representatives if budget allows.
   4. Use x0-only representative minimization for cheaper wider coverage.
   ```

   Latest continuation:

   ```text
   tmp/ct07_nox7_cumulative_x0_x3low4_seed20260660
     windows: 150:4, 362:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered

   tmp/ct07_nox7_low600_variant_frontier_batch256_seed20260661
     256 / 256 SAT
     256 / 256 q-gap hard no_roots
     254.45s
     factor not recovered

   tmp/ct07_nox7_cumulative_x0_x2low4_seed20260662
     windows: 150:4, 265:4
     2 / 2 cumulative minimized
     138-literal variants
     factor not recovered
   ```

   Current focused manifest:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     147 JSONLs
     14223 cube records
     14343 loadable hard clauses
     211 variant clauses across 91 variant records
     138-literal variants: 14
     factors: 0
   ```

20. no-x7 direct/cumulative cycle runner:
   `run_nox7_cumulative_cycle.py` now automates the preferred manual loop.  It
   runs one no-x7 direct q-gap batch, appends its JSONL to the active manifest,
   then runs cumulative representative minimization on fresh rows.

   Verified smoke:

   ```text
   tmp/ct07_nox7_cumulative_cycle_smoke_seed20260663
     direct: 32 / 32 q-gap hard no_roots
     cumulative x0+x2low4: 1 / 1 minimized
     learned clause: 138 literals
     factor not recovered
   ```

   Current focused manifest after the smoke:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     149 JSONLs
     14256 cube records
     10257 unique no-x7 projection keys seen
     6229 variant projection key instances
     92 variant records
     factors: 0
   ```

   Full-size one-iteration continuation:

   ```text
   tmp/ct07_nox7_cumulative_cycle_full_seed20260664_iter1
     direct: 256 / 256 q-gap hard no_roots
     x0+x2low4 cumulative: 2 / 2 minimized
     x0+x3low4 cumulative: 2 / 2 minimized
     learned clauses: four 138-literal variants
     elapsed: 754.62s
     factor not recovered
   ```

   Current focused manifest after that continuation:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     154 JSONLs
     14516 cube records
     11234 unique no-x7 projection keys seen
     7253 variant projection key instances
     96 variant records
     216 variant clauses
     factors: 0
   ```

   Triple cumulative drop probe:

   ```text
   tmp/ct07_nox7_triple_cumulative_x0_x2_x3_seed20260665
     windows: 150:4, 265:4, 362:4
     target completions: 16 + 256 + 4096
     status: manually stopped after more than 30 minutes
     manifest append: none
     factor not recovered
   ```

   This is a negative operational signal: three-window cumulative drops may be
   mathematically useful, but they are too expensive for the routine cycle.
   Keep them as rare targeted proof experiments only.  Do not count the stopped
   probe as a hard clause.

   Direct-only continuation after the triple-drop probe:

   ```text
   tmp/ct07_nox7_direct_cycle_seed20260665_iter1
     direct: 256 / 256 q-gap hard no_roots
     elapsed: 354.34s
     factor not recovered
   ```

   Current focused manifest after the direct-only continuation:

   ```text
   tmp/ct07_pwindow420_scored_qgap_ledgers_20260607.txt
     155 JSONLs
     14772 cube records
     11362 unique no-x7 projection keys seen
     7253 variant projection key instances
     96 variant records
     216 variant clauses
     factors: 0
   ```

   Recommended 12-hour continuation command for the current no-x7 line:

   ```bash
   python3 cryptotest/solutions/07_sat_cas_explore/run_nox7_cumulative_cycle.py \
     --output-dir tmp/ct07_nox7_cycle_12h_seed20260672_direct512_x2x3_top2_skip_sampler \
     --seed-base 20260672 \
     --iterations 48 \
     --max-seconds 43200 \
     --direct-max-total 512 \
     --frontier-top 640 \
     --candidate-pool 65536 \
     --top-pairs 256 \
     --samples-per-pair 2 \
     --x2-cumulative-top 2 \
     --x3-cumulative-top 2 \
     --cumulative-start-index 1 \
     --cumulative-max-completions 256 \
     --workers 8 \
     --direct-command-timeout-seconds 3600 \
     --direct-qgap-timeout-seconds 1800 \
     --skip-sampler-learned-clauses \
     --cumulative-item-timeout-seconds 420 \
     --cumulative-command-timeout-seconds 2400 \
     --q-gap-epsilon 0.04 \
     --q-gap-max-bits 462 \
     --oracle-timeout-seconds 120 \
     --json
   ```

   Expected per full iteration, based on recent timings:

   ```text
   direct batch:          about 4-7 minutes for 512 rows
   x2 cumulative reps:    about 6-8 minutes for 2 reps
   x3 cumulative reps:    about 4-5 minutes for 2 reps
   latest measured total: 14.6-17.7 minutes per iteration
   48 iterations:         bounded by --max-seconds; expected to stop at the
                          12-hour cap before all iterations complete
   ```

   Stop early if a child summary reports `status=factored`; otherwise inspect
   `cycle_summary.json` and the active manifest after the run.  Exit code 2
   still means "completed with no factor", not runner failure.

   If the long run continues to produce only no-root clauses, do not simply add
   a third 4-bit cumulative drop to the default loop.  The first triple-drop
   probe was still unfinished after more than 30 minutes for one representative.
   The next improvement should instead be a cheaper prefilter or a new oracle
   that avoids enumerating all 4096 third-window completions.
