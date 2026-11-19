"""Tool registry and engine (Phase B foundation).

No KBMTI tool is registered yet: tool adapters are Phase C, and shipping a tool that
nothing exercises would be dead code pretending to be a feature. What exists here is the
machinery those adapters will plug into — a closed allow-list, schema validation, access
levels, timeouts and result truncation — all enforced outside the model.
"""

from __future__ import annotations

from app.kie.tools.engine import ToolEngine
from app.kie.tools.registry import ToolRegistry

__all__ = ["ToolEngine", "ToolRegistry"]
