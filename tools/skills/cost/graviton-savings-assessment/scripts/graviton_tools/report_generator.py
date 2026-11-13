# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Report generator — produces markdown and HTML reports from estimate_graviton_savings output.

Generates both reports internally and writes them to disk. Returns file paths only.
The agent never sees the HTML content, keeping the terminal clean.
"""
import html
import json
import hashlib
import os
import re
from datetime import datetime, timedelta

# Default estimated NIH (normalized instance-hours) reduction (%) that the
# price-performance slider opens at. Range 0-40%.
#
# 10, the Graviton Savings Dashboard's own EC2EfficiencyGain default, so the
# HTML opens on the figure GSD shows. stdout and Markdown are always price-only,
# so the HTML headline on open differs from them by this assumption; the page
# labels it, and --nih-reduction 0 makes all three the same figure. A
# performance uplift is an assumption, not a measurement.
#
# When the slider is moved, the headline applies the rate FLAT — once,
# regardless of how many generations an instance advances — which matches the
# Graviton Savings Dashboard's "Estimated NIH % Reduction" control in both value
# and model. The per-hop compounded form, (1 + rate)^-hops, feeds only the
# "If All -> Latest Generation" comparison tile: it credits a Graviton4 target
# with needing fewer instance-hours than a Graviton2 target for identical work,
# which is the more defensible model but also the more speculative claim.
PERF_DEFAULT_PCT = 10.0

# Alias for the CLI's --perf-per-gen spelling of --nih-reduction.
NIH_DEFAULT_PCT = PERF_DEFAULT_PCT

# What the spend figures are, for report headers when the assessment JSON does
# not carry its own statement (summary.spend_basis).
DEFAULT_SPEND_BASIS = ('Amortized cost of instance running hours (EC2, RDS, ElastiCache, OpenSearch) from AWS Cost Explorer, counting usage charges only; credits, refunds, other billing adjustments and AWS Marketplace are excluded.')


def _source_hash() -> str:
    """Combined SHA-256 of every module that can change a figure (not this one).

    Printed in each report footer so two reports can be checked for having come
    from the same computation. Every module on the pricing and target-selection
    path is included, since any of them moves the savings.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    modules = ["assessment_pipeline.py", "instance_classifier.py",
               "fleet_tools.py", "realized_savings.py", "pricing_comparison.py",
               "managed_offerings.py", "instance_offerings.py", "bulk_pricing.py"]
    h = hashlib.sha256()
    for m in sorted(modules):
        path = os.path.join(script_dir, m)
        if os.path.exists(path):
            with open(path, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:12]


def _fmt_cost(amount: float) -> str:
    """Format cost as $X,XXX or $X.XM."""
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    else:
        return f"${amount:,.2f}"


def _engine_badge(status: str) -> tuple:
    """Returns (css_class, marker, text).

    The marker is intentionally empty — status is conveyed by the badge's
    token-based color and its text label, not by an emoji glyph. The brand
    system defines no icon set and explicitly excludes emoji, so callers
    render `text` and let CSS carry the semantics.
    """
    s = status.lower()
    if "ready" in s or "supported" in s:
        return "ready", "", "Ready"
    elif "upgrade" in s:
        return "upgrade", "", "Upgrade needed"
    elif "verify" in s:
        return "upgrade", "", "Verify version"
    elif "blocked" in s:
        return "blocked", "", "Blocked"
    else:
        return "upgrade", "", "Unknown"


from .instance_classifier import expand_size as _expand_size  # one definition


def _build_engine_grouped_html(engine_checks: list) -> str:
    """Build HTML engine readiness section grouped by status category.

    Groups engines into Blocked, Needs Upgrade, and Ready categories with
    color-coded header rows and backgrounds. Deduplicates by engine+version.
    Omits section entirely when no engine checks exist.
    """
    if not engine_checks:
        return ""  # Omit section entirely

    # Deduplicate by engine + version (same engine with different instance types → one row)
    seen = set()
    deduped = []
    for check in engine_checks:
        key = (check.get("engine", ""), check.get("current_version", check.get("version", "")), check.get("status", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(check)

    # Group by status category
    groups = {"Blocked": [], "Needs Upgrade": [], "Ready": [], "Verify": []}
    for check in deduped:
        _, _, status_text = _engine_badge(check.get("status", ""))
        # Only a positive "ready" is Ready. "unknown" (engine not in the table)
        # was once grouped as Ready by an else branch, under a green header,
        # and the "Verify version" text was filed under Needs Upgrade.
        if status_text == "Blocked":
            groups["Blocked"].append(check)
        elif status_text == "Upgrade needed":
            groups["Needs Upgrade"].append(check)
        elif status_text == "Ready":
            groups["Ready"].append(check)
        else:
            groups["Verify"].append(check)

    rows = ""
    # Brand tokens, not raw hex — see the :root block in the HTML template.
    status_colors = {
        "Blocked": "var(--red-100)",
        "Needs Upgrade": "var(--amber-50)",
        "Ready": "var(--green-100)",
        "Verify": "var(--blue-50)",
    }
    for status_name, checks in groups.items():
        if not checks:
            continue
        bg = status_colors[status_name]
        label = f"{status_name} ({len(checks)})" if status_name != "Verify" else f"Needs Version Verification ({len(checks)})"
        rows += f'<tr style="background:{bg};font-weight:600"><td colspan="5">{label}</td></tr>\n'
        for check in checks:
            rows += f'<tr style="background:{bg}33"><td>{check.get("engine","")}</td>'
            rows += f'<td>{check.get("current_version","") or check.get("version","") or "—"}</td><td>{check.get("status","")}</td>'
            rows += f'<td>{check.get("graviton_min_version","")}</td><td>{check.get("notes","") or check.get("note","")}</td></tr>\n'

    return (
        f'<section><h2>Engine Readiness</h2>\n'
        f'<table><tr><th>Engine</th><th>Version</th><th>Status</th>'
        f'<th>Min Graviton Version</th><th>Notes</th></tr>\n{rows}</table>'
        f'</section>'
    )


def _sort_engines_for_md(engine_checks: list) -> list:
    """Sort engine checks by status priority for Markdown rendering.

    Order: Blocked first (0), then Needs Upgrade (1), then Ready (2).
    """
    priority = {"blocked": 0, "upgrade_required": 1, "verify_version": 1, "ready": 2, "unknown": 3}
    return sorted(engine_checks, key=lambda c: priority.get(c.get("status", "").lower(), 3))


_STRATEGY_LABELS = {
    "latest": "Default next-gen (n+1)",
    "graviton2": "Graviton2 (whole fleet)",
    "graviton3": "Graviton3 (whole fleet)",
    "graviton4": "Graviton4 (whole fleet)",
    "graviton5": "Graviton5 (whole fleet)",
}

# target_strategy -> the HTML generation radio the report opens on. Strategies
# with no radio of their own open on "Default next-gen".
_STRATEGY_RADIO = {"graviton2": "g2", "graviton3": "g3",
                   "graviton4": "g4", "graviton5": "g5"}


def _months_between(start: str, end: str):
    """Months in [start, end), or None; fleet_tools.months_in_period is the rule."""
    from .fleet_tools import months_in_period
    return months_in_period(start, end)


def _period_info(summary: dict) -> dict:
    """The analysis period and the basis of every cost figure in the reports.

    The pipeline divides all cost and hours figures by the number of months in
    the period (summary.period.basis == "monthly_average"), so "monthly" and
    "x 12" are right for any period length. A result without that marker is
    per-month only when its period is one month; for a longer one the figures
    are period totals and annualise by 12 / months instead.
    """
    period = summary.get("period") or {}
    date_range = summary.get("date_range") or {}
    start = period.get("start") or date_range.get("start") or ""
    end = period.get("end") or date_range.get("end") or ""
    months = period.get("months")
    if not isinstance(months, (int, float)) or months <= 0:
        months = _months_between(start, end)
    averaged = period.get("basis") == "monthly_average"
    monthly = averaged or months is None or abs(months - 1) < 0.05
    return {
        "start": start, "end": end, "months": months,
        "averaged": averaged, "monthly": monthly,
        "annual_factor": 12.0 if monthly else 12.0 / months,
    }


def _plural(n: int, word: str, plural: str = "") -> str:
    """'1 instance type', '3 instance types'."""
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


def _months_text(months) -> str:
    if months is None:
        return ""
    if abs(months - round(months)) < 0.01:
        n = int(round(months))
        return f"{n} month" if n == 1 else f"{n} months"
    return f"{months:.1f} months"


def _period_text(period: dict) -> str:
    """One sentence naming the period (inclusive last day) and the figures' basis."""
    start, end = period["start"], period["end"]
    if not start or not end:
        return "Analysis period not recorded"
    try:
        last = (datetime.strptime(end, "%Y-%m-%d").date()
                - timedelta(days=1)).isoformat()
    except ValueError:
        last = end
    length = _months_text(period["months"])
    span = f"{start} to {last}" + (f" ({length})" if length else "")
    if period["averaged"]:
        basis = "figures are monthly averages over the period"
    elif period["monthly"]:
        basis = "figures cover one month"
    else:
        adjective = length.replace(" months", "-month").replace(" month", "-month")
        basis = (f"figures are totals for the {adjective} period; annual = "
                 f"x{period['annual_factor']:.2f}")
    return f"Analysis period {span}; {basis}"


def _spend_basis(summary: dict) -> str:
    return summary.get("spend_basis") or DEFAULT_SPEND_BASIS


def _completeness(summary: dict):
    """(complete, failed_pulls). complete is None when the result predates the flag."""
    dc = summary.get("data_completeness") or {}
    complete = dc.get("complete") if isinstance(dc, dict) else None
    failed = list(dc.get("failed_pulls") or []) if isinstance(dc, dict) else []
    return complete, failed


def _nextgen_key(c: dict):
    """The generation key ("g2".."g5") of a row's default next-gen target.

    The generation of the classifier's graviton_upgrade (the default target),
    read by instance_classifier.graviton_generation. The generation-number rule
    is only the fallback for rows without one. Newer generations are tried
    before older ones when the wanted one has no figure, as the classifier does.
    """
    from .instance_classifier import graviton_generation
    label = graviton_generation(c.get("graviton_upgrade") or "")
    labels = [g.label for g in GENERATIONS]
    if label in labels:
        want = labels.index(label)
    else:
        gen = c.get("generation") or 5
        want = (0 if gen <= 5 else 1 if gen == 6 else 2 if gen == 7
                else 3 if c.get("graviton5") else 2)
    keys = [g.key for g in GENERATIONS]
    order = [want] + list(range(want + 1, len(keys))) + list(range(want - 1, -1, -1))
    for i in order:
        if c.get(GENERATIONS[i].savings_field) is not None:
            return keys[i]
    return None


def _not_eligible_reason(c: dict):
    """Why a non-Graviton row cannot earn Graviton savings, or None if it can.

    The same rule score_graviton_fleet uses (fleet_tools.is_ineligible), so a
    row the headline excludes can never add savings to any report total.
    """
    from .fleet_tools import is_commercial_engine, is_ineligible, is_commitment_locked, _is_windows
    if c.get("is_graviton"):
        return None
    if c.get("unclassified"):
        return "Unrecognised instance type"
    if _is_windows(c):
        return "Windows (no Graviton path)"
    if is_commercial_engine(c):
        return f"{c.get('database_engine') or 'Commercial engine'} (no Graviton instance classes)"
    if is_commitment_locked(c):
        fam = (c.get("raw") or "").rsplit(".", 1)[0]
        isp, ri = c.get("cost_sp_isp") or 0, c.get("cost_ri_locked") or 0
        if isp and ri:
            what, end = "EC2 Instance Savings Plan and Reserved Instances hold", ""
        elif isp:
            what, end = "EC2 Instance Savings Plan holds", c.get("isp_end", "")
        else:
            svc = c.get("service") or "ec2"
            what = {"rds": "Reserved DB instances hold", "elasticache": "Reserved nodes hold",
                    "opensearch": "Reserved Instances hold"}.get(
                        svc, "Standard Reserved Instances hold")
            end = c.get("ri_end", "")
        until = f" until {end}" if end else " until they expire"
        return f"{what} the {fam} family{until}"
    if is_ineligible(c):
        # Any other platform fleet_tools rules out (e.g. "Linux with SQL Server
        # Standard": SQL Server has no arm64 build).
        return f"Licensed software with no Graviton build ({c.get('platform') or 'platform'})"
    if not (c.get("graviton_upgrade") or any(c.get(g.target_field) for g in GENERATIONS)):
        return "No Graviton counterpart"
    return None


def _earns_savings(c: dict) -> bool:
    """True for a row whose savings count: not Graviton yet, and eligible."""
    return not c.get("is_graviton") and _not_eligible_reason(c) is None


def _upgradeable_cost(classified: list, kpis: dict) -> float:
    """Spend that can move to Graviton, on the headline's own basis.

    kpis.upgradeable_cost when the scorer supplied it; otherwise the eligible
    rows that have a target. Counting every row with a graviton_upgrade string
    included Windows, SQL Server and Oracle spend.
    """
    if (kpis or {}).get("upgradeable_cost") is not None:
        return kpis["upgradeable_cost"]
    return sum(c.get("cost", 0) or 0 for c in classified
               if _earns_savings(c)
               and (c.get("graviton_upgrade")
                    or any(c.get(g.target_field) for g in GENERATIONS)))


def _not_eligible_rows(classified: list) -> list:
    """Every non-Graviton row with no Graviton path, each with its reason.

    Built once from the classified rows. The migration plan's Wave 4 holds the
    same rows, but only its top five, so it cannot be the source of a list.
    """
    rows = []
    for c in classified:
        reason = _not_eligible_reason(c)
        if reason:
            rows.append({**c, "_reason": reason})
    return sorted(rows, key=lambda r: -r.get("cost", 0))


def _wave(plan: dict, index: int) -> dict:
    """Wave `index` (0-based) of the migration plan, list or dict shaped."""
    raw = plan.get("waves", []) if isinstance(plan, dict) else []
    if isinstance(raw, list):
        w = raw[index] if len(raw) > index and isinstance(raw[index], dict) else {}
        return {"count": w.get("instance_count", w.get("count", 0)),
                "cost": w.get("total_cost", w.get("cost", 0)),
                "est_savings": w.get("est_savings", 0)}
    if isinstance(raw, dict):
        w = raw.get(f"wave_{index + 1}", {})
        return {"count": w.get("count", 0), "cost": w.get("cost", 0),
                "est_savings": w.get("est_savings", 0)}
    return {"count": 0, "cost": 0, "est_savings": 0}


def _next_steps(assessment: dict) -> list:
    """Recommended next steps as (title, detail) pairs, for both report formats.

    One list for both renderers, so the HTML and Markdown cannot recommend
    different things for the same fleet.
    """
    score = assessment.get("score", {}) or {}
    plan = assessment.get("migration_plan", {}) or {}
    summary = assessment.get("summary", {}) or {}
    engine_checks = assessment.get("engine_readiness", []) or []
    kpis = score.get("kpis", {}) or {}
    opportunities = score.get("top_opportunities", []) or []

    items = []
    complete, failed = _completeness(summary)
    if complete is False:
        items.append((
            "Re-run once the failed Cost Explorer pulls succeed",
            f"{len(failed)} pull(s) failed ({', '.join(failed[:4])}"
            f"{'…' if len(failed) > 4 else ''}), so spend and savings are understated."))

    w1 = _wave(plan, 0)
    if w1["count"] > 0:
        items.append((
            "Migrate Wave 1 managed services",
            f"{_plural(w1['count'], 'instance type')}, {_fmt_cost(w1['est_savings'])}/mo "
            f"estimated savings with minimal effort."))

    upgrades = [c for c in engine_checks
                if "upgrade" in (c.get("status") or "").lower()]
    if upgrades:
        engines = sorted({str(c.get("engine", "")) for c in upgrades if c.get("engine")})
        items.append((
            "Upgrade engines below the Graviton minimum",
            f"{_plural(len(upgrades), 'engine version')} ({', '.join(engines)}) "
            f"{'needs' if len(upgrades) == 1 else 'need'} an upgrade before the instance "
            f"class can change."))

    unverified = [c for c in engine_checks if c.get("status") == "verify_version"]
    if unverified:
        items.append((
            "Confirm engine versions",
            f"{_plural(len(unverified), 'engine')} had no version available, usually because the "
            f"optional describe permissions are missing. Grant rds:DescribeDBInstances, "
            f"elasticache:DescribeCacheClusters and es:DescribeDomains and re-run, or "
            f"check the versions in the console."))

    items.append((
        "Identify container workloads",
        "Determine which EC2 instances are EKS/ECS nodes; they need multi-arch image "
        "builds rather than an AMI swap."))

    mismatched = sum(
        1 for o in opportunities
        if o.get("pricing_source") == "capacity_adjusted"
        or _has_size_mismatch(o.get("instance_type", "") or o.get("current", ""),
                              o.get("graviton_target", "")))
    if mismatched:
        items.append((
            "Validate size-mismatch migrations",
            f"{_plural(mismatched, 'top opportunity', 'top opportunities')} "
            f"{'targets' if mismatched == 1 else 'target'} a different size; test those "
            f"workloads before committing."))

    unpriced = kpis.get("unpriced_count") or 0
    if unpriced:
        items.append((
            "Price the unpriced instance types",
            f"{_plural(unpriced, 'instance type')} ({_fmt_cost(kpis.get('unpriced_cost') or 0)}/mo "
            f"spend) {'has' if unpriced == 1 else 'have'} a Graviton target but no price, so "
            f"{'its' if unpriced == 1 else 'their'} savings are excluded. "
            f"This is usually Pricing API throttling; re-run to resolve."))

    already = len(score.get("already_optimized", []) or [])
    if already:
        items.append((
            "Review already cost-optimized instances",
            f"{_plural(already, 'instance type')} {'is' if already == 1 else 'are'} priced "
            f"below {'its' if already == 1 else 'their'} Graviton target; "
            f"migrating them would cost more."))

    w4 = _wave(plan, 3)
    if w4["count"] > 0:
        items.append((
            "Plan for Windows and blocked workloads",
            f"{_plural(w4['count'], 'instance type')} ({_fmt_cost(w4['cost'])}/mo) "
            f"{'has' if w4['count'] == 1 else 'have'} no Graviton path as "
            f"{'it runs' if w4['count'] == 1 else 'they run'}; evaluate a move to Linux "
            f"or an open-source engine."))
    return items


def _extract_instance_size(instance_type: str) -> str:
    """Extract the size suffix from an instance type string.

    Examples: 'm5.32xlarge' → '32xlarge', 'db.r7g.24xlarge' → '24xlarge'
    Returns empty string if no dot-separated size found.
    """
    if not instance_type:
        return ""
    parts = instance_type.rsplit(".", 1)
    return parts[-1] if len(parts) > 1 else ""


def _has_size_mismatch(current: str, target: str) -> bool:
    """Check if source and target instance types have different sizes.

    Compares the size suffix (e.g., 'xlarge', '2xlarge', '32xlarge').
    Returns False if either type is empty or missing a size component.
    """
    src_size = _extract_instance_size(current)
    tgt_size = _extract_instance_size(target)
    if not src_size or not tgt_size:
        return False
    return src_size != tgt_size


def _strategy_label(target_strategy: str) -> str:
    """Return human-readable label for a target_strategy value."""
    return _STRATEGY_LABELS.get(target_strategy, target_strategy)


# Marker for targets whose size differs from the current instance. A glyph
# rather than a parenthetical: these sit in narrow table cells where
# " (capacity-adjusted)" wrapped and doubled the row height.
#
# This is the one glyph in the HTML report. The rest of the brand styling
# carries status through token colour and text, and the AWS brand system
# defines no icon set — so the tooltip does the real work here and the glyph
# is only an attention cue, never the sole carrier of meaning.
WARN_GLYPH = "⚠️"


# ── Graviton generations ────────────────────────────────────────────────────
# THE single place a Graviton generation is named.
#
# Headers, row builders, TOTAL rows, savings accumulators, adoption buckets, CSV
# columns, radio inputs and the JS label map all iterate this tuple. Enumerated
# by hand, any one of them could be widened without the others — a header with
# a Graviton5 column over rows with four, so every later cell sits under the
# wrong heading. From one tuple, header and body come from the same iteration,
# and adding a generation is one line here.
class Gen:
    """One Graviton generation, and the field names that go with it.

    Not a dataclass: this module supports Python 3.10+ and stays dependency-free,
    and a plain class with __slots__ is cheaper than importing dataclasses for
    four immutable instances.
    """

    __slots__ = ("key", "num", "label", "short")

    def __init__(self, key: str, num: int, label: str, short: str):
        self.key = key        # "g2"        — graviton_rates_by_gen / _targets_by_gen key
        self.num = num        # 2           — suffix of the classifier's "graviton2" field
        self.label = label    # "Graviton2" — graviton_options[].generation, and gen_bucket
        self.short = short    # "G2"        — column headings

    @property
    def savings_field(self) -> str:
        """classified_detail / opportunity field holding this gen's savings."""
        return f"est_savings_{self.key}"

    @property
    def target_field(self) -> str:
        """instance_classifier field holding this gen's base family."""
        return f"graviton{self.num}"

    def __repr__(self) -> str:
        return f"Gen({self.key!r})"


GENERATIONS = (
    Gen("g2", 2, "Graviton2", "G2"),
    Gen("g3", 3, "Graviton3", "G3"),
    Gen("g4", 4, "Graviton4", "G4"),
    Gen("g5", 5, "Graviton5", "G5"),
)
GEN_BY_LABEL = {g.label: g for g in GENERATIONS}
# Newest first. "Latest available" walks this and takes the first priced hit, so a
# family that stops at Graviton3 lands on Graviton3 rather than being dropped the
# way a fixed Graviton5 selection would drop it.
GEN_NEWEST_FIRST = tuple(reversed(GENERATIONS))


# Service key -> display label. Module-level because both the fleet detail
# sections and the opportunities tables label the same values, and they should
# not disagree about how a service is spelled.
SERVICE_LABELS = {
    "ec2": "EC2",
    "rds": "RDS",
    "elasticache": "ElastiCache",
    "opensearch": "OpenSearch",
}


def service_label(service: str) -> str:
    """Display label for a service key, upper-cased for anything unrecognised."""
    return SERVICE_LABELS.get((service or "").lower(), (service or "").upper() or "—")


def gen_zeroes() -> dict:
    """A fresh {gen_key: 0} accumulator for every generation."""
    return {g.key: 0 for g in GENERATIONS}


# ── Tables ──────────────────────────────────────────────────────────────────
class Raw(str):
    """Marks a cell whose contents are already HTML and must not be escaped."""

    __slots__ = ()


def _cell_span(cell) -> int:
    """Columns a cell occupies: 1, or its colspan when given as a tuple."""
    if isinstance(cell, tuple):
        return cell[1] if len(cell) > 1 else 1
    return 1


class Table:
    """An HTML table whose body cannot silently disagree with its header.

    Width is taken from the first header row — colspans expand, rowspan cells
    count once — and every row is checked against it as it is added. A mismatch
    raises rather than rendering, because the alternative is a report where every
    cell after the missing one sits under the wrong heading, which looks entirely
    plausible and is wrong.

    `total()` is an alias of `row()` on purpose: a TOTAL row written separately
    from the data rows is exactly where a width mismatch would slip through.

    Cells are `str` (escaped), `Raw` (not escaped), or a tuple
    `(cell, colspan[, rowspan[, style]])`. `style` lands on the element itself,
    which matters for group headings whose background must fill the cell.
    """

    __slots__ = ("_header_rows", "_rows", "_css_class", "_name", "width")

    def __init__(self, *header_rows, css_class: str = "", name: str = ""):
        if not header_rows:
            raise ValueError("a table needs at least one header row")
        self._header_rows = header_rows
        self._rows = []
        self._css_class = css_class
        self._name = name or "table"
        self.width = sum(_cell_span(c) for c in header_rows[0])

    def row(self, *cells, style: str = ""):
        """Append a body row. Raises if it is not exactly `width` columns wide."""
        got = sum(_cell_span(c) for c in cells)
        if got != self.width:
            raise ValueError(
                f"{self._name}: row is {got} column(s) wide but the header "
                f"declares {self.width}. Cells: {cells!r}"
            )
        self._rows.append((cells, style))
        return self

    # A TOTAL row is a row. Same check, no second path.
    total = row

    @staticmethod
    def _render_cell(cell, tag: str) -> str:
        rowspan, style = 1, ""
        if isinstance(cell, tuple):
            value = cell[0]
            colspan = cell[1] if len(cell) > 1 else 1
            rowspan = cell[2] if len(cell) > 2 else 1
            style = cell[3] if len(cell) > 3 else ""
        else:
            value, colspan = cell, 1
        attrs = ""
        if colspan > 1:
            attrs += f' colspan="{colspan}"'
        if rowspan > 1:
            attrs += f' rowspan="{rowspan}"'
        if style:
            attrs += f' style="{style}"'
        text = value if isinstance(value, Raw) else _esc(value)
        return f"<{tag}{attrs}>{text}</{tag}>"

    def render(self) -> str:
        cls = f' class="{self._css_class}"' if self._css_class else ""
        parts = [f"<table{cls}>"]
        for header in self._header_rows:
            parts.append(
                "<tr>" + "".join(self._render_cell(c, "th") for c in header) + "</tr>")
        for cells, style in self._rows:
            attr = f' style="{style}"' if style else ""
            parts.append(
                f"<tr{attr}>" + "".join(self._render_cell(c, "td") for c in cells)
                + "</tr>")
        parts.append("</table>")
        return "\n".join(parts)


def _esc(value) -> str:
    """Escape a value for interpolation into HTML text or a quoted attribute.

    The reports are shareable deliverables — the HTML is emailed to customers and
    opened from file:// — so every interpolated value is an injection sink. For
    example:

      * `--customer` reaches <title>, which is RCDATA: a literal </title> would
        close the element and any following <script> would execute.
      * the same value reaches the masthead subtitle as element content.

    `--customer` is free text, and in this skill an agent may fill it from chat
    text rather than a careful human typing it, so it is treated as untrusted
    regardless of who "owns" it.

    quote=True also escapes " and ', which is what makes this safe inside
    title="..." attributes. None becomes "" rather than the string "None".
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


# Refuses a symlink at the final path component. The output directory may be
# shared (/tmp, a team share), and a link planted there under a deliverable's
# name — assessment.log, say — would otherwise aim our O_TRUNC at any file the
# operator can write. Windows has no O_NOFOLLOW (0 here); creating a symlink
# there needs a privilege an unprivileged co-tenant does not have.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def open_private(path, newline=None):
    """Open path for writing UTF-8 text, owner-only (0600), never via a symlink.

    Every deliverable goes through here: the reports carry a named customer's
    full spend breakdown and account id, and the output directory may be
    world-readable at the default umask on a shared host. The mode is set at
    open rather than chmod-after, because create-then-tighten leaves a window in
    which another local user can open the file and keep the descriptor. fchmod
    then covers a file that already existed with a wider mode (O_CREAT's mode
    applies only to a new file); it acts on the descriptor, not the path, so a
    link swapped in after the open cannot redirect it either.

    Raises OSError (ELOOP) when path is a symlink.
    """
    # O_BINARY (Windows only, as CPython's tempfile adds): text mode on the fd
    # plus the io wrapper's newline translation wrote \r\r\n line ends.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW
                 | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
    except (AttributeError, OSError):
        # No fchmod on Windows before Python 3.13, and some filesystems refuse
        # mode changes. Neither may cost the operator the deliverable.
        pass
    return os.fdopen(fd, "w", encoding="utf-8", newline=newline)


def _write_private(path, content) -> None:
    """Write UTF-8 text through open_private."""
    with open_private(path) as f:
        f.write(content)


def _escape_assessment(value):
    """Return a deep copy of assessment data with every string HTML-escaped.

    generate_html interpolates assessment values into more than a hundred places
    — table cells, tooltips, callouts, badge labels. Escaping each sink
    individually leaves the next one added unprotected, and there is no way for a
    reviewer to confirm the set is complete. Escaping once at the boundary makes
    the whole downstream template safe by construction.

    Only strings are touched: numbers, bools and None pass through so cost
    arithmetic and `is None` checks behave identically. Dict KEYS are left alone —
    they are internal field names, and the code looks them up by literal.

    The input is copied rather than mutated: generate_markdown and the CSV writer
    receive the same dict and need raw values (Markdown is not HTML, and
    pre-escaped text would render as literal `&amp;` in a spreadsheet).

    Note this escapes values used for internal comparison too — `pricing_source`,
    `gen_bucket`, instance types. That is safe because escaping is a no-op for
    every value that does not contain & < > " ', and real AWS identifiers never
    do. A value that DOES contain them is exactly the case we want neutralised.
    """
    if isinstance(value, str):
        return _esc(value)
    if isinstance(value, dict):
        return {k: _escape_assessment(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_escape_assessment(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_escape_assessment(v) for v in value)
    return value


def _esc_json(payload: str) -> str:
    """Make a json.dumps() result safe to embed inside a <script> element.

    json.dumps does NOT escape <, > or /, so a string field containing
    "</script>" would end the script element early and everything after it would
    be parsed as HTML. The embedded PERF_ROWS payload is all-numeric today, so
    this is defence in depth — but it is the difference between "safe" and "safe
    until someone adds a string field", and adding one is a normal change.

    Escaping to \\uXXXX keeps the value valid JSON and identical after parsing.
    """
    return (payload.replace("<", "\\u003c")
                   .replace(">", "\\u003e")
                   .replace("&", "\\u0026"))


# Values that begin with one of these are interpreted as a formula by Excel,
# LibreOffice and Google Sheets when a CSV is opened.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in a CSV cell.

    The validation CSV is a customer deliverable. A cell beginning with = + - @
    tab or CR is evaluated on open, so a crafted value becomes
    =HYPERLINK("http://attacker", "click") for credential phishing, or
    =WEBSERVICE(...) for exfiltration.

    Numbers are returned untouched: savings are legitimately negative, and
    prefixing a real -1954.0 would corrupt the figure the CSV exists to convey.
    Only strings are guarded, by prefixing a single quote — the conventional
    escape, which spreadsheets strip on display.
    """
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


# Anything matching these is redacted from error text before it is logged or
# written into a report. botocore's AccessDenied messages embed the caller's full
# ARN, which names the operator's account and role.
# The one set of redaction rules: the log filter, summary.pricing_errors and
# the CLI's stderr messages (assess._sanitize_error) all apply it. The two used
# to differ: only the CLI masked access key ids.
_REDACT_PATTERNS = (
    (re.compile(r"arn:aws[a-z\-]*:[^\s\"']+"), "<redacted-arn>"),
    (re.compile(r"\b\d{12}\b"), "<redacted-account-id>"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "<redacted-access-key>"),
    # botocore logs "Found credentials from IAM Role: <role name>" on EC2
    # instances with an instance profile.
    (re.compile(r"(IAM Role:\s*)\S+"), r"\1<redacted-role>"),
)


def _redact_sensitive(text) -> str:
    """Strip ARNs and bare 12-digit account ids out of error text.

    Error strings reach assessment.log and summary.pricing_errors, both of which
    are written into the same directory as the customer deliverables. An
    AccessDeniedException from botocore reads "User:
    arn:aws:sts::123456789012:assumed-role/Admin/alice is not authorized to
    perform: pricing:GetProducts" — so zipping the output directory ships the
    operator's identity along with the report.
    """
    if text is None:
        return ""
    out = str(text)
    for pattern, replacement in _REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _report_subject(customer: str, account_id: str, sep: str = " · ") -> str:
    """Render the report's subject line: customer and/or account, never both twice.

    The naive form appended "· Account {id}" unconditionally, which read
    "Account 123 · Account 123" whenever the customer label already carried the
    account number (common, since a run without a known customer name is
    labelled by its account), and "N/A · Account 123" when no customer was
    given at all.

    Each fact appears at most once:
      customer + id, id not already in the label -> "Acme Corp · Account 123"
      customer label already contains the id      -> "Account 123"
      no meaningful customer                      -> "Account 123"
      neither                                     -> "N/A"
    """
    name = (customer or "").strip()
    acct = (account_id or "").strip()
    if name.upper() in ("", "N/A"):
        return f"Account {acct}" if acct else "N/A"
    if not acct or acct in name:
        return name
    return f"{name}{sep}Account {acct}"


def _warn_glyph(reason: str) -> str:
    """Return the size-warning glyph as an HTML span, tooltipped with `reason`.

    All user-facing wording is "size mismatch"; `reason` says which kind it is
    (a nearest-available substitution vs. a differing target size), which the
    shared glyph itself cannot convey. The internal field remains
    `capacity_adjusted`.
    """
    return f' <span class="size-warning" title="{_esc(reason)}">{WARN_GLYPH}</span>'


def _build_next_steps_html(assessment: dict) -> str:
    """HTML 'Recommended Next Steps' section, from the list both reports share."""
    items = _next_steps(assessment)
    if not items:
        return ""
    li_items = "\n".join(
        f"<li><strong>{_esc(title)}</strong><br>{_esc(detail)}</li>"
        for title, detail in items)
    return f"""<section>
<h2>Recommended Next Steps</h2>
<ol class="next-steps">
{li_items}
</ol>
</section>
"""


# Static link sets, shared by the HTML and Markdown builders below so the two
# reports cannot drift. (label, url, blurb) — blurb is "" where the label alone
# carries it, which is the case for the call-to-action list.
_CTA_LINKS = [
    ("Getting Started with Graviton",
     "https://aws.amazon.com/ec2/graviton/getting-started/",
     "for a step-by-step transition overview."),
    ("AWS Graviton Technical Guide",
     "https://github.com/aws/aws-graviton-getting-started",
     "for additional technical information."),
    ("AWS Partners",
     "https://aws.amazon.com/ec2/graviton/partners/",
     "to complement your resources and accelerate your migration."),
]

# Wrapped blurbs are parenthesised explicitly. Implicit concatenation inside a
# list is indistinguishable from a forgotten comma — to a reader and to a linter
# (semgrep string-concat-in-list) — and the failure mode is a silently merged
# entry rather than an error.
_RESOURCE_LINKS = [
    ("Compute Optimizer",
     "https://aws.amazon.com/compute-optimizer/",
     ("Rightsize workloads according to your workload preferences through "
      + "artificial intelligence and machine learning-based analytics to reduce "
      + "costs by up to 25%.")),
    ("Cost Optimization Hub",
     "https://aws.amazon.com/aws-cost-management/cost-optimization-hub/",
     ("Provides you with a comprehensive view of your cost optimization "
      + "recommendations across your AWS Regions and AWS accounts within your "
      + "organization.")),
    ("AWS Graviton Processor Overview",
     "https://aws.amazon.com/ec2/graviton/",
     ("An overview of the AWS Graviton processor, its key features and benefits "
      + "for cost-optimization and performance improvements.")),
    ("Graviton Fast Start",
     "https://aws.amazon.com/ec2/graviton/fast-start/",
     ("The AWS Graviton Fast Start program helps you quickly and easily move "
      + "your workloads to AWS Graviton in as little as four hours for many "
      + "applications such as serverless, containerized, database, and caching.")),
]


def _build_call_to_action_html() -> str:
    """Build the HTML 'Call to Action' section. Static — no assessment data."""
    items = "\n".join(
        f'<li><a href="{url}">{label}</a> {blurb}</li>'
        for label, url, blurb in _CTA_LINKS
    )
    return f"""<section>
<h2>Call to Action</h2>
<p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">
To get started on your Graviton journey, leverage these resources:
</p>
<ul style="font-size:13px;line-height:1.7;padding-left:20px">
{items}
<li>Your AWS account team, AWS Professional Services, and Specialists support.</li>
</ul>
<p class="callout" style="margin-top:var(--space-16)">
Unlock the power of Graviton and take your EC2 workloads to new heights of efficiency.
Connect with your AWS account team today to get started.
</p>
</section>
"""


def _build_additional_resources_html() -> str:
    """Build the HTML 'Additional Resources' section. Static — no assessment data."""
    items = "\n".join(
        f'<li><a href="{url}">{label}</a> — {blurb}</li>'
        for label, url, blurb in _RESOURCE_LINKS
    )
    return f"""<section>
<h2>Additional Resources</h2>
<ul style="font-size:13px;line-height:1.7;padding-left:20px">
{items}
</ul>
</section>
"""


def _build_call_to_action_md() -> str:
    """Build the Markdown 'Call to Action' section."""
    lines = ["## Call to Action\n\n",
             "To get started on your Graviton journey, leverage these resources:\n\n"]
    for label, url, blurb in _CTA_LINKS:
        lines.append(f"- [{label}]({url}) {blurb}\n")
    lines.append("- Your AWS account team, AWS Professional Services, and "
                 "Specialists support.\n\n")
    lines.append("Unlock the power of Graviton and take your EC2 workloads to new "
                 "heights of efficiency. Connect with your AWS account team today "
                 "to get started.\n\n")
    return "".join(lines)


def _build_additional_resources_md() -> str:
    """Build the Markdown 'Additional Resources' section."""
    lines = ["## Additional Resources\n\n"]
    for label, url, blurb in _RESOURCE_LINKS:
        lines.append(f"- [{label}]({url}) - {blurb}\n")
    lines.append("\n")
    return "".join(lines)


def _build_data_quality_html(assessment: dict) -> str:
    """Build HTML 'Data Quality Notes' section showing methodology and limitations."""
    summary = assessment.get("summary", {})
    data_quality = summary.get("data_quality", {}) or {}
    classified = assessment.get("classified_detail", [])
    kpis = (assessment.get("score", {}) or {}).get("kpis", {}) or {}
    realized = assessment.get("realized_savings", {}) or {}

    total_cost = summary.get("total_cost", 0)
    period = _period_info(summary)

    priced_count = sum(1 for c in classified if c.get("od_rate_current"))

    rows = [
        f"<tr><td>Analysis period</td><td>{_esc(_period_text(period))}</td></tr>",
        f"<tr><td>Spend basis</td><td>{_esc(_spend_basis(summary))}. Savings "
        f"are therefore before the customer's own negotiated discounts.</td></tr>",
        "<tr><td>Scope</td><td>Cost Explorer returns every account the credentials "
        "can see. Run with management (payer) account credentials, the figures cover "
        "the whole organization, not only the account named in the header.</td></tr>",
    ]

    complete, failed = _completeness(summary)
    if complete is False:
        rows.append(
            f"<tr><td>Cost Explorer data</td><td><strong>Incomplete.</strong> "
            f"{len(failed)} pull(s) failed: {_esc(', '.join(failed))}. Spend and savings "
            f"are understated until a re-run succeeds.</td></tr>")

    pricing_errors = summary.get("pricing_errors") or {}
    if isinstance(pricing_errors, dict):
        err_count = pricing_errors.get("per_type_error_count", 0) or 0
    else:
        err_count = len(pricing_errors)
    if err_count:
        rows.append(
            f"<tr><td>Pricing lookups</td><td>{err_count} failed (throttling or "
            f"connection). Instance types whose price could not be retrieved are "
            f"excluded from the savings figures; see the incomplete-pricing notice "
            f"above.</td></tr>")

    unpriced = kpis.get("unpriced_count")
    if unpriced is not None:
        detail = (f"{priced_count} instance types priced from AWS Pricing API rates. "
                  f"{unpriced} upgradeable type(s) ({_fmt_cost(kpis.get('unpriced_cost') or 0)}/mo) "
                  f"could not be priced and are <strong>excluded</strong> from every savings "
                  f"figure")
        if unpriced:
            detail += (f"; an indicative 20% estimate for them would be "
                       f"{_fmt_cost(kpis.get('unpriced_indicative_savings') or 0)}/mo, "
                       f"<strong>not included</strong>")
        rows.append(f"<tr><td>Savings source</td><td>{detail}.</td></tr>")
        no_eq = kpis.get("no_equivalent_count") or 0
        if no_eq:
            rows.append(
                f"<tr><td>No equivalent in region</td><td>{no_eq} instance type(s) "
                f"({_fmt_cost(kpis.get('no_equivalent_cost') or 0)}/mo) have a Graviton "
                f"family that is not offered in their region; they carry no savings.</td></tr>")
    else:
        rows.append(
            f"<tr><td>Savings source</td><td>{priced_count} instance types priced from "
            f"AWS Pricing API rates; the rest carry no savings.</td></tr>")

    realized_note = ("Current Graviton spend compared with its Intel equivalent at the "
                     "same purchase terms (RI/SP/OD), using catalog rates for both sides.")
    if realized.get("unpriced_count"):
        realized_note += (f" {realized['unpriced_count']} Graviton type(s) had no rate for "
                          f"one side and are listed as unpriced, outside the total.")
    rows.append(f"<tr><td>Realized savings</td><td>{realized_note}</td></tr>")
    rows.append('<tr><td>Default (n+1) logic</td><td>Gen ≤5 → Graviton2, Gen 6 → Graviton3, Gen 7 → Graviton4, Gen 8+ → Graviton5 where a 9g type exists (c9g/c9gd, m9g/m9gd, r9g/r9gd), otherwise Graviton4. Families with no regular counterpart use a fixed mapping instead (for example r5b → r7g, m5zn → m7g, x2idn → x8g).</td></tr>')
    rows.append('<tr><td>Potential savings basis</td><td>Net figure: instances already priced below their Graviton target carry a negative per-item saving and are netted into every total (Service Summary, Full Fleet Detail, headline KPI and CSV all agree). Per-instance savings — including the negatives — appear in Full Fleet Detail, and already-optimized instances are listed under Already Cost-Optimized.</td></tr>')

    isp_check = data_quality.get("isp_check") or ""
    isp_locked = data_quality.get("isp_locked_cost") or 0
    if isp_check == "checked" and isp_locked > 0:
        rows.append(
            f"<tr><td>EC2 Instance Savings Plans</td><td>{_fmt_cost(isp_locked)}/mo of "
            f"Savings Plan spend is held by EC2 Instance Savings Plans, which apply only "
            f"to their instance family until they expire. That spend books no saving; "
            f"rows it fully covers are listed under Not Eligible.</td></tr>")
    sp_movable = sum(max((c.get("cost_sp") or 0) - (c.get("cost_sp_isp") or 0), 0)
                     for c in classified if _earns_savings(c))
    if sp_movable > 0:
        rows.append(
            f"<tr><td>Savings Plan spend</td><td>{_fmt_cost(sp_movable)}/mo of Savings Plan "
            f"spend keeps its saving on the assumption that the plan's hourly commitment "
            f"is absorbed by other eligible usage. The commitment is paid after the "
            f"migration too, so with no other usage to take it that saving arrives at "
            f"the plan's renewal.</td></tr>")
    isp_unmatched = data_quality.get("isp_unmatched_regions") or []
    if isp_check == "checked" and isp_unmatched:
        rows.append(
            f"<tr><td>EC2 Instance Savings Plans, unmatched</td><td>Plans in "
            f"{_esc(', '.join(isp_unmatched))} could not be matched to a region code, so "
            f"they were not applied to any row; savings on that Savings Plan spend may be "
            f"overstated.</td></tr>")
    elif isp_check.startswith("not_checked"):
        rows.append(
            f"<tr><td>EC2 Instance Savings Plans</td><td><strong>Not checked</strong> "
            f"({_esc(isp_check.split(':', 1)[-1].strip())}). Savings Plan spend is treated "
            f"as Compute Savings Plan spend, which moves to Graviton. Spend held by an EC2 "
            f"Instance Savings Plan would save nothing until the plan expires, so the "
            f"savings may be overstated.</td></tr>")

    ri_locked = data_quality.get("ri_locked_cost") or 0
    if ri_locked > 0:
        rows.append(
            f"<tr><td>Family-locked reservations</td><td>{_fmt_cost(ri_locked)}/mo of "
            f"Reserved Instance spend is held by reservations that cannot change instance "
            f"family: EC2 Standard Reserved Instances, and RDS, ElastiCache and OpenSearch "
            f"reservations. It books no saving until they end; rows they fully cover are "
            f"listed under Not Eligible. EC2 Convertible Reserved Instances can be "
            f"exchanged for Graviton, so their spend keeps its saving.</td></tr>")
    ri_unknown = data_quality.get("ri_class_unknown_cost") or 0
    if ri_unknown > 0:
        rows.append(
            f"<tr><td>Reservation class unknown</td><td>{_fmt_cost(ri_unknown)}/mo of EC2 "
            f"Reserved Instance spend has no offering class (standard or convertible) in "
            f"Cost Explorer. It is treated as able to move; if it is Standard, it would "
            f"save nothing until the reservation ends.</td></tr>")

    split_est = data_quality.get("split_estimated_cost") or 0
    if split_est > 0:
        rows.append(
            f"<tr><td>Estimated cost splits</td><td>{_fmt_cost(split_est)}/mo of spend "
            f"was apportioned by estimate rather than measured: Savings Plan and Spot "
            f"spend of a type that runs in several regions on several platforms "
            f"(Cost Explorer reports it by region and by platform, not by both; split "
            f"by iterative proportional fitting), and managed-service spend of an "
            f"engine or deployment group with no on-demand hours to price it by (split "
            f"by running hours, with a Multi-AZ hour counted as two, as RDS bills it). Totals per type and region are exact.</td></tr>")

    unclassified_types = data_quality.get("unclassified_types") or []
    if unclassified_types:
        u_cost = sum(u.get("cost", 0) or 0 for u in unclassified_types)
        names = ", ".join(_esc(u.get("instance_type", "")) for u in unclassified_types[:8])
        more = f" and {len(unclassified_types) - 8} more" if len(unclassified_types) > 8 else ""
        rows.append(
            f"<tr><td>Unrecognised instance types</td><td>{len(unclassified_types)} "
            f"type(s) ({_fmt_cost(u_cost)}/mo) are counted in total spend with no "
            f"Graviton path: {names}{more}.</td></tr>")
    else:
        unclassified = data_quality.get("unclassified", {}) or {}
        unclassified_total = sum(v for v in unclassified.values() if isinstance(v, (int, float)))
        if unclassified_total > 0:
            unclassified_pct = round(unclassified_total / max(total_cost, 1) * 100, 1)
            rows.append(f'<tr><td>Unclassified spend</td><td>{_fmt_cost(unclassified_total)} ({unclassified_pct}% of total) across OD/RI/SP/Spot</td></tr>')

    engine_checks = assessment.get("engine_readiness", [])
    if engine_checks:
        rows.append('<tr><td>Engine versions</td><td>Resolved from the RDS, ElastiCache and OpenSearch describe APIs where the credentials allow. Rows marked verify_version had no version available.</td></tr>')
    else:
        rows.append('<tr><td>Engine versions</td><td>No managed-service engines in this fleet, or none could be checked.</td></tr>')

    rows_html = "\n".join(rows)
    return f"""<section>
<h2>Data Quality Notes</h2>
<table>
<tr><th>Item</th><th>Detail</th></tr>
{rows_html}
</table>
</section>
"""


def _build_next_steps_md(assessment: dict) -> str:
    """Markdown 'Recommended Next Steps' section, from the list both reports share."""
    items = _next_steps(assessment)
    if not items:
        return ""
    lines = ["## Recommended Next Steps\n\n"]
    for i, (title, detail) in enumerate(items, 1):
        lines.append(f"{i}. **{title}** — {detail}\n")
    lines.append("\n")
    return "".join(lines)


# ASCII punctuation CommonMark gives a meaning to, minus "&" and "<", which
# _escape_markdown turns into entities. Backslash-escaping any of these is
# always valid and renders as the character itself.
_MD_META = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~])")


def _md_text(value) -> str:
    """Backslash-escape Markdown syntax in a free-text value (customer, account).

    Entity escaping stops HTML; this stops Markdown. Without it a --customer of
    "[Click here](https://evil.example)" rendered as a live link in the .md
    deliverable. Applied to free text only: instance types and regions are AWS
    identifiers, and escaping their dots and hyphens would only add noise.
    """
    if value is None:
        return ""
    return _MD_META.sub(r"\\\1", str(value))


def _escape_markdown(value):
    """Deep-copy assessment data with `<` and `&` neutralised in every string.

    The .md deliverable renders as live HTML in the viewers customers actually
    open it in (VS Code preview, GitHub, IDE plugins), so an assessment string
    containing `<img onerror=...>` executes there just as it would have in the
    HTML report before _escape_assessment. Only `<` and `&` are escaped — that
    is sufficient to prevent an HTML element from opening, it round-trips
    through markdown renderers as the original character, and it is a no-op for
    every value that real AWS identifiers can hold (same argument, and same
    boundary pattern, as _escape_assessment for the HTML report).
    """
    if isinstance(value, str):
        return value.replace("&", "&amp;").replace("<", "&lt;")
    if isinstance(value, dict):
        return {k: _escape_markdown(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_escape_markdown(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_escape_markdown(v) for v in value)
    return value


def _service_savings(classified: list, assessment: dict):
    """Per-service savings aggregated from classified instances and the
    realized-savings detail. Shared by generate_html and generate_markdown so
    both renderers show identical per-service figures.

    Returns (svc_savings, svc_realized, has_realized):
    - svc_savings[svc] = {"recommended", "g2", "g3", "g4", "g5"} — potential
      savings. These NET already-cost-optimized rows: an instance already priced
      below its Graviton target carries a negative per-item saving and is counted
      here, so the Service Summary matches the Full Fleet Detail, headline KPI and
      CSV, which all net. Those rows are still surfaced per-instance and under
      Already Cost-Optimized, so the netted figure stays backed by a breakdown.
    - svc_realized[svc] = summed realized savings from realized_savings_detail.
    - has_realized = whether any realized detail exists.
    """
    svc_savings = {}  # {service: {"recommended": 0, "g2": 0, "g3": 0, "g4": 0, "g5": 0}}
    for c in classified:
        svc = c.get("service", "ec2")
        svc_savings.setdefault(svc, {"recommended": 0, "g2": 0, "g3": 0, "g4": 0, "g5": 0})
        # Only rows the headline counts. Enrichment can price a row the scorer
        # then excludes (a "Windows with SQL Server" platform), and summing it
        # here put that saving in the Service Summary.
        if _earns_savings(c):
            svc_savings[svc]["recommended"] += c.get("est_savings", 0) or 0
            svc_savings[svc]["g2"] += c.get("est_savings_g2", 0) or 0
            svc_savings[svc]["g3"] += c.get("est_savings_g3", 0) or 0
            svc_savings[svc]["g4"] += c.get("est_savings_g4", 0) or 0
            svc_savings[svc]["g5"] += c.get("est_savings_g5", 0) or 0

    realized_detail = assessment.get("realized_savings_detail", [])
    svc_realized = {}  # {service: total_savings}
    for rd in realized_detail:
        svc = rd.get("service", "ec2")
        svc_realized[svc] = svc_realized.get(svc, 0) + (rd.get("savings") or 0)
    return svc_savings, svc_realized, bool(realized_detail)


def _service_purchase_costs(classified: list) -> dict:
    """{service: {"od", "ri", "sp", "spot"}} spend, shared by both reports.

    Spot has its own bucket: it was added into "sp", so the SP column showed
    Spot spend as Savings Plan spend.
    """
    out = {}
    for c in classified:
        b = out.setdefault(c.get("service", "ec2"), {"od": 0, "ri": 0, "sp": 0, "spot": 0})
        if any(c.get(f) is not None for f in ("cost_od", "cost_ri", "cost_sp", "cost_spot")):
            b["od"] += c.get("cost_od", 0) or 0
            b["ri"] += c.get("cost_ri", 0) or 0
            b["sp"] += c.get("cost_sp", 0) or 0
            b["spot"] += c.get("cost_spot", 0) or 0
            continue
        pt = (c.get("purchase_type") or "").lower()
        cost = c.get("cost", 0) or 0
        if pt == "spot":
            b["spot"] += cost
        elif "reserved" in pt or pt == "ri":
            b["ri"] += cost
        elif "savings" in pt or pt == "sp":
            b["sp"] += cost
        else:
            b["od"] += cost
    return out


def generate_markdown(assessment: dict, customer: str = "", account_id: str = "",
                      target_strategy: str = "latest") -> str:
    """Generate markdown report content from assessment result."""
    # Escaped once at the boundary, like generate_html — see _escape_markdown.
    # The free-text values additionally get Markdown syntax escaped (_md_text).
    assessment = _escape_markdown(assessment)
    customer = _escape_markdown(_md_text(customer))
    account_id = _escape_markdown(_md_text(account_id))
    summary = assessment.get("summary", {})
    score = assessment.get("score", {})
    plan = assessment.get("migration_plan", {})
    engine_checks = assessment.get("engine_readiness", [])
    classified = assessment.get("classified_detail", [])

    total_cost = summary.get("total_cost", 0)
    total_types = summary.get("total_types", 0)
    graviton_pct = summary.get("graviton_pct", 0)
    pricing_source = summary.get("pricing_source", "none")
    pricing_resolved = summary.get("pricing_types_resolved", 0)
    regions = summary.get("regions_priced", [])

    # Top opportunities from score
    opportunities = score.get("top_opportunities", [])
    service_breakdown = score.get("service_breakdown", {})

    # Migration waves — normalize list format to dict keyed by wave_N
    raw_waves = plan.get("waves", []) if isinstance(plan, dict) else []
    if isinstance(raw_waves, list):
        waves = {}
        for i, w in enumerate(raw_waves):
            if isinstance(w, dict):
                key = f"wave_{i + 1}"
                # Normalize keys: instance_count→count, total_cost→cost
                waves[key] = {
                    "name": w.get("wave", w.get("name", key)),
                    "count": w.get("instance_count", w.get("count", 0)),
                    "cost": w.get("total_cost", w.get("cost", 0)),
                    "est_savings": w.get("est_savings", 0),
                    "timeline": w.get("timeline", ""),
                    "effort": w.get("effort", ""),
                    "top_instances": w.get("top_instances", []),
                    # Carries each wave's caveat (e.g. that containers cannot be
                    # detected from billing data) through to both renderers.
                    "note": w.get("note", ""),
                }
    else:
        waves = raw_waves if isinstance(raw_waves, dict) else {}

    # Savings
    total_savings = (
        score.get("kpis", {}).get("est_total_savings", 0)
        or sum(o.get("est_monthly_savings", 0) for o in opportunities)
    )

    # Already on Graviton

    # Compute KPI subvalues for markdown parentheticals
    graviton_cost = summary.get("graviton_cost", 0)
    if not graviton_cost:
        graviton_cost = sum(c.get("cost", 0) for c in classified if c.get("is_graviton"))
    graviton_spend_pct = round(graviton_cost / total_cost * 100, 1) if total_cost > 0 else 0.0
    upgradeable_cost = _upgradeable_cost(classified, score.get("kpis", {}))
    savings_pct_of_spend = round(total_savings / total_cost * 100, 1) if total_cost > 0 else 0.0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    period = _period_info(summary)
    kpis = score.get("kpis", {}) or {}
    header = "# Graviton Migration Assessment\n\n"
    header += f"**Customer:** {_report_subject(customer, account_id, sep=' / ')}"
    header += f"\n**Generated:** {now}\n"
    header += f"> {datetime.now().strftime('%B %Y')} | {len(regions)} regions | Pricing: {pricing_source}\n\n"
    header += f"**{_period_text(period)}.**\n\n"
    header += f"**Spend basis:** {_spend_basis(summary)}.\n\n"
    header += f"**Pricing Source:** {pricing_source} — {pricing_resolved} types resolved"
    if regions:
        header += f" across {len(regions)} regions"
    header += "\n\n"
    complete, failed = _completeness(summary)
    if complete is False:
        header += (f"> **Incomplete Cost Explorer data — spend and savings are understated.** "
                   f"{len(failed)} pull(s) failed: {', '.join(failed)}. Re-run before "
                   f"relying on these figures.\n\n")
    header += "---\n\n"

    # Executive summary. Figures are monthly averages over the analysis period
    # (see _period_info); annual is the monthly figure annualised.
    per = "Monthly" if period["monthly"] else _months_text(period["months"]).title()
    lines = [header]
    lines.append("## Executive Summary\n\n")
    lines.append("| Metric | Value |\n|--------|-------|\n")
    lines.append(f"| {'Average Monthly' if period['averaged'] else 'Total ' + per} Spend | {_fmt_cost(total_cost)} |\n")
    lines.append(f"| Graviton Coverage | {graviton_pct:.1f}% by NIH ({graviton_spend_pct:.1f}% by spend) |\n")
    lines.append(f"| Upgradeable Spend | {_fmt_cost(upgradeable_cost)} ({round(upgradeable_cost / max(total_cost, 1) * 100, 1)}% of total) |\n")
    lines.append(f"| Estimated {'Average Monthly' if period['averaged'] else per} Savings (price-only) | {_fmt_cost(total_savings)} ({savings_pct_of_spend:.1f}% of total spend) |\n")
    lines.append(f"| Estimated Annual Savings | {_fmt_cost(total_savings * period['annual_factor'])} |\n")
    if kpis.get("unpriced_count"):
        lines.append(
            f"| Unpriced, excluded from savings | {kpis['unpriced_count']} types, "
            f"{_fmt_cost(kpis.get('unpriced_cost') or 0)} spend; an indicative 20% would be "
            f"{_fmt_cost(kpis.get('unpriced_indicative_savings') or 0)}/mo (not included) |\n")
    if kpis.get("no_equivalent_count"):
        lines.append(
            f"| No Graviton equivalent in region | {kpis['no_equivalent_count']} types, "
            f"{_fmt_cost(kpis.get('no_equivalent_cost') or 0)} spend, no savings |\n")
    lines.append("\n")

    # Purchase type breakdown (v3 only — shows OD/RI/SP/Spot split)
    pt_summary = summary.get("purchase_type_summary")
    if pt_summary:
        lines.append("### Cost by Purchase Type\n\n")
        lines.append("| Purchase Type | Monthly Cost |\n|--------------|-------------|\n")
        for pt_key, pt_label in [("od_cost", "On-Demand"), ("ri_cost", "Reserved Instances"),
                                  ("sp_cost", "Savings Plans"), ("spot_cost", "Spot")]:
            val = pt_summary.get(pt_key, 0)
            if val > 0:
                lines.append(f"| {pt_label} | {_fmt_cost(val)} |\n")
        ri_sav = pt_summary.get("ri_savings", 0)
        if ri_sav > 0:
            lines.append(f"| RI Net Savings | {_fmt_cost(ri_sav)} |\n")
        lines.append("\n")

    # Coverage summary (v3 only)
    cov_summary = summary.get("coverage_summary")
    if cov_summary and cov_summary.get("overall_coverage_pct", 0) > 0:
        lines.append(f"*RI/SP Coverage: {cov_summary['overall_coverage_pct']:.1f}% of running hours*\n\n")

    lines.append("---\n\n")

    # Service breakdown
    if service_breakdown:
        # Per-service savings, computed exactly as generate_html does (shared
        # helper). The Est. Savings column shows the recommended/default (n+1)
        # potential savings, net of already-cost-optimized rows.
        svc_savings, _svc_realized, _has_realized = _service_savings(classified, assessment)
        svc_purchase = _service_purchase_costs(classified)

        lines.append("## Service Summary\n\n")
        lines.append("| Service | Types | Monthly Cost | Graviton Types | Graviton % | OD Cost | RI Cost | SP Cost | Spot Cost | Est. Savings |\n")
        lines.append("|---------|-------|-------------|----------------|------------|---------|---------|---------|-----------|-------------|\n")
        for svc, data in service_breakdown.items():
            if isinstance(data, dict):
                grav_count = data.get(
                    'graviton', data.get('graviton_count', 0))
                grav_pct = data.get(
                    'graviton_pct',
                    round(grav_count / max(data.get('count', 1), 1) * 100, 1)
                )
                pt_data = svc_purchase.get(svc, {"od": 0, "ri": 0, "sp": 0, "spot": 0})
                od_cost = _fmt_cost(pt_data["od"]) if pt_data["od"] > 0 else "$0"
                ri_cost = _fmt_cost(pt_data["ri"]) if pt_data["ri"] > 0 else "$0"
                sp_cost = _fmt_cost(pt_data["sp"]) if pt_data["sp"] > 0 else "$0"
                spot_cost = _fmt_cost(pt_data["spot"]) if pt_data["spot"] > 0 else "$0"
                # Net potential savings; a value rounding to zero shows a dash,
                # a negative (already-optimized) value renders with its sign.
                svc_rec = svc_savings.get(svc, {}).get("recommended", 0)
                savings_str = _fmt_cost(svc_rec) if round(svc_rec, 2) != 0 else "—"
                lines.append(
                    f"| {svc} | {data.get('count', 0)} "
                    f"| {_fmt_cost(data.get('cost', 0))} "
                    f"| {grav_count} | {grav_pct:.1f}% "
                    f"| {od_cost} | {ri_cost} | {sp_cost} | {spot_cost} "
                    f"| {savings_str} |\n"
                )
        # Total row
        total_types = sum(d.get('count', 0) for d in service_breakdown.values() if isinstance(d, dict))
        total_svc_cost = sum(d.get('cost', 0) for d in service_breakdown.values() if isinstance(d, dict))
        total_grav = sum(d.get('graviton', d.get('graviton_count', 0)) for d in service_breakdown.values() if isinstance(d, dict))
        total_grav_pct = round(total_grav / max(total_types, 1) * 100, 1)
        total_od = sum(v["od"] for v in svc_purchase.values())
        total_ri = sum(v["ri"] for v in svc_purchase.values())
        total_sp = sum(v["sp"] for v in svc_purchase.values())
        total_spot = sum(v["spot"] for v in svc_purchase.values())
        total_rec = sum(s.get("recommended", 0) for s in svc_savings.values())
        total_rec_str = _fmt_cost(total_rec) if round(total_rec, 2) != 0 else "—"
        lines.append(
            f"| **TOTAL** | **{total_types}** "
            f"| **{_fmt_cost(total_svc_cost)}** "
            f"| **{total_grav}** | **{total_grav_pct:.1f}%** "
            f"| **{_fmt_cost(total_od)}** | **{_fmt_cost(total_ri)}** | **{_fmt_cost(total_sp)}** "
            f"| **{_fmt_cost(total_spot)}** "
            f"| **{total_rec_str}** |\n"
        )
        lines.append("\n---\n\n")

    # Top opportunities
    if opportunities:
        strategy_note = _strategy_label(target_strategy)
        lines.append("## Top 15 Migration Opportunities\n\n")
        lines.append(f"*Target generation: {strategy_note}*\n\n")
        lines.append("| Current | Service | Target | Region | Monthly Cost | Savings % | Monthly Savings | Source |\n")
        lines.append("|---------|---------|--------|--------|-------------|-----------|----------------|--------|\n")
        has_size_mismatch = False
        for o in opportunities[:15]:
            current = _expand_size(
                o.get('current', '') or o.get('instance_type', ''))
            region = o.get('region', '')
            # Multi-target rendering
            options = o.get("graviton_options", [])
            if len(options) > 1:
                parts = []
                recommended_type = _expand_size(o.get("graviton_target", ""))
                for opt in options:
                    gen_short = opt["generation"].replace("Graviton", "G")
                    inst = _expand_size(opt["instance_type"])
                    is_rec = (inst == recommended_type)
                    part = f"{gen_short}: {inst}"
                    if is_rec:
                        part += " (rec)"
                    if _has_size_mismatch(current, inst):
                        part += f" {WARN_GLYPH}"
                        has_size_mismatch = True
                    parts.append(part)
                # NOT " | ": this string goes into a single markdown table cell,
                # and a pipe inside a cell starts a new one, which would push every
                # later column out from under its heading.
                target_str = " / ".join(parts)
            elif len(options) == 1:
                target_str = _expand_size(options[0]["instance_type"])
                if _has_size_mismatch(current, target_str):
                    target_str += f" {WARN_GLYPH}"
                    has_size_mismatch = True
            else:
                target_str = _expand_size(
                    o.get('target', '') or o.get('graviton_target', ''))
                if _has_size_mismatch(current, target_str):
                    target_str += f" {WARN_GLYPH}"
                    has_size_mismatch = True
            # A row without a percentage has no priced target: say which kind.
            _pct = o.get('est_savings_pct')
            _src = o.get('pricing_source', '')
            if isinstance(_pct, (int, float)):
                _pct_str = f"{_pct:.1f}%"
            elif _src == "estimate_20pct":
                _pct_str = "unpriced"
            elif _src == "no_equivalent":
                _pct_str = "no equivalent"
            else:
                _pct_str = "review"
            lines.append(
                f"| {current} | {service_label(o.get('service', ''))} "
                f"| {target_str} | {region} "
                f"| {_fmt_cost(o.get('cost', 0))} "
                f"| {_pct_str} "
                f"| {_fmt_cost(o.get('est_monthly_savings', 0))} "
                f"| {o.get('pricing_source', 'estimate')} |\n"
            )
        if has_size_mismatch:
            lines.append(f"\n> {WARN_GLYPH} **Size mismatch**: some targets have different vCPU/size. "
                         "Savings are still counted; validate workload compatibility.\n")
        if any(o.get("pricing_source") in ("estimate_20pct", "no_equivalent")
               for o in opportunities[:15]):
            lines.append("\n> **unpriced** rows have a Graviton target but no price, and "
                         "**no equivalent** rows have no Graviton family offered in their "
                         "region. Both contribute $0 to every total.\n")
        if any(o.get("pricing_source") == "od_ratio_proxy" for o in opportunities[:15]):
            lines.append("\n> **od_ratio_proxy**: Spot rows are estimated with the on-demand "
                         "price ratio applied to their spot cost — spot market rates are not "
                         "pulled, so this assumes the spot discount is equally deep on the "
                         "current and Graviton sides.\n")
        lines.append("\n---\n\n")

    # Already Cost-Optimized
    already_optimized = score.get("already_optimized", [])
    if already_optimized:
        lines.append("## Already Cost-Optimized\n\n")
        lines.append(
            "These instances are already priced lower than their "
            "Graviton equivalents — no migration needed for "
            "cost savings.\n\n"
        )
        lines.append("| Instance Type | Current OD Rate | Graviton Target | Savings % | Reason |\n")
        lines.append("|--------------|----------------|-----------------|-----------|--------|\n")
        for entry in already_optimized:
            inst_type = _expand_size(entry.get('instance_type', '') or entry.get('current', ''))
            od_current = entry.get('od_current', 0)
            graviton_target = _expand_size(entry.get('graviton_target', '') or entry.get('target', ''))
            savings_pct = entry.get('est_savings_pct', 0)
            reason = entry.get('reason', '')
            lines.append(
                f"| {inst_type} | ${od_current:.4f}/hr "
                f"| {graviton_target} | {savings_pct:.1f}% "
                f"| {reason} |\n"
            )
        lines.append("\n---\n\n")

    # Migration plan
    lines.append("## Migration Plan\n\n")
    for wave_key in sorted(waves.keys()):
        wave = waves[wave_key]
        if wave and wave.get("count", 0) > 0:
            lines.append(f"### {wave.get('name', wave_key)}\n")
            lines.append(f"- **Timeline:** {wave.get('timeline', 'TBD')}\n")
            lines.append(f"- **Effort:** {wave.get('effort', 'TBD')}\n")
            lines.append(f"- **Types:** {wave.get('count', 0)}\n")
            lines.append(f"- **Monthly Cost:** {_fmt_cost(wave.get('cost', 0))}\n")
            lines.append(f"- **Estimated Savings:** {_fmt_cost(wave.get('est_savings', 0))}/mo\n")
            if wave.get("note"):
                lines.append(f"- *{wave['note']}*\n")
            lines.append("\n")
            # Instance-level action items
            top = wave.get("top_instances", [])
            if top:
                lines.append("| Current | Target | Service | Monthly Cost | Region |\n")
                lines.append("|---------|--------|---------|-------------|--------|\n")
                for inst in top:
                    if isinstance(inst, dict):
                        current = _expand_size(inst.get("raw", ""))
                        target = _expand_size(
                            inst.get("graviton_target", "")
                            or inst.get("graviton_upgrade", "")
                        ) or "—"
                        svc = inst.get("service", "ec2")
                        cost = inst.get("cost", 0)
                        rgn = inst.get("region", "")
                        lines.append(f"| {current} | {target or '—'} | {svc} | {_fmt_cost(cost)} | {rgn} |\n")
                lines.append("\n")
        elif wave and "Container" in wave.get("name", ""):
            # Empty by construction, not by measurement — say which. Container
            # nodes need a multi-arch image rebuild, more work than the AMI swap
            # Wave 3 costs them at, so the plan must not imply they are easier.
            lines.append(f"### {wave.get('name', wave_key)}\n")
            lines.append(
                "- **Not detected — this is a data limitation, not a finding "
                "that the fleet has no containers.**\n"
            )
            lines.append(
                f"- *{wave.get('note')}*\n\n" if wave.get("note") else
                "- *EKS/ECS nodes bill as ordinary EC2 instance hours and cannot "
                "be separated without resource tags; Fargate is outside this "
                "assessment's instance-hours scope. Any container nodes are "
                "counted in Wave 3, where the effort estimate assumes an AMI "
                "swap rather than a multi-arch rebuild.*\n\n"
            )
    lines.append("---\n\n")

    # Engine readiness — sorted by status priority (Blocked first, then Needs Upgrade, then Ready)
    if engine_checks:
        sorted_checks = _sort_engines_for_md(engine_checks)
        lines.append("## Engine Readiness\n\n")
        lines.append("| Instance | Engine | Version | Graviton Min | Status |\n")
        lines.append("|----------|--------|---------|--------------|--------|\n")
        for check in sorted_checks:
            status = check.get("status", "unknown")
            status_icon = "Ready" if status == "ready" else "Upgrade required" if "upgrade" in status else "Blocked" if "blocked" in status.lower() else status
            lines.append(
                f"| {check.get('instance_class', '')} "
                f"| {check.get('engine', '')} "
                f"| {check.get('current_version', '')} "
                f"| {check.get('graviton_min_version', '')} "
                f"| {status_icon} |\n"
            )
        lines.append("\n---\n\n")

    # Recommended next steps
    next_steps_md = _build_next_steps_md(assessment)
    if next_steps_md:
        lines.append(next_steps_md)
        lines.append("---\n\n")
    # Static, so appended unconditionally — unlike next steps, these sections
    # have nothing to be empty about.
    lines.append(_build_call_to_action_md())
    lines.append(_build_additional_resources_md())
    lines.append("---\n\n")

    lines.append(f"*Generated by Graviton Savings Assessment | Pricing: {pricing_source} | Source: {_source_hash()}*\n")
    return "".join(lines)


# Scorer sources that carry a real, priced saving (see fleet_tools._book).
_BOOKED_PRICED = frozenset({"enriched", "pricing_api", "capacity_adjusted",
                            "od_ratio_proxy"})


def generate_html(assessment: dict, customer: str = "", account_id: str = "",
                  target_strategy: str = "latest",
                  perf_per_gen: float = PERF_DEFAULT_PCT) -> str:
    """Generate self-contained HTML report from assessment result.

    perf_per_gen: default estimated NIH (normalized instance-hours) reduction (%)
    the slider opens at. Applied flat to the projected Graviton cost (not
    compounded per generation), matching the Graviton Savings Dashboard.
    0 reproduces the price-only view.
    """
    # Escape ONCE, here, so every one of the hundred-plus interpolations below is
    # safe by construction. Escaping at individual sinks leaves the next sink
    # added unprotected and gives a reviewer no way to confirm the set is
    # complete. Numbers pass through untouched; the caller's dict is not mutated,
    # so generate_markdown and the CSV writer still receive raw values.
    assessment = _escape_assessment(assessment)

    summary = assessment.get("summary", {})
    score = assessment.get("score", {})
    plan = assessment.get("migration_plan", {})
    engine_checks = assessment.get("engine_readiness", [])
    classified = assessment.get("classified_detail", [])

    total_cost = summary.get("total_cost", 0)
    graviton_pct = summary.get("graviton_pct", 0)
    pricing_source = summary.get("pricing_source", "none")
    pricing_resolved = summary.get("pricing_types_resolved", 0)
    regions = summary.get("regions_priced", [])

    opportunities = score.get("top_opportunities", [])
    service_breakdown = score.get("service_breakdown", {})

    # Normalize waves list to dict keyed by wave_N
    raw_waves = plan.get("waves", []) if isinstance(plan, dict) else []
    if isinstance(raw_waves, list):
        waves = {}
        for i, w in enumerate(raw_waves):
            if isinstance(w, dict):
                key = f"wave_{i + 1}"
                waves[key] = {
                    "name": w.get("wave", w.get("name", key)),
                    "count": w.get("instance_count", w.get("count", 0)),
                    "cost": w.get("total_cost", w.get("cost", 0)),
                    "est_savings": w.get("est_savings", 0),
                    "timeline": w.get("timeline", ""),
                    "effort": w.get("effort", ""),
                    "top_instances": w.get("top_instances", []),
                    # Carries each wave's caveat (e.g. that containers cannot be
                    # detected from billing data) through to both renderers.
                    "note": w.get("note", ""),
                }
    else:
        waves = raw_waves if isinstance(raw_waves, dict) else {}

    total_savings = (
        score.get("kpis", {}).get("est_total_savings", 0)
        or sum(o.get("est_monthly_savings", 0) for o in opportunities)
    )


    # Compute KPI subvalues
    graviton_cost = summary.get("graviton_cost", 0)
    if not graviton_cost:
        graviton_cost = sum(c.get("cost", 0) for c in classified if c.get("is_graviton"))
    graviton_spend_pct = round(graviton_cost / total_cost * 100, 1) if total_cost > 0 else 0.0
    upgradeable_cost = _upgradeable_cost(classified, score.get("kpis", {}))
    savings_pct_of_spend = round(total_savings / total_cost * 100, 1) if total_cost > 0 else 0.0

    # Realized savings KPI
    realized_summary = assessment.get("realized_savings", {})
    realized_total = realized_summary.get("total_realized_savings", 0) if isinstance(realized_summary, dict) else 0

    period = _period_info(summary)
    kpis = score.get("kpis", {}) or {}
    # The generation radio the report opens on, so the opening headline is the
    # generation --graviton-generation chose (and the one stdout/Markdown report).
    open_gen = _STRATEGY_RADIO.get(target_strategy, "nextgen")
    if period["averaged"]:
        spend_label, savings_label = "Avg Monthly Spend", "Avg Monthly Savings Opportunity"
    elif period["monthly"]:
        spend_label, savings_label = "Total Monthly Spend", "Monthly Savings Opportunity"
    else:
        _len = _months_text(period["months"])
        spend_label, savings_label = f"Spend ({_len})", f"Savings Opportunity ({_len})"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # One subject string drives both the <title> and the masthead, so they
    # cannot name the report differently. Escaped once here, since both sinks
    # are HTML.
    _subject = _report_subject(customer, account_id)
    _title_suffix = "" if _subject == "N/A" else f" - {_esc(_subject)}"

    # Build opportunity rows
    # Header from GENERATIONS, so it and the row builder below cannot disagree
    # about how many generation columns there are.
    # Service is a column because this table mixes services: a bare
    # "r6g.xlarge" and a "db.r6g.xlarge" read as the same kind of thing, and
    # ElastiCache/OpenSearch rows are indistinguishable from EC2 by name alone.
    # The reader needs to know which team owns the migration.
    opp_table = Table(
        ["Current Instance", "Service", "Region", "Monthly Cost"]
        + [part for g in GENERATIONS
           for part in (f"{g.label} Target", f"{g.short} Savings")]
        + ["Source"],
        css_class="sortable", name="Top Migration Opportunities",
    )
    has_size_mismatch_html = False
    for o in opportunities[:12]:
        current = _expand_size(o.get("current", "") or o.get("instance_type", ""))
        region = o.get("region", "")
        cost = o.get("cost", 0)
        options = o.get("graviton_options", [])
        source = o.get("pricing_source", "estimate")

        # Enriched per-generation savings, keyed by generation label. These were
        # four sibling reads feeding a four-branch if/elif chain, which is how a
        # generation could be added to one and not the other.
        enriched = {g.label: o.get(g.savings_field) for g in GENERATIONS}

        # Build per-gen columns (target + savings)
        gen_data = {g.label: {} for g in GENERATIONS}
        for opt in options:
            gen = opt.get("generation", "")
            if gen in gen_data:
                inst = _expand_size(opt.get("instance_type", ""))
                est = enriched.get(gen)
                # Prefer the purchase-type-aware figure from enrichment.
                if est is not None:
                    savings_amt = round(est, 0)
                    savings_pct = round(est / cost * 100, 1) if cost > 0 else 0
                else:
                    # Fallback: OD ratio from graviton_options.
                    #
                    # savings_pct is None on options that could not be priced at
                    # all — an unpriced capacity-adjusted downsize, or a target
                    # flagged not_available / not_offered_in_region. `.get(k, 0)`
                    # does NOT cover this: the key exists holding None, so the
                    # default never applies. Leave both as None and let the cell
                    # render "review" rather than fabricating a $0 saving.
                    savings_pct = opt.get("savings_pct")
                    savings_amt = (
                        round(cost * savings_pct / 100, 0)
                        if savings_pct is not None else None
                    )

                # A glyph rather than a parenthetical: these markers sit inside
                # narrow table cells where " (capacity-adjusted)" wrapped and
                # doubled the row height. The title attribute carries the
                # distinction between the two cases that the shared glyph loses.
                size_warn = ""
                if opt.get("pricing_source") == "capacity_adjusted":
                    size_warn = _warn_glyph("size mismatch: nearest available size differs in vCPU/memory")
                    has_size_mismatch_html = True
                elif _has_size_mismatch(current, inst):
                    size_warn = _warn_glyph("size mismatch: target size differs from current")
                    has_size_mismatch_html = True
                gen_data[gen] = {"target": inst, "savings": savings_amt, "pct": savings_pct, "warn": size_warn}

        # Returns the (target, savings) PAIR for one generation, so the row
        # builder cannot emit a target without its savings or vice versa.
        def _gen_cells(gen_key):
            d = gen_data.get(gen_key, {})
            if not d:
                return ["—", "—"]
            # warn is markup (the glyph); target text is escaped here.
            target_cell = Raw(_esc(d["target"]) + d["warn"])
            # No figure for this generation's target (e.g. an unpriced downsize).
            if d["savings"] is None or d["pct"] is None:
                savings_cell = "review"
            elif d["savings"] >= 0:
                savings_cell = f'${d["savings"]:,.0f} ({d["pct"]:.1f}%)'
            else:
                savings_cell = f'$-{abs(d["savings"]):,.0f} ({d["pct"]:.1f}%)'
            return [target_cell, savings_cell]

        cells = [Raw(f"<strong>{_esc(current)}</strong>"),
                 service_label(o.get("service", "")), region, _fmt_cost(cost)]
        for g in GENERATIONS:
            cells.extend(_gen_cells(g.label))
        cells.append(source)
        opp_table.row(*cells)

    opp_size_mismatch_callout = (
        f'<p class="callout">{WARN_GLYPH} <strong>Size mismatch</strong> — a marked target '
        'differs in vCPU/memory from the current instance. Its savings <em>are</em> included in the '
        'figures above; validate workload compatibility before committing to it.</p>'
        if has_size_mismatch_html else ""
    )
    opp_od_proxy_callout = (
        '<p class="callout"><strong>od_ratio_proxy</strong> — Spot rows are estimated with the '
        'on-demand price ratio applied to their spot cost. Spot market rates are not pulled, so '
        'this assumes the spot discount is equally deep on the current and Graviton sides.</p>'
        if any(o.get("pricing_source") == "od_ratio_proxy" for o in opportunities[:12]) else ""
    )

    # Build already-optimized rows
    already_optimized = score.get("already_optimized", [])
    already_opt_rows = ""
    for entry in already_optimized:
        inst_type = _expand_size(entry.get("instance_type", "") or entry.get("current", ""))
        # `or 0` rather than a .get() default: these keys exist holding None on
        # rows an upstream stage could not price, so the default never fires and
        # the format spec below would raise on None.
        od_current = entry.get("od_current") or 0
        graviton_target = _expand_size(entry.get("graviton_target", "") or entry.get("target", ""))
        savings_pct = entry.get("est_savings_pct") or 0
        reason = entry.get("reason", "")
        already_opt_rows += f'<tr><td>{inst_type}</td><td>${od_current:.4f}/hr</td>'
        already_opt_rows += f'<td>{graviton_target}</td><td>{savings_pct:.1f}%</td>'
        already_opt_rows += f'<td>{reason}</td></tr>\n'

    already_opt_section = ""
    if already_opt_rows:
        already_opt_section = '<section>\n<h2>Already Cost-Optimized</h2>\n'
        already_opt_section += (
            '<p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">'
            'These instances are already priced lower than their '
            'Graviton equivalents — no migration needed for cost '
            'savings.</p>\n'
        )
        already_opt_section += (
            '<table>\n<tr><th>Instance Type</th>'
            '<th>Current OD Rate</th><th>Graviton Target</th>'
            '<th>Savings %</th><th>Reason</th></tr>\n'
        )
        already_opt_section += already_opt_rows
        already_opt_section += '</table>\n</section>'

    svc_purchase = _service_purchase_costs(classified)

    # Per-service savings (potential, net of already-optimized; and realized).
    # Shared with generate_markdown so both renderers show identical figures.
    svc_savings, svc_realized, has_realized = _service_savings(classified, assessment)

    # Aggregate current Graviton adoption per service by generation
    svc_graviton = {}  # {service: {"g2": cost, "g3": cost, "g4": cost, "g5": cost, "total": cost, "pct": float}}
    for c in classified:
        if not c.get("is_graviton"):
            continue
        svc = c.get("service", "ec2")
        # "other" exists so every Graviton dollar lands in exactly one bucket:
        # the per-service percentage divides by "total" while the TOTAL row sums
        # the generation buckets, so spend whose gen_bucket matches no branch
        # (e.g. "Graviton" with no digit) would make the two disagree.
        svc_graviton.setdefault(
            svc, {"g2": 0, "g3": 0, "g4": 0, "g5": 0, "other": 0, "total": 0})
        cost = c.get("cost", 0)
        gen_bucket = c.get("gen_bucket", "")
        svc_graviton[svc]["total"] += cost
        if "2" in gen_bucket:
            svc_graviton[svc]["g2"] += cost
        elif "3" in gen_bucket:
            svc_graviton[svc]["g3"] += cost
        elif "4" in gen_bucket:
            svc_graviton[svc]["g4"] += cost
        elif "5" in gen_bucket:
            svc_graviton[svc]["g5"] += cost
        else:
            svc_graviton[svc]["other"] += cost

    # Build service rows
    # Two-tier header, both tiers from GENERATIONS. The adoption and potential
    # groups each spanned a hardcoded colspan="5" (four generations plus one
    # extra column), so adding a generation needed four coordinated edits here
    # and in both row builders. Now the span is computed.
    _adoption_span = len(GENERATIONS) + 1      # generations + "Graviton %"
    _potential_span = len(GENERATIONS) + 1     # generations + the selected target
    # With --graviton-generation the selected figure is that generation's, so
    # it must not be headed "Default (n+1)".
    _sel_col = ("Default (n+1)" if target_strategy == "latest"
                else f"Selected ({_STRATEGY_LABELS.get(target_strategy, target_strategy).split(' (')[0]})")
    _GREEN = "text-align:center;background:var(--green-700);color:var(--white)"
    _BLUE = "text-align:center;background:var(--blue-700);color:var(--white)"
    svc_table = Table(
        [("Service", 1, 2), ("Purchase Options", 1, 2), ("Monthly Cost", 1, 2),
         ("Current Graviton Adoption", _adoption_span, 1, _GREEN),
         ("Realized Savings", 1, 2),
         ("Potential Graviton Savings", _potential_span, 1, _BLUE)],
        [g.short for g in GENERATIONS] + ["Graviton %", _sel_col]
        + [f"If All→{g.short}" for g in GENERATIONS],
        css_class="sortable", name="Service Summary",
    )
    for svc, data in service_breakdown.items():
        if isinstance(data, dict):
            pt_data = svc_purchase.get(svc, {"od": 0, "ri": 0, "sp": 0, "spot": 0})
            savings_data = svc_savings.get(svc, {"recommended": 0, **gen_zeroes()})
            od_cost = _fmt_cost(pt_data["od"]) if pt_data["od"] > 0 else "$0"
            ri_cost = _fmt_cost(pt_data["ri"]) if pt_data["ri"] > 0 else "$0"
            sp_cost = _fmt_cost(pt_data["sp"]) if pt_data["sp"] > 0 else "$0"
            spot_cost = _fmt_cost(pt_data["spot"]) if pt_data["spot"] > 0 else "$0"
            # Realized savings. Shown signed: a service that realized a net loss
            # (its per-service total is negative) must render that value, not a
            # "—", so the column sums to the netted TOTAL and the realized KPI.
            realized = svc_realized.get(svc, 0)
            realized_str = _fmt_cost(realized) if has_realized and round(realized, 2) != 0 else "—"
            # Per-gen potential savings
            rec_str = _fmt_cost(savings_data["recommended"]) if round(savings_data["recommended"], 2) != 0 else "—"
            # Current Graviton adoption
            grav_data = svc_graviton.get(
                svc, {**gen_zeroes(), "other": 0, "total": 0})
            svc_cost = data.get("cost", 0)
            grav_pct = round(grav_data["total"] / max(svc_cost, 1) * 100) if svc_cost > 0 else 0

            # Adoption cells are spend (never negative) — a zero reads better as
            # "—". Savings cells net already-optimized rows and so can be
            # negative; those must render, or the column would not sum to its
            # TOTAL. Only a value that rounds to zero shows a dash.
            def _money(value):
                return _fmt_cost(value) if value and value > 0 else "—"

            def _savings(value):
                return _fmt_cost(value) if value and round(value, 2) != 0 else "—"

            svc_table.row(
                Raw(f"<strong>{_esc(svc.upper())}</strong>"),
                (Raw(f"OD: {_esc(od_cost)}<br>RI: {_esc(ri_cost)}<br>"
                     f"SP: {_esc(sp_cost)}<br>Spot: {_esc(spot_cost)}"), 1, 1,
                 "font-size:11px"),
                _fmt_cost(svc_cost),
                *[_money(grav_data.get(g.key)) for g in GENERATIONS],
                f"{grav_pct}%",
                realized_str,
                rec_str,
                *[_savings(savings_data.get(g.key)) for g in GENERATIONS],
            )

    # Total row for service breakdown
    total_svc_cost = sum(d.get("cost", 0) for d in service_breakdown.values() if isinstance(d, dict))
    total_realized = sum(svc_realized.values()) if has_realized else 0
    total_rec = sum(s["recommended"] for s in svc_savings.values())
    total_savings_by_gen = {g.key: sum(s.get(g.key, 0) for s in svc_savings.values())
                            for g in GENERATIONS}
    total_adoption_by_gen = {g.key: sum(a.get(g.key, 0) for a in svc_graviton.values())
                             for g in GENERATIONS}
    # Sum "total", not the generation buckets: identical now that every dollar is
    # bucketed, and it stays correct if an unrecognised gen_bucket appears again.
    total_grav = sum(g.get("total", 0) for g in svc_graviton.values())
    total_grav_pct = round(total_grav / max(total_svc_cost, 1) * 100) if total_svc_cost > 0 else 0
    def _total_money(value):
        return _fmt_cost(value) if value and value > 0 else "—"

    def _total_savings(value):
        return _fmt_cost(value) if value and round(value, 2) != 0 else "—"

    svc_table.total(
        "TOTAL", "", _fmt_cost(total_svc_cost),
        *[_total_money(total_adoption_by_gen[g.key]) for g in GENERATIONS],
        f"{total_grav_pct}%",
        _total_savings(total_realized),
        _total_savings(total_rec),
        *[_total_savings(total_savings_by_gen[g.key]) for g in GENERATIONS],
        style="font-weight:bold;border-top:2px solid var(--gray-700)",
    )

    # Build engine readiness section (grouped by status)
    engine_section = _build_engine_grouped_html(engine_checks)

    # Build processor distribution bar (NIH-based compute coverage)
    # NIH = hours × normalization factor (accounts for instance size differences)
    from collections import defaultdict
    svc_proc_nih = defaultdict(lambda: {"intel": 0, "graviton": 0, "amd": 0})
    for c in classified:
        svc = c.get("service", "ec2").upper()
        hrs = c.get("hours", 0)
        nih_factor = c.get("nih_factor", 4)  # Default to 'large' if unknown
        nih = hrs * nih_factor
        if c.get("is_graviton"):
            svc_proc_nih[svc]["graviton"] += nih
        elif c.get("is_amd"):
            svc_proc_nih[svc]["amd"] += nih
        else:
            svc_proc_nih[svc]["intel"] += nih

    intel_nih = sum(p["intel"] for p in svc_proc_nih.values())
    grav_nih = sum(p["graviton"] for p in svc_proc_nih.values())
    amd_nih = sum(p["amd"] for p in svc_proc_nih.values())
    total_nih = intel_nih + grav_nih + amd_nih

    if total_nih > 0:
        intel_pct = round(intel_nih / total_nih * 100, 1)
        grav_pct_bar = round(grav_nih / total_nih * 100, 1)
        amd_pct = round(amd_nih / total_nih * 100, 1)
    else:
        intel_pct = grav_pct_bar = amd_pct = 0

    processor_bar_html = ""
    if total_nih > 0:
        # Per-service NIH table
        svc_proc_rows = ""
        for svc in sorted(svc_proc_nih.keys()):
            p = svc_proc_nih[svc]
            svc_total = p["intel"] + p["graviton"] + p["amd"]
            if svc_total <= 0:
                continue
            grav_pct_svc = round(p["graviton"] / svc_total * 100, 1)
            svc_proc_rows += (
                f'<tr><td>{svc}</td>'
                f'<td>{p["intel"]:,.0f}</td>'
                f'<td>{p["graviton"]:,.0f}</td>'
                f'<td>{p["amd"]:,.0f}</td>'
                f'<td>{grav_pct_svc}%</td></tr>\n'
            )
        # Total row
        total_grav_pct = round(grav_nih / total_nih * 100, 1)
        svc_proc_rows += (
            f'<tr style="font-weight:bold;border-top:2px solid var(--gray-700)"><td>TOTAL</td>'
            f'<td>{intel_nih:,.0f}</td>'
            f'<td>{grav_nih:,.0f}</td>'
            f'<td>{amd_nih:,.0f}</td>'
            f'<td>{total_grav_pct}%</td></tr>\n'
        )

        # Segments carry an inline label only when the slice is wide enough to
        # hold it. A 10px monospace label like "GRAVITON 4.3%" needs ~90px, and
        # a slice narrower than PROC_LABEL_MIN_PCT of the container cannot fit
        # that, so centered nowrap text would clip mid-word and read as running
        # underneath the neighbouring slice. Narrow slices stay bare and the
        # legend below names every processor, so no figure is ever hidden.
        PROC_LABEL_MIN_PCT = 14.0
        procs = [
            ("Intel", intel_pct, "rgb(0,153,255)", "rgb(0,108,224)"),
            ("Graviton", grav_pct_bar, "rgb(255,187,69)", "rgb(250,111,0)"),
            ("AMD", amd_pct, "rgb(173,92,255)", "rgb(133,117,255)"),
        ]
        proc_segments = ""
        proc_legend = ""
        for name, pct, c_from, c_to in procs:
            if pct <= 0:
                continue  # a zero-width slice would still paint a 1px sliver
            label = f"{name} {pct}%"
            inner = f"<span>{label}</span>" if pct >= PROC_LABEL_MIN_PCT else ""
            proc_segments += (
                f'<div style="width:{pct}%;'
                f'background:linear-gradient(180deg,{c_from},{c_to})" '
                f'title="{label}">{inner}</div>\n'
            )
            proc_legend += (
                f'<span><i style="background:linear-gradient(180deg,{c_from},{c_to})"></i>'
                f'{label}</span>\n'
            )

        processor_bar_html = f'''<section>
<h2>Compute Coverage by Processor (NIH)</h2>
<div class="proc-bar">
{proc_segments}</div>
<div class="proc-legend">
{proc_legend}</div>
<table style="font-size:13px" class="sortable">
<tr><th>Service</th><th>Intel (NIH)</th><th>Graviton (NIH)</th><th>AMD (NIH)</th><th>Graviton %</th></tr>
{svc_proc_rows}</table>
<p style="font-size:11px;color:var(--text-tertiary);margin-top:8px">NIH = Normalized Instance Hours (accounts for instance size: nano=0.25, xlarge=8, 12xlarge=96, etc.)</p>
</section>
'''

    # Build fleet inventory grouped by service. Existing Graviton is not
    # actionable, and rows with no Graviton path are listed once, under
    # "Not Eligible", rather than here as well.
    fleet_by_service = {}
    for c in sorted(classified, key=lambda x: x.get("cost", 0), reverse=True):
        if c.get("is_graviton") or _not_eligible_reason(c):
            continue
        svc = c.get("service", "ec2")
        fleet_by_service.setdefault(svc, []).append(c)

    def _fleet_row(c):
        raw = _expand_size(c.get("raw", ""))
        rgn = c.get("region", "")
        cost = c.get("cost", 0)
        purchase_type = c.get("purchase_type", "OD")

        # Per-gen targets and savings. Prefer the *validated* target names from
        # enrichment (graviton_targets_by_gen) — these reflect what AWS actually
        # offers, including capacity-adjusted (nearest-smaller) sizes for managed
        # services. Fall back to string construction only when validation data is
        # absent (e.g. Graviton items or price-less runs). A capacity-adjusted
        # target is tagged so the reader sees it is a review-only downsize.
        prefix = c.get("prefix", "")
        size = c.get("target_size") or c.get("size", "")
        type_suffix = c.get("type_suffix", "")
        targets_by_gen = c.get("graviton_targets_by_gen") or {}

        def _gen_target(gkey, base):
            info = targets_by_gen.get(gkey)
            if info is not None and (not info.get("type") or info.get("not_offered")):
                # Validation ran and found nothing AWS sells for this
                # generation here. A string-built name would print a phantom.
                return Raw('— <span class="gen-na" style="color:var(--text-tertiary);'
                           'font-size:11px">not offered in '
                           f'{_esc(rgn) or "this region"}</span>')
            if info and info.get("type"):
                label = _esc(_expand_size(info["type"]))
                if info.get("capacity_adjusted"):
                    # Already-escaped text plus a markup glyph, hence Raw.
                    label += _warn_glyph(
                        "size mismatch: nearest available size differs in vCPU/memory")
                return Raw(label)
            if base:
                return _expand_size(f"{prefix}{base}.{size}{type_suffix}")
            return "—"

        # Source badge
        pricing_src = c.get("pricing_source", "")
        if pricing_src == "pricing_api" or c.get("od_rate_current"):
            source_badge = Raw('<span class="badge ready">actual</span>')
        else:
            source_badge = Raw('<span class="badge upgrade">est</span>')

        # The validated target of the generation enrichment selected, when
        # there is one. graviton_upgrade is the classifier's string-built name
        # and can be a type the region's catalog rejected.
        _sel = GEN_BY_LABEL.get(c.get("graviton_target_generation", ""))
        _sel_info = targets_by_gen.get(_sel.key) if _sel else None
        if c.get("graviton_target_priced"):
            # The type est_savings was priced against, so the cell beside it
            # cannot name a different one.
            default_target = _expand_size(c["graviton_target_priced"])
        elif _sel_info and _sel_info.get("type") and not _sel_info.get("not_offered"):
            default_target = _expand_size(_sel_info["type"])
        elif targets_by_gen and all(not i.get("type") or i.get("not_offered")
                                    for i in targets_by_gen.values()):
            default_target = "—"
        else:
            default_target = (_expand_size(c.get("graviton_upgrade", ""))
                              if c.get("graviton_upgrade") else "—")
        default_savings = c.get("est_savings", 0)

        cells = [
            raw, rgn, purchase_type, _fmt_cost(cost),
            default_target,
            _fmt_cost(default_savings) if default_savings else "—",
        ]
        # One target/savings pair per generation, in GENERATIONS order — the same
        # iteration the header uses, so the two cannot fall out of step. A "—"
        # target means no equivalent exists for that generation (graviton5 is only
        # populated for families with an announced 9g type), not that one was
        # missed.
        for g in GENERATIONS:
            cells.append(_gen_target(g.key, c.get(g.target_field, "")))
            sav = c.get(g.savings_field)
            cells.append(_fmt_cost(sav) if sav else "—")
        cells.append(source_badge)
        return cells

    # Header derived from GENERATIONS, exactly as _fleet_row's cells are. Adding a
    # generation widens both or neither; there is no edit that widens one.
    _SVC_HEADER = (
        ["Instance", "Region", "Purchase", "Cost",
         "Default Target" if target_strategy == "latest" else "Selected Target", _sel_col]
        + [part for g in GENERATIONS
           for part in (f"{g.short} Target", f"{g.short} Savings")]
        + ["Source"]
    )

    fleet_sections = ""
    for svc in ["ec2", "rds", "elasticache", "opensearch"]:
        items = fleet_by_service.get(svc, [])
        if not items:
            continue
        svc_label = service_label(svc)
        svc_cost = sum(c.get("cost", 0) for c in items)
        total_default = sum(c.get("est_savings", 0) or 0 for c in items)
        gen_totals = {g.key: sum(c.get(g.savings_field, 0) or 0 for c in items)
                      for g in GENERATIONS}

        table = Table(_SVC_HEADER, css_class="fleet-table sortable",
                      name=f"Fleet Detail ({svc})")
        for c in items:
            table.row(*_fleet_row(c))
        # The TOTAL row goes through the same width check as the data rows, so
        # it cannot drift from the header. Totals net the per-row savings (which already include negative,
        # already-optimized rows), so a non-zero negative must render — only a
        # value that rounds to zero shows "—".
        total_cells = [f"TOTAL ({len(items)} types)", "", "", _fmt_cost(svc_cost),
                       "", _fmt_cost(total_default) if round(total_default, 2) != 0 else "—"]
        for g in GENERATIONS:
            total_cells += ["", _fmt_cost(gen_totals[g.key])
                            if round(gen_totals[g.key], 2) != 0 else "—"]
        total_cells.append("")
        table.total(*total_cells,
                    style="font-weight:bold;border-top:2px solid var(--gray-700)")
        fleet_sections += f'''<details>
<summary style="cursor:pointer;font-weight:600;font-size:15px;padding:8px 0">
{svc_label} — {len(items)} types | {_fmt_cost(svc_cost)} spend | {_fmt_cost(total_default)} potential savings
</summary>
<div class="fleet-wrapper">
{table.render()}
</div>
</details>\n'''

    # Regional breakdown
    region_data = {}
    for c in classified:
        rgn = c.get("region", "unknown")
        region_data.setdefault(rgn, {"count": 0, "cost": 0, "graviton": 0})
        region_data[rgn]["count"] += 1
        region_data[rgn]["cost"] += c.get("cost", 0)
        if c.get("is_graviton"):
            region_data[rgn]["graviton"] += 1
    region_rows = ""
    for rgn, data in sorted(region_data.items(), key=lambda x: -x[1]["cost"]):
        gpct = round(data["graviton"] / max(data["count"], 1) * 100, 1)
        region_rows += f'<tr><td>{rgn}</td><td>{data["count"]}</td><td>{_fmt_cost(data["cost"])}</td>'
        region_rows += f'<td>{data["graviton"]}</td><td>{gpct}%</td></tr>\n'

    # "Not Eligible" section: every non-Graviton row with no Graviton path,
    # built once from the classified rows. Wave 4 holds the same rows, but only
    # its top five, so adding Wave 4 to a separate Windows list (as this
    # section once did) counted Windows twice.
    no_equivalent_section = ""
    not_eligible = _not_eligible_rows(classified)
    if not_eligible:
        total_not_eligible_cost = sum(c.get("cost", 0) for c in not_eligible)
        ne_table = Table(
            ["Instance Type", "Service", "Region", "Purchase Options",
             "Monthly Cost", "Reason"],
            css_class="sortable", name="Not Eligible")
        for c in not_eligible:
            od, ri, sp, spot = (c.get("cost_od", 0), c.get("cost_ri", 0),
                                c.get("cost_sp", 0), c.get("cost_spot", 0))
            if od or ri or sp or spot:
                pt_cell = (Raw(f"OD: {_esc(_fmt_cost(od))}<br>RI: {_esc(_fmt_cost(ri))}<br>"
                               f"SP: {_esc(_fmt_cost(sp))}<br>Spot: {_esc(_fmt_cost(spot))}"),
                           1, 1, "font-size:11px")
            else:
                pt_cell = c.get("purchase_type", "")
            ne_table.row(_expand_size(c.get("raw", "") or c.get("instance_type", "")),
                         service_label(c.get("service", "ec2")), c.get("region", ""),
                         pt_cell, _fmt_cost(c.get("cost", 0)), c["_reason"])
        ne_table.total(f"TOTAL ({_plural(len(not_eligible), 'type')})", "", "", "",
                       _fmt_cost(total_not_eligible_cost), "",
                       style="font-weight:bold;border-top:2px solid var(--gray-700)")
        no_equivalent_section = f'''<section>
<h2>Not Eligible for Graviton Savings</h2>
<p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">{_plural(len(not_eligible), "instance type")} ({_fmt_cost(total_not_eligible_cost)} spend) {"is" if len(not_eligible) == 1 else "are"} not included in savings calculations.</p>
{ne_table.render()}
</section>'''

    # ── Generation selector + NIH slider data ──────────────────────────────
    # Per-instance price data for live client-side recompute. Only upgradeable
    # rows with real pricing are included; blocked/Windows/already-Graviton rows
    # never contribute savings.
    #
    # Each row carries the "next-gen" target (`tgt`, what the assessment chose)
    # AND every priced generation's rate (`g2`/`g3`/`g4`/`g5`), so the generation
    # radios can retarget the whole fleet without a re-run. Rows missing a
    # generation fall back to their next-gen target, matching the dashboard.
    perf_default_pct = perf_per_gen
    perf_rows = []
    # "newest" is counted separately: the comparison tile reaches any row with at
    # least one priced generation, which is broader coverage than g5 alone.
    gen_available = {**gen_zeroes(), "newest": 0}
    # Upgradeable rows excluded for lack of pricing. These are NOT "no Graviton
    # option exists" — most often the Pricing API throttled and the price was
    # dropped. Tracked so the report can say so instead of silently omitting
    # real spend from the totals.
    unpriced_rows = []
    for c in classified:
        # Rows with no Graviton path (Windows, commercial engines, licensed
        # platforms) belong in "Not Eligible". They never enter PERF_ROWS: the
        # page's script rebuilds the headline from these rows on load, so one
        # row the scorer excludes here would put its saving in the headline.
        if not _earns_savings(c):
            continue
        if (not c.get("od_rate_current")
                and c.get("graviton_upgrade") and c.get("cost", 0) > 0):
            unpriced_rows.append({
                "raw": c.get("raw", ""),
                "region": c.get("region", ""),
                "cost": round(c.get("cost", 0), 2),
            })
        cur = c.get("od_rate_current")
        # Always the true next-gen rate, never the CLI-selected generation —
        # otherwise the "Default next-gen" radio would mean whatever
        # --graviton-generation was passed, and the same fleet would report
        # different next-gen savings per invocation.
        tgt = c.get("od_rate_graviton_nextgen") or c.get("od_rate_graviton")
        cost = c.get("cost", 0)
        # Savings AMOUNTS, not rates. est_savings and est_savings_gN are
        # commitment-matched (the Graviton Savings Dashboard's basis: amortized
        # current cost against a target priced at the same term, payment option
        # and offering class). Shipping the amounts rather than rates means the
        # client never re-derives savings: the slider's 0% position equals the
        # Python total by construction, and savings are defined in one place.
        if not cur or not tgt or cur <= 0 or cost <= 0:
            continue
        # The scorer's own figure: enrichment's commitment-matched saving, else
        # what the scorer booked for the row. Never re-derived here. The page
        # rebuilds its headline from these rows, so a row the scorer left
        # unpriced must stay out of PERF_ROWS (and go to the unpriced list).
        _default_sav = c.get("est_savings")
        if _default_sav is None:
            if c.get("booked_source") in _BOOKED_PRICED:
                _default_sav = c.get("booked_savings") or 0.0
            else:
                if not any(u["raw"] == c.get("raw", "") and
                           u["region"] == c.get("region", "") for u in unpriced_rows):
                    unpriced_rows.append({
                        "raw": c.get("raw", ""),
                        "region": c.get("region", ""),
                        "cost": round(cost, 2),
                    })
                continue
        row = {
            "cost": round(cost, 2),
            # The figure for the generation the report opens on: the server's
            # own selected-target saving, so the opening headline equals the
            # stdout and Markdown totals exactly.
            "sav": round(_default_sav, 2),
            # Generational steps to that target. The comparison tile compounds
            # the NIH rate per step, so each row needs its own hop count rather
            # than a fleet-wide constant. 0 for a same-generation move
            # (m6a -> m6g), which earns no generational uplift.
            "h": int(c.get("gen_hops") or 0),
        }
        by_gen = c.get("graviton_rates_by_gen") or {}
        if target_strategy != "latest":
            # The opening selection is not next-gen, so "Default next-gen" needs
            # its own figure; without it that radio would show the forced
            # generation's savings under the next-gen label.
            _nk = _nextgen_key(c)
            if _nk and c.get(f"est_savings_{_nk}") is not None:
                row["nx"] = round(c[f"est_savings_{_nk}"], 2)
                row["nxh"] = int((by_gen.get(_nk) or {}).get("hops") or 0)
        for _g in GENERATIONS:
            gkey = _g.key
            entry = by_gen.get(gkey)
            gen_sav = c.get(_g.savings_field)
            if entry and entry.get("rate") and gen_sav is not None:
                row[gkey] = round(gen_sav, 2)
                # Per-generation hop count, so switching the generation radio
                # also switches the compounding exponent.
                row[gkey + "h"] = int(entry.get("hops") or 0)
                gen_available[gkey] += 1
        # "Latest available" reaches any row with at least one priced generation,
        # since it walks g5 -> g2 and takes the first hit. Counted separately so
        # the radio reports its own real coverage rather than borrowing g5's,
        # which is much narrower (only c/m families have a 9g type).
        if any(g.key in row for g in GENERATIONS):
            gen_available["newest"] += 1
        perf_rows.append(row)
    # One radio per generation, from GENERATIONS, so a new generation cannot be
    # added to the tables and the CSV but missed here or in the JS label map.
    gen_radios_html = "\n".join(
        '<label style="display:block;margin-bottom:6px;cursor:pointer">'
        + f'<input type="radio" name="gen-select" value="{g.key}"'
        + (' checked' if open_gen == g.key else '') + f'> {g.label} '
        + f'<span class="gen-avail" data-gen="{g.key}" '
        + 'style="color:var(--text-tertiary);font-size:11px"></span></label>'
        for g in GENERATIONS
    )
    # The script's label map and newest-first walk order, serialised from the same
    # tuple the markup uses, rather than restated as JS literals.
    #   nextgen — the "Default next-gen" radio, not a fixed generation
    #   newest  — the "If All -> Latest Generation" comparison; no radio, but
    #             resolveGen() still needs the key
    gen_labels_json = json.dumps(
        {"nextgen": "Default next-gen", "newest": "Latest available",
         **{g.key: g.label for g in GENERATIONS}}, separators=(",", ":"))
    gen_desc_json = json.dumps([g.key for g in GEN_NEWEST_FIRST],
                               separators=(",", ":"))
    perf_data_json = json.dumps(perf_rows, separators=(",", ":"))
    gen_available_json = json.dumps(gen_available, separators=(",", ":"))
    # Baseline price-only savings at the opening selection, so the slider's 0%
    # position reconciles with the headline KPI.
    perf_baseline_savings = round(sum(r["sav"] for r in perf_rows), 2)
    # Rows that fell back to another generation because the requested one
    # isn't offered/priced in their region — surfaced so it isn't silent.
    gen_fallback_count = sum(
        1 for c in classified if c.get("graviton_generation_fallback")
    )

    # ── Incomplete-pricing banner ──────────────────────────────────────────
    # Silently dropping throttled rows makes real spend look like it doesn't
    # exist. Surface both the excluded rows and the underlying API errors.
    pricing_err = (assessment.get("summary", {}) or {}).get("pricing_errors") or {}
    per_type_errors = pricing_err.get("per_type_errors") or []
    per_type_error_count = pricing_err.get("per_type_error_count", 0)
    # Counts and spend come from score.kpis when present: it covers every
    # upgradeable row with no price, including those priced on the current side
    # but not the target's. The named rows are the ones with no current price.
    unpriced_count = kpis.get("unpriced_count")
    if unpriced_count is None:
        unpriced_count = len(unpriced_rows)
        unpriced_cost = round(sum(r["cost"] for r in unpriced_rows), 2)
    else:
        unpriced_cost = kpis.get("unpriced_cost") or 0
    indicative = kpis.get("unpriced_indicative_savings")
    pricing_warning_html = ""
    if unpriced_count or per_type_error_count:
        throttled = sum(1 for e in per_type_errors if "Throttling" in e or "Rate exceeded" in e)
        detail = ""
        if unpriced_count:
            listed = ", ".join(
                f"{r['raw']} ({r['region']}, {_fmt_cost(r['cost'])})"
                for r in sorted(unpriced_rows, key=lambda x: -x["cost"])[:8]
            )
            more = (f" and {len(unpriced_rows) - 8} more"
                    if len(unpriced_rows) > 8 else "")
            named = f", including {listed}{more}" if listed else ""
            estimate = (f" An indicative 20% estimate for them would be "
                        f"{_fmt_cost(indicative)}/mo; it is <strong>not</strong> "
                        f"included anywhere." if indicative else "")
            detail = (
                f"<br><strong>{unpriced_count} upgradeable instance type(s)</strong> "
                f"({_fmt_cost(unpriced_cost)}/mo) are <strong>excluded from every savings "
                f"figure above</strong> because no price could be resolved{named}.{estimate}"
            )
        cause = ""
        if throttled:
            cause = (
                f"<br>{throttled} of {per_type_error_count} pricing lookup(s) failed with "
                f"<code>ThrottlingException</code> (Pricing API rate limit). This is "
                f"transient — re-run, or avoid running multiple assessments concurrently. "
                f"These instances <em>do</em> exist; their prices were not retrieved."
            )
        elif per_type_error_count:
            cause = f"<br>{per_type_error_count} pricing lookup(s) failed. See <code>pricing_errors</code> in the JSON result."
        pricing_warning_html = f'''<div class="callout" style="margin:var(--space-16) 0">
<strong>Incomplete pricing data — savings are understated</strong>{detail}{cause}
</div>'''

    complete, failed_pulls = _completeness(summary)
    completeness_html = ""
    if complete is False:
        completeness_html = (
            '<div class="callout" style="margin:var(--space-16) 0">'
            '<strong>Incomplete Cost Explorer data — spend and savings are understated.</strong> '
            f'{len(failed_pulls)} pull(s) failed: {_esc(", ".join(failed_pulls))}. '
            'Re-run before relying on these figures.</div>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Graviton Savings Assessment{_title_suffix}</title>
{_CSS}
</head>
<body>
<div class="container">
<header>
<h1>Graviton Savings Assessment</h1>
<p class="subtitle">{_esc(_report_subject(customer, account_id))}</p>
<div class="meta">
<span>{datetime.now().strftime("%B %Y")}</span>
<span>{len(regions)} regions</span>
<span>Pricing: {pricing_source}</span>
<span>Target: {_esc(_strategy_label(target_strategy))}</span>
</div>
<p style="font-size:12px;color:var(--text-secondary);margin-top:var(--space-8)">{_esc(_period_text(period))}. Spend basis: {_esc(_spend_basis(summary))}.</p>
</header>
{completeness_html}

<div class="kpi-grid">
<div class="kpi"><div class="value">{_fmt_cost(total_cost)}</div><div class="label">{spend_label}</div></div>
<div class="kpi"><div class="value">{graviton_pct:.1f}%</div><div class="label">Graviton Coverage (NIH)</div><div class="subvalue">{graviton_spend_pct:.1f}% by spend</div></div>
<div class="kpi"><div class="value">{_fmt_cost(realized_total)}</div><div class="label">Realized Savings</div><div class="subvalue">Current Graviton vs Intel</div></div>
<div class="kpi highlight"><div class="value" id="kpi-monthly-savings">{_fmt_cost(total_savings)}</div><div class="label">{savings_label}</div><div class="subvalue" id="kpi-savings-pct">{savings_pct_of_spend:.1f}% of total spend</div></div>
<div class="kpi highlight"><div class="value" id="kpi-annual-savings">{_fmt_cost(total_savings * period["annual_factor"])}</div><div class="label">Annualized Savings</div></div>
<div class="kpi"><div class="value">{round(upgradeable_cost / max(total_cost, 1) * 100, 1)}%</div><div class="label">Upgradeable Spend</div><div class="subvalue">{_fmt_cost(upgradeable_cost)}</div></div>
</div>

{pricing_warning_html}

<!-- Graviton Opportunity: generation selector + NIH reduction slider -->
<section id="perf-panel">
<h2>Graviton Opportunity</h2>
<p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">
This section estimates potential savings from migrating to AWS Graviton. <strong>All figures below refresh
dynamically based on your selections.</strong>
</p>
<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start">

<div style="flex:1;min-width:260px">
<div style="font-weight:600;margin-bottom:8px">Select Preferred Graviton Generation</div>
<label style="display:block;margin-bottom:6px;cursor:pointer"><input type="radio" name="gen-select" value="nextgen"{' checked' if open_gen == 'nextgen' else ''}> <strong>Default next-gen</strong> <span style="color:var(--text-secondary);font-size:12px">— n+1 from current (e.g. c5 → c6g)</span></label>
{gen_radios_html}
<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">
Graviton2/3/4/5 migrate <em>all</em> instances to that generation. Instances with no priced target in
that generation keep their next-gen target and are counted below.
</div>
<div class="callout" style="margin-top:var(--space-12);font-size:12px">
<strong>Read the generation comparison with care.</strong> Older Graviton generations are cheaper
<em>per hour</em>, so they show the <em>largest</em> savings here — Graviton2 will usually top this
list. <strong>That is not a recommendation to target Graviton2.</strong> The NIH reduction is applied
as a single flat percentage to every generation (matching the Graviton Savings Dashboard), so these
figures do <strong>not</strong> model the fact that a newer generation does the same work in fewer
instance-hours. A newer target needs fewer normalized instance-hours than an older one, and that
effect is not captured above. Use this to size the <em>opportunity</em>, not to choose a target
generation — for that, validate price-performance against your own workload benchmarks.
</div>
</div>

<div style="flex:1;min-width:260px">
<div style="font-weight:600;margin-bottom:8px">Estimated NIH % Reduction <span style="font-weight:400;color:var(--text-tertiary);font-size:12px">Range: [0–40%]</span></div>
<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
<input type="number" id="perf-input" min="0" max="40" step="1" value="{perf_default_pct:.0f}" style="width:72px;padding:var(--space-4) var(--space-8);font-family:var(--font-mono);font-size:15px;border:1px solid var(--border-default);border-radius:var(--radius-sm);text-align:right">
<span style="font-weight:600">%</span>
</div>
<input type="range" id="perf-slider" min="0" max="40" step="1" value="{perf_default_pct:.0f}" style="width:100%">
<div style="font-size:12px;color:var(--text-secondary);margin-top:8px">
Input your projected <strong>Normalized Instance Hours (NIH)</strong> reduction — the share of
instance-hours the same workload no longer needs on Graviton's higher per-vCPU performance. This is an
<strong>assumption, not a measurement</strong> — actual savings require workload testing and validation.
<br><br>
The headline figure applies this rate <strong>once, flat</strong>, regardless of how many generations an
instance advances: <code>additional = projected_graviton_cost × NIH%</code>. This matches the Graviton
Savings Dashboard's <code>EC2EfficiencyGain</code>, so the two report the same quantity the same way. At
0% it collapses to price-only.
<br><br>
The <strong>If All → Latest Generation</strong> figure beside it is a comparison, not the headline. It
retargets every instance to the newest Graviton its family offers and compounds the same rate
<strong>per generational hop</strong>, because a Graviton4 target genuinely needs fewer instance-hours
than a Graviton2 target for identical work. Hops run from the source generation to the target's
(<code>c5 → c9g</code> = 4 hops; <code>m6a → m6g</code> = 0), and the rate is divisive rather than
subtractive: <code>nih_factor = (1 + NIH%)<sup>−hops</sup></code>, so 10%/hop means the work fits into
1/1.1 of the hours — 9.1% over one hop and 1/1.1<sup>4</sup> = 0.683, a 31.7% reduction, over four. A
same-generation move crosses no generation and earns no uplift.
<br><br>
Read the gap between the two as <strong>the value of targeting newer silicon</strong>, and treat the
compounded figure as the more speculative of the pair — it assumes both the retargeting and a
per-hop performance gain, neither of which is measured here.
</div>
</div>
</div>

<div class="kpi-grid" style="margin-top:20px">
<div class="kpi"><div class="value" id="pp-base">—</div><div class="label">Potential Graviton Base Savings</div><div class="subvalue">Instance migration only · <span id="pp-gen-label">Default next-gen</span></div></div>
<div class="kpi"><div class="value" id="pp-additional">—</div><div class="label">Estimated Additional Savings Due to Performance</div><div class="subvalue">On top of base · <span id="pp-nih-label">—</span> · flat, no hops</div></div>
<div class="kpi"><div class="value" id="pp-latest">—</div><div class="label">If All → Latest Generation</div><div class="subvalue">Comparison only · <span id="pp-latest-note">—</span></div></div>
</div>
<p style="font-size:11px;color:var(--text-tertiary);margin-top:8px">
The <strong>first two</strong> figures are the components of the <strong>Monthly Savings Opportunity</strong>
above, which updates with this slider — base + performance. The third is a what-if at latest-generation
targets with the rate compounded per hop, and is <strong>not</strong> included in the headline. Computed live
over {len(perf_rows)} upgradeable instance types. <span id="pp-fallback-note"></span>
</p>
</section>

<!-- Processor Distribution -->
{processor_bar_html}

<!-- Service Summary -->
<section>
<h2>Service Summary</h2>
<div class="callout info" style="margin-bottom:var(--space-16)">
<strong>Methodology:</strong><br>
• <strong>Realized Savings:</strong> Current savings from Graviton usage vs Intel equivalent at the same purchase terms (RI/SP/OD).<br>
• <strong>Default (n+1):</strong> Savings from migrating each instance to its next-generation Graviton target (Gen ≤5→G2, Gen 6→G3, Gen 7→G4, Gen 8+→G5 where a 9g type exists).<br>
• <strong>G2–G5 columns:</strong> What-if scenarios if ALL items targeted that specific generation regardless of current gen.
</div>
{svc_table.render()}
</section>

<!-- Top Migration Opportunities -->
<section>
<h2>Top Migration Opportunities</h2>
<p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Top 12 instances by cost with actual OD rate comparisons from AWS Pricing API. Each row shows savings for all available Graviton generations.</p>
{opp_table.render()}
{opp_size_mismatch_callout}
{opp_od_proxy_callout}
</section>

{already_opt_section}

{no_equivalent_section}

{engine_section}

<section>
<h2>Potential Graviton Savings - Full Fleet Detail</h2>
<div class="callout info" style="margin-bottom:var(--space-16)">
<strong>Source:</strong> Items marked <span class="badge ready">actual</span> use AWS Pricing API rates matched to the same purchase option (RI/SP/OD).
Items marked <span class="badge upgrade">est</span> had no price; they are excluded from every savings figure.
</div>
{fleet_sections}
</section>

{_build_next_steps_html(assessment)}

<!-- Call to Action -->
{_build_call_to_action_html()}

<!-- Additional Resources -->
{_build_additional_resources_html()}

{_build_data_quality_html(assessment)}

<footer>
<p>Generated by Graviton Savings Assessment | Data: AWS Cost Explorer (AmortizedCost)
| Pricing: {pricing_source} ({pricing_resolved} types resolved) | {now} | Source: {_source_hash()}</p>
</footer>
</div>
<script>
{_SORT_JS}

// ── Graviton generation selector + NIH reduction slider ─────────────────
const PERF_ROWS = {_esc_json(perf_data_json)};
const PERF_BASELINE = {perf_baseline_savings};
const TOTAL_MONTHLY_COST = {total_cost};
const GEN_AVAILABLE = {_esc_json(gen_available_json)};
const GEN_FALLBACK_COUNT = {gen_fallback_count};
// Generation vocabulary, serialised from the GENERATIONS tuple rather than
// restated as JS literals. GEN_DESC is newest-first: the latest-generation
// comparison walks it and takes the first priced hit per row, so a family that
// stops at Graviton3 lands on Graviton3 instead of being dropped the way a fixed
// Graviton5 selection would drop it.
const GEN_LABELS = {gen_labels_json};
const GEN_DESC = {gen_desc_json};
// The radio the report opens on, and the factor that annualises its figures.
const OPEN_GEN = {json.dumps(open_gen)};
const ANNUAL_FACTOR = {period["annual_factor"]};
{_REPORT_JS}
</body>
</html>"""
    return html


def _write_validation_csv(assessment: dict, output_dir: str, timestamp: str) -> str:
    """Write a flat CSV with all instance types for validation against GSR.

    One row per classified instance type. Includes realized savings (Graviton items),
    potential savings (non-Graviton), and not-eligible (Windows/blocked).

    Returns the CSV file path.
    """
    import csv

    classified = assessment.get("classified_detail", [])
    csv_path = os.path.join(output_dir, f"graviton-validation-{timestamp}.csv")

    with open_private(csv_path, newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instance_type", "service", "region", "platform", "purchase_type",
            "processor", "gen_bucket", "monthly_cost", "hours",
            "cost_od", "cost_ri", "cost_sp", "cost_spot", "cost_sp_isp", "cost_ri_locked",
            "graviton_target", "od_rate_current", "od_rate_graviton",
            # Generation columns from GENERATIONS, matching the row below. Width
            # parity alone could not catch a generation missing from both.
            "est_savings_default", *(g.savings_field for g in GENERATIONS),
            "realized_savings", "intel_equivalent", "intel_rate",
            "category", "pricing_source",
        ])

        for item in sorted(classified, key=lambda x: (-x.get("cost", 0))):
            raw = item.get("raw", "")
            service = item.get("service", "ec2")
            region = item.get("region", "")
            platform = item.get("platform", "")
            purchase_type = item.get("purchase_type", "")
            cost = item.get("cost", 0)
            hours = item.get("hours", 0)

            # Processor
            if item.get("is_graviton"):
                processor = "Graviton"
            elif item.get("is_amd"):
                processor = "AMD"
            else:
                processor = "Intel"

            gen_bucket = item.get("gen_bucket", "")

            # Category: realized (Graviton), potential (non-Graviton upgradeable),
            # or not_eligible_* with the same reason the HTML's Not Eligible
            # section gives.
            reason = _not_eligible_reason(item)
            if item.get("is_graviton"):
                category = "realized"
            elif reason is None:
                category = "potential"
            elif reason.startswith("Windows"):
                category = "not_eligible_windows"
            elif reason == "Unrecognised instance type":
                category = "not_eligible_unclassified"
            elif reason == "No Graviton counterpart":
                category = "not_eligible_no_target"
            elif reason.startswith("Licensed software"):
                category = "not_eligible_licensed_software"
            else:
                category = "not_eligible_commercial_engine"

            # Pricing
            od_rate = item.get("od_rate_current", "")
            od_grav = item.get("od_rate_graviton", "")
            est_savings = item.get("est_savings", "")
            gen_savings = [item.get(g.savings_field, "") for g in GENERATIONS]
            if category.startswith("not_eligible"):
                # Enrichment may have priced a row the scorer excludes; a figure
                # in this column would read as a saving the headline omits.
                est_savings, gen_savings = "", ["" for _ in GENERATIONS]
            # Prefer the catalog-validated target over the classifier's
            # string-built candidate, matching what the HTML report renders.
            # Using graviton_upgrade alone printed types AWS does not offer
            # (c7g.24xlarge, db.r7g.32xlarge) into a customer deliverable.
            graviton_target = _expand_size(
                item.get("graviton_target_priced", "") or item.get("graviton_target", "")
                or item.get("graviton_upgrade", "")
            )

            # Realized savings (for Graviton items)
            realized_savings = ""
            intel_equivalent = ""
            intel_rate = ""
            if item.get("is_graviton"):
                # Per row, not per type: rows are keyed by (type, region,
                # coordinates), so a type-keyed lookup repeated one row's figures.
                rd = item.get("realized") or {}
                realized_savings = rd.get("savings", "")
                intel_equivalent = rd.get("intel_equivalent", "")
                intel_rate = rd.get("intel_price_per_hr", "")

            # Cost breakdown
            cost_od = item.get("cost_od", "")
            cost_ri = item.get("cost_ri", "")
            cost_sp = item.get("cost_sp", "")
            cost_spot = item.get("cost_spot", "")
            cost_sp_isp = item.get("cost_sp_isp", "")
            cost_ri_locked = item.get("cost_ri_locked", "")

            # Pricing source. "capacity_adjusted" must surface here: those rows
            # carry a different-size target, so a bare "actual" would present
            # them as a like-for-like recommendation in the CSV deliverable.
            if item.get("graviton_capacity_adjusted"):
                pricing_src = "capacity_adjusted"
            elif item.get("od_rate_current"):
                pricing_src = "actual"
            else:
                pricing_src = "none"

            # _csv_safe on every cell: this file is a customer deliverable, and
            # Excel/Sheets evaluate a cell beginning = + - @ tab or CR on open.
            # Numbers pass through unchanged so negative savings stay numeric.
            writer.writerow([_csv_safe(v) for v in (
                raw, service, region, platform, purchase_type,
                processor, gen_bucket, round(cost, 2), round(hours, 2),
                cost_od, cost_ri, cost_sp, cost_spot, cost_sp_isp, cost_ri_locked,
                graviton_target, od_rate, od_grav,
                est_savings, *gen_savings,
                realized_savings, intel_equivalent, intel_rate,
                category, pricing_src,
            )])

    return csv_path


def write_reports(assessment: dict, output_dir: str = ".",
                  customer: str = "", account_id: str = "",
                  target_strategy: str = "latest",
                  perf_per_gen: float = PERF_DEFAULT_PCT) -> dict:
    """Generate and write both markdown and HTML reports to disk.

    Args:
        assessment: The full result dict from estimate_graviton_savings
        output_dir: Directory to write reports to
        customer: Customer name for report header
        account_id: Account ID for report header
        target_strategy: The pipeline's target_strategy. Labels both reports and
            picks the generation radio the HTML opens on.
        perf_per_gen: NIH reduction (%) the HTML slider opens at; 0 is
            price-only, matching the stdout and Markdown figures.

    Returns:
        Dict with markdown_path, html_path, csv_path, and summary stats.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    base = f"graviton-migration-report-{timestamp}"

    md_content = generate_markdown(assessment, customer, account_id, target_strategy)
    html_content = generate_html(assessment, customer, account_id, target_strategy,
                                 perf_per_gen=perf_per_gen)

    md_path = os.path.join(output_dir, f"{base}.md")
    html_path = os.path.join(output_dir, f"{base}.html")

    # encoding is explicit because the reports contain —, ·, and the warning
    # glyph while declaring charset=UTF-8; relying on the platform default
    # raises UnicodeEncodeError on a cp1252 locale.
    _write_private(md_path, md_content)
    _write_private(html_path, html_content)

    # Validation CSV
    csv_path = _write_validation_csv(assessment, output_dir, timestamp)

    summary = assessment.get("summary", {})
    return {
        "markdown_path": md_path,
        "html_path": html_path,
        "csv_path": csv_path,
        "timestamp": timestamp,
        "total_types": summary.get("total_types", 0),
        "total_cost": summary.get("total_cost", 0),
        "graviton_pct": summary.get("graviton_pct", 0),
        "pricing_source": summary.get("pricing_source", "none"),
    }


# ── Report assets ──────────────────────────────────────────────────────────
# The stylesheet and the report's client-side script, held as plain (NON-f)
# strings and interpolated once into the HTML template. Inside the template's
# f-string every literal brace would have to be doubled, and a mis-escaped brace
# is invisible until the template renders on a particular interpreter (f-string
# rules differ before Python 3.12). As plain strings, braces are just braces.
#
# Kept in this module rather than split into .css/.js files: the assets are
# inlined at generation time to keep the report a single self-contained file,
# and a separate file would be one more thing to keep identical between the two
# skill bundles. _source_hash() covers only the computation modules, so
# presentation assets do not belong in it either way.


_CSS = """\
<style>
/* ── AWS brand tokens ───────────────────────────────────────────────────
   Values transcribed from the AWS brand design system (fig-tokens.css:
   18 hues x 12 shades + a 20-step gray ramp). Colors are token values, not
   picked by eye — if a shade is needed that isn't here, use the nearest token.

   Fonts are referenced by name only; no font files are redistributed. Amazon
   Ember renders for anyone who has it installed and falls back to the system
   stack otherwise.

   Brand conventions applied: hairline insets instead of drop shadows, 2px/5px
   radii only, spacing from the fixed scale, monospace reserved for metadata,
   no emoji. */
:root{
  --white:#fff;
  --gray-50:rgb(252,252,253);--gray-100:rgb(249,249,251);--gray-150:rgb(246,246,249);
  --gray-200:rgb(243,243,247);--gray-250:rgb(235,235,240);--gray-300:rgb(222,222,227);
  --gray-350:rgb(204,204,209);--gray-400:rgb(180,180,187);--gray-500:rgb(140,140,148);
  --gray-600:rgb(101,104,113);--gray-700:rgb(51,56,67);--gray-800:rgb(27,35,45);
  --gray-850:rgb(22,29,38);--gray-900:rgb(19,25,32);--gray-1000:rgb(6,8,10);
  --amber-50:rgb(255,247,230);--amber-100:rgb(255,232,189);--amber-300:rgb(255,187,69);
  --amber-400:rgb(255,153,0);--amber-700:rgb(158,55,0);--amber-800:rgb(122,43,0);
  --blue-50:rgb(240,251,255);--blue-100:rgb(209,241,255);--blue-600:rgb(0,108,224);
  --blue-700:rgb(0,74,158);
  --green-100:rgb(217,255,214);--green-700:rgb(0,102,0);
  --red-50:rgb(255,242,242);--red-100:rgb(255,220,220);--red-700:rgb(158,0,0);
  --purple-600:rgb(151,71,255);
  /* semantic aliases */
  --surface-page:var(--gray-200);--surface-card:var(--white);--surface-sunken:var(--gray-200);
  --border-subtle:var(--gray-250);--border-default:var(--gray-350);
  --text-primary:var(--gray-850);--text-secondary:var(--gray-600);--text-tertiary:var(--gray-500);
  --accent-amber:var(--amber-400);--link:var(--blue-600);
  /* spacing scale — 2,4,8,12,16,20,24,32,40,64 (no values between steps) */
  --space-2:2px;--space-4:4px;--space-8:8px;--space-12:12px;--space-16:16px;
  --space-20:20px;--space-24:24px;--space-32:32px;--space-40:40px;--space-64:64px;
  /* radii — 2px and 5px only */
  --radius-sm:2px;--radius-md:5px;
  /* hairline inset used instead of drop shadows */
  --hairline:inset 0 0 0 1px rgba(0,0,0,0.1);
  /* Gradients. The brand's own gradient library is 144 diamond/radial bitmap
     wallpapers (light + dark, 3 styles), used full-bleed on hero/cover surfaces.
     Those bitmaps aren't in this bundle, so these are CSS approximations built
     only from real palette tokens, echoing the diamond/radial character at the
     brand's saturation. Treat as an extension of the system, not a literal
     reproduction — swap in the real assets if the imagery bundle arrives. */
  --grad-hero:linear-gradient(103deg,
      rgb(255,153,0) 0%, rgb(255,75,20) 34%,
      rgb(173,92,255) 72%, rgb(92,127,255) 100%);
  --grad-rule:linear-gradient(90deg,
      rgb(255,153,0) 0%, rgb(255,75,20) 55%, rgb(173,92,255) 100%);
  --grad-diamond:radial-gradient(120% 120% at 12% 0%,
      rgb(255,247,230) 0%, rgb(255,232,189) 38%, rgb(255,255,255) 78%);
  /* Font stacks mirror AWS's production CSS (a0.awsstatic.com/libra-css,
     style-awsm-base.css), which declares:
         font-family: AmazonEmber, Helvetica Neue, Helvetica, Arial, sans-serif
     Family names are referenced only — no font files are bundled or served, so
     nothing is redistributed. Machines with Amazon Ember installed render it;
     everyone else gets the same Helvetica/Arial fallback AWS itself specifies.
     Deliberately NOT the -apple-system stack: that renders as SF/Segoe, which
     is the generic system-UI look rather than anything AWS. */
  --font-display:"Amazon Ember Display",AmazonEmber,"Amazon Ember","Helvetica Neue",Helvetica,Arial,sans-serif;
  --font-body:AmazonEmber,"Amazon Ember","Amazon Ember Display","Helvetica Neue",Helvetica,Arial,sans-serif;
  --font-mono:"Amazon Ember Mono",AmazonEmberMono,ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font-body);background:var(--surface-page);
color:var(--text-primary);line-height:1.5;-webkit-font-smoothing:antialiased}
.container{max-width:1400px;margin:0 auto;padding:var(--space-32) var(--space-24)}
/* Masthead: a printed-report title block, not a colored slab. Squid ink is
   reserved for type here; the amber rule is the only chrome. */
header{position:relative;background:var(--grad-diamond);color:var(--text-primary);
padding:var(--space-32) var(--space-32) var(--space-24);margin-bottom:var(--space-32);
border-radius:var(--radius-md);border:1px solid var(--border-subtle);overflow:hidden}
/* Brand-gradient keyline across the masthead — the one saturated moment. */
header::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;
background:var(--grad-hero)}
header h1{font-family:var(--font-display);font-size:34px;font-weight:700;
letter-spacing:-0.02em;line-height:1.12;margin-bottom:var(--space-4)}
header .subtitle{color:var(--text-secondary);font-size:15px}
header .meta{display:flex;gap:var(--space-20);flex-wrap:wrap;
font-family:var(--font-mono);font-size:10px;text-transform:uppercase;
letter-spacing:0.06em;color:var(--text-tertiary);margin-top:var(--space-16)}
/* KPI band: figures do the work. Numbers are right-aligned and tabular so
   columns of currency line up the way a financial statement expects. */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:0;margin-bottom:var(--space-32);background:var(--surface-card);
border:1px solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden}
.kpi{background:var(--surface-card);padding:var(--space-20);
border-right:1px solid var(--border-subtle)}
.kpi:last-child{border-right:none}
.kpi .value{font-family:var(--font-display);font-size:27px;font-weight:700;
color:var(--text-primary);line-height:1.1;letter-spacing:-0.02em;
font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.kpi .label{font-family:var(--font-mono);font-size:10px;text-transform:uppercase;
letter-spacing:0.06em;color:var(--text-secondary);margin-top:var(--space-8);line-height:1.4}
.kpi .subvalue{font-size:12px;color:var(--text-tertiary);margin-top:var(--space-4)}
/* Emphasis is an amber keyline + amber figure — no inverted block. */
.kpi{position:relative}
.kpi.highlight{background:var(--grad-diamond)}
/* Gradient cap marks the headline figures without inverting the tile. */
.kpi.highlight::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
background:var(--grad-rule)}
.kpi.highlight .value{color:var(--amber-700)}
.kpi.highlight .label{color:var(--amber-800)}
section{background:var(--surface-card);border:1px solid var(--border-subtle);
border-radius:var(--radius-md);padding:var(--space-24);margin-bottom:var(--space-20)}
/* Section titles read as statement headings: small amber eyebrow rule above a
   plain squid-ink title, rather than an underlined colored bar. */
h2{font-family:var(--font-display);font-size:19px;font-weight:700;
letter-spacing:-0.015em;margin-bottom:var(--space-16);color:var(--text-primary);
padding-top:var(--space-12);display:inline-block;padding-right:var(--space-24);
position:relative}
/* Gradient eyebrow rule above each section title. */
h2::before{content:'';position:absolute;top:0;left:0;width:44px;height:3px;
background:var(--grad-rule);border-radius:var(--radius-sm)}
h3{font-family:var(--font-display);font-weight:700;letter-spacing:-0.01em}
table{width:100%;border-collapse:collapse;font-size:13px;
font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
th{background:transparent;padding:var(--space-8) var(--space-12);text-align:left;
font-family:var(--font-mono);font-size:10px;font-weight:400;text-transform:uppercase;
letter-spacing:0.05em;color:var(--text-secondary);
border-bottom:1px solid var(--gray-700)}
td{padding:var(--space-8) var(--space-12);border-bottom:1px solid var(--border-subtle)}
/* Currency and percentages right-align — the convention that makes columns
   of figures scannable. */
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:nth-child(even){background:var(--gray-100)}
tbody tr:hover{background:var(--amber-50)}
tbody tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:var(--space-2) var(--space-8);
border-radius:var(--radius-sm);font-family:var(--font-mono);font-size:10px}
.badge.warn{background:var(--amber-100);color:var(--amber-800)}
.ready{background:var(--green-100);color:var(--green-700)}
.upgrade{background:var(--amber-100);color:var(--amber-800)}
.blocked{background:var(--red-100);color:var(--red-700)}
.callout{background:var(--amber-50);border-left:3px solid var(--accent-amber);
padding:var(--space-12) var(--space-16);border-radius:0 var(--radius-sm) var(--radius-sm) 0;
margin:var(--space-12) 0;font-size:13px}
.callout.info{background:var(--blue-50);border-left-color:var(--link)}
a{color:var(--link);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:var(--link)}
.size-warning{font-family:var(--font-mono);font-size:10px;color:var(--amber-800);
background:var(--amber-100);padding:0 var(--space-4);border-radius:var(--radius-sm)}
footer{position:relative;padding:var(--space-24) 0;font-family:var(--font-mono);
font-size:10px;color:var(--text-tertiary);
display:flex;justify-content:space-between;flex-wrap:wrap;gap:var(--space-8)}
footer::before{content:'';position:absolute;top:0;left:0;width:44px;height:2px;
background:var(--grad-rule)}
footer::after{content:'';position:absolute;top:0;left:44px;right:0;height:1px;
background:var(--border-subtle)}
.gen-tag{display:inline-block;background:var(--blue-50);color:var(--blue-700);
padding:var(--space-2) var(--space-8);border-radius:var(--radius-sm);
font-family:var(--font-mono);font-size:10px;margin:1px}
.gen-tag.rec{background:var(--amber-100);color:var(--amber-800)}
.subvalue{font-size:12px;color:var(--text-tertiary);margin-top:var(--space-4)}
code{font-family:var(--font-mono);font-size:0.92em;background:var(--surface-sunken);
padding:1px var(--space-4);border-radius:var(--radius-sm)}
.fleet-table{font-size:11px}
.fleet-table th{font-size:10px;padding:var(--space-4) var(--space-8);position:sticky;top:0;
background:var(--surface-sunken);z-index:1;cursor:pointer}
.fleet-table th:hover,table.sortable th:hover{background:var(--gray-250)}
table.sortable th{cursor:pointer}
table.sortable th::after{content:'';display:inline-block;width:0;height:0;margin-left:var(--space-4);
border-left:3px solid transparent;border-right:3px solid transparent;
border-top:4px solid var(--gray-400);vertical-align:middle}
.fleet-table td{padding:var(--space-4) var(--space-8);font-size:11px}
.fleet-wrapper{max-height:500px;overflow-y:auto;border:1px solid var(--border-subtle);
border-radius:var(--radius-sm)}
ol.next-steps{list-style:none;counter-reset:steps;padding:0}
ol.next-steps li{counter-increment:steps;padding:var(--space-12) 0 var(--space-12) var(--space-40);
position:relative;border-bottom:1px solid var(--border-subtle);font-size:14px}
ol.next-steps li::before{content:counter(steps);position:absolute;left:0;top:var(--space-12);
width:22px;height:22px;background:var(--accent-amber);color:var(--gray-850);
border-radius:50%;display:flex;align-items:center;justify-content:center;
font-family:var(--font-mono);font-size:11px;font-weight:700}
.meta-row{display:flex;flex-wrap:wrap;gap:var(--space-16);margin-top:var(--space-12);
font-family:var(--font-mono);font-size:10px;text-transform:uppercase;
letter-spacing:0.06em;color:var(--gray-500)}
input[type=range]{accent-color:var(--accent-amber)}
/* Processor coverage bar — gradient segments, hairline frame, labels that
   disappear rather than overflow when a segment is too narrow. */
.proc-bar{display:flex;height:40px;border-radius:var(--radius-sm);overflow:hidden;
margin-bottom:var(--space-8);box-shadow:var(--hairline)}
.proc-bar>div{display:flex;align-items:center;justify-content:center;
min-width:0;overflow:hidden}
.proc-bar span{font-family:var(--font-mono);font-size:10px;text-transform:uppercase;
letter-spacing:0.05em;color:var(--white);white-space:nowrap;padding:0 var(--space-4)}
/* Legend names every processor regardless of slice width, so figures for thin
   slices stay readable instead of being clipped inside the bar. */
.proc-legend{display:flex;flex-wrap:wrap;gap:var(--space-16);
margin-bottom:var(--space-12);font-family:var(--font-mono);font-size:10px;
text-transform:uppercase;letter-spacing:0.05em;color:var(--text-secondary)}
.proc-legend span{display:inline-flex;align-items:center;gap:var(--space-4);
white-space:nowrap}
.proc-legend i{width:8px;height:8px;border-radius:var(--radius-sm);
box-shadow:var(--hairline);flex:none}
@media print {
    body { background: var(--white) !important; }
    header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    section, .kpi, .wave-card { box-shadow: none !important; break-inside: avoid;
        border: 1px solid var(--border-subtle); }
    .fleet-wrapper { max-height: none !important; overflow: visible !important; }
    .container { max-width: 100%; }
}
</style>"""


# Static tail of the report script. The data constants it reads (PERF_ROWS,
# PERF_BASELINE, TOTAL_MONTHLY_COST, GEN_AVAILABLE, GEN_FALLBACK_COUNT,
# GEN_LABELS, GEN_DESC, OPEN_GEN, ANNUAL_FACTOR) are emitted by the template
# immediately above this, so this block stays free of interpolation.
# Column sorting for any table marked class="sortable". Static, so it carries no
# interpolation and lives outside the template's f-string like the other assets.
_SORT_JS = """\
document.querySelectorAll('table.sortable th').forEach(th => {
  th.addEventListener('click', function() {
    const table = th.closest('table');
    const idx = Array.from(th.parentNode.children).indexOf(th);
    const rows = Array.from(table.querySelectorAll('tr')).slice(1);
    // Separate total row (last row with bold)
    const totalRow = rows[rows.length-1];
    const isTotal = totalRow && totalRow.style.fontWeight === 'bold';
    const dataRows = isTotal ? rows.slice(0, -1) : rows;
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
    th.dataset.dir = dir;
    dataRows.sort((a, b) => {
      let av = a.children[idx] ? a.children[idx].textContent.trim() : '';
      let bv = b.children[idx] ? b.children[idx].textContent.trim() : '';
      // Parse as number if starts with $ or is numeric
      const an = parseFloat(av.replace(/[$,]/g, ''));
      const bn = parseFloat(bv.replace(/[$,]/g, ''));
      if (!isNaN(an) && !isNaN(bn)) {
        return dir === 'asc' ? an - bn : bn - an;
      }
      return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    const tbody = table.querySelector('tbody') || table;
    dataRows.forEach(r => tbody.appendChild(r));
    if (isTotal) tbody.appendChild(totalRow);
  });
});"""


_REPORT_JS = """\
(function() {
  const slider = document.getElementById('perf-slider');
  const input = document.getElementById('perf-input');
  if (!slider || !input) return;

  // Per-row resolution for a selected generation. Returns the target rate and
  // the hop count that goes with it, or null when the row cannot reach it.
  // Rows carry commitment-matched savings AMOUNTS, not rates: r.sav for the
  // default next-gen target and r.g2..r.g5 per generation. The server already
  // applied the cost basis, so this resolves an amount and its hop count and
  // never re-derives savings from rates.
  function resolveGen(r, gen) {
    // r.sav is the figure for the generation the report opened on; r.nx is the
    // next-gen figure when that opening generation was not next-gen.
    const openGen = (typeof OPEN_GEN !== 'undefined') ? OPEN_GEN : 'nextgen';
    if (gen === 'nextgen') {
      if (r.nx !== undefined) return {sav: r.nx, hops: r.nxh || 0};
      return {sav: r.sav, hops: r.h || 0};
    }
    if (gen === openGen) return {sav: r.sav, hops: r.h || 0};
    if (gen === 'newest') {
      for (const g of GEN_DESC) {
        if (r[g] !== undefined) {
          return {sav: r[g], hops: (r[g + 'h'] !== undefined) ? r[g + 'h'] : (r.h || 0)};
        }
      }
      return null;
    }
    if (r[gen] !== undefined) {
      return {sav: r[gen], hops: (r[gen + 'h'] !== undefined) ? r[gen + 'h'] : (r.h || 0)};
    }
    return null;
  }

  const fmt = n => {
    const a = Math.abs(n);
    if (a >= 1e6) return '$' + (n/1e6).toFixed(2) + 'M';
    if (a >= 1e3) return '$' + Math.round(n/1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  };

  // Annotate each radio with how many priced rows can actually reach it, and
  // disable generations no row can reach so the option can't silently no-op.
  document.querySelectorAll('.gen-avail').forEach(el => {
    const g = el.dataset.gen;
    const n = GEN_AVAILABLE[g] || 0;
    const total = PERF_ROWS.length;
    if (n === 0) {
      el.textContent = '— not available in this fleet/region';
      const radio = document.querySelector('input[name="gen-select"][value="' + g + '"]');
      if (radio) { radio.disabled = true; radio.parentElement.style.opacity = '0.5'; }
    } else if (n < total) {
      el.textContent = '— ' + n + ' of ' + total + ' types';
    } else {
      el.textContent = '— all ' + total + ' types';
    }
  });

  function selectedGen() {
    const checked = document.querySelector('input[name="gen-select"]:checked');
    return checked ? checked.value : 'nextgen';
  }

  function recompute() {
    let pct = parseFloat(input.value);
    if (isNaN(pct)) pct = 0;
    pct = Math.max(0, Math.min(40, pct));
    const p = pct / 100;
    const gen = selectedGen();

    // Base savings: on-demand rate delta at the requested generation's target.
    // A row with no priced target there keeps its next-gen target and is counted
    // as a fallback, so switching generations never silently drops spend.
    //
    // compound=false is the FLAT model: the rate is applied once regardless of
    // how many generations an instance advances, matching the Graviton Savings
    // Dashboard's EC2EfficiencyGain. This drives the headline.
    //
    // compound=true applies it PER GENERATION HOP, divisively: "p% faster per
    // step" means the work fits in 1/(1+p) of the hours per hop, not (1-p), so
    // c5 -> c9g (4 hops) needs (1+p)^-4 of the normalized instance-hours. Over
    // 4 hops at 10% that is 1/1.1^4 = 0.683, a 31.7% reduction. Only the
    // latest-generation comparison uses this.
    function scenario(genKey, compound) {
      let base = 0, gravCost = 0, additional = 0, fellBack = 0, hopWeighted = 0;
      for (const r of PERF_ROWS) {
        let sav = r.sav;
        let hops = r.h || 0;
        const resolved = resolveGen(r, genKey);
        if (resolved) {
          sav = resolved.sav;
          hops = resolved.hops;
        } else {
          // Cannot reach the requested generation: keep the default next-gen
          // figure and count it, so switching never silently drops spend.
          fellBack++;
        }
        // Projected Graviton cost is what remains after the saving. Deriving it
        // this way rather than from rates is what makes the 0% position equal
        // the server-side total exactly.
        const gravitonCost = r.cost - sav;
        gravCost += gravitonCost;
        base += sav;
        additional += compound
          ? gravitonCost * (1 - Math.pow(1 + p, -hops))
          : gravitonCost * p;
        hopWeighted += gravitonCost * hops;
      }
      return {
        base: base,
        additional: additional,
        total: base + additional,
        gravCost: gravCost,
        fellBack: fellBack,
        meanHops: gravCost > 0 ? hopWeighted / gravCost : 0,
      };
    }

    // Headline: selected generation, flat rate applied once.
    const sel = scenario(gen, false);
    // Comparison: every row retargeted to its newest available Graviton, rate
    // compounded per hop. Deliberately excluded from the headline.
    const latest = scenario('newest', true);

    const baseSavings = sel.base;
    const additional = sel.additional;
    const total = sel.total;
    const fellBack = sel.fellBack;

    document.getElementById('pp-base').textContent = fmt(baseSavings);
    document.getElementById('pp-additional').textContent = fmt(additional);
    document.getElementById('pp-latest').textContent = fmt(latest.total);
    // Name what the comparison assumes, and how much of it is the compounding
    // rather than the retargeting, so the gap to the headline is attributable.
    const latestNote = document.getElementById('pp-latest-note');
    if (latestNote) {
      const effPctLatest = latest.gravCost > 0
        ? (latest.additional / latest.gravCost * 100) : 0;
      latestNote.textContent = pct > 0
        ? pct.toFixed(0) + '%/hop compounded · ' + effPctLatest.toFixed(1) +
          '% effective over ' + latest.meanHops.toFixed(1) + ' avg hops'
        : 'price-only at latest-gen targets';
    }
    // Drive the headline KPIs from the same computation. Without this the top
    // of the report kept its render-time value while the panel below moved,
    // presenting two different "total savings" figures for one fleet.
    const kpiM = document.getElementById('kpi-monthly-savings');
    const kpiA = document.getElementById('kpi-annual-savings');
    const kpiP = document.getElementById('kpi-savings-pct');
    if (kpiM) kpiM.textContent = fmt(total);
    if (kpiA) kpiA.textContent = fmt(total * ((typeof ANNUAL_FACTOR !== 'undefined') ? ANNUAL_FACTOR : 12));
    if (kpiP && TOTAL_MONTHLY_COST > 0) {
      // Name the basis. This figure now moves with the slider, so a bare
      // "% of total spend" would leave a reader unable to tell which NIH
      // assumption produced it — and the markdown report's equivalent line is
      // price-only, so the two would appear to disagree for no stated reason.
      const pctOfSpend = (total / TOTAL_MONTHLY_COST * 100).toFixed(1);
      kpiP.textContent = pct > 0
        ? pctOfSpend + '% of spend · incl. ' + pct.toFixed(0) + '% NIH reduction'
        : pctOfSpend + '% of spend · price-only';
    }
    document.getElementById('pp-gen-label').textContent = GEN_LABELS[gen] || gen;
    // The headline rate is flat, so the effective reduction equals the slider
    // value by construction — say so plainly rather than restating it, and make
    // the contrast with the compounded comparison tile explicit.
    document.getElementById('pp-nih-label').textContent = pct.toFixed(0) + '% of Graviton cost';

    const note = document.getElementById('pp-fallback-note');
    if (note) {
      const parts = [];
      if (fellBack > 0) {
        parts.push(fellBack + ' type' + (fellBack === 1 ? '' : 's') +
          ' had no priced ' + (GEN_LABELS[gen] || gen) +
          ' target and kept the target the report opened on.');
      }
      if (GEN_FALLBACK_COUNT > 0) {
        parts.push(GEN_FALLBACK_COUNT + ' row(s) fell back to another generation ' +
          '(the nearest older one, else the nearest newer) because the requested ' +
          'one is not offered or priced in their region.');
      }
      note.textContent = parts.join(' ');
    }
  }

  slider.addEventListener('input', () => { input.value = slider.value; recompute(); });
  input.addEventListener('input', () => {
    let v = Math.max(0, Math.min(40, parseFloat(input.value) || 0));
    slider.value = v;
    recompute();
  });
  document.querySelectorAll('input[name="gen-select"]').forEach(radio => {
    radio.addEventListener('change', recompute);
  });
  recompute();
})();
</script>"""
