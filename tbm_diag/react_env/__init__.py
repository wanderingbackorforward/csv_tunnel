"""Closed-loop ReAct environment harness.

This package builds the environment that a future LLM policy can act inside:
finite actions, explicit observations, verifier-controlled claim levels, and
deterministic termination.
"""

from tbm_diag.react_env.runner import ReactEnvResult, run_react_environment
from tbm_diag.react_env.state import EnvironmentState, TraceRecord

__all__ = ["EnvironmentState", "ReactEnvResult", "TraceRecord", "run_react_environment"]
