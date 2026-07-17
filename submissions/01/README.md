# 문제 1 제출 패키지 안내

최종 보고서는 [`../../writeups/01_암호분석.md`](../../writeups/01_암호분석.md), 실행 코드는 [`../../solutions/solve_01_classical.py`](../../solutions/solve_01_classical.py)다.

## 실행

Python 3.10 이상과 배포 ZIP만 필요하다. 외부 패키지는 사용하지 않는다.

```bash
python3 solutions/solve_01_classical.py
python3 solutions/solve_01_classical.py --full-caesar-table
python3 solutions/solve_01_classical.py --dump-caesar-dir /tmp/problem01-caesar
```

두 번째 명령은 26개 Caesar key 각각의 A~Z 빈도와 카이제곱 값을 포함한 상세 표를 출력한다. 세 번째 명령은 26개 전체 복호문과 빈도 TSV를 만든다. 실행 마지막의 `self-checks: PASS`로 모든 정답과 학습 결과를 검증한다.

## 공식 결과

```text
ciphertexts1: Caesar, IC=0.067638 (답안 표기 0.068), shift=6
ciphertexts2: Vigenere, IC=0.043972 (답안 표기 0.044), key=KLVOJ, line-reset

3-다/4-다 평문:
THESOVEREIGNTYOFTHEREPUBLICOFKOREASHALLRESIDEINTHEPEOPLEANDALLSTATEAUTHORITYSHALLEMANATEFROMTHEPEOPLE

학습 분류기:
standardized L2 logistic regression
train=218, held-out test=58, accuracy=58/58

짧은 암호문 1..4의 관측 구조:
Caesar-like, Caesar-like, Caesar-like, Caesar-like
shift=6, 10, 10, 6
```

짧은 암호문 1/2와 3/4는 각각 전역 shift만 다른 쌍이다. 길이 1 Vigenère는 Caesar와 동일하므로, 문제에서 말한 숨은 “혼합” 생성기 라벨은 암호문만으로 식별 불가능하다. 보고서에 모델 설계, 출력 확률, 이 한계의 수학적 증명을 함께 적었다.
