"""Evidence-based trade outcome metrics and failure analysis."""

from app.outcomes.analyzer import analyze_outcome
from app.outcomes.metrics import excursion_r, net_r_multiple

__all__ = ["analyze_outcome", "excursion_r", "net_r_multiple"]
