# 문제 4 디지털포렌식 방법론 보고서

## 1. 결과

```text
CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}
```

제출 코드 `solve.py`는 Python 표준 라이브러리만 사용한다. 공식 TinyLlama
ZIP을 열고 SafeTensors의 목표 embedding row만 순차적으로 읽은 뒤, F32
원시 byte의 low nibble을 결합해 위 FLAG를 콘솔에 출력한다.

```bash
python3 solve.py TinyLlama-1.1B-Chat-v1.0.zip --verify-sha256
```

## 2. 입력 무결성

문제 PDF에 적힌 SHA-256은 다음과 같다.

| 파일 | SHA-256 |
|---|---|
| `TinyLlama-1.1B-Chat-v1.0.zip` | `144155ad4b55ecf4e14f08457d4d8874ef656ea69e29632cc55bb97057269fa7` |
| `server.zip` | `1a0ecbdcb1ed4e3e51069643690659002612fbccc5a7a27919df17b7ab49dd5c` |
| ZIP 내부 `server.log` | `d7e3c1fb4c94754c80cedddbd2a6caa0fb7f2aa6a3344bcba9a25e132d1f4cd5` |

`solve.py --verify-sha256`은 모델 ZIP을 8MiB씩 읽어 첫 번째 값을 직접
확인한다. 모델 전체나 tensor 전체를 메모리에 올리지 않는다.

## 3. 로그에서 얻은 단서

17GB `server.log`를 ZIP member에서 한 줄씩 읽었다. 각 chat record의
`q1`, `a1`은 부족한 base64 `=`만 보충해 decode하고, 알파벳에 Caesar
`+11`을 적용했다. `secret`, `square`, `flag`, `crypto`, `4 bit`,
`nibble`을 포함한 복호문만 남겼다.

핵심 record는 다음과 같다.

```text
model: TinyLlama/TinyLlama-1.1B-Chat-v1.0
chat_id: chat-000005
Q: What secret does the model have?
A: The LLM knows the secret. Trust me. "square" for open seasame!!!
```

기존 구현처럼 복호문 끝의 `l`을 임의로 제거하지 않았다. padding 길이가
따로 주어지지 않았으므로 정상 문자를 삭제할 근거가 없기 때문이다.

`square`를 모델에 입력했을 때 기록된 “Wouldn't about 4 bits be enough?”
응답은 low 4-bit 채널을 조사하게 한 가설이었다. 당시 generation 환경이
보존되지 않았으므로 이 응답의 결정론적 재현을 공격의 전제로 삼지는 않았다.

## 4. 모든 F32 tensor의 blind discovery

SafeTensors의 각 F32 값은 little-endian 4 byte다. 각 값의 첫 byte에서

```text
nibble = raw_f32_bytes[0] & 0x0f
```

를 취하고, 모든 F32 tensor에 대해 비영 nibble 수와 nibble-pair ASCII
preview를 조사했다. 전체 tensor는 8MiB chunk로 순차 처리했다.

가장 두드러진 후보는 다음이었다.

```text
tensor = model.embed_tokens.weight
row    = 0
non-zero low nibbles = 345
```

이 blind discovery와 17GB 로그의 offset·hash를 남기는 범용 분석 코드는
저장소의 `solutions/solve_04_digital_forensics.py`에 보존했다. 제출용
`solve.py`에는 사람이 최종 추출식을 바로 확인할 수 있도록 확정된
tensor와 row를 읽는 경로만 남겼다.

범용 분석기는 후보를 찾는 즉시 `log-evidence.jsonl`에 1-based line
number, 압축 해제된 로그의 byte offset, line/record SHA-256, 일치한
검색어, 복호 질문·답변, raw와 손실 없는 base64를 기록한다. 마지막에는
전체 line·record·후보·decode 오류 수와 스트리밍 계산한 내부 로그
SHA-256을 남긴다. 논리 line은 기본 1MiB로 제한하고 더 긴 line은 작은
조각으로 끝까지 해시에 포함하되 정규식 분석에서는 제외하므로, 메모리는
17GB 입력 크기가 아니라 chunk와 최대 line 크기에 의해 제한된다.

## 5. payload 추출

SafeTensors의 `data_offsets`는 파일 절대 위치가 아니라 JSON header 직후
data buffer 기준이다. 제출 코드는 다음 순서로 동작한다.

1. ZIP 안의 유일한 `.safetensors` member를 연다.
2. 앞 8바이트의 little-endian header 길이와 JSON을 읽는다.
3. `model.embed_tokens.weight`가 2차원 F32 tensor인지 확인한다.
4. `data_offsets`와 shape로 첫 행 위치를 계산해 그 행만 읽는다.
5. 각 F32의 첫 byte에서 low nibble을 취한다.
6. 연속한 두 nibble을 `(high << 4) | low`로 결합한다.
7. 복원 byte열에서 `CRYPTO{...}`를 찾아 출력한다.

분석용 parser는 읽기 전에 header 길이·JSON padding·duplicate key,
dtype/shape, tensor byte 수, sub-byte 정렬, 모든 range의 hole/overlap과
row 경계를 확인한다. 정렬한 tensor range가 data buffer 전체를 빈틈과
중복 없이 정확히 덮지 않으면 fail-closed한다.

중간의 0 nibble이나 0 byte를 삭제하지 않으며 float로 변환했다가 다시
직렬화하지도 않는다. 첫 embedding row를 복원하면 다음 payload가 나온다.

```text
"The lighthouse opens at midnight. Meet me at the bar."

Well done, Agent H.
You traced the secBet into the model itself.
The flag is: CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}
```

`secBet`과 `open seasame`은 추출·로그 기록에 있던 철자를 그대로 적었다.
코드는 복원된 원시 byte열에서 `CRYPTO{...}`를 실제로 찾아야만 성공한다.

## 6. 합성 검증과 재현 범위

공식 대형 입력과 독립적으로 작은 합성 ZIP 회귀를 실행한다.

```bash
python3 -m unittest -v solutions.test_solve_04_digital_forensics
```

테스트는 discovery/extract 왕복, nibble과 chunk 경계, empty/scalar
tensor, 잘못된 header padding·duplicate key·hole·overlap·sub-byte 범위
거부, 초장문 로그의 bounded skip, offset/hash/raw evidence와 UTF-8 오류
집계를 확인한다. 이는 parser와 스트리밍 구현 검증이며 공식 payload를
다시 측정했다는 주장은 아니다.

대형 TinyLlama ZIP과 약 17GB `server.zip`은 제출물에 중복 포함하지 않는다.
현재 문서 검토 환경에도 두 공식 대상 입력이 없어 기존 분석의
`chat-000005`, 비영 nibble 수 345와 payload를 새로 측정했다고 주장하지
않는다. 공식 모델 ZIP이 주어지면 제출 코드는 archive SHA-256, tensor
경계와 FLAG를 다시 검증한다.

blind discovery부터 제3자가 검토하려면 공식 입력으로 생성한
`log-evidence.jsonl`과 모든 F32 tensor 통계를 담은 `discovery.json`도
함께 보존해야 한다.

## 참고 자료

- [SafeTensors 공식 포맷 명세](https://github.com/huggingface/safetensors#format) — header 길이, 상대 `data_offsets`, little-endian row-major data 규칙
- [TinyLlama-1.1B-Chat-v1.0 공식 모델 카드](https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0) — 로그의 모델 식별자 확인
- [Zhang et al., “TinyLlama: An Open-Source Small Language Model”](https://arxiv.org/abs/2401.02385) — 대상 모델군의 배경
