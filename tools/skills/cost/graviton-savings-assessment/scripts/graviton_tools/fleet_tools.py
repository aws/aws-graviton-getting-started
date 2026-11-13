# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Fleet scoring, target selection, migration planning, and engine readiness.

score_graviton_fleet and generate_migration_plan take pre-fetched on-demand
prices (a RegionalPrices book from assessment_pipeline, or a plain dict for one
region) and make no pricing calls of their own. fetch_engine_versions reads
the running engine versions from the RDS, ElastiCache and OpenSearch APIs, and
check_engine_graviton_readiness compares them with the minimum each Graviton
target family supports.
"""
import re, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple
from .instance_classifier import classify_and_upgrade, full_type, graviton_generation
from .pricing_comparison import fetch_prices

# Instance size -> NIH (normalized instance hours) factor, roughly vCPU count.
#
# ONE table, because the size *ordering* is derived from it below. Two
# hand-maintained lists drift: a size missing from the factors scores as
# "large" (3xlarge would read 4 instead of 24), and a size missing from the
# ladder has no smaller rungs for the capacity-adjusted fallback. Deriving one
# from the other makes that disagreement unrepresentable.
#
# Ordered largest-first in the literal so ties (metal and 24xlarge are both 192)
# resolve to the more specific size, since sorted() is stable.
SIZE_NIH_FACTORS = {
    "112xlarge": 896, "96xlarge": 768, "56xlarge": 448,
    "48xlarge": 384, "32xlarge": 256, "24xlarge": 192, "metal": 192,
    "18xlarge": 144, "16xlarge": 128, "12xlarge": 96, "10xlarge": 80,
    "9xlarge": 72, "8xlarge": 64, "6xlarge": 48, "4xlarge": 32,
    "3xlarge": 24, "2xlarge": 16, "xlarge": 8, "large": 4,
    "medium": 2, "small": 1, "micro": 0.5, "nano": 0.25,
}

# Standard instance size ladder, largest to smallest. Module-level because the
# pricing collectors in assessment_pipeline must walk the same rungs this module
# uses to resolve a capacity-adjusted (nearest-smaller) target — otherwise they
# price a size that does not exist and the real target is never priced at all.
SIZE_LADDER = sorted(SIZE_NIH_FACTORS, key=lambda s: -SIZE_NIH_FACTORS[s])


# A .metal size is the family's largest size, which differs by family. The
# table's single "metal" = 192 (24xlarge) counted Graviton2/3 metal (16xlarge,
# 128) 1.5x too high. Sized variants carry their size in the name.
_METAL_VARIANT_FACTORS = {"metal-16xl": 128, "metal-24xl": 192,
                          "metal-32xl": 256, "metal-48xl": 384}
_METAL_BY_FAMILY = (
    (re.compile(r"^(?:db\.|cache\.)?[a-z]+[67]g[a-z]*$"), 128),   # Graviton2/3 metal = 16xlarge
    (re.compile(r"^[a-z]+6i[a-z]*$"), 256),                        # 6th-gen Intel = 32xlarge
    (re.compile(r"^[a-z]+6a[a-z]*$"), 384),                        # 6th-gen AMD = 48xlarge
)


def nih_factor(size: str, instance_type: str = "") -> float:
    """NIH normalization factor for a size; "large" (4) if unrecognised.

    `instance_type` refines "metal", whose size is the family's largest.
    """
    if size in _METAL_VARIANT_FACTORS:
        return _METAL_VARIANT_FACTORS[size]
    if size == "metal" and instance_type:
        fam = instance_type.lower().rsplit(".", 1)[0]
        for pattern, factor in _METAL_BY_FAMILY:
            if pattern.match(fam):
                return factor
    return SIZE_NIH_FACTORS.get(size, 4)


def months_in_period(start_date: str, end_date: str) -> Optional[float]:
    """Months in the end-exclusive range [start, end); None if invalid or empty.

    Whole calendar months when both dates are the 1st, else days / 30.4375.
    The one definition: the pipeline normalises by it and the reports describe
    the period with it, and two copies had drifted (one rounded, one did not).
    """
    from datetime import date
    try:
        s, e = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError):
        return None
    if e <= s:
        return None
    if s.day == 1 and e.day == 1:
        return float((e.year - s.year) * 12 + (e.month - s.month))
    return (e - s).days / (365.25 / 12)


def sizes_at_or_below(size: str) -> List[str]:
    """Return `size` plus every smaller rung of the ladder.

    Used by the pricing collector to enumerate the candidate sizes a
    capacity-adjusted target could resolve to, so all of them are priced up
    front. Returns just [size] for a size not on the ladder.
    """
    try:
        idx = SIZE_LADDER.index(size)
    except ValueError:
        return [size] if size else []
    return SIZE_LADDER[idx:]

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# FLEET ENGINE VERSION DISCOVERY — fetch actual versions from AWS APIs
# ═══════════════════════════════════════════════════════════════════════════

def fetch_engine_versions(
    regions: list, services: Optional[list] = None
) -> Dict[tuple, list]:
    """Fetch actual engine versions from AWS describe APIs.

    Args:
        regions: List of AWS region strings to query.
        services: List of services to query. Defaults to ["rds", "elasticache", "opensearch"].

    Returns:
        Dict keyed by (service, instance_type, region) -> list of {"engine": str, "version": str}.
        Each key may have multiple entries if different engines share the same instance type+region.
    """
    if services is None:
        services = ["rds", "elasticache", "opensearch"]

    results: Dict[tuple, list] = {}
    lock = __import__("threading").Lock()

    def _merge(key, engine, version):
        entry = {"engine": engine, "version": version}
        with lock:
            existing = results.setdefault(key, [])
            if entry not in existing:
                existing.append(entry)

    def _fetch_rds_region(region: str):
        try:
            import boto3
            rds = boto3.client("rds", region_name=region)
            # Describe instances (covers standalone + Aurora instances)
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page["DBInstances"]:
                    itype = db.get("DBInstanceClass", "")
                    engine = db.get("Engine", "")
                    version = db.get("EngineVersion", "")
                    if itype and engine:
                        _merge(("rds", itype, region), engine, version)
        except Exception as e:
            logger.warning("fetch_engine_versions: RDS failed in %s: %s", region, e)

    def _fetch_elasticache_region(region: str):
        try:
            import boto3
            ec = boto3.client("elasticache", region_name=region)
            paginator = ec.get_paginator("describe_cache_clusters")
            for page in paginator.paginate(ShowCacheNodeInfo=True):
                for cluster in page["CacheClusters"]:
                    node_type = cluster.get("CacheNodeType", "")
                    engine = cluster.get("Engine", "")
                    version = cluster.get("EngineVersion", "")
                    if node_type and engine:
                        _merge(("elasticache", node_type, region), engine, version)
        except Exception as e:
            logger.warning("fetch_engine_versions: ElastiCache failed in %s: %s", region, e)

    def _fetch_opensearch_region(region: str):
        try:
            import boto3
            client = boto3.client("opensearch", region_name=region)
            domains = client.list_domain_names().get("DomainNames", [])
            if not domains:
                return
            names = [d["DomainName"] for d in domains]
            # describe_domains accepts max 5 at a time
            for i in range(0, len(names), 5):
                batch = names[i:i + 5]
                resp = client.describe_domains(DomainNames=batch)
                for ds in resp.get("DomainStatusList", []):
                    version = ds.get("EngineVersion", "")  # e.g. "OpenSearch_2.11"
                    # Extract node type from cluster config
                    cc = ds.get("ClusterConfig", {})
                    itype = cc.get("InstanceType", "")
                    if itype and version:
                        _merge(("opensearch", itype, region), "opensearch", version)
        except Exception as e:
            logger.warning("fetch_engine_versions: OpenSearch failed in %s: %s", region, e)

    # Build work items: (function, region) pairs
    tasks = []
    for region in regions:
        if "rds" in services:
            tasks.append((_fetch_rds_region, region))
        if "elasticache" in services:
            tasks.append((_fetch_elasticache_region, region))
        if "opensearch" in services:
            tasks.append((_fetch_opensearch_region, region))

    if not tasks:
        return results

    # Each fetcher catches and logs its own failures, so result() only waits.
    with ThreadPoolExecutor(max_workers=min(len(tasks), 12)) as pool:
        futures = [pool.submit(fn, rgn) for fn, rgn in tasks]
        for f in as_completed(futures):
            f.result()

    return results


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: Expand abbreviated instance type sizes
# ═══════════════════════════════════════════════════════════════════════════

class RegionalPrices(dict):
    """On-demand price books keyed by region: {region: {price_key: $/hr}}.

    A flat {type: price} dict cannot hold the same type in two regions, so the
    last region priced won for every row and multi-region fleets were priced
    at one region's rates. Every per-row consumer reads its own region's book
    through prices_for().
    """

    def for_region(self, region: str) -> Dict[str, float]:
        return self.get(region) or {}

    def book(self, region: str) -> Dict[str, float]:
        """The region's book, created if absent, for writers."""
        return self.setdefault(region, {})

    def type_count(self) -> int:
        return sum(len(v) for v in self.values())


def prices_for(od_prices, region: str) -> Dict[str, float]:
    """The price book that applies to `region`.

    A plain dict is region-agnostic (tests and callers that price one region
    pass one) and is returned as is.
    """
    if isinstance(od_prices, RegionalPrices):
        return od_prices.for_region(region)
    return od_prices or {}


def _price_maps_by_region(rows: List[Dict], od_prices) -> Dict[str, Dict[str, float]]:
    """Per-region {type: price} maps covering every candidate type of `rows`."""
    by_region: Dict[str, List[Dict]] = {}
    for r in rows:
        by_region.setdefault(r.get("region", ""), []).append(r)
    maps = {}
    for region, region_rows in by_region.items():
        book = prices_for(od_prices, region)
        types = _collect_candidate_types(region_rows)
        maps[region] = (fetch_prices(list(types), region, pricing_json=book)
                        if types and book else {})
    return maps


def _size_of(instance_type: str) -> str:
    """The size part of a full type string (db.r6g.16xlarge -> 16xlarge)."""
    t = (instance_type or "").lower()
    if t.endswith(".search"):
        t = t[:-len(".search")]
    for prefix in ("db.", "cache."):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    return t.split(".", 1)[1] if "." in t else ""


# vCPU count per instance type, filled from the Pricing API's product
# attributes as prices are read (assessment_pipeline._parse_price_list_item).
# The size table cannot size "metal": an m6i.metal has 128 vCPUs and an
# m7g.metal 64, so treating metal-to-metal as like-for-like doubled the saving.
VCPU_BY_TYPE: Dict[str, int] = {}
# Memory per instance type (GiB), from the same attributes. Memory-dense
# families are sized by memory, so their capacity is compared on memory: one
# x2iedn.32xlarge (4,096 GiB) needs 1.33 x8g.48xlarge (3,072 GiB), although
# the x8g has more vCPUs.
MEMORY_GIB_BY_TYPE: Dict[str, float] = {}


def capacity_factor(source_size: str, target: str, source_type: str = "",
                    basis: str = "vcpu") -> Optional[float]:
    """How many `target` instances match the capacity of one source instance.

    Compared on `basis` ("vcpu", or "memory" for the memory-dense families)
    when the Pricing API gave both instances' figures. Otherwise the size
    table: 1.0 for the same size, the NIH ratio for different sizes. None when
    a metal size is involved and its capacity is unknown, because metal sizes
    differ by family and nothing here can compare them.
    """
    table = MEMORY_GIB_BY_TYPE if basis == "memory" else VCPU_BY_TYPE
    src_v = table.get((source_type or "").lower())
    tgt_v = table.get((target or "").lower())
    if src_v and tgt_v:
        # Never below one instance: a larger target (t2.micro has 1 vCPU,
        # t4g.micro 2) still costs a whole instance. Pricing half of one
        # credited a 53% saving on a 6% price difference.
        return max(1.0, src_v / tgt_v)
    tgt = _size_of(target)
    if "metal" in (source_size or "") or "metal" in tgt:
        return None
    if not source_size or not tgt or source_size == tgt:
        return 1.0
    if source_size not in SIZE_NIH_FACTORS or tgt not in SIZE_NIH_FACTORS:
        return 1.0
    return SIZE_NIH_FACTORS[source_size] / SIZE_NIH_FACTORS[tgt]


def target_type(r: Dict, base: str, size: Optional[str] = None) -> str:
    """Full type string for Graviton family `base` built from row `r`.

    Uses the row's target size (which differs from its own size only for the
    memory-dense families the classifier sizes by memory) and carries the row's
    prefix and type suffix, so an OpenSearch row's targets stay `.search` types
    and are priced and validated as OpenSearch rather than as EC2.
    """
    size = size or r.get("target_size") or r.get("size", "")
    return full_type(r.get("prefix", ""), base, size, r.get("type_suffix", ""))


from .instance_classifier import expand_size as _expand_size  # one definition


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: Collect all Graviton candidate types for pricing validation
# ═══════════════════════════════════════════════════════════════════════════

def _collect_candidate_types(items: List[Dict]) -> set:
    """Gather all instance types that need pricing: current + g2/g3/g4/g5 candidates.

    For each upgradeable instance, builds full instance type strings from the
    graviton2/3/4/5 base families + the instance's prefix and size.

    All generations are collected (not just the selected target) so the HTML
    report's generation selector can switch between them client-side without
    a re-run. graviton5 is only present for families with an announced 9g type.
    """
    types = set()
    for r in items:
        raw = r.get("raw", "")
        if raw:
            types.add(raw)
        # Primary target
        target = r.get("graviton_upgrade", "")
        if target:
            types.add(target)
        # Multi-gen candidates: base families need prefix + size to become full types
        size = r.get("target_size") or r.get("size", "")
        for gkey in ("graviton2", "graviton3", "graviton4", "graviton5"):
            base = r.get(gkey)
            if base:
                types.add(target_type(r, base))
                # And every smaller size in the family. The same-size string above
                # may name a type AWS does not offer (db.r6i.32xlarge yields
                # db.r6g.32xlarge, which does not exist). _build_graviton_options
                # then substitutes the nearest smaller REAL size, so that size has
                # to be priced here or the substituted target resolves to no rate
                # and the row contributes $0 to headline savings.
                for smaller in sizes_at_or_below(size)[1:]:
                    types.add(target_type(r, base, smaller))
    return types


def _build_graviton_options(
    r: Dict, od_prices: Dict, target_strategy: str = "latest", region: str = ""
) -> Tuple[List[Dict], Optional[Dict]]:
    """Build priced Graviton options (g2/g3/g4/g5) for one instance.

    Returns:
        (options_list, best_option) where best_option is selected based on target_strategy,
        or None if no option has real pricing.

    target_strategy:
        "latest": Pick the n+1 Graviton generation matching graviton_upgrade from
                  instance_classifier (gen<=5->g2, gen6->g3, gen7->g4, gen>=8->g5 where
                  it exists). If that generation has no priced option, take the
                  newest one that has (G5, then G4, G3, G2).
        "graviton2"/"graviton3"/"graviton4"/"graviton5": Force every instance to that
                  generation. When the forced target isn't offered or priced, take the
                  nearest older generation first (a missing G5 lands on G4), then the
                  newer ones nearest first, and mark the row generation_fallback.

    region: when provided, targets not offered in that region are excluded via
        DescribeInstanceTypeOfferings. Availability lookup failures are non-fatal
        and simply skip this filtering.

    Target existence is validated against the real offerings catalog for the
    row's service (see the "Existence oracle" block below), so string-built
    candidates that AWS does not offer never become recommendations. When the
    exact size has no Graviton equivalent, the nearest smaller real size is
    returned flagged as capacity-adjusted. Its savings ARE included in the
    headline, but a same-size target always wins over it when one exists — see
    the two-pass pool walk in _build_graviton_options().
    """
    raw = r.get("raw", "")
    size = r.get("size", "")
    target_size = r.get("target_size") or size
    # An OS this tool cannot price is not priced as Linux: no current rate, so
    # no option is priced and the row is reported as unpriced.
    current_od = od_prices.get(raw) if platform_priceable(r) else None

    # Graviton generation label -> AWS generation number (m6g=6, m7g=7, m8g=8, m9g=9)
    _GRAVITON_GEN_NUM = {"Graviton2": 6, "Graviton3": 7, "Graviton4": 8, "Graviton5": 9}
    source_gen = r.get("generation", 5)
    service = (r.get("service") or "ec2").lower()

    # ── Existence oracle ──────────────────────────────────────────────────
    # One validation strategy for every service, matching the core rule of the
    # Graviton Savings Dashboard (GSD, the AWS Cost Intelligence Dashboards
    # view this assessment is reconciled against): a Graviton target only
    # counts if AWS actually offers that exact family.size in that region. GSD
    # enforces this with a region-scoped price-list LEFT JOIN; we use the
    # offerings APIs instead, which are authoritative rather than a price proxy:
    #   EC2             -> DescribeInstanceTypeOfferings      (instance_offerings)
    #   RDS             -> DescribeOrderableDBInstanceOptions (managed_offerings)
    #   ElastiCache     -> DescribeReservedCacheNodesOfferings
    # None => the lookup was unavailable (missing IAM, throttle, no region).
    # Never treat that as "nothing exists" — fall back to the price heuristic.
    # The lookups catch their own failures and return None, so no handler is
    # needed here; the imports are late so tests can substitute the lookups.
    offered = None
    managed_offered = None
    if region:
        from .instance_offerings import get_offered_types
        offered = get_offered_types(region)
        if service == "rds":
            from .managed_offerings import get_rds_offered_classes
            managed_offered = get_rds_offered_classes(
                region, r.get("database_engine") or ""
            )
        elif service == "elasticache":
            from .managed_offerings import get_elasticache_offered_classes
            managed_offered = get_elasticache_offered_classes(region)

    def _catalog_for(candidate_type: str):
        """Existence oracle for THIS candidate, selected by type SHAPE.

        Shape rather than the row's ``service`` field, because the classifier
        reports service='ec2' for OpenSearch ``.search`` types. Keying on
        service sent those to DescribeInstanceTypeOfferings, which never
        enumerates ``.search`` (nor db./cache.), so every real OpenSearch
        target was rejected as nonexistent, dropped to no price, and the row
        fell through to the flat 20% estimate with its target name lost.

        Returns None when no catalog covers this shape, which means "unknown"
        and degrades to the price-driven heuristic — never "nothing exists".
        """
        t = (candidate_type or "").lower()
        if t.startswith(("db.", "cache.")):
            return managed_offered
        if t.endswith(".search"):
            # OpenSearch has an authoritative catalog of its own
            # (opensearch:ListInstanceTypeDetails) but it is not wired up yet,
            # so validation is skipped rather than applied from the wrong set.
            return None
        return offered

    def _hops_to(base_family: str, gen_label: str) -> int:
        """Generational steps from the source instance to a target family.

        Read from the target family's own generation digit (c9g -> 9) rather
        than from the Graviton-label map, because that map assumes standard
        numbering (m6g == Graviton2 == gen 6) and the t-family is offset:
        t4g IS Graviton2. Via the label map a t3 -> t4g move scored 3 hops and
        t2 -> t4g scored 4, when they are 1 and 2. Harmless while the uplift was
        flat; with a per-hop uplift it would over-credit every burstable
        instance roughly threefold.

        Falls back to the label map when the family carries no digit (a1, i8ge
        variants), and floors at 0 so a same-generation move (m6a -> m6g) earns
        no generational uplift.
        """
        m = re.search(r"(\d+)", base_family or "")
        target_gen = int(m.group(1)) if m else _GRAVITON_GEN_NUM.get(gen_label)
        if not target_gen:
            return 0
        return max(target_gen - source_gen, 0)

    def _resolve_with_fallback(base: str, target_size: str
                               ) -> Tuple[Optional[str], Optional[float], bool, Optional[bool]]:
        """Resolve a Graviton target size to a real, orderable instance type.

        Returns (instance_type, od_price, is_capacity_adjusted, exists), where
        exists is False when the catalog says no size of this family fits,
        True when it confirmed one, and None when no catalog was available.

        Existence is decided by ``catalog`` — the real offerings API for this
        service — never by "does a price exist", which is only a proxy and
        would let string-built phantoms (c7g.24xlarge, db.r7g.32xlarge) be
        reported as real targets.

        is_capacity_adjusted=True means the exact source size has no Graviton
        equivalent in this family, so a genuinely smaller real size was
        substituted. GSD stops at this point and books the row as "No
        equivalent graviton instance" with NULL savings — it never downsizes.
        This assessment departs from GSD here: the capacity-adjusted target's
        savings ARE counted in the headline, flagged so the report marks the
        row for workload validation, and a same-size target always wins over
        it when one exists (see the two-pass pool walk below).
        """
        full = target_type(r, base, target_size)
        catalog = _catalog_for(full)

        if catalog is not None:
            if full.lower() in catalog:
                return full, od_prices.get(full), False, True
            # Exact size not offered by this family. Walk the FULL ladder to the
            # nearest smaller size that genuinely exists — a 24xlarge source may
            # be two or more rungs above the largest real Graviton size (e.g.
            # c7g stops at 16xlarge), which a single-step probe would miss and
            # then silently mislabel as a same-size target.
            try:
                start_idx = SIZE_LADDER.index(target_size)
            except ValueError:
                return full, None, False, False
            for smaller in SIZE_LADDER[start_idx + 1:]:
                candidate = target_type(r, base, smaller)
                if candidate.lower() in catalog:
                    return candidate, od_prices.get(candidate), True, True
            # Nothing in this family fits: GSD's "No equivalent graviton
            # instance". No price, so no savings can be credited.
            return full, None, False, False

        # Catalog unavailable — degrade to the price-driven heuristic rather
        # than dropping every target. One step down only, flagged
        # capacity-adjusted: it counts in the headline at equal capacity (see
        # _capacity_factor) and the report marks it for workload validation.
        price = od_prices.get(full)
        if price:
            return full, price, False, None
        try:
            start_idx = SIZE_LADDER.index(target_size)
        except ValueError:
            return full, None, False, None
        if start_idx + 1 < len(SIZE_LADDER):
            candidate_size = SIZE_LADDER[start_idx + 1]
            candidate = target_type(r, base, candidate_size)
            price = od_prices.get(candidate)
            if price:
                return candidate, price, True, None
        return full, None, False, None

    options = []
    for gen_label, gkey in [("Graviton2", "graviton2"), ("Graviton3", "graviton3"),
                            ("Graviton4", "graviton4"), ("Graviton5", "graviton5")]:
        base = r.get(gkey)
        if not base:
            continue
        tgt_type, target_od, size_adjusted, exists = _resolve_with_fallback(base, target_size)
        if exists is False:
            # The service's own catalog has no size of this family that fits.
            # Recorded so the row can be booked as "no equivalent" rather than
            # as a pricing gap.
            options.append({
                "generation": gen_label,
                "instance_type": tgt_type,
                "od_rate": None,
                "savings_pct": None,
                "gen_hops": _hops_to(base, gen_label),
                "pricing_source": "not_offered_in_region",
                "note": f"No {base} size is offered in {region} for this row",
            })
            continue
        # Drop targets AWS doesn't offer in this region. Only applied to plain
        # EC2 types — db./cache./.search aren't enumerated by this API.
        if offered is not None and tgt_type:
            bare = tgt_type.lower()
            if not bare.startswith(("db.", "cache.")) and not bare.endswith(".search"):
                if bare not in offered:
                    options.append({
                        "generation": gen_label,
                        "instance_type": tgt_type,
                        "od_rate": None,
                        "savings_pct": None,
                        "gen_hops": _hops_to(base, gen_label),
                        "pricing_source": "not_offered_in_region",
                        "note": f"{tgt_type} is not offered in {region}",
                    })
                    continue
        # Generational hops from source to this target, floored at 0 (no negative uplift).
        gen_hops = _hops_to(base, gen_label)
        if size_adjusted:
            # Capacity-adjusted: the exact source size has no Graviton equivalent
            # in this family, so this is a SMALLER instance. Its price delta
            # conflates Graviton savings with a hardware downsize.
            #
            # By policy these savings ARE included in the headline. The
            # size_adjusted flag is what carries the caveat downstream: the
            # report marks these targets with a warning glyph, and the two-pass
            # pool walk in the selection below keeps a downsize from displacing
            # a like-for-like target that actually exists.
            #
            # The saving is priced at equal capacity: as many of the smaller
            # instances as it takes to match the source (capacity_factor), so
            # the dropped vCPUs are not counted as a Graviton saving.
            #
            # savings_pct stays None when the smaller size could not be priced —
            # there is no figure to include in that case.
            factor = capacity_factor(target_size, tgt_type, raw,
                                     basis=r.get("size_basis") or "vcpu")
            cap_pct = (
                round((1 - target_od * factor / current_od) * 100, 1)
                if factor and target_od and current_od and current_od > 0 else None
            )
            options.append({
                "generation": gen_label,
                "instance_type": tgt_type,
                "od_rate": round(target_od, 4) if target_od else None,
                "savings_pct": cap_pct,
                "gen_hops": gen_hops,
                "pricing_source": "capacity_adjusted",
                "size_adjusted": True,
                "capacity_factor": round(factor, 4) if factor else None,
                "note": (
                    f"No same-size Graviton equivalent — nearest smaller: "
                    f"{tgt_type}; priced as {factor:g} of them to match the "
                    f"capacity of one {size}. Validate workload fit"
                    if factor else
                    f"No same-size Graviton equivalent — nearest smaller: "
                    f"{tgt_type}; its capacity relative to {size} is unknown, "
                    f"so no saving is computed"
                ),
            })
        elif (target_od and current_od and current_od > 0
              and capacity_factor(target_size, tgt_type, raw,
                                  basis=r.get("size_basis") or "vcpu") is not None):
            # A same-size string can still differ in capacity (metal sizes,
            # memory-sized targets), so the factor applies here too; it is 1.0
            # for real like-for-like.
            factor = capacity_factor(target_size, tgt_type, raw,
                                     basis=r.get("size_basis") or "vcpu")
            savings_pct = round((1 - target_od * factor / current_od) * 100, 1)
            opt = {
                "generation": gen_label,
                "instance_type": tgt_type,
                "od_rate": round(target_od, 4),
                "savings_pct": savings_pct,
                "gen_hops": gen_hops,
                "pricing_source": "pricing_api",
                "capacity_factor": round(factor, 4),
            }
            if r.get("size_basis") == "memory":
                opt["note"] = (f"Sized by memory: {raw} has twice the memory per "
                               f"vCPU of the Graviton family, so the target is one "
                               f"size larger")
            options.append(opt)
        else:
            options.append({
                "generation": gen_label,
                "instance_type": tgt_type,
                "od_rate": None,
                "savings_pct": None,
                "gen_hops": gen_hops,
                "pricing_source": "not_available",
            })

    # Fallback: if no multi-gen fields were present, try graviton_upgrade directly.
    if not options:
        target = r.get("graviton_upgrade", "")
        if target:
            target_od = od_prices.get(target)
            if target_od and current_od and current_od > 0:
                savings_pct = round((1 - target_od / current_od) * 100, 1)
                options.append({
                    "generation": "Graviton",
                    "instance_type": target,
                    "od_rate": round(target_od, 4),
                    "savings_pct": savings_pct,
                    "pricing_source": "pricing_api",
                })

    # Select "best" based on target_strategy
    priced = [o for o in options if o["savings_pct"] is not None]
    if not priced:
        return options, None

    # Capacity-adjusted (downsized) options are priced and eligible now that
    # their savings count toward the headline. But a downsize must never
    # displace a like-for-like target that exists — its price delta mixes the
    # Graviton saving with a hardware reduction, and it is always the cheaper
    # rate, so on savings alone it would win every time.
    #
    # Selection therefore runs over the SAME-SIZE pool first and only falls back
    # to the full pool if that yields nothing. Filtering per generation would not
    # be enough: the generation-preference walk below prefers newer generations,
    # so a G5-only downsize would otherwise shadow a same-size G3.
    _same_size = [c for c in priced if not c.get("size_adjusted")]
    _pools = [_same_size, priced] if _same_size else [priced]

    def _select(pool):
        """Apply the active target_strategy within one candidate pool."""
        if not pool:
            return None
        if target_strategy in ("graviton2", "graviton3", "graviton4", "graviton5"):
            # Forced generation: migrate everything to this Graviton generation
            # (the dashboard's "Graviton2/3/4/5" radio options). When the forced
            # target isn't offered or priced in this region, fall back to the
            # newest available older generation and mark the row so the fallback
            # is visible rather than silently reported as the requested one.
            forced_label = {
                "graviton2": "Graviton2", "graviton3": "Graviton3",
                "graviton4": "Graviton4", "graviton5": "Graviton5",
            }[target_strategy]
            matching = [o for o in pool if o["generation"] == forced_label]
            if matching:
                return matching[0]
            # The nearest OLDER generation first (a missing G5 lands on G4, not
            # G2), and only then the newer ones, nearest first. Walking G5 down
            # to G2 regardless sent a forced graviton2 that was unavailable to G5,
            # the opposite of what the caller asked for.
            order = ("Graviton2", "Graviton3", "Graviton4", "Graviton5")
            idx = order.index(forced_label)
            fallback_order = list(reversed(order[:idx])) + list(order[idx + 1:])
            for fallback_label in fallback_order:
                candidates = [o for o in pool if o["generation"] == fallback_label]
                if candidates:
                    chosen = dict(candidates[0])
                    chosen["requested_generation"] = forced_label
                    chosen["generation_fallback"] = True
                    chosen["note"] = (
                        f"{forced_label} target unavailable in "
                        f"{region or 'this region'} — using {fallback_label}"
                    )
                    return chosen
            return max(pool, key=lambda o: o["savings_pct"])

        # "latest" (default, the dashboard's "Default next-gen"): pick the n+1
        # Graviton generation matching graviton_upgrade from instance_classifier
        # (gen<=5->g2, gen6->g3, gen7->g4, gen>=8->g5 where a 9g type exists).
        # If that generation has no pricing, fall back to next available.
        # The classifier's graviton_upgrade is the default target; its
        # generation is read, not re-derived, so a static override (r5b -> r7g,
        # m5zn -> m7g) is priced as the type the reports name.
        expected_gen_label = graviton_generation(r.get("graviton_upgrade") or "")
        if not expected_gen_label:
            generation = r.get("generation", 5)
            if generation <= 5:
                expected_gen_label = "Graviton2"
            elif generation == 6:
                expected_gen_label = "Graviton3"
            elif generation == 7:
                expected_gen_label = "Graviton4"
            else:  # generation >= 8 — Graviton5 only where the family has a 9g type
                expected_gen_label = "Graviton5" if r.get("graviton5") else "Graviton4"

        matching = [o for o in pool if o["generation"] == expected_gen_label]
        if matching:
            return matching[0]
        # Fallback: for "latest", prefer newer generations over older ones.
        for gen_label in ("Graviton5", "Graviton4", "Graviton3", "Graviton2"):
            candidates = [o for o in pool if o["generation"] == gen_label]
            if candidates:
                return candidates[0]
        return max(pool, key=lambda o: o["savings_pct"])

    # A forced generation is honoured at any size before falling back to a
    # different generation: the same-size pool alone made a priced smaller
    # target of the requested generation lose to another generation's
    # same-size one, and the note then said the requested one was unavailable.
    if target_strategy in ("graviton2", "graviton3", "graviton4", "graviton5"):
        wanted = "Graviton" + target_strategy[-1]
        for _pool in _pools:
            hit = [o for o in _pool if o["generation"] == wanted]
            if hit:
                return options, hit[0]

    best = None
    for _pool in _pools:
        best = _select(_pool)
        if best is not None:
            break

    return options, best


def _row_savings(r: Dict, od_prices: Dict, target_strategy: str = "latest") -> float:
    """One row's savings on the SAME basis the headline KPI uses.

    Prefers the enriched, commitment-matched figure attached by
    assessment_pipeline._enrich_classified_with_pricing, and falls back to the
    on-demand ratio only for rows enrichment could not price.

    This exists because the migration plan and the headline disagreed. Both
    describe the same fleet, and score_graviton_fleet was fixed to prefer the
    enriched figure while generate_migration_plan kept calling _best_savings,
    which computes the pure on-demand ratio and looks prices up by bare instance
    type (so managed-service rows got default engine/deployment coordinates).
    Measured on a real production fleet: the headline read $77,850 and the wave plan
    $56,157 for the same rows, 28% apart, in one report.
    """
    enriched = r.get("est_savings")
    if enriched is not None:
        return enriched
    return _best_savings(r, od_prices, target_strategy)[0]


def _best_savings(r: Dict, od_prices: Dict, target_strategy: str = "latest") -> Tuple[float, str, str]:
    """Compute savings for one instance using best validated Graviton target.

    Uses _build_graviton_options() internally to ensure consistent target selection
    with score_graviton_fleet(). Returns (savings_amount, target_type, pricing_source).
    """
    raw = r.get("raw", "")
    cost = r.get("cost", 0)
    current_od = od_prices.get(raw)

    # Enrichment found no target rate at this row's own coordinates. The plain
    # keys here hold the default engine/deployment and Linux, so re-pricing
    # from them would book someone else's ratio; the row is unpriced instead.
    if r.get("savings_unmatched") and r.get("est_savings") is None:
        return 0.0, r.get("graviton_upgrade", "") or "", "estimate_20pct"

    # Use _build_graviton_options for consistent target selection
    options, best = _build_graviton_options(
        r, od_prices, target_strategy, region=r.get("region", "")
    )

    if best and current_od and current_od > 0:
        target_od = best["od_rate"]
        target_type = best["instance_type"]
        # instance_type is a clean type string — the size_adjusted flag carries
        # the warning, so there is no display prefix to strip here.
        #
        # Report capacity_adjusted when that is what was selected, so the report
        # can mark the row. It now carries real savings, so the source is the
        # only thing distinguishing it from a like-for-like target.
        src = ("capacity_adjusted"
               if best.get("pricing_source") == "capacity_adjusted" else "pricing_api")
        # No spot rate exists anywhere in the pipeline, so a Spot row's savings
        # are the on-demand price ratio applied to its spot cost — an assumption
        # that the spot discount is equally deep on both sides. Label the basis
        # the way estimate_20pct self-identifies; capacity_adjusted keeps its
        # label because the size warning outranks the basis note.
        if src == "pricing_api" and r.get("purchase_type") == "Spot":
            src = "od_ratio_proxy"
        factor = best.get("capacity_factor", 1.0) or 1.0
        return (cost * _movable_share(r) * (1 - target_od * factor / current_od),
                target_type, src)

    # An unpriced capacity-adjusted option is the one remaining case with no
    # figure to report: a real Graviton family exists but the nearest smaller
    # size has no price, so there is nothing to include.
    capacity_opt = next(
        (o for o in options if o.get("pricing_source") == "capacity_adjusted"), None
    )
    if capacity_opt:
        # Unpriced, not a priced zero: _tally counts it beside the headline.
        return 0.0, capacity_opt.get("instance_type", ""), "capacity_unpriced"

    # Every candidate was rejected by the service's own catalog: there is no
    # Graviton equivalent for this row in its region, so nothing is saved.
    if options and all(o.get("pricing_source") == "not_offered_in_region" for o in options):
        return 0.0, "", "no_equivalent"

    # A real target exists but no price could be resolved. No saving is booked;
    # the indicative ESTIMATE_FALLBACK_RATIO figure is reported separately.
    primary = r.get("graviton_upgrade", "")
    return 0.0, primary or "", "estimate_20pct"


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: De-duplicate already-optimized entries
# ═══════════════════════════════════════════════════════════════════════════

def _dedup_already_optimized(entries: list) -> list:
    """De-duplicate already_optimized by (instance_type, region, platform), keeping highest cost.

    When multiple CE dimensions produce the same row, retain only the one with
    the highest cost value to avoid inflating the list. Platform is part of the
    key because rows are per platform: a Linux and a RHEL row of one type and
    region are different rows with different rates, not duplicates.
    All fields from the retained entry are preserved unchanged.
    """
    seen: Dict[tuple, dict] = {}
    for entry in entries:
        key = (entry.get("instance_type", ""), entry.get("region", ""),
               entry.get("platform", ""))
        existing = seen.get(key)
        if existing is None or entry.get("cost", 0) > existing.get("cost", 0):
            seen[key] = entry
    return list(seen.values())


# ═══════════════════════════════════════════════════════════════════════════
# 1. FLEET SUMMARY — aggregate classify_usage_types into executive summary
# ═══════════════════════════════════════════════════════════════════════════

# Indicative savings ratio for rows no pricing tier could resolve. It is shown
# beside the headline as a labelled estimate and NEVER added into it: a row with
# no price has no measured saving, and the flat figure was roughly three times
# the real gap for some families (m7i-flex -> m8g).
ESTIMATE_FALLBACK_RATIO = 0.20

# Commercial database engines with no Graviton instance classes on RDS.
_COMMERCIAL_ENGINE_TOKENS = ("oracle", "sql server", "sqlserver", "db2")


def is_commercial_engine(r: Dict) -> bool:
    """True for RDS rows on Oracle, SQL Server or Db2, which cannot move to Graviton."""
    engine = (r.get("database_engine") or "").lower()
    return any(tok in engine for tok in _COMMERCIAL_ENGINE_TOKENS)


def _is_sql_server_platform(r: Dict) -> bool:
    """EC2 platforms bundling SQL Server ("Linux with SQL Server Standard").

    SQL Server has no arm64 build, so these have no Graviton path even when
    the OS is Linux.
    """
    return "sql server" in (r.get("platform") or "").lower()


def _locked_cost(r: Dict) -> float:
    """Spend a family-locked commitment holds: an EC2 Instance Savings Plan
    (cost_sp_isp) or a reservation that cannot change family (cost_ri_locked)."""
    return (r.get("cost_sp_isp") or 0) + (r.get("cost_ri_locked") or 0)


def is_commitment_locked(r: Dict) -> bool:
    """True when family-locked commitments hold all of the row's spend.

    Such a row cannot move to Graviton without paying for both until the
    commitment ends. Partly held rows stay eligible; only the rest of their
    spend earns a saving.
    """
    cost = r.get("cost") or 0
    return cost > 0 and _locked_cost(r) >= cost * 0.995


is_isp_locked = is_commitment_locked  # former name


def _movable_share(r: Dict) -> float:
    """Fraction of the row's spend no family-locked commitment holds."""
    cost = r.get("cost") or 0
    return max(cost - _locked_cost(r), 0.0) / cost if cost > 0 else 1.0


def is_ineligible(r: Dict) -> bool:
    """Rows with no Graviton path: Windows, SQL Server, commercial engines, locked spend."""
    return (_is_windows(r) or _is_sql_server_platform(r) or is_commercial_engine(r)
            or is_commitment_locked(r))


# EC2 platforms whose Graviton price the pipeline can look up, as Cost
# Explorer spells them (lowercased, without " (Amazon VPC)"). Anything else
# (RHEL with HA, Ubuntu Pro, BYOL variants) is left unpriced rather than
# priced as plain Linux, which overstated its saving.
_PRICEABLE_EC2_PLATFORMS = frozenset({
    "", "linux/unix", "linux", "red hat enterprise linux", "rhel", "suse linux", "suse",
})


def platform_priceable(r: Dict) -> bool:
    """True when the row's OS and tenancy can be priced on both sides of a savings ratio.

    On-demand EC2 prices are read at shared tenancy only, so a Dedicated
    Instance or Dedicated Host row would be divided by shared-tenancy rates;
    such rows are left unpriced and reported beside the headline instead.
    """
    svc = r.get("service") or "ec2"
    if svc == "rds" and not (r.get("database_engine") or "").strip():
        # No engine (a failed coverage pull leaves it empty): an Oracle or SQL
        # Server row cannot be told from an open-source one, and is_ineligible
        # would pass it, so its savings would count. Leave it unpriced.
        return False
    if svc != "ec2":
        return True
    ten = (r.get("tenancy") or "").strip().lower()
    if ten.startswith(("dedicated", "host")):
        return False
    plat = re.sub(r"\s*\(amazon vpc\)$", "", (r.get("platform") or "").strip().lower())
    return plat in _PRICEABLE_EC2_PLATFORMS


def _has_target(r: Dict) -> bool:
    return bool(r.get("graviton_upgrade") or r.get("graviton2") or r.get("graviton3")
                or r.get("graviton4") or r.get("graviton5"))


def _is_windows(r: Dict) -> bool:
    """True for rows whose CE platform is any Windows variant.

    Windows has no Graviton path, and the classifier still attaches
    graviton_upgrade strings to these rows (it only sees the type shape), so
    every consumer that selects "upgradeable" rows must also check the platform.
    Enrichment already skips Windows; before this check, score and plan priced
    those rows from the plain (Linux) price keys and counted the fabricated
    savings the report's Not-Eligible section said were excluded.
    """
    return "windows" in (r.get("platform") or "").lower()


def score_graviton_fleet(classified_instances: List[Dict], region: str = "us-east-1",
                         od_prices: Optional[Dict[str, float]] = None,
                         target_strategy: str = "latest") -> dict:
    """Aggregate classified instances into fleet summary with ranked opportunities.

    Prices come from `od_prices` only; nothing here calls the Pricing API. A row
    no price resolves for books no saving and is counted under the unpriced KPIs.

    Args:
        classified_instances: Output from classify_usage_types
        region: AWS region (for metadata only)
        od_prices: RegionalPrices from assessment_pipeline, or a plain
            {instance_type: $/hr} dict that applies to every row
        target_strategy: "latest" or "graviton2".."graviton5"

    Returns:
        Executive summary with KPIs, top opportunities with multi-gen options,
        adoption %, wave breakdown.
    """
    total_cost = sum(r.get("cost", 0) for r in classified_instances)
    total_hours = sum(r.get("hours", 0) for r in classified_instances)
    total_instances = len(classified_instances)

    graviton = [r for r in classified_instances if r.get("is_graviton")]
    upgradeable = [r for r in classified_instances
                   if _has_target(r) and not r.get("is_graviton") and not is_ineligible(r)]
    legacy = [r for r in classified_instances if r.get("generation", 99) <= 5 and not r.get("is_graviton")]

    graviton_cost = sum(r.get("cost", 0) for r in graviton)
    upgradeable_cost = sum(r.get("cost", 0) for r in upgradeable)

    # Per-region price maps: each row is priced from its own region's book.
    price_maps = _price_maps_by_region(upgradeable, od_prices)

    def _map_for(r):
        return price_maps.get(r.get("region", ""), {})

    _debug_pricing = {
        "od_prices_provided": od_prices is not None,
        "regions": sorted(price_maps),
        "resolved_count": sum(len(m) for m in price_maps.values()),
    }

    # Top opportunities ranked by cost (biggest savings first)
    # Exclude negative savings (Graviton more expensive) from top opportunities
    opps = sorted(upgradeable, key=lambda x: x.get("cost", 0), reverse=True)
    # Build one detailed opportunity entry per row (pricing, best target,
    # savings). Shared by the Top Opportunities list and the Already
    # Cost-Optimized list so both describe a row the same way.
    def _opp_entry(r):
        raw = r.get("raw", "")
        cost = r.get("cost", 0)
        hours = r.get("hours", 0)
        eff = r.get("effective_rate", 0)
        od_price_map = _map_for(r)
        current_od = od_price_map.get(raw)

        # Build multi-gen options with pricing
        options, best = _build_graviton_options(
            r, od_price_map, target_strategy, region=r.get("region", "")
        )
        capacity_unpriced = False

        # Use best validated option for the primary recommendation
        if best and current_od and current_od > 0:
            target = best["instance_type"]
            target_od = best["od_rate"]
            real_savings_pct = best["savings_pct"]
            gen_hops = best.get("gen_hops", 0)
            factor = best.get("capacity_factor", 1.0) or 1.0
            est_graviton_rate = round(eff * (target_od * factor / current_od), 4) if eff > 0 else 0
            est_monthly_savings = round(
                cost * _movable_share(r) * (1 - target_od * factor / current_od), 2)
            # Capacity-adjusted targets now contribute real savings; the source
            # is what tells the report to mark them for workload validation.
            pricing_source = ("capacity_adjusted"
                              if best.get("pricing_source") == "capacity_adjusted"
                              else "pricing_api")
            # Same proxy labelling as _best_savings: Spot rows are priced by the
            # on-demand ratio because no spot rate is pulled anywhere.
            if pricing_source == "pricing_api" and r.get("purchase_type") == "Spot":
                pricing_source = "od_ratio_proxy"
        else:
            capacity_opt = next(
                (o for o in options if o.get("pricing_source") == "capacity_adjusted"),
                None,
            )
            if capacity_opt:
                # Only reachable when the nearest-smaller size could not be
                # priced, so there is no figure to include. A priced
                # capacity-adjusted option is selected as `best` above and
                # carries its real savings.
                target = capacity_opt.get("instance_type", "")
                target_od = None
                real_savings_pct = None
                gen_hops = 0
                est_graviton_rate = 0
                est_monthly_savings = 0.0
                pricing_source = "capacity_adjusted"
                capacity_unpriced = True
            elif options and all(o.get("pricing_source") == "not_offered_in_region"
                                 for o in options):
                # The catalog rejected every candidate: no equivalent here.
                target = ""
                target_od = None
                real_savings_pct = None
                gen_hops = 0
                est_graviton_rate = 0
                est_monthly_savings = 0.0
                pricing_source = "no_equivalent"
            else:
                # A target exists but has no price. No saving is booked; the
                # indicative figure travels separately as unpriced_estimate.
                target = r.get("graviton_upgrade", "")
                target_od = None
                real_savings_pct = None
                gen_hops = 0
                est_graviton_rate = 0
                est_monthly_savings = 0.0
                pricing_source = "estimate_20pct"

        # One basis for the row AND the total. If the total banked the local
        # on-demand figure while the row showed the enriched commitment-matched
        # one, a commitment-heavy fleet's per-row column and headline would
        # describe the same rows with different arithmetic (~43% apart on a
        # measured 340-type fleet).
        #
        # The enriched figure wins because it is the Graviton Savings Dashboard's
        # basis: amortized current cost against a target priced at the same term,
        # payment option and offering class. The on-demand ratio remains the
        # fallback for rows enrichment could not price.
        row_savings = r.get("est_savings")
        if row_savings is None and r.get("savings_unmatched"):
            # See _best_savings: no rate at the row's coordinates, so unpriced.
            row_savings = 0.0
            pricing_source = "estimate_20pct"
        elif row_savings is None:
            row_savings = est_monthly_savings
        elif pricing_source in ("estimate_20pct", "no_equivalent"):
            # Enrichment priced this row at its own coordinates even though the
            # plain-key lookup here could not; the figure is a priced one.
            pricing_source = "pricing_api"

        opp_entry = {
            "instance_type": _expand_size(raw),
            "graviton_target": _expand_size(target),
            "cost": round(cost, 2),
            "hours": round(hours),
            "effective_rate": eff,
            "od_current": round(current_od, 4) if current_od else None,
            "od_graviton": round(target_od, 4) if target_od else None,
            "gen_hops": gen_hops,
            "est_graviton_rate": est_graviton_rate,
            "est_savings_pct": real_savings_pct,
            "est_monthly_savings": row_savings,
            "pricing_source": pricing_source,
            "region": r.get("region", ""),
            "platform": r.get("platform", ""),
            "service": r.get("service", "ec2"),
            "gen_bucket": r.get("gen_bucket", ""),
            "category": r.get("category", ""),
            "purchase_type": r.get("purchase_type", "Unknown"),
            "est_savings_g2": r.get("est_savings_g2"),
            "est_savings_g3": r.get("est_savings_g3"),
            "est_savings_g4": r.get("est_savings_g4"),
            "est_savings_g5": r.get("est_savings_g5"),
        }
        if capacity_unpriced and r.get("est_savings") is None:
            # Only an unpriced smaller-size target exists: nothing is booked, so
            # the row is unpriced spend, not a priced zero. It once counted in
            # neither the headline nor the unpriced total.
            opp_entry["capacity_unpriced"] = True
        if ((pricing_source == "estimate_20pct" or opp_entry.get("capacity_unpriced"))
                and r.get("est_savings") is None):
            opp_entry["unpriced_estimate"] = round(cost * ESTIMATE_FALLBACK_RATIO, 2)
        # Include multi-gen options: same-size targets and capacity-adjusted
        # (smaller) ones. A priced capacity-adjusted option counts like any
        # other, at equal capacity, and is marked for workload validation; an
        # unpriced one (savings_pct=None) is shown but books nothing.
        shown_options = [
            o for o in options
            if o["pricing_source"] in ("pricing_api", "capacity_adjusted")
        ]
        if shown_options:
            opp_entry["graviton_options"] = shown_options
        return opp_entry

    top_opps = []
    tail_already_optimized = []
    total_est_savings = 0.0
    # Rows with a real target but no price. Kept out of total_est_savings and
    # reported beside it, so a reader sees how much spend is unpriced.
    unpriced = {"count": 0, "cost": 0.0, "indicative_savings": 0.0}
    no_equivalent = {"count": 0, "cost": 0.0}

    def _tally(r, source):
        if r.get("est_savings") is not None:
            return
        if source in ("estimate_20pct", "capacity_unpriced"):
            unpriced["count"] += 1
            unpriced["cost"] += r.get("cost", 0)
            unpriced["indicative_savings"] += r.get("cost", 0) * ESTIMATE_FALLBACK_RATIO
        elif source == "no_equivalent":
            no_equivalent["count"] += 1
            no_equivalent["cost"] += r.get("cost", 0)

    def _book(r, amount, source):
        # The exact figure this row put in the headline, and why. The HTML
        # report rebuilds its headline from rows, so it reads these rather than
        # re-deriving a saving the scorer may have declined to book.
        r["booked_savings"] = round(amount or 0.0, 2)
        r["booked_source"] = source

    for idx, r in enumerate(opps):
        if idx < 15:
            entry = _opp_entry(r)
            total_est_savings += entry["est_monthly_savings"]
            src = ("capacity_unpriced" if entry.get("capacity_unpriced")
                   else entry["pricing_source"])
            _tally(r, src)
            _book(r, entry["est_monthly_savings"], src)
            top_opps.append(entry)
        else:
            # Rows beyond the top 15 contribute to the total on the same basis
            # (enriched est_savings, else the on-demand ratio — otherwise the
            # headline would silently change basis at row 16). Build a full entry
            # only for the already-optimized negatives, so the Already
            # Cost-Optimized section reflects the WHOLE fleet rather than just the
            # top 15; these rows are netted into the headline either way.
            row_savings = r.get("est_savings")
            src = "enriched"
            if row_savings is None:
                row_savings, _, src = _best_savings(r, _map_for(r), target_strategy)
                _tally(r, src)
            _book(r, row_savings, src)
            total_est_savings += row_savings
            if row_savings is not None and row_savings < 0:
                tail_already_optimized.append(_opp_entry(r))

    # Pricing hit/miss counts over the shown opportunities (the top 15), computed
    # from the pricing source so the counters survive the refactor unchanged.
    pricing_hits = sum(
        1 for o in top_opps
        if o["pricing_source"] in ("pricing_api", "od_ratio_proxy"))
    pricing_misses = sum(
        1 for o in top_opps
        if o["pricing_source"] in ("capacity_adjusted", "estimate_20pct"))

    # Already-optimized (Graviton more expensive) = every negative-saving instance
    # across the fleet: the negatives from the top 15 plus those found in the
    # tail. Top Opportunities keeps only the positive top-15 rows.
    already_optimized = (
        [o for o in top_opps if o.get("est_monthly_savings", 0) < 0]
        + tail_already_optimized
    )
    top_opps = [o for o in top_opps if o.get("est_monthly_savings", 0) >= 0]

    # Add reason field to each already-optimized entry
    for entry in already_optimized:
        od_current = entry.get("od_current")
        od_graviton = entry.get("od_graviton")
        graviton_target = entry.get("graviton_target", "")
        instance_type = entry.get("instance_type", "")
        # The classifier's own processor flag. A suffix test ("ends in a")
        # labelled m5ad, r5ad and c6ad as Intel.
        _info = classify_and_upgrade(instance_type)
        processor = "AMD EPYC" if _info and _info.is_amd else "Intel"
        if od_current is not None and od_graviton is not None:
            entry["reason"] = (
                f"{processor} pricing (${od_current}/hr) is lower than "
                f"Graviton {graviton_target} (${od_graviton}/hr) "
                f"— already cost-optimized"
            )
        else:
            entry["reason"] = f"{processor} instance is already cost-optimized — Graviton equivalent is more expensive"

    # Generation breakdown
    gen_buckets = {}
    for r in classified_instances:
        b = r.get("gen_bucket", "Unknown")
        gen_buckets.setdefault(b, {"count": 0, "cost": 0})
        gen_buckets[b]["count"] += 1
        gen_buckets[b]["cost"] += r.get("cost", 0)

    # Service breakdown
    svc_buckets = {}
    for r in classified_instances:
        s = r.get("service", "ec2")
        svc_buckets.setdefault(s, {"count": 0, "cost": 0, "graviton": 0})
        svc_buckets[s]["count"] += 1
        svc_buckets[s]["cost"] += r.get("cost", 0)
        if r.get("is_graviton"):
            svc_buckets[s]["graviton"] += 1

    # Hours-based Graviton adoption percentage (Req 1.2)
    graviton_hours = sum(r.get("hours", 0) for r in graviton)
    if total_hours > 0:
        graviton_pct = round(graviton_hours / total_hours * 100, 1)
    else:
        # Fallback: count-based when all hours are zero (Req 1.4)
        graviton_pct = round(len(graviton) / max(total_instances, 1) * 100, 1)

    # Processor generation breakdown (Req 2.5)
    processor_gen_breakdown: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in classified_instances:
        if r.get("is_graviton"):
            proc = "Graviton"
        elif r.get("is_amd"):
            proc = "AMD"
        else:
            proc = "Intel"
        gen = r.get("gen_bucket", "Unknown")
        processor_gen_breakdown.setdefault(proc, {}).setdefault(gen, {"count": 0, "cost": 0, "hours": 0})
        processor_gen_breakdown[proc][gen]["count"] += 1
        processor_gen_breakdown[proc][gen]["cost"] += r.get("cost", 0)
        processor_gen_breakdown[proc][gen]["hours"] += r.get("hours", 0)

    # De-duplicate already_optimized by (instance_type, region, platform)
    already_optimized = _dedup_already_optimized(already_optimized)

    return {
        "kpis": {
            "total_instances": total_instances,
            "total_cost": round(total_cost, 2),
            "graviton_count": len(graviton),
            "graviton_pct": graviton_pct,
            "graviton_hours": round(graviton_hours, 2),
            "total_hours": round(total_hours, 2),
            "graviton_cost": round(graviton_cost, 2),
            "upgradeable_count": len(upgradeable),
            "upgradeable_pct": round(len(upgradeable) / max(total_instances, 1) * 100, 1),
            "upgradeable_cost": round(upgradeable_cost, 2),
            "est_total_savings": round(total_est_savings, 2),
            "unpriced_count": unpriced["count"],
            "unpriced_cost": round(unpriced["cost"], 2),
            "unpriced_indicative_savings": round(unpriced["indicative_savings"], 2),
            "no_equivalent_count": no_equivalent["count"],
            "no_equivalent_cost": round(no_equivalent["cost"], 2),
            "legacy_count": len(legacy),
        },
        "top_opportunities": top_opps,
        "already_optimized": already_optimized,
        "generation_breakdown": {
            k: {"count": v["count"], "cost": round(v["cost"], 2)}
            for k, v in sorted(gen_buckets.items(), key=lambda x: -x[1]["cost"])
        },
        "service_breakdown": {
            k: {"count": v["count"], "cost": round(v["cost"], 2), "graviton": v["graviton"]}
            for k, v in svc_buckets.items()
        },
        "processor_generation_breakdown": processor_gen_breakdown,
        "pricing_metadata": {
            "source": "agent_provided" if od_prices else "no_pricing",
            "region": region,
            "api_hits": pricing_hits,
            "fallback_estimates": pricing_misses,
            "note": ("Savings are the current-to-Graviton rate ratio applied to amortized "
                     "spend. Spend counts usage charges only: credits, refunds and other "
                     "billing adjustments are not applied."),
            "_debug": _debug_pricing,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. ENGINE GRAVITON READINESS — RDS, Aurora, ElastiCache, OpenSearch versions
# ═══════════════════════════════════════════════════════════════════════════

# The lowest engine version AWS supports on each Graviton instance family.
#
# It depends on the TARGET family, not only on the engine: Redis OSS runs on
# cache.r6g from 5.0.6 but needs 6.2 on cache.r7g and is not offered on
# cache.r8g at all; RDS PostgreSQL 13 runs on db.r7g from 13.4 but needs 13.11
# on db.r8g. One minimum per engine was too lax for the newer families and too
# strict for the older ones.
#
# Shape: engine -> family -> {release line: minimum}
#   release line  see _major(): "13" for PostgreSQL 13.x, "8.0" for MySQL
#                 8.0.x, "10.6" for MariaDB, "3" for Aurora MySQL 3.x,
#                 "Elasticsearch"/"OpenSearch" for OpenSearch Service, and "*"
#                 for the ElastiCache engines, which AWS lists with a single
#                 minimum per node family.
#   minimum       lowest supported version on that line ("13" means every
#                 13.x), or (minimum, [extra exact versions below it]) — e.g.
#                 Aurora PostgreSQL 11.9 is supported although 11.10/11.11
#                 are not.
# A release line missing from a family's map is not supported on that family,
# and an engine missing for a family means the engine is not offered on it.
#
# Mirrored in references/engine-compatibility.md; update both together.
ENGINE_SUPPORT_REVIEWED = "2026-11-12"
ENGINE_SUPPORT_SOURCES = {
    "rds": "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.DBInstanceClass.Support.html",
    "aurora": "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.DBInstanceClass.SupportAurora.html",
    "elasticache": "https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheNodes.SupportedTypes.html",
    "opensearch": "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html",
}


def _families(names: str, rules: Dict) -> Dict[str, Dict]:
    return {f.strip(): rules for f in names.split(",")}


_MARIADB_ALL = {line: line for line in
                ("10.4", "10.5", "10.6", "10.11", "11.4", "11.8", "12.3")}

GRAVITON_ENGINE_SUPPORT: Dict[str, Dict[str, Dict]] = {
    # RDS — ENGINE_SUPPORT_SOURCES["rds"]
    "postgres": {
        **_families("m6g, r6g, t4g, x2g",
                    {"12": "12.7", "13": "13", "14": "14", "15": "15", "16": "16", "17": "17"}),
        **_families("m6gd",
                    {"13": ("13.7", ["13.4"]), "14": "14", "15": "15", "16": "16", "17": "17"}),
        **_families("r6gd, c6gd",
                    {"13": ("13.7", ["13.4"]), "14": "14.5", "15": "15", "16": "16", "17": "17"}),
        **_families("m7g, r7g",
                    {"13": "13.4", "14": "14.5", "15": "15", "16": "16", "17": "17"}),
        **_families("m8g, r8g",
                    {"13": "13.11", "14": "14.9", "15": "15.4", "16": "16.1", "17": "17.1"}),
        **_families("m8gd, r8gd, m9g",
                    {"13": "13.18", "14": "14.17", "15": "15.10", "16": "16.6", "17": "17.2",
                     "18": "18.1"}),
    },
    "mysql": {
        **_families("m6g, r6g, t4g, x2g, m6gd, r6gd, c6gd, m7g, r7g",
                    {"8.0": "8.0", "8.4": "8.4"}),
        **_families("m8g, r8g", {"8.0": "8.0.32", "8.4": "8.4"}),
        **_families("m8gd, r8gd, m9g", {"8.0": "8.0.40", "8.4": "8.4.3"}),
    },
    "mariadb": {
        **_families("m6g, r6g, t4g, x2g, m6gd, r6gd, m7g, r7g", _MARIADB_ALL),
        **_families("m8g, r8g",
                    {"10.4": "10.4.29", "10.5": "10.5.20", "10.6": "10.6.13",
                     "10.11": "10.11.7", "11.4": "11.4.3", "11.8": "11.8.3", "12.3": "12.3.2"}),
        **_families("m8gd, r8gd, m9g",
                    {"10.5": "10.5.27", "10.6": "10.6.19", "10.11": "10.11.9",
                     "11.4": "11.4.3", "11.8": "11.8.3", "12.3": "12.3.2"}),
    },
    # Aurora — ENGINE_SUPPORT_SOURCES["aurora"]
    "aurora-mysql": {
        **_families("r6g, x2g, t4g", {"2": "2", "3": "3"}),
        **_families("r7g", {"2": "2.12.0", "3": "3.03.1"}),
        **_families("r8g", {"3": "3.08.0"}),
    },
    "aurora-postgresql": {
        **_families("r6g, x2g",
                    {"11": ("11.12", ["11.9"]), "12": "12.8", "13": "13.3", "14": "14.3",
                     "15": "15.2", "16": "16.1", "17": "17.4"}),
        **_families("t4g",
                    {"11": "11.12", "12": "12.7", "13": "13.3", "14": "14.3",
                     "15": "15.2", "16": "16.1", "17": "17.4"}),
        **_families("r6gd", {"14": "14.9", "15": "15.4", "16": "16.1", "17": "17.4"}),
        **_families("r7g",
                    {"13": "13.10", "14": "14.7", "15": "15.2", "16": "16.1", "17": "17.4"}),
        **_families("r8g",
                    {"13": "13.15", "14": "14.12", "15": "15.7", "16": "16.3", "17": "17.4"}),
        **_families("r8gd", {"14": "14.12", "15": "15.7", "16": "16.3", "17": "17.4"}),
    },
    # ElastiCache — ENGINE_SUPPORT_SOURCES["elasticache"]
    "redis": {
        **_families("m6g, r6g, t4g", {"*": "5.0.6"}),
        **_families("m7g, r7g, c7gn, r6gd", {"*": "6.2"}),
    },
    "memcached": {
        **_families("m6g, r6g, t4g, m7g, r7g", {"*": "1.5.16"}),
        **_families("m8g, r8g, c7gn, c8gn", {"*": "1.6.6"}),
    },
    "valkey": {
        **_families("m6g, r6g, t4g, m7g, r7g, m8g, r8g, r6gd, r7gd, r8gd, c7gn, c8gn",
                    {"*": "7.2"}),
    },
    # OpenSearch Service — ENGINE_SUPPORT_SOURCES["opensearch"]
    "opensearch": {
        **_families("c6g, m6g, r6g, r6gd, im4gn, i4g, c7g, m7g, r7g, r7gd, "
                    "c8g, m8g, r8g, r8gd, i8g, i8ge",
                    {"Elasticsearch": "7.9", "OpenSearch": "1.0"}),
    },
}

# Engines whose service publishes one minimum per node family (no release lines).
_SINGLE_LINE_ENGINES = {"redis", "memcached", "valkey"}

# The family checked when the row's target family cannot be determined: the
# Graviton2 family each engine is most often moved to. A note says so.
_BASELINE_FAMILY = {
    "postgres": "m6g", "mysql": "m6g", "mariadb": "m6g",
    "aurora-mysql": "r6g", "aurora-postgresql": "r6g",
    "redis": "m6g", "memcached": "m6g", "valkey": "m6g", "opensearch": "r6g",
}

_ENGINE_LABELS = {
    "postgres": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB",
    "aurora-mysql": "Aurora MySQL", "aurora-postgresql": "Aurora PostgreSQL",
    "redis": "Redis OSS", "memcached": "Memcached", "valkey": "Valkey",
    "opensearch": "OpenSearch Service",
}

# Commercial engines: no Graviton instance classes exist for them on RDS.
_COMMERCIAL_ENGINE_NOTES = {
    "sqlserver": "SQL Server has no Graviton instance classes. Consider migrating to Aurora PostgreSQL.",
    "oracle": "Oracle has no Graviton instance classes on RDS.",
    "db2": "Db2 has no Graviton instance classes on RDS.",
}


def _normalize_engine(engine: str) -> str:
    """Cost Explorer, describe-API and display spellings -> one engine key."""
    e = (engine or "").strip().lower()
    if e.startswith("aurora"):
        return "aurora-postgresql" if "postgres" in e else "aurora-mysql"
    if "postgres" in e:
        return "postgres"
    if "sql server" in e or e.startswith("sqlserver"):
        return "sqlserver"
    if e.startswith("oracle"):
        return "oracle"
    if e.startswith("db2"):
        return "db2"
    if e in ("redis", "redis oss"):
        return "redis"
    if e in ("elasticsearch", "opensearch", "opensearch service"):
        return "opensearch"
    return e


def ver_tuple(version: str) -> Tuple[int, ...]:
    """Numeric version, padded to 3 parts: "8.0" -> (8, 0, 0), "13.4" -> (13, 4, 0).

    Padding keeps "8.0" from sorting below "8.0.17". Non-numeric parts are
    ignored, so pass the plain version (see _plain_version), never a string
    such as "OpenSearch_2.11", which would otherwise read as (11, 0, 0).
    """
    parts = tuple(int(x) for x in re.findall(r"\d+", version or ""))
    return parts + (0,) * (3 - len(parts))


def _plain_version(engine: str, version: str) -> Tuple[str, str]:
    """(release line, plain numeric version) for an engine version string.

    Returns ("", "") when the version cannot be read. Handles:
      - Aurora MySQL "8.0.mysql_aurora.3.05.2" -> ("3", "3.05.2")
      - OpenSearch "OpenSearch_2.11" -> ("OpenSearch", "2.11"),
        "Elasticsearch_7.10" -> ("Elasticsearch", "7.10")
      - MySQL/MariaDB lines are major.minor ("8.0", "10.6"); PostgreSQL lines
        are the major ("13"); the ElastiCache engines have the single line "*".
    """
    v = (version or "").strip()
    if not v:
        return "", ""
    if engine == "opensearch":
        m = re.match(r"(?i)(opensearch|elasticsearch)[_ ]?(\d+(?:\.\d+)*)", v)
        if not m:
            return "", ""
        dist = "OpenSearch" if m.group(1).lower() == "opensearch" else "Elasticsearch"
        return dist, m.group(2)
    if engine == "aurora-mysql":
        m = re.search(r"mysql_aurora\.(\d+(?:\.\d+)*)", v)
        if m:
            v = m.group(1)
        elif not re.match(r"[123](\.\d|$)", v):
            # "5.7.12"-style strings name the MySQL compatibility level, not the
            # Aurora release, so the Aurora minimums cannot be checked.
            return "", ""
    m = re.match(r"\d+(?:\.\d+)*", v)
    if not m:
        return "", ""
    v = m.group(0)
    parts = v.split(".")
    if engine in _SINGLE_LINE_ENGINES:
        return "*", v
    if engine in ("mysql", "mariadb"):
        return ".".join(parts[:2]), v
    return parts[0], v


def _rule(rules: Dict, line: str) -> Tuple[Optional[str], List[str]]:
    spec = rules.get(line)
    if spec is None:
        return None, []
    if isinstance(spec, tuple):
        return spec[0], list(spec[1])
    return spec, []


def _target_family(instance_class: str, target_class: str = "") -> Tuple[str, Optional[bool]]:
    """(Graviton family the row would move to, whether the class is already Graviton).

    The family is read from `target_class` when given, else from the
    classifier's recommended upgrade for `instance_class`. Returns ("", None)
    when neither names a family.
    """
    def _family(t: str) -> str:
        t = (t or "").lower()
        for pfx in ("db.", "cache."):
            if t.startswith(pfx):
                t = t[len(pfx):]
        return t.split(".")[0] if "." in t else ""

    if target_class:
        return _family(target_class), None
    if not instance_class:
        return "", None
    info = classify_and_upgrade(
        instance_class,
        "rds" if instance_class.startswith("db.")
        else "elasticache" if instance_class.startswith("cache.")
        else "ec2",
    )
    if not info:
        return "", None
    if info.is_graviton:
        return _family(info.raw), True
    return _family(info.graviton_upgrade or ""), False


def _lowest_minimum(rules: Dict) -> str:
    """The lowest supported version across a family's release lines, for display."""
    if set(rules) == {"Elasticsearch", "OpenSearch"}:
        return f"Elasticsearch {rules['Elasticsearch']}+ or any OpenSearch"
    mins = [_rule(rules, line)[0] for line in rules]
    mins = [m for m in mins if m]
    if not mins:
        return ""
    return min(mins, key=ver_tuple)


def check_engine_graviton_readiness(engine: str, version: str, instance_class: str = "",
                                    target_class: str = "") -> dict:
    """Check whether an engine version runs on the Graviton family a row moves to.

    Args:
        engine: Engine name in any common spelling ("postgres", "PostgreSQL",
            "aurora-mysql", "Redis", "opensearch", ...).
        version: Running version as the describe APIs report it ("13.4",
            "8.0.mysql_aurora.3.05.2", "OpenSearch_2.11", "Elasticsearch_7.10").
            Empty when unknown.
        instance_class: Current class, e.g. "db.r5.xlarge". The target family
            is the classifier's recommended upgrade for it.
        target_class: Overrides the target ("db.r8g.xlarge" or a family).

    Returns:
        A dict with engine, current_version, status ("ready",
        "upgrade_required", "blocked", "verify_version" or "unknown"),
        graviton_min_version, recommended_version, steps, note and
        instance_class. When no version is known the dict carries version and
        notes instead of current_version and note.
    """
    key = _normalize_engine(engine)

    if key in _COMMERCIAL_ENGINE_NOTES:
        note = _COMMERCIAL_ENGINE_NOTES[key]
        if not version:
            return {"engine": engine, "version": "—", "status": "blocked",
                    "graviton_min_version": "N/A", "notes": note,
                    "instance_class": instance_class}
        return {"engine": engine, "current_version": version, "status": "blocked",
                "graviton_min_version": "N/A", "recommended_version": "N/A",
                "steps": [note], "note": note, "instance_class": instance_class}

    support = GRAVITON_ENGINE_SUPPORT.get(key)
    if not support:
        return {"engine": engine, "version": version, "status": "unknown",
                "notes": f"Engine '{engine}' not in readiness database. Check AWS docs.",
                "instance_class": instance_class}

    label = _ENGINE_LABELS.get(key, engine)
    family, already_graviton = _target_family(instance_class, target_class)
    if target_class and "." not in target_class:
        family = target_class.lower()
    family_note = ""
    if not family:
        family = _BASELINE_FAMILY[key]
        family_note = (f" No target family was known, so this is checked against "
                       f"{family}; newer Graviton families can need newer versions.")

    rules = support.get(family)
    if rules is None:
        # Distinguish "this engine is not offered on that family" from "the
        # family is not in the reviewed table" — the first is a fact from the
        # AWS docs, the second only means the table needs a review.
        known = {f for eng in GRAVITON_ENGINE_SUPPORT.values() for f in eng}
        offered_on = sorted(support)
        if family in known:
            note = (f"{label} is not offered on {family} instances "
                    f"(AWS docs reviewed {ENGINE_SUPPORT_REVIEWED}). Supported "
                    f"Graviton families: {', '.join(offered_on)}.")
            if key == "redis" and "valkey" in GRAVITON_ENGINE_SUPPORT:
                note += " Valkey 7.2+ runs on it."
            status = "upgrade_required"
        else:
            note = (f"{family} is not in the engine support table reviewed "
                    f"{ENGINE_SUPPORT_REVIEWED}; confirm {label} support in the AWS docs.")
            status = "verify_version"
        result = {"engine": engine, "status": status, "graviton_min_version": "N/A",
                  "instance_class": instance_class}
        if version:
            result.update(current_version=version, recommended_version="N/A",
                          steps=[note], note=note)
        else:
            result.update(version="—", notes=note)
        return result

    if not version:
        lowest = _lowest_minimum(rules)
        return {
            "engine": engine, "version": "—", "status": "verify_version",
            "graviton_min_version": lowest,
            "notes": (
                f"{label} on {family} needs {lowest}+ (minimums differ per release "
                f"line). Version not available from billing data — verify with "
                f"`rds describe-db-instances`, `elasticache describe-cache-clusters` "
                f"or `opensearch describe-domains`.{family_note}"
            ),
            "instance_class": instance_class,
        }

    line, plain = _plain_version(key, version)
    steps: List[str] = []
    minimum, extras = _rule(rules, line) if line else (None, [])
    recommended = minimum or ""

    if not line:
        status = "verify_version"
        note = (f"Could not read the {label} release from '{version}'; confirm it "
                f"against the {family} minimums.{family_note}")
        graviton_min = _lowest_minimum(rules)
    elif minimum is not None:
        graviton_min = minimum
        if key == "opensearch" and line == "OpenSearch":
            graviton_min = "any OpenSearch version"
        if ver_tuple(plain) >= ver_tuple(minimum) or plain in extras:
            status = "ready"
            note = f"{label} {version} is supported on {family}.{family_note}"
        else:
            status = "upgrade_required"
            note = (f"{label} {version} is below the {family} minimum "
                    f"({minimum}+ on this release line).{family_note}")
            steps.append(f"Upgrade {label} from {version} to {minimum}+ "
                         f"(the minimum for {family})")
    else:
        # This release line is not supported on the family. Either the version
        # is older than every supported line (upgrade to the next one) or newer
        # than the reviewed table knows about (verify).
        lines = [ln for ln in rules if ln != "*"]
        newer = sorted((ln for ln in lines
                        if ver_tuple(_rule(rules, ln)[0]) > ver_tuple(plain)),
                       key=lambda ln: ver_tuple(_rule(rules, ln)[0]))
        if key == "opensearch" or not newer:
            graviton_min = _lowest_minimum(rules)
            status = "verify_version"
            note = (f"{label} {version} is newer than the {family} support table "
                    f"reviewed {ENGINE_SUPPORT_REVIEWED}; confirm in the AWS docs."
                    f"{family_note}")
        else:
            target_min = _rule(rules, newer[0])[0]
            graviton_min = target_min
            recommended = target_min
            status = "upgrade_required"
            note = (f"{label} {version} is not supported on {family}; the oldest "
                    f"supported release is {target_min}+.{family_note}")
            steps.append(f"Upgrade {label} from {version} to {target_min}+ "
                         f"(the oldest release supported on {family})")

    if instance_class:
        if already_graviton:
            steps.append(f"{instance_class} is already Graviton — no instance change needed")
        elif family and not family_note:
            info = classify_and_upgrade(
                instance_class,
                "rds" if instance_class.startswith("db.")
                else "elasticache" if instance_class.startswith("cache.")
                else "ec2",
            )
            if target_class:
                steps.append(f"Change instance class: {instance_class} → {target_class}")
            elif info and info.graviton_upgrade:
                steps.append(f"Change instance class: {instance_class} → {info.graviton_upgrade}")
        elif family_note:
            steps.append(f"No Graviton equivalent found for {instance_class}")
            status = "blocked" if status == "ready" else status

    return {
        "engine": engine,
        "current_version": version,
        "status": status,
        "graviton_min_version": graviton_min,
        "recommended_version": recommended,
        "steps": steps,
        "note": note,
        "instance_class": instance_class,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. MIGRATION PLAN GENERATOR — phased plan from fleet data
# ═══════════════════════════════════════════════════════════════════════════

def generate_migration_plan(classified_instances: List[Dict], region: str = "us-east-1",
                            od_prices: Optional[Dict[str, float]] = None,
                            target_strategy: str = "latest") -> dict:
    """Generate a phased migration plan from classified fleet data.

    Prices come from `od_prices` only; nothing here calls the Pricing API.

    Args:
        classified_instances: Output from classify_usage_types
        region: AWS region (for metadata only)
        od_prices: RegionalPrices from assessment_pipeline, or a plain
            {instance_type: $/hr} dict that applies to every row
        target_strategy: "latest" or "graviton2".."graviton5"

    Returns:
        4-wave migration plan with instances, savings, and timeline per wave.
    """
    wave1_easy = []  # Managed services (RDS, ElastiCache) — instance class change
    # Managed services whose engine version is below the target family's
    # minimum (engine_readiness == "upgrade_required"): the engine upgrade comes
    # first, so they are not a Week 1-2, low-effort move.
    wave2_engine_upgrade = []
    wave3_ec2 = []  # EC2 — AMI + launch template change
    wave4_blocked = []  # Windows, no Graviton equivalent

    migratable = []
    for r in classified_instances:
        if r.get("is_graviton"):
            continue
        if is_ineligible(r):
            # Windows and the commercial RDS engines have no Graviton path
            # whatever the instance type says; Wave 4 is where they belong.
            # The classifier attaches targets on type shape alone, so without
            # this check they would land in Wave 3 (Windows) or Wave 1 (SQL
            # Server, Oracle) with savings priced from Linux/open-source rates.
            wave4_blocked.append(r)
            continue
        if not _has_target(r):
            wave4_blocked.append(r)
            continue
        migratable.append(r)

        svc = r.get("service", "ec2")
        if svc in ("rds", "elasticache", "opensearch"):
            if r.get("engine_readiness") == "upgrade_required":
                wave2_engine_upgrade.append(r)
            else:
                wave1_easy.append(r)
        else:
            # Everything else is EC2, including EKS/ECS container nodes, which
            # bill as ordinary instance hours and cannot be told apart without
            # resource tags this assessment does not read.
            wave3_ec2.append(r)

    # Per-region price maps: each row is priced from its own region's book.
    price_maps = _price_maps_by_region(migratable, od_prices)

    def _map_for(r):
        return price_maps.get(r.get("region", ""), {})

    def wave_summary(name, items, timeline, effort, blocked=False, note=""):
        cost = sum(i.get("cost", 0) for i in items)
        if blocked:
            savings = 0.0
        else:
            # Same basis as the headline KPI — see _row_savings.
            savings = sum(_row_savings(i, _map_for(i), target_strategy) for i in items)
        top = sorted(items, key=lambda x: x.get("cost", 0), reverse=True)[:5]
        # Expand abbreviated instance names for customer-facing output
        # and update graviton_upgrade to match the unified target selection
        for inst in top:
            if "raw" in inst:
                inst["raw"] = _expand_size(inst["raw"])
            if not blocked:
                # Use unified target selection to update graviton_upgrade
                _, best_target, _ = _best_savings(inst, _map_for(inst), target_strategy)
                if best_target:
                    inst["graviton_upgrade"] = _expand_size(best_target)
                    inst["graviton_target"] = _expand_size(best_target)
                elif inst.get("graviton_upgrade"):
                    inst["graviton_upgrade"] = _expand_size(inst["graviton_upgrade"])
                    inst["graviton_target"] = _expand_size(inst.get("graviton_upgrade", ""))
        # Purchase type breakdown for this wave
        pt_breakdown = {}
        for i in items:
            pt = i.get("purchase_type", "Unknown")
            pt_breakdown.setdefault(pt, {"count": 0, "cost": 0})
            pt_breakdown[pt]["count"] += 1
            pt_breakdown[pt]["cost"] += i.get("cost", 0)
        # Round costs
        for pt in pt_breakdown:
            pt_breakdown[pt]["cost"] = round(pt_breakdown[pt]["cost"], 2)
        result = {
            "wave": name,
            "instance_count": len(items),
            "total_cost": round(cost, 2),
            "est_savings": round(savings, 2),
            "timeline": timeline,
            "effort": effort,
            "top_instances": top,
        }
        if pt_breakdown and any(pt != "Unknown" for pt in pt_breakdown):
            result["purchase_type_breakdown"] = pt_breakdown
        if note:
            result["note"] = note
        return result

    waves = [
        wave_summary(
            "Wave 1: Managed Services", wave1_easy,
            "Week 1-2", "Low - instance class change, blue/green deploy",
            note=("Rows whose engine version could not be read (other accounts, "
                  "or no describe permission) are here; check their version "
                  "against the Engine Readiness table before moving them.")),
        wave_summary(
            "Wave 2: Managed Services, engine upgrade first", wave2_engine_upgrade,
            "Week 3-8", "Medium - engine version upgrade, then instance class change",
            note=("The engine version is below the minimum for the Graviton "
                  "target family. Savings arrive after the engine upgrade; see "
                  "Engine Readiness for the version each row needs.")),
        wave_summary(
            "Wave 3: EC2 Instances", wave3_ec2,
            "Week 3-6", "Medium - AMI rebuild, launch template update, testing",
            note=("Includes any EKS/ECS container nodes, which bill as ordinary "
                  "EC2 instance hours and cannot be separated without resource "
                  "tags. Their real effort is a multi-arch image rebuild, above "
                  "the AMI swap costed here; Fargate is outside this "
                  "assessment's instance-hours scope.")),
        wave_summary(
            "Wave 4: Blocked/Deferred", wave4_blocked,
            "Deferred",
            "N/A - Windows, no Graviton equivalent, or blocked software",
            blocked=True),
    ]

    total_addressable = sum(w["est_savings"] for w in waves[:3])
    return {
        "waves": waves,
        "summary": {
            "total_addressable_savings": round(total_addressable, 2),
            "total_addressable_annual": round(total_addressable * 12, 2),
            "blocked_count": len(wave4_blocked),
            "total_migratable": sum(w["instance_count"] for w in waves[:3]),
        },
        "pricing_metadata": {
            "source": "agent_provided" if od_prices else "no_pricing",
            "region": region,
            "types_priced": sum(len(m) for m in price_maps.values()),
        },
    }
