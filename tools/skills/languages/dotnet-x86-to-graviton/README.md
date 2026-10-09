# .NET x86-to-Graviton Migration Skill

Validates .NET application compatibility with AWS Graviton (ARM64) architecture and applies the minimum changes required to run on ARM64.

## What it does

This skill guides an AI coding assistant through a complete .NET Graviton migration:

1. **Static Analysis**: Checks, by content, that every resolved NuGet package (including transitives) ships an aarch64 native file for each target runtime identifier and the target's C library, glibc, libstdc++ and page size, and scans for native files committed to the repository, P/Invoke loads, x86 intrinsics, project settings that pin x64, amd64-pinned Dockerfiles, Lambda descriptors and Windows-only APIs
2. **Compatibility Resolution**: Updates only ARM64-blocking packages (to the lowest version whose linux-arm64 native files load on the target), regenerates lock files through the project's own package management, adds Arm64 code paths, fixes project and deployment settings, and documents Graviton runtime recommendations without applying them
3. **Validation**: Builds, publishes, tests and starts the application on ARM64, scans every publish output and container image by content, classifies failures, and produces a structured migration report

The skill is scoped strictly to ARM64 compatibility. It will not change target frameworks (unless a team approves a change that Graviton requires), switch package management, modernize dependencies, or fix security issues; only what's required for Graviton.

Applications that run on Windows today, on modern .NET or .NET Framework, reach Graviton through Linux: the skill plans the move to modern .NET on Linux as one decision for the solution, and reports Windows Forms, WPF and ASP.NET Web Forms projects as blockers with options.

It works with PackageReference projects, central package management, lock files, packages.config and Paket.

## Quick Start

Copy this folder into your .NET project:

```bash
mkdir -p /path/to/your/project/.skills && \
  cp -r tools/skills/languages/dotnet-x86-to-graviton /path/to/your/project/.skills/
```

Then ask your AI assistant:

> Run the dotnet-x86-to-graviton skill on this project

## Customizing for your environment (optional)

By default the skill uses neutral, vendor-agnostic defaults. To orient it around your
team's toolchain (target runtime identifiers such as linux-musl-arm64 for Alpine images,
where the validation SDK comes from, a preferred test command, an internal image registry,
your cluster's ARM64 node labels), copy the template to a `skill-config.md` at your project
root and fill in what applies:

```bash
cp .skills/dotnet-x86-to-graviton/document_references/skill-config.template.md \
   skill-config.md
```

The config lives in *your* repo (not the skill folder), so skill updates never overwrite
it. It steers **how** the transformation runs but never widens its scope; see
[document_references/skill-configuration.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/dotnet-x86-to-graviton/document_references/skill-configuration.md).

## Skill Files

[summaries.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/dotnet-x86-to-graviton/summaries.md) is the canonical index of every file in this skill, with its purpose and when it is read. Start at [SKILL.md](https://github.com/aws/aws-graviton-getting-started/blob/main/tools/skills/languages/dotnet-x86-to-graviton/SKILL.md); it routes to everything else at the step that needs it.

## Output

The skill produces a `graviton-validation/` folder in the project root with structured reports:

- `00-summary.md`: Executive summary and exit criteria checklist
- `01-project-assessment.md`: Deployment type, starting point, package management, target frameworks, SDK and target OS
- `02-native-library-report.md`: Native files committed to the repository, native loads and downloads, and their resolutions
- `03-dependency-compatibility-report.md`: Per-package verdicts with per-RID evidence
- `04-code-scan-findings.md`: Architecture-specific code, project settings, Windows-only APIs and Dockerfile findings
- `05-runtime-configuration.md`: Graviton runtime recommendations (documented, not applied)
- `06-build-test-results.md`: Build, publish, output scan and test results

## Related

- [.NET on Graviton guide](../../../../dotnet.md): The upstream Graviton .NET documentation this skill draws from
