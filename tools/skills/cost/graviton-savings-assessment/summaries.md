# Skill File Index

This file is the canonical inventory of the skill. Every file in the skill folder is listed below with its purpose and when to read it. Keep it in sync when adding, removing, or renaming files.

* "summaries.md": "This file. Canonical index of every file in the skill and when to read each one. Linked from SKILL.md; useful when entering mid-skill or needing the full file map."

* "SKILL.md": "Main entry point (Agent Skills format). Finding a working Python with boto3, verifying AWS credentials, scoping the run (payer-account consolidation, analysis period), running the assessment, presenting results with the mandatory caveats, single-instance classification, and gotchas (exit codes, pricing sources, run log location, spot savings basis). Read this first."

* "references/engine-compatibility.md": "Graviton readiness by database and cache engine (RDS MySQL/PostgreSQL/MariaDB, Aurora, ElastiCache Redis OSS/Valkey/Memcached, OpenSearch): minimum engine versions per Graviton family, with sources and review date. Read when the report flags an engine upgrade or the user asks whether their engine version supports Graviton."

* "references/blocked-instances.md": "Instance families and platforms with no Graviton migration path (for example GPU, Mac, Windows, SQL Server, commercial database engines) and why. Read when explaining excluded spend or a type the report marks as not eligible."

* "references/migration-waves.md": "Definitions of the four migration waves the report uses (scope, effort, timeline, required actions, examples). Read when presenting or explaining the phased migration plan."

* "references/error-codes.md": "Exit codes and the stderr messages the CLI prints, with the remediation for each. Read when assess.py exits non-zero and stderr is not enough."

* "scripts/assess.py": "CLI entry point with two subcommands: `assess` (full fleet assessment, writes the reports, the full JSON result and the run log to --output-dir, each name carrying the run's timestamp, and prints a JSON summary) and `classify` (single instance type, no AWS credentials needed). Run, do not read, during a normal assessment."

* "scripts/requirements.txt": "The only external dependency (boto3). Installed with `<python> -m pip install -r scripts/requirements.txt`."

* "scripts/graviton_tools/__init__.py": "Package marker for the assessment library."

* "scripts/graviton_tools/assessment_pipeline.py": "Orchestrates the assessment: Cost Explorer pulls, fleet rows per service, type, region and pricing coordinates, monthly normalisation, pricing resolution, savings, scoring, migration-wave planning, and engine readiness."

* "scripts/graviton_tools/fleet_tools.py": "Graviton target selection and validation per instance type and generation, regional price books, savings scoring, migration waves, and engine readiness."

* "scripts/graviton_tools/instance_classifier.py": "Parses instance type names into family, generation, processor, size, and Graviton2-5 equivalents, checked against the families AWS sells. Backs the `classify` subcommand."

* "scripts/graviton_tools/instance_offerings.py": "Checks that a Graviton target is offered in each region (EC2 DescribeInstanceTypeOfferings, optional permission)."

* "scripts/graviton_tools/managed_offerings.py": "Validates RDS and ElastiCache Graviton targets against the real orderable catalog (optional permissions)."

* "scripts/graviton_tools/pricing_comparison.py": "Resolves prices for a list of instance types from a price book, including abbreviated size spellings."

* "scripts/graviton_tools/aws_config.py": "One bounded botocore Config (10s connect, bounded retries) that every AWS client takes, so an unreachable network cannot stall a run."
* "scripts/graviton_tools/bulk_pricing.py": "Fallback pricing from a local cache of public AWS price lists, kept in the user cache directory and refreshed per region."

* "scripts/graviton_tools/realized_savings.py": "Finds the x86 equivalent of a Graviton instance, for savings already realized."

* "scripts/graviton_tools/report_generator.py": "Writes the Markdown, HTML and CSV deliverables with escaping, owner-only file modes, and symlink-safe file creation (open_private, which assess.py also uses for the JSON result and the run log)."

* "README.md": "Human-facing overview: what the skill does, install quick start, outputs, IAM permissions, cost of running, security posture, and data privacy. Not read during a run; it points humans at this index for the file map."
