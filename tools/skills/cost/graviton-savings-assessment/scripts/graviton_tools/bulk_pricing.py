# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Bulk pricing loader — downloads AWS public pricing files and indexes into local SQLite.

Downloads per-region pricing files for ElastiCache, OpenSearch, and RDS from the
public AWS pricing endpoint (no credentials needed). Indexes into a local SQLite DB
for fast lookups. EC2 is excluded (412MB per region) — EC2 types are priced
through the AWS Pricing API only.

This is the FALLBACK tier: the pipeline asks the live Pricing API first and comes
here only for types it left unpriced. Each (service, region) pair is refreshed
on its own when older than 7 days, and a stale or missing pair returns nothing,
so an old download can never stand in for a current rate.

The database lives in the user's cache directory, not in the skill folder:
${XDG_CACHE_HOME:-~/.cache}/graviton-savings-assessment/pricing.db
"""
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

PRICING_BASE = "https://pricing.us-east-1.amazonaws.com"
# The ONLY host this module will fetch from. Enforced on every request rather
# than assumed from PRICING_BASE, because the per-region URL is a path taken from
# a downloaded JSON document: string-concatenating a value beginning "@" or
# "//host" silently retargets the request, and urlopen honours file:// and
# redirects to anywhere by default.
_ALLOWED_HOST = urlsplit(PRICING_BASE).hostname
# A regional EC2 offer file is ~470MB; the services here are far smaller. This is
# a guard against an unbounded read exhausting memory, not a size expectation.
_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse redirects outright.

    A redirect off the pricing endpoint would leave the allowlist check below
    meaningless, since it validates the URL we request, not the one we end up at.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(
            f"refusing redirect to {newurl!r}: pricing data must come directly "
            f"from {_ALLOWED_HOST}")


_opener = urllib.request.build_opener(_NoRedirects)


def _fetch_json(url: str, timeout: int):
    """Fetch and parse JSON from the pricing endpoint, or raise.

    Validates scheme and host before the request, refuses redirects, and bounds
    the read. urlopen would otherwise accept file:// and any host reachable via
    redirect — the finding behind bandit B310 and semgrep
    dynamic-urllib-use-detected.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != _ALLOWED_HOST:
        raise ValueError(
            f"refusing to fetch {url!r}: only https://{_ALLOWED_HOST} is allowed")

    with _opener.open(url, timeout=timeout) as resp:  # nosec B310 - validated above
        declared = resp.headers.get("Content-Length")
        if declared and int(declared) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"pricing file at {url!r} declares {declared} bytes, over the "
                f"{_MAX_DOWNLOAD_BYTES} cap")
        raw = resp.read(_MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > _MAX_DOWNLOAD_BYTES:
        raise ValueError(f"pricing file at {url!r} exceeds the "
                         f"{_MAX_DOWNLOAD_BYTES} byte cap")
    return json.loads(raw)


def _get_region_url(service_code: str, region: str) -> Optional[str]:
    """Resolve the per-region pricing file URL from the service's region index.

    service_code comes from BULK_SERVICES (a module constant), never from input.
    """
    url = f"{PRICING_BASE}/offers/v1.0/aws/{service_code}/current/region_index.json"
    try:
        data = _fetch_json(url, timeout=10)
        entry = (data.get("regions") or {}).get(region)
        if not entry or not entry.get("currentVersionUrl"):
            return None
        # urljoin, not concatenation: a value starting "@" or "//" would change
        # the host under a bare +. _fetch_json re-validates regardless.
        return urljoin(PRICING_BASE, entry["currentVersionUrl"])
    except Exception as e:
        # Was a bare `except: pass`, indistinguishable from "region not offered".
        logger.warning("Bulk pricing region index failed for %s/%s: %s: %s",
                       service_code, region, type(e).__name__, e)
    return None


def _default_cache_dir() -> Path:
    """${XDG_CACHE_HOME:-~/.cache}/graviton-savings-assessment.

    It used to be a `cache/` folder inside the skill's own scripts directory,
    so a run wrote into the source tree a user had copied into their agent's
    skills location (and into git, with no .gitignore covering it). A relative
    XDG_CACHE_HOME is ignored, as the XDG spec requires.
    """
    base = os.environ.get("XDG_CACHE_HOME", "")
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "graviton-savings-assessment"


CACHE_DIR = _default_cache_dir()
PRICING_DB = CACHE_DIR / "pricing.db"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days

# Services to download bulk pricing for (EC2 excluded — too large)
BULK_SERVICES = {
    "AmazonRDS": {"engine_key": "databaseEngine", "prefix": "db."},
    "AmazonElastiCache": {"engine_key": "cacheEngine", "prefix": "cache."},
    "AmazonES": {"engine_key": None, "prefix": ""},
}

# Engine preference when a type has rows for several engines, compared by
# EQUALITY: a substring test let "mysql" select an "aurora mysql" row. Redis
# leads the cache engines because it is the pipeline's default ElastiCache
# coordinate, so a bulk rate lands at the same coordinate as an API rate.
ENGINE_PREFERENCE = ["mysql", "postgresql", "mariadb", "aurora mysql",
                     "aurora postgresql", "redis", "valkey", "memcached"]

# Commercial engines have no Graviton instance classes and are never stored.
_COMMERCIAL_ENGINE_TOKENS = ("oracle", "sql server", "db2")


def _service_code_for_type(instance_type: str) -> Optional[str]:
    """The bulk service holding `instance_type`, or None (EC2 is not held)."""
    t = (instance_type or "").strip().lower()
    if t.startswith("db."):
        return "AmazonRDS"
    if t.startswith("cache."):
        return "AmazonElastiCache"
    if t.endswith(".search"):
        return "AmazonES"
    return None


def _ensure_cache_dir() -> None:
    """Create the cache directory owner-only (0o700), refusing a symlinked one."""
    if CACHE_DIR.is_symlink():
        raise OSError(f"refusing to use symlinked pricing cache directory {CACHE_DIR}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CACHE_DIR, 0o700)


def _connect() -> sqlite3.Connection:
    """Open the pricing DB, owner-only, refusing a symlink planted in its place."""
    _ensure_cache_dir()
    if PRICING_DB.is_symlink():
        raise OSError(f"refusing to use symlinked pricing database {PRICING_DB}")
    conn = sqlite3.connect(str(PRICING_DB), timeout=30)
    _init_db(conn)  # creates the file if it is new
    try:
        os.chmod(PRICING_DB, 0o600)
    except OSError:
        pass
    return conn


def _init_db(conn: sqlite3.Connection):
    """Create the pricing table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS od_prices (
            instance_type TEXT NOT NULL,
            region TEXT NOT NULL,
            service TEXT NOT NULL,
            engine TEXT DEFAULT '',
            od_price REAL NOT NULL,
            PRIMARY KEY (instance_type, region, service, engine)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()


def _refreshed_key(service_code: str, region: str) -> str:
    return f"refreshed:{service_code}:{region}"


def _age_seconds(conn: sqlite3.Connection, service_code: str, region: str) -> Optional[float]:
    """Seconds since (service, region) was last indexed, None if it never was."""
    row = conn.execute("SELECT value FROM metadata WHERE key = ?",
                       (_refreshed_key(service_code, region),)).fetchone()
    if not row:
        return None
    try:
        return time.time() - float(row[0])
    except (TypeError, ValueError):
        return None


def _is_fresh(conn: sqlite3.Connection, service_code: str, region: str) -> bool:
    age = _age_seconds(conn, service_code, region)
    return age is not None and 0 <= age < CACHE_MAX_AGE_SECONDS


def _usage_type_ok(service_code: str, usage_type: str) -> bool:
    """True if `usage_type` is the running-instance rate for the service.

    The same rule as assessment_pipeline._od_usage_type_ok, applied when the
    offer file is indexed. Without it the ElastiCache SyncDurability add-on
    (about a seventh of the node rate) and other add-on SKUs were stored under
    the node's own key and could win it.
    """
    ut = (usage_type or "").lower()
    if "extendedsupport" in ut:
        return False
    if service_code == "AmazonElastiCache":
        return "nodeusage" in ut and "sync" not in ut
    if service_code == "AmazonES":
        return "esinstance" in ut
    if service_code == "AmazonRDS":
        return "iooptimized" not in ut
    return True


def _parse_rows(service_code: str, region: str, data: dict) -> List[tuple]:
    """Running-instance on-demand rows from one offer file.

    Returns [(instance_type, region, service, engine, od_price)], one per key.
    When two SKUs survive the filters under the same key the lower rate is kept,
    so the result does not depend on the file's SKU order (it used to be last
    one wins).
    """
    svc_config = BULK_SERVICES[service_code]
    engine_key = svc_config["engine_key"]

    products = data.get("products", {})
    terms = data.get("terms", {}).get("OnDemand", {})

    best: Dict[tuple, float] = {}
    collisions = 0
    for sku in sorted(products):
        attrs = products[sku].get("attributes", {})

        # Only instance products (not storage, data transfer, etc.)
        instance_type = attrs.get("instanceType", "")
        if not instance_type:
            continue

        # Skip non-standard locations (Outposts, Local Zones, Wavelength)
        location_type = attrs.get("locationType", "")
        if location_type and location_type != "AWS Region":
            continue

        # For RDS: only Single-AZ (Multi-AZ is ~2x and not comparable)
        if service_code == "AmazonRDS":
            deployment = attrs.get("deploymentOption", "")
            if deployment and deployment != "Single-AZ":
                continue

        if not _usage_type_ok(service_code, attrs.get("usagetype", "")):
            continue

        engine = (attrs.get(engine_key, "") if engine_key else "").strip().lower()
        if any(tok in engine for tok in _COMMERCIAL_ENGINE_TOKENS):
            continue

        price = None
        for offer in (terms.get(sku) or {}).values():
            for dim in (offer.get("priceDimensions") or {}).values():
                try:
                    p = float((dim.get("pricePerUnit") or {}).get("USD", "0"))
                except (ValueError, TypeError):
                    continue
                if p > 0:
                    price = p
                    break
            break  # Only first offer
        if price is None:
            continue

        key = (instance_type.lower(), region, service_code, engine)
        if key in best:
            collisions += 1
            if price < best[key]:
                best[key] = price
        else:
            best[key] = price

    if collisions:
        logger.debug("Bulk pricing %s/%s: %d SKU collisions resolved to the lower rate",
                     service_code, region, collisions)
    return [k + (v,) for k, v in sorted(best.items())]


def _parse_and_store(conn: sqlite3.Connection, service_code: str, region: str, data: dict):
    """Replace one (service, region)'s rows with those parsed from `data`."""
    rows = _parse_rows(service_code, region, data)
    with conn:
        conn.execute("DELETE FROM od_prices WHERE region = ? AND service = ?",
                     (region, service_code))
        conn.executemany(
            "INSERT OR REPLACE INTO od_prices (instance_type, region, service, engine, od_price) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                     (_refreshed_key(service_code, region), str(time.time())))
    return len(rows)


def _download_and_index(conn: sqlite3.Connection, service_code: str, region: str) -> int:
    """Download a per-region pricing file and index it.

    The region's existing rows are replaced only after a successful download
    and parse, so a failed refresh leaves them in place (and still stale).
    """
    url = _get_region_url(service_code, region)
    if not url:
        return 0

    try:
        data = _fetch_json(url, timeout=60)
        return _parse_and_store(conn, service_code, region, data)
    except Exception as e:
        # Returning 0 silently made a download failure look like an empty
        # catalogue. Log it, so a broken bulk tier is diagnosable instead of
        # quietly falling through to the API for every type.
        logger.warning("Bulk pricing download failed for %s/%s: %s: %s",
                       service_code, region, type(e).__name__, e)
        return 0


def warm_cache(regions: List[str] = None) -> dict:
    """Download and index pricing for every bulk service in `regions`.

    Only (service, region) pairs older than CACHE_MAX_AGE_SECONDS, or never
    indexed, are downloaded. Other regions' rows are never touched: the whole
    table used to be wiped whenever the file's mtime aged out, then refilled
    for the requested regions only.

    Args:
        regions: List of AWS region codes. Defaults to ["us-east-1"].

    Returns:
        Summary of what was downloaded and indexed.
    """
    if not regions:
        regions = ["us-east-1"]

    conn = _connect()
    try:
        results = {}
        total = 0
        refreshed = 0
        for region in regions:
            for service_code in BULK_SERVICES:
                if _is_fresh(conn, service_code, region):
                    results[f"{service_code}/{region}"] = "cache_fresh"
                    continue
                count = _download_and_index(conn, service_code, region)
                results[f"{service_code}/{region}"] = count
                total += count
                refreshed += 1
        stored = conn.execute("SELECT COUNT(*) FROM od_prices").fetchone()[0]
    finally:
        conn.close()

    return {
        "status": "refreshed" if refreshed else "cache_fresh",
        "total_prices": stored,
        "indexed_now": total,
        "by_service_region": results,
        "regions": regions,
        "db_path": str(PRICING_DB),
    }


def lookup_prices(instance_types: List[str], region: str = "us-east-1") -> Dict[str, float]:
    """Look up OD prices for a list of instance types from the local cache.

    Only (service, region) data that is fresh is read; a stale or missing pair
    returns nothing for its types, so the caller reports them unpriced rather
    than priced from an old file. Applies ENGINE_PREFERENCE by exact engine
    name. Commercial engines are never stored. Returns {instance_type: od_price}.
    """
    if not PRICING_DB.exists() or PRICING_DB.is_symlink():
        return {}

    conn = sqlite3.connect(str(PRICING_DB), timeout=30)
    try:
        _init_db(conn)
        fresh: Dict[str, bool] = {}
        prices = {}
        for it in instance_types:
            it_lower = it.strip().lower()
            service_code = _service_code_for_type(it_lower)
            if not service_code:
                continue
            if service_code not in fresh:
                fresh[service_code] = _is_fresh(conn, service_code, region)
            if not fresh[service_code]:
                continue

            # Try exact match first, then size-expanded variant (e.g., db.m5.12xl → db.m5.12xlarge)
            variants = [it_lower]
            expanded = re.sub(r'\.(\d*)xl$', r'.\1xlarge', it_lower)
            if expanded != it_lower:
                variants.append(expanded)
            abbreviated = re.sub(r'\.(\d*)xlarge$', r'.\1xl', it_lower)
            if abbreviated != it_lower:
                variants.append(abbreviated)

            rows = []
            for variant in variants:
                rows = conn.execute(
                    "SELECT engine, od_price FROM od_prices "
                    "WHERE instance_type = ? AND region = ? AND service = ? "
                    "ORDER BY engine",
                    (variant, region, service_code)
                ).fetchall()
                if rows:
                    break

            if not rows:
                continue

            if len(rows) == 1:
                prices[it] = rows[0][1]
                continue
            best = None
            for pref in ENGINE_PREFERENCE:
                for engine, price in rows:
                    if engine == pref:
                        best = (engine, price)
                        break
                if best:
                    break
            if not best:
                best = min(rows, key=lambda x: (x[1], x[0]))
            prices[it] = best[1]
    finally:
        conn.close()
    return prices
