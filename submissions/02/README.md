# 문제 2 제출 패키지 안내

이 폴더에는 2번 문제의 최종 코드와 공식 제출용 PDF 보고서를 직접
포함했다.

## 제출 형식

문제 원문의 7절은 다음 두 가지를 모두 제출하도록 요구한다.

1. 최종 구현 코드
   - 제공된 테스트 벡터를 검증할 수 있어야 한다.
   - 성능 측정 코드를 포함해야 한다.
2. 분석 문서(PDF)
   - permutation 구조 분석 과정
   - `rot` 값 도출 과정
   - 구현 방법 상세 설명
   - 테스트 벡터 검증 결과
   - 성능 최적화 기법
   - 벤치마크 결과

따라서 writeup을 넣는 것은 양식 위반이 아니라 **필수 제출 조건**이다.
이 패키지에서는 [`report.pdf`](report.pdf)가 공식 제출용 writeup이다.
원문에는 파일명, 압축 구조, 정확한 파일 개수, README나 Markdown 부가
자료의 포함을 제한하는 규정이 없다. 다만 실제 접수 시스템에 별도
지침이 없다면 제출용 압축 파일은 필수 산출물인 `contest.c`와
`report.pdf`를 중심으로 구성하는 것이 가장 안전하다. Markdown 문서는
PDF를 대신할 수 없다.

저장소의 더 자세한 한국어 풀이와 전체 최적화 기록은
[`../../writeups/02_암호구현.md`](../../writeups/02_암호구현.md)에 있다.
같은 내용을 두 위치에 복사해 서로 달라지는 일을 피하기 위해, 이
README에서는 해당 단일 원본을 직접 연결한다.

## 파일 구성

- [`contest.c`](contest.c): 최종 scalar BMI2 구현과 문제에서 제공한 검증·성능 측정 harness
- [`report.pdf`](report.pdf): 원문이 요구한 여섯 항목을 모두 담은 공식 제출 보고서
- [`report.tex`](report.tex): PDF를 다시 만들 수 있는 LaTeX 원본
- [`run_contest.sh`](run_contest.sh): 원본 ZIP의 공식 벡터로 score build를 재현하는 실행 스크립트
- [`README.md`](README.md): 제출 형식과 재현 방법 안내

`report.tex`, `run_contest.sh`, `README.md`는 저장소에서 검토와 재현을
돕는 부가 파일이다. 공식 필수 제출물은 코드와 PDF다.

## 최종 복원 결과

한 라운드의 연산 순서와 rotation은 다음과 같다.

```text
rotate -> XOR -> 32바이트 전체 역순 -> add
rot = {43, 7, 29, 14}
```

최종 코드는 한 라운드의 전체 byte reversal을 네 번의 64비트
`BSWAP`으로 바꾸고, 두 라운드 뒤 word reversal이 상쇄되는 성질을
이용해 네 개의 독립 dependency chain을 만든다. 이 2-round block을 열
번 전개하고 BMI2의 non-destructive rotate를 사용한다.

현재 제출 기준 구현은 실제 평가 장비인 Intel Core Ultra 7 255H에서
확정 측정을 하기 전까지 scalar BMI2 버전으로 유지한다. 최우선 A/B
후보는 lane-wise AVX2이고, counted block-2/3/5가 그다음 frontend
후보다. 이 후보들은 정답성과 정적 감사를 통과했지만 개발용 AMD VM의
CPU affinity에 따라 scalar와의 우열이 뒤집혔다. 서로 다른 시점의 두
세션에서 P/E/LP-E 코어 모두에 일관된 우세가 있어야만 제출 코드를
교체한다. 후보와 실패 전략의 전체 기록은
[`../../writeups/02_암호구현.md`](../../writeups/02_암호구현.md)와
[`../../solutions/02_optimization/deep_review_02.md`](../../solutions/02_optimization/deep_review_02.md)에
정리했다.

문서에 적힌 정확한 mnemonic 개수와 byte 수는 각 표가 명시한 compiler
version으로 만든 binary의 감사 기록이다. GCC 13.3.0과 다른 compiler는
동치인 C도 다르게 배치할 수 있으므로, 이 수치를 정답성 조건이나
255H에서의 성능 순위로 해석하지 않는다.

## 실행

저장소 루트에서 다음 명령을 실행한다.

```bash
./submissions/02/run_contest.sh
```

스크립트는 추적 중인 원본 문제 ZIP에서 두 공식 벡터를 임시
디렉터리로 꺼내고, 문제에서 허용한 추가 최적화 플래그로 컴파일한 뒤
두 검증과 성능 측정을 실행한다. 실행이 끝나면 벡터와 binary를 모두
지우므로 저장소에 생성 파일을 남기지 않는다.

score build는 다음과 같다.

```bash
gcc -O3 -Wall -Wextra -mbmi2 -finline-limit=2000 \
  -o contest submissions/02/contest.c
```

추가 플래그가 없는 문제 원문의 기본 명령으로도 컴파일된다.

```bash
gcc -O3 -Wall -Wextra -o contest submissions/02/contest.c
```

직접 실행할 때는 `testvector.txt`와 `testvector_20round.txt`가 현재
작업 디렉터리에 있어야 한다.

## 검증과 벤치마크

최종 구현은 다음 검증을 통과했다.

- 공식 1-round 벡터 1,000개
- 공식 20-round 벡터
- 독립 reference를 사용한 임의 상태·상수 100,000개
- 1-round와 20-round differential test
- 측정 loop의 반복 횟수, 최종 상태, 출력 형식과 assembly 감사

동일한 source를 기본 build와 score build로 비교하는 반복 벤치마크는
다음처럼 재현한다.

```bash
python3 solutions/benchmark_02_permutation.py \
  --case default=submissions/02/contest.c \
  --case inline=submissions/02/contest.c \
  --baseline default \
  --case-cflag inline=-mbmi2 \
  --case-cflag inline=-finline-limit=2000 \
  --audit-mode default=default-call-allowed \
  --audit-mode inline=full-inline-320 \
  --cpu auto \
  --iterations 3000000 \
  --warmups 3 \
  --samples 21 \
  --random-cases 100000 \
  --json /tmp/challenge02-inline.json
```

도구는 correctness gate를 먼저 수행하고, 별도 process warm-up을
버린 뒤 후보 실행 순서를 교차해 여러 표본을 수집한다. 중앙값, MAD,
percentile, bootstrap 신뢰구간과 paired speedup을 JSON에 함께 기록한다.

최신 11차 상태의 여섯 후보를 같은 campaign에서 비교하는 명령은 다음과
같다. 새 측정마다 `--campaign-id`와 출력 경로를 바꾸고, 두 번째
affinity에서는 `--cpu 1`을 `--cpu 3`으로 바꾼다.

```bash
python3 solutions/benchmark_02_permutation.py \
  --case scalar=submissions/02/contest.c \
  --case full549=solutions/02_optimization/contest_simd_avx2_inline_asm.c \
  --case old_block2=solutions/02_optimization/contest_simd_avx2_pair_block2.c \
  --case block2_counted=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --case block3_tail1=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --case block5_counted=solutions/02_optimization/contest_simd_avx2_pair_block3_tail1.c \
  --baseline full549 \
  --case-cflag scalar=-mbmi2 \
  --case-cflag scalar=-finline-limit=2000 \
  --case-cflag full549=-mavx2 \
  --case-cflag full549=-DCH2_SIMD_INLINE \
  --case-cflag full549=-finline-limit=2000 \
  --case-cflag old_block2=-mavx2 \
  --case-cflag old_block2=-DCH2_SIMD_INLINE \
  --case-cflag old_block2=-finline-limit=2000 \
  --case-cflag block2_counted=-mavx2 \
  --case-cflag block2_counted=-DCH2_SIMD_INLINE \
  --case-cflag block2_counted=-DCH2_TENTH_BLOCK2 \
  --case-cflag block2_counted=-finline-limit=2000 \
  --case-cflag block3_tail1=-mavx2 \
  --case-cflag block3_tail1=-DCH2_SIMD_INLINE \
  --case-cflag block3_tail1=-finline-limit=2000 \
  --case-cflag block5_counted=-mavx2 \
  --case-cflag block5_counted=-DCH2_SIMD_INLINE \
  --case-cflag block5_counted=-DCH2_TENTH_BLOCK5 \
  --case-cflag block5_counted=-finline-limit=2000 \
  --audit-mode scalar=full-inline-320 \
  --audit-mode full549=avx2-inline-lanewise \
  --audit-mode old_block2=avx2-inline-pair-block2 \
  --audit-mode block2_counted=avx2-inline-pair-block2-counted \
  --audit-mode block3_tail1=avx2-inline-pair-block3-tail1 \
  --audit-mode block5_counted=avx2-inline-pair-block5-counted \
  --cpu 1 \
  --iterations 3000000 \
  --warmups 6 \
  --samples 24 \
  --random-cases 100000 \
  --campaign-id ch2-stationarity-cpu1-rerun-a \
  --json /tmp/challenge02-stationarity-cpu1.json
```

보존한 raw 결과는
[`stationarity_gate_timing_02_cpu1.json`](../../solutions/02_optimization/stationarity_gate_timing_02_cpu1.json)과
[`stationarity_gate_timing_02_cpu3.json`](../../solutions/02_optimization/stationarity_gate_timing_02_cpu3.json)이다.
CPU 1의 AVX2 비교는 모두 안정 판정을 받았지만 paired median이
`0.999624--1.002591x`이고 모든 95% 구간이 1을 포함했다. CPU 3은
full549의 absolute spread가 `8.2770%`라 campaign 전체가 진단용으로
분류됐다. 따라서 최신 측정도 scalar incumbent를 바꾸지 않는다.

실제 255H에서는
[`../../solutions/02_optimization/autotune_02_255h.py`](../../solutions/02_optimization/autotune_02_255h.py)의
`probe -> screen -> confirm -> decide` 절차로 P/E/LP-E 코어를 구분해 두
독립 세션에서 재측정해야 한다. 그 절차가 한 후보를 일관되게 선택하지
않으면 이 폴더의 scalar 코드를 그대로 제출한다.

## 제출 전 확인

```bash
./submissions/02/run_contest.sh
pdfinfo submissions/02/report.pdf
git status --short submissions/02
```

마지막으로 실제 접수 페이지에 원문 ZIP과 다른 파일명·압축 구조
지침이 표시된다면 그 지침을 우선한다.
