"""squelch-harness: adversarial eval harness for Splunk detections.

Standalone library — no LLM or agent required.

    from squelch_harness import evaluate_detection, cluster_fps, perturb_and_eval

Requires a running Splunk instance and splunk-sdk.
"""

from .eval_lib import (
    EvalResult,
    evaluate_detection,
    gate_revision,
    perturb_and_eval,
    temporal_holdout_eval,
)
from .cluster import cluster_fps
from .attack_inject import run_adversarial_eval
from .utils import load_lookup

__version__ = "0.1.0"

__all__ = [
    "EvalResult",
    "evaluate_detection",
    "gate_revision",
    "perturb_and_eval",
    "temporal_holdout_eval",
    "cluster_fps",
    "run_adversarial_eval",
    "load_lookup",
]
