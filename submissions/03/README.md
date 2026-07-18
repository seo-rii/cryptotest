# 3번 제출 패키지

- [`forged_record.txt`](forged_record.txt): Ethernet/IP/TCP header를 제외한 77바이트 TLS application data record hex
- [`report.pdf`](report.pdf): nonce 재사용 분석, GHASH key 복원, ciphertext/tag 위조, 검증 보고서
- [`report.tex`](report.tex): 제출 보고서 LaTeX 원본

상세 writeup은 [`../../writeups/03_네트워크보안.md`](../../writeups/03_네트워크보안.md), 재현 solver는 [`../../solutions/solve_03_tls_gcm_nonce_reuse.py`](../../solutions/solve_03_tls_gcm_nonce_reuse.py)다.

저장소 루트에서 다음을 실행하면 pcap 파싱부터 최종 제출 파일 일치 검증까지 재현한다.

```bash
python3 solutions/solve_03_tls_gcm_nonce_reuse.py
```
