# Python x86-to-Graviton Migration Skill

Validates Python application compatibility with AWS Graviton (ARM64) architecture and applies the minimum changes required to run on ARM64.

## What it does

This skill guides an AI coding assistant through a complete Python Graviton migration:

1. **Static Analysis**: Verifies that every pinned dependency (including transitives) publishes an aarch64 wheel for the project's Python version, and scans for vendored binaries, native extensions with x86-only build flags, hash locks that only cover x86 wheels, architecture-specific code, and amd64-pinned Dockerfiles
2. **Compatibility Resolution**: Updates only ARM64-blocking dependencies (to the lowest version with an aarch64 wheel), regenerates locks through the project's own package manager, adds aarch64 code paths, fixes build configuration, and documents Graviton runtime recommendations without applying them
3. **Validation**: Installs, imports, tests and starts the application on ARM64, classifies failures, and produces a structured migration report

The skill is scoped strictly to ARM64 compatibility. It will not upgrade the Python version (unless a team allows it as the only path to an aarch64 wheel), switch package managers, modernize dependencies, or fix security issues; only what's required for Graviton.

It works with pip, pip-tools, PEP 621/setuptools, uv, Poetry and conda projects, and maps Pipenv, PDM, Hatch, vendored site-packages and Lambda layers onto the same checks.

## Quick Start

Copy this folder into your Python project:

```bash
mkdir -p /path/to/your/project/.skills && \
  cp -r tools/skills/languages/python-x86-to-graviton /path/to/your/project/.skills/
```

Then ask your AI assistant:

> Run the python-x86-to-graviton skill on this project

## Customizing for your environment (optional)

By default the skill uses neutral, vendor-agnostic defaults. To orient it around your
team's toolchain (an internal PyPI mirror, uv-managed interpreters, a preferred test
command, an internal image registry, your cluster's ARM64 node labels), copy the template
to a `skill-config.md` at your project root and fill in what applies:

```bash
cp .skills/python-x86-to-graviton/document_references/skill-config.template.md \
   skill-config.md
```

The config lives in *your* repo (not the skill folder), so skill updates never overwrite
it. It steers **how** the transformation runs but never widens its scope; see
[document_references/skill-configuration.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/python-x86-to-graviton/document_references/skill-configuration.md).

## Skill Files

[summaries.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/python-x86-to-graviton/summaries.md) is the canonical index of every file in this skill, with its purpose and when it is read. Start at [SKILL.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/python-x86-to-graviton/SKILL.md); it routes to everything else at the step that needs it.

## Output

The skill produces a `graviton-validation/` folder in the project root with structured reports:

- `00-summary.md`: Executive summary and exit criteria checklist
- `01-project-assessment.md`: Project structure, package manager(s) and Python environment
- `02-native-library-report.md`: Native extensions, vendored binaries and their resolutions
- `03-dependency-compatibility-report.md`: Per-dependency aarch64 wheel verdicts
- `04-code-scan-findings.md`: Architecture-specific code, build flags and Dockerfile findings
- `05-runtime-configuration.md`: Graviton runtime recommendations (documented, not applied)
- `06-build-test-results.md`: Install, build and test results

## Related

- [Python on Graviton guide](../../../../python.md): The upstream Graviton Python documentation this skill draws from
