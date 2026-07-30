#define _GNU_SOURCE

/*
 * Same-process timing control for challenge 2.
 *
 * The two complete contest sources are included under disjoint symbol names so
 * GCC can inline their 20-round implementations into two otherwise identical
 * runners. Each runner is page aligned.
 */

#define state256_t scalar_state256_t
#define rotl64 scalar_rotl64
#define print_state256 scalar_print_state256
#define rotate_words_left_64wise scalar_rotate_words_left_64wise
#define xor_constants_256wise scalar_xor_constants_256wise
#define shuffle_bytes_256 scalar_shuffle_bytes_256
#define add_constants_64wise scalar_add_constants_64wise
#define bswap64_portable scalar_bswap64_portable
#define transform_word scalar_transform_word
#define permute_20rounds_unrolled scalar_permute_20rounds_unrolled
#define permute_one_round scalar_permute_one_round
#define permute_20rounds scalar_permute_20rounds
#define main scalar_contest_main
#include "../../submissions/02/contest.c"
#undef main
#undef permute_20rounds
#undef permute_one_round
#undef permute_20rounds_unrolled
#undef transform_word
#undef bswap64_portable
#undef add_constants_64wise
#undef shuffle_bytes_256
#undef xor_constants_256wise
#undef rotate_words_left_64wise
#undef print_state256
#undef rotl64
#undef state256_t

#define CH2_SIMD_INLINE
#define state256_t avx2_state256_t
#define rotl64 avx2_rotl64
#define print_state256 avx2_print_state256
#define rotate_words_left_64wise avx2_rotate_words_left_64wise
#define xor_constants_256wise avx2_xor_constants_256wise
#define shuffle_bytes_256 avx2_shuffle_bytes_256
#define add_constants_64wise avx2_add_constants_64wise
#define bswap64_portable avx2_bswap64_portable
#define transform_word avx2_transform_word
#define keep_in_vector_register avx2_keep_in_vector_register
#define rotl64_lanes_avx2 avx2_rotl64_lanes_avx2
#define permute_20rounds_unrolled avx2_permute_20rounds_unrolled
#define permute_one_round avx2_permute_one_round
#define permute_20rounds avx2_permute_20rounds
#define main avx2_contest_main
#include "contest_simd_avx2_lanewise.c"
#undef main
#undef permute_20rounds
#undef permute_one_round
#undef permute_20rounds_unrolled
#undef rotl64_lanes_avx2
#undef keep_in_vector_register
#undef transform_word
#undef bswap64_portable
#undef add_constants_64wise
#undef shuffle_bytes_256
#undef xor_constants_256wise
#undef rotate_words_left_64wise
#undef print_state256
#undef rotl64
#undef state256_t
#undef CH2_SIMD_INLINE

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <sched.h>
#include <stddef.h>
#include <sys/resource.h>
#include <unistd.h>
#include <x86intrin.h>

static const unsigned int benchmark_rot[4] = {43U, 7U, 29U, 14U};
static const uint8_t benchmark_shuffle[32] = {
    31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16,
    15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
};
static const uint64_t benchmark_add[4] = {
    UINT64_C(0x8f4a2c1e9b7d3f61), UINT64_C(0x3c6e9a1d5b7f2840),
    UINT64_C(0xa7e2d9c4b1f60853), UINT64_C(0x5d0f3a8e2c6b4197),
};
static const uint64_t benchmark_xor[4] = {
    UINT64_C(0xe7b92d4a6c1f8035), UINT64_C(0x1a4f8c3e9d2b6074),
    UINT64_C(0xc3f05a2e8d6194b7), UINT64_C(0x6b2e9d1a4f7c3085),
};

static volatile uint64_t benchmark_sink;

#define RUNNER_ATTRIBUTES                                                    \
    __attribute__((noinline, noclone, used, externally_visible, aligned(4096)))

RUNNER_ATTRIBUTES uint64_t run_scalar_block(uint64_t iterations) {
    scalar_state256_t state = {{
        UINT64_C(0x0123456789abcdef), UINT64_C(0xfedcba9876543210),
        UINT64_C(0x0f1e2d3c4b5a6978), UINT64_C(0x8877665544332211),
    }};
    for (uint64_t i = 0; i < iterations; ++i) {
        scalar_permute_20rounds(&state, benchmark_rot, benchmark_shuffle,
                                benchmark_add, benchmark_xor);
    }
    const uint64_t checksum =
        state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3];
    benchmark_sink ^= checksum;
    return checksum;
}

RUNNER_ATTRIBUTES uint64_t run_avx2_block(uint64_t iterations) {
    avx2_state256_t state = {{
        UINT64_C(0x0123456789abcdef), UINT64_C(0xfedcba9876543210),
        UINT64_C(0x0f1e2d3c4b5a6978), UINT64_C(0x8877665544332211),
    }};
    for (uint64_t i = 0; i < iterations; ++i) {
        avx2_permute_20rounds(&state, benchmark_rot, benchmark_shuffle,
                              benchmark_add, benchmark_xor);
    }
    const uint64_t checksum =
        state.w[0] ^ state.w[1] ^ state.w[2] ^ state.w[3];
    benchmark_sink ^= checksum;
    return checksum;
}

#undef RUNNER_ATTRIBUTES

typedef struct {
    uint64_t raw_ns;
    uint64_t thread_ns;
    uint64_t tsc_cycles;
    uint64_t checksum;
    unsigned int aux_start;
    unsigned int aux_end;
    int cpu_start;
    int cpu_end;
    long voluntary_context_switches;
    long involuntary_context_switches;
} measurement_t;

typedef struct {
    uint64_t total;
    uint64_t busy;
    int valid;
} cpu_stat_t;

static void fail(const char *what) {
    perror(what);
    exit(EXIT_FAILURE);
}

static uint64_t timespec_ns(const struct timespec *value) {
    return (uint64_t)value->tv_sec * UINT64_C(1000000000) +
           (uint64_t)value->tv_nsec;
}

static uint64_t serialized_rdtscp(unsigned int *aux) {
    _mm_lfence();
    const uint64_t value = __rdtscp(aux);
    _mm_lfence();
    return value;
}

static measurement_t measure(uint64_t (*runner)(uint64_t),
                             uint64_t iterations) {
    struct timespec raw_start;
    struct timespec raw_end;
    struct timespec thread_start;
    struct timespec thread_end;
    struct rusage usage_start;
    struct rusage usage_end;
    measurement_t result = {0};

    if (getrusage(RUSAGE_SELF, &usage_start) != 0) fail("getrusage start");
    result.cpu_start = sched_getcpu();
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &raw_start) != 0)
        fail("clock_gettime raw start");
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &thread_start) != 0)
        fail("clock_gettime thread start");
    const uint64_t tsc_start = serialized_rdtscp(&result.aux_start);

    result.checksum = runner(iterations);

    const uint64_t tsc_end = serialized_rdtscp(&result.aux_end);
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &thread_end) != 0)
        fail("clock_gettime thread end");
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &raw_end) != 0)
        fail("clock_gettime raw end");
    result.cpu_end = sched_getcpu();
    if (getrusage(RUSAGE_SELF, &usage_end) != 0) fail("getrusage end");

    result.raw_ns = timespec_ns(&raw_end) - timespec_ns(&raw_start);
    result.thread_ns = timespec_ns(&thread_end) - timespec_ns(&thread_start);
    result.tsc_cycles = tsc_end - tsc_start;
    result.voluntary_context_switches =
        usage_end.ru_nvcsw - usage_start.ru_nvcsw;
    result.involuntary_context_switches =
        usage_end.ru_nivcsw - usage_start.ru_nivcsw;
    return result;
}

static cpu_stat_t read_cpu_stat(int cpu) {
    cpu_stat_t result = {0, 0, 0};
    FILE *input = fopen("/proc/stat", "r");
    if (input == NULL) return result;

    char line[512];
    char target[32];
    if (snprintf(target, sizeof(target), "cpu%d ", cpu) < 0) {
        fclose(input);
        return result;
    }
    while (fgets(line, sizeof(line), input) != NULL) {
        if (strncmp(line, target, strlen(target)) != 0) continue;
        uint64_t fields[10] = {0};
        const int count = sscanf(
            line + strlen(target),
            "%" SCNu64 " %" SCNu64 " %" SCNu64 " %" SCNu64
            " %" SCNu64 " %" SCNu64 " %" SCNu64 " %" SCNu64
            " %" SCNu64 " %" SCNu64,
            &fields[0], &fields[1], &fields[2], &fields[3], &fields[4],
            &fields[5], &fields[6], &fields[7], &fields[8], &fields[9]);
        if (count < 8) break;
        for (int i = 0; i < count; ++i) result.total += fields[i];
        /* guest and guest_nice are already included in user and nice. */
        if (count > 8) result.total -= fields[8];
        if (count > 9) result.total -= fields[9];
        result.busy = result.total - fields[3] - fields[4];
        result.valid = 1;
        break;
    }
    fclose(input);
    return result;
}

static void emit_measurement(unsigned int sample, const char *order,
                             const char *candidate,
                             const measurement_t *measurement,
                             const cpu_stat_t *selected_before,
                             const cpu_stat_t *selected_after,
                             const cpu_stat_t *sibling_before,
                             const cpu_stat_t *sibling_after) {
    printf(
        "{\"type\":\"measurement\",\"sample\":%u,\"order\":\"%s\","
        "\"candidate\":\"%s\",\"raw_ns\":%" PRIu64
        ",\"thread_ns\":%" PRIu64 ",\"tsc_cycles\":%" PRIu64
        ",\"checksum\":\"%016" PRIx64 "\",\"aux_start\":%u,"
        "\"aux_end\":%u,\"cpu_start\":%d,\"cpu_end\":%d,"
        "\"voluntary_context_switches\":%ld,"
        "\"involuntary_context_switches\":%ld,"
        "\"selected_total_delta\":%" PRIu64
        ",\"selected_busy_delta\":%" PRIu64
        ",\"sibling_total_delta\":%" PRIu64
        ",\"sibling_busy_delta\":%" PRIu64 "}\n",
        sample, order, candidate, measurement->raw_ns, measurement->thread_ns,
        measurement->tsc_cycles, measurement->checksum, measurement->aux_start,
        measurement->aux_end, measurement->cpu_start, measurement->cpu_end,
        measurement->voluntary_context_switches,
        measurement->involuntary_context_switches,
        selected_after->total - selected_before->total,
        selected_after->busy - selected_before->busy,
        sibling_after->total - sibling_before->total,
        sibling_after->busy - sibling_before->busy);
}

static uint64_t parse_u64(const char *text, const char *name) {
    char *end = NULL;
    errno = 0;
    const unsigned long long value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value == 0) {
        fprintf(stderr, "invalid %s: %s\n", name, text);
        exit(EXIT_FAILURE);
    }
    return (uint64_t)value;
}

static int parse_cpu(const char *text, const char *name) {
    char *end = NULL;
    errno = 0;
    const long value = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value < 0 ||
        value > INT_MAX) {
        fprintf(stderr, "invalid %s: %s\n", name, text);
        exit(EXIT_FAILURE);
    }
    return (int)value;
}

int main(int argc, char **argv) {
    if (argc != 6) {
        fprintf(stderr,
                "usage: %s CPU SIBLING ITERATIONS WARMUPS SAMPLES\n", argv[0]);
        return EXIT_FAILURE;
    }
    const int selected_cpu = parse_cpu(argv[1], "CPU");
    const int sibling_cpu = parse_cpu(argv[2], "SIBLING");
    const uint64_t iterations = parse_u64(argv[3], "ITERATIONS");
    const uint64_t warmups = parse_u64(argv[4], "WARMUPS");
    const uint64_t samples = parse_u64(argv[5], "SAMPLES");

    cpu_set_t affinity;
    CPU_ZERO(&affinity);
    CPU_SET(selected_cpu, &affinity);
    if (sched_setaffinity(0, sizeof(affinity), &affinity) != 0)
        fail("sched_setaffinity");
    if (sched_getcpu() != selected_cpu) {
        fprintf(stderr, "affinity migration did not settle on CPU %d\n", selected_cpu);
        return EXIT_FAILURE;
    }

    printf("{\"type\":\"meta\",\"cpu\":%d,\"sibling\":%d,"
           "\"iterations\":%" PRIu64 ",\"warmups\":%" PRIu64
           ",\"samples\":%" PRIu64 "}\n",
           selected_cpu, sibling_cpu, iterations, warmups, samples);

    for (uint64_t warmup = 0; warmup < warmups; ++warmup) {
        measurement_t scalar;
        measurement_t avx2;
        if ((warmup & 1U) == 0) {
            scalar = measure(run_scalar_block, iterations);
            avx2 = measure(run_avx2_block, iterations);
        } else {
            avx2 = measure(run_avx2_block, iterations);
            scalar = measure(run_scalar_block, iterations);
        }
        if (scalar.checksum != avx2.checksum) {
            fprintf(stderr, "warmup checksum mismatch at index %" PRIu64 "\n",
                    warmup);
            return EXIT_FAILURE;
        }
    }

    for (uint64_t sample = 0; sample < samples; ++sample) {
        const int scalar_first = (sample & 1U) == 0;
        const char *order = scalar_first ? "AB" : "BA";
        const cpu_stat_t selected_before = read_cpu_stat(selected_cpu);
        const cpu_stat_t sibling_before = read_cpu_stat(sibling_cpu);
        measurement_t scalar;
        measurement_t avx2;
        if (scalar_first) {
            scalar = measure(run_scalar_block, iterations);
            avx2 = measure(run_avx2_block, iterations);
        } else {
            avx2 = measure(run_avx2_block, iterations);
            scalar = measure(run_scalar_block, iterations);
        }
        const cpu_stat_t selected_after = read_cpu_stat(selected_cpu);
        const cpu_stat_t sibling_after = read_cpu_stat(sibling_cpu);
        if (!selected_before.valid || !selected_after.valid ||
            !sibling_before.valid || !sibling_after.valid) {
            fprintf(stderr, "could not read per-CPU /proc/stat counters\n");
            return EXIT_FAILURE;
        }
        if (scalar.checksum != avx2.checksum) {
            fprintf(stderr, "sample checksum mismatch at index %" PRIu64 "\n",
                    sample);
            return EXIT_FAILURE;
        }
        emit_measurement((unsigned int)sample, order, "scalar", &scalar,
                         &selected_before, &selected_after, &sibling_before,
                         &sibling_after);
        emit_measurement((unsigned int)sample, order, "avx2", &avx2,
                         &selected_before, &selected_after, &sibling_before,
                         &sibling_after);
        fflush(stdout);
    }
    fprintf(stderr, "benchmark_sink=%016" PRIx64 "\n", benchmark_sink);
    return EXIT_SUCCESS;
}
