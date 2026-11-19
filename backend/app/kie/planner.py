"""Planner: turn one user turn into an ordered, bounded list of steps.

Phase B is the foundation: the planner emits exactly one ``answer`` step, because no tool
is wired into the chat loop yet (tools are Phase C). What *is* real here is the contract
the later phases rely on — steps carry a kind, an optional tool name and arguments, the
plan has a hard step budget, and the workflow controller refuses to run a plan that
exceeds it or repeats itself.

Splitting this out now is deliberate: when tool routing arrives it changes
``Planner.plan``, not the core loop.
"""

from __future__ import annotations

import re

from app.kie.config import KieConfig
from app.kie.contracts import Mode, Plan, PlanStep, ToolSpec

MAX_TOOL_STEPS = 4

_GOAL_CHAR_LIMIT = 2000


class Planner:
    def __init__(self, config: KieConfig) -> None:
        self.config = config

    def plan(
        self,
        goal: str,
        *,
        mode: Mode,
        tools: list[ToolSpec] | None = None,
    ) -> Plan:
        """Produce a plan for this turn.

        ``tools`` is accepted (and recorded) so the call site does not have to change when
        tool routing lands; Phase B never asks the model to call one.
        """

        cleaned = re.sub(r"\s+", " ", (goal or "").strip())[:_GOAL_CHAR_LIMIT]
        available = sorted(spec.name for spec in (tools or []))
        description = "Answer from the conversation and the CONTEXT block."
        if available:
            description += f" Tools available for a later phase: {', '.join(available)}."
        step = PlanStep(index=0, kind="answer", description=description)
        return Plan(goal=cleaned, steps=(step,), mode=mode, max_steps=MAX_TOOL_STEPS)
