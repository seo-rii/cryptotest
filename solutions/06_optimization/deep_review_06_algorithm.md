# 6번 state recovery 알고리즘 심층 검토

## 결론

현재의 C++/GMP/OpenMP 구현을 교체할 만큼 재현 가능한 알고리즘 개선은 찾지
못했다. 가장 좋은 실험 후보인 `jacobian-batch`, width-4, block 32 조합도
8-thread 중앙값에서 기준 구현과 사실상 같았다. Brier--Joye x-only ladder는
정확하게 동작했지만 quadratic-residue 검사를 뒤로 미루면 약 2.06배 느렸고,
Legendre 선필터를 넣어도 기준보다 느렸다.

따라서 **알고리즘 비교 층**의 권고안은 다음과 같다. 전체 최고 성능 경로는
이후 별도 검토한 `deep_native_06.cpp`이며, 그 구현은 같은 공격을 고정폭
arithmetic와 cache-friendly layout으로 옮긴 것이다.

1. 알고리즘 대조군은 기존 `solve_06_gmp.cpp`의 Jacobian + fixed-Q table +
   OpenMP 경로를 유지한다.
2. width-4와 batch inversion은 실제 채점 CPU에서 다시 이득이 확인될 때만
   채택한다. 이 VM에서 관측된 차이는 노이즈 범위였다.
3. Brier--Joye x-only 경로와 cubic finite difference는 채택하지 않는다.
4. 최종 실행 성능이 목표라면 검증된 native 경로를 사용한다.

모든 후보는 매 실행마다 다음 값을 검증했다.

```text
d  = 0x1c3cdd6b221806db0a7b28
s2 = 0x638d9d631ab436da51e640
r3 = 0x2443c8daf1a9d52b09
```

`s2` 표기는 중요하다. `r0`에서 lift한 점은 `s1 Q`이고, 여기에 `d`를
곱한 점의 affine x-coordinate는 `X(s1 P)=s2`다.

## 기준 병목

정답 low bits `0x5338`에 도달하기 전 curve 위에 있는 x 후보는 10,690개다.
기준 구현에서는 후보마다 다음 두 번의 affine conversion이 발생한다.

1. `d * (s1 Q)`의 Jacobian 결과에서 `s2` 복원
2. `s2 * Q`의 Jacobian 결과에서 `r1` 복원

따라서 정답 전까지 `mpz_invert`가 21,380회 호출된다. 프로파일에서 point
doubling 898,148회, point addition 344,486회도 확인했다. 이 수치를 기준으로
x-only와 batch inversion을 평가했다.

## 후보 1: Brier--Joye x-only ladder

### 구현

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

### 결과와 실패 이유

Brier--Joye 원문이 제시하는 비용은 scalar bit마다 대략 field multiplication
14회와 constant multiplication 5회다. width-5 wNAF Jacobian은 비잔여 x를
sqrt 단계에서 제거하고, 남은 후보에만 doubling과 sparse addition을 수행한다.

x-only에서 curve 검사를 완전히 뒤로 미루면 정답 전의 모든 21,305개 x에
regular ladder를 실행해야 한다. 그 결과 8-thread 중앙값은 `1.003282 s`로,
기준 `0.486286 s`의 약 2.06배였다. `mpz_legendre`로 비잔여를 먼저 제거하면
`0.516119 s`까지 회복했지만 여전히 기준보다 6% 느렸다. 즉 이 문제에서는
sqrt 제거 이득보다 regular x-only ladder의 높은 per-bit 비용이 더 컸다.

Mike Hamburg의 후속 연구는 짧은 Weierstrass curve ladder를 bit당
`8M+3S+7A`까지 줄이지만, exceptional-point 처리까지 포함하는 별도 formula
set이 필요하다. 현재 Brier--Joye 결과만으로 제출 경로를 바꿀 근거는 없으며,
Hamburg formula는 향후 독립 후보로 남긴다.

## 후보 2: Montgomery batch inversion

### 구현

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

### 결과와 실패 이유

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

`r1`은 사실상 유일한 강한 early filter이고 `r2`, `r3` 계산은 `r1` hit 뒤로
미뤘다. x-only에서 curve-membership 검사까지 `r1` 뒤로 미루는 순서는
비잔여 후보에도 비싼 ladder를 수행해 실패했다.

## 반복 측정

환경:

```text
CPU: AMD EPYC 7B12
logical CPUs / threads: 8 / 8
compiler: g++ 12.2.0, -O3 -DNDEBUG -std=c++20 -fopenmp
arithmetic: GMP 6.2.1
protocol: warmup 1회, 측정 5회, 매 round 실행 순서 회전
```

아래 값은 solver 내부의 state-recovery 구간 중앙값이다. telemetry 분석과
process 시작 비용은 제외했다. 모든 sample에서 `d`, `s2`, `r3`를 검증했다.

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

## 참고 자료

- [Eric Brier and Marc Joye, "Weierstrass Elliptic Curves and Side-Channel Attacks" (2002)](https://marcjoye.github.io/papers/BJ02espa.pdf) — Figure 3의 ladder invariant와 식 (6), (7), (9), (10)의 x-only differential addition/doubling을 그대로 구현했다. 원문은 projective ladder 비용도 bit당 약 14 multiplications로 분석한다.
- [Mike Hamburg, "Faster Montgomery and double-add ladders for short Weierstrass curves" (TCHES 2020 / ePrint 2020/437)](https://eprint.iacr.org/2020/437) — Brier--Joye 이후 short-Weierstrass ladder의 operation count 개선과 exceptional-point 문제를 검토하는 데 사용했다.
- [Peter L. Montgomery, "Speeding the Pollard and Elliptic Curve Methods of Factorization" (Mathematics of Computation, 1987)](https://www.ams.org/journals/mcom/1987-48-177/S0025-5718-1987-0866113-7/S0025-5718-1987-0866113-7.pdf) — differential-addition ladder와 inversion amortization의 원형을 확인했다.
- [Daniel J. Bernstein et al., "OpenSSLNTRU: Faster post-quantum TLS key exchange" (2021), Section 2.2](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf) — Montgomery batch inversion의 prefix/reverse 알고리즘과 `3n-3` multiplications + 1 inversion 비용을 대조했다.
- [GNU MP Manual, Number Theoretic Functions](https://gmplib.org/manual/Number-Theoretic-Functions) — `mpz_invert`와 `mpz_legendre`의 공식 API 의미를 확인했다.
