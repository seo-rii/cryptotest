# 문제 6: native arithmetic/cache 심층 최적화

## 결론

88비트 소수체를 GMP 대신 고정 2-limb Montgomery 체로 구현하고, Jacobian
point를 무할당 POD로 만들며, 고정점 `Q`의 byte-comb table을 affine으로
batch-normalize했다. 최종 후보는 다음을 기본으로 쓴다.

- field element: 16바이트 (`uint64_t` 두 limb)
- Jacobian point: 48바이트, heap allocation 없음
- `Q` table: `11 * 256 * 32 = 90,112`바이트 affine read-only layout
- Jacobian + affine mixed addition: `madd-2007-bl`
- 임의점 `dR`: per-candidate precomputation이 없는 width-2 NAF
- 역원: canonical `unsigned __int128` binary extended GCD
- 제곱근: 고정 지수 `(p+1)/4`의 width-4 sliding window
- scheduler 기본값 `adaptive`: 1 thread는 batch affine-x block, 2 threads
  이상은 scalar pipeline을 64-candidate 연속 block 단위로 배분

같은 프로세스 단위 benchmark run에서 원본 Python 대비 1 thread는
38.81배, 8 threads는 165.42배 빨랐다. 같은 thread 수의 GMP 구현과
비교하면 각각 5.44배, 5.13배였다. 모든 수치는 정답 검증을 통과한
sample만 포함한다.

구현은 `deep_native_06.cpp`, 반복 측정기는
`benchmark_deep_native_06.py`다. 이 파일들은 실험 후보이며 기존
maintained solver를 몰래 대체하지 않는다.

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
`11M+5S`, mixed addition `7M+4S`다. `dR`에도 같은 mixed formula를
쓰기 위해 width-2 NAF의 digit `{-1,0,+1}`만 사용한다. 실제 `d`의
width-2 NAF는 27개 nonzero digit이다. width-4는 digit/addition 수만
보면 precompute 3회 + digit 16회로 작지만, 매 후보에서 odd multiple을
만들어 affine으로 바꾸거나 generic addition을 써야 하므로 이 layout과
맞지 않았다.

### 3. block scheduling과 batch affine-x

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

1. **Field 층:** deterministic 2,000 vector에 대해 Montgomery
   conversion/add/subtract/multiply를 canonical U128 double-and-add
   modular multiplication과 비교한다. Binary-GCD inverse와 Fermat
   inverse, binary sqrt와 window-4 sqrt도 서로 대조한다.
2. **Point/table 층:** 32개 작은 scalar와 224개 deterministic random
   scalar, 총 256개에 대해 affine slope/inverse 기반 simple binary
   reference, NAF/mixed Jacobian, fixed `Q` comb 결과의 x/y를 모두
   비교한다.
3. **전체 attack 층:** 모든 benchmark process가 아래를 검사한다.

```text
d        = 0x1c3cdd6b221806db0a7b28
P == dQ  = true
s2       = 0x638d9d631ab436da51e640
r3       = 0x2443c8daf1a9d52b09
lift low = 0x5338
```

원본 Python은 low bits를 출력하지 않으므로 runner가 그 process에서는
`d`, `P=dQ`, `s2`, `r3`를 검증한다. GMP/native process는 low bits까지
검증한다. 기존 원본의 출력 이름 `s1`은 수학적으로 `s2`이고 runner는
그 값만 정상화한다.

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
scan, final prediction을 포함한다. 구현 순서는 round마다 cyclic rotation
후 reverse하여 고정 순서 bias를 줄였다. 한 번의 warm-up을 버리고 5회
측정했으며 `time.perf_counter` external wall clock을 사용했다.

### 최종 통합 측정

이 표는 원본 Python, GMP, native를 **같은 interleaved run**에서 직접
측정한 결과다. `ratio`는 median의 비이고 `paired`는 같은 round의
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

### 별도 run을 섞은 참고 추정

이전 full matrix의 원본 Python median 14.298741초와 7회 native scalar
8-thread median 0.077461초를 단순히 나누면 약 184.6배다. 그러나 서로
다른 run/부하를 섞은 값이므로 최종 성능 주장에는 쓰지 않는다. 위의
동일-run 165.42배가 재현 가능한 end-to-end 결과다.

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
stage timing, ratio-of-medians, paired speedup을 JSON에 모두 보존한다.

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
  AVX2 integer multiply가 제공하는 operand/result lane 폭을 확인하는
  1차 자료다. 이 제약 때문에 2-limb 64-bit Montgomery의 직접 AVX2
  변환을 보류했다.

## 제한과 이식성

- GNU/Clang 계열의 `unsigned __int128`과 OpenMP가 필요하다.
- `-march=native` 결과이므로 다른 CPU의 절대 시간과 직접 비교하면 안 된다.
- VM 공유 부하가 있으므로 raw sample과 MAD를 함께 봐야 한다.
- Table은 90KB라 이 host의 private cache에는 맞지만, cache가 매우 작은
  target에서는 4-bit fixed-window 같은 작은 table과 다시 비교해야 한다.
- 생성 binary와 JSON report는 `/tmp`에만 두며 repository asset으로
  commit하지 않는다.
