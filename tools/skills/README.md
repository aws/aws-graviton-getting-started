# Graviton Agent Skills

Portable Agent Skills that help developers migrate codebases to AWS Graviton (ARM64) processors and estimate the savings of doing so.

## What are Agent Skills?

Agent Skills are an open standard for packaging expert instructions in a format AI coding assistants can follow. Each skill is a folder containing instructions, references, and scripts that teach an agent how to perform a specific task — in this case, migrating applications to Graviton.

For the full specification, see [agentskills.io](https://agentskills.io).

## Platform Compatibility

Each skill follows the [Agent Skills specification](https://agentskills.io/specification): a single `SKILL.md` entry point plus optional `references/` and `scripts/` directories. This one format is recognized by Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, and [20+ other tools](https://agentskills.io). On Kiro these install as Agent Skills via **Import a skill** (see [below](#kiro)); they are not packaged as Kiro Powers, which these skills do not need (no bundled MCP servers).

## Available Skills

### Languages

| Skill | Language | Status | Description |
|-------|----------|--------|-------------|
| [java-x86-to-graviton](languages/java-x86-to-graviton/) | Java | Stable | Full x86-to-Graviton migration: dependency audit, native library validation, JVM optimization, ARM64 build validation |
| [python-x86-to-graviton](languages/python-x86-to-graviton/) | Python | Beta | Full x86-to-Graviton migration: aarch64 wheel verification for every pinned dependency (including transitives), native extension and vendored binary validation, runtime recommendations, ARM64 install and test validation |
| [dotnet-x86-to-graviton](languages/dotnet-x86-to-graviton/) | .NET | Beta | Full x86-to-Graviton migration: per-RID native file verification for every resolved NuGet package (including transitives), committed native file and Windows-only API validation, the move to Linux for Windows and .NET Framework starting points, runtime recommendations, ARM64 build, publish and test validation |

### Cost

| Skill | Status | Description |
|-------|--------|-------------|
| [graviton-savings-assessment](cost/graviton-savings-assessment/) | Beta | Fleet-wide Graviton savings estimate from Cost Explorer usage and real AWS pricing across EC2, RDS, ElastiCache, and OpenSearch: instance classification, Graviton target selection, engine readiness, phased migration waves, and Markdown/HTML/CSV/JSON reports. Read-only; needs Python 3.10+, boto3, and AWS credentials |

## How to Install

Each skill installs on its own. The commands below install the Java skill; set `SKILL` to another folder name from [Available Skills](#available-skills) (for example `python-x86-to-graviton`) to install that skill instead, and set `CATEGORY` to the folder it sits in (`languages` or `cost`). Run the project-level commands (GitHub Copilot, Windsurf, Roo Code, Any platform) from your project's root directory.

### Kiro

Open the **Agent Steering & Skills** panel, click **+** > **Import a skill** > **GitHub**, and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/dotnet-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/cost/graviton-savings-assessment
```

### Cursor

Open **Settings** (`Cmd+Shift+J` / `Ctrl+Shift+J`) > **Rules** > **Add Rule** > **Remote Rule (GitHub)** and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/dotnet-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/cost/graviton-savings-assessment
```

### Claude Code

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.claude/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### GitHub Copilot / VS Code

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.github/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### OpenAI Codex

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.codex/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Windsurf

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.windsurf/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Gemini CLI

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.gemini/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Roo Code

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.roo/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Goose

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=~/.config/goose/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

### Any platform (project-level)

Copy the skill folder into the cross-platform standard path:

```bash
(
  CATEGORY=languages
  SKILL=java-x86-to-graviton
  SRC="tools/skills/$CATEGORY/$SKILL"
  DEST=.agents/skills
  TMP="$(mktemp -d)" && trap 'rm -rf "$TMP"' EXIT || exit 1
  git clone --quiet --depth 1 --filter=blob:none --sparse \
      https://github.com/aws/aws-graviton-getting-started.git "$TMP" &&
    git -C "$TMP" sparse-checkout set "$SRC" &&
    [ -f "$TMP/$SRC/SKILL.md" ] ||
    { echo "Could not fetch $SRC; nothing was installed or removed." >&2; exit 1; }
  mkdir -p "$DEST" && rm -rf "$DEST/$SKILL" && cp -R "$TMP/$SRC" "$DEST/"
)
```

Not every platform reads `.agents/skills/`. For Kiro CLI copy the folder to `.kiro/skills/`, and for Claude Code to `.claude/skills/`.

`graviton-savings-assessment` also runs a Python script: after copying it, install its one dependency with `python3 -m pip install -r <skills-dir>/graviton-savings-assessment/scripts/requirements.txt` (Windows: `py -3 -m pip ...`). See its [README](cost/graviton-savings-assessment/README.md) for the AWS permissions it needs.

## Skill Folder Structure

Each skill folder contains:

```
<skill-name>/
├── SKILL.md                    # Entry point (Agent Skills format)
├── summaries.md                # Canonical file index for agent discovery
├── references/                 # Phase instructions, scope guardrails, output standards
├── scripts/                    # Optional executable helpers the skill runs
└── README.md                   # Human-readable overview
```

## Creating New Skills

See the [skill template](_templates/SKILL.template.md) for the boilerplate structure. When creating a new skill:

1. Create a folder under the matching category (`languages/` for a language migration, `cost/` for savings and cost analysis) named to match the skill's `name` field
2. Create `SKILL.md` with Agent Skills frontmatter (`name`, `description`, optional `metadata`)
3. Add a `summaries.md` listing every file in the skill, each with its purpose and when it is read. This is the **canonical** inventory — link it from `SKILL.md`, and do not duplicate the file list elsewhere in the skill
4. Add a `README.md` with a human-readable overview that points at `summaries.md` for the file map
5. Keep the main entry point under 500 lines — split detailed instructions into `references/` or `scripts/` subdirectories
6. Link each supporting file inline from the step that needs it, so an agent reading top to bottom reaches it just in time. `summaries.md` serves agents that enter mid-skill or need the whole map at once

Fill in language-specific details based on the existing [Graviton documentation](../../) for each language.
