# 2026 암호분석경진대회 전체 정리

> 최종 갱신: 2026-07-18

이 문서는 `cryptotest`의 8개 문제에 대한 현재 완료 상태, 핵심 결과,
재현 진입점과 검증 수준을 한곳에 모은 전체 색인이다. 문제별 수식,
실험 과정, 실패 전략과 참고 문헌은 각 상세 writeup에 둔다.

## 전체 진행상황

| 번호 | 주제 | 상태 | 최종 결과 | 상세 writeup |
|---:|---|---|---|---|
| 1 | 고전 암호와 분류 | 완료 | Caesar shift `6`, Vigenère key `KLVOJ`, 재현 가능한 분류 모델과 식별 불가능성 분석 | [01_암호분석](01_암호분석.md) |
| 2 | 256비트 permutation 구현 | 풀이·현 제출 최적화 완료 | `rot={43,7,29,14}`, 2-round 합성과 scalar full-unroll/BMI2 제출 구현 | [02_암호구현](02_암호구현.md) |
| 3 | TLS 1.2 AES-GCM 위조 | 완료 | nonce 재사용으로 `H`와 `E_K(J0)`를 복원하고 유효한 급여 변경 record 생성 | [03_네트워크보안](03_네트워크보안.md) |
| 4 | LLM weight steganography | 완료 | `CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}` 추출 | [04_디지털포렌식](04_디지털포렌식.md) |
| 5 | textbook-BGV | 완료 | ternary secret 64계수, 날짜 `20260410→20260411`, 고정 `State` 복원 | [05_동형암호](05_동형암호.md) |
| 6 | Dual_EC_DRBG | 풀이·최적화 완료 | backdoor scalar `d`, state `s2`, `r3=0x2443c8daf1a9d52b09` 복원 | [06_PRNG](06_PRNG.md) |
| 7 | RSA partial key exposure | 완료 | `p`, `q`와 `FLAG{d1rty_b1t_l34k_c0pp3rsm1th_m33ts_str4t3gy}` 복원 | [07_소인수분해](07_소인수분해.md) |
| 8 | 변형 AES 7라운드 | 완료 | master key `2923be84e16cd6ae529049f1f1bbe9eb` 복원 | [08_블록암호](08_블록암호.md) |

8문제의 요구 결과를 모두 정리했다. 1번에서 관측 암호문만으로 유일하게
결정할 수 없는 숨은 생성기 label은 임의 답을 만들지 않고 그 식별
불가능성을 증명했으며, 나머지는 요구 값을 복원했다. 원문이 별도 형식을
요구한 답안, 코드, 계수, TLS record와 PDF는
[제출 파일 색인](../submissions/README.md)에 문제별로 정리되어 있다.

## 완료와 성능 개선의 구분

2번과 6번은 정답 복원만으로 끝나지 않고 실행 시간이 점수나 실용성에
영향을 주는 문제다. 두 문제 모두 정확성 조건은 완료됐으며, 성능
결과는 다음처럼 별도로 관리한다.

### 2번

- 20라운드를 두 라운드씩 합성하면 word reversal이 상쇄되어 네 개의
  독립 scalar chain이 된다.
- 최종 제출은 ten-pair full-unroll과 local BMI2 target을 사용한다.
- 제공 1-round vector 1,000개, 20-round vector, 무작위 differential
  100,000개를 통과한 후보만 측정한다.
- AMD EPYC 호스트의 10,000,000-iteration, 3-warmup, 15-sample 반복
  실행에서는 최적화 전후 paired 중앙값이 1.068x였다. shared VM 변동과
  Intel frontend 차이 때문에 Core Ultra 7 255H로 이식할 때는
  full-unroll과 `unroll5_bmi2`를 다시 A/B하는 것을 권장한다. 이는 완료된
  현 제출 구현의 정확성이나 현재 호스트 선택을 바꾸지 않는 이식 점검이다.
- 측정 도구와 raw 기록은 [02 optimization README](../solutions/02_optimization/README.md),
  [deep review](../solutions/02_optimization/deep_review_02.md),
  [raw samples](../solutions/02_optimization/deep_results_02.txt)에 있다.

### 6번

- telemetry 전수조사를 `floor_sum` 기반 analytic count로 바꾸고,
  sign 대칭, fixed-`Q` comb, wNAF, native Montgomery arithmetic와
  OpenMP scheduling을 적용했다.
- telemetry 단계 자체의 반복 측정 중앙값은 1,453.475ms에서 0.750ms로
  줄어 1,938x 개선됐다.
- 모든 benchmark sample은 `d`, `s2`와 `r3`를 다시 검사하므로 빠른
  오답 구현은 결과에 포함되지 않는다.
- 같은 반복 캠페인에서 native adaptive 8-thread 구현은 원래 Python
  대비 ratio-of-medians 165.42x를 기록했다. 절대 시간은 호스트 부하에
  민감하므로 raw sample, median과 MAD를 함께 보존한다.
- 구현과 ablation은 [06 optimization README](../solutions/06_optimization/README.md),
  [algorithm review](../solutions/06_optimization/deep_review_06_algorithm.md),
  [native/cache review](../solutions/06_optimization/deep_review_06_micro.md)에 있다.

나머지 여섯 문제는 최종 산출물의 정확성이 주된 목표이며, 별도의
score-facing 성능 경쟁은 없다.

## 최종 재현 진입점

저장소 루트에서 실행한다.

| 번호 | 최종 재현 파일 | 역할 |
|---:|---|---|
| 1 | [`solve_01_classical.py`](../solutions/solve_01_classical.py) | IC, Caesar/Vigenère 복호와 분류 결과 재현 |
| 2 | [`solve_02_permutation.py`](../solutions/solve_02_permutation.py), [`solve_02_permutation.c`](../solutions/solve_02_permutation.c), [`benchmark_02_permutation.py`](../solutions/benchmark_02_permutation.py) | 구조 복원, standalone oracle와 warmup 후 반복 benchmark |
| 3 | [`solve_03_tls_gcm_nonce_reuse.py`](../solutions/solve_03_tls_gcm_nonce_reuse.py) | pcap 파싱, GHASH 복원, record 위조와 제출값 검증 |
| 4 | [`solve_04_digital_forensics.py`](../solutions/solve_04_digital_forensics.py) | 공식 모델 ZIP 해시 검증과 weight nibble payload 추출 |
| 5 | [`solve_05_bgv.py`](../solutions/solve_05_bgv.py) | GF(257) 선형계로 secret과 두 평문 복원 |
| 6 | [`solve_06_prng.py`](../solutions/solve_06_prng.py), [`deep_native_06.cpp`](../solutions/06_optimization/deep_native_06.cpp), [`benchmark_deep_native_06.py`](../solutions/06_optimization/benchmark_deep_native_06.py) | dependency-free Python 정답 경로, 최종 native 경로와 warmup 후 반복 benchmark |
| 7 | [`solve_07_final.py`](../solutions/solve_07_final.py), [`solve_07_grouped_hm_flatter.cpp`](../solutions/solve_07_grouped_hm_flatter.cpp) | 결과 검증/RSA 복호화와 grouped HM 공격 재실행 |
| 8 | [`solve_08_aes_key.py`](../solutions/solve_08_aes_key.py) | leak 기반 MITM key 복원과 전체 pair 재검증 |

먼저 빠른 정답·smoke 검증은 다음과 같다.

```bash
python3 solutions/solve_01_classical.py

python3 solutions/benchmark_02_permutation.py \
  --warmups 1 --samples 5 --iterations 1000000 --random-cases 100000

python3 solutions/solve_03_tls_gcm_nonce_reuse.py
python3 solutions/solve_04_digital_forensics.py --verify-sha256
python3 solutions/solve_05_bgv.py
python3 solutions/solve_06_prng.py --backend int --telemetry analytic
python3 solutions/solve_07_final.py
python3 solutions/solve_08_aes_key.py
```

2번의 1.068x 장기 캠페인과 6번의 165.42x native matrix를 같은 protocol로
다시 측정하려면 각각 다음을 실행한다. 절대 시간과 speedup은 CPU 및 shared
VM 부하에 따라 달라질 수 있으므로 raw sample, median과 MAD를 함께 본다.

```bash
python3 solutions/benchmark_02_permutation.py \
  --warmups 3 --samples 15 --iterations 10000000 --random-cases 100000

python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 5 --threads 1,8 \
  --native-schedules adaptive --include-original-python \
  --output /tmp/challenge06-native.json
```

4번은 Git에서 제외한 대형 공식 입력을 `4_raw/`에 두어야 한다. 2번의
benchmark는 correctness gate를 먼저 수행하며, 7번의 전체 격자 공격
빌드·실행 명령은 상세 writeup의 `격자 공격 재실행` 절에 있다.

## 최종 검증 상태

| 번호 | 검증 기준 |
|---:|---|
| 1 | Caesar shift `6`, Kasiski period `5`와 key `KLVOJ`, held-out 분류 58/58, 구조적 식별 불가능성 확인 |
| 2 | 제공 1-round 1,000개와 20-round vector, 100,000개 deterministic random differential case 통과 |
| 3 | pcap record 경계, nonce 재사용, `H`, `E_K(J0)`, plaintext delta, tag, 77바이트 record 길이와 제출 hex 일치 |
| 4 | 공식 ZIP SHA-256 확인 후 `model.embed_tokens.weight`의 low nibble payload에서 flag 추출 |
| 5 | 같은 secret으로 두 ciphertext 복호화, 날짜 하루 증가, 동일 `State`, error range `1..4` 확인 |
| 6 | `P=dQ`, `d`, `s2`, `r3` 확인; native preflight에서 field 2,000개와 point/scalar 256개 reference 대조 |
| 7 | `p*q=N`, `(p & MASK)==P_AND_MASK`, RSA 재암호화와 plaintext bytes 일치 |
| 8 | 복구한 master key로 50,000개 평문/암문 pair 전체 재암호화, mismatch 0 |

## 7번 장기 탐색의 최종 정리

7번은 장기간 여러 solver와 변수 분할을 비교했지만 최종 공격은 간결하다.
양끝 4비트씩만 256개로 열거하고, 정답 `cid=155 (0x9b)`에서 나머지를 `[265,420)` 155비트와
`[600,830)` 230비트의 두 연속 변수로 완화한다. `m=17,t=5`의
171차원 Herrmann--May 격자를 FLATTER로 감축한 뒤, 소수체 resultant/GCD와
CRT로 정답 근을 복원했다.

SMT, exact-tail CP-SAT, Hensel prefix, exact·얕은 grouped HM, cuso 설계,
two-sided/partial-`p`, Coron, 휴리스틱 q-gap과 조건부 low600 clause, ranker와
Jochemsz--May low-lift의 결과와 중단 근거는
[7번 실패 전략 절](07_소인수분해.md#1-직접-탐색과-실패한-전략)에
전략별로 정리했다.

시점별 세부 실험은 다음 자료에 보존한다.

- [탐색 README](../solutions/07_sat_cas_explore/README.md)
- [실험 계획과 의사결정 기록](../solutions/07_sat_cas_explore/EXPLORATION_PLAN.md)
- [실행 로그](../solutions/07_sat_cas_explore/RUN_LOG.md)

이 자료의 중간 시점에 적힌 `UNKNOWN`, `no-factor`와 다음 실행 계획은
당시 탐색 문맥을 보존한 기록이다. 현재 완료 상태와 최종 방법의 기준은
이 전체 정리와 [7번 최종 writeup](07_소인수분해.md)이다.

## 문서와 제출물 구조

- `writeups/01..08`: 문제별 배경지식, 최종 풀이, 검증, 참고 자료
- [제출 파일 색인](../submissions/README.md): 문제별 실제 제출 산출물
- [저장소 README](../README.md): 저장소 구성과 가장 짧은 완료 현황
- `solutions/02_optimization`, `solutions/06_optimization`: 반복 측정,
  후보 비교와 micro/algorithm review
- `solutions/07_sat_cas_explore`: 7번 장기 탐색의 시점별 원자료

따라서 진행상황을 판단할 때는 이 문서의 `전체 진행상황`을 먼저 보고,
수치와 근거는 해당 문제의 상세 writeup 및 재현 코드에서 확인한다.
