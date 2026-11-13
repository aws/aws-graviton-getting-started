# Graviton Savings Assessment Skill

An agent skill that assesses AWS compute fleets for AWS Graviton (ARM64) migration opportunities. It classifies instance types across the four instance-based services it assesses (EC2, RDS, ElastiCache and OpenSearch; Graviton also runs Lambda, Fargate, EMR, MSK and more, which this skill does not cover), estimates cost savings using real AWS pricing, and produces shareable migration reports.

> **Note:** This is sample code, for non-production usage. You should work with your security and legal teams to meet your organizational security, regulatory and compliance requirements before deployment.

## How It Works

When activated, the skill:
1. Pulls fleet usage data from AWS Cost Explorer (last full month by default; every figure is a monthly average over the period)
2. Classifies every instance type by architecture, generation, and Graviton eligibility
3. Identifies upgrade targets (current-gen → next-gen Graviton) per instance, checked against the instance families AWS sells
4. Fetches real On-Demand, Reserved Instance and Savings Plans pricing; instance types that cannot be priced are excluded from the savings, never estimated into them
5. Optionally queries engine versions (RDS, ElastiCache, OpenSearch) for readiness checks
6. Generates a scored assessment with phased migration plan and detailed reports

Savings are estimates: amortized spend (usage charges only, before credits,
refunds and other billing adjustments), compared with public Graviton rates at
the same purchase terms where a matching rate exists. stdout and the Markdown
report are price-only, assuming a same-size Graviton instance does the same
work. The HTML headline also applies an assumed 10% performance uplift by
default, the Graviton Savings Dashboard's default (`--nih-reduction 0` turns it
off). Validate the figures with workload benchmarks before quoting them.

The agent invokes a Python CLI under the hood — no user interaction with the CLI is required.

## Quick Start

Install the skill into your assistant's skills folder. See the
[Agent Skills catalogue](../../README.md#how-to-install) for every platform
(set `CATEGORY=cost` and `SKILL=graviton-savings-assessment`). For Claude Code:

```bash
(
  SKILL=graviton-savings-assessment
  SRC="tools/skills/cost/$SKILL"
  DEST=~/.claude/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

Then install the Python dependency through the interpreter that will run the skill:

```bash
cd ~/.claude/skills/graviton-savings-assessment/scripts/
python3 -m pip install -r requirements.txt   # Windows: py -3 -m pip install -r requirements.txt
```

Use `<python> -m pip`, not a bare `pip`: on a machine with several Pythons, `pip` often
installs into a different one. The skill's first step also checks this and tells the agent
how to fix it.

If pip refuses with `externally-managed-environment` (PEP 668: recent Homebrew and Linux
distribution Pythons), use a virtual environment and run the skill with its Python:

```bash
python3 -m venv ~/.venvs/graviton-assessment
~/.venvs/graviton-assessment/bin/python -m pip install -r requirements.txt   # Windows: ~\.venvs\graviton-assessment\Scripts\python.exe
```

Sign in with temporary AWS credentials (`aws sso login`, or an `AWS_PROFILE` that assumes a
read-only role with the [permissions below](#iam-permissions-required)), then ask your AI assistant:

> Estimate my Graviton savings

## Skill Files

[summaries.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/cost/graviton-savings-assessment/summaries.md) is the canonical index of every file in this skill, with its
purpose and when it is read. Start at [SKILL.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/cost/graviton-savings-assessment/SKILL.md): it routes to everything else at
the step that needs it.

## Compatibility

- **Operating systems:** macOS, Linux, Windows (anywhere Python 3.10+ and boto3 run)
- **AI assistants:** Any agent supporting the agentskills.io spec (Kiro, Claude Code, Cursor, Windsurf, Copilot, Gemini CLI, OpenAI Codex)
- **AWS regions:** Works with any account in the commercial AWS partition (`aws`); Cost Explorer data is global, pricing is resolved per-region based on the customer's fleet. AWS GovCloud (US) and the China regions are not supported: the Cost Explorer, Pricing and Savings Plans clients use the commercial `us-east-1` endpoints, so every request fails there
- **No MCP server required** — The skill runs a local Python script directly, no server process needed

## What It Produces

| Output | Description |
|--------|-------------|
| **Markdown report** | Full migration assessment: executive summary, service breakdown, top opportunities, migration waves, engine readiness, full fleet inventory |
| **HTML report** | Same content as markdown, rendered as a self-contained shareable page with collapsible sections |
| **JSON assessment** | Complete structured data — classified fleet, scoring, migration plan, engine readiness, pricing metadata. For programmatic consumption or custom reporting |
| **Validation CSV** | Flat file with one row per instance type — cost, pricing, savings by generation, purchase type breakdown. For spreadsheet analysis |
| **Compact JSON summary** | Key KPIs returned to the agent: total cost, Graviton %, estimated savings, pricing source, output paths |

## Prerequisites

- **Python 3.10+**
- **boto3** (the only external dependency)
- **Valid AWS credentials** with the permissions listed below

## Cost of Running

Cost Explorer API requests are billed at $0.01 each
([Cost Explorer pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/)),
to the account whose credentials run the assessment. A run makes about 24
requests (8 usage summary, 4 reservation coverage, 4 reservation utilization,
4 Savings Plans, 4 Spot), plus one per extra page of results on large fleets,
so it typically costs $0.25–$1. The Pricing, Savings Plans and describe APIs
it also calls are free.

## IAM Permissions Required

The skill performs exclusively **read-only** operations. Required actions:

| Action | Purpose |
|--------|---------|
| `ce:GetReservationCoverage` | Instance usage data from Cost Explorer |
| `ce:GetCostAndUsage` | Cost and usage metrics for fleet classification |
| `ce:GetReservationUtilization` | RI utilization for purchase-type attribution |
| `pricing:GetProducts` | On-Demand pricing for savings calculations |
| `savingsplans:DescribeSavingsPlansOfferingRates` | SP rates for SP-covered instances |
| `ce:GetSavingsPlansUtilizationDetails` | Finds EC2 Instance Savings Plans, whose spend stays on its family until the plan expires (every plan in the organization when run from the management account) |
| `savingsplans:DescribeSavingsPlans` | Fallback for the same check if the call above fails (lists only the caller's own plans; without either, the report says the check was not done) |
| `sts:GetCallerIdentity` | Credential verification (fail-fast) |

**Optional** (enables precise engine readiness checks and region-accurate targets):

| Action | Purpose |
|--------|---------|
| `ec2:DescribeInstanceTypeOfferings` | Verifies Graviton targets are actually offered in each region (one cached call per region). Without it, availability is inferred from whether a price is returned, which cannot distinguish "not launched here" from "pricing lookup failed" |
| `rds:DescribeOrderableDBInstanceOptions` | Verifies RDS Graviton instance classes actually exist for each engine/region, so string-built targets that AWS does not offer (e.g. `db.r7g.32xlarge`) are replaced with the nearest real size instead of shown as phantom targets |
| `rds:DescribeDBEngineVersions` | Lists engine versions so the orderable-class lookup can be pinned to the newest few majors instead of paging every version. Without it, the lookup still runs unpinned — same result, minutes slower on engines with many versions |
| `elasticache:DescribeReservedCacheNodesOfferings` | Same real-catalog validation for ElastiCache node types |
| `rds:DescribeDBInstances` | RDS engine versions |
| `elasticache:DescribeCacheClusters` | ElastiCache engine versions |
| `es:ListDomainNames` | OpenSearch domain enumeration |
| `es:DescribeDomains` | OpenSearch engine versions |

Without the optional permissions, engine readiness checks fall back to "verify_version" (manual verification needed).

### Minimum IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GravitonAssessmentReadOnly",
      "Effect": "Allow",
      "Action": [
        "ce:GetReservationCoverage",
        "ce:GetCostAndUsage",
        "ce:GetReservationUtilization",
        "pricing:GetProducts",
        "savingsplans:DescribeSavingsPlansOfferingRates",
        "savingsplans:DescribeSavingsPlans",
        "ce:GetSavingsPlansUtilizationDetails",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "OptionalEngineVersionLookup",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstanceTypeOfferings",
        "rds:DescribeOrderableDBInstanceOptions",
        "rds:DescribeDBEngineVersions",
        "elasticache:DescribeReservedCacheNodesOfferings",
        "rds:DescribeDBInstances",
        "elasticache:DescribeCacheClusters",
        "es:ListDomainNames",
        "es:DescribeDomains"
      ],
      "Resource": "*"
    }
  ]
}
```

> Cost Explorer, Pricing, and Savings Plans actions require `Resource: "*"` — they do not support resource-level permissions. This policy grants no write access to any AWS service.

## Security Posture

- **Read-only operations only** — No write, delete, or modify API calls exist in the source code
- **Fail-fast credential verification** — Validates credentials via STS before making any data calls
- **No raw stack traces exposed** — Errors are categorized and sanitized
- **One dependency** — `boto3`, the AWS SDK for Python, pinned in `scripts/requirements.txt`; everything else is the Python standard library

## Data Privacy

- **No telemetry or phone-home behavior** — No usage metrics, analytics, update checks, or registration calls
- **Local processing only** — All classification, scoring, and report generation happens on the machine running the skill
- **No outbound calls to non-AWS endpoints** — Network traffic limited to:
  - AWS Cost Explorer (`ce.us-east-1.amazonaws.com`)
  - AWS Price List Query API (`api.pricing.us-east-1.amazonaws.com`), and the public
    price-list files (`pricing.us-east-1.amazonaws.com`) for the bulk fallback
  - AWS Savings Plans (`savingsplans.amazonaws.com`)
  - AWS STS (the regional endpoint for your configured region,
    `sts.<region>.amazonaws.com`, with current boto3)
  - AWS EC2 (`DescribeInstanceTypeOfferings`, optional target validation)
  - AWS RDS, ElastiCache, OpenSearch APIs (optional engine lookups)
- **No credentials stored or logged** — Uses the existing credential chain; never writes, caches, or echoes credentials
- **No customer data retained between runs** — The local pricing cache contains only public AWS price-list data, and is kept in the user cache directory (`$XDG_CACHE_HOME/graviton-savings-assessment/`, by default `~/.cache/graviton-savings-assessment/`) rather than inside the skill folder

