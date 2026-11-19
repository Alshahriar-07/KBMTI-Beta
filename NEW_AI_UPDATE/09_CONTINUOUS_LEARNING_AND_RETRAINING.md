# 09 — Continuous Learning and Controlled Retraining

## 1. Goal

Use reviewed outcomes and new market data to improve the system without allowing one bad week, one lucky backtest, or noisy labels to corrupt production behavior.

## 2. Learning layers

Not every improvement requires model fine-tuning:
1. Correct data/feature bugs.
2. Improve deterministic strategy rules with versioned experiments.
3. Improve retrieval documents and examples.
4. Improve prompts and tool schemas.
5. Fine-tune Qwen with a reviewed LoRA dataset only when evidence shows a model behavior gap.

PATRON forecasting retraining remains out of scope and must not be triggered by this pipeline.

## 3. Eligibility for training

A case can enter the candidate dataset only if:
- snapshot and timestamps are valid;
- strategy/model versions are known;
- no future leakage exists;
- outcome is fully resolved or the example is explicitly an outcome-independent knowledge case;
- label provenance is present;
- failure diagnosis has review status;
- user-private/account data is removed or appropriately protected;
- duplicate and near-duplicate checks pass.

Do not automatically convert every losing trade into a negative example or every winning trade into a positive example.

## 4. Retraining triggers

Use configurable evidence-based triggers, such as:
- enough newly reviewed examples accumulated;
- sustained drop in held-out structured-task performance;
- repeated failure category above a defined minimum sample count;
- strategy performance deterioration across a minimum evaluation window;
- significant data/feature distribution shift.

Triggers create a **candidate training job**, not an automatic production update.

## 5. Pipeline

```text
Resolved trades + reviewed cases
              |
       Eligibility filter
              |
      Dataset candidate build
              |
      Leakage / quality audit
              |
       Human approval gate
              |
      Offline LoRA training
              |
       Candidate model package
              |
      Structured task evaluation
              |
      Historical + walk-forward
       strategy evaluation
              |
        Paper-trading gate
              |
       Explicit promotion
              |
       Monitor + rollback
```

## 6. Avoid catastrophic forgetting

- Keep the original base model and previous approved adapters.
- Mix stable foundational examples with recent reviewed cases.
- Evaluate old and new tasks, not only recent failure cases.
- Track regressions in no-trade behavior, risk explanations and tool use.
- Use small, controlled LoRA experiments.
- Do not train directly on raw chain-of-thought. Train on concise explanations, evidence references and structured decisions.

## 7. Candidate promotion

A candidate may be promoted only if:
- data audit passes;
- no critical safety regression;
- schema/tool-use performance passes;
- held-out task quality improves or meets a predeclared non-inferiority threshold;
- strategy evaluation passes all required metrics;
- paper-trading evidence meets the configured minimum;
- operator explicitly approves.

If it fails, retain the current production version and store the candidate report.

## 8. Rollback

Keep:
- current production model package;
- previous known-good package;
- model/adapter hashes;
- config and prompt versions;
- evaluation report;
- promotion timestamp and approver.

Rollback must be one controlled operation and must not alter historical trade records.

## 9. Retraining dashboard

Show:
- new reviewed cases;
- dataset version and label distribution;
- candidate training status;
- train/validation/test metrics;
- regressions;
- strategy backtest and paper results;
- promotion eligibility;
- rejection reason;
- active model version and rollback target.
