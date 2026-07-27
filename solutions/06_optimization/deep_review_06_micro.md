# 문제 6: native arithmetic/cache 심층 최적화

## 결론

88비트 소수체를 GMP 대신 고정 2-limb Montgomery 체로 구현하고, Jacobian
point를 무할당 POD로 만들며, 고정점 `Q`의 byte-comb table을 affine으로
batch-normalize했다. 두 번째 최적화 pass에서 scan과 고정 `d` 곱까지 다시
검토해 최종 기본값은 다음과 같다.

- field element: 16바이트 (`uint64_t` 두 limb)
- x86-64 BMI2/ADX: `_mulx_u64`, `_addcarryx_u64`, `_subborrow_u64`를 쓴
  2x2 REDC와 branchless add/subtract
- 그 밖의 target: `unsigned __int128` portable unrolled 2x2 REDC,
  필요하면 `CH6_GENERIC_MONTGOMERY` carry-loop 대조군
- Jacobian point: 48바이트, heap allocation 없음
- `Q` table: `11 * 256 * 32 = 90,112`바이트 affine read-only layout
- Jacobian + affine mixed addition: `madd-2007-bl`
- scan: `r1` lift → `r2` filter의 shifted window
- hot `dR`: Hamburg 2020 co-Z x-only ladder, exceptional input은 width-2
  NAF fallback
- lift residue: Montgomery residue에서 바로 시작해 U128에서 U64로
  전환하는 Euclidean Jacobi; Hamburg exceptional NAF에서만 width-4
  sqrt를 지연 실행
- subgroup: `Fp2` Frobenius--Tate trace의 x-only cofactor-5 판정,
  `E=20H`의 115-byte fixed Lucas-PRAC과 11개 `mu_20` trace 비교
- subgroup batch layout: fraction을 caller에서 직접 만들고 in-place로
  compact한 뒤 block마다 분모를 한 번에 batch-invert
- scan curve: 원곡선과 동형인 `a=-3` 모델, 결과 x는 원래 좌표로 환산
- 역원: canonical `unsigned __int128` binary extended GCD
- 제곱근 fallback: 고정 지수 `(p+1)/4`의 width-4 sliding window
- scheduler 기본값 `adaptive`: 1 thread는 block64, 2 threads는 block32,
  3 threads 이상은 scalar64

이전 native 경로의 동일-run 역사 수치는 원본 Python 대비 1 thread
38.81배, 8 threads 165.42배였다. Jacobi 도입 전 두 번째 pass binary는
별도 broad screening에서 GMP 대비 1 thread 25.91배, 8 threads 10.02배였지만
shared VM 부하가 커 절대 시간과 broad ratio는 진단값으로만 취급한다.
현재 기본값의 작은 변경은 아래 40-pair adjacent AB/BA campaign으로 각각
분리해 판정했다. 모든 수치는 정답 검증을 통과한 sample만 포함한다.

구현은 `deep_native_06.cpp`, broad screening은
`benchmark_deep_native_06.py`, 후보 승격은 `benchmark_06_promotion.py`다.
의존성 없는 정답 경로 `solutions/solve_06_prng.py`는 그대로 유지한다.

## 출발점과 hot path

원본 Python의 정답 도달 전 profile에서는 다음이 관측되었다.

| 항목 | 호출/작업 수 |
|---|---:|
| 후보 구간 | 10,690 |
| `point_double` | 898,148 |
| `point_add` | 344,486 |
| `modp` | 14,445,392 |
| `affine_x` / modular inverse | 21,380 |

별도 `cProfile` run의 총 시간은 22.432초였고, `scalar_mul`이
19.892초, telemetry brute force가 1.836초였다. 즉 analytic
`floor_sum`으로 telemetry를 줄인 뒤에는 작은 체의 point arithmetic와
그 임시 객체가 지배적이었다.

기존 C++/GMP 구현은 이 병목을 크게 줄였지만 다음 비용을 남겼다.

1. 각 field temporary가 `mpz_class`이고, 연산마다 GMP call 및 limb
   관리가 들어간다.
2. `Q` table은 11-by-256 Jacobian point다. 각 entry가 field element
   세 개이고 `fixed_mul`도 generic Jacobian addition을 사용한다.
3. 후보마다 affine 변환이 두 번 일어나며 GMP inverse를 호출한다.
4. 정답 low bits `0x5338`보다 뒤의 work를 정적 분할하면 불필요한
   후보가 많이 실행된다.

참고 baseline run에서 GMP의 1/2/4/8-thread median은 각각
1.7807/1.0456/0.6456/0.4581초로, SMT까지도 이득이 있었다. 아래 최종
표는 환경 부하와 compiler flag를 맞추기 위해 이 숫자를 재사용하지
않고 같은 runner에서 GMP를 다시 측정한다.

## 구현 상세

### 1. 2-limb Montgomery field

소수

```text
p = 0xd9047b5f32dda5ca6f569b
```

는 88비트이므로 reduced residue를 두 개의 64비트 limb에 담을 수 있다.
`R=2^128`을 택하고 `unsigned __int128`로 64x64→128 partial product를
계산한다. 두 word REDC 단계는 `n'=-p^(-1) mod 2^64`를 사용하고,
마지막 conditional subtraction으로 canonical Montgomery residue를
얻는다. hot path에는 division, GMP, vector, heap allocation이 없다.

기본 빌드는 `-march=native`가 BMI2와 ADX를 제공할 때 scalar intrinsic
경로를 자동 선택한다. 2x2 product와 두 REDC word를 `_mulx_u64`로
전개하고 `_addcarryx_u64`로 carry chain을 연결했다. add/subtract도
`_subborrow_u64` 결과로 mask를 만들어 분기 없이 modulus를 보정한다.
기존 compiler output의 field multiply는 약 206 instruction, 688 byte,
조건 분기 6개와 spill을 가졌지만 새 hot function은 약 74 instruction,
256 byte, 조건 분기 1개이고 spill이 없었다.

`CH6_PORTABLE_ARITHMETIC` 또는 BMI2/ADX가 없는 빌드는 네 partial product와
두 REDC 단계를 고정식 `unsigned __int128` 코드로 실행한다. 이 portable
unrolled 경로는 generic carry-loop보다 paired median 약 `1.3507x` 빨랐지만
VM phase가 달라 stationarity gate는 통과하지 못했다. default,
`-march=native` 없는 portable, assertion-enabled debug, window-4 table
변형이 모두 같은 self-test와 known answer를 통과했다.

Barrett reduction도 검토했지만 88x88→176비트 product의 상위 부분과
quotient 근사를 다시 여러 word로 다뤄야 한다. 이 instance에서는
두 word REDC가 더 짧고 검증하기 쉬워 Montgomery를 선택했다.

역원은 처음에는 `a^(p-2)` Fermat exponentiation을 사용했다. 하지만
후보마다 두 번 이상 실행되므로 canonical value에 shift/subtract만
쓰는 binary extended GCD가 더 빨랐다. 변환에는 Montgomery multiply가
앞뒤로 한 번씩 들지만 약 88회의 square와 다수 multiply를 없앤다.

제곱근 fallback은 `p == 3 mod 4`이므로 `a^((p+1)/4)` 뒤 square check를
한다. 이 고정 지수는 86비트이고 popcount가 49다. binary exponentiation의
약 48 multiply를 width-4 odd-power table과 약 18개의 후속 window로 바꿔,
구현상 대략 25~26 multiply와 low-80s square가 된다.

초기 구현은 모든 x에 이 sqrt를 실행했고, 별도 Legendre exponent를 앞에
붙이는 후보는 두 exponentiation이 겹쳐 실패했다. Hamburg 정상 경로가 y를
쓰지 않는다는 점을 이용해 최종 구현은 Montgomery 88비트 우변의 Jacobi
symbol만 계산한다. `R=2^128=(2^64)^2`이므로 canonical 변환 없이도 symbol은
같다. U128 Euclidean reduction 도중 두 피연산자가 64비트가 되면 U64
remainder loop로 전환한다. 비잔여는 즉시 버리고 Hamburg denominator
예외에서만 sqrt를 실행한다. 최종 1-thread campaign은 sqrt/Jacobi 외부 중앙값
`0.076186/0.070292 s`, paired `1.0819x`(CI `1.0769..1.0842`)로
stationarity PASS였다. 반복 뺄셈 Jacobi는 `1.0072x`, parity-containing
CI여서 Euclidean remainder 경로를 유지했다.

Jacobi 함수만 분리한 microbenchmark에서는 full-U128 Euclidean,
canonical-hybrid, Montgomery-hybrid가 각각
`0.086159/0.056937/0.055429 s`였다. Montgomery 입력은 canonical-hybrid보다
약 2.7% 빨랐다. 반면 부분군 필터를 끈 전체 attack의 full-U128/hybrid
40-pair는 `1.0013x`(CI `0.9699..1.0315`)로 noisy parity였다. 따라서
이 변경은 검증된 hot primitive 단순화로 유지하되 별도 end-to-end 승격
수치로 합산하지 않는다.

### 2. POD Jacobian과 affine `Q` comb

기존 table 모양인 11개 byte position × 256 digit은 유지한다. 따라서
`state * Q`에는 최대 11번의 table addition만 필요하다. 다만 table
구축 뒤 Montgomery trick으로 모든 entry를 batch-normalize하여 affine
`(x,y)` 두 field만 저장한다.

| layout | 고정 크기 | native POD 기준 |
|---|---:|---:|
| Jacobian `11*256*(X,Y,Z)` | 135,168 B | 100% |
| affine `11*256*(x,y)` | 90,112 B | 66.7% |

따라서 table 자체가 정확히 1/3 작고, GMP의 별도 할당 limb까지 고려한
실제 차이는 더 크다. 각 row는 64-byte aligned이고 read-only로 모든
OpenMP thread가 공유한다.

Affine table 덕분에 generic Jacobian addition 대신 EFD의
`madd-2007-bl`을 쓴다. 공개 operation count는 generic addition
`11M+5S`, mixed addition `7M+4S`다. `dR`의 완전한 fallback에도 같은
mixed formula와 width-2 NAF digit `{-1,0,+1}`을 사용한다. 실제 `d`의
width-2 NAF는 27개 nonzero digit이다. hot path는 Hamburg co-Z ladder로
바뀌었지만 scalar가 다르거나 exceptional denominator가 생기면 이 NAF가
정확성을 보장한다. width-4는 digit/addition 수만 보면 precompute 3회 +
digit 16회로 작지만, 매 후보에서 odd multiple을 만들고 affine으로
바꾸거나 generic addition을 써야 하므로 fallback layout과 맞지 않았다.

고정 `Q` table의 폭은 compile-time 4--11 bit를 모두 표현할 수 있게
일반화했다. w4--w7은 addition 증가가 cache 절약보다 컸고, w9는 명목상
약 `1.0273x`였지만 bootstrap CI가 parity를 포함하고 stationarity도
실패했다. 별도 w8 대 w4 40-pair 검사는 w4가 paired `0.9483x`
(95% CI `0.9243..0.9737`)여서 기본 w8을 유지했다.

balanced signed-w9도 별도로 구현했다. 88비트 scalar를 9비트 signed digit
10개로 recode하고 magnitude `0..256`만 저장하므로 logical table은
82,240바이트, 64-byte row padding을 포함한 `sizeof(FixedTable)`은
82,560바이트다. carry 경계와 `n±1`, 88비트 최댓값까지 reference를
통과했지만 w8/signed-w9 paired `1.0065x`(CI `1.0035..1.0094`)로 2%
문턱에 못 미쳤다.

block 전체의 fixed-`Q`를 comb row별 affine addition으로 바꾸는 후보도
정상 addition을 `7M+4S`에서 약 `5M+1S`로 줄였다. 하지만 row마다 inverse
하나와 약 30KB scratch가 추가돼 paired `0.9351x`로 약 6.5% 느렸다.
`CH6_SIGNED_FIXED_TABLE`과 `CH6_ROW_BATCHED_FIXED_MUL`은 정확성·재현용
실험 macro로만 남는다.

### 3. shifted scan, `a=-3` 동형과 Hamburg ladder

기존에는 `r0`를 lift하고 `r1`으로 걸렀다. 최종 경로는 한 칸 뒤의
`r1`을 lift하고 `r2`로 거른다. lift한 점이 `T=±s2Q`이면
`X(dT)=s3`이고, 공개된 `r2=TMSB(X(s3Q))`가 같은 72비트 filter가 된다.
정답 low가 `0x5338`에서 `0x3cea`로 바뀌어 순차 prefix가 21,305개에서
15,595개로 26.8% 줄었다. 1-thread 40-pair 승격 측정은 paired
`1.3428x`, 95% CI `1.3336..1.3510`, stationarity PASS였다.

임의점 `dT`의 doubling에는 원곡선과 동형인

```text
y'^2 = x'^3 - 3*x' + 0x5e7dc2bc27aea7935c6b6
x    = 0x9b4427ecf55d466c0bbf44 * x' mod p
```

를 사용한다. EFD의 `a=-3` doubling은 이 구현 기준 `4M+4S`이고
generic-`a` 경로는 `3M+7S`라 square 세 번을 줄인다. ingress에는 위
계수의 역원 `0x664cac18b1d56fb30d39ed`를 Montgomery `R^2`와 미리
합치고 egress에는 원 계수를 써 mapping 비용도 최소화했다. 직교 40-pair
결과는 paired 약 `1.1022x`, bootstrap CI
`1.0320..1.1274`였지만 VM phase 변화로 stationarity는 실패했으므로 이
수치는 diagnostic-only로 기록한다.

고정 복원값 `d`에는 Hamburg Figure 3의 co-Z x-only ladder를 쓴다.
최종 분수를 개별 invert하지 않고 Jacobian `X/Z^2`로 넘겨 block batch
normalization과 결합했다. inline은 약 10KB code와 spill을 만들어
느렸고 `noinline`일 때만 승격됐다. NAF 대비 1-thread paired
`1.1716x`(95% CI `1.1682..1.1764`, stationarity PASS)였다. 8-thread도
40쌍 모두 이겼고 median `1.0868x`였지만 한 effect outlier 때문에
stationarity gate는 실패해 보조 자료로만 쓴다.

Hamburg 앞에는 cofactor-5 x-only membership filter를 둔다. `Fp2`의
Frobenius `-1` eigenspace에 있는 order-5 점으로 Miller 함수를 전개한 뒤
`W+W^-1` trace를 취해 y좌표를 없앴다. 고정
`E=(p+1)/5=20H`에 대해 115-byte fixed Lucas-PRAC으로 `L_H`를 계산하고
11개 `mu_20` trace와 비교한다. binary 기준의 `85M+85S=170` products를
`118M+6S=124`로 줄였고, trace 준비와 batch normalization까지 후보당
약 137 field M/S다. 초기화와 마무리를 포함한 `[d]T` Hamburg 전체는
약 930 products이고, 79.94% reject율을 반영한 손익분기점 약 743보다
작다. 실제 정답
prefix에서 curve-valid 7,713개 중 1,547개만 통과해 79.94%를 미리
버린다.

caller가 `SubgroupTraceFraction`을 직접 만들고 batch 함수가 이를
in-place compact한다. 최종 1-lane은 normalized trace를 지역값으로
계산하고 multi-lane ablation만 numerator를 덮어쓴다. x/RHS와
numerator/denominator를 각각 따로 staging하던 배열을 없애 GCC 12의
raw `batch_subgroup_membership` prologue allocation을 `0x38a8`에서
`0x1180`으로 줄였다. 이 layout 단독 성능은 `1.0007x`(CI
`0.9912..1.0082`)로
동률이었지만 compact PRAC과 결합한 두 campaign은 각각 `1.0345x`와
`1.0311x`로 승격 gate를 통과했다.

필터 없음/있음 40-pair 결과는 1 thread에서
`0.085280/0.044124 s`, paired `1.9444x`(CI `1.9113..1.9687`), 2
thread에서 `0.053521/0.030619 s`, paired `1.7448x`(CI
`1.7161..1.7904`)였다. 호스트 load와 swap 포화 때문에 strict
stationarity는 실패했지만, 네 effect block은 1 thread에서
`1.9569/1.8740/1.9486/1.9833x`, 2 thread에서
`1.7654/1.7710/1.7574/1.7184x`로 모두 큰 이득이었다.
이 수치는 source SHA-256
`5f169154d1c3b681a496169b6f4ec456a5a55c41c5986bf1ae27b5e1e90005a8`을
고정한 campaign이다. 이후 최종 source는 중복 `PreparedLift` 저장과
중복 `x^2` 계산을 제거했고 correctness suite를 다시 통과했지만, 포화된
host에서 같은 no-filter/filter ablation을 다시 수치화하지는 않았다.

### 4. block scheduling과 batch affine-x

Atomic block counter가 낮은 low bits부터 연속 block으로 나눠 준다. 정답이
발견되면 아직 배정되지 않은 `low >= best_low` block을 즉시 중단한다.
연속 후보는 `Q` table과 code를 cache에 유지하고, OpenMP dynamic loop의
세밀한 iteration dispatch도 피한다.

두 pipeline을 보존했다.

- `block`: 한 block의 quadratic-residue point를 모아 `dR`의 affine x를
  한 번의 batch inverse로 구하고, `state*Q` 결과도 다시 batch inverse로
  구한다.
- `scalar`: 같은 atomic block 배분을 쓰되 후보 하나를 끝까지 처리한다.

7회 ablation에서는 1 thread에서 batch가 0.386404초, scalar가
0.410719초로 batch가 약 6% 빨랐다. 반면 8 threads에서는 batch가
0.082014초, scalar가 0.077461초로 scalar가 약 6% 빨랐다. Binary GCD
inverse가 이미 싸고, thread별 batch stack/extra Montgomery multiply가
겹치기 때문이다. 이 첫 ablation만으로는 2-thread를 따로 판정하지 않았다.

후속 공식 runner는 compile-time variant뿐 아니라 runtime schedule과 block
크기도 같은 frozen binary에서 비교하도록 확장했다. 2-thread
`scalar64/adaptive-block32`의 warm-up 20쌍 + 40-pair 결과는 외부 중앙값
`0.047541/0.039171 s`, paired `1.2121x`(CI `1.2051..1.2163`)였고
stationarity PASS였다. 반면 4/8-thread block screening은 CI·block별 방향이
불안정했다. 최종 `--schedule adaptive`는 `1T=block64`, `2T=block32`,
`3T+=scalar64`를 고른다. `block`, `scalar`, `static`은 명시적으로 재현할
수 있고 JSON은 요청/실효 block을 구분한다.

부분군 batch inverse가 추가된 뒤 1-thread block64/block256을 다시
비교하면 paired `1.0365x`(CI `1.0173..1.0503`)였지만 effect
stationarity가 실패했다. 2-thread block32/block128도 host 포화 속에서
결론을 내지 못했다. 따라서 새 구조에서 큰 block이 유망하다는 기록만
남기고 자동 정책은 조용한 target에서 재측정할 때까지 바꾸지 않았다.

## 정확성 검증

검증을 세 층으로 분리했다.

1. **Field 층:** deterministic random 2,000 pair와
   `{0,1,2,p-2,p-1,2^64-1,2^64,2^64+1}`의 64개 경계 pair에 대해 Montgomery
   conversion/add/subtract/multiply를 canonical U128 double-and-add
   modular multiplication과 비교한다. Binary-GCD inverse와 Fermat
   inverse, binary sqrt와 window-4 sqrt, full-U128/hybrid-U64
   Euclidean/subtractive Jacobi, canonical/Montgomery 입력과
   Fermat/Legendre 결과도 서로 대조한다.
2. **Point/table 층:** signed carry, subgroup order와 88비트 끝값을 포함한
   16개 경계 scalar와 240개 deterministic random scalar, 총 256개에 대해
   affine slope/inverse 기반 simple binary
   reference, NAF/mixed Jacobian, fixed `Q` comb 결과의 x/y를 모두
   비교한다. row-batched macro에서는 256개를 한 번에 다시 비교한다. 별도로
   실제 curve-valid lift 128개에서 Hamburg와 NAF의 affine x를 대조한다.
   같은 128개에서 scalar/batched Frobenius--Tate trace와 직접 `[n]T=O`를
   비교하고, `Q` 양성·`Fp`-rational order-5 음성 벡터도 검사한다.
3. **전체 attack 층:** 모든 benchmark process가 아래를 검사한다.

```text
d                  = 0x1c3cdd6b221806db0a7b28
P == dQ            = true
legacy state s2    = 0x638d9d631ab436da51e640, low 0x5338
shifted state s3   = 0x948173253ad6d120a3f562, low 0x3cea
r3                 = 0x2443c8daf1a9d52b09
```

원본 Python은 low bits를 출력하지 않으므로 runner가 그 process에서는
`d`, `P=dQ`, `s2`, `r3`를 검증한다. GMP/native process는 low bits까지
검증한다. native는 `state_label`, lift/filter output index,
`field_backend`, curve model, `d` multiplication, lift residue, subgroup
membership test와 constant/batch layout, Lucas bit scan/step,
scan-buffer/curve-constant layout, table width/encoding/multiplication,
요청/실효 block, 요청/실제 thread, schedule, inverse와 sqrt까지 출력한다.
runner는 요청한 후보와 이
metadata가 다르면 timing 전에 실패한다. 기존 원본의 출력 이름 `s1`은
수학적으로 `s2`이고 runner는 그 값만 정상화한다.

이 self-test는 formal verification이 아니다. 특히 구현은 challenge
공격 코드이며 constant-time이 아니므로 비밀 scalar를 다루는 production
ECC library로 사용하면 안 된다.

## 반복 benchmark

환경은 AMD EPYC 7B12 VM, 8 logical CPU, Debian GCC 12.2.0, Python
3.11.2였다. C++ 양쪽은 동일하게 다음 flag로 build했다.

```text
-O3 -DNDEBUG -march=native -std=c++20 -fopenmp
```

Build와 self-test는 측정에서 제외했다. 각 sample은 새 process의 전체
attack이고 process startup, telemetry recovery, table precomputation,
scan, final prediction을 포함한다.

측정 증거는 두 층으로 나눴다.

- `benchmark_deep_native_06.py`는 GMP/native 및 thread 수를 넓게 거르는
  broad screening이다. cyclic/reversed ordering의 같은 repetition index를
  비교하지만 실행이 반드시 인접하지 않으므로 작은 차이의 승격 근거로 쓰지
  않는다.
- `benchmark_06_promotion.py`는 정확히 두 frozen-source build를 같은 CPU
  set에 pin하고, warm-up 뒤 fresh process 40개 adjacent pair를 네 block
  각각 AB 5개/BA 5개로 균형화한다. paired ratio median의 5,000회
  bootstrap은 block×order 8개 stratum 안에서 재표집한다. AB/BA 두
  stratum과 absolute/effect stationarity를 모두 통과하고 median이
  `1.02x`를 넘어야 작은 후보를 승격한다. compile define뿐 아니라 서로
  다른 runtime schedule/block도 같은 binary로 비교할 수 있다.
  `--trials-per-pair N`은 각 logical pair를 `N`개 fresh-process trial의
  중앙값으로 만들되 bootstrap 표본 수는 40으로 유지한다. 저장된 schema-3
  JSON 옆에는 source snapshot, source/runner/binary SHA-256, build argv,
  CPU model/flags/topology, raw trial과 pair aggregate를 함께 보존한다.

### 이전 native의 동일-run 기준선

다음 표는 이번 pass 이전 native와 원본 Python/GMP를 **같은 interleaved
run**에서 직접 측정한 역사 기준선이다. 새 stack의 속도라고 소급해
표시하지 않는다. `ratio`는 median의 비이고 `paired`는 같은 round의
speedup median이다.

| 구현 | median | MAD | ratio | paired median |
|---|---:|---:|---:|---:|
| 원본 Python | 14.073190 s | 0.295610 s | 1.00x | 1.00x |
| GMP, 1 thread | 1.971840 s | 0.048047 s | 7.14x vs Python | — |
| native adaptive, 1 thread (`block`) | 0.362651 s | 0.009200 s | 38.81x vs Python; 5.44x vs GMP | 38.81x / 5.31x |
| GMP, 8 threads | 0.436403 s | 0.007239 s | 32.25x vs Python | — |
| native adaptive, 8 threads (`scalar`) | 0.085076 s | 0.006915 s | 165.42x vs Python; 5.13x vs GMP | 160.12x / 5.34x |

Raw external seconds:

```text
python-original = [13.777580, 14.396470, 13.622788, 14.138053, 14.073190]
gmp-1t          = [ 1.983506,  1.971840,  2.041384,  1.923793,  1.817540]
native-1t       = [ 0.380280,  0.356095,  0.384722,  0.353451,  0.362651]
gmp-8t          = [ 0.427484,  0.440208,  0.454003,  0.436403,  0.429163]
native-8t       = [ 0.075537,  0.096514,  0.085076,  0.078161,  0.089694]
```

8-thread native의 MAD가 8.13%로 비교적 크므로 절대 시간은 host load에
민감하다. 그렇지만 가장 느린 native sample도 가장 빠른 GMP sample보다
4배 이상 빠르고, paired comparison도 방향이 일관됐다.

### 두 번째 pass 결과

새 기본 stack의 broad screening 7회 결과는 다음과 같다. 당시 shared
VM 부하로 특히 8-thread MAD가 컸으므로 큰 효과의 sanity check일 뿐,
작은 변경의 판단에는 쓰지 않는다.

| 구현 | median | MAD | GMP 대비 ratio-of-medians |
|---|---:|---:|---:|
| GMP, 1 thread | 2.529046 s | 0.129817 s | 1.00x |
| 최종 native, 1 thread | 0.097596 s | 0.004957 s | 25.91x |
| GMP, 8 threads | 0.575237 s | 0.054633 s | 1.00x |
| 최종 native, 8 threads | 0.057401 s | 0.009471 s | 10.02x |

후보별 40-pair 판정은 다음과 같다.

| 후보 (`A/B`) | paired median | bootstrap 95% CI | stationarity | 판정 |
|---|---:|---:|---|---|
| legacy `(r0,r1)` / shifted `(r1,r2)` | 1.3428x | 1.3336..1.3510 | PASS | shifted 채택 |
| width-2 NAF / Hamburg co-Z | 1.1716x | 1.1682..1.1764 | PASS | Hamburg 채택 |
| sqrt lift / Jacobi lift | 1.0819x | 1.0769..1.0842 | PASS | Jacobi 채택 |
| 2T scalar64 / adaptive block32 | 1.2121x | 1.2051..1.2163 | PASS | 2T 정책 채택 |
| no subgroup filter / Frobenius--Tate trace, 1T | 1.9444x | 1.9113..1.9687 | FAIL | 큰 전 구간 이득, diagnostic timing |
| no subgroup filter / Frobenius--Tate trace, 2T | 1.7448x | 1.7161..1.7904 | FAIL | 큰 전 구간 이득, diagnostic timing |
| binary/xy / PRAC20/direct, 1T run 1 | 1.0345x | 1.0271..1.0448 | PASS | 기본값 승격 |
| binary/xy / PRAC20/direct, 1T run 2 | 1.0311x | 1.0268..1.0376 | PASS | 독립 재현 |
| binary/xy / PRAC20/direct, post-audit | 1.0289x | 0.9791..1.0878 | FAIL | 포화 host 진단 |
| binary branch / branchless select | 0.9770x | 0.9609..0.9914 | FAIL | branch 유지 |
| U128 bit scan / U64 stream | 1.0068x | 1.0001..1.0191 | FAIL | 2% 미달, U128 유지 |
| xy-separated / direct fraction only | 1.0007x | 0.9912..1.0082 | PASS | 단독 승격 안 함 |
| binary 1-lane / binary 2-lane | 1.0180x | 1.0015..1.0316 | FAIL | 2% 미달 |
| binary / compact PRAC only | 1.0180x | 1.0117..1.0286 | FAIL | 결합 후보로 이동 |
| full-U128 / Montgomery-hybrid Jacobi | 1.0013x | 0.9699..1.0315 | FAIL | micro 개선만 확인 |
| unsigned w8 / signed-w9 | 1.0065x | 1.0035..1.0094 | PASS | 2% 미달 |
| Euclidean / subtractive Jacobi | 1.0072x | 0.9851..1.0225 | FAIL | Euclidean 유지 |
| candidate-Jacobian / row-batched affine | 0.9351x | 0.9254..0.9438 | FAIL | 기존 유지 |
| original curve / isomorphic `a=-3` | 1.1022x | 1.0320..1.1274 | FAIL | diagnostic-only |
| w8 table / w4 table | 0.9483x | 0.9243..0.9737 | FAIL | w8 유지 |
| block 64 / block 128 | 0.9948x | 0.9093..1.0473 | FAIL | 64 유지 |
| subgroup stack block64 / block256 | 1.0365x | 1.0173..1.0503 | FAIL | stationarity 재측정 필요 |
| generic carry / BMI2+ADX | 2.9808x | 2.7330..3.2589 | FAIL | 큰 방향성만 확인 |

PRAC/direct 승격 뒤 최종 기본 매크로로 다시 실행한 1-thread campaign도
paired `1.0382x`(CI `1.0248..1.0537`)였지만, 후반 host phase가 바뀌어
stationarity만 실패했다. 앞의 독립 PASS 두 번과 hot-path code가 같은
보조 확인으로만 쓴다. 8-thread median도 `1.0381x`였지만 CI
`0.9070..1.1621`로 너무 넓어 결론을 내리지 않았다.
최종 감사 source SHA-256
`840999f697112a17c7ebe6809351b4971b1a713d021e4c356334e3c4462ae073`의
seed `0x44444444` 재실행도 median `1.0289x`, CI
`0.9791..1.0878`이었다. baseline/candidate block spread가 각각
53.8%/72.1%라 stationarity가 실패했으므로 audit-snapshot 성능 근거로
추가하지 않는다. 뒤의 최종 변경은 timed path가 아닌 direct-fraction
self-test fixture만 강화했다.

코드생성 쪽에서는 subgroup/curve Montgomery 상수를 compile-time으로
만들어 local-static guard를 없앴고, write-before-read가 증명된 scan
buffer의 eager zero-fill을 제거했다. `-ftrivial-auto-var-init=pattern`
self-test/KAT로 초기화 누락을 확인했다. 정식 wall-clock은 각각 host
stationarity를 통과하지 못해 별도 속도 수치를 주장하지 않는다.
최종-source block256은 `1.0183x`, LTO는 `1.0083x`, 전체 codegen cleanup
ablation은 `1.0140x`로 모두 2% promotion rule을 넘지 못했다.

마지막 arithmetic holdout은 40쌍 모두 BMI2/ADX가 `2.04x` 이상
이겼지만 host load average가 16을 넘으며 block spread gate가 실패했다.
따라서 그 숫자는 diagnostic-only다. x86 BMI2/ADX 기본 경로와 portable
fallback 선택은 유지하되, 정확한 target CPU 성능을 주장할 때에는 조용한
환경에서 holdout을 다시 실행해야 한다.

Jacobi 전 source/runner를 고정한 뒤 generic carry + legacy scan + 원곡선 +
NAF 전체 대조군과 당시 stack을 충분한 warm-up 10쌍 뒤 40쌍으로 다시
검사했다. baseline/candidate median은 `0.283205/0.076114 s`, paired
median은 `3.7126x`(CI `3.7106..3.7251`)였다. AB/BA stratum median도
`3.7125x/3.7197x`였고 absolute block spread는 각각 0.81%/0.76%,
effect spread는 1.32%로 stationarity와 promotion gate를 모두 통과했다.
현재 기본값에는 이후 Jacobi가 더해졌으므로 역사적 합산 결과로만 본다.
보고서와 정확한 source snapshot은
`/tmp/ch6-final-stack-final-run.json[.source.cpp]`에 생성하며 repository에는
넣지 않는다.

### 별도 run을 섞은 참고 추정

이전 full matrix의 원본 Python median 14.298741초와 7회 native scalar
8-thread median 0.077461초를 단순히 나누면 약 184.6배다. 그러나 서로
다른 run/부하를 섞은 값이므로 최종 성능 주장에는 쓰지 않는다. 위의
165.42배는 이전 native의 역사적 동일-run end-to-end 기준선일 뿐, 이번
최종 stack의 속도로 소급하지 않는다.

### Inverse/sqrt ablation

다음은 최종 batch pipeline을 넣기 전 scalar pipeline을 5회씩 측정한
독립 ablation이다. 따라서 절대 시간보다는 같은 행/열의 방향만 본다.

| inverse | sqrt | 1T median | 8T median |
|---|---|---:|---:|
| binary GCD | window-4 | 0.408371 s | 0.077916 s |
| binary GCD | binary | 0.395508 s | 0.079889 s |
| Fermat | window-4 | 0.429445 s | 0.088159 s |
| Fermat | binary | 0.423692 s | 0.089331 s |

Binary GCD는 일관되게 이겼다. Window-4 sqrt는 전체 scan에서 차이가
작아 1T noise에는 뒤집혔지만 8T median과 operation count가 우세하여
기본값으로 유지했다. 모든 네 조합은 known-answer와 field cross-check를
통과한다.

## 재현

독립 build와 검증:

```bash
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06
/tmp/deep_native_06 --self-test
/tmp/deep_native_06 --threads 1 --json
/tmp/deep_native_06 --threads 8 --json
```

Portable fallback도 별도로 검증할 수 있다.

```bash
g++ -O3 -DNDEBUG -std=c++20 -fopenmp \
  -DCH6_PORTABLE_ARITHMETIC \
  solutions/06_optimization/deep_native_06.cpp \
  -o /tmp/deep_native_06_portable
/tmp/deep_native_06_portable --self-test --json
```

두 pipeline과 GMP를 반복 비교하는 기본 runner:

```bash
python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 7 --threads 1,8 \
  --native-schedules block,scalar \
  --output /tmp/deep-native-06.json
```

원본 Python을 포함한 최종 통합 측정은 느리므로 opt-in이다.

```bash
python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 5 --threads 1,8 \
  --native-schedules adaptive \
  --include-original-python \
  --output /tmp/deep-native-06-integrated.json
```

Runner는 `OMP_DYNAMIC=FALSE`, `OMP_PROC_BIND=SPREAD`,
`OMP_PLACES=THREADS`를 고정하며 raw sample, median, MAD, percentile,
stage timing과 same-repetition diagnostic ratio를 JSON에 모두 보존한다.

작은 후보를 최종 판정할 때에는 별도 runner를 사용한다. 다음 예는 NAF를
대조군으로 Hamburg 기본값을 40쌍 비교한다.

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label naf --candidate-label hamburg \
  --baseline-define CH6_NAF_D_MULTIPLICATION \
  --threads 1 --warmup-pairs 2 --pairs 40 \
  --output /tmp/ch6-hamburg-holdout.json
```

출력과 함께 `/tmp/ch6-hamburg-holdout.json.source.cpp`가 생성된다.
최종 전체-stack holdout 명령은 다음과 같다.

```bash
python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label legacy-native --candidate-label final-native \
  --baseline-define CH6_GENERIC_MONTGOMERY \
  --baseline-define CH6_LEGACY_R0_SCAN \
  --baseline-define CH6_ORIGINAL_CURVE_SCAN \
  --baseline-define CH6_NAF_D_MULTIPLICATION \
  --threads 1 --cpus 0 --warmup-pairs 10 --pairs 40 \
  --output /tmp/ch6-final-stack-final-run.json
```

## 실패·보류 및 채택 뒤 재검토한 전략

### Fermat inverse

구현이 간단하고 Montgomery domain을 벗어나지 않지만 affine conversion
호출 수가 많아 fixed 88-bit binary GCD보다 느렸다. 비교/회귀용 옵션으로
남겼다.

### 모든 thread에서 batch inversion

Montgomery trick은 inverse 수를 크게 줄이지만 각 point에 prefix/reverse
multiply를 추가한다. Binary GCD inverse가 싸진 뒤 8 threads에서는
thread-local stack traffic과 extra multiply가 이득을 넘었다. 1 thread에만
자동 적용한다.

### 넓은 wNAF

Width-4/5는 nonzero digit 수를 줄이지만 임의의 lifted point마다 odd
multiple table을 새로 만들어야 한다. 그 table을 affine으로 만드는
inverse나 generic Jacobian addition 비용 때문에 width-2 mixed NAF가
더 맞았다. 반대로 고정점 `Q`에는 한 번만 만드는 byte-comb가 확실히
유리하다.

### 전용 square와 direct U128 add

대칭 cross term을 한 번만 계산하는 portable square와 BMI2 전용 square를
각각 구현했다. 전자는 paired 약 `1.0179x`였지만 2% 승격 문턱에 못
미치고 stationarity도 실패했다. 후자는 `0.9982x`, CI
`0.9919..1.0034`로 완전한 동률이었다. GCC가 inline call site에서 이미
두 cross term을 공통 부분식으로 합쳤기 때문이다. `join(left)+join(right)`
형태의 direct U128 add도 carry intrinsic보다 빠르지 않았다.

당시 binary 부분군 Lucas ladder가 square를 많이 써 두 구현을 다시 측정했지만
오히려 portable specialized square는 paired `0.7111x`(CI
`0.6640..0.8047`), BMI2 intrinsic square는 `0.9230x`(CI
`0.8584..0.9899`)로 명확히 느렸다. 일반 multiply-as-square를 유지한다.

### 고정 sqrt addition chain

`(p+1)/4`에 대해 straight-line chain을 생성해 sliding-window
exponentiation을 대체했다. `addchain` 탐색의 최선은 약 107회
square/multiply였고 현재 경로는 약 108회 수준이어서 table 준비와 code
증가를 상쇄하지 못했다. fixed-chain과 intrinsic-square 조합도
end-to-end 이득이 없어 기본 sliding window를 유지했다.

### 잘못된 inline/noinline 선택

field multiply를 `noinline`으로 떼면 call/return과 register save가
hot path에 들어가 paired 약 `0.9754x`로 악화됐다. 반대로 Hamburg
ladder를 inline하면 caller code가 약 10KB로 팽창하고 spill이 생겼다.
따라서 작은 field primitive는 inline, 큰 Hamburg ladder만
`[[gnu::noinline]]`으로 두었다.

### table 폭과 block 크기

고정 `Q` table의 w4--w7은 table을 줄이지만 fixed-base addition 수가
늘어 w8보다 느렸다. w9의 명목상 `1.0273x`는 CI가 parity를 포함했다.
최신 w4 holdout도 `0.9483x`라 w8을 유지한다. carry가 생기는 signed
9-bit recoding까지 구현하면 table은 82,560바이트로 줄지만 paired
`1.0065x`에 그쳐 2% 승격 문턱을 넘지 못했다. block 8 대 64의 이전
8-thread 비교와 block 128 대 64의 1-thread 비교도 CI가 parity를 포함했다.
다만 thread 수를 분리한 최종 campaign에서 2-thread block32만
`1.2121x`로 gate를 통과했으므로 adaptive 정책의 유일한 예외로 채택했다.

부분군 filter 뒤에는 batch inverse amortization 때문에 1-thread block256이
block64보다 paired `1.0365x`로 유망했고 CI도 parity를 제외했지만,
chronological effect spread가 gate를 실패했다. 2-thread block128 검사는
시스템 swap 포화로 paired `1.0048x`에 불과하고 CI가 넓었다. 자동 정책은
보수적으로 그대로 두고 runtime `--block-size` 비교만 열어 뒀다.

### Euclidean과 subtractive Jacobi

초기의 Legendre 선필터는 field exponentiation 뒤 살아남은 후보에서 sqrt
exponentiation을 다시 실행해 작업을 중복했다. 최종 구현은 Hamburg 정상
경로가 y를 쓰지 않는다는 사실을 이용해, canonical 88비트 정수에
quadratic-reciprocity를 적용하는 Euclidean Jacobi만 실행한다. 이 경로는
sqrt-every-lift 대비 paired `1.0819x`로 승격됐다.

U128 나눗셈을 없애려 trailing-zero 제거와 반복 뺄셈만 쓰는 subtractive
Jacobi도 구현했다. 같은 random/경계 Legendre 교차 검증은 통과했지만
Euclidean/subtractive 비교는 `1.0072x`, CI `0.9851..1.0225`였고 시간
block별 방향도 바뀌었다. 88비트 입력에서는 늘어난 iteration이 remainder
제거 이득을 상쇄해 Euclidean 구현을 유지했다.

### Row-batched fixed-`Q`

후보별 최대 11회의 Jacobian mixed addition 대신 block의 모든 scalar를
comb row별 affine addition으로 함께 진행했다. 정상 addition의 근사 비용은
`7M+4S`에서 `5M+1S`로 줄지만, row마다 inverse 하나와 약 30KB scratch,
동일점·반대점·infinity 예외 처리가 추가된다. 256개 scalar reference는
통과했으나 paired `0.9351x`(CI `0.9254..0.9438`)로 약 6.5% 느렸다.
`CH6_ROW_BATCHED_FIXED_MUL`은 재현용 macro로만 남겼다.

### 2-lane lockstep과 Hamburg의 다른 DAG

독립 후보 두 개의 sqrt/Hamburg 연산을 교차 배치해 instruction-level
parallelism을 노린 2-lane prototype은 scalar 대비 `0.8624x`였고 40쌍
모두 졌다. Hamburg stack frame이 약 `0x198`에서 `0x458`바이트로 커지며
GPR spill과 stack traffic이 이득을 압도했다. 논문의 Figure 4는 Figure 3의
단순 재스케줄이 아니라 비용 `9M+3S+7A`인 Joye ladder다. 같은
`8M+3S+7A`를 4개 실행 단위용 DAG로 배치한 Appendix Figure 6도 검토했지만,
현재 2-limb scalar backend의 register pressure 때문에 구현 우선순위를
낮췄다.

### scheduler의 나머지 thread 수

2-thread block32는 CPU 6--7 고정 40-pair campaign에서 통과했지만,
4/8-thread block 후보는 CI와 시간 block별 방향이 불안정했다. worker가
늘면 batch scratch와 추가 multiply가 private cache와 memory bandwidth를
더 압박한다. 근거 없는 보간을 피하고 `1T=block64`, `2T=block32`,
`3T+=scalar64`만 자동 선택한다. 명시적 `block/scalar/static` 모드는 후속
target별 재측정을 위해 유지한다.

### elliptic scalar PRAC, GLV와 더 넓은 고정 chain

elliptic-point PRAC은 임의 scalar multiplication의 addition chain을 줄일
수 있지만 이 문제의 hot scalar `d`는 고정이고 Hamburg ladder가 이미 더
규칙적인 x-only 경로를 제공한다. GLV/endomorphism 분해는 이 generic-j
short-Weierstrass curve에서 쓸 수 있는 효율적인 endomorphism과 subgroup
구조가 주어지지 않았다. 매우 넓은 고정 addition chain도 code size,
per-lift precomputation과 exceptional case를 포함하면 NAF/Hamburg를
넘지 못해 구현 후보에서 제외했다.

이 실패는 아래의 trace recurrence용 Lucas-PRAC과 다른 문제다.

### Lucas-PRAC과 `mu_20` campaign

binary Lucas 기준은 `E=(p+1)/5`의 84개 남은 bit마다 multiply와 square를
실행해 170 products를 썼다. `E/4`를 PRAC으로 계산한 뒤 `mu_4` traces
`{0,2,-2}`와 비교하는 후보는 약 128 products, factor별 composition은
약 136이었다. 최종 `E=20H`와 11개 `mu_20` trace 방식이
`118M+6S=124`로 가장 짧았다. 이는 찾은 chain 중 최선이지 전역 최적성
증명은 아니며, Fibonacci형 하한 맥락 약 117과 일곱 product 차이다.

dynamic PRAC은 후보마다 U128 division/remainder와 rule 선택을 수행하므로
고정 지수에 맞지 않았다. offline에서 만든 115-byte schedule을 compact
loop로 해석했다. 큰 opcode switch를 복제한 fused interpreter는
`0.9880x`, 2-lane PRAC은 `0.9941x`로 졌다. compact interpreter만 쓰면
`1.0180x`로 문턱 아래였고, direct in-place fraction layout과 결합한 뒤
두 독립 run에서 `1.0345x`, `1.0311x`로 PASS해 기본값에 넣었다.

84-step binary loop의 완전 template unroll은 code bloat로 실패했다.
binary 2-lane interleaving은 `1.0180x`, U64 MSB bit stream은
`1.0068x`라 2%에 못 미쳤다. mask-select branchless binary step은 함수
크기를 줄였지만 매 step의 네 limb 선택 때문에 `0.9770x`로 명확히
느렸다. 이 후보들은 binary oracle/ablation macro로만 남겼다.

### `mpz_legendre`와 exponentiation 선필터

GMP 후보에서 `mpz_legendre`를 sqrt 앞에 붙였지만 width-5는
`0.483517/0.490778 s`, width-4는 `0.494902/0.493416 s`로 동률 이하였다.
Native에서 Fermat exponent로 Legendre를 계산하는 후보도 살아남은 절반에
sqrt exponent를 다시 실행해 중복됐다. 이것은 위에서 채택한 작은 정수
Euclidean Jacobi와 다른 전략이다.

### cofactor-5 subgroup 선필터와 기각한 변형

PARI로 `#E(F_p)=5n`, `E(F_p)`가 cyclic이고 `ord(Q)=n`임을 확인한 뒤,
`Fp2` 비유리 5-torsion의 reduced Tate character를 x-only Frobenius
trace로 바꿔 기본 경로에 채택했다. shifted 정답 prefix의 curve-valid
7,713개에서 `[n]T=O`인 1,547개와 정확히 일치한다. 식과 상수, Lucas
recurrence는 `deep_review_06_algorithm.md`에 적었다.

처음 구현한 역원 없는 변형은 Miller 값
`f=(y+i*c1(x))^2*(y+i*c2(x))`를 직접 `Fp2`에서
`(p+1)/5`승하고 허수부가 0인지 검사했다. 판정은 맞지만 먼저 y를
구하기 위한 sqrt와 Fp2 연산이 필요해 no-filter 대비 paired
`1.1643x`에 그쳤다. x-only trace+block batch inversion의 `1.9444x`보다
낮아 기각했다. 역사적 binary Lucas bit loop를 84단계 template로 완전히
펼치는 후보도
함수가 약 `0x510`에서 `0x298e`바이트로 커졌고 paired `1.0451x`, CI
`0.9133..1.1072`로 불확실했다. 이후의 fixed PRAC/direct-fraction
선택 과정은 바로 위 campaign에 정리했다.

### BMI2/ADX 이후의 carry chain

GCC 12와 Clang 21 assembly를 직접 세어 보니 두 compiler 모두 current
multiply에 `mulx+adc`를 쓰고 `adcx/adox`는 0회였다. 따라서 `bmi2-adx`
metadata는 실제 ADX opcode 사용 보장이 아니라 compile-time capability
gate다. 별도 dual-carry REDC assembly는 self-test와 KAT를 통과했지만
CPU 고정 quick 비교에서 약 4--5% 느렸다. 2-limb 크기에서는 짧은 직렬
REDC dependency와 추가 move/carry가 dual chain 이득을 상쇄했다.

같은 source의 Clang 21+libomp는 1-thread quick 비교에서 GCC보다 약
`1.076x`로 유망했지만 2-thread는 `1.016x`로 불확실했다. Clang+libgomp는
요청한 두 thread를 만들지 못했으므로 결과에서 제외했다. compiler 교체는
libomp 의존성과 현재 host 포화가 해소된 뒤 별도 40-pair campaign으로
판정한다.

### constant guard와 scan-buffer 초기화

subgroup 여섯 상수, 곡선 네 상수와 11개 `mu_20` trace를
`constexpr` Montgomery residue로 만들었다. 이전 function-local static
초기화 guard가 hot `subgroup_trace_fraction`과 curve accessor에
들어오지 않는다. self-test는 각 compile-time 값을 runtime
`to_montgomery` 결과와 다시 비교한다. 이 변경은 code layout을
단순화하지만 noisy 전체 ablation이 promotion gate를 통과하지 않아
독립적인 속도 수치는 주장하지 않는다. 재현용
`CH6_RUNTIME_SUBGROUP_CONSTANTS`는 rational-map 상수뿐 아니라 11개
root trace의 Montgomery 변환도 function-local static으로 되돌려 JSON
layout label과 실제 codegen을 맞춘다.

block evaluator의 큰 POD 배열도 실제 write 순서를 감사했다.
`PreparedLift::y`는 `y_available`가 참인 fallback에서만 읽고, caller의
목적지에 직접 prepare한다. members의 필요한 false fill을 제외하면
evaluator와 subgroup batch의 eager zero-fill을 제거했다. default와
`-ftrivial-auto-var-init=pattern` build가 field/point/subgroup self-test와
전체 KAT를 모두 통과했다. 재현용 `CH6_EAGER_ZERO_SCAN_BUFFERS`는
기존 초기화를 되살린다.

binary oracle의 128-bit variable shift를 U64 MSB stream으로 바꾸는 후보도
`shrd/shrx`를 줄였지만 함수 크기는 오히려 늘었다. paired `1.0068x`
(CI `1.0001..1.0191`)로 2% 문턱과 stationarity를 놓쳐 최종 기본값은
U128 scan을 유지한다. GCC LTO도 text와 일부 함수 크기를 줄였지만
`1.0083x`에 그쳐 기본 build flag에 넣지 않았다.

### cache hint, padding과 compiler flag

고정 table prefetch distance 1/2/4는 각각 paired
`0.9953/0.9921/0.9805x`, row padding 1/3 cache line은
`0.9814/0.9826x`였다. 하드웨어 prefetch와 현재 연속 row 접근보다 나아지지
않았다. signed-w10은 `1.0118x`로 2% 문턱 아래였고,
`-funroll-loops`도 `1.0074x`였다. 4-thread scalar chunk32/chunk256은
`1.0155/0.9987x`이며 order와 시간 block이 불안정했다. 모두 기본 cache
layout·compiler flag·adaptive 정책을 유지한다.

### AVX2 field arithmetic

현재 representation의 핵심은 full 64x64→128 product와 carry다. AVX2의
`VPMULUDQ`/`_mm256_mul_epu32`는 각 64-bit lane 전체가 아니라 선택된
32-bit 값만 곱해 64-bit 결과를 만든다. Packed 64x64→128 integer
instruction이 없다. Radix-32로 다시 쪼개면 여러 multiply, shuffle,
cross-term, lane carry가 필요하고, quadratic-residue 분기 뒤 lane
compaction까지 필요하다. 이 작은 88-bit field와 이미 잘 scaling하는
OpenMP 후보 병렬성에서는 검증 부담과 overhead가 더 클 가능성이 높아
AVX2 코드를 만들지 않았다.

AVX-512 IFMA52가 있는 다른 CPU라면 radix-44/52 multi-buffer field를
다시 검토할 수 있지만, 측정 host에는 AVX-512가 없으므로 이 결과에
포함하지 않는다.

### block cubic recurrence와 trace DAG

변환 곡선의 연속 후보에서 `f(x)=x^3+ax+b`는 block 첫 원소만 직접
평가하고 고정 step `h`의 1·2·3차 차분을 field add로 갱신한다.
따라서 recurrence 경로는 부분군 필터까지 `x^2` 없이 진행한다.
direct/recurrence
준비 결과는 다섯 시작점에서 각 128개, 전체 known-answer에서는
정답 low와 `candidates_started`까지 같았다. 같은 block64의 단독 결과는
`1.0089x`로 CI가 parity를 포함했지만, direct-block64 대비
recurrence-block256은 fresh-process 5/7-trial logical pair campaign에서
각각 `1.0485x`, `1.0455x`였다. CI는 모두 parity를 제외했으나 effect
spread 2.13% 또는 공유 host absolute drift 때문에 stationarity를
통과하지 못했다. recurrence는 정확한 product 제거로 유지하고 자동
block은 64에 둔다.

기존 recurrence는 Jacobi 직후 `x^2`를 계산해 curve-valid 7,713개 모두에
square를 썼지만, trace를 통과해 Hamburg에 들어가는 것은 1,547개다.
square를 `multiply_prepared_lift` 직전으로 옮겨 정답 prefix에서 정확히
6,166 products를 없앴다. direct-cubic과 scalar 경로는 RHS 계산 때 만든
square를 계속 재사용한다. eager/deferred 5-trial logical-pair campaign은
shared-host drift 속에서 `1.0042x`(CI `0.9749..1.0280`)와 stationarity
실패였으므로 timing PASS로 세지 않는다. 기본값은 정확한 연산 제거와
self-test/KAT에 근거하며 `CH6_EAGER_BLOCK_X_SQUARE`를 ablation으로 남겼다.

reciprocal trace의 다섯 계수에는 더 강한 구조가 있다. 유일한 fifth root
`lambda`로 `r=lambda/(x-alpha)`를 잡으면

```text
tau = 2 + r*((r+h)^2+k)^2
```

가 정확히 성립한다. binary-GCD의 마지막 Montgomery 변환 상수를
`lambda*R^2`로 바꿔 scale을 흡수했고, trace는 Horner `5M`에서
`2S+1M`으로 줄었다. batch prefix/reverse 양 끝의 불필요한 세 곱도
없애 normalization+trace를 `8m+I`에서 `6m-3+I`로 줄였다.

CPU 7 고정 cycle microbenchmark는 2,000-call warm-up 뒤 다음 결과를
보였다.

| 활성 원소 `m` | Horner cycles | shifted-square cycles | 비율 |
|---:|---:|---:|---:|
| 32 | 5,198 | 4,095 | 1.269x |
| 128 | 18,990 | 14,558 | 1.304x |
| 256 | 37,373 | 28,485 | 1.313x |

full solver의 5-trial logical-pair 결과는 `1.0077x`
(CI `1.0043..1.0149`)였지만 절대-time stationarity와 2% 문턱을
놓쳤다. 뒤의 124-product PRAC과 나머지 pipeline이 micro 이득을
희석한다. Sage는 symbolic polynomial identity와 실제 sample을,
C++는 Horner/shifted-square, 일반/scaled binary inverse와
batch count `1..256`의 선택된 경계를 교차 검증한다.

3-product trace 네 개를 software-pipeline한 isolated micro는 활성 원소
32/128/256개에서 `1.0287/1.0521/1.0599x`였지만, 124-product PRAC까지
붙이면 2/4-lane 모두 `0.995..1.007x`로 희석됐다. reverse sweep 뒤 별도
trace/PRAC pass도 최대 약 `1.006x`, numerator에 prefix를 겹쳐 저장한
layout도 `0.999..1.002x`였다. 활성 원소별 membership cost는 8--16개에서
이미 약 2,859 cycles/active로 평탄해져 block64의 평균 약 32개면 inverse
amortization이 충분했다. 따라서 더 큰 block의 명목상 이득을 subgroup
inverse 하나만으로 설명하지 않는다.

PRAC도 실제 dependency를 반영한 125-product/109--113-step seed,
`0x03,0x83*40` 전용 prefix와 38-run RLE를 추가 검사했다. prefix는
41 dispatch를 없앴지만 weighted seed와 결합한 전체 결과가 `1.0127x`
(CI `0.9807..1.0418`)와 stationarity 실패였다. RLE는 hot body 확대,
spill과 rare-rule helper 호출 때문에 기준 약 1.35--1.47us에서
1.91--3.96us로 느려졌다.

### frame 축소와 추가 codegen 후보

reciprocal 기본 경로의 unused numerator 제거는 evaluator frame을
4,096바이트, deferred-sqrt/Hamburg에서 불필요한 `PreparedLift::y`를
조건부 제거하면 6,160바이트, 둘을 합치면 10,256바이트 줄였다. 그러나
paired 결과는 `0.9996x`, `1.0051x`, `1.0033x`로 모두 CI가 parity를
포함했다. scan 범위의 `gamma` singularity guard 제거도 `1.0050x`였다.
속도 근거 없이 조건부 layout 복잡도를 늘리지 않았다.

현재 `field_multiply`는 GCC 12에서 253 bytes/70 instructions이며
`mulx` 7회와 짧은 carry chain을 쓴다. 최종 REDC 보정 확률 상한이
`p/2^128≈7.71e-13`이라 조건분기는 사실상 항상 같은 방향이다.
branchless 보정은 primitive `0.6702x`, unlikely hint는 `0.9596x`,
CIOS kernel은 약 `0.694x`로 졌다. high×high 상위 limb 생략은 full
solver에서 `1.0196x`였지만 isolated primitive가 `0.7832x`이고
callee-save push가 늘어 불안정 후보로 보류했다. Horner 수동 unroll,
`field_add` always-inline과 PRAC 상수 재사용도 결정적 이득이 없었다.

새 factorized trace의 GCC 12 helper는 330 bytes, 32-byte stack과 세 번의
out-of-line multiply call을 쓴다. `flatten`은 isolated trace를
`1.1174x`로 만들었지만 helper가 945 bytes로 커지고 full solver는
`0.9882x`로 명확히 느렸다. 전역/trace 전용 BMI2 square도 isolated
`1.0891x/1.0429x`와 달리 full solver `1.0042x/0.9845x`에 그쳤다.
마지막 `+2`를 tail helper로 분리한 후보는 한 run의 `1.0355x`가
3-trial 재측정에서 `0.9603x`로 뒤집혀 기각했다. Clang inline code도
전체 `1.0101x`와 parity-containing CI여서 작은 GCC 3-call body를 유지한다.

### 다중 trial logical pair

20--40ms process 한 번의 scheduler 지연이 작은 후보를 뒤집지 않도록
promotion runner에 `--trials-per-pair N`을 추가했다. 각 logical pair는
동일 순서의 `N`개 fresh-process AB 또는 BA trial을 수행하고, variant
시간과 trial ratio의 중앙값을 사용한다. bootstrap과 stationarity의
표본 수는 여전히 logical pair 40개이며 raw event, `trial_index`,
pair aggregate와 집계 규칙을 schema 3 JSON에 모두 보존한다.

## 참고 자료와 논문

- Peter L. Montgomery, [“Modular Multiplication Without Trial
  Division”](https://doi.org/10.1090/S0025-5718-1985-0777282-X),
  *Mathematics of Computation* 44(170), 1985, pp. 519–521. REDC와
  nonstandard residue representation의 원 논문이다.
- Daniel J. Bernstein and Tanja Lange,
  [Explicit-Formulas Database: short Weierstrass Jacobian formulas](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html).
  사용한 `madd-2007-bl` 공식, 가정 `Z2=1`, operation count
  `7M+4S`를 제공하며 machine-checked script도 연결한다.
- Bernstein--Lange,
  [EFD: short Weierstrass Jacobian formulas for `a=-3`](https://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian-3.html).
  동형 곡선에서 사용한 `dbl-2001-b` 계열 공식과 operation count의
  1차 자료다.
- Mike Hamburg,
  [“Faster Montgomery and double-add ladders for short Weierstrass
  curves”](https://eprint.iacr.org/2020/437), TCHES 2020. Figure 3의
  co-Z state와 `8M+3S+7A` 분석을 실제 고정-`d` hot path에 적용했다.
  [공식 supplementary formulas](https://github.com/bitwiseshiftleft/ladder_formulas)로
  Figure 4와 Appendix Figure 6의 dependency graph도 대조했다.
- Niels Möller,
  [“Efficient computation of the Jacobi symbol”](https://arxiv.org/abs/1907.07795),
  그리고 [GNU MP의 Jacobi 알고리즘 설명](https://gmplib.org/manual/Jacobi-Symbol.html).
  Euclidean/GCD reduction 중 quadratic-reciprocity 상태를 갱신하는 최종
  residue test의 근거다.
- Dmitrii Koshelev,
  [“Subgroup membership testing on elliptic curves via the Tate pairing”](https://eprint.iacr.org/2022/037.pdf).
  small-cofactor pairing test의 출발점이다. 논문의 basic-field 조건
  `e | p-1`은 `p mod 5=4`인 현재 곡선에서 성립하지 않으므로 그대로
  적용하지 않고 `Fp2` Frobenius `-1` eigenspace로 옮겼다.
- Andreas Enge,
  [“Bilinear pairings on elliptic curves”](https://arxiv.org/abs/1301.5520).
  Miller recurrence, reduced Tate pairing과 Frobenius 관계를 이용해
  order-5 Miller 값을 x-only trace로 전개할 때 참고했다.
- Peter L. Montgomery,
  [“Evaluating recurrences of form X_(m+n)=f(X_m,X_n,X_(m-n)) via
  Lucas chains”](https://cr.yp.to/bib/1992/montgomery-lucas.pdf).
  differential Lucas chain과 PRAC rule의 원자료다.
- Paul Zimmermann and Bruce Dodson,
  [“20 years of ECM”, Section
  2.2](https://members.loria.fr/PZimmermann/papers/ecm-submitted.pdf).
  golden-ratio 및 transformed-alpha PRAC seed와 비용 탐색을 대조했다.
- Martin Kutz,
  [“Lower Bounds for Lucas Chains”](https://epubs.siam.org/doi/10.1137/S0097539700379255),
  *SIAM Journal on Computing* 31(6), 2002. Fibonacci형 길이 하한의
  맥락이며, 현재 124-op chain의 전역 최적성을 뜻하지는 않는다.
- [GMP-ECM `lucas.c`](https://sources.debian.org/src/gmp-ecm/7.0.6%2Bds-2/lucas.c/).
  production `pp1_mul_prac`의 rule 순서와 alias-safe update를 확인했다.
- François Morain and Jorge Olivos,
  [“Speeding up the computations on an elliptic curve using
  addition-subtraction chains”](https://www.numdam.org/item/ITA_1990__24_6_531_0/),
  *RAIRO Informatique théorique et applications* 24(6), 1990,
  pp. 531–543. Signed addition/subtraction chain과 NAF 선택의 근거다.
- [OpenMP API Specification 5.1: `omp_set_schedule`](https://www.openmp.org/spec-html/5.1/openmpsu130.html)
  및 [OpenMP 5.0 `OMP_SCHEDULE`](https://www.openmp.org/spec-html/5.0/openmpse49.html).
  정적/동적 schedule과 chunk 의미의 공식 명세다. 최종 코드는 조기
  종료를 더 정확히 제어하기 위해 atomic monotone block counter를 쓴다.
- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html).
  채택한 BMI2/ADX scalar multiply/carry intrinsic의 의미와 AVX2 integer
  multiply가 제공하는 operand/result lane 폭을 확인하는 1차 자료다.
- Michael McLoughlin,
  [`addchain`](https://github.com/mmcloughlin/addchain). 고정 sqrt 지수의
  addition chain을 탐색해 기존 sliding-window와 operation 수가 사실상
  같은지 확인하는 데 사용했다.

## 제한과 이식성

- GNU/Clang 계열의 `unsigned __int128`과 OpenMP가 필요하다.
- `-march=native` 결과이므로 다른 CPU의 절대 시간과 직접 비교하면 안 된다.
- VM 공유 부하가 있으므로 raw sample과 MAD를 함께 봐야 한다.
- Table은 90KB라 이 host의 private cache에는 맞지만, cache가 매우 작은
  target에서는 4-bit fixed-window 같은 작은 table과 다시 비교해야 한다.
- 생성 binary와 JSON report는 `/tmp`에만 두며 repository asset으로
  commit하지 않는다.
