#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__AVX2__)
#include <immintrin.h>
#endif

typedef struct {
    uint64_t w[4];
} state256_t;

static const unsigned int ROTATIONS[4] = {43U, 7U, 29U, 14U};
static const uint8_t REVERSE_BYTES[32] = {
    31, 30, 29, 28, 27, 26, 25, 24,
    23, 22, 21, 20, 19, 18, 17, 16,
    15, 14, 13, 12, 11, 10, 9, 8,
    7, 6, 5, 4, 3, 2, 1, 0,
};
static const uint64_t CONSTANTS1[4] = {
    UINT64_C(0x8f4a2c1e9b7d3f61),
    UINT64_C(0x3c6e9a1d5b7f2840),
    UINT64_C(0xa7e2d9c4b1f60853),
    UINT64_C(0x5d0f3a8e2c6b4197),
};
static const uint64_t CONSTANTS2[4] = {
    UINT64_C(0xe7b92d4a6c1f8035),
    UINT64_C(0x1a4f8c3e9d2b6074),
    UINT64_C(0xc3f05a2e8d6194b7),
    UINT64_C(0x6b2e9d1a4f7c3085),
};

#if defined(__GNUC__) && !defined(__clang__)
#define NOINLINE_NOCLONE __attribute__((noinline, noclone))
#define NO_VECTORIZE __attribute__((optimize("no-tree-vectorize")))
#if defined(__x86_64__) || defined(__i386__)
#define TARGET_BMI2 __attribute__((target("bmi2")))
#else
#define TARGET_BMI2
#endif
#elif defined(__GNUC__) || defined(__clang__)
#define NOINLINE_NOCLONE __attribute__((noinline))
#define NO_VECTORIZE
#if defined(__x86_64__) || defined(__i386__)
#define TARGET_BMI2 __attribute__((target("bmi2")))
#else
#define TARGET_BMI2
#endif
#else
#define NOINLINE_NOCLONE
#define NO_VECTORIZE
#define TARGET_BMI2
#endif

static inline uint64_t rotl64(uint64_t value, unsigned int amount) {
    return (value << amount) | (value >> (64U - amount));
}

static inline uint64_t bswap64(uint64_t value) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_bswap64(value);
#else
    value = ((value & UINT64_C(0x00ff00ff00ff00ff)) << 8) |
            ((value >> 8) & UINT64_C(0x00ff00ff00ff00ff));
    value = ((value & UINT64_C(0x0000ffff0000ffff)) << 16) |
            ((value >> 16) & UINT64_C(0x0000ffff0000ffff));
    return (value << 32) | (value >> 32);
#endif
}

static inline uint64_t transform_word(uint64_t value,
                                      unsigned int rotation,
                                      uint64_t xor_constant,
                                      uint64_t add_constant) {
    return bswap64(rotl64(value, rotation) ^ xor_constant) + add_constant;
}

/* Generic byte-oriented oracle, intentionally kept separate from candidates. */
static void reference_one_round(state256_t *state) {
    uint8_t input[32];
    uint8_t output[32];
    size_t index;

    for (index = 0U; index < 4U; ++index) {
        state->w[index] = rotl64(state->w[index], ROTATIONS[index]);
        state->w[index] ^= CONSTANTS2[index];
    }
    memcpy(input, state, sizeof(input));
    for (index = 0U; index < 32U; ++index) {
        output[index] = input[REVERSE_BYTES[index]];
    }
    memcpy(state, output, sizeof(output));
    for (index = 0U; index < 4U; ++index) {
        state->w[index] += CONSTANTS1[index];
    }
}

static void reference_20_rounds(state256_t *state) {
    unsigned int round;
    for (round = 0U; round < 20U; ++round) {
        reference_one_round(state);
    }
}

/*
 * Candidate 1: model the current submission.  Calling a state-writing helper
 * from the 20-round loop forces conservative alias handling for c1/c2 and is
 * the behavior visible in the current GCC-generated contest.c assembly.
 */
static inline void current_one_round(state256_t *state,
                                     const uint64_t c1[4],
                                     const uint64_t c2[4]) {
    const uint64_t x0 = state->w[0];
    const uint64_t x1 = state->w[1];
    const uint64_t x2 = state->w[2];
    const uint64_t x3 = state->w[3];
    state->w[0] = transform_word(x3, 14U, c2[3], c1[0]);
    state->w[1] = transform_word(x2, 29U, c2[2], c1[1]);
    state->w[2] = transform_word(x1, 7U, c2[1], c1[2]);
    state->w[3] = transform_word(x0, 43U, c2[0], c1[3]);
}

NOINLINE_NOCLONE static void candidate_current(state256_t *state,
                                                const uint64_t c1[4],
                                                const uint64_t c2[4]) {
    unsigned int round;
    for (round = 0U; round < 20U; ++round) {
        current_one_round(state, c1, c2);
    }
}

/* Candidate 2: one-round loop, but keep state and constants in registers. */
NOINLINE_NOCLONE static void candidate_register_loop(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];
    unsigned int round;

    for (round = 0U; round < 20U; ++round) {
        const uint64_t y0 = transform_word(x3, 14U, k3, a0);
        const uint64_t y1 = transform_word(x2, 29U, k2, a1);
        const uint64_t y2 = transform_word(x1, 7U, k1, a2);
        const uint64_t y3 = transform_word(x0, 43U, k0, a3);
        x0 = y0;
        x1 = y1;
        x2 = y2;
        x3 = y3;
    }
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

/*
 * After two rounds the word reversal cancels.  The four words become four
 * independent chains, exposing instruction-level parallelism without moves.
 */
#define APPLY_TWO_ROUNDS()                                                     \
    do {                                                                       \
        x0 = transform_word(transform_word(x0, 43U, k0, a3), 14U, k3, a0);    \
        x1 = transform_word(transform_word(x1, 7U, k1, a2), 29U, k2, a1);     \
        x2 = transform_word(transform_word(x2, 29U, k2, a1), 7U, k1, a2);     \
        x3 = transform_word(transform_word(x3, 14U, k3, a0), 43U, k0, a3);    \
    } while (0)

NOINLINE_NOCLONE static void candidate_paired_loop(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];
    unsigned int pair;

    for (pair = 0U; pair < 10U; ++pair) {
        APPLY_TWO_ROUNDS();
    }
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

/* Same two-round recurrence, with GCC's automatic SLP/vectorization disabled. */
NOINLINE_NOCLONE NO_VECTORIZE static void candidate_paired_loop_scalar(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];
    unsigned int pair;

    for (pair = 0U; pair < 10U; ++pair) {
        APPLY_TWO_ROUNDS();
    }
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

/* Candidate 4: remove the remaining ten-iteration branch explicitly. */
NOINLINE_NOCLONE static void candidate_paired_unrolled(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];

    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}


/* Explicit 20-round scalar unroll, useful when vector latency is unfavorable. */
NOINLINE_NOCLONE NO_VECTORIZE static void candidate_paired_unrolled_scalar(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];

    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

/*
 * Same scalar unroll, but request only BMI2 locally.  This lets GCC select
 * non-destructive RORX even when the supplied run script has no -march flag.
 */
NOINLINE_NOCLONE NO_VECTORIZE TARGET_BMI2 static void
candidate_paired_unrolled_bmi2(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = c1[0], a1 = c1[1], a2 = c1[2], a3 = c1[3];
    const uint64_t k0 = c2[0], k1 = c2[1], k2 = c2[2], k3 = c2[3];

    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    APPLY_TWO_ROUNDS();
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

#undef APPLY_TWO_ROUNDS

#if defined(__AVX2__)
/* Candidate 5: a single 256-bit state in one AVX2 register. */
NOINLINE_NOCLONE static void candidate_avx2_single(
    state256_t *restrict state,
    const uint64_t c1[restrict 4],
    const uint64_t c2[restrict 4]) {
    const __m256i left = _mm256_setr_epi64x(43, 7, 29, 14);
    const __m256i right = _mm256_setr_epi64x(21, 57, 35, 50);
    const __m256i reverse_each_128 = _mm256_setr_epi8(
        15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
        15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0);
    const __m256i add = _mm256_loadu_si256((const __m256i *)(const void *)c1);
    const __m256i xors = _mm256_loadu_si256((const __m256i *)(const void *)c2);
    __m256i value = _mm256_loadu_si256((const __m256i *)(const void *)state);
    unsigned int round;

    for (round = 0U; round < 20U; ++round) {
        const __m256i lo = _mm256_sllv_epi64(value, left);
        const __m256i hi = _mm256_srlv_epi64(value, right);
        value = _mm256_or_si256(lo, hi);
        value = _mm256_xor_si256(value, xors);
        value = _mm256_shuffle_epi8(value, reverse_each_128);
        value = _mm256_permute2x128_si256(value, value, 0x01);
        value = _mm256_add_epi64(value, add);
    }
    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

/*
 * Four independent states, transposed so every AVX2 lane is one state.  This
 * measures throughput potential, but cannot replace the contest's one-state
 * permute_20rounds API without changing the forbidden timing harness.
 */
NOINLINE_NOCLONE static void candidate_avx2_batch4(state256_t states[4]) {
    const __m256i byte_swap = _mm256_setr_epi8(
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8);
    const __m256i a0 = _mm256_set1_epi64x((long long)CONSTANTS1[0]);
    const __m256i a1 = _mm256_set1_epi64x((long long)CONSTANTS1[1]);
    const __m256i a2 = _mm256_set1_epi64x((long long)CONSTANTS1[2]);
    const __m256i a3 = _mm256_set1_epi64x((long long)CONSTANTS1[3]);
    const __m256i k0 = _mm256_set1_epi64x((long long)CONSTANTS2[0]);
    const __m256i k1 = _mm256_set1_epi64x((long long)CONSTANTS2[1]);
    const __m256i k2 = _mm256_set1_epi64x((long long)CONSTANTS2[2]);
    const __m256i k3 = _mm256_set1_epi64x((long long)CONSTANTS2[3]);
    __m256i x0 = _mm256_setr_epi64x((long long)states[0].w[0],
                                    (long long)states[1].w[0],
                                    (long long)states[2].w[0],
                                    (long long)states[3].w[0]);
    __m256i x1 = _mm256_setr_epi64x((long long)states[0].w[1],
                                    (long long)states[1].w[1],
                                    (long long)states[2].w[1],
                                    (long long)states[3].w[1]);
    __m256i x2 = _mm256_setr_epi64x((long long)states[0].w[2],
                                    (long long)states[1].w[2],
                                    (long long)states[2].w[2],
                                    (long long)states[3].w[2]);
    __m256i x3 = _mm256_setr_epi64x((long long)states[0].w[3],
                                    (long long)states[1].w[3],
                                    (long long)states[2].w[3],
                                    (long long)states[3].w[3]);
    uint64_t out[4][4];
    unsigned int round;

#define ROTATE_VECTOR(v, left_count, right_count)                              \
    _mm256_or_si256(_mm256_slli_epi64((v), (left_count)),                     \
                    _mm256_srli_epi64((v), (right_count)))
#define BSWAP_VECTOR(v) _mm256_shuffle_epi8((v), byte_swap)
    for (round = 0U; round < 20U; ++round) {
        const __m256i y0 = _mm256_add_epi64(
            BSWAP_VECTOR(_mm256_xor_si256(ROTATE_VECTOR(x3, 14, 50), k3)), a0);
        const __m256i y1 = _mm256_add_epi64(
            BSWAP_VECTOR(_mm256_xor_si256(ROTATE_VECTOR(x2, 29, 35), k2)), a1);
        const __m256i y2 = _mm256_add_epi64(
            BSWAP_VECTOR(_mm256_xor_si256(ROTATE_VECTOR(x1, 7, 57), k1)), a2);
        const __m256i y3 = _mm256_add_epi64(
            BSWAP_VECTOR(_mm256_xor_si256(ROTATE_VECTOR(x0, 43, 21), k0)), a3);
        x0 = y0;
        x1 = y1;
        x2 = y2;
        x3 = y3;
    }
#undef BSWAP_VECTOR
#undef ROTATE_VECTOR
    _mm256_storeu_si256((__m256i *)(void *)out[0], x0);
    _mm256_storeu_si256((__m256i *)(void *)out[1], x1);
    _mm256_storeu_si256((__m256i *)(void *)out[2], x2);
    _mm256_storeu_si256((__m256i *)(void *)out[3], x3);
    for (unsigned int state_index = 0U; state_index < 4U; ++state_index) {
        for (unsigned int word = 0U; word < 4U; ++word) {
            states[state_index].w[word] = out[word][state_index];
        }
    }
}
#endif

typedef void (*candidate_function)(state256_t *, const uint64_t[4],
                                   const uint64_t[4]);
typedef double (*measure_function)(uint64_t, uint64_t);

typedef struct {
    const char *name;
    candidate_function function;
    measure_function measure;
} candidate_t;

static volatile uint64_t benchmark_sink;

static double monotonic_seconds(void) {
    struct timespec timestamp;
#if defined(CLOCK_MONOTONIC_RAW)
    const clockid_t clock_id = CLOCK_MONOTONIC_RAW;
#else
    const clockid_t clock_id = CLOCK_MONOTONIC;
#endif
    if (clock_gettime(clock_id, &timestamp) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (double)timestamp.tv_sec + (double)timestamp.tv_nsec * 1.0e-9;
}

static state256_t initial_state(uint64_t salt) {
    const state256_t state = {{
        UINT64_C(0x0123456789abcdef) ^ salt,
        UINT64_C(0xfedcba9876543210) + salt,
        UINT64_C(0x0f1e2d3c4b5a6978) ^ (salt << 1),
        UINT64_C(0x8877665544332211) - salt,
    }};
    return state;
}

#define DEFINE_MEASURE(label, function_name)                                  \
    static double measure_##label(uint64_t iterations, uint64_t salt) {       \
        state256_t state = initial_state(salt);                               \
        uint64_t index;                                                       \
        const double start = monotonic_seconds();                             \
        for (index = 0U; index < iterations; ++index) {                       \
            function_name(&state, CONSTANTS1, CONSTANTS2);                    \
        }                                                                     \
        const double elapsed = monotonic_seconds() - start;                   \
        benchmark_sink ^= state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3]; \
        return elapsed;                                                       \
    }

#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 0
DEFINE_MEASURE(current, candidate_current)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 1
DEFINE_MEASURE(register_loop, candidate_register_loop)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 2
DEFINE_MEASURE(paired_loop, candidate_paired_loop)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 3
DEFINE_MEASURE(paired_loop_scalar, candidate_paired_loop_scalar)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 4
DEFINE_MEASURE(paired_unrolled, candidate_paired_unrolled)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 5
DEFINE_MEASURE(paired_unrolled_scalar, candidate_paired_unrolled_scalar)
#endif
#if !defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 6
DEFINE_MEASURE(paired_unrolled_bmi2, candidate_paired_unrolled_bmi2)
#endif
#if defined(__AVX2__) && \
    (!defined(SELECT_CANDIDATE) || SELECT_CANDIDATE == 7)
DEFINE_MEASURE(avx2_single, candidate_avx2_single)
#endif

#undef DEFINE_MEASURE

#if !defined(SELECT_CANDIDATE)
static const candidate_t CANDIDATES[] = {
    {"current_submission", candidate_current, measure_current},
    {"register_loop", candidate_register_loop, measure_register_loop},
    {"paired_loop", candidate_paired_loop, measure_paired_loop},
    {"paired_loop_scalar", candidate_paired_loop_scalar, measure_paired_loop_scalar},
    {"paired_unrolled", candidate_paired_unrolled, measure_paired_unrolled},
    {"paired_unrolled_scalar", candidate_paired_unrolled_scalar,
     measure_paired_unrolled_scalar},
    {"paired_unrolled_bmi2", candidate_paired_unrolled_bmi2,
     measure_paired_unrolled_bmi2},
#if defined(__AVX2__)
    {"avx2_single", candidate_avx2_single, measure_avx2_single},
#endif
};
#elif SELECT_CANDIDATE == 0
static const candidate_t CANDIDATES[] = {
    {"current_submission", candidate_current, measure_current},
};
#elif SELECT_CANDIDATE == 1
static const candidate_t CANDIDATES[] = {
    {"register_loop", candidate_register_loop, measure_register_loop},
};
#elif SELECT_CANDIDATE == 2
static const candidate_t CANDIDATES[] = {
    {"paired_loop", candidate_paired_loop, measure_paired_loop},
};
#elif SELECT_CANDIDATE == 3
static const candidate_t CANDIDATES[] = {
    {"paired_loop_scalar", candidate_paired_loop_scalar,
     measure_paired_loop_scalar},
};
#elif SELECT_CANDIDATE == 4
static const candidate_t CANDIDATES[] = {
    {"paired_unrolled", candidate_paired_unrolled, measure_paired_unrolled},
};
#elif SELECT_CANDIDATE == 5
static const candidate_t CANDIDATES[] = {
    {"paired_unrolled_scalar", candidate_paired_unrolled_scalar,
     measure_paired_unrolled_scalar},
};
#elif SELECT_CANDIDATE == 6
static const candidate_t CANDIDATES[] = {
    {"paired_unrolled_bmi2", candidate_paired_unrolled_bmi2,
     measure_paired_unrolled_bmi2},
};
#elif SELECT_CANDIDATE == 7 && defined(__AVX2__)
static const candidate_t CANDIDATES[] = {
    {"avx2_single", candidate_avx2_single, measure_avx2_single},
};
#else
#error "SELECT_CANDIDATE is invalid or requires AVX2"
#endif

static int states_equal(const state256_t *left, const state256_t *right) {
    return memcmp(left, right, sizeof(*left)) == 0;
}

static uint64_t xorshift64(uint64_t *state) {
    uint64_t value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    return value;
}

static int read_state(FILE *stream, state256_t *state) {
    return fscanf(stream,
                  "%" SCNx64 " %" SCNx64 " %" SCNx64 " %" SCNx64,
                  &state->w[0], &state->w[1], &state->w[2], &state->w[3]) == 4;
}

static int verify_one_round_vectors(const char *path, size_t *checked) {
    FILE *stream = fopen(path, "r");
    unsigned int number;
    char label[16];

    if (stream == NULL) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        return 0;
    }
    *checked = 0U;
    while (fscanf(stream, " #%u", &number) == 1) {
        state256_t input;
        state256_t expected;
        if (fscanf(stream, "%15s", label) != 1 || strcmp(label, "input") != 0 ||
            !read_state(stream, &input) || fscanf(stream, "%15s", label) != 1 ||
            strcmp(label, "output") != 0 || !read_state(stream, &expected)) {
            fprintf(stderr, "malformed vector near #%u\n", number);
            fclose(stream);
            return 0;
        }
        reference_one_round(&input);
        if (!states_equal(&input, &expected)) {
            fprintf(stderr, "one-round mismatch at vector #%u\n", number);
            fclose(stream);
            return 0;
        }
        ++*checked;
    }
    fclose(stream);
    return *checked != 0U;
}

static int verify_twenty_round_vector(const char *path) {
    FILE *stream = fopen(path, "r");
    state256_t input;
    state256_t expected;
    char label[16];
    size_t candidate_index;
    int parsed;

    if (stream == NULL) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        return 0;
    }
    parsed = fscanf(stream, "%15s", label) == 1 && strcmp(label, "input") == 0 &&
             read_state(stream, &input) && fscanf(stream, "%15s", label) == 1 &&
             strcmp(label, "output") == 0 && read_state(stream, &expected);
    fclose(stream);
    if (!parsed) {
        fprintf(stderr, "malformed 20-round vector\n");
        return 0;
    }
    for (candidate_index = 0U;
         candidate_index < sizeof(CANDIDATES) / sizeof(CANDIDATES[0]);
         ++candidate_index) {
        state256_t result = input;
        CANDIDATES[candidate_index].function(&result, CONSTANTS1, CONSTANTS2);
        if (!states_equal(&result, &expected)) {
            fprintf(stderr, "%s failed 20-round vector\n",
                    CANDIDATES[candidate_index].name);
            return 0;
        }
    }
    return 1;
}

static int differential_test(size_t cases) {
    uint64_t seed = UINT64_C(0x6a09e667f3bcc909);
    size_t case_index;

    for (case_index = 0U; case_index < cases; ++case_index) {
        state256_t input;
        state256_t expected;
        size_t candidate_index;
        for (unsigned int word = 0U; word < 4U; ++word) {
            input.w[word] = xorshift64(&seed);
        }
        expected = input;
        reference_20_rounds(&expected);
        for (candidate_index = 0U;
             candidate_index < sizeof(CANDIDATES) / sizeof(CANDIDATES[0]);
             ++candidate_index) {
            state256_t result = input;
            CANDIDATES[candidate_index].function(&result, CONSTANTS1, CONSTANTS2);
            if (!states_equal(&result, &expected)) {
                fprintf(stderr, "%s random mismatch at case %zu\n",
                        CANDIDATES[candidate_index].name, case_index);
                return 0;
            }
        }
#if defined(__AVX2__) && !defined(SELECT_CANDIDATE)
        if ((case_index & 3U) == 0U && case_index + 3U < cases) {
            state256_t batch[4];
            state256_t batch_expected[4];
            for (unsigned int item = 0U; item < 4U; ++item) {
                for (unsigned int word = 0U; word < 4U; ++word) {
                    batch[item].w[word] = xorshift64(&seed);
                }
                batch_expected[item] = batch[item];
                reference_20_rounds(&batch_expected[item]);
            }
            candidate_avx2_batch4(batch);
            for (unsigned int item = 0U; item < 4U; ++item) {
                if (!states_equal(&batch[item], &batch_expected[item])) {
                    fprintf(stderr, "avx2_batch4 mismatch at case %zu item %u\n",
                            case_index, item);
                    return 0;
                }
            }
        }
#endif
    }
    return 1;
}

static int compare_double(const void *left, const void *right) {
    const double a = *(const double *)left;
    const double b = *(const double *)right;
    return (a > b) - (a < b);
}

static double median_copy(const double *values, size_t count) {
    double *copy = malloc(count * sizeof(*copy));
    double result;
    if (copy == NULL) {
        fprintf(stderr, "allocation failure\n");
        exit(EXIT_FAILURE);
    }
    memcpy(copy, values, count * sizeof(*copy));
    qsort(copy, count, sizeof(*copy), compare_double);
    if ((count & 1U) != 0U) {
        result = copy[count / 2U];
    } else {
        result = (copy[count / 2U - 1U] + copy[count / 2U]) * 0.5;
    }
    free(copy);
    return result;
}

static double median_absolute_deviation(const double *values, size_t count,
                                        double median) {
    double *deviations = malloc(count * sizeof(*deviations));
    double result;
    if (deviations == NULL) {
        fprintf(stderr, "allocation failure\n");
        exit(EXIT_FAILURE);
    }
    for (size_t index = 0U; index < count; ++index) {
        deviations[index] = fabs(values[index] - median);
    }
    result = median_copy(deviations, count);
    free(deviations);
    return result;
}

static void shuffle_indices(size_t *indices, size_t count, uint64_t *seed) {
    for (size_t index = count; index > 1U; --index) {
        const size_t other = (size_t)(xorshift64(seed) % index);
        const size_t temporary = indices[index - 1U];
        indices[index - 1U] = indices[other];
        indices[other] = temporary;
    }
}

#if defined(__AVX2__) && !defined(SELECT_CANDIDATE)
static double measure_batch4(uint64_t iterations, uint64_t salt) {
    state256_t states[4];
    double start;
    double elapsed;
    for (unsigned int item = 0U; item < 4U; ++item) {
        states[item] = initial_state(salt + item * UINT64_C(0x9e3779b97f4a7c15));
    }
    start = monotonic_seconds();
    for (uint64_t index = 0U; index < iterations; ++index) {
        candidate_avx2_batch4(states);
    }
    elapsed = monotonic_seconds() - start;
    for (unsigned int item = 0U; item < 4U; ++item) {
        benchmark_sink ^= states[item].w[0] ^ states[item].w[1] ^
                          states[item].w[2] ^ states[item].w[3];
    }
    return elapsed;
}
#endif

static int benchmark(uint64_t iterations, uint64_t warmup_iterations,
                     size_t repeats) {
    const size_t candidate_count = sizeof(CANDIDATES) / sizeof(CANDIDATES[0]);
    double *samples = calloc(candidate_count * repeats, sizeof(*samples));
    double *medians = calloc(candidate_count, sizeof(*medians));
    size_t *order = malloc(candidate_count * sizeof(*order));
    uint64_t order_seed = UINT64_C(0x243f6a8885a308d3);

    if (iterations == 0U || warmup_iterations == 0U || repeats < 3U ||
        samples == NULL || medians == NULL || order == NULL) {
        fprintf(stderr, "iterations/warmup must be positive and repeats >= 3\n");
        free(samples);
        free(medians);
        free(order);
        return 0;
    }

    printf("measurement=warmup_then_randomized_order_samples\n");
#if defined(CLOCK_MONOTONIC_RAW)
    printf("timer=CLOCK_MONOTONIC_RAW\n");
#else
    printf("timer=CLOCK_MONOTONIC\n");
#endif
    printf("iterations=%" PRIu64 " warmup_iterations=%" PRIu64
           " repeats=%zu candidates=%zu\n",
           iterations, warmup_iterations, repeats, candidate_count);

    for (size_t index = 0U; index < candidate_count; ++index) {
        (void)CANDIDATES[index].measure(
            warmup_iterations,
            UINT64_C(0x9e3779b97f4a7c15) * (uint64_t)(index + 1U));
    }
    printf("sample,candidate,ns_per_20round\n");
    for (size_t sample = 0U; sample < repeats; ++sample) {
        for (size_t index = 0U; index < candidate_count; ++index) {
            order[index] = index;
        }
        shuffle_indices(order, candidate_count, &order_seed);
        for (size_t position = 0U; position < candidate_count; ++position) {
            const size_t index = order[position];
            const uint64_t salt = UINT64_C(0x9e3779b97f4a7c15) *
                                  (uint64_t)(sample * candidate_count + index + 1U);
            const double elapsed = CANDIDATES[index].measure(iterations, salt);
            const double ns = elapsed * 1.0e9 / (double)iterations;
            samples[index * repeats + sample] = ns;
            printf("%zu,%s,%.3f\n", sample + 1U, CANDIDATES[index].name, ns);
        }
    }

    for (size_t index = 0U; index < candidate_count; ++index) {
        medians[index] = median_copy(&samples[index * repeats], repeats);
    }
    printf("summary_candidate,median_ns,mad_ns,min_ns,max_ns,speedup_vs_current\n");
    for (size_t index = 0U; index < candidate_count; ++index) {
        const double *row = &samples[index * repeats];
        double minimum = row[0];
        double maximum = row[0];
        for (size_t sample = 1U; sample < repeats; ++sample) {
            if (row[sample] < minimum) minimum = row[sample];
            if (row[sample] > maximum) maximum = row[sample];
        }
        printf("%s,%.3f,%.3f,%.3f,%.3f,%.4f\n",
               CANDIDATES[index].name,
               medians[index],
               median_absolute_deviation(row, repeats, medians[index]),
               minimum,
               maximum,
               medians[0] / medians[index]);
    }

#if defined(__AVX2__) && !defined(SELECT_CANDIDATE)
    {
        double *batch_samples = calloc(repeats, sizeof(*batch_samples));
        if (batch_samples == NULL) {
            fprintf(stderr, "allocation failure\n");
            free(samples);
            free(medians);
            free(order);
            return 0;
        }
        (void)measure_batch4(warmup_iterations / 4U + 1U, 1U);
        for (size_t sample = 0U; sample < repeats; ++sample) {
            const double elapsed = measure_batch4(
                iterations,
                UINT64_C(0xd1b54a32d192ed03) * (uint64_t)(sample + 1U));
            batch_samples[sample] = elapsed * 1.0e9 /
                                    ((double)iterations * 4.0);
        }
        const double batch_median = median_copy(batch_samples, repeats);
        printf("batch4_throughput_per_state_median_ns=%.3f\n", batch_median);
        printf("batch4_speedup_vs_four_current=%.4f\n", medians[0] / batch_median);
        printf("batch4_submission_api_compatible=no\n");
        free(batch_samples);
    }
#endif
    printf("benchmark_sink=%016" PRIx64 "\n", benchmark_sink);
    free(samples);
    free(medians);
    free(order);
    return 1;
}

static uint64_t parse_u64(const char *text, const char *name) {
    char *end = NULL;
    unsigned long long value;
    errno = 0;
    value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') {
        fprintf(stderr, "invalid %s: %s\n", name, text);
        exit(EXIT_FAILURE);
    }
    return (uint64_t)value;
}

static void usage(const char *program) {
    fprintf(stderr,
            "usage:\n"
            "  %s --selftest TESTVECTOR TESTVECTOR_20ROUND RANDOM_CASES\n"
            "  %s --benchmark ITERATIONS WARMUP_ITERATIONS REPEATS\n",
            program, program);
}

int main(int argc, char **argv) {
    if (argc == 5 && strcmp(argv[1], "--selftest") == 0) {
        size_t vectors = 0U;
        const size_t random_cases = (size_t)parse_u64(argv[4], "random cases");
        const int ok = verify_one_round_vectors(argv[2], &vectors) &&
                       verify_twenty_round_vector(argv[3]) &&
                       differential_test(random_cases);
        printf("one_round_vectors=%zu\n", vectors);
        printf("twenty_round_vector=%s\n", ok ? "PASS" : "FAIL");
        printf("random_differential_cases=%zu\n", random_cases);
        printf("candidate_count=%zu\n", sizeof(CANDIDATES) / sizeof(CANDIDATES[0]));
#if defined(__AVX2__) && !defined(SELECT_CANDIDATE)
        printf("avx2_batch4=PASS\n");
#endif
        printf("selftest=%s\n", ok ? "PASS" : "FAIL");
        return ok ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    if (argc == 5 && strcmp(argv[1], "--benchmark") == 0) {
        return benchmark(parse_u64(argv[2], "iterations"),
                         parse_u64(argv[3], "warmup iterations"),
                         (size_t)parse_u64(argv[4], "repeats"))
                   ? EXIT_SUCCESS
                   : EXIT_FAILURE;
    }
    usage(argv[0]);
    return EXIT_FAILURE;
}
