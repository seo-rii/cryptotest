#!/usr/bin/env python3
"""Run the Go Hensel-tail DIMACS exporter and solve shortlist cubes with PySAT.

This is a SAT filter for problem 7 edge candidates. It expects python-sat
(`pysat`) in the active Python environment and calls `src/go_hensel_tail`
to generate a DIMACS product-prefix CNF for each case.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOLUTIONS = ROOT / "src"
GO_EXPORTER = ROOT / "experiments" / "go_hensel_tail"
CONSTANTS = ROOT / "src" / "investigate_rsa_partial_bits.py"


def load_constants() -> tuple[int, int, int]:
    spec = importlib.util.spec_from_file_location("c7_constants", CONSTANTS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load constants from {CONSTANTS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    n = int(module.N_HEX.replace(" ", ""), 16)
    mask = int(module.MASK_HEX.replace(" ", ""), 16)
    known = int(module.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    return n, mask, known


def dimacs_stats(path: Path) -> tuple[int, int]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("p cnf "):
                continue
            parts = line.split()
            if len(parts) != 4:
                break
            return int(parts[2]), int(parts[3])
    raise RuntimeError(f"could not find DIMACS header in {path}")


def parse_case(text: str) -> tuple[int, int, str]:
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("expected X1:X2LOW7[:LABEL]")
    x1 = int(parts[0], 0)
    x2 = int(parts[1], 0)
    if x1 < 0 or x1 >= (1 << 39):
        raise argparse.ArgumentTypeError("x1 does not fit 39 bits")
    if x2 < 0 or x2 >= (1 << 7):
        raise argparse.ArgumentTypeError("x2low7 does not fit 7 bits")
    label = parts[2] if len(parts) == 3 else f"x1_{x1:x}_x2_{x2:x}"
    return x1, x2, label


def load_case_file(path: Path) -> list[tuple[int, int, str]]:
    cases: list[tuple[int, int, str]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            cases.append(parse_case(line))
        except argparse.ArgumentTypeError as exc:
            raise argparse.ArgumentTypeError(f"{path}:{line_no}: {exc}") from exc
    return cases


def x2low7_assumptions(var_map: dict[str, int], x2: int) -> list[int]:
    assumptions: list[int] = []
    for off in range(7):
        name = f"p_{265 + off}"
        try:
            var = int(var_map[name])
        except KeyError as exc:
            raise RuntimeError(f"Go var-map does not contain {name}") from exc
        assumptions.append(var if (x2 >> off) & 1 else -var)
    return assumptions


def x1high7_assumptions(var_map: dict[str, int], x1_high7: int) -> list[int]:
    assumptions: list[int] = []
    for off in range(7):
        name = f"p_{242 + off}"
        try:
            var = int(var_map[name])
        except KeyError as exc:
            raise RuntimeError(f"Go var-map does not contain {name}") from exc
        assumptions.append(var if (x1_high7 >> off) & 1 else -var)
    return assumptions


def x6low_assumptions(var_map: dict[str, int], x6_low: int, width: int) -> list[int]:
    assumptions: list[int] = []
    for off in range(width):
        name = f"p_{784 + off}"
        try:
            var = int(var_map[name])
        except KeyError as exc:
            raise RuntimeError(f"Go var-map does not contain {name}") from exc
        assumptions.append(var if (x6_low >> off) & 1 else -var)
    return assumptions


def extract_p_bits(var_map: dict[str, int], model_lits: set[int], start: int, width: int) -> int:
    value = 0
    for off in range(width):
        name = f"p_{start + off}"
        try:
            var = int(var_map[name])
        except KeyError as exc:
            raise RuntimeError(f"Go var-map does not contain {name}") from exc
        if var in model_lits:
            value |= 1 << off
    return value


def try_extract_p_bits(var_map: dict[str, int], model_lits: set[int], start: int, width: int) -> int | None:
    value = 0
    for off in range(width):
        name = f"p_{start + off}"
        if name not in var_map:
            return None
        if int(var_map[name]) in model_lits:
            value |= 1 << off
    return value


def model_blocking_clause(var_map: dict[str, int], model_lits: set[int], ranges: list[tuple[int, int]]) -> list[int]:
    clause: list[int] = []
    for start, width in ranges:
        for off in range(width):
            name = f"p_{start + off}"
            try:
                var = int(var_map[name])
            except KeyError as exc:
                raise RuntimeError(f"Go var-map does not contain {name}") from exc
            clause.append(-var if var in model_lits else var)
    return clause


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", type=parse_case, help="X1:X2LOW7[:LABEL]")
    parser.add_argument("--case-file", action="append", type=Path, help="file with one X1:X2LOW7[:LABEL] per line")
    parser.add_argument("--x1", action="append", type=lambda s: int(s, 0), help="full 39-bit x1 value; combine with --x2low7/--x2low7-all")
    parser.add_argument("--x1low32", action="append", type=lambda s: int(s, 0), help="low 32 bits of x1; combine with --x1high7/--x1high7-all and --x2low7/--x2low7-all")
    parser.add_argument("--x1high7", action="append", type=lambda s: int(s, 0), help="specific x1 high-7-bit value for --x1low32")
    parser.add_argument("--x1high7-all", action="store_true", help="generate every x1 high-7-bit value for each --x1low32")
    parser.add_argument("--x2low7", action="append", type=lambda s: int(s, 0), help="specific x2 low-7-bit value")
    parser.add_argument("--x2low7-all", action="store_true", help="generate cases for every x2low7 value for each --x1")
    parser.add_argument("--x6", type=lambda s: int(s, 0), default=0x245521490BD)
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        help="add an extra fixed p bit range as START:WIDTH:VALUE; repeatable",
    )
    parser.add_argument(
        "--fix-p-range-sweep",
        help="for direct fixed cases, generate one fixed CNF per p range value as START:WIDTH:all or START:WIDTH:V1,V2,...",
    )
    parser.add_argument(
        "--assume-p-range",
        help="for direct fixed cases, sweep p bit assumptions as START:WIDTH:all or START:WIDTH:V1,V2,...",
    )
    parser.add_argument("--x6high", type=lambda s: int(s, 0), help="high prefix of 46-bit x6 for x6-low assumption sweeps")
    parser.add_argument("--x6high-bits", type=int, default=44, help="number of high x6 bits fixed by --x6high")
    parser.add_argument("--x6low", action="append", type=lambda s: int(s, 0), help="specific low bits of x6 for x6-low assumption sweeps")
    parser.add_argument("--x6low-all", action="store_true", help="generate every low x6 value under --x6high")
    parser.add_argument("--T", type=int, default=784)
    parser.add_argument(
        "--T-candidates",
        help="comma-separated T values to try for x1high/x2low or x6low assumption sweeps",
    )
    parser.add_argument("--limb-bits", type=int, default=16)
    parser.add_argument("--tail-limbs", type=int, default=4)
    parser.add_argument("--arith-bits", type=int, default=800)
    parser.add_argument(
        "--exact-tail-limbs",
        type=int,
        help="set arithmetic_bits to T + limb_bits * exact_tail_limbs for each generated CNF",
    )
    parser.add_argument("--skip-known-prefix-limbs", type=int)
    parser.add_argument("--skip-known-prefix-bits", type=int)
    parser.add_argument("--tail-window-start", type=int)
    parser.add_argument("--tail-window-bits", type=int, default=0)
    parser.add_argument("--tail-window-carry-bits", type=int, default=0)
    parser.add_argument("--exact-tail-carry-limbs", type=int, default=0)
    parser.add_argument("--exact-carry-bits", type=int, default=0)
    parser.add_argument(
        "--lowlift-q",
        type=int,
        default=0,
        help="ask the Go exporter to add an affine q low lift; currently supports 265 and 272",
    )
    parser.add_argument(
        "--q-interval-bound",
        action="store_true",
        help="ask the Go exporter to add q_min <= q <= q_max lower-tail bound clauses",
    )
    parser.add_argument(
        "--odd-residue-prime",
        action="append",
        type=int,
        default=[],
        help="ask the Go exporter to add a redundant p*q == N modulo this odd prime; repeatable",
    )
    parser.add_argument(
        "--assume-x2low7",
        action="store_true",
        help="build one CNF per x1/x6 and sweep x2low7 through PySAT assumptions",
    )
    parser.add_argument(
        "--assume-x1high7-x2low7",
        action="store_true",
        help="build one CNF per x1low32/x6 and sweep x1 high bits plus x2low7 through PySAT assumptions",
    )
    parser.add_argument(
        "--assume-x6low-x1high7-x2low7",
        action="store_true",
        help="build one CNF per x1low32/x6 high prefix and sweep x6 low bits, x1 high bits, and x2low7 through PySAT assumptions",
    )
    parser.add_argument(
        "--free-x1-filter",
        action="store_true",
        help="build one CNF per fixed full x6 and leave x1 plus x2low7 free; solves the base CNF directly",
    )
    parser.add_argument(
        "--free-x1-x6high-filter",
        action="store_true",
        help="build one CNF per fixed x6 high prefix and leave x6 low, x1, and x2low7 free",
    )
    parser.add_argument(
        "--x6-candidate",
        action="append",
        type=lambda s: int(s, 0),
        help="full 46-bit x6 candidate for --free-x1-filter; repeatable, defaults to --x6",
    )
    parser.add_argument(
        "--x6high-candidate",
        action="append",
        type=lambda s: int(s, 0),
        help="x6 high-prefix candidate for --free-x1-x6high-filter; repeatable, defaults to --x6high",
    )
    parser.add_argument(
        "--free-x1-model-limit",
        type=int,
        default=0,
        help="when a free-x1 CNF is SAT, enumerate up to this many distinct x1/x2low7 model projections",
    )
    parser.add_argument("--branch-low", type=lambda s: int(s, 0), default=0)
    parser.add_argument("--branch-high", type=lambda s: int(s, 0), default=0)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--go-binary", type=Path, help="prebuilt go_hensel_tail binary; built automatically when omitted")
    parser.add_argument("--keep-cnf", action="store_true")
    parser.add_argument("--build-only", action="store_true", help="generate CNF and report DIMACS size without loading or solving it")
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--summary-json", type=Path, help="write compact aggregate SAT/UNSAT counts to this JSON file")
    parser.add_argument("--summary-only", action="store_true", help="suppress per-case JSON rows and print only the final summary")
    args = parser.parse_args()

    t_candidates = None
    if args.T_candidates:
        t_candidates = []
        for raw_t in args.T_candidates.split(","):
            raw_t = raw_t.strip()
            if not raw_t:
                continue
            try:
                t_candidates.append(int(raw_t, 0))
            except ValueError:
                parser.error(f"invalid --T-candidates value: {raw_t!r}")
        if not t_candidates:
            parser.error("--T-candidates must contain at least one T value")

    extra_fixed_p_ranges: list[dict[str, int | str]] = []
    for raw_range in args.fix_p_range:
        parts = raw_range.split(":")
        if len(parts) != 3:
            parser.error(f"invalid --fix-p-range {raw_range!r}: expected START:WIDTH:VALUE")
        try:
            start = int(parts[0], 0)
            width = int(parts[1], 0)
            value = int(parts[2], 0)
        except ValueError:
            parser.error(f"invalid --fix-p-range {raw_range!r}: expected integer START:WIDTH:VALUE")
        if start < 0:
            parser.error(f"--fix-p-range start must be non-negative: {raw_range!r}")
        if width <= 0:
            parser.error(f"--fix-p-range width must be positive: {raw_range!r}")
        if value < 0 or value >= (1 << width):
            parser.error(f"--fix-p-range value does not fit width {width}: {raw_range!r}")
        extra_fixed_p_ranges.append({"start": start, "width": width, "value": hex(value)})

    fix_p_sweep_start: int | None = None
    fix_p_sweep_width = 0
    fix_p_sweep_values: list[int] | None = None
    if args.fix_p_range_sweep:
        parts = args.fix_p_range_sweep.split(":")
        if len(parts) != 3:
            parser.error("--fix-p-range-sweep expects START:WIDTH:all or START:WIDTH:V1,V2,...")
        try:
            fix_p_sweep_start = int(parts[0], 0)
            fix_p_sweep_width = int(parts[1], 0)
        except ValueError:
            parser.error(f"invalid --fix-p-range-sweep bounds: {args.fix_p_range_sweep!r}")
        if fix_p_sweep_start < 0:
            parser.error("--fix-p-range-sweep start must be non-negative")
        if fix_p_sweep_width <= 0:
            parser.error("--fix-p-range-sweep width must be positive")
        raw_values = parts[2].strip()
        if raw_values == "all":
            if fix_p_sweep_width > 12:
                parser.error("--fix-p-range-sweep all is capped at width <= 12; list larger sweeps explicitly")
            fix_p_sweep_values = list(range(1 << fix_p_sweep_width))
        else:
            fix_p_sweep_values = []
            for raw_value in raw_values.split(","):
                raw_value = raw_value.strip()
                if not raw_value:
                    continue
                try:
                    fix_p_sweep_values.append(int(raw_value, 0))
                except ValueError:
                    parser.error(f"invalid --fix-p-range-sweep value: {raw_value!r}")
            if not fix_p_sweep_values:
                parser.error("--fix-p-range-sweep must include at least one value")
        for fix_p_sweep_value in fix_p_sweep_values:
            if fix_p_sweep_value < 0 or fix_p_sweep_value >= (1 << fix_p_sweep_width):
                parser.error(f"--fix-p-range-sweep value does not fit width {fix_p_sweep_width}: {fix_p_sweep_value:#x}")

    assume_p_start: int | None = None
    assume_p_width = 0
    assume_p_values: list[int] | None = None
    if args.assume_p_range:
        parts = args.assume_p_range.split(":")
        if len(parts) != 3:
            parser.error("--assume-p-range expects START:WIDTH:all or START:WIDTH:V1,V2,...")
        try:
            assume_p_start = int(parts[0], 0)
            assume_p_width = int(parts[1], 0)
        except ValueError:
            parser.error(f"invalid --assume-p-range bounds: {args.assume_p_range!r}")
        if assume_p_start < 0:
            parser.error("--assume-p-range start must be non-negative")
        if assume_p_width <= 0:
            parser.error("--assume-p-range width must be positive")
        raw_values = parts[2].strip()
        if raw_values == "all":
            if assume_p_width > 16:
                parser.error("--assume-p-range all is capped at width <= 16")
            assume_p_values = list(range(1 << assume_p_width))
        else:
            assume_p_values = []
            for raw_value in raw_values.split(","):
                raw_value = raw_value.strip()
                if not raw_value:
                    continue
                try:
                    assume_p_values.append(int(raw_value, 0))
                except ValueError:
                    parser.error(f"invalid --assume-p-range value: {raw_value!r}")
            if not assume_p_values:
                parser.error("--assume-p-range must include at least one value")
        for assume_p_value in assume_p_values:
            if assume_p_value < 0 or assume_p_value >= (1 << assume_p_width):
                parser.error(f"--assume-p-range value does not fit width {assume_p_width}: {assume_p_value:#x}")

    cases = list(args.case or [])
    low32_cases: list[tuple[int, int, int, str]] = []
    low32_x6low_cases: list[tuple[int, int, int, int, str]] = []
    for case_file in args.case_file or []:
        cases.extend(load_case_file(case_file))
    x2_values = list(args.x2low7 or [])
    for x2 in x2_values:
        if x2 < 0 or x2 >= (1 << 7):
            parser.error(f"--x2low7 value does not fit 7 bits: {x2:#x}")
    if args.x2low7_all:
        x2_values = list(range(1 << 7))
    for x1 in args.x1 or []:
        if x1 < 0 or x1 >= (1 << 39):
            parser.error(f"--x1 value does not fit 39 bits: {x1:#x}")
        if not x2_values:
            parser.error("--x1 requires --x2low7 or --x2low7-all")
        for x2 in x2_values:
            cases.append((x1, x2, f"x1_{x1:x}_x2_{x2:02x}"))
    x1high_values = list(args.x1high7 or [])
    for x1_high7 in x1high_values:
        if x1_high7 < 0 or x1_high7 >= (1 << 7):
            parser.error(f"--x1high7 value does not fit 7 bits: {x1_high7:#x}")
    if args.x1high7_all:
        x1high_values = list(range(1 << 7))
    for x1low32 in args.x1low32 or []:
        if x1low32 < 0 or x1low32 >= (1 << 32):
            parser.error(f"--x1low32 value does not fit 32 bits: {x1low32:#x}")
        if not x1high_values:
            parser.error("--x1low32 requires --x1high7 or --x1high7-all")
        if not x2_values:
            parser.error("--x1low32 requires --x2low7 or --x2low7-all")
        for x1_high7 in x1high_values:
            for x2 in x2_values:
                x1 = (x1_high7 << 32) | x1low32
                low32_cases.append((x1low32, x1_high7, x2, f"x1_{x1:x}_x2_{x2:02x}"))
    x6_low_width = 46 - args.x6high_bits
    x6low_values = list(args.x6low or [])
    for x6low in x6low_values:
        if x6low < 0 or x6low >= (1 << max(0, x6_low_width)):
            parser.error(f"--x6low value does not fit {x6_low_width} bits: {x6low:#x}")
    if args.x6low_all:
        if not (0 < x6_low_width <= 16):
            parser.error("--x6low-all requires 1..16 low x6 bits; adjust --x6high-bits")
        x6low_values = list(range(1 << x6_low_width))
    if args.assume_x6low_x1high7_x2low7:
        if args.x6high is None:
            parser.error("--assume-x6low-x1high7-x2low7 requires --x6high")
        if not (1 <= args.x6high_bits < 46):
            parser.error("--x6high-bits must be in 1..45 for x6-low assumption sweeps")
        if args.x6high < 0 or args.x6high >= (1 << args.x6high_bits):
            parser.error(f"--x6high value does not fit {args.x6high_bits} bits: {args.x6high:#x}")
        if t_candidates is None and args.T < 830 - args.x6high_bits:
            parser.error("--T must be high enough that unfixed x6 low bits are below T")
        if not x6low_values:
            parser.error("--assume-x6low-x1high7-x2low7 requires --x6low or --x6low-all")
        if not low32_cases:
            parser.error("--assume-x6low-x1high7-x2low7 requires --x1low32 with x1high7/x2low7 values")
        for x1low32, x1_high7, x2, label in low32_cases:
            for x6low in x6low_values:
                low32_x6low_cases.append((x1low32, x1_high7, x2, x6low, f"{label}_x6low_{x6low:0{(x6_low_width + 3) // 4}x}"))
        low32_cases = []
    if low32_cases and not args.assume_x1high7_x2low7:
        parser.error("--x1low32 cases require --assume-x1high7-x2low7")
    if low32_x6low_cases and not args.assume_x6low_x1high7_x2low7:
        parser.error("--x6low cases require --assume-x6low-x1high7-x2low7")
    if args.free_x1_model_limit < 0:
        parser.error("--free-x1-model-limit must be non-negative")
    for x6_candidate in args.x6_candidate or []:
        if x6_candidate < 0 or x6_candidate >= (1 << 46):
            parser.error(f"--x6-candidate value does not fit 46 bits: {x6_candidate:#x}")
    if args.free_x1_filter and args.free_x1_x6high_filter:
        parser.error("--free-x1-filter and --free-x1-x6high-filter are mutually exclusive")
    free_x1_direct_filter = args.free_x1_filter or args.free_x1_x6high_filter
    for x6high_candidate in args.x6high_candidate or []:
        if x6high_candidate < 0 or x6high_candidate >= (1 << args.x6high_bits):
            parser.error(f"--x6high-candidate value does not fit {args.x6high_bits} bits: {x6high_candidate:#x}")
    if args.free_x1_x6high_filter:
        if not (1 <= args.x6high_bits < 46):
            parser.error("--free-x1-x6high-filter requires --x6high-bits in 1..45")
        if args.x6high is None and not args.x6high_candidate:
            parser.error("--free-x1-x6high-filter requires --x6high or --x6high-candidate")
        if args.x6high is not None and (args.x6high < 0 or args.x6high >= (1 << args.x6high_bits)):
            parser.error(f"--x6high value does not fit {args.x6high_bits} bits: {args.x6high:#x}")
    if free_x1_direct_filter and (args.assume_x2low7 or args.assume_x1high7_x2low7 or args.assume_x6low_x1high7_x2low7):
        parser.error("free-x1 direct filters cannot be combined with assumption sweep modes")
    if args.assume_p_range and (free_x1_direct_filter or args.assume_x2low7 or args.assume_x1high7_x2low7 or args.assume_x6low_x1high7_x2low7):
        parser.error("--assume-p-range currently supports direct fixed cases only")
    if args.fix_p_range_sweep and (free_x1_direct_filter or args.assume_x2low7 or args.assume_x1high7_x2low7 or args.assume_x6low_x1high7_x2low7):
        parser.error("--fix-p-range-sweep currently supports direct fixed cases only")
    if args.fix_p_range_sweep and args.assume_p_range:
        parser.error("--fix-p-range-sweep and --assume-p-range are mutually exclusive")
    if free_x1_direct_filter and (args.case or args.case_file or args.x1 or args.x1low32):
        parser.error("free-x1 direct filters do not use --case, --case-file, --x1, or --x1low32 inputs")
    if args.free_x1_filter and t_candidates is None and args.T < 784:
        parser.error("--free-x1-filter requires T >= 784 so fixed full x6 is below or at the split")
    if args.free_x1_x6high_filter and t_candidates is None and args.T < 830 - args.x6high_bits:
        parser.error("--free-x1-x6high-filter requires T >= 830 - x6high_bits so unfixed x6 low bits are below the split")
    if free_x1_direct_filter and args.arith_bits < 272 and args.exact_tail_limbs is None:
        parser.error("free-x1 direct filters need --arith-bits >= 272 to constrain x2low7")
    if args.assume_x1high7_x2low7 and args.assume_x2low7:
        parser.error("--assume-x1high7-x2low7 and --assume-x2low7 are mutually exclusive")
    if args.assume_x6low_x1high7_x2low7 and (args.assume_x1high7_x2low7 or args.assume_x2low7):
        parser.error("--assume-x6low-x1high7-x2low7 cannot be combined with other assumption modes")
    if t_candidates is not None and not (args.assume_x1high7_x2low7 or args.assume_x6low_x1high7_x2low7 or free_x1_direct_filter):
        parser.error("--T-candidates requires an x1high7/x2low7, x6low assumption, or free-x1 sweep")
    if args.exact_tail_limbs is not None and args.exact_tail_limbs < 0:
        parser.error("--exact-tail-limbs must be non-negative")
    if args.skip_known_prefix_bits is not None and args.skip_known_prefix_bits < 0:
        parser.error("--skip-known-prefix-bits must be non-negative")
    if not free_x1_direct_filter and not cases and not low32_cases and not low32_x6low_cases:
        parser.error("provide at least one --case, --case-file, --x1, or --x1low32 case")
    if args.skip_known_prefix_limbs is None and args.skip_known_prefix_bits is None:
        if free_x1_direct_filter:
            args.skip_known_prefix_bits = 210
        elif args.assume_x6low_x1high7_x2low7:
            args.skip_known_prefix_limbs = 15
        elif args.assume_x1high7_x2low7:
            args.skip_known_prefix_limbs = 15
        elif args.assume_x2low7:
            args.skip_known_prefix_limbs = 16
        else:
            args.skip_known_prefix_limbs = 17
    if args.skip_known_prefix_limbs is None:
        args.skip_known_prefix_limbs = 0
    if args.skip_known_prefix_bits is None:
        args.skip_known_prefix_bits = 0
    if args.assume_x2low7 and args.skip_known_prefix_limbs > 16:
        parser.error("--assume-x2low7 leaves p[265..271] unknown in the base CNF; use --skip-known-prefix-limbs <= 16")
    if args.assume_x1high7_x2low7 and args.skip_known_prefix_limbs > 15:
        parser.error("--assume-x1high7-x2low7 leaves p[242..248] unknown in the base CNF; use --skip-known-prefix-limbs <= 15")
    if args.assume_x6low_x1high7_x2low7 and args.skip_known_prefix_limbs > 15:
        parser.error("--assume-x6low-x1high7-x2low7 leaves p[242..248] unknown in the base CNF; use --skip-known-prefix-limbs <= 15")
    if args.assume_x2low7 and args.skip_known_prefix_bits > 265:
        parser.error("--assume-x2low7 leaves p[265..271] unknown in the base CNF; use --skip-known-prefix-bits <= 265")
    if args.assume_x1high7_x2low7 and args.skip_known_prefix_bits > 242:
        parser.error("--assume-x1high7-x2low7 leaves p[242..248] unknown in the base CNF; use --skip-known-prefix-bits <= 242")
    if args.assume_x6low_x1high7_x2low7 and args.skip_known_prefix_bits > 242:
        parser.error("--assume-x6low-x1high7-x2low7 leaves p[242..248] unknown in the base CNF; use --skip-known-prefix-bits <= 242")
    if free_x1_direct_filter and args.skip_known_prefix_bits > 210:
        parser.error("free-x1 direct filters leave x1 unknown from bit 210; use --skip-known-prefix-bits <= 210")
    if free_x1_direct_filter and args.skip_known_prefix_limbs * args.limb_bits > 210:
        parser.error("free-x1 direct filters leave x1 unknown from bit 210; use --skip-known-prefix-limbs low enough")

    try:
        from pysat.formula import CNF
        from pysat.solvers import Solver
    except ImportError as exc:
        print(
            "[!] python-sat is not available in this Python environment. "
            "Create a venv and install it, e.g. `python3 -m venv /tmp/cryptotest_sat_venv && "
            "/tmp/cryptotest_sat_venv/bin/python -m pip install python-sat`.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    n, mask, known = load_constants()
    workdir_context = tempfile.TemporaryDirectory(prefix="crypto7_go_sat_") if args.workdir is None else None
    base_dir = args.workdir if args.workdir is not None else Path(workdir_context.name)
    base_dir.mkdir(parents=True, exist_ok=True)
    go_binary = args.go_binary
    if go_binary is None:
        go_binary = ROOT / "experiments" / "go_hensel_tail"
        subprocess.run(
            ["go", "build", "-o", str(go_binary), "."],
            cwd=GO_EXPORTER,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        if free_x1_direct_filter:
            if args.free_x1_x6high_filter:
                x6_candidates = args.x6high_candidate or [args.x6high]
                fixed_start = 830 - args.x6high_bits
                fixed_width = args.x6high_bits
                candidate_key = "x6high"
                mode = "free_x1_x6high_filter"
            else:
                x6_candidates = args.x6_candidate or [args.x6]
                fixed_start = 784
                fixed_width = 46
                candidate_key = "x6"
                mode = "free_x1_filter"
            summary = {
                "mode": mode,
                "sat": 0,
                "unsat": 0,
                "candidate_count": len(x6_candidates),
                "t_candidates": t_candidates,
                "x6_count": len(x6_candidates) if args.free_x1_filter else None,
                "x6high_bits": args.x6high_bits if args.free_x1_x6high_filter else None,
                "by_candidate": {},
                "by_x6": {} if args.free_x1_filter else None,
                "by_x6high": {} if args.free_x1_x6high_filter else None,
            } if args.summary_json is not None or args.summary_only else None
            if summary is not None and t_candidates is not None:
                summary["skipped_t"] = []
            for x6_candidate in x6_candidates:
                if x6_candidate is None:
                    parser.error("--free-x1-x6high-filter requires a concrete x6 high prefix")
                for t_value in (t_candidates or [args.T]):
                    if t_value < fixed_start:
                        reason = f"T={t_value} is below fixed high boundary {fixed_start}"
                        skipped_row = {
                            candidate_key: hex(x6_candidate),
                            "fixed_start": fixed_start,
                            "fixed_width": fixed_width,
                            "T": t_value,
                            "skipped": True,
                            "reason": reason,
                        }
                        if summary is not None:
                            summary.setdefault("skipped_t", []).append(skipped_row)
                        if not args.summary_only:
                            print(json.dumps(skipped_row), flush=True)
                        continue

                    group_label = f"{mode}_{candidate_key}_{x6_candidate:x}_{fixed_width}_T_{t_value}"
                    if args.q_interval_bound:
                        group_label += "_qbound"
                    input_path = base_dir / f"{group_label}.json"
                    cnf_path = base_dir / f"{group_label}.cnf"
                    var_map_path = base_dir / f"{group_label}.vars.json"
                    arith_bits = args.arith_bits
                    if args.exact_tail_limbs is not None:
                        arith_bits = t_value + args.limb_bits * args.exact_tail_limbs
                    payload = {
                        "T": t_value,
                        "limb_bits": args.limb_bits,
                        "tail_limbs": args.tail_limbs,
                        "arithmetic_bits": arith_bits,
                        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                        "skip_known_prefix_bits": args.skip_known_prefix_bits,
                        "tail_window_start": args.tail_window_start or 0,
                        "tail_window_bits": args.tail_window_bits,
                        "tail_window_carry_bits": args.tail_window_carry_bits,
                        "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                        "exact_carry_bits": args.exact_carry_bits,
                        "lowlift_q_bits": args.lowlift_q,
                        "q_interval_bound": args.q_interval_bound,
                        "odd_residue_primes": args.odd_residue_prime,
                        "no_comments": True,
                        "n": hex(n),
                        "known_p": hex(known),
                        "mask_p": hex(mask),
                        "branch_low": args.branch_low,
                        "branch_high": args.branch_high,
                        "fixed_p_ranges": [
                            {"start": fixed_start, "width": fixed_width, "value": hex(x6_candidate)},
                        ] + extra_fixed_p_ranges,
                    }
                    input_path.write_text(json.dumps(payload), encoding="utf-8")
                    exporter = subprocess.run(
                        [str(go_binary), "-input", str(input_path), "-out", str(cnf_path), "-var-map", str(var_map_path), "-no-comments"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if exporter.returncode != 0:
                        reason = exporter.stderr.strip()
                        if t_candidates is not None and "tail is not fully known above T" in reason:
                            skipped_row = {
                                candidate_key: hex(x6_candidate),
                                "fixed_start": fixed_start,
                                "fixed_width": fixed_width,
                                "T": t_value,
                                "skipped": True,
                                "reason": reason,
                            }
                            if summary is not None:
                                summary.setdefault("skipped_t", []).append(skipped_row)
                            if not args.summary_only:
                                print(json.dumps(skipped_row), flush=True)
                            input_path.unlink(missing_ok=True)
                            cnf_path.unlink(missing_ok=True)
                            var_map_path.unlink(missing_ok=True)
                            continue
                        print(reason, file=sys.stderr)
                        raise subprocess.CalledProcessError(exporter.returncode, exporter.args)
                    if args.build_only:
                        vars_count, clauses_count = dimacs_stats(cnf_path)
                        row = {
                            candidate_key: hex(x6_candidate),
                            "fixed_start": fixed_start,
                            "fixed_width": fixed_width,
                            "T": t_value,
                            "arith_bits": arith_bits,
                            "exact_tail_limbs": args.exact_tail_limbs,
                            "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                            "skip_known_prefix_bits": args.skip_known_prefix_bits,
                            "tail_window_start": args.tail_window_start or t_value,
                            "tail_window_bits": args.tail_window_bits,
                            "tail_window_carry_bits": args.tail_window_carry_bits,
                            "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                            "exact_carry_bits": args.exact_carry_bits,
                            "lowlift_q_bits": args.lowlift_q,
                            "q_interval_bound": args.q_interval_bound,
                            "odd_residue_primes": args.odd_residue_prime,
                            "free_x1_filter": args.free_x1_filter,
                            "free_x1_x6high_filter": args.free_x1_x6high_filter,
                            "build_only": True,
                            "vars": vars_count,
                            "clauses": clauses_count,
                            "sat": None,
                        }
                        if summary is not None:
                            summary["build_only"] = True
                            summary["build_count"] = summary.get("build_count", 0) + 1
                            summary.setdefault("build_rows", []).append(row)
                        if not args.summary_only:
                            print(json.dumps(row), flush=True)
                        if not args.keep_cnf:
                            cnf_path.unlink(missing_ok=True)
                            input_path.unlink(missing_ok=True)
                            var_map_path.unlink(missing_ok=True)
                        continue
                    cnf = CNF(from_file=str(cnf_path))
                    var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
                    models = []
                    with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                        sat = solver.solve()
                        if sat and args.free_x1_model_limit > 0:
                            for _ in range(args.free_x1_model_limit):
                                model_lits = {lit for lit in solver.get_model() if lit > 0}
                                x1 = extract_p_bits(var_map, model_lits, 210, 39)
                                x2low7 = extract_p_bits(var_map, model_lits, 265, 7)
                                model_row = {
                                    "x1": hex(x1),
                                    "x1low32": hex(x1 & ((1 << 32) - 1)),
                                    "x1high7": hex(x1 >> 32),
                                    "x2low7": hex(x2low7),
                                }
                                full_x6 = try_extract_p_bits(var_map, model_lits, 784, 46)
                                if full_x6 is not None:
                                    model_row["x6"] = hex(full_x6)
                                models.append(model_row)
                                block_ranges = [(210, 39), (265, 7)]
                                if args.free_x1_x6high_filter and full_x6 is not None:
                                    block_ranges.append((784, 46))
                                block = model_blocking_clause(var_map, model_lits, block_ranges)
                                if not block:
                                    break
                                solver.add_clause(block)
                                if not solver.solve():
                                    break
                    row = {
                        candidate_key: hex(x6_candidate),
                        "fixed_start": fixed_start,
                        "fixed_width": fixed_width,
                        "T": t_value,
                        "arith_bits": arith_bits,
                        "exact_tail_limbs": args.exact_tail_limbs,
                        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                        "skip_known_prefix_bits": args.skip_known_prefix_bits,
                        "tail_window_start": args.tail_window_start or t_value,
                        "tail_window_bits": args.tail_window_bits,
                        "tail_window_carry_bits": args.tail_window_carry_bits,
                        "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                        "exact_carry_bits": args.exact_carry_bits,
                        "lowlift_q_bits": args.lowlift_q,
                        "q_interval_bound": args.q_interval_bound,
                        "odd_residue_primes": args.odd_residue_prime,
                        "free_x1_filter": args.free_x1_filter,
                        "free_x1_x6high_filter": args.free_x1_x6high_filter,
                        "vars": cnf.nv,
                        "clauses": len(cnf.clauses),
                        "sat": sat,
                        "model_count": len(models),
                        "models": models,
                    }
                    if summary is not None:
                        if sat:
                            summary["sat"] += 1
                        else:
                            summary["unsat"] += 1
                        candidate_summary = summary["by_candidate"].setdefault(hex(x6_candidate), {"by_t": {}}) if t_candidates is not None else row
                        if t_candidates is not None:
                            candidate_summary["by_t"][str(t_value)] = row
                        else:
                            summary["by_candidate"][hex(x6_candidate)] = row
                        if args.free_x1_filter:
                            if t_candidates is not None:
                                x6_summary = summary["by_x6"].setdefault(hex(x6_candidate), {"by_t": {}})
                                x6_summary["by_t"][str(t_value)] = row
                            else:
                                summary["by_x6"][hex(x6_candidate)] = row
                        if args.free_x1_x6high_filter:
                            if t_candidates is not None:
                                x6high_summary = summary["by_x6high"].setdefault(hex(x6_candidate), {"by_t": {}})
                                x6high_summary["by_t"][str(t_value)] = row
                            else:
                                summary["by_x6high"][hex(x6_candidate)] = row
                    if not args.summary_only:
                        print(json.dumps(row), flush=True)
                    if not args.keep_cnf:
                        cnf_path.unlink(missing_ok=True)
                        input_path.unlink(missing_ok=True)
                        var_map_path.unlink(missing_ok=True)
            if summary is not None:
                summary["by_candidate"] = {
                    x6_key: summary["by_candidate"][x6_key]
                    for x6_key in sorted(summary["by_candidate"], key=lambda value: int(value, 0))
                }
                if args.free_x1_filter:
                    summary["by_x6"] = {
                        x6_key: summary["by_x6"][x6_key]
                        for x6_key in sorted(summary["by_x6"], key=lambda value: int(value, 0))
                    }
                if args.free_x1_x6high_filter:
                    summary["by_x6high"] = {
                        x6_key: summary["by_x6high"][x6_key]
                        for x6_key in sorted(summary["by_x6high"], key=lambda value: int(value, 0))
                    }
                if args.summary_json is not None:
                    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
                    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.summary_only:
                    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return 0

        if args.assume_x6low_x1high7_x2low7:
            grouped_x6low: dict[int, list[tuple[int, int, int, str]]] = {}
            for x1low32, x1_high7, x2, x6low, label in low32_x6low_cases:
                grouped_x6low.setdefault(x1low32, []).append((x1_high7, x2, x6low, label))

            summary = {"sat": 0, "unsat": 0, "by_base": {}} if args.summary_json is not None or args.summary_only else None
            if summary is not None and t_candidates is not None:
                summary["skipped_t"] = []
            x6_high_start = 830 - args.x6high_bits
            for x1low32, high_x2_x6_labels in grouped_x6low.items():
                for t_value in (t_candidates or [args.T]):
                    if t_value < x6_high_start:
                        reason = f"T={t_value} is below x6 high boundary {x6_high_start}"
                        if summary is not None:
                            summary["skipped_t"].append(
                                {
                                    "x1low32": hex(x1low32),
                                    "x6high": hex(args.x6high),
                                    "x6high_bits": args.x6high_bits,
                                    "T": t_value,
                                    "reason": reason,
                                }
                            )
                        if not args.summary_only:
                            print(
                                json.dumps(
                                    {
                                        "x1low32": hex(x1low32),
                                        "x6high": hex(args.x6high),
                                        "x6high_bits": args.x6high_bits,
                                        "T": t_value,
                                        "skipped": True,
                                        "reason": reason,
                                    }
                                ),
                                flush=True,
                            )
                        continue

                    group_label = f"x1low32_{x1low32:x}_x6h_{args.x6high:x}_{args.x6high_bits}_T_{t_value}"
                    input_path = base_dir / f"{group_label}.json"
                    cnf_path = base_dir / f"{group_label}.cnf"
                    var_map_path = base_dir / f"{group_label}.vars.json"
                    arith_bits = args.arith_bits
                    if args.exact_tail_limbs is not None:
                        arith_bits = t_value + args.limb_bits * args.exact_tail_limbs
                    payload = {
                        "T": t_value,
                        "limb_bits": args.limb_bits,
                        "tail_limbs": args.tail_limbs,
                        "arithmetic_bits": arith_bits,
                        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                        "skip_known_prefix_bits": args.skip_known_prefix_bits,
                            "tail_window_start": args.tail_window_start or 0,
                            "tail_window_bits": args.tail_window_bits,
                            "tail_window_carry_bits": args.tail_window_carry_bits,
                            "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                            "exact_carry_bits": args.exact_carry_bits,
                            "lowlift_q_bits": args.lowlift_q,
                            "q_interval_bound": args.q_interval_bound,
                        "odd_residue_primes": args.odd_residue_prime,
                        "no_comments": True,
                        "n": hex(n),
                        "known_p": hex(known),
                        "mask_p": hex(mask),
                        "branch_low": args.branch_low,
                        "branch_high": args.branch_high,
                        "fixed_p_ranges": [
                            {"start": x6_high_start, "width": args.x6high_bits, "value": hex(args.x6high)},
                            {"start": 210, "width": 32, "value": hex(x1low32)},
                        ] + extra_fixed_p_ranges,
                    }
                    input_path.write_text(json.dumps(payload), encoding="utf-8")
                    exporter = subprocess.run(
                        [str(go_binary), "-input", str(input_path), "-out", str(cnf_path), "-var-map", str(var_map_path), "-no-comments"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if exporter.returncode != 0:
                        reason = exporter.stderr.strip()
                        if t_candidates is not None and "tail is not fully known above T" in reason:
                            if summary is not None:
                                summary["skipped_t"].append(
                                    {
                                        "x1low32": hex(x1low32),
                                        "x6high": hex(args.x6high),
                                        "x6high_bits": args.x6high_bits,
                                        "T": t_value,
                                        "reason": reason,
                                    }
                                )
                            if not args.summary_only:
                                print(
                                    json.dumps(
                                        {
                                            "x1low32": hex(x1low32),
                                            "x6high": hex(args.x6high),
                                            "x6high_bits": args.x6high_bits,
                                            "T": t_value,
                                            "skipped": True,
                                            "reason": reason,
                                        }
                                    ),
                                    flush=True,
                                )
                            input_path.unlink(missing_ok=True)
                            cnf_path.unlink(missing_ok=True)
                            var_map_path.unlink(missing_ok=True)
                            continue
                        print(reason, file=sys.stderr)
                        raise subprocess.CalledProcessError(exporter.returncode, exporter.args)

                    cnf = CNF(from_file=str(cnf_path))
                    var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
                    with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                        for x1_high7, x2, x6low, label in high_x2_x6_labels:
                            x1 = (x1_high7 << 32) | x1low32
                            x6 = (args.x6high << x6_low_width) | x6low
                            assumptions = x1high7_assumptions(var_map, x1_high7)
                            assumptions.extend(x2low7_assumptions(var_map, x2))
                            assumptions.extend(x6low_assumptions(var_map, x6low, x6_low_width))
                            sat = solver.solve(assumptions=assumptions)
                            row = {
                                "label": label,
                                "x1": hex(x1),
                                "x1low32": hex(x1low32),
                                "x1high7": hex(x1_high7),
                                "x2low7": hex(x2),
                                "x6": hex(x6),
                                "x6high": hex(args.x6high),
                                "x6high_bits": args.x6high_bits,
                                "x6low": hex(x6low),
                                "x6low_bits": x6_low_width,
                                "T": t_value,
                                "arith_bits": arith_bits,
                                "exact_tail_limbs": args.exact_tail_limbs,
                                "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                                "skip_known_prefix_bits": args.skip_known_prefix_bits,
                                    "tail_window_start": args.tail_window_start or t_value,
                                    "tail_window_bits": args.tail_window_bits,
                                    "tail_window_carry_bits": args.tail_window_carry_bits,
                                    "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                                    "exact_carry_bits": args.exact_carry_bits,
                                    "lowlift_q_bits": args.lowlift_q,
                                    "q_interval_bound": args.q_interval_bound,
                                "odd_residue_primes": args.odd_residue_prime,
                                "assume_x6low_x1high7_x2low7": True,
                                "vars": cnf.nv,
                                "clauses": len(cnf.clauses),
                                "assumptions": len(assumptions),
                                "sat": sat,
                            }
                            if summary is not None:
                                base_key = hex(x1low32)
                                base_summary = summary["by_base"].setdefault(
                                    base_key,
                                    {
                                        "sat": 0,
                                        "unsat": 0,
                                        "vars": cnf.nv,
                                        "clauses": len(cnf.clauses),
                                        "assumptions": len(assumptions),
                                        "by_x2": {},
                                        "by_t": {},
                                        "sat_rows": [],
                                    },
                                )
                                base_summary.setdefault("by_t", {})
                                t_key = str(t_value)
                                t_summary = base_summary["by_t"].setdefault(
                                    t_key,
                                    {
                                        "sat": 0,
                                        "unsat": 0,
                                        "vars": cnf.nv,
                                        "clauses": len(cnf.clauses),
                                        "assumptions": len(assumptions),
                                        "by_x2": {},
                                        "sat_rows": [],
                                    },
                                )
                                x2_key = hex(x2)
                                x2_summary = base_summary["by_x2"].setdefault(x2_key, {"sat": 0, "unsat": 0})
                                t_x2_summary = t_summary["by_x2"].setdefault(x2_key, {"sat": 0, "unsat": 0})
                                if sat:
                                    summary["sat"] += 1
                                    base_summary["sat"] += 1
                                    t_summary["sat"] += 1
                                    x2_summary["sat"] += 1
                                    t_x2_summary["sat"] += 1
                                    if len(base_summary["sat_rows"]) < 20:
                                        base_summary["sat_rows"].append(row)
                                    if len(t_summary["sat_rows"]) < 20:
                                        t_summary["sat_rows"].append(row)
                                else:
                                    summary["unsat"] += 1
                                    base_summary["unsat"] += 1
                                    t_summary["unsat"] += 1
                                    x2_summary["unsat"] += 1
                                    t_x2_summary["unsat"] += 1
                            if not args.summary_only:
                                print(json.dumps(row), flush=True)
                    if not args.keep_cnf:
                        cnf_path.unlink(missing_ok=True)
                        input_path.unlink(missing_ok=True)
                        var_map_path.unlink(missing_ok=True)
            if summary is not None:
                summary["by_base"] = {
                    base_key: summary["by_base"][base_key]
                    for base_key in sorted(summary["by_base"], key=lambda value: int(value, 0))
                }
                for base_summary in summary["by_base"].values():
                    base_summary["by_x2"] = {
                        x2_key: base_summary["by_x2"][x2_key]
                        for x2_key in sorted(base_summary["by_x2"], key=lambda value: int(value, 0))
                    }
                    if "by_t" in base_summary:
                        base_summary["by_t"] = {
                            t_key: base_summary["by_t"][t_key]
                            for t_key in sorted(base_summary["by_t"], key=lambda value: int(value, 0))
                        }
                        for t_summary in base_summary["by_t"].values():
                            t_summary["by_x2"] = {
                                x2_key: t_summary["by_x2"][x2_key]
                                for x2_key in sorted(t_summary["by_x2"], key=lambda value: int(value, 0))
                            }
                if args.summary_json is not None:
                    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
                    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.summary_only:
                    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return 0

        if args.assume_x1high7_x2low7:
            grouped_low32: dict[int, list[tuple[int, int, str]]] = {}
            for x1low32, x1_high7, x2, label in low32_cases:
                grouped_low32.setdefault(x1low32, []).append((x1_high7, x2, label))

            summary = {"sat": 0, "unsat": 0, "by_base": {}} if args.summary_json is not None or args.summary_only else None
            if summary is not None and t_candidates is not None:
                summary["skipped_t"] = []
            for x1low32, high_x2_labels in grouped_low32.items():
                for t_value in (t_candidates or [args.T]):
                    group_label = f"x1low32_{x1low32:x}_x6_{args.x6:x}_T_{t_value}"
                    input_path = base_dir / f"{group_label}.json"
                    cnf_path = base_dir / f"{group_label}.cnf"
                    var_map_path = base_dir / f"{group_label}.vars.json"
                    arith_bits = args.arith_bits
                    if args.exact_tail_limbs is not None:
                        arith_bits = t_value + args.limb_bits * args.exact_tail_limbs
                    payload = {
                        "T": t_value,
                        "limb_bits": args.limb_bits,
                        "tail_limbs": args.tail_limbs,
                        "arithmetic_bits": arith_bits,
                        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                        "skip_known_prefix_bits": args.skip_known_prefix_bits,
                            "tail_window_start": args.tail_window_start or 0,
                            "tail_window_bits": args.tail_window_bits,
                            "tail_window_carry_bits": args.tail_window_carry_bits,
                            "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                            "exact_carry_bits": args.exact_carry_bits,
                            "lowlift_q_bits": args.lowlift_q,
                            "q_interval_bound": args.q_interval_bound,
                        "odd_residue_primes": args.odd_residue_prime,
                        "no_comments": True,
                        "n": hex(n),
                        "known_p": hex(known),
                        "mask_p": hex(mask),
                        "branch_low": args.branch_low,
                        "branch_high": args.branch_high,
                        "fixed_p_ranges": [
                            {"start": 784, "width": 46, "value": hex(args.x6)},
                            {"start": 210, "width": 32, "value": hex(x1low32)},
                        ] + extra_fixed_p_ranges,
                    }
                    input_path.write_text(json.dumps(payload), encoding="utf-8")
                    exporter = subprocess.run(
                        [str(go_binary), "-input", str(input_path), "-out", str(cnf_path), "-var-map", str(var_map_path), "-no-comments"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if exporter.returncode != 0:
                        reason = exporter.stderr.strip()
                        if t_candidates is not None and "tail is not fully known above T" in reason:
                            if summary is not None:
                                summary["skipped_t"].append(
                                    {
                                        "x1low32": hex(x1low32),
                                        "x6": hex(args.x6),
                                        "T": t_value,
                                        "reason": reason,
                                    }
                                )
                            if not args.summary_only:
                                print(
                                    json.dumps(
                                        {
                                            "x1low32": hex(x1low32),
                                            "x6": hex(args.x6),
                                            "T": t_value,
                                            "skipped": True,
                                            "reason": reason,
                                        }
                                    ),
                                    flush=True,
                                )
                            input_path.unlink(missing_ok=True)
                            cnf_path.unlink(missing_ok=True)
                            var_map_path.unlink(missing_ok=True)
                            continue
                        print(reason, file=sys.stderr)
                        raise subprocess.CalledProcessError(exporter.returncode, exporter.args)
                    cnf = CNF(from_file=str(cnf_path))
                    var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
                    with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                        for x1_high7, x2, label in high_x2_labels:
                            x1 = (x1_high7 << 32) | x1low32
                            assumptions = x1high7_assumptions(var_map, x1_high7)
                            assumptions.extend(x2low7_assumptions(var_map, x2))
                            sat = solver.solve(assumptions=assumptions)
                            row = {
                                "label": label,
                                "x1": hex(x1),
                                "x1low32": hex(x1low32),
                                "x1high7": hex(x1_high7),
                                "x2low7": hex(x2),
                                "x6": hex(args.x6),
                                "T": t_value,
                                "arith_bits": arith_bits,
                                "exact_tail_limbs": args.exact_tail_limbs,
                                "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                                "skip_known_prefix_bits": args.skip_known_prefix_bits,
                                    "tail_window_start": args.tail_window_start or t_value,
                                    "tail_window_bits": args.tail_window_bits,
                                    "tail_window_carry_bits": args.tail_window_carry_bits,
                                    "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                                    "exact_carry_bits": args.exact_carry_bits,
                                    "lowlift_q_bits": args.lowlift_q,
                                    "q_interval_bound": args.q_interval_bound,
                                "odd_residue_primes": args.odd_residue_prime,
                                "assume_x1high7_x2low7": True,
                                "vars": cnf.nv,
                                "clauses": len(cnf.clauses),
                                "assumptions": len(assumptions),
                                "sat": sat,
                            }
                            if summary is not None:
                                base_key = hex(x1low32)
                                base_summary = summary["by_base"].setdefault(
                                    base_key,
                                    {
                                        "sat": 0,
                                        "unsat": 0,
                                        "vars": cnf.nv,
                                        "clauses": len(cnf.clauses),
                                        "assumptions": len(assumptions),
                                        "by_x2": {},
                                        "by_t": {},
                                        "sat_rows": [],
                                    },
                                )
                                base_summary.setdefault("by_t", {})
                                t_key = str(t_value)
                                t_summary = base_summary["by_t"].setdefault(
                                    t_key,
                                    {
                                        "sat": 0,
                                        "unsat": 0,
                                        "vars": cnf.nv,
                                        "clauses": len(cnf.clauses),
                                        "assumptions": len(assumptions),
                                        "by_x2": {},
                                        "sat_rows": [],
                                    },
                                )
                                x2_key = hex(x2)
                                x2_summary = base_summary["by_x2"].setdefault(x2_key, {"sat": 0, "unsat": 0})
                                t_x2_summary = t_summary["by_x2"].setdefault(x2_key, {"sat": 0, "unsat": 0})
                                if sat:
                                    summary["sat"] += 1
                                    base_summary["sat"] += 1
                                    t_summary["sat"] += 1
                                    x2_summary["sat"] += 1
                                    t_x2_summary["sat"] += 1
                                    if len(base_summary["sat_rows"]) < 20:
                                        base_summary["sat_rows"].append(row)
                                    if len(t_summary["sat_rows"]) < 20:
                                        t_summary["sat_rows"].append(row)
                                else:
                                    summary["unsat"] += 1
                                    base_summary["unsat"] += 1
                                    t_summary["unsat"] += 1
                                    x2_summary["unsat"] += 1
                                    t_x2_summary["unsat"] += 1
                            if not args.summary_only:
                                print(json.dumps(row), flush=True)
                    if not args.keep_cnf:
                        cnf_path.unlink(missing_ok=True)
                        input_path.unlink(missing_ok=True)
                        var_map_path.unlink(missing_ok=True)
            if summary is not None:
                summary["by_base"] = {
                    base_key: summary["by_base"][base_key]
                    for base_key in sorted(summary["by_base"], key=lambda value: int(value, 0))
                }
                for base_summary in summary["by_base"].values():
                    base_summary["by_x2"] = {
                        x2_key: base_summary["by_x2"][x2_key]
                        for x2_key in sorted(base_summary["by_x2"], key=lambda value: int(value, 0))
                    }
                    if "by_t" in base_summary:
                        base_summary["by_t"] = {
                            t_key: base_summary["by_t"][t_key]
                            for t_key in sorted(base_summary["by_t"], key=lambda value: int(value, 0))
                        }
                        for t_summary in base_summary["by_t"].values():
                            t_summary["by_x2"] = {
                                x2_key: t_summary["by_x2"][x2_key]
                                for x2_key in sorted(t_summary["by_x2"], key=lambda value: int(value, 0))
                            }
                if args.summary_json is not None:
                    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
                    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.summary_only:
                    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return 0

        if args.assume_x2low7:
            grouped: dict[int, list[tuple[int, str]]] = {}
            for x1, x2, label in cases:
                grouped.setdefault(x1, []).append((x2, label))

            for x1, x2_labels in grouped.items():
                group_label = f"x1_{x1:x}_x6_{args.x6:x}"
                input_path = base_dir / f"{group_label}.json"
                cnf_path = base_dir / f"{group_label}.cnf"
                var_map_path = base_dir / f"{group_label}.vars.json"
                arith_bits = args.arith_bits
                if args.exact_tail_limbs is not None:
                    arith_bits = args.T + args.limb_bits * args.exact_tail_limbs
                payload = {
                    "T": args.T,
                    "limb_bits": args.limb_bits,
                    "tail_limbs": args.tail_limbs,
                    "arithmetic_bits": arith_bits,
                    "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                    "skip_known_prefix_bits": args.skip_known_prefix_bits,
                        "tail_window_start": args.tail_window_start or 0,
                        "tail_window_bits": args.tail_window_bits,
                        "tail_window_carry_bits": args.tail_window_carry_bits,
                        "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                        "exact_carry_bits": args.exact_carry_bits,
                        "lowlift_q_bits": args.lowlift_q,
                        "q_interval_bound": args.q_interval_bound,
                    "odd_residue_primes": args.odd_residue_prime,
                    "no_comments": True,
                    "n": hex(n),
                    "known_p": hex(known),
                    "mask_p": hex(mask),
                    "branch_low": args.branch_low,
                    "branch_high": args.branch_high,
                    "fixed_p_ranges": [
                        {"start": 784, "width": 46, "value": hex(args.x6)},
                        {"start": 210, "width": 39, "value": hex(x1)},
                    ] + extra_fixed_p_ranges,
                }
                input_path.write_text(json.dumps(payload), encoding="utf-8")
                subprocess.run(
                    [str(go_binary), "-input", str(input_path), "-out", str(cnf_path), "-var-map", str(var_map_path), "-no-comments"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                cnf = CNF(from_file=str(cnf_path))
                var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
                with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                    for x2, label in x2_labels:
                        assumptions = x2low7_assumptions(var_map, x2)
                        sat = solver.solve(assumptions=assumptions)
                        print(
                            json.dumps(
                                {
                                    "label": label,
                                    "x1": hex(x1),
                                    "x2low7": hex(x2),
                                    "x6": hex(args.x6),
                                    "T": args.T,
                                    "arith_bits": arith_bits,
                                    "exact_tail_limbs": args.exact_tail_limbs,
                                    "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                                    "skip_known_prefix_bits": args.skip_known_prefix_bits,
                                        "tail_window_start": args.tail_window_start or args.T,
                                        "tail_window_bits": args.tail_window_bits,
                                        "tail_window_carry_bits": args.tail_window_carry_bits,
                                        "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                                        "exact_carry_bits": args.exact_carry_bits,
                                        "lowlift_q_bits": args.lowlift_q,
                                        "q_interval_bound": args.q_interval_bound,
                                    "odd_residue_primes": args.odd_residue_prime,
                                    "assume_x2low7": True,
                                    "vars": cnf.nv,
                                    "clauses": len(cnf.clauses),
                                    "assumptions": len(assumptions),
                                    "sat": sat,
                                }
                            ),
                            flush=True,
                        )
                if not args.keep_cnf:
                    cnf_path.unlink(missing_ok=True)
                    input_path.unlink(missing_ok=True)
                    var_map_path.unlink(missing_ok=True)
            return 0

        direct_summary = {"sat": 0, "unsat": 0, "build_count": 0, "rows": [], "sat_rows": []} if args.summary_json is not None or args.summary_only else None
        for x1, x2, label in cases:
            sweep_values = fix_p_sweep_values if fix_p_sweep_values is not None else [None]
            for fix_p_sweep_value in sweep_values:
                arith_bits = args.arith_bits
                if args.exact_tail_limbs is not None:
                    arith_bits = args.T + args.limb_bits * args.exact_tail_limbs
                run_label = label
                fixed_ranges = list(extra_fixed_p_ranges)
                fix_p_sweep_row = None
                if fix_p_sweep_value is not None:
                    assert fix_p_sweep_start is not None
                    suffix_width = max(1, (fix_p_sweep_width + 3) // 4)
                    run_label = f"{label}_p{fix_p_sweep_start}_{fix_p_sweep_width}_{fix_p_sweep_value:0{suffix_width}x}"
                    fixed_ranges.append({"start": fix_p_sweep_start, "width": fix_p_sweep_width, "value": hex(fix_p_sweep_value)})
                    fix_p_sweep_row = {
                        "start": fix_p_sweep_start,
                        "width": fix_p_sweep_width,
                        "value": hex(fix_p_sweep_value),
                    }
                input_path = base_dir / f"{run_label}.json"
                cnf_path = base_dir / f"{run_label}.cnf"
                var_map_path = base_dir / f"{run_label}.vars.json"
                payload = {
                    "T": args.T,
                    "limb_bits": args.limb_bits,
                    "tail_limbs": args.tail_limbs,
                    "arithmetic_bits": arith_bits,
                    "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                    "skip_known_prefix_bits": args.skip_known_prefix_bits,
                    "tail_window_start": args.tail_window_start or 0,
                    "tail_window_bits": args.tail_window_bits,
                    "tail_window_carry_bits": args.tail_window_carry_bits,
                    "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                    "exact_carry_bits": args.exact_carry_bits,
                    "lowlift_q_bits": args.lowlift_q,
                    "q_interval_bound": args.q_interval_bound,
                    "odd_residue_primes": args.odd_residue_prime,
                    "no_comments": True,
                    "n": hex(n),
                    "known_p": hex(known),
                    "mask_p": hex(mask),
                    "branch_low": args.branch_low,
                    "branch_high": args.branch_high,
                    "fixed_p_ranges": [
                        {"start": 784, "width": 46, "value": hex(args.x6)},
                        {"start": 210, "width": 39, "value": hex(x1)},
                        {"start": 265, "width": 7, "value": hex(x2)},
                    ] + fixed_ranges,
                }
                input_path.write_text(json.dumps(payload), encoding="utf-8")
                exporter_cmd = [str(go_binary), "-input", str(input_path), "-out", str(cnf_path), "-no-comments"]
                if assume_p_values is not None:
                    exporter_cmd.extend(["-var-map", str(var_map_path)])
                exporter = subprocess.run(
                    exporter_cmd,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if exporter.returncode != 0:
                    print(exporter.stderr.strip(), file=sys.stderr)
                    raise subprocess.CalledProcessError(exporter.returncode, exporter.args)
                if args.build_only:
                    vars_count, clauses_count = dimacs_stats(cnf_path)
                    row = {
                        "label": run_label,
                        "x1": hex(x1),
                        "x2low7": hex(x2),
                        "x6": hex(args.x6),
                        "T": args.T,
                        "arith_bits": arith_bits,
                        "exact_tail_limbs": args.exact_tail_limbs,
                        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                        "skip_known_prefix_bits": args.skip_known_prefix_bits,
                        "tail_window_start": args.tail_window_start or args.T,
                        "tail_window_bits": args.tail_window_bits,
                        "tail_window_carry_bits": args.tail_window_carry_bits,
                        "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                        "exact_carry_bits": args.exact_carry_bits,
                        "lowlift_q_bits": args.lowlift_q,
                        "q_interval_bound": args.q_interval_bound,
                        "odd_residue_primes": args.odd_residue_prime,
                        "build_only": True,
                        "vars": vars_count,
                        "clauses": clauses_count,
                        "sat": None,
                    }
                    if fix_p_sweep_row is not None:
                        row["fix_p_range_sweep"] = fix_p_sweep_row
                    if direct_summary is not None:
                        direct_summary["build_count"] += 1
                        direct_summary["rows"].append(row)
                    if not args.summary_only:
                        print(json.dumps(row), flush=True)
                    if not args.keep_cnf:
                        cnf_path.unlink(missing_ok=True)
                        input_path.unlink(missing_ok=True)
                        var_map_path.unlink(missing_ok=True)
                    continue
                cnf = CNF(from_file=str(cnf_path))
                if assume_p_values is not None:
                    var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
                    with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                        for assume_p_value in assume_p_values:
                            assumptions: list[int] = []
                            assert assume_p_start is not None
                            for off in range(assume_p_width):
                                name = f"p_{assume_p_start + off}"
                                try:
                                    var = int(var_map[name])
                                except KeyError as exc:
                                    raise RuntimeError(f"Go var-map does not contain {name}") from exc
                                assumptions.append(var if (assume_p_value >> off) & 1 else -var)
                            sat = solver.solve(assumptions=assumptions)
                            row = {
                                "label": run_label,
                                "x1": hex(x1),
                                "x2low7": hex(x2),
                                "x6": hex(args.x6),
                                "T": args.T,
                                "arith_bits": arith_bits,
                                "exact_tail_limbs": args.exact_tail_limbs,
                                "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                                "skip_known_prefix_bits": args.skip_known_prefix_bits,
                                "tail_window_start": args.tail_window_start or args.T,
                                "tail_window_bits": args.tail_window_bits,
                                "tail_window_carry_bits": args.tail_window_carry_bits,
                                "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                                "exact_carry_bits": args.exact_carry_bits,
                                "lowlift_q_bits": args.lowlift_q,
                                "q_interval_bound": args.q_interval_bound,
                                "odd_residue_primes": args.odd_residue_prime,
                                "assume_p_range": {
                                    "start": assume_p_start,
                                    "width": assume_p_width,
                                    "value": hex(assume_p_value),
                                },
                                "vars": cnf.nv,
                                "clauses": len(cnf.clauses),
                                "assumptions": len(assumptions),
                                "sat": sat,
                            }
                            if direct_summary is not None:
                                if sat:
                                    direct_summary["sat"] += 1
                                    direct_summary["sat_rows"].append(row)
                                else:
                                    direct_summary["unsat"] += 1
                                direct_summary["rows"].append(row)
                            if not args.summary_only:
                                print(json.dumps(row), flush=True)
                    if not args.keep_cnf:
                        cnf_path.unlink(missing_ok=True)
                        input_path.unlink(missing_ok=True)
                        var_map_path.unlink(missing_ok=True)
                    continue
                with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                    sat = solver.solve()
                row = {
                    "label": run_label,
                    "x1": hex(x1),
                    "x2low7": hex(x2),
                    "x6": hex(args.x6),
                    "T": args.T,
                    "arith_bits": arith_bits,
                    "exact_tail_limbs": args.exact_tail_limbs,
                    "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
                    "skip_known_prefix_bits": args.skip_known_prefix_bits,
                    "tail_window_start": args.tail_window_start or args.T,
                    "tail_window_bits": args.tail_window_bits,
                    "tail_window_carry_bits": args.tail_window_carry_bits,
                    "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                    "exact_carry_bits": args.exact_carry_bits,
                    "lowlift_q_bits": args.lowlift_q,
                    "q_interval_bound": args.q_interval_bound,
                    "odd_residue_primes": args.odd_residue_prime,
                    "vars": cnf.nv,
                    "clauses": len(cnf.clauses),
                    "sat": sat,
                }
                if fix_p_sweep_row is not None:
                    row["fix_p_range_sweep"] = fix_p_sweep_row
                if direct_summary is not None:
                    if sat:
                        direct_summary["sat"] += 1
                        direct_summary["sat_rows"].append(row)
                    else:
                        direct_summary["unsat"] += 1
                    direct_summary["rows"].append(row)
                if not args.summary_only:
                    print(json.dumps(row), flush=True)
                if not args.keep_cnf:
                    cnf_path.unlink(missing_ok=True)
                    input_path.unlink(missing_ok=True)
                    var_map_path.unlink(missing_ok=True)
        if direct_summary is not None:
            if args.summary_json is not None:
                args.summary_json.parent.mkdir(parents=True, exist_ok=True)
                args.summary_json.write_text(json.dumps(direct_summary, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.summary_only:
                print(json.dumps(direct_summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        if workdir_context is not None:
            workdir_context.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
