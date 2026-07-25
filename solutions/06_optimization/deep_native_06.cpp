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

#if !defined(CH6_FIXED_WINDOW_BITS)
#define CH6_FIXED_WINDOW_BITS 8
#endif

constexpr std::size_t FIXED_WINDOW_BITS = CH6_FIXED_WINDOW_BITS;
constexpr std::size_t FIXED_TABLE_ROWS =
    (88U + FIXED_WINDOW_BITS - 1U) / FIXED_WINDOW_BITS;
constexpr std::size_t FIXED_TABLE_ENTRIES = 1U << FIXED_WINDOW_BITS;
constexpr std::size_t FIXED_NORMALIZE_CAPACITY =
    std::max(FIXED_TABLE_ROWS, FIXED_TABLE_ENTRIES);
static_assert(FIXED_WINDOW_BITS >= 4 && FIXED_WINDOW_BITS <= 11);

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

U128 mul_mod_reference(U128 left, U128 right, U128 modulus) {
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

inline FieldElement curve_x_to_montgomery(U128 canonical) {
    assert(canonical < FIELD);
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    return field_multiply(split(canonical), split(TRANSFORMED_X_MONTGOMERY_R2));
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
    static const FieldElement value = to_montgomery(CURVE_A_CANON);
    return value;
}

const FieldElement& curve_b() {
    static const FieldElement value = to_montgomery(CURVE_B_CANON);
    return value;
}

const FieldElement& transformed_curve_b() {
    static const FieldElement value = to_montgomery(TRANSFORMED_CURVE_B);
    return value;
}

const FieldElement& transformed_curve_a() {
    static const FieldElement value = to_montgomery(TRANSFORMED_CURVE_A);
    return value;
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
    std::array<FieldElement, 256> prefixes{};
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

void batch_affine_x(
    JacobianPoint* points, U128* output, std::size_t count) {
    batch_affine_x_impl<false>(points, output, count);
}

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

JacobianPoint fixed_mul(U128 scalar, const FixedTable& table) {
    JacobianPoint result = infinity();
    for (std::size_t row = 0; row < table.rows.size(); ++row) {
        const unsigned digit =
            static_cast<unsigned>(
                (scalar >> (FIXED_WINDOW_BITS * row)) &
                (FIXED_TABLE_ENTRIES - 1U));
        if (digit != 0) {
            result = point_add_mixed(result, table.rows[row].points[digit]);
        }
    }
    return result;
}

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

struct CandidateContext {
    U128 d;
    const NafDigits& d_digits;
    const FixedTable& q_table;
    const AffinePoint& generator_p;
};

bool lift_state_point(
    int low, const CandidateContext& context, JacobianPoint& state_point) {
    const U128 canonical_x = (KNOWN_OUTPUTS[LIFT_OUTPUT_INDEX] << 16U) |
                             static_cast<unsigned>(low);
    if (canonical_x >= FIELD) {
        return false;
    }
    const FieldElement x =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        curve_x_to_montgomery(canonical_x);
#else
        to_montgomery(canonical_x);
#endif
    const FieldElement x2 = field_square(x);
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
    const FieldElement three_x = field_add(x, field_double(x));
    const FieldElement rhs = field_add(
        field_subtract(field_multiply(x2, x), three_x),
        transformed_curve_b());
#else
    const FieldElement rhs = field_add(
        field_add(field_multiply(x2, x), field_multiply(curve_a(), x)),
        curve_b());
#endif
    FieldElement y;
    if (!field_sqrt(rhs, y)) {
        return false;
    }

    // +/-y yield opposite points, while every observation uses affine x only.
#if !defined(CH6_NAF_D_MULTIPLICATION)
    const FieldElement& curve_a_value =
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        transformed_curve_a();
#else
        curve_a();
#endif
    if (scalar_mul_hamburg_x(
            context.d, x, x2, rhs, curve_a_value, state_point)) {
    } else {
        // The simple Hamburg finalization has exceptional small-order inputs.
        // The y-coordinate is already available, so retain the complete NAF
        // path as a fail-closed fallback.
#if !defined(CH6_ORIGINAL_CURVE_SCAN)
        state_point =
            scalar_mul_naf_minus3(context.d_digits, AffinePoint{x, y});
#else
        state_point = scalar_mul_naf(context.d_digits, AffinePoint{x, y});
#endif
    }
#elif !defined(CH6_ORIGINAL_CURVE_SCAN)
    state_point =
        scalar_mul_naf_minus3(context.d_digits, AffinePoint{x, y});
#else
    state_point = scalar_mul_naf(context.d_digits, AffinePoint{x, y});
#endif
    return true;
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
    std::array<int, 256> low_bits{};
    std::array<JacobianPoint, 256> state_points{};
    std::array<U128, 256> states{};
    std::size_t count = 0;
    for (int low = start; low < stop; ++low) {
        JacobianPoint state_point;
        if (lift_state_point(low, context, state_point)) {
            low_bits[count] = low;
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

    std::array<JacobianPoint, 256> output_points{};
    std::array<U128, 256> output_x{};
    for (std::size_t index = 0; index < count; ++index) {
        output_points[index] = fixed_mul(states[index], context.q_table);
    }
    batch_affine_x(output_points.data(), output_x.data(), count);

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

    const AffinePoint q = point_q();
    FixedTable q_table;
    build_fixed_table(q, q_table);
    for (int iteration = 0; iteration < 256; ++iteration) {
        const U128 scalar = iteration < 32
            ? static_cast<unsigned>(iteration + 1)
            : (((static_cast<U128>(random64()) << 64U) | random64()) %
               (ORDER - 1U)) + 1U;
        const AffineReferencePoint reference =
            scalar_mul_affine_reference(scalar, q);
        if (reference.is_infinity) {
            throw std::runtime_error("unexpected point self-test infinity");
        }
        const AffinePoint naf =
            affine_point(scalar_mul_naf(make_naf(scalar), q));
        const AffinePoint fixed = affine_point(fixed_mul(scalar, q_table));
        if (!field_equal(reference.point.x, naf.x) ||
            !field_equal(reference.point.y, naf.y) ||
            !field_equal(reference.point.x, fixed.x) ||
            !field_equal(reference.point.y, fixed.y)) {
            throw std::runtime_error("point/table self-test failed");
        }
    }
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
        ++lifted_checked;
    }
    if (lifted_checked != 128) {
        throw std::runtime_error("insufficient Hamburg lift self-tests");
    }
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
        ? (threads == 1 ? "block" : "scalar")
        : schedule;

    try {
        if (self_test) {
            run_self_test();
            std::cout << (json
                ? "{\"self_test\":true,\"field_vectors\":2000,"
                  "\"field_boundary_pairs\":64,\"point_vectors\":256,"
                  "\"hamburg_lift_vectors\":128}\n"
                : "self-test: ok (2000 random + 64 boundary field pairs, "
                  "256 point/table, 128 Hamburg/NAF lift vectors)\n");
            return 0;
        }

        const auto started = std::chrono::steady_clock::now();
        const U128 d = recover_backdoor_scalar();
        validate_d(d);
        const auto telemetry_done = std::chrono::steady_clock::now();
        double precompute_seconds = 0;
        double scan_seconds = 0;
        const Prediction prediction = recover_state(
            d, threads, block_size, effective_schedule,
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
                      << "\",\"r3\":\""
                      << hex(prediction.r3)
                      << "\",\"lift_low_bits\":" << prediction.low_bits
                      << ",\"schedule_requested\":\"" << schedule
                      << "\",\"schedule_effective\":\"" << effective_schedule
                      << "\",\"block_size\":" << block_size
                      << ",\"threads\":" << threads
                      << ",\"inverse_method\":\"" << inverse_name
                      << "\",\"sqrt_method\":\"" << sqrt_name
                      << "\",\"telemetry_strategy\":\"analytic\""
                      << ",\"p_equals_dq\":true,\"field_bytes\":"
                      << sizeof(FieldElement)
                      << ",\"jacobian_bytes\":" << sizeof(JacobianPoint)
                      << ",\"fixed_table_bytes\":" << sizeof(FixedTable)
                      << ",\"fixed_window_bits\":" << FIXED_WINDOW_BITS
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
                      << "schedule requested = " << schedule << '\n'
                      << "schedule effective = " << effective_schedule << '\n'
                      << "inverse = " << inverse_name << '\n'
                      << "sqrt = " << sqrt_name << '\n'
                      << "field backend = " << FIELD_BACKEND << '\n'
                      << "scan curve = " << SCAN_CURVE_MODEL << '\n'
                      << "d multiplication = " << D_MULTIPLICATION << '\n'
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
