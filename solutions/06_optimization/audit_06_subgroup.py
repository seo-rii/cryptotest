#!/usr/bin/env -S sage -python
"""Independent Sage audit for the Problem-6 curve and subgroup filter.

The default audit checks the original and isomorphic ``a=-3`` curves, ``P=dQ``,
the group order/cyclicity witness, rational and Frobenius-minus order-5 points,
tangent constants, the 11 ``mu_20`` traces, and deterministic subgroup samples.
For every sample it compares:

1. direct ``[n]T == O`` membership;
2. the old ``L_((p+1)/5) == 2`` trace criterion; and
3. the new ``L_((p+1)/100) in Tr(mu_20)`` criterion.

It also expands the original Fp2 Miller numerator
``(y+v*A)^2*(y+v*B)``, proves the resulting polynomial identity, and checks
that its Frobenius quotient trace equals the rational x-only formula used by
``deep_native_06.cpp``.  Finally, it cancels the common ``(x-gamma)^4`` factor
symbolically and verifies all five coefficients of the reciprocal polynomial
in ``z=(x-alpha)^-1``.

Run from the repository root:

    sage -python solutions/06_optimization/audit_06_subgroup.py
    sage -python solutions/06_optimization/audit_06_subgroup.py --full-prefix

``--full-prefix`` additionally scans the complete shifted prefix
``low=0..0x3cea`` and asserts the documented 7,713 valid lifts and 1,547
order-n members.  SageMath 9.5 or newer is sufficient; no Python package beyond
Sage is required.
"""

import argparse
import json
import random

from sage.all import EllipticCurve, GF, Integer, PolynomialRing, inverse_mod


P_FIELD = Integer("d9047b5f32dda5ca6f569b", 16)
CURVE_A = Integer("674fdf5b55923897a16f40", 16)
CURVE_B = Integer("1d0c9956783f6026e6c981", 16)
ORDER = Integer("2b674bdfd6fc4ba4ba751d", 16)
POINT_P = (
    Integer("5340e87bd80d1463a6ff8d", 16),
    Integer("94ebeb5ca5b3c685e00c20", 16),
)
POINT_Q = (
    Integer("4a05101411039decf537a5", 16),
    Integer("3395a009c2210836b63d4b", 16),
)
BACKDOOR_D = Integer("1c3cdd6b221806db0a7b28", 16)

TRANSFORMED_A = -3
TRANSFORMED_B = Integer("5e7dc2bc27aea7935c6b6", 16)
ORIGINAL_X_FROM_TRANSFORMED_SCALE = Integer(
    "9b4427ecf55d466c0bbf44", 16
)
TRANSFORMED_X_MONTGOMERY_R2 = Integer(
    "92c54f3ef7e023efbc8e5b", 16
)

SUBGROUP_ALPHA = Integer("d59dbc5a89d7c3dcfc7aef", 16)
SUBGROUP_BETA = Integer("c34366b11d118d0d635fbb", 16)
SUBGROUP_GAMMA = Integer("0e953f99abc72cff8f3ff9", 16)
SUBGROUP_DELTA = Integer("94b152fc315f97ae6ea4c7", 16)
SUBGROUP_TANGENT_M1 = Integer("d1e74749596975d56c869e", 16)
SUBGROUP_TANGENT_M2 = Integer("3a7862416ae71b5fea671e", 16)
SUBGROUP_RATIONAL_TORSION_X = Integer("20b363e845196f8282e59d", 16)
SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS = tuple(
    Integer(value, 16)
    for value in (
        "c97682b97af7f9b83508b1",
        "6f977142976da7c6e471f8",
        "b56d7f4f899680f860ef2b",
        "a70788aa8b9edb2fe870f2",
        "a1a50d0fa2d3c77e33b7da",
    )
)
SUBGROUP_ROOT_TRACES = {
    Integer(value, 16)
    for value in (
        "2",
        "49321ac5168966c4e21a84",
        "464f7cf080ef9f665193b9",
        "bf1ef683b3802a2312bcf5",
        "464f7cf080ef9f665193b8",
        "0",
        "92b4fe6eb1ee06641dc2e3",
        "19e584db7f5d7ba75c99a6",
        "92b4fe6eb1ee06641dc2e2",
        "8fd2609a1c543f058d3c17",
        "d9047b5f32dda5ca6f5699",
    )
}

SHIFTED_OUTPUT = Integer("617985fad38ec3b1a3", 16)
SHIFTED_LOW = 0x3CEA
EXPECTED_CURVE_LIFTS = 7713
EXPECTED_SUBGROUP_LIFTS = 1547


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def lucas_pair(trace, exponent):
    """Return ``(L_exponent,L_(exponent+1))`` in the base field."""

    if exponent == 0:
        return trace.parent()(2), trace
    left, right = lucas_pair(trace, exponent // 2)
    even = left * left - 2
    odd = left * right - trace
    if exponent % 2 == 0:
        return even, odd
    return odd, right * right - 2


def fp2_conjugate(value, v):
    coefficients = value.polynomial().list()
    constant = coefficients[0] if coefficients else value.parent().base_ring()(0)
    linear = coefficients[1] if len(coefficients) > 1 else value.parent().base_ring()(0)
    require(
        all(coefficient == 0 for coefficient in coefficients[2:]),
        "unexpected extension degree",
    )
    return value.parent()(constant) - value.parent()(linear) * v


def fp2_to_base(value, base_field):
    coefficients = value.polynomial().list()
    require(
        all(coefficient == 0 for coefficient in coefficients[1:]),
        f"value is not in the base field: {value}",
    )
    return base_field(coefficients[0] if coefficients else 0)


def find_primitive_twentieth_root(extension, v, base_field):
    """Deterministically find an order-20 element in the norm-one torus."""

    for constant in range(1, 256):
        candidate = extension(base_field(constant)) + v
        norm_one = candidate ** (P_FIELD - 1)
        root = norm_one ** ((P_FIELD + 1) // 20)
        if (
            root ** 20 == 1
            and root ** 10 != 1
            and root ** 4 != 1
        ):
            return root
    raise AssertionError("failed to construct an order-20 norm-one root")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples",
        type=int,
        default=200,
        help="deterministic whole-group samples in addition to fixed vectors",
    )
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0x06C0FFEE)
    parser.add_argument(
        "--full-prefix",
        action="store_true",
        help="audit every curve-valid shifted lift through low=0x3cea",
    )
    parser.add_argument("--json", action="store_true", help="emit a compact summary")
    args = parser.parse_args()
    if args.samples < 0:
        parser.error("--samples must be nonnegative")

    require(P_FIELD.is_prime(), "field modulus is not prime")
    require(ORDER.is_prime(), "subgroup order is not prime")
    require(P_FIELD % 5 == 4, "expected the non-basic-field p mod 5 = 4 case")

    base_field = GF(P_FIELD)
    original_curve = EllipticCurve(base_field, [base_field(CURVE_A), base_field(CURVE_B)])
    point_p = original_curve(base_field(POINT_P[0]), base_field(POINT_P[1]))
    point_q = original_curve(base_field(POINT_Q[0]), base_field(POINT_Q[1]))
    require(BACKDOOR_D * point_q == point_p, "P != dQ")
    require(ORDER * point_q == original_curve(0), "[n]Q is not infinity")
    require(point_q != original_curve(0), "Q is infinity")

    group_order = original_curve.cardinality()
    require(group_order == 5 * ORDER, "unexpected curve cardinality")

    scale = base_field(ORIGINAL_X_FROM_TRANSFORMED_SCALE)
    transformed_b = base_field(TRANSFORMED_B)
    require(
        base_field(CURVE_A) / scale ** 2 == base_field(TRANSFORMED_A),
        "a=-3 coefficient transform failed",
    )
    require(
        base_field(CURVE_B) / scale ** 3 == transformed_b,
        "transformed b coefficient mismatch",
    )
    require(scale.is_square(), "x-coordinate scale has no compatible y scale")
    y_scale = (scale ** 3).sqrt()
    transformed_curve = EllipticCurve(
        base_field, [base_field(TRANSFORMED_A), transformed_b]
    )

    def to_transformed(point):
        if point == original_curve(0):
            return transformed_curve(0)
        return transformed_curve(point[0] / scale, point[1] / y_scale)

    transformed_p = to_transformed(point_p)
    transformed_q = to_transformed(point_q)
    require(BACKDOOR_D * transformed_q == transformed_p, "isomorphism broke P=dQ")
    require(ORDER * transformed_q == transformed_curve(0), "transformed Q order mismatch")

    montgomery_r = Integer(1) << 128
    expected_transformed_r2 = (
        montgomery_r ** 2 * inverse_mod(ORIGINAL_X_FROM_TRANSFORMED_SCALE, P_FIELD)
    ) % P_FIELD
    require(
        expected_transformed_r2 == TRANSFORMED_X_MONTGOMERY_R2,
        "transformed Montgomery R2 constant mismatch",
    )

    rational_x = base_field(SUBGROUP_RATIONAL_TORSION_X)
    rational_rhs = rational_x ** 3 - 3 * rational_x + transformed_b
    require(rational_rhs.is_square(), "rational order-5 x does not lift")
    rational_five = transformed_curve(rational_x, rational_rhs.sqrt())
    require(5 * rational_five == transformed_curve(0), "rational torsion is not 5-torsion")
    require(rational_five != transformed_curve(0), "rational torsion is infinity")

    # Q has prime order n, rational_five has prime order 5, and the curve has
    # exactly 5n points.  Their sum is therefore an explicit cyclic generator.
    cyclic_generator = transformed_q + rational_five
    require((5 * ORDER) * cyclic_generator == transformed_curve(0), "bad group exponent")
    require(ORDER * cyclic_generator != transformed_curve(0), "generator lacks 5-part")
    require(5 * cyclic_generator != transformed_curve(0), "generator lacks n-part")

    polynomial_ring = PolynomialRing(base_field, "z")
    z = polynomial_ring.gen()
    require(not base_field(2).is_square(), "v^2-2 unexpectedly splits over Fp")
    extension = base_field.extension(z ** 2 - 2, names=("v",))
    v = extension.gen()
    require(v ** P_FIELD == -v, "Frobenius does not send v to -v")
    transformed_curve_fp2 = transformed_curve.base_extend(extension)

    # Symbolically expand f=(Y+v*A)^2*(Y+v*B), representing Fp2 elements as
    # (real, v-coefficient) pairs with v^2=2.  This proves the C/D and U/V
    # rational trace formulas independently of any sampled curve point.
    identity_ring = PolynomialRing(base_field, names=("Y", "A", "B"))
    symbolic_y, symbolic_a, symbolic_b = identity_ring.gens()
    symbolic_rhs = symbolic_y ** 2
    symbolic_c = (
        symbolic_rhs
        + 2 * symbolic_a ** 2
        + 4 * symbolic_a * symbolic_b
    )
    symbolic_d = -(
        (symbolic_rhs + 2 * symbolic_a ** 2) * symbolic_b
        + 2 * symbolic_rhs * symbolic_a
    )
    squared_real = symbolic_rhs + 2 * symbolic_a ** 2
    squared_imaginary = 2 * symbolic_y * symbolic_a
    product_real = squared_real * symbolic_y + 2 * squared_imaginary * symbolic_b
    product_imaginary = squared_real * symbolic_b + squared_imaginary * symbolic_y
    require(product_real == symbolic_y * symbolic_c, "symbolic Miller real part failed")
    require(product_imaginary == -symbolic_d, "symbolic Miller v-part failed")
    symbolic_u = symbolic_rhs * symbolic_c ** 2
    symbolic_v = 2 * symbolic_d ** 2
    require(
        product_real ** 2 - 2 * product_imaginary ** 2
        == symbolic_u - symbolic_v,
        "symbolic Miller norm denominator failed",
    )
    require(
        2 * (product_real ** 2 + 2 * product_imaginary ** 2)
        == 2 * (symbolic_u + symbolic_v),
        "symbolic Frobenius trace numerator failed",
    )

    alpha = base_field(SUBGROUP_ALPHA)
    beta = base_field(SUBGROUP_BETA)
    gamma = base_field(SUBGROUP_GAMMA)
    delta = base_field(SUBGROUP_DELTA)
    tangent_m1 = base_field(SUBGROUP_TANGENT_M1)
    tangent_m2 = base_field(SUBGROUP_TANGENT_M2)
    frobenius_five = transformed_curve_fp2(
        extension(alpha), extension(beta) * v
    )
    require(
        5 * frobenius_five == transformed_curve_fp2(0),
        "Frobenius point is not 5-torsion",
    )
    require(
        transformed_curve_fp2(
            frobenius_five[0] ** P_FIELD,
            frobenius_five[1] ** P_FIELD,
        )
        == -frobenius_five,
        "order-5 point is not in the Frobenius -1 eigenspace",
    )
    doubled_five = 2 * frobenius_five
    require(
        doubled_five[0] == extension(gamma)
        and doubled_five[1] == extension(delta) * v,
        "2P- coordinates do not match gamma/delta",
    )
    require(
        (3 * alpha ** 2 - 3) / (4 * beta) == tangent_m1,
        "first tangent coefficient mismatch",
    )
    require(
        (3 * gamma ** 2 - 3) / (4 * delta) == tangent_m2,
        "second tangent coefficient mismatch",
    )

    # Expand the C++ trace formula as polynomials in x.  Its denominator has
    # the exact factorization
    #
    #   U - V = (x-gamma)^4 (x-alpha)^5,
    #
    # while the numerator has the same removable fourth-power factor.  After
    # cancellation, dividing by (x-alpha)^5 gives the five checked-in
    # reciprocal coefficients.
    x_ring = PolynomialRing(base_field, "X")
    x_variable = x_ring.gen()
    x_rhs = x_variable ** 3 - 3 * x_variable + transformed_b
    x_a = beta + tangent_m1 * (x_variable - alpha)
    x_b = delta + tangent_m2 * (x_variable - gamma)
    x_rhs_plus_two_a_squared = x_rhs + 2 * x_a ** 2
    x_c = x_rhs_plus_two_a_squared + 4 * x_a * x_b
    x_d = -(x_rhs_plus_two_a_squared * x_b + 2 * x_rhs * x_a)
    x_u = x_rhs * x_c ** 2
    x_v = 2 * x_d ** 2
    cancelled_factor = (x_variable - gamma) ** 4
    reciprocal_denominator = (x_variable - alpha) ** 5
    reciprocal_numerator = 2 * reciprocal_denominator
    for index, coefficient in enumerate(
        SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS
    ):
        reciprocal_numerator += (
            base_field(coefficient)
            * (x_variable - alpha) ** (4 - index)
        )
    require(
        x_u - x_v == cancelled_factor * reciprocal_denominator,
        "expanded trace denominator factorization failed",
    )
    require(
        2 * (x_u + x_v) == cancelled_factor * reciprocal_numerator,
        "reciprocal trace coefficients do not match the expanded formula",
    )

    twentieth_root = find_primitive_twentieth_root(extension, v, base_field)
    generated_root_traces = set()
    for exponent in range(20):
        trace = twentieth_root ** exponent + twentieth_root ** (-exponent)
        require(trace ** P_FIELD == trace, "mu_20 trace escaped Fp")
        generated_root_traces.add(Integer(fp2_to_base(trace, base_field)))
    require(
        generated_root_traces == SUBGROUP_ROOT_TRACES,
        "checked-in mu_20 trace table mismatch",
    )

    old_exponent = (P_FIELD + 1) // 5
    new_exponent = (P_FIELD + 1) // 100
    require(old_exponent == 20 * new_exponent, "expected E=20H")
    root_trace_field = {base_field(value) for value in SUBGROUP_ROOT_TRACES}
    for trace in root_trace_field:
        require(lucas_pair(trace, 20)[0] == 2, "invalid mu_20 trace")
    trace_ring = PolynomialRing(base_field, "T")
    trace_variable = trace_ring.gen()
    all_twentieth_roots = set(
        (lucas_pair(trace_variable, 20)[0] - 2).roots(multiplicities=False)
    )
    require(
        all_twentieth_roots == root_trace_field,
        "mu_20 table is not the complete root set of L_20(T)-2",
    )

    def trace_and_membership(point, crosscheck_fp2):
        require(point != transformed_curve(0), "cannot trace infinity")
        x = base_field(point[0])
        y = base_field(point[1])
        rhs = y ** 2
        a_value = beta + tangent_m1 * (x - alpha)
        b_value = delta + tangent_m2 * (x - gamma)
        a_squared = a_value ** 2
        rhs_plus_two_a_squared = rhs + 2 * a_squared
        c_value = rhs_plus_two_a_squared + 4 * a_value * b_value
        d_value = -(rhs_plus_two_a_squared * b_value + 2 * rhs * a_value)
        u_value = rhs * c_value ** 2
        v_value = 2 * d_value ** 2
        denominator = u_value - v_value
        require(denominator != 0, "x-only trace denominator is zero")
        rational_trace = 2 * (u_value + v_value) / denominator
        reciprocal = 1 / (x - alpha)
        reciprocal_trace = base_field(2)
        reciprocal_power = reciprocal
        for coefficient in SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS:
            reciprocal_trace += base_field(coefficient) * reciprocal_power
            reciprocal_power *= reciprocal
        require(
            reciprocal_trace == rational_trace,
            "reciprocal and expanded x-only traces differ",
        )

        if crosscheck_fp2:
            # Vertical Miller denominators are in Fp and cancel from f^p/f.
            miller_numerator = (
                (extension(y) + v * extension(a_value)) ** 2
                * (extension(y) + v * extension(b_value))
            )
            require(miller_numerator != 0, "Miller numerator is zero")
            conjugate = fp2_conjugate(miller_numerator, v)
            require(
                conjugate == miller_numerator ** P_FIELD,
                "explicit conjugation differs from Frobenius",
            )
            quotient = conjugate / miller_numerator
            require(quotient * fp2_conjugate(quotient, v) == 1, "quotient norm is not one")
            direct_trace = quotient + 1 / quotient
            require(
                fp2_to_base(direct_trace, base_field) == rational_trace,
                "direct Fp2 and rational x-only traces differ",
            )
            require(
                trace_and_membership(-point, False)[0] == rational_trace,
                "trace unexpectedly depends on lift sign",
            )

        direct_member = ORDER * point == transformed_curve(0)
        old_member = lucas_pair(rational_trace, old_exponent)[0] == 2
        new_trace = lucas_pair(rational_trace, new_exponent)[0]
        new_member = new_trace in root_trace_field
        require(
            direct_member == old_member == new_member,
            "direct/old/new subgroup decisions differ",
        )
        return rational_trace, direct_member

    fixed_points = [
        transformed_q,
        rational_five,
        transformed_q + rational_five,
        2 * rational_five,
    ]
    sample_members = 0
    for point in fixed_points:
        _, member = trace_and_membership(point, True)
        sample_members += int(member)

    rng = random.Random(int(args.seed))
    for _ in range(args.samples):
        scalar = rng.randrange(1, int(5 * ORDER))
        point = scalar * cyclic_generator
        require(point != transformed_curve(0), "sample unexpectedly hit infinity")
        _, member = trace_and_membership(point, True)
        sample_members += int(member)

    prefix_valid = None
    prefix_members = None
    if args.full_prefix:
        prefix_valid = 0
        prefix_members = 0
        for low in range(SHIFTED_LOW + 1):
            original_x = (SHIFTED_OUTPUT << 16) | low
            require(original_x < P_FIELD, "shifted x candidate exceeds the field")
            transformed_x = base_field(original_x) / scale
            rhs = transformed_x ** 3 - 3 * transformed_x + transformed_b
            if not rhs.is_square():
                continue
            point = transformed_curve(transformed_x, rhs.sqrt())
            _, member = trace_and_membership(point, False)
            prefix_valid += 1
            prefix_members += int(member)
        require(
            prefix_valid == EXPECTED_CURVE_LIFTS,
            f"shifted prefix has {prefix_valid} curve lifts",
        )
        require(
            prefix_members == EXPECTED_SUBGROUP_LIFTS,
            f"shifted prefix has {prefix_members} subgroup members",
        )

    summary = {
        "curve_order": int(group_order),
        "cyclic_witness": True,
        "deterministic_members": int(sample_members),
        "deterministic_vectors": int(args.samples + len(fixed_points)),
        "frobenius_torsion": True,
        "isomorphism": True,
        "mu20_traces": len(generated_root_traces),
        "p_equals_dq": True,
        "prefix_members": None if prefix_members is None else int(prefix_members),
        "prefix_valid_lifts": None if prefix_valid is None else int(prefix_valid),
        "trace_identity": True,
        "reciprocal_trace_identity": True,
        "trace_identity_symbolic": True,
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"curve/order OK: #E(Fp)=5*n={group_order}, cyclic witness verified")
        print("isomorphism/P=dQ/torsion/tangent constants OK")
        print(
            "trace identity and subgroup criteria OK: "
            f"{args.samples + len(fixed_points)} deterministic vectors"
        )
        print(f"mu_20 trace table OK: {len(generated_root_traces)} unique values")
        if args.full_prefix:
            print(
                "shifted prefix OK: "
                f"{prefix_valid} curve lifts, {prefix_members} subgroup members"
            )


if __name__ == "__main__":
    main()
