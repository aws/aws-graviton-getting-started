# Graviton Agent Skills

Portable Agent Skills that help developers migrate codebases to AWS Graviton (ARM64) processors.

## Before you use a skill

The skills are provided as is, for migration assessment, without warranty, under the licenses of this repository (see [LICENSE-SUMMARY](../../LICENSE-SUMMARY)): [CC BY-SA 4.0](../../LICENSE) for the documentation and [MIT-0](../../LICENSE-SAMPLECODE) for its sample code, including the scripts in each skill's `scripts/` folder. Review and test every change a skill makes before the change reaches production. A skill works on the project you bring to it, and your AI assistant runs the skill's commands in your shell, with your permissions and network access. During a run, the skill:

- runs the project's build tooling with the project's own build files, from Phase 1 on: `mvn` or `./gradlew`, `dotnet restore` and MSBuild, or `pip` and the project's Python build backend; in Phase 3 it also runs the project's tests and the application;
- runs containers with Docker or another container runtime, from images that include the base images the project's Dockerfiles name;
- downloads what the checks need: packages from the project's package sources, into the caches the build tools normally use; container images; and, for .NET, an SDK that the repository needs and that is not installed, into a temporary folder;
- writes its reports into `graviton-validation/<skill-name>/` at the project root, a folder of its own, changes the project in Phase 2 (dependency versions, build files, code that checks the architecture, Dockerfiles, CI files), and commits each step that changes files to the local git repository, which it creates with `git init` when there is none. The skills never push: review the commits before you push them.

Run a skill on a project whose code you would build and run yourself. For a repository you did not write or do not trust, such as a fork or someone else's pull request, run the skill in a disposable container or VM. The opening of `references/phase1-static-analysis.md` in each skill lists the Phase 1 steps that run code.

## What are Agent Skills?

Agent Skills are an open standard for packaging expert instructions in a format AI coding assistants can follow. Each skill is a folder containing instructions, references, and scripts that teach an agent how to perform a specific task — in this case, migrating applications to Graviton.

For the full specification, see [agentskills.io](https://agentskills.io).

## Platform Compatibility

Each skill follows the [Agent Skills specification](https://agentskills.io/specification): a single `SKILL.md` entry point plus optional `references/` and `scripts/` directories. This one format is recognized by Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, and [20+ other tools](https://agentskills.io). On Kiro these install as Agent Skills via **Import a skill** (see [below](#kiro)); they are not packaged as Kiro Powers, which these skills do not need (no bundled MCP servers).

## Available Skills

| Skill | Language | Status | Description |
|-------|----------|--------|-------------|
| [java-x86-to-graviton](languages/java-x86-to-graviton/) | Java | Stable | Full x86-to-Graviton migration: dependency audit, native library validation, JVM optimization, ARM64 build validation |
| [python-x86-to-graviton](languages/python-x86-to-graviton/) | Python | Beta | Full x86-to-Graviton migration: aarch64 wheel verification for every pinned dependency (including transitives), native extension and vendored binary validation, runtime recommendations, ARM64 install and test validation |
| [dotnet-x86-to-graviton](languages/dotnet-x86-to-graviton/) | .NET | Beta | Full x86-to-Graviton migration: per-RID native file verification for every resolved NuGet package (including transitives), committed native file and Windows-only API validation, the move to Linux for Windows and .NET Framework starting points, runtime recommendations, ARM64 build, publish and test validation |

## How to Install

Each skill installs on its own. The commands below install the Java skill; set `SKILL` to another folder name from [Available Skills](#available-skills) (for example `python-x86-to-graviton`) to install that skill instead. Run the project-level commands (GitHub Copilot, Windsurf, Roo Code, Any platform) from your project's root directory. Each command prints the commit it installs from. Read the skill's files (`SKILL.md`, `references/`, `scripts/`) before its first run, and again after an update.

### Kiro

Open the **Agent Steering & Skills** panel, click **+** > **Import a skill** > **GitHub**, and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/dotnet-x86-to-graviton
```

### Cursor

Open **Settings** (`Cmd+Shift+J` / `Ctrl+Shift+J`) > **Rules** > **Add Rule** > **Remote Rule (GitHub)** and paste the URL of the skill you want:

```
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/java-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/python-x86-to-graviton
https://github.com/aws/aws-graviton-getting-started/tree/main/tools/skills/languages/dotnet-x86-to-graviton
```

### Claude Code

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p ~/.claude/skills && \
  rm -rf ~/.claude/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" ~/.claude/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### GitHub Copilot / VS Code

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p .github/skills && \
  rm -rf .github/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" .github/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### OpenAI Codex

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p ~/.codex/skills && \
  rm -rf ~/.codex/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" ~/.codex/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### Windsurf

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p .windsurf/skills && \
  rm -rf .windsurf/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" .windsurf/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### Gemini CLI

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p ~/.gemini/skills && \
  rm -rf ~/.gemini/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" ~/.gemini/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### Roo Code

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p .roo/skills && \
  rm -rf .roo/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" .roo/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### Goose

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p ~/.config/goose/skills && \
  rm -rf ~/.config/goose/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" ~/.config/goose/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

### Any platform (project-level)

Copy the skill folder into the cross-platform standard path:

```bash
SKILL=java-x86-to-graviton
: "${SKILL:?set SKILL first}" && \
  GV_CLONE=$(mktemp -d "${TMPDIR:-/tmp}/graviton-skill.XXXXXX") && \
  git clone --filter=blob:none --sparse https://github.com/aws/aws-graviton-getting-started.git "$GV_CLONE" && \
  git -C "$GV_CLONE" sparse-checkout set "tools/skills/languages/$SKILL" && \
  echo "installing $SKILL from commit $(git -C "$GV_CLONE" rev-parse HEAD)" && \
  mkdir -p .agents/skills && \
  rm -rf .agents/skills/"$SKILL" && \
  cp -r "$GV_CLONE/tools/skills/languages/$SKILL" .agents/skills/; \
  [ -z "${GV_CLONE-}" ] || rm -rf "$GV_CLONE"
```

Not every platform reads `.agents/skills/`. For Kiro CLI copy the folder to `.kiro/skills/`, and for Claude Code to `.claude/skills/`.

## Skill Folder Structure

Each skill folder contains:

```
<skill-name>/
├── SKILL.md                    # Entry point (Agent Skills format)
├── summaries.md                # Canonical file index for agent discovery
├── references/                 # Phase instructions, scope guardrails, output standards
└── README.md                   # Human-readable overview
```

## Creating New Skills

See the [skill template](_templates/SKILL.template.md) for the boilerplate structure. When creating a new skill:

1. Create a folder under `languages/` named to match the skill's `name` field
2. Create `SKILL.md` with Agent Skills frontmatter (`name`, `description`, optional `metadata`)
3. Add a `summaries.md` listing every file in the skill, each with its purpose and when it is read. This is the **canonical** inventory — link it from `SKILL.md`, and do not duplicate the file list elsewhere in the skill
4. Add a `README.md` with a human-readable overview that points at `summaries.md` for the file map
5. Keep the main entry point under 500 lines — split detailed instructions into `references/` or `scripts/` subdirectories
6. Link each supporting file inline from the step that needs it, so an agent reading top to bottom reaches it just in time. `summaries.md` serves agents that enter mid-skill or need the whole map at once

Fill in language-specific details based on the existing [Graviton documentation](../../) for each language.
