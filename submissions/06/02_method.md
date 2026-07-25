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
대신 mixed addition을 쓴다. 연속 64-candidate block을 atomic counter로
배분하며, 1 thread에서는 batch inverse, 다중 thread에서는 scalar
pipeline을 택한다. AVX2는 packed 64x64→128 정수 곱이 없어 radix 분해와
lane compaction 비용이 커지므로 보류했다.

`a=-3`의 직교 측정은 `1.1022x`(CI `1.0320..1.1274`)였지만
stationarity gate를 실패해 성능 수치는 diagnostic-only다. 원곡선
compile-time fallback과 실제 lift 교차 검증을 함께 유지한다.

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
(95% CI `1.1682..1.1764`)였고 둘 다 stationarity gate를 통과했다.
최종 source의 전체 legacy/final holdout도 warm-up 10쌍 뒤 paired
`3.7126x`(95% CI `3.7106..3.7251`)로 gate를 통과했다.

timing 전에 독립 canonical arithmetic와 affine reference로 field 2,000개,
64개 경계 field pair, point/scalar 256개와 실제 lift Hamburg/NAF 128개를
교차 검증했다. 모든 측정 process도 `P=dQ`, `d`, `r3`와
`state_label`별 `s2/s3`, 정답 low bits를 다시 검사했다.

## 참고 자료

- [Shumow--Ferguson, *On the Possibility of a Back Door in the NIST SP800-90 Dual EC PRNG*](https://rump2007.cr.yp.to/15-shumow.pdf): truncated output lift와 숨은 점 관계 공격.
- [AtCoder Library `floor_sum`](https://atcoder.github.io/ac-library/production/document_en/math.html), [공식 구현](https://github.com/atcoder/ac-library/blob/master/atcoder/internal_math.hpp): Euclidean floor-sum recurrence.
- [Explicit-Formulas Database](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html): short-Weierstrass Jacobian 점 연산 공식.
- [Morain--Olivos, *Speeding up the computations on an elliptic curve using addition-subtraction chains*](https://www.numdam.org/item/ITA_1990__24_6_531_0/): NAF addition-subtraction chain.
- [Brier--Joye, *Weierstrass Elliptic Curves and Side-Channel Attacks*](https://marcjoye.github.io/papers/BJ02espa.pdf): X/Z-only ladder 후보.
- [EFD `a=-3` Jacobian formulas](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian-3.html): 동형 곡선 doubling 공식.
- [Hamburg, *Faster Montgomery and double-add ladders for short Weierstrass curves*](https://eprint.iacr.org/2020/437): 실제 구현한 co-Z ladder와 exceptional case.
- [Bernstein et al., *OpenSSLNTRU*](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf): prefix/reverse batch inversion 비용.
- [Montgomery, *Modular Multiplication Without Trial Division*](https://doi.org/10.1090/S0025-5718-1985-0777282-X): 2-limb REDC와 Montgomery 표현.
- [GNU MP Manual](https://gmplib.org/manual/) 및 [OpenMP 5.2](https://www.openmp.org/spec-html/5.2/openmp.html): C++ arithmetic와 병렬 구현.
