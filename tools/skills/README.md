# Graviton Agent Skills

Portable Agent Skills that help developers migrate codebases to AWS Graviton (ARM64) processors.

## What are Agent Skills?

Agent Skills are an open standard for packaging expert instructions in a format AI coding assistants can follow. Each skill is a folder containing instructions, references, and scripts that teach an agent how to perform a specific task — in this case, migrating applications to Graviton.

For the full specification, see [agentskills.io](https://agentskills.io).

## Platform Compatibility

Each skill folder contains two entry point files to support the broadest range of AI tools:

| File | Platforms | Format |
|------|-----------|--------|
| `SKILL.md` | Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, and [20+ others](https://agentskills.io) | [Agent Skills spec](https://agentskills.io/specification) |
| `POWER.md` | Kiro | Kiro Powers format (`displayName`, `keywords`, `author` frontmatter) |

Both files contain the same instructions — only the frontmatter differs. Your platform will pick up the file it recognizes and ignore the other.

## Available Skills

| Skill | Language | Status | Description |
|-------|----------|--------|-------------|
| [java-x86-to-graviton](languages/java-x86-to-graviton/) | Java | Stable | Full x86-to-Graviton migration: dependency audit, native library validation, JVM optimization, ARM64 build validation |
| [python-x86-to-graviton](languages/python-x86-to-graviton/) | Python | Beta | Full x86-to-Graviton migration: aarch64 wheel verification for every pinned dependency (including transitives), native extension and vendored binary validation, runtime recommendations, ARM64 install and test validation |

## How to Install

Each skill installs on its own. The commands below install the Java skill; set `SKILL` to another folder name from [Available Skills](#available-skills) (for example `python-x86-to-graviton`) to install that skill instead. Run the project-level commands (GitHub Copilot, Windsurf, Roo Code, Any platform) from your project's root directory.

### Kiro

Open the **Agent Steering & Skills** panel, click **+** > **Import a skill** > **GitHub**, and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
```

### Cursor

Open **Settings** (`Cmd+Shift+J` / `Ctrl+Shift+J`) > **Rules** > **Add Rule** > **Remote Rule (GitHub)** and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
```

### Claude Code

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p ~/.claude/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" ~/.claude/skills/ && \
  rm -rf /tmp/graviton-skill
```

### GitHub Copilot / VS Code

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p .github/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" .github/skills/ && \
  rm -rf /tmp/graviton-skill
```

### OpenAI Codex

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p ~/.codex/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" ~/.codex/skills/ && \
  rm -rf /tmp/graviton-skill
```

### Windsurf

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p .windsurf/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" .windsurf/skills/ && \
  rm -rf /tmp/graviton-skill
```

### Gemini CLI

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p ~/.gemini/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" ~/.gemini/skills/ && \
  rm -rf /tmp/graviton-skill
```

### Roo Code

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p .roo/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" .roo/skills/ && \
  rm -rf /tmp/graviton-skill
```

### Goose

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p ~/.config/goose/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" ~/.config/goose/skills/ && \
  rm -rf /tmp/graviton-skill
```

### Any platform (project-level)

Copy the skill folder into the cross-platform standard path:

```bash
SKILL=java-x86-to-graviton   # or python-x86-to-graviton
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  git -C /tmp/graviton-skill sparse-checkout set "tools/skills/languages/$SKILL" && \
  mkdir -p .agents/skills && \
  cp -r "/tmp/graviton-skill/tools/skills/languages/$SKILL" .agents/skills/ && \
  rm -rf /tmp/graviton-skill
```

The `.agents/skills/` path is supported by all Agent Skills-compatible platforms.

## Skill Folder Structure

Each skill folder contains:

```
<skill-name>/
├── SKILL.md                    # Entry point (Agent Skills format)
├── POWER.md                    # Entry point (Kiro format)
├── summaries.md                # Canonical file index for agent discovery
├── phases/                     # Detailed phase instructions
├── document_references/        # Scope guardrails and output standards
└── README.md                   # Human-readable overview
```

## Creating New Skills

See the [skill template](_templates/SKILL.template.md) for the boilerplate structure. When creating a new skill:

1. Create a folder under `languages/` named to match the skill's `name` field
2. Create both `SKILL.md` (Agent Skills frontmatter) and `POWER.md` (Kiro frontmatter) with the same body content
3. Add a `summaries.md` listing every file in the skill, each with its purpose and when it is read. This is the **canonical** inventory — link it from `SKILL.md`/`POWER.md`, and do not duplicate the file list elsewhere in the skill
4. Add a `README.md` with a human-readable overview that points at `summaries.md` for the file map
5. Keep the main entry point under 500 lines — split detailed instructions into `phases/`, `references/`, or `scripts/` subdirectories
6. Link each supporting file inline from the step that needs it, so an agent reading top to bottom reaches it just in time. `summaries.md` serves agents that enter mid-skill or need the whole map at once

Fill in language-specific details based on the existing [Graviton documentation](../../) for each language.
