# Python x86-to-Graviton Migration Skill

Validates Python application compatibility with AWS Graviton (ARM64) architecture and applies the minimum changes required to run on ARM64.

## Before you run it

The skill is provided as is, for migration assessment, without warranty, under the licenses of the [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) repository (see [LICENSE-SUMMARY](https://github.com/aws/aws-graviton-getting-started/blob/main/LICENSE-SUMMARY)). Review and test every change it makes before the change reaches production. It works on the project you bring to it, and your AI assistant runs its commands in your shell, with your permissions and network access:

- Phase 1 runs pip's dry run, which runs the build backend of every source distribution it resolves and, when it resolves `.`, of the project itself, and runs the base image's `python3` and the target images' package tools in containers. The opening of [references/phase1-static-analysis.md](references/phase1-static-analysis.md) lists every step that runs code.
- Phase 2 changes dependency pins and locks, build configuration, architecture checks in the code, Dockerfiles and CI files.
- Phase 3 installs the dependencies and the project into a new virtual environment or folder under the temporary directory, and runs the project's tests and the application, on an ARM64 host or in an arm64 container.
- The skill writes its reports into `graviton-validation/` at the project root. After each step that changes files, it commits to the local git repository, which it creates with `git init` when there is none. It never pushes: review the commits before you push them.

Run it on a project whose code you would build and run yourself. For a repository you did not write or do not trust, run it in a disposable container or VM.

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
  rm -rf /path/to/your/project/.skills/python-x86-to-graviton && \
  cp -r tools/skills/languages/python-x86-to-graviton /path/to/your/project/.skills/
```

Then ask your AI assistant:

> Run the python-x86-to-graviton skill on this project

## Customizing for your environment (optional)

By default the skill uses neutral, vendor-agnostic defaults. To orient it around your
team's toolchain (an internal PyPI mirror, uv-managed interpreters, a preferred test
command, an internal image registry, your cluster's ARM64 node labels, the hosts and images you deploy to), copy the template
to a `skill-config.md` at your project root and fill in what applies:

```bash
cp .skills/python-x86-to-graviton/references/skill-config.template.md \
   skill-config.md
```

The config lives in *your* repo (not the skill folder), so skill updates never overwrite
it. It steers **how** the transformation runs but never widens its scope; see
[references/skill-configuration.md](references/skill-configuration.md).

## Skill Files

[summaries.md](summaries.md) is the canonical index of every file in this skill, with its purpose and when it is read. Start at [SKILL.md](SKILL.md); it routes to everything else at the step that needs it.

## Output

The skill produces a `graviton-validation/` folder in the project root with structured reports:

- `00-summary.md`: Executive summary and exit criteria checklist
- `01-project-assessment.md`: Project structure, package manager(s) and Python environment
- `02-native-library-report.md`: Native extensions, vendored binaries and their resolutions
- `03-dependency-compatibility-report.md`: Per-dependency aarch64 wheel verdicts
- `04-code-scan-findings.md`: Architecture-specific code, build flags and Dockerfile findings
- `05-runtime-configuration.md`: Graviton runtime recommendations (documented, not applied)
- `06-build-test-results.md`: Install, build and test results
