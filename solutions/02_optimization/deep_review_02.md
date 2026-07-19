# 2번 심층 최적화 재검토

## 결론

현재의 `BMI2 + 2-round + scalar full-unroll` 연산 본문은 여전히 가장 강한
구현이다. 이번 재검토에서 본문을 다른 알고리즘으로 줄이지는 못했지만, 같은
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
   다시 추측하는 것이 아니라 generic, `-mtune=alderlake`, 그리고 Alder tune에
   IRA priority를 더한 세 schedule의 실제 성능 순위를 판정하는 것이다.
4. one-state SIMD, partial unroll, table, 수동 재스케줄링은 target에서 두
   독립 세션 모두 유의한 차이를 보이지 않는 한 채택하지 않는다.

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
승격하지 않고 255H의 우선 후보로만 남긴다. 실제 schema-4 원시는
[CPU 0](gcc133_schedule_results_02_cpu0.json)과
[CPU 4](gcc133_schedule_results_02_cpu4.json)에 있다.

```bash
python3 solutions/02_optimization/screen_gcc133_schedules_02.py \
  --json /tmp/challenge02-gcc133-schedule-screen.json
```

### 상수와 좌표계 축의 종결

XOR를 BSWAP 뒤 또는 rotate 앞으로 옮긴 두 표현은 임의 상수까지 포함한
100,000건 검증을 통과했다. 후보를 정확히 재생성한 뒤 schema 4와 실측 binary
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
이 1,000-call smoke의 timing 값은 성능 근거로 사용하지 않는다.
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
현재 schema 4는 reference oracle self-test와 candidate 검증을 분리한다. 각
`contest.c`를 `main`만 rename한 object로 만들고
[`verify_contest_candidate_02.c`](verify_contest_candidate_02.c)에 별도로
link하여, candidate의 public 1/20-round 함수를 무작위 상태와 무작위 상수로
직접 호출한다. `--audit-mode`를 지정한 case는 정확히 timing할 complete
executable을 `default-call-allowed`, `full-inline-320`,
`portable-inline-320` 중 해당 assembly contract로 감사하고, 이를 통과한
artifact만 warm-up과 timing에 사용한다. 권장 명령과 autotuner manifest는 모든
case에 mode를 명시하므로 correctness용 object와 performance binary가 달라
생기는 검증 공백도 닫는다. verifier reference TU에는 candidate의 전처리/target
flag를 적용하지 않으며, `-fwhole-program`처럼 candidate object 검증에 별도
override가 필요하면 autotuner 승격 대상에서 제외한다.

schema 2의 과거 stages/alignment/codegen JSON에 있던 `random_differential_cases`는
oracle self-test 횟수였으므로 그 파일들은 공식-vector gate가 있는 성능
기록으로만 읽는다. 최종 inline/ROL JSON은 candidate 직접 PASS가 들어간
schema 3의 역사적 결과이고, 이후 권장 측정은 모든 case에 assembly audit를
지정한 schema 4를 사용한다.

## Intel Core Ultra 7 255H/GCC 13.3.0 이식 판단

Intel 제품 명세는 최종 CPU의 AVX2 지원을 명시한다. 하지만 이 문제에서는
AVX2 지원 여부보다 scalar rotate/byte-swap latency와 frontend 특성이 더
중요하며, AMD EPYC 결과를 Intel 순위로 그대로 옮길 수 없다.

문제 PDF는 추가 최적화 flag를 허용한다. GCC 13.3 실물에서 limit 700/2000이
complete binary까지 같았으므로 둘을 별도 성능 후보로 반복 측정할 필요는 없다.
2000을 incumbent로 두고 700은 release/codegen 동등성 진단에만 사용한다.

다만 문제의 수정 가능 범위는 `contest.c` 세 위치와 external helper로 제한되어
있고 `run_contest.sh` 수정 권한은 명시적으로 분명하지 않다. 따라서 최종 코드는
추가 flag 없이도 compile되는 현재 경로를 반드시 유지해야 한다. source에 특정
세대의 `arch=`를 하드코딩하는 것보다, 허용될 때 build command에서 native
tuning을 적용하는 편이 안전하다.

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
| adaptive full-unroll | 위 flag + `-mtune=native` | target compiler 진단용 |

`autotune_02_candidates.json`은 이 후보와 portable/partial-unroll 대조군을
manifest hash와 함께 고정한다. 먼저 `probe`와 짧은 `screen`으로 환경과 후보를
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
score안이며, 실제 255H 결과 없이 source 순서나 tune/IRA/scheduler
flag를 더하지 않는다.

## 참고 자료

- [GCC, Common Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html) — `always_inline`, `noinline`, `noclone`, `target`, `aligned`의 의미와 linker가 함수 정렬을 제한할 수 있다는 조건을 확인했다.
- [GCC, x86 Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/x86-Function-Attributes.html) — 서로 다른 target option을 가진 함수의 inlining 제한을 확인했다.
- [GCC 13.3, Optimize Options](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Optimize-Options.html) — `-finline-limit`, `-fira-algorithm`, scheduling과 PGO/LTO 후보의 정확한 의미 및 release별 heuristic 의존성을 확인했다.
- [GCC 13.3, x86 Options](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html) — `-mtune`은 ISA를 넓히지 않는다는 의미와 `alderlake` target의 존재, `arrowlake` 전용 target 부재를 확인했다.
- [LLVM, *llvm-mca Machine Code Analyzer*](https://llvm.org/docs/CommandGuide/llvm-mca.html) — scheduling model 기반 throughput/resource-pressure 분석의 용도와 모델 정확도 한계를 확인했다.
- [Intel, Intel® 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) — loop unrolling, instruction frontend, code layout은 microarchitecture별 실측으로 결정해야 한다는 분석 기준으로 사용했다.
- [Intel, Core™ Ultra 7 Processor 255H specifications](https://www.intel.com/content/www/us/en/products/sku/241751/intel-core-ultra-7-processor-255h-24m-cache-up-to-5-10-ghz/specifications.html) — 최종 CPU가 AVX2를 지원함을 확인했다.
- [Intel, *Game Dev Guide for 12th Gen Intel® Core™ Processor*](https://www.intel.com/content/www/us/en/developer/articles/guide/12th-gen-intel-core-processor-gamedev-guide.html) — hybrid flag와 logical CPU별 CPUID leaf `0x1a` core type, probe 중 affinity 고정이 필요한 이유를 확인했다.
- [Linux kernel, CPU topology](https://docs.kernel.org/admin-guide/cputopology.html)와 [CPU sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-devices-system-cpu) — physical package/core/thread sibling과 capacity를 교차 확인하고 서로 다른 physical representative를 선택할 때 사용했다.
- [Claude Carlet, *Boolean Functions for Cryptography and Coding Theory*](https://doi.org/10.1017/9781108606806) — 작은 table 분해를 점검할 때 사용한 algebraic normal form, degree와 finite-difference 관점의 이론적 배경이다.
- [Mytkowicz et al., *Producing Wrong Data Without Doing Anything Obviously Wrong!*](https://sape.inf.usi.ch/publications/asplos09.html) — 함수 배치와 실행 순서만으로 생기는 benchmark 편향을 통제하기 위해 separate binary, AB/BA와 reverse layout을 사용했다.
