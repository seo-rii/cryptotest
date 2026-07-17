/*
 * Centered, triangular Herrmann--May lattice solver for challenge #7.
 *
 * Build (Debian FLINT plus locally installed FLATTER):
 *   g++ -O3 -std=c++17 -I/usr/local/include grouped_hm_flatter.cpp \
 *     -L/usr/local/lib -Wl,-rpath,/usr/local/lib \
 *     -lflatter -lflint -lgmpxx -lgmp -lopenblas -pthread \
 *     -o grouped_hm_flatter
 *
 * The defaults run a planted self-check.  Scan one challenge edge candidate:
 *   OPENBLAS_NUM_THREADS=1 ./grouped_hm_flatter \
 *     --challenge --cid 0 --lead x --centered
 */
#include <flatter/computation_context.h>
#include <flatter/data/lattice.h>
#include <flatter/data/matrix.h>
#include <flatter/flatter.h>
#include <flatter/problems/lattice_reduction.h>
#include <gmpxx.h>
#include <flint/nmod_mpoly.h>
#include <flint/nmod_poly.h>
#include <flint/ulong_extras.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using Clock = std::chrono::steady_clock;
using Monomial = std::pair<unsigned int, unsigned int>;
using Polynomial = std::map<Monomial, mpz_class>;

struct ModularRoot {
    bool found = false;
    bool gcd_is_one = false;
    ulong x = 0;
    ulong y = 0;
    unsigned int resultants = 0;
};

static ulong linear_root(const nmod_poly_t polynomial, ulong prime) {
    const ulong constant = nmod_poly_get_coeff_ui(polynomial, 0);
    const ulong linear = nmod_poly_get_coeff_ui(polynomial, 1);
    return (ulong)(((__uint128_t)(constant == 0 ? 0 : prime-constant)
                    * n_invmod(linear, prime)) % prime);
}

static ModularRoot recover_mod_prime(const std::vector<std::vector<mpz_class>> &polynomials,
                                     const std::vector<Monomial> &monomials,
                                     ulong prime) {
    ModularRoot answer;
    nmod_mpoly_ctx_t context;
    nmod_mpoly_ctx_init(context, 2, ORD_LEX, prime);
    std::vector<nmod_mpoly_struct> modular(polynomials.size());
    for(unsigned int row = 0; row < polynomials.size(); row++) {
        nmod_mpoly_init(&modular[row], context);
        for(unsigned int col = 0; col < monomials.size(); col++) {
            const ulong coefficient = mpz_fdiv_ui(polynomials[row][col].get_mpz_t(), prime);
            if(coefficient == 0)
                continue;
            const ulong exponents[2] = {monomials[col].first, monomials[col].second};
            nmod_mpoly_set_coeff_ui_ui(&modular[row], coefficient, exponents, context);
        }
    }

    nmod_mpoly_t resultant;
    nmod_mpoly_init(resultant, context);
    nmod_poly_t univariate, y_gcd, scratch;
    nmod_poly_init(univariate, prime);
    nmod_poly_init(y_gcd, prime);
    nmod_poly_init(scratch, prime);
    bool have_gcd = false;
    for(unsigned int gap = 1; gap < polynomials.size() && !answer.found; gap++) {
        for(unsigned int a = 0; a + gap < polynomials.size() && !answer.found; a++) {
            const unsigned int b = a + gap;
            nmod_mpoly_zero(resultant, context);
            if(!nmod_mpoly_resultant(resultant, &modular[a], &modular[b], 0, context))
                continue;
            answer.resultants++;
            const slong y_degree = nmod_mpoly_degree_si(resultant, 1, context);
            if(y_degree < 0)
                continue;
            nmod_poly_zero(univariate);
            for(slong degree = 0; degree <= y_degree; degree++) {
                const ulong exponents[2] = {0, (ulong)degree};
                const ulong coefficient = nmod_mpoly_get_coeff_ui_ui(resultant, exponents, context);
                if(coefficient)
                    nmod_poly_set_coeff_ui(univariate, degree, coefficient);
            }
            if(nmod_poly_is_zero(univariate))
                continue;
            if(!have_gcd) {
                nmod_poly_set(y_gcd, univariate);
                nmod_poly_make_monic(y_gcd, y_gcd);
                have_gcd = true;
            } else {
                nmod_poly_gcd(scratch, y_gcd, univariate);
                nmod_poly_swap(y_gcd, scratch);
            }
            const slong gcd_degree = nmod_poly_degree(y_gcd);
            if(gcd_degree == 0) {
                answer.gcd_is_one = true;
                break;
            }
            if(gcd_degree != 1)
                continue;
            const ulong y = linear_root(y_gcd, prime);

            // Specialize several independent rows at y and GCD the resulting
            // univariate polynomials in x.
            nmod_poly_t x_gcd, specialized;
            nmod_poly_init(x_gcd, prime);
            nmod_poly_init(specialized, prime);
            bool have_x_gcd = false;
            unsigned int max_x_degree = 0;
            for(const Monomial &monomial : monomials)
                max_x_degree = std::max(max_x_degree, monomial.first);
            for(unsigned int row = 0; row < polynomials.size(); row++) {
                nmod_poly_zero(specialized);
                std::vector<ulong> coefficients(max_x_degree + 1, 0);
                for(unsigned int col = 0; col < monomials.size(); col++) {
                    const ulong c = mpz_fdiv_ui(polynomials[row][col].get_mpz_t(), prime);
                    if(c == 0)
                        continue;
                    const unsigned int xd = monomials[col].first;
                    const unsigned int yd = monomials[col].second;
                    const ulong y_power = n_powmod2_preinv(y, yd, prime, n_preinvert_limb(prime));
                    coefficients[xd] = (coefficients[xd] +
                        (ulong)((__uint128_t)c * y_power % prime)) % prime;
                }
                for(unsigned int degree = 0; degree < coefficients.size(); degree++)
                    if(coefficients[degree])
                        nmod_poly_set_coeff_ui(specialized, degree, coefficients[degree]);
                if(nmod_poly_is_zero(specialized))
                    continue;
                if(!have_x_gcd) {
                    nmod_poly_set(x_gcd, specialized);
                    nmod_poly_make_monic(x_gcd, x_gcd);
                    have_x_gcd = true;
                } else {
                    nmod_poly_gcd(scratch, x_gcd, specialized);
                    nmod_poly_swap(x_gcd, scratch);
                }
            }
            if(have_x_gcd && nmod_poly_degree(x_gcd) == 1) {
                const ulong x = linear_root(x_gcd, prime);
                bool validates = true;
                const ulong preinverse = n_preinvert_limb(prime);
                for(unsigned int row = 0; row < polynomials.size() && validates; row++) {
                    ulong evaluation = 0;
                    for(unsigned int col = 0; col < monomials.size(); col++) {
                        const ulong c = mpz_fdiv_ui(polynomials[row][col].get_mpz_t(), prime);
                        const ulong xp = n_powmod2_preinv(x, monomials[col].first, prime, preinverse);
                        const ulong yp = n_powmod2_preinv(y, monomials[col].second, prime, preinverse);
                        evaluation = (evaluation + (ulong)((__uint128_t)c * xp % prime) * yp) % prime;
                    }
                    validates = evaluation == 0;
                }
                if(validates) {
                    answer.x = x;
                    answer.y = y;
                    answer.found = true;
                }
            }
            nmod_poly_clear(specialized);
            nmod_poly_clear(x_gcd);
        }
        if(answer.gcd_is_one)
            break;
    }

    nmod_poly_clear(scratch);
    nmod_poly_clear(y_gcd);
    nmod_poly_clear(univariate);
    nmod_mpoly_clear(resultant, context);
    for(unsigned int row = 0; row < modular.size(); row++)
        nmod_mpoly_clear(&modular[row], context);
    nmod_mpoly_ctx_clear(context);
    return answer;
}

static Polynomial multiply(const Polynomial &a, const Polynomial &b) {
    Polynomial out;
    for(const auto &left : a) {
        for(const auto &right : b) {
            Monomial monomial(left.first.first + right.first.first,
                              left.first.second + right.first.second);
            out[monomial] += left.second * right.second;
        }
    }
    return out;
}

static mpz_class positive_mod(const mpz_class &value, const mpz_class &modulus) {
    mpz_class out;
    mpz_mod(out.get_mpz_t(), value.get_mpz_t(), modulus.get_mpz_t());
    return out;
}

static mpz_class centered_mod(const mpz_class &value, const mpz_class &modulus) {
    mpz_class out = positive_mod(value, modulus);
    if(2*out > modulus)
        out -= modulus;
    return out;
}

static mpz_class inverse_mod(const mpz_class &value, const mpz_class &modulus) {
    mpz_class out;
    if(mpz_invert(out.get_mpz_t(), value.get_mpz_t(), modulus.get_mpz_t()) == 0)
        throw std::runtime_error("coefficient is not invertible modulo N");
    return out;
}

static unsigned long bit_length(const mpz_class &value) {
    if(value == 0)
        return 0;
    mpz_class absolute = value >= 0 ? value : -value;
    return mpz_sizeinbase(absolute.get_mpz_t(), 2);
}

int main(int argc, char **argv) {
    unsigned int m = 17;
    unsigned int t = 5;
    double rhf = 1.15;
    bool wrong = false;
    bool lead_y = true;
    bool modular_selftest = false;
    bool centered = false;
    bool build_only = false;
    bool challenge = false;
    unsigned int candidate_id = 0;
    unsigned int trim_x = 0;
    unsigned int trim_y = 0;
    for(int i = 1; i < argc; i++) {
        const std::string arg(argv[i]);
        if(arg == "--wrong")
            wrong = true;
        else if(arg == "--modular-selftest")
            modular_selftest = true;
        else if(arg == "--centered")
            centered = true;
        else if(arg == "--build-only")
            build_only = true;
        else if(arg == "--challenge")
            challenge = true;
        else if(arg == "--cid" && i + 1 < argc)
            candidate_id = std::stoul(argv[++i]);
        else if(arg == "--m" && i + 1 < argc)
            m = std::stoul(argv[++i]);
        else if(arg == "--t" && i + 1 < argc)
            t = std::stoul(argv[++i]);
        else if(arg == "--rhf" && i + 1 < argc)
            rhf = std::stod(argv[++i]);
        else if(arg == "--trim-x" && i + 1 < argc)
            trim_x = std::stoul(argv[++i]);
        else if(arg == "--trim-y" && i + 1 < argc)
            trim_y = std::stoul(argv[++i]);
        else if(arg == "--lead" && i + 1 < argc) {
            const std::string lead(argv[++i]);
            if(lead == "x")
                lead_y = false;
            else if(lead == "y")
                lead_y = true;
            else
                throw std::runtime_error("--lead must be x or y");
        }
        else
            throw std::runtime_error("usage: grouped_hm_bench [--wrong] [--centered] [--build-only] [--challenge --cid ID] [--m M] [--t T] [--rhf R] [--lead x|y] [--trim-x BITS] [--trim-y BITS]");
    }

    if(modular_selftest) {
        const ulong prime = 1000000007UL;
        const std::vector<Monomial> test_monomials = {{0, 0}, {0, 1}, {1, 0}};
        std::vector<std::vector<mpz_class>> test_polynomials(
            3, std::vector<mpz_class>(test_monomials.size()));
        // All three independent lines meet at (x,y)=(123,456).
        test_polynomials[0] = {-1035, 2, 1};
        test_polynomials[1] = {87, -1, 3};
        test_polynomials[2] = {-58389, 1, 471};
        const ModularRoot root = recover_mod_prime(test_polynomials, test_monomials, prime);
        std::cout << "modular_selftest found=" << root.found << " x=" << root.x
                  << " y=" << root.y << " resultants=" << root.resultants << std::endl;
        return root.found && root.x == 123 && root.y == 456 ? 0 : 3;
    }

    mpz_class p(
        "139773431854021281271736705032839551372385378223078249488714387022053707762160184030000820110759251464638835908443654590590873412700295972838370976285356834995663180121250283923714728535481058462696468878908705276979936759999142735461662795490663950093112660772557497713563069383210926104062195936697533305679");
    mpz_class q(
        "143449853748163455492455987098088022908256984692660781771219349799964765272709320661469143316537312565587752348414776682359567958116152141772423798009272397057560392423578565822003672975144830742207718548586963825774616832377676796913678891689207164199807190848727945996885781205079038941735247845734249163973");
    mpz_class N = p * q;
    if(trim_x >= 155 || trim_y >= 230)
        throw std::runtime_error("trim width must leave a nonempty variable");
    const mpz_class X_full = mpz_class(1) << 155;
    const mpz_class Y_full = mpz_class(1) << 230;
    const mpz_class X = mpz_class(1) << (155-trim_x);
    const mpz_class Y = mpz_class(1) << (230-trim_y);
    const mpz_class A = mpz_class(1) << 265;
    const mpz_class B = mpz_class(1) << 600;
    const mpz_class x_mask = (X_full - 1) << 265;
    const mpz_class y_mask = (Y_full - 1) << 600;
    mpz_class x_full = (p >> 265) & (X_full - 1);
    mpz_class y_full = (p >> 600) & (Y_full - 1);
    mpz_class x_root = x_full & (X - 1);
    mpz_class y_root = y_full & (Y - 1);
    mpz_class C = (p & ~x_mask & ~y_mask)
                + A*(x_full-x_root) + B*(y_full-y_root);
    if(challenge) {
        if(candidate_id > 255 || trim_x != 0 || trim_y != 0)
            throw std::runtime_error("challenge mode requires cid 0..255 and no trim");
        N = mpz_class(
            "28911038028892288721461082510998394891328607709148468885236292554551485183612270427880961938955096882048786900444864896262986081272043396364921296918043343303721687797074642131810738332704884636727137913915770831133412587091299820673650778261348284710843037439953619158022512686479498963762697526533691935071897067788267949777152902269087589409776381146497580293399500483422743493677161514281068159877530687857451278067397222959237884082709363721539425894048212697121029989969843192628614747960340415955905048506894700002043189150318317345739309101911544938232694237137666254934197281205812437685866456940481012087537");
        C = mpz_class(
            "179515246255815592049382700812392123641046166021131275990343968955793538238883059072225409166502121645306115720946460687914076491557498898105911859815287417041053926720698237166238811094699134172925259015096436440834561723538767868383437380305866712832346780365821696023513887543155182468247839238102689616841");
        C += mpz_class(candidate_id & 15U) << 150;
        C += mpz_class(candidate_id >> 4U) << 920;
        p = q = x_full = y_full = x_root = y_root = 0;
    }
    if(wrong)
        C ^= mpz_class(1) << 150;

    // Normalize C + A*x + B*y to a polynomial monic in the selected variable.
    const mpz_class inverse = inverse_mod(lead_y ? B : A, N);
    Polynomial f;
    f[lead_y ? Monomial{0, 1} : Monomial{1, 0}] = 1;
    f[lead_y ? Monomial{1, 0} : Monomial{0, 1}] = positive_mod((lead_y ? A : B) * inverse, N);
    f[{0, 0}] = positive_mod(C * inverse, N);

    const auto basis_start = Clock::now();
    std::vector<mpz_class> n_powers(t + 1);
    n_powers[0] = 1;
    for(unsigned int i = 1; i <= t; i++)
        n_powers[i] = n_powers[i-1] * N;
    std::vector<Polynomial> powers(m + 1);
    powers[0][{0, 0}] = 1;
    for(unsigned int k = 1; k <= m; k++) {
        powers[k] = multiply(powers[k-1], f);
        // Once k reaches t, retaining coefficients only modulo N^t is stable
        // under every later multiplication.  For k<t the exact power must be
        // retained for the next recursion, although its lattice copy below is
        // centered modulo N^k.
        if(centered && k >= t) {
            for(auto &term : powers[k])
                term.second = centered_mod(term.second, n_powers[t]);
        }
    }

    std::vector<Polynomial> shifts;
    // Order rows by their leading monomial.  For the x-monic orientation the
    // leading term is x^k*y^shift (and symmetrically for y-monic), so iterating
    // total degree first makes the row-basis lower triangular in the monomial
    // order below.  The explicit transpose into libflatter is therefore upper
    // triangular and can use its dedicated fast path.
    for(unsigned int degree = 0; degree <= m; degree++) {
      for(unsigned int k = 0; k <= degree; k++) {
        const unsigned int shift = degree-k;
        const mpz_class multiplier = k < t ? n_powers[t-k] : mpz_class(1);
        Polynomial polynomial;
        for(const auto &term : powers[k]) {
            const Monomial monomial = lead_y
                ? Monomial{term.first.first + shift, term.first.second}
                : Monomial{term.first.first, term.first.second + shift};
            mpz_class coefficient = term.second;
            if(centered && k > 0)
                coefficient = centered_mod(coefficient, n_powers[std::min(k, t)]);
            polynomial[monomial] = coefficient * multiplier;
        }
        shifts.push_back(std::move(polynomial));
      }
    }

    std::vector<Monomial> monomials;
    for(unsigned int degree = 0; degree <= m; degree++)
        for(unsigned int x_degree = 0; x_degree <= degree; x_degree++)
            monomials.emplace_back(x_degree, degree-x_degree);
    const unsigned int dimension = (m+1)*(m+2)/2;
    if(shifts.size() != dimension || monomials.size() != dimension)
        throw std::runtime_error("unexpected nonsquare HM basis");
    std::map<Monomial, unsigned int> column;
    for(unsigned int i = 0; i < dimension; i++)
        column[monomials[i]] = i;

    std::vector<mpz_class> x_powers(m + 1), y_powers(m + 1), scales(dimension);
    x_powers[0] = y_powers[0] = 1;
    for(unsigned int i = 1; i <= m; i++) {
        x_powers[i] = x_powers[i-1] * X;
        y_powers[i] = y_powers[i-1] * Y;
    }
    for(unsigned int i = 0; i < dimension; i++)
        scales[i] = x_powers[monomials[i].first] * y_powers[monomials[i].second];

    std::cout << "mode=" << (challenge ? "challenge" : (wrong ? "wrong" : "correct"))
              << " cid=" << candidate_id
              << " m=" << m << " t=" << t << " dim=" << dimension
              << " rhf=" << rhf << " lead=" << (lead_y ? "y" : "x")
              << " centered=" << centered
              << " trim_x=" << trim_x << " trim_y=" << trim_y
              << " xbits=" << bit_length(x_root)
              << " ybits=" << bit_length(y_root) << std::endl;
    const auto matrix_start = Clock::now();
    flatter::initialize();
    flatter::Matrix basis(flatter::MPZ, dimension, dimension);
    flatter::Matrix transform(flatter::MPZ, dimension, dimension);
    transform.set_identity();
    flatter::MatrixData<mpz_t> data = basis.data<mpz_t>();
    unsigned long basis_max_bits = 0;
    for(unsigned int row = 0; row < dimension; row++) {
        for(const auto &term : shifts[row]) {
            const unsigned int col = column.at(term.first);
            const mpz_class coefficient = term.second * scales[col];
            basis_max_bits = std::max(basis_max_bits, bit_length(coefficient));
            mpz_set(data(col, row), coefficient.get_mpz_t());
        }
    }
    std::cout << "matrix_seconds="
              << std::chrono::duration<double>(Clock::now()-matrix_start).count()
              << " basis_seconds="
              << std::chrono::duration<double>(Clock::now()-basis_start).count()
              << " basis_max_bits=" << basis_max_bits << std::endl;
    if(build_only) {
        flatter::finalize();
        return 0;
    }

    flatter::Lattice lattice(basis);
    flatter::LatticeReductionParams params(lattice, transform, rhf, true);
    flatter::ComputationContext context(4);
    flatter::LatticeReduction reduction(params, context);
    const auto reduction_start = Clock::now();
    reduction.solve();
    const double reduction_seconds =
        std::chrono::duration<double>(Clock::now()-reduction_start).count();
    std::cout << "reduction_seconds=" << reduction_seconds << std::endl;

    flatter::MatrixData<mpz_t> reduced = lattice.basis().data<mpz_t>();
    std::vector<mpz_class> planted_x_powers(m + 1), planted_y_powers(m + 1);
    planted_x_powers[0] = planted_y_powers[0] = 1;
    for(unsigned int i = 1; i <= m; i++) {
        planted_x_powers[i] = planted_x_powers[i-1] * x_root;
        planted_y_powers[i] = planted_y_powers[i-1] * y_root;
    }
    unsigned int zero_rows = 0;
    unsigned int integral_rows = 0;
    std::vector<unsigned long> first_l1_bits;
    std::vector<std::pair<unsigned long, unsigned int>> row_order;
    for(unsigned int row = 0; row < dimension; row++) {
        bool integral = true;
        mpz_class evaluation = 0;
        mpz_class l1 = 0;
        for(unsigned int col = 0; col < dimension; col++) {
            mpz_class scaled_coefficient;
            mpz_set(scaled_coefficient.get_mpz_t(), reduced(col, row));
            l1 += scaled_coefficient >= 0 ? scaled_coefficient : -scaled_coefficient;
            if(!mpz_divisible_p(scaled_coefficient.get_mpz_t(), scales[col].get_mpz_t())) {
                integral = false;
                break;
            }
            const mpz_class coefficient = scaled_coefficient / scales[col];
            evaluation += coefficient * planted_x_powers[monomials[col].first]
                                      * planted_y_powers[monomials[col].second];
        }
        if(row < 12)
            first_l1_bits.push_back(bit_length(l1));
        row_order.emplace_back(bit_length(l1), row);
        if(integral) {
            integral_rows++;
            if(!challenge && evaluation == 0)
                zero_rows++;
        }
    }
    std::cout << "integral_rows=" << integral_rows << " planted_zero_rows=" << zero_rows
              << " first_l1_bits=";
    for(unsigned int i = 0; i < first_l1_bits.size(); i++)
        std::cout << (i ? "," : "") << first_l1_bits[i];
    std::cout << std::endl;

    std::sort(row_order.begin(), row_order.end());
    const unsigned int selected_count = std::min<unsigned int>(12, dimension);
    std::vector<std::vector<mpz_class>> selected(
        selected_count, std::vector<mpz_class>(dimension));
    for(unsigned int selected_row = 0; selected_row < selected_count; selected_row++) {
        const unsigned int row = row_order[selected_row].second;
        for(unsigned int col = 0; col < dimension; col++) {
            mpz_class scaled_coefficient;
            mpz_set(scaled_coefficient.get_mpz_t(), reduced(col, row));
            if(!mpz_divisible_p(scaled_coefficient.get_mpz_t(), scales[col].get_mpz_t()))
                throw std::runtime_error("reduced coefficient lost its monomial scale");
            selected[selected_row][col] = scaled_coefficient / scales[col];
        }
    }

    mpz_class crt_x = 0, crt_y = 0, crt_modulus = 1;
    bool recovered = false;
    ulong prime = 1000000000UL;
    for(unsigned int round = 0; round < 10 && !recovered; round++) {
        prime = n_nextprime(prime, 1);
        const auto modular_start = Clock::now();
        const ModularRoot root = recover_mod_prime(selected, monomials, prime);
        const double modular_seconds =
            std::chrono::duration<double>(Clock::now()-modular_start).count();
        std::cout << "prime=" << prime << " resultant_count=" << root.resultants
                  << " gcd_one=" << root.gcd_is_one << " root=" << root.found
                  << " modular_seconds=" << modular_seconds << std::endl;
        if(!root.found)
            break;

        const ulong current_x = mpz_fdiv_ui(crt_x.get_mpz_t(), prime);
        const ulong current_y = mpz_fdiv_ui(crt_y.get_mpz_t(), prime);
        const ulong modulus_mod_prime = mpz_fdiv_ui(crt_modulus.get_mpz_t(), prime);
        const ulong inverse_modulus = n_invmod(modulus_mod_prime, prime);
        const ulong delta_x = (ulong)((__uint128_t)((root.x + prime-current_x) % prime)
                                     * inverse_modulus % prime);
        const ulong delta_y = (ulong)((__uint128_t)((root.y + prime-current_y) % prime)
                                     * inverse_modulus % prime);
        crt_x += crt_modulus * delta_x;
        crt_y += crt_modulus * delta_y;
        crt_modulus *= prime;
        std::cout << "crt_bits=" << bit_length(crt_modulus) << std::endl;
        if(crt_modulus > Y && crt_x < X && crt_y < Y) {
            const mpz_class candidate = C + A*crt_x + B*crt_y;
            recovered = candidate > 1 && N % candidate == 0;
            if(recovered)
                std::cout << "RECOVERED p=" << candidate << std::endl;
        }
    }
    flatter::finalize();
    const bool expected = challenge ? recovered
                        : wrong ? (!recovered && zero_rows == 0)
                                : (recovered && zero_rows >= 2);
    return expected ? 0 : 2;
}
