#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Graviton Savings Assessment CLI.

Entry point for the Graviton savings assessment skill. Provides two subcommands:
  - assess: Run a full fleet assessment (classify → price → score → plan → report)
  - classify: Classify a single instance type and print JSON to stdout

Exit codes:
  0 - Success
  1 - Invalid arguments or Python version
  2 - Credential errors
  3 - Network errors
  4 - Pipeline errors
  5 - Missing Python dependency (boto3)

Runs on macOS, Linux, and Windows. Paths are handled through pathlib, and the
owner-only file modes are advisory on Windows, where the filesystem ignores
POSIX permission bits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Ensure graviton_tools is importable from the same directory as this script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
# No __pycache__ inside the installed skill folder: the skill is copied into
# agent config directories, and the first run wrote bytecode there.
sys.dont_write_bytecode = True

# One timestamp per run, shared with the report file names, so a second run in
# the same --output-dir no longer replaces the first run's JSON and log.
_RUN_STAMP = datetime.now().strftime("%Y-%m-%d-%H%M")


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
EXIT_SUCCESS = 0
EXIT_INVALID_ARGS = 1
EXIT_CREDENTIAL_ERROR = 2
EXIT_NETWORK_ERROR = 3
EXIT_PIPELINE_ERROR = 4
# Distinct from EXIT_CREDENTIAL_ERROR so a caller can tell "install boto3" from
# "fix your credentials": the fix for a missing dependency is a pip install, not
# `aws sso login`.
EXIT_MISSING_DEPENDENCY = 5

# Pricing sources that yield trustworthy per-instance savings. Anything else
# means live Pricing API rates were unavailable for the run.
_TRUSTWORTHY_PRICING_SOURCES = frozenset({"pricing_api_boto3"})


def _pricing_warning(summary: dict) -> Optional[str]:
    """Return a user-facing warning if pricing degraded below the live API.

    The Pricing API (pricing:GetProducts) is required for accurate per-instance
    savings. Without it, only managed-service list prices from AWS's public
    bulk price files are available, EC2 rows go unpriced, and unpriced rows are
    excluded from the savings figures — so the headline is understated. This
    surfaces that so results are not trusted blindly.

    Returns None when pricing is trustworthy.
    """
    source = summary.get("pricing_source", "none")
    if source in _TRUSTWORTHY_PRICING_SOURCES:
        return None

    detail = {
        "bulk_cache": (
            "The live AWS Pricing API was unavailable (likely missing "
            "pricing:GetProducts), so only managed-service list prices from the "
            "public bulk price files were used. EC2 and any other unpriced "
            "instance types are excluded from the savings figures, which are "
            "therefore understated."
        ),
        "none": (
            "No prices were resolved, so no savings could be computed. Check "
            "pricing:GetProducts and network access to the AWS Pricing endpoint."
        ),
    }.get(source, f"Pricing source '{source}' is not the live Pricing API; savings may be inaccurate.")

    remediation = (
        "Grant pricing:GetProducts to the credentials in use (the Pricing API is "
        "account-agnostic — any valid AWS identity you own works) and re-run."
    )
    return f"{detail} {remediation}"


def _emit_completeness_warning(summary: dict) -> None:
    """Print a banner to stderr when a Cost Explorer pull failed."""
    from graviton_tools.report_generator import _completeness
    complete, failed = _completeness(summary)
    if complete is not False:
        return
    banner = "=" * 72
    print(
        f"\n{banner}\n"
        f"WARNING — incomplete Cost Explorer data; spend and savings are understated\n"
        f"{banner}\n"
        f"{len(failed)} pull(s) failed: {', '.join(failed) or 'unknown'}.\n"
        f"Re-run before relying on these figures.\n"
        f"{banner}\n",
        file=sys.stderr,
    )


def _analysis_period(summary: dict) -> dict:
    """The period and cost basis for the stdout summary."""
    period = summary.get("period") or {}
    date_range = summary.get("date_range") or {}
    return {
        "start": period.get("start") or date_range.get("start", ""),
        "end_exclusive": period.get("end") or date_range.get("end", ""),
        "months": period.get("months"),
        "basis": period.get("basis", ""),
    }


def _emit_pricing_warning(summary: dict) -> None:
    """Print a prominent pricing-degradation banner to stderr, if applicable."""
    warning = _pricing_warning(summary)
    if not warning:
        return
    source = summary.get("pricing_source", "none")
    banner = "=" * 72
    print(
        f"\n{banner}\n"
        f"⚠️  PRICING WARNING — results may be inaccurate (pricing_source={source})\n"
        f"{banner}\n"
        f"{warning}\n"
        f"{banner}\n",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------
def _check_python_version() -> None:
    """Verify Python >= 3.10. Exits with code 1 if too old."""
    if sys.version_info < (3, 10):
        detected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        _error_exit(
            f"Python 3.10+ required. Detected: {detected}",
            EXIT_INVALID_ARGS,
        )


# ---------------------------------------------------------------------------
# Error handling utilities
# ---------------------------------------------------------------------------
def _error_exit(message: str, exit_code: int) -> None:
    """Print error message to stderr and exit with the given code.

    Args:
        message: User-facing error message (no raw tracebacks or credentials).
        exit_code: Process exit code.
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)


def _sanitize_error(error: Exception) -> str:
    """Extract a safe error description without credentials or account IDs.

    Args:
        error: The caught exception.

    Returns:
        A sanitized string safe for user display.
    """
    # The same rules as the log file and summary.pricing_errors: ARNs (an
    # AccessDenied names the caller's role), account ids, access key ids.
    from graviton_tools.report_generator import _redact_sensitive
    msg = _redact_sensitive(error)
    # Truncate overly long messages
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


class _RedactingLogFilter(logging.Filter):
    """Strip ARNs and account ids from every record before a handler emits it.

    The pipeline's warning paths log raw boto3 exceptions, and an access-denied
    message embeds the operator's full caller ARN. The log file sits in the same
    directory as the customer deliverables, so it travels with them when the
    directory is zipped — the same reason summary.pricing_errors is redacted at
    its own sink.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from graviton_tools.report_generator import _redact_sensitive
        record.msg = _redact_sensitive(record.getMessage())
        record.args = ()
        return True


# ---------------------------------------------------------------------------
# Credential verification
# ---------------------------------------------------------------------------
def check_credentials(timeout: int = 10) -> dict:
    """Verify AWS credentials via STS GetCallerIdentity.

    Args:
        timeout: Connection and read timeout in seconds.

    Returns:
        The identity dict from STS on success.

    Raises:
        SystemExit: On credential or network failures with appropriate exit code.
    """
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import (
            ClientError,
            NoCredentialsError,
            EndpointConnectionError,
            ConnectTimeoutError,
            ReadTimeoutError,
        )
    except ImportError:
        # Name the running interpreter rather than a bare `pip`: on machines with
        # several Pythons (the common case on macOS and Windows), `pip install`
        # frequently installs into a different one than the caller is using, and
        # the failure repeats identically.
        requirements = Path(__file__).resolve().parent / "requirements.txt"
        _error_exit(
            "boto3 is required but not installed. Install it into this "
            f'interpreter with:\n  {sys.executable} -m pip install -r "{requirements}"',
            EXIT_MISSING_DEPENDENCY,
        )

    config = Config(
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={"max_attempts": 1},
    )

    try:
        sts = boto3.client("sts", config=config)
        identity = sts.get_caller_identity()
        return identity
    except NoCredentialsError:
        _error_exit(
            "No AWS credentials found. Run `aws sso login` (or `aws configure sso` to "
            "set up a profile), or set AWS_PROFILE to a profile that assumes a "
            "read-only role.",
            EXIT_CREDENTIAL_ERROR,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ExpiredTokenException" or "expired" in str(e).lower():
            _error_exit(
                "AWS credentials expired. Run `aws sso login` or refresh your session.",
                EXIT_CREDENTIAL_ERROR,
            )
        elif error_code == "InvalidClientTokenId" or "invalid" in error_code.lower():
            _error_exit(
                "AWS credentials invalid. Run `aws sso login` again, or check that "
                "AWS_PROFILE names the intended profile.",
                EXIT_CREDENTIAL_ERROR,
            )
        elif error_code == "AccessDenied" or error_code == "AccessDeniedException":
            _error_exit(
                "AWS access denied. Check IAM permissions.",
                EXIT_CREDENTIAL_ERROR,
            )
        else:
            _error_exit(
                f"AWS credential check failed: {error_code}",
                EXIT_CREDENTIAL_ERROR,
            )
    except (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError):
        _error_exit(
            "Network error: unable to reach AWS. Check internet connectivity and proxy settings.",
            EXIT_NETWORK_ERROR,
        )
    except (OSError, ConnectionError):
        _error_exit(
            "Network error: unable to reach AWS. Check internet connectivity and proxy settings.",
            EXIT_NETWORK_ERROR,
        )
    except Exception as e:
        # Catch-all for unexpected errors during credential check
        if "timeout" in str(e).lower() or "connect" in str(e).lower():
            _error_exit(
                "Network error: unable to reach AWS. Check internet connectivity and proxy settings.",
                EXIT_NETWORK_ERROR,
            )
        _error_exit(
            f"Credential verification failed: {_sanitize_error(e)}",
            EXIT_CREDENTIAL_ERROR,
        )


# ---------------------------------------------------------------------------
# Output directory validation
# ---------------------------------------------------------------------------
def validate_output_dir(path: str) -> Path:
    """Resolve the output directory, creating it if it does not exist.

    Creating rather than refusing: this runs as a skill, where the caller is an
    agent that picked the path itself. Requiring a prior `mkdir` made the first
    run fail on a technicality, and `mkdir -p` is not a command on Windows, so
    the documented workaround was not portable either.

    Args:
        path: Path string to validate.

    Returns:
        Resolved Path object on success.

    Raises:
        SystemExit: If the path cannot be created, is not a directory, or is
            not writable.
    """
    # expandvars as well as ~: an agent on Windows may pass %USERPROFILE% or
    # $HOME, which PowerShell does not expand inside an argument.
    dir_path = Path(os.path.expandvars(path)).expanduser().resolve()

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        # Path exists as a file (or something else that is not a directory);
        # reported below with a clearer message than the raw OSError.
        pass
    except OSError as e:
        _error_exit(
            f"Could not create output directory '{path}': {e.strerror or e}.",
            EXIT_INVALID_ARGS,
        )

    if not dir_path.is_dir():
        _error_exit(
            f"Output directory '{path}' is not a directory.",
            EXIT_INVALID_ARGS,
        )

    if not os.access(dir_path, os.W_OK):
        _error_exit(
            f"Output directory '{path}' is not writable.",
            EXIT_INVALID_ARGS,
        )

    return dir_path


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------
def _validate_date(value: str, arg_name: str) -> str:
    """Validate a date string is in YYYY-MM-DD format.

    Args:
        value: The date string to validate.
        arg_name: The argument name for error messages.

    Returns:
        The validated date string.

    Raises:
        SystemExit: If the date format is invalid.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        _error_exit(
            f"Invalid {arg_name}: '{value}'. Expected format: YYYY-MM-DD",
            EXIT_INVALID_ARGS,
        )


# Cost Explorer retains ~14 months of history by default. Older ranges are a
# warning rather than an error: accounts can be opted in to a longer window,
# and this check has no way to know which.
_CE_RETENTION_MONTHS = 14


def _check_date_range(start_date: str, end_date: str) -> None:
    """Reject an inverted range and warn about one Cost Explorer will not have.

    Checked here because inside the pipeline both conditions surface only as an
    opaque Cost Explorer ValidationException, after the credential preflight has
    already made a network round trip.
    """
    if not start_date:
        # A defaulted start is the month before the end, which is always valid.
        return
    if not end_date:
        # The pipeline defaults the end to the 1st of this month. Check against
        # that here: a lone --start-date after it once skipped this check and
        # the inverted range scaled every monthly figure about 30x.
        end_date = datetime.now().date().replace(day=1).strftime("%Y-%m-%d")

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    if start >= end:
        detail = (
            "the range is start-inclusive and end-exclusive in Cost Explorer, so "
            "equal dates select no usage at all"
            if start == end else
            "the dates are reversed"
        )
        _error_exit(
            f"Invalid date range: --start-date ({start_date}) must be before "
            f"--end-date ({end_date}) — {detail}.",
            EXIT_INVALID_ARGS,
        )

    months_back = (date.today().year - start.year) * 12 + date.today().month - start.month
    if months_back > _CE_RETENTION_MONTHS:
        print(
            f"Warning: --start-date {start_date} is about {months_back} months "
            f"back. Cost Explorer retains roughly {_CE_RETENTION_MONTHS} months "
            "unless the account is opted in to a longer window, so this run may "
            "fail or return only partial usage.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Subcommand: classify
# ---------------------------------------------------------------------------
def cmd_classify(args: argparse.Namespace) -> None:
    """Handle the 'classify' subcommand.

    Classifies a single instance type and prints JSON to stdout.

    Args:
        args: Parsed argparse namespace with instance_type and service.
    """
    from graviton_tools.instance_classifier import classify_and_upgrade
    from dataclasses import asdict

    instance_type = args.instance_type
    service = args.service

    result = classify_and_upgrade(instance_type, service)

    if result is None:
        _error_exit(
            f"Unable to classify instance type: '{instance_type}'",
            EXIT_INVALID_ARGS,
        )

    output = asdict(result)
    print(json.dumps(output, indent=2, default=str))
    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# Subcommand: assess
# ---------------------------------------------------------------------------
def cmd_assess(args: argparse.Namespace) -> None:
    """Handle the 'assess' subcommand.

    Validates arguments, checks credentials, runs the assessment pipeline,
    writes reports, and prints a compact JSON summary to stdout.

    Args:
        args: Parsed argparse namespace with assessment parameters.
    """
    # Validate output directory
    output_dir = validate_output_dir(args.output_dir)

    # Configure logging.
    #
    # --log-file is resolved and confined to the validated output directory.
    # The log is opened with O_TRUNC, so an unconfined path would let a caller
    # TRUNCATE any file the process can write — and in an agent-driven
    # skill the agent composes this flag, so the value is not necessarily a
    # careful human's.
    if args.log_file:
        requested = Path(os.path.expandvars(args.log_file)).expanduser()
        # A bare name (run.log) means a file in --output-dir, not in the
        # current directory, which the check below would then reject.
        if not requested.is_absolute() and len(requested.parts) == 1:
            requested = output_dir / requested
        # Resolve the directory only. Resolving the whole path follows a
        # symlink planted under the log's name, and the log would then be
        # opened (and truncated) at its target; left unresolved, open_private
        # refuses the link.
        requested = requested.parent.resolve() / requested.name
        if requested.parent != output_dir.resolve():
            _error_exit(
                f"--log-file must sit inside --output-dir ({output_dir}); "
                f"got {requested}",
                EXIT_INVALID_ARGS,
            )
        log_file = str(requested)
    else:
        log_file = str(output_dir / f"assessment-{_RUN_STAMP}.log")
    # Owner-only, like the reports: the log records the operator's activity and
    # sits beside the customer deliverables, so it travels with them if the
    # directory is zipped or shared. Opened through open_private rather than
    # logging.FileHandler, which follows a symlink planted under this name in a
    # shared output directory and truncates whatever it points at.
    from graviton_tools.report_generator import open_private
    try:
        log_stream = open_private(log_file)
    except OSError as e:
        _error_exit(
            f"Cannot open the log file {log_file}: {e.strerror or e}. If it is a "
            "symlink, remove it or pass a different --log-file.",
            EXIT_INVALID_ARGS,
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(log_stream),
            logging.StreamHandler(sys.stderr),
        ],
    )
    for _handler in logging.getLogger().handlers:
        _handler.addFilter(_RedactingLogFilter())
    log = logging.getLogger("assess")
    log.info("Log file: %s", log_file)

    # Validate dates if provided
    start_date = ""
    end_date = ""
    if args.start_date:
        start_date = _validate_date(args.start_date, "--start-date")
    if args.end_date:
        end_date = _validate_date(args.end_date, "--end-date")
    _check_date_range(start_date, end_date)

    # Validate customer name length
    customer = args.customer or ""
    if len(customer) > 128:
        _error_exit(
            f"Invalid --customer: value exceeds 128 characters (got {len(customer)}).",
            EXIT_INVALID_ARGS,
        )
    # Control and format characters (newlines, tabs, bidi overrides,
    # zero-width) have no place in a name printed in report headers, and a line
    # break in an agent-composed argument is a sign the value was not quoted as
    # SKILL.md asks.
    if any(unicodedata.category(ch)[0] == "C" or unicodedata.category(ch) in ("Zl", "Zp")
           for ch in customer):
        _error_exit(
            "Invalid --customer: control characters and line breaks are not allowed.",
            EXIT_INVALID_ARGS,
        )

    # Clamp NIH reduction to the slider's supported range [0, 40].
    perf_per_gen = max(0.0, min(40.0, args.nih_reduction))

    # Parse services
    services = None
    if args.services:
        valid_services = {"ec2", "rds", "elasticache", "opensearch"}
        services = [s.strip().lower() for s in args.services.split(",")]
        for svc in services:
            if svc not in valid_services:
                _error_exit(
                    f"Invalid --services: '{svc}'. Allowed values: ec2, rds, elasticache, opensearch",
                    EXIT_INVALID_ARGS,
                )

    # Map the generation choice onto the pipeline's target_strategy.
    # "next-gen" == "latest" (n+1 from current); the rest force one generation.
    target_strategy = (
        "latest" if args.graviton_generation == "next-gen"
        else args.graviton_generation
    )

    # Check credentials (fail-fast)
    identity = check_credentials(timeout=10)
    account_id = identity.get("Account", "") if identity else ""

    # Run the assessment pipeline
    try:
        from graviton_tools.assessment_pipeline import estimate_graviton_savings

        result = estimate_graviton_savings(
            start_date=start_date,
            end_date=end_date,
            services=services,
            target_strategy=target_strategy,
        )
    except Exception as e:
        if "timeout" in str(e).lower() or "connect" in str(e).lower():
            _error_exit(
                "Network error: unable to reach AWS. Check internet connectivity and proxy settings.",
                EXIT_NETWORK_ERROR,
            )
        _error_exit(
            f"Assessment failed: {_sanitize_error(e)}",
            EXIT_PIPELINE_ERROR,
        )

    # Check for pipeline errors in result
    if "error" in result:
        error_msg = _sanitize_error(Exception(result["error"]))
        _error_exit(
            f"Assessment failed: {error_msg}",
            EXIT_PIPELINE_ERROR,
        )

    # Write full assessment JSON to output directory
    assessment_path = output_dir / f"graviton_assessment_result-{_RUN_STAMP}.json"
    try:
        # Holds the entire result — every instance type, cost, region, and the
        # account id — so it gets the deliverables' treatment: UTF-8, 0600 at
        # open, and never written through a symlink.
        from graviton_tools.report_generator import open_private
        with open_private(assessment_path) as f:
            json.dump(result, f, indent=2, default=str)
    except (OSError, IOError) as e:
        _error_exit(
            f"Failed to write assessment result: {_sanitize_error(e)}",
            EXIT_PIPELINE_ERROR,
        )

    # Write reports
    try:
        from graviton_tools.report_generator import write_reports

        report_result = write_reports(
            assessment=result,
            output_dir=str(output_dir),
            customer=customer,
            account_id=account_id,
            target_strategy=target_strategy,
            perf_per_gen=perf_per_gen,
        )
    except Exception as e:
        _error_exit(
            f"Report generation failed: {_sanitize_error(e)}",
            EXIT_PIPELINE_ERROR,
        )

    # Print compact JSON summary to stdout
    summary = result.get("summary", {})
    score = result.get("score", {})
    kpis = score.get("kpis", {})

    from graviton_tools.report_generator import _completeness, _period_info
    pricing_warning = _pricing_warning(summary)
    data_complete, failed_pulls = _completeness(summary)
    est_total_savings = kpis.get("est_total_savings", 0) or 0
    annual_factor = _period_info(summary)["annual_factor"]

    # Every cost figure is a monthly average over analysis_period. The savings
    # are price-only: unpriced rows are excluded, and their indicative 20%
    # estimate is reported beside the total, never in it.
    compact_summary = {
        "analysis_period": _analysis_period(summary),
        "spend_basis": summary.get("spend_basis") or (
            'Amortized cost of instance running hours (EC2, RDS, ElastiCache, OpenSearch) from AWS Cost Explorer, counting usage charges only; credits, refunds, other billing adjustments and AWS Marketplace are excluded.'),
        "total_types": summary.get("total_types", 0),
        "total_cost": summary.get("total_cost", 0),
        "graviton_pct": summary.get("graviton_pct", 0),
        "est_total_savings": est_total_savings,
        "est_annual_savings": round(est_total_savings * annual_factor, 2),
        "unpriced_types": kpis.get("unpriced_count", 0),
        "unpriced_cost": kpis.get("unpriced_cost", 0),
        "unpriced_indicative_savings_not_included": kpis.get(
            "unpriced_indicative_savings", 0),
        "no_equivalent_types": kpis.get("no_equivalent_count", 0),
        "pricing_source": summary.get("pricing_source", "none"),
        "nih_reduction": perf_per_gen,
        "graviton_generation": args.graviton_generation,
        "pricing_degraded": pricing_warning is not None,
        "pricing_warning": pricing_warning,
        "data_complete": data_complete,
        "failed_pulls": failed_pulls,
        "split_estimated_cost": (summary.get("data_quality") or {}).get(
            "split_estimated_cost", 0),
        "isp_check": (summary.get("data_quality") or {}).get("isp_check", ""),
        "isp_locked_cost": (summary.get("data_quality") or {}).get("isp_locked_cost", 0),
        "output_dir": str(output_dir),
        "result_json": assessment_path.name,
        "log_file": os.path.basename(log_file),
        "report_md": os.path.basename(report_result.get("markdown_path", "")),
        "report_html": os.path.basename(report_result.get("html_path", "")),
    }

    # Alert the user prominently before they trust degraded numbers.
    _emit_completeness_warning(summary)
    _emit_pricing_warning(summary)

    print(json.dumps(compact_summary, indent=2))
    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
class _AssessArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser that exits with code 1 for argument errors."""

    def error(self, message: str) -> None:
        """Override to use exit code 1 instead of argparse default 2.

        Args:
            message: The error message from argparse.
        """
        self.print_usage(sys.stderr)
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(EXIT_INVALID_ARGS)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with assess and classify subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = _AssessArgumentParser(
        prog="assess.py",
        description="Graviton Savings Assessment — classify AWS fleets and estimate migration savings.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- assess subcommand ---
    assess_parser = subparsers.add_parser(
        "assess",
        help="Run a full Graviton savings assessment",
        description="Assess AWS compute fleet for Graviton migration opportunities.",
    )
    assess_parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for analysis period (YYYY-MM-DD). Default: first of last month.",
    )
    assess_parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for analysis period (YYYY-MM-DD). Default: first of current month.",
    )
    assess_parser.add_argument(
        "--services",
        type=str,
        default=None,
        help="Comma-separated service filter: ec2,rds,elasticache,opensearch. Default: all.",
    )
    assess_parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Directory to write assessment results and reports.",
    )
    assess_parser.add_argument(
        "--customer",
        type=str,
        default="",
        help="Customer name for report header (max 128 characters, no control "
             "characters or line breaks).",
    )
    assess_parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Log file name, inside --output-dir. If omitted, logs go to <output-dir>/assessment-<timestamp>.log.",
    )
    assess_parser.add_argument(
        "--nih-reduction",
        "--perf-per-gen",  # back-compat alias
        dest="nih_reduction",
        type=float,
        default=10.0,
        help="Value (%%) the HTML report's NIH (normalized instance-hours) reduction "
             "slider opens at, an assumed performance uplift from Graviton. The HTML "
             "headline applies it once, flat, to the projected Graviton cost, and says "
             "so; only the 'If All -> Latest Generation' comparison tile compounds it "
             "per generational hop. stdout and the Markdown report are always "
             "price-only. Default: 10. Range 0-40 (0 makes the HTML price-only too).",
    )
    assess_parser.add_argument(
        "--graviton-generation",
        type=str,
        choices=["next-gen", "graviton2", "graviton3", "graviton4", "graviton5"],
        default="next-gen",
        help="Graviton generation the savings are computed for, and that the HTML "
             "report opens on. 'next-gen' targets n+1 from each instance's current "
             "generation; graviton2/3/4/5 move the whole fleet to that generation, "
             "falling back where a row has no target in it. The HTML report's radios "
             "switch this live. Default: next-gen.",
    )

    # --- classify subcommand ---
    classify_parser = subparsers.add_parser(
        "classify",
        help="Classify a single instance type",
        description="Parse an instance type and show Graviton upgrade targets.",
    )
    classify_parser.add_argument(
        "instance_type",
        type=str,
        help="Instance type to classify (e.g., m5.xlarge, db.r6g.large).",
    )
    classify_parser.add_argument(
        "--service",
        type=str,
        default="ec2",
        choices=["ec2", "rds", "elasticache", "opensearch"],
        help="Service context for classification. Default: ec2.",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Entry point. Checks Python version, parses args, dispatches to subcommand."""
    _check_python_version()

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help(sys.stderr)
        sys.exit(EXIT_INVALID_ARGS)

    if args.command == "assess":
        cmd_assess(args)
    elif args.command == "classify":
        cmd_classify(args)
    else:
        parser.print_help(sys.stderr)
        sys.exit(EXIT_INVALID_ARGS)


if __name__ == "__main__":
    main()
