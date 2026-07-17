# 5번 비밀 다항식 복원 방법

암호문은 $R_q=\mathbb Z_q[x]/(x^{64}+1)$에서
$c_1=c_0s+te+m\pmod q$를 만족한다. 두 연속 날짜의 암호문을 빼면

$$
\Delta c_1=\Delta c_0s+t\Delta e+\Delta m\pmod q
$$

가 된다. 주어진 모듈러스에는 결정적인 취약점이 있다.

$$
\gcd(q,t)=257
$$

257은 $q$와 $t$를 모두 나누므로 위 식을 $\mathbb F_{257}$로 줄이면 noise가 사라져

$$
\Delta c_1=\Delta c_0s+\Delta m\pmod {257}
$$

를 얻는다. 두 평문의 `State`와 중간 0 padding은 같으므로 $\Delta m$의 앞 56개 계수는 0이고, 마지막 8개 계수만 `YYYYMMDD`의 하루 증가분이다. 2025~2027년의 유효 날짜에서 서로 다른 하루 증가 digit pattern을 열거했다.

각 pattern마다 $\Delta c_0$와의 negacyclic convolution을 나타내는 $64\times64$ 행렬 $A$를 만들고 $As=\Delta c_1-\Delta m$을 $\mathbb F_{257}$에서 Gauss 소거했다. 정답 pattern `[0,0,0,0,0,0,0,1]`에서는 rank가 63이므로 해가 1차원 affine space이다. 그 257개 해를 순회해 모든 계수가 $\{256,0,1\}$인 유일한 해를 찾고, 256을 -1로 해석하여 ternary secret을 복원했다.

복원한 $s$로 각 날의 $c_1-c_0s$를 centered lift한 뒤 modulo $t$로 줄였다. 두 평문에서 앞 56개 계수가 동일하고 날짜만 `20260410`에서 `20260411`로 변했다. 고정 보고문은 다음과 같다.

```text
BGV DAILY STATUS CORE-A LINK OK TEMP NORMAL POWER STABLE
```

두 날의 error 계수 범위도 모두 `1..4`여서 암호화 식과 일치한다. 비밀 다항식과 State 계수는 각각 `02_secret_s.txt`, `03_state.txt`에 $x^0$부터 차수 오름차순으로 기록했다.
