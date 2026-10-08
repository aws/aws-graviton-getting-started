# Skill Configuration (Optional)

## Purpose

Teams can steer HOW this transformation runs (which package manager to drive, which package index to probe, which tool provides the validation interpreter, which test command, which container registry, which deployment vocabulary) without forking the skill or committing environment-specific values into it. This keeps the skill vendor-neutral while letting each team orient it around their environment (e.g. an internal PyPI mirror, uv-managed interpreters, an internal image mirror, their cluster's ARM64 node labels).

## How It Works

1. A team copies [skill-config.template.md](skill-config.template.md)
   to **`skill-config.md` at their project root** (next to requirements.txt /
   pyproject.toml) and fills in the fields they care about. The file lives in the team's
   own repo, never in the skill folder, so skill updates never clobber it and no
   environment-specific values leak upstream.
2. Before Phase 1, the agent checks for `skill-config.md`. If present, it reads
   the configuration and applies each set field as an override at the wiring points below. If
   absent, it uses the skill's neutral defaults.
3. Applied overrides are recorded in `01-project-assessment.md` for auditability.

## Section Layout

Fields are grouped into **shared** sections (`Container`, `Deployment`, `CI`) that apply regardless of language, and **per-language** sections (`Python`) holding toolchain fields specific to that ecosystem. A project keeps only the language section(s) it uses; a field in a language section the project does not use is simply ignored.

## Precedence Rules

1. **The configuration steers HOW, never WHAT.** It selects tools, environments, indexes,
   registries, and labels. It cannot add work, modernize dependencies, switch the project's
   package manager, or relax any scope rule.
2. **`agent-scope-boundaries.md` always wins.** If any configured value would imply an
   out-of-scope change, ignore that value and use the neutral default.
3. **Interpreter scope split.** `python.interpreter_select` chooses the tool that provides the
   session-scoped BUILD / VALIDATION interpreter only (Phase 3.0). The project's declared
   interpreter is governed by `python.interpreter_bump` alone, whose default `never` keeps it
   unchanged. Steering the former never changes the latter.
4. **`python.interpreter_bump` only unlocks a bump that is the sole path to an aarch64 wheel, decided once for the whole dependency set.**
   With `ask`, the agent presents the blocking packages and the lowest interpreter that resolves
   them, then waits; with `approved=<3.X>`, it applies that version and records it in
   `01-project-assessment.md` and `00-summary.md`. Neither value permits a bump for any other
   reason (end of life, performance, "newer is better").
5. **Registry/mirror redirects preserve substance.** A `container.base_image_registry`
   override changes only WHERE an image is pulled from; it must keep the same base-image
   distribution AND version.
6. **Index settings are verify-then-apply.** `python.index_url` / `python.extra_index_url`
   point every probe and install at the configured index, and Phase 1.3 also probes PyPI. A pin
   that resolves on PyPI but not on the configured index is recorded as INFRA (the mirror lacks
   the aarch64 wheel), never "fixed" by choosing another version; if the index is unreachable,
   record that in `01-project-assessment.md` and probe PyPI only.
7. **Pinned tools fall back when absent.** If `python.package_manager` or `container.runtime`
   names a tool that is not installed or does not respond, use the auto-detected one rather
   than failing, and record the fallback.
8. **Absent configuration → neutral defaults**, and applied overrides are recorded in
   `01-project-assessment.md`.

## Field Reference

| Field | Section | Steers | Neutral default it overrides |
|-------|---------|--------|------------------------------|
| `container.base_image_registry` | Container (shared) | Where base images are pulled from | current base image, registry preserved (same distro/version); phase2 §2.4 "Dockerfile updates" |
| `container.runtime` | Container (shared) | Container CLI | auto-detected `CONTAINER_CMD`; phase3 "Container Runtime Detection", run before the first container command (Phase 1.1) |
| `deploy.arch_selector` / `deploy.nodepool_label` | Deployment (shared) | ARM64 node selection in manifests | generic `kubernetes.io/arch: arm64`, no nodepool label; phase2 §2.4 "Deployment manifests" |
| `deploy.registry` / `deploy.ingress_convention` | Deployment (shared) | Manifest registry & ingress | existing registry/ingress left unchanged; phase2 §2.4 "Deployment manifests" |
| `ci.system` | CI (shared) | CI vocabulary in the post-transformation note | generic CI/CD wording; SKILL.md "User Responsibility (Post-Transformation)" |
| `python.package_manager` | Python | Which manager's commands drive export, override and lock regeneration | auto-detected from marker files; phase1 §1.1 "Detect Package Manager and Interpreter" |
| `python.index_url` / `python.extra_index_url` | Python | Index used by every probe and install | the index the project's pip configuration already uses (PyPI by default); phase1 §1.3, phase2 §2.2, phase3 §3.1 |
| `python.interpreter_bump` | Python | Whether the declared interpreter may change when it is the only path to an aarch64 wheel | `never`; phase1 §1.5, phase2 §2.2 "Interpreter-ABI blockers" |
| `python.interpreter_select` | Python | Tool that provides the session-scoped validation interpreter | first that works: `uv`, a matching `pythonX.Y` on PATH, `pyenv`, `conda`; phase3 "Session-Scoped Python Switching" |
| `python.install_hint` | Python | Install command surfaced if no matching interpreter is found | `uv python install <version>` or the distribution's package; phase3 "If no matching interpreter is found" |
| `python.test_command` | Python | Test command for Phase 3.2 | the project's own runner (`python -m pytest`, `python -m unittest`, `tox`, Makefile target); phase3 §3.2 |

## Authoring Notes

- Leave a field blank or delete it to use the neutral default; partial configs are fine.
- Keep genuinely private values (internal hostnames, index URLs, proxies, account-specific labels) in
  your own repo's copy. Never add them to the skill.
- Never put credentials in `skill-config.md`. An index that needs authentication keeps its
  credentials in the user's pip configuration, keyring or environment, not in the skill config.
