"""RuleEngine: orchestrates rule selection and evaluation."""

from planara_engine.engine import registry
from planara_engine.engine.registry import EvaluationResult
from planara_engine.engine.rule_engine import evaluate

__all__ = ["EvaluationResult", "evaluate", "registry"]
