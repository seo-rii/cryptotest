# 문제 1 제출 패키지 안내

이 폴더에 제출 보고서와 실행 코드를 직접 포함했다.

- [`report.pdf`](report.pdf): 최종 분석 보고서
- [`report.tex`](report.tex): PDF 재생성 원본
- [`classifier.py`](classifier.py): 표준 라이브러리만 사용하는 분석·학습 코드

저장소의 상세 검토본은 [`../../writeups/01_암호분석.md`](../../writeups/01_암호분석.md),
동일한 solver 원본은
[`../../solutions/solve_01_classical.py`](../../solutions/solve_01_classical.py)다.

## 실행

Python 3.10 이상과 배포 ZIP만 필요하다. 외부 패키지는 사용하지 않는다.

```bash
python3 submissions/01/classifier.py
python3 submissions/01/classifier.py --full-caesar-table
python3 submissions/01/classifier.py --dump-caesar-dir /tmp/problem01-caesar
```

저장소 밖에서 실행할 때는 배포 ZIP 경로를
`--problem-zip /path/to/1_암호분석.zip`으로 지정한다. 두 번째 명령은
26개 Caesar key 각각의 A~Z 빈도와 카이제곱 값을 포함한 상세 표를
출력한다. 세 번째 명령은 26개 전체 복호문과 빈도 TSV를 만든다. 실행
마지막의 `self-checks: PASS`로 모든 정답과 학습 결과를 검증한다.

## 공식 결과

```text
ciphertexts1: Caesar, IC=0.067638 (답안 표기 0.068), shift=6
ciphertexts2: Vigenere, IC=0.043972 (답안 표기 0.044), key=KLVOJ, line-reset

3-다/4-다 평문:
THESOVEREIGNTYOFTHEREPUBLICOFKOREASHALLRESIDEINTHEPEOPLEANDALLSTATEAUTHORITYSHALLEMANATEFROMTHEPEOPLE

학습 분류기:
standardized L2 logistic regression
train=218, paired within-corpus/fixed-key holdout=58, accuracy=58/58

짧은 암호문 1..4의 관측 구조:
Caesar-like, Caesar-like, Caesar-like, Caesar-like
shift=6, 10, 10, 6

출제 의도 추정 라벨:
Caesar, Vigenere, Vigenere, Caesar
```

짧은 암호문 1/2와 3/4는 각각 전역 shift만 다른 쌍이다. 길이 1
Vigenère는 Caesar와 동일하므로, 문제에서 말한 숨은 “혼합” 생성기
라벨은 암호문만으로 식별 불가능하다. 보고서에는 관측 가능한 구조와
shift 6/10에서 추정한 출제 의도 라벨을 분리해 함께 적었다.
