# 문제 7 제출 및 재현 안내

문제가 요구한 big-endian 평문 바이트열과 최신 한국어 분석 보고서를 함께
포함했다.

- [`plaintext.txt`](plaintext.txt): ASCII 평문
- [`plaintext.hex`](plaintext.hex): 마지막 줄바꿈을 제외한 평문의 hexadecimal 표현
- [`report.pdf`](report.pdf): 사람이 읽는 한국어 제출 보고서
- [`report.tex`](report.tex): PDF 편집 원본

공식 답안은 다음과 같다.

```text
FLAG{d1rty_b1t_l34k_c0pp3rsm1th_m33ts_str4t3gy}
```

복원한 factor, 유출 mask, RSA 재암호화는 저장소 루트에서 다음 명령으로
독립 검증한다.

```bash
python3 solutions/solve_07_final.py
```

격자 공격은 양끝 8비트의 256개 edge 후보를 계획하고, 나머지를
155비트와 230비트의 두 변수로 완화한 뒤 `m=17,t=5`의 171차원
Herrmann--May 격자를 FLATTER로 감축한다. 감축된 보조 다항식의 modular
resultant/GCD와 CRT로 근을 복원한다. 실제 pinned 환경에서 재검증한
성공 branch는 `cid=155`다.

정답 edge 후보를 모르는 상태에서 `cid=0..255`를 숫자 순서로 모두
실행하고 각 로그·해시와 성공 후보 수를 JSON으로 남기는 진입점은
[`run_07_grouped_hm_scan.py`](../../solutions/run_07_grouped_hm_scan.py)다.
runner는 전체 blind scan을 수행할 수 있도록 작성됐지만, 현재 문서는
전체 256개 실행을 이 문서 작성 시점에 다시 완료했다고 주장하지 않는다.
runner의 계획과 실제 재검증한 `cid=155` 결과를 구분한다.

격자 감축, 짧은 행 선택과 일부 resultant/GCD를 이용한 root extraction은
heuristic이다. 얻은 factor는 `p*q == N`, mask 일치와 RSA 재암호화로
검증하므로 양성 결과는 sound하지만, `no_recovery` branch에 근이 없다는
completeness는 주장하지 않는다.

최신 상세 연구 기록은
[`07_소인수분해.md`](../../writeups/07_소인수분해.md)에 있으며,
제출 PDF에는 최종 공격, 정확성 경계, 재현 방법, 참고문헌과 실패한 전략
15종의 독립적인 판단 기록을 포함했다.
