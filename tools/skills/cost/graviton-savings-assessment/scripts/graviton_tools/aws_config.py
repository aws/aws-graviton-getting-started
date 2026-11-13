# SPDX-License-Identifier: MIT-0
"""One bounded botocore configuration for every AWS client the skill creates.

botocore's defaults (60s to connect, five attempts) let a single unreachable
network cost minutes per request, and the skill makes hundreds of them: Cost
Explorer, Pricing, Savings Plans, and per-region describe calls. Every client
takes its Config from here, so a new one cannot quietly go back to the defaults
(tests/test_pricing_paths.py checks that each boto3.client call passes one).
"""


def bounded_client_config(read_timeout: int = 60, adaptive: bool = False):
    """Config with a 10s connect timeout and bounded retries.

    read_timeout: seconds to wait for a response. 60 suits calls that can
        legitimately be slow (Cost Explorer group-bys, paginated describes);
        the Pricing and Savings Plans clients use 30.
    adaptive: client-side rate limiting with up to 10 attempts. Only the
        Pricing and Savings Plans clients use it, where a throttled lookup that
        also fails its retry would silently drop a type from the savings.
        Everything else, Cost Explorer especially (every request is billed),
        retries three times in standard mode.
    """
    from botocore.config import Config
    retries = ({"max_attempts": 10, "mode": "adaptive"} if adaptive
               else {"max_attempts": 3, "mode": "standard"})
    return Config(connect_timeout=10, read_timeout=read_timeout, retries=retries)
