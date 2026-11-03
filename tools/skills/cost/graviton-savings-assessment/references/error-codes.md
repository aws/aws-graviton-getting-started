# Error Codes

Every failure prints one line to stderr beginning `Error:`, then exits with the
code below. Match on the message text; `<...>` marks the variable part.

## Exit 1 — invalid arguments

| stderr message | Remediation |
|----------------|-------------|
| `Error: Python 3.10+ required. Detected: <version>` | Run with Python 3.10 or later (see SKILL.md Step 0). |
| `Error: <argparse message>` (after a usage line) | A flag is missing, misspelled or has an invalid value. Run `assess.py assess --help`. |
| `Error: Could not create output directory '<path>': <reason>.` | Check the path and its parent's permissions. The directory and its parents are created automatically. |
| `Error: Output directory '<path>' is not a directory.` | The path names an existing file. Choose another `--output-dir`. |
| `Error: Output directory '<path>' is not writable.` | Choose a directory the current user can write to. |
| `Error: --log-file must sit inside --output-dir (<dir>); got <path>` | Give `--log-file` a name inside `--output-dir`, or omit it. |
| `Error: Cannot open the log file <path>: <reason>. If it is a symlink, remove it or pass a different --log-file.` | Remove the symlink, or pass a different `--log-file`. |
| `Error: Invalid --start-date: '<value>'. Expected format: YYYY-MM-DD` (or `--end-date`) | Use `YYYY-MM-DD`. |
| `Error: Invalid date range: --start-date (<start>) must be before --end-date (<end>) — <detail>.` | The range is start-inclusive and end-exclusive, so the dates cannot be equal or reversed. |
| `Error: Invalid --customer: value exceeds 128 characters (got <n>).` | Shorten the name. |
| `Error: Invalid --customer: control characters and line breaks are not allowed.` | Pass the name on one line, in single quotes (see SKILL.md Step 2). |
| `Error: Invalid --services: '<value>'. Allowed values: ec2, rds, elasticache, opensearch` | Use a comma-separated subset of the allowed values. |
| `Error: Unable to classify instance type: '<type>'` (`classify` subcommand) | The string is not an instance type the classifier recognises, e.g. `u-6tb1.metal`. Check the spelling; hyphenated high-memory types are not parsed. |

Running `assess.py` with no subcommand prints the help to stderr and also exits 1.

## Exit 2 — credentials

| stderr message | Remediation |
|----------------|-------------|
| `Error: No AWS credentials found. Run ...` | Run `aws sso login` (`aws configure sso` to create a profile first), or set `AWS_PROFILE` to a profile that assumes a read-only role. |
| `Error: AWS credentials expired. Run ...` | Run `aws sso login` or refresh the session. |
| `Error: AWS credentials invalid. Run ...` | Sign in again with `aws sso login`, or check that `AWS_PROFILE` names the intended profile. |
| `Error: AWS access denied. Check IAM permissions.` | STS `GetCallerIdentity` was denied. Use credentials whose policy allows it (see the README's IAM section). |
| `Error: AWS credential check failed: <error code>` | STS returned another error; the code names it. |
| `Error: Credential verification failed: <details>` | An unexpected error during the STS check; account ids and ARNs are redacted from the details. |

## Exit 3 — network

| stderr message | Remediation |
|----------------|-------------|
| `Error: Network error: unable to reach AWS. Check internet connectivity and proxy settings.` | Check connectivity, proxy settings and any firewall rule for the AWS endpoints listed in the README. |

## Exit 4 — pipeline

| stderr message | Remediation |
|----------------|-------------|
| `Error: Assessment failed: No coverage data. Check credentials and date range.` | Cost Explorer returned no instance usage for the period. Check that the credentials can read Cost Explorer for the intended account and that the period has usage. |
| `Error: Assessment failed: No classifiable instances in data.` | Usage exists but none of it is an instance type the skill assesses. |
| `Error: Assessment failed: CE data pull failed: <error>` | A Cost Explorer call failed outright; the error names it (often `AccessDeniedException` for a missing `ce:*` permission). |
| `Error: Assessment failed: <details>` | Any other pipeline failure; check `assessment.log` in `--output-dir`. |
| `Error: Failed to write assessment result: <details>` | Check free space and permissions in `--output-dir`. |
| `Error: Report generation failed: <details>` | The JSON result was written; the reports were not. Check `assessment.log`. |

## Exit 5 — missing dependency

| stderr message | Remediation |
|----------------|-------------|
| `Error: boto3 is required but not installed. Install it into this interpreter with: <command>` | Run the printed `<python> -m pip install -r <scripts>/requirements.txt` command. Not a credential problem — a bare `pip install` may target a different interpreter. |

## Warnings (exit 0)

A run that succeeds can still print these to stderr. They mean the figures are
understated or less accurate, so read them before quoting a result.

| stderr text | Meaning |
|-------------|---------|
| `Warning: --start-date <date> is about <n> months back. ...` | Cost Explorer usually keeps about 14 months; the run may return partial usage. |
| `WARNING — incomplete Cost Explorer data; spend and savings are understated` | One or more Cost Explorer pulls failed. The stdout summary has `data_complete: false` and lists them in `failed_pulls`. Re-run. |
| `PRICING WARNING — results may be inaccurate (pricing_source=<source>)` | Live Pricing API rates were unavailable; unpriced instance types are excluded from the savings. Allow the Pricing API's `GetProducts` call (see the README's IAM section) and re-run. |

## Parameters

### `assess` Subcommand

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--start-date` | string (YYYY-MM-DD) | First of last month | Start of the analysis period (inclusive) |
| `--end-date` | string (YYYY-MM-DD) | First of current month | End of the analysis period (exclusive) |
| `--services` | string (comma-separated) | All services | Filter: `ec2`, `rds`, `elasticache`, `opensearch` |
| `--output-dir` | string (path) | **Required** | Directory for assessment JSON and reports. Created if absent, including parent directories; `~` is expanded |
| `--customer` | string | Empty | Customer name for the report header: at most 128 characters, no line breaks or control characters. Pass it in single quotes |
| `--log-file` | string (path) | `<output-dir>/assessment.log` | Log destination; must sit inside `--output-dir` |
| `--graviton-generation` | string | `next-gen` | Generation the savings are computed for and the HTML opens on: `next-gen` (n+1 from current) or `graviton2`–`graviton5` for the whole fleet |
| `--nih-reduction` | float | `0` | Where the HTML performance-uplift slider opens, clamped to [0, 40]. Applied flat to the HTML headline; stdout and Markdown stay price-only (`--perf-per-gen` is an alias) |

### `classify` Subcommand

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `instance_type` | string (positional) | **Required** | Instance type to classify (e.g., `m5.xlarge`) |
| `--service` | string | `ec2` | Service context: `ec2`, `rds`, `elasticache`, or `opensearch` |

## IAM Permissions

The required and optional actions, and a ready-made policy, are in the README's
[Minimum IAM Policy](../README.md#minimum-iam-policy) section. All of them are
read-only.
