// Optimized challenge-6 solver using GMP and optional OpenMP parallelism.
//
// Build:
//   g++ -O3 -DNDEBUG -std=c++20 -fopenmp solve_06_gmp.cpp -lgmpxx -lgmp -o solve_06_gmp

#include <gmpxx.h>
#include <omp.h>

#include <array>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using Z = mpz_class;

const Z& field() {
    static const Z value("0xd9047b5f32dda5ca6f569b");
    return value;
}
const Z& curve_a() {
    static const Z value("0x674fdf5b55923897a16f40");
    return value;
}
const Z& curve_b() {
    static const Z value("0x1d0c9956783f6026e6c981");
    return value;
}
const Z& order() {
    static const Z value("0x2b674bdfd6fc4ba4ba751d");
    return value;
}

struct Affine {
    Z x;
    Z y;
};

struct Point {
    Z x;
    Z y;
    Z z;
};

const Affine& point_p() {
    static const Affine value{
        Z("0x5340e87bd80d1463a6ff8d"), Z("0x94ebeb5ca5b3c685e00c20")};
    return value;
}
const Affine& point_q() {
    static const Affine value{
        Z("0x4a05101411039decf537a5"), Z("0x3395a009c2210836b63d4b")};
    return value;
}
const std::array<Z, 3>& known_outputs() {
    static const std::array<Z, 3> values{
        Z("0xb3939f4aadcc13ca74"), Z("0x617985fad38ec3b1a3"),
        Z("0xd8c20715ccc94d2283")};
    return values;
}
const Point& infinity() {
    static const Point value{0, 1, 0};
    return value;
}

Z modp(Z value) {
    mpz_mod(value.get_mpz_t(), value.get_mpz_t(), field().get_mpz_t());
    return value;
}

Point to_jacobian(const Affine& point) {
    return {modp(point.x), modp(point.y), 1};
}

Point point_double(const Point& point) {
    const Z& x1 = point.x;
    const Z& y1 = point.y;
    const Z& z1 = point.z;
    if (z1 == 0 || y1 == 0) {
        return infinity();
    }
    const Z xx = modp(x1 * x1);
    const Z yy = modp(y1 * y1);
    const Z yyyy = modp(yy * yy);
    const Z zz = modp(z1 * z1);
    const Z sum = modp(2 * (modp((x1 + yy) * (x1 + yy)) - xx - yyyy));
    const Z slope = modp(3 * xx + curve_a() * modp(zz * zz));
    const Z x3 = modp(slope * slope - 2 * sum);
    const Z y3 = modp(slope * (sum - x3) - 8 * yyyy);
    const Z z3 = modp((y1 + z1) * (y1 + z1) - yy - zz);
    return {x3, y3, z3};
}

Point point_add(const Point& left, const Point& right) {
    if (left.z == 0) {
        return right;
    }
    if (right.z == 0) {
        return left;
    }

    const Z z1z1 = modp(left.z * left.z);
    const Z z2z2 = modp(right.z * right.z);
    const Z u1 = modp(left.x * z2z2);
    const Z u2 = modp(right.x * z1z1);
    const Z s1 = modp(left.y * right.z * z2z2);
    const Z s2 = modp(right.y * left.z * z1z1);
    if (u1 == u2) {
        return s1 == s2 ? point_double(left) : infinity();
    }

    const Z h = modp(u2 - u1);
    const Z i = modp(4 * h * h);
    const Z j = modp(h * i);
    const Z r = modp(2 * (s2 - s1));
    const Z v = modp(u1 * i);
    const Z x3 = modp(r * r - j - 2 * v);
    const Z y3 = modp(r * (v - x3) - 2 * s1 * j);
    const Z z3 = modp(((left.z + right.z) * (left.z + right.z) - z1z1 - z2z2) * h);
    return {x3, y3, z3};
}

Z affine_x(const Point& point) {
    if (point.z == 0) {
        throw std::runtime_error("affine conversion of infinity");
    }
    Z inverse;
    if (mpz_invert(inverse.get_mpz_t(), point.z.get_mpz_t(), field().get_mpz_t()) == 0) {
        throw std::runtime_error("non-invertible projective coordinate");
    }
    return modp(point.x * inverse * inverse);
}

bool sqrt_mod(const Z& value, Z& root) {
    static const Z exponent = (field() + 1) / 4;
    mpz_powm(root.get_mpz_t(), value.get_mpz_t(), exponent.get_mpz_t(), field().get_mpz_t());
    return modp(root * root) == modp(value);
}

std::vector<int> wnaf(Z scalar) {
    std::vector<int> digits;
    constexpr int width = 5;
    const unsigned modulus = 1U << width;
    const unsigned half = 1U << (width - 1);
    while (scalar > 0) {
        int digit = 0;
        if (mpz_odd_p(scalar.get_mpz_t())) {
            unsigned residue = mpz_fdiv_ui(scalar.get_mpz_t(), modulus);
            digit = residue >= half ? static_cast<int>(residue) - static_cast<int>(modulus)
                                    : static_cast<int>(residue);
            scalar -= digit;
        }
        digits.push_back(digit);
        mpz_fdiv_q_2exp(scalar.get_mpz_t(), scalar.get_mpz_t(), 1);
    }
    return digits;
}

Point scalar_mul_wnaf(const std::vector<int>& digits, const Affine& affine) {
    const Point base = to_jacobian(affine);
    const Point twice = point_double(base);
    std::array<Point, 8> odd{
        infinity(), infinity(), infinity(), infinity(),
        infinity(), infinity(), infinity(), infinity()};
    odd[0] = base;
    for (std::size_t i = 1; i < odd.size(); ++i) {
        odd[i] = point_add(odd[i - 1], twice);
    }

    Point result = infinity();
    for (auto it = digits.rbegin(); it != digits.rend(); ++it) {
        result = point_double(result);
        const int digit = *it;
        if (digit != 0) {
            Point addend = odd[(std::abs(digit) - 1) / 2];
            if (digit < 0) {
                addend.y = modp(-addend.y);
            }
            result = point_add(result, addend);
        }
    }
    return result;
}

using FixedTable = std::array<std::array<Point, 256>, 11>;

FixedTable build_fixed_table(const Affine& affine) {
    FixedTable table;
    Point base = to_jacobian(affine);
    for (auto& row : table) {
        row[0] = infinity();
        for (std::size_t digit = 1; digit < row.size(); ++digit) {
            row[digit] = point_add(row[digit - 1], base);
        }
        for (int bit = 0; bit < 8; ++bit) {
            base = point_double(base);
        }
    }
    return table;
}

Point fixed_mul(const Z& scalar, const FixedTable& table) {
    Point result = infinity();
    Z shifted;
    for (std::size_t position = 0; position < table.size(); ++position) {
        mpz_fdiv_q_2exp(
            shifted.get_mpz_t(), scalar.get_mpz_t(), static_cast<mp_bitcnt_t>(8 * position));
        const unsigned digit = mpz_fdiv_ui(shifted.get_mpz_t(), 256);
        if (digit != 0) {
            result = point_add(result, table[position][digit]);
        }
    }
    return result;
}

struct TelemetryRow {
    Z scale;
    Z offset;
    Z summary;
};

const std::array<TelemetryRow, 6>& telemetry() {
    static const std::array<TelemetryRow, 6> rows{{
        {Z("0x5be8f8855cda8bdb723a9"), Z("0x12e35533ef5dde02b7027f"),
         Z("0x1f68cf02073feacc6")},
        {Z("0x1fbe506564b0539be633aa"), Z("0x299e1b1adff7420cef9fe5"),
         Z("0xcd0358f1355f0b3d")},
        {Z("0x1fc1daff7dd3452c4caa0c"), Z("0x240c52026e263ad3bd225a"),
         Z("0x15a1b08ae98c4eab")},
        {Z("0x2948590a4beb30791bb611"), Z("0x2ac1187cf21a7b420ceff1"),
         Z("0x2367335d000e53a71")},
        {Z("0x1112fa15203ecdc8fc0e8f"), Z("0x86ec8c44277687ad756e1"),
         Z("0x3aa277ff28866b56")},
        {Z("0x1785485643ea003095ae60"), Z("0x15b8b80cc7b5aac0b31ee4"),
         Z("0x2604db789049c2807")},
    }};
    return rows;
}

Z recover_backdoor_scalar_recurrence() {
    const auto& rows = telemetry();
    Z scale_inverse;
    if (mpz_invert(
            scale_inverse.get_mpz_t(), rows[0].scale.get_mpz_t(), order().get_mpz_t()) == 0) {
        throw std::runtime_error("telemetry scale is not invertible");
    }
    Z candidate = ((rows[0].summary << 20) - rows[0].offset) * scale_inverse % order();
    if (candidate < 0) {
        candidate += order();
    }
    Z check_value = (rows[1].scale * candidate + rows[1].offset) % order();
    if (check_value < 0) {
        check_value += order();
    }
    const Z check_delta = rows[1].scale * scale_inverse % order();

    Z survivor;
    int survivor_count = 0;
    for (unsigned low = 0; low < (1U << 20); ++low) {
        if ((check_value >> 20) == rows[1].summary) {
            bool valid = true;
            for (std::size_t index = 2; index < rows.size(); ++index) {
                Z value = (rows[index].scale * candidate + rows[index].offset) % order();
                if (value < 0) {
                    value += order();
                }
                if ((value >> 20) != rows[index].summary) {
                    valid = false;
                    break;
                }
            }
            if (valid) {
                survivor = candidate;
                ++survivor_count;
            }
        }
        candidate += scale_inverse;
        if (candidate >= order()) {
            candidate -= order();
        }
        check_value += check_delta;
        if (check_value >= order()) {
            check_value -= order();
        }
    }
    if (survivor_count != 1) {
        throw std::runtime_error("telemetry did not yield exactly one scalar");
    }
    return survivor;
}

Z floor_sum(Z n_terms, Z modulus, Z multiplier, Z offset) {
    Z answer = 0;
    while (true) {
        if (multiplier >= modulus) {
            answer += (n_terms - 1) * n_terms * (multiplier / modulus) / 2;
            multiplier %= modulus;
        }
        if (offset >= modulus) {
            answer += n_terms * (offset / modulus);
            offset %= modulus;
        }
        const Z maximum = multiplier * n_terms + offset;
        if (maximum < modulus) {
            return answer;
        }
        const Z old_modulus = modulus;
        modulus = multiplier;
        multiplier = old_modulus;
        n_terms = maximum / old_modulus;
        offset = maximum % old_modulus;
    }
}

Z count_mod_less_than(
    const Z& length, const Z& multiplier, const Z& offset, const Z& bound,
    const Z& modulus) {
    if (bound <= 0) {
        return 0;
    }
    if (bound >= modulus) {
        return length;
    }
    const Z greater_or_equal =
        floor_sum(length, modulus, multiplier, offset + modulus - bound) -
        floor_sum(length, modulus, multiplier, offset);
    return length - greater_or_equal;
}

Z recover_backdoor_scalar_analytic() {
    const auto& rows = telemetry();
    constexpr unsigned bucket = 1U << 20;
    Z inverse0;
    if (mpz_invert(
            inverse0.get_mpz_t(), rows[0].scale.get_mpz_t(), order().get_mpz_t()) == 0) {
        throw std::runtime_error("telemetry scale is not invertible");
    }
    Z base = ((rows[0].summary << 20) - rows[0].offset) * inverse0 % order();
    if (base < 0) {
        base += order();
    }
    const Z multiplier = rows[1].scale * inverse0 % order();
    const Z offset = (rows[1].scale * base + rows[1].offset) % order();
    const Z lower = rows[1].summary << 20;
    Z upper = (rows[1].summary + 1) << 20;
    if (upper > order()) {
        upper = order();
    }
    const Z available = order() - (rows[0].summary << 20);
    const unsigned domain =
        available < bucket ? static_cast<unsigned>(available.get_ui()) : bucket;

    const auto count_interval = [&](unsigned start, unsigned stop) -> Z {
        const Z length = stop - start;
        const Z shifted_offset = offset + multiplier * start;
        const Z below_upper =
            count_mod_less_than(length, multiplier, shifted_offset, upper, order());
        const Z below_lower =
            count_mod_less_than(length, multiplier, shifted_offset, lower, order());
        return below_upper - below_lower;
    };

    std::vector<unsigned> candidate_lows;
    std::vector<std::pair<unsigned, unsigned>> pending{{0, domain}};
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
        const unsigned middle = start + (stop - start) / 2;
        pending.emplace_back(middle, stop);
        pending.emplace_back(start, middle);
    }
    if (std::getenv("SOINSU_DEBUG_TELEMETRY") != nullptr) {
        std::cerr << "analytic second-row hits: " << candidate_lows.size() << '\n';
    }

    Z survivor;
    int survivor_count = 0;
    for (const unsigned low : candidate_lows) {
        Z candidate = (base + low * inverse0) % order();
        bool valid = true;
        for (const auto& row : rows) {
            Z value = (row.scale * candidate + row.offset) % order();
            if (value < 0) {
                value += order();
            }
            if ((value >> 20) != row.summary) {
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
        throw std::runtime_error("analytic telemetry did not yield exactly one scalar");
    }
    return survivor;
}

struct Prediction {
    Z state_s2;
    Z r3;
    int low_bits;
};

Prediction recover_state(const Z& d, int threads) {
    const FixedTable q_table = build_fixed_table(point_q());
    const std::vector<int> d_digits = wnaf(d);
    std::atomic<int> best_low{1 << 16};
    std::mutex result_mutex;
    Prediction prediction{0, 0, 1 << 16};

    omp_set_num_threads(threads);
#pragma omp parallel for schedule(dynamic, 64)
    for (int low = 0; low < (1 << 16); ++low) {
        if (low >= best_low.load(std::memory_order_relaxed)) {
            continue;
        }
        Z x = (known_outputs()[0] << 16) | low;
        if (x >= field()) {
            continue;
        }
        Z rhs = modp(x * x * x + curve_a() * x + curve_b());
        Z y;
        if (!sqrt_mod(rhs, y)) {
            continue;
        }

        // The negative square root gives -(dR), whose affine x is identical.
        // The lifted point is s1*Q.  d times that point is s1*P, whose
        // affine x-coordinate is the next state s2.
        const Z state2 = affine_x(scalar_mul_wnaf(d_digits, Affine{x, y}));
        const Z r1 = affine_x(fixed_mul(state2, q_table)) >> 16;
        if (r1 != known_outputs()[1]) {
            continue;
        }
        const Z state3 = affine_x(scalar_mul_wnaf(wnaf(state2), point_p()));
        const Z r2 = affine_x(fixed_mul(state3, q_table)) >> 16;
        if (r2 != known_outputs()[2]) {
            continue;
        }
        const Z state4 = affine_x(scalar_mul_wnaf(wnaf(state3), point_p()));
        const Z r3 = affine_x(fixed_mul(state4, q_table)) >> 16;

        std::lock_guard<std::mutex> guard(result_mutex);
        if (low < prediction.low_bits) {
            prediction = {state2, r3, low};
            best_low.store(low, std::memory_order_relaxed);
        }
    }
    if (prediction.low_bits == (1 << 16)) {
        throw std::runtime_error("state recovery failed");
    }
    return prediction;
}

std::string hex(const Z& value) {
    return "0x" + value.get_str(16);
}

}  // namespace

int main(int argc, char** argv) {
    int threads = 1;
    bool json = false;
    std::string telemetry_strategy = "analytic";
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--json") {
            json = true;
        } else if (argument == "--threads" && index + 1 < argc) {
            threads = std::stoi(argv[++index]);
        } else if (argument == "--telemetry" && index + 1 < argc) {
            telemetry_strategy = argv[++index];
        } else {
            std::cerr << "usage: " << argv[0]
                      << " [--threads N] [--telemetry analytic|recurrence] [--json]\n";
            return 2;
        }
    }
    if (threads < 1) {
        std::cerr << "thread count must be positive\n";
        return 2;
    }
    if (telemetry_strategy != "analytic" && telemetry_strategy != "recurrence") {
        std::cerr << "telemetry strategy must be analytic or recurrence\n";
        return 2;
    }

    try {
        const auto started = std::chrono::steady_clock::now();
        const Z d = telemetry_strategy == "analytic" ? recover_backdoor_scalar_analytic()
                                                       : recover_backdoor_scalar_recurrence();
        const Point recovered_p = scalar_mul_wnaf(wnaf(d), point_q());
        Z inverse_z;
        if (mpz_invert(inverse_z.get_mpz_t(), recovered_p.z.get_mpz_t(),
                       field().get_mpz_t()) == 0 ||
            modp(recovered_p.x * inverse_z * inverse_z) != point_p().x ||
            modp(recovered_p.y * inverse_z * inverse_z * inverse_z) != point_p().y) {
            throw std::runtime_error("recovered scalar does not satisfy P = dQ");
        }
        const auto telemetry_done = std::chrono::steady_clock::now();
        const Prediction prediction = recover_state(d, threads);
        const auto finished = std::chrono::steady_clock::now();

        const Z expected_d("0x1c3cdd6b221806db0a7b28");
        const Z expected_state("0x638d9d631ab436da51e640");
        const Z expected_r3("0x2443c8daf1a9d52b09");
        if (d != expected_d || prediction.state_s2 != expected_state ||
            prediction.r3 != expected_r3) {
            throw std::runtime_error("known-answer validation failed");
        }

        const std::chrono::duration<double> telemetry_time = telemetry_done - started;
        const std::chrono::duration<double> state_time = finished - telemetry_done;
        const std::chrono::duration<double> total_time = finished - started;
        if (json) {
            std::cout << "{\"implementation\":\"cpp-gmp-omp-" << threads << '-'
                      << telemetry_strategy
                      << "\",\"d\":\"" << hex(d) << "\",\"state\":\""
                      << hex(prediction.state_s2)
                      << "\",\"state_label\":\"s2\",\"r3\":\""
                      << hex(prediction.r3) << "\",\"lift_low_bits\":" << prediction.low_bits
                      << ",\"telemetry_seconds\":" << std::setprecision(12)
                      << telemetry_time.count() << ",\"state_seconds\":"
                      << state_time.count() << ",\"total_seconds\":" << total_time.count()
                      << "}\n";
        } else {
            std::cout << "threads = " << threads << '\n'
                      << "backdoor scalar d = " << hex(d) << '\n'
                      << "recovered state s2 = " << hex(prediction.state_s2) << '\n'
                      << "predicted r3 = " << hex(prediction.r3) << '\n'
                      << "timing: telemetry=" << telemetry_time.count()
                      << "s, state=" << state_time.count() << "s, total="
                      << total_time.count() << "s\n";
        }
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
