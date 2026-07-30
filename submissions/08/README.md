# 문제 8 제출 패키지 안내

이 폴더에는 복원한 마스터 키와 최신 한국어 제출 보고서를 직접 포함했다.

- [`master_key.txt`](master_key.txt): 복원한 16바이트 마스터 키의 32자리 hex
- [`report.pdf`](report.pdf): 누출 기반 키 복원 과정과 전체 검증을 정리한 제출 보고서
- [`report.tex`](report.tex): PDF를 다시 만들 수 있는 LaTeX 원본
- [`investigate_aes_leak.py`](investigate_aes_leak.py),
  [`solve_aes_key.py`](solve_aes_key.py): 실행 코드
- [`8_블록암호.zip`](8_블록암호.zip): 원본 문제 ZIP

복원 결과:

```text
2923be84e16cd6ae529049f1f1bbe9eb
```

보고서는 변형 AES 구조, 직접 복원되는 3바이트, `2^16`/16/512/`2^20`
후보 결합, `complete_partial_keys()`의 마지막 3바이트 완전 생성, 유일 key
확정과 50,000쌍 재암호화 검증을 포함한다. 문제 힌트인
Demirci–Selçuk 공격과 실제로 구현한 leak-assisted key-byte constraint
join의 범위도 구분했다.

## 재현

이 폴더 안에서 Python 3.10 이상으로 실행한다. 외부 패키지는 필요하지
않으며 solver가 동봉된 `8_블록암호.zip`에서 데이터와 leak를 직접
읽는다.

```bash
cd submissions/08
python3 investigate_aes_leak.py
python3 solve_aes_key.py
```

정상 실행의 마지막 출력은 다음과 같다.

```text
master key = 2923be84e16cd6ae529049f1f1bbe9eb
verified pairs = 50000
mismatches = 0
submission key check = PASS
```

상세 개발 기록은
[`../../writeups/08_블록암호.md`](../../writeups/08_블록암호.md)에 있다.
제출용 PDF는 이 폴더만으로 공격 과정과 검증 근거를 확인할 수 있도록
독립적으로 작성했다.

## PDF 재생성

Noto Sans CJK KR과 D2Coding 글꼴, LuaLaTeX가 필요하다.

```bash
cd submissions/08
lualatex -interaction=nonstopmode -halt-on-error report.tex
lualatex -interaction=nonstopmode -halt-on-error report.tex
```
