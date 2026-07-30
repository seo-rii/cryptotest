# 5번 비밀 다항식 및 고정 보고문 복원

암호문은 $R_q=\mathbb Z_q[x]/(x^{64}+1)$에서
$c_1=c_0s+te+m\pmod q$를 만족한다. 두 연속 날짜의 암호문을 빼면

$$
\Delta c_1=\Delta c_0s+t\Delta e+\Delta m\pmod q
$$

가 된다. 주어진 모듈러스에는 결정적인 취약점이 있다.

$$
\gcd(q,t)=257
$$

257은 $q$와 $t$를 모두 나누므로 위 식을 $\mathbb F_{257}$로 줄이면
noise가 사라져

$$
\Delta c_1=\Delta c_0s+\Delta m\pmod {257}
$$

를 얻는다. 두 평문의 `State`와 중간 0 padding은 같으므로
$\Delta m$의 앞 56개 계수는 0이고, 마지막 8개만 `YYYYMMDD`의 다음 날
digit 차분이다. 숨은 연도 범위를 가정하지 않고 네 자리 Gregorian 연도
`0001..9999`의 모든 전이를 포함했다. 같은 달의 `01->02` … `30->31`과
각 월말 전이를 전부 생성해 중복 제거하면 서로 다른 modulo-257 pattern은
11개다.

각 pattern마다 $\Delta c_0$와의 negacyclic convolution을 나타내는
$64\times64$ 행렬 $A$를 만들고
$As=\Delta c_1-\Delta m$을 $\mathbb F_{257}$에서 Gauss 소거했다.

| 검증량 | 결과 |
|---|---:|
| 날짜 delta pattern | 11 |
| 정답 선형계 rank / nullity | 63 / 1 |
| affine 해 전수조사 | 257 |
| ternary 대수 후보 | 1 |
| 날짜·State·noise 검증 통과 | 1 |

정답 pattern `[0,0,0,0,0,0,0,1]`의 257개 affine 해를 모두 순회해
계수가 $\{256,0,1\}$인 후보를 전부 수집하고, 256을 -1로 해석했다.
첫 후보에서 멈추지 않고 모든 후보를 두 ciphertext에 다시 적용해 다음을
확인했다.

- 날짜가 유효한 ASCII `YYYYMMDD`이고 `day2 = day1 + 1 day`
- 두 `State || 00...00` prefix가 같음
- 뒤쪽 NUL padding만 제거한 State가 printable ASCII
- 두 날 모두 암호화식을 재구성하며 error range가 `1..4`

복원 날짜는 `20260410`, `20260411`이고 실제 padding 길이는 0이다.
고정 보고문은 다음과 같다.

```text
BGV DAILY STATUS CORE-A LINK OK TEMP NORMAL POWER STABLE
```

비밀 다항식과 padding을 제외한 State 계수는 각각 `02_secret_s.txt`,
`03_state.txt`에 $x^0$부터 차수 오름차순으로 기록했다.

## 파일 구성

- [`report.pdf`](report.pdf): 최종 제출용 방법론 보고서
- [`report.tex`](report.tex): PDF 생성 원본 LaTeX
- [`src.zip`](src.zip): 재현용 코드가 압축된 ZIP 파일
- `src/`: 재현 및 제출용 디렉터리
  - [`src/solve_bgv.py`](src/solve_bgv.py): 복원 및 무결성 검증 solver 스크립트
  - `src/5_동형암호.zip`: 문제 데이터 ZIP 파일
  - [`src/02_secret_s.txt`](src/02_secret_s.txt): 복원된 비밀 다항식 계수 파일
  - [`src/03_state.txt`](src/03_state.txt): 복원된 고정 보고문 State 계수 파일

## 실행 방법

`src/` 디렉터리 내부로 이동한 뒤 Python으로 solver를 실행하여 모든 복원 과정과 무결성 검증을 수행할 수 있습니다.

```bash
cd submissions/05/src
python3 solve_bgv.py
```

