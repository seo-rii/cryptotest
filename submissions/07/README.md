# 문제 7 제출 및 재현 안내

문제가 요구한 big-endian 평문 바이트열은 두 형식으로 포함했다.

- [`plaintext.txt`](plaintext.txt): ASCII 평문
- [`plaintext.hex`](plaintext.hex): 텍스트 파일의 마지막 줄바꿈을 제외한 평문의 hexadecimal 표현

복원한 factor, 유출 mask, RSA 재암호화는 다음 명령으로 독립 검증한다.

```bash
python3 solutions/solve_07_final.py
```

정답 edge 후보를 모르는 상태에서 `cid=0..255`를 실행하고 각 로그·해시와
성공 후보 수를 JSON으로 남기는 진입점은
[`run_07_grouped_hm_scan.py`](../../solutions/run_07_grouped_hm_scan.py)다.
공격의 격자 구성, heuristic root extraction의 soundness/completeness
경계, 고정한 FLATTER revision과 실행 명령은
[`07_소인수분해.md`](../../writeups/07_소인수분해.md)에 정리했다.
