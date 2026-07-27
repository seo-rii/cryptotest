# 6. PRNG - Dual_EC_DRBG 백도어 복원과 최적화

## 현재 구현 상태

- 정답 `r3`, 복원한 `d`, `s2/s3`와 원래 곡선의 점 관계는 확정했다.
- 최종 native source는 `solutions/06_optimization/deep_native_06.cpp`다.
  범용 carry loop 대신 고정 2-limb Montgomery REDC를 사용하고, 임의점
  scan은 원곡선과 교차 검증되는 동형 `a=-3` 곡선에서 수행한다. lift의
  제곱잉여 여부는 Montgomery residue의 hybrid 128/64비트 Jacobi symbol로
  판정하고, 이어서 x-only Frobenius--Tate trace로 cofactor-5 부분군을
  선별한다. Hamburg exceptional fallback에서만 실제 제곱근을 구한다.
- field 2,000개, 경계 pair 64개, point/table 256개와 실제 lift 128개의
  Hamburg/NAF 및 scalar/batched subgroup self-test, known-answer 전체
  실행을 timing 전에 통과해야 한다.
- adaptive scheduler는 1 thread에서 block 64, 2 threads에서 block 32,
  3 threads 이상에서 scalar 64를 선택한다. 2-thread 정책은 고정 CPU의
  40-pair 승격 gate를 통과했다.
- 현재 VM의 순위는 Core Ultra 7 255H 결론이 아니다. P-only, E-only,
  P+E, all-core와 table/block 크기는 타깃에서 별도로 재측정한다.

score 후보의 기본 build와 검증은 다음과 같다.

```bash
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/deep_native_06.cpp -o /tmp/deep_native_06
/tmp/deep_native_06 --self-test --json
/tmp/deep_native_06 --threads 1 --json
```

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
d                 = 0x1c3cdd6b221806db0a7b28
legacy scan s2    = 0x638d9d631ab436da51e640
shifted scan s3   = 0x948173253ad6d120a3f562
r3                = 0x2443c8daf1a9d52b09
```

기존 문서와 코드가 `0x638d...`를 `s1`이라고 쓴 것은 한 칸 어긋난
표기였다. `r0`에서 lift한 점은 `s1 Q`이고, 여기에 `d`를 곱한 점의
x좌표는 `X(s1 P)=s2`다. 의존성 없는 Python/GMP 경로는 이 `s2`를
복원하고, 최종 native 경로는 관측 window를 한 칸 옮겨 `s3`를 직접
복원한다. 둘 다 같은 목표 `r3`를 예측한다.

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

기본 공격은 `r0`의 가능한 하위 16비트를 붙여 x좌표 후보를 만든다.

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

### 최종 native의 shifted scan

출력 정의를 한 칸 뒤에서 똑같이 적용할 수 있다. `r1`에 low 16비트를
붙여 lift한 점을 `T`라 하면 올바른 후보는 부호를 제외하고 `s2 Q`다.

```text
T       = +/-s2 Q
X(dT)   = X(s2 P) = s3
r2   ?= TMSB(X(s3 Q))
s4      = X(s3 P)
r3      = TMSB(X(s4 Q))
```

이미 알려진 `r2`가 72비트 filter이므로 후보 유일성과 예측 절차는
`r0/r1` 경로와 같다. 단순히 정답 위치를 먼저 검사하는 hardcode가 아니라
공개 관측 쌍을 `(r0,r1)`에서 `(r1,r2)`로 옮긴 것이다.

이 인스턴스의 full `r0` x low는 `0x5338`, full `r1` x low는
`0x3cea`다. 따라서 정답을 포함한 순차 prefix가 21,305개에서 15,595개로
26.8% 줄었다. 40개 adjacent balanced AB/BA pair의 1-thread 측정은
paired median `1.3428x`, bootstrap 95% CI `1.3336..1.3510`이었고
stationarity gate를 통과했다. 최종 native JSON은 이를 `state_label=s3`,
`lift_output_index=1`, `filter_output_index=2`로 명시한다.

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

### GMP 기준의 width-5 wNAF와 폭 재검토

원래 right-to-left double-and-add는 매 비트 doubling과 binary 1마다
generic Jacobian addition을 했다. 최적화 구현은 signed digit width-5
NAF를 사용한다. 점의 음수는 y좌표의 부호만 바꾸면 되므로 싸고, 0이
아닌 digit의 밀도가 줄어 addition 횟수가 감소한다. 각 임의 점에 대해
`P,3P,...,15P` 여덟 개를 준비한다.

실제 `d`는 85비트이고 binary popcount는 40이다. plain width-2 NAF의
nonzero digit은 27개지만, GMP width-5 wNAF는 14개다. 다만 후보마다
`P,3P,...,15P`를 만드는 7회 addition도 필요하므로 합계는 21회다.
width-4는 nonzero 16개와 precompute 3개, 합계 19회로 이론상 더 작았다.
그러나 8-thread GMP 반복 측정에서는 width-5 0.483517초, width-4
0.494902초로 역전되어 width-4의 우위를 입증하지 못했다. Python/GMP 객체
비용과 scheduler 분산이 작은 operation-count 차이보다 컸기 때문에 현재
GMP 경로는 width-5를 유지한다.

### 고정-base byte comb

후보마다 `state * Q`를 계산하지만 `Q`는 항상 같다. 88비트 scalar를 11개
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
성능 경로인 `deep_native_06.cpp`는 88비트 체를 고정 2-limb Montgomery
표현으로 옮겼다. x86-64 BMI2/ADX가 있으면 `_mulx_u64`,
`_addcarryx_u64`, `_subborrow_u64`로 2x2 REDC와 branchless add/subtract를
실행하고, 그 밖의 target에서는 고정식 `unsigned __int128` 구현으로
자동 fallback한다. `-march=native` 없는 portable, assertion-enabled
debug와 기본 BMI2/ADX 빌드가 모두 같은 self-test를 통과했다.

임의 lift의 `d` 곱은 원곡선과 동형인 `a=-3` 모델에서 수행한다.

```text
y'^2 = x'^3 - 3*x' + 0x5e7dc2bc27aea7935c6b6
x    = 0x9b4427ecf55d466c0bbf44 * x' mod p
```

EFD `a=-3` doubling으로 square 수를 줄였다. 원곡선과의 40-pair 직교
비교는 paired `1.1022x`, bootstrap CI `1.0320..1.1274`였지만 VM phase
변화로 stationarity가 실패해 이 수치는 diagnostic-only다. 구현은
원곡선 compile-time fallback과 교차 검증을 유지한 채 기본으로 선택했다.

복원된 고정 `d`에는 Hamburg 2020 Figure 3의 co-Z x-only ladder를
적용했다. 최종 분수를 개별 invert하지 않고 Jacobian `X/Z^2`로 넘겨
block batch normalization과 합친다. 알 수 없는 scalar나 exceptional
denominator에서는 width-2 NAF로 되돌아간다.
NAF 대 Hamburg 1-thread 40-pair 결과는 `1.1716x`, bootstrap 95% CI
`1.1682..1.1764`, stationarity PASS였다. inline Hamburg는 code가 약
10KB로 팽창하고 spill이 생겨 느렸으므로 큰 ladder만 `noinline`으로 뒀다.

Hamburg의 정상 성공 경로는 x좌표와 곡선식의 우변만 사용하고 y좌표를
사용하지 않는다. 따라서 모든 x에서 `a^((p+1)/4)`를 계산할 필요 없이,
Montgomery 88비트 우변의 Jacobi symbol로 제곱잉여 여부만 먼저 판정한다.
`R=2^128=(2^64)^2`이므로 `(aR/p)=(a/p)`이고 canonical 변환도 필요 없다.
U128 Euclidean reduction 중 두 피연산자가 64비트가 되면 U64 loop로
전환한다.
비잉여는 즉시 버리고, 드문 Hamburg denominator 예외에서 NAF fallback이
y를 요구할 때만 기존 sqrt를 실행한다. 이 방식은 Legendre exponent 뒤에
sqrt exponent를 다시 실행했던 실패 후보와 달리 두 exponentiation을
중복하지 않는다. field random 2,000개와 경계 64개에서 Jacobi 결과를
Fermat/Legendre 결과와 교차 검증했다.

최종 source/runner의 1-thread 40-pair 비교에서 sqrt-lift와 Jacobi-lift의
외부 시간 중앙값은 `0.076186/0.070292 s`, paired median은 `1.0819x`
(층화 bootstrap 95% CI `1.0769..1.0842`)였다. AB/BA 중앙값은
`1.0823x/1.0817x`, 네 시간 block은 `1.0863/1.0814/1.0809/1.0817x`로
stationarity와 promotion gate를 모두 통과해 Jacobi를 기본값으로
승격했다.

후속 Jacobi-only microbenchmark에서 full-U128 Euclidean,
canonical-hybrid, Montgomery-hybrid는
`0.086159/0.056937/0.055429 s`였다. U64 tail과 Montgomery 직접 입력은
primitive를 줄였지만, 부분군 필터를 끈 전체 attack의 full/hybrid 비교는
paired `1.0013x`(CI `0.9699..1.0315`)로 noisy parity였다. 따라서 별도
end-to-end 가속 수치로 합산하지 않는다.

### cofactor-5 부분군을 x-only로 판정하기

곡선의 군 구조는

```text
#E(Fp) = 5*n = 262358068131633367380937105
E(Fp)  = cyclic
ord(Q) = n
```

이다. true lift는 `s2Q`이므로 order-`n` 부분군에 있다. 정답까지 검사하는
shifted prefix에는 curve-valid 점이 7,713개 있지만 `[n]T=O`인 점은
1,547개뿐이다. 따라서 정확하고 싼 부분군 판정은 Hamburg 호출의
`6,166/7,713=79.94%`를 제거한다.

Koshelev의 small-cofactor Tate-pairing 검사는 이 아이디어의 출발점이지만,
논문의 basic-field 알고리즘은 작은 인수 `e`가 `p-1`을 나눈다고 가정한다.
여기서는 `p mod 5=4`, 즉 `5∤p-1`이므로 그대로 적용할 수 없다. 대신
`Fp2=Fp[v]/(v^2-2)`에서 `v^p=-v`인 Frobenius `-1` eigenspace의
order-5 점을 사용했다.

```text
P-  = (alpha, beta*v)
2P- = (gamma, delta*v)
alpha = d59dbc5a89d7c3dcfc7aef
beta  = c34366b11d118d0d635fbb
gamma = 0e953f99abc72cff8f3ff9
delta = 94b152fc315f97ae6ea4c7
m1    = d1e74749596975d56c869e
m2    = 3a7862416ae71b5fea671e
```

`m1*v`, `m2*v`는 각각 `P-`, `2P-`에서의 tangent slope다. Enge가 정리한
Miller recurrence로 order-5 Miller 함수를 전개하고
`W=f(T)^p/f(T)`, `tau=W+W^-1`을 취하면 lift의 y가 사라진다. 변환 곡선의
우변을 `r=x^3-3x+b`라고 할 때 필요한 Fp 계산은 다음과 같다.

```text
A = beta + m1*(x-alpha)
B = delta + m2*(x-gamma)
C = r + 2*A^2 + 4*A*B
D = -((r + 2*A^2)*B + 2*r*A)
U = r*C^2
V = 2*D^2
tau = 2*(U+V)/(U-V)
```

고정 지수 `e=(p+1)/5=0x2b674bdfd6f921287caaec`에 대해
`L_k=W^k+W^-k`를 Lucas ladder로 계산한다.

```text
L_2k   = L_k^2 - 2
L_2k+1 = L_k*L_k+1 - tau
T is in <Q>  <=>  L_e = 2
```

trace 식은 약 `6M+3S`, block batch inversion은 후보당 약 4M과 block당
inverse 하나, Lucas ladder는 170 M/S다. 합계 약 183 field-operation
equivalent라 Hamburg의 약 930보다 충분히 작다. scalar schedule은 개별
inverse를 쓰고 block schedule은 모든 `U-V`를 한 번에 invert한다. 유효한
rational lift에서는 `U-V=0`이 나타나지 않았고, 구현은 그래도 0이면
fail-closed로 버린다.

정확성은 Sage와 C++ 양쪽에서 확인했다. Sage는 고정 torsion/Frobenius 관계,
무작위 200점, 실제 prefix의 7,713개 curve-valid lift를 검사했고 trace
member 1,547개와 직접 `[n]T=O` 1,547개 사이 mismatch는 0이었다. C++
self-test도 실제 lift 128개에서 scalar/batched trace를 직접 order 곱과
비교하고 `Q` 양성 벡터, `Fp`-rational order-5 음성 벡터를 검사한다.

source SHA-256
`5f169154d1c3b681a496169b6f4ec456a5a55c41c5986bf1ae27b5e1e90005a8`을
고정하고 `CH6_NO_SUBGROUP_FILTER`만 바꾼 40-pair 결과는 다음과 같다.

| threads | no filter | trace filter | paired | 95% CI |
|---:|---:|---:|---:|---:|
| 1 | 0.085280 s | 0.044124 s | 1.9444x | 1.9113..1.9687 |
| 2 | 0.053521 s | 0.030619 s | 1.7448x | 1.7161..1.7904 |

모든 chronological effect block이 1 thread에서 `1.874x`, 2 thread에서
`1.718x` 이상이었지만, 당시 shared host는 다른 Rust/C++ 빌드와 swap으로
포화되어 absolute/effect stationarity gate는 실패했다. 전수 등가 검증과
전 구간의 큰 효과를 근거로 필터를 기본값에 넣되, 위 절대 시간은
diagnostic-only로 취급한다.
그 뒤 최종 source에서는 중복 `PreparedLift` 저장을 없애고 이미 계산한
`x^2`를 재사용했다. correctness suite는 다시 통과했지만, 포화된 host에서
최종 source의 새 성능 수치를 만들지는 않았다.

고정 `Q` table은 width 4--11을 compile-time으로 비교했고 w8을 유지했다.
w4는 최신 40-pair에서 `0.9483x`(CI `0.9243..0.9737`)였고, w9의 작은
명목상 이득은 CI가 parity를 포함했다. 후속 balanced signed-w9는 논리적으로
`10*257*32=82,240`바이트이고 row alignment를 포함한 실제 table은
82,560바이트로 w8의 90,112바이트보다 작다. 최대 digit 수도 11개에서
10개로 줄지만 paired `1.0065x`(CI `1.0035..1.0094`, stationarity PASS)에
그쳐 2% 승격 문턱을 넘지 못했다. 경계 scalar `255/256`, `511/512`,
`2^81±1`, `2^87±1`, `n±1`, 88비트 최댓값까지 reference와 대조한
실험 macro만 남기고 기본 w8 unsigned table을 유지했다.

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
기준을 넘지 못했다. 첫 GMP 검토에서는 Hamburg의 후속 `8M+3S+7A` 식을
exceptional-point 처리 때문에 보류했지만, 후속 native 검토에서
denominator 예외를 NAF fallback으로 처리해 채택했다. 따라서 실패한 것은
x-only 발상 전체가 아니라 이 Brier--Joye `14M` ladder와 residue 처리
순서다.

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
`r0/r1` 기준에서는 `r1`을 강한 early filter로 사용하고 `r2/r3` 계산을 hit
뒤로 미뤘다. low 16비트 탐색을 정답 `0x5338` 주변부터 시작하는 것은 답
hardcode라 제외했다. 반면 공개 window를 `(r1,r2)`로 옮기는 shifted scan은
같은 72비트 filter를 보존하며 prefix를 실제로 줄이므로 채택했다. telemetry
recurrence는 곱셈을 덧셈으로 바꿔도 `2^20`회 순회가 남았고, `gmpy2`만
적용한 Python과 병렬화만 적용한 경로도 interpreter 또는 중복 scalar
multiplication 병목이 남아 최종안이 되지 못했다.

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

BMI2/ADX target에서는 2x2 product와 REDC를 `_mulx_u64`와 carry
intrinsic으로 직선화하고 add/subtract도 borrow mask로 분기 없이
보정한다. hot multiply의 compiler output은 약 206 instruction/688 byte,
분기 6개와 spill에서 약 74 instruction/256 byte, 분기 1개와 spill 없음으로
줄었다. 지원하지 않는 CPU는 portable U128 unrolled 경로를 쓴다.

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

11x256 고정-`Q` table을 구축 과정에서 batch-normalize한 뒤 affine
`(x,y)`로 저장했다. native 기준 Jacobian table은 135,168바이트지만
affine table은 90,112바이트여서 정확히 1/3 작다. 각 row를 64바이트
경계에 맞추고 모든 thread가 read-only로 공유한다. query에서는 generic
Jacobian addition
대신 EFD의 `madd-2007-bl` mixed addition을 사용해 공개 operation count를
`11M+5S`에서 `7M+4S`로 줄였다.

임의 lift에 대한 `dR`의 기본은 Hamburg co-Z ladder이고 width-2 NAF와
mixed addition은 exceptional fallback이다. 넓은 wNAF는 digit 수는
줄지만 매 후보의 table 구축·정규화 비용이 더 컸다. 고정점 `Q`, 일반
fallback과 고정 `d` hot path에 서로 다른 전략을 쓰는 것이 핵심이다.

### 스케줄링, batch inversion과 SIMD 검토

atomic counter가 낮은 값부터 연속 candidate block을 배정한다. 기본 크기는
64이고 2-thread adaptive에서만 32다. 아직
배정되지 않은 block이 현재 최선의 low bits 이상이면 즉시 멈추므로 정적
분할의 불필요한 tail work를 피한다. 1 thread에서는 block의 affine 변환을
batch inversion하는 경로가 scalar보다 약 6% 빨랐지만, 8 threads에서는
thread-local stack traffic과 추가 multiply 때문에 scalar가 약 6%
빨랐다. 초기 정책은 이에 따라 1 thread만 block으로 뒀다.

| scheduler 경로 | 1 thread | 8 threads |
|---|---:|---:|
| block batch | 0.386404 s | 0.082014 s |
| scalar | 0.410719 s | 0.077461 s |

후속 검토에서는 2-thread만 별도로 block 크기까지 다시 탐색했다. 최종
source에서 explicit `scalar/64`와 adaptive `block/32`를 CPU 6--7에 고정하고
warm-up 20쌍 뒤 40쌍을 비교한 결과 외부 중앙값은
`0.047541/0.039171 s`, paired median은 `1.2121x`(95% CI
`1.2051..1.2163`)였다. AB/BA는 `1.2013x/1.2153x`, 네 block은
`1.2065/1.2093/1.2139/1.2168x`로 stationarity PASS였다. 따라서 현재
adaptive 정책은 `1T=block64`, `2T=block32`, `3T 이상=scalar64`다.
4/8-thread block screening은 방향과 변동이 일관되지 않아 기존 scalar를
유지한다. JSON에는 요청 block과 실제 선택 block을 각각
`block_size_requested`, `block_size`로 기록한다.

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
따라서 임의점의 완전한 fallback에는 width-2 mixed NAF, hot 고정 `d`에는
Hamburg, 한 번만 구축하는 고정점 `Q`에는 큰 byte-comb를 서로 다르게
적용했다.

**Legendre exponent 선필터.** 별도 exponentiation으로 residue를 확인한 뒤
같은 후보에 sqrt exponent를 다시 실행해 작업이 중복됐다. GMP 후보에서는
동률 이하였고 native에서도 채택하지 않았다. 최종 Jacobi 경로는 이 실패를
그대로 되풀이하지 않고, 정수 Euclidean reduction만으로 residue를 판정한 뒤
Hamburg 예외에서만 sqrt를 지연 실행한다.

**Subtractive Jacobi.** U128 나눗셈을 없애려고 trailing-zero 제거와 반복
뺄셈만 쓰는 binary Jacobi도 구현했다. 경계/random Legendre 교차 검증과
전체 정답은 통과했지만 Euclidean-remainder Jacobi 대비 paired `1.0072x`,
CI `0.9851..1.0225`로 parity를 포함했고 시간 block별 부호도 바뀌었다.
88비트 두 limb에서는 뺄셈 iteration 증가가 division 제거 이득을 상쇄해
기본 Euclidean 경로를 유지했다.

**Row-batched affine fixed-`Q`.** 후보마다 최대 11회의 Jacobian mixed
addition을 한 뒤 한 번 batch-normalize하는 대신, block 전체를 comb row별
affine addition하고 row마다 분모를 Montgomery trick으로 함께 invert했다.
정상 addition의 근사 비용은 `7M+4S`에서 `5M+1S`로 줄지만 row마다 역원
하나, 약 30KB의 추가 thread-local 배열과 exceptional affine 처리가 생겼다.
실제 결과는 기존/candidate 외부 중앙값 `0.078683/0.083765 s`, paired
`0.9351x`(CI `0.9254..0.9438`)로 candidate가 약 6.5% 느려 기각했다.

**2-lane lockstep과 Hamburg DAG.** 독립 후보 두 개의 sqrt/Hamburg 단계를
교차 배치해 instruction-level parallelism을 노린 prototype은 scalar 대비
`0.8624x`였고 40쌍 모두 졌다. Hamburg stack frame이 약 `0x198`에서
2-lane `0x458`바이트로 커지며 GPR spill이 이득을 압도했다. 논문의 Figure 4는
현재 Figure 3과 같은 식의 단순 재스케줄이 아니라 `9M+3S+7A` Joye ladder다.
같은 `8M+3S+7A`에서 4-unit DAG를 제시하는 것은 Appendix Figure 6이지만,
현재 2-limb scalar backend에서는 register pressure가 커 구현 우선순위를
낮췄다.

**전용 square와 direct U128 add.** 대칭 cross term을 한 번만 계산하는
portable square는 약 `1.0179x`였지만 2% 승격 문턱과 stationarity를
통과하지 못했다. BMI2 square는 `0.9982x`, CI `0.9919..1.0034`로
동률이었다. GCC가 generic multiply의 동일 operand를 보고 이미 cross
term을 합쳤기 때문이다. direct U128 add도 carry intrinsic보다 빠르지
않았다. 새 Lucas-heavy 부분군 경로에서도 다시 검사했지만 portable
specialized square는 paired `0.7111x`, BMI2 intrinsic square는
`0.9230x`로 더 느렸다.

**고정 sqrt chain.** `addchain`으로 `(p+1)/4` straight-line chain을
탐색했지만 최선이 약 107회 square/multiply로 현재 sliding-window 약
108회와 사실상 같았다. code와 table 준비를 늘릴 end-to-end 근거가 없어
채택하지 않았다.

**inline/noinline.** field multiply를 `noinline`으로 만들면 약
`0.9754x`로 악화됐다. 반대로 Hamburg를 inline하면 약 10KB code와
spill이 생겼다. 작은 field primitive는 inline하고 큰 Hamburg 함수만
`noinline`으로 뒀다.

**table 폭과 block 크기.** w4--w7은 작은 table 대신 addition이 늘었고,
w9의 작은 명목상 이득은 CI가 parity를 포함했다. balanced signed-w9도
table을 82,560바이트로 줄였지만 `1.0065x`에 그쳤다. 최신 w8/w4 결과는
`0.9483x`로 w4가 느렸다. block 8/64와 128/64 비교도 CI가 parity를
포함했다. 단, thread 수를 분리한 최종 측정에서 2-thread block32만 gate를
통과해 adaptive 정책에 반영했다. 부분군 batch inverse를 넣은 뒤
1-thread block256은 block64보다 paired `1.0365x`(CI
`1.0173..1.0503`)로 유망했지만 stationarity를 실패했다. 2-thread
block128도 포화된 host에서 결론을 내지 못해 자동 block 정책은 유지했다.

**PRAC과 GLV/endomorphism.** 고정 `d`에는 Hamburg가 이미 규칙적인
x-only 경로를 제공하며, 이 generic-j 곡선에는 효율적인 GLV
endomorphism과 필요한 subgroup 구조가 주어지지 않았다. 넓은 fixed
addition chain까지 포함해 이론적 operation 절약이 precomputation과
exception 처리를 상쇄하지 못했다.

**Cofactor-5 필터의 실패한 변형.** 채택한 x-only trace 전에는 Miller 값
`f=(y+i*c1(x))^2*(y+i*c2(x))`를 직접 `Fp2`에서 `(p+1)/5`승하고
허수부가 0인지 보는 역원 없는 구현을 만들었다. 판정은 맞았지만 먼저 y를
구하는 sqrt와 Fp2 연산 때문에 no-filter 대비 paired `1.1643x`에 그쳐,
x-only trace의 `1.9444x`보다 낮았다. Lucas 84-bit loop를 template로 완전히
펼친 후보도 code가 약 `0x510`에서 `0x298e`바이트로 커졌고 paired
`1.0451x`, CI `0.9133..1.1072`여서 기각했다.

**ADX, compiler와 cache hint.** GCC 12와 Clang 21의 현 hot assembly는
`mulx+adc`만 쓰고 `adcx/adox`는 생성하지 않았다. 직접 짠 dual-carry
REDC는 KAT를 통과했지만 약 4--5% 느렸다. Clang+libomp는 quick 1-thread에서
약 `1.076x` 유망했지만 2-thread는 `1.016x`로 불확실해 정식 재측정 전에는
기본 compiler를 바꾸지 않았다. fixed-table prefetch distance 1/2/4는
`0.9953/0.9921/0.9805x`, row padding 1/3 cache line은
`0.9814/0.9826x`, `-funroll-loops`는 `1.0074x`였다. signed-w10과
4-thread chunk 변형도 2% 문턱 또는 안정성을 넘지 못했다.

AVX2도 검토했지만 현재 REDC가 요구하는 packed 64x64→128 정수 곱이 없다.
32비트 radix로 바꾸면 cross-term, shuffle, lane carry가 늘고 residue 분기
뒤 lane compaction도 필요하다. 이미 후보 단위 OpenMP 병렬성이 잘
작동하는 이 88비트 workload에는 이식성과 검증 비용을 상쇄할 근거가
없어 구현하지 않았다. AVX-512 IFMA52가 있는 별도 target이라면 radix-44/52
multi-buffer 구현을 다시 비교할 수 있다.

## 6. 정확성 검증

검증 범위는 runner별로 명시했다.

- 알고리즘 후보 runner는 측정 전에 x-only 실제 lift 8개와 finite-difference
  256개를 reference와 대조하고, 매 sample의 known answer를 검사한다.
- 공용/deep-native runner는 `state_label`에 따라 legacy `s2/0x5338` 또는
  shifted `s3/0x3cea`를 검사하고 `d`, `r3`, `P=dQ`도 확인한다. 원본
  Python은 low bits를 출력하지 않아 `s2` known answer까지만 검사한다.
- native preflight는 deterministic random field pair 2,000개, limb/modulus
  경계 pair 64개, point/scalar/table 256개, 실제 lift Hamburg/NAF 및
  scalar/batched subgroup 128개를
  독립 canonical U128 및 affine reference와 대조한다. point vector에는
  signed recoding carry가 바뀌는 `255/256`, `511/512`, `n±1`과 88비트
  최댓값을 명시적으로 포함한다. full-U128/hybrid-U64,
  canonical/Montgomery, Euclidean/subtractive Jacobi도 Legendre 결과와
  함께 비교한다.
- promotion runner는 field backend, curve model, `d` multiplication,
  lift residue와 subgroup membership 판정, table 폭/부호 encoding, scan output index,
  fixed multiplication, 요청/실효 block, thread/schedule/inverse/sqrt
  metadata가 요청한 후보와 일치하는지 검사한다.
  solver는 실제 생성된 OpenMP team 크기를 `threads_actual`로 보고하고,
  요청값과 다르면 timing 전에 종료한다. 서로 다른 compile-time 후보가
  같은 binary hash를 만들거나 build/runtime 설정이 같은 A/A 비교도
  명시적인 null calibration이 아니면 inactive ablation으로 거부한다.

최종 Python 실행 예:

```text
backdoor scalar d = 0x1c3cdd6b221806db0a7b28
P == d*Q: True
recovered state s2 = 0x638d9d631ab436da51e640
predicted r3 = 0x2443c8daf1a9d52b09
```

Binary-GCD/Fermat inverse,
binary/window-4 sqrt, NAF/mixed multiplication, Hamburg ladder와 fixed
comb가 모두 이 교차 검증을 통과해야 timing을 시작한다. 이는 challenge용
correctness 검사이며 secret scalar를 위한 constant-time 구현을 뜻하지는
않는다.

## 7. 반복 benchmark

`solutions/benchmark_06_prng.py`와 `benchmark_deep_native_06.py`는 넓은
언어/backend/thread 조합을 거르는 broad protocol을 사용한다.

- 각 구현을 먼저 1회 완전히 실행해 warm-up 표본을 버린다.
- 구현마다 완전한 end-to-end 실행을 5회 측정한다.
- 매 round 실행 순서를 cyclic rotation하고, contender 수를 넘겨 다음 rotation
  cycle에 들어가면 reverse하도록 구현했다. 최종 5-contender/5-sample
  캠페인은 정확히 첫 rotation 집합을 한 번 사용해 reverse 분기에는 도달하지
  않았다.
- 모든 표본에서 `d`, `r3`, `P=dQ`와 `state_label`별 `s2` 또는 `s3`,
  해당 lift low를 검사한다.
- raw sample, median, MAD, p05/p95, min/max, 같은 repetition index의
  diagnostic ratio와 내부 telemetry/state 시간을 JSON으로 보존한다.
- C++ build는 임시 디렉터리에서 한 번 수행하고 timed region에서 제외한다.

공용 runner의 현재 기본 목록은 원본, Python `int`/`gmpy2`, GMP 1/auto,
native 1/auto adaptive의 7개다. 5회 실행이면 이 runner도 reverse 구간에
도달하지 않는다. 아래의 과거 5행 language/backend 표를 정확히 다시 만들
때에는 `--implementations`로 해당 다섯 경로를 명시해야 한다. OpenMP 환경은
`OMP_DYNAMIC=FALSE`, `OMP_PROC_BIND=SPREAD`, `OMP_PLACES=THREADS`로 고정했다.
상속된 `OMP_THREAD_LIMIT`, `OMP_NUM_THREADS`, `OMP_SCHEDULE`,
`GOMP_CPU_AFFINITY`는 제거하고 어떤 변수를 지웠는지 보고서에 남긴다.
`auto` thread 수는 `os.cpu_count()`가 아니라 현재 affinity mask를 따르며,
mask보다 많은 thread를 요청하면 build 전에 거부한다.

작은 후보의 승격에는 더 엄격한 `benchmark_06_promotion.py`를 쓴다. 정확히
두 frozen-source build를 같은 CPU set에 pin하고, warm-up 뒤 fresh process
40개 adjacent pair를 네 시간 block마다 AB 5개/BA 5개로 균형화한다. paired
median이 `1.02x`를 넘고, 시간 block과 AB/BA 순서의 8개 stratum 안에서
각각 재표집한 5,000회 bootstrap CI가 parity를 제외하며 AB/BA 두 stratum과
absolute/effect stationarity를 모두 통과해야 승격한다.
보고서 옆에는 측정 source snapshot과 source/runner/binary SHA-256, build
argv, CPU model/flags/topology, 모든 timestamp와 child CPU time을 보존한다.

측정 환경은 AMD EPYC 7B12 VM, 8 logical CPU, Python 3.11.2, G++ 12.2.0이다.
먼저 언어/backend 단계별 효과를 확인한 역사 캠페인은 다음과 같다.

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

다음 표는 **이번 pass 이전 native**와 원본 Python, 같은 thread 수의 GMP를
하나의 cyclic-rotation 실행 순서에 넣어 측정한 역사 기준선이다. 서로 다른
부하의 run을 나눈 값은 아니지만 shifted/Hamburg/BMI2 최종 binary의 수치로
소급해서 부르지 않는다.

| 구현 | end-to-end 중앙값 | MAD | 중앙값 비율 |
|---|---:|---:|---:|
| 기존 Python | 14.073190 s | 0.295610 s | 1.00x |
| C++/GMP 1 thread | 1.971840 s | 0.048047 s | 7.14x vs Python |
| native adaptive 1 thread | 0.362651 s | 0.009200 s | 38.81x vs Python; 5.44x vs GMP |
| C++/GMP/OpenMP 8 threads | 0.436403 s | 0.007239 s | 32.25x vs Python |
| native adaptive 8 threads | 0.085076 s | 0.006915 s | 165.42x vs Python; 5.13x vs GMP |

같은 repetition index의 native/GMP diagnostic ratio 중앙값은 각각
5.31x와 5.34x였다.
8-thread native MAD는 8.13%로 host load 영향이 보이지만, 가장 느린 native
표본도 가장 빠른 GMP 표본보다 4배 이상 빨랐다. 서로 다른 캠페인을 섞어
계산하면 더 큰 수치가 나오지만 서로 다른 run의 수치이므로 폐기했다.

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
requested/effective schedule, build command와 same-index diagnostic ratio를
함께 보존한다.

두 번째 pass의 broad screening 7회에서는 최종 native가 1 thread
`0.097596 s`(MAD `0.004957 s`), 8 threads `0.057401 s`
(MAD `0.009471 s`)였다. 같은 run의 GMP는 각각 `2.529046 s`,
`0.575237 s`여서 ratio-of-medians는 `25.91x`, `10.02x`였다. shared VM
부하와 8-thread MAD가 커 이 표는 큰 효과의 sanity check로만 쓴다.

작은 후보의 40-pair 결과는 다음과 같다.

| 후보 (`A/B`) | paired median | bootstrap 95% CI | stationarity | 판정 |
|---|---:|---:|---|---|
| legacy / shifted scan | 1.3428x | 1.3336..1.3510 | PASS | shifted 채택 |
| width-2 NAF / Hamburg | 1.1716x | 1.1682..1.1764 | PASS | Hamburg 채택 |
| sqrt lift / Jacobi lift | 1.0819x | 1.0769..1.0842 | PASS | Jacobi 채택 |
| 2T scalar64 / adaptive block32 | 1.2121x | 1.2051..1.2163 | PASS | 2T 정책 채택 |
| no subgroup filter / Frobenius--Tate trace, 1T | 1.9444x | 1.9113..1.9687 | FAIL | 전 구간 큰 이득, diagnostic timing |
| no subgroup filter / Frobenius--Tate trace, 2T | 1.7448x | 1.7161..1.7904 | FAIL | 전 구간 큰 이득, diagnostic timing |
| full-U128 / Montgomery-hybrid Jacobi | 1.0013x | 0.9699..1.0315 | FAIL | micro 개선만 확인 |
| unsigned w8 / balanced signed-w9 | 1.0065x | 1.0035..1.0094 | PASS | 2% 미달, w8 유지 |
| Euclidean / subtractive Jacobi | 1.0072x | 0.9851..1.0225 | FAIL | Euclidean 유지 |
| candidate-Jacobian / row-batched affine | 0.9351x | 0.9254..0.9438 | FAIL | 기존 경로 유지 |
| original curve / isomorphic `a=-3` | 1.1022x | 1.0320..1.1274 | FAIL | diagnostic-only |
| w8 / w4 fixed table | 0.9483x | 0.9243..0.9737 | FAIL | w8 유지 |
| block 64 / block 128 | 0.9948x | 0.9093..1.0473 | FAIL | 64 유지 |
| subgroup stack block64 / block256 | 1.0365x | 1.0173..1.0503 | FAIL | stationarity 재측정 필요 |
| generic carry / BMI2+ADX | 2.9808x | 2.7330..3.2589 | FAIL | diagnostic-only |

마지막 arithmetic holdout은 40쌍 모두 BMI2/ADX가 크게 이겼지만 host load
average가 16을 넘으며 시간 block spread가 gate를 실패했다. 따라서 방향과
portable fallback의 필요성만 뒷받침하며 절대 성능 주장에는 쓰지 않는다.

Jacobi와 새 2-thread 정책을 넣기 전 source에서 수행한 전체 legacy/당시-final
비교는 warm-up 10쌍 뒤
40쌍을 측정했다. baseline/candidate median은 `0.283205/0.076114 s`,
paired median은 `3.7126x`(CI `3.7106..3.7251`)였다. AB/BA stratum도
각각 `3.7125x/3.7197x`였고 absolute/effect block spread가 모두 기준
안에 들어 stationarity와 promotion gate를 통과했다. 이 합산 결과는
generic carry, legacy scan, 원곡선과 NAF 대조군에서 당시 BMI2/shifted/
Hamburg stack까지의 동일-source compile-time 비교다. 현재 기본값에는 그
위에 Jacobi lift가 추가됐으므로 이 `3.7126x`를 새 전체 합산 수치로
소급하지 않는다.

재현 명령이다. 첫 Python 정답 경로는 표준 라이브러리만 필요하다. C++/native
benchmark에는 C++20을 지원하는 `g++`, OpenMP와 GMP 개발 라이브러리가
필요하다.

```bash
python3 solutions/solve_06_prng.py --backend int --telemetry analytic

python3 solutions/benchmark_06_prng.py \
  --warmup 1 --repetitions 5 \
  --output /tmp/challenge06-benchmark.json

python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 5 --threads 1,8 \
  --native-schedules adaptive --include-original-python \
  --output /tmp/challenge06-native.json

python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label naf --candidate-label hamburg \
  --baseline-define CH6_NAF_D_MULTIPLICATION \
  --candidate-define CH6_SQRT_LIFT \
  --threads 1 --warmup-pairs 2 --pairs 40 \
  --output /tmp/challenge06-hamburg.json

python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label sqrt-lift --candidate-label jacobi-lift \
  --baseline-define CH6_SQRT_LIFT \
  --threads 1 --cpus 6 --warmup-pairs 10 --pairs 40 \
  --output /tmp/challenge06-jacobi.json

python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label scalar64 --candidate-label adaptive-block32 \
  --baseline-schedule scalar --candidate-schedule adaptive \
  --threads 2 --cpus 6,7 --warmup-pairs 20 --pairs 40 \
  --output /tmp/challenge06-2t-schedule.json
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

g++ -O3 -DNDEBUG -std=c++20 -fopenmp \
  -DCH6_PORTABLE_ARITHMETIC \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06_portable
/tmp/deep_native_06_portable --self-test --json
```

## 8. 계산 복잡도와 메모리

- telemetry: 둘째 행 interval hit가 하나인 이 인스턴스에서
  `O(log B * log n)`, `B=2^20`; 마지막 여섯 행 검증은 상수 시간이다.
  일반적으로 hit가 `h`개면 구간 분할 비용이 `h`에 비례한다.
- 상태 복원: 최악 `2^16` x후보에서 Jacobi 판정을 하고 제곱잉여인 약 절반에
  고정 86비트 Frobenius--Tate/Lucas membership test를 수행한다. 그중
  order-`n` 부분군인 약 1/5에만 `O(log n)` arbitrary-point multiplication이
  남는다. asymptotic work는 여전히 `O(2^16 log n)`이며, 제곱근은 Hamburg
  exceptional fallback에서만 필요하다. `w` worker의 이상적 wall time은
  대략 `1/w`이나 precomputation과 scheduling overhead가 있다.
- fixed-base table: GMP 기준은 11x256 Jacobian point이고, native 최종안은
  90,112바이트의 11x256 affine point다. 구축 시 정확히 2,794회 mixed
  addition, 80회 doubling과 12번의 batch-normalization call이 필요하며
  각 query는 최대 11회 mixed addition이다.
- 그 밖의 탐색 메모리는 worker마다 상수 크기 point 상태만 필요하다.

### 제한과 이식성

- native 구현은 GNU/Clang 계열의 `unsigned __int128`과 OpenMP가 필요하다.
  BMI2/ADX는 선택 사항이며 없으면 portable unrolled 경로로 fallback한다.
- `-march=native` BMI2/ADX로 얻은 절대 시간은 다른 CPU와 직접 비교할 수 없다.
- 90KB affine table은 현재 host cache에는 맞지만 private cache가 작은 target은
  4-bit fixed-window 같은 작은 table과 다시 비교해야 한다.
- 이 코드는 공개 challenge input을 찾는 공격 구현이며 constant-time production
  ECC library가 아니다.
- 생성 binary, JSON report와 frozen source snapshot은 `/tmp`에만 만들고
  repository에는 source와 문서만 남겼다.

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
- [Explicit-Formulas Database, `a=-3` Jacobian coordinates](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian-3.html) — 동형 곡선의 `dbl-2001-b` 계열 공식과 operation count를 확인했다.
- [Cohen, Miyaji, Ono, *Efficient Elliptic Curve Exponentiation Using Mixed Coordinates*](https://dspace.jaist.ac.jp/dspace/handle/10119/4458?locale=en) — coordinate 선택과 mixed addition 최적화 검토의 원 논문이다.
- [Morain and Olivos, *Speeding up the computations on an elliptic curve using addition-subtraction chains*](https://www.numdam.org/item/ITA_1990__24_6_531_0/) — signed digit/NAF로 point addition 수를 줄이는 근거다.
- [Brier and Joye, *Weierstrass Elliptic Curves and Side-Channel Attacks*](https://marcjoye.github.io/papers/BJ02espa.pdf) — 일반 Weierstrass 곡선에서 x-only ladder 후보를 검토할 때 사용했다.
- [Hamburg, *Faster Montgomery and double-add ladders for short Weierstrass curves*](https://eprint.iacr.org/2020/437), [공식 supplementary formulas](https://github.com/bitwiseshiftleft/ladder_formulas) — Figure 3의 co-Z ladder를 고정 `d` hot path에 구현하고 exceptional denominator를 NAF fallback으로 처리했으며 Figure 4/6 DAG 후보를 대조했다.
- [Möller, *Efficient computation of the Jacobi symbol*](https://arxiv.org/abs/1907.07795), [GNU MP Jacobi algorithm](https://gmplib.org/manual/Jacobi-Symbol.html) — GCD/Euclidean reduction 중 하위 비트로 Jacobi 부호를 갱신하는 근거다. 이 문제에서는 88비트 고정 입력에 맞춘 작은 구현으로 sqrt를 지연했다.
- [Koshelev, *Subgroup membership testing on elliptic curves via the Tate pairing*](https://eprint.iacr.org/2022/037.pdf) — small-cofactor pairing test의 출발점이다. 논문의 basic-field 조건 `e | p-1`은 현재 `p mod 5=4` 곡선에서 성립하지 않아, 구현은 그대로 복사하지 않고 `Fp2` Frobenius 고유공간으로 확장했다.
- [Enge, *Bilinear pairings on elliptic curves*](https://arxiv.org/abs/1301.5520) — Miller recurrence, reduced Tate pairing과 Frobenius 작용을 이용해 order-5 Miller 값을 x-only trace 식으로 전개할 때 참고했다.
- [Montgomery, *Speeding the Pollard and Elliptic Curve Methods of Factorization*](https://doi.org/10.1090/S0025-5718-1987-0866113-7) — differential ladder와 inversion amortization의 원형을 확인했다.
- [Bernstein et al., *OpenSSLNTRU: Faster post-quantum TLS key exchange*](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf) — prefix/reverse batch inversion의 `3n-3` multiplication과 1 inversion 비용을 확인했다.
- [Montgomery, *Modular Multiplication Without Trial Division*](https://doi.org/10.1090/S0025-5718-1985-0777282-X) — 고정 2-limb REDC와 Montgomery residue 표현의 근거다.
- [GNU MP Manual, Number Theoretic Functions](https://gmplib.org/manual/Number-Theoretic-Functions)과 [OpenMP 5.2 Specification](https://www.openmp.org/spec-html/5.2/openmp.html) — `mpz_invert`/`mpz_legendre`와 병렬 search의 구현 기준이다.
- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html) — 채택한 BMI2/ADX scalar multiply/carry intrinsic과 AVX2에 packed 64x64→128 정수 곱이 없음을 확인했다.
- [Michael McLoughlin, `addchain`](https://github.com/mmcloughlin/addchain) — 고정 sqrt 지수 addition chain을 탐색하고 sliding-window와 operation 수를 대조했다.
- [Mytkowicz et al., *Producing Wrong Data Without Doing Anything Obviously Wrong!*](https://sape.inf.usi.ch/publications/asplos09.html), [Google Benchmark User Guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md), [NIST Measures of Scale](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm) — 순서 교차, 반복 표본, raw data 보존과 MAD 보고라는 측정 방법의 근거다.
