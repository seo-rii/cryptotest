# 문제 4 제출 안내

- 정답: [`flag.txt`](flag.txt)
- 제출용 Python 소스: [`src/solve.py`](src/solve.py)
- 분석용 정본과 회귀 테스트: [`src/digital_forensics.py`](src/digital_forensics.py),
  [`src/test_digital_forensics.py`](src/test_digital_forensics.py)
- 방법론 문서: [`report.pdf`](report.pdf)
- 문서 원본: [`report.tex`](report.tex)

`solve.py`는 최종 공격이 한눈에 보이도록 정리한 독립 실행 extractor다.
공식 TinyLlama ZIP에서 SafeTensors header와
`model.embed_tokens.weight`의 첫 행만 스트리밍으로 읽고, 각 F32의
little-endian 첫 byte에서 low nibble을 꺼내 FLAG를 출력한다.

```bash
cd submissions/04/src
python3 solve.py /path/to/TinyLlama-1.1B-Chat-v1.0.zip \
  --verify-sha256
```

모든 F32 tensor의 blind discovery, 17GB 로그 증거 보존과 방어적인
SafeTensors 검증을 포함한 분석용 정본은
[`src/digital_forensics.py`](src/digital_forensics.py), 그 합성 회귀
테스트는 [`src/test_digital_forensics.py`](src/test_digital_forensics.py)에
분리했다. 다음 명령으로 재현한다.

```bash
cd submissions/04/src
python3 -m unittest -v test_digital_forensics
```

간결 제출본 자체의 ZIP/offset/nibble end-to-end 검증은
[`solutions/test_submission_04_readable.py`](../../solutions/test_submission_04_readable.py)에
있다.

원본 TinyLlama 모델과 서버 로그는 대용량 배포 입력이므로 이 저장소에 중복 포함하지 않는다.
