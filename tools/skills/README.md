# Graviton Agent Skills

Portable Agent Skills that help developers migrate codebases to AWS Graviton (ARM64) processors and estimate the savings of doing so.

## Before you use a skill

The skills are provided as is, for migration and savings assessment, without warranty, under the licenses of this repository (see [LICENSE-SUMMARY](../../LICENSE-SUMMARY)): [CC BY-SA 4.0](../../LICENSE) for the documentation and [MIT-0](../../LICENSE-SAMPLECODE) for its sample code, including the scripts in each skill's `scripts/` folder. Review and test every change a skill makes before the change reaches production. A skill works on the project you bring to it, and your AI assistant runs the skill's commands in your shell, with your permissions and network access. During a run, the skill:

- runs the project's build tooling with the project's own build files, from Phase 1 on: `mvn` or `./gradlew`, `dotnet restore` and MSBuild, or `pip` and the project's Python build backend; in Phase 3 it also runs the project's tests and the application;
- runs containers with Docker or another container runtime, from images that include the base images the project's Dockerfiles name;
- downloads what the checks need: packages from the project's package sources, into the caches the build tools normally use; container images; and, for .NET, an SDK that the repository needs and that is not installed, into a temporary folder;
- writes its reports into `graviton-validation/<skill-name>/` at the project root, a folder of its own, changes the project in Phase 2 (dependency versions, build files, code that checks the architecture, Dockerfiles, CI files), and commits each step that changes files to the local git repository, which it creates with `git init` when there is none. The skills never push: review the commits before you push them.

Run a skill on a project whose code you would build and run yourself. For a repository you did not write or do not trust, such as a fork or someone else's pull request, run the skill in a disposable container or VM. The opening of `references/phase1-static-analysis.md` in each migration skill lists the Phase 1 steps that run code.

The cost skills work differently: [graviton-savings-assessment](cost/graviton-savings-assessment/) does not build, run, or change a project. It runs its bundled Python script, which makes read-only AWS API calls (Cost Explorer, Savings Plans, Price List, STS, and the EC2, RDS, ElastiCache, and OpenSearch describe APIs) with the credentials in your shell, and writes its reports to the `--output-dir` you choose.

## What are Agent Skills?

Agent Skills are an open standard for packaging expert instructions in a format AI coding assistants can follow. Each skill is a folder containing instructions, references, and scripts that teach an agent how to perform a specific task — in this case, migrating applications to Graviton or estimating the savings of doing so.

For the full specification, see [agentskills.io](https://agentskills.io).

## Platform Compatibility

Each skill follows the [Agent Skills specification](https://agentskills.io/specification): a single `SKILL.md` entry point plus optional `references/` and `scripts/` directories. This one format is recognized by Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, and [20+ other tools](https://agentskills.io). On Kiro these install as Agent Skills via **Import a skill** (see [below](#kiro)); they are not packaged as Kiro Powers, which these skills do not need (no bundled MCP servers).

## Available Skills

### Migration

| Skill | Language | Status | Description |
|-------|----------|--------|-------------|
| [java-x86-to-graviton](migration/java-x86-to-graviton/) | Java | Stable | Full x86-to-Graviton migration: dependency audit, native library validation, JVM optimization, ARM64 build validation |
| [python-x86-to-graviton](migration/python-x86-to-graviton/) | Python | Beta | Full x86-to-Graviton migration: aarch64 wheel verification for every pinned dependency (including transitives), native extension and vendored binary validation, runtime recommendations, ARM64 install and test validation |
| [dotnet-x86-to-graviton](migration/dotnet-x86-to-graviton/) | .NET | Beta | Full x86-to-Graviton migration: per-RID native file verification for every resolved NuGet package (including transitives), committed native file and Windows-only API validation, the move to Linux for Windows and .NET Framework starting points, runtime recommendations, ARM64 build, publish and test validation |

### Cost

| Skill | Status | Description |
|-------|--------|-------------|
| [graviton-savings-assessment](cost/graviton-savings-assessment/) | Beta | Fleet-wide Graviton savings estimate from Cost Explorer usage and real AWS pricing across EC2, RDS, ElastiCache, and OpenSearch: instance classification, Graviton target selection, engine readiness, phased migration waves, and Markdown/HTML/CSV/JSON reports. Read-only; needs Python 3.10+, boto3, and AWS credentials |

## How to Install

Each skill installs on its own. The commands below install the Java skill; set `SKILL` to another folder name from [Available Skills](#available-skills) (for example `python-x86-to-graviton`) to install that skill instead, and set `CATEGORY` to the folder it sits in (`migration` or `cost`). Run the project-level commands (GitHub Copilot, Windsurf, Roo Code, Any platform) from your project's root directory. Each command prints the commit it installs from. Read the skill's files (`SKILL.md`, `references/`, `scripts/`) before its first run, and again after an update.

### Kiro

Open the **Agent Steering & Skills** panel, click **+** > **Import a skill** > **GitHub**, and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/dotnet-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/cost/graviton-savings-assessment
```

`graviton-savings-assessment` runs the Python programs in its `scripts/` folder, and this import route has not been tested for bringing that folder along. After importing it, check that the skill's folder contains `scripts/assess.py`; if it does not, install the skill with one of the git commands below instead.

### Cursor

Open **Settings** (`Cmd+Shift+J` / `Ctrl+Shift+J`) > **Rules** > **Add Rule** > **Remote Rule (GitHub)** and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/migration/dotnet-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/cost/graviton-savings-assessment
```

As with Kiro, check that an imported `graviton-savings-assessment` contains `scripts/assess.py`; if it does not, use a git command below.

### Claude Code

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.claude/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### GitHub Copilot / VS Code

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.github/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### OpenAI Codex

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.codex/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Windsurf

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.windsurf/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Gemini CLI

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.gemini/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Roo Code

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.roo/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Goose

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.config/goose/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Any platform (project-level)

Copy the skill folder into the cross-platform standard path:

```bash
(
  CATEGORY=migration
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.agents/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  echo "installing $SKILL from commit $(git -C "$TMP" rev-parse HEAD)"
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

Not every platform reads `.agents/skills/`. For Kiro CLI copy the folder to `.kiro/skills/`, and for Claude Code to `.claude/skills/`.

`graviton-savings-assessment` also runs a Python script: after copying it, install its one dependency with `python3 -m pip install -r <skills-dir>/graviton-savings-assessment/scripts/requirements.txt` (Windows: `py -3 -m pip ...`), where `<skills-dir>` is the folder the skill was installed into. The skill's Step 0 also walks the assistant through this. See its [README](cost/graviton-savings-assessment/README.md) for the AWS permissions it needs.

## Skill Folder Structure

Each skill folder contains:

```
<skill-name>/
├── SKILL.md                    # Entry point (Agent Skills format)
├── summaries.md                # Canonical file index for agent discovery
├── references/                 # Phase instructions, scope guardrails, output standards
├── scripts/                    # Programs the skill's blocks run from the skill folder
└── README.md                   # Human-readable overview
```

## Creating New Skills

See the [skill template](_templates/SKILL.template.md) for the boilerplate structure. When creating a new skill:

1. Create a folder under the matching category (`migration/` for a language migration, `cost/` for savings and cost analysis) named to match the skill's `name` field
2. Create `SKILL.md` with Agent Skills frontmatter (`name`, `description`, optional `metadata`)
3. Add a `summaries.md` listing every file in the skill, each with its purpose and when it is read. This is the **canonical** inventory — link it from `SKILL.md`, and do not duplicate the file list elsewhere in the skill
4. Add a `README.md` with a human-readable overview that points at `summaries.md` for the file map
5. Keep the main entry point under 500 lines — split detailed instructions into `references/` or `scripts/` subdirectories
6. Link each supporting file inline from the step that needs it, so an agent reading top to bottom reaches it just in time. `summaries.md` serves agents that enter mid-skill or need the whole map at once
7. Put code the agent runs in `scripts/`, not in a heredoc in a reference file, so the agent runs it instead of reading it and writing it out again. Start each script with the license header after its shebang line (`# SPDX-License-Identifier: MIT-0`, then `# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.`). A block that runs a script names the skill folder on its first line and runs nothing unless that line is an absolute path to a folder that holds the script; it never takes a script's path from a file in the project
8. Write the skill's reports to `graviton-validation/<skill-name>/` at the project root, so the reports of two skills run on one repository stay apart. A skill that does not work on a project, such as a cost skill, writes them to a folder the user chooses

Fill in language-specific details based on the existing [Graviton documentation](../../) for each language.
