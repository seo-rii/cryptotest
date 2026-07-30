#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    uint64_t w[4];
} state256_t;

/* Supplied by a contest.c object compiled with main renamed. */
void permute_one_round(state256_t *state,
                       const unsigned int rotations[4],
                       const uint8_t shuffle_map[32],
                       const uint64_t constants2[4],
                       const uint64_t constants1[4]);
void permute_20rounds(state256_t *state,
                      const unsigned int rotations[4],
                      const uint8_t shuffle_map[32],
                      const uint64_t constants1[4],
                      const uint64_t constants2[4]);

int main(int argc, char **argv) {
    static const unsigned int rotations[4] = {43U, 7U, 29U, 14U};
    uint8_t shuffle_map[32];
    uint64_t generator = UINT64_C(0x243f6a8885a308d3);
    uint64_t case_count = UINT64_C(100000);
    uint64_t index;
    int byte_index;

    if (argc > 2) {
        fprintf(stderr, "usage: %s [random-cases]\n", argv[0]);
        return 2;
    }
    if (argc == 2) {
        char *end = NULL;
        errno = 0;
        case_count = strtoull(argv[1], &end, 10);
        if (errno != 0 || end == argv[1] || *end != '\0' || case_count == 0U) {
            fprintf(stderr, "invalid positive random-case count: %s\n", argv[1]);
            return 2;
        }
    }

    for (byte_index = 0; byte_index < 32; ++byte_index) {
        shuffle_map[byte_index] = (uint8_t)(31 - byte_index);
    }

    for (index = 0; index < case_count; ++index) {
        state256_t actual;
        state256_t expected;
        state256_t input;
        uint64_t constants1[4];
        uint64_t constants2[4];
        int word;

        for (word = 0; word < 4; ++word) {
            uint64_t *destinations[3] = {
                &actual.w[word], &constants1[word], &constants2[word]};
            int destination;
            for (destination = 0; destination < 3; ++destination) {
                uint64_t value =
                    (generator += UINT64_C(0x9e3779b97f4a7c15));
                value = (value ^ (value >> 30)) *
                        UINT64_C(0xbf58476d1ce4e5b9);
                value = (value ^ (value >> 27)) *
                        UINT64_C(0x94d049bb133111eb);
                *destinations[destination] = value ^ (value >> 31);
            }
        }
        input = actual;
        {
            int round_count_index;
            for (round_count_index = 0; round_count_index < 2;
                 ++round_count_index) {
                const int rounds = round_count_index == 0 ? 1 : 20;
                int round;
                actual = input;
                expected = input;
                for (round = 0; round < rounds; ++round) {
                    const uint64_t y0 =
                        __builtin_bswap64(
                            ((expected.w[3] << rotations[3]) |
                             (expected.w[3] >> (64U - rotations[3]))) ^
                            constants2[3]) +
                        constants1[0];
                    const uint64_t y1 =
                        __builtin_bswap64(
                            ((expected.w[2] << rotations[2]) |
                             (expected.w[2] >> (64U - rotations[2]))) ^
                            constants2[2]) +
                        constants1[1];
                    const uint64_t y2 =
                        __builtin_bswap64(
                            ((expected.w[1] << rotations[1]) |
                             (expected.w[1] >> (64U - rotations[1]))) ^
                            constants2[1]) +
                        constants1[2];
                    const uint64_t y3 =
                        __builtin_bswap64(
                            ((expected.w[0] << rotations[0]) |
                             (expected.w[0] >> (64U - rotations[0]))) ^
                            constants2[0]) +
                        constants1[3];
                    expected.w[0] = y0;
                    expected.w[1] = y1;
                    expected.w[2] = y2;
                    expected.w[3] = y3;
                }
                if (rounds == 1) {
                    permute_one_round(
                        &actual, rotations, shuffle_map, constants2, constants1);
                } else {
                    permute_20rounds(
                        &actual, rotations, shuffle_map, constants1, constants2);
                }

                for (word = 0; word < 4; ++word) {
                    if (actual.w[word] != expected.w[word]) {
                        fprintf(stderr,
                                "candidate mismatch at case=%" PRIu64
                                " rounds=%d word=%d expected=%016" PRIx64
                                " actual=%016" PRIx64 "\n",
                                index,
                                rounds,
                                word,
                                expected.w[word],
                                actual.w[word]);
                        return 1;
                    }
                }
            }
        }
    }

    printf("candidate_random_differential_cases=%" PRIu64 "\n", case_count);
    printf("candidate_random_seed=0x%016" PRIx64 "\n",
           UINT64_C(0x243f6a8885a308d3));
    printf("candidate_random_state_and_constants=PASS\n");
    printf("candidate_round_counts=1,20\n");
    printf("candidate_differential=PASS\n");
    return 0;
}
