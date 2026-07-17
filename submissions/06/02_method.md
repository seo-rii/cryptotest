# 6번 Dual_EC_DRBG 분석

## 백도어 스칼라 복원

telemetry의 각 행은 다음 누설로 해석된다.

$$
\mathrm{summary}=((\mathrm{scale}\cdot d+\mathrm{offset})\bmod n)\gg20
$$

첫 행에서 제거된 하위 20비트를 모두 붙이고 `scale`의 modulo-$n$ 역원을 곱해 $d$ 후보를 만든 뒤 나머지 5행으로 걸렀다. 유일한 후보는

```text
d = 0x1c3cdd6b221806db0a7b28
```

이며 실제 곡선 연산으로 `P == d*Q`임을 확인했다.

## 상태 복원과 예측

`r0` 뒤에 가능한 하위 16비트를 붙여 x-coordinate 후보를 만들고, $y^2=x^3+ax+b$의 제곱근이 존재하는 후보를 양쪽 y 부호로 lift했다. lift한 점이 $s_1Q$라면 백도어 관계에서

$$
d(s_1Q)=s_1P,\qquad s_2=X(s_1P)
$$

이므로 내부 상태를 전진시킬 수 있다. 공개된 `r1`, `r2`를 모두 재생하는 유일한 상태는

```text
s1 = 0x638d9d631ab436da51e640
```

이다. 여기서 한 번 더 상태 갱신과 출력 truncation을 적용해 다음 값을 얻었다.

```text
r3 = 0x2443c8daf1a9d52b09
```

## 구현과 복잡도

구현은 Jacobian 좌표의 double-and-add scalar multiplication을 사용해 반복적인 affine inversion을 피한다. telemetry 단계는 최대 `6 * 2^20` modular operations를 사용한다. 생존 후보가 하나인 이 인스턴스의 추가 메모리는 `O(1)`이며, 생존 후보 목록의 이론적 최악 메모리는 `O(2^20)`이다. 출력 lift 단계는 최대 `O(2^16 * log n)` 타원곡선 group operations와 `O(1)` 메모리를 사용한다. 순수 Python으로 전체 계산은 이 환경에서 약 21~34초가 걸렸다. 코드는 `solutions/solve_06_prng.py`에 있다.
