# 6. PRNG - Dual_EC_DRBG 백도어 복원과 최적화

## 문제와 결론

문제의 생성기는 다음과 같다.

```text
s_{i+1} = X(s_i P)
r_i     = TMSB(X(s_{i+1} Q))
```

필드는 88비트이고 출력은 x좌표의 하위 16비트를 버린 상위 72비트다.
또한 `telemetry.csv`의 여섯 행은 같은 비밀 스칼라 `d`에 대한 affine
함숫값에서 하위 20비트를 버린 결과다. 복원 결과는 다음과 같다.

```text
d  = 0x1c3cdd6b221806db0a7b28
s2 = 0x638d9d631ab436da51e640
r3 = 0x2443c8daf1a9d52b09
```

기존 문서와 코드가 `0x638d...`를 `s1`이라고 쓴 것은 한 칸 어긋난
표기였다. `r0`에서 lift한 점은 `s1 Q`이고, 여기에 `d`를 곱한 점의
x좌표는 `X(s1 P)=s2`다. 최종 구현과 제출 문서에서는 `s2`로 바로잡았다.

## 1. telemetry에서 `d` 복원

### 선형 전수조사 풀이

`B=2^20`이라 하자. 첫 행 `(scale_0, offset_0, summary_0)`은 다음을
뜻한다.

```text
(scale_0*d + offset_0) mod n = summary_0*B + low
0 <= low < B
```

따라서 첫 행만으로 `2^20`개의 후보를 만들 수 있다.

```text
d(low) = ((summary_0*B + low - offset_0) * scale_0^{-1}) mod n
```

원래 구현은 후보마다 나머지 다섯 행을 검사했다. 정답은 나오지만
Python에서 약 1.45초와 `O(2^20)` modular operation이 필요했다. 후보와
둘째 행의 값을 매번 덧셈으로 갱신하는 recurrence도 구현해 곱셈은
줄였지만 탐색 횟수 자체는 그대로였다.

### `floor_sum`을 이용한 비열거 복원

첫 행의 역원을 `v=scale_0^{-1} mod n`이라 두고 `low=0`일 때 후보를
`d_0`라 하면 다음과 같다.

```text
d(low) = d_0 + low*v mod n
```

이를 둘째 행에 대입하면 하나의 modular interval 문제가 된다.

```text
(a*low + c) mod n in [L,U)

a = scale_1*v mod n
c = scale_1*d_0 + offset_1 mod n
L = summary_1*B
U = min((summary_1+1)*B, n)
```

`F(k,m,a,b)=sum_{i=0}^{k-1} floor((a*i+b)/m)`를 Euclidean recurrence로
`O(log m)`에 계산한다. 다음 indicator 항등식이 핵심이다.

```text
1[((a*i+b) mod m) >= y]
 = floor((a*i+b+m-y)/m) - floor((a*i+b)/m)
```

그러므로 prefix `k`개 중 remainder가 `y`보다 작은 항의 수는 다음처럼
계산된다.

```text
count_lt(k,y)
 = k - (F(k,m,a,b+m-y) - F(k,m,a,b))
```

`count_lt(k,U)-count_lt(k,L)`로 임의의 `low` 구간에 해가 몇 개인지 알
수 있다. 해가 없는 구간은 버리고 나머지를 반으로 나누면 모든 hit를
열거 없이 찾는다. 이 인스턴스에서 둘째 행의 hit가 하나이므로
`O(log B * log n)`이고, 찾은 후보는 마지막에 여섯 행 전체로 다시
검증한다.

```text
missing low20 = 0x1f051
d             = 0x1c3cdd6b221806db0a7b28
```

독립 warm 반복 측정에서 이 단계의 중앙값은 1,453.475ms에서 0.750ms로
줄어 약 1,938배 빨라졌다. 전체 공격에서는 타원곡선 탐색이 지배적이므로
end-to-end 개선폭은 이보다 작다.

## 2. Dual_EC 상태 복원

복원한 값은 실제 점 관계를 만족한다.

```text
P = dQ
```

`r0`의 가능한 하위 16비트를 붙여 x좌표 후보를 만든다.

```text
x = (r0 << 16) | low16
```

`x < p`이고 다음 곡선식에 제곱근이 있을 때만 점 후보가 된다.

```text
y^2 = x^3 + a*x + b mod p
```

이 점을 `R=s1 Q`라 하면 백도어 관계에서 다음을 얻는다.

```text
dR = d(s1 Q) = s1 P
s2 = X(dR)
```

이후 공개 출력으로 후보를 즉시 검사한다.

```text
r1 ?= TMSB(X(s2 Q))
s3  = X(s2 P)
r2 ?= TMSB(X(s3 Q))
s4  = X(s3 P)
r3  = TMSB(X(s4 Q))
```

`r1`은 72비트이므로 잘못된 후보가 다음 단계까지 생존할 확률은 매우
낮다. 실제로 `r1`, `r2`를 모두 재생하는 후보가 위의 `s2` 하나이고,
거기서 예측한 `r3`가 정답과 일치한다.

## 3. 타원곡선 구현 최적화

### `+y/-y` 중복 제거

같은 x좌표의 두 lift는 `R`과 `-R`이다.

```text
d(-R) = -(dR)
X(-(dR)) = X(dR)
```

이 문제의 이후 계산은 x좌표만 사용하므로 두 부호를 모두 스칼라 곱할
필요가 없다. 원래 코드는 각 유효 x마다 같은 상태와 `r1`을 두 번
계산했으며, 이 관찰만으로 해당 작업을 절반으로 줄인다.

### width-5 wNAF와 폭 재검토

원래 right-to-left double-and-add는 매 비트 doubling과 binary 1마다
generic Jacobian addition을 했다. 최적화 구현은 signed digit width-5
NAF를 사용한다. 점의 음수는 y좌표의 부호만 바꾸면 되므로 싸고, 0이
아닌 digit의 밀도가 줄어 addition 횟수가 감소한다. 각 임의 점에 대해
`P,3P,...,15P` 여덟 개를 준비한다.

실제 `d`는 85비트이고 binary popcount는 40이다. plain width-2 NAF의
nonzero digit은 27개지만, 현재 width-5 wNAF는 14개다. 다만 후보마다
`P,3P,...,15P`를 만드는 7회 addition도 필요하므로 합계는 21회다.
width-4는 nonzero 16개와 precompute 3개, 합계 19회로 이론상 더 작았다.
그러나 8-thread GMP 반복 측정에서는 width-5 0.483517초, width-4
0.494902초로 역전되어 width-4의 우위를 입증하지 못했다. Python/GMP 객체
비용과 scheduler 분산이 작은 operation-count 차이보다 컸기 때문에 현재
GMP 경로는 width-5를 유지한다.

### 고정-base byte comb

후보마다 `s2 Q`를 계산하지만 `Q`는 항상 같다. 88비트 scalar를 11개
byte로 분해하고 다음 테이블을 한 번 만든다.

```text
table[position][digit] = digit * 2^(8*position) * Q
position = 0..10, digit = 0..255
```

그 뒤 한 번의 fixed-base 곱은 88회 doubling과 수십 회 addition 대신
최대 11개 table point addition으로 끝난다. 테이블은 읽기 전용이라
C++ 병렬 worker가 함께 사용한다.

### arithmetic backend와 병렬화

최종 Python 코드는 기본 `int`만으로 동작하고, `gmpy2`가 설치되어 있으면
`auto` backend가 `mpz`를 사용한다. 별도 C++20 구현은 GMP의 `mpz_class`를
사용하고, 남은 low-16 후보를 OpenMP dynamic 64-candidate chunk로 나눈다.
정답보다 큰 index는 atomic best index를 보고 조기에 건너뛴다. build
시간은 benchmark에서 제외하지만 입력, precomputation, process startup과
전체 공격 시간은 포함한다.

GMP 경로는 알고리즘 후보를 비교하는 신뢰 가능한 기준으로 남겼다. 최고
성능 경로는 같은 수학적 공격을 유지하되 88비트 체를 고정 2-limb
Montgomery 표현으로 옮긴 `deep_native_06.cpp`다. 이 구분 덕분에
알고리즘 변화와 arithmetic/object-layout 변화의 효과를 섞지 않고 비교할
수 있다.

## 4. 알고리즘 심층 재검토와 실패한 방법

상태 복원의 남은 비용을 줄이기 위해
[`solve_06_algorithm_candidates.cpp`](../solutions/06_optimization/solve_06_algorithm_candidates.cpp)와
전용 [반복 runner](../solutions/06_optimization/benchmark_06_algorithm_candidates.py)를
만들었다. 자세한 식, 검증 및 raw protocol은
[`deep_review_06_algorithm.md`](../solutions/06_optimization/deep_review_06_algorithm.md)에
정리했다. 아래 값은 8-thread, warm-up 1회 뒤 5회 측정한 state-recovery
중앙값이다. 이 구간은 self-test, telemetry 복원과 process startup을 제외한
`state_seconds`이며, build는 `-O3 -DNDEBUG -std=c++20 -fopenmp`, GMP 6.2.1을
사용했다. 매 round에는 후보 순서를 cyclic rotation했다.

기준 implementation이 정답 low bits `0x5338`에 도달하기 전 관측한 hot path는
curve 위 x후보 10,690개, affine inversion 21,380회, point doubling 898,148회,
point addition 344,486회였다. 이 계측을 기준으로 아래 12개 경로를 모두
측정했다.

| 후보 | 중앙값 | 표준편차 | 기준 대비 |
|---|---:|---:|---:|
| 기존 width-5 | 0.486286 s | 0.059031 s | 1.000x |
| scalar w5, 기본 | 0.483517 s | 0.046498 s | 1.006x |
| scalar w5, Legendre | 0.490778 s | 0.051460 s | 0.991x |
| scalar w4, 기본 | 0.494902 s | 0.038164 s | 0.983x |
| scalar w4, Legendre | 0.493416 s | 0.043990 s | 0.986x |
| batch w3, block 32 | 0.519042 s | 0.037902 s | 0.937x |
| batch w4, block 32 | 0.484463 s | 0.047953 s | 1.004x |
| batch w5, block 32 | 0.491504 s | 0.046052 s | 0.989x |
| batch w4, direct cubic | 0.488690 s | 0.039137 s | 0.995x |
| batch w4, Legendre 없음 | 0.475473 s | 0.044612 s | 1.023x |
| x-only, residue 검사 지연 | 1.003282 s | 0.082780 s | 0.485x |
| x-only, Legendre 선필터 | 0.516119 s | 0.057353 s | 0.942x |

### Brier--Joye X/Z-only ladder

`y`와 sqrt를 생략하기 위해 affine x를 `(X:Z)`, `x=X/Z`로 나타내고
`(R0,R1)=(P,2P)`, `R1-R0=P` invariant를 유지했다. 사용한 differential
addition/doubling은 다음 식이다.

```text
X(P+Q) = (X1*X2-a*Z1*Z2)^2
         - 4*b*Z1*Z2*(X1*Z2+X2*Z1)
Z(P+Q) = x(P-Q)*(X1*Z2-X2*Z1)^2

X(2P) = (X1^2-a*Z1^2)^2 - 8*b*X1*Z1^3
Z(2P) = 4*Z1*(X1^3+a*X1*Z1^2+b*Z1^3)
```

`dQ=P`와 실제 curve lift 8개를 기존 Jacobian 결과와 대조해 정확성을
확인했다. 그러나 원 식은 scalar bit마다 대략 `14M`과 constant multiply
5회가 들고, residue 검사를 미루면 비잔여까지 21,305개 x에 전체 ladder를
실행한다. 그 결과 기준보다 약 2.06배 느렸다. Legendre 선필터도 0.516119초로
기준을 넘지 못했다. Hamburg의 후속 `8M+3S+7A` 식은 exceptional-point
처리를 포함하는 별도 formula set이 필요해 후속 연구 후보로만 남겼다.

### Batch inversion과 연속 cubic

block마다 `sqrt/lift -> dR projective -> batch affine s2 -> fixed-Q
projective -> batch affine r1`의 두 단계 pipeline을 만들었다. prefix product와
reverse sweep으로 원소 `m`개의 역원을 inversion 1회와 `3m-3` multiply로
계산하고, zero denominator는 index에서 제외했다. buffer는 OpenMP thread마다
한 번 만들고 재사용했다. 하지만 88비트 `mpz_invert`가 이미 싸서
`mpz_class` temporary, multiplication과 memory traffic이 절감분을 상쇄했다.

연속 x의 `f(x)=x^3+a*x+b`에는 다음 finite difference를 적용했다.

```text
f  += d1
d1 += d2
d2 += 6
```

256개 연속 값을 direct cubic과 대조했다. 곱셈 두 번 대신 modular
addition/reduction 세 번이 생기며, 0.484463초 대 direct 0.488690초의 차이는
분산보다 작았다.

### Legendre, wNAF 폭과 실행 순서

Legendre 선필터의 직교 비교도 모두 동률 이하였다.

| scalar 경로 | Legendre 없음 | Legendre 있음 |
|---|---:|---:|
| width-5 | 0.483517 s | 0.490778 s |
| width-4 | 0.494902 s | 0.493416 s |

실제 `d`에 대해 nonzero digit과 후보별 odd-multiple precompute를 합친
addition 수는 다음과 같다.

| wNAF width | nonzero digit | precompute | 합계 |
|---:|---:|---:|---:|
| 2 | 27 | 0 | 27 |
| 3 | 21 | 1 | 22 |
| 4 | 16 | 3 | 19 |
| 5 | 14 | 7 | 21 |
| 6 | 12 | 15 | 27 |

연산 수로는 width-4가 최소지만 실제 GMP 반복에서는 width-5보다 느렸다.
`r1`을 유일한 강한 early filter로 사용하고 `r2/r3` 계산은 hit 뒤로 미뤘다.
low 16비트 탐색을 정답 `0x5338` 주변부터 시작하는 것은 답 hardcode라
제외했다. telemetry recurrence는 곱셈을 덧셈으로 바꿔도 `2^20`회 순회가
남았고, `gmpy2`만 적용한 Python과 병렬화만 적용한 경로도 interpreter 또는
중복 scalar multiplication 병목이 남아 최종안이 되지 못했다.

## 5. native arithmetic와 캐시/micro 최적화

알고리즘 후보가 GMP 기준을 안정적으로 넘지 못한 뒤, hot path의 표현과
메모리 이동을 별도로 검토했다. 구현·ablation·raw sample은
[`deep_review_06_micro.md`](../solutions/06_optimization/deep_review_06_micro.md),
반복 측정기는
[`benchmark_deep_native_06.py`](../solutions/06_optimization/benchmark_deep_native_06.py)에
정리했다.

원본의 별도 `cProfile` run은 총 22.432초였고 `scalar_mul` 19.892초,
telemetry brute force 1.836초였다. 정답 전까지 `modp`는 14,445,392회
호출됐다. analytic telemetry 이후에는 작은 field의 point arithmetic와
임시 객체가 지배적이라는 뜻이다. GMP control도 1/2/4/8 thread에서 각각
1.7807/1.0456/0.6456/0.4581초로 scaling했지만 general-purpose limb와
`mpz_class` 객체 비용은 남았다.

### 고정폭 Montgomery 체와 POD point

`p`는 88비트이므로 field element를 16바이트 두 limb에 넣고
`R=2^128`인 Montgomery REDC를 `uint64_t`와 `unsigned __int128`로
구현했다. hot path에는 division, GMP call, heap allocation이 없다.
Jacobian point도 `(X,Y,Z)` 세 field인 48바이트 POD다. 역원은 고정 크기
canonical 값의 binary extended GCD가 Fermat `a^(p-2)`보다 빨랐고,
`p=3 mod 4` 제곱근은 고정 지수 `(p+1)/4`의 width-4 sliding window를
사용했다.

Barrett reduction도 검토했지만 88x88→176비트 product의 상위 word와
quotient 근사를 다시 처리해야 했다. 이 크기에서는 두 word REDC가 더 짧고
검증하기 쉬웠다. 제곱근 지수는 86비트, popcount 49다. binary 방식의 약
48회 후속 multiply를 width-4 odd-power table과 약 18개 window로 바꿔
대략 25--26 multiply까지 줄였다.

이 선택은 Cython wrapper만 씌우는 것보다 큰 범위의 병목을 제거한다.
Python 호출 경계를 넘기는 것뿐 아니라 `mpz_class` temporary, general
limb 관리, point 객체 할당까지 동시에 사라지기 때문이다. 반대로
검증 가능한 의존성 없는 풀이로는 기존 Python 구현을 계속 제공한다.

### affine comb table과 mixed addition

11x256 고정-`Q` table을 한 번 batch-normalize한 뒤 affine `(x,y)`로
저장했다. native 기준 Jacobian table은 135,168바이트지만 affine table은
90,112바이트여서 정확히 1/3 작다. 각 row를 64바이트 경계에 맞추고 모든
thread가 read-only로 공유한다. query에서는 generic Jacobian addition
대신 EFD의 `madd-2007-bl` mixed addition을 사용해 공개 operation count를
`11M+5S`에서 `7M+4S`로 줄였다.

임의 lift에 대한 `dR`은 per-candidate odd-multiple table을 만들지 않는
width-2 NAF와 mixed addition을 쓴다. 넓은 wNAF는 digit 수는 줄지만 매
후보의 table 구축·정규화 비용이 더 컸다. 고정점과 임의점에 서로 다른
전략을 쓰는 것이 핵심이다.

### 스케줄링, batch inversion과 SIMD 검토

atomic counter가 낮은 값부터 연속 64-candidate block을 배정한다. 아직
배정되지 않은 block이 현재 최선의 low bits 이상이면 즉시 멈추므로 정적
분할의 불필요한 tail work를 피한다. 1 thread에서는 block의 affine 변환을
batch inversion하는 경로가 scalar보다 약 6% 빨랐지만, 8 threads에서는
thread-local stack traffic과 추가 multiply 때문에 scalar가 약 6%
빨랐다. `adaptive`는 이 측정에 따라 1 thread에서 `block`, 2 threads
이상에서 `scalar`를 고른다.

| scheduler 경로 | 1 thread | 8 threads |
|---|---:|---:|
| block batch | 0.386404 s | 0.082014 s |
| scalar | 0.410719 s | 0.077461 s |

inverse와 sqrt 구현도 네 조합을 모두 known-answer 검증한 뒤 비교했다.

| inverse | sqrt | 1 thread | 8 threads |
|---|---|---:|---:|
| binary GCD | window-4 | 0.408371 s | 0.077916 s |
| binary GCD | binary | 0.395508 s | 0.079889 s |
| Fermat | window-4 | 0.429445 s | 0.088159 s |
| Fermat | binary | 0.423692 s | 0.089331 s |

절대값은 최종 batch pipeline 전 별도 ablation이므로 행/열의 방향만 비교했다.
Binary GCD는 일관되게 이겼다. Window-4 sqrt는 1-thread noise에서는 뒤집혔지만
8-thread 결과와 operation count를 근거로 기본값으로 유지했다.

### micro 단계에서 실패하거나 보류한 방법

**Fermat inverse.** Montgomery domain 안에서 단순하게 구현할 수 있지만
affine conversion마다 약 88회 square와 여러 multiply를 수행해 binary GCD보다
느렸다.

**모든 thread의 batch inversion.** Inversion 수는 줄지만 prefix/reverse
multiply와 thread-local stack traffic이 추가된다. Binary GCD가 싸진 뒤에는
1 thread에서만 이겼고 8 threads에서는 scalar 경로가 더 빨랐다.

**넓은 arbitrary-point wNAF.** Width-4/5는 digit 수를 줄이지만 lift마다
odd-multiple table을 만들고 affine 정규화 또는 generic addition을 해야 한다.
따라서 임의점에는 width-2 mixed NAF, 한 번만 구축하는 고정점 `Q`에는 큰
byte-comb를 서로 다르게 적용했다.

**Native Legendre 선필터.** 별도 exponentiation으로 residue를 확인하면 바로
sqrt를 계산하는 것보다 작업이 중복된다. GMP에서는 후보로 측정했지만 native
기본 경로에는 넣지 않았다.

AVX2도 검토했지만 현재 REDC가 요구하는 packed 64x64→128 정수 곱이 없다.
32비트 radix로 바꾸면 cross-term, shuffle, lane carry가 늘고 residue 분기
뒤 lane compaction도 필요하다. 이미 후보 단위 OpenMP 병렬성이 잘
작동하는 이 88비트 workload에는 이식성과 검증 비용을 상쇄할 근거가
없어 구현하지 않았다. AVX-512 IFMA52가 있는 별도 target이라면 radix-44/52
multi-buffer 구현을 다시 비교할 수 있다.

## 6. 정확성 검증

검증 범위는 runner별로 명시했다.

- 알고리즘 후보 runner는 측정 전에 x-only 실제 lift 8개와 finite-difference
  256개를 reference와 대조하고, 매 sample의 `d`, `s2`, `state_label`, `r3`를
  검사한다.
- 공용 runner는 모든 구현의 `d`, `s2`, `r3`를 검사하며 solver가 제공하면
  `P == dQ`도 확인한다.
- deep-native runner는 GMP/native에서 정답 lift low bits까지 검사한다. 원본
  Python은 low bits를 출력하지 않으므로 `P == dQ`, `d`, `s2`, `r3`를 검사한다.
- native preflight는 독립 canonical U128 연산과 affine reference를 사용해
  deterministic field 2,000개와 point/scalar 256개를 대조한다.

최종 Python 실행 예:

```text
backdoor scalar d = 0x1c3cdd6b221806db0a7b28
P == d*Q: True
recovered state s2 = 0x638d9d631ab436da51e640
predicted r3 = 0x2443c8daf1a9d52b09
```

Binary-GCD/Fermat inverse,
binary/window-4 sqrt, NAF/mixed multiplication과 fixed comb가 모두 이
교차 검증을 통과해야 timing을 시작한다. 이는 challenge용 correctness
검사이며 secret scalar를 위한 constant-time 구현을 뜻하지는 않는다.

## 7. 반복 benchmark

`solutions/benchmark_06_prng.py`는 다음 protocol을 사용한다.

- 각 구현을 먼저 1회 완전히 실행해 warm-up 표본을 버린다.
- 구현마다 완전한 end-to-end 실행을 5회 측정한다.
- 매 round 실행 순서를 cyclic rotation하고, contender 수를 넘겨 다음 rotation
  cycle에 들어가면 reverse하도록 구현했다. 최종 5-contender/5-sample
  캠페인은 정확히 첫 rotation 집합을 한 번 사용해 reverse 분기에는 도달하지
  않았다.
- 모든 표본에서 `d`, `s2`, `r3`를 검사한다.
- raw sample, median, MAD, p05/p95, min/max, 같은 round의 paired speedup과
  내부 telemetry/state 시간을 JSON으로 보존한다.
- C++ build는 임시 디렉터리에서 한 번 수행하고 timed region에서 제외한다.

공용 runner의 현재 기본 목록은 원본, Python `int`/`gmpy2`, GMP 1/auto,
native 1/auto adaptive의 7개다. 5회 실행이면 이 runner도 reverse 구간에
도달하지 않는다. 아래의 과거 5행 language/backend 표를 정확히 다시 만들
때에는 `--implementations`로 해당 다섯 경로를 명시해야 한다. OpenMP 환경은
`OMP_DYNAMIC=FALSE`, `OMP_PROC_BIND=SPREAD`, `OMP_PLACES=THREADS`로 고정했다.

측정 환경은 AMD EPYC 7B12 VM, 8 logical CPU, Python 3.11.2, G++ 12.2.0이다.
먼저 언어/backend 단계별 효과를 확인한 캠페인은 다음과 같다.

| 구현 | end-to-end 중앙값 | 중앙값 비율 | paired 중앙값 |
|---|---:|---:|---:|
| 기존 Python | 14.298741 s | 1.00x | 1.00x |
| 최적화 Python `int` | 3.272242 s | 4.37x | 4.41x |
| 최적화 Python `gmpy2` | 3.000356 s | 4.77x | 4.61x |
| C++/GMP 1 thread | 1.873220 s | 7.63x | 7.44x |
| C++/GMP/OpenMP 8 threads | 0.447919 s | 31.92x | 30.75x |

8-thread 표본의 중앙값은 0.447919초, MAD는 0.022003초(4.91%)였고
paired p05--p95는 25.21x--33.48x였다. 앞선 독립 캠페인도 0.445551초와
31.76x를 기록해 같은 규모를 재현했다. 이 VM은 다른 작업과 공유되므로
절대값보다 warm-up 이후 raw sample과 강건 통계를 함께 본다.

native 최종 수치는 원본 Python, 같은 thread 수의 GMP와 native를 하나의
cyclic-rotation 실행 순서에 넣어 다시 측정했다. 따라서 서로 다른 부하의
run을 나눈 값이 아니다.

| 구현 | end-to-end 중앙값 | MAD | 중앙값 비율 |
|---|---:|---:|---:|
| 기존 Python | 14.073190 s | 0.295610 s | 1.00x |
| C++/GMP 1 thread | 1.971840 s | 0.048047 s | 7.14x vs Python |
| native adaptive 1 thread | 0.362651 s | 0.009200 s | 38.81x vs Python; 5.44x vs GMP |
| C++/GMP/OpenMP 8 threads | 0.436403 s | 0.007239 s | 32.25x vs Python |
| native adaptive 8 threads | 0.085076 s | 0.006915 s | 165.42x vs Python; 5.13x vs GMP |

같은 round의 native/GMP paired speedup 중앙값은 각각 5.31x와 5.34x였다.
8-thread native MAD는 8.13%로 host load 영향이 보이지만, 가장 느린 native
표본도 가장 빠른 GMP 표본보다 4배 이상 빨랐다. 서로 다른 캠페인을 섞어
계산하면 더 큰 수치가 나오지만 최종 주장에는 같은-run의 165.42x만 쓴다.

최종 표의 외부 wall-clock raw sample은 다음과 같다.

```text
python-original = [13.777580, 14.396470, 13.622788, 14.138053, 14.073190]
gmp-1t          = [ 1.983506,  1.971840,  2.041384,  1.923793,  1.817540]
native-1t       = [ 0.380280,  0.356095,  0.384722,  0.353451,  0.362651]
gmp-8t          = [ 0.427484,  0.440208,  0.454003,  0.436403,  0.429163]
native-8t       = [ 0.075537,  0.096514,  0.085076,  0.078161,  0.089694]
```

서로 다른 run의 기존 Python 14.298741초와 native 0.077461초를 나누면
184.6x지만 host 부하가 달라 최종 수치로 폐기했다. JSON에는 raw sample 외에
`telemetry/precompute/scan/state/total` stage, field/point/table 크기,
requested/effective schedule, build command와 paired speedup을 함께 보존한다.

재현 명령:

```bash
python3 solutions/solve_06_prng.py --backend int --telemetry analytic

python3 solutions/benchmark_06_prng.py \
  --warmup 1 --repetitions 5 \
  --output /tmp/challenge06-benchmark.json

python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 5 --threads 1,8 \
  --native-schedules adaptive --include-original-python \
  --output /tmp/challenge06-native.json
```

C++만 직접 실행하려면:

```bash
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/solve_06_gmp.cpp \
  -lgmpxx -lgmp -o /tmp/solve_06_gmp
/tmp/solve_06_gmp --threads 8 --telemetry analytic

g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06
/tmp/deep_native_06 --self-test
/tmp/deep_native_06 --threads 8 --schedule adaptive --json
```

## 8. 계산 복잡도와 메모리

- telemetry: 둘째 행 interval hit가 하나인 이 인스턴스에서
  `O(log B * log n)`, `B=2^20`; 마지막 여섯 행 검증은 상수 시간이다.
  일반적으로 hit가 `h`개면 구간 분할 비용이 `h`에 비례한다.
- 상태 복원: 최악 `2^16` x후보에 대해 제곱근과 `O(log n)` arbitrary-point
  multiplication이 필요하므로 work는 여전히 `O(2^16 log n)`이다. `w`
  worker의 이상적 wall time은 대략 `1/w`이나 precomputation과 scheduling
  overhead가 있다.
- fixed-base table: GMP 기준은 11x256 Jacobian point이고, native 최종안은
  90,112바이트의 11x256 affine point다. 구축 시 약 2,805회 addition과
  한 번의 batch normalization이 필요하며 각 query는 최대 11회 mixed
  addition이다.
- 그 밖의 탐색 메모리는 worker마다 상수 크기 point 상태만 필요하다.

### 제한과 이식성

- native 구현은 GNU/Clang 계열의 `unsigned __int128`과 OpenMP가 필요하다.
- `-march=native`로 얻은 절대 시간은 다른 CPU와 직접 비교할 수 없다.
- 90KB affine table은 현재 host cache에는 맞지만 private cache가 작은 target은
  4-bit fixed-window 같은 작은 table과 다시 비교해야 한다.
- 이 코드는 공개 challenge input을 찾는 공격 구현이며 constant-time production
  ECC library가 아니다.
- 생성 binary와 JSON report는 `/tmp`에만 만들고 repository에는 source,
  문서와 작은 raw text만 남겼다.

## 제출 파일

- `submissions/06/01_answer.txt`: 예측한 `r3`
- `submissions/06/02_method.md`: 제출용 압축 분석 문서
- `solutions/solve_06_prng.py`: 의존성 없는 fallback을 포함한 최종 Python 풀이
- `solutions/06_optimization/solve_06_gmp.cpp`: 알고리즘 비교용 C++/GMP 기준
- `solutions/06_optimization/deep_native_06.cpp`: 최고 성능 native C++/OpenMP 풀이

## 참고 자료와 활용

- [NIST SP 800-90 Rev. 1 (withdrawn)](https://csrc.nist.gov/pubs/sp/800/90/r1/final) — 상태 갱신, 두 공개 점과 truncated output이라는 Dual_EC 구조를 대조했다.
- [Shumow and Ferguson, *On the Possibility of a Back Door in the NIST SP800-90 Dual EC PRNG*](https://rump2007.cr.yp.to/15-shumow.pdf) — 출력의 누락 비트를 lift하고 숨은 점 관계로 다음 상태를 얻는 공격의 원형이다.
- [AtCoder Library `floor_sum` 공식 문서](https://atcoder.github.io/ac-library/production/document_en/math.html), [공식 구현](https://github.com/atcoder/ac-library/blob/master/atcoder/internal_math.hpp), [공식 유도](https://atcoder.jp/contests/practice2/editorial/579) — Euclidean floor-sum recurrence와 `O(log n)` 복잡도의 근거다. 여기서는 86비트 modulus이므로 같은 recurrence를 arbitrary-precision 정수로 옮겼다.
- [Explicit-Formulas Database, short-Weierstrass Jacobian coordinates](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html) — Jacobian double/add 공식과 operation count를 점 연산 구현·후보 비교에 사용했다.
- [Cohen, Miyaji, Ono, *Efficient Elliptic Curve Exponentiation Using Mixed Coordinates*](https://dspace.jaist.ac.jp/dspace/handle/10119/4458?locale=en) — coordinate 선택과 mixed addition 최적화 검토의 원 논문이다.
- [Morain and Olivos, *Speeding up the computations on an elliptic curve using addition-subtraction chains*](https://www.numdam.org/item/ITA_1990__24_6_531_0/) — signed digit/NAF로 point addition 수를 줄이는 근거다.
- [Brier and Joye, *Weierstrass Elliptic Curves and Side-Channel Attacks*](https://marcjoye.github.io/papers/BJ02espa.pdf) — 일반 Weierstrass 곡선에서 x-only ladder 후보를 검토할 때 사용했다.
- [Hamburg, *Faster Montgomery and double-add ladders for short Weierstrass curves*](https://eprint.iacr.org/2020/437) — Brier--Joye 이후의 더 낮은 operation count와 exceptional-point 조건을 대조했다.
- [Montgomery, *Speeding the Pollard and Elliptic Curve Methods of Factorization*](https://doi.org/10.1090/S0025-5718-1987-0866113-7) — differential ladder와 inversion amortization의 원형을 확인했다.
- [Bernstein et al., *OpenSSLNTRU: Faster post-quantum TLS key exchange*](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf) — prefix/reverse batch inversion의 `3n-3` multiplication과 1 inversion 비용을 확인했다.
- [Montgomery, *Modular Multiplication Without Trial Division*](https://doi.org/10.1090/S0025-5718-1985-0777282-X) — 고정 2-limb REDC와 Montgomery residue 표현의 근거다.
- [GNU MP Manual, Number Theoretic Functions](https://gmplib.org/manual/Number-Theoretic-Functions)과 [OpenMP 5.2 Specification](https://www.openmp.org/spec-html/5.2/openmp.html) — `mpz_invert`/`mpz_legendre`와 병렬 search의 구현 기준이다.
- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html) — AVX2에 packed 64x64→128 정수 곱이 없음을 확인했다.
- [Mytkowicz et al., *Producing Wrong Data Without Doing Anything Obviously Wrong!*](https://sape.inf.usi.ch/publications/asplos09.html), [Google Benchmark User Guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md), [NIST Measures of Scale](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm) — 순서 교차, 반복 표본, raw data 보존과 MAD 보고라는 측정 방법의 근거다.
