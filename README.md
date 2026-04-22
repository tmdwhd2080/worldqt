# WorldQuant BRAIN Alpha Iteration System

자동화된 알파 시뮬레이션 + 피드백 루프. 당신이 채팅에서 아이디어를 주면
Claude가 표현식을 작성하고, BRAIN REST API로 시뮬레이션을 돌리고, 결과를
분석해 통과 기준을 만족할 때까지 반복 수정합니다.

## Pass criteria (from IQC 2026 Stage 1)

| Metric | Cutoff |
|---|---|
| Sharpe | ≥ 1.25 |
| Fitness | ≥ 1.0 |
| Sub-universe Sharpe | ≥ -0.16 |
| Turnover | 1% ~ 70% |
| Weight distribution | well distributed |
| Competition match | IQC 2026 Stage 1 |

## Constraint

**`data/brain_operators (1).csv` 의 오퍼레이터와 `data/IQC_brain_datafields (1).csv` 의
데이터필드만 사용.** `validate` 명령이 위반 여부를 체크합니다.

## Setup

```bash
pip install -r requirements.txt
cp credentials.example.json credentials.json
# credentials.json 에 BRAIN platform 계정 email/password 입력
python main.py auth        # 인증 테스트
```

`credentials.json` 은 `.gitignore` 되어 있어 커밋되지 않음.

## CLI

```bash
# Datafield/operator 탐색
python main.py search-op ts_rank
python main.py search-field cash_flow

# 표현식이 허용된 이름만 쓰는지 검증 (시뮬레이션 없음)
python main.py validate "ts_rank(close, 252)"

# 단일 시뮬레이션 실행 (결과는 alphas/<timestamp>_<idea>/ 에 저장)
python main.py run "breakout_momentum" "ts_rank(close, 252)"
```

## Iteration loop (chat-driven)

채팅에서 아이디어를 주면 Claude 쪽에서 다음을 반복합니다:

```python
from alpha_system.runner import Runner

runner = Runner(idea="52week_high_capital_flow_long_short")

# 시도 1
rec = runner.run_attempt("<expression_v1>")
print(rec.analysis.summary)
if rec.analysis.passed:
    print("PASS, alpha_id:", rec.alpha_id)
else:
    print("Feedback:", rec.analysis.feedback)
    # 피드백 읽고 표현식 수정 → 시도 2
    rec = runner.run_attempt("<expression_v2>")
```

## Attempt artifacts

각 시도마다 `alphas/<timestamp>_<idea>/` 아래 저장:

- `attempt_NN_expression.txt` — 원본 FASTEXPR
- `attempt_NN_record.json` — 검증 + 분석 요약
- `attempt_NN_feedback.md` — 사람이 읽는 형식의 체크리스트 + 수정 힌트
- `attempt_NN_raw.json` — BRAIN API 원본 응답

## Default simulation settings

`alpha_system/config.py` 의 `DEFAULT_SETTINGS`:

```
region=USA, universe=TOP3000, delay=1, decay=0,
neutralization=SUBINDUSTRY, truncation=0.08,
pasteurization=ON, unitHandling=VERIFY, nanHandling=OFF,
language=FASTEXPR
```

시도별로 `settings_override` 파라미터로 오버라이드 가능.

## 모듈 구조

```
alpha_system/
├── config.py      # pass criteria, endpoints, defaults
├── credentials.py # load credentials.json
├── client.py      # BRAIN REST client (auth / simulate / poll / fetch)
├── registry.py    # operators + datafields loaded from data/*.csv
├── validator.py   # expression → {ok, operators_used, datafields_used, unknown}
├── analyzer.py    # simulation result → pass/fail + remediation hints
└── runner.py      # attempt orchestration + disk logging
```
