# 6번 state recovery 알고리즘 심층 검토

## 결론

첫 GMP 후보군에서는 안정적인 개선을 찾지 못했지만, native 경로를 다시
검토해 서로 독립적인 세 알고리즘 개선을 채택했다.

1. `r0`를 lift해 `r1`로 거르는 대신 **`r1`을 lift해 `r2`로 거른다**.
   이 인스턴스의 순차 검사량은 21,305개에서 15,595개로 26.8% 줄었다.
2. lift마다 실행하는 고정 스칼라 `d` 곱을 width-2 NAF에서 Hamburg의
   short-Weierstrass co-Z x-only ladder로 바꿨다. exceptional denominator는
   완전한 NAF 경로로 되돌아가도록 fail-closed 처리했다.
3. Hamburg 정상 경로에 y가 필요 없다는 점을 이용해 매 lift의 sqrt를
   88비트 Jacobi symbol 판정으로 바꾸고, exceptional NAF fallback에서만
   sqrt를 지연 실행한다.

40개 adjacent balanced AB/BA pair, 5,000회 deterministic bootstrap,
4개 시간 block stationarity gate를 사용한 1-thread 측정에서 shifted scan은
paired median `1.3428x`(95% CI `1.3336..1.3510`), Hamburg는
`1.1716x`(95% CI `1.1682..1.1764`)였고 둘 다 gate를 통과했다. 따라서
최종 source의 sqrt/Jacobi 비교도 `1.0819x`(95% CI
`1.0769..1.0842`)로 gate를 통과했다. 세 후보를
`deep_native_06.cpp`의 기본값으로 승격했다. Brier--Joye, GMP batch
inversion, finite difference, Legendre 선필터와 넓은 임의점 wNAF는 아래
실패 기록처럼 유지하지 않는다.

모든 후보는 선택한 scan window에 맞춰 다음 값을 검증했다.

```text
d             = 0x1c3cdd6b221806db0a7b28
legacy s2     = 0x638d9d631ab436da51e640
shifted s3    = 0x948173253ad6d120a3f562
predicted r3  = 0x2443c8daf1a9d52b09
```

`state_label`과 lift/filter output index도 함께 검사하므로 `s2` 정답을
우연히 `s3` 경로로 받아들이지 않는다.

## 기준 병목

초기 기준은 `r0`의 low bits `0x5338`을 포함해 21,305개 x를 순서대로
검사했고, 그중 curve 위에 있는 후보는 10,690개였다. 기준 구현에서는
후보마다 다음 두 번의 affine conversion이 발생한다.

1. `d * (s1 Q)`의 Jacobian 결과에서 `s2` 복원
2. `s2 * Q`의 Jacobian 결과에서 `r1` 복원

따라서 정답 전까지 `mpz_invert`가 21,380회 호출된다. 프로파일에서 point
doubling 898,148회, point addition 344,486회도 확인했다. 이 수치를 기준으로
x-only와 batch inversion을 평가했다.

## 채택 1: 관측 window를 한 칸 옮긴 scan

출력 정의가

```text
r_i = TMSB(X(s_{i+1} Q))
```

이므로 `r1`에 low 16비트를 붙여 lift한 점 `T`는 부호를 제외하면
`s2 Q`다. 백도어 관계 `P=dQ`를 적용하면

```text
X(dT) = X(s2 P) = s3
r2 ?= TMSB(X(s3 Q))
s4  = X(s3 P)
r3  = TMSB(X(s4 Q))
```

가 된다. 즉 이미 공개된 `r2`가 72비트 filter 역할을 하므로 `r0/r1`
window와 똑같이 후보를 유일하게 정할 수 있고, 그 뒤 목표 `r3`도 계산할
수 있다. 단순히 정답 주변부터 찾는 순서 hardcode가 아니라 같은 공격을
다음 관측 쌍 `(r1,r2)`에 적용한 것이다.

실제 full x의 low 값은 기존 `r0`에서 `0x5338`, shifted `r1`에서
`0x3cea`다. 따라서 순차 prefix는 각각 21,305개와 15,595개다. OpenMP
실행의 `candidates_started`는 이미 배정된 block 때문에 이보다 조금 클 수
있어, 문서와 JSON은 수학적 prefix와 실제 시작 작업 수를 구분한다.

## 채택 2: Hamburg co-Z x-only `d` 곱

Brier--Joye의 regular ladder 전체를 그대로 쓰는 대신 Hamburg 2020
Figure 3의 short-Weierstrass co-Z state를 **고정된 복원 스칼라 `d`**에
특화했다. hot path는 x와 곡선 우변만으로 `X([d]T)`를 계산한다. 최종
numerator/denominator를 개별 invert하지 않고 Jacobian `X/Z^2`로 인코딩해
기존 block batch normalization과 결합했다.

함수는 의도적으로 `noinline`이다. inline 후보는 caller가 약 10KB로
팽창하고 register spill이 생겨 느렸지만, 독립 함수는 NAF 대비 위의
`1.1716x` 승격 기준을 통과했다. denominator가 0이거나 복원한 scalar가
예상된 `d`가 아니면 width-2 NAF로 되돌아간다. self-test는 실제 lift
128개에서 Hamburg와 NAF의 affine x를 대조한다.

## 채택 3: Jacobi 판정과 deferred sqrt

기존 lift는 모든 우변에 `a^((p+1)/4)`를 계산하고 square로 검증했다.
그러나 Hamburg Figure 3의 정상 계산에는 y가 전혀 들어가지 않는다. 따라서
canonical 우변에 대해 `(a/p)`만 Euclidean reduction으로 구한다. 결과가
`-1`이면 비잔여이므로 버리고, `+1`이면 Hamburg를 실행한다. denominator가
0인 exceptional input에서만 기존 sqrt로 y를 복원해 완전한 NAF로
fallback한다.

이는 아래에서 실패한 `mpz_legendre + sqrt`와 비용 구조가 다르다. 그 후보는
두 exponentiation을 이어서 실행했지만, 최종 native Jacobi는 88비트 정수의
나머지·shift·quadratic-reciprocity 부호 갱신만 수행한다. 2,000개
deterministic random 값과 64개 경계 pair에서 Fermat/Legendre와 결과를
비교했고 완전한 attack 실행의 known answer도 일치했다.

나눗셈을 반복 뺄셈으로 바꾼 subtractive binary Jacobi도 같은 검증을
통과했지만 paired `1.0072x`, CI `0.9851..1.0225`로 동률이었다. 이 고정
2-limb 크기에서는 iteration 증가가 U128 remainder 제거를 상쇄해
Euclidean-remainder 구현을 유지했다.

## 후보 1: Brier--Joye x-only ladder

### Brier--Joye 구현

짧은 Weierstrass 곡선

```text
y^2 = x^3 + a*x + b
```

에서 affine x를 homogeneous `(X:Z)`, 즉 `x=X/Z`로 나타냈다. 구현한
differential addition과 doubling은 Brier--Joye 논문의 식 (9), (10)이다.

```text
X(P+Q) = (X1*X2-a*Z1*Z2)^2
         - 4*b*Z1*Z2*(X1*Z2+X2*Z1)
Z(P+Q) = x(P-Q)*(X1*Z2-X2*Z1)^2

X(2P) = (X1^2-a*Z1^2)^2 - 8*b*X1*Z1^3
Z(2P) = 4*Z1*(X1^3+a*X1*Z1^2+b*Z1^3)
```

ladder는 `(R0,R1)=(P,2P)`에서 시작하며 항상 `R1-R0=P`를 유지한다. 따라서
입력 후보 x에 대해 y를 구하지 않고 `x(dP)`를 계산할 수 있다.

구현 정확성은 다음 두 층으로 검증했다.

- `x(dQ)`를 기존 Jacobian 구현과 비교하고 `x(P)`와 일치함을 확인
- 실제 `r0` 구간에서 curve lift 가능한 서로 다른 8개 x를 골라
  x-only 결과를 Jacobian `d*(x,y)` 결과와 비교

### Brier--Joye 결과와 실패 이유

Brier--Joye 원문이 제시하는 비용은 scalar bit마다 대략 field multiplication
14회와 constant multiplication 5회다. width-5 wNAF Jacobian은 비잔여 x를
sqrt 단계에서 제거하고, 남은 후보에만 doubling과 sparse addition을 수행한다.

x-only에서 curve 검사를 완전히 뒤로 미루면 정답 전의 모든 21,305개 x에
regular ladder를 실행해야 한다. 그 결과 8-thread 중앙값은 `1.003282 s`로,
기준 `0.486286 s`의 약 2.06배였다. `mpz_legendre`로 비잔여를 먼저 제거하면
`0.516119 s`까지 회복했지만 여전히 기준보다 6% 느렸다. 즉 이 문제에서는
sqrt 제거 이득보다 regular x-only ladder의 높은 per-bit 비용이 더 컸다.

Mike Hamburg의 후속 연구는 짧은 Weierstrass curve ladder를 bit당
`8M+3S+7A`까지 줄인다. 첫 GMP 검토에서는 exceptional-point 처리까지
포함하는 별도 formula set이 필요해 보류했지만, 후속 native 검토에서
denominator 예외를 NAF fallback으로 처리하고 채택했다. 따라서 이 절의
Brier--Joye 실패는 “x-only 전체가 부적합”하다는 결론이 아니라, 이
구현의 `14M` regular ladder와 residue 처리 순서가 부적합했다는 결론이다.

## 후보 2: Montgomery batch inversion

### batch inversion 구현

block 안에서 다음 pipeline을 사용했다.

```text
sqrt/lift 및 dR projective 계산
    -> 모든 Z를 한 번에 invert해 s2 복원
    -> fixed-Q projective 계산
    -> 모든 Z를 한 번에 invert해 r1 복원
```

prefix product와 reverse sweep을 이용하면 원소 `m`개의 역원을 inversion 1회와
multiplication `3m-3`회로 구할 수 있다. zero denominator는 별도 index로
제외했다. block buffer는 OpenMP thread마다 한 번 할당한 뒤 재사용했다.

### batch inversion 결과와 실패 이유

block 32, width-4의 8-thread 중앙값은 `0.484463 s`로 기준 대비 1.004배였다.
Legendre를 끈 같은 후보는 `0.475473 s`, 즉 1.023배였지만 표준편차가
`0.044612 s`여서 차이가 노이즈보다 작다. width-3과 width-5도 각각
`0.519042 s`, `0.491504 s`로 개선되지 않았다.

이론상 inversion 수는 크게 줄지만 modulus가 88비트에 불과해 GMP의
`mpz_invert`가 이미 싸다. 반면 batch prefix/reverse에 필요한 modular
multiplication, 임시 `mpz_class`, block scheduling과 메모리 이동은 그대로
지불한다. 1-thread 탐색에서는 간헐적으로 약 5--8% 이득이 보였지만 8-thread
반복에서 사라졌으므로 제출 후보로 채택하지 않았다.

## 후보 3: 연속 cubic finite difference

연속 x에서 `f(x)=x^3+a*x+b`를 직접 다시 곱하지 않도록 다음 차분을 사용했다.

```text
f(x+1)      = f(x) + d1
d1(x+1)     = d1(x) + d2
d2(x+1)     = d2(x) + 6

d1(x) = 3*x^2 + 3*x + 1 + a
d2(x) = 6*x + 6
```

256개의 연속 x에서 매 단계 값을 직접 cubic 계산과 비교했다. 수학적으로는
곱셈 두 번을 줄이지만 매 후보의 modular addition/reduction이 세 번 늘어난다.
block 32 batch 경로에서 finite difference 중앙값은 `0.484463 s`, direct
cubic은 `0.488690 s`였다. 0.9% 차이는 측정 분산보다 작으므로 유의한 개선으로
보지 않았다. 코드 복잡도를 늘릴 이유가 없다.

## 후보 4: filter 순서와 wNAF 폭

### Legendre 선필터

기준 `sqrt_mod`는 모든 rhs에 `(p+1)/4` 거듭제곱을 수행한다. 먼저
`mpz_legendre(rhs,p)`를 호출하면 비잔여 약 절반은 sqrt exponentiation 없이
버릴 수 있다. 그러나 8-thread 직교 비교 결과는 다음과 같다.

| 경로 | Legendre 없음 | Legendre 있음 |
|---|---:|---:|
| scalar width-5 | 0.483517 s | 0.490778 s |
| scalar width-4 | 0.494902 s | 0.493416 s |

차이는 모두 분산보다 작거나 오히려 느렸다. 88비트에서는 Legendre symbol
자체 비용이 낮지 않고, 전체 시간은 curve multiplication이 지배한다.

### wNAF 폭

비밀 스칼라 `d`는 85비트, popcount 40이다. 실제 wNAF와 후보마다 필요한
odd-multiple precomputation을 합친 addition 수는 다음과 같다.

| width | nonzero digits | precompute additions | 합계 |
|---:|---:|---:|---:|
| 2 | 27 | 0 | 27 |
| 3 | 21 | 1 | 22 |
| 4 | 16 | 3 | 19 |
| 5 | 14 | 7 | 21 |
| 6 | 12 | 15 | 27 |

연산 수만 보면 width-4가 최선이지만 8-thread scalar 중앙값은 width-5
`0.483517 s`, width-4 `0.494902 s`였다. 약 2 addition 절감은 GMP 객체와
scheduler 비용에 묻혔다. width-4는 합리적인 이론 후보지만 이 환경에서
성능 우위를 입증하지 못했다.

### 탐색 순서

low 16비트에 대한 추가 정보가 없으므로 후보가 균일하다는 가정 아래 어떤
고정 permutation도 기대 탐색 위치를 낮추지 못한다. 정답 `0x5338` 주변부터
탐색하는 것은 인스턴스 답을 hardcode하는 것과 같아 제외했다. 현재의 작은
dynamic OpenMP chunk가 unbiased ordering에서 load balance가 가장 좋았다.

다만 관측 window 자체를 `(r0,r1)`에서 `(r1,r2)`로 옮기는 것은 fixed
permutation이 아니다. 뒤의 공개 출력도 같은 72비트 early filter이므로
정확성을 유지하면서 이 인스턴스의 true low prefix를 26.8% 줄였고 최종
경로에 채택했다. x-only에서 curve-membership 검사까지 filter 뒤로 미루는
순서는 여전히 비잔여 후보에도 비싼 ladder를 수행해 실패했다.

## 후속 native 후보

### Row-batched affine fixed-`Q`

현재 block 경로는 각 scalar를 최대 11회의 Jacobian mixed addition으로
계산한 뒤 모든 결과의 affine x를 한 번에 normalize한다. 대안은 block의
모든 scalar를 comb row별로 함께 진행하고, 각 row의 affine-add 분모를
Montgomery trick으로 batch-invert하는 것이다. 정상 addition당 근사 비용은
`7M+4S`에서 `5M+1S`로 줄고 마지막 Jacobian normalization도 사라진다.

구현은 infinity, 동일점 doubling, 반대점 infinity를 fail-closed 처리하고
256개 scalar 전체를 affine reference와 비교했다. 하지만 row마다 binary-GCD
inverse 하나, 약 30KB의 thread-local scratch와 불규칙 exceptional 분기가
추가됐다. 1-thread 40-pair 결과는 기존/candidate 중앙값
`0.078683/0.083765 s`, paired `0.9351x`(95% CI
`0.9254..0.9438`)로 명확히 느렸다. 재현용
`CH6_ROW_BATCHED_FIXED_MUL` macro만 유지하고 기본값으로 승격하지 않았다.

### Cofactor-5 subgroup membership

PARI의 `ellcard`, `ellgroup`, `ellorder`로 다음을 독립 확인했다.

```text
#E(Fp) = 5*n = 262358068131633367380937105
E(Fp)  = cyclic
ord(Q) = n
```

shifted 정답 prefix에서 curve-valid lift는 7,713개이고 그중 `[n]T=O`는
1,547개다. true lift는 `s2*Q`이므로 order-`n` subgroup에 있고, 정확한
membership filter는 Hamburg 호출의 6,166/7,713 = 79.94%를 제거한다.
단순 `[n]T`는 대략 Hamburg 한 번의 비용이라 손해다. Hamburg를 bit당
`8M+3S`로 잡으면 filter의 대략적인 손익분기점은 후보당 739 field
operation equivalents다. Koshelev의 small-cofactor Tate-pairing/
power-residue 검사가 유력한 출발점이지만 `p mod 5=4`인 이 곡선에 맞춘
확장체와 exceptional 검증이 필요해 고위험 연구 후보로 남겼다.

## 반복 측정

환경:

```text
CPU: AMD EPYC 7B12
logical CPUs / threads: 8 / 8
compiler: g++ 12.2.0, -O3 -DNDEBUG -std=c++20 -fopenmp
arithmetic: GMP 6.2.1
protocol: warmup 1회, 측정 5회, 매 round 실행 순서 회전
```

아래 값은 **채택 전 GMP 1차 후보군**의 solver 내부 state-recovery 구간
중앙값이다. telemetry 분석과 process 시작 비용은 제외했다. 모든 sample에서
`d`, `s2`, `r3`를 검증했다. shifted/Hamburg/Jacobi의 최종 승격 수치는 위
결론의 별도 40-pair native campaign에서 측정했다.

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

재현 명령:

```bash
python3 solutions/06_optimization/benchmark_06_algorithm_candidates.py \
  --warmup 1 --repetitions 5 --threads 8
```

runner는 두 C++ 실행 파일을 임시 디렉터리에 빌드하고 각 실행의 known answer를
검사한다. JSON 원자료가 필요하면 `--output result.json`을 추가한다.

## 파일

- `solve_06_algorithm_candidates.cpp`: x-only, batch inversion, finite
  difference, Legendre, wNAF 후보와 self-test
- `benchmark_06_algorithm_candidates.py`: warmup/반복/순서 회전/known-answer
  검증 runner
- `benchmark_06_promotion.py`: frozen source, CPU affinity, 40개 balanced
  AB/BA pair, bootstrap CI와 stationarity gate를 쓰는 최종 승격 runner

## 참고 자료

- [Eric Brier and Marc Joye, "Weierstrass Elliptic Curves and Side-Channel Attacks" (2002)](https://marcjoye.github.io/papers/BJ02espa.pdf) — Figure 3의 ladder invariant와 식 (6), (7), (9), (10)의 x-only differential addition/doubling을 그대로 구현했다. 원문은 projective ladder 비용도 bit당 약 14 multiplications로 분석한다.
- [Mike Hamburg, "Faster Montgomery and double-add ladders for short Weierstrass curves" (TCHES 2020 / ePrint 2020/437)](https://eprint.iacr.org/2020/437), [공식 supplementary formulas](https://github.com/bitwiseshiftleft/ladder_formulas) — Figure 3의 co-Z ladder를 고정 `d` hot path에 구현하고 exceptional denominator를 NAF fallback으로 처리했으며 Figure 4/6 DAG를 비교했다.
- [Niels Möller, "Efficient computation of the Jacobi symbol"](https://arxiv.org/abs/1907.07795), [GNU MP Jacobi algorithm](https://gmplib.org/manual/Jacobi-Symbol.html) — Euclidean/GCD reduction 중 quadratic-reciprocity 상태를 갱신하는 residue test의 근거다.
- [Dmitrii Koshelev, "Subgroup membership testing on elliptic curves via the Tate pairing"](https://eprint.iacr.org/2022/037.pdf) — cofactor-5 subgroup 선필터의 장기 연구 출발점이다.
- [Peter L. Montgomery, "Speeding the Pollard and Elliptic Curve Methods of Factorization" (Mathematics of Computation, 1987)](https://www.ams.org/journals/mcom/1987-48-177/S0025-5718-1987-0866113-7/S0025-5718-1987-0866113-7.pdf) — differential-addition ladder와 inversion amortization의 원형을 확인했다.
- [Daniel J. Bernstein et al., "OpenSSLNTRU: Faster post-quantum TLS key exchange" (2021), Section 2.2](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf) — Montgomery batch inversion의 prefix/reverse 알고리즘과 `3n-3` multiplications + 1 inversion 비용을 대조했다.
- [GNU MP Manual, Number Theoretic Functions](https://gmplib.org/manual/Number-Theoretic-Functions) — `mpz_invert`와 `mpz_legendre`의 공식 API 의미를 확인했다.
