#!/usr/bin/env python3
"""Lightweight checks for the challenge 7 SAT+CAS exploration helpers."""

from __future__ import annotations

import unittest

import z3

from sat_cas_core import (
    FixedRange,
    QKnownBits,
    derive_q_known_bits,
    load_instance,
    z3_hensel_prefix_status,
    z3_product_prefix_status,
)
from q_middle_gap_oracle import q_gap_bound_report, q_gap_known_parts
from semi_programmatic_sat import (
    add_bit_value_block_clause,
    learned_clause_bit_value_variants,
    learned_clause_bit_values,
)


class SatCasCoreTest(unittest.TestCase):
    def test_unknown_ranges_match_problem_mask(self) -> None:
        instance = load_instance()
        self.assertEqual(
            instance.unknown_ranges(),
            [
                (150, 153),
                (265, 348),
                (362, 419),
                (600, 668),
                (682, 768),
                (784, 829),
                (920, 923),
            ],
        )

    def test_q_low_expands_when_low_runs_are_fixed(self) -> None:
        instance = load_instance()
        p_known, p_mask = instance.apply_fixed_ranges(
            [
                FixedRange(150, 4, 0),
                FixedRange(265, 84, 0),
                FixedRange(362, 58, 0),
            ]
        )
        q_known = derive_q_known_bits(instance, p_known, p_mask)
        self.assertEqual(q_known.low_bits, 600)
        self.assertEqual(
            ((p_known & ((1 << 600) - 1)) * (q_known.known & ((1 << 600) - 1)) - instance.n)
            % (1 << 600),
            0,
        )

    def test_product_prefix_oracle_reports_sat_for_base_instance(self) -> None:
        instance = load_instance()
        status, meta = z3_product_prefix_status(instance, instance.known, instance.mask, 64, 1000)
        self.assertEqual(status, "sat")
        self.assertGreater(meta["p_fixed_bits_in_prefix"], 0)

    def test_product_prefix_oracle_can_prove_oddness_contradiction(self) -> None:
        instance = load_instance()
        status, _ = z3_product_prefix_status(instance, instance.known & ~1, instance.mask | 1, 8, 1000)
        self.assertEqual(status, "unsat")

    def test_hensel_prefix_oracle_reports_sat_for_base_instance(self) -> None:
        instance = load_instance()
        status, meta = z3_hensel_prefix_status(instance, instance.known, instance.mask, 64, 1000)
        self.assertEqual(status, "sat")
        self.assertEqual(meta["method"], "z3_hensel_bits")

    def test_q_gap_bound_uses_middle_gap_not_low_tail(self) -> None:
        instance = load_instance()
        report = q_gap_bound_report(
            n=instance.n,
            low_bits=608,
            prefix_start=728,
            epsilon=0.02,
            min_hard_margin_bits=8.0,
        )
        self.assertEqual(report["q_gap_bits"], 120)
        self.assertEqual(report["root_bound_bits"], 120)
        self.assertGreater(report["effective_margin_bits"], 300)
        self.assertTrue(report["hard_clause_bound_eligible"])

    def test_q_gap_known_parts_keep_low_and_high_constant(self) -> None:
        q_known = QKnownBits(
            known=0xB000 | 0x000A,
            mask=0xF000 | 0x000F,
            low_bits=4,
            prefix_bits=4,
            prefix_start=12,
            q_min=0,
            q_max=0,
        )
        parts = q_gap_known_parts(q_known, q_bits=16)
        self.assertEqual(parts["gap_bits"], 8)
        self.assertEqual(parts["q_lo"], 0x000A)
        self.assertEqual(parts["q_hi"], 0xB000)
        self.assertEqual(parts["const"], 0xB00A)

    def test_learned_clause_bit_values_expand_ranges_and_drop_bits(self) -> None:
        bit_values, status = learned_clause_bit_values(
            {
                "event": "cube",
                "learned_clause": "q_gap_coppersmith_no_root",
                "cube_ranges": [{"start": 10, "width": 4, "value": 0b1010}],
                "learned_clause_dropped_bits": [11],
            }
        )
        self.assertEqual(status, "ok")
        self.assertEqual(bit_values, {10: 0, 12: 0, 13: 1})

    def test_learned_clause_variants_expand_independent_drops(self) -> None:
        rows = learned_clause_bit_value_variants(
            {
                "event": "cube",
                "learned_clause": "q_gap_coppersmith_no_root",
                "cube_ranges": [{"start": 10, "width": 4, "value": 0b1010}],
                "learned_clause_variants": [
                    {"dropped_bits": [10, 11]},
                    {"dropped_bits": [12, 13]},
                ],
            }
        )
        self.assertEqual(rows[0], ({12: 0, 13: 1}, "ok"))
        self.assertEqual(rows[1], ({10: 0, 11: 1}, "ok"))

    def test_add_bit_value_block_clause_blocks_exact_assignment(self) -> None:
        solver = z3.Solver()
        bit_vars = {10: z3.Bool("p10"), 11: z3.Bool("p11")}
        status, literal_count = add_bit_value_block_clause(
            solver=solver,
            bit_vars=bit_vars,
            base_known=0,
            base_mask=0,
            p_bits=1024,
            bit_values={10: 0, 11: 1},
        )
        self.assertEqual(status, "added")
        self.assertEqual(literal_count, 2)
        solver.push()
        solver.add(bit_vars[10] == False, bit_vars[11] == True)  # noqa: E712
        self.assertEqual(solver.check(), z3.unsat)
        solver.pop()
        solver.add(bit_vars[10] == True, bit_vars[11] == True)  # noqa: E712
        self.assertEqual(solver.check(), z3.sat)


if __name__ == "__main__":
    unittest.main()
