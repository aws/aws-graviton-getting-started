# Java x86-to-Graviton Migration Skill

Validates Java application compatibility with AWS Graviton (ARM64) architecture and applies the minimum changes required to run on ARM64.

## What it does

This skill guides an AI coding assistant through a complete Java Graviton migration:

1. **Static Analysis** — Scans for native libraries (.so files), architecture-specific code, and ARM64-incompatible dependencies (including transitives)
2. **Compatibility Resolution** — Updates only ARM64-blocking dependencies, adds aarch64 code paths, configures Graviton JVM flags
3. **Validation** — Builds and tests on ARM64, classifies failures, produces a structured migration report

The skill is scoped strictly to ARM64 compatibility. It will not upgrade Java versions, modernize dependencies, or fix security issues — only what's required for Graviton.

## Quick Start

Copy this folder into your Java project:

```bash
mkdir -p /path/to/your/project/.skills && \
  cp -r tools/skills/languages/java-x86-to-graviton /path/to/your/project/.skills/
```

Then ask your AI assistant:

> Run the java-x86-to-graviton skill on this project

## Customizing for your environment (optional)

By default the skill uses neutral, vendor-agnostic defaults. To orient it around your
team's toolchain — a specific JDK distribution to build/validate with, the Maven Wrapper,
an internal image registry, your cluster's ARM64 node labels — copy the template to a
`skill-config.md` at your project root and fill in what applies:

```bash
cp .skills/java-x86-to-graviton/document_references/skill-config.template.md \
   skill-config.md
```

The config lives in *your* repo (not the skill folder), so skill updates never overwrite
it. It steers **how** the transformation runs but never widens its scope — see
[document_references/skill-configuration.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/document_references/skill-configuration.md).

## Skill Files

[summaries.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/summaries.md) is the canonical index of every file in this skill, with its purpose and when it is read. Start at [SKILL.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/SKILL.md) — it routes to everything else at the step that needs it.

## Output

The skill produces a `graviton-validation/` folder in the project root with structured reports:

- `00-summary.md` — Executive summary and exit criteria checklist
- `01-project-assessment.md` — Project structure and Java environment
- `02-native-library-report.md` — Native library findings and resolutions
- `03-dependency-compatibility-report.md` — Per-dependency ARM64 verdicts
- `04-code-scan-findings.md` — Architecture-specific code patterns
- `05-jvm-configuration.md` — Graviton JVM flags
- `06-build-test-results.md` — Build and test results

## Related

- [Java on Graviton guide](../../../../java.md) — The upstream Graviton Java documentation this skill draws from
