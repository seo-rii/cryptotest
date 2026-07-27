# 6번 state recovery 알고리즘 심층 검토

## 결론

첫 GMP 후보군에서는 안정적인 개선을 찾지 못했지만, native 경로를 다시
검토해 서로 독립적인 다섯 알고리즘 개선을 채택했다.

1. `r0`를 lift해 `r1`로 거르는 대신 **`r1`을 lift해 `r2`로 거른다**.
   이 인스턴스의 순차 검사량은 21,305개에서 15,595개로 26.8% 줄었다.
2. lift마다 실행하는 고정 스칼라 `d` 곱을 width-2 NAF에서 Hamburg의
   short-Weierstrass co-Z x-only ladder로 바꿨다. exceptional denominator는
   완전한 NAF 경로로 되돌아가도록 fail-closed 처리했다.
3. Hamburg 정상 경로에 y가 필요 없다는 점을 이용해 매 lift의 sqrt를
   Montgomery residue의 hybrid 128/64비트 Jacobi symbol 판정으로 바꾸고,
   exceptional NAF fallback에서만 sqrt를 지연 실행한다.
4. `#E(Fp)=5n`의 작은 cofactor를 이용해, `Fp2`의 비유리 5-torsion으로
   만든 Frobenius--Tate trace가 order-`n` 부분군인지 x좌표만으로 먼저
   판정한다. block에서는 모든 분모를 한 번에 batch-invert한다.
5. 이 trace의 86비트 binary Lucas ladder를
   `E=(p+1)/5=20H` 분해와 고정 Lucas-PRAC chain으로 바꾸고, `L_H`를
   `mu_20`의 11개 trace와 비교한다. trace fraction도 caller 배열에
   직접 준비하고 in-place compact한다.

40개 adjacent balanced AB/BA pair, 5,000회 deterministic bootstrap,
4개 시간 block stationarity gate를 사용한 1-thread 측정에서 shifted scan은
paired median `1.3428x`(95% CI `1.3336..1.3510`), Hamburg는
`1.1716x`(95% CI `1.1682..1.1764`)였고 둘 다 gate를 통과했다. 따라서
최종 source의 sqrt/Jacobi 비교도 `1.0819x`(95% CI
`1.0769..1.0842`)로 gate를 통과했다. 첫 세 후보를
`deep_native_06.cpp`의 기본값으로 승격했다. 네 번째
부분군 필터도 아래의 전수 수학 검증과 큰 반복 측정 효과를 근거로
기본값에 넣었다. 다섯 번째 후보는 아래 1-thread 승격 campaign 두 번에서
각각 `1.0345x`(CI `1.0271..1.0448`)와
`1.0311x`(CI `1.0268..1.0376`)로 모든 gate를 통과했다.
Brier--Joye, GMP batch
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
Montgomery 우변에 대해 `(aR/p)=(a/p)`만 Euclidean reduction으로 구한다.
여기서 `R=2^128=(2^64)^2`이므로 Montgomery factor 자체가 제곱이고 Jacobi
symbol을 바꾸지 않는다. 결과가
`-1`이면 비잔여이므로 버리고, `+1`이면 Hamburg를 실행한다. denominator가
0인 exceptional input에서만 기존 sqrt로 y를 복원해 완전한 NAF로
fallback한다.

이는 아래에서 실패한 `mpz_legendre + sqrt`와 비용 구조가 다르다. 그 후보는
두 exponentiation을 이어서 실행했지만, 최종 native Jacobi는 U128
Euclidean 단계 뒤 두 피연산자가 64비트가 되는 순간 U64 루프로 전환해
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

## 후속 native 검토

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

## 채택 4: cofactor-5 Frobenius--Tate trace 선필터

PARI의 `ellcard`, `ellgroup`, `ellorder`로 다음을 독립 확인했다.

```text
#E(Fp) = 5*n = 262358068131633367380937105
E(Fp)  = cyclic
ord(Q) = n
```

shifted 정답 prefix에서 curve-valid lift는 7,713개이고 그중 `[n]T=O`는
1,547개다. true lift는 `s2*Q`이므로 order-`n` subgroup에 있고, 정확한
membership filter는 Hamburg 호출의 6,166/7,713 = 79.94%를 제거한다.
단순 `[n]T`는 대략 Hamburg 한 번의 비용이라 손해다.

Koshelev의 basic-field 알고리즘은 작은 cofactor `ℓ=5`가 `p-1`을
나눠야 한다.
이 곡선은 `p mod 5=4`라 `5∤p-1`이므로 그대로 적용할 수 없다. 대신
`Fp2=Fp[v]/(v^2-2)`에서 Frobenius가 `v^p=-v`로 작용하는 order-5 점

```text
P-  = (alpha, beta*v)
2P- = (gamma, delta*v)
alpha = d59dbc5a89d7c3dcfc7aef
beta  = c34366b11d118d0d635fbb
gamma = 0e953f99abc72cff8f3ff9
delta = 94b152fc315f97ae6ea4c7
```

을 사용했다. 두 tangent slope는 각각 `m1*v`, `m2*v`이고,
`m1=d1e74749596975d56c869e`,
`m2=3a7862416ae71b5fea671e`다. Miller recurrence를 order 5에 전개한 뒤
`W=f(T)^p/f(T)`와 `tau=W+W^-1`을 취하면 lift의 y가 소거된다. 변환 곡선의
`r=x^3-3x+b`에 대해 실제 코드는 다음 Fp 식만 계산한다.

```text
A = beta + m1*(x-alpha)
B = delta + m2*(x-gamma)
C = r + 2*A^2 + 4*A*B
D = -((r + 2*A^2)*B + 2*r*A)
U = r*C^2
V = 2*D^2
tau = 2*(U+V)/(U-V)
```

Miller quotient에는

```text
W^p = f(T) / f(T)^p = W^-1
```

가 성립한다. 따라서 `W^(p+1)=1`이고 `W`는 norm-one torus
`mu_(p+1)`에 있다. 먼저
`E=(p+1)/5=0x2b674bdfd6f921287caaec`라 놓고
`L_k=W^k+W^-k`를

```text
L_2k   = L_k^2 - 2
L_2k+1 = L_k*L_k+1 - tau
```

의 고정 86비트 binary ladder로 계산하면 `L_E=2`일 때와 오직 그때만
order-`n` 부분군이다. 이 기준 구현은 `85M+85S=170` field product를
쓴다.

최종 경로는 `E=20H`,
`H=0x22b9097fdf2db42063bbf`로 분해한다. `z=W^H`라 하면

```text
L_E = 2
<=> z^20 + z^-20 = 2
<=> (z^20 - 1)^2 / z^20 = 0
<=> z^20 = 1.
```

따라서 `L_H=z+z^-1`가 `mu_20` 원소의 trace인지만 확인하면 된다.
`20 | p+1`이고 `z^p=z^-1`이므로 이 trace는 `Fp`에 있다. inversion
quotient `z ~ z^-1`에는 `z=1,-1`인 singleton 두 개와 나머지 18개가
쌍으로 들어가므로 가능한 값은 정확히 11개다. 구현에 넣은 canonical
trace table은 다음과 같다.

```text
2
49321ac5168966c4e21a84
464f7cf080ef9f665193b9
bf1ef683b3802a2312bcf5
464f7cf080ef9f665193b8
0
92b4fe6eb1ee06641dc2e3
19e584db7f5d7ba75c99a6
92b4fe6eb1ee06641dc2e2
8fd2609a1c543f058d3c17
d9047b5f32dda5ca6f5699
```

Lucas differential identity

```text
L_(a+b) = L_a*L_b - L_(a-b)
L_2a    = L_a^2 - 2
```

때문에 Montgomery의 PRAC 변환을 이 recurrence에 그대로 적용할 수
있다. offline 탐색에서 고른 seed
`r=0x1575ba2094b05be88186b`의 fixed schedule은 115바이트이고,
rule 3이 109회, rule 4가 4회, rule 5와 rule 1이 각각 1회이며 91개
opcode가 pre-swap을 갖는다. schedule SHA-256은
`18b8ddcc131e735e129646411153b5ad76d413e76087e42503cfd56f16a5d739`다.
최종 multiply까지 `118M+6S=124` products로, binary의 170보다 27.1%
적다. 이 backend에서 square도 `field_multiply(x,x)`이므로 M/S를 같은
단위로 합산했다. 11개 table equality에는 field multiplication이 없다.

trace 준비 `6M+3S`, batch inverse의 후보당 약 4M까지 더하면 최종
membership 비용은 약 137 products다. Hamburg의 초기화와 마무리를
포함한 전체 비용은 약 930 products이고, 79.94% reject율을 곱한 filter
손익분기점은 약 743 products이므로 충분히 작다. caller가
`SubgroupTraceFraction`을 직접 준비하고 batch
함수가 이를 앞쪽으로 in-place compact한다. 최종 1-lane 경로는 reverse
pass에서 normalized trace를 지역값으로 계산하고, multi-lane ablation만
numerator를 덮어쓴다. GCC 12의 raw function-prologue stack allocation은
binary/xy의 `0x38a8`에서 PRAC/direct의 `0x1180`으로 줄었다. 유효
rational lift에서는 trace 분모 `U-V`가 0이 될 수 없지만 구현은 0을
만나면 fail-closed로 거부한다.

124는 증명된 전역 최적값이 아니라 찾은 schedule 중 최선이다.
Fibonacci 성장으로 보는 이 지수의 하한 맥락은 약 117 products이고,
golden ratio와 Zimmermann--Dodson의 transformed-alpha 후보 주변을 더
탐색했지만 124보다 짧은 chain은 찾지 못했다.

검증은 세 겹으로 했다. Sage에서 고정 torsion과 Frobenius 관계, 무작위
200점, 정답까지의 curve-valid 7,713점을 확인했고 trace 판정 1,547개와
직접 `[n]T=O` 1,547개 사이 mismatch는 0이었다. C++에서도 scalar와 batched
trace를 실제 lift 128개에서 직접 `[n]T`와 비교하고, `Q` 양성 벡터와
`Fp`-rational order-5 점 음성 벡터를 검사한다. 추가 self-test는 11개
상수가 서로 다르고 모두 `L_20=2`인지 확인하며, canonical-to-Montgomery
상수를 runtime 변환과 대조한다. 64개 field 경계 pair와 2,000개
deterministic random trace에서 fixed PRAC 결과가 binary `L_E=2`
oracle과 일치하고, schedule byte hash와 연산 수는 독립 생성기로
재계산했다. direct-fraction batch는 `1/2/3/4/5/7/127/128/129/255/256`
tail과 256번 원소의 `uint8_t` index를 검사한다. 양성 하나를 포함해 분모
0을 세 위치에 주입하고 255번도 양성으로 만든 256-entry 입력으로
in-place compaction, 원래 index 복원과 active-count 253의 2/4-lane
scalar tail을 검사한다. 전부 분모 0인 입력도 모두 fail-closed인지
확인한다.

binary/separate-array 기준과 PRAC/direct-fraction 후보의 1-thread
40-pair campaign은 두 번 모두 승격 gate를 통과했다. 첫 run은 paired
`1.0345x`(CI `1.0271..1.0448`), 다른 benchmark-order seed의 독립 run은
`1.0311x`(CI `1.0268..1.0376`)였고 둘 다 AB/BA 두 순서와 네
stationarity block이 PASS였다. 최종 기본 매크로로 바꾼 후의 재실행도
`1.0382x`(CI `1.0248..1.0537`)였지만 후반 host phase 변화로
stationarity만 실패해 보조 수치로 남겼다. 8-thread run도 중앙값
`1.0381x`였으나 CI `0.9070..1.1621`로 너무 넓어 성능 주장에 쓰지
않는다. 최종 감사 뒤 source SHA-256
`840999f697112a17c7ebe6809351b4971b1a713d021e4c356334e3c4462ae073`를
seed `0x44444444`로 다시 고정한 run은 중앙값 `1.0289x`였지만 CI
`0.9791..1.0878`, baseline/candidate block spread `53.8%/72.1%`로
더 불안정했다. 이 run도 audit snapshot의 correctness 확인으로만 남기고
승격 근거에는 포함하지 않는다. 최종 source
`a97d24e5d6a581da586c0df48beb64abdeb6ab60273f2cdd00a352b74aa8df16`은
양성 255번, zero-denominator compaction과 multi-lane tail self-test만
강화했고 timed hot path는 바꾸지 않았다.

### Lucas chain 후보별 실패 기록

**86비트 binary ladder.** 처음 채택한 기준은 고정 bit pattern이라
간단하고 검증하기 쉬웠지만 매 bit에 multiply와 square가 하나씩 필요해
`85M+85S=170` products를 쓴다. 최종 PRAC oracle과 ablation 기준으로는
남겼지만 기본 hot path에서는 교체했다.

**`E/4`와 factor-by-factor composition.** `L_(E/4)`를 PRAC으로 계산한
뒤 `mu_4` traces `{0,2,-2}`와 비교하는 방법도 정확하고 약 128 products로
줄었다. 그러나 `E=20H`의 124보다 네 번 많았다. `E`의 인수를 여러 작은
Lucas composition으로 나누는 후보도 약 136 products라 같은 이유로
기각했다.

**dynamic PRAC.** 매 후보마다 `(d,e)`를 줄이는 일반 PRAC을 실행하면
88/128비트 division, remainder와 rule 선택이 hot loop에 들어간다.
지수는 고정이므로 이 비용을 지불하지 않고 offline에서 schedule을 만든
뒤 115 opcode만 해석하는 경로를 택했다.

**완전 unroll과 fused switch.** 84-step binary loop를 template로 모두
펼치면 함수가 약 `0x510`에서 `0x298e`바이트로 팽창했고 CI가 매우
넓었다. PRAC opcode별 body를 크게 복제한 fused interpreter도
`0.9880x`로 졌다. 반면 compact generic interpreter는 단독으로
`1.0180x`(CI `1.0117..1.0286`)까지 왔지만 2% 문턱과 stationarity를
통과하지 못했고, direct-fraction layout과 결합했을 때만 반복 PASS했다.

**lane interleaving과 branchless binary step.** 두 candidate의 binary
Lucas를 교차 배치한 2-lane 경로는 `1.0180x`로 문턱 아래였고 PRAC
2-lane은 `0.9941x`였다. binary bit branch를 mask select로 바꾸면 함수는
`0x579`에서 `0x44c`바이트로 줄었지만 매 bit의 limb select가 늘어
`0.9770x`(CI `0.9609..0.9914`)로 명확히 느렸다.

필터를 끈 동일 source와의 CPU 고정 40-pair 측정은 1 thread에서 외부
중앙값 `0.085280/0.044124 s`, paired `1.9444x`(CI
`1.9113..1.9687`)였고 2 thread에서는 `0.053521/0.030619 s`,
paired `1.7448x`(CI `1.7161..1.7904`)였다. 모든 시간 block이 각각
`1.874x`, `1.718x` 이상이었지만, 다른 빌드가 동시에 실행된 shared host의
절대 시간과 effect spread가 엄격한 stationarity 문턱을 넘었다. 따라서
방향과 큰 효과는 분명하지만 이 절대 시간은 diagnostic-only로 기록한다.
이 campaign의 고정 source SHA-256은
`5f169154d1c3b681a496169b6f4ec456a5a55c41c5986bf1ae27b5e1e90005a8`이다.
이후 최종 source에서는 중복 `PreparedLift` 저장을 없애고 이미 계산한
`x^2`를 재사용했으며, 정확성 suite는 다시 통과시켰지만 포화된 host에서
같은 no-filter/filter ablation을 다시 측정하지는 않았다.

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
- [Dmitrii Koshelev, "Subgroup membership testing on elliptic curves via the Tate pairing"](https://eprint.iacr.org/2022/037.pdf) — 작은 cofactor Tate-pairing 검사의 출발점이다. 논문의 basic-field 조건 `e | p-1`은 여기서 성립하지 않으므로 그대로 적용하지 않고 `Fp2` Frobenius 고유공간으로 옮겼다.
- [Andreas Enge, "Bilinear pairings on elliptic curves"](https://arxiv.org/abs/1301.5520) — Miller 함수 recurrence, reduced Tate pairing과 Frobenius 작용을 전개해 x-only trace 식을 유도할 때 사용했다.
- [Peter L. Montgomery, "Evaluating recurrences of form
  X_(m+n)=f(X_m,X_n,X_(m-n)) via Lucas chains" (1983, rev.
  1992)](https://cr.yp.to/bib/1992/montgomery-lucas.pdf) — differential
  Lucas chain과 PRAC 변환의 원자료다.
- [Paul Zimmermann and Bruce Dodson, "20 years of ECM",
  Section 2.2](https://members.loria.fr/PZimmermann/papers/ecm-submitted.pdf) —
  golden-ratio 및 transformed-alpha PRAC seed 선택과 modular-multiplication
  비용 비교를 대조했다.
- [Martin Kutz, "Lower Bounds for Lucas Chains", *SIAM Journal on
  Computing* 31(6), 2002](https://epubs.siam.org/doi/10.1137/S0097539700379255) —
  Fibonacci 성장과 Lucas-chain 길이 하한의 맥락을 제공한다. 이 논문을
  124-op schedule의 전역 최적성 증명으로 사용하지는 않았다.
- [GMP-ECM `lucas.c`](https://sources.debian.org/src/gmp-ecm/7.0.6%2Bds-2/lucas.c/) —
  `pp1_mul_prac` rule 순서와 alias-safe state update를 구현과 대조했다.
- [Peter L. Montgomery, "Speeding the Pollard and Elliptic Curve Methods of Factorization" (Mathematics of Computation, 1987)](https://www.ams.org/journals/mcom/1987-48-177/S0025-5718-1987-0866113-7/S0025-5718-1987-0866113-7.pdf) — differential-addition ladder와 inversion amortization의 원형을 확인했다.
- [Daniel J. Bernstein et al., "OpenSSLNTRU: Faster post-quantum TLS key exchange" (2021), Section 2.2](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf) — Montgomery batch inversion의 prefix/reverse 알고리즘과 `3n-3` multiplications + 1 inversion 비용을 대조했다.
- [GNU MP Manual, Number Theoretic Functions](https://gmplib.org/manual/Number-Theoretic-Functions) — `mpz_invert`와 `mpz_legendre`의 공식 API 의미를 확인했다.
