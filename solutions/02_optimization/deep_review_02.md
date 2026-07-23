# 2번 심층 최적화 재검토

## 결론

현재의 `BMI2 + 2-round + scalar full-unroll` 연산 본문은 여전히 가장 강하게
검증된 **scalar incumbent**이자 기본 권장안이다. 4-lane AVX2는 일부 AMD
affinity에서 더 빨랐지만 순위가 뒤집혔다. 최신 commutative operand-order
변형은 exact GCC 13.3 loop를 569 bytes에서 **549 bytes**로 줄였지만, 이전
569-byte stream 대비 schema-5 AMD 실측은 CPU 1/3 모두 통계적 동률이었다.
`DEC` counter의 548-byte 변형과 136-byte block-2 부분 언롤도 interval이 모두
1을 포함했다. 따라서 이 셋은 255H-only 후보이며 scalar 제출을 교체하지 않는다.
이번 재검토에서
scalar 본문을 다른 알고리즘으로 줄이지는 못했지만, 같은
source를 score용 flag로 빌드해 그 본문을 `main`의 timing loop까지
인라인하는 새 경로를 찾았다. 호출마다 반복되던 함수 진입/복귀, 상태와 상수
load/store가 사라져 AMD VM의 두 logical CPU에서 기본 build 대비 paired
median `1.116x`, `1.118x`를 얻었다. 각각의 bootstrap 95% interval도
`1.110x--1.143x`, `1.095x--1.140x`로 1보다 컸다.

source는 적응형이다. 제공 명령인 `gcc -O3`에서는 기존의 국소
`target("bmi2")` noinline helper를 그대로 사용한다. `-mbmi2`가 정의되면
helper를 `always_inline`으로 바꾸고, `-finline-limit=2000`으로 공개 wrapper도
timing loop에 합친다. 따라서 추가 flag가 받아들여지지 않는 환경의 정확성과
호환성은 보존하면서, 문제에서 허용한 최적화 flag를 사용할 때만 더 빠른
code-generation 경로를 연다.

더 작은 `unroll5_bmi2`는 과거 한 세션에서 `1.0867x`였지만 즉시 재측정과
`-march=native`에서 역전됐고, 새 인라인 build 아래에서도 full-unroll보다
약 3.5% 느렸다. 켤레관계를 이용한 SIMD, byte/word table, BSWAP--XOR 순서
교환, 수동 assembly scheduling, target clone도 반복 측정에서 이기지 못했다.

현재 권장 순서는 다음과 같다.

1. 제출 source는 적응형 full-unroll 구현을 사용한다. 기본 `gcc -O3` build도
   계속 유효하다.
2. 성능 점수용 1순위 build는
   `-mbmi2 -finline-limit=2000`으로 잡는다.
3. digest로 고정한 공식 GCC 13.3.0에서 limit `700/2000`의 complete binary
   일치와 timing loop의 call 제거를 확인했다. 255H에서 남은 일은 이 사실을
   다시 추측하는 것이 아니라 scalar source/scheduler 변형, 122-instruction
   lane-wise AVX2의 569/549/548-byte stream, block-2 loop, 그리고 재현 가능한
   stream/alignment 배치 클래스의 실제 순위를 판정하는 것이다.
4. current schema 5는 독립 reference로 timing loop 전체의 최종 상태를 계산하고
   preflight, warm-up, 모든 sample에서 iteration 수와 상태를 검증한다. schema
   2--4 결과는 이 repeated-call integrity가 없는 역사적 자료로만 취급한다.
5. one-state SIMD, partial unroll, table, 수동 재스케줄링은 target에서 두
   독립 세션 모두 유의한 차이를 보이지 않는 한 채택하지 않는다. block-2는
   frontend 민감도 대조군이지 현 제출안이 아니다.

기존 18-candidate 원시 측정값은 [deep_results_02.txt](deep_results_02.txt),
새 인라인 캠페인은 [CPU 0 결과](inline_results_02.json),
[CPU 4 결과](inline_results_02_cpu4.json), 호출 경계별 분해는
[3-stage 결과](inline_stages_results_02.json), 추가 codegen과 loop 정렬은
[codegen 결과](inline_codegen_results_02.json)와
[alignment 결과](inline_alignment_results_02.json)에 보존했다. ROL 대조군은
[inline_rol_results_02.json](inline_rol_results_02.json), 실제 loop 감사는
[inline_assembly_audit_02.json](inline_assembly_audit_02.json)에 있다. GCC 13.3
실물 재현은 [gcc133_codegen_results_02.json](gcc133_codegen_results_02.json),
상수 배치의 결정적 검사는
[constant_placement_analysis_02.json](constant_placement_analysis_02.json)에
보존했다.

## 20라운드 합성의 한계

입력 word `i`에 적용되고 출력 word `3-i`로 이동하는 변환을 다음처럼 둔다.

```text
T_i(x) = BSWAP64(ROTL64(x, r_i) xor K_i) + A_(3-i) mod 2^64
```

한 라운드 `R`은 word 순서를 뒤집지만 두 라운드 후에는 순서가 원래대로
돌아온다.

```text
R^2(x)_i = T_(3-i)(T_i(x_i))
R^20     = (R^2)^10
```

따라서 20라운드는 네 개의 독립적인 64비트 dependency chain으로 정확히
분해된다. 이것이 현재 최적화의 핵심이며, 라운드 사이의 word move가 사라지고
CPU가 네 chain을 병렬로 스케줄할 수 있다.

그 이상을 일반적인 함수 거듭제곱처럼 exponentiation-by-squaring으로 줄일 수는
없다. 각 `T_i`에 포함된 modulo 덧셈의 carry 때문에 합성 결과는 rotate/XOR/add의
작은 affine 표현으로 닫히지 않는다. 임의의 64비트 입력에 대한 합성 함수를
lookup table로 표현하려면 사실상 `2^64` mapping이 필요하다.

### 대체 상태 표현

상태를 항상 byte-swapped 형태 `z = BSWAP64(x)`로 유지하는 방법도 검토했다.
그러나 덧셈은 이 좌표계에서 다음 연산이 된다.

```text
z' = BSWAP64(BSWAP64(z) + A)
```

즉 byte swap을 없애는 대신 carry 방향이 뒤집힌 별도 덧셈과 두 번의 변환이
필요하다. rotation 값 `{43, 7, 29, 14}`도 byte 단위가 아니어서 byte-table
분해 시 인접 byte의 비트와 carry 상태가 함께 필요하다. 결과적으로 현재의
`RORX -> XOR -> BSWAP -> ADD`보다 짧은 표현을 얻지 못했다.

## 기계어와 backend 하한

GCC 12.2의 기본 `-O3`에서 full-unroll helper에 함수별 `target("bmi2")`를
적용한 결과는 다음과 같다.

- symbol 크기: 1,267 bytes (`0x4f3`)
- 함수 진입: callee-saved register push 4개
- hot body stack spill: 없음
- 상수 8개와 state word 4개를 register에 유지
- 본문: 네 개의 독립적인 `RORX/XOR/BSWAP/ADD` chain

각 word는 라운드당 네 개의 직렬 연산을 20번 거친다. 즉 chain 하나의 핵심
dependency depth는 약 80개의 단순 정수 연산이다. 측정 VM의 2.25 GHz에서
34~36 ns는 약 77~81 cycles이므로, 네 chain을 interleave한 full-unroll은
이미 이 단순 latency 모델에 근접한다. 새로운 대수적 단축이 없다면 두 자릿수
후반의 추가 개선을 기대하기 어렵고, 남은 차이는 주로 frontend, 코드 배치,
호출 경계 및 실제 Intel 명령 latency에서 나온다.

이를 확인하기 위해 네 chain을 하나씩 끝까지 계산한 `sequential_chains`를
만들었다. 코드 크기는 full-unroll과 비슷한 1,260 bytes지만 paired 성능은
`0.7305x`였다. 연산 개수가 같아도 네 chain을 명시적으로 섞어 CPU의
instruction-level parallelism을 노출하는 것이 중요하다는 증거다.

## frontend, unroll factor와 코드 크기

후보별 독립 바이너리에서 얻은 주요 symbol 크기는 다음과 같다.

| 후보 | 본문 구성 | symbol bytes |
|---|---|---:|
| pair loop | 2 rounds × 10 | 217 |
| unroll2 | 4 rounds × 5 | 356 |
| forced unroll3 | 6 rounds × 3 + 2 rounds | 618 |
| unroll5 | 10 rounds × 2 | 715 |
| forced unroll4 | 8 rounds × 2 + 4 rounds | 864 |
| full-unroll | 20 rounds | 1,267 |

full-unroll은 branch가 없고 넓은 scheduling window를 주지만 instruction/
decoded-uop footprint가 가장 크다. pair loop는 작지만 branch 횟수가 많고
compiler가 볼 수 있는 scheduling window가 짧다. 이 VM의 첫 세션에서는
unroll5가 둘 사이의 좋은 절충이었지만, host contention이 달라지자 우열도
바뀌었다.

| 세션 | flags | full baseline median | unroll5 median | paired speedup |
|---|---|---:|---:|---:|
| 전체 후보 1차 | `-O3` | 34.804 ns | 32.896 ns | **1.0867x** |
| 즉시 독립 재측정 | `-O3` | 53.939 ns | 55.559 ns | **0.9712x** |
| Intel tune 실험 | `-O3 -mtune=alderlake` | 49.155 ns | 51.487 ns | **0.9693x** |
| native 실험 | `-O3 -march=native` | 32.065 ns | 35.949 ns | **0.9214x** |

`-mtune=alderlake` 수치는 AMD에서 실행한 것이므로 Intel 성능 예측값이 아니다.
오직 compiler code-generation 경로가 정상 동작하는지 확인하기 위한 실험이다.

forced unroll3과 unroll4는 compiler가 남은 횟수까지 다시 완전히 펼치지 못하도록
register-only compiler barrier를 사용했다. 각각 15-sample paired speedup이
`0.9855x`, `0.9787x`여서 추가 후보로 남길 이유가 없었다. unroll2는 첫 세션에서
`1.0159x`로 오차 범위에 가까웠다.

## 정렬과 코드 배치

동일한 full-unroll 함수에 최소 alignment만 바꾼 결과는 다음과 같다. 값은
64-byte 기준선 대비 paired median이다.

| alignment | paired speedup | 판단 |
|---:|---:|---|
| 16 bytes | 0.9653x | 느림 |
| 32 bytes | 0.9873x | 동률 이하 |
| 64 bytes | 1.0000x | 유지 |
| 128 bytes | 0.9800x | 느림 |

큰 unroll 후보를 모두 한 실행 파일에 넣었을 때에는 함수 상대 위치만 바뀌어도
scalar 결과가 수십 퍼센트 흔들렸다. 이 때문에 최종 runner는 후보 하나만 남긴
독립 바이너리를 만들고, 후보와 기준선을 시간상 인접하게 무작위 순서로
측정한다. alignment는 최소값일 뿐 linker와 주변 함수 배치도 실제 주소에
영향을 주므로, 최종 제출 파일 전체를 빌드한 뒤 `nm`/`objdump`로 다시 확인해야
한다.

## compiler 속성, 상수와 호출 경계

### BMI2 target

`target("bmi2")`는 기본 compile command에 `-march`가 없어도 GCC가 rotate를
non-destructive `RORX`로 내리게 한다. 같은 full-unroll에서 BMI2 속성을 제거한
후보는 1,119 bytes였지만 paired 성능이 `0.9704x`였다. 따라서 추가 flag가
허용되지 않는 경로에서는 함수별 BMI2 target을 유지하는 편이 낫다.

다만 이 속성은 runtime dispatch가 아니다. 최종 CPU에서 BMI2 CPUID를 확인해야
하며, 다른 CPU로 이식하려면 portable fallback이 필요하다.

### 상수 전달과 constant propagation

상수 배열 pointer를 `restrict`로 받고 진입 시 한 번만 load하는 기준선은 hot
loop에서 재접근하지 않는다. 상수 8개를 literal로 내장한 후보는 `movabs`
encoding 때문에 1,314 bytes로 커졌고 paired 결과는 `1.0009x`였다. 따라서
constant propagation은 실질적 이득이 없었다.

### inline과 제출 wrapper

`always_inline` core를 public wrapper에 강제한 후보는 기준선과 같은 1,267-byte
본문을 만들었고 paired 결과도 `1.0051x`로 동률이었다. 이 초기 실험은 core를
public wrapper에만 합쳤고, benchmark가 호출하는 public wrapper와 `main`의
경계는 남겨 두었다. 실제 수정 제약을 모델링한 다음 형태는 기본 build에서
GCC가 5-byte tail jump로 축약했다.

```c
for (int r = 0; r < 20; ++r) {
    helper_20rounds(state, constants1, constants2);
    r = 19;
}
```

따라서 제공 loop가 19번 더 도는 비용은 없다. 측정 중 wrapper가 일부 빠르게
나온 것은 helper 배치 주소가 달라진 frontend 효과이며, tail jump 자체가
알고리즘을 개선한 것은 아니다.

GCC x86 inliner는 caller와 callee의 target option이 다르면 caller가 callee의
ISA option을 포함할 때만 inline을 허용한다. 기본 wrapper에 BMI2 helper를
`always_inline`하면 target mismatch가 생길 수 있으므로, no-flag 제출 경로는
현재처럼 noinline helper/tail-call을 유지하는 것이 안전하다.

이번 구현은 compile-time `__BMI2__`에 따라 속성을 바꾼다.

```c
#if defined(__GNUC__) && defined(__BMI2__)
#define PERMUTE20_ATTRIBUTE \
    __attribute__((always_inline, optimize("no-tree-vectorize"))) inline
#else
#define PERMUTE20_ATTRIBUTE \
    __attribute__((noinline, noclone, target("bmi2"), ...))
#endif
```

기본 명령에서는 이전 경로와 같지만, 다음 score용 build에서는 caller와
callee의 ISA option이 일치한다.

```bash
gcc -O3 -Wall -Wextra -mbmi2 -finline-limit=2000 \
  -o contest submissions/02/contest.c
```

`-mbmi2`만 주면 320-operation core가 public `permute_20rounds` 안으로 들어가도
`main`의 timing loop에는 여전히 `call permute_20rounds`가 남았다.
`-finline-limit=2000`까지 주면 public wrapper도 timing loop에 합쳐진다.
GCC 12.2에서 확인한 그 loop에는 core 밖의 `call`, `push/pop`, 상태/상수용
memory operand가 없고, 네 state word와 여덟 상수가 outer iteration 사이에도
register에 유지됐다. ABI를 위한 외부 public 함수 사본은 binary에 남지만
timing loop에서는 호출되지 않는다.

동일 source를 case별 flag만 바꿔 3,000,000회, warm-up process 3회,
21 samples로 다시 측정한 결과는 다음과 같다. 모든 process는 공식 vector를
통과했고, 각 candidate object는 timing 전에 무작위 상태와 무작위 ADD/XOR
상수 100,000건의 1/20라운드를 독립 reference와 직접 비교했다.

| affinity | 기본 중앙값 | 인라인 중앙값 | paired 중앙값 | paired MAD | bootstrap 95% CI |
|---:|---:|---:|---:|---:|---:|
| CPU 0 | 44.467 ns | 39.859 ns | **1.115553x** | 0.028078x | 1.109511--1.143275x |
| CPU 4 | 45.924 ns | 40.801 ns | **1.118038x** | 0.032230x | 1.094566--1.140443x |

세 build를 한 캠페인에서 분해한 결과도 원인을 뒷받침한다.

| build | 중앙값 | 기본 대비 paired 중앙값 | 해석 |
|---|---:|---:|---|
| 기본 | 54.411 ns | 1.000x | noinline helper 호출 |
| `-mbmi2` | 54.899 ns | 0.999x | core만 public 함수에 합침 |
| `-mbmi2 -finline-limit=2000` | 49.514 ns | **1.124x** | public 함수도 timing loop에 합침 |

이 3-case 캠페인은 paired MAD가 0.114x로 더 시끄러우므로 효과 크기의 대표값은
위 두 2-case 캠페인을 사용한다. 별도의 `-finline-limit=700` 캠페인도
43.400ns에서 37.867ns, paired `1.122x`(95% CI `1.100x--1.143x`)를 냈다.
GCC 12에서 limit 700과 2000의 실행 파일은 byte-identical했다. 이후 digest로
고정한 GCC 13.3에서도 complete binary 동일성과 1,216-byte/322-instruction,
call 0인 timing loop를 확인했으므로 release 재검증 항목은 완료됐다.

[`audit_inline_02.py`](audit_inline_02.py)는 `main`의 마지막 두 `clock()` 호출
사이에서 timing-loop backedge를 찾아 이 조건을 자동 검사한다. GCC 12의
700/2000 loop는 normalized hash까지 같았고, 1,216 bytes/322 instructions에
`RORX/XOR/BSWAP/ADD-or-LEA`가 각각 정확히 80개였다. core 밖의 call,
push/pop, LEA를 제외한 memory operand는 모두 0이다. 기본 build의 같은
위치에는 19-byte/6-instruction loop와 helper call 1개가 남는다.

호출 경계를 없앤 뒤 같은 flag로 full-unroll, pair loop, unroll5를 다시
비교했다. 중앙값은 각각 37.279ns, 38.618ns, 38.727ns였고 paired 값은
pair loop `0.974x`, unroll5 `0.965x`였다. 즉 작은 본문보다 outer iteration
전체에 걸친 register residency가 더 중요했고, score용 경로에서도
full-unroll이 최종 후보로 남았다.

## AVX2가 느린 이유

두 라운드 후의 네 word를 AVX2 lane에 놓는 구현도 정확하지만 scalar `RORX`
한 번이 하던 lane별 rotate를 다음 세 명령으로 만들어야 한다.

```text
VPSLLVQ + VPSRLVQ + VPOR
```

그 뒤 XOR, `VPSHUFB`, ADD가 이어진다. 한 vector가 네 word를 처리해도 한
state의 다음 라운드는 이전 vector 전체에 의존하므로 latency chain이 길어진다.

| AVX2 후보 | paired speedup | 결과 |
|---|---:|---|
| two-round AVX2 loop | 0.9566x | 느림 |
| two-round AVX2 unroll | 0.9076x | 더 느림 |
| direct one-round AVX2 | 0.6875x | 크게 느림 |

네 개의 서로 독립적인 state가 주어지면 state 간 batch SIMD는 throughput을
높일 수 있다. 그러나 제공 timing harness는 하나의 state 출력을 다음 호출의
입력으로 사용하므로 batch API로 바꿀 수 없다.

## 두 번째 전략 탐색

### BSWAP--XOR 교환과 상수 흡수

byte swap `B`가 XOR에 대해 선형이라는 성질을 쓰면

```text
B(ROL(x) xor K) = B(ROL(x)) xor B(K)
```

이므로 핵심 순서를 `RORX -> BSWAP -> XOR -> ADD`로 바꿀 수 있다. 또한
`H=2^63`에 대해 `z xor H = z + H (mod 2^64)`이므로, swapped XOR 상수의
최상위 bit 하나는 add 상수에 흡수할 수 있다. bit 63 이외의 bit는 carry
때문에 입력에 따라 차이가 달라져 보편적으로 흡수되지 않는다.

이 항등식은 100,000개 무작위 입력에서 reference와 일치했지만, 결국
`RORX/XOR/BSWAP/ADD` 네 instruction은 그대로다. pre-swapped 상수 후보가
서로 다른 process를 비교할 때에는 `1.095x--1.116x`로 좋아 보였지만,
동일 process에서 thread CPU time과 AB/BA 순서를 쓰고 함수 배치를 뒤집자
layout A `1.0146x`(MAD `0.0414x`), layout B `0.9943x`
(MAD `0.0175x`)가 됐다. 수동 inline-assembly 버전도 `0.9975x`였으므로
실제 개선이 아니라 code layout과 shared-host descheduling 효과로 판정했다.

### XOR/ADD 순서 교환의 저비트 완전탐색

교환한 한 transform을 `F(x)=(L(x) xor C)+A`,
`C=BSWAP(K)`로 정규화하고, XOR을 ADD 뒤로 보내 상수를 합칠 수 있는지

```text
(x xor C) + A = (x + B) xor E  (mod 2^64)
```

를 검사했다. 64비트 항등식이면 `mod 2^n`으로 사영한 식도 모든 `x`에 대해
성립해야 한다. 실제 네 `(C,A)`는 각각 `n=5,3,10,4`에서 가능한 `(B,E)`가
하나도 없었다. 따라서 이 형태의 XOR/ADD 교환은 64비트에서도 불가능하다.
`2^63` bit만 ADD에 흡수하는 항등식은 두 C에 적용되지만, 흡수 뒤의 mask가
각각 `0x3794618d2e5af0c3`, `0x05307c4f1a9d2e6b`로 남아 XOR instruction은
사라지지 않는다.

두 라운드의 선형 부분 `B R_s B R_r`도 64개 bit permutation을 직접 합성했다.
네 경우 모두 단일 rotate, `BSWAP` 뒤/앞의 단일 rotate와 일치하지 않았다.
rotation pair 43/14와 14/43의 cycle은 길이 64 하나, 7/29와 29/7은 길이
16 네 개였다. 이 검사는
[`analyze_transform_lower_bound_02.py`](analyze_transform_lower_bound_02.py)로
재현하며 [구조화된 결과](transform_lower_bound_02.json)도 보존했다. 이는
모든 3-instruction 회로의 일반 하한은 아니지만, 시도한
상수 이동과 단일 선형 instruction 합성은 완전히 기각한다.

정확한 대체 표현도 candidate를 직접 호출하는 100,000건 검증 뒤 측정했다.

| exact 후보 | best 대비 paired | bootstrap 95% CI | 결과 |
|---|---:|---:|---|
| post-BSWAP XOR | 0.980x | 0.968--0.988x | 같은 320-op, 느림 |
| top-bit fold | 0.983x | 0.979--0.996x | XOR가 남아 느림 |
| `x xor c = x+c-2(x&c)` | 0.620x | 0.607--0.633x | AND/LEA/ADD 증가 |
| 32-bit halves/funnel shift | 0.251x | 0.247--0.260x | 약 4배 느림 |

### 켤레관계를 이용한 2-lane SIMD

네 word transform 사이에는 역위상 켤레관계가 있다. 적절한 좌표변환
`C0`, `C1`을 잡으면 `T3 = C0 T0 C0^-1`,
`T2 = C1 T1 C1^-1` 꼴이 되어 `(x0,C0^-1(x3))`와
`(x1,C1^-1(x2))`를 두 SIMD lane씩 묶을 수 있다. 이 후보는 공식 vector와
100,000개 differential case를 통과했고 생성된 핵심 instruction 수를
약 320개에서 240개로 줄였다.

그러나 scalar 네 chain이 두 vector chain으로 합쳐지고, lane별 rotate가
shift/shift/OR가 되어 transform critical path는 약 4단계에서 5단계로
늘었다. 두 독립 캠페인의 paired 결과는 `0.8450x`, `0.8482x`로 일관되게
느렸다. 동적 instruction 수만 줄이는 것보다 chain latency와 독립 stream
수가 이 workload에서 더 중요하다는 대조 실험이다.

### 작은 lookup table과 ANF 점검

20라운드 뒤의 word 함수 전체를 정확히 저장하면 함수 하나당
`2^64 * 8 = 2^67` bytes, 즉 128 EiB가 필요하다. 켤레관계로 독립 함수를
두 종류까지 줄여도 256 EiB다. rotate+byte-swap이라는 선형 부분만 8-bit
chunk table로 나누면 총 64 KiB지만 transform당 8 loads와 7 combines가
필요하고, 16-bit table은 8 MiB와 4 loads가 필요해 현재 register 연산보다
불리하다. ADD carry까지 포함하면 chunk가 독립이 아니다.

[analyze_table_decomposition_02.py](analyze_table_decomposition_02.py)는 이
비분리성을 재현한다. 각 네 20-round word 함수에서 모든 입력 byte가 모든
출력 byte에 영향을 주어 `64/64` influence edge가 관측됐다. 서로 다른 두
입력 byte에 대한 혼합 XOR 미분은 1,000회 모두 0이 아니었고, modulo-sum
혼합 미분도 함수별 999회 또는 1,000회가 0이 아니었다. 한 고정 16차원
부분공간의 ANF 차수는 출력 bit별 최소/중앙/최대 `15/15/16`이고 64개 중
29개가 차수 16이었다. 이는 모든 회로 하한을 증명하는 결과는 아니지만,
byte별 독립 XOR/덧셈 table이라는 구체적 분해를 직접 반증한다.

### compiler pass, 수동 scheduling과 병렬화

`-fschedule-insns`, `-frename-registers`, `-fweb`, modulo scheduling, LTO와
PGO를 각각 확인했다. 대부분 hot helper가 byte-identical하거나 paired
차이가 약 1--2%로 분산 안에 있었다. 통제된 동일-process 비교는 다음과 같다.

| isolated hot-function 변형 | paired 중앙값 | 판단 |
|---|---:|---|
| `-fschedule-insns` | 1.0167x (MAD 0.0263x) | 분산보다 작음 |
| `-frename-registers` | 0.9993x (MAD 0.0106x) | 동률 |
| schedule + rename + `-fweb` | 1.0130x (MAD 0.0236x) | 분산보다 작음 |
| `-mtune=skylake` | 1.0167x (MAD 0.0520x) | 불안정 |
| `-march=native` | 1.0501x, reverse layout 1.0471x | AMD에서만 유망 |
| `-fira-algorithm=priority` | 1.0467x, reverse layout 1.0430x | isolated 결과만 유망 |
| Clang 21 | 1.0103x (MAD 0.0413x) | 동률 |
| `target_clones("bmi2","default")` | 0.9998x (MAD 0.0206x) | 코드만 증가 |

이 표는 함수 배치까지 통제한 isolated hot-function 실험이다.
`-march=native`, `-mtune=native`, `-mtune=znver2`의 hot function bytes는
이 AMD host에서 같아 약 5% 차이는 추가 ISA가 아니라 scheduler tuning에서
나왔다. `-fweb`, modulo scheduling, GCC 12의 `-mtune=alderlake`, LTO와 PGO는
hot helper가 기본 build와 byte-identical했다. `-march=native`와
`-fira-algorithm=priority`가 target Intel에서도 같다는 보장은 없다.

더 중요한 complete `contest.c` score build에서도 base/IRA/native tune/결합을
다시 비교했다. 네 binary의 text 크기와 SHA-256이 모두 달라 flag가 실제로
code generation에 영향을 준 것은 확인됐다.

| score build 변형 | 중앙값 | base 대비 paired 중앙값 | bootstrap 95% CI |
|---|---:|---:|---:|
| base inline | 51.197 ns | 1.000x | - |
| `-fira-algorithm=priority` | 50.027 ns | 1.016x | 0.951--1.038x |
| `-mtune=native` | 51.068 ns | 0.985x | 0.946--1.010x |
| 두 flag 결합 | 50.901 ns | 0.970x | 0.958--1.014x |

shared-host 분산이 컸지만 어느 interval도 1보다 높지 않았고 결합은 오히려
paired 중앙값이 낮았다. 따라서 score 기본 명령에는 둘 다 넣지 않는다.
CPU 4, 3,000,000회, warm-up 3회, 21 samples의 원시는
[inline_codegen_results_02.json](inline_codegen_results_02.json)에 있다.

인라인된 timing loop 자체의 fetch alignment도 별도로 측정했다. 기본 loop
target은 `0x1550`(16-byte), `-falign-loops=32`는 `0x1560`, 64/128은
`0x1580`으로 실제 이동했다.

| loop alignment | 중앙값 | 기본 대비 paired 중앙값 | bootstrap 95% CI |
|---:|---:|---:|---:|
| 기본 16 | 37.863 ns | 1.000x | - |
| 32 | 37.975 ns | 1.006x | 0.980--1.025x |
| 64 | 38.034 ns | 0.991x | 0.964--1.009x |
| 128 | 38.052 ns | 0.990x | 0.980--1.003x |

어느 interval도 개선을 확정하지 못했고 64/128은 오히려 중앙값이 느렸다.
따라서 GCC 기본 loop alignment를 유지한다. 3,000,000회, warm-up 3회,
CPU 4 고정 21 samples의 원시는
[inline_alignment_results_02.json](inline_alignment_results_02.json)에 있다.

수동 `RORX` assembly, pure-C compiler barrier와 transform 순서 교환도
callee-saved register 사용이나 move를 줄이지 못했다. 여러 outer call을
병렬 batch로 묶는 방법은 출력 state가 다음 call의 입력인 직렬 recurrence를
바꾸므로 공식 API와 동치가 아니다. 다른 native 언어로 옮겨도 제출 경계가
`gcc contest.c`로 고정되어 있어 이 제약을 없애지 못한다. 반대로 적응형
인라이닝은 계산 순서나 API를 바꾸지 않고 바로 그 call boundary만 제거한다.

### complete-binary flag matrix와 Intel 전용 후보

후속 screen은 GCC/link 조합 120개를 compile했고 hot loop byte stream 26종을
분리했다. LTO, `-fwhole-program`, `-fno-semantic-interposition`, section GC와
section order는 기본 1,216-byte loop와 byte-identical이어서 주소만 바꿨다.
PGO는 loop를 1,225 bytes로 바꿨지만 paired `1.0077x`의 CI가
`0.9901--1.0199x`였다. scheduler는 `0.9857x (0.9698--1.0018)`였다.

IRA priority는 첫 31-sample complete run에서 `1.0217x`와
`1.0172--1.0338x`를 보여 겉보기에는 승자였다. 그러나 loop offset을 통제한
별도 25-sample run에서 IRA offset 0/32/53/56의 paired 값이
`0.9852/0.9948/0.9851/0.9875x`였고 네 CI 모두 1을 포함했다. baseline의
offset 0/32 복제본도 동률이었다. 첫 양성은 shared-host/layout false
positive로 기각하며, 단일 캠페인의 작은 CI만 보고 flag를 채택하지 않는다.

GCC 13.3 문서에는 `arrowlake` 전용 target이 없고 hybrid client용 explicit
target으로 `alderlake`가 있으므로 `-mtune=alderlake`도 조사했다. AMD host의
한 21-sample 캠페인은 `1.0148x (1.0001--1.0207)`였고 근사 LLVM-MCA 모델은
약 `1.0117x`를 예측했다. 그러나 그 모델은 Arrow/Lunar/Alder Lake에 같은
ADLP port model을 쓰며 실제 Lion Cove/Skymont, uop cache, alignment와 OS의
P/E/LP-E 이동을 모델링하지 않는다. 따라서 기본 score flag로 채택하지 않고
실제 255H에서 두 독립 세션으로 확인할 첫 A/B 후보로만 둔다.

고정 register로 네 state의 RORX/XOR/BSWAP/ADD를 phase scheduling한 수동
후보도 loop 1,203 bytes, 모델상 약 `1.033x`였지만 AMD 실측은
`0.993x (0.970--1.027)`였다. all-LEA, MOVBE, AVX-512는 각각 LEA port 병목,
register-register MOVBE 부재, 공식 255H 사양의 AVX2까지만 명시된 조건 때문에
제외했다. 유지보수 가능한 현재 C source를 실제 target 증거 없이 교체하지 않는다.

## GCC 13.3 실물 재현과 4차 탐색

문서상 옵션 지원 여부만 확인하는 데서 멈추지 않고, 공식 `gcc:13.3.0` image를
digest `sha256:1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818`로
고정해 현재 제출 source를 그대로 다시 빌드했다. source SHA-256은
`51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71`이다.

| GCC 13.3 build | complete `.text` | timing loop | call / hot memory | 판정 |
|---|---:|---:|---:|---|
| 기본 `-O3` | 5,972 B | 31 B / 6 insn | 1 / 0 | 호환 경로 |
| BMI2 inline, limit 700 | 7,246 B | 1,216 B / 322 insn | 0 / 0 | full inline |
| BMI2 inline, limit 2000 | 7,246 B | 1,216 B / 322 insn | 0 / 0 | 700과 binary 동일 |
| 위 flag + `-mtune=alderlake` | 7,246 B | 1,216 B / 322 insn | 0 / 0 | 다른 schedule |
| Alder tune + IRA priority | 7,199 B | 1,210 B / 322 insn | 0 / 0 | 세 번째 schedule |

따라서 GCC release가 바뀌면 inline threshold를 다시 봐야 한다는 이전의
불확실성은 해소됐다. generic과 Alder loop는 모두 80개의
`RORX/XOR/BSWAP/ADD-or-LEA`를 가지며, Alder+IRA도 핵심 320연산은 같고
ADD/LEA 선택과 배치만 달라진다. 각 build는 공식 1-round 1,000쌍과 20-round
vector, 임의 state와 임의 ADD/XOR 상수 100,000건의 1/20-round 직접 검증을
통과했다. `alderlake`, `raptorlake`, `meteorlake`는 이 source에서 complete
binary까지 같고, GCC 13.3은 `arrowlake` tune 이름을 지원하지 않는다.

34개 scheduler/allocator 조합 중 32개가 compile됐고 hot-loop stream은 8종만
남았다. [재현 스크립트](screen_gcc133_schedules_02.py)와
[구조화된 결과](gcc133_schedule_screen_02.json)는 모든 후보 flag, binary/loop
hash와 LLVM-MCA 결과를 보존한다. LLVM-MCA 16의 Alder/Raptor/Meteor 근사
모델은 generic/Alder/Alder+IRA를
각각 `125.06/123.62/121.06` cycles로 예측했다. 이는 후보를 줄이는 정적
screen일 뿐 Lion Cove나 Skymont의 실측값은 아니다. 같은 GCC 13.3 binary를
AMD host에서 5,000,000회, warm-up 6회, 40 samples로 비교했을 때
Alder 대비 Alder+IRA의 paired 값은 CPU 0에서 `1.011x`
(CI `1.001--1.015x`), CPU 4에서 `1.008x` (`0.998--1.025x`)였다. CPU별
interval이 일치하지 않고 microarchitecture도 다르므로 제출 기본값으로
승격하지 않고 255H의 우선 후보로만 남긴다. 역사적 schema-4 원시는
[CPU 0](gcc133_schedule_results_02_cpu0.json)과
[CPU 4](gcc133_schedule_results_02_cpu4.json)에 있다.

```bash
python3 solutions/02_optimization/screen_gcc133_schedules_02.py \
  --json /tmp/challenge02-gcc133-schedule-screen.json
```

### 상수와 좌표계 축의 종결

XOR를 BSWAP 뒤 또는 rotate 앞으로 옮긴 두 표현은 임의 상수까지 포함한
100,000건 검증을 통과했다. 후보를 정확히 재생성한 뒤 당시 schema 4와 실측 binary
audit로 CPU 0/4에서 각각 24 samples를 다시 측정하자 post-BSWAP은
`0.959x (0.949--0.970)` / `0.963x (0.940--0.980)`, pre-rotate는
`0.965x (0.953--0.977)` / `0.960x (0.944--0.980)`였다. 어느 표현도 320개
핵심 연산을 줄이지 못했고 두 affinity 모두 일관되게 느렸다.

상수를 memory operand로 강제하면 hot memory operand가 160개로 늘고 loop가
1,216에서 2,015 bytes로 커진다. 21-sample 재측정은 CPU 0에서
`0.979x (0.964--0.992)`, CPU 4에서 `0.988x (0.969--1.002)`였다. 과거
5-sample `0.897x` 선별값보다 후퇴 폭은 작지만, 개선 증거가 없고 한 affinity는
유의하게 느리므로 기각 결론은 같다. 새 원시는
[재배치 CPU 0](constant_reordering_results_02_cpu0.json),
[재배치 CPU 4](constant_reordering_results_02_cpu4.json),
[memory CPU 0](constant_memory_results_02_cpu0.json),
[memory CPU 4](constant_memory_results_02_cpu4.json)에 있다.

공식 상수 literal 특수화는 공식 vector만 통과하고 임의 상수 첫 사례에서
실패하므로 함수 계약을 위반한다. 더구나 핵심 연산 수도 줄지 않는다.
[`analyze_constant_placement_02.py`](analyze_constant_placement_02.py)는 원래
상수, byte-swapped 상수, inverse-rotated 상수와 top-bit fold 잔여값이 모두
x86-64 sign-extended `imm32`에 들어가지 않으며, ADD로 완전히 흡수할 수 있는
잔여 XOR `{0,2^63}`도 없음을 결정적으로 검사한다.

### 5차 source-order/backend 탐색

두 라운드 macro의 `x0..x3` 갱신 네 문장은 서로 독립이므로 24개 순열을 모두
GCC 13.3으로 compile했다. 재현 스크립트
[`screen_gcc133_source_orders_02.py`](screen_gcc133_source_orders_02.py)는
generic, Alder, Alder+IRA 세 profile의 총 72 build를 생성한다. 그중
`x2,x1,x0,x3` 순서가 generic과 Alder에서 정적 최상위였다.

| profile | 기존 `0,1,2,3` | `2,1,0,3` | loop |
|---|---:|---:|---|
| generic | 125.06 cycles | **121.06** | 1,216 -> 1,211 B |
| Alder | 123.62 cycles | **121.06** | 1,216 -> 1,211 B |
| Alder+IRA | 121.06 cycles | 121.06 | 1,210 B |

보존한 [`contest_source_order_2103.c`](contest_source_order_2103.c)는 현재
제출 source와 독립 assignment의 순서만 다르다. 상수와 state local 선언 순서는
세 profile에서 모두 기존 binary와 같았다. `2,1,0,3`의 세 profile은 322개
instruction과 핵심 연산 320개를 유지하고 call, push/pop, spill/hot memory
operand가 없으며, 중립 verifier의 임의 state/상수 100,000건 1/20-round를
통과했다. 전체 24순열의 hash와 정적 순위는
[`gcc133_source_order_results_02.json`](gcc133_source_order_results_02.json)에
있다.

다음으로 [`screen_gcc133_layout_02.py`](screen_gcc133_layout_02.py)는 안정적인
scheduler/layout/link flag 106개와 source-order 교차 3개를 exact GCC 13.3으로
compile했다. 109/109 build의 assembly contract가 통과했고 기본 106개에서
고유 hot loop 9개가 나왔다. shortlist 9개는 공식 vector와 임의 state/상수
100,000건의 1/20-round도 다시 통과했다.

| Alder+IRA 변형 | LLVM-MCA 근사 | 설명 |
|---|---:|---|
| incumbent | 121.06 cycles | 기준 stream |
| `-fselective-scheduling2` | **120.06** | 새 stream |
| `-fno-schedule-insns2` | **120.07** | 새 stream |
| critical-path heuristic off | 120.14 | 새 stream |
| loop align 64 / LTO | 121.06 | 같은 stream, 주소/전체 text만 변경 |

source order와 상위 두 backend flag를 결합해도 각각 120.06/120.07이어서 정적
개선은 더해지지 않았다. AMD 보조 측정도 CPU별로 엇갈렸고 selective 후보는
오히려 느렸으므로 실제 255H의 Lion Cove/Skymont 결론으로 옮기지 않는다. 구조화된
109-build 결과는
[`gcc133_layout_screen_02.json`](gcc133_layout_screen_02.json)에 있다.
LLVM-MCA는 LLVM scheduling model로 machine code의 throughput/resource pressure를
정적으로 진단하는 도구이며, 정확도는 해당 모델에 제한된다
([공식 문서](https://llvm.org/docs/CommandGuide/llvm-mca.html)). 따라서 새 source와
flag는 target-only A/B 후보로만 manifest에 추가했고 incumbent는 바꾸지 않았다.

### 6차: 부분 언롤 재현, scalar 합성 하한과 lane-wise AVX2

#### 더 작은 pair block의 재확인

`contest_source_order_2103.c`에 `P2_PAIR_BLOCK={1,2,5,10}`을 두어 두 라운드
block을 1, 2, 5, 10개씩 펼쳤다. compiler가 다시 전부 펼치지 않도록
register-only barrier를 사용했다. GCC 12의 실제 score loop는 각각
143/278/646/1,211 bytes, 38/71/167/322 instructions였다. 모든 후보는 공식
vector와 임의 state/상수 100,000건의 1/20-round 검사를 통과했다.

CPU 1의 첫 21-sample screen에서 가장 작은 loop가 `1.035x`
(`1.007--1.043`)로 보였지만, warm-up 6회와 6,000,000-call 32 samples로 바로
재확인하자 `1.0004x (0.9855--1.0176)`가 되었다. 중앙값도 full/loop
`41.102/40.936 ns`로 사실상 같았다. unroll2는 첫 screen부터 CI가 1을
가로질렀고 unroll5는 유의하게 느렸다. 따라서 작은 loop는 frontend가 다른
255H에서 확인할 대조군으로만 남기고 scalar incumbent를 바꾸지 않는다. 원시는
[`partial_unroll_results_02_cpu1.json`](partial_unroll_results_02_cpu1.json)과
[`partial_loop_confirm_02_cpu1.json`](partial_loop_confirm_02_cpu1.json)에 있다.

#### 제한된 grammar의 2-round superoptimization

한 word의 한 stage를
`T(x)=BSWAP64(ROL64(x,r) xor k)+a`로 두고
[`analyze_two_round_superopt_02.py`](analyze_two_round_superopt_02.py)에서 bit-vector
CEGIS와 완전탐색을 함께 수행했다. 서로 다른 각 stage에 대해
`rotate/XOR/BSWAP/ADD` 길이 3의 64개 template는 모두 UNSAT였다. 기존
8-operation pair에서 연산 하나를 지운 뒤 남은 상수를 다시 합성하는
`4 chains × 8 positions = 32`개도 모두 UNSAT였다. 선형부는 길이 3 이하
rotate/BSWAP 구문 4,223개, 중복을 제거한 bit permutation 632개를 전수 검사했지만
어느 pair와도 같지 않았다. 실제 상수 역시 sign-extended `imm32`에 들어가지
않는다.

이는 정의한 연산 grammar 안의 stage 하한과 기존 pair의 국소 irredundancy를
보인 것이지, 임의의 x86 instruction이나 전혀 다른 표현까지 포함하는 전역
8-operation 하한은 아니다. 그 범위 안에서는 GCC 12가 이미 320개 scalar 핵심
연산을 spill 없이 내며, Clang 21 후보는 같은 핵심 연산에 stack memory 2개와
`movabs` 3개를 더해 오히려 열세였다. solver 식, 반례, UNSAT 목록과 exact
codegen은
[`two_round_superopt_results_02.json`](two_round_superopt_results_02.json)에
보존했다.

#### 네 chain을 네 YMM lane에 배치

과거의 one-state SIMD는 한 라운드의 word reversal과 서로 다른 회전 때문에
긴 dependent path를 만들었다. 새
[`contest_simd_avx2_lanewise.c`](contest_simd_avx2_lanewise.c)는 두 라운드 뒤
reversal이 사라진 시점의 네 독립 chain을 각각 YMM lane에 둔다. 열 개의
2-round block 전체에서 `VPSLLVQ/VPSRLVQ/VPOR/VPXOR/VPSHUFB/VPADDQ`가 정확히
20개씩 실행된다. tied-register identity helper로 두 forward constant도 timing
loop 밖에 유지하면 exact GCC 13.3 loop는 124 instructions/587 bytes/hot load
2개에서 **122 instructions/579 bytes/hot memory 0개**로 줄어든다. 이 micro
변형 자체의 CPU 2 직접 비교는 `1.0013x (0.9983--1.0039)`로 동률이므로, 속도
주장보다 더 단순한 exact code stream을 선택한 것이다.

최종 AVX2와 scalar incumbent를 각 3,000,000 calls, warm-up 6회, 균형 순서
32 samples로 다시 비교했다.

| AMD affinity | scalar | AVX2 | paired median | bootstrap 95% CI |
|---:|---:|---:|---:|---:|
| CPU 1 | 46.927 ns | 36.690 ns | **1.275x** | 1.260--1.292x |
| CPU 2 | 34.354 ns | 36.569 ns | **0.940x** | 0.923--0.950x |
| CPU 3 | 45.938 ns | 36.724 ns | **1.248x** | 1.222--1.269x |

세 physical affinity에서 CPU 2만 순위가 완전히 뒤집힌 사실은 이 AMD/GCC12
VM의 affinity/frequency 조건을 255H 성능의 대용물로 쓸 수 없다는 직접적인
증거다. 공식 vector와 임의 state/상수 100,000건, exact 122-instruction
감사는 두 campaign 모두 통과했다. 원시는
[`avx2_confirm_02_cpu1.json`](avx2_confirm_02_cpu1.json),
[`avx2_confirm_02_cpu3.json`](avx2_confirm_02_cpu3.json), 전체 12변형과 초기
CPU/SSE2 대조군은 [`simd_results_02.json`](simd_results_02.json)에 있다.
SSE2는 781-instruction/4,064-byte loop와 약 `0.40x`여서 기각했다.

마지막으로 [`screen_255h_toolchains_02.py`](screen_255h_toolchains_02.py)는 host
timing 없이 exact GCC 13.3 추가 47조합과 Clang 21의 53조합을 검사했다. GCC는
기존 120.06-cycle Alder proxy를 넘지 못했다. Clang Arrow Lake의 hidden
`ilpmax/ilpmin`은 1,208-byte, 322-instruction, 무스필 stream을 만들었지만 같은
근사 모델에서 133.79 cycles로 열세였다. GCC 13.3은 Arrow/Lunar/Panther target
이름을 받지 않고 LLVM-MCA 16에도 Lion Cove/Skymont model이 없다. 결과는
[`255h_toolchain_screen_02.json`](255h_toolchain_screen_02.json)에 있다. 따라서
scalar는 안전한 incumbent, lane-wise AVX2는 255H에서 가장 먼저 비교할
target-only 후보다.

### 7차: split-width SIMD, backend 재탐색과 측정 역전 진단

YMM 한 개의 긴 dependency chain을 두 XMM 그룹으로 나누면 instruction-level
parallelism을 다시 얻을 가능성이 있다. 이를 확인하려고 연속 lane, reversal
orbit pair, 두 그룹 직렬 계산, invariant를 lane shuffle로 재계산하는 네
구현을 만들었다. 모든 구현은 exact GCC 13.3, 공식 vector, 무작위 state와
ADD/XOR 상수 100,000건을 통과했다. 그러나 256-bit 명령 하나가 하던 일을
128-bit 명령 두 개가 반복하면서 loop가 242--288 instructions,
1,303--1,509 bytes로 커졌고 register pressure 때문에 hot memory operand도
30--50개 생겼다. LLVM-MCA 근사는 현 YMM loop 대비 Alder에서
`1.78--2.35x`, Zen 2에서 `1.36--2.08x`의 cycle을 요구했다. 이 정도 정적
열세는 noisy host timing으로 뒤집힐 합리적 근거가 없어 측정을 생략하고
manifest에도 넣지 않았다. 재현 도구와 결과는
[`screen_split_simd_02.py`](screen_split_simd_02.py),
[`split_simd_results_02.json`](split_simd_results_02.json)에 있다.

다음으로 [`screen_avx2_codegen_02.py`](screen_avx2_codegen_02.py)는 exact GCC
13.3과 Clang 21에서 target/tune, scheduler, IRA, loop alignment와 다섯 source
표현 및 고정-register 대조군을 113개 build로 검사했다. 100개 complete timed
loop가 exact audit를 통과했고 Pareto 후보와 모든 추출 가능한 source rewrite
14개는 다시 100,000-case 직접
검증을 통과했다. GCC `-fira-region=one`은 579-byte loop를 569 bytes로만
줄였고 122 instructions, memory 0, Alder `100.03`, Zen 2 `180.03` cycle
근사는 그대로였다. Clang은 548-byte loop를 만들었지만 같은 instruction과
근사 cycle이었고 최종 compiler도 아니다.

rotate의 left/right shift 결과는 각 lane에서 서로 겹치지 않으므로 OR 대신
XOR로 합쳐도 정확하다. 실제 변형도 GCC/Clang 모두 1/20-round 100,000-case를
통과했지만 `20 VPOR + 20 VPXOR`가 `40 VPXOR`로 바뀌었을 뿐 instruction 수,
loop bytes, memory와 두 모델의 cycle이 전혀 줄지 않았다. inline assembly로
모든 YMM register를 낮은 번호에 고정한 변형은 VEX encoding을 줄여 563 bytes가
됐지만, GCC가 XOR 상수 하나를 매 iteration reload하고 reverse permute도 다시
계산했다. 그 결과 124 instructions와 hot memory 1개가 되어 정확성 검증은
통과했지만 성능 audit에서 탈락했다. 별도의 inline assembly로
즉시값 `RORX`를 source에 강제한 compact pair loop도 정답성은 통과했지만
기본 `gcc -O3` complete binary에는 여전히 public wrapper call 하나가 남았다
(25 bytes, 8 instructions). 결국 `-finline-limit=2000`이 필요했으므로 기존
adaptive score build를 대체하지 않는다. 전체 backend 기록은
[`avx2_codegen_screen_02.json`](avx2_codegen_screen_02.json)에 있다.

마지막으로 CPU별 순위 역전이 timer·migration·standalone layout 때문인지
분리했다. [`benchmark_timing_stability_02.py`](benchmark_timing_stability_02.py)는
역사적 process-isolated schema-4 측정과, 두 runner를 각각 4 KiB 정렬한 한
프로세스의 AB/BA 측정을 함께 수행한다. 후자는 wall, thread CPU,
serialized `RDTSCP`, 시작/종료 CPU와 `TSC_AUX`, context switch, selected CPU와
SMT sibling의 busy fraction을 각 sample에 기록한다.

CPU 2의 새 6-warm-up, 32-sample, 3,000,000-call 측정에서 process-isolated
scalar/AVX2 비는 `0.8768x (0.859--0.891)`, same-process 비는
`0.9225x (0.8845--0.9290)`였다. wall/thread/TSC 중앙값 차이는 0.000003
미만이고 migration과 `TSC_AUX` 변화는 0이었다. CPU 1/2/3 artifact를 비교하면
scalar와 AVX2의 exact binary 및 normalized loop hash가 모두 같다. 그런데
AVX2 median 범위는 0.78%인 반면 scalar는 45.89%다. 따라서 부호 역전은 AVX2
codegen이나 timer 선택이 아니라 이 공유 VM의 scalar 처리율 변화에 국소화된다.
SMT sibling busy fraction과 scalar time의 상관이 더 컸지만, APERF/MPERF,
cpufreq와 performance counter를 사용할 수 없어 SMT 또는 가상화된 frequency의
인과관계는 단정하지 않는다. 이 진단은
[`timing_stability_results_02.json`](timing_stability_results_02.json)에 보존하며
255H 성능 근거로 사용하지 않는다.

### 8차: 부분 register 고정, phase-stagger와 255H 공식 표

고정-register 실패를 더 좁혀 보면 문제는 inline assembly 자체가 아니라 동시에
살아 있는 YMM 값의 수였다. [`screen_avx2_inline_asm_alloc_02.py`](screen_avx2_inline_asm_alloc_02.py)는
전수 register-map brute force 대신 allocator 자유 배치, 부분 pin, scratch 1/2개,
낮은 상수/높은 control 배치 등의 제한된 가설을 exact GCC 13.3으로 검사했다.
8차 당시에는 10개였고, 9차 commutative 변형을 포함한 현재 record는 11개다. 모든
변형은 공식 vector와 임의 state·ADD/XOR 상수 100,000건의 1/20-round 직접 검증을
거쳤다.

상태만 `ymm0`에 고정하고 오른쪽 shift 결과를 scratch 하나에 둔 다음 왼쪽 shift가
상태 register를 파괴하도록 만들면 GCC가 나머지 상수와 control을 스스로 배치한다.
이 단계의 candidate version은 기존과 같은
122 instructions, hot memory 0, Alder `100.03`, Zen 2 `180.03`을 유지하면서
579-byte loop를 **569 bytes**로 줄였다. `-fira-region=one`도 569 bytes지만
normalized loop hash는 각각 `0ada8e...57af1`, `7fd0b7...728af`로 서로 다른
register stream이다. 반대로 allocator 완전 자유나 상수까지 고정한 8개 변형은
124 instructions와 hot load 1--2개를 남겼다. 전체 실패 이유와 source hash는
[`avx2_inline_asm_alloc_results_02.json`](avx2_inline_asm_alloc_results_02.json)에
있다. 현재 [`contest_simd_avx2_inline_asm.c`](contest_simd_avx2_inline_asm.c)는
아래 9차의 549-byte refinement이며, JSON은 두 allocation record를 함께 보존한다.

두 번째 알고리즘 가설은 reversal orbit 안에서 서로 다른 phase의 값을 같은 XMM에
넣는 방법이다. `T_j(x)=BSWAP(ROL(x,r_j) XOR k_j)+a_{3-j}`라 두고
`[x0,T3(x3)]`와 `[x1,T2(x2)]`를 만들면 각 orbit에서 19개의 immediate-rotate
stage를 공유한 뒤 한 lane에만 epilogue를 적용할 수 있다. 이 방식은 임의 상수에도
정확하고 hot memory가 없지만 128-bit stream을 둘 복제해 257 instructions,
1,253 bytes가 됐다. LLVM-MCA는 현 YMM 대비 Alder `1.160x`, Zen 2 `0.795x`를
예측해 서로 충돌했다.

정적 Zen 2 예측을 실제로 확인하려고 CPU 1과 3에서 각각 warm-up 6회 뒤
3,000,000-call 32표본을 balanced 순서로 측정했다. 모든 measured binary audit와
100,000-case 검증을 다시 통과했다.

| affinity | 569B asm speedup (current/asm), 95% CI | phase speedup (current/phase), 95% CI |
|---|---:|---:|
| CPU 1 | `0.999x (0.998--1.002)` | `0.758x (0.754--0.764)` |
| CPU 3 | `1.000x (0.998--1.002)` | `0.756x (0.751--0.764)` |

따라서 569-byte source는 이 AMD host에서 통계적 동률이고, phase-stagger는 Zen 2
proxy의 유리한 예측과 반대로 처리량이 약 24% 낮고 같은 작업의 실행 시간은 약
32% 길다. 전자는 실제 255H용 후보로만 남기고
후자는 source와 negative record만 보존한다. 원시는
[`eighth_wave_timing_02_cpu1.json`](eighth_wave_timing_02_cpu1.json),
[`eighth_wave_timing_02_cpu3.json`](eighth_wave_timing_02_cpu3.json),
[`phase_staggered_results_02.json`](phase_staggered_results_02.json)에 있다.
첫 실행에서 temporary source로 복사된 phase 파일의 상대 include 기준이 사라지는
도구 문제도 발견했다. 공용 benchmark driver는 이제 원래 source directory를
`-iquote`로 candidate object와 performance build에 전달했다. 위 두 raw campaign은
이 수정 뒤 다시 측정한 결과지만 schema 4이므로 9차 repeated-call integrity
검사 이전의 역사적 자료다.

추가 flag 쪽은 [`screen_gcc133_avx_flags_02.py`](screen_gcc133_avx_flags_02.py)가
preferred vector width, unaligned load/store split, VEX/vzeroupper, move/store
width, cost model과 부분/AVX tune을 포함한 63개 신규 조합과 기준 2개를 검사했다.
65/65 audit가 통과했고 normalized instruction stream은 기존 generic/Alder 두
종류로만 수렴했다. 그러나 `(stream hash, loop-start mod 64)`로 보면 generic
offset `0/8/24/40/48`, Alder offset `8/16/48`의 **8개 배치 클래스**가 남는다.
각 클래스 대표 8개가 직접 100,000-case 검증을 통과했고 instruction count와
proxy cycle은 같지만 frontend 정렬 효과는 LLVM-MCA가 모델링하지 않는다. 기존
명시적 정렬 AMD sweep에는 유의한 승자가 없었으므로 nonbaseline 대표 7개는
기각하지 않고 255H target-only manifest 후보로 남겼다.
[`gcc133_avx_flags_results_02.json`](gcc133_avx_flags_results_02.json)은 이 경계를
포함한 재현 가능한 결과다.

마지막으로 [`analyze_255h_instruction_model_02.py`](analyze_255h_instruction_model_02.py)는
Intel ARK topology, Arrow Lake PerfMon/255H ECI의 core 설명, Intel 공식
Skymont·Crestmont latency/throughput package를 hash로 고정해 사용했다. Skymont
download는 Xeon 6 E-core용이라는 이름이므로 client 255H E-core로의 전이는
조건부다. 더구나 Arrow Lake PerfMon은 LP-E를 Crestmont로 부르지만 255H 전용
ECI 문서는 두 LP-E를 "additional Skymont cores"라고 설명해 공식 자료끼리
충돌한다. 따라서 Crestmont 수치는 PerfMon mapping이 맞을 때의 민감도 사례다.
선택된 AVX2 여섯 명령의 latency는 두 표에서 한 단계당
`parallel shifts 1 + OR/XOR/SHUF/ADD 4`, 즉 20 rounds critical path 100
cycles다. scalar 80-cycle 수치는 정확한 `RORX r64`와 여섯 `LEA` 행이 표에 없어
r32 RORX/ADD를 대신 넣은 민감도 분석일 뿐이다. 2026-07-23에 고정한 Intel
catalog에서는 Lion Cove P-core 공식 per-instruction 표도 확인하지 못했다.
isolated throughput 합은 port 공유·frontend·주파수·whole-loop를 모델링하지
않으므로 runtime bound가 아니다.
[`instruction_model_255h_02.json`](instruction_model_255h_02.json)은 이 gap과
source conflict를 숨기지 않고 winner를 선택하지 않는다.

### 9차: repeated-call 무결성, commutative encoding과 block-2 frontend

#### timing `main` 자체의 의미 검증

기존 runner는 candidate의 public 1/20-round 함수를 독립 reference와 비교하고
실제로 시간을 재는 complete binary의 assembly까지 감사했다. 그러나 이 둘만으로는
`main`이 출력한 iteration 수만큼 함수를 호출했다는 사실이 증명되지 않았다. 이를
확인하려고 scalar source의 timing loop bound만 `iterations / 2`로 바꾼 적대적
대조군을 만들었다. 이 source는 candidate random verifier와 strict
322-instruction inline audit를 모두 통과했고, 구 protocol에서는 **2.253x**라는
가짜 speedup을 만들었다. 알고리즘 성능이 아니라 benchmark semantic gap을
재현한 회귀 시험이다.

현재 schema 5는 [`solve_02_permutation.c`](../solve_02_permutation.c)의 별도
`--final-state N` 경로가 benchmark 초기 상태에서 reference 20-round 함수를 정확히
`N`회 합성해 예상 최종 상태를 계산한다. score-facing
[`benchmark_02_permutation.py`](../benchmark_02_permutation.py)는 semantic
preflight, 각 warm-up, 모든 측정 process마다 다음을 fail-closed로 검사한다.

- final-state, iteration, timing line이 각각 정확히 하나인지
- iteration 값이 요청과 같은지, stderr가 비었는지
- 네 word가 independent repeated-call oracle과 정확히 같은지

`timed_main_validation`에는 oracle의 expected state와 stdout SHA-256, case별
observed state, `preflight/warmup/measured/validated` process 수를 기록한다.
autotuner는 schema, field 집합, 값 형식과 정확한 process 수까지 재검사하고 이
record를 canonical evidence hash에 넣는다. 따라서 JSON 이름이나 공백을 바꿔
semantic record를 생략할 수 없다. 3,000,000-call 두 최종 campaign은 각 case마다
`1+6+32=39` process의 동일 상태를 확인했고 oracle stdout hash는
`8f63859ce7444f34b3fe31191c9f2da2f782f62e33b91860b2576c385fa60076`이다.

[`test_benchmark_02_permutation.py`](test_benchmark_02_permutation.py)는 중복/누락
출력, 10,000-call known state, 음수와 0 iteration의 oracle 거절을 검사한다. 같은
test가 half-loop source가 function verifier를 통과한 뒤에도 semantic preflight에서
거절되는 것을 고정한다. schema 2--4 JSON은 당시 codegen과 timing의 역사적 근거로
남지만 이 repeated-call 무결성 record가 없으므로 현재 confirmation으로 승격할 수
없다.

#### commutative operand order와 549-byte scoped bound

AVX의 세 피연산자 encoding에서는 두 source가 교환 가능해도 어느 값을
VEX.vvvv와 ModRM r/m에 두는지에 따라 high-register extension bit 위치가 달라진다.
`VPOR`, `VPXOR`, `VPADDQ`의 교환법칙을 이용해 낮은 번호의 changing `value`를
ModRM r/m, scratch/constant를 VEX.vvvv에 둔 결과 20개 `VPOR`가 각각 1 byte씩
짧아졌다. exact GCC 13.3의
[`contest_simd_avx2_inline_asm.c`](contest_simd_avx2_inline_asm.c)는 이제
**122 instructions, 549 bytes, hot memory 0**이며 normalized stream hash는
`0b4f2686a2a19ce4fe96d12b89d01e38092c088794252c8e1d8460c75bb8ae4b`다.
명령 수와 Alder/Zen 2 proxy는 기존과 같은
`100.03/180.03` cycles다.

현재 여섯 명령 dataflow의 stage encoding은
`VPSLLVQ 5 + VPSRLVQ 5 + VPOR 4 + VPSHUFB 5 + VPXOR 4 + VPADDQ 4 = 27`
bytes다. 따라서 default counter를 포함한 관측 하한은
`20*27 + SUB 3 + rel32 JNE 6 = 549` bytes다. 이는 이 dataflow와 counter의
**encoding 하한**이며 다른 알고리즘 전체의 하한은 아니다.
`-mtune-ctrl=use_incdec`는 stage를 바꾸지 않고 harness의 3-byte `SUB`만 2-byte
`DEC`로 바꿔 548 bytes가 된다. compiler 내부 tune-control에 의존하므로 실제
P/E/LP-E에서 확인할 target-only 대조군이다.

[`screen_avx2_commutative_layout_02.py`](screen_avx2_commutative_layout_02.py)는
정렬, scheduler, allocator, tune과 link 축의 34개 exact-GCC13 case를 재생성했다.
34/34가 complete-binary audit, 공식 vector와 임의 state·상수 100,000건 검증을
통과했다. 결과는 normalized stream 5개와 `(stream, start mod 64)` 9개 class로
수렴했고 모든 class의 MCA signature는 같다. 따라서 더 작은 encoding의 정확성은
확정됐지만 frontend 배치 순위는 target 실측 문제다. 각 instruction encoding,
source/binary/loop hash, 27-byte 계산과 class member는
[`avx2_commutative_layout_results_02.json`](avx2_commutative_layout_results_02.json)에
있다. VEX/ModRM field 해석은 Intel SDM, tune-control 의미는 GCC x86 options를
따랐다.

#### block-2 부분 언롤과 stage-major 음성 결과

완전 언롤의 작은 code footprint 대조군으로
[`contest_simd_avx2_pair_block2.c`](contest_simd_avx2_pair_block2.c)는 vector
transform 두 개를 한 inner iteration에 묶었다. loop 자체는 **136 bytes/30 static
instructions**, outer call 하나의 CFG-expanded padding 제외 실행량은 **133
modeled instructions**(실제 binary의 alignment NOP 1개 포함 134), hot memory는
0이다. 분기와 counter overhead가 늘어도 critical
dependency chain은 같아서 MCA는 `100.03/180.03`으로 유지된다.

block 1은 75 bytes/18 static이지만 padding 제외 143 instructions(NOP 포함 144)를
실행한다. opaque count를 쓴 block 5는 321 bytes/69 static, padding 제외 131
instructions(NOP 포함 132)이고
Alder proxy throughput도 block 2의 22.2에서 21.8 cycles로 소폭 낮다. 그러나
2명령·0.4-cycle 근사 이득에 비해 정적 footprint가 큰 절충이어서 target 전에는
승격하지 않았다. scalar 쪽에서는 두 stage의 네 독립 chain
source order를 각각 전순열해 `24*24=576`개를 exact GCC 13.3으로 compile했다.
Alder+IRA estimate 분포의 최솟값은 기존 tuned scalar와 같은 `120.06`이고 더 낮은
후보는 없었다. 생성 source, exact audit, CFG dynamic trace와 전체 음성 결과는
[`screen_avx2_pair_blocks_02.py`](screen_avx2_pair_blocks_02.py)와
[`avx2_pair_block_results_02.json`](avx2_pair_block_results_02.json)에 있다.

#### schema-5 최종 host 측정

CPU 1/3에서 old 569-byte `-fira-region=one` stream을 baseline으로 3,000,000 calls,
warm-up 6회, balanced sample 32개, random state·constant 100,000건을 사용했다.
아래 값은 `old569 / candidate`라 1보다 크면 candidate가 빠르다.

| affinity | candidate | paired median | bootstrap 95% CI |
|---:|---|---:|---:|
| CPU 1 | commutative 549 B | **1.000451x** | 0.999294--1.001894x |
| CPU 3 | commutative 549 B | **1.000466x** | 0.998164--1.002395x |
| CPU 1 | `DEC` 548 B | 0.999555x | 0.997869--1.000627x |
| CPU 3 | `DEC` 548 B | 1.001880x | 0.997620--1.004207x |
| CPU 1 | 549 B, align 32 | 0.998679x | 0.994845--1.002219x |
| CPU 3 | 549 B, align 32 | 1.000329x | 0.995564--1.003437x |
| CPU 1 | block 2 | 0.999263x | 0.997061--1.001998x |
| CPU 3 | block 2 | 0.999278x | 0.997635--1.002321x |

모든 interval이 1을 포함한다. 549-byte source는 정적 footprint 개선이지만 host
speedup은 아니며, 548-byte counter와 block 2도 마찬가지다. raw schema-5 record는
[`ninth_wave_timing_02_cpu1.json`](ninth_wave_timing_02_cpu1.json),
[`ninth_wave_timing_02_cpu3.json`](ninth_wave_timing_02_cpu3.json)에 있다. scalar
submission이 계속 incumbent이고 이 세 후보는 모두 255H-only다.

### 255H용 보수적 판정 절차

[`autotune_02_255h.py`](autotune_02_255h.py)는 `probe -> screen -> confirm ->
decide`를 분리한다. `probe`는 허용된 logical CPU마다 잠깐 affinity를 고정해
CPUID leaf `0x1a`의 core type과 Linux topology/frequency/capacity 신호를 함께
기록한다. CPUID는 P와 Atom 계열을 나누지만 LP-E를 E와 직접 구분하지 못하므로,
두 개 이상의 보조 신호가 동의하지 않으면 core type을 추측하지 않고
provisional로 남긴다.

`confirm`은 요청된 core type마다 서로 다른 physical representative 두 개와
서로 다른 두 session을 요구한다. `decide`는 compiler/source/manifest hash,
candidate 직접 정확성 검사와 실제 측정 binary SHA-256/assembly gate를 모두
맞춘 뒤, session 이름만 바꾼 artifact path나 content hash 재사용도 거부한다.
각 run에는 index와 benchmark JSON이 공유하는 128-bit nonce를 넣고, nonce나 JSON
공백을 바꾼 복사본도 canonical evidence hash와 paired-sample hash로 찾아낸다.
또한 autotuner/benchmark driver, loop audit, 독립 oracle/verifier, 공식 입력 ZIP,
Python 및 실제 `objdump`/`size` 실행 파일을 하나의 canonical protocol
fingerprint로 묶는다. `screen` 뒤
이 중 하나라도 바뀌면 `confirm`을 거부하고, 두 confirmation의 fingerprint가
다르거나 현재 코드와 달라도 최종 판정을 provisional로 남긴다. 같은 이유로
현재 protocol보다 오래된 topology probe도 `screen`에 사용할 수 없다. candidate 검증
레코드는 단순 PASS가 아니라 무작위 상태와 무작위 ADD/XOR 상수의 1/20-round
검사를 명시해야 한다. runner는 verifier가 출력한 count/seed/round/constant/PASS
레코드를 정확히 파싱한다. reference TU는 후보 flag와 분리해 고정 flag로 compile하고,
candidate object만 성능 build flag를 사용한다. verifier-only override가 생긴 후보는
격리하며, source는 한 번만 snapshot해 원본과 iteration-rewritten hash를 함께 남긴다.
topology의 cache 배열도 내부 원소가 모두 object인지 검사해 잘못된 nested 입력을
traceback 없이 fail-closed 오류로 돌려준다. 초기 8개 manifest case를 실제로 짧게
통합 실행하면서 diagnostic `portable_rol`에
`portable-inline-320` audit은 지정했지만 `-finline-limit=2000`을 빠뜨린 것도
찾아 고쳤다. 수정 뒤 1,060-byte/323-instruction loop를 포함해 8개 audit가 모두
통과했다. 5차 후보를 추가한 뒤에는 균형 순서의 15-case 통합 screen에서
15개 직접 검증과 15개 exact-binary audit가 모두 통과했다. 의도적으로 작은
두 AMD/GCC12 confirm을 `decide`에 연결했을 때에도 255H, GCC13.3, sample,
warm-up, iteration, random-case 최소치를 각각 열거하고 incumbent를 유지했다.
부분 언롤 세 개와 lane-wise AVX2까지 넣은 19-case smoke도 직접 검증과 실측
binary audit 19/19를 통과했다. 여기에 당시 서로 다른 569-byte stream인
`-fira-region=one`과 single-scratch inline assembly를 추가한 21-case smoke도
21/21을 통과했다. 마지막으로 nonbaseline stream/alignment 대표 7개를 추가한
28-case balanced smoke가 직접 검증 28/28, audit 28/28을 통과했고 28개 모두
원래 source의 `-iquote` context를 기록했다. commutative 549-byte refinement는
기존 assembly entry를 교체하고, 548-byte `DEC` control과 block-2 candidate가
추가되어 현재 manifest는 **30 cases**다. 이 1,000-call timing 값은 성능 근거가
아니라 통합 회귀 검사이며, 현재 confirmation에는 schema-5 repeated-call record도
필수다.
P-core 모든 campaign에서 paired median `>= 1.010`, 보정된 lower bound
`> 1.005`이고 E/LP-E 안전성도 지킨 후보만 통과시킨다. 여러 후보가 동시에 통과하면
자동으로 임의의 하나를 고르지 않고 별도 head-to-head를 요구한다. 따라서 현재
AMD host나 불완전한 topology로 실행해도 incumbent를 잘못 교체할 수 없다.

## 검증 및 측정 방법

[deep_candidates_02.c](deep_candidates_02.c)는 18개 후보를 포함하며 다음 검사를
모두 통과했다.

- 공식 1-round vector 1,000개
- 공식 20-round vector
- 고정 seed 무작위 20-round differential case 100,000개

[run_deep_review_02.py](run_deep_review_02.py)는 다음 절차를 사용한다.

1. 전체 후보 correctness test
2. 후보별 독립 실행 파일 compile
3. 한 logical CPU에 고정
4. 매 측정 전 300,000-call warmup
5. sample당 2,000,000-call 측정
6. 각 후보 15 samples
7. 매 sample에서 기준선과 후보의 실행 순서를 무작위화
8. 인접한 두 측정의 `baseline_ns / candidate_ns`를 paired speedup으로 계산
9. median과 MAD 보고

재현 명령은 다음과 같다.

```bash
python3 solutions/02_optimization/run_deep_review_02.py \
  --iterations 2000000 \
  --warmup-iterations 300000 \
  --samples 15 \
  --random-cases 100000 \
  --output deep-result.txt
```

score-facing [`benchmark_02_permutation.py`](../benchmark_02_permutation.py)의
현재 schema 5는 reference oracle self-test와 candidate 검증을 분리한다. 각
`contest.c`를 `main`만 rename한 object로 만들고
[`verify_contest_candidate_02.c`](verify_contest_candidate_02.c)에 별도로
link하여, candidate의 public 1/20-round 함수를 무작위 상태와 무작위 상수로
직접 호출한다. `--audit-mode`를 지정한 case는 정확히 timing할 complete
executable을 scalar/AVX2 case에 맞는 assembly contract로 감사하고, 이를 통과한
artifact만 warm-up과 timing에 사용한다. 권장 명령과 autotuner manifest는 모든
case에 mode를 명시하므로 correctness용 object와 performance binary가 달라
생기는 검증 공백도 닫는다. verifier reference TU에는 candidate의 전처리/target
flag를 적용하지 않으며, `-fwhole-program`처럼 candidate object 검증에 별도
override가 필요하면 autotuner 승격 대상에서 제외한다.

schema 5는 여기에 독립 repeated-call oracle을 더한다. 모든 case의 preflight,
warm-up, sample output에서 iteration과 final state를 파싱해 oracle과 비교하고,
정확한 process 수와 stdout hash를 JSON에 남긴다. autotuner screen/confirm/decide는
이 record가 없거나 값·형식·hash binding이 맞지 않으면 fail-closed한다.

schema 2의 과거 stages/alignment/codegen JSON에 있던 `random_differential_cases`는
oracle self-test 횟수였으므로 그 파일들은 공식-vector gate가 있는 성능
기록으로만 읽는다. 최종 inline/ROL JSON은 candidate 직접 PASS가 들어간
schema 3의 역사적 결과이고, schema 4는 모든 case의 exact assembly audit을
추가했다. 그러나 schema 2--4 어느 것도 timing `main`의 전체 반복 상태를
검증하지 않으므로 현재 성능 confirmation에는 schema 5만 사용한다.

## Intel Core Ultra 7 255H/GCC 13.3.0 이식 판단

Intel 제품 명세는 최종 CPU의 AVX2 지원을 명시한다. 하지만 이 문제에서는
AVX2 지원 여부보다 scalar rotate/byte-swap latency와 frontend 특성이 더
중요하며, AMD EPYC 결과를 Intel 순위로 그대로 옮길 수 없다.

문제 PDF는 추가 최적화 flag를 허용한다. GCC 13.3 실물에서 limit 700/2000이
complete binary까지 같았으므로 둘을 별도 성능 후보로 반복 측정할 필요는 없다.
2000을 incumbent로 두고 700은 release/codegen 동등성 진단에만 사용한다.

문제의 source 수정 범위는 `contest.c` 세 위치와 external helper로 제한된다.
따라서 제출 source는 추가 flag 없이도 compile되는 현재 경로를 유지한다.
저장소의 `submissions/02/run_contest.sh`는 문제에서 별도로 허용한 추가 최적화
flag를 빠뜨리지 않기 위한 재현 wrapper다. clean checkout에서는 제공 ZIP의 두
벡터만 임시 디렉터리에 풀어 검증하고 생성 binary와 벡터를 정리하며, ZIP 자체는
바꾸지 않는다. source에
특정 세대의 `arch=`를 하드코딩하는 것보다, score 실행 시 build command에서
검증된 flag만 적용하는 편이 안전하다.

최종 채택 판단은 다음 조합을 Intel 실기에서 같은 runner로 비교한다.

| source | build | 목적 |
|---|---|---|
| adaptive full-unroll | 기본 `-O3` | 호환 기준선 |
| adaptive full-unroll | `-mbmi2 -finline-limit=2000` | 현재 score incumbent |
| adaptive full-unroll | 위 flag + `-mtune=alderlake` | GCC hybrid-client schedule |
| adaptive full-unroll | 위 flag + Alder tune + IRA priority | 정적 screen 최상 schedule |
| order `2,1,0,3` full-unroll | generic/Alder/Alder+IRA | source schedule 후보 |
| adaptive/order `2,1,0,3` | Alder+IRA + selective scheduling 2 | 120.06-cycle 정적 후보 |
| adaptive/order `2,1,0,3` | Alder+IRA + post-reload scheduling off | 120.07-cycle 정적 후보 |
| four-lane two-round AVX2 | `-mavx2 -DCH2_SIMD_INLINE -finline-limit=2000` | 122-instruction/579-byte vector 기준선 |
| four-lane AVX2 + IRA region one | 위 flag + `-fira-region=one` | 569-byte distinct stream |
| commutative single-scratch AVX2 | 별도 source + 기본 AVX2 score flag | 549-byte scoped-bound stream, schema-5 AMD 동률 |
| commutative AVX2 + `DEC` | 위 source + `-mtune-ctrl=use_incdec` | 548-byte compiler-control, target-only |
| lane-wise AVX2 block 2 | 별도 source + 기본 AVX2 score flag | 136-byte/133-dynamic frontend 대조군, target-only |
| lane-wise AVX2 layout representatives | generic 4개 + Alder 3개 nonbaseline flag 조합 | 8개 배치 클래스 중 기준 제외 7개, target-only |
| adaptive full-unroll | `-mbmi2 -finline-limit=2000 -mtune=native` | target compiler 진단용 |

`autotune_02_candidates.json`은 이 후보와 portable/partial-unroll 대조군을
포함한 30-case manifest를 hash와 함께 고정한다. 먼저 `probe`와 짧은 `screen`으로 환경과 후보를
줄이고, 별도 시간대의 `confirm` 두 번을 저장한 다음 `decide`를 실행한다.

```bash
python3 solutions/02_optimization/autotune_02_255h.py probe \
  --compiler /path/to/gcc-13.3.0 --out /tmp/ch2-255h/topology.json
python3 solutions/02_optimization/autotune_02_255h.py screen \
  --topology /tmp/ch2-255h/topology.json --session screen-a \
  --out-dir /tmp/ch2-255h/screen-a
```

각 performance binary의 `main` timing loop가 선언한 assembly contract를
통과해야 하고, 서로 다른 session과 physical core representative의 결과가
모두 있어야 한다. 현재 증거로는 full-unroll + cross-call inline이 기본
score안이며, 실제 255H 결과 없이 AVX2 source나 source 순서,
tune/IRA/scheduler flag를 더하지 않는다.

## 참고 자료

- [GCC, Common Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html) — `always_inline`, `noinline`, `noclone`, `target`, `aligned`의 의미와 linker가 함수 정렬을 제한할 수 있다는 조건을 확인했다.
- [GCC, x86 Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/x86-Function-Attributes.html) — 서로 다른 target option을 가진 함수의 inlining 제한을 확인했다.
- [GCC 13.3, Optimize Options](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Optimize-Options.html) — `-finline-limit`, `-fira-algorithm`, scheduling과 PGO/LTO 후보의 정확한 의미 및 release별 heuristic 의존성을 확인했다.
- [GCC 13.3, x86 Options](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html) — `-mtune`은 ISA를 넓히지 않는다는 의미와 `alderlake` target의 존재, `arrowlake` 전용 target 부재를 확인했다.
- [de Moura and Bjørner, *Z3: An Efficient SMT Solver*, TACAS 2008](https://doi.org/10.1007/978-3-540-78800-3_24)와 [Z3 공식 publication 목록](https://www.microsoft.com/en-us/research/project/z3-3/publications/) — 64-bit bit-vector 동치와 연산 삭제 후보의 SAT/UNSAT 판정 근거다.
- [Solar-Lezama et al., *Combinatorial Sketching for Finite Programs*, ASPLOS 2006](https://people.csail.mit.edu/asolar/papers/asplos06-final.pdf) — 연산 template의 빈칸을 반례로 반복 보강하는 CEGIS식 합성 절차의 배경이다.
- [LLVM, *llvm-mca Machine Code Analyzer*](https://llvm.org/docs/CommandGuide/llvm-mca.html) — scheduling model 기반 throughput/resource-pressure 분석의 용도와 모델 정확도 한계를 확인했다.
- [Abel and Reineke, *uops.info: Characterizing Latency, Throughput, and Port Usage of Instructions on Intel Microarchitectures*, ASPLOS 2019](https://arxiv.org/abs/1810.04610) — instruction count만으로 성능을 단정하지 않고 latency, reciprocal throughput과 execution port를 분리해서 해석하는 근거다.
- [Abel and Reineke, *nanoBench: A Low-Overhead Tool for Running Microbenchmarks on x86 Systems*, 2019](https://arxiv.org/abs/1911.03282) — warm-up, serialization, counter overhead와 반복 가능한 low-level 측정 설계의 참고 자료다. 이 VM에서는 필요한 performance counter가 없어 동일 수준의 port/frequency 판정을 주장하지 않았다.
- [Intel, Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html) — AVX2 variable shift, byte shuffle와 packed addition 후보의 ISA 형태를 확인했다.
- [Intel, Intel® 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) — 9차 commutative operand-order 분석에서 VEX.vvvv, ModRM r/m과 extension-bit에 따른 실제 instruction encoding 길이를 해석한 1차 자료다.
- [Intel, Intel® 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) — loop unrolling, instruction frontend, code layout은 microarchitecture별 실측으로 결정해야 한다는 분석 기준으로 사용했다.
- [Intel, *Processors and Processor Cores Based on Skymont Microarchitecture: Instruction Throughput and Latency*](https://www.intel.com/content/www/us/en/content-details/837381/intel-processors-and-processor-cores-based-on-skymont-microarchitecture-instruction-throughput-and-latency.html) — package 이름은 Xeon 6 E-core 범위이므로 255H client E-core에 대한 수치 전이는 조건부이며, 실제 target 측정이 필요한 이유를 뒷받침한다.
- [Intel, *Processors and Processor Cores Based on Crestmont and Redwood Cove Microarchitecture: Instruction Throughput and Latency*](https://www.intel.com/content/www/us/en/content-details/825952/intel-processors-and-processor-cores-based-on-crestmont-and-redwood-cove-microarchitecture-instruction-throughput-and-latency.html) — PerfMon의 LP-E=Crestmont 설명이 맞을 때 적용할 conditional selected-row 모델과 package 한계를 재현했다.
- [Intel, Arrow Lake Performance Monitoring Events](https://perfmon-events.intel.com/platforms/arrowlake/core-events/p-core/) — Arrow Lake client를 Lion Cove P, Skymont E, Crestmont LP-E로 설명하는 공식 자료이며 아래 255H ECI 설명과 충돌하는 한쪽 근거다.
- [Intel, *Heterogeneous Computing on Intel Core Ultra 7 255H*](https://eci.intel.com/embodied-sdk-docs/content/developer_tools_tutorials/heterogeneous_computing.html) — 255H의 두 LP-E를 "additional Skymont cores"라고 설명해 PerfMon의 Crestmont 표기와 상충함을 기록했다.
- [Intel, Core™ Ultra 7 Processor 255H specifications](https://www.intel.com/content/www/us/en/products/sku/241751/intel-core-ultra-7-processor-255h-24m-cache-up-to-5-10-ghz/specifications.html) — 최종 CPU가 AVX2를 지원함을 확인했다.
- [Intel, *Game Dev Guide for 12th Gen Intel® Core™ Processor*](https://www.intel.com/content/www/us/en/developer/articles/guide/12th-gen-intel-core-processor-gamedev-guide.html) — hybrid flag와 logical CPU별 CPUID leaf `0x1a` core type, probe 중 affinity 고정이 필요한 이유를 확인했다.
- [Linux kernel, CPU topology](https://docs.kernel.org/admin-guide/cputopology.html)와 [CPU sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-devices-system-cpu) — physical package/core/thread sibling과 capacity를 교차 확인하고 서로 다른 physical representative를 선택할 때 사용했다.
- [Claude Carlet, *Boolean Functions for Cryptography and Coding Theory*](https://doi.org/10.1017/9781108606806) — 작은 table 분해를 점검할 때 사용한 algebraic normal form, degree와 finite-difference 관점의 이론적 배경이다.
- [Mytkowicz et al., *Producing Wrong Data Without Doing Anything Obviously Wrong!*](https://sape.inf.usi.ch/publications/asplos09.html) — 함수 배치와 실행 순서만으로 생기는 benchmark 편향을 통제하기 위해 separate binary, AB/BA와 reverse layout을 사용했다.
