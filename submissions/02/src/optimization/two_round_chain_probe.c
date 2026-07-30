#include <stdint.h>

#if defined(__GNUC__) && !defined(__clang__)
#define PROBE_NOINLINE __attribute__((noinline, noclone, used))
#elif defined(__GNUC__) || defined(__clang__)
#define PROBE_NOINLINE __attribute__((noinline, used))
#else
#define PROBE_NOINLINE
#endif

static inline uint64_t rol64(uint64_t value, unsigned int amount) {
    return (value << amount) | (value >> (64U - amount));
}

static inline uint64_t swap64(uint64_t value) {
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

/* The exact x0 two-round dependency chain, with all constants kept dynamic. */
PROBE_NOINLINE uint64_t chain_baseline(uint64_t value,
                                       uint64_t first_xor,
                                       uint64_t first_add,
                                       uint64_t second_xor,
                                       uint64_t second_add) {
    value = swap64(rol64(value, 43U) ^ first_xor) + first_add;
    return swap64(rol64(value, 14U) ^ second_xor) + second_add;
}

/* Exact identity with each XOR constant moved through BSWAP. */
PROBE_NOINLINE uint64_t chain_post_bswap(uint64_t value,
                                         uint64_t first_swapped_xor,
                                         uint64_t first_add,
                                         uint64_t second_swapped_xor,
                                         uint64_t second_add) {
    value = (swap64(rol64(value, 43U)) ^ first_swapped_xor) + first_add;
    return (swap64(rol64(value, 14U)) ^ second_swapped_xor) + second_add;
}

/* Exact identity with each XOR constant moved before its rotation. */
PROBE_NOINLINE uint64_t chain_pre_rotate(uint64_t value,
                                         uint64_t first_pre_rotated_xor,
                                         uint64_t first_add,
                                         uint64_t second_pre_rotated_xor,
                                         uint64_t second_add) {
    value = swap64(rol64(value ^ first_pre_rotated_xor, 43U)) + first_add;
    return swap64(rol64(value ^ second_pre_rotated_xor, 14U)) + second_add;
}

/* The same chain with the supplied constants visible as literals. */
PROBE_NOINLINE uint64_t chain_literal_x0(uint64_t value) {
    value = swap64(rol64(value, 43U) ^ UINT64_C(0xe7b92d4a6c1f8035)) +
            UINT64_C(0x5d0f3a8e2c6b4197);
    return swap64(rol64(value, 14U) ^ UINT64_C(0x6b2e9d1a4f7c3085)) +
           UINT64_C(0x8f4a2c1e9b7d3f61);
}

/* Remove the arithmetic deliberately to expose only the linear skeleton. */
PROBE_NOINLINE uint64_t chain_linear_skeleton(uint64_t value) {
    value = swap64(rol64(value, 43U));
    return swap64(rol64(value, 14U));
}

#undef PROBE_NOINLINE
