// Deep algorithm candidates for challenge 6.
//
// This file deliberately includes, but does not modify, the verified GMP solver
// so that both candidate paths reuse exactly the same curve constants, telemetry
// recovery, fixed-Q table, and known-answer checks.
#define main baseline_main_06_for_reuse
#include "solve_06_gmp.cpp"
#undef main

#include <optional>

namespace {

struct XPoint {
    Z x;
    Z z;
};

XPoint x_double(const XPoint& point) {
    if (point.z == 0) {
        return {1, 0};
    }
    const Z x2 = modp(point.x * point.x);
    const Z z2 = modp(point.z * point.z);
    const Z x_minus_az = modp(x2 - curve_a() * z2);
    const Z x_out = modp(
        x_minus_az * x_minus_az -
        8 * curve_b() * point.x * point.z * z2);
    const Z z_out = modp(
        4 * point.z *
        (point.x * x2 + curve_a() * point.x * z2 + curve_b() * point.z * z2));
    return {x_out, z_out};
}

XPoint x_differential_add(
    const XPoint& left, const XPoint& right, const Z& difference_x) {
    const Z z_product = modp(left.z * right.z);
    const Z left_cross = modp(left.x * right.z);
    const Z right_cross = modp(right.x * left.z);
    const Z core = modp(left.x * right.x - curve_a() * z_product);
    const Z x_out = modp(
        core * core - 4 * curve_b() * z_product * (left_cross + right_cross));
    const Z delta = modp(left_cross - right_cross);
    const Z z_out = modp(difference_x * delta * delta);
    return {x_out, z_out};
}

XPoint x_ladder(const Z& scalar, const Z& affine_x_value) {
    if (scalar == 0) {
        return {1, 0};
    }
    XPoint lower{affine_x_value, 1};
    if (scalar == 1) {
        return lower;
    }
    XPoint upper = x_double(lower);
    const std::size_t bit_length = mpz_sizeinbase(scalar.get_mpz_t(), 2);
    for (std::size_t bit = bit_length - 1; bit-- > 0;) {
        if (mpz_tstbit(scalar.get_mpz_t(), bit) == 0) {
            upper = x_differential_add(lower, upper, affine_x_value);
            lower = x_double(lower);
        } else {
            lower = x_differential_add(lower, upper, affine_x_value);
            upper = x_double(upper);
        }
    }
    return lower;
}

Z affine_x(const XPoint& point) {
    if (point.z == 0) {
        throw std::runtime_error("x-only affine conversion of infinity");
    }
    Z inverse;
    if (mpz_invert(inverse.get_mpz_t(), point.z.get_mpz_t(), field().get_mpz_t()) == 0) {
        throw std::runtime_error("x-only denominator is non-invertible");
    }
    return modp(point.x * inverse);
}

std::vector<Z> batch_invert(const std::vector<Z>& values) {
    std::vector<Z> inverses(values.size(), 0);
    std::vector<std::size_t> indices;
    std::vector<Z> prefixes;
    indices.reserve(values.size());
    prefixes.reserve(values.size());
    Z product = 1;
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (values[index] == 0) {
            continue;
        }
        indices.push_back(index);
        prefixes.push_back(product);
        product = modp(product * values[index]);
    }
    if (indices.empty()) {
        return inverses;
    }
    Z reciprocal;
    if (mpz_invert(reciprocal.get_mpz_t(), product.get_mpz_t(), field().get_mpz_t()) == 0) {
        throw std::runtime_error("batch product is non-invertible");
    }
    for (std::size_t position = indices.size(); position-- > 0;) {
        const std::size_t index = indices[position];
        inverses[index] = modp(reciprocal * prefixes[position]);
        reciprocal = modp(reciprocal * values[index]);
    }
    return inverses;
}

std::vector<Z> batch_affine_x(const std::vector<XPoint>& points) {
    std::vector<Z> denominators;
    denominators.reserve(points.size());
    for (const auto& point : points) {
        denominators.push_back(point.z);
    }
    const std::vector<Z> inverses = batch_invert(denominators);
    std::vector<Z> result(points.size(), 0);
    for (std::size_t index = 0; index < points.size(); ++index) {
        if (points[index].z != 0) {
            result[index] = modp(points[index].x * inverses[index]);
        }
    }
    return result;
}

std::vector<Z> batch_affine_x(const std::vector<Point>& points) {
    std::vector<Z> denominators;
    denominators.reserve(points.size());
    for (const auto& point : points) {
        denominators.push_back(point.z);
    }
    const std::vector<Z> inverses = batch_invert(denominators);
    std::vector<Z> result(points.size(), 0);
    for (std::size_t index = 0; index < points.size(); ++index) {
        if (points[index].z != 0) {
            result[index] = modp(points[index].x * inverses[index] * inverses[index]);
        }
    }
    return result;
}

std::vector<int> candidate_wnaf(Z scalar, int width) {
    std::vector<int> digits;
    const unsigned modulus = 1U << width;
    const unsigned half = 1U << (width - 1);
    while (scalar > 0) {
        int digit = 0;
        if (mpz_odd_p(scalar.get_mpz_t())) {
            const unsigned residue = mpz_fdiv_ui(scalar.get_mpz_t(), modulus);
            digit = residue >= half ? static_cast<int>(residue) - static_cast<int>(modulus)
                                    : static_cast<int>(residue);
            scalar -= digit;
        }
        digits.push_back(digit);
        mpz_fdiv_q_2exp(scalar.get_mpz_t(), scalar.get_mpz_t(), 1);
    }
    return digits;
}

Point candidate_scalar_mul(
    const std::vector<int>& digits, const Affine& affine, int width) {
    const Point base = to_jacobian(affine);
    const Point twice = point_double(base);
    std::vector<Point> odd(1U << (width - 2), infinity());
    odd[0] = base;
    for (std::size_t index = 1; index < odd.size(); ++index) {
        odd[index] = point_add(odd[index - 1], twice);
    }
    Point result = infinity();
    for (auto digit = digits.rbegin(); digit != digits.rend(); ++digit) {
        result = point_double(result);
        if (*digit != 0) {
            Point addend = odd[(std::abs(*digit) - 1) / 2];
            if (*digit < 0) {
                addend.y = modp(-addend.y);
            }
            result = point_add(result, addend);
        }
    }
    return result;
}

bool candidate_sqrt(const Z& rhs, Z& root, bool legendre_prefilter) {
    if (rhs == 0) {
        root = 0;
        return true;
    }
    if (legendre_prefilter && mpz_legendre(rhs.get_mpz_t(), field().get_mpz_t()) != 1) {
        return false;
    }
    return sqrt_mod(rhs, root);
}

std::optional<Prediction> finish_candidate(
    int low, const Z& input_x, const Z& state2, const FixedTable& q_table,
    int width) {
    Z root;
    const Z rhs = modp(input_x * input_x * input_x + curve_a() * input_x + curve_b());
    if (!sqrt_mod(rhs, root)) {
        return std::nullopt;
    }
    const Z state3 = affine_x(candidate_scalar_mul(
        candidate_wnaf(state2, width), point_p(), width));
    const Z r2 = affine_x(fixed_mul(state3, q_table)) >> 16;
    if (r2 != known_outputs()[2]) {
        return std::nullopt;
    }
    const Z state4 = affine_x(candidate_scalar_mul(
        candidate_wnaf(state3, width), point_p(), width));
    const Z r3 = affine_x(fixed_mul(state4, q_table)) >> 16;
    return Prediction{state2, r3, low};
}

struct CandidateOptions {
    std::string mode = "jacobian-batch";
    int threads = 1;
    int block_size = 128;
    int width = 4;
    bool finite_difference = true;
    bool legendre_prefilter = true;
};

Prediction recover_state_candidates(const Z& d, const CandidateOptions& options) {
    const FixedTable q_table = build_fixed_table(point_q());
    const std::vector<int> d_digits = candidate_wnaf(d, options.width);
    std::atomic<int> best_low{1 << 16};
    std::mutex result_mutex;
    Prediction prediction{0, 0, 1 << 16};
    const int blocks = ((1 << 16) + options.block_size - 1) / options.block_size;

    omp_set_num_threads(options.threads);
#pragma omp parallel
    {
        std::vector<int> lows;
        std::vector<Z> xs;
        std::vector<Z> states;
        std::vector<Point> state_points;
        std::vector<XPoint> x_state_points;
        std::vector<Point> output_points;
        lows.reserve(options.block_size);
        xs.reserve(options.block_size);
        state_points.reserve(options.block_size);
        x_state_points.reserve(options.block_size);
        output_points.reserve(options.block_size);
#pragma omp for schedule(dynamic, 1)
        for (int block_index = 0; block_index < blocks; ++block_index) {
        const int start = block_index * options.block_size;
        const int stop = std::min(1 << 16, start + options.block_size);
        if (start >= best_low.load(std::memory_order_relaxed)) {
            continue;
        }

        lows.clear();
        xs.clear();
        states.clear();
        state_points.clear();
        x_state_points.clear();
        output_points.clear();

        Z x = (known_outputs()[0] << 16) | start;
        Z rhs = modp(x * x * x + curve_a() * x + curve_b());
        Z delta1 = modp(3 * x * x + 3 * x + 1 + curve_a());
        Z delta2 = modp(6 * x + 6);
        for (int low = start; low < stop; ++low) {
            if (low >= best_low.load(std::memory_order_relaxed)) {
                break;
            }
            if (options.mode == "jacobian-batch") {
                Z root;
                const Z direct_rhs = options.finite_difference
                                         ? rhs
                                         : modp(x * x * x + curve_a() * x + curve_b());
                if (candidate_sqrt(direct_rhs, root, options.legendre_prefilter)) {
                    lows.push_back(low);
                    xs.push_back(x);
                    state_points.push_back(candidate_scalar_mul(
                        d_digits, Affine{x, root}, options.width));
                }
            } else {
                bool keep = true;
                if (options.legendre_prefilter) {
                    const Z direct_rhs = options.finite_difference
                                             ? rhs
                                             : modp(x * x * x + curve_a() * x + curve_b());
                    keep = direct_rhs == 0 ||
                           mpz_legendre(direct_rhs.get_mpz_t(), field().get_mpz_t()) == 1;
                }
                if (keep) {
                    lows.push_back(low);
                    xs.push_back(x);
                    x_state_points.push_back(x_ladder(d, x));
                }
            }
            x = modp(x + 1);
            if (options.finite_difference) {
                rhs = modp(rhs + delta1);
                delta1 = modp(delta1 + delta2);
                delta2 = modp(delta2 + 6);
            }
        }

        if (options.mode == "jacobian-batch") {
            states = batch_affine_x(state_points);
        } else {
            states = batch_affine_x(x_state_points);
        }
        for (const Z& state : states) {
            output_points.push_back(state == 0 ? infinity() : fixed_mul(state, q_table));
        }
        const std::vector<Z> outputs = batch_affine_x(output_points);

        for (std::size_t index = 0; index < outputs.size(); ++index) {
            if (outputs[index] >> 16 != known_outputs()[1]) {
                continue;
            }
            const auto completed =
                finish_candidate(lows[index], xs[index], states[index], q_table, options.width);
            if (!completed) {
                continue;
            }
            std::lock_guard<std::mutex> guard(result_mutex);
            if (completed->low_bits < prediction.low_bits) {
                prediction = *completed;
                best_low.store(completed->low_bits, std::memory_order_relaxed);
            }
        }
        }
    }
    if (prediction.low_bits == (1 << 16)) {
        throw std::runtime_error("algorithm candidate did not recover the state");
    }
    return prediction;
}

Prediction recover_state_scalar(const Z& d, const CandidateOptions& options) {
    const FixedTable q_table = build_fixed_table(point_q());
    const std::vector<int> d_digits = candidate_wnaf(d, options.width);
    std::atomic<int> best_low{1 << 16};
    std::mutex result_mutex;
    Prediction prediction{0, 0, 1 << 16};

    omp_set_num_threads(options.threads);
#pragma omp parallel for schedule(dynamic, 64)
    for (int low = 0; low < (1 << 16); ++low) {
        if (low >= best_low.load(std::memory_order_relaxed)) {
            continue;
        }
        const Z x = (known_outputs()[0] << 16) | low;
        const Z rhs = modp(x * x * x + curve_a() * x + curve_b());
        Z root;
        if (!candidate_sqrt(rhs, root, options.legendre_prefilter)) {
            continue;
        }
        const Z state2 = affine_x(candidate_scalar_mul(
            d_digits, Affine{x, root}, options.width));
        const Z r1 = affine_x(fixed_mul(state2, q_table)) >> 16;
        if (r1 != known_outputs()[1]) {
            continue;
        }
        const auto completed = finish_candidate(low, x, state2, q_table, options.width);
        if (!completed) {
            continue;
        }
        std::lock_guard<std::mutex> guard(result_mutex);
        if (completed->low_bits < prediction.low_bits) {
            prediction = *completed;
            best_low.store(completed->low_bits, std::memory_order_relaxed);
        }
    }
    if (prediction.low_bits == (1 << 16)) {
        throw std::runtime_error("scalar algorithm candidate did not recover the state");
    }
    return prediction;
}

void self_test_algorithm_candidates(const Z& d) {
    if (affine_x(scalar_mul_wnaf(wnaf(d), point_q())) !=
        affine_x(x_ladder(d, point_q().x))) {
        throw std::runtime_error("x-only fixed-point self-test failed");
    }

    int tested = 0;
    for (int low = 0; low < (1 << 16) && tested < 8; ++low) {
        const Z x = (known_outputs()[0] << 16) | low;
        const Z rhs = modp(x * x * x + curve_a() * x + curve_b());
        Z y;
        if (!sqrt_mod(rhs, y)) {
            continue;
        }
        const Z reference = affine_x(scalar_mul_wnaf(wnaf(d), Affine{x, y}));
        const XPoint projected = x_ladder(d, x);
        if (projected.z == 0 || affine_x(projected) != reference) {
            throw std::runtime_error("x-only random-lift self-test failed");
        }
        ++tested;
    }

    Z x = known_outputs()[0] << 16;
    Z rhs = modp(x * x * x + curve_a() * x + curve_b());
    Z delta1 = modp(3 * x * x + 3 * x + 1 + curve_a());
    Z delta2 = modp(6 * x + 6);
    for (int index = 0; index < 256; ++index) {
        const Z direct = modp(x * x * x + curve_a() * x + curve_b());
        if (rhs != direct) {
            throw std::runtime_error("finite-difference self-test failed");
        }
        x = modp(x + 1);
        rhs = modp(rhs + delta1);
        delta1 = modp(delta1 + delta2);
        delta2 = modp(delta2 + 6);
    }
}

}  // namespace

int main(int argc, char** argv) {
    CandidateOptions options;
    bool json = false;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--mode" && index + 1 < argc) {
            options.mode = argv[++index];
        } else if (argument == "--threads" && index + 1 < argc) {
            options.threads = std::stoi(argv[++index]);
        } else if (argument == "--block-size" && index + 1 < argc) {
            options.block_size = std::stoi(argv[++index]);
        } else if (argument == "--wnaf-width" && index + 1 < argc) {
            options.width = std::stoi(argv[++index]);
        } else if (argument == "--direct-cubic") {
            options.finite_difference = false;
        } else if (argument == "--no-legendre") {
            options.legendre_prefilter = false;
        } else if (argument == "--json") {
            json = true;
        } else {
            std::cerr << "unknown or incomplete argument: " << argument << '\n';
            return 2;
        }
    }
    if (options.mode != "jacobian-scalar" && options.mode != "jacobian-batch" &&
        options.mode != "xonly-batch") {
        std::cerr << "mode must be jacobian-scalar, jacobian-batch, or xonly-batch\n";
        return 2;
    }
    if (options.threads < 1 || options.block_size < 1 || options.width < 2 ||
        options.width > 7) {
        std::cerr << "invalid threads, block size, or wNAF width\n";
        return 2;
    }

    try {
        const Z d = recover_backdoor_scalar_analytic();
        self_test_algorithm_candidates(d);
        const auto started = std::chrono::steady_clock::now();
        const Prediction prediction = options.mode == "jacobian-scalar"
                                          ? recover_state_scalar(d, options)
                                          : recover_state_candidates(d, options);
        const auto finished = std::chrono::steady_clock::now();
        const Z expected_d("0x1c3cdd6b221806db0a7b28");
        const Z expected_state("0x638d9d631ab436da51e640");
        const Z expected_r3("0x2443c8daf1a9d52b09");
        if (d != expected_d || prediction.state_s2 != expected_state ||
            prediction.r3 != expected_r3) {
            throw std::runtime_error("known-answer validation failed");
        }
        const std::chrono::duration<double> elapsed = finished - started;
        if (json) {
            std::cout << "{\"implementation\":\"deep-" << options.mode
                      << "\",\"d\":\"" << hex(d) << "\",\"state\":\""
                      << hex(prediction.state_s2) << "\",\"state_label\":\"s2\","
                      << "\"r3\":\"" << hex(prediction.r3)
                      << "\",\"lift_low_bits\":" << prediction.low_bits
                      << ",\"threads\":" << options.threads
                      << ",\"block_size\":" << options.block_size
                      << ",\"wnaf_width\":" << options.width
                      << ",\"finite_difference\":"
                      << (options.finite_difference ? "true" : "false")
                      << ",\"legendre_prefilter\":"
                      << (options.legendre_prefilter ? "true" : "false")
                      << ",\"state_seconds\":" << std::setprecision(12)
                      << elapsed.count() << "}\n";
        } else {
            std::cout << "mode = " << options.mode << '\n'
                      << "d = " << hex(d) << '\n'
                      << "s2 = " << hex(prediction.state_s2) << '\n'
                      << "r3 = " << hex(prediction.r3) << '\n'
                      << "state recovery = " << elapsed.count() << "s\n";
        }
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
