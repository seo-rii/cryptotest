// Challenge 6: optimized fixed-width Dual_EC state recovery.
//
// Native BMI2/ADX build (portable U128 fallback is selected automatically):
//   g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp
//       deep_native_06.cpp -o deep_native_06

#include <omp.h>

#if defined(__x86_64__)
#include <immintrin.h>
#endif

#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using U128 = unsigned __int128;

constexpr U128 parse_hex(std::string_view text) {
    U128 value = 0;
    for (const char character : text) {
        unsigned digit = 0;
        if (character >= '0' && character <= '9') {
            digit = static_cast<unsigned>(character - '0');
        } else if (character >= 'a' && character <= 'f') {
            digit = static_cast<unsigned>(character - 'a') + 10U;
        } else if (character >= 'A' && character <= 'F') {
            digit = static_cast<unsigned>(character - 'A') + 10U;
        } else {
            continue;
        }
        value = (value << 4U) | digit;
    }
    return value;
}

constexpr U128 FIELD = parse_hex("d9047b5f32dda5ca6f569b");
constexpr U128 CURVE_A_CANON = parse_hex("674fdf5b55923897a16f40");
constexpr U128 CURVE_B_CANON = parse_hex("1d0c9956783f6026e6c981");
constexpr U128 ORDER = parse_hex("2b674bdfd6fc4ba4ba751d");
constexpr U128 POINT_P_X = parse_hex("5340e87bd80d1463a6ff8d");
constexpr U128 POINT_P_Y = parse_hex("94ebeb5ca5b3c685e00c20");
constexpr U128 POINT_Q_X = parse_hex("4a05101411039decf537a5");
constexpr U128 POINT_Q_Y = parse_hex("3395a009c2210836b63d4b");
constexpr U128 TRANSFORMED_CURVE_A =
    parse_hex("d9047b5f32dda5ca6f5698");
constexpr U128 TRANSFORMED_CURVE_B =
    parse_hex("5e7dc2bc27aea7935c6b6");
constexpr U128 SUBGROUP_ALPHA =
    parse_hex("d59dbc5a89d7c3dcfc7aef");
constexpr U128 SUBGROUP_BETA =
    parse_hex("c34366b11d118d0d635fbb");
constexpr U128 SUBGROUP_GAMMA =
    parse_hex("0e953f99abc72cff8f3ff9");
constexpr U128 SUBGROUP_DELTA =
    parse_hex("94b152fc315f97ae6ea4c7");
constexpr U128 SUBGROUP_TANGENT_M1 =
    parse_hex("d1e74749596975d56c869e");
constexpr U128 SUBGROUP_TANGENT_M2 =
    parse_hex("3a7862416ae71b5fea671e");
constexpr U128 SUBGROUP_RATIONAL_TORSION_X =
    parse_hex("20b363e845196f8282e59d");
// If z=(x-alpha)^-1, cancellation of the common (x-gamma)^4
// factor in the Frobenius--Tate trace gives
//
//   tau = 2 + c[0]z + c[1]z^2 + ... + c[4]z^5.
//
// The expanded formula remains available as an independent ablation and
// self-test oracle under CH6_EXPANDED_SUBGROUP_TRACE.
constexpr std::array<U128, 5> SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS{
    parse_hex("c97682b97af7f9b83508b1"),
    parse_hex("6f977142976da7c6e471f8"),
    parse_hex("b56d7f4f899680f860ef2b"),
    parse_hex("a70788aa8b9edb2fe870f2"),
    parse_hex("a1a50d0fa2d3c77e33b7da"),
};
constexpr U128 SUBGROUP_LUCAS_EXPONENT = (FIELD + 1U) / 5U;
constexpr U128 SUBGROUP_PRAC_EXPONENT =
    SUBGROUP_LUCAS_EXPONENT / 20U;
// Canonical values z + z^-1 for the 11 inversion orbits in mu_20.
constexpr std::array<U128, 11> SUBGROUP_20TH_ROOT_TRACES{
    parse_hex("2"),
    parse_hex("49321ac5168966c4e21a84"),
    parse_hex("464f7cf080ef9f665193b9"),
    parse_hex("bf1ef683b3802a2312bcf5"),
    parse_hex("464f7cf080ef9f665193b8"),
    parse_hex("0"),
    parse_hex("92b4fe6eb1ee06641dc2e3"),
    parse_hex("19e584db7f5d7ba75c99a6"),
    parse_hex("92b4fe6eb1ee06641dc2e2"),
    parse_hex("8fd2609a1c543f058d3c17"),
    parse_hex("d9047b5f32dda5ca6f5699"),
};
// Offline Montgomery-PRAC schedule for H=(p+1)/100 with seed
// r=0x1575ba2094b05be88186b.  The high bit requests a pre-swap and
// the low bits select a PRAC rule.  SHA-256:
// 18b8ddcc131e735e129646411153b5ad76d413e76087e42503cfd56f16a5d739.
constexpr std::array<std::uint8_t, 115> SUBGROUP_PRAC_SCHEDULE{
    0x03, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x03, 0x83, 0x83, 0x83, 0x83, 0x03, 0x83,
    0x03, 0x03, 0x83, 0x03, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x83, 0x03, 0x83, 0x83, 0x03, 0x83, 0x03,
    0x83, 0x83, 0x83, 0x83, 0x83, 0x83, 0x03, 0x83,
    0x83, 0x83, 0x83, 0x85, 0x03, 0x03, 0x03, 0x84,
    0x04, 0x04, 0x03, 0x83, 0x83, 0x83, 0x83, 0x83,
    0x83, 0x03, 0x83, 0x83, 0x83, 0x84, 0x03, 0x83,
    0x83, 0x83, 0x81, 0x03, 0x83, 0x83, 0x83, 0x83,
    0x03, 0x83, 0x83, 0x03, 0x03, 0x83, 0x83, 0x83,
    0x03, 0x03, 0x83,
};
constexpr U128 ORIGINAL_X_FROM_TRANSFORMED_SCALE =
    parse_hex("9b4427ecf55d466c0bbf44");
constexpr U128 TRANSFORMED_X_MONTGOMERY_R2 =
    parse_hex("92c54f3ef7e023efbc8e5b");
constexpr std::array<U128, 3> KNOWN_OUTPUTS{
    parse_hex("b3939f4aadcc13ca74"),
    parse_hex("617985fad38ec3b1a3"),
    parse_hex("d8c20715ccc94d2283"),
};
constexpr U128 EXPECTED_D = parse_hex("1c3cdd6b221806db0a7b28");
constexpr U128 EXPECTED_STATE_S2 = parse_hex("638d9d631ab436da51e640");
constexpr U128 EXPECTED_STATE_S3 = parse_hex("948173253ad6d120a3f562");
constexpr U128 EXPECTED_R3 = parse_hex("2443c8daf1a9d52b09");
constexpr int EXPECTED_LOW = 21304;
constexpr int EXPECTED_SHIFTED_LOW = 15594;

#if !defined(CH6_LEGACY_R0_SCAN)
constexpr std::size_t LIFT_OUTPUT_INDEX = 1;
constexpr std::size_t FILTER_OUTPUT_INDEX = 2;
constexpr U128 EXPECTED_SCAN_STATE = EXPECTED_STATE_S3;
constexpr int EXPECTED_SCAN_LOW = EXPECTED_SHIFTED_LOW;
constexpr std::string_view SCAN_STATE_LABEL = "s3";
#else
constexpr std::size_t LIFT_OUTPUT_INDEX = 0;
constexpr std::size_t FILTER_OUTPUT_INDEX = 1;
constexpr U128 EXPECTED_SCAN_STATE = EXPECTED_STATE_S2;
constexpr int EXPECTED_SCAN_LOW = EXPECTED_LOW;
constexpr std::string_view SCAN_STATE_LABEL = "s2";
#endif

#if !defined(CH6_PORTABLE_ARITHMETIC) && \
    !defined(CH6_GENERIC_MONTGOMERY) && defined(__x86_64__) && \
    defined(__BMI2__) && defined(__ADX__)
constexpr std::string_view FIELD_BACKEND = "bmi2-adx";
#elif !defined(CH6_GENERIC_MONTGOMERY)
constexpr std::string_view FIELD_BACKEND = "portable-u128-unrolled";
#else
constexpr std::string_view FIELD_BACKEND = "generic-carry-loop";
#endif

#if !defined(CH6_ORIGINAL_CURVE_SCAN)
constexpr std::string_view SCAN_CURVE_MODEL = "isomorphic-a-minus-3";
#else
constexpr std::string_view SCAN_CURVE_MODEL = "original-generic-a";
#endif

#if !defined(CH6_NAF_D_MULTIPLICATION)
constexpr std::string_view D_MULTIPLICATION = "hamburg-co-z";
#else
constexpr std::string_view D_MULTIPLICATION = "width-2-naf";
#endif

#if !defined(CH6_SQRT_LIFT) && !defined(CH6_NAF_D_MULTIPLICATION)
#if defined(CH6_SUBTRACTIVE_JACOBI)
constexpr std::string_view LIFT_RESIDUE_TEST =
    "subtractive-jacobi-deferred-sqrt";
#elif defined(CH6_HYBRID_SUBTRACTIVE_U64_JACOBI)
#if defined(CH6_CANONICAL_JACOBI_INPUT)
constexpr std::string_view LIFT_RESIDUE_TEST =
    "hybrid-u128-euclidean-u64-subtractive-jacobi-deferred-sqrt";
#else
constexpr std::string_view LIFT_RESIDUE_TEST =
    "montgomery-residue-hybrid-u128-euclidean-u64-subtractive-"
    "jacobi-deferred-sqrt";
#endif
#elif defined(CH6_FULL_U128_JACOBI)
constexpr std::string_view LIFT_RESIDUE_TEST =
    "full-u128-euclidean-jacobi-deferred-sqrt";
#elif defined(CH6_CANONICAL_JACOBI_INPUT)
constexpr std::string_view LIFT_RESIDUE_TEST =
    "hybrid-u128-u64-euclidean-jacobi-deferred-sqrt";
#else
constexpr std::string_view LIFT_RESIDUE_TEST =
    "montgomery-residue-hybrid-u128-u64-euclidean-jacobi-deferred-sqrt";
#endif
#else
constexpr std::string_view LIFT_RESIDUE_TEST = "sqrt";
#endif

#if !defined(CH6_FIXED_WINDOW_BITS)
#define CH6_FIXED_WINDOW_BITS 8
#endif

#if !defined(CH6_SUBGROUP_LUCAS_LANES)
#define CH6_SUBGROUP_LUCAS_LANES 1
#endif

#if defined(CH6_BINARY_SUBGROUP_LUCAS) && \
    defined(CH6_PRAC_SUBGROUP_LUCAS)
#error "select either binary or PRAC subgroup Lucas evaluation"
#elif !defined(CH6_BINARY_SUBGROUP_LUCAS) && \
    !defined(CH6_PRAC_SUBGROUP_LUCAS)
#define CH6_PRAC_SUBGROUP_LUCAS
#endif
#if defined(CH6_BINARY_SUBGROUP_LUCAS) && \
    (defined(CH6_GENERIC_PRAC_INTERPRETER) || \
     defined(CH6_FUSED_PRAC_INTERPRETER))
#error "PRAC interpreter selection requires PRAC subgroup evaluation"
#endif
#if defined(CH6_GENERIC_PRAC_INTERPRETER) && \
    defined(CH6_FUSED_PRAC_INTERPRETER)
#error "select either the generic or fused PRAC interpreter"
#endif
#if defined(CH6_PRAC_SUBGROUP_LUCAS) && \
    !defined(CH6_GENERIC_PRAC_INTERPRETER) && \
    !defined(CH6_FUSED_PRAC_INTERPRETER)
#define CH6_GENERIC_PRAC_INTERPRETER
#endif
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS) && \
    defined(CH6_XY_SUBGROUP_BATCH)
#error "select either direct fractions or separate subgroup x/RHS arrays"
#elif !defined(CH6_DIRECT_SUBGROUP_FRACTIONS) && \
    !defined(CH6_XY_SUBGROUP_BATCH)
#define CH6_DIRECT_SUBGROUP_FRACTIONS
#endif
#if defined(CH6_U64_LUCAS_BIT_STREAM) && \
    defined(CH6_VARIABLE_U128_LUCAS_BITS)
#error "select either the U64 or variable-U128 Lucas bit scan"
#endif
#if !defined(CH6_U64_LUCAS_BIT_STREAM) && \
    !defined(CH6_VARIABLE_U128_LUCAS_BITS)
#define CH6_VARIABLE_U128_LUCAS_BITS
#endif

constexpr std::size_t FIXED_WINDOW_BITS = CH6_FIXED_WINDOW_BITS;
constexpr std::size_t SUBGROUP_LUCAS_LANES = CH6_SUBGROUP_LUCAS_LANES;
#if CH6_SUBGROUP_LUCAS_LANES != 1 && \
    CH6_SUBGROUP_LUCAS_LANES != 2 && \
    CH6_SUBGROUP_LUCAS_LANES != 4
#error "CH6_SUBGROUP_LUCAS_LANES must be 1, 2, or 4"
#endif
#if defined(CH6_PRAC_SUBGROUP_LUCAS) && \
    CH6_SUBGROUP_LUCAS_LANES != 1 && \
    CH6_SUBGROUP_LUCAS_LANES != 2
#error "CH6_PRAC_SUBGROUP_LUCAS requires one or two Lucas lanes"
#endif
#if defined(CH6_BRANCHLESS_LUCAS_STEP) && \
    (defined(CH6_PRAC_SUBGROUP_LUCAS) || \
     CH6_SUBGROUP_LUCAS_LANES != 1)
#error "CH6_BRANCHLESS_LUCAS_STEP requires one binary Lucas lane"
#endif
#if defined(CH6_U64_LUCAS_BIT_STREAM) && \
    defined(CH6_PRAC_SUBGROUP_LUCAS)
#error "CH6_U64_LUCAS_BIT_STREAM is a binary Lucas ablation"
#endif
constexpr std::size_t FIXED_RADIX = 1U << FIXED_WINDOW_BITS;
constexpr std::size_t FIXED_UNSIGNED_ROWS =
    (88U + FIXED_WINDOW_BITS - 1U) / FIXED_WINDOW_BITS;
#if defined(CH6_SIGNED_FIXED_TABLE)
constexpr std::size_t FIXED_TABLE_ROWS =
    FIXED_UNSIGNED_ROWS + (88U % FIXED_WINDOW_BITS == 0U ? 1U : 0U);
constexpr std::size_t FIXED_TABLE_ENTRIES = FIXED_RADIX / 2U + 1U;
constexpr std::string_view FIXED_DIGIT_ENCODING = "balanced-signed";
#else
constexpr std::size_t FIXED_TABLE_ROWS = FIXED_UNSIGNED_ROWS;
constexpr std::size_t FIXED_TABLE_ENTRIES = FIXED_RADIX;
constexpr std::string_view FIXED_DIGIT_ENCODING = "unsigned";
#endif
#if defined(CH6_ROW_BATCHED_FIXED_MUL)
constexpr std::string_view FIXED_MULTIPLICATION = "row-batched-affine";
#else
constexpr std::string_view FIXED_MULTIPLICATION = "candidate-jacobian";
#endif
#if defined(CH6_NO_SUBGROUP_FILTER)
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST = "none";
#elif defined(CH6_PRAC_SUBGROUP_LUCAS)
#if CH6_SUBGROUP_LUCAS_LANES == 2
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace-prac-20-interleaved-2";
#elif defined(CH6_GENERIC_PRAC_INTERPRETER)
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace-prac-20-generic";
#else
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace-prac-20-fused";
#endif
#elif CH6_SUBGROUP_LUCAS_LANES == 1
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace";
#elif CH6_SUBGROUP_LUCAS_LANES == 2
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace-interleaved-2";
#elif CH6_SUBGROUP_LUCAS_LANES == 4
constexpr std::string_view SUBGROUP_MEMBERSHIP_TEST =
    "cofactor-5-frobenius-tate-trace-interleaved-4";
#else
#error "CH6_SUBGROUP_LUCAS_LANES must be 1, 2, or 4"
#endif
#if defined(CH6_RUNTIME_SUBGROUP_CONSTANTS)
constexpr std::string_view SUBGROUP_CONSTANT_LAYOUT =
    "function-local-static";
#else
constexpr std::string_view SUBGROUP_CONSTANT_LAYOUT =
    "constexpr-montgomery";
#endif
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
constexpr std::string_view SUBGROUP_BATCH_LAYOUT =
    "direct-in-place-fraction";
#else
constexpr std::string_view SUBGROUP_BATCH_LAYOUT = "xy-separated";
#endif
#if defined(CH6_EXPANDED_SUBGROUP_TRACE)
constexpr std::string_view SUBGROUP_TRACE_FORMULA =
    "expanded-miller-fraction";
#else
constexpr std::string_view SUBGROUP_TRACE_FORMULA =
    "degree-5-reciprocal-polynomial";
#endif
#if defined(CH6_VARIABLE_U128_LUCAS_BITS)
constexpr std::string_view SUBGROUP_LUCAS_BIT_SCAN =
    "variable-u128-shift";
#else
constexpr std::string_view SUBGROUP_LUCAS_BIT_SCAN =
    "u64-msb-stream";
#endif
#if defined(CH6_PRAC_SUBGROUP_LUCAS)
constexpr std::string_view SUBGROUP_LUCAS_STEP = "fixed-prac-schedule";
#elif defined(CH6_BRANCHLESS_LUCAS_STEP)
constexpr std::string_view SUBGROUP_LUCAS_STEP = "branchless-select";
#else
constexpr std::string_view SUBGROUP_LUCAS_STEP = "fixed-pattern-branch";
#endif
#if defined(CH6_EAGER_ZERO_SCAN_BUFFERS)
#define CH6_SCAN_BUFFER_INITIALIZER {}
constexpr std::string_view SCAN_BUFFER_INITIALIZATION = "eager-zero";
#else
#define CH6_SCAN_BUFFER_INITIALIZER
constexpr std::string_view SCAN_BUFFER_INITIALIZATION = "write-before-read";
#endif
#if defined(CH6_RUNTIME_CURVE_CONSTANTS)
constexpr std::string_view CURVE_CONSTANT_LAYOUT = "function-local-static";
#else
constexpr std::string_view CURVE_CONSTANT_LAYOUT = "constexpr-montgomery";
#endif
constexpr std::size_t FIXED_NORMALIZE_CAPACITY =
    std::max(FIXED_TABLE_ROWS, FIXED_TABLE_ENTRIES);
static_assert(FIXED_WINDOW_BITS >= 4 && FIXED_WINDOW_BITS <= 11);
static_assert(
    SUBGROUP_LUCAS_LANES == 1 ||
    SUBGROUP_LUCAS_LANES == 2 ||
    SUBGROUP_LUCAS_LANES == 4);

std::string hex(U128 value) {
    const auto high = static_cast<std::uint64_t>(value >> 64U);
    const auto low = static_cast<std::uint64_t>(value);
    std::ostringstream output;
    output << "0x" << std::hex;
    if (high != 0) {
        output << high << std::setfill('0') << std::setw(16) << low;
    } else {
        output << low;
    }
    return output.str();
}

// Canonical modular helpers are used by the telemetry recovery and as an
// independent, deliberately slow reference for --self-test.  Their operands
// are at most 88 bits, so additions fit in U128 even though products do not.
constexpr U128 add_mod(U128 left, U128 right, U128 modulus) {
    return left >= modulus - right ? left - (modulus - right) : left + right;
}

constexpr U128 sub_mod(U128 left, U128 right, U128 modulus) {
    return left >= right ? left - right : modulus - (right - left);
}

constexpr U128 mul_mod_reference(U128 left, U128 right, U128 modulus) {
    U128 result = 0;
    while (right != 0) {
        if ((right & 1U) != 0) {
            result = add_mod(result, left, modulus);
        }
        right >>= 1U;
        if (right != 0) {
            left = add_mod(left, left, modulus);
        }
    }
    return result;
}

U128 inverse_mod_reference(U128 value, U128 modulus) {
    // Store Bezout coefficients modulo modulus.  This avoids signed 128-bit
    // overflow while the ordinary Euclidean remainders determine quotients.
    U128 coefficient = 0;
    U128 next_coefficient = 1;
    U128 remainder = modulus;
    U128 next_remainder = value % modulus;
    while (next_remainder != 0) {
        const U128 quotient = remainder / next_remainder;
        const U128 coefficient_product =
            mul_mod_reference(quotient % modulus, next_coefficient, modulus);
        const U128 following_coefficient =
            sub_mod(coefficient, coefficient_product, modulus);
        const U128 following_remainder = remainder % next_remainder;
        coefficient = next_coefficient;
        next_coefficient = following_coefficient;
        remainder = next_remainder;
        next_remainder = following_remainder;
    }
    if (remainder != 1) {
        throw std::runtime_error("non-invertible telemetry value");
    }
    return coefficient;
}

// Every hot field value is a reduced Montgomery residue in two 64-bit limbs.
// A field element is 16 bytes and a Jacobian point is exactly 48 bytes; neither
// owns memory or allocates.
struct FieldElement {
    std::uint64_t low;
    std::uint64_t high;
};

static_assert(sizeof(FieldElement) == 16);

constexpr std::uint64_t FIELD_LOW = static_cast<std::uint64_t>(FIELD);
constexpr std::uint64_t FIELD_HIGH = static_cast<std::uint64_t>(FIELD >> 64U);

constexpr std::uint64_t montgomery_negative_inverse() {
    // Newton iteration doubles the number of correct inverse bits each round.
    std::uint64_t inverse = 1;
    for (int iteration = 0; iteration < 6; ++iteration) {
        inverse *= 2U - FIELD_LOW * inverse;
    }
    return 0U - inverse;
}

constexpr std::uint64_t MONTGOMERY_N_PRIME = montgomery_negative_inverse();

constexpr U128 power_of_two_mod_field(int exponent) {
    U128 value = 1;
    for (int bit = 0; bit < exponent; ++bit) {
        value = add_mod(value, value, FIELD);
    }
    return value;
}

constexpr U128 MONTGOMERY_ONE_CANON = power_of_two_mod_field(128);
constexpr U128 MONTGOMERY_R2_CANON = power_of_two_mod_field(256);

constexpr FieldElement split(U128 value) {
    return {static_cast<std::uint64_t>(value),
            static_cast<std::uint64_t>(value >> 64U)};
}

constexpr FieldElement SUBGROUP_ALPHA_MONT = split(mul_mod_reference(
    SUBGROUP_ALPHA, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement SUBGROUP_BETA_MONT = split(mul_mod_reference(
    SUBGROUP_BETA, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement SUBGROUP_GAMMA_MONT = split(mul_mod_reference(
    SUBGROUP_GAMMA, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement SUBGROUP_DELTA_MONT = split(mul_mod_reference(
    SUBGROUP_DELTA, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement SUBGROUP_TANGENT_M1_MONT = split(mul_mod_reference(
    SUBGROUP_TANGENT_M1, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement SUBGROUP_TANGENT_M2_MONT = split(mul_mod_reference(
    SUBGROUP_TANGENT_M2, MONTGOMERY_ONE_CANON, FIELD));
constexpr std::array<FieldElement, 5>
    SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS_MONT{
        split(mul_mod_reference(
            SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[0],
            MONTGOMERY_ONE_CANON, FIELD)),
        split(mul_mod_reference(
            SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[1],
            MONTGOMERY_ONE_CANON, FIELD)),
        split(mul_mod_reference(
            SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[2],
            MONTGOMERY_ONE_CANON, FIELD)),
        split(mul_mod_reference(
            SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[3],
            MONTGOMERY_ONE_CANON, FIELD)),
        split(mul_mod_reference(
            SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[4],
            MONTGOMERY_ONE_CANON, FIELD)),
    };
constexpr FieldElement CURVE_A_MONT = split(mul_mod_reference(
    CURVE_A_CANON, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement CURVE_B_MONT = split(mul_mod_reference(
    CURVE_B_CANON, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement TRANSFORMED_CURVE_A_MONT = split(mul_mod_reference(
    TRANSFORMED_CURVE_A, MONTGOMERY_ONE_CANON, FIELD));
constexpr FieldElement TRANSFORMED_CURVE_B_MONT = split(mul_mod_reference(
    TRANSFORMED_CURVE_B, MONTGOMERY_ONE_CANON, FIELD));
constexpr std::array<FieldElement, 11> SUBGROUP_20TH_ROOT_TRACES_MONT{
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[0], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[1], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[2], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[3], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[4], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[5], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[6], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[7], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[8], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[9], MONTGOMERY_ONE_CANON, FIELD)),
    split(mul_mod_reference(
        SUBGROUP_20TH_ROOT_TRACES[10], MONTGOMERY_ONE_CANON, FIELD)),
};

constexpr U128 join(const FieldElement& value) {
    return (static_cast<U128>(value.high) << 64U) | value.low;
}

constexpr bool field_equal(const FieldElement& left, const FieldElement& right) {
    return left.low == right.low && left.high == right.high;
}

constexpr bool field_is_zero(const FieldElement& value) {
    return (value.low | value.high) == 0;
}

inline void add_product(
    std::uint64_t* limbs, int limb_count, int offset,
    std::uint64_t left, std::uint64_t right) {
    const U128 product = static_cast<U128>(left) * right;
    U128 sum = static_cast<U128>(limbs[offset]) +
               static_cast<std::uint64_t>(product);
    limbs[offset] = static_cast<std::uint64_t>(sum);
    std::uint64_t carry = static_cast<std::uint64_t>(sum >> 64U);

    sum = static_cast<U128>(limbs[offset + 1]) +
          static_cast<std::uint64_t>(product >> 64U) + carry;
    limbs[offset + 1] = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);

    for (int index = offset + 2; carry != 0 && index < limb_count; ++index) {
        sum = static_cast<U128>(limbs[index]) + carry;
        limbs[index] = static_cast<std::uint64_t>(sum);
        carry = static_cast<std::uint64_t>(sum >> 64U);
    }
    assert(carry == 0);
}

inline FieldElement reduce_montgomery_product(std::uint64_t* limbs) {
    for (int index = 0; index < 2; ++index) {
        const std::uint64_t multiplier = limbs[index] * MONTGOMERY_N_PRIME;
        add_product(limbs, 6, index, multiplier, FIELD_LOW);
        add_product(limbs, 6, index + 1, multiplier, FIELD_HIGH);
        assert(limbs[index] == 0);
    }
    assert(limbs[4] == 0 && limbs[5] == 0);

    U128 reduced = (static_cast<U128>(limbs[3]) << 64U) | limbs[2];
    if (reduced >= FIELD) {
        reduced -= FIELD;
    }
    return split(reduced);
}

inline FieldElement field_multiply(
    const FieldElement& left, const FieldElement& right) {
#if !defined(CH6_PORTABLE_ARITHMETIC) && \
    !defined(CH6_GENERIC_MONTGOMERY) && defined(__x86_64__) && \
    defined(__BMI2__) && defined(__ADX__)
    using Limb = unsigned long long;
    static_assert(sizeof(Limb) == sizeof(std::uint64_t));
    const Limb left0 = static_cast<Limb>(left.low);
    const Limb left1 = static_cast<Limb>(left.high);
    const Limb right0 = static_cast<Limb>(right.low);
    const Limb right1 = static_cast<Limb>(right.high);
    const Limb field0 = static_cast<Limb>(FIELD_LOW);
    const Limb field1 = static_cast<Limb>(FIELD_HIGH);
    const Limb n_prime = static_cast<Limb>(MONTGOMERY_N_PRIME);
    Limb limb0;
    Limb limb1;
    Limb limb2 = 0;
    Limb limb3 = 0;
    Limb low;
    Limb high;
    Limb discarded;
    unsigned char carry;

    limb0 = _mulx_u64(left0, right0, &limb1);
    low = _mulx_u64(left0, right1, &high);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(left1, right0, &high);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(left1, right1, &high);
    carry = _addcarryx_u64(0, limb2, low, &limb2);
    carry = _addcarryx_u64(carry, limb3, high, &limb3);
    assert(carry == 0);

    Limb multiplier = limb0 * n_prime;
    low = _mulx_u64(multiplier, field0, &high);
    carry = _addcarryx_u64(0, limb0, low, &discarded);
    assert(discarded == 0);
    carry = _addcarryx_u64(carry, limb1, high, &limb1);
    carry = _addcarryx_u64(carry, limb2, 0, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(multiplier, field1, &high);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);

    multiplier = limb1 * n_prime;
    low = _mulx_u64(multiplier, field0, &high);
    carry = _addcarryx_u64(0, limb1, low, &discarded);
    assert(discarded == 0);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(multiplier, field1, &high);
    carry = _addcarryx_u64(0, limb2, low, &limb2);
    carry = _addcarryx_u64(carry, limb3, high, &limb3);
    assert(carry == 0);

    U128 reduced = (static_cast<U128>(limb3) << 64U) | limb2;
    if (reduced >= FIELD) {
        reduced -= FIELD;
    }
    return split(reduced);
#elif !defined(CH6_GENERIC_MONTGOMERY)
    // Exact 2x2 product.  The middle sum needs at most 66 bits, and the high
    // sum cannot overflow U128 because it is the upper half of a 256-bit
    // product.
    const U128 product00 = static_cast<U128>(left.low) * right.low;
    const U128 product01 = static_cast<U128>(left.low) * right.high;
    const U128 product10 = static_cast<U128>(left.high) * right.low;
    const U128 product11 = static_cast<U128>(left.high) * right.high;
    const U128 middle =
        (product00 >> 64U) +
        static_cast<std::uint64_t>(product01) +
        static_cast<std::uint64_t>(product10);
    const U128 high =
        product11 + (product01 >> 64U) + (product10 >> 64U) +
        (middle >> 64U);
    std::uint64_t limb0 = static_cast<std::uint64_t>(product00);
    std::uint64_t limb1 = static_cast<std::uint64_t>(middle);
    std::uint64_t limb2 = static_cast<std::uint64_t>(high);
    std::uint64_t limb3 = static_cast<std::uint64_t>(high >> 64U);
    std::uint64_t limb4 = 0;

    // REDC word 0.  The first low word cancels by construction.
    std::uint64_t multiplier = limb0 * MONTGOMERY_N_PRIME;
    U128 low_product = static_cast<U128>(multiplier) * FIELD_LOW;
    U128 high_product = static_cast<U128>(multiplier) * FIELD_HIGH;
    U128 sum =
        static_cast<U128>(limb0) +
        static_cast<std::uint64_t>(low_product);
    assert(static_cast<std::uint64_t>(sum) == 0);
    std::uint64_t carry = static_cast<std::uint64_t>(sum >> 64U);
    sum =
        static_cast<U128>(limb1) +
        static_cast<std::uint64_t>(low_product >> 64U) +
        static_cast<std::uint64_t>(high_product) + carry;
    limb1 = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum =
        static_cast<U128>(limb2) +
        static_cast<std::uint64_t>(high_product >> 64U) + carry;
    limb2 = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum = static_cast<U128>(limb3) + carry;
    limb3 = static_cast<std::uint64_t>(sum);
    limb4 = static_cast<std::uint64_t>(sum >> 64U);

    // REDC word 1.
    multiplier = limb1 * MONTGOMERY_N_PRIME;
    low_product = static_cast<U128>(multiplier) * FIELD_LOW;
    high_product = static_cast<U128>(multiplier) * FIELD_HIGH;
    sum =
        static_cast<U128>(limb1) +
        static_cast<std::uint64_t>(low_product);
    assert(static_cast<std::uint64_t>(sum) == 0);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum =
        static_cast<U128>(limb2) +
        static_cast<std::uint64_t>(low_product >> 64U) +
        static_cast<std::uint64_t>(high_product) + carry;
    limb2 = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum =
        static_cast<U128>(limb3) +
        static_cast<std::uint64_t>(high_product >> 64U) + carry;
    limb3 = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum = static_cast<U128>(limb4) + carry;
    limb4 = static_cast<std::uint64_t>(sum);
    assert((sum >> 64U) == 0 && limb4 == 0);

    U128 reduced = (static_cast<U128>(limb3) << 64U) | limb2;
    if (reduced >= FIELD) {
        reduced -= FIELD;
    }
    return split(reduced);
#else
    // Product first, followed by two REDC word eliminations.  Six limbs make
    // carry propagation explicit; reduced inputs guarantee limbs 4 and 5 are
    // zero after division by R=2^128.
    std::uint64_t limbs[6]{};
    add_product(limbs, 6, 0, left.low, right.low);
    add_product(limbs, 6, 1, left.low, right.high);
    add_product(limbs, 6, 1, left.high, right.low);
    add_product(limbs, 6, 2, left.high, right.high);
    return reduce_montgomery_product(limbs);
#endif
}

inline FieldElement field_square(const FieldElement& value) {
#if defined(CH6_INTRINSIC_SQUARE) && defined(__x86_64__) && \
    defined(__BMI2__) && defined(__ADX__)
    using Limb = unsigned long long;
    const Limb operand0 = static_cast<Limb>(value.low);
    const Limb operand1 = static_cast<Limb>(value.high);
    const Limb field0 = static_cast<Limb>(FIELD_LOW);
    const Limb field1 = static_cast<Limb>(FIELD_HIGH);
    const Limb n_prime = static_cast<Limb>(MONTGOMERY_N_PRIME);
    Limb limb0;
    Limb limb1;
    Limb limb2 = 0;
    Limb limb3 = 0;
    Limb low;
    Limb high;
    Limb discarded;
    unsigned char carry;

    limb0 = _mulx_u64(operand0, operand0, &limb1);
    low = _mulx_u64(operand0, operand1, &high);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(operand1, operand1, &high);
    carry = _addcarryx_u64(0, limb2, low, &limb2);
    carry = _addcarryx_u64(carry, limb3, high, &limb3);
    assert(carry == 0);

    Limb multiplier = limb0 * n_prime;
    low = _mulx_u64(multiplier, field0, &high);
    carry = _addcarryx_u64(0, limb0, low, &discarded);
    assert(discarded == 0);
    carry = _addcarryx_u64(carry, limb1, high, &limb1);
    carry = _addcarryx_u64(carry, limb2, 0, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(multiplier, field1, &high);
    carry = _addcarryx_u64(0, limb1, low, &limb1);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);

    multiplier = limb1 * n_prime;
    low = _mulx_u64(multiplier, field0, &high);
    carry = _addcarryx_u64(0, limb1, low, &discarded);
    assert(discarded == 0);
    carry = _addcarryx_u64(carry, limb2, high, &limb2);
    carry = _addcarryx_u64(carry, limb3, 0, &limb3);
    assert(carry == 0);
    low = _mulx_u64(multiplier, field1, &high);
    carry = _addcarryx_u64(0, limb2, low, &limb2);
    carry = _addcarryx_u64(carry, limb3, high, &limb3);
    assert(carry == 0);

    U128 reduced = (static_cast<U128>(limb3) << 64U) | limb2;
    if (reduced >= FIELD) {
        reduced -= FIELD;
    }
    return split(reduced);
#elif defined(CH6_SPECIALIZED_SQUARE)
    // Form 2*low*high from one 64x64->128 product rather than computing the
    // symmetric cross terms independently in the generic multiplier.
    std::uint64_t limbs[6]{};
    add_product(limbs, 6, 0, value.low, value.low);
    add_product(limbs, 6, 2, value.high, value.high);

    const U128 cross = static_cast<U128>(value.low) * value.high;
    const std::uint64_t doubled_low =
        static_cast<std::uint64_t>(cross) << 1U;
    const std::uint64_t doubled_high =
        (static_cast<std::uint64_t>(cross >> 64U) << 1U) |
        (static_cast<std::uint64_t>(cross) >> 63U);
    const std::uint64_t doubled_carry =
        static_cast<std::uint64_t>(cross >> 127U);

    U128 sum = static_cast<U128>(limbs[1]) + doubled_low;
    limbs[1] = static_cast<std::uint64_t>(sum);
    std::uint64_t carry = static_cast<std::uint64_t>(sum >> 64U);
    sum = static_cast<U128>(limbs[2]) + doubled_high + carry;
    limbs[2] = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum = static_cast<U128>(limbs[3]) + doubled_carry + carry;
    limbs[3] = static_cast<std::uint64_t>(sum);
    carry = static_cast<std::uint64_t>(sum >> 64U);
    sum = static_cast<U128>(limbs[4]) + carry;
    limbs[4] = static_cast<std::uint64_t>(sum);
    assert((sum >> 64U) == 0);

    return reduce_montgomery_product(limbs);
#else
    return field_multiply(value, value);
#endif
}

inline FieldElement field_add(
    const FieldElement& left, const FieldElement& right) {
#if !defined(CH6_PORTABLE_ARITHMETIC) && defined(__x86_64__) && \
    defined(__ADX__)
    using Limb = unsigned long long;
    Limb sum0;
    Limb sum1;
    Limb difference0;
    Limb difference1;
    unsigned char carry = _addcarryx_u64(
        0, static_cast<Limb>(left.low), static_cast<Limb>(right.low), &sum0);
    carry = _addcarryx_u64(
        carry, static_cast<Limb>(left.high),
        static_cast<Limb>(right.high), &sum1);
    assert(carry == 0);
    unsigned char borrow = _subborrow_u64(
        0, sum0, static_cast<Limb>(FIELD_LOW), &difference0);
    borrow = _subborrow_u64(
        borrow, sum1, static_cast<Limb>(FIELD_HIGH), &difference1);
    const Limb mask = 0 - static_cast<Limb>(borrow);
    carry = _addcarryx_u64(
        0, difference0, static_cast<Limb>(FIELD_LOW) & mask, &difference0);
    carry = _addcarryx_u64(
        carry, difference1, static_cast<Limb>(FIELD_HIGH) & mask,
        &difference1);
    assert(carry == borrow);
    return {
        static_cast<std::uint64_t>(difference0),
        static_cast<std::uint64_t>(difference1),
    };
#elif defined(CH6_DIRECT_FIELD_ADD)
    U128 sum = join(left) + join(right);
    if (sum >= FIELD) {
        sum -= FIELD;
    }
    return split(sum);
#else
    return split(add_mod(join(left), join(right), FIELD));
#endif
}

inline FieldElement field_subtract(
    const FieldElement& left, const FieldElement& right) {
#if !defined(CH6_PORTABLE_ARITHMETIC) && defined(__x86_64__) && \
    defined(__ADX__)
    using Limb = unsigned long long;
    Limb difference0;
    Limb difference1;
    unsigned char borrow = _subborrow_u64(
        0, static_cast<Limb>(left.low), static_cast<Limb>(right.low),
        &difference0);
    borrow = _subborrow_u64(
        borrow, static_cast<Limb>(left.high),
        static_cast<Limb>(right.high), &difference1);
    const Limb mask = 0 - static_cast<Limb>(borrow);
    unsigned char carry = _addcarryx_u64(
        0, difference0, static_cast<Limb>(FIELD_LOW) & mask, &difference0);
    carry = _addcarryx_u64(
        carry, difference1, static_cast<Limb>(FIELD_HIGH) & mask,
        &difference1);
    assert(carry == borrow);
    return {
        static_cast<std::uint64_t>(difference0),
        static_cast<std::uint64_t>(difference1),
    };
#else
    return split(sub_mod(join(left), join(right), FIELD));
#endif
}

inline FieldElement field_double(const FieldElement& value) {
#if defined(CH6_DIRECT_FIELD_ADD)
    U128 doubled = join(value) << 1U;
    if (doubled >= FIELD) {
        doubled -= FIELD;
    }
    return split(doubled);
#else
    return field_add(value, value);
#endif
}

inline FieldElement field_negate(const FieldElement& value) {
    return field_is_zero(value) ? value : split(FIELD - join(value));
}

inline FieldElement to_montgomery(U128 canonical) {
    assert(canonical < FIELD);
    return field_multiply(split(canonical), split(MONTGOMERY_R2_CANON));
}

inline FieldElement transformed_x_to_montgomery(U128 canonical) {
    assert(canonical < FIELD);
    return field_multiply(
        split(canonical), split(TRANSFORMED_X_MONTGOMERY_R2));
}

inline FieldElement curve_x_to_montgomery(U128 canonical) {
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    return transformed_x_to_montgomery(canonical);
#else
    return to_montgomery(canonical);
#endif
}

inline U128 from_montgomery(const FieldElement& value) {
    return join(field_multiply(value, split(1)));
}

inline U128 curve_x_from_montgomery(const FieldElement& value) {
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    return join(field_multiply(
        value, split(ORIGINAL_X_FROM_TRANSFORMED_SCALE)));
#else
    return from_montgomery(value);
#endif
}

const FieldElement& field_zero() {
    static constexpr FieldElement value{0, 0};
    return value;
}

const FieldElement& field_one() {
    static constexpr FieldElement value = split(MONTGOMERY_ONE_CANON);
    return value;
}

const FieldElement& curve_a() {
#if defined(CH6_RUNTIME_CURVE_CONSTANTS)
    static const FieldElement value = to_montgomery(CURVE_A_CANON);
    return value;
#else
    return CURVE_A_MONT;
#endif
}

const FieldElement& curve_b() {
#if defined(CH6_RUNTIME_CURVE_CONSTANTS)
    static const FieldElement value = to_montgomery(CURVE_B_CANON);
    return value;
#else
    return CURVE_B_MONT;
#endif
}

const FieldElement& transformed_curve_b() {
#if defined(CH6_RUNTIME_CURVE_CONSTANTS)
    static const FieldElement value = to_montgomery(TRANSFORMED_CURVE_B);
    return value;
#else
    return TRANSFORMED_CURVE_B_MONT;
#endif
}

const FieldElement& transformed_curve_a() {
#if defined(CH6_RUNTIME_CURVE_CONSTANTS)
    static const FieldElement value = to_montgomery(TRANSFORMED_CURVE_A);
    return value;
#else
    return TRANSFORMED_CURVE_A_MONT;
#endif
}

const std::array<FieldElement, 11>& subgroup_20th_root_traces() {
#if defined(CH6_RUNTIME_SUBGROUP_CONSTANTS)
    static const auto values = [] {
        std::array<FieldElement, 11> result{};
        for (std::size_t index = 0; index < result.size(); ++index) {
            result[index] =
                to_montgomery(SUBGROUP_20TH_ROOT_TRACES[index]);
        }
        return result;
    }();
    return values;
#else
    return SUBGROUP_20TH_ROOT_TRACES_MONT;
#endif
}

const std::array<FieldElement, 5>&
subgroup_trace_reciprocal_coefficients() {
#if defined(CH6_RUNTIME_SUBGROUP_CONSTANTS)
    static const auto values = [] {
        std::array<FieldElement, 5> result{};
        for (std::size_t index = 0; index < result.size(); ++index) {
            result[index] = to_montgomery(
                SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[index]);
        }
        return result;
    }();
    return values;
#else
    return SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS_MONT;
#endif
}

inline FieldElement transformed_curve_rhs(
    const FieldElement& x, const FieldElement& x_squared) {
    const FieldElement three_x = field_add(x, field_double(x));
    return field_add(
        field_subtract(field_multiply(x_squared, x), three_x),
        transformed_curve_b());
}

inline FieldElement transformed_curve_rhs(const FieldElement& x) {
    return transformed_curve_rhs(x, field_square(x));
}

FieldElement field_power(FieldElement base, U128 exponent) {
    FieldElement result = field_one();
    while (exponent != 0) {
        if ((exponent & 1U) != 0) {
            result = field_multiply(result, base);
        }
        exponent >>= 1U;
        if (exponent != 0) {
            base = field_square(base);
        }
    }
    return result;
}

FieldElement field_power_window4(FieldElement base, U128 exponent) {
    if (exponent == 0) {
        return field_one();
    }
    std::array<FieldElement, 8> odd_powers{};
    odd_powers[0] = base;
    const FieldElement base_squared = field_square(base);
    for (std::size_t index = 1; index < odd_powers.size(); ++index) {
        odd_powers[index] =
            field_multiply(odd_powers[index - 1], base_squared);
    }

    int bit = 127;
    while (((exponent >> bit) & 1U) == 0) {
        --bit;
    }
    FieldElement result = field_one();
    bool initialized = false;
    while (bit >= 0) {
        if (((exponent >> bit) & 1U) == 0) {
            if (initialized) {
                result = field_square(result);
            }
            --bit;
            continue;
        }

        int low_bit = std::max(0, bit - 3);
        while (((exponent >> low_bit) & 1U) == 0) {
            ++low_bit;
        }
        unsigned window = 0;
        for (int position = bit; position >= low_bit; --position) {
            window = (window << 1U) |
                     static_cast<unsigned>((exponent >> position) & 1U);
        }
        if (!initialized) {
            result = odd_powers[window >> 1U];
            initialized = true;
        } else {
            for (int position = low_bit; position <= bit; ++position) {
                result = field_square(result);
            }
            result = field_multiply(result, odd_powers[window >> 1U]);
        }
        bit = low_bit - 1;
    }
    return result;
}

template <unsigned Count>
inline FieldElement repeated_square(FieldElement value) {
#pragma GCC unroll 8
    for (unsigned index = 0; index < Count; ++index) {
        value = field_square(value);
    }
    return value;
}

[[maybe_unused]]
FieldElement field_sqrt_power_fixed_window4(FieldElement base) {
    // Straight-line specialization of the width-4 sliding-window schedule for
    // (FIELD+1)/4 = 0x36411ed7ccb769729bd5a7.  It performs the same 83
    // squarings and 25 multiplications as field_power_window4(), but removes
    // its per-bit window decoding from the candidate hot path.
    std::array<FieldElement, 8> odd_powers{};
    odd_powers[0] = base;
    const FieldElement base_squared = field_square(base);
    for (std::size_t index = 1; index < odd_powers.size(); ++index) {
        odd_powers[index] =
            field_multiply(odd_powers[index - 1], base_squared);
    }

    FieldElement result = odd_powers[6];  // 0xd
    result = field_multiply(repeated_square<4>(result), odd_powers[4]);
    result = field_multiply(repeated_square<6>(result), odd_powers[0]);
    result = field_multiply(repeated_square<7>(result), odd_powers[7]);
    result = field_multiply(repeated_square<5>(result), odd_powers[6]);
    result = field_multiply(repeated_square<5>(result), odd_powers[7]);
    result = field_multiply(repeated_square<4>(result), odd_powers[4]);
    result = field_multiply(repeated_square<4>(result), odd_powers[4]);
    result = field_multiply(repeated_square<5>(result), odd_powers[6]);
    result = field_multiply(repeated_square<4>(result), odd_powers[6]);
    result = field_multiply(repeated_square<3>(result), odd_powers[2]);
    result = field_multiply(repeated_square<6>(result), odd_powers[5]);
    result = field_multiply(repeated_square<4>(result), odd_powers[4]);
    result = field_multiply(repeated_square<5>(result), odd_powers[4]);
    result = field_multiply(repeated_square<4>(result), odd_powers[5]);
    result = field_multiply(repeated_square<4>(result), odd_powers[6]);
    result = field_multiply(repeated_square<5>(result), odd_powers[5]);
    result = field_multiply(repeated_square<5>(result), odd_powers[4]);
    return field_multiply(repeated_square<2>(result), odd_powers[1]);
}

enum class InverseMethod { BinaryGcd, Fermat };
enum class SqrtMethod { Window4, Binary };

InverseMethod inverse_method = InverseMethod::BinaryGcd;
SqrtMethod sqrt_method = SqrtMethod::Window4;

FieldElement field_inverse_fermat(const FieldElement& value) {
    if (field_is_zero(value)) {
        throw std::runtime_error("field inversion of zero");
    }
    return field_power(value, FIELD - 2U);
}

FieldElement field_inverse_binary_gcd(const FieldElement& value) {
    if (field_is_zero(value)) {
        throw std::runtime_error("field inversion of zero");
    }
    U128 left = from_montgomery(value);
    U128 right = FIELD;
    U128 left_coefficient = 1;
    U128 right_coefficient = 0;
    while (left != 1 && right != 1) {
        while ((left & 1U) == 0) {
            left >>= 1U;
            left_coefficient = (left_coefficient & 1U) == 0
                ? left_coefficient >> 1U
                : (left_coefficient + FIELD) >> 1U;
        }
        while ((right & 1U) == 0) {
            right >>= 1U;
            right_coefficient = (right_coefficient & 1U) == 0
                ? right_coefficient >> 1U
                : (right_coefficient + FIELD) >> 1U;
        }
        if (left >= right) {
            left -= right;
            left_coefficient =
                sub_mod(left_coefficient, right_coefficient, FIELD);
        } else {
            right -= left;
            right_coefficient =
                sub_mod(right_coefficient, left_coefficient, FIELD);
        }
    }
    return to_montgomery(left == 1 ? left_coefficient : right_coefficient);
}

FieldElement field_inverse(const FieldElement& value) {
    return inverse_method == InverseMethod::BinaryGcd
        ? field_inverse_binary_gcd(value)
        : field_inverse_fermat(value);
}

bool field_sqrt(const FieldElement& value, FieldElement& root) {
    // FIELD == 3 (mod 4), so this exponent both computes the candidate root
    // and replaces a separate quadratic-residue test.
    const U128 exponent = (FIELD + 1U) >> 2U;
    if (sqrt_method == SqrtMethod::Window4) {
#if defined(CH6_FIXED_SQRT_CHAIN)
        root = field_sqrt_power_fixed_window4(value);
#else
        root = field_power_window4(value, exponent);
#endif
    } else {
        root = field_power(value, exponent);
    }
    return field_equal(field_square(root), value);
}

bool field_is_square_euclidean_jacobi(const FieldElement& value) {
    U128 numerator = from_montgomery(value);
    if (numerator == 0) {
        return true;
    }
    U128 denominator = FIELD;
    int sign = 1;
    while (numerator != 0) {
        unsigned powers_of_two = 0;
        while ((numerator & 1U) == 0) {
            numerator >>= 1U;
            ++powers_of_two;
        }
        if (
            (powers_of_two & 1U) != 0 &&
            ((denominator & 7U) == 3U || (denominator & 7U) == 5U)) {
            sign = -sign;
        }
        if (
            (numerator & 3U) == 3U &&
            (denominator & 3U) == 3U) {
            sign = -sign;
        }
        const U128 next_numerator = denominator % numerator;
        denominator = numerator;
        numerator = next_numerator;
    }
    return denominator == 1 && sign > 0;
}

template <bool SUBTRACTIVE_U64, bool MONTGOMERY_RESIDUE>
bool field_is_square_hybrid_jacobi_impl(const FieldElement& value) {
    // R=2^128=(2^64)^2 is a square modulo the odd prime FIELD.  Therefore a
    // reduced Montgomery residue aR has the same Jacobi symbol as a, and the
    // hot path can avoid one Montgomery conversion.
    U128 numerator = MONTGOMERY_RESIDUE
        ? join(value)
        : from_montgomery(value);
    if (numerator == 0) {
        return true;
    }
    U128 denominator = FIELD;
    int sign = 1;
    while (numerator != 0) {
        const std::uint64_t low = static_cast<std::uint64_t>(numerator);
        const unsigned powers_of_two = low != 0
            ? static_cast<unsigned>(__builtin_ctzll(low))
            : 64U + static_cast<unsigned>(
                __builtin_ctzll(static_cast<std::uint64_t>(numerator >> 64U)));
        numerator >>= powers_of_two;
        if (
            (powers_of_two & 1U) != 0 &&
            ((denominator & 7U) == 3U || (denominator & 7U) == 5U)) {
            sign = -sign;
        }

        if ((numerator >> 64U) == 0 && (denominator >> 64U) == 0) {
            std::uint64_t numerator64 =
                static_cast<std::uint64_t>(numerator);
            std::uint64_t denominator64 =
                static_cast<std::uint64_t>(denominator);
            while (numerator64 != 0) {
                const unsigned twos =
                    static_cast<unsigned>(__builtin_ctzll(numerator64));
                numerator64 >>= twos;
                if (
                    (twos & 1U) != 0 &&
                    ((denominator64 & 7U) == 3U ||
                     (denominator64 & 7U) == 5U)) {
                    sign = -sign;
                }
                if constexpr (SUBTRACTIVE_U64) {
                    if (numerator64 == 1) {
                        return sign > 0;
                    }
                    if (numerator64 < denominator64) {
                        std::swap(numerator64, denominator64);
                        if (
                            (numerator64 & 3U) == 3U &&
                            (denominator64 & 3U) == 3U) {
                            sign = -sign;
                        }
                    }
                    numerator64 -= denominator64;
                } else {
                    if (
                        (numerator64 & 3U) == 3U &&
                        (denominator64 & 3U) == 3U) {
                        sign = -sign;
                    }
                    const std::uint64_t next_numerator =
                        denominator64 % numerator64;
                    denominator64 = numerator64;
                    numerator64 = next_numerator;
                }
            }
            return denominator64 == 1 && sign > 0;
        }

        if (
            (numerator & 3U) == 3U &&
            (denominator & 3U) == 3U) {
            sign = -sign;
        }
        const U128 next_numerator = denominator % numerator;
        denominator = numerator;
        numerator = next_numerator;
    }
    return denominator == 1 && sign > 0;
}

bool field_is_square_hybrid_euclidean_jacobi(const FieldElement& value) {
    return field_is_square_hybrid_jacobi_impl<false, true>(value);
}

bool field_is_square_hybrid_canonical_euclidean_jacobi(
    const FieldElement& value) {
    return field_is_square_hybrid_jacobi_impl<false, false>(value);
}

bool field_is_square_hybrid_subtractive_u64_jacobi(
    const FieldElement& value) {
    return field_is_square_hybrid_jacobi_impl<true, true>(value);
}

bool field_is_square_hybrid_canonical_subtractive_u64_jacobi(
    const FieldElement& value) {
    return field_is_square_hybrid_jacobi_impl<true, false>(value);
}

bool field_is_square_subtractive_jacobi(const FieldElement& value) {
    U128 numerator = from_montgomery(value);
    if (numerator == 0) {
        return true;
    }
    U128 denominator = FIELD;
    int sign = 1;
    while (numerator != 0) {
        const std::uint64_t low = static_cast<std::uint64_t>(numerator);
        const unsigned powers_of_two = low != 0
            ? static_cast<unsigned>(__builtin_ctzll(low))
            : 64U + static_cast<unsigned>(
                __builtin_ctzll(static_cast<std::uint64_t>(numerator >> 64U)));
        numerator >>= powers_of_two;
        if (
            (powers_of_two & 1U) != 0 &&
            ((denominator & 7U) == 3U || (denominator & 7U) == 5U)) {
            sign = -sign;
        }
        if (numerator == 1) {
            return sign > 0;
        }
        if (numerator < denominator) {
            std::swap(numerator, denominator);
            if (
                (numerator & 3U) == 3U &&
                (denominator & 3U) == 3U) {
                sign = -sign;
            }
        }
        numerator -= denominator;
    }
    return denominator == 1 && sign > 0;
}

bool field_is_square_binary_jacobi(const FieldElement& value) {
#if defined(CH6_SUBTRACTIVE_JACOBI)
    return field_is_square_subtractive_jacobi(value);
#elif defined(CH6_HYBRID_SUBTRACTIVE_U64_JACOBI)
#if defined(CH6_CANONICAL_JACOBI_INPUT)
    return field_is_square_hybrid_canonical_subtractive_u64_jacobi(value);
#else
    return field_is_square_hybrid_subtractive_u64_jacobi(value);
#endif
#elif defined(CH6_FULL_U128_JACOBI)
    return field_is_square_euclidean_jacobi(value);
#elif defined(CH6_CANONICAL_JACOBI_INPUT)
    return field_is_square_hybrid_canonical_euclidean_jacobi(value);
#else
    return field_is_square_hybrid_euclidean_jacobi(value);
#endif
}

struct SubgroupTraceFraction {
    FieldElement numerator;
    FieldElement denominator;
};

SubgroupTraceFraction subgroup_trace_fraction_expanded(
    const FieldElement& x, const FieldElement& rhs) {
#if defined(CH6_RUNTIME_SUBGROUP_CONSTANTS)
    static const FieldElement alpha = to_montgomery(SUBGROUP_ALPHA);
    static const FieldElement beta = to_montgomery(SUBGROUP_BETA);
    static const FieldElement gamma = to_montgomery(SUBGROUP_GAMMA);
    static const FieldElement delta = to_montgomery(SUBGROUP_DELTA);
    static const FieldElement tangent_m1 =
        to_montgomery(SUBGROUP_TANGENT_M1);
    static const FieldElement tangent_m2 =
        to_montgomery(SUBGROUP_TANGENT_M2);
#else
    constexpr FieldElement alpha = SUBGROUP_ALPHA_MONT;
    constexpr FieldElement beta = SUBGROUP_BETA_MONT;
    constexpr FieldElement gamma = SUBGROUP_GAMMA_MONT;
    constexpr FieldElement delta = SUBGROUP_DELTA_MONT;
    constexpr FieldElement tangent_m1 = SUBGROUP_TANGENT_M1_MONT;
    constexpr FieldElement tangent_m2 = SUBGROUP_TANGENT_M2_MONT;
#endif
    const FieldElement a = field_add(
        beta, field_multiply(tangent_m1, field_subtract(x, alpha)));
    const FieldElement b = field_add(
        delta, field_multiply(tangent_m2, field_subtract(x, gamma)));
    const FieldElement a_squared = field_square(a);
    const FieldElement rhs_plus_two_a_squared =
        field_add(rhs, field_double(a_squared));
    const FieldElement four_ab =
        field_double(field_double(field_multiply(a, b)));
    const FieldElement c =
        field_add(rhs_plus_two_a_squared, four_ab);
    const FieldElement d = field_negate(field_add(
        field_multiply(rhs_plus_two_a_squared, b),
        field_double(field_multiply(rhs, a))));
    const FieldElement u = field_multiply(rhs, field_square(c));
    const FieldElement v = field_double(field_square(d));
    return {
        field_double(field_add(u, v)),
        field_subtract(u, v),
    };
}

SubgroupTraceFraction subgroup_trace_reciprocal_input(
    const FieldElement& x) {
#if defined(CH6_RUNTIME_SUBGROUP_CONSTANTS)
    static const FieldElement alpha = to_montgomery(SUBGROUP_ALPHA);
    static const FieldElement gamma = to_montgomery(SUBGROUP_GAMMA);
#else
    constexpr FieldElement alpha = SUBGROUP_ALPHA_MONT;
    constexpr FieldElement gamma = SUBGROUP_GAMMA_MONT;
#endif
    // The expanded numerator and denominator both contain
    // (x-gamma)^4. Preserve its original 0/0 fail-closed semantics instead
    // of evaluating the removable singularity in the cancelled formula.
    if (field_equal(x, gamma)) {
        return {field_zero(), field_zero()};
    }
    return {field_zero(), field_subtract(x, alpha)};
}

FieldElement subgroup_trace_from_reciprocal(
    const FieldElement& reciprocal) {
    const auto& coefficients =
        subgroup_trace_reciprocal_coefficients();
    FieldElement trace = coefficients.back();
    for (std::size_t index = coefficients.size() - 1U;
         index-- > 0;) {
        trace = field_add(
            field_multiply(trace, reciprocal), coefficients[index]);
    }
    return field_add(
        field_multiply(trace, reciprocal), field_double(field_one()));
}

SubgroupTraceFraction subgroup_trace_fraction_reciprocal_polynomial(
    const FieldElement& x) {
    const SubgroupTraceFraction input =
        subgroup_trace_reciprocal_input(x);
    if (field_is_zero(input.denominator)) {
        return input;
    }
    const FieldElement& y = input.denominator;
    FieldElement numerator = field_double(field_one());
    for (const FieldElement& coefficient :
         subgroup_trace_reciprocal_coefficients()) {
        numerator =
            field_add(field_multiply(numerator, y), coefficient);
    }
    const FieldElement y_squared = field_square(y);
    const FieldElement y_fourth = field_square(y_squared);
    return {numerator, field_multiply(y_fourth, y)};
}

SubgroupTraceFraction subgroup_trace_fraction(
    const FieldElement& x, const FieldElement& rhs) {
#if defined(CH6_EXPANDED_SUBGROUP_TRACE)
    return subgroup_trace_fraction_expanded(x, rhs);
#else
    (void)rhs;
    return subgroup_trace_reciprocal_input(x);
#endif
}

FieldElement subgroup_trace_from_inverse_denominator(
    const SubgroupTraceFraction& fraction,
    const FieldElement& inverse_denominator) {
#if defined(CH6_EXPANDED_SUBGROUP_TRACE)
    return field_multiply(fraction.numerator, inverse_denominator);
#else
    (void)fraction;
    return subgroup_trace_from_reciprocal(inverse_denominator);
#endif
}

bool subgroup_trace_expanded_normalized(
    const FieldElement& x, const FieldElement& rhs,
    FieldElement& trace) {
    const SubgroupTraceFraction fraction =
        subgroup_trace_fraction_expanded(x, rhs);
    if (field_is_zero(fraction.denominator)) {
        return false;
    }
    trace = field_multiply(
        fraction.numerator, field_inverse(fraction.denominator));
    return true;
}

bool subgroup_trace_reciprocal_normalized(
    const FieldElement& x, FieldElement& trace) {
    const SubgroupTraceFraction input =
        subgroup_trace_reciprocal_input(x);
    if (field_is_zero(input.denominator)) {
        return false;
    }
    trace = subgroup_trace_from_reciprocal(
        field_inverse(input.denominator));
    return true;
}

bool subgroup_member_from_trace_binary(const FieldElement& trace) {
    static_assert((FIELD + 1U) % 5U == 0);
    static_assert((SUBGROUP_LUCAS_EXPONENT >> 85U) == 1U);
    static_assert(
        ((SUBGROUP_LUCAS_EXPONENT >> 84U) & 1U) == 0U);
    const FieldElement two = field_double(field_one());

    // L_k = W^k + W^-k.  Start with (L_1,L_2), then consume the known
    // second exponent bit 0 without recomputing L_2.
    const FieldElement l2 = field_subtract(field_square(trace), two);
    FieldElement l_k = l2;
    FieldElement l_k_plus_one =
        field_subtract(field_multiply(trace, l2), trace);
#if defined(CH6_VARIABLE_U128_LUCAS_BITS)
    for (int bit = 83; bit >= 0; --bit) {
        const bool bit_set =
            ((SUBGROUP_LUCAS_EXPONENT >> bit) & 1U) != 0;
#else
    std::uint64_t exponent_bits =
        static_cast<std::uint64_t>(SUBGROUP_LUCAS_EXPONENT >> 64U) << 44U;
    for (int remaining = 84; remaining > 0; --remaining) {
        const bool bit_set = (exponent_bits >> 63U) != 0;
        exponent_bits <<= 1U;
        if (remaining == 65) {
            exponent_bits =
                static_cast<std::uint64_t>(SUBGROUP_LUCAS_EXPONENT);
        }
#endif
        const FieldElement middle = field_subtract(
            field_multiply(l_k, l_k_plus_one), trace);
#if defined(CH6_BRANCHLESS_LUCAS_STEP)
        const std::uint64_t mask =
            0U - static_cast<std::uint64_t>(bit_set);
        const FieldElement square_input{
            (l_k.low & ~mask) | (l_k_plus_one.low & mask),
            (l_k.high & ~mask) | (l_k_plus_one.high & mask),
        };
        const FieldElement squared =
            field_subtract(field_square(square_input), two);
        l_k = {
            (squared.low & ~mask) | (middle.low & mask),
            (squared.high & ~mask) | (middle.high & mask),
        };
        l_k_plus_one = {
            (middle.low & ~mask) | (squared.low & mask),
            (middle.high & ~mask) | (squared.high & mask),
        };
#else
        if (bit_set) {
            l_k = middle;
            l_k_plus_one =
                field_subtract(field_square(l_k_plus_one), two);
        } else {
            l_k_plus_one = middle;
            l_k = field_subtract(field_square(l_k), two);
        }
#endif
    }
    return field_equal(l_k, two);
}

bool subgroup_member_from_trace_prac(const FieldElement& trace) {
    static_assert(SUBGROUP_LUCAS_EXPONENT % 20U == 0);
    static_assert(
        SUBGROUP_PRAC_EXPONENT ==
        parse_hex("22b9097fdf2db42063bbf"));
    static_assert(SUBGROUP_PRAC_SCHEDULE.size() == 115);
    const FieldElement two = field_double(field_one());
    FieldElement a = field_subtract(field_square(trace), two);
    FieldElement b = trace;
    FieldElement c = trace;
    for (const std::uint8_t encoded_rule : SUBGROUP_PRAC_SCHEDULE) {
#if defined(CH6_GENERIC_PRAC_INTERPRETER)
        if ((encoded_rule & 0x80U) != 0) {
            std::swap(a, b);
        }
        const std::uint8_t rule = encoded_rule & 0x7fU;
        if (rule == 5) {
            const FieldElement c_new =
                field_subtract(field_multiply(c, a), b);
            a = field_subtract(field_square(a), two);
            c = c_new;
            continue;
        }
        const FieldElement t =
            field_subtract(field_multiply(a, b), c);
        switch (rule) {
        case 1: {
            const FieldElement t2 =
                field_subtract(field_multiply(t, a), b);
            const FieldElement b_new =
                field_subtract(field_multiply(b, t), a);
            a = t2;
            b = b_new;
            break;
        }
        case 3:
            c = b;
            b = t;
            break;
        case 4:
            a = field_subtract(field_square(a), two);
            b = t;
            break;
        default:
            throw std::runtime_error("invalid fixed PRAC rule");
        }
#else
        switch (encoded_rule) {
        case 0x03: {
            const FieldElement t =
                field_subtract(field_multiply(a, b), c);
            c = b;
            b = t;
            break;
        }
        case 0x83: {
            const FieldElement t =
                field_subtract(field_multiply(a, b), c);
            const FieldElement old_a = a;
            a = b;
            b = t;
            c = old_a;
            break;
        }
        case 0x04: {
            const FieldElement t =
                field_subtract(field_multiply(a, b), c);
            a = field_subtract(field_square(a), two);
            b = t;
            break;
        }
        case 0x84: {
            const FieldElement t =
                field_subtract(field_multiply(a, b), c);
            a = field_subtract(field_square(b), two);
            b = t;
            break;
        }
        case 0x85: {
            const FieldElement old_a = a;
            const FieldElement c_new =
                field_subtract(field_multiply(c, b), a);
            a = field_subtract(field_square(b), two);
            b = old_a;
            c = c_new;
            break;
        }
        case 0x81: {
            std::swap(a, b);
            const FieldElement t =
                field_subtract(field_multiply(a, b), c);
            const FieldElement t2 =
                field_subtract(field_multiply(t, a), b);
            const FieldElement b_new =
                field_subtract(field_multiply(b, t), a);
            a = t2;
            b = b_new;
            break;
        }
        default:
            throw std::runtime_error("invalid fused PRAC rule");
        }
#endif
    }
    const FieldElement result =
        field_subtract(field_multiply(a, b), c);
    for (const FieldElement& root_trace :
         subgroup_20th_root_traces()) {
        if (field_equal(result, root_trace)) {
            return true;
        }
    }
    return false;
}

bool subgroup_member_from_trace(const FieldElement& trace) {
#if defined(CH6_PRAC_SUBGROUP_LUCAS)
    return subgroup_member_from_trace_prac(trace);
#else
    return subgroup_member_from_trace_binary(trace);
#endif
}

bool subgroup_member_scalar(
    const FieldElement& x, const FieldElement& rhs) {
    const SubgroupTraceFraction fraction =
        subgroup_trace_fraction(x, rhs);
    if (field_is_zero(fraction.denominator)) {
        return false;
    }
    const FieldElement trace = subgroup_trace_from_inverse_denominator(
        fraction, field_inverse(fraction.denominator));
    return subgroup_member_from_trace(trace);
}

#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
void batch_subgroup_membership(
    SubgroupTraceFraction* fractions, bool* members, std::size_t count) {
#else
void batch_subgroup_membership(
    const FieldElement* x_values, const FieldElement* rhs_values,
    bool* members, std::size_t count) {
#endif
    if (count > 256) {
        throw std::runtime_error("subgroup batch capacity exceeded");
    }
    std::fill_n(members, count, false);
    if (count == 0) {
        return;
    }

#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
    using BatchIndex = std::uint8_t;
    static_assert(std::numeric_limits<BatchIndex>::max() == 255);
#else
    using BatchIndex = std::size_t;
#endif
    std::array<BatchIndex, 256> indices CH6_SCAN_BUFFER_INITIALIZER;
#if !defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
    std::array<FieldElement, 256> numerators CH6_SCAN_BUFFER_INITIALIZER;
    std::array<FieldElement, 256> denominators CH6_SCAN_BUFFER_INITIALIZER;
#endif
    std::array<FieldElement, 256> prefixes CH6_SCAN_BUFFER_INITIALIZER;
    std::size_t active_count = 0;
    FieldElement product = field_one();
    for (std::size_t index = 0; index < count; ++index) {
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        const SubgroupTraceFraction fraction = fractions[index];
#else
        const SubgroupTraceFraction fraction =
            subgroup_trace_fraction(x_values[index], rhs_values[index]);
#endif
        if (field_is_zero(fraction.denominator)) {
            continue;
        }
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        if (active_count != index) {
            fractions[active_count] = fraction;
        }
#else
        numerators[active_count] = fraction.numerator;
        denominators[active_count] = fraction.denominator;
#endif
        indices[active_count] = static_cast<BatchIndex>(index);
        prefixes[active_count] = product;
        product = field_multiply(product, fraction.denominator);
        ++active_count;
    }
    if (active_count == 0) {
        return;
    }

    FieldElement inverse_product = field_inverse(product);
#if CH6_SUBGROUP_LUCAS_LANES == 1
    for (std::size_t active = active_count; active-- > 0;) {
        const FieldElement inverse_denominator =
            field_multiply(inverse_product, prefixes[active]);
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        inverse_product = field_multiply(
            inverse_product, fractions[active].denominator);
        const FieldElement trace =
            subgroup_trace_from_inverse_denominator(
                fractions[active], inverse_denominator);
#else
        inverse_product =
            field_multiply(inverse_product, denominators[active]);
        const FieldElement trace =
            subgroup_trace_from_inverse_denominator(
                SubgroupTraceFraction{
                    numerators[active], denominators[active]},
                inverse_denominator);
#endif
        members[indices[active]] = subgroup_member_from_trace(trace);
    }
#else
    for (std::size_t active = active_count; active-- > 0;) {
        const FieldElement inverse_denominator =
            field_multiply(inverse_product, prefixes[active]);
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        inverse_product = field_multiply(
            inverse_product, fractions[active].denominator);
        fractions[active].numerator =
            subgroup_trace_from_inverse_denominator(
                fractions[active], inverse_denominator);
#else
        inverse_product =
            field_multiply(inverse_product, denominators[active]);
        numerators[active] = subgroup_trace_from_inverse_denominator(
            SubgroupTraceFraction{
                numerators[active], denominators[active]},
            inverse_denominator);
#endif
    }

    const FieldElement two = field_double(field_one());
    std::size_t active = 0;
    for (;
         active + SUBGROUP_LUCAS_LANES <= active_count;
         active += SUBGROUP_LUCAS_LANES) {
#if defined(CH6_PRAC_SUBGROUP_LUCAS)
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            prac_a CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            prac_b CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            prac_c CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            prac_t CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            prac_next_a CH6_SCAN_BUFFER_INITIALIZER;
        for (std::size_t lane = 0; lane < SUBGROUP_LUCAS_LANES; ++lane) {
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
            const FieldElement& trace =
                fractions[active + lane].numerator;
#else
            const FieldElement& trace = numerators[active + lane];
#endif
            prac_a[lane] =
                field_subtract(field_square(trace), two);
            prac_b[lane] = trace;
            prac_c[lane] = trace;
        }
        for (const std::uint8_t encoded_rule :
             SUBGROUP_PRAC_SCHEDULE) {
            if ((encoded_rule & 0x80U) != 0) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    std::swap(prac_a[lane], prac_b[lane]);
                }
            }
            const std::uint8_t rule = encoded_rule & 0x7fU;
            if (rule == 5) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_t[lane] = field_subtract(
                        field_multiply(prac_c[lane], prac_a[lane]),
                        prac_b[lane]);
                }
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_a[lane] = field_subtract(
                        field_square(prac_a[lane]), two);
                    prac_c[lane] = prac_t[lane];
                }
                continue;
            }
            for (
                std::size_t lane = 0;
                lane < SUBGROUP_LUCAS_LANES;
                ++lane) {
                prac_t[lane] = field_subtract(
                    field_multiply(prac_a[lane], prac_b[lane]),
                    prac_c[lane]);
            }
            if (rule == 1) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_next_a[lane] = field_subtract(
                        field_multiply(prac_t[lane], prac_a[lane]),
                        prac_b[lane]);
                }
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_t[lane] = field_subtract(
                        field_multiply(prac_b[lane], prac_t[lane]),
                        prac_a[lane]);
                }
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_a[lane] = prac_next_a[lane];
                    prac_b[lane] = prac_t[lane];
                }
            } else if (rule == 3) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_c[lane] = prac_b[lane];
                    prac_b[lane] = prac_t[lane];
                }
            } else if (rule == 4) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    prac_a[lane] = field_subtract(
                        field_square(prac_a[lane]), two);
                    prac_b[lane] = prac_t[lane];
                }
            } else {
                throw std::runtime_error(
                    "invalid interleaved PRAC rule");
            }
        }
        for (std::size_t lane = 0; lane < SUBGROUP_LUCAS_LANES; ++lane) {
            const FieldElement result = field_subtract(
                field_multiply(prac_a[lane], prac_b[lane]),
                prac_c[lane]);
            bool member = false;
            for (const FieldElement& root_trace :
                 subgroup_20th_root_traces()) {
                member = member || field_equal(result, root_trace);
            }
            members[indices[active + lane]] = member;
        }
#else
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            l_k CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            l_k_plus_one CH6_SCAN_BUFFER_INITIALIZER;
        std::array<FieldElement, SUBGROUP_LUCAS_LANES>
            middle CH6_SCAN_BUFFER_INITIALIZER;
        for (std::size_t lane = 0; lane < SUBGROUP_LUCAS_LANES; ++lane) {
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
            const FieldElement& trace =
                fractions[active + lane].numerator;
#else
            const FieldElement& trace = numerators[active + lane];
#endif
            l_k[lane] = field_subtract(field_square(trace), two);
            l_k_plus_one[lane] = field_subtract(
                field_multiply(trace, l_k[lane]), trace);
        }
#if defined(CH6_VARIABLE_U128_LUCAS_BITS)
        for (int bit = 83; bit >= 0; --bit) {
            const bool bit_set =
                ((SUBGROUP_LUCAS_EXPONENT >> bit) & 1U) != 0;
#else
        std::uint64_t exponent_bits =
            static_cast<std::uint64_t>(
                SUBGROUP_LUCAS_EXPONENT >> 64U) << 44U;
        for (int remaining = 84; remaining > 0; --remaining) {
            const bool bit_set = (exponent_bits >> 63U) != 0;
            exponent_bits <<= 1U;
            if (remaining == 65) {
                exponent_bits =
                    static_cast<std::uint64_t>(SUBGROUP_LUCAS_EXPONENT);
            }
#endif
            for (std::size_t lane = 0; lane < SUBGROUP_LUCAS_LANES; ++lane) {
                middle[lane] = field_subtract(
                    field_multiply(l_k[lane], l_k_plus_one[lane]),
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
                    fractions[active + lane].numerator);
#else
                    numerators[active + lane]);
#endif
            }
            if (bit_set) {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    l_k[lane] = middle[lane];
                    l_k_plus_one[lane] = field_subtract(
                        field_square(l_k_plus_one[lane]), two);
                }
            } else {
                for (
                    std::size_t lane = 0;
                    lane < SUBGROUP_LUCAS_LANES;
                    ++lane) {
                    l_k_plus_one[lane] = middle[lane];
                    l_k[lane] =
                        field_subtract(field_square(l_k[lane]), two);
                }
            }
        }
        for (std::size_t lane = 0; lane < SUBGROUP_LUCAS_LANES; ++lane) {
            members[indices[active + lane]] = field_equal(l_k[lane], two);
        }
#endif
    }
    for (; active < active_count; ++active) {
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        members[indices[active]] = subgroup_member_from_trace(
            fractions[active].numerator);
#else
        members[indices[active]] =
            subgroup_member_from_trace(numerators[active]);
#endif
    }
#endif
}

struct AffinePoint {
    FieldElement x;
    FieldElement y;
};

struct JacobianPoint {
    FieldElement x;
    FieldElement y;
    FieldElement z;
};

static_assert(sizeof(AffinePoint) == 32);
static_assert(sizeof(JacobianPoint) == 48);

AffinePoint point_p() {
    return {to_montgomery(POINT_P_X), to_montgomery(POINT_P_Y)};
}

AffinePoint point_q() {
    return {to_montgomery(POINT_Q_X), to_montgomery(POINT_Q_Y)};
}

JacobianPoint infinity() {
    return {field_zero(), field_one(), field_zero()};
}

JacobianPoint to_jacobian(const AffinePoint& point) {
    return {point.x, point.y, field_one()};
}

JacobianPoint point_double(const JacobianPoint& point) {
    if (field_is_zero(point.z) || field_is_zero(point.y)) {
        return infinity();
    }
    const FieldElement xx = field_square(point.x);
    const FieldElement yy = field_square(point.y);
    const FieldElement yyyy = field_square(yy);
    const FieldElement zz = field_square(point.z);
    FieldElement sum = field_square(field_add(point.x, yy));
    sum = field_double(field_subtract(field_subtract(sum, xx), yyyy));
    const FieldElement three_xx = field_add(xx, field_double(xx));
    const FieldElement slope = field_add(
        three_xx, field_multiply(curve_a(), field_square(zz)));
    const FieldElement x3 = field_subtract(
        field_square(slope), field_double(sum));
    FieldElement eight_yyyy = field_double(yyyy);
    eight_yyyy = field_double(eight_yyyy);
    eight_yyyy = field_double(eight_yyyy);
    const FieldElement y3 = field_subtract(
        field_multiply(slope, field_subtract(sum, x3)), eight_yyyy);
    const FieldElement z3 =
        field_double(field_multiply(point.y, point.z));
    return {x3, y3, z3};
}

JacobianPoint point_double_minus3(const JacobianPoint& point) {
    if (field_is_zero(point.z) || field_is_zero(point.y)) {
        return infinity();
    }
    // EFD dbl-2001-b for a=-3, with Z3=2YZ: 4M+4S.  The corresponding
    // generic-a formula above is 3M+7S, so the isomorphic NAF fallback removes
    // two field operations per doubling.
    const FieldElement delta = field_square(point.z);
    const FieldElement gamma = field_square(point.y);
    const FieldElement beta = field_multiply(point.x, gamma);
    FieldElement alpha = field_multiply(
        field_subtract(point.x, delta), field_add(point.x, delta));
    alpha = field_add(alpha, field_double(alpha));
    const FieldElement two_beta = field_double(beta);
    const FieldElement four_beta = field_double(two_beta);
    const FieldElement eight_beta = field_double(four_beta);
    const FieldElement x3 =
        field_subtract(field_square(alpha), eight_beta);
    const FieldElement z3 =
        field_double(field_multiply(point.y, point.z));
    const FieldElement gamma_squared = field_square(gamma);
    FieldElement eight_gamma_squared = field_double(gamma_squared);
    eight_gamma_squared = field_double(eight_gamma_squared);
    eight_gamma_squared = field_double(eight_gamma_squared);
    const FieldElement y3 = field_subtract(
        field_multiply(alpha, field_subtract(four_beta, x3)),
        eight_gamma_squared);
    return {x3, y3, z3};
}

// madd-2007-bl style Jacobian + affine addition.  The fixed-base table and NAF
// digits always feed affine addends, avoiding the generic Jacobian formula.
template <bool Minus3Curve>
JacobianPoint point_add_mixed_impl(
    const JacobianPoint& left, const AffinePoint& right) {
    if (field_is_zero(left.z)) {
        return to_jacobian(right);
    }
    const FieldElement z1z1 = field_square(left.z);
    const FieldElement u2 = field_multiply(right.x, z1z1);
    const FieldElement s2 = field_multiply(
        right.y, field_multiply(left.z, z1z1));
    if (field_equal(u2, left.x)) {
        if (!field_equal(s2, left.y)) {
            return infinity();
        }
        if constexpr (Minus3Curve) {
            return point_double_minus3(left);
        } else {
            return point_double(left);
        }
    }
    const FieldElement h = field_subtract(u2, left.x);
    const FieldElement i = field_square(field_double(h));
    const FieldElement j = field_multiply(h, i);
    const FieldElement r = field_double(field_subtract(s2, left.y));
    const FieldElement v = field_multiply(left.x, i);
    const FieldElement x3 = field_subtract(
        field_subtract(field_square(r), j), field_double(v));
    const FieldElement y3 = field_subtract(
        field_multiply(r, field_subtract(v, x3)),
        field_double(field_multiply(left.y, j)));
    const FieldElement z3 = field_double(field_multiply(left.z, h));
    return {x3, y3, z3};
}

JacobianPoint point_add_mixed(
    const JacobianPoint& left, const AffinePoint& right) {
    return point_add_mixed_impl<false>(left, right);
}

JacobianPoint point_add_mixed_minus3(
    const JacobianPoint& left, const AffinePoint& right) {
    return point_add_mixed_impl<true>(left, right);
}

AffinePoint affine_point(const JacobianPoint& point) {
    if (field_is_zero(point.z)) {
        throw std::runtime_error("affine conversion of infinity");
    }
    const FieldElement inverse_z = field_inverse(point.z);
    const FieldElement inverse_z2 = field_square(inverse_z);
    return {
        field_multiply(point.x, inverse_z2),
        field_multiply(point.y, field_multiply(inverse_z2, inverse_z)),
    };
}

U128 affine_x(const JacobianPoint& point) {
    if (field_is_zero(point.z)) {
        throw std::runtime_error("affine x-coordinate of infinity");
    }
    const FieldElement inverse_z = field_inverse(point.z);
    return from_montgomery(
        field_multiply(point.x, field_square(inverse_z)));
}

U128 affine_x_minus3(const JacobianPoint& point) {
    if (field_is_zero(point.z)) {
        throw std::runtime_error("affine x-coordinate of infinity");
    }
    const FieldElement inverse_z = field_inverse(point.z);
    return curve_x_from_montgomery(
        field_multiply(point.x, field_square(inverse_z)));
}

void batch_normalize(
    JacobianPoint* points, AffinePoint* output, std::size_t count) {
    if (count > FIXED_NORMALIZE_CAPACITY) {
        throw std::runtime_error("batch normalization capacity exceeded");
    }
    std::array<FieldElement, FIXED_NORMALIZE_CAPACITY> prefixes{};
    FieldElement product = field_one();
    for (std::size_t index = 0; index < count; ++index) {
        if (field_is_zero(points[index].z)) {
            throw std::runtime_error("unexpected infinity in fixed table");
        }
        prefixes[index] = product;
        product = field_multiply(product, points[index].z);
    }
    FieldElement inverse_product = field_inverse(product);
    for (std::size_t index = count; index-- > 0;) {
        const FieldElement original_z = points[index].z;
        const FieldElement inverse_z =
            field_multiply(inverse_product, prefixes[index]);
        inverse_product = field_multiply(inverse_product, original_z);
        const FieldElement inverse_z2 = field_square(inverse_z);
        output[index] = {
            field_multiply(points[index].x, inverse_z2),
            field_multiply(
                points[index].y, field_multiply(inverse_z2, inverse_z)),
        };
    }
}

template <bool Minus3Curve>
void batch_affine_x_impl(
    JacobianPoint* points, U128* output, std::size_t count) {
    if (count > 256) {
        throw std::runtime_error("batch affine-x capacity exceeded");
    }
    if (count == 0) {
        return;
    }
    std::array<FieldElement, 256> prefixes CH6_SCAN_BUFFER_INITIALIZER;
    FieldElement product = field_one();
    for (std::size_t index = 0; index < count; ++index) {
        if (field_is_zero(points[index].z)) {
            throw std::runtime_error("unexpected infinity during state scan");
        }
        prefixes[index] = product;
        product = field_multiply(product, points[index].z);
    }
    FieldElement inverse_product = field_inverse(product);
    for (std::size_t index = count; index-- > 0;) {
        const FieldElement original_z = points[index].z;
        const FieldElement inverse_z =
            field_multiply(inverse_product, prefixes[index]);
        inverse_product = field_multiply(inverse_product, original_z);
        const FieldElement affine_x_value =
            field_multiply(points[index].x, field_square(inverse_z));
        if constexpr (Minus3Curve) {
            output[index] = curve_x_from_montgomery(affine_x_value);
        } else {
            output[index] = from_montgomery(affine_x_value);
        }
    }
}

#if !defined(CH6_ROW_BATCHED_FIXED_MUL)
void batch_affine_x(
    JacobianPoint* points, U128* output, std::size_t count) {
    batch_affine_x_impl<false>(points, output, count);
}
#endif

void batch_affine_x_minus3(
    JacobianPoint* points, U128* output, std::size_t count) {
    batch_affine_x_impl<true>(points, output, count);
}

struct NafDigits {
    std::array<std::int8_t, 129> digits{};
    int count = 0;
};

NafDigits make_naf(U128 scalar) {
    NafDigits result;
    while (scalar != 0) {
        int digit = 0;
        if ((scalar & 1U) != 0) {
            digit = 2 - static_cast<int>(scalar & 3U);
            if (digit > 0) {
                scalar -= static_cast<unsigned>(digit);
            } else {
                scalar += static_cast<unsigned>(-digit);
            }
        }
        if (result.count >= static_cast<int>(result.digits.size())) {
            throw std::runtime_error("NAF digit capacity exceeded");
        }
        result.digits[result.count++] = static_cast<std::int8_t>(digit);
        scalar >>= 1U;
    }
    return result;
}

template <bool Minus3Curve>
JacobianPoint scalar_mul_naf_impl(
    const NafDigits& digits, const AffinePoint& base) {
    JacobianPoint result = infinity();
    const AffinePoint negative{base.x, field_negate(base.y)};
    for (int index = digits.count - 1; index >= 0; --index) {
        if constexpr (Minus3Curve) {
            result = point_double_minus3(result);
        } else {
            result = point_double(result);
        }
        if (digits.digits[index] > 0) {
            if constexpr (Minus3Curve) {
                result = point_add_mixed_minus3(result, base);
            } else {
                result = point_add_mixed(result, base);
            }
        } else if (digits.digits[index] < 0) {
            if constexpr (Minus3Curve) {
                result = point_add_mixed_minus3(result, negative);
            } else {
                result = point_add_mixed(result, negative);
            }
        }
    }
    return result;
}

JacobianPoint scalar_mul_naf(
    const NafDigits& digits, const AffinePoint& base) {
    return scalar_mul_naf_impl<false>(digits, base);
}

JacobianPoint scalar_mul_naf_minus3(
    const NafDigits& digits, const AffinePoint& base) {
    return scalar_mul_naf_impl<true>(digits, base);
}

[[gnu::noinline]]
bool scalar_mul_hamburg_x(
    U128 scalar, const FieldElement& x, const FieldElement& x_squared,
    const FieldElement& rhs, const FieldElement& curve_a_value,
    JacobianPoint& output) {
    // This is an instance-specialized hot path selected only after telemetry
    // recovery has produced and validated EXPECTED_D.  Unknown scalars fall
    // back to the general NAF implementation in the caller.
    if (scalar != EXPECTED_D) {
        return false;
    }
    // Hamburg 2020, Figure 3.  The co-Z state represents two consecutive
    // multiples using XQP=(xQ-xP)Z^2, XRP=(xR-xP)Z^2, M=mZ and
    // YP=2yPZ^3.  It computes x([scalar]P) without carrying a y-coordinate.
    const FieldElement z_squared = field_double(field_double(rhs));
    FieldElement m = field_add(
        field_add(x_squared, field_double(x_squared)), curve_a_value);
    FieldElement xqp = field_zero();
    const FieldElement x_z_squared = field_multiply(x, z_squared);
    FieldElement xrp = field_subtract(
        field_square(m),
        field_add(x_z_squared, field_double(x_z_squared)));
    FieldElement yp = field_square(z_squared);

    for (int bit = 83; bit >= 0; --bit) {
        const bool one = ((EXPECTED_D >> bit) & 1U) != 0;
        if (!one) {
            std::swap(xqp, xrp);
        }

        const FieldElement ybar_r =
            field_add(yp, field_double(field_multiply(m, xrp)));
        const FieldElement difference = field_subtract(xqp, xrp);
        const FieldElement product = field_multiply(ybar_r, difference);
        const FieldElement difference_squared = field_square(difference);
        const FieldElement xrp_prime =
            field_multiply(xrp, difference_squared);
        const FieldElement ybar_squared = field_square(ybar_r);
        const FieldElement m_prime = field_multiply(m, product);
        const FieldElement yp_prime = field_multiply(
            field_multiply(yp, product), difference_squared);
        const FieldElement k = field_add(ybar_squared, m_prime);
        const FieldElement l = field_add(k, m_prime);
        const FieldElement m_next = field_subtract(xrp_prime, k);
        const FieldElement xsp = field_multiply(ybar_squared, l);
        const FieldElement xtp =
            field_add(field_square(xrp_prime), yp_prime);
        const FieldElement yp_next =
            field_multiply(yp_prime, ybar_squared);

        xqp = xsp;
        xrp = xtp;
        m = m_next;
        yp = yp_next;
        if (!one) {
            std::swap(xqp, xrp);
        }
    }

    const FieldElement denominator =
        field_subtract(field_subtract(field_square(m), xqp), xrp);
    if (field_is_zero(denominator)) {
        return false;
    }
    const FieldElement triple_xqp = field_add(xqp, field_double(xqp));
    const FieldElement numerator =
        field_multiply(x, field_add(denominator, triple_xqp));
    // The formula yields numerator/denominator.  Encode that ratio as
    // Jacobian X/Z^2 without an individual inversion so the block path can
    // normalize all candidates with one Montgomery batch inversion.
    output = {
        field_multiply(numerator, denominator),
        field_one(),
        denominator,
    };
    return true;
}

struct AffineReferencePoint {
    AffinePoint point{};
    bool is_infinity = true;
};

AffineReferencePoint affine_add_reference(
    const AffineReferencePoint& left,
    const AffineReferencePoint& right) {
    if (left.is_infinity) {
        return right;
    }
    if (right.is_infinity) {
        return left;
    }

    FieldElement numerator;
    FieldElement denominator;
    if (field_equal(left.point.x, right.point.x)) {
        if (!field_equal(left.point.y, right.point.y) ||
            field_is_zero(left.point.y)) {
            return {};
        }
        const FieldElement x_squared = field_square(left.point.x);
        numerator = field_add(
            field_add(x_squared, field_double(x_squared)), curve_a());
        denominator = field_double(left.point.y);
    } else {
        numerator = field_subtract(right.point.y, left.point.y);
        denominator = field_subtract(right.point.x, left.point.x);
    }
    const FieldElement slope =
        field_multiply(numerator, field_inverse(denominator));
    const FieldElement x3 = field_subtract(
        field_subtract(field_square(slope), left.point.x), right.point.x);
    const FieldElement y3 = field_subtract(
        field_multiply(slope, field_subtract(left.point.x, x3)),
        left.point.y);
    return {{x3, y3}, false};
}

AffineReferencePoint scalar_mul_affine_reference(
    U128 scalar, const AffinePoint& base) {
    AffineReferencePoint result;
    AffineReferencePoint addend{base, false};
    while (scalar != 0) {
        if ((scalar & 1U) != 0) {
            result = affine_add_reference(result, addend);
        }
        scalar >>= 1U;
        if (scalar != 0) {
            addend = affine_add_reference(addend, addend);
        }
    }
    return result;
}

struct alignas(64) FixedRow {
    std::array<AffinePoint, FIXED_TABLE_ENTRIES> points{};
};

struct FixedTable {
    std::array<FixedRow, FIXED_TABLE_ROWS> rows{};
};

void build_fixed_table(const AffinePoint& base, FixedTable& table) {
    std::array<JacobianPoint, FIXED_TABLE_ROWS> row_bases_jacobian{};
    row_bases_jacobian[0] = to_jacobian(base);
    for (std::size_t row = 1; row < row_bases_jacobian.size(); ++row) {
        JacobianPoint next = row_bases_jacobian[row - 1];
        for (std::size_t bit = 0; bit < FIXED_WINDOW_BITS; ++bit) {
            next = point_double(next);
        }
        row_bases_jacobian[row] = next;
    }
    std::array<AffinePoint, FIXED_TABLE_ROWS> row_bases{};
    batch_normalize(
        row_bases_jacobian.data(), row_bases.data(), row_bases.size());

    std::array<JacobianPoint, FIXED_TABLE_ENTRIES - 1U> multiples{};
    for (std::size_t row = 0; row < table.rows.size(); ++row) {
        multiples[0] = to_jacobian(row_bases[row]);
        for (std::size_t digit = 1; digit < multiples.size(); ++digit) {
            multiples[digit] =
                point_add_mixed(multiples[digit - 1], row_bases[row]);
        }
        batch_normalize(
            multiples.data(), table.rows[row].points.data() + 1,
            multiples.size());
    }
}

struct FixedDigit {
    unsigned magnitude;
    bool negative;
};

FixedDigit take_fixed_digit(U128& scalar) {
    unsigned digit = static_cast<unsigned>(scalar & (FIXED_RADIX - 1U));
    scalar >>= FIXED_WINDOW_BITS;
#if defined(CH6_SIGNED_FIXED_TABLE)
    const bool negative = digit > FIXED_RADIX / 2U;
    if (negative) {
        digit = static_cast<unsigned>(FIXED_RADIX) - digit;
        ++scalar;
    }
    return {digit, negative};
#else
    return {digit, false};
#endif
}

JacobianPoint fixed_mul(U128 scalar, const FixedTable& table) {
    JacobianPoint result = infinity();
    for (std::size_t row = 0; row < table.rows.size(); ++row) {
        const FixedDigit digit = take_fixed_digit(scalar);
        if (digit.magnitude != 0) {
            AffinePoint addend = table.rows[row].points[digit.magnitude];
#if defined(CH6_SIGNED_FIXED_TABLE)
            if (digit.negative) {
                addend.y = field_negate(addend.y);
            }
#endif
            result = point_add_mixed(result, addend);
        }
    }
    assert(scalar == 0);
    return result;
}

#if defined(CH6_ROW_BATCHED_FIXED_MUL)
[[gnu::noinline]]
void batch_fixed_mul_affine_x(
    const U128* scalars, U128* output, std::size_t count,
    const FixedTable& table) {
    if (count > 256) {
        throw std::runtime_error("batch fixed multiplication capacity exceeded");
    }
    std::array<U128, 256> remaining{};
    std::array<AffinePoint, 256> accumulators{};
    std::array<bool, 256> is_infinity{};
    std::copy_n(scalars, count, remaining.begin());
    std::fill_n(is_infinity.begin(), count, true);

    std::array<std::size_t, 256> active_indices{};
    std::array<FieldElement, 256> denominators{};
    std::array<FieldElement, 256> numerators{};
    std::array<FieldElement, 256> addend_x{};
    std::array<FieldElement, 256> prefixes{};
    for (std::size_t row = 0; row < table.rows.size(); ++row) {
        std::size_t active_count = 0;
        FieldElement product = field_one();
        for (std::size_t index = 0; index < count; ++index) {
            const FixedDigit digit = take_fixed_digit(remaining[index]);
            if (digit.magnitude == 0) {
                continue;
            }
            AffinePoint addend = table.rows[row].points[digit.magnitude];
#if defined(CH6_SIGNED_FIXED_TABLE)
            if (digit.negative) {
                addend.y = field_negate(addend.y);
            }
#endif
            if (is_infinity[index]) {
                accumulators[index] = addend;
                is_infinity[index] = false;
                continue;
            }
            if (field_equal(accumulators[index].x, addend.x)) {
                const AffineReferencePoint sum = affine_add_reference(
                    {accumulators[index], false}, {addend, false});
                is_infinity[index] = sum.is_infinity;
                if (!sum.is_infinity) {
                    accumulators[index] = sum.point;
                }
                continue;
            }
            active_indices[active_count] = index;
            denominators[active_count] =
                field_subtract(addend.x, accumulators[index].x);
            numerators[active_count] =
                field_subtract(addend.y, accumulators[index].y);
            addend_x[active_count] = addend.x;
            prefixes[active_count] = product;
            product = field_multiply(product, denominators[active_count]);
            ++active_count;
        }
        if (active_count == 0) {
            continue;
        }
        FieldElement inverse_product = field_inverse(product);
        for (std::size_t active = active_count; active-- > 0;) {
            const FieldElement inverse_denominator =
                field_multiply(inverse_product, prefixes[active]);
            inverse_product =
                field_multiply(inverse_product, denominators[active]);
            const std::size_t index = active_indices[active];
            const FieldElement slope =
                field_multiply(numerators[active], inverse_denominator);
            const FieldElement x3 = field_subtract(
                field_subtract(field_square(slope), accumulators[index].x),
                addend_x[active]);
            const FieldElement y3 = field_subtract(
                field_multiply(
                    slope, field_subtract(accumulators[index].x, x3)),
                accumulators[index].y);
            accumulators[index] = {x3, y3};
        }
    }
    for (std::size_t index = 0; index < count; ++index) {
        if (remaining[index] != 0) {
            throw std::runtime_error("fixed scalar exceeds table capacity");
        }
        output[index] = is_infinity[index]
            ? std::numeric_limits<U128>::max()
            : from_montgomery(accumulators[index].x);
    }
}
#endif

struct TelemetryRow {
    U128 scale;
    U128 offset;
    U128 summary;
};

constexpr std::array<TelemetryRow, 6> TELEMETRY{{
    {parse_hex("5be8f8855cda8bdb723a9"), parse_hex("12e35533ef5dde02b7027f"),
     parse_hex("1f68cf02073feacc6")},
    {parse_hex("1fbe506564b0539be633aa"), parse_hex("299e1b1adff7420cef9fe5"),
     parse_hex("cd0358f1355f0b3d")},
    {parse_hex("1fc1daff7dd3452c4caa0c"), parse_hex("240c52026e263ad3bd225a"),
     parse_hex("15a1b08ae98c4eab")},
    {parse_hex("2948590a4beb30791bb611"), parse_hex("2ac1187cf21a7b420ceff1"),
     parse_hex("2367335d000e53a71")},
    {parse_hex("1112fa15203ecdc8fc0e8f"), parse_hex("86ec8c44277687ad756e1"),
     parse_hex("3aa277ff28866b56")},
    {parse_hex("1785485643ea003095ae60"), parse_hex("15b8b80cc7b5aac0b31ee4"),
     parse_hex("2604db789049c2807")},
}};

U128 floor_sum(U128 terms, U128 modulus, U128 multiplier, U128 offset) {
    U128 answer = 0;
    while (true) {
        if (multiplier >= modulus) {
            answer += (terms - 1U) * terms * (multiplier / modulus) / 2U;
            multiplier %= modulus;
        }
        if (offset >= modulus) {
            answer += terms * (offset / modulus);
            offset %= modulus;
        }
        const U128 maximum = multiplier * terms + offset;
        if (maximum < modulus) {
            return answer;
        }
        terms = maximum / modulus;
        offset = maximum % modulus;
        std::swap(modulus, multiplier);
    }
}

U128 count_mod_less_than(
    U128 length, U128 multiplier, U128 offset, U128 bound, U128 modulus) {
    if (bound == 0) {
        return 0;
    }
    if (bound >= modulus) {
        return length;
    }
    const U128 greater_or_equal =
        floor_sum(length, modulus, multiplier, offset + modulus - bound) -
        floor_sum(length, modulus, multiplier, offset);
    return length - greater_or_equal;
}

U128 recover_backdoor_scalar() {
    constexpr U128 bucket = U128{1} << 20U;
    const U128 inverse0 =
        inverse_mod_reference(TELEMETRY[0].scale, ORDER);
    const U128 bucket0 = TELEMETRY[0].summary << 20U;
    const U128 base = mul_mod_reference(
        sub_mod(bucket0, TELEMETRY[0].offset, ORDER), inverse0, ORDER);
    const U128 multiplier =
        mul_mod_reference(TELEMETRY[1].scale, inverse0, ORDER);
    const U128 offset = add_mod(
        mul_mod_reference(TELEMETRY[1].scale, base, ORDER),
        TELEMETRY[1].offset, ORDER);
    const U128 lower = TELEMETRY[1].summary << 20U;
    const U128 upper = std::min(ORDER, lower + bucket);
    const U128 domain = std::min(bucket, ORDER - bucket0);

    const auto count_interval = [&](unsigned start, unsigned stop) {
        const U128 length = stop - start;
        const U128 shifted_offset = offset + multiplier * start;
        return count_mod_less_than(
                   length, multiplier, shifted_offset, upper, ORDER) -
               count_mod_less_than(
                   length, multiplier, shifted_offset, lower, ORDER);
    };

    std::vector<std::pair<unsigned, unsigned>> pending{
        {0, static_cast<unsigned>(domain)}};
    std::vector<unsigned> candidate_lows;
    while (!pending.empty()) {
        const auto [start, stop] = pending.back();
        pending.pop_back();
        if (count_interval(start, stop) == 0) {
            continue;
        }
        if (stop - start == 1) {
            candidate_lows.push_back(start);
            continue;
        }
        const unsigned middle = start + (stop - start) / 2U;
        pending.emplace_back(middle, stop);
        pending.emplace_back(start, middle);
    }

    U128 survivor = 0;
    int survivor_count = 0;
    for (const unsigned low : candidate_lows) {
        const U128 candidate = add_mod(
            base, mul_mod_reference(low, inverse0, ORDER), ORDER);
        bool valid = true;
        for (const auto& row : TELEMETRY) {
            const U128 value = add_mod(
                mul_mod_reference(row.scale, candidate, ORDER),
                row.offset, ORDER);
            if ((value >> 20U) != row.summary) {
                valid = false;
                break;
            }
        }
        if (valid) {
            survivor = candidate;
            ++survivor_count;
        }
    }
    if (survivor_count != 1) {
        throw std::runtime_error("telemetry did not yield exactly one scalar");
    }
    return survivor;
}

struct Prediction {
    U128 state = 0;
    U128 r3 = 0;
    int low_bits = 1 << 16;
    std::uint64_t candidates_started = 0;
};

int probe_openmp_team_size(int requested_threads) {
    omp_set_dynamic(0);
    omp_set_num_threads(requested_threads);
    int actual_threads = 0;
#pragma omp parallel shared(actual_threads)
    {
#pragma omp single
        actual_threads = omp_get_num_threads();
    }
    return actual_threads;
}

struct CandidateContext {
    U128 d;
    const NafDigits& d_digits;
    const FixedTable& q_table;
    const AffinePoint& generator_p;
};

struct PreparedLift {
    FieldElement x CH6_SCAN_BUFFER_INITIALIZER;
    FieldElement x_squared CH6_SCAN_BUFFER_INITIALIZER;
    FieldElement rhs CH6_SCAN_BUFFER_INITIALIZER;
    FieldElement y CH6_SCAN_BUFFER_INITIALIZER;
#if defined(CH6_ORIGINAL_CURVE_SCAN) && \
    !defined(CH6_NO_SUBGROUP_FILTER)
    FieldElement subgroup_x CH6_SCAN_BUFFER_INITIALIZER;
    FieldElement subgroup_rhs CH6_SCAN_BUFFER_INITIALIZER;
#endif
    bool y_available CH6_SCAN_BUFFER_INITIALIZER;
};

#if !defined(CH6_NO_SUBGROUP_FILTER)
const FieldElement& prepared_subgroup_x(const PreparedLift& prepared) {
#if defined(CH6_ORIGINAL_CURVE_SCAN)
    return prepared.subgroup_x;
#else
    return prepared.x;
#endif
}

const FieldElement& prepared_subgroup_rhs(const PreparedLift& prepared) {
#if defined(CH6_ORIGINAL_CURVE_SCAN)
    return prepared.subgroup_rhs;
#else
    return prepared.rhs;
#endif
}
#endif

bool prepare_lift(int low, PreparedLift& prepared) {
    const U128 canonical_x = (KNOWN_OUTPUTS[LIFT_OUTPUT_INDEX] << 16U) |
                             static_cast<unsigned>(low);
    if (canonical_x >= FIELD) {
        return false;
    }
    prepared.y_available = false;
    prepared.x =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        curve_x_to_montgomery(canonical_x);
#else
        to_montgomery(canonical_x);
#endif
    prepared.x_squared = field_square(prepared.x);
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    prepared.rhs = transformed_curve_rhs(prepared.x, prepared.x_squared);
#else
    prepared.rhs = field_add(
        field_add(
            field_multiply(prepared.x_squared, prepared.x),
            field_multiply(curve_a(), prepared.x)),
        curve_b());
#if !defined(CH6_NO_SUBGROUP_FILTER)
    prepared.subgroup_x = transformed_x_to_montgomery(canonical_x);
    prepared.subgroup_rhs = transformed_curve_rhs(prepared.subgroup_x);
#endif
#endif
#if !defined(CH6_SQRT_LIFT) && !defined(CH6_NAF_D_MULTIPLICATION)
    if (!field_is_square_binary_jacobi(prepared.rhs)) {
        return false;
    }
#else
    if (!field_sqrt(prepared.rhs, prepared.y)) {
        return false;
    }
    prepared.y_available = true;
#endif
    return true;
}

bool multiply_prepared_lift(
    const PreparedLift& prepared, const CandidateContext& context,
    JacobianPoint& state_point) {
    // +/-y yield opposite points, while every observation uses affine x only.
#if !defined(CH6_NAF_D_MULTIPLICATION)
    const FieldElement& curve_a_value =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        transformed_curve_a();
#else
        curve_a();
#endif
    if (!scalar_mul_hamburg_x(
            context.d, prepared.x, prepared.x_squared, prepared.rhs,
            curve_a_value, state_point)) {
        // The simple Hamburg finalization has exceptional small-order inputs.
        // Recover y only on this exceptional path, then retain the complete
        // NAF implementation as a fail-closed fallback.
        FieldElement y;
        if (prepared.y_available) {
            y = prepared.y;
        } else {
            if (!field_sqrt(prepared.rhs, y)) {
                return false;
            }
        }
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        state_point =
            scalar_mul_naf_minus3(
                context.d_digits, AffinePoint{prepared.x, y});
#else
        state_point =
            scalar_mul_naf(context.d_digits, AffinePoint{prepared.x, y});
#endif
    }
#elif !defined(CH6_ORIGINAL_CURVE_SCAN)
    if (!prepared.y_available) {
        return false;
    }
    state_point = scalar_mul_naf_minus3(
        context.d_digits, AffinePoint{prepared.x, prepared.y});
#else
    if (!prepared.y_available) {
        return false;
    }
    state_point =
        scalar_mul_naf(context.d_digits, AffinePoint{prepared.x, prepared.y});
#endif
    return true;
}

bool lift_state_point(
    int low, const CandidateContext& context, JacobianPoint& state_point) {
    PreparedLift prepared;
    if (!prepare_lift(low, prepared)) {
        return false;
    }
#if !defined(CH6_NO_SUBGROUP_FILTER)
    if (!subgroup_member_scalar(
            prepared_subgroup_x(prepared), prepared_subgroup_rhs(prepared))) {
        return false;
    }
#endif
    return multiply_prepared_lift(prepared, context, state_point);
}

bool finish_after_filter(
    int low, U128 state, const CandidateContext& context,
    Prediction& result) {
#if !defined(CH6_LEGACY_R0_SCAN)
    const U128 state4 = affine_x(
        scalar_mul_naf(make_naf(state), context.generator_p));
    const U128 r3 = affine_x(fixed_mul(state4, context.q_table)) >> 16U;
    result = {state, r3, low, 0};
    return true;
#else
    const U128 state3 = affine_x(
        scalar_mul_naf(make_naf(state), context.generator_p));
    const U128 r2 = affine_x(fixed_mul(state3, context.q_table)) >> 16U;
    if (r2 != KNOWN_OUTPUTS[2]) {
        return false;
    }
    const U128 state4 = affine_x(
        scalar_mul_naf(make_naf(state3), context.generator_p));
    const U128 r3 = affine_x(fixed_mul(state4, context.q_table)) >> 16U;
    result = {state, r3, low, 0};
    return true;
#endif
}

bool evaluate_candidate(
    int low, const CandidateContext& context, Prediction& result) {
    JacobianPoint state_point;
    if (!lift_state_point(low, context, state_point)) {
        return false;
    }
    const U128 state =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        affine_x_minus3(state_point);
#else
        affine_x(state_point);
#endif
    const U128 filter =
        affine_x(fixed_mul(state, context.q_table)) >> 16U;
    if (filter != KNOWN_OUTPUTS[FILTER_OUTPUT_INDEX]) {
        return false;
    }
    return finish_after_filter(low, state, context, result);
}

bool evaluate_candidate_block(
    int start, int stop, const CandidateContext& context,
    Prediction& result) {
    std::array<PreparedLift, 256>
        prepared_lifts CH6_SCAN_BUFFER_INITIALIZER;
    std::array<int, 256> prepared_lows CH6_SCAN_BUFFER_INITIALIZER;
    std::size_t prepared_count = 0;
    for (int low = start; low < stop; ++low) {
        if (prepare_lift(low, prepared_lifts[prepared_count])) {
            prepared_lows[prepared_count] = low;
            ++prepared_count;
        }
    }
    if (prepared_count == 0) {
        return false;
    }

    std::array<bool, 256> subgroup_members CH6_SCAN_BUFFER_INITIALIZER;
#if !defined(CH6_NO_SUBGROUP_FILTER)
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
    std::array<SubgroupTraceFraction, 256>
        subgroup_fractions CH6_SCAN_BUFFER_INITIALIZER;
    for (std::size_t index = 0; index < prepared_count; ++index) {
        subgroup_fractions[index] = subgroup_trace_fraction(
            prepared_subgroup_x(prepared_lifts[index]),
            prepared_subgroup_rhs(prepared_lifts[index]));
    }
    batch_subgroup_membership(
        subgroup_fractions.data(), subgroup_members.data(), prepared_count);
#else
    std::array<FieldElement, 256>
        subgroup_x_values CH6_SCAN_BUFFER_INITIALIZER;
    std::array<FieldElement, 256>
        subgroup_rhs_values CH6_SCAN_BUFFER_INITIALIZER;
    for (std::size_t index = 0; index < prepared_count; ++index) {
        subgroup_x_values[index] =
            prepared_subgroup_x(prepared_lifts[index]);
        subgroup_rhs_values[index] =
            prepared_subgroup_rhs(prepared_lifts[index]);
    }
    batch_subgroup_membership(
        subgroup_x_values.data(), subgroup_rhs_values.data(),
        subgroup_members.data(), prepared_count);
#endif
#else
    std::fill_n(subgroup_members.data(), prepared_count, true);
#endif

    std::array<int, 256> low_bits CH6_SCAN_BUFFER_INITIALIZER;
    std::array<JacobianPoint, 256>
        state_points CH6_SCAN_BUFFER_INITIALIZER;
    std::array<U128, 256> states CH6_SCAN_BUFFER_INITIALIZER;
    std::size_t count = 0;
    for (std::size_t index = 0; index < prepared_count; ++index) {
        if (!subgroup_members[index]) {
            continue;
        }
        JacobianPoint state_point;
        if (multiply_prepared_lift(
                prepared_lifts[index], context, state_point)) {
            low_bits[count] = prepared_lows[index];
            state_points[count] = state_point;
            ++count;
        }
    }
    if (count == 0) {
        return false;
    }
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    batch_affine_x_minus3(state_points.data(), states.data(), count);
#else
    batch_affine_x(state_points.data(), states.data(), count);
#endif

    std::array<U128, 256> output_x CH6_SCAN_BUFFER_INITIALIZER;
#if defined(CH6_ROW_BATCHED_FIXED_MUL)
    batch_fixed_mul_affine_x(
        states.data(), output_x.data(), count, context.q_table);
#else
    std::array<JacobianPoint, 256>
        output_points CH6_SCAN_BUFFER_INITIALIZER;
    for (std::size_t index = 0; index < count; ++index) {
        output_points[index] = fixed_mul(states[index], context.q_table);
    }
    batch_affine_x(output_points.data(), output_x.data(), count);
#endif

    bool found = false;
    for (std::size_t index = 0; index < count; ++index) {
        if (
            (output_x[index] >> 16U) !=
            KNOWN_OUTPUTS[FILTER_OUTPUT_INDEX]) {
            continue;
        }
        Prediction candidate;
        if (finish_after_filter(
                low_bits[index], states[index], context, candidate) &&
            candidate.low_bits < result.low_bits) {
            result = candidate;
            found = true;
        }
    }
    return found;
}

Prediction recover_state(
    U128 d, int threads, int block_size, const std::string& schedule,
    double& precompute_seconds, double& scan_seconds) {
    const auto precompute_started = std::chrono::steady_clock::now();
    const AffinePoint generator_p = point_p();
    const AffinePoint generator_q = point_q();
    const NafDigits d_digits = make_naf(d);
    FixedTable q_table;
    build_fixed_table(generator_q, q_table);
    const auto precompute_done = std::chrono::steady_clock::now();

    std::atomic<int> best_low{1 << 16};
    std::atomic<int> next_block{0};
    Prediction prediction;
    std::mutex prediction_mutex;
    const CandidateContext context{d, d_digits, q_table, generator_p};
    std::uint64_t candidates_started = 0;
    const auto record_prediction = [&](const Prediction& candidate) {
        std::lock_guard<std::mutex> guard(prediction_mutex);
        if (candidate.low_bits < prediction.low_bits) {
            prediction = candidate;
            best_low.store(candidate.low_bits, std::memory_order_relaxed);
        }
    };

    omp_set_dynamic(0);
    omp_set_num_threads(threads);
    if (schedule == "block" || schedule == "scalar") {
#pragma omp parallel reduction(+ : candidates_started)
        {
            while (true) {
                const int start = next_block.fetch_add(
                    block_size, std::memory_order_relaxed);
                if (start >= (1 << 16) ||
                    start >= best_low.load(std::memory_order_relaxed)) {
                    break;
                }
                const int stop = std::min(start + block_size, 1 << 16);
                if (schedule == "block") {
                    candidates_started += static_cast<std::uint64_t>(stop - start);
                    Prediction candidate;
                    if (evaluate_candidate_block(start, stop, context, candidate)) {
                        record_prediction(candidate);
                    }
                } else {
                    for (int low = start; low < stop; ++low) {
                        if (low >= best_low.load(std::memory_order_relaxed)) {
                            break;
                        }
                        ++candidates_started;
                        Prediction candidate;
                        if (evaluate_candidate(low, context, candidate)) {
                            record_prediction(candidate);
                        }
                    }
                }
            }
        }
    } else if (schedule == "static") {
#pragma omp parallel for schedule(static) reduction(+ : candidates_started)
        for (int low = 0; low < (1 << 16); ++low) {
            if (low >= best_low.load(std::memory_order_relaxed)) {
                continue;
            }
            ++candidates_started;
            Prediction candidate;
            if (!evaluate_candidate(low, context, candidate)) {
                continue;
            }
            record_prediction(candidate);
        }
    } else {
        throw std::runtime_error("schedule must be block, scalar, or static");
    }
    const auto scan_done = std::chrono::steady_clock::now();
    if (prediction.low_bits == (1 << 16)) {
        throw std::runtime_error("state recovery failed");
    }
    prediction.candidates_started = candidates_started;
    precompute_seconds =
        std::chrono::duration<double>(precompute_done - precompute_started).count();
    scan_seconds =
        std::chrono::duration<double>(scan_done - precompute_done).count();
    return prediction;
}

bool point_is_on_curve(const AffinePoint& point) {
    const FieldElement left = field_square(point.y);
    const FieldElement x2 = field_square(point.x);
    const FieldElement right = field_add(
        field_add(
            field_multiply(x2, point.x),
            field_multiply(curve_a(), point.x)),
        curve_b());
    return field_equal(left, right);
}

void validate_d(U128 d) {
    const AffinePoint recovered =
        affine_point(scalar_mul_naf(make_naf(d), point_q()));
    const AffinePoint expected = point_p();
    if (!field_equal(recovered.x, expected.x) ||
        !field_equal(recovered.y, expected.y)) {
        throw std::runtime_error("recovered scalar does not satisfy P = dQ");
    }
}

void run_self_test() {
    if ((FIELD & 3U) != 3U || !point_is_on_curve(point_p()) ||
        !point_is_on_curve(point_q())) {
        throw std::runtime_error("constant or curve self-test failed");
    }
    if (
        !field_equal(
            SUBGROUP_ALPHA_MONT, to_montgomery(SUBGROUP_ALPHA)) ||
        !field_equal(
            SUBGROUP_BETA_MONT, to_montgomery(SUBGROUP_BETA)) ||
        !field_equal(
            SUBGROUP_GAMMA_MONT, to_montgomery(SUBGROUP_GAMMA)) ||
        !field_equal(
            SUBGROUP_DELTA_MONT, to_montgomery(SUBGROUP_DELTA)) ||
        !field_equal(
            SUBGROUP_TANGENT_M1_MONT,
            to_montgomery(SUBGROUP_TANGENT_M1)) ||
        !field_equal(
            SUBGROUP_TANGENT_M2_MONT,
            to_montgomery(SUBGROUP_TANGENT_M2)) ||
        !field_equal(CURVE_A_MONT, to_montgomery(CURVE_A_CANON)) ||
        !field_equal(CURVE_B_MONT, to_montgomery(CURVE_B_CANON)) ||
        !field_equal(
            TRANSFORMED_CURVE_A_MONT,
            to_montgomery(TRANSFORMED_CURVE_A)) ||
        !field_equal(
            TRANSFORMED_CURVE_B_MONT,
            to_montgomery(TRANSFORMED_CURVE_B))) {
        throw std::runtime_error(
            "subgroup Montgomery constant self-test failed");
    }
    for (std::size_t index = 0;
         index < SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS.size();
         ++index) {
        if (!field_equal(
                subgroup_trace_reciprocal_coefficients()[index],
                to_montgomery(
                    SUBGROUP_TRACE_RECIPROCAL_COEFFICIENTS[index]))) {
            throw std::runtime_error(
                "subgroup reciprocal-trace constant self-test failed");
        }
    }
    const FieldElement subgroup_two = field_double(field_one());
    for (std::size_t index = 0;
         index < SUBGROUP_20TH_ROOT_TRACES.size();
         ++index) {
        for (std::size_t earlier = 0; earlier < index; ++earlier) {
            if (
                SUBGROUP_20TH_ROOT_TRACES[index] ==
                SUBGROUP_20TH_ROOT_TRACES[earlier]) {
                throw std::runtime_error(
                    "duplicate subgroup root-trace constant");
            }
        }
        if (!field_equal(
                subgroup_20th_root_traces()[index],
                to_montgomery(SUBGROUP_20TH_ROOT_TRACES[index]))) {
            throw std::runtime_error(
                "subgroup root-trace constant self-test failed");
        }
        const FieldElement& trace =
            subgroup_20th_root_traces()[index];
        const FieldElement l2 =
            field_subtract(field_square(trace), subgroup_two);
        const FieldElement l3 =
            field_subtract(field_multiply(trace, l2), trace);
        const FieldElement l4 =
            field_subtract(field_square(l2), subgroup_two);
        const FieldElement l5 =
            field_subtract(field_multiply(trace, l4), l3);
        const FieldElement l10 =
            field_subtract(field_square(l5), subgroup_two);
        const FieldElement l20 =
            field_subtract(field_square(l10), subgroup_two);
        if (
            !field_equal(l20, subgroup_two) ||
            !subgroup_member_from_trace_binary(trace) ||
            !subgroup_member_from_trace_prac(trace)) {
            throw std::runtime_error(
                "invalid subgroup root-trace constant");
        }
    }
    std::uint64_t state = UINT64_C(0x9e3779b97f4a7c15);
    const auto random64 = [&]() {
        state ^= state >> 12U;
        state ^= state << 25U;
        state ^= state >> 27U;
        return state * UINT64_C(0x2545f4914f6cdd1d);
    };
    const auto check_field_pair = [](U128 left, U128 right) {
        const FieldElement left_mont = to_montgomery(left);
        const FieldElement right_mont = to_montgomery(right);
        if (from_montgomery(left_mont) != left ||
            from_montgomery(field_add(left_mont, right_mont)) !=
                add_mod(left, right, FIELD) ||
            from_montgomery(field_subtract(left_mont, right_mont)) !=
                sub_mod(left, right, FIELD) ||
            from_montgomery(field_multiply(left_mont, right_mont)) !=
                mul_mod_reference(left, right, FIELD)) {
            throw std::runtime_error("Montgomery arithmetic self-test failed");
        }
        if (left != 0 &&
            (!field_equal(
                 field_multiply(
                     left_mont, field_inverse_binary_gcd(left_mont)),
                 field_one()) ||
             !field_equal(
                 field_inverse_binary_gcd(left_mont),
                 field_inverse_fermat(left_mont)))) {
            throw std::runtime_error("field inverse self-test failed");
        }
        const FieldElement square = field_square(left_mont);
        const FieldElement root_binary =
            field_power(square, (FIELD + 1U) >> 2U);
        const FieldElement root_window =
            field_power_window4(square, (FIELD + 1U) >> 2U);
        if (!field_equal(field_square(root_binary), square) ||
            !field_equal(field_square(root_window), square) ||
            !field_equal(root_binary, root_window)) {
            throw std::runtime_error("field square-root self-test failed");
        }
        const FieldElement legendre =
            field_power(left_mont, (FIELD - 1U) >> 1U);
        const bool expected_square =
            left == 0 || field_equal(legendre, field_one());
        if (
            field_is_square_euclidean_jacobi(left_mont) != expected_square ||
            field_is_square_hybrid_euclidean_jacobi(left_mont) !=
                expected_square ||
            field_is_square_hybrid_canonical_euclidean_jacobi(left_mont) !=
                expected_square ||
            field_is_square_hybrid_subtractive_u64_jacobi(left_mont) !=
                expected_square ||
            field_is_square_hybrid_canonical_subtractive_u64_jacobi(
                left_mont) != expected_square ||
            field_is_square_subtractive_jacobi(left_mont) != expected_square ||
            field_is_square_binary_jacobi(left_mont) != expected_square) {
            throw std::runtime_error("binary Jacobi self-test failed");
        }
        if (
            subgroup_member_from_trace_binary(left_mont) !=
            subgroup_member_from_trace_prac(left_mont)) {
            throw std::runtime_error("subgroup PRAC self-test failed");
        }
    };
    constexpr std::array<U128, 8> FIELD_BOUNDARIES{
        0,
        1,
        2,
        FIELD - 2U,
        FIELD - 1U,
        (static_cast<U128>(1) << 64U) - 1U,
        static_cast<U128>(1) << 64U,
        (static_cast<U128>(1) << 64U) + 1U,
    };
    for (const U128 left : FIELD_BOUNDARIES) {
        for (const U128 right : FIELD_BOUNDARIES) {
            check_field_pair(left, right);
        }
    }
    for (int iteration = 0; iteration < 2000; ++iteration) {
        const U128 left =
            ((static_cast<U128>(random64()) << 64U) | random64()) % FIELD;
        const U128 right =
            ((static_cast<U128>(random64()) << 64U) | random64()) % FIELD;
        check_field_pair(left, right);
    }

    const auto check_subgroup_trace_identity =
        [](const FieldElement& x, bool check_normalized_trace) {
        const FieldElement rhs = transformed_curve_rhs(x);
        const SubgroupTraceFraction expanded =
            subgroup_trace_fraction_expanded(x, rhs);
        const SubgroupTraceFraction reciprocal =
            subgroup_trace_fraction_reciprocal_polynomial(x);
        const bool expanded_undefined =
            field_is_zero(expanded.denominator);
        const bool reciprocal_undefined =
            field_is_zero(reciprocal.denominator);
        if (expanded_undefined != reciprocal_undefined) {
            throw std::runtime_error(
                "subgroup trace singularity self-test failed");
        }
        if (!expanded_undefined) {
            const FieldElement expanded_cross =
                field_multiply(
                    expanded.numerator, reciprocal.denominator);
            const FieldElement reciprocal_cross =
                field_multiply(
                    reciprocal.numerator, expanded.denominator);
            if (!field_equal(expanded_cross, reciprocal_cross)) {
                throw std::runtime_error(
                    "subgroup trace rational identity self-test failed");
            }
        }
        if (!check_normalized_trace) {
            return;
        }
        FieldElement expanded_trace{};
        FieldElement reciprocal_trace{};
        const bool expanded_defined =
            subgroup_trace_expanded_normalized(x, rhs, expanded_trace);
        const bool reciprocal_defined =
            subgroup_trace_reciprocal_normalized(x, reciprocal_trace);
        if (
            expanded_defined != reciprocal_defined ||
            (expanded_defined &&
             !field_equal(expanded_trace, reciprocal_trace))) {
            throw std::runtime_error(
                "subgroup normalized trace self-test failed");
        }
    };
    constexpr std::array<U128, 11> SUBGROUP_TRACE_BOUNDARIES{
        0,
        1,
        2,
        FIELD - 2U,
        FIELD - 1U,
        SUBGROUP_ALPHA - 1U,
        SUBGROUP_ALPHA,
        SUBGROUP_ALPHA + 1U,
        SUBGROUP_GAMMA - 1U,
        SUBGROUP_GAMMA,
        SUBGROUP_GAMMA + 1U,
    };
    for (const U128 canonical_x : SUBGROUP_TRACE_BOUNDARIES) {
        check_subgroup_trace_identity(
            to_montgomery(canonical_x), true);
    }
    for (const U128 singular_x :
         {SUBGROUP_ALPHA, SUBGROUP_GAMMA}) {
        const FieldElement x = to_montgomery(singular_x);
        const FieldElement rhs = transformed_curve_rhs(x);
        if (
            !field_is_zero(
                subgroup_trace_fraction_expanded(x, rhs).denominator) ||
            !field_is_zero(
                subgroup_trace_reciprocal_input(x).denominator) ||
            !field_is_zero(
                subgroup_trace_fraction(x, rhs).denominator)) {
            throw std::runtime_error(
                "subgroup trace singularity must fail closed");
        }
    }
    for (int iteration = 0; iteration < 512; ++iteration) {
        const U128 canonical_x =
            ((static_cast<U128>(random64()) << 64U) | random64()) %
            FIELD;
        check_subgroup_trace_identity(
            to_montgomery(canonical_x), true);
    }
    for (const U128 output_prefix : KNOWN_OUTPUTS) {
        for (unsigned low = 0; low < (1U << 16U); ++low) {
            const U128 canonical_x =
                (output_prefix << 16U) | low;
            if (canonical_x >= FIELD) {
                continue;
            }
            check_subgroup_trace_identity(
                transformed_x_to_montgomery(canonical_x), false);
        }
    }

    const AffinePoint q = point_q();
    FixedTable q_table;
    build_fixed_table(q, q_table);
    constexpr std::array<U128, 16> POINT_SCALAR_BOUNDARIES{
        1,
        255,
        256,
        257,
        511,
        512,
        (U128{1} << 81U) - 1U,
        U128{1} << 81U,
        (U128{1} << 81U) + 1U,
        (U128{1} << 87U) - 1U,
        U128{1} << 87U,
        (U128{1} << 87U) + 1U,
        ORDER - 1U,
        ORDER,
        ORDER + 1U,
        (U128{1} << 88U) - 1U,
    };
    constexpr U128 MAX_FIXED_SCALAR = (U128{1} << 88U) - 1U;
    std::array<U128, 256> point_scalars{};
    std::array<U128, 256> expected_fixed_x{};
    for (int iteration = 0; iteration < 256; ++iteration) {
        const U128 scalar =
            iteration < static_cast<int>(POINT_SCALAR_BOUNDARIES.size())
            ? POINT_SCALAR_BOUNDARIES[iteration]
            : ((((static_cast<U128>(random64()) << 64U) | random64()) %
                MAX_FIXED_SCALAR) + 1U);
        point_scalars[iteration] = scalar;
        const AffineReferencePoint reference =
            scalar_mul_affine_reference(scalar, q);
        const JacobianPoint naf_jacobian =
            scalar_mul_naf(make_naf(scalar), q);
        const JacobianPoint fixed_jacobian = fixed_mul(scalar, q_table);
        if (reference.is_infinity) {
            if (!field_is_zero(naf_jacobian.z) ||
                !field_is_zero(fixed_jacobian.z)) {
                throw std::runtime_error("point/table infinity self-test failed");
            }
            expected_fixed_x[iteration] = std::numeric_limits<U128>::max();
            continue;
        }
        if (field_is_zero(naf_jacobian.z) ||
            field_is_zero(fixed_jacobian.z)) {
            throw std::runtime_error("unexpected point self-test infinity");
        }
        const AffinePoint naf = affine_point(naf_jacobian);
        const AffinePoint fixed = affine_point(fixed_jacobian);
        expected_fixed_x[iteration] = from_montgomery(reference.point.x);
        if (!field_equal(reference.point.x, naf.x) ||
            !field_equal(reference.point.y, naf.y) ||
            !field_equal(reference.point.x, fixed.x) ||
            !field_equal(reference.point.y, fixed.y)) {
            throw std::runtime_error("point/table self-test failed");
        }
    }
#if defined(CH6_ROW_BATCHED_FIXED_MUL)
    std::array<U128, 256> batch_fixed_x{};
    batch_fixed_mul_affine_x(
        point_scalars.data(), batch_fixed_x.data(), point_scalars.size(),
        q_table);
    if (batch_fixed_x != expected_fixed_x) {
        throw std::runtime_error("row-batched fixed multiplication self-test failed");
    }
#endif
    const FieldElement transformed_q_x =
        transformed_x_to_montgomery(POINT_Q_X);
    const FieldElement transformed_q_rhs =
        transformed_curve_rhs(transformed_q_x);
    const FieldElement rational_torsion_x =
        to_montgomery(SUBGROUP_RATIONAL_TORSION_X);
    const FieldElement rational_torsion_rhs =
        transformed_curve_rhs(rational_torsion_x);
    if (!subgroup_member_scalar(transformed_q_x, transformed_q_rhs) ||
        subgroup_member_scalar(
            rational_torsion_x, rational_torsion_rhs)) {
        throw std::runtime_error("subgroup known-answer self-test failed");
    }

    const NafDigits order_digits = make_naf(ORDER);
    std::array<FieldElement, 256> subgroup_x_values{};
    std::array<FieldElement, 256> subgroup_rhs_values{};
    std::array<bool, 256> expected_subgroup_members{};
    int lifted_checked = 0;
    for (unsigned low = 0;
         low < (1U << 16U) && lifted_checked < 128;
         ++low) {
        const U128 canonical_x =
            (KNOWN_OUTPUTS[LIFT_OUTPUT_INDEX] << 16U) | low;
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        const FieldElement x = curve_x_to_montgomery(canonical_x);
        const FieldElement x_squared = field_square(x);
        const FieldElement three_x = field_add(x, field_double(x));
        const FieldElement rhs = field_add(
            field_subtract(field_multiply(x_squared, x), three_x),
            transformed_curve_b());
        const FieldElement& curve_a_value = transformed_curve_a();
#else
        const FieldElement x = to_montgomery(canonical_x);
        const FieldElement x_squared = field_square(x);
        const FieldElement rhs = field_add(
            field_add(
                field_multiply(x_squared, x),
                field_multiply(curve_a(), x)),
            curve_b());
        const FieldElement& curve_a_value = curve_a();
#endif
        FieldElement y;
        if (!field_sqrt(rhs, y)) {
            continue;
        }
        const AffinePoint base{x, y};
        const JacobianPoint naf =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
            scalar_mul_naf_minus3(make_naf(EXPECTED_D), base);
#else
            scalar_mul_naf(make_naf(EXPECTED_D), base);
#endif
        JacobianPoint hamburg;
        if (!scalar_mul_hamburg_x(
                EXPECTED_D, x, x_squared, rhs, curve_a_value, hamburg)) {
            continue;
        }
        const U128 naf_x =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
            affine_x_minus3(naf);
#else
            affine_x(naf);
#endif
        const U128 hamburg_x =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
            affine_x_minus3(hamburg);
#else
            affine_x(hamburg);
#endif
        if (naf_x != hamburg_x) {
            throw std::runtime_error("Hamburg/NAF lift self-test failed");
        }

        const FieldElement subgroup_x =
            transformed_x_to_montgomery(canonical_x);
        const FieldElement subgroup_rhs =
            transformed_curve_rhs(subgroup_x);
        FieldElement subgroup_y;
        if (!field_sqrt(subgroup_rhs, subgroup_y)) {
            throw std::runtime_error(
                "isomorphic subgroup lift self-test failed");
        }
        const bool expected_subgroup_member = field_is_zero(
            scalar_mul_naf_minus3(
                order_digits, AffinePoint{subgroup_x, subgroup_y}).z);
        if (subgroup_member_scalar(subgroup_x, subgroup_rhs) !=
            expected_subgroup_member) {
            throw std::runtime_error("scalar subgroup self-test failed");
        }
        subgroup_x_values[lifted_checked] = subgroup_x;
        subgroup_rhs_values[lifted_checked] = subgroup_rhs;
        expected_subgroup_members[lifted_checked] =
            expected_subgroup_member;
        ++lifted_checked;
    }
    if (lifted_checked != 128) {
        throw std::runtime_error("insufficient Hamburg lift self-tests");
    }
    for (std::size_t index = 128; index < subgroup_x_values.size(); ++index) {
        subgroup_x_values[index] = subgroup_x_values[index - 128];
        subgroup_rhs_values[index] = subgroup_rhs_values[index - 128];
        expected_subgroup_members[index] =
            expected_subgroup_members[index - 128];
    }
    std::array<bool, 256> batch_subgroup_members{};
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
    std::array<SubgroupTraceFraction, 256> subgroup_fractions{};
    for (std::size_t index = 0; index < subgroup_fractions.size(); ++index) {
        subgroup_fractions[index] = subgroup_trace_fraction(
            subgroup_x_values[index], subgroup_rhs_values[index]);
    }
    auto working_subgroup_fractions = subgroup_fractions;
    batch_subgroup_membership(
        working_subgroup_fractions.data(),
        batch_subgroup_members.data(), batch_subgroup_members.size());
#else
    batch_subgroup_membership(
        subgroup_x_values.data(), subgroup_rhs_values.data(),
        batch_subgroup_members.data(), batch_subgroup_members.size());
#endif
    if (batch_subgroup_members != expected_subgroup_members) {
        throw std::runtime_error("batch subgroup self-test failed");
    }
    constexpr std::array<std::size_t, 11> subgroup_tail_counts{
        1, 2, 3, 4, 5, 7, 127, 128, 129, 255, 256};
    for (const std::size_t count : subgroup_tail_counts) {
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
        working_subgroup_fractions = subgroup_fractions;
        batch_subgroup_membership(
            working_subgroup_fractions.data(),
            batch_subgroup_members.data(), count);
#else
        batch_subgroup_membership(
            subgroup_x_values.data(), subgroup_rhs_values.data(),
            batch_subgroup_members.data(), count);
#endif
        for (std::size_t index = 0; index < count; ++index) {
            if (
                batch_subgroup_members[index] !=
                expected_subgroup_members[index]) {
                throw std::runtime_error(
                    "batch subgroup tail self-test failed");
            }
        }
    }
#if defined(CH6_DIRECT_SUBGROUP_FRACTIONS)
    auto compacted_subgroup_fractions = subgroup_fractions;
    auto compacted_expected_subgroup_members =
        expected_subgroup_members;
    constexpr std::size_t known_member_index = 3;
    if (!expected_subgroup_members[known_member_index]) {
        throw std::runtime_error(
            "subgroup compaction fixture lost its known member");
    }
    compacted_subgroup_fractions[255] =
        subgroup_fractions[known_member_index];
    compacted_expected_subgroup_members[255] = true;
    constexpr std::array<std::size_t, 3> zero_denominator_indices{
        0, known_member_index, 128};
    for (const std::size_t index : zero_denominator_indices) {
        compacted_subgroup_fractions[index].denominator = field_zero();
        compacted_expected_subgroup_members[index] = false;
    }
    batch_subgroup_membership(
        compacted_subgroup_fractions.data(),
        batch_subgroup_members.data(),
        compacted_subgroup_fractions.size());
    if (batch_subgroup_members != compacted_expected_subgroup_members) {
        throw std::runtime_error(
            "batch subgroup compaction self-test failed");
    }

    std::fill(
        compacted_subgroup_fractions.begin(),
        compacted_subgroup_fractions.end(),
        SubgroupTraceFraction{field_zero(), field_zero()});
    batch_subgroup_membership(
        compacted_subgroup_fractions.data(),
        batch_subgroup_members.data(),
        compacted_subgroup_fractions.size());
    if (std::any_of(
            batch_subgroup_members.begin(),
            batch_subgroup_members.end(),
            [](bool member) { return member; })) {
        throw std::runtime_error(
            "batch subgroup empty-compaction self-test failed");
    }
#endif
    const U128 d = recover_backdoor_scalar();
    if (d != EXPECTED_D) {
        throw std::runtime_error("telemetry self-test failed");
    }
    validate_d(d);
}

}  // namespace

int main(int argc, char** argv) {
    int threads = 1;
    int block_size = 64;
    bool json = false;
    bool self_test = false;
    std::string schedule = "adaptive";
    std::string inverse_name = "binary";
    std::string sqrt_name = "window4";
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--json") {
            json = true;
        } else if (argument == "--self-test") {
            self_test = true;
        } else if (argument == "--threads" && index + 1 < argc) {
            threads = std::stoi(argv[++index]);
        } else if (argument == "--block-size" && index + 1 < argc) {
            block_size = std::stoi(argv[++index]);
        } else if (argument == "--schedule" && index + 1 < argc) {
            schedule = argv[++index];
        } else if (argument == "--inverse" && index + 1 < argc) {
            inverse_name = argv[++index];
        } else if (argument == "--sqrt" && index + 1 < argc) {
            sqrt_name = argv[++index];
        } else {
            std::cerr << "usage: " << argv[0]
                      << " [--threads N] [--schedule adaptive|block|scalar|static]"
                         " [--block-size N] [--inverse binary|fermat]"
                         " [--sqrt window4|binary] [--self-test] [--json]\n";
            return 2;
        }
    }
    if (threads < 1 || block_size < 1 || block_size > 256 ||
        (schedule != "adaptive" && schedule != "block" &&
         schedule != "scalar" && schedule != "static") ||
        (inverse_name != "binary" && inverse_name != "fermat") ||
        (sqrt_name != "window4" && sqrt_name != "binary")) {
        std::cerr << "invalid thread count, block size (1..256), schedule, inverse, or sqrt\n";
        return 2;
    }
    inverse_method = inverse_name == "binary"
        ? InverseMethod::BinaryGcd
        : InverseMethod::Fermat;
    sqrt_method = sqrt_name == "window4"
        ? SqrtMethod::Window4
        : SqrtMethod::Binary;
    const std::string effective_schedule = schedule == "adaptive"
        ? (threads <= 2 ? "block" : "scalar")
        : schedule;
    const int effective_block_size =
        schedule == "adaptive" && threads == 2 ? 32 : block_size;
    const int actual_threads = probe_openmp_team_size(threads);
    if (actual_threads != threads) {
        std::cerr << "OpenMP created " << actual_threads
                  << " threads, but " << threads << " were requested\n";
        return 2;
    }

    try {
        if (self_test) {
            run_self_test();
            std::cout << (json
                ? "{\"self_test\":true,\"field_vectors\":2000,"
                  "\"field_boundary_pairs\":64,\"point_vectors\":256,"
                  "\"hamburg_lift_vectors\":128,"
                  "\"subgroup_lift_vectors\":128}\n"
                : "self-test: ok (2000 random + 64 boundary field pairs, "
                  "256 point/table, 128 Hamburg/NAF and subgroup lift "
                  "vectors)\n");
            return 0;
        }

        const auto started = std::chrono::steady_clock::now();
        const U128 d = recover_backdoor_scalar();
        validate_d(d);
        const auto telemetry_done = std::chrono::steady_clock::now();
        double precompute_seconds = 0;
        double scan_seconds = 0;
        const Prediction prediction = recover_state(
            d, threads, effective_block_size, effective_schedule,
            precompute_seconds, scan_seconds);
        const auto finished = std::chrono::steady_clock::now();

        if (d != EXPECTED_D || prediction.state != EXPECTED_SCAN_STATE ||
            prediction.r3 != EXPECTED_R3 ||
            prediction.low_bits != EXPECTED_SCAN_LOW) {
            throw std::runtime_error("known-answer validation failed");
        }

        const double telemetry_seconds =
            std::chrono::duration<double>(telemetry_done - started).count();
        const double state_seconds =
            std::chrono::duration<double>(finished - telemetry_done).count();
        const double total_seconds =
            std::chrono::duration<double>(finished - started).count();
        if (json) {
            std::cout << "{\"implementation\":\"cpp-native-montgomery-"
                      << inverse_name << '-' << sqrt_name << '-'
                      << effective_schedule << '-' << threads
                      << "\",\"d\":\"" << hex(d)
                      << "\",\"state\":\"" << hex(prediction.state)
                      << "\",\"state_label\":\"" << SCAN_STATE_LABEL
                      << "\",\"lift_output_index\":" << LIFT_OUTPUT_INDEX
                      << ",\"filter_output_index\":" << FILTER_OUTPUT_INDEX
                      << ",\"field_backend\":\"" << FIELD_BACKEND
                      << "\",\"scan_curve_model\":\"" << SCAN_CURVE_MODEL
                      << "\",\"d_multiplication\":\"" << D_MULTIPLICATION
                      << "\",\"lift_residue_test\":\"" << LIFT_RESIDUE_TEST
                      << "\",\"subgroup_membership_test\":\""
                      << SUBGROUP_MEMBERSHIP_TEST
                      << "\",\"subgroup_constant_layout\":\""
                      << SUBGROUP_CONSTANT_LAYOUT
                      << "\",\"subgroup_batch_layout\":\""
                      << SUBGROUP_BATCH_LAYOUT
                      << "\",\"subgroup_trace_formula\":\""
                      << SUBGROUP_TRACE_FORMULA
                      << "\",\"subgroup_lucas_bit_scan\":\""
                      << SUBGROUP_LUCAS_BIT_SCAN
                      << "\",\"subgroup_lucas_step\":\""
                      << SUBGROUP_LUCAS_STEP
                      << "\",\"scan_buffer_initialization\":\""
                      << SCAN_BUFFER_INITIALIZATION
                      << "\",\"curve_constant_layout\":\""
                      << CURVE_CONSTANT_LAYOUT
                      << "\",\"r3\":\""
                      << hex(prediction.r3)
                      << "\",\"lift_low_bits\":" << prediction.low_bits
                      << ",\"schedule_requested\":\"" << schedule
                      << "\",\"schedule_effective\":\"" << effective_schedule
                      << "\",\"block_size_requested\":" << block_size
                      << ",\"block_size\":" << effective_block_size
                      << ",\"threads\":" << threads
                      << ",\"threads_actual\":" << actual_threads
                      << ",\"inverse_method\":\"" << inverse_name
                      << "\",\"sqrt_method\":\"" << sqrt_name
                      << "\",\"telemetry_strategy\":\"analytic\""
                      << ",\"p_equals_dq\":true,\"field_bytes\":"
                      << sizeof(FieldElement)
                      << ",\"jacobian_bytes\":" << sizeof(JacobianPoint)
                      << ",\"fixed_table_bytes\":" << sizeof(FixedTable)
                      << ",\"fixed_window_bits\":" << FIXED_WINDOW_BITS
                      << ",\"fixed_digit_encoding\":\""
                      << FIXED_DIGIT_ENCODING << '"'
                      << ",\"fixed_multiplication\":\""
                      << FIXED_MULTIPLICATION << '"'
                      << ",\"candidates_started\":"
                      << prediction.candidates_started
                      << ",\"telemetry_seconds\":" << std::setprecision(12)
                      << telemetry_seconds
                      << ",\"precompute_seconds\":" << precompute_seconds
                      << ",\"scan_seconds\":" << scan_seconds
                      << ",\"state_seconds\":" << state_seconds
                      << ",\"total_seconds\":" << total_seconds << "}\n";
        } else {
            std::cout << "threads = " << threads << '\n'
                      << "threads actual = " << actual_threads << '\n'
                      << "schedule requested = " << schedule << '\n'
                      << "schedule effective = " << effective_schedule << '\n'
                      << "block size requested = " << block_size << '\n'
                      << "block size effective = " << effective_block_size << '\n'
                      << "inverse = " << inverse_name << '\n'
                      << "sqrt = " << sqrt_name << '\n'
                      << "field backend = " << FIELD_BACKEND << '\n'
                      << "scan curve = " << SCAN_CURVE_MODEL << '\n'
                      << "d multiplication = " << D_MULTIPLICATION << '\n'
                      << "lift residue test = " << LIFT_RESIDUE_TEST << '\n'
                      << "subgroup membership test = "
                      << SUBGROUP_MEMBERSHIP_TEST << '\n'
                      << "subgroup constant layout = "
                      << SUBGROUP_CONSTANT_LAYOUT << '\n'
                      << "subgroup batch layout = "
                      << SUBGROUP_BATCH_LAYOUT << '\n'
                      << "subgroup trace formula = "
                      << SUBGROUP_TRACE_FORMULA << '\n'
                      << "subgroup Lucas bit scan = "
                      << SUBGROUP_LUCAS_BIT_SCAN << '\n'
                      << "subgroup Lucas step = "
                      << SUBGROUP_LUCAS_STEP << '\n'
                      << "scan buffer initialization = "
                      << SCAN_BUFFER_INITIALIZATION << '\n'
                      << "curve constant layout = "
                      << CURVE_CONSTANT_LAYOUT << '\n'
                      << "fixed multiplication = " << FIXED_MULTIPLICATION << '\n'
                      << "backdoor scalar d = " << hex(d) << '\n'
                      << "P == d*Q: True\n"
                      << "recovered state " << SCAN_STATE_LABEL << " = "
                      << hex(prediction.state) << '\n'
                      << "predicted r3 = " << hex(prediction.r3) << '\n'
                      << "lift low bits = " << prediction.low_bits << '\n'
                      << "timing: telemetry=" << telemetry_seconds
                      << "s, precompute=" << precompute_seconds
                      << "s, scan=" << scan_seconds
                      << "s, total=" << total_seconds << "s\n";
        }
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
