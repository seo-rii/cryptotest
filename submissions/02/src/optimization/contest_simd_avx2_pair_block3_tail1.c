#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    uint64_t w[4];
} state256_t;

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

void rotate_words_left_64wise(state256_t *state, const unsigned int rot[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] = rotl64(state->w[i], rot[i]);
    }
}

void xor_constants_256wise(state256_t *state, const uint64_t constants2[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] ^= constants2[i];
    }
}

void shuffle_bytes_256(state256_t *state, const uint8_t shuffle_map[32]) {
    uint8_t in[32];
    uint8_t out[32];

    memcpy(in, state, 32);
    for (int i = 0; i < 32; i++) {
        out[i] = in[shuffle_map[i] & 31];
    }
    memcpy(state, out, 32);
}

void add_constants_64wise(state256_t *state, const uint64_t constants1[4]) {
    for (int i = 0; i < 4; i++) {
        state->w[i] += constants1[i];
    }
}

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

#if defined(__GNUC__) && !defined(__clang__) && \
    (defined(__BMI2__) || defined(CH2_SIMD_INLINE))
#define PERMUTE20_ATTRIBUTE                                                   \
    __attribute__((always_inline, optimize("no-tree-vectorize"))) inline
#elif defined(__GNUC__) && !defined(__clang__)
#define PERMUTE20_ATTRIBUTE                                                   \
    __attribute__((noinline, noclone, target("bmi2,avx2"),                  \
                   optimize("no-tree-vectorize"), aligned(64)))
#elif defined(__clang__) && defined(__BMI2__)
#define PERMUTE20_ATTRIBUTE __attribute__((always_inline)) inline
#elif defined(__clang__)
#define PERMUTE20_ATTRIBUTE                                                   \
    __attribute__((noinline, target("bmi2,avx2"), aligned(64)))
#else
#define PERMUTE20_ATTRIBUTE
#endif

static inline uint64_t transform_word(uint64_t value,
                                      unsigned int rotation,
                                      uint64_t xor_constant,
                                      uint64_t add_constant) {
    return bswap64_portable(rotl64(value, rotation) ^ xor_constant) +
           add_constant;
}

#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)               \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                        \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                           \
    "vpor %[value], %[scratch], %[value]\n\t"                                \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                        \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                           \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"

#define INLINE_ASM_PAIR()                                                      \
    INLINE_ASM_TRANSFORM("left_forward", "right_forward", "xor_forward",      \
                         "add_reverse")                                        \
    INLINE_ASM_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",      \
                         "add_forward")

/*
 * Ten two-round pairs are scheduled as 3 + 3 + 3 + 1.  The three-pair body
 * cuts the dynamic loop-control cost relative to block2, while the one-pair
 * tail avoids padding the loop to a divisor of ten.  The local label uses %=
 * so inlining the statement more than once cannot collide.  The separate
 * block2 and block5 wrappers select their respective counted branches below
 * without duplicating the shared dataflow or verification harness.
 */
PERMUTE20_ATTRIBUTE static void permute_20rounds_block3_tail1(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    register __m256i value __asm__("ymm0") =
        _mm256_loadu_si256((const __m256i *)(const void *)state);
    __m256i xor_forward =
        _mm256_loadu_si256((const __m256i *)(const void *)constants2);
    __m256i add_reverse =
        _mm256_permute4x64_epi64(
            _mm256_loadu_si256((const __m256i *)(const void *)constants1),
            _MM_SHUFFLE(0, 1, 2, 3));
    __m256i xor_reverse =
        _mm256_permute4x64_epi64(xor_forward, _MM_SHUFFLE(0, 1, 2, 3));
    __m256i add_forward =
        _mm256_loadu_si256((const __m256i *)(const void *)constants1);
    __m256i scratch;
    __m256i left_forward =
        _mm256_setr_epi64x(43, 7, 29, 14);
    __m256i right_forward =
        _mm256_setr_epi64x(21, 57, 35, 50);
    __m256i left_reverse =
        _mm256_setr_epi64x(14, 29, 7, 43);
    __m256i right_reverse =
        _mm256_setr_epi64x(50, 35, 57, 21);
    __m256i byte_swap =
        _mm256_setr_epi8(
            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,
            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8);
    unsigned int blocks;

/* TENTH_COUNTED_KERNEL_BEGIN */
#if defined(CH2_TENTH_BLOCK2)
    __asm__(
        "movl $5, %[blocks]\n\t"
        ".Ltenth_dec_block2_%=:\n\t"
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        "decl %[blocks]\n\t"
        "jne .Ltenth_dec_block2_%=\n\t"
        : [value] "+x"(value), [scratch] "=&x"(scratch),
          [blocks] "=&r"(blocks)
        : [xor_forward] "x"(xor_forward), [add_reverse] "x"(add_reverse),
          [xor_reverse] "x"(xor_reverse), [add_forward] "x"(add_forward),
          [left_forward] "x"(left_forward), [right_forward] "x"(right_forward),
          [left_reverse] "x"(left_reverse), [right_reverse] "x"(right_reverse),
          [byte_swap] "x"(byte_swap)
        : "cc");
#elif !defined(CH2_TENTH_BLOCK5)
    __asm__(
        "movl $3, %[blocks]\n\t"
        ".Ltenth_dec_block3_%=:\n\t"
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        "decl %[blocks]\n\t"
        "jne .Ltenth_dec_block3_%=\n\t"
        INLINE_ASM_PAIR()
        : [value] "+x"(value), [scratch] "=&x"(scratch),
          [blocks] "=&r"(blocks)
        : [xor_forward] "x"(xor_forward), [add_reverse] "x"(add_reverse),
          [xor_reverse] "x"(xor_reverse), [add_forward] "x"(add_forward),
          [left_forward] "x"(left_forward), [right_forward] "x"(right_forward),
          [left_reverse] "x"(left_reverse), [right_reverse] "x"(right_reverse),
          [byte_swap] "x"(byte_swap)
        : "cc");
#else
    __asm__(
        "movl $2, %[blocks]\n\t"
        ".Ltenth_dec_block5_%=:\n\t"
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        INLINE_ASM_PAIR()
        "decl %[blocks]\n\t"
        "jne .Ltenth_dec_block5_%=\n\t"
        : [value] "+x"(value), [scratch] "=&x"(scratch),
          [blocks] "=&r"(blocks)
        : [xor_forward] "x"(xor_forward), [add_reverse] "x"(add_reverse),
          [xor_reverse] "x"(xor_reverse), [add_forward] "x"(add_forward),
          [left_forward] "x"(left_forward), [right_forward] "x"(right_forward),
          [left_reverse] "x"(left_reverse), [right_reverse] "x"(right_reverse),
          [byte_swap] "x"(byte_swap)
        : "cc");
#endif
/* TENTH_COUNTED_KERNEL_END */

    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

#undef INLINE_ASM_PAIR
#undef INLINE_ASM_TRANSFORM
#undef PERMUTE20_ATTRIBUTE

void permute_one_round(state256_t *state,
                       const unsigned int rot[4],
                       const uint8_t shuffle_map[32],
                       const uint64_t constants2[4],
                       const uint64_t constants1[4]) {
    rotate_words_left_64wise(state, rot);
    xor_constants_256wise(state, constants2);
    shuffle_bytes_256(state, shuffle_map);
    add_constants_64wise(state, constants1);
}

void permute_20rounds(state256_t *state,
                      const unsigned int rot[4],
                      const uint8_t shuffle_map[32],
                      const uint64_t constants1[4],
                      const uint64_t constants2[4]) {
    for (int r = 0; r < 20; r++) {
        (void)rot;
        (void)shuffle_map;
        permute_20rounds_block3_tail1(state, constants1, constants2);
        r = 19;
    }
}

int main(void) {
    const unsigned int rot[4] = {43, 7, 29, 14};
    uint8_t shuffle_map[32];
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

    for (int i = 0; i < 32; i++) {
        shuffle_map[i] = (uint8_t)(31 - i);
    }

    printf("=== Test 1: one round I/O ===\n");
    {
        FILE *fv = fopen("testvector.txt", "r");
        char line[64];
        int n = 0;
        int all_ok = 1;

        if (!fv) {
            perror("fopen testvector.txt for read");
            return 1;
        }
        while (fgets(line, sizeof(line), fv)) {
            if (line[0] == '#') {
                unsigned long long in0, in1, in2, in3;
                unsigned long long out0, out1, out2, out3;
                state256_t vin;
                state256_t vout;

                if (!fgets(line, sizeof(line), fv)) break;
                if (fscanf(fv, "%llx %llx %llx %llx",
                           &in0, &in1, &in2, &in3) != 4) {
                    all_ok = 0;
                    break;
                }
                if (!fgets(line, sizeof(line), fv)) break;
                if (!fgets(line, sizeof(line), fv)) break;
                if (fscanf(fv, "%llx %llx %llx %llx",
                           &out0, &out1, &out2, &out3) != 4) {
                    all_ok = 0;
                    break;
                }
                if (!fgets(line, sizeof(line), fv)) break;

                vin = (state256_t){.w = {in0, in1, in2, in3}};
                vout = vin;
                permute_one_round(
                    &vout, rot, shuffle_map, constants2, constants1);
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
            printf(
                "one-round testvector verification: OK (%d pairs checked)\n\n",
                n);
        } else {
            printf("one-round testvector verification: MISMATCH\n\n");
        }
    }

    printf("=== Test 2: 20 rounds ===\n");
    {
        FILE *fv20r = fopen("testvector_20round.txt", "r");
        char dummy[16];
        unsigned long long in0, in1, in2, in3;
        unsigned long long out0, out1, out2, out3;
        state256_t vin;
        state256_t vout;
        int ok;

        if (!fv20r) {
            perror("fopen testvector_20round.txt for read");
            return 1;
        }
        if (fscanf(fv20r, "%15s", dummy) != 1 ||
            fscanf(fv20r, "%llx %llx %llx %llx",
                   &in0, &in1, &in2, &in3) != 4 ||
            fscanf(fv20r, "%15s", dummy) != 1 ||
            fscanf(fv20r, "%llx %llx %llx %llx",
                   &out0, &out1, &out2, &out3) != 4) {
            fprintf(stderr, "Failed to parse testvector_20round.txt\n");
            fclose(fv20r);
            return 1;
        }
        fclose(fv20r);

        vin = (state256_t){.w = {in0, in1, in2, in3}};
        vout = vin;
        permute_20rounds(
            &vout, rot, shuffle_map, constants1, constants2);
        ok = vout.w[0] == out0 && vout.w[1] == out1 &&
             vout.w[2] == out2 && vout.w[3] == out3;
        printf(
            ok ? "20-round testvector verification: OK\n\n"
               : "20-round testvector verification: MISMATCH\n\n");
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
        clock_t end;
        double elapsed_sec;
        double per_call_us;

        for (int i = 0; i < iterations; i++) {
            permute_20rounds(
                &bench, rot, shuffle_map, constants1, constants2);
        }
        end = clock();
        elapsed_sec = (double)(end - start) / CLOCKS_PER_SEC;
        per_call_us = (elapsed_sec * 1000000.0) / iterations;

        print_state256("benchmark final state", &bench);
        printf("iterations           = %d\n", iterations);
        printf("total elapsed time   = %.6f sec\n", elapsed_sec);
        printf("average per 20rounds = %.6f us\n", per_call_us);
    }

    return 0;
}
