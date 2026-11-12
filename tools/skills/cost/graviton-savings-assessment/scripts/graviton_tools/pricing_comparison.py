# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Price lookup over pre-fetched on-demand rates.

Pure computation with no AWS calls: assessment_pipeline fetches on-demand rates
from the AWS Pricing API and passes them in as `pricing_json`. This module only
matches instance type strings against those keys, tolerating the abbreviated
sizes Cost Explorer uses ("db.m5.12xl" for "db.m5.12xlarge").
"""
import re
from typing import Optional, Dict, List


def fetch_prices(instance_types: List[str], region: str = "us-east-1",
                 pricing_json: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Resolve on-demand $/hr for `instance_types` from pre-fetched prices.

    Matching is exact up to size spelling, and the service prefix and suffix
    are part of the key: db.r5.large is never priced from a bare r5.large (EC2)
    or a cache.r5.large (ElastiCache). Those are different products with
    different rates, and a cross-service match makes a wrong savings ratio
    look like a priced one.

    Args:
        instance_types: Instance type strings to look up.
        region: Kept for API compatibility; `pricing_json` is already the
            price book for the caller's region.
        pricing_json: {instance_type: $/hr} for one region.

    Returns:
        {instance_type: $/hr} for every requested type that has a price.
    """
    if not pricing_json:
        return {}

    exact_map = {}
    for k, v in pricing_json.items():
        for var in _size_variants(k.strip().lower()):
            exact_map[var] = v

    prices = {}
    for it in instance_types:
        for var in _size_variants(it.strip().lower()):
            if var in exact_map:
                prices[it] = exact_map[var]
                break
    return prices


def _size_variants(key: str) -> List[str]:
    """Size abbreviation/expansion variants of a key (12xl <-> 12xlarge)."""
    variants = [key]
    expanded = _expand_size(key)
    if expanded != key:
        variants.append(expanded)
    abbreviated = _abbreviate_size(key)
    if abbreviated != key:
        variants.append(abbreviated)
    return variants


def _expand_size(instance_type: str) -> str:
    """Expand abbreviated size suffixes: 12xl -> 12xlarge, 2xl -> 2xlarge, etc."""
    # Match patterns like .12xl, .2xl, .xl at the end (but not .xlarge already)
    return re.sub(r'\.(\d*)xl$', r'.\1xlarge', instance_type)


def _abbreviate_size(instance_type: str) -> str:
    """Abbreviate size suffixes: 12xlarge -> 12xl, 2xlarge -> 2xl, etc."""
    return re.sub(r'\.(\d*)xlarge$', r'.\1xl', instance_type)
