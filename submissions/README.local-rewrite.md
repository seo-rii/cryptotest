# 제출 파일 색인

원문이 요구한 답안과 별도 형식의 파일을 문제별로 모았다. 상세 분석은 각 writeup, 결과 생성과 검증은 `solutions/`의 solver가 담당한다.

| 번호 | 제출 파일 | 비고 |
|---:|---|---|
| 1 | [`01/report.pdf`](01/report.pdf), [`01/report.tex`](01/report.tex), [`01/classifier.py`](01/classifier.py), [`01/README.md`](01/README.md) | 분석 보고서와 표준 라이브러리 분류기 |
| 2 | [`02/contest.c`](02/contest.c), [`02/report.pdf`](02/report.pdf), [`02/report.tex`](02/report.tex) | 기본 build 호환 adaptive BMI2/cross-call inline C와 제출 문서 |
| 3 | [`03/forged_record.txt`](03/forged_record.txt), [`03/report.pdf`](03/report.pdf), [`03/report.tex`](03/report.tex), [`03/README.md`](03/README.md) | TLS record hex와 nonce-reuse/GHASH 위조 보고서 |
| 4 | [`04/solve.py`](04/solve.py), [`04/report.pdf`](04/report.pdf), [`04/report.md`](04/report.md), [`04/report.tex`](04/report.tex), [`04/flag.txt`](04/flag.txt), [`04/README.md`](04/README.md) | 발견·추출 Python, 방법론 문서와 FLAG |
| 5 | [`05/01_method_1page.pdf`](05/01_method_1page.pdf), [`Markdown`](05/01_method_1page.md), [`TeX`](05/01_method_1page.tex), [`05/02_secret_s.txt`](05/02_secret_s.txt), [`05/03_state.txt`](05/03_state.txt) | 1페이지 방법론과 차수 오름차순 계수 |
| 6 | [`06/01_answer.txt`](06/01_answer.txt), [`06/02_method.pdf`](06/02_method.pdf), [`06/02_method.md`](06/02_method.md), [`06/02_method.tex`](06/02_method.tex), [`06/README.md`](06/README.md) | `r3`, 복잡도·정확성·반복 벤치마크를 포함한 분석 보고서 |
| 7 | [`07/plaintext.txt`](07/plaintext.txt), [`07/plaintext.hex`](07/plaintext.hex), [`07/report.pdf`](07/report.pdf), [`07/report.tex`](07/report.tex), [`07/README.md`](07/README.md) | big-endian 평문 ASCII/hex와 성공·실패 전략을 정리한 보고서 |
| 8 | [`08/master_key.txt`](08/master_key.txt), [`08/report.pdf`](08/report.pdf), [`08/report.tex`](08/report.tex), [`08/README.md`](08/README.md) | 16바이트 master key와 meet-in-the-middle 복구 보고서 |

Markdown/TeX 원본도 PDF와 함께 보존하여 결과를 수정하거나 다시 렌더링할 수 있게 했다. 문제 4의 대형 배포 입력은 제출물이 아니며 저장소에서도 제외한다.
