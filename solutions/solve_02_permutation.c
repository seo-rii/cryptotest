#define _POSIX_C_SOURCE 200809L

#include <errno.h>
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

#if defined(__GNUC__) || defined(__clang__)
#define NOINLINE __attribute__((noinline))
#else
#define NOINLINE
#endif

static inline uint64_t rotl64(uint64_t value, unsigned int amount) {
    amount &= 63U;
    return amount == 0U ? value : (value << amount) | (value >> (64U - amount));
}

static inline uint64_t bswap64_portable(uint64_t value) {
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

/* Straightforward restoration of the four operations from contest.c. */
static inline void reference_one_round(state256_t *state,
                                       const unsigned int rotations[4],
                                       const uint8_t shuffle_map[32],
                                       const uint64_t constants2[4],
                                       const uint64_t constants1[4]) {
    uint8_t input[32];
    uint8_t output[32];
    int i;

    for (i = 0; i < 4; ++i) {
        state->w[i] = rotl64(state->w[i], rotations[i]);
    }
    for (i = 0; i < 4; ++i) {
        state->w[i] ^= constants2[i];
    }
    memcpy(input, state, sizeof(input));
    for (i = 0; i < 32; ++i) {
        output[i] = input[shuffle_map[i] & 31U];
    }
    memcpy(state, output, sizeof(output));
    for (i = 0; i < 4; ++i) {
        state->w[i] += constants1[i];
    }
}

NOINLINE static void reference_20_rounds(state256_t *state,
                                         const unsigned int rotations[4],
                                         const uint8_t shuffle_map[32],
                                         const uint64_t constants2[4],
                                         const uint64_t constants1[4]) {
    int round;
    for (round = 0; round < 20; ++round) {
        reference_one_round(state, rotations, shuffle_map, constants2, constants1);
    }
}

/*
 * A 32-byte reversal is exactly word reversal plus a byte swap in every word:
 *   out = {bswap(in[3]), bswap(in[2]), bswap(in[1]), bswap(in[0])}.
 * Keeping the four words in locals also removes round-by-round temporary arrays.
 */
static inline void optimized_round_registers(uint64_t *x0,
                                             uint64_t *x1,
                                             uint64_t *x2,
                                             uint64_t *x3) {
    const uint64_t y0 = bswap64_portable(rotl64(*x3, 14U) ^ CONSTANTS2[3]) + CONSTANTS1[0];
    const uint64_t y1 = bswap64_portable(rotl64(*x2, 29U) ^ CONSTANTS2[2]) + CONSTANTS1[1];
    const uint64_t y2 = bswap64_portable(rotl64(*x1, 7U) ^ CONSTANTS2[1]) + CONSTANTS1[2];
    const uint64_t y3 = bswap64_portable(rotl64(*x0, 43U) ^ CONSTANTS2[0]) + CONSTANTS1[3];
    *x0 = y0;
    *x1 = y1;
    *x2 = y2;
    *x3 = y3;
}

static inline void optimized_one_round(state256_t *state) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    optimized_round_registers(&x0, &x1, &x2, &x3);
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

#if defined(__GNUC__) && !defined(__clang__)
#define OPTIMIZED20_ATTRIBUTE                                                 \
    __attribute__((noinline, noclone, target("bmi2"),                       \
                   optimize("no-tree-vectorize"), aligned(64)))
#elif defined(__GNUC__) || defined(__clang__)
#define OPTIMIZED20_ATTRIBUTE __attribute__((noinline, target("bmi2"), aligned(64)))
#else
#define OPTIMIZED20_ATTRIBUTE NOINLINE
#endif

#define APPLY_TWO_OPTIMIZED_ROUNDS()                                          \
    do {                                                                      \
        x0 = bswap64_portable(                                                \
                 rotl64(bswap64_portable(rotl64(x0, 43U) ^ CONSTANTS2[0]) +  \
                            CONSTANTS1[3],                                    \
                        14U) ^                                                \
                 CONSTANTS2[3]) +                                            \
             CONSTANTS1[0];                                                   \
        x1 = bswap64_portable(                                                \
                 rotl64(bswap64_portable(rotl64(x1, 7U) ^ CONSTANTS2[1]) +   \
                            CONSTANTS1[2],                                    \
                        29U) ^                                                \
                 CONSTANTS2[2]) +                                            \
             CONSTANTS1[1];                                                   \
        x2 = bswap64_portable(                                                \
                 rotl64(bswap64_portable(rotl64(x2, 29U) ^ CONSTANTS2[2]) +  \
                            CONSTANTS1[1],                                    \
                        7U) ^                                                 \
                 CONSTANTS2[1]) +                                            \
             CONSTANTS1[2];                                                   \
        x3 = bswap64_portable(                                                \
                 rotl64(bswap64_portable(rotl64(x3, 14U) ^ CONSTANTS2[3]) +  \
                            CONSTANTS1[0],                                    \
                        43U) ^                                                \
                 CONSTANTS2[0]) +                                            \
             CONSTANTS1[3];                                                   \
    } while (0)

OPTIMIZED20_ATTRIBUTE static void optimized_20_rounds(state256_t *state) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];

    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    APPLY_TWO_OPTIMIZED_ROUNDS();
    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

#undef APPLY_TWO_OPTIMIZED_ROUNDS
#undef OPTIMIZED20_ATTRIBUTE

static int states_equal(const state256_t *left, const state256_t *right) {
    return left->w[0] == right->w[0] && left->w[1] == right->w[1] &&
           left->w[2] == right->w[2] && left->w[3] == right->w[3];
}

static int read_state(FILE *stream, state256_t *state) {
    return fscanf(stream,
                  "%" SCNx64 " %" SCNx64 " %" SCNx64 " %" SCNx64,
                  &state->w[0], &state->w[1], &state->w[2], &state->w[3]) == 4;
}

static int verify_one_round_file(const char *path, size_t *checked) {
    FILE *stream = fopen(path, "r");
    unsigned int vector_number;
    char label[16];
    int status = 1;

    if (stream == NULL) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        return 0;
    }
    *checked = 0U;
    while (fscanf(stream, " #%u", &vector_number) == 1) {
        state256_t input;
        state256_t expected;
        state256_t reference;
        state256_t optimized;

        if (fscanf(stream, "%15s", label) != 1 || strcmp(label, "input") != 0 ||
            !read_state(stream, &input) || fscanf(stream, "%15s", label) != 1 ||
            strcmp(label, "output") != 0 || !read_state(stream, &expected)) {
            fprintf(stderr, "malformed one-round vector near #%u\n", vector_number);
            status = 0;
            break;
        }
        reference = input;
        optimized = input;
        reference_one_round(&reference, ROTATIONS, REVERSE_BYTES, CONSTANTS2, CONSTANTS1);
        optimized_one_round(&optimized);
        if (!states_equal(&reference, &expected) || !states_equal(&optimized, &expected)) {
            fprintf(stderr, "one-round mismatch at vector #%u\n", vector_number);
            status = 0;
            break;
        }
        ++*checked;
    }
    if (ferror(stream)) {
        fprintf(stderr, "error reading %s\n", path);
        status = 0;
    }
    fclose(stream);
    return status && *checked != 0U;
}

static int verify_twenty_round_file(const char *path) {
    FILE *stream = fopen(path, "r");
    char label[16];
    state256_t input;
    state256_t expected;
    state256_t reference;
    state256_t optimized;
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
        fprintf(stderr, "malformed 20-round vector file: %s\n", path);
        return 0;
    }

    reference = input;
    optimized = input;
    reference_20_rounds(&reference, ROTATIONS, REVERSE_BYTES, CONSTANTS2, CONSTANTS1);
    optimized_20_rounds(&optimized);
    if (!states_equal(&reference, &expected) || !states_equal(&optimized, &expected)) {
        fprintf(stderr, "20-round vector mismatch\n");
        return 0;
    }
    return 1;
}

static uint64_t xorshift64(uint64_t *state) {
    uint64_t value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    return value;
}

static int differential_test(size_t cases) {
    uint64_t seed = UINT64_C(0x6a09e667f3bcc909);
    size_t index;

    for (index = 0; index < cases; ++index) {
        state256_t input = {{
            xorshift64(&seed), xorshift64(&seed),
            xorshift64(&seed), xorshift64(&seed),
        }};
        state256_t reference = input;
        state256_t optimized = input;
        reference_one_round(&reference, ROTATIONS, REVERSE_BYTES, CONSTANTS2, CONSTANTS1);
        optimized_one_round(&optimized);
        if (!states_equal(&reference, &optimized)) {
            fprintf(stderr, "random one-round mismatch at case %zu\n", index);
            return 0;
        }
        reference = input;
        optimized = input;
        reference_20_rounds(&reference, ROTATIONS, REVERSE_BYTES, CONSTANTS2, CONSTANTS1);
        optimized_20_rounds(&optimized);
        if (!states_equal(&reference, &optimized)) {
            fprintf(stderr, "random 20-round mismatch at case %zu\n", index);
            return 0;
        }
    }
    return 1;
}

static double monotonic_seconds(void) {
    struct timespec timestamp;
    if (clock_gettime(CLOCK_MONOTONIC, &timestamp) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (double)timestamp.tv_sec + (double)timestamp.tv_nsec * 1.0e-9;
}

static volatile uint64_t benchmark_sink;

static double benchmark_reference(uint64_t iterations, uint64_t salt) {
    state256_t state = {{
        UINT64_C(0x0123456789abcdef) ^ salt,
        UINT64_C(0xfedcba9876543210),
        UINT64_C(0x0f1e2d3c4b5a6978),
        UINT64_C(0x8877665544332211),
    }};
    uint64_t index;
    const double start = monotonic_seconds();
    for (index = 0; index < iterations; ++index) {
        reference_20_rounds(&state, ROTATIONS, REVERSE_BYTES, CONSTANTS2, CONSTANTS1);
    }
    benchmark_sink += state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3];
    return monotonic_seconds() - start;
}

static double benchmark_optimized(uint64_t iterations, uint64_t salt) {
    state256_t state = {{
        UINT64_C(0x0123456789abcdef) ^ salt,
        UINT64_C(0xfedcba9876543210),
        UINT64_C(0x0f1e2d3c4b5a6978),
        UINT64_C(0x8877665544332211),
    }};
    uint64_t index;
    const double start = monotonic_seconds();
    for (index = 0; index < iterations; ++index) {
        optimized_20_rounds(&state);
    }
    benchmark_sink += state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3];
    return monotonic_seconds() - start;
}

static int compare_double(const void *left, const void *right) {
    const double a = *(const double *)left;
    const double b = *(const double *)right;
    return (a > b) - (a < b);
}

static int run_benchmark(uint64_t iterations, size_t repeats) {
    double *reference = calloc(repeats, sizeof(*reference));
    double *optimized = calloc(repeats, sizeof(*optimized));
    size_t sample;

    if (iterations == 0U || repeats == 0U || reference == NULL || optimized == NULL) {
        fprintf(stderr, "invalid benchmark parameters or allocation failure\n");
        free(reference);
        free(optimized);
        return 0;
    }

    (void)benchmark_reference(iterations / 20U + 1U, 0U);
    (void)benchmark_optimized(iterations / 20U + 1U, 0U);
    for (sample = 0; sample < repeats; ++sample) {
        const uint64_t salt = UINT64_C(0x9e3779b97f4a7c15) * (sample + 1U);
        if ((sample & 1U) == 0U) {
            reference[sample] = benchmark_reference(iterations, salt);
            optimized[sample] = benchmark_optimized(iterations, salt);
        } else {
            optimized[sample] = benchmark_optimized(iterations, salt);
            reference[sample] = benchmark_reference(iterations, salt);
        }
        printf("sample=%zu reference_ns=%.3f optimized_ns=%.3f speedup=%.3f\n",
               sample + 1U,
               reference[sample] * 1.0e9 / (double)iterations,
               optimized[sample] * 1.0e9 / (double)iterations,
               reference[sample] / optimized[sample]);
    }
    qsort(reference, repeats, sizeof(*reference), compare_double);
    qsort(optimized, repeats, sizeof(*optimized), compare_double);
    printf("benchmark iterations=%" PRIu64 " repeats=%zu\n", iterations, repeats);
    printf("median_reference_ns=%.3f\n", reference[repeats / 2U] * 1.0e9 / (double)iterations);
    printf("median_optimized_ns=%.3f\n", optimized[repeats / 2U] * 1.0e9 / (double)iterations);
    printf("median_speedup=%.3f\n", reference[repeats / 2U] / optimized[repeats / 2U]);
    printf("benchmark_sink=%016" PRIx64 "\n", benchmark_sink);
    free(reference);
    free(optimized);
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
            "  %s --selftest TESTVECTOR TESTVECTOR_20ROUND [RANDOM_CASES]\n"
            "  %s --benchmark ITERATIONS REPEATS\n",
            program, program);
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "--selftest") == 0) {
        const size_t random_cases = argc >= 5 ? (size_t)parse_u64(argv[4], "random cases") : 10000U;
        size_t vectors = 0U;
        int ok;
        if (argc < 4 || argc > 5) {
            usage(argv[0]);
            return EXIT_FAILURE;
        }
        ok = verify_one_round_file(argv[2], &vectors) &&
             verify_twenty_round_file(argv[3]) &&
             differential_test(random_cases);
        printf("one_round_vectors=%zu\n", vectors);
        printf("twenty_round_vector=%s\n", ok ? "PASS" : "FAIL");
        printf("random_differential_cases=%zu\n", random_cases);
        printf("selftest=%s\n", ok ? "PASS" : "FAIL");
        return ok ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    if (argc == 4 && strcmp(argv[1], "--benchmark") == 0) {
        const uint64_t iterations = parse_u64(argv[2], "iterations");
        const size_t repeats = (size_t)parse_u64(argv[3], "repeats");
        return run_benchmark(iterations, repeats) ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    usage(argv[0]);
    return EXIT_FAILURE;
}
