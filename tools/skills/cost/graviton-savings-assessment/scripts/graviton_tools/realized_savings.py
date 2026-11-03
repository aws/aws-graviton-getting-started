"""
Intel-equivalent mapping for Graviton instance types.

Reverse-maps a Graviton instance to its Intel n-1 equivalent. Used by the
realized-savings computation in assessment_pipeline._compute_realized_savings.
"""
from typing import Optional

from .instance_classifier import classify_and_upgrade, full_type


def get_intel_equivalent(graviton_instance: str) -> Optional[str]:
    """Get the Intel n-1 equivalent for a Graviton instance type.

    Delegates to instance_classifier.classify_and_upgrade() which computes
    previous_intel algorithmically (with static overrides for irregular families).

    Returns full instance type string (e.g., "m5.xlarge" for "m6g.xlarge"),
    or None if not Graviton or no known Intel equivalent.
    """
    info = classify_and_upgrade(graviton_instance)
    if not info or not info.is_graviton or not info.previous_intel:
        return None
    return full_type(info.prefix, info.previous_intel, info.size, info.type_suffix)
