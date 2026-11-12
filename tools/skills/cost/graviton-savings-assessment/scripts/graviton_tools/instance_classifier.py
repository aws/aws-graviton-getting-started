# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""
Algorithmic AWS instance classifier with multi-generation Graviton targets.

Parses any instance type string (EC2, RDS, ElastiCache, OpenSearch) into structured
components and generates upgrade candidates (Graviton2/3/4/5 + Intel) dynamically.

Design:
  - Algorithm-first: suffix pattern extraction handles most families automatically.
  - Every generated Graviton family is checked against GRAVITON_FAMILIES, the list
    of families AWS actually sells. A variant letter with no Graviton counterpart
    (m6in -> m7gn) is dropped rather than emitted as a type that does not exist.
  - Static overrides: the irregular families (x, i, hpc, a1, g5g, OpenSearch-only)
    that don't follow standard {family}{gen}{suffix}.{size} naming.
  - Downstream validation: the existence oracle in fleet_tools checks each target
    against the offerings API for the row's own region.
"""
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Optional, Dict

# ── Instance families by category ───────────────────────────────────────────────────────────────
GENERAL_PURPOSE = {"m", "mac", "a", "t"}
COMPUTE_OPT = {"c", "hpc"}
MEMORY_OPT = {"r", "x", "z", "u"}
STORAGE_OPT = {"d", "h", "i", "im", "is"}
ACCEL_COMPUTE = {"p", "dl", "trn", "inf", "g", "vt", "f"}

# ── The families AWS actually sells ────────────────────────────────────────
# Source: the current- and previous-generation lists at
#   https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-types.html
# Last reviewed: 2026-11-04. When AWS launches a family, add it here; until then
# a target that would need it falls back to the nearest real family below.
#
# Graviton EC2 families. "x2g" is the RDS-only name for the X2g class
# (db.x2g.*); EC2 sells the same hardware as x2gd.
GRAVITON_FAMILIES = frozenset({
    "a1",
    "c6g", "c6gd", "c6gn", "c7g", "c7gd", "c7gn",
    "c8g", "c8gb", "c8gd", "c8gn", "c9g", "c9gd",
    "m6g", "m6gd", "m7g", "m7gd",
    "m8g", "m8gb", "m8gd", "m8gn", "m9g", "m9gd",
    "r6g", "r6gd", "r7g", "r7gd",
    "r8g", "r8gb", "r8gd", "r8gn", "r9g", "r9gd",
    "t4g", "x2gd", "x2g", "x8g",
    "i4g", "i8g", "i8ge", "im4gn", "is4gen",
    "g5g", "hpc7g",
})

# x86 families that have a Graviton counterpart, used to validate the Intel
# equivalent a Graviton row is compared against for realized savings (c8gn must
# not be compared against a c7in, which does not exist). Same source and date.
X86_FAMILIES = frozenset({
    "c5", "c5a", "c5ad", "c5d", "c5n", "c6a", "c6i", "c6id", "c6in",
    "c7a", "c7i", "c8a", "c8i", "c8id", "c8in", "c8ine", "c8ib",
    "m5", "m5a", "m5ad", "m5d", "m5dn", "m5n", "m5zn", "m6a", "m6i", "m6id",
    "m6idn", "m6in", "m7a", "m7i", "m8a", "m8azn", "m8i", "m8id", "m8in",
    "m8idn", "m8ine", "m8ib", "m8idb",
    "r5", "r5a", "r5ad", "r5b", "r5d", "r5dn", "r5n", "r6a", "r6i", "r6id",
    "r6idn", "r6in", "r7a", "r7i", "r7iz", "r8a", "r8i", "r8id", "r8in",
    "r8idn", "r8ib", "r8idb",
    "t2", "t3", "t3a", "t8i",
    "x1", "x1e", "x2idn", "x2iedn", "x2iezn", "x8i", "x8aedz",
    "i3", "i3en", "i4i", "i7i", "i7ie",
    "hpc6a", "hpc6id", "hpc7a", "hpc8a", "g4dn",
})

# When a variant letter has no Graviton counterpart in a generation, the letters
# are dropped in this order: keep local NVMe ("d") longest because losing it is
# a functional change (instance store disappears); then network ("n"); then EBS
# bandwidth ("b"). Letters not listed ("e", "z") have no Graviton analogue.
_OPTION_WEIGHT = {"d": 4, "n": 2, "b": 1}


def _real_family(fmt: str, base_options: str, allowed: frozenset) -> Optional[str]:
    """First real family for `fmt.format(opts)`, dropping variant letters as needed.

    Tries every subset of `base_options` (order kept) from most to least
    valuable, so m6idn -> m8gdn (not sold) -> m8gd (sold).
    """
    letters = list(dict.fromkeys(base_options))
    subsets = []
    for n in range(len(letters), -1, -1):
        for combo in combinations(letters, n):
            subsets.append("".join(combo))
    subsets.sort(key=lambda s: (-sum(_OPTION_WEIGHT.get(c, 0) for c in s), -len(s)))
    for opts in subsets:
        candidate = fmt.format(opts)
        if candidate in allowed:
            return candidate
    return None


# ── Static overrides for irregular families ────────────────────────────────
# These don't follow the standard algorithmic pattern.
# Format: family -> (generation_label, processor, previous_intel, latest_arm, g2, g3, g4)
# Values are base families WITHOUT service prefix (db./cache.) or suffix (.search).
# The algorithm applies prefix/suffix when building full instance type strings.
STATIC_OVERRIDES: Dict[str, tuple] = {
    # Legacy memory (non-standard generation numbering). x1 and x2idn carry
    # 16 GiB per vCPU like x2gd/x8g, so they map size for size. x1e, x2iedn,
    # x2iezn and x8aedz carry 32 GiB per vCPU: see MEMORY_SIZED_FAMILIES.
    "x1":     ("",          "Intel",    "",     "x2gd",  "x2gd", "",    "x8g"),
    "x1e":    ("",          "Intel",    "",     "x2gd",  "x2gd", "",    "x8g"),
    "x2gd":   ("Graviton2", "Graviton", "x1",  "x8g",   "x2gd", "",    "x8g"),
    "x2idn":  ("",          "Intel",    "",     "x8g",   "x2gd", "",    "x8g"),
    "x2iedn": ("",          "Intel",    "",     "x8g",   "x2gd", "",    "x8g"),
    "x2iezn": ("",          "Intel",    "",     "x8g",   "x2gd", "",    "x8g"),
    "x8i":    ("",          "Intel",    "",     "x8g",   "x2gd", "",    "x8g"),
    "x8aedz": ("",          "AMD",      "",     "x8g",   "x2gd", "",    "x8g"),
    "x8g":    ("Graviton4", "Graviton", "x2idn","x8g",   "x2gd", "",    "x8g"),
    # Storage-optimized (different family names for Graviton). I4g is
    # Graviton2. i3en and i7ie are the dense-storage families (2,500 GB per
    # xlarge); their like-for-like target is i8ge, not the 937 GB i8g/i4g.
    "i2":     ("",          "Intel",    "",     "i4g",   "i4g",  "",    "i8g"),
    "i3":     ("",          "Intel",    "",     "i4g",   "i4g",  "",    "i8g"),
    "i3en":   ("",          "Intel",    "",     "i8ge",  "",     "",    "i8ge"),
    "i4g":    ("Graviton2", "Graviton", "i3",   "i8g",   "i4g",  "",    "i8g"),
    "i4i":    ("",          "Intel",    "",     "i4g",   "i4g",  "",    "i8g"),
    "i7i":    ("",          "Intel",    "",     "i8g",   "i4g",  "",    "i8g"),
    "i7ie":   ("",          "Intel",    "",     "i8ge",  "",     "",    "i8ge"),
    "i8g":    ("Graviton4", "Graviton", "i7i",  "i8g",   "i4g",  "",    "i8g"),
    "i8ge":   ("Graviton4", "Graviton", "i7ie", "i8ge",  "",     "",    "i8ge"),
    "im4gn":  ("Graviton2", "Graviton", "",     "im4gn", "im4gn","",    ""),
    "is4gen": ("Graviton2", "Graviton", "",     "is4gen","is4gen","",    ""),
    # OpenSearch-optimized families (.search only): OR1/OR2/OM2/OI2 are
    # Graviton-based ARM64 with no x86 predecessor and no 'g'-suffix successor.
    # Without these, the algorithm misreads them as Intel (no 'g' in suffix) and
    # fabricates nonexistent upgrade targets (or6g/or7g/om6g/oi6g). latest_arm ==
    # key so no upgrade is emitted — they count as already-migrated.
    "or1":    ("Graviton",   "Graviton", "",     "or1",   "",     "",    ""),
    "or2":    ("Graviton",   "Graviton", "",     "or2",   "",     "",    ""),
    "om2":    ("Graviton",   "Graviton", "",     "om2",   "",     "",    ""),
    "oi2":    ("Graviton",   "Graviton", "",     "oi2",   "",     "",    ""),
    # First-gen Graviton
    "a1":     ("Graviton",  "Graviton", "",     "c6g",   "a1",   "",    ""),
    # GPU with Graviton (g5g is the only one)
    "g5g":    ("Graviton2", "Graviton", "g4dn", "g5g",   "g5g",  "",    ""),
    # HPC (Graviton starts at gen 7, not gen 6). hpc7g comes only in 4xlarge,
    # 8xlarge and 16xlarge; the existence oracle walks larger sources down.
    "hpc6a":  ("",          "AMD",      "",     "hpc7g", "",     "hpc7g",""),
    "hpc6id": ("",          "Intel",    "",     "hpc7g", "",     "hpc7g",""),
    "hpc7a":  ("",          "AMD",      "",     "hpc7g", "",     "hpc7g",""),
    "hpc8a":  ("",          "AMD",      "",     "hpc7g", "",     "hpc7g",""),
    "hpc7g":  ("Graviton3", "Graviton", "hpc6a","hpc7g", "",     "hpc7g",""),
    # Gen-5 network and EBS variants. Graviton drops the 'n' here because the
    # base Graviton families already match a gen-5 'n' type's bandwidth.
    "m5dn":   ("",          "Intel",    "",     "m6gd",  "m6gd", "m7gd","m8gd"),
    "m5n":    ("",          "Intel",    "",     "m6g",   "m6g",  "m7g", "m8g"),
    "r5dn":   ("",          "Intel",    "",     "r6gd",  "r6gd", "r7gd","r8gd"),
    "r5n":    ("",          "Intel",    "",     "r6g",   "r6g",  "r7g", "r8g"),
    "r5b":    ("",          "Intel",    "",     "r7g",   "r6g",  "r7g", "r8g"),
    "m5zn":   ("",          "Intel",    "",     "m7g",   "m6g",  "m7g", "m8g"),
    "c5n":    ("",          "Intel",    "",     "c6gn",  "c6gn", "c7gn","c8gn"),
}

# Families whose memory per vCPU is twice the Graviton target's (32 vs 16 GiB),
# per the memory-optimized spec tables at
# https://docs.aws.amazon.com/ec2/latest/instancetypes/mo.html (reviewed
# 2026-11-04): x1e.xlarge has 122 GiB, x2gd.xlarge and x8g.xlarge have 64 GiB.
# Their targets are sized by memory, one size up, so the comparison is between
# instances that can hold the same working set.
MEMORY_SIZED_FAMILIES = frozenset({"x1e", "x2iedn", "x2iezn", "x8aedz"})

# The next size up (twice the vCPUs and memory). 32xlarge has no 64xlarge to go
# to, so it goes to the largest ladder size and the oracle takes it from there.
_DOUBLE_SIZE = {
    "medium": "large", "large": "xlarge", "xlarge": "2xlarge",
    "2xlarge": "4xlarge", "3xlarge": "6xlarge", "4xlarge": "8xlarge",
    "6xlarge": "12xlarge", "8xlarge": "16xlarge", "12xlarge": "24xlarge",
    "16xlarge": "32xlarge", "24xlarge": "48xlarge", "32xlarge": "48xlarge",
}

# Families with NO Graviton equivalent at all
# Note: g5g (Graviton GPU) is handled via static override, so "g" stays blocked here
NO_GRAVITON = {"p", "dl", "trn", "inf", "vt", "f", "g", "d", "h", "z", "u", "mac",
               "cc", "cc1", "cc2", "cg1", "cr", "cr1"}

# ── Graviton5 (9g) launch lineup ───────────────────────────────────────────
# Derived from GRAVITON_FAMILIES rather than kept as a second list. Maps family
# -> set of base_options with a real 9g type: "" is the plain family (c9g) and
# "d" the NVMe variant (c9gd).
#
# Regional availability is NOT modelled here — 9g rolls out region by region.
# instance_offerings.py validates each target against the customer's own
# region, so listing a family here is safe as soon as it exists anywhere.
GRAVITON5_FAMILIES: Dict[str, set] = {}
for _fam in GRAVITON_FAMILIES:
    _m = re.fullmatch(r"([a-z]+)9g([a-z]*)", _fam)
    if _m:
        GRAVITON5_FAMILIES.setdefault(_m.group(1), set()).add(_m.group(2))

# Graviton generation label -> AWS generation number, shared with fleet_tools.
# t-family is offset (t4g=Graviton2), handled separately at the call site.
GRAVITON_GEN_NUM = {
    "Graviton2": 6,
    "Graviton3": 7,
    "Graviton4": 8,
    "Graviton5": 9,
}

_OPENSEARCH_SUFFIX = ".search"


@dataclass
class InstanceInfo:
    """Parsed instance type components."""
    raw: str
    service: str            # ec2, rds, elasticache, opensearch
    prefix: str             # "", "db.", "cache."
    family: str             # m, c, r, t, i, ...
    generation: int         # 3,4,5,6,7,8
    suffix: str             # "", "i", "a", "g", "gd", "id", "ad", "n", "d"
    size: str               # nano, micro, small, medium, large, xlarge, ...
    is_graviton: bool = False
    is_amd: bool = False
    is_intel: bool = False
    category: str = ""      # general, compute, memory, storage, accelerated
    gen_label: str = ""     # "Gen 5 Intel", "Graviton3", etc.
    # "flex" for m7i-flex.xlarge. Kept out of `size`, which once read
    # "xlarge-flex" and broke every target string and size lookup built from it.
    variant: str = ""
    # ".search" for OpenSearch types, kept out of `size` for the same reason.
    # Every full type string built from prefix + family + size appends it.
    type_suffix: str = ""
    # The size Graviton targets are built at. Equal to `size` except for the
    # memory-dense families in MEMORY_SIZED_FAMILIES.
    target_size: str = ""
    size_basis: str = ""    # "memory" when target_size was chosen by memory
    # Multi-generation Graviton targets (base family only, e.g. "c6g")
    graviton2: Optional[str] = None
    graviton3: Optional[str] = None
    graviton4: Optional[str] = None
    # Graviton5 (9g). Only populated for families with a real 9g type.
    graviton5: Optional[str] = None
    # Best recommended upgrade (full instance type string with prefix + size)
    graviton_upgrade: Optional[str] = None
    intel_upgrade: Optional[str] = None
    previous_intel: Optional[str] = None


# ── Regex for instance type parsing ────────────────────────────────────────
# Handles: m5.xlarge, db.r7g.2xlarge, cache.r6g.large, c5d.9xlarge, t4g.nano
# Also handles OpenSearch: c5.xlarge.search (type_suffix = ".search")
# Also handles flex variants: m7i-flex.xlarge (variant = "flex")
_INST_RE = re.compile(
    r"^(?P<prefix>db\.|cache\.)?"
    r"(?P<family>[a-z]+)"
    r"(?P<gen>\d+)"
    r"(?P<suffix>[a-z]*)"
    r"(?P<variant>-[a-z]+)?"
    r"\."
    r"(?P<size>.+)$",
    re.IGNORECASE,
)


def service_for_type(instance_type: str) -> str:
    """The service an instance type string belongs to, from its shape.

    The one place this is decided. It used to be open-coded in about eight
    places that disagreed (".search" vs "search." vs "ultrawarm").
    """
    t = (instance_type or "").strip().lower()
    if t.startswith("db."):
        return "rds"
    if t.startswith("cache."):
        return "elasticache"
    if t.endswith(_OPENSEARCH_SUFFIX):
        return "opensearch"
    return "ec2"


def full_type(prefix: str, family: str, size: str, type_suffix: str = "") -> str:
    """Full instance type string: db.r8g.xlarge, m8g.large.search, c8g.xlarge."""
    return f"{prefix}{family}.{size}{type_suffix}"


def _extract_base_options(suffix: str) -> str:
    """Strip processor indicators (a, i, g) from suffix, keep variant options (d, n, b, e).

    This is the key insight from the CID dynamic mapping SQL:
    base_options = REGEXP_REPLACE(suffix, '[aig]', '')

    Examples:
        "gd"  -> "d"   (NVMe variant)
        "gn"  -> "n"   (network variant)
        "id"  -> "d"   (NVMe variant)
        "ad"  -> "d"   (NVMe variant)
        "i"   -> ""    (plain Intel)
        "g"   -> ""    (plain Graviton)
        "a"   -> ""    (plain AMD)
        ""    -> ""    (no suffix)
        "gdn" -> "dn"  (NVMe + network)
        "b"   -> "b"   (memory-optimized variant, e.g. r5b)
    """
    return re.sub(r"[aig]", "", suffix)


def _build_type(prefix: str, family: str, gen: int, suffix: str, size: str) -> str:
    """Build a full instance type string."""
    return f"{prefix}{family}{gen}{suffix}.{size}"


def _build_graviton_family(base_type: str, gen: int, base_options: str) -> str:
    """Build a Graviton family string (no prefix, no size).

    Examples: _build_graviton_family("c", 6, "") -> "c6g"
              _build_graviton_family("m", 6, "d") -> "m6gd"
              _build_graviton_family("c", 7, "n") -> "c7gn"
    """
    return f"{base_type}{gen}g{base_options}"


def parse(instance_type: str, service: str = "ec2") -> Optional[InstanceInfo]:
    """Parse an instance type string into InstanceInfo."""
    if not instance_type or instance_type in ("unknown", "N/A", ""):
        return None

    raw = instance_type.strip().lower()
    m = _INST_RE.match(raw)
    if not m:
        return None

    prefix = m.group("prefix") or ""
    family = m.group("family")
    gen = int(m.group("gen"))
    suffix = m.group("suffix") or ""
    variant = (m.group("variant") or "").lstrip("-")  # e.g. "flex"
    size = m.group("size")

    type_suffix = ""
    if size.endswith(_OPENSEARCH_SUFFIX):
        size = size[: -len(_OPENSEARCH_SUFFIX)]
        type_suffix = _OPENSEARCH_SUFFIX
        service = "opensearch"

    # Processor detection from suffix
    is_graviton = "g" in suffix
    is_amd = "a" in suffix and "g" not in suffix
    is_intel = not is_graviton and not is_amd

    # Category
    if family in GENERAL_PURPOSE:
        cat = "general"
    elif family in COMPUTE_OPT:
        cat = "compute"
    elif family in MEMORY_OPT:
        cat = "memory"
    elif family in STORAGE_OPT:
        cat = "storage"
    elif family in ACCEL_COMPUTE:
        cat = "accelerated"
    else:
        cat = "other"

    # Generation label
    proc = "Graviton" if is_graviton else ("AMD" if is_amd else "Intel")
    gen_label = f"Gen {gen} {proc}"

    return InstanceInfo(
        raw=raw, service=service, prefix=prefix, family=family,
        generation=gen, suffix=suffix, size=size,
        is_graviton=is_graviton, is_amd=is_amd, is_intel=is_intel,
        category=cat, gen_label=gen_label,
        variant=variant, type_suffix=type_suffix, target_size=size,
    )


def _service_family(prefix: str, family: str) -> str:
    """The family name as the row's service sells it (db.x2g, not db.x2gd)."""
    if prefix == "db." and family == "x2gd":
        return "x2g"
    return family


def _resolve_static_override(info: InstanceInfo) -> bool:
    """Check static overrides and populate fields if matched. Returns True if matched."""
    key = info.family + str(info.generation) + info.suffix
    override = STATIC_OVERRIDES.get(key)
    if not override:
        return False

    gen_label, processor, prev_intel, latest_arm, g2, g3, g4 = override

    # Update processor detection from override
    if processor == "Graviton":
        info.is_graviton = True
        info.is_amd = False
        info.is_intel = False
    elif processor == "AMD":
        info.is_amd = True
        info.is_graviton = False
        info.is_intel = False
    elif processor == "Intel":
        info.is_intel = True
        info.is_graviton = False
        info.is_amd = False

    if gen_label:
        info.gen_label = gen_label

    if key in MEMORY_SIZED_FAMILIES:
        info.target_size = _DOUBLE_SIZE.get(info.size, info.size)
        info.size_basis = "memory"

    prefix = info.prefix

    # Populate Graviton generation targets (as base families)
    info.graviton2 = _service_family(prefix, g2) if g2 else None
    info.graviton3 = _service_family(prefix, g3) if g3 else None
    info.graviton4 = _service_family(prefix, g4) if g4 else None
    info.previous_intel = prev_intel or None

    # Best Graviton upgrade = latest_arm at the target size
    if latest_arm and (not info.is_graviton or latest_arm != key):
        info.graviton_upgrade = full_type(
            prefix, _service_family(prefix, latest_arm), info.target_size,
            info.type_suffix)

    return True


def generate_upgrades(info: InstanceInfo) -> InstanceInfo:
    """Populate upgrade targets on an InstanceInfo.

    Strategy:
      1. Check static overrides for irregular families
      2. If not overridden, use algorithmic generation based on base_options pattern
      3. Generate g2/g3/g4/g5 candidates + best graviton_upgrade + intel_upgrade
    """
    if info is None:
        return info

    # ── Step 1: Static overrides ────────────────────────────────────────
    if _resolve_static_override(info):
        return info

    family = info.family
    gen = info.generation
    size = info.size
    prefix = info.prefix
    suffix = info.suffix
    base_options = _extract_base_options(suffix)

    # ── Step 2: No-Graviton families ────────────────────────────────────
    if family in NO_GRAVITON:
        return info

    # ── Step 3: Algorithmic Graviton targets ────────────────────────────
    # t-family is Graviton-capped: t4g (Graviton2) is the ONLY Graviton burstable
    # instance. There is no t5g/t6g/t7g — emitting g3/g4 columns for them
    # fabricated nonexistent types. So t stops at Graviton2; g3/g4 stay None.
    if family == "t":
        gens = {"graviton2": 4}
    else:
        gens = {"graviton2": 6, "graviton3": 7, "graviton4": 8, "graviton5": 9}

    # Each generation resolves to a family AWS actually sells, dropping variant
    # letters that have no Graviton counterpart in that generation (m6in ->
    # m6g, m7g, m8gn, m9g). A generation with no real family stays None.
    for field, g in gens.items():
        setattr(info, field, _real_family(
            f"{family}{g}g{{}}", base_options, GRAVITON_FAMILIES))

    # ── Step 4: Best Graviton upgrade (latest_arm) ──────────────────────
    by_gen = [info.graviton2, info.graviton3, info.graviton4, info.graviton5]
    if not info.is_graviton:
        # Non-Graviton: the next generation after the source's own.
        if family == "t" or gen <= 5:
            want = 0
        elif gen == 6:
            want = 1
        elif gen == 7:
            want = 2
        else:
            want = 3          # gen 8+ x86 -> Graviton5 where it exists
        # The wanted generation first, then newer, then older — a gen-8 family
        # with no 9g type lands on Graviton4 rather than on no target.
        order = [want] + list(range(want + 1, 4)) + list(range(want - 1, -1, -1))
        target_family = next((by_gen[i] for i in order if by_gen[i]), None)
        if target_family:
            info.graviton_upgrade = full_type(
                prefix, target_family, size, info.type_suffix)
    else:
        # Already Graviton: recommend the next Graviton generation, if one is sold.
        if family != "t":
            nxt = {6: info.graviton3, 7: info.graviton4, 8: info.graviton5}.get(gen)
            if nxt and nxt != f"{family}{gen}{suffix}":
                info.graviton_upgrade = full_type(prefix, nxt, size, info.type_suffix)
            # gen 9 = latest, no upgrade

    # ── Step 5: Intel upgrade path ──────────────────────────────────────
    if not info.is_graviton and not info.is_amd and family != "t":
        if gen < 6:
            intel_suffix = "i" + base_options
            info.intel_upgrade = _build_type(prefix, family, 6, intel_suffix, size)
        elif gen < 7:
            intel_suffix = "i" + base_options
            info.intel_upgrade = _build_type(prefix, family, 7, intel_suffix, size)

    # ── Step 6: Previous Intel ──────────────────────────────────────────
    # The x86 type a Graviton row is compared against for realized savings,
    # validated against X86_FAMILIES: c8gn has no c7in to compare against, so
    # it uses c7i.
    if info.is_graviton and not info.previous_intel:
        if family == "t":
            info.previous_intel = "t3"
        elif gen == 6:
            info.previous_intel = _real_family(f"{family}5{{}}", base_options, X86_FAMILIES)
        elif gen == 7:
            info.previous_intel = _real_family(f"{family}6i{{}}", base_options, X86_FAMILIES)
        elif gen == 8:
            info.previous_intel = _real_family(f"{family}7i{{}}", base_options, X86_FAMILIES)

    return info


def classify_and_upgrade(instance_type: str, service: str = "ec2") -> Optional[InstanceInfo]:
    """One-call: parse + generate upgrades."""
    info = parse(instance_type, service)
    if info:
        generate_upgrades(info)
    return info


# ── Batch helpers ──────────────────────────────────────────────────────────

def classify_usage_type(usage_type: str) -> Optional[InstanceInfo]:
    """Extract instance type from a Cost Explorer USAGE_TYPE string and classify it.

    Handles patterns like:
      USW2-BoxUsage:m5.xlarge
      USE1-InstanceUsage:db.r7g.2xlarge
      NodeUsage:cache.r6g.large
      USW2-SpotUsage:c5.9xlarge
    """
    if not usage_type:
        return None
    if ":" not in usage_type:
        return None
    inst_part = usage_type.split(":")[-1].strip()
    if not inst_part:
        return None

    return classify_and_upgrade(inst_part, service_for_type(inst_part))


def generation_bucket(gen: int, is_graviton: bool, is_other: bool = False) -> str:
    """Return a display bucket for generation grouping.

    For Graviton instances, maps instance family generation to Graviton processor generation:
      gen ≤6 → Graviton 2, gen 7 → Graviton 3, gen 8 → Graviton 4, gen ≥9 → Graviton 5.
    """
    if is_other:
        return f"Gen {gen} Other"
    if is_graviton:
        if gen <= 6:
            return "Graviton 2"
        elif gen == 7:
            return "Graviton 3"
        elif gen == 8:
            return "Graviton 4"
        else:
            return "Graviton 5"
    if gen <= 4:
        return "Gen ≤4 (Legacy)"
    elif gen == 5:
        return "Gen 5"
    elif gen == 6:
        return "Gen 6"
    else:
        return f"Gen {gen}+"
