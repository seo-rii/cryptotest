/*
 * The block5 target-only candidate shares the audited dataflow and harness
 * with block3+tail1; only the counted frontend selected below differs.
 */
#define CH2_TENTH_BLOCK5 1
#include "contest_simd_avx2_pair_block3_tail1.c"
