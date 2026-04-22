# CLAUDE.md — Claude Code onboarding for this repo

이 파일은 **Claude Code 세션이 이 repo를 열 때 자동으로 읽히는 지침서**입니다.
새로운 협업자가 자기 Claude Code로 이 프로젝트를 이어받을 때, 이 문서에 적힌
규칙을 그대로 따르면 됩니다.

---

## What this repo is

WorldQuant BRAIN REST API를 활용한 **알파 자동 반복 시스템**.

- 사용자가 채팅에서 "XX 아이디어로 알파 만들어줘" 라고 하면
- Claude가 `data/` 의 오퍼레이터/데이터필드만 써서 FASTEXPR 표현식을 작성하고
- `alpha_system.Runner` 로 BRAIN에 시뮬레이션을 제출/폴링/분석하고
- 결과 피드백을 읽고 통과 기준을 만족할 때까지 표현식을 수정

**통과 기준 (IQC 2026 Stage 1):**
- Sharpe ≥ 1.25, Fitness ≥ 1.0, Sub-universe Sharpe ≥ −0.16
- Turnover ∈ [1%, 70%], Weight well distributed
- Competition: International Quant Championship 2026 Stage 1

---

## Hard rules (Claude가 반드시 지킬 것)

1. **`data/brain_operators (1).csv` 의 오퍼레이터와 `data/IQC_brain_datafields (1).csv` 의
   데이터필드만** 사용한다. 외부 라이브러리 함수나 임의 이름을 만들지 않는다.
2. 표현식을 제출하기 전에 항상 `validate_expression(expr)` 로 검증한다. `unknown` 이
   비어있지 않으면 제출하지 말고 수정한다.
3. 시뮬레이션은 **`alpha_system.Runner.run_attempt()` 로만** 돌린다 — 원본 API를
   직접 호출하지 않는다. 이 함수가 attempt 로그를 자동 저장한다.
4. **`credentials.json` 은 절대 git 에 커밋하지 않는다.** 이미 `.gitignore` 처리됨.
5. 실패 결과를 받으면 `analysis.feedback` 를 읽고 **어떤 체크가 실패했는지** 확인한 뒤,
   `_REMEDIATION` 힌트를 바탕으로 표현식을 **최소 변경**으로 수정한다.
   아이디어의 핵심은 유지하면서 기술적 결함만 고친다.
6. 기본 세팅은 `alpha_system/config.py::DEFAULT_SETTINGS`. 필요하면 attempt 별로
   `settings_override` 로 오버라이드하되, **region/universe/delay/language 는
   IQC 2026 Stage 1 조건 (USA/TOP3000/1/FASTEXPR) 을 벗어나지 않는다**.
7. 한 아이디어당 시도 횟수는 권장 **최대 10회**. 10회 안에 통과 못 하면 사용자에게
   현황 보고 후 아이디어 자체를 재검토한다.

---

## First-time setup (협업자 관점)

```bash
# 1. Clone
git clone <repo-url>
cd worldqt

# 2. Python deps
pip install -r requirements.txt

# 3. 자기 BRAIN 계정 credentials 설정
cp credentials.example.json credentials.json
#   credentials.json 을 열어서 자기 BRAIN 가입 email 과 password 로 채움

# 4. 인증 확인
python main.py auth         # "Authentication OK" 떠야 함

# 5. (선택) 오퍼레이터/필드 검색 확인
python main.py search-op ts_rank
python main.py search-field close
```

---

## How to start a new Claude Code session

협업자가 이 repo를 자기 로컬에서 Claude Code로 열면, Claude가 이 `CLAUDE.md` 를
자동으로 읽습니다. 그 상태에서 아래 **시작 프롬프트** 중 하나를 붙여 넣으면 됩니다.

### 시작 프롬프트 A — 새 아이디어 돌리기

```
이 repo의 alpha_system을 써서 다음 아이디어로 알파를 만들어줘:

[아이디어 설명을 자유롭게 적는다. 예:
 "미국 대형주 중 52주 신고가를 뚫었을 때 수급(시총 비중 상승)이 동반되는
  종목은 롱, 반대 (신고가 후 수급 약화) 는 숏"]

제약:
- data/ 의 오퍼레이터와 데이터필드만 사용
- 통과 기준: Sharpe>=1.25, Fitness>=1.0, Sub-universe Sharpe>=-0.16,
  Turnover 1~70%, Weight 분산, IQC 2026 Stage 1 매칭
- 실패하면 피드백 보고 표현식 수정해서 통과할 때까지 반복 (최대 10회)
- 매 시도는 alphas/ 아래 저장된 record를 참고해도 됨
```

### 시작 프롬프트 B — 기존 아이디어 이어가기

```
alphas/ 아래에서 가장 최근 시도 폴더를 열어서 마지막 attempt의 feedback.md 를 읽고,
그 피드백을 반영한 다음 표현식을 만들어 run_attempt() 로 돌려줘. 통과할 때까지 반복.
```

### 시작 프롬프트 C — 탐색만

```
이 아이디어에 쓸만한 오퍼레이터/데이터필드를 먼저 조사해줘:
[아이디어]
python main.py search-op / search-field 로 탐색하고, 표현식 후보 2~3개를
validate 까지만 돌려서 보여줘. 시뮬레이션은 내 확인 후 돌릴 것.
```

---

## Typical working flow (Claude가 세션 안에서 실행하는 흐름)

```python
from alpha_system.runner import Runner
from alpha_system.validator import validate_expression

runner = Runner(idea="my_idea_short_name")

expression_v1 = """
  zscore(ts_rank(close, 252)) * sign(ts_delta(cap, 21))
"""

# 검증 먼저
v = validate_expression(expression_v1)
assert v.ok, f"Unknown identifiers: {v.unknown}"

# 시뮬레이션
rec = runner.run_attempt(expression_v1)
print(rec.analysis.summary)

if not rec.analysis.passed:
    # rec.analysis.feedback 를 보고 표현식 v2 작성 → run_attempt 다시
    expression_v2 = "..."
    rec = runner.run_attempt(expression_v2)
```

모든 시도는 `alphas/<timestamp>_<idea>/` 에 자동 저장:
- `attempt_NN_expression.txt` — 원본 표현식
- `attempt_NN_feedback.md` — 사람이 읽는 체크리스트 + 수정 힌트
- `attempt_NN_record.json` — 검증 + 분석 요약 (프로그래밍용)
- `attempt_NN_raw.json` — BRAIN API 원본 응답

---

## 디렉토리 구조

```
worldqt/
├── data/                          # 오퍼레이터 + 데이터필드 CSV (읽기 전용)
│   ├── brain_operators (1).csv
│   └── IQC_brain_datafields (1).csv
├── alpha_system/
│   ├── config.py                  # 엔드포인트, 통과 기준, 기본 세팅
│   ├── credentials.py             # credentials.json 로더
│   ├── client.py                  # BRAIN REST client (auth/simulate/poll/fetch)
│   ├── registry.py                # CSV → 허용 오퍼레이터/필드 목록
│   ├── validator.py               # 표현식 검증
│   ├── analyzer.py                # 결과 → PASS/FAIL + 피드백
│   └── runner.py                  # attempt orchestration + 디스크 로깅
├── alphas/                        # 런타임 산출물 (gitignored)
├── credentials.json               # BRAIN 계정 (gitignored)
├── credentials.example.json       # 템플릿
├── main.py                        # CLI
├── requirements.txt
├── .gitignore
├── README.md
└── CLAUDE.md                      # ← 이 파일
```

---

## 금지 사항 (Don't)

- ❌ `credentials.json` 을 커밋하거나 stdout 에 비밀번호를 출력하지 말 것
- ❌ `data/*.csv` 바깥의 오퍼레이터/필드 이름을 지어내지 말 것
- ❌ `Runner` 를 우회해서 `client.run_simulation()` 을 직접 부르지 말 것
  (attempt 로그가 남지 않음)
- ❌ 통과 기준을 만족하지 못했는데 "passed" 라고 보고하지 말 것
- ❌ 실패 원인을 분석 없이 표현식을 크게 뒤엎지 말 것 — 피드백에 기반한 최소 수정

---

## 확장 포인트

- 통과 기준 변경 → `alpha_system/config.py::PassCriteria`
- 기본 세팅 변경 → `alpha_system/config.py::DEFAULT_SETTINGS`
- 피드백 템플릿 추가 → `alpha_system/analyzer.py::_REMEDIATION`
- 다른 스테이지 (IQC Stage 2 등) 추가 → `PassCriteria` 를 스테이지별로 만들어
  `Runner(criteria=...)` 로 전달
