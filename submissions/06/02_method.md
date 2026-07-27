# 6번 Dual_EC_DRBG 분석 및 최적화

## 결과

```text
d                 = 0x1c3cdd6b221806db0a7b28
legacy scan s2    = 0x638d9d631ab436da51e640
shifted scan s3   = 0x948173253ad6d120a3f562
r3                = 0x2443c8daf1a9d52b09
```

여기서 `0x638d...`는 `s1`이 아니라 `s2`다. `r0`에서 lift한 점이
`s1 Q`이고 `d(s1 Q)=s1 P`의 x좌표가 `s2=X(s1 P)`이기 때문이다.

## telemetry의 비밀 스칼라 복원

`B=2^20`이라 두면 첫 telemetry 행은 다음과 같다.

```text
(scale0*d + offset0) mod n = summary0*B + low,  0 <= low < B
```

`v=scale0^{-1} mod n`과 `low=0`일 때의 후보 `d0`를 구하면
`d(low)=d0+low*v mod n`이다. 이를 둘째 행에 대입해 다음 modular
interval을 얻었다.

```text
(a*low+c) mod n in [L,U)
a = scale1*v mod n
c = scale1*d0+offset1 mod n
L = summary1*B, U = min((summary1+1)*B,n)
```

`F(k,m,a,b)=sum floor((a*i+b)/m)`를 Euclidean recurrence로 계산하고

```text
count((a*i+b) mod m < y)
 = k - (F(k,m,a,b+m-y)-F(k,m,a,b))
```

를 사용하면 임의의 `low` 구간에 해가 몇 개인지 `O(log n)`에 센다.
해가 있는 구간만 이분해 이 인스턴스의 유일한 `low=0x1f051`을 찾았다.
복원한 `d`는 여섯 telemetry 행 전체와 전체 점 등식 `P=dQ`로 재검증했다.
기존 `2^20` 전수조사는 중앙값 1,453.475ms, 이 방법은 0.750ms로 약
1,938배 차이가 났다.

## 출력 lift와 다음 값 예측

기본 Python/GMP 경로는 `r0` 뒤에 가능한 하위 16비트를 붙여
`x=(r0<<16)|low16`을 만들고,
`y^2=x^3+ax+b mod p`의 제곱근이 있는 x만 남겼다. lift한 점을 `R=s1Q`라
하면 백도어 관계로 다음 상태를 직접 얻는다.

```text
s2 = X(dR)
```

이 `s2`에서 `r1`을 재생해 후보를 거르고, `s3=X(s2P)`에서 `r2`까지
검증했다. 유일한 생존 상태에서 `s4=X(s3P)`와
`r3=TMSB(X(s4Q))`를 계산해 위의 정답을 얻었다.

최종 native 경로는 같은 공격을 한 칸 뒤로 옮겼다. `r1`을 lift한
`T=±s2Q`에서 `X(dT)=s3`를 얻고 공개 `r2`로 후보를 거른 뒤 `r3`를
예측한다. true low가 `0x5338`에서 `0x3cea`로 바뀌어 정답을 포함한
순차 prefix가 21,305개에서 15,595개로 26.8% 줄었다. 40개 adjacent
AB/BA pair에서 paired median `1.3428x`, bootstrap 95% CI
`1.3336..1.3510`으로 stationarity gate를 통과했다.

## 구현 최적화

- `(x,+y)`와 `(x,-y)`는 각각 `R,-R`이고 `X(dR)=X(-dR)`이므로 한
  부호만 계산했다.
- GMP 임의 점 `d`배는 width-5 wNAF를 사용한다. 최종 native hot path는
  Hamburg co-Z x-only ladder이며 exceptional input은 width-2 NAF로
  fallback한다.
- 반복되는 고정점 `Q`는
  `table[i][j]=j*2^(8i)Q`인 11x256 byte-comb table을 만들었다. 이후
  fixed-base 곱은 최대 11번의 table point addition으로 끝난다.
- 최종 Python은 제3자 패키지 없이 `int`로 동작하고, 설치되어 있으면
  `gmpy2`를 선택한다. 별도 C++20/GMP 구현은 low-16 탐색을 OpenMP
  dynamic 64-candidate chunk로 병렬화한다.

알고리즘 단계에서는 Brier--Joye x-only ladder, block batch inversion,
width-4 wNAF, Legendre 선필터와 연속 cubic finite difference를 각각 반복
비교했다. 가장 좋은 명목상 결과도 GMP 기준 1.023배였고 표준편차보다
차이가 작았으며, x-only는 최대 약 2.06배 느렸다. 따라서 수학적 공격은
유지하고 arithmetic와 cache layout을 별도로 최적화했다.

최고 성능 C++ 경로는 88비트 체를 16바이트 2-limb Montgomery 값으로
구현한다. BMI2/ADX에서는 `_mulx_u64`와 carry/borrow intrinsic을 쓰고,
지원하지 않는 target은 portable `unsigned __int128` 경로로 fallback한다.
Jacobian point는 48바이트 POD다. 임의점 scan은 동형 `a=-3` 곡선과
Hamburg ladder를 쓰고, 고정 `Q` table은 구축 중
batch-normalize한 90,112바이트 affine table로 만들어 generic addition
대신 mixed addition을 쓴다. Hamburg 정상 경로에는 y좌표가 필요 없으므로
모든 lift에서 제곱근 지수승을 하지 않고 Montgomery residue의 hybrid
128/64비트 Euclidean Jacobi symbol만 계산한다. `R=2^128`은 제곱이므로
canonical 변환 없이도 symbol이 같다. denominator 예외에서 NAF fallback이
필요할 때만 실제 제곱근을 지연 계산한다.

곡선군은 `#E(Fp)=5n`, `ord(Q)=n`이다. `p mod 5=4`라 Koshelev의
basic-field 조건 `5 | p-1`은 성립하지 않으므로, `Fp2` Frobenius `-1`
eigenspace의 order-5 점으로 Tate/Miller 값을 전개했다.
`W=f(T)^p/f(T)`의 trace `tau=W+W^-1`는 y가 소거되어 x만으로 계산되고,
`W^p=W^-1`이므로 norm-one 군에 있다. `E=(p+1)/5=20H`라 두면
`L_E=2`는 `z=W^H`에 대해 `z^20=1`과 동치다. 따라서 fixed PRAC으로
`L_H`를 계산하고 `mu_20/{z~z^-1}`의 정확히 11개 trace와 비교한다.
115-byte schedule은 `118M+6S=124` products로 binary Lucas의
`85M+85S=170`보다 27.1% 적다. block은 trace fraction을 직접 준비하고
in-place compact한 뒤 모든 분모를 한 번에 batch-invert한다. 정답
prefix의 curve-valid 7,713개 중 직접 `[n]T=O`인 1,547개와 trace 결과가
모두 일치해 Hamburg 호출의 79.94%를 제거한다.

binary/separate-array 기준과 PRAC/direct-fraction 기본 경로의 1-thread
40-pair campaign은 두 번 모두 통과했다. paired median과 CI는 각각
`1.0345x`(`1.0271..1.0448`), `1.0311x`
(`1.0268..1.0376`)였다.
최종 감사 뒤 같은 비교는 median `1.0289x`였지만 CI
`0.9791..1.0878`와 53.8%/72.1%의 절대 block spread로 stationarity를
실패해 audit-snapshot correctness 확인용 진단으로만 남겼다. 이후
최종 변경은 timed path가 아니라 direct-fraction 경계 self-test만
강화했다.

연속 candidate block은 atomic counter로 배분한다. 최종 adaptive 정책은
1 thread에서 block/batch inverse 64개, 2 threads에서 block 32개, 3 threads
이상에서 scalar 64개다. 2-thread만 별도 고정 CPU 40-pair 검사를 통과했기
때문에 다른 thread 수로 보간하지 않았다. AVX2는 packed 64x64→128 정수
곱이 없어 radix 분해와 lane compaction 비용이 커지므로 보류했다.

`a=-3`의 직교 측정은 `1.1022x`(CI `1.0320..1.1274`)였지만
stationarity gate를 실패해 성능 수치는 diagnostic-only다. 원곡선
compile-time fallback과 실제 lift 교차 검증을 함께 유지한다.

후속 후보도 같은 정확성·측정 gate로 판정했다. balanced signed-w9는 table을
82,560바이트로 줄였지만 `1.0065x`에 그쳤고, comb row별 affine batch는
`0.9351x`로 느렸다. 나눗셈을 반복 뺄셈으로 바꾼 Jacobi는 `1.0072x`이며
CI가 parity를 포함했다. 두 후보는 실험 macro만 남기고 unsigned w8 table과
Euclidean Jacobi를 유지했다. 부분군 필터의 직접 `Fp2` character 변형은
sqrt가 필요해 paired `1.1643x`에 그쳤고, x-only trace의 `1.9444x`보다
느려 기각했다. elliptic-point scalar PRAC은 고정 `d`의 Hamburg보다
불리했지만, 이는 채택한 Lucas-recurrence PRAC과 별개다.

Lucas 쪽에서는 `E/4` 뒤 `mu_4` trace 비교가 128 products,
factor composition이 약 136이라 최종 124보다 길었다. dynamic PRAC은
hot U128 division/remainder가 필요했고, 84-step binary 완전 unroll과
fused PRAC은 code-size/dispatch 비용 때문에 느렸다. binary 2-lane은
`1.0180x`, branchless mask-select는 `0.9770x`, U64 bit stream은
`1.0068x`라 기본값으로 승격하지 않았다. direct fraction layout 단독도
`1.0007x`였지만 compact PRAC과 결합했을 때만 반복 PASS했다.

복잡도는 telemetry가 이 인스턴스에서 `O(log B log n)`, 상태 탐색 work가
최악 `O(2^16 log n)`이다. native 고정 table 외 탐색 메모리는 worker마다
상수 크기다.

## 반복 측정

AMD EPYC 7B12 VM(8 logical CPU), Python 3.11.2, G++ 12.2.0에서 각 구현을
1회 warm-up한 뒤 완전한 공격을 5회 교차 실행했다. 매 표본마다 `d`,
`r3`와 경로별 `s2/s3`를 검증하고 median/MAD/raw sample을 보존했다.

| 구현 | 중앙값 | 중앙값 비율 | paired 중앙값 |
|---|---:|---:|---:|
| 기존 Python | 14.298741 s | 1.00x | 1.00x |
| 최적화 Python `int` | 3.272242 s | 4.37x | 4.41x |
| 최적화 Python `gmpy2` | 3.000356 s | 4.77x | 4.61x |
| C++/GMP 1 thread | 1.873220 s | 7.63x | 7.44x |
| C++/GMP/OpenMP 8 threads | 0.447919 s | 31.92x | 30.75x |

8-thread MAD는 0.022003초(4.91%)였고 paired p05--p95는
25.21x--33.48x였다. 앞선 독립 반복에서도 0.445551초를 얻었다.

다음 native 표는 이번 추가 최적화 전 경로를 원본 Python/GMP와 같은
interleaved run에서 warm-up 1회 후 각각 5회 측정한 역사 기준선이다.

| 구현 | 중앙값 | MAD | 비교 |
|---|---:|---:|---:|
| 기존 Python | 14.073190 s | 0.295610 s | 1.00x |
| GMP 1 thread | 1.971840 s | 0.048047 s | — |
| native 1 thread | 0.362651 s | 0.009200 s | Python 대비 38.81x, GMP 대비 5.44x |
| GMP 8 threads | 0.436403 s | 0.007239 s | — |
| native 8 threads | 0.085076 s | 0.006915 s | Python 대비 165.42x, GMP 대비 5.13x |

후속 40-pair 승격 측정에서 shifted scan은 `1.3428x`
(95% CI `1.3336..1.3510`), Hamburg는 `1.1716x`
(95% CI `1.1682..1.1764`), sqrt/Jacobi는 `1.0819x`
(95% CI `1.0769..1.0842`), 2-thread scalar64/adaptive-block32는
`1.2121x`(95% CI `1.2051..1.2163`)였고 모두 stationarity gate를 통과했다.
no-subgroup-filter/trace-filter는 1 thread에서
`0.085280/0.044124 s`, paired `1.9444x`(CI `1.9113..1.9687`), 2
thread에서 `0.053521/0.030619 s`, paired `1.7448x`(CI
`1.7161..1.7904`)였다. 모든 effect block이 1.71x 이상이었지만 shared
host 포화로 stationarity는 실패해 절대 시간은 diagnostic-only다.
이는 source SHA-256
`5f169154d1c3b681a496169b6f4ec456a5a55c41c5986bf1ae27b5e1e90005a8`을
고정한 campaign이다. 이후 최종 source의 중복 `PreparedLift` 저장과
`x^2` 계산을 제거하고 correctness를 재검증했지만, 포화된 host에서 같은
no-subgroup-filter/trace-filter ablation은 다시 수치화하지 않았다.
Jacobi와 새 2-thread 정책 전 source의 전체 legacy/당시-final holdout은
warm-up 10쌍 뒤 paired `3.7126x`(95% CI `3.7106..3.7251`)였다. 이는 현재
전체 stack의 합산 수치가 아니라 이전 단계의 역사적 같은-source 비교다.

timing 전에 독립 canonical arithmetic와 affine reference로 field 2,000개,
64개 경계 field pair, point/scalar 256개와 실제 lift Hamburg/NAF 및
scalar/batched subgroup 128개를 교차 검증했다. Sage에서도 무작위 200점과
실제 prefix 전부를 직접 `[n]T`와 비교해 mismatch 0을 확인했다. signed
carry와 subgroup order 경계도 point vector에 넣고, 모든 Jacobi 변형을
Fermat/Legendre와 비교했다. 11개 `mu_20` trace의 uniqueness와
`L_20=2`, runtime Montgomery 변환, 2,000 random+boundary trace의
binary/PRAC 일치도 검사했다. direct-fraction batch는 256-entry 경계와
분모 0을 주입한 compaction/fail-closed 경로도 검사했다.
pattern-initialized build도 전체 self-test/KAT를 통과했다. 모든 측정
process도 `P=dQ`, `d`, `r3`, `state_label`별 `s2/s3`, 정답 low bits와
요청/실제 thread·schedule·table·residue metadata를 다시 검사했다.

## 참고 자료

- [Shumow--Ferguson, *On the Possibility of a Back Door in the NIST SP800-90 Dual EC PRNG*](https://rump2007.cr.yp.to/15-shumow.pdf): truncated output lift와 숨은 점 관계 공격.
- [AtCoder Library `floor_sum`](https://atcoder.github.io/ac-library/production/document_en/math.html), [공식 구현](https://github.com/atcoder/ac-library/blob/master/atcoder/internal_math.hpp): Euclidean floor-sum recurrence.
- [Explicit-Formulas Database](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html): short-Weierstrass Jacobian 점 연산 공식.
- [Morain--Olivos, *Speeding up the computations on an elliptic curve using addition-subtraction chains*](https://www.numdam.org/item/ITA_1990__24_6_531_0/): NAF addition-subtraction chain.
- [Brier--Joye, *Weierstrass Elliptic Curves and Side-Channel Attacks*](https://marcjoye.github.io/papers/BJ02espa.pdf): X/Z-only ladder 후보.
- [EFD `a=-3` Jacobian formulas](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian-3.html): 동형 곡선 doubling 공식.
- [Hamburg, *Faster Montgomery and double-add ladders for short Weierstrass curves*](https://eprint.iacr.org/2020/437), [공식 supplementary formulas](https://github.com/bitwiseshiftleft/ladder_formulas): 실제 구현한 co-Z ladder, exceptional case와 대조한 Figure 4/6 DAG.
- [Möller, *Efficient computation of the Jacobi symbol*](https://arxiv.org/abs/1907.07795), [GNU MP Jacobi algorithm](https://gmplib.org/manual/Jacobi-Symbol.html): Euclidean reduction 중 quadratic-reciprocity 부호 갱신.
- [Koshelev, *Subgroup membership testing on elliptic curves via the Tate pairing*](https://eprint.iacr.org/2022/037.pdf): small-cofactor pairing test의 출발점. basic-field 조건은 성립하지 않아 `Fp2`로 확장했다.
- [Enge, *Bilinear pairings on elliptic curves*](https://arxiv.org/abs/1301.5520): Miller recurrence와 reduced Tate pairing을 x-only Frobenius trace로 전개할 때 참고했다.
- [Montgomery, *Evaluating recurrences via Lucas chains*](https://cr.yp.to/bib/1992/montgomery-lucas.pdf): differential Lucas chain과 PRAC rule.
- [Zimmermann--Dodson, *20 years of ECM*, Section 2.2](https://members.loria.fr/PZimmermann/papers/ecm-submitted.pdf): PRAC seed와 operation-cost 탐색.
- [Kutz, *Lower Bounds for Lucas Chains*](https://epubs.siam.org/doi/10.1137/S0097539700379255): Fibonacci형 길이 하한의 맥락; 124-product chain의 최적성 증명으로 쓰지는 않았다.
- [GMP-ECM `lucas.c`](https://sources.debian.org/src/gmp-ecm/7.0.6%2Bds-2/lucas.c/): production PRAC rule update와 대조.
- [Bernstein et al., *OpenSSLNTRU*](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf): prefix/reverse batch inversion 비용.
- [Montgomery, *Modular Multiplication Without Trial Division*](https://doi.org/10.1090/S0025-5718-1985-0777282-X): 2-limb REDC와 Montgomery 표현.
- [GNU MP Manual](https://gmplib.org/manual/) 및 [OpenMP 5.2](https://www.openmp.org/spec-html/5.2/openmp.html): C++ arithmetic와 병렬 구현.
