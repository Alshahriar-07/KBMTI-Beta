# 13 — Safety, Permissions and Operational Rules

## 1. Product boundary

KBMTI provides decision support and educational analysis. It does not guarantee profits or eliminate trading risk. Users remain responsible for decisions.

## 2. No forced signal

WAIT and NO_TRADE are valid outcomes. If data is stale, context is incomplete, dependencies fail, strategy conditions conflict, or risk validation fails, do not show an actionable plan.

## 3. LLM restrictions

Qwen must not:
- invent live prices or indicator values;
- invent PATRON forecast outputs;
- invent account balance or position size;
- override the risk engine;
- claim unmeasured probabilities;
- alter strategy definitions during an active decision;
- place orders or access exchange credentials;
- run arbitrary shell commands;
- promote a model or dataset without approval.

## 4. Permission modes

Suggested modes:
- Observe: analysis and explanation only.
- Assisted: generate validated plans and journal user-confirmed actions.
- Autonomous execution: not included; requires a separate project and explicit approval.

## 5. Data and privacy

- Minimize stored account information.
- Never include API secrets in prompts, logs or training data.
- Redact personal/account identifiers from training examples.
- Restrict access to trade journals and account-specific metrics.
- Define retention and deletion policy.

## 6. Operational controls

- Single-flight or bounded concurrency according to runtime limits.
- Request timeouts and cancellation.
- Model unavailable -> deterministic UI and safe no-trade state.
- Risk service unavailable -> no actionable plan.
- Stale market data -> stale badge and no new setup.
- Audit every plan and lifecycle transition.
- Kill switch for disabling setup generation.

## 7. User-facing language

Avoid:
- “Guaranteed profit”
- “Perfect signal”
- “100% accurate”
- “Risk-free trade”

Prefer:
- “Validated setup candidate”
- “Conditions currently met”
- “Confirmation pending”
- “Plan invalidated”
- “Historical result; not a guarantee”
- “Insufficient evidence — no trade”
