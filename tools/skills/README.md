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

## How to Install

### Kiro

Open the **Agent Steering & Skills** panel, click **+** > **Import a skill** > **GitHub**, and paste:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
```

### Cursor

Open **Settings** (`Cmd+Shift+J` / `Ctrl+Shift+J`) > **Rules** > **Add Rule** > **Remote Rule (GitHub)** and paste:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
```

### Claude Code

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  cp -r tools/skills/languages/java-x86-to-graviton ~/.claude/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### GitHub Copilot / VS Code

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p .github/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton .github/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### OpenAI Codex

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p ~/.codex/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton ~/.codex/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### Windsurf

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p .windsurf/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton .windsurf/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### Gemini CLI

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p ~/.gemini/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton ~/.gemini/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### Roo Code

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p .roo/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton .roo/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### Goose

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p ~/.config/goose/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton ~/.config/goose/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

### Any platform (project-level)

Copy the skill folder into the cross-platform standard path:

```bash
git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git /tmp/graviton-skill && \
  cd /tmp/graviton-skill && \
  git sparse-checkout set tools/skills/languages/java-x86-to-graviton && \
  mkdir -p .agents/skills && \
  cp -r tools/skills/languages/java-x86-to-graviton .agents/skills/ && \
  cd - && rm -rf /tmp/graviton-skill
```

The `.agents/skills/` path is supported by all Agent Skills-compatible platforms.

## Skill Folder Structure

Each skill folder contains:

```
<skill-name>/
├── SKILL.md                    # Entry point (Agent Skills format)
├── POWER.md                    # Entry point (Kiro format)
├── summaries.md                # File index for agent discovery
├── phases/                     # Detailed phase instructions
├── document_references/        # Scope guardrails and output standards
└── README.md                   # Human-readable overview
```

## Creating New Skills

See the [skill template](_templates/SKILL.template.md) for the boilerplate structure. When creating a new skill:

1. Create a folder under `languages/` named to match the skill's `name` field
2. Create both `SKILL.md` (Agent Skills frontmatter) and `POWER.md` (Kiro frontmatter) with the same body content
3. Add a `summaries.md` listing all files in the skill for agent discovery
4. Add a `README.md` with a human-readable overview
5. Keep the main entry point under 500 lines — split detailed instructions into `phases/`, `references/`, or `scripts/` subdirectories

Fill in language-specific details based on the existing [Graviton documentation](../../) for each language.
