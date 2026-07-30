#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <immintrin.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

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
static const uint64_t C1[4] = {
    UINT64_C(0x8f4a2c1e9b7d3f61),
    UINT64_C(0x3c6e9a1d5b7f2840),
    UINT64_C(0xa7e2d9c4b1f60853),
    UINT64_C(0x5d0f3a8e2c6b4197),
};
static const uint64_t C2[4] = {
    UINT64_C(0xe7b92d4a6c1f8035),
    UINT64_C(0x1a4f8c3e9d2b6074),
    UINT64_C(0xc3f05a2e8d6194b7),
    UINT64_C(0x6b2e9d1a4f7c3085),
};

#if defined(__GNUC__) && !defined(__clang__)
#define ATTR_BMI2(alignment)                                                  \
    __attribute__((noinline, noclone, target("bmi2"),                       \
                   optimize("no-tree-vectorize"), aligned(alignment)))
#define ATTR_BMI2_LOOP(alignment)                                             \
    __attribute__((noinline, noclone, target("bmi2"),                       \
                   optimize("no-tree-vectorize,no-unroll-loops,no-peel-loops"), \
                   aligned(alignment)))
#define ATTR_SCALAR(alignment)                                                \
    __attribute__((noinline, noclone, optimize("no-tree-vectorize"),        \
                   aligned(alignment)))
#define ATTR_AVX2(alignment)                                                  \
    __attribute__((noinline, noclone, target("avx2"), aligned(alignment)))
#define ATTR_INLINE_BMI2                                                      \
    __attribute__((always_inline, target("bmi2"),                           \
                   optimize("no-tree-vectorize")))
#else
#define ATTR_BMI2(alignment) __attribute__((noinline, target("bmi2"), aligned(alignment)))
#define ATTR_BMI2_LOOP(alignment) ATTR_BMI2(alignment)
#define ATTR_SCALAR(alignment) __attribute__((noinline, aligned(alignment)))
#define ATTR_AVX2(alignment) __attribute__((noinline, target("avx2"), aligned(alignment)))
#define ATTR_INLINE_BMI2 __attribute__((always_inline, target("bmi2")))
#endif

static inline uint64_t rotl64(uint64_t value, unsigned int amount) {
    return (value << amount) | (value >> (64U - amount));
}

static inline uint64_t bswap64(uint64_t value) {
    return __builtin_bswap64(value);
}

static inline uint64_t transform(uint64_t value, unsigned int rotation,
                                 uint64_t xor_constant,
                                 uint64_t add_constant) {
    return bswap64(rotl64(value, rotation) ^ xor_constant) + add_constant;
}

#define DECLARE_RUNTIME_CONSTANTS()                                           \
    const uint64_t a0 = constants1[0], a1 = constants1[1];                   \
    const uint64_t a2 = constants1[2], a3 = constants1[3];                   \
    const uint64_t k0 = constants2[0], k1 = constants2[1];                   \
    const uint64_t k2 = constants2[2], k3 = constants2[3]

#define DECLARE_EMBEDDED_CONSTANTS()                                          \
    const uint64_t a0 = UINT64_C(0x8f4a2c1e9b7d3f61);                       \
    const uint64_t a1 = UINT64_C(0x3c6e9a1d5b7f2840);                       \
    const uint64_t a2 = UINT64_C(0xa7e2d9c4b1f60853);                       \
    const uint64_t a3 = UINT64_C(0x5d0f3a8e2c6b4197);                       \
    const uint64_t k0 = UINT64_C(0xe7b92d4a6c1f8035);                       \
    const uint64_t k1 = UINT64_C(0x1a4f8c3e9d2b6074);                       \
    const uint64_t k2 = UINT64_C(0xc3f05a2e8d6194b7);                       \
    const uint64_t k3 = UINT64_C(0x6b2e9d1a4f7c3085)

#define LOAD_STATE()                                                          \
    uint64_t x0 = state->w[0];                                                \
    uint64_t x1 = state->w[1];                                                \
    uint64_t x2 = state->w[2];                                                \
    uint64_t x3 = state->w[3]

#define STORE_STATE()                                                         \
    do {                                                                      \
        state->w[0] = x0;                                                     \
        state->w[1] = x1;                                                     \
        state->w[2] = x2;                                                     \
        state->w[3] = x3;                                                     \
    } while (0)

#define PAIR_STEP()                                                           \
    do {                                                                      \
        x0 = transform(transform(x0, 43U, k0, a3), 14U, k3, a0);             \
        x1 = transform(transform(x1, 7U, k1, a2), 29U, k2, a1);              \
        x2 = transform(transform(x2, 29U, k2, a1), 7U, k1, a2);              \
        x3 = transform(transform(x3, 14U, k3, a0), 43U, k0, a3);             \
    } while (0)

#define TEN_PAIR_STEPS()                                                      \
    do {                                                                      \
        PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP();     \
        PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP();     \
    } while (0)

/* 0: current best recommendation and paired-speedup baseline. */
ATTR_BMI2(64) static void candidate_full_bmi2_align64(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    TEN_PAIR_STEPS();
    STORE_STATE();
}

/* 1: compact 2-round loop, forced to remain scalar and rolled. */
ATTR_BMI2_LOOP(64) static void candidate_pair_loop_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    for (unsigned int pair = 0U; pair < 10U; ++pair) {
        PAIR_STEP();
    }
    STORE_STATE();
}

/* 2: four rounds in the body, five loop iterations. */
ATTR_BMI2_LOOP(64) static void candidate_unroll2_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    for (unsigned int block = 0U; block < 5U; ++block) {
        PAIR_STEP();
        PAIR_STEP();
    }
    STORE_STATE();
}

/* 3: ten rounds in the body, two loop iterations. */
ATTR_BMI2_LOOP(64) static void candidate_unroll5_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    for (unsigned int block = 0U; block < 2U; ++block) {
        PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP();
    }
    STORE_STATE();
}

/* 16: six rounds per loop iteration (three times), plus one final pair. */
ATTR_BMI2_LOOP(64) static void candidate_unroll3_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    unsigned int blocks = 3U;
    __asm__ __volatile__("" : "+r"(blocks));
    for (unsigned int block = 0U; block < blocks; ++block) {
        PAIR_STEP(); PAIR_STEP(); PAIR_STEP();
    }
    PAIR_STEP();
    STORE_STATE();
}

/* 17: eight rounds per loop iteration (twice), plus two final pairs. */
ATTR_BMI2_LOOP(64) static void candidate_unroll4_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    unsigned int blocks = 2U;
    __asm__ __volatile__("" : "+r"(blocks));
    for (unsigned int block = 0U; block < blocks; ++block) {
        PAIR_STEP(); PAIR_STEP(); PAIR_STEP(); PAIR_STEP();
    }
    PAIR_STEP(); PAIR_STEP();
    STORE_STATE();
}

/* 4-6: identical full unroll with different minimum function alignment. */
ATTR_BMI2(16) static void candidate_full_bmi2_align16(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE(); DECLARE_RUNTIME_CONSTANTS(); TEN_PAIR_STEPS(); STORE_STATE();
}

ATTR_BMI2(32) static void candidate_full_bmi2_align32(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE(); DECLARE_RUNTIME_CONSTANTS(); TEN_PAIR_STEPS(); STORE_STATE();
}

ATTR_BMI2(128) static void candidate_full_bmi2_align128(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE(); DECLARE_RUNTIME_CONSTANTS(); TEN_PAIR_STEPS(); STORE_STATE();
}

/* 7: constants embedded in the helper rather than loaded through arguments. */
ATTR_BMI2(64) static void candidate_full_bmi2_embedded(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    (void)constants1;
    (void)constants2;
    LOAD_STATE();
    DECLARE_EMBEDDED_CONSTANTS();
    TEN_PAIR_STEPS();
    STORE_STATE();
}

static __attribute__((always_inline, target("avx2"))) inline __m256i
rotate_lanes(__m256i value, __m256i left, __m256i right) {
    return _mm256_or_si256(_mm256_sllv_epi64(value, left),
                           _mm256_srlv_epi64(value, right));
}

static __attribute__((always_inline, target("avx2"))) inline __m256i
avx_pair_step(__m256i value,
              __m256i c1_forward,
              __m256i c1_reverse,
              __m256i c2_forward,
              __m256i c2_reverse,
              __m256i byte_swap,
              __m256i left_forward,
              __m256i right_forward,
              __m256i left_reverse,
              __m256i right_reverse) {
    value = rotate_lanes(value, left_forward, right_forward);
    value = _mm256_xor_si256(value, c2_forward);
    value = _mm256_shuffle_epi8(value, byte_swap);
    value = _mm256_add_epi64(value, c1_reverse);
    value = rotate_lanes(value, left_reverse, right_reverse);
    value = _mm256_xor_si256(value, c2_reverse);
    value = _mm256_shuffle_epi8(value, byte_swap);
    return _mm256_add_epi64(value, c1_forward);
}

#define DECLARE_AVX_PAIR_CONSTANTS()                                          \
    const __m256i c1f = _mm256_loadu_si256(                                  \
        (const __m256i *)(const void *)constants1);                           \
    const __m256i c2f = _mm256_loadu_si256(                                  \
        (const __m256i *)(const void *)constants2);                           \
    const __m256i c1r = _mm256_permute4x64_epi64(c1f, 0x1b);                 \
    const __m256i c2r = _mm256_permute4x64_epi64(c2f, 0x1b);                 \
    const __m256i lf = _mm256_setr_epi64x(43, 7, 29, 14);                    \
    const __m256i rf = _mm256_setr_epi64x(21, 57, 35, 50);                   \
    const __m256i lr = _mm256_setr_epi64x(14, 29, 7, 43);                    \
    const __m256i rr = _mm256_setr_epi64x(50, 35, 57, 21);                   \
    const __m256i swap = _mm256_setr_epi8(                                   \
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,             \
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8)

/* 8: compact manual AVX2 two-round loop. */
ATTR_AVX2(64) static void candidate_pair_loop_avx2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    DECLARE_AVX_PAIR_CONSTANTS();
    __m256i value = _mm256_loadu_si256((const __m256i *)(const void *)state);
    for (unsigned int pair = 0U; pair < 10U; ++pair) {
        value = avx_pair_step(value, c1f, c1r, c2f, c2r, swap,
                              lf, rf, lr, rr);
    }
    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

/* 9: same AVX2 pair transform, explicitly expanded ten times. */
ATTR_AVX2(64) static void candidate_pair_unrolled_avx2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    DECLARE_AVX_PAIR_CONSTANTS();
    __m256i value = _mm256_loadu_si256((const __m256i *)(const void *)state);
#define AVX_PAIR()                                                            \
    value = avx_pair_step(value, c1f, c1r, c2f, c2r, swap, lf, rf, lr, rr)
    AVX_PAIR(); AVX_PAIR(); AVX_PAIR(); AVX_PAIR(); AVX_PAIR();
    AVX_PAIR(); AVX_PAIR(); AVX_PAIR(); AVX_PAIR(); AVX_PAIR();
#undef AVX_PAIR
    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

/* 10: direct one-round AVX2 state representation, included as a known failure. */
ATTR_AVX2(64) static void candidate_single_round_avx2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    const __m256i left = _mm256_setr_epi64x(43, 7, 29, 14);
    const __m256i right = _mm256_setr_epi64x(21, 57, 35, 50);
    const __m256i reverse128 = _mm256_setr_epi8(
        15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
        15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0);
    const __m256i add = _mm256_loadu_si256(
        (const __m256i *)(const void *)constants1);
    const __m256i xors = _mm256_loadu_si256(
        (const __m256i *)(const void *)constants2);
    __m256i value = _mm256_loadu_si256((const __m256i *)(const void *)state);
    for (unsigned int round = 0U; round < 20U; ++round) {
        value = rotate_lanes(value, left, right);
        value = _mm256_xor_si256(value, xors);
        value = _mm256_shuffle_epi8(value, reverse128);
        value = _mm256_permute2x128_si256(value, value, 1);
        value = _mm256_add_epi64(value, add);
    }
    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

/* 11: deliberately serialize the four independent chains. */
ATTR_BMI2(64) static void candidate_sequential_chains(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
#define STEP_X0() x0 = transform(transform(x0, 43U, k0, a3), 14U, k3, a0)
#define STEP_X1() x1 = transform(transform(x1, 7U, k1, a2), 29U, k2, a1)
#define STEP_X2() x2 = transform(transform(x2, 29U, k2, a1), 7U, k1, a2)
#define STEP_X3() x3 = transform(transform(x3, 14U, k3, a0), 43U, k0, a3)
    STEP_X0(); STEP_X0(); STEP_X0(); STEP_X0(); STEP_X0();
    STEP_X0(); STEP_X0(); STEP_X0(); STEP_X0(); STEP_X0();
    STEP_X1(); STEP_X1(); STEP_X1(); STEP_X1(); STEP_X1();
    STEP_X1(); STEP_X1(); STEP_X1(); STEP_X1(); STEP_X1();
    STEP_X2(); STEP_X2(); STEP_X2(); STEP_X2(); STEP_X2();
    STEP_X2(); STEP_X2(); STEP_X2(); STEP_X2(); STEP_X2();
    STEP_X3(); STEP_X3(); STEP_X3(); STEP_X3(); STEP_X3();
    STEP_X3(); STEP_X3(); STEP_X3(); STEP_X3(); STEP_X3();
#undef STEP_X0
#undef STEP_X1
#undef STEP_X2
#undef STEP_X3
    STORE_STATE();
}

/* 12: exact extra-call shape needed when only the supplied loop body is edited. */
ATTR_BMI2(64) static void candidate_submission_wrapper(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    for (int round = 0; round < 20; ++round) {
        candidate_full_bmi2_align64(state, constants1, constants2);
        round = 19;
    }
}

static ATTR_INLINE_BMI2 inline void inline_full_core(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE(); DECLARE_RUNTIME_CONSTANTS(); TEN_PAIR_STEPS(); STORE_STATE();
}

/* 13: force the 20-round core into the public wrapper. */
ATTR_BMI2(64) static void candidate_inline_core(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    inline_full_core(state, constants1, constants2);
}

/* 14: full scalar unroll without a BMI2 target attribute (default flags). */
ATTR_SCALAR(64) static void candidate_full_without_bmi2(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE(); DECLARE_RUNTIME_CONSTANTS(); TEN_PAIR_STEPS(); STORE_STATE();
}

/* 15: current compact register-resident one-round loop. */
ATTR_BMI2_LOOP(64) static void candidate_register_loop(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    LOAD_STATE();
    DECLARE_RUNTIME_CONSTANTS();
    for (unsigned int round = 0U; round < 20U; ++round) {
        const uint64_t y0 = transform(x3, 14U, k3, a0);
        const uint64_t y1 = transform(x2, 29U, k2, a1);
        const uint64_t y2 = transform(x1, 7U, k1, a2);
        const uint64_t y3 = transform(x0, 43U, k0, a3);
        x0 = y0; x1 = y1; x2 = y2; x3 = y3;
    }
    STORE_STATE();
}

#undef DECLARE_AVX_PAIR_CONSTANTS
#undef TEN_PAIR_STEPS
#undef PAIR_STEP
#undef STORE_STATE
#undef LOAD_STATE
#undef DECLARE_EMBEDDED_CONSTANTS
#undef DECLARE_RUNTIME_CONSTANTS

typedef void (*candidate_fn)(state256_t *, const uint64_t[4],
                             const uint64_t[4]);
typedef struct {
    const char *name;
    candidate_fn function;
} candidate_entry;

#define ALL_CANDIDATES                                                         \
    {"full_bmi2_align64", candidate_full_bmi2_align64},                      \
    {"pair_loop_bmi2", candidate_pair_loop_bmi2},                            \
    {"unroll2_bmi2", candidate_unroll2_bmi2},                                \
    {"unroll5_bmi2", candidate_unroll5_bmi2},                                \
    {"full_bmi2_align16", candidate_full_bmi2_align16},                      \
    {"full_bmi2_align32", candidate_full_bmi2_align32},                      \
    {"full_bmi2_align128", candidate_full_bmi2_align128},                    \
    {"full_bmi2_embedded", candidate_full_bmi2_embedded},                    \
    {"pair_loop_avx2", candidate_pair_loop_avx2},                            \
    {"pair_unrolled_avx2", candidate_pair_unrolled_avx2},                    \
    {"single_round_avx2", candidate_single_round_avx2},                      \
    {"sequential_chains", candidate_sequential_chains},                      \
    {"submission_wrapper", candidate_submission_wrapper},                    \
    {"inline_core", candidate_inline_core},                                  \
    {"full_without_bmi2", candidate_full_without_bmi2},                      \
    {"register_loop", candidate_register_loop},                              \
    {"unroll3_bmi2", candidate_unroll3_bmi2},                                \
    {"unroll4_bmi2", candidate_unroll4_bmi2}

#if !defined(SELECT_CANDIDATE)
static const candidate_entry CANDIDATES[] = {ALL_CANDIDATES};
#elif SELECT_CANDIDATE == 0
#define SELECTED_NAME "full_bmi2_align64"
#define SELECTED_FUNCTION candidate_full_bmi2_align64
#elif SELECT_CANDIDATE == 1
#define SELECTED_NAME "pair_loop_bmi2"
#define SELECTED_FUNCTION candidate_pair_loop_bmi2
#elif SELECT_CANDIDATE == 2
#define SELECTED_NAME "unroll2_bmi2"
#define SELECTED_FUNCTION candidate_unroll2_bmi2
#elif SELECT_CANDIDATE == 3
#define SELECTED_NAME "unroll5_bmi2"
#define SELECTED_FUNCTION candidate_unroll5_bmi2
#elif SELECT_CANDIDATE == 4
#define SELECTED_NAME "full_bmi2_align16"
#define SELECTED_FUNCTION candidate_full_bmi2_align16
#elif SELECT_CANDIDATE == 5
#define SELECTED_NAME "full_bmi2_align32"
#define SELECTED_FUNCTION candidate_full_bmi2_align32
#elif SELECT_CANDIDATE == 6
#define SELECTED_NAME "full_bmi2_align128"
#define SELECTED_FUNCTION candidate_full_bmi2_align128
#elif SELECT_CANDIDATE == 7
#define SELECTED_NAME "full_bmi2_embedded"
#define SELECTED_FUNCTION candidate_full_bmi2_embedded
#elif SELECT_CANDIDATE == 8
#define SELECTED_NAME "pair_loop_avx2"
#define SELECTED_FUNCTION candidate_pair_loop_avx2
#elif SELECT_CANDIDATE == 9
#define SELECTED_NAME "pair_unrolled_avx2"
#define SELECTED_FUNCTION candidate_pair_unrolled_avx2
#elif SELECT_CANDIDATE == 10
#define SELECTED_NAME "single_round_avx2"
#define SELECTED_FUNCTION candidate_single_round_avx2
#elif SELECT_CANDIDATE == 11
#define SELECTED_NAME "sequential_chains"
#define SELECTED_FUNCTION candidate_sequential_chains
#elif SELECT_CANDIDATE == 12
#define SELECTED_NAME "submission_wrapper"
#define SELECTED_FUNCTION candidate_submission_wrapper
#elif SELECT_CANDIDATE == 13
#define SELECTED_NAME "inline_core"
#define SELECTED_FUNCTION candidate_inline_core
#elif SELECT_CANDIDATE == 14
#define SELECTED_NAME "full_without_bmi2"
#define SELECTED_FUNCTION candidate_full_without_bmi2
#elif SELECT_CANDIDATE == 15
#define SELECTED_NAME "register_loop"
#define SELECTED_FUNCTION candidate_register_loop
#elif SELECT_CANDIDATE == 16
#define SELECTED_NAME "unroll3_bmi2"
#define SELECTED_FUNCTION candidate_unroll3_bmi2
#elif SELECT_CANDIDATE == 17
#define SELECTED_NAME "unroll4_bmi2"
#define SELECTED_FUNCTION candidate_unroll4_bmi2
#else
#error "invalid SELECT_CANDIDATE"
#endif

static void reference_one_round(state256_t *state) {
    uint8_t input[32];
    uint8_t output[32];
    for (unsigned int word = 0U; word < 4U; ++word) {
        state->w[word] = rotl64(state->w[word], ROTATIONS[word]);
        state->w[word] ^= C2[word];
    }
    memcpy(input, state, sizeof(input));
    for (unsigned int byte = 0U; byte < 32U; ++byte) {
        output[byte] = input[REVERSE_BYTES[byte]];
    }
    memcpy(state, output, sizeof(output));
    for (unsigned int word = 0U; word < 4U; ++word) {
        state->w[word] += C1[word];
    }
}

static void reference_20_rounds(state256_t *state) {
    for (unsigned int round = 0U; round < 20U; ++round) {
        reference_one_round(state);
    }
}

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
    return fscanf(stream, "%" SCNx64 " %" SCNx64 " %" SCNx64 " %" SCNx64,
                  &state->w[0], &state->w[1], &state->w[2], &state->w[3]) == 4;
}

static int verify_one_round_file(const char *path, size_t *count) {
    FILE *stream = fopen(path, "r");
    unsigned int number;
    char label[16];
    if (stream == NULL) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        return 0;
    }
    *count = 0U;
    while (fscanf(stream, " #%u", &number) == 1) {
        state256_t input;
        state256_t expected;
        if (fscanf(stream, "%15s", label) != 1 || strcmp(label, "input") != 0 ||
            !read_state(stream, &input) || fscanf(stream, "%15s", label) != 1 ||
            strcmp(label, "output") != 0 || !read_state(stream, &expected)) {
            fclose(stream);
            return 0;
        }
        reference_one_round(&input);
        if (!states_equal(&input, &expected)) {
            fprintf(stderr, "one-round mismatch at #%u\n", number);
            fclose(stream);
            return 0;
        }
        ++*count;
    }
    fclose(stream);
    return *count != 0U;
}

static int verify_twenty_round_file(const char *path) {
    FILE *stream = fopen(path, "r");
    char label[16];
    state256_t input;
    state256_t expected;
    int parsed;
    if (stream == NULL) return 0;
    parsed = fscanf(stream, "%15s", label) == 1 && strcmp(label, "input") == 0 &&
             read_state(stream, &input) && fscanf(stream, "%15s", label) == 1 &&
             strcmp(label, "output") == 0 && read_state(stream, &expected);
    fclose(stream);
    if (!parsed) return 0;
#if !defined(SELECT_CANDIDATE)
    for (size_t index = 0U; index < sizeof(CANDIDATES) / sizeof(CANDIDATES[0]);
         ++index) {
        state256_t result = input;
        CANDIDATES[index].function(&result, C1, C2);
        if (!states_equal(&result, &expected)) {
            fprintf(stderr, "%s failed supplied 20-round vector\n",
                    CANDIDATES[index].name);
            return 0;
        }
    }
#else
    state256_t result = input;
    SELECTED_FUNCTION(&result, C1, C2);
    if (!states_equal(&result, &expected)) return 0;
#endif
    return 1;
}

static int differential_test(size_t cases) {
    uint64_t seed = UINT64_C(0x6a09e667f3bcc909);
    for (size_t case_index = 0U; case_index < cases; ++case_index) {
        state256_t input;
        for (unsigned int word = 0U; word < 4U; ++word) {
            input.w[word] = xorshift64(&seed);
        }
        state256_t expected = input;
        reference_20_rounds(&expected);
#if !defined(SELECT_CANDIDATE)
        for (size_t index = 0U;
             index < sizeof(CANDIDATES) / sizeof(CANDIDATES[0]); ++index) {
            state256_t result = input;
            CANDIDATES[index].function(&result, C1, C2);
            if (!states_equal(&result, &expected)) {
                fprintf(stderr, "%s failed random case %zu\n",
                        CANDIDATES[index].name, case_index);
                return 0;
            }
        }
#else
        state256_t result = input;
        SELECTED_FUNCTION(&result, C1, C2);
        if (!states_equal(&result, &expected)) return 0;
#endif
    }
    return 1;
}

#if defined(SELECT_CANDIDATE)
static double monotonic_seconds(void) {
    struct timespec timestamp;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &timestamp) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (double)timestamp.tv_sec + (double)timestamp.tv_nsec * 1.0e-9;
}

static volatile uint64_t benchmark_sink;

static state256_t initial_state(uint64_t salt) {
    const state256_t state = {{
        UINT64_C(0x0123456789abcdef) ^ salt,
        UINT64_C(0xfedcba9876543210) + salt,
        UINT64_C(0x0f1e2d3c4b5a6978) ^ (salt << 1),
        UINT64_C(0x8877665544332211) - salt,
    }};
    return state;
}

static double measure(uint64_t iterations, uint64_t salt) {
    state256_t state = initial_state(salt);
    const double start = monotonic_seconds();
    for (uint64_t index = 0U; index < iterations; ++index) {
        SELECTED_FUNCTION(&state, C1, C2);
    }
    const double elapsed = monotonic_seconds() - start;
    benchmark_sink ^= state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3];
    return elapsed;
}
#endif

static uint64_t parse_u64(const char *text) {
    char *end = NULL;
    errno = 0;
    const unsigned long long value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') exit(EXIT_FAILURE);
    return (uint64_t)value;
}

int main(int argc, char **argv) {
    if (argc == 5 && strcmp(argv[1], "--selftest") == 0) {
        size_t vectors = 0U;
        const size_t random_cases = (size_t)parse_u64(argv[4]);
        const int ok = verify_one_round_file(argv[2], &vectors) &&
                       verify_twenty_round_file(argv[3]) &&
                       differential_test(random_cases);
        printf("one_round_vectors=%zu\n", vectors);
#if !defined(SELECT_CANDIDATE)
        printf("candidate_count=%zu\n",
               sizeof(CANDIDATES) / sizeof(CANDIDATES[0]));
#else
        printf("candidate=%s\n", SELECTED_NAME);
#endif
        printf("random_differential_cases=%zu\n", random_cases);
        printf("selftest=%s\n", ok ? "PASS" : "FAIL");
        return ok ? EXIT_SUCCESS : EXIT_FAILURE;
    }
#if defined(SELECT_CANDIDATE)
    if (argc == 5 && strcmp(argv[1], "--bench") == 0) {
        const uint64_t iterations = parse_u64(argv[2]);
        const uint64_t warmup = parse_u64(argv[3]);
        const uint64_t salt = parse_u64(argv[4]);
        if (iterations == 0U || warmup == 0U) return EXIT_FAILURE;
        (void)measure(warmup, salt ^ UINT64_C(0xd1b54a32d192ed03));
        const double elapsed = measure(iterations, salt);
        printf("candidate=%s ns=%.3f sink=%016" PRIx64 "\n",
               SELECTED_NAME, elapsed * 1.0e9 / (double)iterations,
               benchmark_sink);
        return EXIT_SUCCESS;
    }
#endif
    fprintf(stderr, "usage: --selftest V1 V20 CASES | --bench ITERS WARMUP SALT\n");
    return EXIT_FAILURE;
}
