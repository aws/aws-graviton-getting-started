# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Graviton assessment pipeline — full fleet assessment via direct boto3 CE calls.

Takes raw CE usage type data and runs the full pipeline internally:
classify → collect pricing types → fetch OD pricing (AWS Pricing API) → score → migrate → engine readiness.

Returns a single structured JSON with everything the agent needs for reports.
"""
import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from .instance_classifier import classify_usage_type, generation_bucket, service_for_type
from .fleet_tools import (
    RegionalPrices,
    MEMORY_GIB_BY_TYPE,
    VCPU_BY_TYPE,
    capacity_factor,
    is_ineligible,
    platform_priceable,
    prices_for,
    target_type,
    score_graviton_fleet,
    generate_migration_plan,
    check_engine_graviton_readiness,
    _build_graviton_options,
    fetch_engine_versions,
    sizes_at_or_below,
    SIZE_NIH_FACTORS,
    nih_factor,
)
from .report_generator import _redact_sensitive

try:
    from .bulk_pricing import warm_cache, lookup_prices as bulk_lookup
except ImportError:
    warm_cache = None
    bulk_lookup = None


# Module-level pricing cache — persists across calls within the same session.
# Key: (instance_type, region), Value: od_price_per_hour
_pricing_cache: Dict[tuple, float] = {}

# Module-level RI pricing cache — Key: (instance_type, region), Value: effective_hourly_rate (1yr No Upfront)
_ri_pricing_cache: Dict[tuple, float] = {}

# Module-level SP pricing cache.
# Key: (instance_type, region, product_description, tenancy, duration_seconds)
# Value: sp_rate_per_hour.
#
# The product/tenancy/term dimensions are part of the key on purpose.
# DescribeSavingsPlansOfferingRates returns a rate per OS x tenancy x usage-type
# x term combination, so a (type, region) key cannot name a single rate: whichever
# combination the API happened to return first would win and then be reused
# fleet-wide. That silently priced a Graviton target against a different product
# than its source (e.g. m5 Linux/shared vs m8g "RHEL with HA"/UnusedBox), which
# inverted the savings ratio for SP rows.
_sp_pricing_cache: Dict[tuple, float] = {}

# SP term used for every offering-rate lookup, in seconds (1yr).
#
# Both sides of a savings ratio MUST be read at the same term or the ratio is
# meaningless — a 3yr source rate against a 1yr target rate reads as a cost
# increase. This is a fixed 1yr rather than the customer's actual term because
# Cost Explorer's SP utilization data does not carry the term; holding it
# constant keeps the ratio honest even where the absolute rates are not the
# customer's. Rows are labelled by pricing_source so the basis stays visible.
_SP_DURATION_SECONDS = 31536000

# Pricing API operatingSystem -> SP offering-rate productDescription. The two
# APIs name the same products differently, and the SP filter only matches its
# own spelling.
_OS_TO_SP_PRODUCT_DESCRIPTION = {
    "Linux": "Linux/UNIX",
    "RHEL": "Red Hat Enterprise Linux",
    "SUSE": "SUSE Linux",
    "Windows": "Windows",
}


def _sp_tenancy(tenancy: str) -> str:
    """Fleet tenancy string -> SP offering-rate `tenancy` filter value.

    Cost Explorer reports shared tenancy as "Shared", "default" or an empty
    string; the SP API only accepts lowercase "shared"/"dedicated"/"host".
    """
    t = (tenancy or "").strip().lower()
    if t.startswith("dedicated"):
        return "dedicated"
    if t.startswith("host"):
        return "host"
    return "shared"


# Cost Explorer platform string -> Pricing API operatingSystem value.
#
# Module-level because three call sites need it and each used to carry its own
# copy. A row's SP rate is keyed on this value, so two copies drifting apart
# would silently move rows to a different pricing product.
_PLATFORM_TO_OS = {
    "linux/unix": "Linux", "linux": "Linux",
    "windows (amazon vpc)": "Windows", "windows": "Windows",
    "red hat enterprise linux": "RHEL", "rhel": "RHEL",
    "suse linux": "SUSE", "suse": "SUSE",
}


def _sp_coords(item: Dict) -> Tuple[str, str]:
    """A fleet row's (operating_system, tenancy) for SP rate lookups.

    One accessor so a row's source rate and its targets cannot be looked up at
    different coordinates — the failure that made SP savings ratios meaningless.
    """
    platform = (item.get("platform") or "").lower().strip()
    return _PLATFORM_TO_OS.get(platform, "Linux"), _sp_tenancy(item.get("tenancy", ""))


def _lookup_sp_rate(instance_type: str, region: str, operating_system: str,
                    tenancy: str) -> Optional[float]:
    """Read one SP rate from the cache at explicit coordinates.

    Single accessor so no caller has to spell the 5-tuple key itself; an
    open-coded `(type, region)` lookup would silently miss and fall back to the
    on-demand ratio, which is the failure this key shape exists to prevent.
    """
    return _sp_pricing_cache.get((
        instance_type.lower(), region,
        _OS_TO_SP_PRODUCT_DESCRIPTION.get(operating_system, "Linux/UNIX"),
        tenancy, _SP_DURATION_SECONDS))


def _sp_usage_type_matches(usage_type: str, tenancy: str) -> bool:
    """True if `usage_type` is the running-instance rate for `tenancy`.

    Rejects the `Unused*` usage types, which price unused reservation capacity
    rather than a running instance and are never the right basis for a migration
    estimate. They carry the same rate as their running counterpart for shared
    Linux but diverge for other products, so they cannot be treated as
    interchangeable.
    """
    ut = (usage_type or "").lower()
    if "unused" in ut:
        return False
    if tenancy == "dedicated":
        return "dedicatedusage" in ut
    if tenancy == "host":
        return "hostusage" in ut
    return "boxusage" in ut


# ── Per-service pricing coordinates ────────────────────────────────────────
# A price is only comparable to another price at the same coordinates. EC2 needs
# OS and tenancy; the managed services have their own dimensions, and leaving
# them unpinned is the same defect as the Savings Plan one, in a different API:
#
#   RDS          one SKU per databaseEngine AND per deploymentOption. The filter
#                pinned deploymentOption to Single-AZ and did not pin the engine
#                at all, so the loop took whichever engine's SKU came back first.
#                Observed: db.m5.4xlarge priced as PostgreSQL (0.9121) while its
#                db.m6g.4xlarge target was priced as MariaDB (0.7787), reporting
#                $572.43 of savings where the matched figure is $417.98. And with
#                Single-AZ pinned, every Multi-AZ row's displayed rate was half
#                what the customer pays (Multi-AZ is a clean 2x, so the ratio
#                survived and only the rates were wrong).
#   ElastiCache  one SKU per cacheEngine. Valkey is 20% below Redis on every node
#                type measured, and the engine was pinned to Redis.
#   OpenSearch   verified to have exactly one ESInstance SKU per type, including
#                or2/ultrawarm1. No dimension to pin.
_RDS_DEFAULT_DEPLOYMENT = "Single-AZ"
_ELASTICACHE_DEFAULT_ENGINE = "Redis"


def _pricing_coords(item: Dict) -> Tuple[str, str, str]:
    """(service, engine, deployment) pricing coordinates for a fleet row.

    One accessor, so a row's own rate and its Graviton targets are always priced
    and cached at the same coordinates. Everything downstream keys on the tuple
    this returns rather than re-deriving it.
    """
    svc = (item.get("service") or "ec2").lower()
    if svc == "rds":
        return ("rds", item.get("database_engine") or "",
                item.get("deployment_option") or _RDS_DEFAULT_DEPLOYMENT)
    if svc == "elasticache":
        return ("elasticache",
                item.get("cache_engine") or _ELASTICACHE_DEFAULT_ENGINE, "")
    if svc == "opensearch":
        return ("opensearch", "", "")
    os_val, tenancy = _sp_coords(item)
    return ("ec2", os_val, tenancy)


def _coord_key(coords: Tuple[str, str, str]) -> str:
    """Stable string form of coordinates, for cache keys and price-dict keys."""
    return "|".join(coords)


def _od_usage_type_ok(service: str, usage_type: str) -> bool:
    """True if `usage_type` is the running-instance rate for `service`.

    The managed-service APIs return add-on SKUs alongside the node rate.
    ElastiCache in particular returns `SyncDurability-NodeUsage` — an add-on at
    roughly a seventh of the node rate — and for cache.m6g.2xlarge it is the
    FIRST result when the engine is not pinned. The old `cacheEngine=Redis`
    filter hid that by accident; pinning the row's real engine would expose it,
    so the usage type is now checked rather than relied upon.

    Aurora's I/O-Optimized cluster configuration bills the same instance class
    under its own usage type at a higher rate. Both sides of a ratio are read at
    the standard rate, so those SKUs are rejected rather than left to whichever
    came back first.
    """
    ut = (usage_type or "").lower()
    if "extendedsupport" in ut:
        return False
    if service == "elasticache":
        return "nodeusage" in ut and "sync" not in ut
    if service == "opensearch":
        return "esinstance" in ut
    if service == "rds":
        return "iooptimized" not in ut
    return True


# Module-level error collector — surfaces pricing failures in assessment summary.
_pricing_errors: List[str] = []

# Per-phase wall time, in call order. Step 3-4 used to be a single logged number
# covering pricing, enrichment, scoring and migration planning — 99% of the run
# in one opaque bucket. Locating a 745s regression inside it meant correlating
# log timestamps by hand, and only worked because two unrelated modules happened
# to log per-call INFO lines.
_phase_timings: List[Tuple[str, float]] = []


@contextmanager
def _phase(name: str):
    """Time a named phase, record it, and log it at INFO."""
    t0 = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - t0
        _phase_timings.append((name, elapsed))
        logger.info("  phase %-28s %7.1fs", name, elapsed)


def _log_phase_breakdown(total: float) -> None:
    """Log every phase with its share of total, slowest first."""
    if not _phase_timings:
        return
    logger.info("Phase breakdown (%.1fs total):", total)
    for name, elapsed in sorted(_phase_timings, key=lambda p: -p[1]):
        pct = (elapsed / total * 100) if total > 0 else 0
        logger.info("  %-28s %7.1fs  %5.1f%%", name, elapsed, pct)
    accounted = sum(e for _, e in _phase_timings)
    logger.info("  %-28s %7.1fs  %5.1f%%", "(unattributed)", total - accounted,
                ((total - accounted) / total * 100) if total > 0 else 0)


def _collect_all_fleet_types(classified: List[Dict]) -> Dict[str, set]:
    """Collect ALL unique instance types by region for full-fleet pricing.

    Includes:
    - Current types (raw field) — needed for od_rate_current
    - Primary Graviton upgrade target
    - Multi-gen candidates (graviton2/3/4 with prefix+size)
    - Intel equivalents of existing Graviton (for realized savings)

    Returns: {region: {instance_type, ...}}
    """
    types_by_region: Dict[str, set] = {}
    for item in classified:
        region = item.get("region", "us-east-1")
        if region not in types_by_region:
            types_by_region[region] = set()

        bucket = types_by_region[region]

        # Current type (always needed for od_rate_current)
        raw = item.get("raw", "")
        if raw:
            bucket.add(raw)

        # Graviton upgrade targets
        size = item.get("target_size") or item.get("size", "")
        for gkey in ("graviton_upgrade", "graviton2", "graviton3", "graviton4", "graviton5"):
            val = item.get(gkey)
            if val:
                full = target_type(item, val) if "." not in val else val
                bucket.add(_expand_size(full))
                # Also price the SMALLER sizes in this family. The same-size type
                # above is string-built and may not exist — db.r6i.32xlarge yields
                # db.r6g.32xlarge, which AWS does not offer. When that happens
                # _build_graviton_options substitutes the nearest smaller real
                # size (db.r6g.16xlarge), but that type was never in this price
                # request, so it resolved to no rate and the row reported $0
                # savings despite a real, priceable Graviton target existing.
                #
                # Enumerating the ladder here rather than consulting the
                # offerings catalog keeps this collector free of region/engine
                # lookups; the extra types are mostly cache/bulk hits, and the
                # catalog still decides which one is actually used.
                if "." not in val and size:
                    for smaller in sizes_at_or_below(size)[1:]:
                        bucket.add(_expand_size(target_type(item, val, smaller)))

        # For existing Graviton instances: add Intel n-1 equivalent (for realized savings)
        if item.get("is_graviton") and raw:
            try:
                from .realized_savings import get_intel_equivalent
                intel_eq = get_intel_equivalent(raw)
                if intel_eq:
                    bucket.add(intel_eq)
            except ImportError:
                pass  # realized_savings not available in this package yet

    return types_by_region


def normalize_instance_type(instance_type: str, service: str = "") -> str:
    """One spelling per instance type, applied wherever CE data is ingested.

    Cost Explorer spells the same OpenSearch node both "m7g.large" and
    "m7g.large.search" depending on the API, and abbreviates RDS sizes
    ("db.m5.12xl"). Rows keyed on the raw strings then collided with, or missed,
    each other: an OpenSearch row keyed "r5.large" merged into the EC2 r5.large
    row and was priced against the EC2 catalog. Every OpenSearch type carries
    ".search" after this, which is also the spelling the Pricing API and
    DescribeDomains use.
    """
    t = _expand_size((instance_type or "").strip().lower())
    if service == "opensearch" and t and not t.endswith(".search"):
        t += ".search"
    return t


def _expand_size(instance_type: str) -> str:
    """Expand abbreviated instance type sizes for Pricing API compatibility.

    CE returns abbreviated forms like db.m5.12xl, db.r5.2xl, db.m5.4xl, db.r5.xl.
    The Pricing API requires full forms: db.m5.12xlarge, db.r5.2xlarge, db.m5.4xlarge, db.r5.xlarge.
    Types already in full form (db.m5.large, cache.r4.2xlarge) pass through unchanged.
    """
    import re
    # Match sizes ending in .xl, .2xl, .12xl etc but NOT .xlarge
    if instance_type.endswith('xl') and not instance_type.endswith('xlarge'):
        return re.sub(r'\.(\d*)xl$', r'.\1xlarge', instance_type)
    return instance_type


# ── AWS error classification ───────────────────────────────────────────────
# Decided from the botocore error code where the exception carries one. These
# used to be substring tests on the exception's class name, which for a
# ClientError is always "ClientError" — so an AccessDenied from the Pricing API
# was not recognised as a credential failure and every remaining type was tried
# (and failed) anyway.
_AUTH_ERROR_CODES = frozenset({
    "AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
    "UnauthorizedException", "AuthFailure", "ExpiredToken",
    "ExpiredTokenException", "InvalidClientTokenId", "InvalidIdentityToken",
    "InvalidIdentityTokenException", "UnrecognizedClientException",
    "SignatureDoesNotMatch", "IncompleteSignature", "MissingAuthenticationToken",
    "InvalidSignatureException", "RequestExpired",
})
_THROTTLE_ERROR_CODES = frozenset({
    "Throttling", "ThrottlingException", "ThrottledException",
    "RequestLimitExceeded", "RequestThrottled", "RequestThrottledException",
    "TooManyRequestsException", "SlowDown", "LimitExceededException",
})


def _aws_error_code(exc: BaseException) -> str:
    """The botocore error code carried by `exc`, or "" if it has none."""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return str((resp.get("Error") or {}).get("Code") or "")
    return ""


def _is_auth_error(exc: BaseException) -> bool:
    """True when `exc` means the credentials are missing, expired or not allowed.

    No further lookup with the same credentials can succeed after one of these,
    so callers stop instead of repeating the failure for every remaining type.
    Exceptions without an error code (botocore's NoCredentialsError and the
    other credential-provider errors) are recognised by name.
    """
    code = _aws_error_code(exc)
    if code:
        return code in _AUTH_ERROR_CODES
    name, text = type(exc).__name__, str(exc)
    return any(tok in name or tok in text for tok in (
        "NoCredentials", "PartialCredentials", "CredentialRetrieval",
        "TokenRetrieval", "SSOTokenLoad", "UnauthorizedSSOToken",
        "ExpiredToken", "InvalidIdentityToken", "InvalidClientToken",
        "AccessDenied",
    ))


def _is_throttle(exc: BaseException) -> bool:
    """True when `exc` is a rate limit — transient, so the lookup is retried."""
    if _aws_error_code(exc) in _THROTTLE_ERROR_CODES:
        return True
    return "Throttling" in type(exc).__name__ or "Rate exceeded" in str(exc)


# ── Price List parsing ─────────────────────────────────────────────────────
# Hours in a reserved term, for spreading the upfront fee over the term.
_LEASE_HOURS = {"1yr": 8760, "3yr": 26280}

# Engines an unpinned RDS lookup prefers, in order. Without an engine filter
# GetProducts returns one SKU per engine in no specified order, so a row and its
# Graviton targets could land on different engines; a fixed preference puts both
# sides of the ratio on the same one.
_RDS_ENGINE_PREFERENCE = ("mysql", "postgresql", "mariadb",
                          "aurora mysql", "aurora postgresql")

# Commercial engines have no Graviton instance classes and are never priced.
_COMMERCIAL_ENGINE_TOKENS = ("oracle", "sql server", "db2")

# GetProducts pages read per type before the type is reported unpriced. With a
# full filter set one page is normal; the cap only bounds an unpinned RDS query.
_PRICE_LIST_PAGE_CAP = 10
_PRICE_LIST_PAGE_SIZE = 100


def _usd(dim: Dict) -> float:
    """A price dimension's USD amount, 0.0 if absent or malformed."""
    try:
        return float((dim.get("pricePerUnit") or {}).get("USD", "0") or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_price_list_item(pl, service: str) -> Optional[Dict]:
    """Parse one Pricing API PriceList entry into its running-instance rates.

    The ONE parser for both the first pass and the throttle retry sweep. The
    retry used to carry its own copy that skipped the usage-type check and the
    reserved terms, so a type that was throttled once could come back priced at
    ElastiCache's SyncDurability add-on (about a seventh of the node rate) and
    with no RI rates at all.

    Returns None for a SKU that is not the running-instance rate (add-ons,
    Extended Support, Aurora I/O-Optimized, commercial engines). Otherwise:
        {"engine": str, "od": $/hr or None,
         "ri": [(lease, purchase_option, offering_class, $/hr), ...]}

    Every reserved term is kept, All Upfront included, and its rate is
    AMORTIZED: the recurring hourly charge plus the upfront fee spread over the
    term's hours. That is the basis of Cost Explorer's effectiveHourlyRate,
    which is the customer's side of an RI ratio. Reading the recurring charge
    alone priced a Partial Upfront target at about half its real cost and gave
    an All Upfront target no rate at all.
    """
    if isinstance(pl, str):
        pl = json.loads(pl)
    attrs = (pl.get("product") or {}).get("attributes") or {}
    # vCPU count, for capacity comparisons the size table cannot make (metal).
    _vcpu, _itype = str(attrs.get("vcpu") or ""), (attrs.get("instanceType") or "").lower()
    if _itype and _vcpu.isdigit():
        VCPU_BY_TYPE[_itype] = int(_vcpu)
    _mem = re.match(r"^\s*([\d,.]+)\s*GiB", str(attrs.get("memory") or ""))
    if _itype and _mem:
        try:
            MEMORY_GIB_BY_TYPE[_itype] = float(_mem.group(1).replace(",", ""))
        except ValueError:
            pass
    if not _od_usage_type_ok(service, attrs.get("usagetype", "")):
        return None
    engine = (attrs.get("databaseEngine") or attrs.get("cacheEngine") or "").strip()
    if any(tok in engine.lower() for tok in _COMMERCIAL_ENGINE_TOKENS):
        return None
    terms = pl.get("terms") or {}

    od = None
    for term in (terms.get("OnDemand") or {}).values():
        for dim in (term.get("priceDimensions") or {}).values():
            price = _usd(dim)
            if price > 0:
                od = price
                break
        break  # only the first OnDemand term carries the list rate

    ri = []
    for term in (terms.get("Reserved") or {}).values():
        ta = term.get("termAttributes") or {}
        lease = ta.get("LeaseContractLength", "")
        hours = _LEASE_HOURS.get(lease)
        if not hours:
            continue
        hourly = upfront = 0.0
        for dim in (term.get("priceDimensions") or {}).values():
            unit = (dim.get("unit") or "").lower()
            desc = (dim.get("description") or "").lower()
            if unit == "quantity" or ("upfront" in desc and "fee" in desc):
                upfront += _usd(dim)
            else:
                hourly += _usd(dim)
        effective = hourly + upfront / hours
        if effective > 0:
            # RDS and ElastiCache terms carry no OfferingClass: every managed
            # reservation is the standard kind.
            ri.append((lease, ta.get("PurchaseOption", ""),
                       (ta.get("OfferingClass") or "standard").lower(), effective))
    return {"engine": engine, "od": od, "ri": ri}


def _choose_price_item(candidates: List[Dict], service: str,
                       engine_pinned: bool) -> Optional[Dict]:
    """The SKU to price a type at, from the parsed running-instance SKUs."""
    priced = [c for c in candidates if c.get("od")]
    if not priced:
        return None
    if service == "rds" and not engine_pinned:
        for pref in _RDS_ENGINE_PREFERENCE:
            for c in priced:
                if c["engine"].lower() == pref:
                    return c
    return priced[0]


def _query_price_item(client, service_code: str, filters: List[Dict],
                      service: str, engine_pinned: bool) -> Optional[Dict]:
    """Page through GetProducts until a running-instance SKU is found.

    One page of ten used to be all that was read. An unpinned RDS query returns
    a SKU per engine and license model, so the first page could hold nothing
    but Oracle and SQL Server SKUs (skipped) and the type was reported unpriced.
    An unpinned RDS query reads every page up to the cap so the engine
    preference sees every engine; everything else stops at the first usable SKU.
    """
    candidates: List[Dict] = []
    token = None
    for _ in range(_PRICE_LIST_PAGE_CAP):
        kwargs = {"ServiceCode": service_code, "Filters": filters,
                  "MaxResults": _PRICE_LIST_PAGE_SIZE}
        if token:
            kwargs["NextToken"] = token
        resp = client.get_products(**kwargs)
        for pl in resp.get("PriceList", []):
            parsed = _parse_price_list_item(pl, service)
            if parsed and parsed["od"]:
                candidates.append(parsed)
        token = resp.get("NextToken")
        if not token or (candidates and (service != "rds" or engine_pinned)):
            break
    return _choose_price_item(candidates, service, engine_pinned)


def _store_price_item(item: Dict, instance_type: str, api_type: str, region: str,
                      coord: Tuple[str, str, str, str], prices: Dict[str, float]) -> None:
    """Record one parsed SKU's on-demand and reserved rates in the caches."""
    keys = {instance_type.lower(), api_type.lower()}
    od = item["od"]
    if od:
        prices[instance_type] = od
        if api_type != instance_type:
            prices[api_type] = od
        for k in keys:
            _pricing_cache[(k, region) + coord] = od
    for lease, payment, offering_class, rate in item["ri"]:
        for k in keys:
            _ri_pricing_cache[(k, region, lease, payment, offering_class) + coord] = rate
            # 1yr / No Upfront / standard doubles as the simple key, for callers
            # that do not know the reservation's terms.
            if lease == "1yr" and payment == "No Upfront" and offering_class == "standard":
                _ri_pricing_cache[(k, region) + coord] = rate


def _fetch_od_prices_boto3(instance_types: set, region: str = "us-east-1",
                          operating_system: str = "Linux",
                          db_engine: str = "", deployment_option: str = "",
                          cache_engine: str = "",
                          status: Optional[Dict] = None) -> Dict[str, float]:
    """Fetch On-Demand prices directly from AWS Pricing API via boto3.

    One GetProducts lookup per type, paginated, with the service's filters.
    Reserved-term rates from the same SKU are stored in _ri_pricing_cache.
    Uses a module-level cache to avoid redundant API calls across regions.

    Every type in one call is priced at the SAME coordinates, for the same reason
    the Savings Plan fetch groups its types: the rates are divided to form a
    savings ratio, so a source and target read at different coordinates give a
    nonsense number. Callers must group by coordinates and call once per group.

    Args:
        instance_types: Set of instance type strings to price.
        region: AWS region for pricing lookup.
        operating_system: EC2 only — "Linux", "RHEL", "SUSE", "Windows".
        db_engine: RDS only — the CE/display engine name ("PostgreSQL",
            "Aurora PostgreSQL", ...). Empty leaves the engine unpinned, and
            the SKU is then chosen by _RDS_ENGINE_PREFERENCE; pass the row's
            engine.
        deployment_option: RDS only — "Single-AZ" or "Multi-AZ".
        cache_engine: ElastiCache only — "Redis", "Valkey", "Memcached".
        status: Optional dict. Receives "auth_error" (the error text) when a
            credential failure stopped the lookups, so a caller pricing several
            regions can stop calling the API instead of failing once per region.

    Returns:
        Dict of {instance_type: od_price_per_hour}.
        Raises ImportError if boto3 is not available.
        Collects per-type errors in _pricing_errors module-level list.
    """

    import boto3  # Let ImportError propagate — caller handles it
    from .instance_classifier import service_for_type

    # Cache key carries every coordinate that changes the price. It was
    # (type, region, OS), which is right for EC2 but collided for the managed
    # services: one db.m5.4xlarge entry had to serve PostgreSQL and MySQL,
    # Single-AZ and Multi-AZ, so whichever was fetched first won for all of them.
    _coord = (operating_system, db_engine, deployment_option, cache_engine)
    prices = {}
    types_to_fetch = set()
    for t in instance_types:
        cache_key = (t.lower(), region) + _coord
        if cache_key in _pricing_cache:
            prices[t] = _pricing_cache[cache_key]
        else:
            types_to_fetch.add(t)

    if not types_to_fetch:
        return prices  # All cached

    # Group uncached types by service
    by_service = {"ec2": [], "rds": [], "elasticache": [], "opensearch": []}
    for t in sorted(types_to_fetch):
        by_service[service_for_type(t)].append(t)

    # The region is passed to the Pricing API as `regionCode`, not as a
    # `location` display name.
    #
    # This used to be a hand-maintained region -> display-name map with
    # `.get(region, "US East (N. Virginia)")` as the fallback. It listed 14 of
    # the 34 commercial regions, so a fleet in any of the other 20 — Seoul,
    # Stockholm, Zurich, Hong Kong, Cape Town, Tel Aviv, Jakarta, Mexico,
    # Calgary, the Middle East regions — was priced at N. Virginia rates with no
    # warning. N. Virginia is the cheapest region, so every one of those rates
    # was understated (Cape Town and Zurich by ~24%, Seoul by ~19%).
    #
    # `regionCode` is the region string itself, so there is nothing to maintain
    # and a new region cannot silently fall back. Verified against AmazonEC2,
    # AmazonRDS, AmazonElastiCache and AmazonES.

    # Service configs: (service_code, extra_filters)
    service_configs = {
        "ec2": ("AmazonEC2", [
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ]),
        # RDS returns one SKU per (databaseEngine, deploymentOption). Both are
        # pinned from the row when known. An unpinned engine let the loop take
        # whichever engine came back first, which is how a PostgreSQL source got
        # compared against a MariaDB target.
        "rds": ("AmazonRDS", [
            {"Type": "TERM_MATCH", "Field": "deploymentOption",
             "Value": deployment_option or _RDS_DEFAULT_DEPLOYMENT},
        ] + ([{"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": db_engine}]
             if db_engine else [])),
        # Valkey is 20% below Redis on every node type measured, so pinning Redis
        # for a Valkey fleet overstated every rate.
        "elasticache": ("AmazonElastiCache", [
            {"Type": "TERM_MATCH", "Field": "cacheEngine",
             "Value": cache_engine or _ELASTICACHE_DEFAULT_ENGINE},
        ]),
        # Verified to have exactly one ESInstance SKU per type — nothing to pin.
        "opensearch": ("AmazonES", []),
    }

    # NOTE: `prices` is NOT re-initialised here. It was, which silently discarded
    # every cache hit collected above: cached types are excluded from
    # types_to_fetch, so once wiped they were never re-added and came back absent
    # from the return value. Masked only when EVERY type was cached, because that
    # path returns early — so the bug appeared when a fleet was partly cached,
    # which is the normal case on the second and later calls in a process.
    _fatal_error = None  # Track credential/auth errors to fail fast
    # Adaptive retries: the default (4 attempts, legacy mode) throttles on
    # fleets with hundreds of types — especially with concurrent assessments —
    # and each throttled type is silently dropped from savings. Adaptive mode
    # adds client-side rate limiting on top of more retries.
    try:
        from botocore.config import Config
        client = boto3.client(
            "pricing", region_name="us-east-1",
            config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
        )
    except ImportError:
        client = boto3.client("pricing", region_name="us-east-1")

    def _price_one(svc: str, instance_type: str) -> bool:
        """Look one type up and store its rates. True if an on-demand rate was found.

        The first pass and the retry sweep both come through here, so a retried
        type is parsed exactly like any other. Raises on API errors.
        """
        svc_code, extra_filters = service_configs[svc]
        # Expand abbreviated sizes (db.m5.12xl -> db.m5.12xlarge) for Pricing API
        api_type = _expand_size(instance_type)
        filters = [
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": api_type},
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            {"Type": "TERM_MATCH", "Field": "locationType", "Value": "AWS Region"},
        ] + extra_filters
        item = _query_price_item(client, svc_code, filters, svc,
                                 engine_pinned=(svc != "rds" or bool(db_engine)))
        if not item:
            return False
        _store_price_item(item, instance_type, api_type, region, _coord, prices)
        return True

    def _record_fatal(e: BaseException) -> None:
        nonlocal _fatal_error
        _fatal_error = f"{type(e).__name__}: {e}"
        remaining = sum(len(t) for t in by_service.values()) - len(prices)
        _pricing_errors.append(
            f"FATAL: Credential/auth error detected, "
            f"skipping remaining {remaining} types"
        )

    # Types throttled on the first pass, retried before we give up on them.
    _throttled: List[tuple] = []

    # Deliberately serial. Each type is an independent get_products call, so this
    # looks like the obvious thing to parallelise, and it is the second-largest
    # cost in a run (~173s). It was tried and measured slower: on 384 types in
    # us-west-2, warmed and with serial run first to remove order effects,
    # 1 worker took 42.1s against 53.6-54.7s for 4, 8 and 16 workers — flat
    # across the three, which is the signature of the client's `mode="adaptive"`
    # rate limiter clamping the global request rate once it observes throttling
    # under concurrency. Extra workers only add queueing behind that clamp.
    #
    # Switching to `mode="standard"` would remove the clamp, but the whole point
    # of adaptive mode here is that a throttled type which also fails its retry
    # sweep is dropped from savings silently. Trading ~40s for that risk is a bad
    # deal, especially now the RDS offerings lookup accounts for the bulk of the
    # runtime. Do not re-parallelise this without re-measuring both together.
    for svc, types in by_service.items():
        if not types or _fatal_error:
            continue
        for instance_type in types:
            if _fatal_error:
                break
            try:
                _price_one(svc, instance_type)
            except Exception as e:
                err_name = type(e).__name__
                # Throttling means the price wasn't retrieved, NOT that the
                # instance doesn't exist. Queue it for a retry sweep rather
                # than dropping it — a dropped type silently understates
                # savings, which is worse than a slow assessment. It is only
                # recorded as an error if that sweep also fails, so a recovered
                # type doesn't show up in the report's "unpriced" warning.
                if _is_throttle(e):
                    _throttled.append((svc, instance_type))
                    logger.info(
                        "Pricing throttled for %s@%s — queued for retry.",
                        instance_type, region,
                    )
                    continue
                _pricing_errors.append(f"{svc}/{instance_type}@{region}: {err_name}: {e}")
                # Fail fast on credential/auth errors
                if _is_auth_error(e):
                    _record_fatal(e)
                    break
                logger.warning(
                    "Pricing lookup failed for %s@%s (%s) — excluded from savings.",
                    instance_type, region, err_name,
                )

    # ── Retry sweep for throttled types ───────────────────────────────────
    # Throttling is transient, so abandoning these would silently understate
    # savings for instances that genuinely exist. Retry serially with a pause
    # to let the rate limiter recover. Only after this do we report a type as
    # unpriced.
    if _throttled and not _fatal_error:
        logger.info(
            "Retrying %d throttled pricing lookup(s) after backoff...", len(_throttled)
        )
        for attempt in range(3):
            if not _throttled or _fatal_error:
                break
            time.sleep(2 ** attempt * 2)  # 2s, 4s, 8s
            still_failing = []
            for svc, instance_type in _throttled:
                if instance_type in prices:
                    continue
                if _fatal_error:
                    still_failing.append((svc, instance_type))
                    continue
                try:
                    _price_one(svc, instance_type)
                except Exception as e:
                    if _is_throttle(e):
                        still_failing.append((svc, instance_type))
                    elif _is_auth_error(e):
                        _pricing_errors.append(
                            f"{svc}/{instance_type}@{region}: {type(e).__name__}: {e}")
                        _record_fatal(e)
                    else:
                        logger.warning(
                            "Retry failed for %s@%s (%s).", instance_type, region, type(e).__name__
                        )
            _throttled = still_failing

        if _throttled:
            for svc, instance_type in _throttled:
                if instance_type not in prices:
                    logger.warning(
                        "Pricing still throttled for %s@%s after 3 retry sweeps — "
                        "excluded from savings. The instance exists; its price could "
                        "not be retrieved.", instance_type, region,
                    )
                    _pricing_errors.append(
                        f"{svc}/{instance_type}@{region}: ThrottlingException after retry sweeps"
                    )
        else:
            logger.info("All throttled pricing lookups recovered on retry.")

    if status is not None and _fatal_error:
        status["auth_error"] = _fatal_error
    return prices


def _fetch_sp_offering_rates(instance_types: set, region: str = "us-east-1",
                             sp_type: str = "Compute", sp_payment: str = "No Upfront",
                             operating_system: str = "Linux",
                             tenancy: str = "shared") -> Dict[str, float]:
    """Fetch Savings Plans offering rates for instance types from public catalog.

    Uses DescribeSavingsPlansOfferingRates (public API, no customer data needed)
    to look up SP rates matching the provided plan parameters.

    Every type in one call is priced at the SAME coordinates — product, tenancy,
    payment option and term. That is the whole point of the call: the rates are
    consumed as a source/target *ratio*, so a source and target read at different
    coordinates produce a nonsense number rather than a slightly-off one. Callers
    must therefore group their types by (region, OS, tenancy) and issue one call
    per group, not pass a mixed set.

    Args:
        instance_types: Set of instance type strings to price, all sharing
            `operating_system` and `tenancy`.
        region: AWS region for pricing lookup.
        sp_type: Savings Plan type (Compute, EC2Instance, SageMaker). From CE SP utilization data.
        sp_payment: Payment option (No Upfront, Partial Upfront, All Upfront). From CE SP utilization data.
        operating_system: Pricing API OS value ("Linux", "RHEL", "SUSE"). Mapped
            to the SP API's own productDescription spelling. EC2 only — the
            Database SP products carry no product description.
        tenancy: SP tenancy filter value ("shared", "dedicated", "host").

    Returns:
        Dict of {instance_type: sp_rate_per_hour}.
        Returns empty dict on any failure (graceful degradation).
    """

    product_description = _OS_TO_SP_PRODUCT_DESCRIPTION.get(operating_system, "Linux/UNIX")

    # Check cache first
    sp_prices = {}
    types_to_fetch = set()
    for t in instance_types:
        cache_key = (t.lower(), region, product_description, tenancy, _SP_DURATION_SECONDS)
        if cache_key in _sp_pricing_cache:
            sp_prices[t] = _sp_pricing_cache[cache_key]
        else:
            types_to_fetch.add(t)

    if not types_to_fetch:
        return sp_prices

    try:
        import boto3
        from .instance_classifier import service_for_type
        sp_client = boto3.client("savingsplans", region_name="us-east-1")

        for instance_type in sorted(types_to_fetch):
            api_type = _expand_size(instance_type)
            # The SP API's product names, from the one service detector.
            product_type = {"rds": "RDS", "elasticache": "ElastiCache",
                            "opensearch": "OpenSearch"}.get(
                                service_for_type(instance_type), "EC2")

            try:
                # Determine correct SP type for this product
                # Compute SP covers EC2/Lambda/Fargate; Database SP covers RDS/ElastiCache/OpenSearch
                if product_type in ("RDS", "ElastiCache", "OpenSearch"):
                    effective_sp_type = "Database"
                else:
                    effective_sp_type = sp_type  # Use caller-provided (Compute or EC2Instance)

                filters = [
                    {"name": "instanceType", "values": [api_type]},
                    {"name": "region", "values": [region]},
                ]
                # productDescription/tenancy exist only on the EC2 product. The
                # Database SP products reject them, and sending them there would
                # turn a priced row into an unpriced one.
                if product_type == "EC2":
                    filters.append({"name": "productDescription",
                                    "values": [product_description]})
                    filters.append({"name": "tenancy", "values": [tenancy]})

                resp = sp_client.describe_savings_plans_offering_rates(
                    savingsPlanPaymentOptions=[sp_payment],
                    savingsPlanTypes=[effective_sp_type],
                    products=[product_type],
                    filters=filters,
                    maxResults=100,
                )
                # Take the running-instance rate at the requested term, not
                # whichever result came back first. Even after filtering, the API
                # still returns both terms and both the running and unused-capacity
                # usage types, and their order is not specified.
                for rate_entry in resp.get("searchResults", []):
                    offering = rate_entry.get("savingsPlanOffering", {})
                    if offering.get("durationSeconds") != _SP_DURATION_SECONDS:
                        continue
                    if product_type == "EC2" and not _sp_usage_type_matches(
                            rate_entry.get("usageType", ""), tenancy):
                        continue
                    sp_rate = float(rate_entry.get("rate", "0"))
                    if sp_rate > 0:
                        sp_prices[instance_type] = sp_rate
                        _sp_pricing_cache[(instance_type.lower(), region,
                                           product_description, tenancy,
                                           _SP_DURATION_SECONDS)] = sp_rate
                        if api_type != instance_type:
                            _sp_pricing_cache[(api_type.lower(), region,
                                               product_description, tenancy,
                                               _SP_DURATION_SECONDS)] = sp_rate
                        break
            except Exception as e:
                err_name = type(e).__name__
                if _is_auth_error(e):
                    _pricing_errors.append(f"SP_RATES: Auth error, skipping: {err_name}")
                    break
                continue

    except ImportError:
        pass  # boto3 not available
    except Exception as e:
        _pricing_errors.append(f"SP_RATES: {type(e).__name__}: {e}")

    return sp_prices


def _resolve_full_fleet_prices(types_by_region: Dict[str, set]):
    """Resolve OD prices for the full fleet, one price book per region.

    Two tiers for each region, in this order:
      1. _fetch_od_prices_boto3 — the live AWS Pricing API. It reads and fills
         the module-level _pricing_cache at full coordinates itself.
      2. bulk_pricing — the local SQLite copy of the public offer files, for
         RDS/ElastiCache/OpenSearch types the API left unpriced, read only from
         that region's own data and only while it is fresh. EC2 is not in it.

    The bulk tier used to run FIRST, so once a pricing.db existed every managed
    type it held was priced from it — at any age, at its default engine — and
    the live rate was never asked for. And when it did run as the fallback it
    warmed and read us-east-1 only, pricing every region at N. Virginia rates.

    On a credential failure the API is not called again for later regions; the
    bulk tier still runs for them.

    Args:
        types_by_region: Dict of {region: {instance_type, ...}} from _collect_all_fleet_types.

    Returns:
        RegionalPrices — {region: {instance_type: od_price_per_hour}} — with a
        `tier_counts` attribute: {"pricing_api": n, "bulk_cache": m}, the number
        of requested types each tier priced.
    """
    from .fleet_tools import RegionalPrices
    from .instance_classifier import service_for_type

    prices = RegionalPrices()
    tier_counts = {"pricing_api": 0, "bulk_cache": 0}
    auth_error = None

    for region, types in types_by_region.items():
        if not types:
            continue
        # Attached only if something was priced, so an empty result is falsy.
        book: Dict[str, float] = {}

        # 1. Live Pricing API.
        if not auth_error:
            status: Dict[str, str] = {}
            try:
                api_results = _fetch_od_prices_boto3(set(types), region, status=status)
            except ImportError:
                raise
            except Exception as e:
                api_results = {}
                _pricing_errors.append(f"{region}: {type(e).__name__}: {e}")
                if _is_auth_error(e):
                    status["auth_error"] = f"{type(e).__name__}: {e}"
            book.update(api_results)
            tier_counts["pricing_api"] += sum(1 for t in types if t in api_results)
            if status.get("auth_error"):
                auth_error = status["auth_error"]
                _pricing_errors.append(f"AUTH_STOP: {auth_error}")

        # 2. Bulk offer files, for managed types still unpriced, this region only.
        unpriced = sorted(
            t for t in types
            if t not in book and service_for_type(t) != "ec2"
        )
        if unpriced and bulk_lookup and warm_cache:
            try:
                warm_cache([region])
                bulk_results = bulk_lookup(unpriced, region)
            except Exception as e:
                # Recorded, so a corrupt cache DB, a schema change or a failed
                # download is distinguishable from "no rows for these types".
                logger.warning("Bulk pricing fallback failed for %s: %s: %s",
                               region, type(e).__name__, e)
                _pricing_errors.append(
                    f"bulk pricing fallback ({region}): {type(e).__name__}: {e}")
                bulk_results = {}
            for t, price in bulk_results.items():
                if t not in book and price:
                    book[t] = price
                    tier_counts["bulk_cache"] += 1

        if book:
            prices.book(region).update(book)

    prices.tier_counts = tier_counts
    return prices


def _od_at(od_prices: Dict[str, float], instance_type: str, od_key: str,
           os_val: str = ""):
    """On-demand price at given coordinates, falling back to the plain key.

    The coordinate-suffixed key is written alongside the plain one so the older
    consumers in fleet_tools keep working; anything comparing a rate against "the
    on-demand price" must ask at the same coordinates or the comparison that
    decides whether a commitment rate was really found gives the wrong answer.

    `os_val` is the EC2 OS axis. Step 4a-OS stores non-Linux prices under
    "{type}|{os}" — not under the full coordinate key — and the current-side
    lookup in enrichment already asks there. Target lookups must too: without
    this step a RHEL source rate was divided by a Linux target rate, which
    overstated RHEL/SUSE savings (+85% on the fleet it was found on).
    """
    if od_key:
        v = od_prices.get(f"{instance_type}|{od_key}")
        if v:
            return v
    if os_val and os_val != "Linux":
        v = od_prices.get(f"{instance_type}|{os_val}")
        if v:
            return v
    return od_prices.get(instance_type)


def _capacity_factor(item: Dict, target_type: str) -> float:
    """How many target instances replace one source instance.

    1.0 for a like-for-like target. A capacity-adjusted target is a smaller
    size (c5.24xlarge has no c6g equivalent, so c6g.16xlarge is offered), and
    comparing one of each credited the dropped vCPUs as a Graviton saving.
    Pricing 1.5 x c6g.16xlarge against the c5.24xlarge compares the same
    capacity.
    """
    return capacity_factor(item.get("target_size") or item.get("size", ""), target_type,
                           item.get("raw", ""), basis=item.get("size_basis") or "vcpu")


def _od_with_tier(book: Dict[str, float], instance_type: str, od_key: str,
                  os_val: str = "") -> Tuple[Optional[float], Optional[str]]:
    """(rate, tier) from the first price key that exists: coordinates, OS, plain.

    The tier says which coordinates the rate was read at, so the other side of
    a ratio can be read at the same ones.
    """
    if od_key:
        v = book.get(f"{instance_type}|{od_key}")
        if v:
            return v, "coord"
    if os_val and os_val != "Linux":
        v = book.get(f"{instance_type}|{os_val}")
        if v:
            return v, "os"
    v = book.get(instance_type)
    return (v, "plain") if v else (None, None)


def _od_at_tier(book: Dict[str, float], instance_type: str, tier: str,
                od_key: str, os_val: str) -> Optional[float]:
    if tier == "coord":
        return book.get(f"{instance_type}|{od_key}")
    if tier == "os":
        return book.get(f"{instance_type}|{os_val}")
    return book.get(instance_type)


def _ensure_target_rates(book: Dict[str, float], item: Dict, target_type: str,
                         region: str, tier: Optional[str], od_key: str,
                         os_val: str, sp_ten: str) -> None:
    """Price `target_type` at the row's own coordinates if no pass priced it there.

    The coordinate passes price each row's same-size targets. A capacity-adjusted
    target is a smaller size, so it had only the plain (default-coordinate) price,
    and a PostgreSQL Multi-AZ source was divided by a MySQL Single-AZ target. One
    lookup per such target, only when it is chosen; the result is cached.
    """
    svc, eng, depl = _pricing_coords(item)
    try:
        if tier == "coord" and not book.get(f"{target_type}|{od_key}"):
            kw = ({"db_engine": eng, "deployment_option": depl} if svc == "rds"
                  else {"cache_engine": eng} if svc == "elasticache" else None)
            if kw is not None:
                for k, v in _fetch_od_prices_boto3({target_type}, region, **kw).items():
                    book[f"{k}|{od_key}"] = v
        elif tier == "os" and not book.get(f"{target_type}|{os_val}"):
            for k, v in _fetch_od_prices_boto3({target_type}, region,
                                               operating_system=os_val).items():
                book[f"{k}|{os_val}"] = v
        if (svc == "ec2" and (item.get("cost_sp") or 0) > 0
                and _lookup_sp_rate(target_type, region, os_val, sp_ten) is None):
            _fetch_sp_offering_rates({target_type}, region, operating_system=os_val,
                                     tenancy=sp_ten)
    except Exception as e:
        logger.debug("Target pricing at row coordinates unavailable (%s %s): %s: %s",
                     target_type, region, type(e).__name__, e)


def _savings_ratio_for_target(item: Dict, target_type: str, target_od: float,
                              current_od: float, purchase_type: str,
                              ri_rate: Optional[float], sp_rate: Optional[float],
                              region: str, od_prices: Dict[str, float],
                              sp_os: str = "Linux",
                              sp_tenancy: str = "shared",
                              coord: Tuple[str, str, str, str] = ("Linux", "", "", ""),
                              od_key: str = "",
                              current_tier: Optional[str] = None) -> Optional[float]:
    """Savings ratio for one Graviton target, commitment-matched where possible.

    `current_tier` names the price key the source rate was read from (see
    _od_with_tier). The target is then read from the same tier, or both sides
    fall back to the plain key together; a ratio is never formed from one side
    at the row's coordinates and the other at defaults. None when no matched
    pair exists, or when the target's capacity cannot be compared.

    This is the Graviton Savings Dashboard's basis: the current side is the
    amortized/effective cost, and the target is priced at the SAME purchase
    coordinates (term, payment option, offering class) rather than at list price.
    GSD joins its pricing table on leasecontractlength/purchaseoption/
    offeringclass on both sides; the RI and SP branches below are the equivalent.

    `sp_os`/`sp_tenancy` carry the SOURCE row's product and tenancy into the SP
    target lookup. Without them the target resolved to whichever product the SP
    API listed first, so a Linux/shared source could be compared against a
    "RHEL with HA" unused-capacity rate and report a cost increase.

    Falls back to the on-demand ratio when no commitment rate can be found for the
    target — a proxy, not the basis, and the same thing GSD does not do (it emits
    NULL). Kept because dropping those rows would understate more than the proxy
    does; the row is still labelled by its pricing_source.

    Extracted so the default target and every per-generation what-if share one
    definition. They previously did not: the default was commitment-matched while
    est_savings_g2..g5 were always pure on-demand, so flipping the report's
    generation radio silently switched cost basis — even to the generation that
    was already the default.
    """
    # Re-resolve the target's on-demand rate at the SOURCE's coordinates before
    # forming the ratio. The caller takes target_od from _build_graviton_options,
    # which reads od_prices by plain instance type and therefore gets the default
    # coordinates. Once the source side became coordinate-correct, that mismatch
    # showed up immediately: a Multi-AZ db.m5.4xlarge (2.848) divided by a
    # Single-AZ db.m9g.4xlarge (1.465) reported 48.6% savings on a target that is
    # actually 2.9% more expensive. Both sides must come from the same place.
    if current_tier:
        # No fallback to the plain keys when the target has no rate at the
        # row's tier: plain keys hold the default engine/deployment and Linux,
        # so a PostgreSQL Multi-AZ or RHEL row would be booked at a MySQL
        # Single-AZ or Linux ratio. The row goes to unpriced instead. The one
        # exception is EC2 Linux, whose coordinates ARE the plain key's.
        matched = _od_at_tier(od_prices, target_type, current_tier, od_key, coord[0])
        if (not matched and current_tier == "coord"
                and od_key == _coord_key(("ec2", "", ""))
                and coord[0] in ("Linux", "")):
            matched = od_prices.get(target_type)
        if not matched or not current_od:
            return None
        target_od = matched
    else:
        _target_od_at_coords = _od_at(od_prices, target_type, od_key, coord[0])
        if _target_od_at_coords:
            target_od = _target_od_at_coords
    # Capacity: a smaller target is priced at as many instances as it takes to
    # match the source (see _capacity_factor). 1.0 for like-for-like targets.
    factor = _capacity_factor(item, target_type)
    if factor is None:
        return None
    ratio = 1 - target_od * factor / current_od

    if purchase_type == "RI":
        graviton_ri = _lookup_rate_for_type(
            target_type, region, "RI", od_prices,
            ri_offering=item.get("ri_offering_type", ""),
            ri_terms=_ri_terms(item),
            coord=coord, od_key=od_key,
        )
        # Only trust it if it came from the RI cache rather than the OD fallback.
        if graviton_ri and graviton_ri != _od_at(od_prices, target_type, od_key, coord[0]):
            ri_effective = item.get("ri_effective_hourly_rate", 0)
            if ri_effective and ri_effective > 0:
                return 1 - graviton_ri * factor / ri_effective
            if ri_rate and ri_rate > 0:
                return 1 - graviton_ri * factor / ri_rate

    if purchase_type == "SP" and sp_rate:
        graviton_sp = _lookup_rate_for_type(target_type, region, "SP", od_prices,
                                            ri_offering="", sp_os=sp_os,
                                            sp_tenancy=sp_tenancy,
                                            coord=coord, od_key=od_key)
        if graviton_sp and graviton_sp != _od_at(od_prices, target_type, od_key, coord[0]) and sp_rate > 0:
            return 1 - graviton_sp * factor / sp_rate

    return ratio


def _lookup_rate_for_type(instance_type: str, region: str, purchase_type: str,
                          od_prices: Dict[str, float],
                          ri_offering: str = "",
                          sp_os: str = "Linux",
                          sp_tenancy: str = "shared",
                          coord: Tuple[str, str, str, str] = ("Linux", "", "", ""),
                          od_key: str = "",
                          ri_terms: Tuple[str, str, str] = ("", "", "")) -> Optional[float]:
    """Unified rate lookup for any instance type at a given purchase option.

    Checks RI/SP caches first (with term matching for RI and product/tenancy/term
    matching for SP), falls back to OD. Used by both potential savings (Graviton
    target lookup) and realized savings (Intel equivalent lookup) to avoid
    duplicating cache access logic.

    `sp_os`/`sp_tenancy`/`coord` must describe the SOURCE row even when looking up
    a target, so both sides of a ratio come from the same coordinates. `coord` is
    the (OS, db_engine, deployment_option, cache_engine) tuple the OD and RI
    caches are keyed on; `od_key` is the coordinate-suffixed on-demand price key
    to prefer for the fallback.

    `ri_terms` is the source reservation's (lease, purchase option, offering
    class), e.g. ("3yr", "All Upfront", "convertible"), as
    _fetch_reservation_utilization derives them. When all three are known only
    the exact term is used: substituting the 1yr / No Upfront rate for a 3yr All
    Upfront reservation is the comparison of different terms that made those
    rows' savings understated or negative. With no exact match the lookup falls
    through to the on-demand rate, which callers already treat as "no
    commitment rate found". When the terms are not all known, `ri_offering` is
    parsed as before and the 1yr / No Upfront rate remains the fallback.
    """
    key_lower = instance_type.lower()

    if purchase_type == "RI":
        lease, payment, offering_class = _normalize_ri_terms(ri_terms)
        if lease and payment and offering_class:
            rate = _ri_pricing_cache.get(
                (key_lower, region, lease, payment, offering_class) + coord)
            if rate:
                return rate
        elif ri_offering:
            # Parse RI terms from the offering string, letting any term that
            # is known from ri_terms override the parsed one.
            ri_lower = ri_offering.lower()
            p_lease = "3yr" if ("3yr" in ri_lower or "3 yr" in ri_lower) else "1yr"
            p_payment = "No Upfront"
            if "partial" in ri_lower:
                p_payment = "Partial Upfront"
            elif "all upfront" in ri_lower or "all_upfront" in ri_lower:
                p_payment = "All Upfront"
            p_class = "convertible" if "convertible" in ri_lower else "standard"
            # Precise match first, then the simple key — both at this row's
            # coordinates, so an RDS PostgreSQL row cannot read a MariaDB rate.
            rate = _ri_pricing_cache.get(
                (key_lower, region, lease or p_lease, payment or p_payment,
                 offering_class or p_class) + coord)
            if rate:
                return rate
            rate = _ri_pricing_cache.get((key_lower, region) + coord)
            if rate:
                return rate
        else:
            rate = _ri_pricing_cache.get((key_lower, region) + coord)
            if rate:
                return rate

    elif purchase_type == "SP":
        rate = _lookup_sp_rate(instance_type, region, sp_os, sp_tenancy)
        if rate:
            return rate

    # Fallback to OD, preferring the coordinate-suffixed price, then the
    # OS-suffixed one — the same ladder as _od_at, and for the same reason.
    return _od_at(od_prices, instance_type, od_key, coord[0])


def _ri_terms(item: Dict) -> Tuple[str, str, str]:
    """(lease, payment option, offering class) of a row's RIs, "" where unknown.

    Read from Cost Explorer's subscription attributes by
    _fetch_reservation_utilization. With all three known, the Graviton RI rate
    is read at exactly those terms; a 3yr All Upfront RI is no longer compared
    against a 1yr No Upfront rate.
    """
    return (item.get("ri_lease", "") or "", item.get("ri_payment_option", "") or "",
            item.get("ri_offering_class", "") or "")


def _savings_by_purchase_type(item: Dict, target_type: str, target_od: float,
                              current_od: float, ri_rate: Optional[float],
                              sp_rate: Optional[float], region: str,
                              od_prices: Dict[str, float], **coords) -> Optional[float]:
    """Savings for one target, with each purchase-type slice at its own ratio.

    A row's cost is split into its On-Demand, RI, Savings Plan and Spot parts
    (cost_od..cost_spot). Each part is scaled by the ratio for that purchase
    type, so a 60/40 SP/OD row is no longer costed entirely on the SP basis.
    Rows without the breakdown fall back to their primary purchase type.
    """
    slices = {pt: item.get(field) or 0 for pt, field in _PT_COST_FIELD.items()}
    if not any(slices.values()):
        slices = {(item.get("purchase_type") or "OD"): item.get("cost", 0)}
    total = 0.0
    for pt, slice_cost in slices.items():
        if slice_cost:
            ratio = _savings_ratio_for_target(
                item, target_type, target_od, current_od, pt.upper(), ri_rate,
                sp_rate, region, od_prices, **coords)
            if ratio is None:
                return None
            total += slice_cost * ratio
    return total


def _normalize_ri_terms(ri_terms) -> Tuple[str, str, str]:
    """(lease, purchase option, offering class) in the Price List's spelling.

    "1yr"/"3yr", "No Upfront"/"Partial Upfront"/"All Upfront",
    "standard"/"convertible"; "" for anything not recognised.
    """
    lease, payment, offering_class = (tuple(ri_terms or ()) + ("", "", ""))[:3]
    lease = (lease or "").strip().lower().replace(" ", "")
    lease = lease if lease in _LEASE_HOURS else ""
    p = (payment or "").strip().lower().replace("_", " ")
    payment = ("All Upfront" if p == "all upfront" else
               "Partial Upfront" if p == "partial upfront" else
               "No Upfront" if p == "no upfront" else "")
    offering_class = (offering_class or "").strip().lower()
    offering_class = offering_class if offering_class in ("standard", "convertible") else ""
    return lease, payment, offering_class


def _enrich_classified_with_pricing(
    classified: List[Dict], od_prices: Dict[str, float], target_strategy: str
) -> None:
    """Attach pricing fields to ALL classified items (Graviton and non-Graviton).

    For non-Graviton items: attaches Graviton target rates and est_savings.
    For Graviton items: attaches Intel equivalent rate for realized savings.

    Mutates items in-place. Only attaches fields where pricing data is available.

    Per-gen fields added: est_savings_g2, est_savings_g3, est_savings_g4, est_savings_g5
    RI/SP rates: Uses purchase-type-aware pricing when available.

    Args:
        classified: List of classified instance dicts from the fleet classification step.
        od_prices: Dict of {instance_type: od_price_per_hour} from full-fleet pricing.
        target_strategy: Graviton generation targeting strategy ("latest", "cheapest", "same_gen").
    """
    for item in classified:
        # This row's own region's price book; see RegionalPrices.
        book = prices_for(od_prices, item.get("region", "us-east-1"))
        raw = item.get("raw", "")
        purchase_type = (item.get("purchase_type") or "OD").upper()
        # Both values come from _sp_coords so this row's source rate and its
        # Graviton targets are priced at identical coordinates.
        os_val, sp_ten = _sp_coords(item)

        # Skip rows with no Graviton path (Windows, SQL Server platforms,
        # commercial RDS engines) and OSes this tool cannot price; pricing them
        # as Linux would only manufacture a saving for the headline.
        if is_ineligible(item) or not platform_priceable(item):
            continue

        # This row's full pricing coordinates. For EC2 that is the OS; for the
        # managed services it is the engine and deployment option, which the
        # price genuinely varies by and which used to be unpinned.
        _svc, _eng, _depl = _pricing_coords(item)
        coord = ((os_val, "", "", "") if _svc == "ec2"
                 else (os_val, _eng, _depl, "") if _svc == "rds"
                 else (os_val, "", "", _eng) if _svc == "elasticache"
                 else (os_val, "", "", ""))
        od_key = _coord_key((_svc, _eng, _depl))

        # Determine the current rate. The coordinate-suffixed key first, then the
        # OS-suffixed one (EC2's older scheme), then the plain key.
        current_od, current_tier = _od_with_tier(book, raw, od_key, os_val)
        if current_od:
            item["od_rate_current"] = round(current_od, 6)

        # Also look up RI and SP rates for this item. Savings Plan ratios are
        # EC2-only: Database Savings Plan rates are not matched on engine or
        # deployment, so a managed row's SP slice uses the on-demand ratio.
        region = item.get("region", "us-east-1")
        ri_rate = _ri_pricing_cache.get((raw.lower(), region) + coord)
        sp_rate = _lookup_sp_rate(raw, region, os_val, sp_ten) if _svc == "ec2" else None

        if ri_rate:
            item["ri_rate_current"] = round(ri_rate, 6)
        if sp_rate:
            item["sp_rate_current"] = round(sp_rate, 6)

        # Find best Graviton target and its price + all gen options
        if not item.get("is_graviton") and item.get("graviton_upgrade"):
            options, best = _build_graviton_options(
                item, book, target_strategy, region=region
            )
            # Record the *validated* per-gen target name for every generation,
            # even when it is capacity-adjusted (no same-size) or has no price.
            # The fleet detail table uses this instead of naive string
            # construction, which would otherwise print sizes AWS doesn't offer
            # (e.g. db.r7g.32xlarge). None => that generation has no target.
            _GEN_FIELD_T = {
                "Graviton2": "g2", "Graviton3": "g3",
                "Graviton4": "g4", "Graviton5": "g5",
            }
            targets_by_gen = {}
            any_capacity_adjusted = False
            for opt in options:
                fld = _GEN_FIELD_T.get(opt.get("generation", ""))
                if not fld:
                    continue
                if opt.get("pricing_source") == "not_offered_in_region":
                    # The catalog rejected it: there is no target for this
                    # generation here, and the report must not print one.
                    targets_by_gen[fld] = {"type": "", "capacity_adjusted": False,
                                           "not_offered": True}
                    continue
                targets_by_gen[fld] = {
                    "type": opt.get("instance_type", ""),
                    "capacity_adjusted": opt.get("pricing_source") == "capacity_adjusted",
                }
                if opt.get("pricing_source") == "capacity_adjusted":
                    any_capacity_adjusted = True
            if targets_by_gen:
                item["graviton_targets_by_gen"] = targets_by_gen
            if any_capacity_adjusted:
                item["graviton_capacity_adjusted"] = True

            if best and best.get("od_rate"):
                # Reported at this row's coordinates, so the pair of rates the
                # report shows are the pair the savings figure came from.
                item["od_rate_graviton"] = round(
                    _od_at(book, best.get("instance_type", ""), od_key, os_val)
                    or best["od_rate"], 6)
                # Generational hops (source gen -> target gen); drives price-performance uplift.
                item["gen_hops"] = best.get("gen_hops", 0)
                item["graviton_target_generation"] = best.get("generation", "")
                # Surface a forced-generation fallback (e.g. G5 requested but not
                # offered here) so the report can label it instead of silently
                # reporting a different generation than the one requested.
                if best.get("generation_fallback"):
                    item["graviton_generation_fallback"] = True
                    item["graviton_requested_generation"] = best.get("requested_generation", "")

                # Retain every priced generation's rate + hops so the HTML
                # report's generation selector can switch targets client-side
                # with no re-run. _build_graviton_options already priced all of
                # them, so this costs no extra API calls.
                _GEN_FIELD = {
                    "Graviton2": "g2", "Graviton3": "g3",
                    "Graviton4": "g4", "Graviton5": "g5",
                }
                by_gen = {}
                for opt in options:
                    field = _GEN_FIELD.get(opt.get("generation", ""))
                    if field and opt.get("od_rate"):
                        by_gen[field] = {
                            "rate": round(opt["od_rate"], 6),
                            "hops": int(opt.get("gen_hops", 0) or 0),
                            "type": opt.get("instance_type", ""),
                        }
                if by_gen:
                    item["graviton_rates_by_gen"] = by_gen

                # The report's "Default next-gen" radio must mean next-gen
                # regardless of what --graviton-generation selected, so resolve
                # it independently. Using od_rate_graviton here would make every
                # radio relative to the CLI's choice, so the same fleet would
                # report different next-gen savings per invocation.
                if target_strategy == "latest":
                    item["od_rate_graviton_nextgen"] = item["od_rate_graviton"]
                else:
                    _, nextgen_best = _build_graviton_options(
                        item, book, "latest", region=region
                    )
                    if nextgen_best and nextgen_best.get("od_rate"):
                        item["od_rate_graviton_nextgen"] = round(nextgen_best["od_rate"], 6)

                # Compute savings using the most appropriate rate for this purchase type
                # OD ratio is used for all types — it's the best proxy available
                if current_od and current_od > 0:
                    graviton_target = best.get("instance_type", "")
                    _ensure_target_rates(book, item, graviton_target, region,
                                         current_tier, od_key, os_val, sp_ten)
                    row_savings = _savings_by_purchase_type(
                        item, graviton_target, best["od_rate"], current_od,
                        ri_rate, sp_rate, region, book,
                        sp_os=os_val, sp_tenancy=sp_ten,
                        coord=coord, od_key=od_key, current_tier=current_tier,
                    )
                    # Surface the matched commitment rates for the report/CSV.
                    if purchase_type == "RI":
                        _g_ri = _lookup_rate_for_type(
                            graviton_target, region, "RI", book,
                            ri_offering=item.get("ri_offering_type", ""),
                            ri_terms=_ri_terms(item),
                            coord=coord, od_key=od_key)
                        if _g_ri and _g_ri != _od_at(book, graviton_target, od_key, os_val):
                            item["ri_rate_graviton"] = round(_g_ri, 6)
                    if purchase_type == "SP" and sp_rate:
                        _g_sp = _lookup_rate_for_type(graviton_target, region, "SP",
                                                      book, ri_offering="",
                                                      sp_os=os_val, sp_tenancy=sp_ten,
                                                      coord=coord, od_key=od_key)
                        if _g_sp and _g_sp != _od_at(book, graviton_target, od_key, os_val):
                            item["sp_rate_graviton"] = round(_g_sp, 6)

                    if row_savings is not None:
                        item["est_savings"] = round(row_savings, 2)
                    else:
                        # No matched rate pair at the row's coordinates. Flag
                        # it so the scorer reports it unpriced instead of
                        # re-pricing it from default-coordinate plain keys.
                        item["savings_unmatched"] = True

            # Store per-gen savings for what-if columns. Commitment-matched via
            # the same helper as the default target, so switching generations in
            # the report changes the TARGET, never the cost basis.
            if current_od and current_od > 0:
                for opt in options:
                    gen = opt.get("generation", "")
                    od_rate = opt.get("od_rate")
                    if od_rate and od_rate > 0:
                        _ensure_target_rates(book, item, opt.get("instance_type", ""),
                                             region, current_tier, od_key, os_val, sp_ten)
                        per_gen = _savings_by_purchase_type(
                            item, opt.get("instance_type", ""), od_rate,
                            current_od, ri_rate, sp_rate, region, book,
                            sp_os=os_val, sp_tenancy=sp_ten,
                            coord=coord, od_key=od_key, current_tier=current_tier)
                        if per_gen is None:
                            continue
                        savings = round(per_gen, 2)
                        if "Graviton2" in gen or "G2" in gen:
                            item["est_savings_g2"] = savings
                        elif "Graviton3" in gen or "G3" in gen:
                            item["est_savings_g3"] = savings
                        elif "Graviton4" in gen or "G4" in gen:
                            item["est_savings_g4"] = savings
                        elif "Graviton5" in gen or "G5" in gen:
                            item["est_savings_g5"] = savings

        # For Graviton items: attach Intel equivalent rate for realized savings
        if item.get("is_graviton") and item.get("previous_intel"):
            from .realized_savings import get_intel_equivalent
            intel_eq = get_intel_equivalent(raw)
            if intel_eq:
                item["intel_equivalent"] = intel_eq
                intel_rate = _lookup_rate_for_type(
                    intel_eq, region, purchase_type, book,
                    ri_offering=item.get("ri_offering_type", ""),
                    ri_terms=_ri_terms(item),
                    sp_os=os_val, sp_tenancy=sp_ten,
                    coord=coord, od_key=od_key
                )
                if intel_rate:
                    item["rate_intel_equiv"] = round(intel_rate, 6)
                # Graviton's OWN rate at the SAME purchase coordinates. Realized
                # savings scale actual cost by intel_rate/graviton_rate, so both
                # sides must come from this one helper at the same purchase_type
                # (OD/SP/RI/Spot) or the ratio stops being a pure architectural
                # delta and reabsorbs the customer's discount (the GSA-2 bug).
                graviton_rate_equiv = _lookup_rate_for_type(
                    raw, region, purchase_type, book,
                    ri_offering=item.get("ri_offering_type", ""),
                    ri_terms=_ri_terms(item),
                    sp_os=os_val, sp_tenancy=sp_ten,
                    coord=coord, od_key=od_key
                )
                if graviton_rate_equiv:
                    item["rate_graviton_equiv"] = round(graviton_rate_equiv, 6)


def _resolve_engine_versions(classified: List[Dict]) -> Dict[tuple, list]:
    """Resolve engine versions for managed service instances in the fleet.

    Only queries regions/services that appear in the classified data.
    Returns empty dict on total failure (graceful degradation).

    Args:
        classified: List of classified instance dicts from the fleet classification step.

    Returns:
        Dict keyed by (service, instance_type, region) -> [{"engine": str, "version": str}]
        Empty dict if no managed services in fleet or on any failure.
    """
    # Collect active regions and services from classified data
    active_regions = set()
    active_services = set()
    for item in classified:
        svc = item.get("service", "ec2")
        if svc in ("rds", "elasticache", "opensearch"):
            active_services.add(svc)
            region = item.get("region", "")
            if region:
                active_regions.add(region)

    if not active_regions or not active_services:
        return {}

    try:
        return fetch_engine_versions(list(active_regions), list(active_services))
    except Exception:
        return {}  # Graceful degradation — empty versions like today


def _compute_realized_savings(
    classified: List[Dict], od_prices: Dict[str, float]
) -> Optional[Tuple[List, Dict]]:
    """Compute realized savings for existing Graviton instances.

    Uses pre-computed `rate_intel_equiv` from the enrichment pass (purchase-type-aware).
    Falls back to OD rate ratio if enrichment didn't attach the rate.

    Returns None if no Graviton instances exist (caller omits block).
    Otherwise returns (detail_list, summary_dict).
    """
    from .realized_savings import get_intel_equivalent

    graviton_items = [item for item in classified if item.get("is_graviton") and item.get("raw")]
    if not graviton_items:
        return None

    results = []
    total_graviton_cost = 0.0
    total_intel_equivalent_cost = 0.0
    total_savings = 0.0
    unpriced_count = 0

    for item in graviton_items:
        book = prices_for(od_prices, item.get("region", "us-east-1"))
        raw = item.get("raw", "")
        cost = item.get("cost", 0)
        hours = item.get("hours", 0)
        service = item.get("service", "ec2")
        region = item.get("region", "us-east-1")
        purchase_type = (item.get("purchase_type") or "OD").upper()

        # Skip items with zero cost — fully covered by RI/SP, no actual savings to claim
        if cost <= 0:
            continue

        intel_eq = item.get("intel_equivalent") or get_intel_equivalent(raw)
        if not intel_eq:
            continue

        # Realized savings on ONE pricing basis.
        #
        # `cost` is the customer's ACTUAL amortized spend — it already reflects
        # their effective committed Savings Plan / Reserved Instance rates. The
        # Intel-equivalent "before" must be derived on that SAME basis, or the figure
        # silently absorbs the whole discount on top of the architectural Graviton delta
        # (the GSA-2 ~10x overstatement). We hold both sides on one basis by
        # scaling actual cost by the ratio of catalog rates looked up at the SAME
        # purchase coordinates for the Intel equivalent and this Graviton type:
        #
        #     intel_cost = cost * (intel_rate / graviton_rate)
        #
        # Because both rates come from the same rate lookup at the same purchase
        # type, the ratio is architecture-only and the discount in `cost` cancels.
        # This is the single-basis method potential savings already uses, and it
        # holds for OD, SP, RI and Spot alike. Running hours do not enter the
        # computation: `cost` already covers the period. When either rate cannot
        # be resolved we report NO realized savings for the row rather than
        # fabricating a flat percentage.
        intel_rate = item.get("rate_intel_equiv")
        graviton_rate = item.get("rate_graviton_equiv")
        if not intel_rate or not graviton_rate:
            # Fallback: look up BOTH sides directly, at the row's own coordinates,
            # through the same helper so they stay on one basis. The coordinates
            # matter — without them an SP row on RHEL/SUSE or dedicated tenancy
            # misses the SP cache and silently drops to an OD rate on one side.
            _os_val, _sp_ten = _sp_coords(item)
            if not intel_rate:
                intel_rate = _lookup_rate_for_type(
                    intel_eq, region, purchase_type, book,
                    ri_offering=item.get("ri_offering_type", ""),
                    ri_terms=_ri_terms(item),
                    sp_os=_os_val, sp_tenancy=_sp_ten,
                )
            if not graviton_rate:
                graviton_rate = _lookup_rate_for_type(
                    raw, region, purchase_type, book,
                    ri_offering=item.get("ri_offering_type", ""),
                    ri_terms=_ri_terms(item),
                    sp_os=_os_val, sp_tenancy=_sp_ten,
                )

        if intel_rate and graviton_rate and graviton_rate > 0:
            ratio = intel_rate / graviton_rate
            intel_cost = cost * ratio
            savings = intel_cost - cost
            savings_pct = round((1 - 1 / ratio) * 100, 1) if ratio > 0 else 0
            pricing_source = "catalog_ratio"
            total_graviton_cost += cost
            total_intel_equivalent_cost += intel_cost
            total_savings += savings
        else:
            # Either rate is missing (even the On-Demand fallback). Report no
            # realized savings for the row, as the comment above promises: it is
            # listed as unpriced and kept out of every total, rather than given
            # a flat figure that looks measured.
            intel_cost = cost
            savings = 0.0
            savings_pct = None
            pricing_source = "unpriced"
            unpriced_count += 1

        # Rows are per (type, region, coordinates), so a lookup by type alone
        # gave every row of a multi-region type the last row's figures. Stamp
        # the result on its own row; the CSV reads it from there.
        item["realized"] = {
            "savings": round(savings, 2),
            "intel_equivalent": intel_eq,
            "intel_price_per_hr": round(intel_rate, 6) if intel_rate else 0,
        }

        results.append({
            "graviton_type": raw,
            "region": region,
            "platform": item.get("platform", ""),
            "intel_equivalent": intel_eq,
            "service": service,
            "hours": hours,
            "graviton_cost": round(cost, 2),
            "intel_price_per_hr": round(intel_rate, 6) if intel_rate else 0,
            "graviton_price_per_hr": round(graviton_rate, 6) if graviton_rate else 0,
            "estimated_intel_cost": round(intel_cost, 2),
            "savings": round(savings, 2),
            "savings_pct": savings_pct,
            "pricing_source": pricing_source,
        })

    summary = {
        "total_graviton_cost": round(total_graviton_cost, 2),
        "total_intel_equivalent_cost": round(total_intel_equivalent_cost, 2),
        "total_realized_savings": round(total_savings, 2),
        "avg_savings_pct": round(total_savings / max(total_intel_equivalent_cost, 1) * 100, 1),
        "instance_count": len(results),
        "unpriced_count": unpriced_count,
    }
    return results, summary


# ---------------------------------------------------------------------------
# Direct boto3 CE assessment (GSR pattern)
# ---------------------------------------------------------------------------

# Service configs for getReservationCoverage calls
_COVERAGE_SERVICES = {
    "ec2": {
        "service_filter": "Amazon Elastic Compute Cloud - Compute",
        "group_by": [
            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
            {"Type": "DIMENSION", "Key": "REGION"},
            {"Type": "DIMENSION", "Key": "PLATFORM"},
            {"Type": "DIMENSION", "Key": "TENANCY"},
        ],
    },
    "rds": {
        "service_filter": "Amazon Relational Database Service",
        "group_by": [
            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
            {"Type": "DIMENSION", "Key": "REGION"},
            {"Type": "DIMENSION", "Key": "DATABASE_ENGINE"},
            {"Type": "DIMENSION", "Key": "DEPLOYMENT_OPTION"},
        ],
    },
    "elasticache": {
        "service_filter": "Amazon ElastiCache",
        "group_by": [
            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
            {"Type": "DIMENSION", "Key": "REGION"},
            {"Type": "DIMENSION", "Key": "CACHE_ENGINE"},
        ],
    },
    "opensearch": {
        "service_filter": "Amazon OpenSearch Service",
        "group_by": [
            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
            {"Type": "DIMENSION", "Key": "REGION"},
        ],
    },
}

_PURCHASE_TYPE_SERVICES = [
    "Amazon Elastic Compute Cloud - Compute",
    "Amazon Relational Database Service",
    "Amazon ElastiCache",
    "Amazon OpenSearch Service",
]

# Running hours filter values — restricts to actual instance compute hours
_RUNNING_HOURS_GROUPS = [
    "EC2: Running Hours",
    "RDS: Running Hours",
    "ElastiCache: Running Hours",
    "OpenSearchService: Running Hours",
]

# The usage record types: on-demand, RI-covered and Savings Plan-covered usage.
# Counting only these leaves out every credit, refund and billing adjustment
# without naming them. Checked on a live account: the same total, to the cent,
# as excluding the non-usage types one by one.
_USAGE_RECORD_TYPES = ["Usage", "DiscountedUsage", "SavingsPlanCoveredUsage"]


def _fetch_usage_summary(start_date: str, end_date: str) -> Dict[str, Any]:
    """Authoritative cost and hours per instance type, by region and by platform.

    Eight getCostAndUsage calls: the four purchase types (OD, RI, SP, Spot), each
    grouped twice — INSTANCE_TYPE + REGION and INSTANCE_TYPE + PLATFORM — because
    GroupBy takes two keys and a fleet row needs three. Every call is filtered by:
    - USAGE_TYPE_GROUP = running hours (EC2/RDS/ElastiCache/OpenSearch)
    - PURCHASE_TYPE = the purchase option
    - RECORD_TYPE = usage charges only (no credits, refunds or adjustments)
    - excludes Marketplace

    The previous version grouped by type + platform only and kept whichever
    platform came back last, so every region's spend for a type collapsed onto
    one row (priced in one region) and a Linux/Windows mix was labelled by
    accident.

    Returns:
        {"by_region":   {itype: {region:   {pt: {"cost": c, "hours": h}}}},
         "by_platform": {itype: {platform: {pt: {"cost": c, "hours": h}}}},
         "failed": [label, ...]}
        Totals cover the whole period; _normalize_to_monthly divides them later.
    """
    client = _ce_client()

    # Common filter parts
    marketplace_excl = {"Not": {"Dimensions": {"Key": "BILLING_ENTITY", "Values": ["AWS Marketplace"]}}}
    record_type_excl = {"Dimensions": {"Key": "RECORD_TYPE", "Values": _USAGE_RECORD_TYPES}}
    running_hours_filter = {"Or": [
        {"Dimensions": {"Key": "USAGE_TYPE_GROUP", "Values": [g]}} for g in _RUNNING_HOURS_GROUPS
    ]}

    purchase_types = [
        ("OD", [{"Dimensions": {"Key": "PURCHASE_TYPE", "Values": ["On Demand Instances"]}}]),
        ("RI", [{"Or": [
            {"Dimensions": {"Key": "PURCHASE_TYPE", "Values": ["Convertible Reserved Instances"]}},
            {"Dimensions": {"Key": "PURCHASE_TYPE", "Values": ["Standard Reserved Instances"]}},
        ]}]),
        ("SP", [{"Dimensions": {"Key": "PURCHASE_TYPE", "Values": ["Savings Plans"]}}]),
        ("Spot", [{"Dimensions": {"Key": "PURCHASE_TYPE", "Values": ["Spot Instances"]}}]),
    ]

    out: Dict[str, Any] = {"by_region": {}, "by_platform": {}, "failed": []}

    for pt_label, pt_filters in purchase_types:
        for dim, bucket_name in (("REGION", "by_region"), ("PLATFORM", "by_platform")):
            bucket = out[bucket_name]
            try:
                next_token = None
                while True:
                    kwargs = {
                        "TimePeriod": {"Start": start_date, "End": end_date},
                        "Granularity": "MONTHLY",
                        "Metrics": ["AmortizedCost", "UsageQuantity"],
                        "GroupBy": [
                            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
                            {"Type": "DIMENSION", "Key": dim},
                        ],
                        "Filter": {"And": [
                            marketplace_excl,
                            record_type_excl,
                            *pt_filters,
                            running_hours_filter,
                        ]},
                    }
                    if next_token:
                        kwargs["NextPageToken"] = next_token
                    resp = client.get_cost_and_usage(**kwargs)
                    for tb in resp.get("ResultsByTime", []):
                        for g in tb.get("Groups", []):
                            keys = g.get("Keys", [])
                            if len(keys) < 2:
                                continue
                            itype = normalize_instance_type(keys[0])
                            second = keys[1] or ""
                            cost = float(g["Metrics"]["AmortizedCost"]["Amount"])
                            hours = float(g["Metrics"]["UsageQuantity"]["Amount"])
                            if not itype or (cost == 0 and hours == 0):
                                continue
                            cell = (bucket.setdefault(itype, {}).setdefault(second, {})
                                    .setdefault(pt_label, {"cost": 0.0, "hours": 0.0}))
                            cell["cost"] += cost
                            cell["hours"] += hours
                    next_token = resp.get("NextPageToken")
                    if not next_token:
                        break
            except Exception as e:
                label = f"usage_summary/{pt_label}/{dim.lower()}"
                out["failed"].append(label)
                logger.warning("%s failed: %s: %s", label, type(e).__name__, e)

    logger.info("Usage summary: %d instance types, $%.2f total",
                len(out["by_region"]),
                sum(c["cost"] for regions in out["by_region"].values()
                    for pts in regions.values() for c in pts.values()))
    return out


# ── Fleet rows ──────────────────────────────────────────────────────────────
# One row per (service, instance type, region, pricing coordinates). Pricing
# coordinates are platform + tenancy for EC2, engine + deployment for RDS, and
# engine for ElastiCache; OpenSearch has none.

_PURCHASE_TYPES = ("OD", "RI", "SP", "Spot")
_PT_COST_FIELD = {"OD": "cost_od", "RI": "cost_ri", "SP": "cost_sp", "Spot": "cost_spot"}

# Row fields that are totals over the analysis period. _normalize_to_monthly
# divides every one of them, so all of them describe the same month.
_ADDITIVE_FIELDS = (
    "cost", "hours", "cost_od", "cost_ri", "cost_sp", "cost_spot",
    "od_cost", "ri_cost", "sp_cost", "spot_cost", "ri_savings",
    "ri_unused_hours", "od_hours", "reserved_hours", "split_estimated_cost",
)


def _canon_platform(platform: str) -> str:
    """Comparable form of a CE platform string ("Windows (Amazon VPC)" -> "windows")."""
    return re.sub(r"\s*\(amazon vpc\)$", "", (platform or "").strip().lower())


def _coverage_coords(svc: str, row: Dict) -> tuple:
    if svc == "ec2":
        return (row.get("platform", "") or "", row.get("tenancy", "") or "")
    if svc == "rds":
        return (row.get("database_engine", "") or "", row.get("deployment_option", "") or "")
    if svc == "elasticache":
        return (row.get("cache_engine", "") or "",)
    return ()


def _ipf(seeds: Dict[tuple, float], row_totals: Dict, col_totals: Dict,
         iterations: int = 60, _open: bool = False) -> Dict[tuple, float]:
    """Fit a (row, col) table to both margins, starting from `seeds`.

    Iterative proportional fitting. Rows are regions and columns platforms here:
    Cost Explorer gives exact region totals and exact platform totals for a type
    but not the cross-tab, and the coverage data supplies the starting shape. A
    margin entry with no seeded cell is seeded from the independence estimate so
    its spend has somewhere to go. Finishes on the row margin, because region is
    what pricing and target availability depend on.
    """
    cells = {k: v for k, v in seeds.items()
             if v > 0 and k[0] in row_totals and k[1] in col_totals}
    total = sum(row_totals.values())
    if total <= 0:
        return {}
    col_total = sum(col_totals.values()) or total
    for r, r_tot in row_totals.items():
        if r_tot > 0 and not any(cells.get((r, c), 0) > 0 for c in col_totals):
            for c, c_tot in col_totals.items():
                if c_tot > 0:
                    cells[(r, c)] = cells.get((r, c), 0) + r_tot * c_tot / col_total
    for c, c_tot in col_totals.items():
        if c_tot > 0 and not any(cells.get((r, c), 0) > 0 for r in row_totals):
            for r, r_tot in row_totals.items():
                if r_tot > 0:
                    cells[(r, c)] = cells.get((r, c), 0) + r_tot * c_tot / col_total

    def _scale(axis: int, totals: Dict):
        sums: Dict = {}
        for k, v in cells.items():
            sums[k[axis]] = sums.get(k[axis], 0) + v
        for k in cells:
            s = sums.get(k[axis], 0)
            cells[k] = cells[k] * totals.get(k[axis], 0) / s if s > 0 else 0.0

    if not col_totals:
        _scale(0, row_totals)
        return cells
    for _ in range(iterations):
        _scale(0, row_totals)
        _scale(1, col_totals)
    _scale(0, row_totals)

    # The seeds can rule out the only cells a margin could go to: coverage shows
    # a region on RHEL alone, while the type's Savings Plan spend there is
    # mostly Linux. Then no fit meets both margins, and finishing on regions
    # silently moves platform spend. Refit with every cell open, the seeds kept
    # as the starting shape.
    col_sums: Dict = {}
    for (r, c), v in cells.items():
        col_sums[c] = col_sums.get(c, 0) + v
    worst = max((abs(col_sums.get(c, 0) - t) for c, t in col_totals.items()), default=0)
    if worst > 1e-6 * max(total, 1.0) and not _open:
        open_seeds = dict(cells)
        for r, r_tot in row_totals.items():
            for c, c_tot in col_totals.items():
                if r_tot > 0 and c_tot > 0:
                    open_seeds[(r, c)] = open_seeds.get((r, c), 0) + 0.01 * r_tot * c_tot / col_total
        return _ipf(open_seeds, row_totals, col_totals, iterations * 4, _open=True)
    return cells


def _classify_row(itype: str, svc: str) -> Optional[dict]:
    """Classify an instance type into a fleet-row dict, or None."""
    itype = normalize_instance_type(itype, svc)
    if svc == "rds":
        usage_type = f"InstanceUsage:{itype}"
    elif svc == "elasticache":
        usage_type = f"NodeUsage:{itype}"
    else:
        usage_type = f"BoxUsage:{itype}"
    info = classify_usage_type(usage_type)
    if not info:
        return None
    from dataclasses import asdict
    d = asdict(info)
    d["service"] = svc
    d["raw"] = _expand_size(d.get("raw", ""))
    if d.get("graviton_upgrade"):
        d["graviton_upgrade"] = _expand_size(d["graviton_upgrade"])
    d["gen_bucket"] = generation_bucket(info.generation, info.is_graviton)
    d["nih_factor"] = _nih_factor(d.get("size", ""))
    return d


def _unclassified_row(itype: str, svc: str) -> dict:
    """A row for spend whose type the classifier cannot parse (u-6tb1.metal).

    It used to be dropped, which removed its spend from the total and inflated
    the Graviton share. It stays in every total, has no Graviton target, and is
    listed under data quality.
    """
    base = itype[:-len(".search")] if itype.endswith(".search") else itype
    size = base.rsplit(".", 1)[-1] if "." in base else ""
    return {
        "raw": itype, "service": svc, "prefix": "", "family": "", "generation": 0,
        "suffix": "", "size": size, "is_graviton": False, "is_amd": False,
        "is_intel": False, "category": "other", "gen_label": "Unclassified",
        "gen_bucket": "Unclassified", "nih_factor": _nih_factor(size),
        "graviton2": None, "graviton3": None, "graviton4": None, "graviton5": None,
        "graviton_upgrade": None, "intel_upgrade": None, "previous_intel": None,
        "variant": "", "type_suffix": "", "target_size": size, "size_basis": "",
        "unclassified": True,
        "reason": "Instance type not recognised by the classifier",
    }


def _build_fleet_rows(coverage_rows: List[Dict], ri_rows: List[Dict],
                      sp_cost_data: Dict[tuple, float],
                      spot_cost_data: Dict[tuple, float],
                      usage_summary: Dict[str, Any]) -> List[Dict]:
    """One row per (service, type, region, pricing coordinates), with authoritative cost.

    Cost and hours come from the usage summary (exact per region and per
    platform), split across coordinates using the coverage data. Types the
    summary did not return (or purchase types whose summary pull failed) use the
    detail pulls instead: coverage for OD, RI utilization for RI, and the SP and
    Spot pulls. RI term metadata is attached from the RI utilization rows of the
    same type and region.
    """
    failed = set((usage_summary or {}).get("failed", []))
    by_region = (usage_summary or {}).get("by_region", {})
    by_platform = (usage_summary or {}).get("by_platform", {})

    svc_of: Dict[str, str] = {}
    cov: Dict[tuple, Dict[tuple, Dict[str, float]]] = {}
    for row in coverage_rows:
        svc = row.get("service") or "ec2"
        it = normalize_instance_type(row.get("instance_type", ""), svc)
        if not it:
            continue
        svc_of.setdefault(it, svc)
        c = cov.setdefault((it, row.get("region", "")), {}).setdefault(
            _coverage_coords(svc, row),
            {"hours": 0.0, "od_hours": 0.0, "reserved_hours": 0.0, "od_cost": 0.0})
        c["hours"] += row.get("total_hours", 0) or 0
        c["od_hours"] += row.get("od_hours", 0) or 0
        c["reserved_hours"] += row.get("reserved_hours", 0) or 0
        c["od_cost"] += row.get("od_cost", 0) or 0

    ri_agg: Dict[tuple, Dict] = {}
    ri_by_platform: Dict[tuple, Dict] = {}
    ri_platforms: Dict[tuple, set] = {}
    for ri in ri_rows:
        svc = ri.get("service") or "ec2"
        it = normalize_instance_type(ri.get("instance_type", ""), svc)
        if not it:
            continue
        svc_of.setdefault(it, svc)
        entry = ri_agg.setdefault((it, ri.get("region", "")), {
            "cost": 0.0, "savings": 0.0, "hours": 0.0, "unused_hours": 0.0,
            "purchased": 0.0, "_max": -1.0})
        entry["cost"] += ri.get("total_amortized", 0) or 0
        entry["purchased"] += ri.get("purchased_hours", 0) or 0
        entry["savings"] += ri.get("net_ri_savings", 0) or 0
        entry["hours"] += ri.get("actual_hours", 0) or 0
        entry["unused_hours"] += ri.get("unused_hours", 0) or 0
        # The same per (type, region, platform). A Windows RI's rate and terms
        # must not be read as a Linux row's, so rows take metadata from their
        # own platform's subscriptions first.
        plat = _canon_platform(ri.get("platform", ""))
        ri_platforms.setdefault((it, ri.get("region", "")), set()).add(plat)
        pentry = ri_by_platform.setdefault((it, ri.get("region", ""), plat), {
            "cost": 0.0, "savings": 0.0, "hours": 0.0, "unused_hours": 0.0,
            "purchased": 0.0, "_max": -1.0})
        pentry["cost"] += ri.get("total_amortized", 0) or 0
        pentry["purchased"] += ri.get("purchased_hours", 0) or 0
        pentry["savings"] += ri.get("net_ri_savings", 0) or 0
        pentry["hours"] += ri.get("actual_hours", 0) or 0
        pentry["unused_hours"] += ri.get("unused_hours", 0) or 0
        for e in (entry, pentry):
            # Term metadata from the largest subscription, as the most representative.
            if (ri.get("total_amortized", 0) or 0) > e["_max"]:
                e["_max"] = ri.get("total_amortized", 0) or 0
                e["offering_type"] = ri.get("offering_type", "")
                e["effective_hourly_rate"] = ri.get("effective_hourly_rate", 0)
                e["od_hourly_rate"] = ri.get("od_hourly_rate", 0)
                e["lease"] = ri.get("lease", "")
                e["payment_option"] = ri.get("payment_option", "")
                e["offering_class"] = ri.get("offering_class", "")

    detail_cost: Dict[str, Dict[tuple, float]] = {"SP": {}, "Spot": {}}
    for label, data in (("SP", sp_cost_data), ("Spot", spot_cost_data)):
        for (itype, region, svc), cost in (data or {}).items():
            it = normalize_instance_type(itype, svc)
            if not it or cost <= 0:
                continue
            svc_of.setdefault(it, svc)
            key = (it, region)
            detail_cost[label][key] = detail_cost[label].get(key, 0) + cost

    def _detail_region_totals(it: str, pt: str) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        if pt == "OD":
            for (t, region), sub in cov.items():
                if t == it:
                    out[region] = {"cost": sum(c["od_cost"] for c in sub.values()),
                                   "hours": sum(c["od_hours"] for c in sub.values())}
        elif pt == "RI":
            for (t, region), e in ri_agg.items():
                if t == it:
                    out[region] = {"cost": e["cost"], "hours": e["hours"]}
        else:
            for (t, region), cost in detail_cost[pt].items():
                if t == it:
                    out[region] = {"cost": cost, "hours": 0.0}
        return out

    types = (set(by_region) | {t for t, _ in cov} | {t for t, _ in ri_agg}
             | {t for t, _ in detail_cost["SP"]} | {t for t, _ in detail_cost["Spot"]})

    rows: List[Dict] = []
    for it in sorted(types):
        svc = svc_of.get(it) or service_for_type(it)
        cells: Dict[tuple, Dict[str, Dict[str, float]]] = {}
        platform_display: Dict[str, str] = {}
        # Cells fitted per platform (one row per platform, all tenancies), as
        # opposed to one row per coverage coordinate group.
        platform_cells: set = set()

        for pt in _PURCHASE_TYPES:
            if it in by_region and f"usage_summary/{pt}/region" not in failed:
                region_tot = {r: v[pt] for r, v in by_region[it].items() if pt in v}
            elif it in by_region:
                region_tot = _detail_region_totals(it, pt)
            else:
                region_tot = _detail_region_totals(it, pt)
            region_tot = {r: v for r, v in region_tot.items()
                          if (v.get("cost") or 0) or (v.get("hours") or 0)}
            if not region_tot:
                continue

            plat_tot = {}
            if svc == "ec2" and f"usage_summary/{pt}/platform" not in failed:
                for plat, v in (by_platform.get(it) or {}).items():
                    if pt in v:
                        canon = _canon_platform(plat)
                        platform_display.setdefault(canon, plat)
                        prev = plat_tot.setdefault(canon, {"cost": 0.0, "hours": 0.0})
                        prev["cost"] += v[pt]["cost"]
                        prev["hours"] += v[pt]["hours"]

            if plat_tot:
                # Seeds come from this purchase type's own evidence: on-demand
                # hours for OD, reserved hours for RI. Coverage carries nothing
                # on Savings Plan or Spot usage, so those start from an even
                # spread and take their shape from the two margins alone.
                seed_field = {"OD": "od_hours", "RI": "reserved_hours"}.get(pt)
                seeds: Dict[tuple, float] = {}
                tenancy_hours: Dict[tuple, Dict[str, float]] = {}
                for region in region_tot:
                    for (plat, ten), c in cov.get((it, region), {}).items():
                        canon = _canon_platform(plat)
                        if seed_field:
                            seeds[(region, canon)] = seeds.get((region, canon), 0) + c[seed_field]
                        th = tenancy_hours.setdefault((region, canon), {})
                        th[ten] = th.get(ten, 0) + c["hours"]
                cost_cells = _ipf(seeds, {r: v["cost"] for r, v in region_tot.items()},
                                  {p: v["cost"] for p, v in plat_tot.items()})
                hour_cells = _ipf(seeds, {r: v["hours"] for r, v in region_tot.items()},
                                  {p: v["hours"] for p, v in plat_tot.items()})
                for key in set(cost_cells) | set(hour_cells):
                    region, canon = key
                    th = tenancy_hours.get(key) or {}
                    tenancy = max(th, key=th.get) if th else ""
                    coords = (platform_display.get(canon, canon), tenancy)
                    platform_cells.add((region, coords))
                    cell = cells.setdefault((region, coords), {})
                    cell[pt] = {"cost": cost_cells.get(key, 0.0),
                                "hours": hour_cells.get(key, 0.0),
                                # SP and Spot have no per-cell evidence: with
                                # several regions AND platforms the split is
                                # fitted to the two margins, not measured.
                                "est": (not seed_field and len(region_tot) > 1
                                        and len(plat_tot) > 1)}
            else:
                for region, tot in region_tot.items():
                    sub = cov.get((it, region), {}) or {_coverage_coords(svc, {}): None}
                    # Hours split by each coordinate group's running hours. Cost
                    # split by hours x that group's own on-demand rate, because
                    # the groups do not cost the same per hour: a SQL Server
                    # license-included hour costs several PostgreSQL hours.
                    #
                    # Each purchase type is split by its own hours: OD spend by
                    # on-demand hours, RI spend by reserved hours. Splitting every
                    # type by total hours moved one engine's RI spend onto another
                    # engine's on-demand row. SP and Spot hours are not reserved
                    # hours, so they follow the on-demand hours.
                    rates = {k: c["od_cost"] / c["od_hours"]
                             for k, c in sub.items() if c and c["od_hours"] > 0 and c["od_cost"] > 0}
                    mean_rate = sum(rates.values()) / len(rates) if rates else 1.0
                    basis = "reserved_hours" if pt == "RI" else "od_hours"
                    hour_w = {k: (c[basis] if c else 1.0) for k, c in sub.items()}
                    if not any(hour_w.values()):
                        hour_w = {k: (c["hours"] if c else 1.0) for k, c in sub.items()}
                    cost_w = {k: hour_w[k] * rates.get(k, mean_rate) for k in sub}
                    h_total, c_total = sum(hour_w.values()), sum(cost_w.values())
                    n = len(sub)
                    for coords in sub:
                        h_share = hour_w[coords] / h_total if h_total > 0 else 1.0 / n
                        c_share = cost_w[coords] / c_total if c_total > 0 else 1.0 / n
                        cell = cells.setdefault((region, coords), {})
                        cell[pt] = {"cost": tot["cost"] * c_share,
                                    "hours": tot["hours"] * h_share}

        base = _classify_row(it, svc)
        # RI cost per region across this type's cells, to share RI metadata out.
        ri_cost_by_region: Dict[str, float] = {}
        for (region, _), pts in cells.items():
            ri_cost_by_region[region] = ri_cost_by_region.get(region, 0) + pts.get("RI", {}).get("cost", 0)

        for (region, coords), pts in sorted(cells.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            cost_by_pt = {pt: pts[pt]["cost"] for pt in pts}
            hours = sum(pts[pt]["hours"] for pt in pts)
            cost = sum(cost_by_pt.values())
            if cost <= 0 and hours <= 0:
                continue
            d = dict(base) if base else _unclassified_row(it, svc)
            d["region"] = region
            d["database_engine"] = d["cache_engine"] = d["deployment_option"] = ""
            d["platform"] = d["tenancy"] = ""
            if svc == "ec2":
                d["platform"], d["tenancy"] = coords
            elif svc == "rds":
                d["database_engine"], d["deployment_option"] = coords
            elif svc == "elasticache":
                d["cache_engine"] = coords[0]
            primary = max(cost_by_pt, key=cost_by_pt.get) if cost_by_pt else "OD"
            d.update(
                cost=cost, hours=hours, purchase_type=primary,
                effective_rate=round(cost / hours, 4) if hours > 0 else 0,
                **{_PT_COST_FIELD[pt]: cost_by_pt.get(pt, 0.0) for pt in _PURCHASE_TYPES},
            )
            # Spend on this row whose region x platform split was estimated
            # (see "est" above). Reported, so the reader knows it is modelled.
            d["split_estimated_cost"] = sum(
                pts[pt]["cost"] for pt in pts if pts[pt].get("est"))
            d["od_cost"] = d["cost_od"]
            d["sp_cost"] = d["cost_sp"]
            d["spot_cost"] = d["cost_spot"]

            # Coverage statistics for this cell's coordinates.
            sub = cov.get((it, region), {})
            if (region, coords) in platform_cells:
                match = [c for k, c in sub.items()
                         if _canon_platform(k[0]) == _canon_platform(coords[0])]
            else:
                # One row per coordinate group: only that group's hours, or
                # every row on the platform would count all of its hours.
                match = [c for k, c in sub.items() if k == coords]
            od_h = sum(c["od_hours"] for c in match)
            res_h = sum(c["reserved_hours"] for c in match)
            d["od_hours"], d["reserved_hours"] = od_h, res_h
            d["coverage_pct"] = round(res_h / (od_h + res_h) * 100, 1) if (od_h + res_h) > 0 else 0

            ri_all = ri_agg.get((it, region))
            if ri_all and d["cost_ri"] > 0:
                share = d["cost_ri"] / ri_cost_by_region[region] if ri_cost_by_region.get(region) else 1.0
                d["ri_cost"] = d["cost_ri"]
                d["ri_savings"] = ri_all["savings"] * share
                d["ri_unused_hours"] = ri_all["unused_hours"] * share
                # Rate and terms: this row's own platform/engine subscriptions,
                # or the type's only set of subscriptions; never another
                # platform's when several are present.
                own = _canon_platform(d["platform"] if svc == "ec2"
                                      else (d["database_engine"] or d["cache_engine"]))
                plats = ri_platforms.get((it, region), set())
                ri = ri_by_platform.get((it, region, own))
                if ri is None and len(plats) <= 1:
                    ri = ri_all
                if ri is not None:
                    d["ri_offering_type"] = ri.get("offering_type", "")
                    # Per instance-hour: amortized fee over purchased hours.
                    # Cost Explorer's effectiveHourlyRate attribute is for the
                    # whole subscription (rate x instances: $5.81/h for twelve
                    # m5.4xlarge at $0.484), and dividing a per-instance
                    # Graviton rate by it reported ~93% RI savings.
                    d["ri_effective_hourly_rate"] = (
                        round(ri["cost"] / ri["purchased"], 6) if ri.get("purchased") else 0)
                    d["ri_od_hourly_rate"] = ri.get("od_hourly_rate", 0)
                    d["ri_lease"] = ri.get("lease", "")
                    d["ri_payment_option"] = ri.get("payment_option", "")
                    d["ri_offering_class"] = ri.get("offering_class", "")
            rows.append(d)
    return rows


def _months_in_period(start_date: str, end_date: str) -> float:
    """Length of [start, end) in months: whole calendar months when both are the 1st."""
    from datetime import date
    s, e = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if e <= s:
        # Clamping this to a day once turned an inverted range into a divisor
        # of ~0.033, scaling every "monthly" figure about 30x.
        raise ValueError(f"empty or inverted period: {start_date} to {end_date} "
                         "(start is inclusive, end exclusive)")
    if s.day == 1 and e.day == 1:
        months = (e.year - s.year) * 12 + (e.month - s.month)
        if months > 0:
            return float(months)
    return max((e - s).days, 1) / (365.25 / 12)


def _normalize_to_monthly(rows: List[Dict], months: float) -> None:
    """Turn period totals into monthly averages, in place.

    The reports label figures "monthly" and multiply savings by 12 for the annual
    figure. Before this, a three-month run (which SKILL.md suggests) reported
    three months of spend as one month, and an annual figure three times too
    high.
    """
    for r in rows:
        for f in _ADDITIVE_FIELDS:
            v = r.get(f)
            if isinstance(v, (int, float)):
                r[f] = round(v / months, 2)


# What the spend figures are, stated in every report header. It matches the
# usage-summary filter (_USAGE_RECORD_TYPES).
_SPEND_BASIS = ('Amortized cost of instance running hours (EC2, RDS, ElastiCache, OpenSearch) from AWS Cost Explorer, counting usage charges only; credits, refunds, other billing adjustments and AWS Marketplace are excluded.')

# Error-list prefixes written by the Cost Explorer fetchers when a pull fails.
_CE_PULL_PREFIXES = ("coverage/", "ri_util/", "purchase_type/")


def _data_completeness(usage_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Which Cost Explorer pulls failed, so a partial fleet is never reported as whole."""
    failed = list((usage_summary or {}).get("failed", []))
    if not (usage_summary or {}).get("by_region") and "usage_summary" not in failed:
        failed.append("usage_summary")
    failed += [e.split(":", 1)[0] for e in _pricing_errors if e.startswith(_CE_PULL_PREFIXES)]
    seen = []
    for f in failed:
        if f not in seen:
            seen.append(f)
    return {"complete": not seen, "failed_pulls": seen}


def _as_regional(od_prices, types_by_region: Dict[str, set]) -> RegionalPrices:
    """Accept the resolver's result as regional price books.

    A flat dict (a resolver that predates regional books) is split by the region
    each type was requested for.
    """
    if isinstance(od_prices, RegionalPrices):
        return od_prices
    books = RegionalPrices()
    for region, types in types_by_region.items():
        book = books.book(region)
        for t in types:
            if t in (od_prices or {}):
                book[t] = od_prices[t]
    return books


# Normalization factors for computing NIH (Normalized Instance Hours)
# Based on EC2 instance size normalization: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ri-modification-instancemove.html
# Re-exported from fleet_tools, which owns the single size table that the size
# LADDER is also derived from. This module kept its own copy, and the two drifted:
# the copy here had no "3xlarge" (so those rows scored 4 instead of 24, a 6x
# understatement) while the ladder had no "10xlarge" or "metal".
_NIH_FACTORS = SIZE_NIH_FACTORS
_nih_factor = nih_factor


def _ce_client():
    """Create a Cost Explorer boto3 client.

    Returns:
        boto3 CE client.
    """
    import boto3
    return boto3.client("ce", region_name="us-east-1")


def _fetch_reservation_coverage(start_date: str, end_date: str,
                                services: Optional[List[str]] = None) -> List[Dict]:
    """Fetch getReservationCoverage for up to 4 services.

    Returns instance-level OD/reserved hours with dimensions
    (engine, deploy, region, platform, tenancy).

    Args:
        start_date: YYYY-MM-DD start of analysis period.
        end_date: YYYY-MM-DD end of analysis period.
        services: Optional list of service keys to query.

    Returns:
        List of dicts with instance-level coverage data.
    """
    client = _ce_client()
    rows = []
    svc_filter = services or list(_COVERAGE_SERVICES.keys())

    for svc_key in svc_filter:
        cfg = _COVERAGE_SERVICES.get(svc_key)
        if not cfg:
            continue
        try:
            next_token = None
            while True:
                kwargs = {
                    "TimePeriod": {"Start": start_date, "End": end_date},
                    "Filter": {
                        "Dimensions": {"Key": "SERVICE", "Values": [cfg["service_filter"]]}
                    },
                    "GroupBy": cfg["group_by"],
                    "Metrics": ["Hour", "Cost"],
                }
                if next_token:
                    kwargs["NextPageToken"] = next_token
                resp = client.get_reservation_coverage(**kwargs)
                for tb in resp.get("CoveragesByTime", []):
                    for g in tb.get("Groups", []):
                        a = g.get("Attributes", {})
                        h = g.get("Coverage", {}).get("CoverageHours", {})
                        c = g.get("Coverage", {}).get("CoverageCost", {})
                        itype = a.get("instanceType", "")
                        if not itype:
                            continue
                        rows.append({
                            "instance_type": itype,
                            "region": a.get("region", ""),
                            "service": svc_key,
                            "platform": a.get("platform", ""),
                            "tenancy": a.get("tenancy", ""),
                            "database_engine": a.get("databaseEngine", ""),
                            "cache_engine": a.get("cacheEngine", ""),
                            "deployment_option": a.get("deploymentOption", ""),
                            "od_hours": float(h.get("OnDemandHours", 0)),
                            "reserved_hours": float(h.get("ReservedHours", 0)),
                            "total_hours": float(h.get("TotalRunningHours", 0)),
                            "coverage_pct": float(h.get("CoverageHoursPercentage", 0)),
                            "od_cost": float(c.get("OnDemandCost", 0)),
                        })
                next_token = resp.get("NextPageToken")
                if not next_token:
                    break
        except Exception as e:
            _pricing_errors.append(f"coverage/{svc_key}: {type(e).__name__}: {e}")
            if _is_auth_error(e):
                _pricing_errors.append("FATAL: Credential error on getReservationCoverage")
                break
    return rows


def _safe_float(val, default=0.0) -> float:
    """Safely convert a value to float, returning default for N/A or invalid values."""
    if val is None or val == "" or val == "N/A":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _ri_lease_from_dates(start: str, end: str) -> str:
    """"1yr"/"3yr" from a reservation's start and end timestamps, "" if neither.

    The term used to be guessed from a "3yr" substring of the offering type,
    which the attribute never contains, so every reservation was treated as a
    1-year one. A Marketplace reservation can have any remaining length; only
    lengths close to a standard term are classified.
    """
    from datetime import datetime

    def _parse(v):
        v = (v or "").strip()
        if not v:
            return None
        v = v.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            try:
                return datetime.strptime(v[:10], "%Y-%m-%d")
            except ValueError:
                return None

    a, b = _parse(start), _parse(end)
    if not a or not b:
        return ""
    if a.tzinfo is not None and b.tzinfo is None:
        b = b.replace(tzinfo=a.tzinfo)
    elif b.tzinfo is not None and a.tzinfo is None:
        a = a.replace(tzinfo=b.tzinfo)
    days = (b - a).days
    if 330 <= days <= 400:
        return "1yr"
    if 1000 <= days <= 1130:
        return "3yr"
    return ""


def _ri_terms_from_attributes(attrs: Dict, service: str) -> Tuple[str, str, str]:
    """(lease, payment_option, offering_class) of one reservation's CE attributes.

    The payment option and class are read from whichever of the descriptive
    attributes carries them, because the API reference does not enumerate the
    attribute keys. The lease comes from startDateTime/endDateTime, falling back
    to a term written in those strings. RDS, ElastiCache and OpenSearch sell one
    reservation class, so theirs is "standard". "" means not determined.
    """
    text = " ".join(str(attrs.get(k, "")) for k in (
        "offeringType", "subscriptionType", "offeringClass", "paymentOption",
        "purchaseOption")).lower().replace("_", " ")
    if "all upfront" in text:
        payment = "All Upfront"
    elif "partial upfront" in text:
        payment = "Partial Upfront"
    elif "no upfront" in text:
        payment = "No Upfront"
    else:
        payment = ""
    if "convertible" in text:
        offering_class = "convertible"
    elif "standard" in text or service != "ec2":
        offering_class = "standard"
    else:
        offering_class = ""
    lease = _ri_lease_from_dates(attrs.get("startDateTime", ""), attrs.get("endDateTime", ""))
    if not lease:
        if "3yr" in text or "3 yr" in text or "3 year" in text:
            lease = "3yr"
        elif "1yr" in text or "1 yr" in text or "1 year" in text:
            lease = "1yr"
    return lease, payment, offering_class


def _fetch_reservation_utilization(start_date: str, end_date: str,
                                   services: Optional[List[str]] = None) -> List[Dict]:
    """Fetch getReservationUtilization for up to 4 services.

    Returns per-RI subscription details grouped by SUBSCRIPTION_ID.

    Args:
        start_date: YYYY-MM-DD start of analysis period.
        end_date: YYYY-MM-DD end of analysis period.
        services: Optional list of service keys to query.

    Returns:
        List of dicts with per-RI utilization data.
    """
    client = _ce_client()
    rows = []
    svc_filter = services or list(_COVERAGE_SERVICES.keys())

    for svc_key in svc_filter:
        cfg = _COVERAGE_SERVICES.get(svc_key)
        if not cfg:
            continue
        try:
            next_token = None
            while True:
                kwargs = {
                    "TimePeriod": {"Start": start_date, "End": end_date},
                    "Filter": {
                        "Dimensions": {"Key": "SERVICE", "Values": [cfg["service_filter"]]}
                    },
                    "GroupBy": [{"Type": "DIMENSION", "Key": "SUBSCRIPTION_ID"}],
                    "SortBy": {"Key": "UtilizationPercentage", "SortOrder": "ASCENDING"},
                    "MaxResults": 3000,
                }
                if next_token:
                    kwargs["NextPageToken"] = next_token
                resp = client.get_reservation_utilization(**kwargs)
                for tb in resp.get("UtilizationsByTime", []):
                    for g in tb.get("Groups", []):
                        a = g.get("Attributes", {})
                        u = g.get("Utilization", {})
                        itype = a.get("instanceType", "")
                        if not itype:
                            continue
                        lease, payment_option, offering_class = (
                            _ri_terms_from_attributes(a, svc_key))
                        rows.append({
                            "instance_type": itype,
                            "region": a.get("region", ""),
                            "service": svc_key,
                            "subscription_id": a.get("subscriptionId", ""),
                            "offering_type": a.get("offeringType", ""),
                            # The reservation's terms, for pricing its Graviton
                            # target at the same term (see _lookup_rate_for_type).
                            "lease": lease,
                            "payment_option": payment_option,
                            "offering_class": offering_class,
                            "platform": a.get("platform", ""),
                            "utilization_pct": _safe_float(u.get("UtilizationPercentage")),
                            "purchased_hours": _safe_float(u.get("PurchasedHours")),
                            "actual_hours": _safe_float(u.get("TotalActualHours")),
                            "unused_hours": _safe_float(u.get("UnusedHours")),
                            "od_cost_equivalent": _safe_float(u.get("OnDemandCostOfRIHoursUsed")),
                            "net_ri_savings": _safe_float(u.get("NetRISavings")),
                            "total_amortized": _safe_float(u.get("TotalAmortizedFee")),
                            "ri_cost_unused": _safe_float(u.get("RICostForUnusedHours")),
                            "effective_hourly_rate": _safe_float(a.get("effectiveHourlyRate")),
                            "od_hourly_rate": _safe_float(a.get("averageOnDemandHourlyRate")),
                        })
                next_token = resp.get("NextPageToken")
                if not next_token:
                    break
        except Exception as e:
            _pricing_errors.append(f"ri_util/{svc_key}: {type(e).__name__}: {e}")
            if _is_auth_error(e):
                _pricing_errors.append("FATAL: Credential error on getReservationUtilization")
                break
    return rows


def _fetch_purchase_type_cost(start_date: str, end_date: str,
                              purchase_type: str, label: str) -> Dict[tuple, float]:
    """Fetch getCostAndUsage with purchase type filter, per service (GSR pattern).

    Makes one CE call per service to get accurate service attribution.
    Returns {(instance_type_lower, region, service): cost}.
    Groups by USAGE_TYPE + REGION to avoid multi-region cost inflation.

    Args:
        start_date: YYYY-MM-DD start of analysis period.
        end_date: YYYY-MM-DD end of analysis period.
        purchase_type: Purchase type filter value (e.g., "Savings Plans").
        label: Label for error reporting.

    Returns:
        Dict mapping (instance_type, region, service) tuples to cost amounts.
    """
    # Map CE service name → our internal service key
    _SERVICE_NAME_TO_KEY = {
        "Amazon Elastic Compute Cloud - Compute": "ec2",
        "Amazon Relational Database Service": "rds",
        "Amazon ElastiCache": "elasticache",
        "Amazon OpenSearch Service": "opensearch",
    }

    client = _ce_client()
    result: Dict[tuple, float] = {}

    for ce_service_name, svc_key in _SERVICE_NAME_TO_KEY.items():
        try:
            next_token = None
            while True:
                kwargs = {
                    "TimePeriod": {"Start": start_date, "End": end_date},
                    "Granularity": "MONTHLY",
                    "Metrics": ["AmortizedCost", "UsageQuantity"],
                    "GroupBy": [
                        {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
                        {"Type": "DIMENSION", "Key": "REGION"},
                    ],
                    "Filter": {"And": [
                        {"Not": {"Dimensions": {
                            "Key": "BILLING_ENTITY", "Values": ["AWS Marketplace"]
                        }}},
                        {"Dimensions": {"Key": "PURCHASE_TYPE", "Values": [purchase_type]}},
                        {"Dimensions": {"Key": "SERVICE", "Values": [ce_service_name]}},
                        {"Dimensions": {"Key": "RECORD_TYPE", "Values": _USAGE_RECORD_TYPES}},
                    ]},
                }
                if next_token:
                    kwargs["NextPageToken"] = next_token
                resp = client.get_cost_and_usage(**kwargs)
                for tb in resp.get("ResultsByTime", []):
                    for g in tb.get("Groups", []):
                        keys = g.get("Keys", [])
                        if len(keys) < 2:
                            continue
                        ut = keys[0]
                        region = keys[1]
                        if ":" not in ut:
                            continue
                        itype = _expand_size(ut.split(":", 1)[1]).lower()
                        cost = float(
                            g.get("Metrics", {}).get("AmortizedCost", {}).get("Amount", 0)
                        )
                        if cost > 0:
                            lookup_key = (itype, region, svc_key)
                            result[lookup_key] = result.get(lookup_key, 0) + cost
                next_token = resp.get("NextPageToken")
                if not next_token:
                    break
        except Exception as e:
            _pricing_errors.append(f"purchase_type/{label}/{svc_key}: {type(e).__name__}: {e}")
    return result


def estimate_graviton_savings(
    start_date: str = "",
    end_date: str = "",
    services: Optional[List[str]] = None,
    target_strategy: str = "latest",
) -> dict:
    """Estimate Graviton migration savings for an AWS account.

    Performs direct boto3 CE calls to assess the fleet:
    4 coverage + 4 RI utilization + 2 purchase type (SP/Spot).
    OD cost from getReservationCoverage.
    Total cost = OD + SP + Spot + RI amortized.
    Then: classify -> price -> score -> migrate -> engine readiness.

    Requires local AWS credentials with permissions:
    ce:GetReservationCoverage, ce:GetReservationUtilization,
    ce:GetCostAndUsage, pricing:GetProducts, sts:GetCallerIdentity.

    Args:
        start_date: YYYY-MM-DD. Default: first of last month.
        end_date: YYYY-MM-DD. Default: first of current month.
        services: Optional filter. Default: all 4 services.
        target_strategy: Graviton target selection strategy. Valid values:
            "latest" (default) — target n+1 generation Graviton.
            "cheapest" — picks cheapest Graviton generation.
            "same_gen" — match source x86 generation.
            Omit for direct credentials.

    Returns:
        Complete assessment result dict with summary, score, migration_plan,
        engine_readiness, and classified_detail.
    """
    from datetime import datetime

    # Default date range: last full month
    if not end_date:
        today = datetime.now().date()
        end_date = today.replace(day=1).strftime("%Y-%m-%d")
    if not start_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_dt.month == 1:
            start_date = end_dt.replace(
                year=end_dt.year - 1, month=12, day=1
            ).strftime("%Y-%m-%d")
        else:
            start_date = end_dt.replace(
                month=end_dt.month - 1, day=1
            ).strftime("%Y-%m-%d")
    # Validated after the defaults are filled in, not before: a lone start date
    # after the defaulted end is otherwise never compared with it.
    if start_date >= end_date:
        raise ValueError(f"--start-date ({start_date}) must be before the end "
                         f"date ({end_date}); the end is exclusive")

    _pricing_errors.clear()
    # Module-level, so a second assessment in one process would otherwise report
    # the first run's phases alongside its own.
    _phase_timings.clear()

    logger.info("Assessment started: date_range=%s to %s, services=%s, target_strategy=%s",
                start_date, end_date, services or "all", target_strategy or "none")
    t0 = time.time()

    # --- Step 1: Pull all CE data (parallel) ---
    from concurrent.futures import ThreadPoolExecutor

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            f_coverage = pool.submit(
                _fetch_reservation_coverage, start_date, end_date, services
            )
            f_ri = pool.submit(
                _fetch_reservation_utilization, start_date, end_date, services
            )
            f_sp = pool.submit(
                _fetch_purchase_type_cost, start_date, end_date, "Savings Plans", "sp"
            )
            f_spot = pool.submit(
                _fetch_purchase_type_cost, start_date, end_date, "Spot Instances", "spot"
            )
            f_summary = pool.submit(
                _fetch_usage_summary, start_date, end_date
            )

        coverage_rows = f_coverage.result()
        ri_rows = f_ri.result()
        sp_cost_data = f_sp.result()
        spot_cost_data = f_spot.result()
        usage_summary = f_summary.result()

    except ImportError:
        return {"error": "boto3 not installed — required for assessment"}
    except Exception as e:
        return {"error": f"CE data pull failed: {type(e).__name__}: {e}"}

    logger.info("Step 1 complete (%.1fs): coverage=%d rows, RI=%d rows, SP=%d entries, Spot=%d entries, summary=%d types",
                time.time() - t0, len(coverage_rows), len(ri_rows),
                len(sp_cost_data), len(spot_cost_data),
                len((usage_summary or {}).get("by_region", {})))

    if not coverage_rows:
        # Distinguish "the account genuinely had no usage" from "every CE call
        # failed". Reporting the latter as a credential/date-range problem sent
        # at least one debugging session down the wrong path: the real cause was
        # upstream request failures, already recorded above.
        upstream = [_redact_sensitive(e) for e in _pricing_errors
                    if not e.startswith(("SP_RATES", "ec2/", "rds/",
                                         "elasticache/", "opensearch/"))]
        if upstream:
            detail = "; ".join(upstream[:3])
            more = f" (+{len(upstream) - 3} more)" if len(upstream) > 3 else ""
            error = (f"No coverage data: every Cost Explorer request failed. "
                     f"First failures: {detail}{more}")
        else:
            error = (f"No coverage data: Cost Explorer returned no usage for "
                     f"{start_date}..{end_date}. The requests succeeded, so this "
                     f"is an empty period rather than an access problem — check "
                     f"the date range (end date is exclusive) and that the "
                     f"account had compute usage.")
        return {
            "error": error,
            "pricing_errors": [_redact_sensitive(e) for e in _pricing_errors[:10]],
        }

    # --- Step 2-3: One row per (service, type, region, pricing coordinates) ---
    # Cost and hours come from the usage summary, split by region and platform;
    # see _build_fleet_rows. The coverage, RI, SP and Spot pulls supply the
    # coordinates and RI term metadata, and stand in for any summary pull that
    # failed.
    classified = _build_fleet_rows(coverage_rows, ri_rows, sp_cost_data,
                                   spot_cost_data, usage_summary)
    if services:
        # --services narrows the whole assessment, not just the coverage pull:
        # the summary and the SP/Spot pulls return every service.
        wanted = {s.lower() for s in services}
        classified = [r for r in classified if r.get("service") in wanted]
    if not classified:
        return {"error": "No classifiable instances in data.", "raw_rows": len(coverage_rows)}

    # Every figure below is a monthly average over the analysis period.
    period_months = _months_in_period(start_date, end_date)
    _normalize_to_monthly(classified, period_months)

    # Diagnostics: raw API totals, on the same monthly basis.
    raw_od_total = sum(r.get("od_cost", 0) for r in coverage_rows) / period_months
    raw_ri_total = sum(r.get("total_amortized", 0) for r in ri_rows) / period_months
    raw_sp_total = sum(v for v in sp_cost_data.values()) / period_months
    raw_spot_total = sum(v for v in spot_cost_data.values()) / period_months
    summary_total = sum(
        c["cost"] for regions in (usage_summary or {}).get("by_region", {}).values()
        for pts in regions.values() for c in pts.values()) / period_months
    unclassified_types = [
        {"instance_type": r.get("raw", ""), "service": r.get("service", ""),
         "region": r.get("region", ""), "cost": r.get("cost", 0)}
        for r in classified if r.get("unclassified")
    ]
    logger.info("Step 2-3 complete: %d rows, %d regions, $%.2f/month, %d unclassified",
                len(classified), len({r.get("region", "") for r in classified}),
                sum(r.get("cost", 0) for r in classified), len(unclassified_types))

    # --- Step 4: Fetch OD prices for full fleet ---
    types_by_region = _collect_all_fleet_types(classified)
    od_prices = RegionalPrices()
    pricing_source = "none"
    regions_priced = []
    boto3_error = None
    bulk_error = None

    try:
        with _phase("od-pricing"):
            od_prices = _as_regional(_resolve_full_fleet_prices(types_by_region),
                                     types_by_region)
        if od_prices.type_count():
            tiers = getattr(od_prices, "tier_counts", {}) or {}
            pricing_source = ("bulk_cache" if tiers.get("bulk_cache") and not tiers.get("pricing_api")
                              else "pricing_api_boto3")
            regions_priced = sorted(r for r, book in od_prices.items() if book)
    except ImportError:
        boto3_error = "boto3 not available for Pricing API"
    except Exception as e:
        boto3_error = f"{type(e).__name__}: {e}"

    # --- Step 4b: Fetch SP offering rates for full fleet (parallel with enrichment) ---
    # Fetch SP rates for: current SP types, their Graviton targets, AND Intel equivalents
    # of Graviton instances (needed for realized savings at same purchase terms).

    # --- Step 4a-OS: Fetch pricing for non-Linux instances (RHEL, SUSE) ---
    # Windows is NOT supported on Graviton — those items are in "Not Eligible" section.
    # RHEL and SUSE ARE supported on Graviton, need correct OS pricing.
    if od_prices.type_count():
        # Group non-Linux/non-Windows items by OS and region for separate pricing calls
        # Windows is excluded — no Graviton equivalent exists
        os_types: Dict[str, Dict[str, set]] = {}  # {os_value: {region: {types}}}
        for item in classified:
            os_val, _ = _sp_coords(item)
            if os_val in ("Linux", "Windows"):
                continue  # Linux already priced, Windows not eligible for Graviton
            raw = item.get("raw", "")
            region = item.get("region", "us-east-1")
            if raw:
                os_types.setdefault(os_val, {}).setdefault(region, set()).add(raw)
                # Also add targets
                for gkey in ("graviton_upgrade", "graviton2", "graviton3", "graviton4", "graviton5"):
                    target = item.get(gkey)
                    if target:
                        full = target_type(item, target) if "." not in target else target
                        os_types[os_val][region].add(full)

        with _phase("od-pricing-non-linux"):
            for os_val, regions_dict in os_types.items():
                for rgn, types in regions_dict.items():
                    try:
                        os_prices = _fetch_od_prices_boto3(types, rgn, operating_system=os_val)
                        if os_prices:
                            # Store OS-specific prices — these override Linux prices for affected items
                            book = od_prices.book(rgn)
                            for k, v in os_prices.items():
                                book[f"{k}|{os_val}"] = v
                    except Exception as e:
                        # Non-fatal: the Linux price is still usable. Logged so an
                        # OS-specific pricing gap is explicable rather than silent.
                        logger.debug("OS-specific pricing unavailable (%s): %s: %s",
                                     rgn, type(e).__name__, e)

    # --- Step 4a-MANAGED: price RDS/ElastiCache at each row's real coordinates ---
    # RDS price varies by databaseEngine AND deploymentOption; ElastiCache by
    # cacheEngine. The full-fleet pass above cannot express those, so it prices
    # them at defaults; this pass re-prices each row and its Graviton targets at
    # the row's own coordinates and stores them under a coordinate-suffixed key
    # that the enrichment pass prefers. Without it a PostgreSQL Multi-AZ row was
    # compared against a MariaDB Single-AZ target.
    if od_prices.type_count():
        managed: Dict[tuple, set] = {}   # (region, service, engine, deployment) -> types
        for item in classified:
            svc, eng, depl = _pricing_coords(item)
            if svc not in ("rds", "elasticache"):
                continue
            raw = item.get("raw", "")
            if not raw:
                continue
            region = item.get("region", "us-east-1")
            group = managed.setdefault((region, svc, eng, depl), set())
            group.add(raw)
            # Targets go in the SAME group, which is the entire point.
            for gkey in ("graviton_upgrade", "graviton2", "graviton3",
                         "graviton4", "graviton5"):
                target = item.get(gkey)
                if target:
                    full = target_type(item, target) if "." not in target else target
                    group.add(_expand_size(full))

        if managed:
            with _phase("od-pricing-managed"):
                for (rgn, svc, eng, depl), types in managed.items():
                    kw = ({"db_engine": eng, "deployment_option": depl}
                          if svc == "rds" else {"cache_engine": eng})
                    try:
                        got = _fetch_od_prices_boto3(types, rgn, **kw)
                    except Exception as e:
                        # Non-fatal: the default-coordinate price from the
                        # full-fleet pass remains as a fallback.
                        logger.debug("Managed pricing unavailable (%s/%s/%s/%s): %s: %s",
                                     rgn, svc, eng, depl, type(e).__name__, e)
                        continue
                    suffix = _coord_key((svc, eng, depl))
                    book = od_prices.book(rgn)
                    for k, v in got.items():
                        book[f"{k}|{suffix}"] = v

    # Grouped by (region, OS, tenancy), not region alone. A row's Graviton
    # targets land in the SAME group as the row itself, because the savings ratio
    # divides the target's rate by the source's and the two must therefore be read
    # at identical coordinates. Grouping also stops the previous behaviour of
    # pricing every type in every region the fleet touches.
    from .realized_savings import get_intel_equivalent
    sp_groups: Dict[tuple, set] = {}

    for r in classified:
        # Any EC2 row with Savings Plan spend, not just SP-primary rows: the SP
        # slice of a mixed row is priced at the SP ratio. Managed services are
        # left out — Database SP rates are not matched on engine or deployment.
        if (r.get("service") or "ec2") != "ec2":
            continue
        if r.get("purchase_type", "").upper() != "SP" and not (r.get("cost_sp") or 0) > 0:
            continue
        region = r.get("region", "us-east-1")
        # Same accessor the enrichment pass uses, so the group a row is fetched
        # under is by construction the group it is later read from.
        os_val, sp_ten = _sp_coords(r)
        if os_val == "Windows":
            continue  # No Graviton equivalent — never priced.
        group = sp_groups.setdefault((region, os_val, sp_ten), set())

        raw = r.get("raw", "")
        if raw:
            group.add(raw)

        # Non-Graviton SP items: add their Graviton targets
        if not r.get("is_graviton") and r.get("graviton_upgrade"):
            for gkey in ("graviton_upgrade", "graviton2", "graviton3", "graviton4", "graviton5"):
                val = r.get(gkey)
                if val:
                    full = target_type(r, val) if "." not in val else val
                    group.add(_expand_size(full))

        # Graviton SP items: add their Intel equivalent
        if r.get("is_graviton") and raw:
            intel_eq = get_intel_equivalent(raw)
            if intel_eq:
                group.add(intel_eq)

    if sp_groups:
        try:
            with _phase("sp-rates"):
                sp_type = "Compute"
                sp_payment = "No Upfront"
                for (rgn, os_val, ten), types in sp_groups.items():
                    _fetch_sp_offering_rates(types, rgn, sp_type=sp_type,
                                             sp_payment=sp_payment,
                                             operating_system=os_val, tenancy=ten)
        except Exception as e:
            # Non-fatal: Savings Plan rates are an enhancement, and their absence
            # only means the on-demand ratio is used for SP rows.
            logger.debug("Savings Plan offering rates unavailable: %s: %s",
                         type(e).__name__, e)

    # --- Step 4c: Enrich classified items with per-item pricing ---
    # Also where instance_offerings and managed_offerings availability lookups
    # happen, via _build_graviton_options.
    with _phase("enrich+offerings"):
        _enrich_classified_with_pricing(classified, od_prices, target_strategy)

    # --- Step 4c: Compute realized savings for existing Graviton instances ---
    with _phase("realized-savings"):
        realized_savings_result = _compute_realized_savings(classified, od_prices)

    logger.info("Step 3-4 complete (%.1fs): pricing_source=%s, types_resolved=%d, realized_savings=%s",
                time.time() - t0, pricing_source, od_prices.type_count(),
                "yes" if realized_savings_result else "no")

    # --- Step 5: Score + migrate + engine readiness ---
    with _phase("score-fleet"):
        score_result = score_graviton_fleet(
            classified, region="us-east-1", od_prices=od_prices if od_prices.type_count() else None,
            target_strategy=target_strategy,
        )
    with _phase("migration-plan"):
        plan_result = generate_migration_plan(
            classified, region="us-east-1", od_prices=od_prices if od_prices.type_count() else None,
            target_strategy=target_strategy,
        )

    engine_checks = []
    seen_engines = set()
    # Normalize CE engine names to what check_engine_graviton_readiness expects
    _ENGINE_NORMALIZE = {
        "postgresql": "postgres",
        "aurora postgresql": "aurora-postgresql",
        "aurora mysql": "aurora-mysql",
        "sql server": "sqlserver",
        "mariadb": "mariadb",
        "mysql": "mysql",
        "redis": "redis",
        "memcached": "memcached",
        "valkey": "valkey",
        "opensearch": "opensearch",
    }

    # Resolve actual engine versions from AWS describe APIs
    engine_version_map = _resolve_engine_versions(classified)

    for r in classified:
        svc = r.get("service", "ec2")
        if svc not in ("rds", "elasticache", "opensearch") or r.get("is_graviton"):
            continue
        engine = (r.get("database_engine") or r.get("cache_engine")
                  or ("opensearch" if svc == "opensearch" else ""))
        if not engine:
            continue
        engine_lower = engine.lower().strip()
        normalized = _ENGINE_NORMALIZE.get(engine_lower, engine_lower)
        instance_type = r.get("raw", "")
        region = r.get("region", "us-east-1")

        # Look up actual version from describe APIs
        version = ""
        version_entries = engine_version_map.get((svc, instance_type, region), [])
        for entry in version_entries:
            # Match by normalized engine name
            entry_engine = entry["engine"].lower().strip()
            entry_normalized = _ENGINE_NORMALIZE.get(entry_engine, entry_engine)
            if entry_normalized == normalized:
                version = entry["version"]
                break
        # If no exact engine match, use first available version for this instance type
        if not version and version_entries:
            version = version_entries[0]["version"]

        # The engine minimum depends on the target family, so check against the
        # target this row was actually given (which follows
        # --graviton-generation), not the classifier's default.
        chosen = ""
        gen_field = {"Graviton2": "g2", "Graviton3": "g3", "Graviton4": "g4",
                     "Graviton5": "g5"}.get(r.get("graviton_target_generation", ""))
        if gen_field:
            chosen = ((r.get("graviton_targets_by_gen") or {}).get(gen_field) or {}).get("type", "")
        key = f"{normalized}:{version}:{instance_type}:{chosen}"
        if key not in seen_engines:
            seen_engines.add(key)
            engine_checks.append(
                check_engine_graviton_readiness(normalized, version, instance_type,
                                                target_class=chosen)
            )

    # --- Build summary ---
    total_cost = sum(r.get("cost", 0) for r in classified)
    graviton_count = sum(1 for r in classified if r.get("is_graviton"))
    graviton_cost = sum(r.get("cost", 0) for r in classified if r.get("is_graviton"))
    # Compute NIH-based Graviton coverage
    graviton_nih = sum(r.get("hours", 0) * r.get("nih_factor", 4) for r in classified if r.get("is_graviton"))
    total_nih = sum(r.get("hours", 0) * r.get("nih_factor", 4) for r in classified)
    total_hours = sum(r.get("hours", 0) for r in classified)
    graviton_hours = sum(r.get("hours", 0) for r in classified if r.get("is_graviton"))
    if total_nih > 0:
        graviton_pct = round(graviton_nih / total_nih * 100, 1)
    elif total_hours > 0:
        graviton_pct = round(graviton_hours / total_hours * 100, 1)
    else:
        graviton_pct = round(graviton_count / max(len(classified), 1) * 100, 1)

    # Cost by purchase type, summed from each row's per-PT breakdown
    # (cost_od..cost_spot, set by the usage-summary merge). The previous basis —
    # bucket each row's entire cost under its single primary purchase_type, read
    # through per-source fields like spot_cost that only cover the rows the
    # region-scoped pull happened to match — mixed bases and mis-binned every
    # mixed-purchase row: a measured fleet's table said Spot $4,530 while both
    # Cost Explorer pulls said $10,178. Rows the summary never matched carry no
    # breakdown fields; their whole cost falls back to the primary label so the
    # table still sums to the classified fleet.
    _PT_FIELD = {"OD": "cost_od", "RI": "cost_ri", "SP": "cost_sp", "Spot": "cost_spot"}
    _pt_totals = {f: 0.0 for f in _PT_FIELD.values()}
    for r in classified:
        if any(f in r for f in _pt_totals):
            for f in _pt_totals:
                _pt_totals[f] += r.get(f, 0)
        else:
            _pt_totals[_PT_FIELD.get(r.get("purchase_type"), "cost_od")] += r.get("cost", 0)
    total_od = _pt_totals["cost_od"]
    total_ri = _pt_totals["cost_ri"]
    total_sp = _pt_totals["cost_sp"]
    total_spot = _pt_totals["cost_spot"]
    # Every row with RI spend carries its share of the net RI savings,
    # whatever its primary purchase type.
    total_ri_savings = sum(r.get("ri_savings", 0) or 0 for r in classified)
    total_od_hours = sum(r.get("od_hours", 0) for r in classified)
    total_reserved_hours = sum(r.get("reserved_hours", 0) for r in classified)

    # Diagnostics: classified totals
    classified_sp = sum(r.get("cost", 0) for r in classified if r.get("purchase_type") == "SP")
    classified_spot = sum(r.get("cost", 0) for r in classified if r.get("purchase_type") == "Spot")
    classified_ri = sum(r.get("cost", 0) for r in classified if r.get("purchase_type") == "RI")
    classified_od = sum(r.get("cost", 0) for r in classified if r.get("purchase_type") == "OD")

    # --- Build response dict ---
    result = {
        "summary": {
            "version": "v3",
            "total_types": len(classified),
            "total_cost": round(total_cost, 2),
            "graviton_count": graviton_count,
            "graviton_pct": graviton_pct,
            "graviton_cost": round(graviton_cost, 2),
            "graviton_hours": round(graviton_hours, 2),
            "total_hours": round(total_hours, 2),
            "pricing_source": pricing_source,
            "pricing_types_resolved": od_prices.type_count(),
            "pricing_tiers": dict(getattr(od_prices, "tier_counts", {}) or {}),
            "regions_priced": regions_priced or [],
            "date_range": {"start": start_date, "end": end_date},
            "period": {"start": start_date, "end": end_date,
                       "months": round(period_months, 2), "basis": "monthly_average"},
            "spend_basis": _SPEND_BASIS,
            "data_completeness": _data_completeness(usage_summary),
            "coverage_summary": {
                "total_od_hours": round(total_od_hours, 1),
                "total_reserved_hours": round(total_reserved_hours, 1),
                "overall_coverage_pct": round(
                    total_reserved_hours
                    / max(total_od_hours + total_reserved_hours, 1) * 100, 1
                ),
            },
            "purchase_type_summary": {
                "od_cost": round(total_od, 2),
                "ri_cost": round(total_ri, 2),
                "sp_cost": round(total_sp, 2),
                "spot_cost": round(total_spot, 2),
                "ri_savings": round(total_ri_savings, 2),
            },
            "ri_subscriptions": len(ri_rows),
            "data_quality": {
                "raw_api_totals": {
                    "od_from_coverage": round(raw_od_total, 2),
                    "ri_from_utilization": round(raw_ri_total, 2),
                    "sp_from_ce": round(raw_sp_total, 2),
                    "spot_from_ce": round(raw_spot_total, 2),
                },
                "usage_summary_total": round(summary_total, 2),
                "unclassified_types": unclassified_types,
                "split_estimated_cost": round(sum(
                    c.get("split_estimated_cost", 0) or 0 for c in classified), 2),
                "classified_totals": {
                    "od": round(classified_od, 2),
                    "ri": round(classified_ri, 2),
                    "sp": round(classified_sp, 2),
                    "spot": round(classified_spot, 2),
                },
                "unclassified": {
                    "od": round(raw_od_total - classified_od, 2),
                    "ri": round(raw_ri_total - classified_ri, 2),
                    "sp": round(raw_sp_total - classified_sp, 2),
                    "spot": round(raw_spot_total - classified_spot, 2),
                },
                "coverage_rows": len(coverage_rows),
                "entries_by_purchase_type": {
                    "OD": sum(1 for r in classified if r.get("purchase_type") == "OD"),
                    "RI": sum(1 for r in classified if r.get("purchase_type") == "RI"),
                    "SP": sum(1 for r in classified if r.get("purchase_type") == "SP"),
                    "Spot": sum(1 for r in classified if r.get("purchase_type") == "Spot"),
                },
            },
            # Redacted HERE, at the single choke point where raw exception text
            # becomes deliverable content: this dict lands verbatim in
            # graviton_assessment_result.json, and botocore access-denied
            # messages embed the operator's full caller ARN.
            "pricing_errors": {
                "boto3": _redact_sensitive(boto3_error) if boto3_error else boto3_error,
                "bulk_cache": _redact_sensitive(bulk_error) if bulk_error else bulk_error,
                "per_type_errors": ([_redact_sensitive(e) for e in _pricing_errors[:10]]
                                    if _pricing_errors else []),
                "per_type_error_count": len(_pricing_errors),
            } if (boto3_error or bulk_error or _pricing_errors) else None,
        },
        "score": score_result,
        "migration_plan": plan_result,
        "engine_readiness": engine_checks,
        "classified_detail": classified,
        # Realized savings — only present when Graviton instances exist
        **({"realized_savings": realized_savings_result[1]} if realized_savings_result else {}),
        **({"realized_savings_detail": realized_savings_result[0]} if realized_savings_result else {}),
    }

    _total_elapsed = time.time() - t0
    logger.info("Assessment complete (%.1fs): total_cost=$%.2f, classified=%d, graviton_pct=%.1f%%",
                _total_elapsed, total_cost, len(classified), graviton_pct)
    _log_phase_breakdown(_total_elapsed)

    return result
