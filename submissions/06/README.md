# 문제 6 제출 안내

원문이 요구한 다음 출력과 분석 문서를 제출용 파일로 정리했다.

- 정답: [`src/01_answer.txt`](src/01_answer.txt)
- 분석 문서: [`02_method.pdf`](02_method.pdf)
- 분석 문서 원본: [`02_method.tex`](02_method.tex)
- 상세 검토용 원고: [`02_method.md`](02_method.md)

공식 제출에는 `src/01_answer.txt`와 `02_method.pdf`를 사용한다. 정답
파일은 문제의 지시대로 다음 출력 `r3`를 16진수 문자열 한 줄로 기록한다.

보고서는 telemetry 누설식 추론과 `d` 복원, truncated output lift와
`r3` 예측, 계산 복잡도를 먼저 설명한다. 이어서 최신 native 구현의
shifted-square `2S+1M`, endpoint-elided batch inversion
`6m-3+I`, block-local cubic recurrence, 부분군 필터, 정확성 검증과
stationarity를 통과하지 못한 작은 성능 수치의 한계를 구분해 기록한다.

최종 구현과 보조 검증 코드는 이 폴더의 `src`에 있다.

- [`src/deep_native.cpp`](src/deep_native.cpp)
- [`src/generate_prac_schedule.py`](src/generate_prac_schedule.py)
- [`src/audit_subgroup.py`](src/audit_subgroup.py)
- [`src/6_PRNG.zip`](src/6_PRNG.zip): 원본 문제 ZIP. telemetry와 곡선
  파라미터는 이미 `deep_native.cpp`에 상수로 포함돼 있어 실행에는
  필요 없지만, 대조를 위해 함께 둔다.

`src` 디렉터리 안에서 최종 C++ 경로를 검증한다.

```bash
cd submissions/06/src
g++ -O3 -DNDEBUG -march=native -std=c++20 -fopenmp \
  deep_native.cpp -o /tmp/deep_native
/tmp/deep_native --self-test --json
/tmp/deep_native --threads 1 --schedule adaptive --json
```

보고서는 Noto Sans CJK KR과 D2Coding을 사용해 LuaLaTeX로 생성한다.

```bash
cd submissions/06
lualatex -interaction=nonstopmode -halt-on-error 02_method.tex
lualatex -interaction=nonstopmode -halt-on-error 02_method.tex
```

빌드 뒤 `02_method.log`, `02_method.aux`, `02_method.out`은 생성
중간물이며 제출 파일에 포함하지 않는다.
