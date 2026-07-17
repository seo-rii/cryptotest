# 2026 암호분석경진대회 풀이

2026 암호분석경진대회 8문제의 분석, 재현 코드, writeup과 제출용 결과를 모은 저장소다. 모든 문제의 요구 결과를 복원했으며, 원문이 요구한 별도 제출 형식도 `submissions/`에 정리했다.

## 구성

- `problems/`: 배포된 문제 자료
- `solutions/`: 분석 및 재현 코드
- `writeups/`: 문제별 풀이 문서
- `submissions/`: 제출용 코드·답안·PDF·계수 파일
- `2026_암호분석경진대회_0525.zip`: 원본 문제 묶음

문제 7의 장기 연구는 별도 `soinsu` 프로젝트에서 진행했으며, 최종 결과만 이 저장소로 옮겼다.

- [문제 7 최종 writeup](writeups/07_소인수분해.md)
- [문제 7 최종 격자 solver](solutions/solve_07_grouped_hm_flatter.cpp)
- [문제 7 결과 검증 및 RSA 복호화](solutions/solve_07_final.py)

## 완료 현황

| 번호 | 문제 | 최종 결과 | 재현 코드 |
|---:|---|---|---|
| 1 | [암호분석](writeups/01_암호분석.md) | Caesar `6`, Vigenère `KLVOJ`, 학습 분류기 완료 | [`solve_01_classical.py`](solutions/solve_01_classical.py) |
| 2 | [암호구현](writeups/02_암호구현.md) | 연산 순서와 `rot={43,7,29,14}`, 최적화 C/벤치마크 완료 | [`solve_02_permutation.c`](solutions/solve_02_permutation.c) |
| 3 | [네트워크보안](writeups/03_네트워크보안.md) | 유효한 TLS-GCM 위조 record | [`solve_03_tls_gcm_nonce_reuse.py`](solutions/solve_03_tls_gcm_nonce_reuse.py) |
| 4 | [디지털포렌식](writeups/04_디지털포렌식.md) | `CRYPTO{...}` 모델 은닉 payload | [`solve_04_digital_forensics.py`](solutions/solve_04_digital_forensics.py) |
| 5 | [동형암호](writeups/05_동형암호.md) | BGV secret 64계수와 State 56계수 | [`solve_05_bgv.py`](solutions/solve_05_bgv.py) |
| 6 | [PRNG](writeups/06_PRNG.md) | `r3=0x2443c8daf1a9d52b09` | [`solve_06_prng.py`](solutions/solve_06_prng.py) |
| 7 | [소인수분해](writeups/07_소인수분해.md) | RSA 인수와 `FLAG{...}` | [`solve_07_final.py`](solutions/solve_07_final.py) |
| 8 | [블록암호](writeups/08_블록암호.md) | AES key `2923be84e16cd6ae529049f1f1bbe9eb` | [`solve_08_aes_key.py`](solutions/solve_08_aes_key.py) |

[제출 파일 색인](submissions/README.md)에는 문제별로 바로 제출하거나 패키징할 파일을 연결했다.

1번의 네 짧은 분류 표본은 모두 단일 Caesar shift로 완전히 설명된다. 길이 1 Vigenère는 Caesar와 같은 함수이므로, 별도의 숨은 생성기 라벨은 암호문만으로 식별할 수 없다. 모델 결과와 이 식별 불가능성 증명은 1번 writeup에 함께 기록했다.

## 제외한 로컬 자료

`4_raw/`의 모델 가중치·17GB 서버 로그와 `tmp/`의 실험 중간 산출물은 용량이 크거나 다시 만들 수 있어 Git에 포함하지 않는다. 4번 solver는 문제 PDF에 적힌 공식 SHA-256을 검증하며, 필요한 원본 경로를 명확히 안내한다. Python cache, CNF, 실행 로그, 일반 컴파일 산출물도 `.gitignore`로 제외한다.
