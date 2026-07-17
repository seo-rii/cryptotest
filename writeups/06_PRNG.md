# 6. PRNG - Dual_EC_DRBG 백도어

## 문제

단순화된 Dual_EC_DRBG가 주어진다.

```text
s_{i+1} = X(s_i P)
r_i     = TMSB(X(s_{i+1} Q))
```

필드 bit 길이는 88이고, 출력은 상위 72비트만 공개된다. 즉 각 출력마다 x-coordinate의 하위 16비트가 제거된다.

추가로 `telemetry.csv`에는 공개 값 `scale`, `offset`, `summary`가 6행 들어 있다. 문제 설명은 이 로그가 같은 비밀 스칼라와 관련된 affine function의 상위 bit 요약이라고 말한다.

목표는 다음 출력 `r3`를 예측하는 것이다.

## 배경지식

### Dual_EC_DRBG 백도어

Dual_EC_DRBG의 위험한 구조는 두 점 `P`, `Q` 사이에 비밀 관계가 있을 때 발생한다.

```text
P = dQ
```

공격자가 `d`를 알면 출력 `X(sQ)` 일부에서 가능한 x-coordinate을 lift한 뒤, 점에 `d`를 곱해 내부 상태 갱신값 `sP`의 x-coordinate을 얻을 수 있다.

문제에서는 `r_i`가 `X(s_{i+1}Q)`의 상위 72비트이므로, 누락된 16비트를 전수조사하면 가능한 curve point를 복원할 수 있다.

### Telemetry leak

로그의 affine leak는 다음 형태로 해석할 수 있다.

```text
summary = ((scale * d + offset) mod n) >> 20
```

제거된 하위 20비트만 brute force하면 각 행이 같은 `d`를 만족하는지 검증할 수 있다.

## 풀이

### 1. 백도어 스칼라 `d` 복원

첫 번째 telemetry row에서 제거된 20비트를 모두 시도한다.

```text
candidate = (((summary << 20) | low) - offset) * scale^{-1} mod n
```

나머지 5개 row에 대해 같은 식이 성립하는 후보만 남긴다.

결과는 단일 후보다.

```text
d = 0x1c3cdd6b221806db0a7b28
```

검증:

```text
P == d*Q: True
```

### 2. `r0` lift

`r0`는 x-coordinate의 상위 72비트다. 하위 16비트 `low`를 붙여 다음 후보를 만든다.

```text
x = (r0 << 16) | low
```

각 `x`에 대해 curve equation

```text
y^2 = x^3 + ax + b mod p
```

의 제곱근이 존재하면 curve point 후보가 된다. 각 x에는 보통 `+y`, `-y` 두 후보가 있다.

### 3. 내부 상태 복원

후보 point가 `s1 Q`라면, `d`를 곱해 `s1 P`를 얻는다.

```text
d * (s1 Q) = s1 P
s2 = X(s1 P)
```

그 다음 `r1`, `r2`와 일치하는지 검증한다. 실제 일치한 상태:

```text
s1 = 0x638d9d631ab436da51e640
```

### 4. 다음 출력 예측

검증된 상태에서 한 번 더 갱신하고 출력 함수를 적용한다.

```text
r3 = 0x2443c8daf1a9d52b09
```

## 검증

재현 명령:

```bash
python3 solutions/solve_06_prng.py
```

출력:

```text
backdoor scalar d = 0x1c3cdd6b221806db0a7b28
P == d*Q: True
recovered state s1 = 0x638d9d631ab436da51e640
predicted r3 = 0x2443c8daf1a9d52b09
```

검증 논리:

- telemetry 6행이 모두 같은 `d`를 만족한다.
- `dQ`가 실제 `P`와 같다.
- `r0`에서 lift한 후보 중 `r1`, `r2`를 동시에 만족하는 상태가 나온다.
- 그 상태에서 계산한 다음 출력이 `r3`다.

## 참고 자료

- Dual_EC_DRBG design
- Elliptic curve scalar multiplication
- Hidden point relation backdoor
- Truncated x-coordinate state recovery
