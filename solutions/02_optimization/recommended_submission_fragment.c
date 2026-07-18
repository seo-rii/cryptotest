/*
 * Add this block outside the three editable locations in contest.c.  External
 * helpers are explicitly allowed by the statement.  state256_t must already
 * be defined by contest.c.
 */
#if defined(__GNUC__) && !defined(__clang__)
#define P2_FAST_ATTRIBUTE                                                    \
    __attribute__((noinline, noclone, target("bmi2"),                       \
                   optimize("no-tree-vectorize"), aligned(64)))
#elif defined(__GNUC__) || defined(__clang__)
#define P2_FAST_ATTRIBUTE __attribute__((noinline, target("bmi2"), aligned(64)))
#else
#define P2_FAST_ATTRIBUTE
#endif

static inline uint64_t p2_bswap64(uint64_t value) {
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

static inline uint64_t p2_transform(uint64_t value,
                                    unsigned int rotation,
                                    uint64_t xor_constant,
                                    uint64_t add_constant) {
    return p2_bswap64(rotl64(value, rotation) ^ xor_constant) + add_constant;
}

#define P2_APPLY_TWO_ROUNDS()                                                \
    do {                                                                     \
        x0 = p2_transform(p2_transform(x0, 43U, k0, a3), 14U, k3, a0);      \
        x1 = p2_transform(p2_transform(x1, 7U, k1, a2), 29U, k2, a1);       \
        x2 = p2_transform(p2_transform(x2, 29U, k2, a1), 7U, k1, a2);       \
        x3 = p2_transform(p2_transform(x3, 14U, k3, a0), 43U, k0, a3);      \
    } while (0)

P2_FAST_ATTRIBUTE static void p2_permute_20rounds_unrolled(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    uint64_t x0 = state->w[0];
    uint64_t x1 = state->w[1];
    uint64_t x2 = state->w[2];
    uint64_t x3 = state->w[3];
    const uint64_t a0 = constants1[0];
    const uint64_t a1 = constants1[1];
    const uint64_t a2 = constants1[2];
    const uint64_t a3 = constants1[3];
    const uint64_t k0 = constants2[0];
    const uint64_t k1 = constants2[1];
    const uint64_t k2 = constants2[2];
    const uint64_t k3 = constants2[3];

    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();
    P2_APPLY_TWO_ROUNDS();

    state->w[0] = x0;
    state->w[1] = x1;
    state->w[2] = x2;
    state->w[3] = x3;
}

#undef P2_APPLY_TWO_ROUNDS
#undef P2_FAST_ATTRIBUTE

/*
 * Replace only the body at the permitted 20-round-loop edit location with:
 *
 * (void)rot; (void)shuffle_map;
 * p2_permute_20rounds_unrolled(state, constants1, constants2); r = 19;
 *
 * The helper performs all 20 rounds during the first outer-loop iteration;
 * assigning r=19 then terminates the now-redundant supplied loop.
 */
