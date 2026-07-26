# 2026 암호분석경진대회 전체 정리

> 최종 갱신: 2026-07-23

이 문서는 `cryptotest`의 8개 문제에 대한 현재 완료 상태, 핵심 결과,
재현 진입점과 검증 수준을 한곳에 모은 전체 색인이다. 문제별 수식,
실험 과정, 실패 전략과 참고 문헌은 각 상세 writeup에 둔다.

## 전체 진행상황

| 번호 | 주제 | 상태 | 최종 결과 | 상세 writeup |
|---:|---|---|---|---|
| 1 | 고전 암호와 분류 | 완료 | Caesar shift `6`, Vigenère key `KLVOJ`, 재현 가능한 분류 모델과 식별 불가능성 분석 | [01_암호분석](01_암호분석.md) |
| 2 | 256비트 permutation 구현 | scalar incumbent 완료·11차 정상성 gate/범위 제한 ISA 합성까지 로컬 탐색 종료·255H 실측 미정 | `rot={43,7,29,14}`, 2-round scalar full-unroll, 122-insn/549B AVX2와 122B/29-static counted block2 | [02_암호구현](02_암호구현.md) |
| 3 | TLS 1.2 AES-GCM 위조 | 완료 | nonce 재사용으로 `H`와 `E_K(J0)`를 복원하고 유효한 급여 변경 record 생성 | [03_네트워크보안](03_네트워크보안.md) |
| 4 | LLM weight steganography | 완료 | `CRYPTO{G00D_J0B!_y0u_f0und_7h3_h1dd3n_s3cr37_1n_LLM}` 추출 | [04_디지털포렌식](04_디지털포렌식.md) |
| 5 | textbook-BGV | 완료 | ternary secret 64계수, 날짜 `20260410→20260411`, 고정 `State` 복원 | [05_동형암호](05_동형암호.md) |
| 6 | Dual_EC_DRBG | 풀이·최적화 완료 | `d`와 `r3` 복원; shifted scan·Hamburg·Jacobi와 2T adaptive scheduler 채택 | [06_PRNG](06_PRNG.md) |
| 7 | RSA partial key exposure | 완료 | `p`, `q`와 `FLAG{d1rty_b1t_l34k_c0pp3rsm1th_m33ts_str4t3gy}` 복원 | [07_소인수분해](07_소인수분해.md) |
| 8 | 변형 AES 7라운드 | 완료 | master key `2923be84e16cd6ae529049f1f1bbe9eb` 복원 | [08_블록암호](08_블록암호.md) |

8문제의 요구 결과를 모두 정리했다. 1번에서 관측 암호문만으로 유일하게
결정할 수 없는 숨은 생성기 label은 임의 답을 만들지 않고 그 식별
불가능성을 증명했으며, 나머지는 요구 값을 복원했다. 원문이 별도 형식을
요구한 답안, 코드, 계수, TLS record와 PDF는
[제출 파일 색인](../submissions/README.md)에 문제별로 정리되어 있다.

## 완료와 성능 개선의 구분

2번과 6번은 정답 복원만으로 끝나지 않고 실행 시간이 점수나 실용성에
영향을 주는 문제다. 두 문제 모두 정확성 조건은 완료됐으며, 성능
결과는 다음처럼 별도로 관리한다.

### 2번

- 20라운드를 두 라운드씩 합성하면 word reversal이 상쇄되어 네 개의
  독립 scalar chain이 된다.
- 최종 source는 ten-pair full-unroll을 사용하며, 기본 build에서는 local
  BMI2 noinline helper, score build에서는 timing loop까지 adaptive inline한다.
- 제공 1-round vector 1,000개, 20-round vector, 무작위 differential
  100,000개를 통과한 후보만 측정한다.
- 동일 최종 source를 기본 flag와 `-mbmi2 -finline-limit=2000`으로 비교한
  3,000,000-iteration, 3-warmup, 21-sample 캠페인은 두 CPU affinity에서
  paired `1.116x`, `1.118x`였다. bootstrap 95% interval도 각각
  `1.110--1.143x`, `1.095--1.140x`였다.
- `-mbmi2`만으로는 public-to-`main` call이 남아 `0.999x`였고, outer inline
  단계에서 `1.124x`가 됐다. digest로 고정한 공식 GCC 13.3.0 image에서도
  inline limit 700/2000은 complete binary까지 같았고, 실제 timing loop는
  1,216 bytes/322 instructions, call·stack·memory operand 0으로 확인됐다.
- full-unroll은 같은 fast flag 아래 pair loop와 `unroll5_bmi2`보다 각각
  약 2.6%, 3.5% 빨랐다. 켤레 SIMD, table, BSWAP/XOR 재배열과 수동 scheduling은
  검증된 실패 전략으로 상세 writeup에 기록했다.
- 현재 schema-5 측정 도구는 후보를 직접 링크해 무작위 상태·ADD/XOR 상수 100,000건의
  1/20라운드를 먼저 검증하고, warm-up 직전 실제 측정 binary 자체를 감사한다.
  score loop의 320개 core 연산과 call/stack/memory 부재, codegen hash와 정렬을
  같은 JSON에 남긴다. 독립 oracle가 계산한 반복 후 256-bit state와 선언한
  반복 횟수를 semantic preflight, 모든 warm-up·sample process에서도 맞춰야
  한다. current protocol은 total/average 일치와 total-derived ns, child-CPU
  coverage, fresh nonce에서 유도한 alternate iteration challenge까지 요구한다.
  이는 재현한 우회에 대한 방어선이지 모든 악성 C에 대한 암호학적 증명은 아니다.
  9·10차 schema-5 JSON은 현재 stationarity field/protocol hash 변경 전 역사
  자료이고, schema 2--4 raw JSON은 repeated-call 의미 보증도 없는 더 오래된
  기록으로 구분한다.
- 292-byte 작은 portable ROL은 `0.985x (0.958--1.002)`였고, XOR/ADD 저비트
  완전탐색과 120개 GCC/link 조합에서도 채택할 승자가 없었다.
  GCC 13.3에서 `-mtune=alderlake`는 실제 hot-loop schedule을 바꿨고 근사
  LLVM-MCA 모델은 generic 대비 약 1.012x를 예측했다. Alder tune과 IRA priority를
  합친 변형은 1,210-byte loop와 약 1.021x 추가 정적 예측을 얻었지만 AMD의 두
  확인 캠페인은 `1.011x (1.001--1.015)`와 `1.008x (0.998--1.025)`로 엇갈렸다.
  둘 다 실제 255H에서만 판정할 A/B 후보다.
- XOR을 BSWAP 뒤 또는 rotate 앞으로 옮긴 정확한 두 표현은 당시 schema 4의 두
  affinity 재측정에서 각각 `0.959--0.963x`, `0.960--0.965x`였고 네 CI가 모두
  1 아래였다. 상수를 memory operand로 강제하면 hot loop에 160개 memory
  operand가 생기며 두 재측정은 `0.979x`, `0.988x`로 개선되지 않았다.
  실제 상수의 모든 pre/post 변환값도 sign-extended imm32에 들어가지 않아
  명령 한 개를 줄일 수 없었다.
- 5차 탐색은 독립 chain 문장의 24개 순열과 scheduler/layout flag
  106개를 exact GCC 13.3으로 전수 검사했다. `2,1,0,3` source 순서는
  generic/Alder LLVM-MCA 근사를 `125.06/123.62 -> 121.06` cycles로
  줄였고, Alder+IRA에 `-fselective-scheduling2` 또는
  `-fno-schedule-insns2`를 더한 stream은 `120.06/120.07` cycles였다.
  109/109 build audit와 shortlist의 임의 state/상수 100,000건이 통과했지만,
  모델은 Lion Cove/Skymont 실측이 아니고 AMD 보조 결과도 엇갈렸다.
  따라서 새 255H A/B 후보로만 보존하고 incumbent는 유지했다.
- 6차 탐색에서는 두 라운드 뒤 생기는 네 독립 chain을 YMM 네 lane에 놓아
  exact GCC 13.3 loop를 122 instructions/579 bytes/hot memory 0으로 줄였다.
  warm-up 6회 뒤 32 samples의 AMD CPU 1/3에서는 scalar 대비
  `1.275x (1.260--1.292)`, `1.248x (1.222--1.269)`였지만 CPU 2에서는
  `0.940x (0.923--0.950)`로 순위가 뒤집혔다. 따라서 AVX2는 최우선 255H
  후보일 뿐 incumbent는 아니다. 부분 pair loop의 첫 `1.035x`도 더 큰
  확인에서 `1.0004x (0.9855--1.0176)`로 사라졌다. Z3/완전탐색으로 제한된
  rotate/XOR/BSWAP/ADD grammar의 연산 삭제 32개가 모두 UNSAT임도 기록했다.
- 7차 탐색은 YMM의 긴 dependency chain을 두 XMM 그룹으로 나눈 네 구현을
  만들었지만 242--288 instructions, 30--50 hot memory와 현 YMM 대비 최소
  1.36배 정적 cycle로 모두 기각했다. exact GCC 13.3/Clang 21의 113-build
  codegen matrix도 새 GCC source 승자를 만들지 못했다. OR-to-XOR rotate merge는
  두 compiler에서 100,000-case 검증을 통과했지만 instruction/byte/model cycle을
  줄이지 못했다.
- CPU 2 역전 진단은 page-aligned same-process AB/BA와 wall/thread/TSC 세 timer로
  재현했다. migration은 없었고 세 timer 비는 0.000003 이내로 같았다. CPU
  1/2/3의 exact binary가 같은데 AVX2 median 범위는 0.78%, scalar는 45.89%여서
  공유 VM의 scalar 처리율 변동으로 국소화했다. counter가 없어 SMT/frequency
  인과는 단정하지 않았으며 이 결과는 255H 선택에 쓰지 않는다.
- 8차 register-allocation 탐색은 value만 `ymm0`에 고정하고 rotate scratch를
  하나로 줄인 source를 찾았다. Exact GCC 13.3 loop는 122 instructions/hot
  memory 0을 유지하면서 579B에서 569B가 됐고, 공식 vector와 임의 state/상수
  100,000건을 통과했다. 그러나 CPU 1/3의 6-warm-up, 32-sample campaign은
  각각 `0.999x (0.998--1.002)`, `1.000x (0.998--1.002)`으로 동률이었다.
- phase-staggered XMM은 word-reversal orbit 안에 한 단계 어긋난 두 값을 넣어
  immediate rotate를 공유한다. 정확하고 memory-free지만 257 instructions/
  1,253B로 커졌고, 유리했던 Zen 2 정적 proxy와 달리 CPU 1/3에서
  `0.758x/0.756x`였다. 즉 처리량은 약 24% 낮고 같은 작업 시간은 약 32%
  길었다. 정적 scheduling model을 반드시 반복 실측으로 반증해야 한다는 사례로
  남겼다.
- 신규 GCC AVX flag 63개와 기준 2개는 normalized stream 두 종류로 수렴했지만
  `(stream hash, loop-start mod 64)` 기준으로는 generic 5개와 Alder 3개의 배치
  클래스가 남았다. 8개 대표 모두 임의 100,000건을 통과했고 nonbaseline 7개를
  255H target-only 후보에 추가했다.
- Intel 공식 instruction 표의 AVX2 chain은 조건부 latency path 100 cycles지만
  Skymont package는 Xeon 6 E-core 범위이고 scalar exact `RORX64`/`LEA` 행과
  Lion Cove 표도 없다. Arrow Lake PerfMon은 LP-E를 Crestmont로, 255H 전용 ECI는
  두 LP-E를 추가 Skymont core로 불러 서로 충돌하므로 공식 자료만으로 winner를
  선택하지 않았다.
- 9차에서는 timing loop만 반복을 절반으로 줄인 악의적 후보가 공개
  함수 검증과 assembly audit를 통과하면서 거짓 `2.253x`를 내는 회귀를
  구성했다. schema 5가 모든 timing process의 최종 상태를 검증하면서 이
  공백을 닫았다.
- `VPOR`/`VPXOR`/`VPADDQ`의 교환 피연산자 순서를 VEX encoding에
  맞춰 배치해 AVX2 loop를 122 instructions/0 hot memory 그대로
  **569B에서 549B**로 줄였다. 34개 exact-GCC13.3 flag/link case가 공식
  vector와 무작위 상태·상수 100,000건을 통과했고 5 stream/9
  stream-alignment class로 수렴했다. `use_incdec`는 548B target-only 대조군이다.
- 완전 언롤과 작은 loop 사이의 block1/2/5를 비교했다. block2는 정적
  timing region을 **136B/30 instructions**로 줄이면서 hot memory 0과
  `100.03/180.03` Alder/Zen 2 critical-path proxy를 유지했지만 padding 제외
  modeled 명령은 122에서 133으로(정렬 NOP 포함 134) 늘었다. scalar
  stage-major chain 순서 576개는 tuned
  120.06-cycle proxy보다 엄격히 낮은 경우가 없었다.
- old 569B stream 대비 549B, 548B, align32, block2를 CPU 1/3에서 각
  3,000,000회·6 warm-up·32 samples로 schema-5 재측정했다. 새 후보의
  모든 paired bootstrap CI가 1을 포함해, code footprint 감소는 확인했지만
  현 AMD host의 처리량 승자로는 선택하지 않았다. scalar incumbent는 유지한다.
- 10차는 열 pair의 quotient/remainder 분해를 block 크기 1--10까지 생성했다.
  exact GCC 13.3·공식 vector·임의 state/상수 100,000건을 통과한 Pareto point는
  counted block 2의 **122B/29-static/133-dynamic**, block 3+tail 1의
  **238B/53/129**, counted block 5의 **292B/65/127**이다. 모두 hot memory 0과
  `100.03/180.03` Alder/Zen-2 dependency proxy를 유지한다. x86 `LOOP`는 더
  짧은 encoding에도 Intel proxy µop/throughput이 나빠 target 전에는 기각했다.
- high state를 VEX.vvvv/destination에 두고 low scratch를 ModRM에 두는 세
  register 배치는 549B baseline과 동률이었다. `VPADDQ` rotate merge도
  byte/instruction/model tie이고, right-branch XOR은 Intel proxy는 그대로인 채
  Zen-2 proxy만 `180.03 -> 160.03`이었다. 강제 same-register `ROL`은
  322 instructions/1,052B로 작지만 Intel proxy가 `RORX`의
  `121.06 cycles/402 µops`에서 `138.13/482`로 악화됐다. `SHLD`는 serial
  latency proxy `3.03`으로 `RORX`의 `1.03`보다 길어 full expansion 전에
  기각했다. 모두 255H 실측이 아닌 정적 선별 결과다.
- current protocol의 적대적 회귀는 timer 뒤에서 계산을 완성하는 후보를
  child-CPU coverage로, 알려진 최종 상태를 하드코딩한 후보를 fresh
  nonce/campaign/source-hash 기반 alternate iteration으로, 출력 average만
  절반으로 쓰는 후보를 total/average 일치와 total-derived ns로 거절한다.
- counted block 2/3/5를 full549와 CPU 1/3에서 3,000,000회·6 warm-up·32
  samples로 측정했다. CPU 1 block 3은 `1.005x (1.001--1.014)`였지만 campaign
  도중 host 부하가 크게 변했고, CPU 3의 `1.001x (0.997--1.004)`에서
  재현되지 않았으며 1% 승격 기준에도 못 미쳤다. 나머지 새 후보 interval은
  1을 포함했다. scalar incumbent를 유지하고 세 후보는 255H target-only로 둔다.
- 현 schema 5는 chronological sample을 사전에 정한 네 block으로 나눈다. 최소
  16 samples, `N`-case screen의 `4*N` 배수와 2-case confirmation의 최소 40·
  8의 배수를 요구한다. absolute block-median spread 5%, paired-effect spread
  2%, `0.995` 미만과 `1.005` 초과의 material sign reversal을 넘으면 해당
  pair만 diagnostic-only다. autotuner가 raw에서 record를 독립 재계산한다.
  [Barrett et al.](https://arxiv.org/abs/1602.00602)의 changepoint 동기와
  [Kalibera/Jones](https://doi.org/10.1145/2464157.2464160)의 반복·effect-size
  설계를 참고했지만 PELT나 전체 hierarchical model의 재현은 아니다.
- 새 24-sample CPU 1 record는 full549 absolute spread `2.3157%`와 네 AVX
  pair를 eligible로 판정했지만 AVX paired median은
  `0.999624--1.002591x`이고 모든 CI가 1을 포함했다. scalar control만 absolute
  `9.0577%`로 diagnostic-only였다. CPU 3은 full549 absolute `8.2770%`,
  AVX pair-effect spread 최소 `2.2451%`로 campaign 전체가 diagnostic-only다.
  승격은 없고 scalar incumbent를 유지한다.
- 11차 ISA 합성은 qword shift, arbitrary word-local byte shuffle와
  XOR/OR/carry-free ADD로 이뤄진 세 명령 grammar에서 one-instruction와
  parallel `two unary + combine`을 전수하고, 나머지 DAG topology는
  bit-loss/bijectivity/projection 구조 논증으로 제외했다. 이는 범위 제한
  UNSAT이지 전역 x86 하한이 아니다. exact split-shuffle 세 대조군은 공식·100,000
  random 1/20-round 검증을 통과했지만 122 instructions/549B를
  142 instructions/669--689B로 키웠고, modular ADD carry가 round-boundary
  shuffle cancellation을 막았다.
- LLVM 19.1.7의 `arrowlake`는
  [`X86.td`](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/llvm/lib/Target/X86/X86.td)에서
  `AlderlakePModel`을 쓰며 테스트한
  여섯 LLVM 19 label은 각 stream에서 같은 metric을 냈다. 이는 255H 모델
  증거가 아니다. [`llvm-mca` guide](https://llvm.org/docs/CommandGuide/llvm-mca.html)의
  정적 모델 범위로만 해석한다. 문서화한 로컬 algorithmic/ISA, codegen, cache/frontend,
  micro 탐색 범위는 닫혔고 남은 것은 실제 255H의
  `probe -> screen ->` 독립 `confirm` 두 번 `-> decide`뿐이다.
- `autotune_02_255h.py`는 pinned CPUID와 Linux topology로 P/E/LP-E를 보수적으로
  분류하고 `probe → screen → confirm → decide`를 실행한다. 두 session·core type별
  두 physical core·correctness/assembly gate가 갖춰지지 않으면 winner 대신
  `provisional` 또는 incumbent 유지로 끝낸다. 복수 후보가 동시에 기준을 넘겨도
  임의 선택하지 않고 직접 head-to-head를 요구한다. runner/audit/oracle/verifier,
  공식 ZIP, Python, `objdump`/`size`까지 한 protocol fingerprint로 고정해 코드가
  바뀐 세션끼리 섞이지 않게 했다. 128-bit run id와 canonical evidence/raw-sample
  hash는 공백만 바꾼 동일 측정 재사용도 막는다. verifier reference TU는 후보
  flag와 분리하고 출력 count/seed/round/PASS를 정확히 파싱한다. cache
  배열의 malformed nested 원소도 fail-closed한다. 8-case 초기 통합 smoke로
  portable control의 누락된 inline flag를 찾아 고쳤고, 확장된 15-case
  screen은 15개 직접 검증과 15개 assembly audit를 모두 통과했다.
  부분 언롤과 AVX2를 더한 19-case screen은 19/19 직접 검증과 audit를
  통과했다. 당시 서로 다른 두 569-byte 후보를 더한 21-case screen 뒤 배치 대표
  7개까지 포함한 28-case screen도 직접 검증 28/28과 assembly audit
  28/28을 통과했으며, 짧은 smoke timing은 성능 근거로 쓰지 않았다.
  9차의 549-byte commutative source가 기존 assembly entry를 대체하고 548-byte
  `DEC` 대조군과 기존 compact block2를 더한 상태는 30 case였다. 10차 counted
  block-2/3/5를 추가한 최신 manifest는 **33-case**이며, 새 세 entry도 각각
  exact audit·random gate를 통과했다.
- 측정 도구와 raw 기록은 [02 optimization README](../solutions/02_optimization/README.md),
  [deep review](../solutions/02_optimization/deep_review_02.md),
  [inline raw samples](../solutions/02_optimization/inline_results_02.json),
  [GCC 13.3 결과](../solutions/02_optimization/gcc133_codegen_results_02.json),
  [GCC 13.3 schedule screen](../solutions/02_optimization/gcc133_schedule_screen_02.json),
  [GCC 13.3 source-order screen](../solutions/02_optimization/gcc133_source_order_results_02.json),
  [GCC 13.3 layout/backend screen](../solutions/02_optimization/gcc133_layout_screen_02.json),
  [split-width SIMD screen](../solutions/02_optimization/split_simd_results_02.json),
  [AVX2 codegen screen](../solutions/02_optimization/avx2_codegen_screen_02.json),
  [inline-assembly allocation screen](../solutions/02_optimization/avx2_inline_asm_alloc_results_02.json),
  [phase-staggered screen](../solutions/02_optimization/phase_staggered_results_02.json),
  [additional GCC AVX flags](../solutions/02_optimization/gcc133_avx_flags_results_02.json),
  [255H instruction model](../solutions/02_optimization/instruction_model_255h_02.json),
  [8차 CPU 1 timing](../solutions/02_optimization/eighth_wave_timing_02_cpu1.json),
  [8차 CPU 3 timing](../solutions/02_optimization/eighth_wave_timing_02_cpu3.json),
  [9차 commutative layout](../solutions/02_optimization/avx2_commutative_layout_results_02.json),
  [9차 compact block screen](../solutions/02_optimization/avx2_pair_block_results_02.json),
  [9차 CPU 1 schema-5 timing](../solutions/02_optimization/ninth_wave_timing_02_cpu1.json),
  [9차 CPU 3 schema-5 timing](../solutions/02_optimization/ninth_wave_timing_02_cpu3.json),
  [10차 counted frontend screen](../solutions/02_optimization/tenth_avx2_counted_frontends_results_02.json),
  [10차 AVX2 codegen screen](../solutions/02_optimization/tenth_codegen_results_02.json),
  [10차 scalar rotate screen](../solutions/02_optimization/tenth_codegen_scalar_rotate_results_02.json),
  [10차 CPU 1 current-schema-5 timing](../solutions/02_optimization/tenth_wave_timing_02_cpu1.json),
  [10차 CPU 3 current-schema-5 timing](../solutions/02_optimization/tenth_wave_timing_02_cpu3.json),
  [11차 CPU 1 stationarity-gated timing](../solutions/02_optimization/stationarity_gate_timing_02_cpu1.json),
  [11차 CPU 3 stationarity-gated timing](../solutions/02_optimization/stationarity_gate_timing_02_cpu3.json),
  [11차 범위 제한 ISA 합성](../solutions/02_optimization/eleventh_isa_synthesis_results_02.json),
  [11차 ISA 합성 재현 script](../solutions/02_optimization/screen_eleventh_isa_synthesis_02.py),
  [timing stability 진단](../solutions/02_optimization/timing_stability_results_02.json),
  [schedule CPU 0 raw](../solutions/02_optimization/gcc133_schedule_results_02_cpu0.json),
  [schedule CPU 4 raw](../solutions/02_optimization/gcc133_schedule_results_02_cpu4.json),
  [상수 배치 분석](../solutions/02_optimization/constant_placement_analysis_02.json),
  [상수 재배치 CPU 0 raw](../solutions/02_optimization/constant_reordering_results_02_cpu0.json),
  [상수 재배치 CPU 4 raw](../solutions/02_optimization/constant_reordering_results_02_cpu4.json),
  [상수 memory CPU 0 raw](../solutions/02_optimization/constant_memory_results_02_cpu0.json),
  [상수 memory CPU 4 raw](../solutions/02_optimization/constant_memory_results_02_cpu4.json),
  [255H autotuner](../solutions/02_optimization/autotune_02_255h.py),
  [기존 18-candidate raw samples](../solutions/02_optimization/deep_results_02.txt)에 있다.

### 6번

- telemetry 전수조사를 `floor_sum` 기반 analytic count로 바꾸고,
  sign 대칭, shifted `r1/r2` scan, fixed-`Q` comb, BMI2/ADX 및 portable
  Montgomery arithmetic, `a=-3` 동형 곡선, Hamburg co-Z ladder와 OpenMP
  scheduling을 적용했다.
- telemetry 단계 자체의 반복 측정 중앙값은 1,453.475ms에서 0.750ms로
  줄어 1,938x 개선됐다.
- 모든 benchmark sample은 `d`, `r3`, `P=dQ`와 `state_label`별 legacy
  `s2/0x5338` 또는 shifted `s3/0x3cea`를 다시 검사하므로 빠른 오답
  구현은 결과에 포함되지 않는다.
- shifted scan은 40-pair에서 `1.3428x`(95% CI
  `1.3336..1.3510`), Hamburg는 `1.1716x`(95% CI
  `1.1682..1.1764`)였고 둘 다 stationarity gate를 통과했다.
- Hamburg 정상 경로에서 y가 필요 없다는 점을 이용해 모든 lift의 sqrt를
  88비트 Euclidean Jacobi 판정으로 바꿨다. sqrt/Jacobi 40-pair는
  `1.0819x`(95% CI `1.0769..1.0842`)로 gate를 통과했다.
- runtime schedule까지 같은 frozen binary에서 비교해 2-thread만
  `scalar64`에서 `block32`로 바꿨다. paired `1.2121x`(95% CI
  `1.2051..1.2163`)였으며 최종 adaptive 정책은 `1T=block64`,
  `2T=block32`, `3T+=scalar64`다.
- balanced signed-w9(`1.0065x`), subtractive Jacobi(`1.0072x`, parity 포함),
  row-batched affine fixed-`Q`(`0.9351x`)와 2-lane Hamburg(`0.8624x`)는
  검증·반복 측정 뒤 기각했다. cofactor-5 subgroup 선필터는 유효 lift의
  79.94%를 제거할 잠재력이 있지만 판정 비용 때문에 고위험 연구로 남겼다.
- warm-up 10쌍 뒤 전체 legacy/당시-final 40-pair holdout의
  `3.7126x`(95% CI `3.7106..3.7251`)는 Jacobi와 새 2-thread 정책 전의
  역사적 합산 결과다. 현재 전체 stack 수치로 소급하지 않는다.
- 이전 native의 동일-run 역사 기준선은 원래 Python 대비 8-thread
  165.42x였다. 새 최종 stack의 broad 절대 시간은 shared VM 부하에
  민감하므로 작은 후보는 CPU-pinned adjacent AB/BA runner로 따로 판정한다.
- 구현과 ablation은 [06 optimization README](../solutions/06_optimization/README.md),
  [algorithm review](../solutions/06_optimization/deep_review_06_algorithm.md),
  [native/cache review](../solutions/06_optimization/deep_review_06_micro.md)에 있다.

나머지 여섯 문제는 최종 산출물의 정확성이 주된 목표이며, 별도의
score-facing 성능 경쟁은 없다.

## 최종 재현 진입점

저장소 루트에서 실행한다.

| 번호 | 최종 재현 파일 | 역할 |
|---:|---|---|
| 1 | [`solve_01_classical.py`](../solutions/solve_01_classical.py) | IC, Caesar/Vigenère 복호와 분류 결과 재현 |
| 2 | [`solve_02_permutation.py`](../solutions/solve_02_permutation.py), [`solve_02_permutation.c`](../solutions/solve_02_permutation.c), [`benchmark_02_permutation.py`](../solutions/benchmark_02_permutation.py) | 구조 복원, standalone oracle와 warmup 후 반복 benchmark |
| 3 | [`solve_03_tls_gcm_nonce_reuse.py`](../solutions/solve_03_tls_gcm_nonce_reuse.py) | pcap 파싱, GHASH 복원, record 위조와 제출값 검증 |
| 4 | [`solve_04_digital_forensics.py`](../solutions/solve_04_digital_forensics.py) | 로그 증거 스트리밍, 전체 F32 tensor discovery와 payload 추출 |
| 5 | [`solve_05_bgv.py`](../solutions/solve_05_bgv.py) | 네 자리 날짜 delta 전체와 GF(257) 선형계에서 유일 secret·평문 검증 |
| 6 | [`solve_06_prng.py`](../solutions/solve_06_prng.py), [`deep_native_06.cpp`](../solutions/06_optimization/deep_native_06.cpp), [`benchmark_deep_native_06.py`](../solutions/06_optimization/benchmark_deep_native_06.py), [`benchmark_06_promotion.py`](../solutions/06_optimization/benchmark_06_promotion.py) | dependency-free Python 정답, 최종 native, broad screening과 frozen-source AB/BA 승격 benchmark |
| 7 | [`solve_07_final.py`](../solutions/solve_07_final.py), [`solve_07_grouped_hm_flatter.cpp`](../solutions/solve_07_grouped_hm_flatter.cpp), [`run_07_grouped_hm_scan.py`](../solutions/run_07_grouped_hm_scan.py) | 결과 검증/RSA 복호화, grouped HM과 256개 blind scan |
| 8 | [`solve_08_aes_key.py`](../solutions/solve_08_aes_key.py) | leak 기반 후보 join으로 key 복원과 전체 pair 재검증 |

먼저 기본 정답·smoke 검증은 다음과 같다. 8번 전체 key 복원은 이 호스트에서
약 1분 이상 걸릴 수 있다.

```bash
python3 solutions/solve_01_classical.py

python3 solutions/benchmark_02_permutation.py \
  --warmups 1 --samples 5 --iterations 1000000 --random-cases 100000

python3 solutions/solve_03_tls_gcm_nonce_reuse.py
python3 solutions/solve_04_digital_forensics.py --verify-sha256
python3 solutions/solve_05_bgv.py
python3 solutions/solve_06_prng.py --backend int --telemetry analytic
python3 solutions/solve_07_final.py
python3 solutions/solve_08_aes_key.py
```

2번의 adaptive-inline 장기 캠페인과 6번의 broad native matrix를 각각
재측정하려면 다음을 실행한다. 두 도구의 통계 protocol은 같지 않다.
절대 시간과 speedup은 CPU 및 shared VM 부하에 따라 달라질 수 있으므로
raw sample, median과 MAD를 함께 본다.

```bash
python3 solutions/benchmark_02_permutation.py \
  --case default=submissions/02/contest.c \
  --case inline=submissions/02/contest.c --baseline default \
  --case-cflag inline=-mbmi2 \
  --case-cflag inline=-finline-limit=2000 \
  --audit-mode default=default-call-allowed \
  --audit-mode inline=full-inline-320 \
  --warmups 3 --samples 21 --iterations 3000000 --random-cases 100000 \
  --json /tmp/challenge02-inline.json

python3 solutions/06_optimization/benchmark_deep_native_06.py \
  --warmup 1 --repetitions 5 --threads 1,8 \
  --native-schedules adaptive --include-original-python \
  --output /tmp/challenge06-native.json

python3 solutions/06_optimization/benchmark_06_promotion.py \
  --baseline-label naf --candidate-label hamburg \
  --baseline-define CH6_NAF_D_MULTIPLICATION \
  --threads 1 --warmup-pairs 2 --pairs 40 \
  --output /tmp/challenge06-hamburg.json
```

4번은 Git에서 제외한 대형 공식 입력을 `4_raw/`에 두어야 한다. 2번의
benchmark는 correctness gate를 먼저 수행하며, 7번의 전체 격자 공격
빌드·실행 명령은 상세 writeup의 `격자 공격 재실행` 절에 있다.

## 최종 검증 상태

| 번호 | 검증 기준 |
|---:|---|
| 1 | Caesar shift `6`, Kasiski period `5`와 key `KLVOJ`, 동일 corpus/key의 paired holdout 58/58; 관측 구조와 출제 의도 추정 label 분리 |
| 2 | 제공 1-round 1,000개와 20-round vector, 100,000개 deterministic random differential case 통과 |
| 3 | GCM bit ordering self-test, pcap record 경계, nonce 재사용, 유일 `H`, known-plaintext 출처, tag와 77바이트 제출 hex 일치 |
| 4 | 모든 F32 tensor의 bounded-memory discovery, SafeTensors 범위와 로그 증거 보존을 합성 테스트 5개로 검증; 공식 대형 원본 재실행은 별도 필요 |
| 5 | 네 자리 Gregorian 다음날 delta 11종 전체에서 ternary 후보를 수집하고, 연속 날짜·동일 `State`·padding·error·제출 TXT를 통과한 후보가 1개인지 확인 |
| 6 | `P=dQ`, `d`, legacy `s2`/shifted `s3`, `r3` 확인; native preflight에서 random field 2,000 pair, boundary 64 pair, point/table 256개, Hamburg/NAF lift 128개 및 Euclidean/subtractive Jacobi reference 대조; 요청/실제 thread와 모든 후보 metadata 검사 |
| 7 | pinned FLATTER로 `cid=155` 복원과 선택 다항식 12개의 정수 평가 0 확인; `p*q=N`, mask, RSA 재암호화 일치. 256개 blind runner는 제공하되 전체 scan은 이번 정리에서 재실행하지 않음 |
| 8 | 모든 partial completion을 generator로 열거·중복 제거해 유일 key를 얻고, 50,000개 평문/암문 pair 전체 재암호화 mismatch 0 |

## 7번 장기 탐색의 최종 정리

7번은 장기간 여러 solver와 변수 분할을 비교했지만 최종 공격은 간결하다.
양끝 4비트씩만 256개로 열거하고, 정답 `cid=155 (0x9b)`에서 나머지를 `[265,420)` 155비트와
`[600,830)` 230비트의 두 연속 변수로 완화한다. `m=17,t=5`의
171차원 Herrmann--May 격자를 고정한 FLATTER revision으로 감축한 뒤,
소수체 resultant/GCD와 CRT로 정답 근을 복원했다. 선택 행과 modular
resultant 추출은 heuristic이라 실패 branch의 completeness는 보장하지
않지만, 복원 factor는 나눗셈·mask·RSA 재암호화로 sound하게 검증한다.
`run_07_grouped_hm_scan.py`는 정답 cid를 seed하지 않고 0..255의 로그·해시와
성공 후보 수를 JSON으로 남긴다.

SMT, exact-tail CP-SAT, Hensel prefix, exact·얕은 grouped HM, cuso 설계,
two-sided/partial-`p`, Coron, 휴리스틱 q-gap과 조건부 low600 clause, ranker와
Jochemsz--May low-lift의 결과와 중단 근거는
[7번 실패 전략 부록](07_소인수분해.md#직접-탐색과-실패한-전략)에
전략별로 정리했다.

시점별 세부 실험은 다음 자료에 보존한다.

- [탐색 README](../solutions/07_sat_cas_explore/README.md)
- [실험 계획과 의사결정 기록](../solutions/07_sat_cas_explore/EXPLORATION_PLAN.md)
- [실행 로그](../solutions/07_sat_cas_explore/RUN_LOG.md)

이 자료의 중간 시점에 적힌 `UNKNOWN`, `no-factor`와 다음 실행 계획은
당시 탐색 문맥을 보존한 기록이다. 현재 완료 상태와 최종 방법의 기준은
이 전체 정리와 [7번 최종 writeup](07_소인수분해.md)이다.

## 문서와 제출물 구조

- `writeups/01..08`: 문제별 배경지식, 최종 풀이, 검증, 참고 자료
- [제출 파일 색인](../submissions/README.md): 문제별 실제 제출 산출물
- [저장소 README](../README.md): 저장소 구성과 가장 짧은 완료 현황
- `solutions/02_optimization`, `solutions/06_optimization`: 반복 측정,
  후보 비교와 micro/algorithm review
- `solutions/07_sat_cas_explore`: 7번 장기 탐색의 시점별 원자료

따라서 진행상황을 판단할 때는 이 문서의 `전체 진행상황`을 먼저 보고,
수치와 근거는 해당 문제의 상세 writeup 및 재현 코드에서 확인한다.
