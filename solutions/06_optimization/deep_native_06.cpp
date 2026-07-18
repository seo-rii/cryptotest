// Challenge 6: fixed-width 88-bit field / POD Jacobian experiment.
//
// Build:
//   g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp
//       deep_native_06.cpp -o deep_native_06

#include <omp.h>

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
constexpr std::array<U128, 3> KNOWN_OUTPUTS{
    parse_hex("b3939f4aadcc13ca74"),
    parse_hex("617985fad38ec3b1a3"),
    parse_hex("d8c20715ccc94d2283"),
};
constexpr U128 EXPECTED_D = parse_hex("1c3cdd6b221806db0a7b28");
constexpr U128 EXPECTED_STATE_S2 = parse_hex("638d9d631ab436da51e640");
constexpr U128 EXPECTED_R3 = parse_hex("2443c8daf1a9d52b09");
constexpr int EXPECTED_LOW = 21304;

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

inline FieldElement field_multiply(
    const FieldElement& left, const FieldElement& right) {
    // Product first, followed by two REDC word eliminations.  Six limbs make
    // carry propagation explicit; reduced inputs guarantee limbs 4 and 5 are
    // zero after division by R=2^128.
    std::uint64_t limbs[6]{};
    add_product(limbs, 6, 0, left.low, right.low);
    add_product(limbs, 6, 1, left.low, right.high);
    add_product(limbs, 6, 1, left.high, right.low);
    add_product(limbs, 6, 2, left.high, right.high);

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

inline FieldElement field_square(const FieldElement& value) {
    return field_multiply(value, value);
}

inline FieldElement field_add(
    const FieldElement& left, const FieldElement& right) {
    return split(add_mod(join(left), join(right), FIELD));
}

inline FieldElement field_subtract(
    const FieldElement& left, const FieldElement& right) {
    return split(sub_mod(join(left), join(right), FIELD));
}

inline FieldElement field_double(const FieldElement& value) {
    return field_add(value, value);
}

inline FieldElement field_negate(const FieldElement& value) {
    return field_is_zero(value) ? value : split(FIELD - join(value));
}

inline FieldElement to_montgomery(U128 canonical) {
    assert(canonical < FIELD);
    return field_multiply(split(canonical), split(MONTGOMERY_R2_CANON));
}

inline U128 from_montgomery(const FieldElement& value) {
    return join(field_multiply(value, split(1)));
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
    root = sqrt_method == SqrtMethod::Window4
        ? field_power_window4(value, exponent)
        : field_power(value, exponent);
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
    const FieldElement z3 = field_subtract(
        field_subtract(field_square(field_add(point.y, point.z)), yy), zz);
    return {x3, y3, z3};
}

// madd-2007-bl style Jacobian + affine addition.  The fixed-base table and NAF
// digits always feed affine addends, avoiding the generic Jacobian formula.
JacobianPoint point_add_mixed(
    const JacobianPoint& left, const AffinePoint& right) {
    if (field_is_zero(left.z)) {
        return to_jacobian(right);
    }
    const FieldElement z1z1 = field_square(left.z);
    const FieldElement u2 = field_multiply(right.x, z1z1);
    const FieldElement s2 = field_multiply(
        right.y, field_multiply(left.z, z1z1));
    if (field_equal(u2, left.x)) {
        return field_equal(s2, left.y) ? point_double(left) : infinity();
    }
    const FieldElement h = field_subtract(u2, left.x);
    const FieldElement hh = field_square(h);
    const FieldElement i = field_double(field_double(hh));
    const FieldElement j = field_multiply(h, i);
    const FieldElement r = field_double(field_subtract(s2, left.y));
    const FieldElement v = field_multiply(left.x, i);
    const FieldElement x3 = field_subtract(
        field_subtract(field_square(r), j), field_double(v));
    const FieldElement y3 = field_subtract(
        field_multiply(r, field_subtract(v, x3)),
        field_double(field_multiply(left.y, j)));
    const FieldElement z3 = field_subtract(
        field_subtract(field_square(field_add(left.z, h)), z1z1), hh);
    return {x3, y3, z3};
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

void batch_normalize(
    JacobianPoint* points, AffinePoint* output, std::size_t count) {
    if (count > 256) {
        throw std::runtime_error("batch normalization capacity exceeded");
    }
    std::array<FieldElement, 256> prefixes{};
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

void batch_affine_x(
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
        output[index] = from_montgomery(
            field_multiply(points[index].x, field_square(inverse_z)));
    }
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

JacobianPoint scalar_mul_naf(
    const NafDigits& digits, const AffinePoint& base) {
    JacobianPoint result = infinity();
    const AffinePoint negative{base.x, field_negate(base.y)};
    for (int index = digits.count - 1; index >= 0; --index) {
        result = point_double(result);
        if (digits.digits[index] > 0) {
            result = point_add_mixed(result, base);
        } else if (digits.digits[index] < 0) {
            result = point_add_mixed(result, negative);
        }
    }
    return result;
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
    std::array<AffinePoint, 256> points{};
};

struct FixedTable {
    std::array<FixedRow, 11> rows{};
};

static_assert(sizeof(FixedRow) == 8192);
static_assert(sizeof(FixedTable) == 90112);

void build_fixed_table(const AffinePoint& base, FixedTable& table) {
    std::array<JacobianPoint, 11> row_bases_jacobian{};
    row_bases_jacobian[0] = to_jacobian(base);
    for (std::size_t row = 1; row < row_bases_jacobian.size(); ++row) {
        JacobianPoint next = row_bases_jacobian[row - 1];
        for (int bit = 0; bit < 8; ++bit) {
            next = point_double(next);
        }
        row_bases_jacobian[row] = next;
    }
    std::array<AffinePoint, 11> row_bases{};
    batch_normalize(
        row_bases_jacobian.data(), row_bases.data(), row_bases.size());

    std::array<JacobianPoint, 255> multiples{};
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
            static_cast<unsigned>((scalar >> (8U * row)) & 0xffU);
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
    U128 state_s2 = 0;
    U128 r3 = 0;
    int low_bits = 1 << 16;
    std::uint64_t candidates_started = 0;
};

struct CandidateContext {
    const NafDigits& d_digits;
    const FixedTable& q_table;
    const AffinePoint& generator_p;
};

bool lift_state_point(
    int low, const CandidateContext& context, JacobianPoint& state_point) {
    const U128 canonical_x = (KNOWN_OUTPUTS[0] << 16U) |
                             static_cast<unsigned>(low);
    if (canonical_x >= FIELD) {
        return false;
    }
    const FieldElement x = to_montgomery(canonical_x);
    const FieldElement x2 = field_square(x);
    const FieldElement rhs = field_add(
        field_add(field_multiply(x2, x), field_multiply(curve_a(), x)),
        curve_b());
    FieldElement y;
    if (!field_sqrt(rhs, y)) {
        return false;
    }

    // +/-y yield opposite points, while every observation uses affine x only.
    state_point = scalar_mul_naf(context.d_digits, AffinePoint{x, y});
    return true;
}

bool finish_after_r1(
    int low, U128 state2, const CandidateContext& context,
    Prediction& result) {
    const U128 state3 = affine_x(
        scalar_mul_naf(make_naf(state2), context.generator_p));
    const U128 r2 = affine_x(fixed_mul(state3, context.q_table)) >> 16U;
    if (r2 != KNOWN_OUTPUTS[2]) {
        return false;
    }
    const U128 state4 = affine_x(
        scalar_mul_naf(make_naf(state3), context.generator_p));
    const U128 r3 = affine_x(fixed_mul(state4, context.q_table)) >> 16U;
    result = {state2, r3, low, 0};
    return true;
}

bool evaluate_candidate(
    int low, const CandidateContext& context, Prediction& result) {
    JacobianPoint state_point;
    if (!lift_state_point(low, context, state_point)) {
        return false;
    }
    const U128 state2 = affine_x(state_point);
    const U128 r1 = affine_x(fixed_mul(state2, context.q_table)) >> 16U;
    if (r1 != KNOWN_OUTPUTS[1]) {
        return false;
    }
    return finish_after_r1(low, state2, context, result);
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
    batch_affine_x(state_points.data(), states.data(), count);

    std::array<JacobianPoint, 256> output_points{};
    std::array<U128, 256> output_x{};
    for (std::size_t index = 0; index < count; ++index) {
        output_points[index] = fixed_mul(states[index], context.q_table);
    }
    batch_affine_x(output_points.data(), output_x.data(), count);

    bool found = false;
    for (std::size_t index = 0; index < count; ++index) {
        if ((output_x[index] >> 16U) != KNOWN_OUTPUTS[1]) {
            continue;
        }
        Prediction candidate;
        if (finish_after_r1(
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
    const CandidateContext context{d_digits, q_table, generator_p};
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
    for (int iteration = 0; iteration < 2000; ++iteration) {
        const U128 left =
            ((static_cast<U128>(random64()) << 64U) | random64()) % FIELD;
        const U128 right =
            ((static_cast<U128>(random64()) << 64U) | random64()) % FIELD;
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
                  "\"point_vectors\":256}\n"
                : "self-test: ok (2000 field, 256 point/table vectors)\n");
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

        if (d != EXPECTED_D || prediction.state_s2 != EXPECTED_STATE_S2 ||
            prediction.r3 != EXPECTED_R3 ||
            prediction.low_bits != EXPECTED_LOW) {
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
                      << "\",\"state\":\"" << hex(prediction.state_s2)
                      << "\",\"state_label\":\"s2\",\"r3\":\""
                      << hex(prediction.r3)
                      << "\",\"lift_low_bits\":" << prediction.low_bits
                      << ",\"schedule_requested\":\"" << schedule
                      << "\",\"schedule_effective\":\"" << effective_schedule
                      << "\",\"p_equals_dq\":true,\"field_bytes\":"
                      << sizeof(FieldElement)
                      << ",\"jacobian_bytes\":" << sizeof(JacobianPoint)
                      << ",\"fixed_table_bytes\":" << sizeof(FixedTable)
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
                      << "backdoor scalar d = " << hex(d) << '\n'
                      << "P == d*Q: True\n"
                      << "recovered state s2 = " << hex(prediction.state_s2) << '\n'
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
