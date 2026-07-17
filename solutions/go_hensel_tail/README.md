# Go Hensel Tail CNF Prototype

This directory is a minimal Go/CNF scaffold for cryptotest problem 7 tail probes.
It mirrors the shape of `try_07_hensel_tail_cp_sat.py` without depending on
OR-Tools.

Implemented:

- JSON input for cube/parameter records, including direct fields and `argv`
  records produced by the Python tail-plan tooling.
- 16-bit lower-limb model for `T = 784`, `800`, `816`, `832`, or `848`.
- Limb, carry, and column data structures for the lower Hensel recurrence and
  the exact-tail columns:
  `pL*qL`, `pH*qL`, `qH*pL`, and constant `pH*qH` tail terms.
- Automatic `q` low-bit derivation and high common-prefix derivation from the
  current `p` interval, matching the Python CP-SAT tail model's setup step.
- Verification that both `p` and `q` tails above `T` are fully known before the
  tail-lock column model is built.
- DIMACS variable and clause manager.
- `p`/`q` fixed-bit assumptions emitted as DIMACS unit clauses.
- Optional `-var-map` JSON export for `p_<bit>` and `q_<bit>` DIMACS
  variable ids. This is used by PySAT assumption sweeps without relying on
  variable creation order or DIMACS comments.
- Optional `arithmetic_bits` / `--arith-bits` product-prefix arithmetic CNF.
  This bit-blasts `p*q == N (mod 2^k)` using AND, XOR, and full-adder clauses.
  For `k > T`, the factor bits above `T` are read from the known `p`/`q` high
  tails. It is intended as the first SAT-export smoke path before the optimized
  tail-lock column equality is encoded. `k` may now run up to the full RSA
  product width, `2048`, so shortlist probes can include product bits beyond
  the 1024-bit factor boundary.
- Optional `skip_known_prefix_limbs` / `--skip-known-prefix-limbs` carry seed.
  When p/q bits below that limb boundary are fully known, their product is
  folded into a constant carry and the corresponding low-low product terms are
  omitted from the arithmetic CNF.
- Optional `skip_known_prefix_bits` / `--skip-known-prefix-bits` carry seed.
  This is the bit-precise form of the same optimization and is useful when a
  fixed prefix ends at a non-limb boundary such as bit 265. If both limb and bit
  skip values are provided, they must describe the same boundary.
- Optional `tail_window_bits` / `--tail-window-bits` arithmetic window CNF.
  This checks `p*q == N` on a bit window, defaulting to `[T, T + bits)`, without
  bit-blasting the whole prefix up to `T`. The carry entering the window is
  represented by a bounded free binary value (`--tail-window-carry-bits`,
  default 12). This is a conservative filter: it is weaker than a true Hensel
  lower-column recurrence, but much smaller than `arithmetic_bits=T+bits`.
- Optional `q_interval_bound` / `--q-interval-bound` lower-tail bound clauses.
  The exporter computes the current interval `q_min <= q <= q_max`, subtracts
  the known high tail `qH * 2^T`, and emits unsigned CNF bounds for `qL`. This
  is a cheap redundant constraint: it adds no variables and only a few hundred
  long clauses for the current 784-bit lower tail.
- Optional `lowlift_q_bits=265` / `--lowlift-q 265` affine 2-adic lift. When
  `x0` is fixed, `q[210..264]` is an affine function of
  `x1=p[210..248]` modulo `2^55`. The exporter encodes that relation directly
  in CNF, tying q's middle-low bits to the p edge variable without
  bit-blasting the lower product columns again.
- Optional `lowlift_q_bits=272` / `--lowlift-q 272` affine 2-adic lift. This
  limb-aligned variant extends the same linear inverse relation through
  `q[0..271]`, so `x2low7=p[265..271]` is tied to q-low together with `x1`.
  It is larger than the 265-bit middle-only lift, but better aligned with the
  current `x1high7*x2low7` assumption sweeps.
- Optional `odd_residue_primes` / `--odd-residue-prime` redundant modular
  constraints. For each small odd modulus, the exporter builds deterministic
  residue automata for `p mod r` and `q mod r`, then forbids residue pairs with
  `p*q != N (mod r)`. Known bits are folded as constant residue shifts, so the
  automata allocate state variables only at unknown bit positions. This is off
  by default because it still adds many clauses and is useful mainly as a
  shortlist/probe option.

Still incomplete:

- Full optimized Boolean CNF encoding of the Hensel-tail column equalities above
  `T`. A first exact carry-column encoder exists behind
  `exact_tail_carry_limbs` / `--exact-tail-carry-limbs`; it ties lower columns
  and tail columns with explicit binary carry vectors, but it is still a naive
  bit-blasted prototype and is not yet a fast broad pruning oracle. The
  tail-window CNF remains the smaller weak model with a bounded free carry-in.
- Solver invocation or model decoding.

The `--lowlift-q` paths have semantic regression tests. The 265-bit path checks
selected `x1` values against the expected q-middle bits; the 272-bit path checks
an `x1/x2low7` assignment against the full expected q-low value. In both cases,
the expected assignment unit-propagates without contradiction and a one-bit
flipped q assignment conflicts. In current problem-7 free-`x1` probes,
lowlift-q265 plus q interval bounds, odd residues, and a 16-bit tail window
still leaves the five tracked full-`x6` candidates SAT. This confirms the
encoding is useful plumbing, but the next pruning step still needs exact lower
carry elimination or a real tail carry-vector equality.

## Input

The tool expects `n`, `known_p`, and `mask_p` as decimal or hex strings. It also
accepts tail-plan `argv` fields to fill `T`, branch nibbles, and fixed ranges.

```json
{
  "T": 848,
  "limb_bits": 16,
  "tail_limbs": 8,
  "arithmetic_bits": 800,
  "skip_known_prefix_limbs": 17,
  "skip_known_prefix_bits": 0,
  "tail_window_bits": 16,
  "tail_window_carry_bits": 12,
  "lowlift_q_bits": 265,
  "q_interval_bound": true,
  "n": "0x...",
  "known_p": "0x...",
  "mask_p": "0x...",
  "branch_low": 0,
  "branch_high": 0,
  "fixed_p_ranges": [
    {"start": 210, "width": 4, "value": "0xa"}
  ],
  "fixed_q_ranges": [
    {"start": 832, "width": 16, "value": "0x1234"}
  ]
}
```

For JSONL plan records, copy one record into a JSON file and add `n`, `known_p`,
and `mask_p` fields. The `argv` array is parsed for compatible flags.

## Usage

```sh
go run . --input input.json --summary
go run . --input input.json --out tail.cnf
go run . --input input.json --out tail.cnf --var-map tail.vars.json -no-comments
```

Without `arithmetic_bits`, the generated DIMACS declares bit variables and
fixed-bit unit clauses only. With `arithmetic_bits`, it also includes a concrete
product-prefix CNF. For example, on the current best problem-7 shortlist cube
with `T=784` and `tail_limb=4`, the exporter emits:

```text
arithmetic_bits=64:                 3136 variables,   7809 clauses
arithmetic_bits=128:                7755 variables,  29356 clauses
arithmetic_bits=800:              442468 variables, 2013402 clauses
arithmetic_bits=800, skip 17 limbs: 390569 variables, 1771380 clauses
```

The extended product-prefix path is much heavier but can be used as a shortlist
verifier before implementing the optimized tail-lock columns. On a representative
`T=800`, high32-`x6` assumptions cube with 15 known prefix limbs, constant-aware
adder simplification produced:

```text
arithmetic_bits=272:   2744 variables,    6282 clauses
arithmetic_bits=800: 403415 variables, 1809331 clauses
arithmetic_bits=1040: 777622 variables, 3453804 clauses
```

The matching PySAT/CaDiCaL smoke for one assumption tuple returned `UNSAT`.
This is too large for broad sweeps, but it proves the exporter can now inject
product bits past the 1024-bit factor prefix.

The lighter tail-window path checks product bits at `T` with a bounded unknown
carry-in. On a representative `T=800`, high32-`x6` assumptions cube with
`arith_bits=272`, `skip_known_prefix_limbs=15`, and `q_interval_bound`:

```text
tail_window_bits=16: 24984 variables, 105144 clauses
tail_window_bits=32: 48497 variables, 209998 clauses
```

The 16-bit window closed all `16384` `x6low14` assumptions for the smoke
`x1low32=0xd08466ff, x1high7=0x60, x2low7=0x7e` with SAT `0`.

To compare this cheap window with a stronger product-prefix oracle, use
`../compare_07_tail_oracle.py`. The oracle run disables `tail_window_bits` and
uses `arithmetic_bits=T+window_bits`, so it is much larger but useful as a
guardrail before implementing exact-tail carry-vector CNF.

```sh
/tmp/cryptotest_sat_venv/bin/python ../compare_07_tail_oracle.py \
  --go-binary /tmp/crypto7_go_hensel_tail_filter_tailwindow \
  --q-interval-bound \
  --T 800 --base-arith-bits 272 \
  --tail-window-bits 16 --tail-window-carry-bits 12 \
  --skip-known-prefix-limbs 15 \
  --x6high-bits 32 --x6high 0x9154852 --x6low 0x0 \
  --x1low32 0x008466ff --x1high7 0x50 --x2low7 0x00
```

On that tuple the weak window and the `arith_bits=816` oracle both returned
`UNSAT`; the weak CNF was `24799` variables / `104355` clauses and the oracle
CNF was `424158` variables / `1901622` clauses.

The same wrapper can sweep carry-in widths. This is useful because too small a
free carry bound could make the weak window accidentally stronger than the
product-prefix oracle.

```sh
/tmp/cryptotest_sat_venv/bin/python ../compare_07_tail_oracle.py \
  --go-binary /tmp/crypto7_go_hensel_tail_filter_tailwindow \
  --q-interval-bound \
  --T 800 --base-arith-bits 272 \
  --tail-window-bits 16 --tail-window-carry-bits-list 8,10,12,14,16 \
  --skip-known-prefix-limbs 15 \
  --x6high-bits 32 --x6high 0x9154852 --x6low 0x0 \
  --x1low32 0x008466ff --x1high7 0x70 --x2low7 0x7e
```

On that tuple every tested carry width returned `both_unsat` against the same
`arith_bits=816` oracle.

On a current `x1low32/x6` assumptions smoke with `T=784`,
`arith_bits=800`, and `skip_known_prefix_limbs=15`, enabling
`q_interval_bound` kept the same variable count and added 516 clauses:

```text
without q interval bound: 434011 variables, 1959285 clauses
with q interval bound:    434011 variables, 1959801 clauses
```

The odd-residue automata are now compressed over known bits. On the direct
free-`x1` smoke with full `x6=0x24552149094`, `--T-candidates 784,800`,
`arith_bits=272`, `--lowlift-q 272`, q interval, and odd residue `3`, the
compressed CNFs were:

```text
T=784: 12116 variables, 46452 clauses
T=800: 12149 variables, 46484 clauses
```

Before compression the same smoke was about `15518/54398` and `15551/54430`
variables/clauses. With odd residues `3,5,7,11` and five tracked full-`x6`
candidates over `T=784,800,816,832,848`, the weak free-`x1` filter still left
all 25 candidate/T pairs SAT. So this optimization lowers broad-probe cost, but
does not replace exact-tail carry-vector CNF.

For `x2low7` sweeps, keep `x2` unfixed in the base CNF and solve with
assumptions over `p_265..p_271`. In that mode
`skip_known_prefix_limbs` must be at most `16`, because the 17th 16-bit limb
contains those unfixed `x2` bits. The current PySAT runner uses `-var-map` for
that path and reuses one CNF per `(x1, x6)` group.

```sh
/tmp/cryptotest_sat_venv/bin/python ../run_07_go_sat_filter.py \
  --assume-x2low7 --x1 0x60c68466ff --x2low7-all \
  --arith-bits 800 --skip-known-prefix-limbs 16
```

For broader `x1` searches, keep only `x1low32` fixed in the base CNF and solve
with assumptions over `p_242..p_248` (`x1high7`) and `p_265..p_271`
(`x2low7`). In that mode `skip_known_prefix_limbs` must be at most `15`,
because the 16th 16-bit limb contains the unfixed `x1high7` bits.

```sh
/tmp/cryptotest_sat_venv/bin/python ../run_07_go_sat_filter.py \
  --assume-x1high7-x2low7 \
  --summary-only --summary-json /tmp/crypto7_x1wide_summary.json \
  --q-interval-bound \
  --x1low32 0xc4fd44ff --x1high7-all --x2low7-all \
  --arith-bits 800 --skip-known-prefix-limbs 15
```

The same summary options also work for fixed full-`x6` `x1high7/x2low7`
sweeps, so broad filters can avoid writing tens of thousands of JSONL rows.
When a full `x6` candidate is fixed, the Python runner can also regenerate the
CNF for several Hensel split points with `--T-candidates`. This is intended as a
diagnostic and shortlist filter: every `T` tests the same underlying
`x1high7/x2low7` assumptions, so do not add the per-`T` UNSAT counts as
independent search-space removals.

```sh
/tmp/cryptotest_sat_venv/bin/python ../run_07_go_sat_filter.py \
  --assume-x1high7-x2low7 \
  --summary-only --summary-json /tmp/crypto7_t_candidates_summary.json \
  --q-interval-bound \
  --T-candidates 784,800,816,832,848 --arith-bits 272 --skip-known-prefix-limbs 15 \
  --x6 0x24552149094 \
  --x1low32 0x2cfd44ff --x1high7 0x00 --x2low7 0x7e
```

Use `--exact-tail-limbs` when the intended check is the safe product-prefix
oracle for a fixed number of limbs beyond each split point. For example,
`--T 784 --exact-tail-limbs 1` is equivalent to `--arith-bits 800`, while
`--T-candidates 784,800,816,832,848 --exact-tail-limbs 1` generates
`arith_bits` `800`, `816`, `832`, `848`, and `864` respectively. This does not use the weak
`tail_window` free carry model.

Use `--exact-tail-carry-limbs` when the intended check is the explicit
limb-column carry-vector prototype. For `--exact-tail-carry-limbs 1`, the Go
exporter encodes all lower columns plus the first column above `T`, with carry
bits linked column-to-column. If `skip_known_prefix_limbs` or
`skip_known_prefix_bits` is set, the exact carry encoder starts after that
known prefix and injects the computed carry as a constant carry-in. The skip
must currently be limb-aligned. `--exact-carry-bits` is a safety cap; the
exporter computes a per-column carry width from simple upper bounds and only
allocates the bits each column can actually need. Skips after a 272-bit prefix
still need a cap above the incoming carry width. This path is exact, unlike
`tail_window`, but currently less optimized than the product-prefix oracle. The
encoder folds fully known limb products into the column constant before emitting
adder literals.

On two active full-`x6` shortlist tuples, `--T-candidates 784,800,848
--exact-tail-limbs 1 --q-interval-bound` returned `UNSAT` for every `T`.
The `T=784` CNFs were the smallest (`402576` and `408419` variables), while
`T=848` grew to roughly `493k..500k` variables. Prefer `T=784` first when the
fixed full-`x6` branch makes both high tails known.

For `x6` prefix searches, use `T=800` or higher so the unfixed low `x6` bits
remain below the Hensel split. The Python runner can then keep an `x6` high
prefix fixed in the base CNF and sweep `x6low`, `x1high7`, and `x2low7` through
assumptions:

```sh
/tmp/cryptotest_sat_venv/bin/python ../run_07_go_sat_filter.py \
  --assume-x6low-x1high7-x2low7 \
  --q-interval-bound \
  --T 800 --arith-bits 800 --skip-known-prefix-limbs 15 \
  --x6high-bits 44 --x6high 0x9154852425 --x6low-all \
  --x1low32 0xc4fd44ff --x1high7 0x61 --x2low7 0x00
```

That smoke keeps a single CNF for the high44 prefix and tests all four low2
values:

```text
x6=0x24552149094 low2=0 SAT=False
x6=0x24552149095 low2=1 SAT=False
x6=0x24552149096 low2=2 SAT=False
x6=0x24552149097 low2=3 SAT=False
vars=434355 clauses=1961280 assumptions=16
```

This mode also supports `--T-candidates`. Candidate split points below the
`x6` high boundary are recorded in `skipped_t` instead of aborting the whole
run. A smoke with `--T-candidates 784,800 --exact-tail-limbs 1`,
`x6high_bits=44`, and `x6high=0x9154852425` skipped `T=784` because the
boundary is `786`, then solved the `T=800` product-prefix oracle for four
`x6low` assumptions; all four were `UNSAT`.

The same path also works for a wider high40 prefix. With `x6high_bits=40`,
`x6high=0x915485242`, `x6low-all`, `x1low32=0xc4fd44ff`,
`x1high7=0x61`, and `x2low7=0x7e`, `T=784` is skipped because the boundary is
`790`; the `T=800` oracle used `429611` variables / `1926508` clauses and
closed all `64` low6 assumptions.

Expanding that high40 check to the full `x1high7=0x00..0x7f` range with the same
`x1low32=0xc4fd44ff`, `x2low7=0x7e`, `T-candidates=784,800`,
`exact-tail-limbs=1`, and `q-interval-bound` keeps `T=784` skipped and closes
all `8192` assumptions at `T=800`. The larger shards and the eight-value shards
use the same `429611` variable / `1926508` clause CNF with `20` assumption
literals per row.

Using the same high40 base with the representative shortlist
`x2low7={0x7e,0x7b,0x43,0x11,0x2b}` closes all `40960` assumptions. The four
extra x2 values each contribute `8192` `UNSAT` rows under the same `T=800`
oracle; `T=784` remains skipped because the x6 high boundary is `790`.
Two additional high40 bases, `x1low32=0x0c22ffff` and `0xfa22ffff`, also close
all `40960` assumptions each under the same representative x2 shortlist.
The next pair, `0xfb22ffff` and `0xd922ffff`, closes in the same way.
The next four bases, `0xda22ffff`, `0xfe22ffff`, `0xbc22ffff`, and
`0x2d22ffff`, also close all `40960` assumptions each. Their `T=800`
product-prefix oracle CNFs range from `428797` to `432599` variables and from
`1923325` to `1940753` clauses.
Four more bases, `0x8122ffff`, `0xde22ffff`, `0xf522ffff`, and `0xa722ffff`,
close the same `40960` assumptions each, with `T=800` CNFs ranging from
`427580` to `431749` variables and from `1917267` to `1936623` clauses. This
brings the closed representative high40 `x1low32` bases to 13, still short of a
full high40-bucket proof. The next four bases, `0xf922ffff`, `0xcf22ffff`,
`0xc722ffff`, and `0xd422ffff`, close as well, with `T=800` CNFs from `428436`
to `431730` variables and from `1921454` to `1936566` clauses. The high40
representative closure count is now 17 bases. The next four bases,
`0xab22ffff`, `0x12fd44ff`, `0xdbfd44ff`, and `0x5cfd44ff`, also close,
bringing the count to 21 bases. Their `T=800` CNFs range from `428385` to
`429993` variables and from `1921077` to `1928712` clauses.
The following eight bases, `0x41fd44ff`, `0x42fd44ff`, `0x60fd44ff`,
`0x3bfd44ff`, `0x4dfd44ff`, `0x68fd44ff`, `0x2afd44ff`, and `0x97fd44ff`,
also close, bringing the representative count to 29 bases. Their `T=800` CNFs
range from `427970` to `430495` variables and from `1919075` to `1930798`
clauses.
The next eight bases, `0x2cfd44ff`, `0x56fd44ff`, `0x20fd44ff`, `0x65fd44ff`,
`0x1dfd44ff`, `0x35fd44ff`, `0x8ffd44ff`, and `0x82fd44ff`, also close,
bringing the representative count to 37 bases. Their `T=800` CNFs range from
`425848` to `431099` variables and from `1909842` to `1933542` clauses.
The next eight bases, `0x798466ff`, `0x1e8466ff`, `0xab8466ff`,
`0xd68466ff`, `0xc68466ff`, `0x868466ff`, `0x8d8466ff`, and `0x538466ff`,
also close, bringing the representative count to 45 bases. Their `T=800` CNFs
range from `425706` to `428607` variables and from `1908721` to `1921818`
clauses.
The next eight bases, `0xe48466ff`, `0xfd8466ff`, `0xce8466ff`,
`0xe98466ff`, `0xd28466ff`, `0x8c8466ff`, `0xeb8466ff`, and `0x6a8466ff`,
also close, bringing the representative count to 53 bases. Their `T=800` CNFs
range from `426774` to `431297` variables and from `1913628` to `1934229`
clauses.
The earlier `0xd08466ff` base was rerun with the same `T-candidates=784,800`
and `exact-tail-limbs=1` product-prefix oracle format; it also closes all
`40960` assumptions with a `426437` variable / `1911857` clause `T=800` CNF.
This closes the 54 representative high40 `x1low32` bases tracked from the
high32 queue, but it is not a proof for every possible high40-bucket base.

The same high40 product-prefix oracle also closes the next 16 `8466ff` bases
from the high32 queue:
`0x218466ff`, `0x1c8466ff`, `0xa78466ff`, `0x718466ff`, `0xa58466ff`,
`0x998466ff`, `0xcc8466ff`, `0xe88466ff`, `0xe38466ff`, `0x188466ff`,
`0x788466ff`, `0xc48466ff`, `0x928466ff`, `0x808466ff`, `0x828466ff`, and
`0x858466ff`. With `x6high_bits=40`, `x6high=0x915485242`, `x6low-all`,
full `x1high7`, the five representative `x2low7` values, `T-candidates=784,800`,
`exact-tail-limbs=1`, and `q-interval-bound`, all `655360` assumptions are
`UNSAT`. The `T=800` CNFs range from `424308` to `428311` variables and from
`1902688` to `1920761` clauses.

Eight more `8466ff` bases, `0x008466ff`, `0x118466ff`, `0x228466ff`,
`0x338466ff`, `0x448466ff`, `0x558466ff`, `0x668466ff`, and `0x778466ff`, close
under the same high40 oracle as well. They add `327680` `UNSAT` assumptions with
`T=800` CNFs from `423637` to `427633` variables and from `1899147` to `1917849`
clauses. The high40 `0x915485242` representative closure count is therefore
`78` bases, or `3194880` `UNSAT` assumptions, still not a full proof for the
entire bucket.

The prefix-assumption path can be widened further. With `x6high_bits=36` and
`x6high=0x91548524`, the runner sweeps `1024` low-`x6` values per base through
assumptions. On ten representative bases
`0xc4fd44ff`, `0xd08466ff`, `0x0c22ffff`, `0xfa22ffff`, `0xfb22ffff`,
`0xd922ffff`, `0xda22ffff`, `0xfe22ffff`, `0xbc22ffff`, and `0x2d22ffff`, full
`x1high7`, and the five representative `x2low7` values, `T=784` is skipped
because the x6 high boundary is `794`; `T=800` closes all `6553600`
assumptions. The CNFs range from `426663` to `432843` variables and from
`1912987` to `1941954` clauses. This is a wider representative sweep, not a
proof for the full high36 bucket.

The next eight representative bases under the same high36 prefix,
`0x8122ffff`, `0xde22ffff`, `0xf522ffff`, `0xa722ffff`, `0xf922ffff`,
`0xcf22ffff`, `0xc722ffff`, and `0xd422ffff`, also close under the same
`T=800`, one-tail-limb product-prefix oracle. This adds `5242880` `UNSAT`
assumptions with CNFs ranging from `427861` to `432018` variables and from
`1918608` to `1937915` clauses. The representative high36 closure is now 18
`x1low32` bases and `11796480` assumptions, still not a proof for the full
bucket.

Another eight high36 representative bases, `0xab22ffff`, `0x12fd44ff`,
`0xdbfd44ff`, `0x5cfd44ff`, `0x41fd44ff`, `0x42fd44ff`, `0x60fd44ff`, and
`0x3bfd44ff`, close under the same conditions as well. This adds another
`5242880` `UNSAT` assumptions with CNFs ranging from `428239` to `430239`
variables and from `1920386` to `1929934` clauses. The high36 representative
closure is now 26 `x1low32` bases and `17039360` assumptions.

The following high40-closed representative bases were also widened to the
high36 prefix: `0x4dfd44ff`, `0x68fd44ff`, `0x2afd44ff`, `0x97fd44ff`,
`0x2cfd44ff`, `0x56fd44ff`, `0x20fd44ff`, and `0x65fd44ff`. The same `T=800`
product-prefix oracle closes another `5242880` assumptions with CNFs ranging
from `426103` to `430765` variables and from `1911069` to `1932097` clauses.
The high36 representative closure is now 34 `x1low32` bases and `22282240`
assumptions.

The next representative batch, `0x1dfd44ff`, `0x35fd44ff`, `0x8ffd44ff`,
`0x82fd44ff`, `0x798466ff`, `0x1e8466ff`, `0xab8466ff`, and `0xd68466ff`,
also closes under the same high36 prefix. This adds `5242880` `UNSAT`
assumptions with CNFs ranging from `427508` to `431345` variables and from
`1917201` to `1934736` clauses. The high36 representative closure is now 42
`x1low32` bases and `27525120` assumptions.

Another `8466ff` representative batch, `0xc68466ff`, `0x868466ff`,
`0x8d8466ff`, `0x538466ff`, `0xe48466ff`, `0xfd8466ff`, `0xce8466ff`, and
`0xe98466ff`, closes under the same high36 prefix. This adds `5242880` more
`UNSAT` assumptions with CNFs ranging from `425975` to `431536` variables and
from `1910012` to `1935415` clauses. The high36 representative closure is now
50 `x1low32` bases and `32768000` assumptions.

The last four bases from the initial representative set, `0xd28466ff`,
`0x8c8466ff`, `0xeb8466ff`, and `0x6a8466ff`, close under the same high36
prefix as well. This adds `2621440` `UNSAT` assumptions with CNFs ranging from
`427151` to `428047` variables and from `1915339` to `1919630` clauses. The
initial 54-base representative set is now closed under high36
`x6high=0x91548524`, with `35389440` assumptions and `SAT=0`. This is still a
representative-set closure, not a proof for the full high36 bucket.

A high36 weak-window sanity sweep with `x1low32=0x218466ff`,
`x1high7={0x00,0x20,0x40,0x60}`, all `x2low7` values, and all high36 `x6low`
values used `arith_bits=272`, `tail_window_bits=16`, `tail_window_carry_bits=16`,
`q_interval_bound`, and odd residues `3,5,7`. It closes `524288` assumptions
with a `55405` variable / `223698` clause CNF. A single tuple
`x1high7=0x00,x2low7=0x00,x6low=0x000` cross-checks as `UNSAT` under the
stronger one-tail-limb product-prefix oracle (`424582` variables,
`1903999` clauses). Treat this as a weak-filter sanity result; final pruning
should still use product-prefix or a stronger verifier.

The same weak-window sanity sweep on the next representative base
`x1low32=0x1c8466ff` also closes all `524288` assumptions with a `55502`
variable / `224055` clause CNF. Its tuple
`x1high7=0x00,x2low7=0x00,x6low=0x000` cross-checks as `UNSAT` under the
stronger one-tail-limb product-prefix oracle; `T=784` is skipped because the
high36 boundary is `794`, while `T=800` uses `427691` variables and `1917845`
clauses.

The third next-base `x1low32=0xa78466ff` behaves the same way: the weak-window
sweep closes all `524288` assumptions with `55609` variables and `224539`
clauses, and the tuple `x1high7=0x00,x2low7=0x00,x6low=0x000` cross-checks as
`UNSAT` under the stronger one-tail-limb product-prefix oracle (`T=800`,
`428632` variables, `1922270` clauses; `T=784` is below boundary `794`).

The fourth next-base `x1low32=0x718466ff` also closes all `524288` weak-window
assumptions with `55582` variables and `224412` clauses. The same tuple
cross-checks as `UNSAT` under the stronger one-tail-limb product-prefix oracle
at `T=800` (`427826` variables, `1918265` clauses; `T=784` is below boundary
`794`). The weak full-`x2low7` sanity set now covers
`0x218466ff/0x1c8466ff/0xa78466ff/0x718466ff`.

Two more next-bases, `x1low32=0xa58466ff` and `0x998466ff`, also close all
`524288` weak-window assumptions each. Their weak CNFs use `55530` variables /
`224223` clauses and `55568` variables / `224363` clauses, respectively. The
same tuple cross-checks as `UNSAT` under the stronger one-tail-limb
product-prefix oracle at `T=800` (`426913` variables / `1914485` clauses and
`426732` variables / `1913281` clauses; `T=784` is below boundary `794`). The
weak full-`x2low7` sanity set now covers six next-bases, with `3145728`
weak-filter assumptions and `SAT=0`.

Four additional next-bases, `0xcc8466ff`, `0xe88466ff`, `0xe38466ff`, and
`0x188466ff`, also close all `524288` weak-window assumptions each. Their weak
CNFs use `55562/224342`, `55575/224370`, `55618/224580`, and `55446/223825`
variables/clauses. The tuple `x1high7=0x00,x2low7=0x00,x6low=0x000`
cross-checks as `UNSAT` under the stronger one-tail-limb product-prefix oracle
at `T=800` with `427694/1917838`, `427153/1915311`, `427533/1917257`, and
`424851/1904931` variables/clauses. The weak full-`x2low7` sanity set now
covers 10 next-bases, with `5242880` weak-filter assumptions and `SAT=0`.

The remaining six next-bases, `0x788466ff`, `0xc48466ff`, `0x928466ff`,
`0x808466ff`, `0x828466ff`, and `0x858466ff`, close all `524288` weak-window
assumptions each as well. Their weak CNFs use `55548/224287`, `55550/224237`,
`55515/224132`, `55419/223671`, `55470/223908`, and `55530/224174`
variables/clauses. The same tuple cross-checks as `UNSAT` under the stronger
one-tail-limb product-prefix oracle at `T=800` with `425865/1909628`,
`426616/1912917`, `426087/1910467`, `425631/1908200`, `425576/1908038`, and
`426102/1910530` variables/clauses. This closes all 16 tracked next-bases under
the high36 weak full-`x2low7` sanity, for `8388608` weak-filter assumptions and
`SAT=0`.

The same 16 next-bases were then checked more directly with the safe
one-tail-limb product-prefix oracle instead of only the weak-window filter.
The common setup was `x6high_bits=36`, `x6high=0x91548524`, all `x6low`
values, all `x1high7` values, representative `x2low7` values
`{0x7e,0x7b,0x43,0x11,0x2b}`, `T-candidates=784,800`,
`--exact-tail-limbs 1`, and `--q-interval-bound`. `T=784` is skipped because
the high36 boundary is `794`; active `T=800` CNFs use roughly `424582..428632`
variables and `1903999..1922270` clauses across the shard bases. The four
summary shards are:

```text
/tmp/crypto7_x6low_t_candidates_high36_91548524_nextbase16_part1_x1hall_x2_shortlist_summary.json
/tmp/crypto7_x6low_t_candidates_high36_91548524_nextbase16_part2_x1hall_x2_shortlist_summary.json
/tmp/crypto7_x6low_t_candidates_high36_91548524_nextbase16_part3_x1hall_x2_shortlist_summary.json
/tmp/crypto7_x6low_t_candidates_high36_91548524_nextbase16_part4_x1hall_x2_shortlist_summary.json
```

Each base closes `1024 * 128 * 5 = 655360` assumptions, and all 16 bases close
`10485760` assumptions with `SAT=0`. This is stronger than the weak-window
sanity because it sweeps full `x6low` and full `x1high7` through the product
prefix oracle, but it is still limited to the representative `x2low7`
shortlist and this high36 prefix. The Python runner remains useful for cube
orchestration, assumptions, and JSON summaries; the expensive repeated CNF
generation and product-prefix checks are the parts moved into Go.

To add redundant small-modulus constraints for a shortlist probe, repeat
`--odd-residue-prime`:

```sh
/tmp/cryptotest_sat_venv/bin/python ../run_07_go_sat_filter.py \
  --assume-x6low-x1high7-x2low7 \
  --q-interval-bound \
  --odd-residue-prime 3 --odd-residue-prime 5 \
  --T 800 --arith-bits 272 --skip-known-prefix-limbs 15 \
  --x6high-bits 44 --x6high 0x9154852425 --x6low-all \
  --x1low32 0xc4fd44ff --x1high7 0x61 --x2low7 0x00
```

A high36 smoke with `x6high=0x91548524`, `x6low=0x094`,
`x1low32=0xd08466ff`, `x1high7=0x60`, `x2low7=0x7e`, and odd residues
`3,5,7` returns `SAT=0`, `UNSAT=1`. `T=784` is skipped by the high boundary
and the `T=800` CNF has `457413` variables and `2032963` clauses. The same
tuple without odd residues was already closed by the product-prefix oracle, so
this is a feature smoke rather than a new pruning signal; broad safe-oracle
sweeps should keep odd residues optional unless a weaker prefix/window model
needs additional filtering.
