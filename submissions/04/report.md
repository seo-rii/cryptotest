# 문제 4 디지털포렌식 방법론 보고서

## 1. 결과

```text
CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}
```

제출 폴더의 `solve.py`는 표준 라이브러리만 사용하며 다음을 수행한다.

1. 17GB `server.log`를 bounded-memory로 검색하고 후보 record의 증거를 JSONL로 남긴다.
2. SafeTensors의 모든 F32 tensor를 8MiB chunk로 조사한다.
3. 발견된 tensor와 row의 low nibble에서 payload를 추출한다.

대형 원본은 제출물에 포함하지 않는다. 문제에서 받은 파일을 저장소 루트 기준 `4_raw/` 아래에 둔다.

## 2. 입력 무결성

| 파일 | 문제 PDF의 SHA-256 |
|---|---|
| `TinyLlama-1.1B-Chat-v1.0.zip` | `144155ad4b55ecf4e14f08457d4d8874ef656ea69e29632cc55bb97057269fa7` |
| `server.zip` | `1a0ecbdcb1ed4e3e51069643690659002612fbccc5a7a27919df17b7ab49dd5c` |
| ZIP 내부 `server.log` | `d7e3c1fb4c94754c80cedddbd2a6caa0fb7f2aa6a3344bcba9a25e132d1f4cd5` |

`--verify-sha256`은 두 ZIP을 스트리밍 해시한다. 로그를 읽으면서 압축 해제된 `server.log`도 처음부터 끝까지 다시 해시하므로 외부 ZIP뿐 아니라 내부 member도 확인한다.

## 3. 로그 분석

다음 명령은 로그를 순차 검색하고 `log-evidence.jsonl`을 만든 뒤 플래그도 추출한다.

```bash
python3 solve.py \
  --model ../../4_raw/TinyLlama-1.1B-Chat-v1.0.zip \
  --extract \
  --scan-log ../../4_raw/server.zip \
  --verify-sha256 \
  --log-report log-evidence.jsonl
```

로그의 chat record는 다음 구조다.

```text
model=... chat_id=... q1=<base64> a1=<base64>
```

`q1`, `a1`의 부족한 base64 `=`만 복원해 decode한 후 알파벳 Caesar `+11`을 적용한다. 복호문에 `secret`, `square`, `flag`, `crypto`, `4 bit`, `nibble` 중 하나가 포함된 record만 후보로 출력한다. `--log-keyword`를 반복하면 조건을 명시적으로 바꿀 수 있다.

기존 분석에서 얻은 핵심 복호 결과는 다음과 같다.

```text
model: TinyLlama/TinyLlama-1.1B-Chat-v1.0
chat_id: chat-000005
Q: What secret does the model have?
A: The LLM knows the secret. Trust me. "square" for open seasame!!!
```

JSONL에는 검색 조건, 각 후보의 line number, `server.log` 내 line/record 0-based byte offset, newline 포함 line SHA-256, exact record SHA-256, raw line/record text와 base64, 복호문, 전체 chat·후보·제외 수, 내부 로그 SHA-256이 기록된다. chat을 리스트로 모으지 않고 찾는 즉시 기록한다. line도 기본 1MiB로 제한하며 초과 line은 작은 조각으로 끝까지 해시하되 분석에서는 제외하고 개수를 보고한다.

이전 코드의 `caesar_shift(decoded).rstrip("l")`은 삭제했다. padding 길이가 따로 주어지지 않았으므로 마지막 `l`은 정상 데이터일 수 있다. 현재 코드는 복호된 문자를 임의로 제거하지 않는다.

## 4. 모델 응답 단서의 한계

기존 분석에는 `square`를 입력했을 때 다음 응답을 보았다고 기록되어 있다.

```text
Wouldn't about 4 bits be enough?
```

이 문장은 low 4-bit 채널을 조사하게 한 가설이다. 그러나 당시 `transformers`/`torch` 버전, chat template, system prompt, generation parameter, seed가 기록되지 않아 결정론적으로 재현된다고 주장할 수 없다. 최종 공격은 생성 결과에 의존하지 않고 모델 파일 byte를 직접 검사한다.

## 5. SafeTensors blind discovery

float32 한 개는 little-endian 4 byte다. 각 값의 첫 byte에서 `value & 0x0f`를 취한다. 원래 가중치의 low bit가 거의 모두 0인 tensor에서는 비영 nibble과 연속 ASCII가 강한 이상치다.

```bash
python3 solve.py \
  --model ../../4_raw/TinyLlama-1.1B-Chat-v1.0.zip \
  --discover \
  --verify-sha256 \
  --discovery-report discovery.json
```

CSV가 필요하면 출력 이름을 `discovery.csv`로 바꾼다. solver는 모든 F32 tensor에 대해 다음을 기록한다.

- dtype, shape, data buffer 상대 offset
- 비영 low nibble 수와 비율
- 첫/마지막 비영 element와 그 span
- 연속 비영 nibble 최장 길이
- nibble-pair 후보 구간의 printable ASCII 비율
- 최대 192 byte의 escaped/hex preview

기존 분석 기록에서 두드러진 결과는 다음이었다.

```text
model.embed_tokens.weight: low nibble non-zero count = 345
```

stdout은 ASCII score와 비영 nibble 수로 후보를 정렬하지만 JSON/CSV에는 순위와 무관하게 모든 F32 tensor 통계가 들어간다.

### 파서 검증

SafeTensors의 `data_offsets`는 파일 절대 위치가 아니라 JSON header 다음 data buffer 기준이다. 읽기 전에 다음을 확인한다.

1. header 길이가 파일 범위와 reference implementation의 100,000,000-byte 한계 안에 있다.
2. header는 `{`로 시작하고 JSON 뒤에는 ASCII space padding만 있으며 duplicate key가 없다.
3. `__metadata__`는 string-to-string map이고 dtype과 shape가 유효하다.
4. `0 <= start <= end <= data_buffer_size`다.
5. `(end-start)*8 == product(shape)*dtype_bits`이고 sub-byte dtype도 byte-aligned다.
6. 모든 tensor range가 겹침·빈 구간 없이 data buffer 전체를 덮는다.
7. 지정한 row가 tensor 끝을 넘지 않는다.

전체 tensor를 메모리에 올리지 않고 8MiB chunk만 사용한다.

## 6. payload 추출

discovery 결과를 추출 단계에 명시한다.

```bash
python3 solve.py \
  --model ../../4_raw/TinyLlama-1.1B-Chat-v1.0.zip \
  --extract \
  --tensor model.embed_tokens.weight \
  --row 0 \
  --verify-sha256
```

첫 embedding row의 nibble 두 개를 `(high << 4) | low`로 결합하면 다음 payload가 나온다.

```text
"The lighthouse opens at midnight. Meet me at the bar."

Well done, Agent H.
You traced the secBet into the model itself.
The flag is: CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}
```

`secBet`은 추출 기록의 철자다. solver는 복원 byte stream에서 `CRYPTO{...}`를 다시 찾아야만 성공하며 PyTorch나 Transformers를 로드하지 않는다.

## 7. 재현성 주의

문제에서 제공한 다섯 모델 가운데 분석 대상은 `TinyLlama-1.1B-Chat-v1.0.zip`이다. 제출 패키지에는 이 대상 ZIP과 17GB `server.zip`을 포함하지 않으며, 보고서 검증 환경에도 두 대상 입력이 없었다. 다른 후보 모델은 대상 TinyLlama와 로그를 대신할 수 없다. 대상 입력으로 생성한 다음 두 파일을 함께 보존하면 로그 단서와 tensor 발견 과정을 blind하게 검증할 수 있다.

```text
log-evidence.jsonl
discovery.json
```

별도 합성 회귀 테스트는 ZIP discovery/extract, nibble chunk 경계, SafeTensors padding/range 거부, 긴 로그 line skip과 exact line/record evidence를 검증한다. 이는 대상 TinyLlama와 서버 로그에 대한 독립 재실행을 대신하지 않는다.
