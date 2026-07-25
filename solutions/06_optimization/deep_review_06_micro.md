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
- scan curve: 원곡선과 동형인 `a=-3` 모델, 결과 x는 원래 좌표로 환산
- 역원: canonical `unsigned __int128` binary extended GCD
- 제곱근: 고정 지수 `(p+1)/4`의 width-4 sliding window
- scheduler 기본값 `adaptive`: 1 thread는 batch affine-x block, 2 threads
  이상은 scalar pipeline을 64-candidate 연속 block 단위로 배분

이전 native 경로의 동일-run 역사 수치는 원본 Python 대비 1 thread
38.81배, 8 threads 165.42배였다. 이번 pass의 최종 binary는 별도 broad
screening에서 GMP 대비 1 thread 25.91배, 8 threads 10.02배였지만 shared
VM 부하가 커 절대 시간과 broad ratio는 진단값으로만 취급한다. 작은 변경의
채택 근거는 아래 40-pair adjacent AB/BA campaign으로 분리했다. 모든
수치는 정답 검증을 통과한 sample만 포함한다.

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

제곱근은 `p == 3 mod 4`이므로 `a^((p+1)/4)` 뒤 square check를 한다.
이 고정 지수는 86비트이고 popcount가 49다. binary exponentiation의
약 48 multiply를 width-4 odd-power table과 약 18개의 후속 window로
바꿔, 구현상 대략 25~26 multiply와 low-80s square가 된다. 제곱근은
모든 `x`에 필요하고, 별도의 Legendre exponent를 앞에 붙이면 작업이
중복되므로 native 경로에는 residue pre-test를 넣지 않았다.

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

### 4. block scheduling과 batch affine-x

Atomic block counter가 낮은 low bits부터 연속 64개씩 나눠 준다. 정답이
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
겹치기 때문이다. 그래서 `--schedule adaptive`는 1 thread에서
`block`, 그보다 많을 때 `scalar`를 고른다. `block`, `scalar`, `static`
모두 명시적으로 재현할 수 있다.

## 정확성 검증

검증을 세 층으로 분리했다.

1. **Field 층:** deterministic random 2,000 pair와
   `{0,1,2,p-2,p-1,2^64-1,2^64,2^64+1}`의 64개 경계 pair에 대해 Montgomery
   conversion/add/subtract/multiply를 canonical U128 double-and-add
   modular multiplication과 비교한다. Binary-GCD inverse와 Fermat
   inverse, binary sqrt와 window-4 sqrt도 서로 대조한다.
2. **Point/table 층:** 32개 작은 scalar와 224개 deterministic random
   scalar, 총 256개에 대해 affine slope/inverse 기반 simple binary
   reference, NAF/mixed Jacobian, fixed `Q` comb 결과의 x/y를 모두
   비교한다. 별도로 실제 curve-valid lift 128개에서 Hamburg와 NAF의
   affine x를 대조한다.
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
`field_backend`, curve model, `d` multiplication, table width, thread,
schedule, inverse와 sqrt까지 출력한다. runner는 요청한 후보와 이
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
  bootstrap CI, AB/BA 두 stratum과 absolute/effect stationarity를 모두
  통과하고 median이 `1.02x`를 넘어야 작은 후보를 승격한다. 저장된 JSON
  옆에는 source snapshot, source/runner/binary SHA-256, build argv, CPU
  model/flags/topology와 raw event를 함께 보존한다.

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
| original curve / isomorphic `a=-3` | 1.1022x | 1.0320..1.1274 | FAIL | diagnostic-only |
| w8 table / w4 table | 0.9483x | 0.9243..0.9737 | FAIL | w8 유지 |
| block 64 / block 128 | 0.9948x | 0.9093..1.0473 | FAIL | 64 유지 |
| generic carry / BMI2+ADX | 2.9808x | 2.7330..3.2589 | FAIL | 큰 방향성만 확인 |

마지막 arithmetic holdout은 40쌍 모두 BMI2/ADX가 `2.04x` 이상
이겼지만 host load average가 16을 넘으며 block spread gate가 실패했다.
따라서 그 숫자는 diagnostic-only다. x86 BMI2/ADX 기본 경로와 portable
fallback 선택은 유지하되, 정확한 target CPU 성능을 주장할 때에는 조용한
환경에서 holdout을 다시 실행해야 한다.

최종 source/runner를 고정한 뒤 generic carry + legacy scan + 원곡선 +
NAF 전체 대조군과 최종 stack을 충분한 warm-up 10쌍 뒤 40쌍으로 다시
검사했다. baseline/candidate median은 `0.283205/0.076114 s`, paired
median은 `3.7126x`(CI `3.7106..3.7251`)였다. AB/BA stratum median도
`3.7125x/3.7197x`였고 absolute block spread는 각각 0.81%/0.76%,
effect spread는 1.32%로 stationarity와 promotion gate를 모두 통과했다.
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

## 실패하거나 보류한 전략

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
최신 w4 holdout도 `0.9483x`라 w8을 유지한다. block 8 대 64의 이전
8-thread 비교와 block 128 대 64의 최신 1-thread 비교 모두 CI가 parity를
포함해 기본 64를 유지했다.

### PRAC, GLV와 더 넓은 고정 chain

PRAC은 임의 scalar multiplication의 addition chain을 줄일 수 있지만 이
문제의 hot scalar `d`는 고정이고 Hamburg ladder가 이미 더 규칙적인
x-only 경로를 제공한다. GLV/endomorphism 분해는 이 generic-j
short-Weierstrass curve에서 쓸 수 있는 효율적인 endomorphism과 subgroup
구조가 주어지지 않았다. 매우 넓은 고정 addition chain도 code size,
per-lift precomputation과 exceptional case를 포함하면 NAF/Hamburg를
넘지 못해 구현 후보에서 제외했다.

### `mpz_legendre` 선필터

GMP에서는 `mpz_powm` sqrt 전에 값싼 Jacobi/Legendre test로 비잔여 절반을
거르는 후보를 별도로 실험할 가치가 있다. Native 구현에서는 Legendre를
다른 exponentiation으로 계산하면 바로 sqrt를 계산하는 것보다 작업이
중복되므로 채택하지 않았다.

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
