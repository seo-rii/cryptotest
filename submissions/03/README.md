# 3번 제출 패키지

- [`report.pdf`](report.pdf): nonce 재사용 분석, GHASH key 복원, ciphertext/tag 위조, 검증 보고서
- [`report.tex`](report.tex): 제출 보고서 LaTeX 원본
- [`src/solve_tls_gcm_nonce_reuse.py`](src/solve_tls_gcm_nonce_reuse.py),
  [`src/3_네트워크보안.zip`](src/3_네트워크보안.zip): 실행 코드와 원본 문제 ZIP
- [`src/forged_record.txt`](src/forged_record.txt): Ethernet/IP/TCP header를 제외한 77바이트 TLS application data record hex

상세 writeup은 [`../../writeups/03_네트워크보안.md`](../../writeups/03_네트워크보안.md)다.

`src` 디렉터리 안에서 다음을 실행하면 pcap 파싱부터 최종 제출 파일 일치 검증까지 재현한다.

```bash
cd submissions/03/src
python3 solve_tls_gcm_nonce_reuse.py
```
