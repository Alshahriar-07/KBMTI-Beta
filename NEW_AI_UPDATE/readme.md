# PROJECT: KBMTI — FULL AI TRADING INTELLIGENCE UPGRADE

## PRIMARY OBJECTIVE

Transform KBMTI from a candle-forecasting-focused application into a comprehensive AI-powered Market Intelligence, Trading Assistance, Trade Management, and Continuous Learning platform.

The system must provide intelligent market analysis, explainable trade setups, entry/exit guidance, risk management, trade monitoring, outcome analysis, and controlled model improvement.

This is a major architectural upgrade. Prioritize correctness, modularity, measurable performance, safety, and compatibility with the existing application.

---

# 1. NON-NEGOTIABLE EXISTING SYSTEM PRESERVATION

Before changing anything, inspect the complete existing repository.

Read:
- docs/KIE_INTEGRATION_PLAN.md
- docs/KIE_PHASE_A_RESULTS.md
- docs/KIE_PHASE_B_RESULTS.md if present
- Existing KIE modules
- Existing PATRON integration
- Existing forecasting pipeline
- Existing chart implementation
- Existing backend API
- Existing frontend architecture
- Existing database models and migrations
- Existing tests

Important constraints:

1. PATRON must remain an independent quantitative candle-forecasting model.
2. Do not modify PATRON architecture, weights, training pipeline, or forecasting logic.
3. Do not replace PATRON with Qwen.
4. Qwen must not become the source of fabricated price predictions.
5. Preserve existing candle prediction charts.
6. Preserve existing API compatibility.
7. Preserve deterministic chat functionality.
8. Continue using the embedded in-process llama.cpp runtime and Qwen3-4B.
9. No Ollama, llama-server subprocess, cloud inference, or external inference server.
10. Do not silently change existing runtime configuration.
11. Do not claim unmeasured prediction accuracy or guaranteed trading profitability.

If Phase B has not been completed, identify this dependency and do not bypass it.

---

# 2. NEW SYSTEM ARCHITECTURE

Create modular components:

- Market Intelligence Engine
- Market Structure Engine
- Momentum Analysis Engine
- Volatility Analysis Engine
- Liquidity Analysis Engine
- Multi-Timeframe Analysis Engine
- Strategy Knowledge Base
- Strategy Evaluation Engine
- Qwen Trading Intelligence
- Trade Setup Engine
- Signal Validation Engine
- Risk Management Engine
- Trade Management Engine
- Trade Outcome Analyzer
- Trading Experience Database
- Dataset Builder
- Model Training Manager
- Model Evaluation Manager
- Model Version Manager

Each module must have clear interfaces, typed contracts, validation, logging, and unit tests.

Avoid a monolithic trading service.

---

# 3. QWEN TRADING INTELLIGENCE

Qwen3-4B must evolve into the primary natural-language market analysis and strategy reasoning model.

Teach it:

A. Market structure:
- HH, HL, LH, LL
- BOS
- CHoCH
- Trend continuation
- Trend reversal

B. Technical analysis:
- Support and resistance
- Supply and demand
- Trendlines
- EMA
- RSI
- MACD
- ATR
- VWAP

C. Price action:
- Breakouts
- Retests
- Rejections
- False breakouts
- Candlestick formations

D. Liquidity:
- Liquidity pools
- Liquidity sweeps
- Stop runs
- Equal highs and lows

E. Market regimes:
- Trending
- Ranging
- Consolidation
- High volatility
- Low volatility
- Potential reversal

F. Trading strategies:
- Trend following
- Breakout and retest
- Pullback entries
- Support/resistance rejection
- Momentum continuation
- Reversal setups

G. Risk management:
- Position sizing
- Risk/reward
- Stop loss
- Take profit
- Partial exits
- Breakeven
- Trade invalidation

Use a versioned trading knowledge base and retrieval system before attempting LoRA fine-tuning.

Do not assume that teaching concepts guarantees successful trading decisions.

---

# 4. STRATEGY DATASET AND MODEL TRAINING

Build a structured strategy training pipeline.

Each training example should contain:

- Timestamp
- Symbol
- Timeframe
- OHLCV context
- Market structure
- Indicator values
- Volatility
- Liquidity context
- Market regime
- PATRON forecast features, if available
- Strategy conditions
- Decision
- Entry conditions
- Stop loss logic
- Take profit logic
- Invalidation conditions
- Explanation
- Outcome, when available

Use temporally correct historical data.

Prevent:
- Lookahead bias
- Data leakage
- Future candle contamination
- Duplicate samples
- Incorrect labels
- Survivorship bias where relevant

Build dataset validation and versioning.

Implement LoRA fine-tuning as an isolated training workflow.

Training must not block the live inference runtime.

Investigate actual hardware compatibility and memory requirements before implementing training.

Do not assume that the RX 580 supports a particular training backend.

Provide CPU fallback only where practical and measured.

---

# 5. MARKET ANALYSIS ENGINE

Generate structured quantitative market analysis.

Required outputs:

- Market direction
- Trend strength
- Momentum
- Momentum weakening
- Market structure
- Support zones
- Resistance zones
- Liquidity zones
- Volatility
- Volume confirmation
- Market regime
- Multi-timeframe alignment

All numerical analysis must come from deterministic calculations or validated model outputs.

Qwen should interpret and explain these results, not invent their numerical values.

If information is unavailable, mark it unavailable.

---

# 6. TRADE SETUP ENGINE

Support:

- LONG
- SHORT
- WAIT
- NO TRADE

Every setup must contain:

- Symbol
- Timeframe
- Strategy name
- Direction
- Setup status
- Entry zone
- Stop loss
- TP1
- TP2
- TP3
- Risk/reward
- Position risk estimate
- Confirmation conditions
- Invalidation conditions
- Expiration condition
- Supporting evidence
- Conflicting evidence
- Model and strategy versions

Do not force a trade.

A setup must be rejected if required conditions are not satisfied.

Separate:
- Forecast direction
- Market bias
- Trade setup
- Actual execution decision

A bullish PATRON forecast must never automatically trigger a LONG recommendation.

---

# 7. RISK MANAGEMENT ENGINE

Implement deterministic risk calculations.

Requirements:

- Configurable maximum risk per trade
- Position sizing
- Stop-loss distance
- Take-profit distance
- Risk/reward calculation
- Maximum exposure
- Daily loss limit
- Consecutive loss protection
- Strategy-specific risk constraints

Reject invalid setups.

Never invent account balance or leverage.

Do not use Qwen to calculate critical monetary values without deterministic verification.

Do not automatically execute trades.

---

# 8. AI TRADING UI

Build a dedicated AI Trading Assistant experience.

First inspect the current UI and reuse its existing design system.

Do not redesign unrelated pages.

Create these sections:

## A. Market Intelligence

Show:
- Current market bias
- Trend
- Momentum
- Market structure
- Volatility
- Liquidity
- Support/resistance
- Multi-timeframe agreement
- PATRON forecast summary

## B. Next Trade

Show the best currently validated opportunity, if one exists.

Display:
- LONG / SHORT / WAIT / NO TRADE
- Entry zone
- Stop loss
- TP1 / TP2 / TP3
- Risk/reward
- Setup quality
- Confirmation status
- Invalidation conditions
- Setup expiration

If no valid setup exists, clearly explain why.

## C. AI Trading Instructions

Provide chronological, actionable instructions:

1. Current market condition.
2. What confirmation is required.
3. What condition permits entry consideration.
4. Where invalidation occurs.
5. How to manage the position.
6. When to consider partial exits.
7. When to exit.
8. What conditions cancel the setup.

Instructions must be generated from validated market and strategy data.

## D. Chart Integration

Integrate:
- Historical candles
- PATRON predicted candles
- Momentum information
- Market structure
- Support/resistance
- Entry zone
- Stop-loss line
- Take-profit lines
- Setup invalidation level

Do not confuse predicted candles with guaranteed future prices.

Do not remove existing chart features.

## E. Active Trade Monitoring

Show:
- Entry
- Current price
- Unrealized PnL
- SL distance
- TP progress
- Risk exposure
- Momentum changes
- Invalidation warnings
- Management instructions

Support manually registered trades and paper trades.

Do not connect automatic live execution in this phase.

---

# 9. TRADE OUTCOME ANALYSIS

Create a complete trade lifecycle.

Record:
- Setup creation
- Setup acceptance or rejection
- Entry
- Position changes
- Partial exits
- Final exit
- SL/TP events
- Fees and slippage
- Final realized PnL
- R-multiple
- Maximum favorable excursion
- Maximum adverse excursion

After a trade closes, generate an outcome report.

Analyze:

- Was the market direction correct?
- Was entry timing correct?
- Was the strategy valid?
- Was confirmation sufficient?
- Did the market regime change?
- Was the stop loss appropriate?
- Was the target realistic?
- Did momentum weaken?
- Did PATRON forecast align with actual movement?
- Did execution costs affect the result?

Classify outcomes:

- SUCCESS
- LOSS
- BREAKEVEN
- INVALID_SETUP
- EXECUTION_ERROR
- INSUFFICIENT_DATA

Identify root causes using actual recorded evidence.

Do not invent explanations.

---

# 10. CONTINUOUS LEARNING AND RETRAINING

Build a controlled learning pipeline.

Workflow:

Completed Trade
→ Outcome Analyzer
→ Root Cause Classification
→ Experience Database
→ Dataset Quality Validation
→ Dataset Versioning
→ Candidate Training
→ Model Evaluation
→ Champion Comparison
→ Approval or Rejection

Requirements:

1. Store successful and failed examples.
2. Do not train on incomplete or unreliable examples.
3. Separate strategy failures from execution failures.
4. Prevent future data from entering historical training samples.
5. Use chronological train/validation/test separation.
6. Use walk-forward evaluation.
7. Compare candidate model against the existing champion.
8. Reject regressions.
9. Preserve the previous model.
10. Support rollback.
11. Maintain complete training logs and model manifests.

Retraining must be scheduled or manually approved, not automatically triggered by every trade.

Never assume that a losing trade necessarily means the strategy or model was wrong.

---

# 11. STRATEGY PERFORMANCE DASHBOARD

Track:

- Win rate
- Profit factor
- Expectancy
- Average R
- Maximum drawdown
- Consecutive losses
- Average holding time
- Fees and slippage
- Strategy-specific performance
- Market-regime performance
- Long vs short performance
- Setup rejection rate

Evaluate performance using out-of-sample and walk-forward testing.

Do not optimize for win rate alone.

---

# 12. API AND DATA CONTRACTS

Design additive APIs for:

- Market analysis
- Strategy evaluation
- Trade recommendations
- Trade instructions
- Trade monitoring
- Trade outcome reports
- Dataset inspection
- Training jobs
- Model evaluation
- Model versions
- Model rollback

Use strict Pydantic schemas or the existing equivalent.

Validate all model outputs.

Do not expose arbitrary shell execution through AI tools.

All privileged operations require authorization.

---

# 13. TESTING AND VALIDATION

Add tests for:

- Market calculations
- Market structure
- Strategy conditions
- LONG/SHORT/WAIT decisions
- Entry validation
- SL/TP calculation
- Position sizing
- Risk limits
- Invalid setups
- Trade lifecycle
- Outcome analysis
- Dataset leakage prevention
- Training reproducibility
- Model comparison
- Model rollback
- API validation
- UI state handling
- Existing PATRON regression
- Existing KIE regression
- Existing chat regression

Use deterministic test fixtures.

Do not use fabricated backtest results.

---

# 14. IMPLEMENTATION PHASES

Do not implement everything blindly in one change.

First create a complete architecture and implementation roadmap.

Then implement in controlled phases:

Phase 1: Repository audit and architecture design.

Phase 2: Market Intelligence and Strategy Knowledge Base.

Phase 3: Strategy Engine and deterministic Risk Engine.

Phase 4: Qwen Trading Intelligence integration.

Phase 5: AI Trading Assistant UI and chart integration.

Phase 6: Trade Lifecycle and Monitoring.

Phase 7: Trade Outcome Analyzer.

Phase 8: Dataset Builder and Learning Pipeline.

Phase 9: LoRA Training and Model Evaluation.

Phase 10: Paper Trading and end-to-end validation.

Each phase must have:
- Implementation report
- Tests
- Known limitations
- Performance measurements
- Migration notes
- Acceptance criteria

Do not silently move to the next phase if the current phase fails.

---

# FINAL PRODUCT VISION

KBMTI should become an AI-powered trading intelligence platform where:

- PATRON forecasts future candles.
- Market Intelligence analyzes current market conditions.
- Qwen understands and evaluates trading strategies.
- Signal Engine identifies validated opportunities.
- Risk Engine checks risk and position sizing.
- AI Trading Assistant explains what to do next.
- Trade Monitor tracks active positions.
- Outcome Analyzer explains wins and losses.
- Learning Pipeline builds better datasets.
- LoRA Training improves future candidate models.
- Model Evaluation decides whether a new model deserves deployment.

The objective is not to promise guaranteed profit.

The objective is to create a transparent, measurable, continuously evaluated trading assistance system that helps users make better-informed decisions while controlling risk.

Start with a repository audit and produce:

docs/KBMTI_AI_TRADING_UPGRADE_MASTER_PLAN.md

Also produce:
docs/KBMTI_AI_TRADING_DATA_ARCHITECTURE.md
docs/KBMTI_AI_TRADING_UI_SPECIFICATION.md
docs/KBMTI_QWEN_TRAINING_STRATEGY.md
docs/KBMTI_TRADE_OUTCOME_LEARNING_PLAN.md

Do not modify PATRON or start large-scale training during the initial planning phase.

Report exact existing capabilities, missing components, dependencies, risks, and the recommended implementation order.