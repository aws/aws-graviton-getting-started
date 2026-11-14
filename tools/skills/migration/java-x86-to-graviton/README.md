# Java x86-to-Graviton Migration Skill

Validates Java application compatibility with AWS Graviton (ARM64) architecture and applies the minimum changes required to run on ARM64.

## Before you run it

The skill is provided as is, for migration assessment, without warranty, under the licenses of the [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) repository (see [LICENSE-SUMMARY](https://github.com/aws/aws-graviton-getting-started/blob/main/LICENSE-SUMMARY)). Review and test every change it makes before the change reaches production. It works on the project you bring to it, and your AI assistant runs its commands in your shell, with your permissions and network access:

- Phase 1 runs Maven, or Gradle through the project's `./gradlew`, with the project's build files; this writes `target/deps` or `build/deps` inside the project. It also runs the target images' package tools in containers. The opening of [references/phase1-static-analysis.md](references/phase1-static-analysis.md) lists every step that runs code.
- Phase 2 changes dependency versions in the build files, architecture checks in the code, Dockerfiles and CI files.
- Phase 3 builds the project and runs its tests and the application, on an ARM64 host or in an arm64 container.
- The skill writes its reports into `graviton-validation/java-x86-to-graviton/` at the project root. After each step that changes files, it commits to the local git repository, which it creates with `git init` when there is none. It never pushes: review the commits before you push them.

Run it on a project whose code you would build and run yourself. For a repository you did not write or do not trust, run it in a disposable container or VM.

## What it does

This skill guides an AI coding assistant through a complete Java Graviton migration:

1. **Static Analysis** — Scans for native libraries (.so files), architecture-specific code, and ARM64-incompatible dependencies (including transitives)
2. **Compatibility Resolution** — Updates only ARM64-blocking dependencies, adds aarch64 code paths, documents Graviton JVM flag recommendations
3. **Validation** — Builds and tests on ARM64, classifies failures, produces a structured migration report

The skill is scoped strictly to ARM64 compatibility. It will not upgrade Java versions, modernize dependencies, or fix security issues — only what's required for Graviton.

## Quick Start

Copy this folder into your Java project:

```bash
mkdir -p /path/to/your/project/.skills && \
  rm -rf /path/to/your/project/.skills/java-x86-to-graviton && \
  cp -r tools/skills/migration/java-x86-to-graviton /path/to/your/project/.skills/
```

Run it from a clone of this repository; `git rev-parse HEAD` in the clone shows the commit you copied. Read the skill's files before its first run.

Then ask your AI assistant:

> Run the java-x86-to-graviton skill on this project

## Customizing for your environment (optional)

By default the skill uses neutral, vendor-agnostic defaults. To orient it around your
team's toolchain (a specific JDK distribution to build/validate with, the Maven Wrapper,
an internal image registry, your cluster's ARM64 node labels, the hosts and images you deploy to), copy the template to a
`skill-config.md` at your project root and fill in what applies:

```bash
cp .skills/java-x86-to-graviton/references/skill-config.template.md \
   skill-config.md
```

The config lives in *your* repo (not the skill folder), so skill updates never overwrite
it. It steers **how** the transformation runs but never widens its scope — see
[references/skill-configuration.md](references/skill-configuration.md).

## Skill Files

[summaries.md](summaries.md) is the canonical index of every file in this skill, with its purpose and when it is read. Start at [SKILL.md](SKILL.md): it routes to everything else at the step that needs it.

## Output

The skill produces a `graviton-validation/java-x86-to-graviton/` folder in the project root with structured reports:

- `00-summary.md` — Executive summary and exit criteria checklist
- `01-project-assessment.md` — Project structure and Java environment
- `02-native-library-report.md` — Native library findings and resolutions
- `03-dependency-compatibility-report.md` — Per-dependency ARM64 verdicts
- `04-code-scan-findings.md` — Architecture-specific code patterns
- `05-jvm-configuration.md` — Graviton JVM flag recommendations (documented, not applied)
- `06-build-test-results.md` — Build and test results
