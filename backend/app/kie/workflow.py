"""Workflow Controller: bounded step execution with a loop guard.

The controller is deliberately dumb about *what* a step does: it receives a plan and an
executor callable. That keeps the loop guard, retry budget and cancellation in one place
that can be tested adversarially today, while Phase D adds richer steps.

Guards enforced here (not by the model):

* the plan may not exceed its step budget (4 by default);
* a step may be retried at most ``max_attempts - 1`` times;
* two consecutive steps with the same identity (kind/tool/arguments) abort the run —
  that is the duplicate-call detector;
* cancellation is checked before every attempt.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.kie.contracts import Plan, PlanStep


@dataclass
class StepOutcome:
    index: int
    kind: str
    ok: bool
    output: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "ok": self.ok,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "attempts": self.attempts,
        }


@dataclass
class WorkflowResult:
    ok: bool
    outcomes: list[StepOutcome]
    cancelled: bool = False
    aborted_reason: str | None = None

    @property
    def last_output(self) -> str:
        for outcome in reversed(self.outcomes):
            if outcome.ok and outcome.output:
                return outcome.output
        return ""


StepExecutor = Callable[[PlanStep], StepOutcome | str]


class WorkflowController:
    def __init__(self, *, max_attempts: int = 2) -> None:
        self.max_attempts = max(1, int(max_attempts))

    @staticmethod
    def _identity(step: PlanStep) -> tuple[str, str | None, str]:
        return (step.kind, step.tool, str(sorted(step.arguments.items())))

    def run(
        self,
        plan: Plan,
        executor: StepExecutor,
        *,
        cancel_event: Any = None,
    ) -> WorkflowResult:
        outcomes: list[StepOutcome] = []
        previous_identity: tuple[str, str | None, str] | None = None

        if len(plan.steps) > plan.max_steps:
            return WorkflowResult(
                ok=False,
                outcomes=[],
                aborted_reason=f"plan has {len(plan.steps)} steps, budget is {plan.max_steps}",
            )

        for step in plan.steps:
            if cancel_event is not None and cancel_event.is_set():
                return WorkflowResult(ok=False, outcomes=outcomes, cancelled=True, aborted_reason="cancelled")

            identity = self._identity(step)
            if identity == previous_identity:
                return WorkflowResult(
                    ok=False,
                    outcomes=outcomes,
                    aborted_reason=f"loop guard: repeated step {step.kind} '{step.tool or step.description[:40]}'",
                )
            previous_identity = identity

            outcome: StepOutcome | None = None
            for attempt in range(1, self.max_attempts + 1):
                if cancel_event is not None and cancel_event.is_set():
                    return WorkflowResult(ok=False, outcomes=outcomes, cancelled=True, aborted_reason="cancelled")
                started = time.perf_counter()
                try:
                    raw = executor(step)
                    outcome = raw if isinstance(raw, StepOutcome) else StepOutcome(
                        index=step.index, kind=step.kind, ok=True, output=str(raw)
                    )
                except Exception as exc:  # noqa: BLE001 - step failures are part of the flow
                    if getattr(exc, "retryable", True) is False:
                        # Structured, non-retryable failures (busy queue, model unloaded,
                        # invalid arguments) must reach the caller with their own code.
                        raise
                    outcome = StepOutcome(
                        index=step.index,
                        kind=step.kind,
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                outcome.attempts = attempt
                outcome.duration_ms = (time.perf_counter() - started) * 1000.0
                if outcome.ok:
                    break
            assert outcome is not None
            outcomes.append(outcome)
            if not outcome.ok:
                return WorkflowResult(
                    ok=False,
                    outcomes=outcomes,
                    aborted_reason=outcome.error or "step failed",
                )

        return WorkflowResult(ok=bool(outcomes), outcomes=outcomes)
