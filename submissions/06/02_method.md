# 6번 Dual_EC_DRBG 분석 및 최적화

## 입력 파라미터와 결과

| 항목 | 값 |
|---|---|
| field | `p=0xd9047b5f32dda5ca6f569b` |
| curve | `y^2=x^3+a*x+b`, `a=0x674fdf5b55923897a16f40`, `b=0x1d0c9956783f6026e6c981` |
| `P` | `(0x5340e87bd80d1463a6ff8d, 0x94ebeb5ca5b3c685e00c20)` |
| `Q` | `(0x4a05101411039decf537a5, 0x3395a009c2210836b63d4b)` |
| subgroup order | `n=0x2b674bdfd6fc4ba4ba751d` |
| known outputs | `r0=0xb3939f4aadcc13ca74`, `r1=0x617985fad38ec3b1a3`, `r2=0xd8c20715ccc94d2283` |
| output truncation | x좌표 하위 16비트 제거 |
| telemetry | affine residue의 하위 20비트 제거, 정확한 생성식은 미제공 |

```text
d   = 0x1c3cdd6b221806db0a7b28
s2  = 0x638d9d631ab436da51e640
s3  = 0x948173253ad6d120a3f562
r3  = 0x2443c8daf1a9d52b09
```

`r0`에서 lift한 점은 `s1 Q`이고 `d(s1 Q)=s1 P`의 x좌표가 `s2`다.
같은 관계를 `r1`에서 시작하면 직접 복원되는 상태는 `s3`다.

## telemetry의 비밀 스칼라 복원

문제는 각 행이 같은 비밀 `d`에 대한 affine 함숫값의 하위 20비트를
버렸다고만 설명하고 정확한 식은 주지 않는다. `d`가 order-`n` 부분군의
스칼라라는 점에서 `scale`, `offset`을 `Z/nZ`의 원소로 보고, `B=2^20`일
때 다음의 가장 단순한 affine-residue 가설을 세웠다.

```text
u_i       = (scale_i*d + offset_i) mod n
summary_i = floor(u_i/B)
```

이는 입력으로 주어진 식이 아니라 검증할 추론이다. 여섯 `scale_i` 모두
`gcd(scale_i,n)=1`이므로 역원이 존재한다. 특히 첫 행은 다음과 같다.

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
복원한 `d`는 여섯 행에서
`((scale_i*d+offset_i) mod n)>>20=summary_i`를 모두 만족했다. 더 중요한
독립 검증으로 전체 타원곡선 점 등식 `P=dQ`도 성립했다. 따라서 누설식
추론과 복원값을 telemetry 내부 일치만으로 순환 검증한 것이 아니다.
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

native 경로는 같은 공격을 다음 관측쌍에 적용한다. `r1`을 lift한
`T=±s2Q`에서 `X(dT)=s3`를 얻고 공개 `r2`로 후보를 거른 뒤 `r3`를
예측한다. 정답 low가 `0x5338`에서 `0x3cea`로 바뀌어 정답을 포함한
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

곡선군은 `#E(Fp)=5n`, `ord(Q)=n`이다. Koshelev 본문의 basic-field
검사는 `5 | p-1`을 가정하지만, 같은 논문의 Appendix는 base change를
통한 extension-field 일반화를 제시한다. 여기서는 `p mod 5=4`인 dual
embedding degree 2의 경우를 `Fp2` Frobenius `-1` eigenspace의 order-5
점에 특수화하고, Tate/Miller 값을 이 인스턴스용 x-only 식으로 전개했다.
`W=f(T)^p/f(T)`의 trace `tau=W+W^-1`는 y가 소거되어 x만으로 계산되고,
`W^p=W^-1`이므로 norm-one 군에 있다. `E=(p+1)/5=20H`라 두면
`L_E=2`는 `z=W^H`에 대해 `z^20=1`과 동치다. 따라서 fixed PRAC으로
`L_H`를 계산하고 `mu_20/{z~z^-1}`의 정확히 11개 trace와 비교한다.
115-byte schedule은 `118M+6S=124` products로 binary Lucas의
`85M+85S=170`보다 27.1% 적다. block은 trace fraction을 직접 준비하고
in-place compact한 뒤 모든 분모를 한 번에 batch-invert한다. 정답
prefix의 curve-valid 7,713개 중 직접 `[n]T=O`인 1,547개와 trace 결과가
모두 일치해 Hamburg 호출의 79.94%를 제거한다.

expanded trace의 분자와 분모를 `x`에 대한 다항식으로 다시 인수분해하면

```text
U-V       = (x-gamma)^4 * (x-alpha)^5
2*(U+V)   = (x-gamma)^4
            * (2*y^5+c1*y^4+c2*y^3+c3*y^2+c4*y+c5)
y         = x-alpha
```

가 정확히 성립한다. 따라서 `z=y^-1`에 대해
`tau=2+c1*z+c2*z^2+...+c5*z^5`를 Horner 법으로 계산한다. 공통인
`(x-gamma)^4`를 없애고 이미 구한 `z`를 재사용해 trace 비용을
`6M+3S`에서 `5M`으로 줄였다. 원식에서 정의되지 않는 `x=alpha,gamma`는
동일하게 fail-closed 처리한다.

다섯 계수는 다시

```text
r = lambda*z
tau = 2 + r*((r+h)^2+k)^2
```

로 인수분해된다. `lambda^5`는 5차항 계수다. binary-GCD 역원의 마지막
Montgomery 변환에 `lambda*R^2`를 넣어 scale product를 없애고 trace를
Horner `5M`에서 multiplicative-degree 하한인 `2S+1M`으로 줄였다.
batch inversion도 첫 forward와 마지막 두 reverse endpoint product를
생략해 normalization+trace가 `8m+I`에서 `6m-3+I`가 된다. 이에 따라
block 전체 membership 비용은 `130m-3+I`, 3-thread 이상 scalar 경로는
`127 M/S + I/candidate`다. `I`는 field inversion이며 block에서는 한 번을
공유한다. 79.94% reject가 절약하는 full Hamburg 비용은 약 743
products이므로 M/S 부분은 충분히 작다.

binary/separate-array 기준과 PRAC/direct-fraction 경로의 1-thread
40-pair 측정은 독립적으로 두 번 stationarity 조건을 통과했다. paired
median과 CI는 각각
`1.0345x`(`1.0271..1.0448`), `1.0311x`
(`1.0268..1.0376`)였다.
같은 비교의 포화-host 측정은 median `1.0289x`였지만 CI
`0.9791..1.0878`와 53.8%/72.1%의 절대 block spread로 stationarity를
실패해 성능 근거에는 포함하지 않았다. 이는 correctness 실패가 아니다.

후속 expanded/reciprocal trace 비교는 CPU를 고정하고 warm-up 10쌍 뒤
40쌍을 측정했다. 1-thread paired median은 `1.0270x`, bootstrap 95% CI는
`1.0027..1.0360`이었지만 시간 block stationarity를 실패했다. 따라서 이
wall-clock 값은 진단값으로만 남긴다. reciprocal 식의 채택 근거는
`9→5` products의 대수적 감소와 Sage 인수분해, C++ 전수 등가 검사이며,
기존 expanded 식도 `CH6_EXPANDED_SUBGROUP_TRACE` ablation으로 유지한다.

shifted-square/Horner의 후속 다중 fresh-process 측정은 paired
`1.0077x`(CI `1.0043..1.0149`)였으나 2% 문턱과 절대-time stationarity를
통과하지 못했다. normalization+trace 전용 cycle 측정은 활성 원소
32/128/256개에서 각각 `1.269/1.304/1.313x`였다. 기본값 채택 근거는
wall-clock PASS가 아니라 정확한 `8m→6m-3` product 감소와 Sage/C++
등가 검증이며, Horner와 기존 batch prefix는 ablation으로 남겼다.

연속 candidate block은 atomic counter로 배분한다. 최종 adaptive 정책은
1 thread에서 block/batch inverse 64개, 2 threads에서 block 32개, 3 threads
이상에서 scalar 64개다. 2-thread만 별도 고정 CPU 40-pair 검사를 통과했기
때문에 다른 thread 수로 보간하지 않았다. AVX2는 packed 64x64→128 정수
곱이 없어 radix 분해와 lane compaction 비용이 커지므로 보류했다.

block 안의 `x^3+ax+b`는 첫 원소만 직접 계산하고 1·2·3차 finite
difference를 field add로 갱신한다. recurrence가 RHS를 이미 주므로
Hamburg용 `x^2`는 Jacobi 직후가 아니라 부분군 필터를 통과한 후보만
계산한다. 정답 prefix에서 7,713개 curve-valid lift 중 1,547개만 남아
field square 6,166회를 없앤다. eager/deferred 측정은
`1.0042x`(CI `0.9749..1.0280`)와 stationarity 실패였지만, 실행 연산의
진부분집합이라는 점과 self-test/KAT를 근거로 기본값에 두고
`CH6_EAGER_BLOCK_X_SQUARE`를 oracle로 남겼다.
direct-block64/recurrence-block256은 두 번의
다중-process 측정에서 `1.0485x`, `1.0455x`였지만 stationarity gate를
실패했다. 연산 감소가 검증된 recurrence는 유지하되 자동 block 크기는
64로 유지했다.

`a=-3`의 직교 측정은 `1.1022x`(CI `1.0320..1.1274`)였지만
stationarity gate를 실패해 성능 수치는 diagnostic-only다. 원곡선
compile-time fallback과 실제 lift 교차 검증을 함께 유지한다.

대안 구현도 먼저 같은 correctness 검사를 통과시킨 뒤 성능 gate로 판정했다.
balanced signed-w9는 table을
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
`1.0068x`라 채택하지 않았다. direct fraction layout 단독도
`1.0007x`였고, compact PRAC과 결합한 두 반복 측정에서만 안정적인 개선을
보였다.
incumbent seed 주변 10,000,001개와 전 구간 무작위 천만 seed를 더
검사했지만 124 products 아래의 유효 chain은 없었다. rule 6 후보도 같은
124 products와 end-to-end `1.0060x`에 그쳤다. 역원을 없앤 homogeneous
Lucas는 약 383 products/candidate, common-denominator 변형은 후보당
약 255 products라 현재 약 130보다 불리해 기각했다.
실제 dependency를 줄인 125-product/109--113-step weighted seed와
첫 `0x03,0x83*40`을 전용 loop로 만든 후보도 검사했다. 둘을 합친 전체
결과는 `1.0127x`(CI `0.9807..1.0418`)와 stationarity 실패였고,
115 opcode를 38 run으로 압축한 RLE는 spill/helper call 때문에 더 느렸다.

3-product trace만 네 lane으로 교차하면 최대 `1.0599x`였지만 PRAC까지
붙인 전체 hot path는 `0.995..1.007x`였다. GCC flatten과 전용 square도
isolated trace는 `1.04..1.12x` 빨랐으나 full solver는 동률 이하였고,
compact한 세 번의 out-of-line multiply call을 유지했다.

복잡도는 telemetry가 이 인스턴스에서 `O(log B log n)`, 상태 탐색 work가
최악 `O(2^16 log n)`이다. native 고정 table 외 탐색 메모리는 worker마다
상수 크기다.

## 재현

최종 native source는
`solutions/06_optimization/deep_native_06.cpp`다. 저장소의
`solutions/06_optimization/`에는 Sage 부분군·trace 검증과 PRAC schedule
생성·검증을 재현하는 스크립트도 함께 제공한다.

```bash
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06
/tmp/deep_native_06 --self-test --json
/tmp/deep_native_06 --threads 1 --schedule adaptive --json

python3 solutions/06_optimization/generate_06_prac_schedule.py --json
sage -python solutions/06_optimization/audit_06_subgroup.py --json
sage -python solutions/06_optimization/audit_06_subgroup.py \
  --samples 0 --full-prefix --json
```

`--self-test` 실행의 JSON은 `"self_test":true`여야 한다. 실제 공격
실행은 적어도 다음 known-answer 필드를 출력해야 한다.

```text
d=0x1c3cdd6b221806db0a7b28
state_label=s3
state=0x948173253ad6d120a3f562
lift_low_bits=15594
r3=0x2443c8daf1a9d52b09
p_equals_dq=true
```

PRAC 재생성 결과는 `source_match=true`, `length=115`,
`field_products=124`여야 한다. Sage 전체 prefix 감사는
`prefix_valid_lifts=7713`, `prefix_members=1547`을 출력한다.

## 반복 측정

AMD EPYC 7B12 VM(8 logical CPU), Python 3.11.2, G++ 12.2.0에서 각 구현을
1회 warm-up한 뒤 완전한 공격을 5회 교차 실행했다. 매 표본마다 `d`,
`r3`와 경로별 `s2/s3`를 먼저 검증하고 median/MAD/raw sample을 기록했다.
아래 stationarity 실패는 correctness가 아니라 그 측정에서 성능 개선을
확정할 수 없다는 뜻이다. 다음 두 end-to-end 표는 최적화 단계별 역사
기준선이며 현재 최종 source의 절대 시간표가 아니다.

| 구현 | 중앙값 | 중앙값 비율 | paired 중앙값 |
|---|---:|---:|---:|
| 기존 Python | 14.298741 s | 1.00x | 1.00x |
| 최적화 Python `int` | 3.272242 s | 4.37x | 4.41x |
| 최적화 Python `gmpy2` | 3.000356 s | 4.77x | 4.61x |
| C++/GMP 1 thread | 1.873220 s | 7.63x | 7.44x |
| C++/GMP/OpenMP 8 threads | 0.447919 s | 31.92x | 30.75x |

8-thread MAD는 0.022003초(4.91%)였고 paired p05--p95는
25.21x--33.48x였다. 앞선 독립 반복에서도 0.445551초를 얻었다.

다음 native 표는 Jacobi, 부분군 trace/PRAC와 새 2-thread 정책 전 경로를
원본 Python/GMP와 같은 interleaved run에서 warm-up 1회 후 각각 5회
측정한 역사 기준선이다. 현재 최종 source의 절대 시간으로 소급하지 않는다.

| 구현 | 중앙값 | MAD | 비교 |
|---|---:|---:|---:|
| 기존 Python | 14.073190 s | 0.295610 s | 1.00x |
| GMP 1 thread | 1.971840 s | 0.048047 s | — |
| native 1 thread | 0.362651 s | 0.009200 s | Python 대비 38.81x, GMP 대비 5.44x |
| GMP 8 threads | 0.436403 s | 0.007239 s | — |
| native 8 threads | 0.085076 s | 0.006915 s | Python 대비 165.42x, GMP 대비 5.13x |

구성요소별 40-pair 측정에서 `r0,r1` 대비 `r1,r2` scan window는 `1.3428x`
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
고정한 측정이다. 이후 source에서는 중복 `PreparedLift` 저장을 제거하고
direct/scalar 경로는 이미 계산한 `x^2`를 재사용했다. recurrence 경로는
그 square를 부분군 필터 뒤로 더 미뤘다. correctness를 재검증했지만
포화된 host에서 같은
no-subgroup-filter/trace-filter 비교는 다시 수치화하지 않았다.
Jacobi와 새 2-thread 정책 전 source의 당시 baseline/optimized stack
비교는 warm-up 10쌍 뒤 paired `3.7126x`(95% CI
`3.7106..3.7251`)였다. 이는 현재 전체 stack의 합산 수치가 아니라 이전
단계의 역사적 같은-source 비교다.

timing 전에 독립 canonical arithmetic와 affine reference로 field 2,000개,
64개 경계 field pair, point/scalar 256개와 실제 lift Hamburg/NAF 및
scalar/batched subgroup 128개를 교차 검증했다. Sage에서도 무작위 200점과
실제 prefix 전부를 직접 `[n]T`와 비교해 mismatch 0을 확인했다. Sage는
expanded trace의 공통 인수, reciprocal 계수와 shifted-square 인수분해도
symbolically 검증한다.
signed carry와 subgroup order 경계도 point vector에 넣고, 모든 Jacobi
변형을 Fermat/Legendre와 비교했다. 11개 `mu_20` trace의 uniqueness와
`L_20=2`, runtime Montgomery 변환, 2,000 random+boundary trace의
binary/PRAC 일치도 검사했다. C++는 reciprocal/expanded 식을 경계값,
무작위 512개와 공개된 세 prefix의 전체 `3*65,536`개 x후보에서
cross-multiply해 대조하고 scaled binary inverse를 일반 inverse oracle과
비교한다. direct-fraction batch는 256-entry 경계와 분모
0을 주입한 compaction/fail-closed 경로도 검사했다.
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
- [Koshelev, *Subgroup membership testing on elliptic curves via the Tate pairing*](https://eprint.iacr.org/2022/037.pdf), [extension-field Appendix의 출판 correction](https://doi.org/10.1007/s13389-023-00331-3): small-cofactor pairing test와 base change 일반화. 본 풀이는 dual embedding degree 2의 `Fp2` Frobenius eigenspace에 특수화해 x-only trace와 fixed Lucas-PRAC을 유도했다.
- [Enge, *Bilinear pairings on elliptic curves*](https://arxiv.org/abs/1301.5520): Miller recurrence와 reduced Tate pairing을 x-only Frobenius trace로 전개할 때 참고했다.
- [Montgomery, *Evaluating recurrences via Lucas chains*](https://cr.yp.to/bib/1992/montgomery-lucas.pdf): differential Lucas chain과 PRAC rule.
- [Zimmermann--Dodson, *20 years of ECM*, Section 2.2](https://members.loria.fr/PZimmermann/papers/ecm-submitted.pdf): PRAC seed와 operation-cost 탐색.
- [Kutz, *Lower Bounds for Lucas Chains*](https://epubs.siam.org/doi/10.1137/S0097539700379255): Fibonacci형 길이 하한의 맥락; 124-product chain의 최적성 증명으로 쓰지는 않았다.
- [Bernstein--Cottaar--Lange, *Searching for differential addition chains*](https://doi.org/10.1007/s40993-024-00604-8): 최소 continued-fraction differential chain 탐색과 meet-in-the-middle 방법.
- [GMP-ECM `lucas.c`](https://sources.debian.org/src/gmp-ecm/7.0.6%2Bds-2/lucas.c/): production PRAC rule update와 대조.
- [Bernstein et al., *OpenSSLNTRU*](https://opensslntru.cr.yp.to/opensslntru-20211006.pdf): prefix/reverse batch inversion 비용.
- [Montgomery, *Modular Multiplication Without Trial Division*](https://doi.org/10.1090/S0025-5718-1985-0777282-X): 2-limb REDC와 Montgomery 표현.
- [GNU MP Manual](https://gmplib.org/manual/) 및 [OpenMP 5.2](https://www.openmp.org/spec-html/5.2/openmp.html): C++ arithmetic와 병렬 구현.
