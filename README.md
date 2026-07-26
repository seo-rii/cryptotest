# 2026 암호분석경진대회 풀이

2026 암호분석경진대회 8문제의 분석, 재현 코드, writeup과 제출용 결과를 모은 저장소다. 복원 가능한 요구 결과를 모두 얻었고, 데이터만으로 결정할 수 없는 1번의 숨은 생성기 label은 그 식별 불가능성을 증명했다. 원문이 요구한 별도 제출 형식도 `submissions/`에 정리했다.

처음 읽는 경우 [전체 정리와 진행상황](writeups/2026_crypto_contest_learning_notes.md)에서 8문제의 결과·성능·검증 수준을 확인한 뒤, 아래 표에서 문제별 상세 writeup으로 들어가면 된다.

## 구성

- `problems/`: 배포된 문제 자료의 정식 사본
- `solutions/`: 분석 및 재현 코드
- `writeups/`: 문제별 풀이 문서
- `submissions/`: 제출용 코드·답안·PDF·계수 파일과 색인

## 빠른 검증과 벤치마크

개발용 Python 의존성에는 pytest, Z3와 7번 Coppersmith 테스트의
`sympy`/`fpylll` fallback이 들어 있다. `gmpy2` 가속 경로까지 재현할 때만
두 번째 파일을 추가로 설치하면 된다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r requirements-fast.txt  # 선택
```

C/C++ 검증에는 GCC/G++, OpenMP, `make`, `unzip`이 필요하고,
`make bench-06`의 GMP 대조군에는 GMP 개발 라이브러리도 필요하다.
저장소 루트의 공통 진입점은 다음과 같다.

```bash
make test      # pytest.ini에 따라 역사 보관용 *.old 트리는 수집하지 않음
make check-02  # 2번 회귀 테스트와 공식 벡터/제출 harness
make check-06  # Python, native self-test, UBSan 전체 1-thread 실행
make bench-02  # scalar와 lane-wise AVX2의 검증된 교차 측정
make bench-06  # native thread/schedule 측정
```

벤치마크 기본 출력은 `/tmp/cryptotest-bench-0{2,6}.json`이며 CPU, compiler,
플래그, affinity/thread 수, warm-up, 원시 표본, median/MAD, source hash와
Git 상태를 기록한다. 255H에서는 논리 CPU 번호를 먼저 확인한 뒤 서로 다른
시점에 코어 종류별로 실행해야 한다.

```bash
make bench-02 BENCH02_CPU=3 \
  BENCH02_OUTPUT=/tmp/ch2-pcore-session1.json
taskset -c 0-5 make bench-06 BENCH06_THREADS=6 \
  BENCH06_OUTPUT=/tmp/ch6-ponly-session1.json
```

`BENCH06_THREADS`, `BENCH06_SCHEDULES`, `BENCH06_BLOCK_SIZE`를 바꾸어
P-only/E-only/P+E/all-core 및 block-size 후보를 각각 별도 JSON으로
보존한다. 16 thread가 14 thread보다 빠르다고 가정하지 않는다.

문제 7의 장기 연구는 별도 `soinsu` 프로젝트에서 진행했다. 이 저장소에서는 아래 최종 solver와 writeup을 정본으로 삼고, `solutions/07_sat_cas_explore*`는 해결 전 탐색의 역사 기록으로만 보존한다.

- [문제 7 최종 writeup](writeups/07_소인수분해.md)
- [문제 7 최종 격자 solver](solutions/solve_07_grouped_hm_flatter.cpp)
- [문제 7 결과 검증 및 RSA 복호화](solutions/solve_07_final.py)

## 완료 현황

| 번호 | 문제 | 최종 결과 | 재현 코드 |
|---:|---|---|---|
| 1 | [암호분석](writeups/01_암호분석.md) | Caesar `6`, Vigenère `KLVOJ`, held-out `58/58`; 숨은 label 식별 불가능성 증명 | [`solve_01_classical.py`](solutions/solve_01_classical.py) |
| 2 | [암호구현](writeups/02_암호구현.md) | `rot={43,7,29,14}`, 검증된 scalar incumbent, 122-instruction/549-byte AVX2·122-byte/29-static counted block 후보, raw-recomputed 정상성 gate와 범위 제한 ISA 합성까지 로컬 탐색 종료; 실제 255H 판정만 미완 | [`solve_02_permutation.c`](solutions/solve_02_permutation.c) |
| 3 | [네트워크보안](writeups/03_네트워크보안.md) | 유효한 TLS-GCM 위조 record | [`solve_03_tls_gcm_nonce_reuse.py`](solutions/solve_03_tls_gcm_nonce_reuse.py) |
| 4 | [디지털포렌식](writeups/04_디지털포렌식.md) | `CRYPTO{...}` 모델 은닉 payload | [`solve_04_digital_forensics.py`](solutions/solve_04_digital_forensics.py) |
| 5 | [동형암호](writeups/05_동형암호.md) | BGV secret 64계수와 State 56계수 | [`solve_05_bgv.py`](solutions/solve_05_bgv.py) |
| 6 | [PRNG](writeups/06_PRNG.md) | `r3=0x2443c8daf1a9d52b09`; analytic telemetry, shifted `s3` scan, BMI2/ADX와 Hamburg native 경로 | [`Python`](solutions/solve_06_prng.py), [`native C++`](solutions/06_optimization/deep_native_06.cpp) |
| 7 | [소인수분해](writeups/07_소인수분해.md) | RSA 인수와 `FLAG{...}` | [`solve_07_final.py`](solutions/solve_07_final.py) |
| 8 | [블록암호](writeups/08_블록암호.md) | AES key `2923be84e16cd6ae529049f1f1bbe9eb` | [`solve_08_aes_key.py`](solutions/solve_08_aes_key.py) |

[제출 파일 색인](submissions/README.md)에는 문제별로 바로 제출하거나 패키징할 파일을 연결했다.

1번의 네 짧은 분류 표본은 모두 단일 Caesar shift로 완전히 설명된다. 길이 1 Vigenère는 Caesar와 같은 함수이므로, 별도의 숨은 생성기 라벨은 암호문만으로 식별할 수 없다. 모델 결과와 이 식별 불가능성 증명은 1번 writeup에 함께 기록했다.

## 제외한 로컬 자료

`4_raw/`의 모델 가중치·17GB 서버 로그와 `tmp/`의 실험 중간 산출물은 용량이 크거나 다시 만들 수 있어 Git에 포함하지 않는다. 4번 solver는 `--verify-sha256`을 지정하면 문제 PDF에 적힌 공식 SHA-256을 검증하며, 필요한 원본 경로를 명확히 안내한다. Python cache, CNF, 실행 로그, 일반 컴파일 산출물도 `.gitignore`로 제외한다.
