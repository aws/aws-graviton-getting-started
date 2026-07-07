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
cp -r tools/skills/languages/java-x86-to-graviton/ /path/to/your/project/.skills/java-x86-to-graviton/
```

Then ask your AI assistant:

> Run the java-x86-to-graviton skill on this project

## Skill Files

| File | Purpose |
|------|---------|
| [SKILL.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/SKILL.md) | Main entry point — scope, workflow, exit criteria |
| [phases/phase1-static-analysis.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/phases/phase1-static-analysis.md) | Dependency audit, native library scanning, code analysis |
| [phases/phase2-resolution.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/phases/phase2-resolution.md) | ARM64-blocking fixes, JVM flags, Dockerfile updates |
| [phases/phase3-validation.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/phases/phase3-validation.md) | ARM64 build, test, startup validation |
| [document_references/agent-scope-boundaries.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/document_references/agent-scope-boundaries.md) | Scope guardrails and decision tree |
| [document_references/documentation-standards.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/java-x86-to-graviton/document_references/documentation-standards.md) | Output file format and naming conventions |

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
