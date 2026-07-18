# 2번 심층 최적화 재검토

## 결론

현재의 `BMI2 + 2-round + scalar full-unroll + 64-byte alignment` 구현은
구조적으로도, 생성된 기계어의 dependency depth 측면에서도 이미 강한 기준선이다.
AMD VM에서 더 작은 `unroll5_bmi2`가 한 세션에서는 paired median 기준
`1.0867x` 빨랐지만, 같은 조건의 즉시 재측정에서는 `0.9712x`로 역전됐다.
`-march=native` 세션에서도 `0.9214x`로 full-unroll이 우세했다. 따라서
unroll5는 최종 Intel 채점기에서 반드시 A/B할 유망 후보이지만, 현재 구현을
대체할 보편적 승자로 볼 수는 없다.

현재 권장 순서는 다음과 같다.

1. 제출 기본안은 1,267-byte full-unroll BMI2 helper와 64-byte alignment를 유지한다.
2. Intel Core Ultra 7 255H/GCC 13.3.0에서 715-byte unroll5 후보를 같은 paired
   harness로 다시 측정한다.
3. 서로 다른 두 세션에서 paired median이 모두 `1.02x` 이상이고 MAD가 충분히
   작을 때에만 unroll5로 교체한다.
4. one-state AVX2, sequential-chain 배치, 상수 literal 내장, alignment 16/32/128은
   채택하지 않는다.

전체 원시 측정값은 [deep_results_02.txt](deep_results_02.txt)에 보존했다.

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
본문을 만들었고 paired 결과도 `1.0051x`로 동률이었다. 반면 실제 수정 제약을
모델링한 다음 형태는 GCC에서 5-byte tail jump로 축약됐다.

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

## Intel Core Ultra 7 255H/GCC 13.3.0 이식 판단

Intel 제품 명세는 최종 CPU의 AVX2 지원을 명시한다. 하지만 이 문제에서는
AVX2 지원 여부보다 scalar rotate/byte-swap latency와 frontend 특성이 더
중요하며, AMD EPYC 결과를 Intel 순위로 그대로 옮길 수 없다.

문제 PDF는 추가 최적화 flag를 허용한다. 조직위가 실제 build command 변경도
허용한다면 채점기 자체에서 다음 두 build를 모두 비교할 가치가 있다.

```bash
gcc -O3 ...
gcc -O3 -march=native ...
```

`-march=native`는 채점 CPU에서 compile하고 같은 CPU에서 실행할 때 ISA와 tuning을
함께 맞춘다. ISA 활성화를 보수적으로 유지하려면 함수별 `target("bmi2")`와
`-mtune=native` 조합도 비교할 수 있다.

다만 문제의 수정 가능 범위는 `contest.c` 세 위치와 external helper로 제한되어
있고 `run_contest.sh` 수정 권한은 명시적으로 분명하지 않다. 따라서 최종 코드는
추가 flag 없이도 compile되는 현재 경로를 반드시 유지해야 한다. source에 특정
세대의 `arch=`를 하드코딩하는 것보다, 허용될 때 build command에서 native
tuning을 적용하는 편이 안전하다.

최종 채택 판단은 다음 네 조합을 Intel 실기에서 같은 runner로 비교한다.

| core | build |
|---|---|
| full-unroll BMI2 align64 | 기본 `-O3` |
| unroll5 BMI2 align64 | 기본 `-O3` |
| full-unroll BMI2 align64 | `-O3 -march=native` |
| unroll5 BMI2 align64 | `-O3 -march=native` |

현재 증거만으로는 full-unroll을 기본안으로 유지하는 것이 가장 보수적이다.

## 참고 자료

- [GCC, Common Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/Common-Attributes.html) — `always_inline`, `noinline`, `noclone`, `target`, `aligned`의 의미와 linker가 함수 정렬을 제한할 수 있다는 조건을 확인했다.
- [GCC, x86 Function Attributes](https://gcc.gnu.org/onlinedocs/gcc/x86-Attributes.html) — 서로 다른 target option을 가진 함수의 inlining 제한을 확인했다.
- [Intel, Intel® 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) — loop unrolling, instruction frontend, code layout은 microarchitecture별 실측으로 결정해야 한다는 분석 기준으로 사용했다.
- [Intel, Core™ Ultra 7 Processor 255H specifications](https://www.intel.com/content/www/us/en/products/sku/241751/intel-core-ultra-7-processor-255h-24m-cache-up-to-5-10-ghz/specifications.html) — 최종 CPU가 AVX2를 지원함을 확인했다.
