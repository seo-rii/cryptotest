# 2026 암호분석경진대회 풀이

2026 암호분석경진대회 문제 분석, 풀이 코드, writeup을 모은 저장소다.

## 구성

- `problems/`: 배포된 문제 자료
- `solutions/`: 분석 및 재현 코드
- `writeups/`: 문제별 풀이 문서
- `2026_암호분석경진대회_0525.zip`: 원본 문제 묶음

문제 7의 장기 연구는 별도 `soinsu` 프로젝트에서 진행했으며, 최종 결과만 이 저장소로 옮겼다.

- [문제 7 최종 writeup](writeups/07_소인수분해.md)
- [문제 7 최종 격자 solver](solutions/solve_07_grouped_hm_flatter.cpp)
- [문제 7 결과 검증 및 RSA 복호화](solutions/solve_07_final.py)

## 문제별 문서

1. [암호분석](writeups/01_암호분석.md)
2. [암호구현](writeups/02_암호구현.md)
3. [네트워크보안](writeups/03_네트워크보안.md)
4. [디지털포렌식](writeups/04_디지털포렌식.md)
5. [동형암호](writeups/05_동형암호.md)
6. [PRNG](writeups/06_PRNG.md)
7. [소인수분해](writeups/07_소인수분해.md)
8. [블록암호](writeups/08_블록암호.md)

## 제외한 로컬 자료

`4_raw/`의 모델 가중치와 `tmp/`의 실험 중간 산출물은 용량이 크거나 다시 만들 수 있어 Git에 포함하지 않는다. Python cache, CNF, 실행 로그, 컴파일 산출물도 `.gitignore`로 제외한다.
