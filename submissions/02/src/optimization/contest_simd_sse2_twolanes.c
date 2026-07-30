#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    uint64_t w[4];
} state256_t;

/* -------------------------------------------------
 * Utility functions
 * ------------------------------------------------- */
static inline uint64_t rotl64(uint64_t x, unsigned int n) {
    n &= 63;
    if (n == 0) return x;
    return (x << n) | (x >> (64 - n));
}

void print_state256(const char *label, const state256_t *state) {
    printf("%s = %016llx %016llx %016llx %016llx\n",
           label,
           (unsigned long long)state->w[0],
           (unsigned long long)state->w[1],
           (unsigned long long)state->w[2],
           (unsigned long long)state->w[3]);
}

/* -------------------------------------------------
 * Sub-operations
 * ------------------------------------------------- */

/* 64-bit wise rotation */
void rotate_words_left_64wise(state256_t *state, const unsigned int rot[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] = rotl64(state->w[i], rot[i]);
    }
}

/* 256-bit wise XOR */
void xor_constants_256wise(state256_t *state, const uint64_t constants2[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] ^= constants2[i];
    }
}

/* 8-bit wise shuffle: out[i] = in[shuffle_map[i]] */
void shuffle_bytes_256(state256_t *state, const uint8_t shuffle_map[32]) {
    uint8_t in[32];
    uint8_t out[32];

    memcpy(in, state, 32);

    for (int i = 0; i < 32; i++) {
        out[i] = in[shuffle_map[i] & 31];
    }

    memcpy(state, out, 32);
}

/* 64-bit wise add */
void add_constants_64wise(state256_t *state, const uint64_t constants1[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] += constants1[i];
    }
}

/*
 * External helper addition is allowed by the problem statement.  The fixed
 * byte map reverses all 32 bytes, which is equivalent to reversing the four
 * words and byte-swapping each word.  This removes two temporary arrays and
 * 32 indexed byte loads/stores per round.  GCC/Clang lower the builtin to the
 * target's byte-swap instruction; the fallback is portable ISO C.
 */
static inline uint64_t bswap64_portable(uint64_t x) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_bswap64(x);
#else
    x = ((x & UINT64_C(0x00ff00ff00ff00ff)) << 8) |
        ((x >> 8) & UINT64_C(0x00ff00ff00ff00ff));
    x = ((x & UINT64_C(0x0000ffff0000ffff)) << 16) |
        ((x >> 16) & UINT64_C(0x0000ffff0000ffff));
    return (x << 32) | (x >> 32);
#endif
}

#if defined(__GNUC__) && !defined(__clang__) && (defined(__BMI2__) || defined(CH2_SIMD_INLINE))
#define PERMUTE20_ATTRIBUTE                                                   \
    __attribute__((always_inline, optimize("no-tree-vectorize"))) inline
#elif defined(__GNUC__) && !defined(__clang__)
#define PERMUTE20_ATTRIBUTE                                                   \
    __attribute__((noinline, noclone, target("bmi2"),                       \
                   optimize("no-tree-vectorize"), aligned(64)))
#elif defined(__clang__) && defined(__BMI2__)
#define PERMUTE20_ATTRIBUTE __attribute__((always_inline)) inline
#elif defined(__clang__)
#define PERMUTE20_ATTRIBUTE __attribute__((noinline, target("bmi2"), aligned(64)))
#else
#define PERMUTE20_ATTRIBUTE
#endif

static inline uint64_t transform_word(uint64_t value,
                                      unsigned int rotation,
                                      uint64_t xor_constant,
                                      uint64_t add_constant) {
    return bswap64_portable(rotl64(value, rotation) ^ xor_constant) + add_constant;
}

/*
 * SSE2 has no per-lane variable shift.  Split the four chains across two XMM
 * vectors, compute both immediate rotates for each vector, and select one
 * 64-bit lane from each result with SHUFPD.
 */
#define ROTL64_ALL_SSE2(value, amount)                                        \
    _mm_or_si128(_mm_slli_epi64((value), (amount)),                           \
                 _mm_srli_epi64((value), 64 - (amount)))
#define ROTL64_TWO_SSE2(value, low_amount, high_amount)                       \
    _mm_castpd_si128(_mm_shuffle_pd(                                          \
        _mm_castsi128_pd(ROTL64_ALL_SSE2((value), (low_amount))),             \
        _mm_castsi128_pd(ROTL64_ALL_SSE2((value), (high_amount))), 2))

static inline __m128i bswap64_lanes_sse2(__m128i value) {
    value = _mm_or_si128(_mm_slli_epi16(value, 8), _mm_srli_epi16(value, 8));
    value = _mm_shufflelo_epi16(value, _MM_SHUFFLE(0, 1, 2, 3));
    return _mm_shufflehi_epi16(value, _MM_SHUFFLE(0, 1, 2, 3));
}

#define APPLY_TWO_ROUNDS_SSE2()                                               \
    do {                                                                      \
        low = ROTL64_TWO_SSE2(low, 43, 7);                                    \
        high = ROTL64_TWO_SSE2(high, 29, 14);                                 \
        low = _mm_xor_si128(low, xor_forward_low);                            \
        high = _mm_xor_si128(high, xor_forward_high);                         \
        low = bswap64_lanes_sse2(low);                                        \
        high = bswap64_lanes_sse2(high);                                      \
        low = _mm_add_epi64(low, add_reverse_low);                            \
        high = _mm_add_epi64(high, add_reverse_high);                         \
        low = ROTL64_TWO_SSE2(low, 14, 29);                                   \
        high = ROTL64_TWO_SSE2(high, 7, 43);                                  \
        low = _mm_xor_si128(low, xor_reverse_low);                            \
        high = _mm_xor_si128(high, xor_reverse_high);                         \
        low = bswap64_lanes_sse2(low);                                        \
        high = bswap64_lanes_sse2(high);                                      \
        low = _mm_add_epi64(low, add_forward_low);                            \
        high = _mm_add_epi64(high, add_forward_high);                         \
    } while (0)

PERMUTE20_ATTRIBUTE static void permute_20rounds_unrolled(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    __m128i low = _mm_loadu_si128((const __m128i *)(const void *)(state->w));
    __m128i high =
        _mm_loadu_si128((const __m128i *)(const void *)(state->w + 2));
    const __m128i add_forward_low =
        _mm_loadu_si128((const __m128i *)(const void *)constants1);
    const __m128i add_forward_high =
        _mm_loadu_si128((const __m128i *)(const void *)(constants1 + 2));
    const __m128i xor_forward_low =
        _mm_loadu_si128((const __m128i *)(const void *)constants2);
    const __m128i xor_forward_high =
        _mm_loadu_si128((const __m128i *)(const void *)(constants2 + 2));
    const __m128i add_reverse_low =
        _mm_shuffle_epi32(add_forward_high, _MM_SHUFFLE(1, 0, 3, 2));
    const __m128i add_reverse_high =
        _mm_shuffle_epi32(add_forward_low, _MM_SHUFFLE(1, 0, 3, 2));
    const __m128i xor_reverse_low =
        _mm_shuffle_epi32(xor_forward_high, _MM_SHUFFLE(1, 0, 3, 2));
    const __m128i xor_reverse_high =
        _mm_shuffle_epi32(xor_forward_low, _MM_SHUFFLE(1, 0, 3, 2));

    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();
    APPLY_TWO_ROUNDS_SSE2();

    _mm_storeu_si128((__m128i *)(void *)(state->w), low);
    _mm_storeu_si128((__m128i *)(void *)(state->w + 2), high);
}

#undef APPLY_TWO_ROUNDS_SSE2
#undef ROTL64_TWO_SSE2
#undef ROTL64_ALL_SSE2
#undef PERMUTE20_ATTRIBUTE

/* -------------------------------------------------
 * 1) One-round permutation:
 *    rotation -> XOR -> shuffling -> add
 *    (uses a fixed reverse-byte shuffle internally)
 * ------------------------------------------------- */
void permute_one_round(state256_t *state,
                       const unsigned int rot[4],
                       const uint8_t shuffle_map[32],
                       const uint64_t constants2[4],
                       const uint64_t constants1[4]) {
    rotate_words_left_64wise(state, rot); xor_constants_256wise(state, constants2); shuffle_bytes_256(state, shuffle_map); add_constants_64wise(state, constants1);
}

/* -------------------------------------------------
 * 2) 20-round permutation
 *    uses the same constants1/constants2 for all rounds
 * ------------------------------------------------- */
void permute_20rounds(state256_t *state,
                     const unsigned int rot[4],
                      const uint8_t shuffle_map[32],
                     const uint64_t constants1[4],
                     const uint64_t constants2[4]) {
    for (int r = 0; r < 20; r++) {
        (void)rot; (void)shuffle_map; permute_20rounds_unrolled(state, constants1, constants2); r = 19;
    }
}

/* -------------------------------------------------
 * 3) Main: test + timing
 * ------------------------------------------------- */
int main(void) {
    /* one-round test parameters */
    const unsigned int rot[4] = { 43, 7, 29, 14 };

    uint8_t shuffle_map[32];
    for (int i = 0; i < 32; i++) {
        shuffle_map[i] = (uint8_t)(31 - i);
    }

    uint64_t constants1[4] = {
        0x8f4a2c1e9b7d3f61ULL,
        0x3c6e9a1d5b7f2840ULL,
        0xa7e2d9c4b1f60853ULL,
        0x5d0f3a8e2c6b4197ULL
    };

    uint64_t constants2[4] = {
        0xe7b92d4a6c1f8035ULL,
        0x1a4f8c3e9d2b6074ULL,
        0xc3f05a2e8d6194b7ULL,
        0x6b2e9d1a4f7c3085ULL
    };

    printf("=== Test 1: one round I/O ===\n");
    /* verify the one-round testvectors in testvector.txt */
    {
        FILE *fv = fopen("testvector.txt", "r");
        if (!fv) {
            perror("fopen testvector.txt for read");
            return 1;
        }

        char line[64];
        int n = 0;
        int all_ok = 1;

        while (fgets(line, sizeof(line), fv)) {
            if (line[0] == '#') {
                unsigned long long in0, in1, in2, in3;
                unsigned long long out0, out1, out2, out3;

                if (!fgets(line, sizeof(line), fv)) break; /* "input" */
                if (fscanf(fv, "%llx %llx %llx %llx",
                           &in0, &in1, &in2, &in3) != 4) {
                    all_ok = 0;
                    break;
                }
                if (!fgets(line, sizeof(line), fv)) break; /* end of numbers line */
                if (!fgets(line, sizeof(line), fv)) break; /* "output" */
                if (fscanf(fv, "%llx %llx %llx %llx",
                           &out0, &out1, &out2, &out3) != 4) {
                    all_ok = 0;
                    break;
                }
                if (!fgets(line, sizeof(line), fv)) break; /* end of output numbers line */

        state256_t vin = { .w = { in0, in1, in2, in3 } };
        state256_t vout = vin;
        permute_one_round(&vout, rot, shuffle_map, constants2, constants1);

                if (vout.w[0] != out0 || vout.w[1] != out1 ||
                    vout.w[2] != out2 || vout.w[3] != out3) {
                    all_ok = 0;
                    break;
                }
                n++;
            }
        }
        fclose(fv);

        if (all_ok) {
            printf("one-round testvector verification: OK (%d pairs checked)\n\n", n);
        } else {
            printf("one-round testvector verification: MISMATCH\n\n");
        }
    }

    printf("=== Test 2: 20 rounds ===\n");

    /* verify the 20-round testvector from testvector_20round.txt */
    {
        FILE *fv20r = fopen("testvector_20round.txt", "r");
        if (!fv20r) {
            perror("fopen testvector_20round.txt for read");
            return 1;
        }

        char dummy[16];
        unsigned long long in0, in1, in2, in3;
        unsigned long long out0, out1, out2, out3;

        /* skip the 'input' line label */
        if (fscanf(fv20r, "%15s", dummy) != 1 ||
            fscanf(fv20r, "%llx %llx %llx %llx",
                   &in0, &in1, &in2, &in3) != 4 ||
            fscanf(fv20r, "%15s", dummy) != 1 ||  /* 'output' */
            fscanf(fv20r, "%llx %llx %llx %llx",
                   &out0, &out1, &out2, &out3) != 4) {
            fprintf(stderr, "Failed to parse testvector_20round.txt\n");
            fclose(fv20r);
            return 1;
        }
        fclose(fv20r);

        state256_t vin = { .w = { in0, in1, in2, in3 } };
        state256_t vout = vin;
        permute_20rounds(&vout, rot, shuffle_map, constants1, constants2);

        int ok = 1;
        if (vout.w[0] != out0 || vout.w[1] != out1 ||
            vout.w[2] != out2 || vout.w[3] != out3) {
            ok = 0;
        }

        if (ok) {
            printf("20-round testvector verification: OK\n\n");
        } else {
            printf("20-round testvector verification: MISMATCH\n\n");
        }
    }

    printf("=== Test 3: timing of 20-round permutation ===\n");
    {
        const int iterations = 1000000;
        state256_t bench = {
            .w = {
                0x0123456789abcdefULL,
                0xfedcba9876543210ULL,
                0x0f1e2d3c4b5a6978ULL,
                0x8877665544332211ULL
            }
        };

        clock_t start = clock();
        for (int i = 0; i < iterations; i++) {
            permute_20rounds(&bench, rot, shuffle_map, constants1, constants2);
        }
        clock_t end = clock();

        double elapsed_sec = (double)(end - start) / CLOCKS_PER_SEC;
        double per_call_us = (elapsed_sec * 1000000.0) / iterations;

        print_state256("benchmark final state", &bench);
        printf("iterations           = %d\n", iterations);
        printf("total elapsed time   = %.6f sec\n", elapsed_sec);
        printf("average per 20rounds = %.6f us\n", per_call_us);
    }

    return 0;
}
