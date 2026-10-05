# Skill Configuration (Optional)

## Purpose

Teams can steer HOW this transformation runs (which runtime identifiers to target, how the target framework decision is approved, which tool provides the validation SDK, which test command, which container registry, which deployment vocabulary) without forking the skill or committing environment-specific values into it. This keeps the skill vendor-neutral while letting each team orient it around their environment (e.g. an Alpine-based image fleet, an internal image mirror, their cluster's ARM64 node labels).

## How It Works

1. A team copies [skill-config.template.md](skill-config.template.md)
   to **`skill-config.md` at their project root** (next to the solution or project files) and
   fills in the fields they care about. The file lives in the team's own repo, never in the
   skill folder, so skill updates never clobber it and no environment-specific values leak
   upstream.
2. Before Phase 1, the agent checks for `skill-config.md`. If present, it reads
   the configuration and applies each set field as an override at the wiring points below. If
   absent, it uses the skill's neutral defaults.
3. Applied overrides are recorded in `01-project-assessment.md` for auditability.

## Section Layout

Fields are grouped into **shared** sections (`Container`, `Deployment`, `CI`) that apply regardless of language, and **per-language** sections (`.NET`) holding toolchain fields specific to that ecosystem. A project keeps only the language section(s) it uses; a field in a language section the project does not use is simply ignored.

## Precedence Rules

1. **The configuration steers HOW, never WHAT.** It selects tools, environments, RIDs,
   registries, and labels. It cannot add work, modernize dependencies, switch the project's
   package management, or relax any scope rule.
2. **`agent-scope-boundaries.md` always wins.** If any configured value would imply an
   out-of-scope change, ignore that value and use the neutral default.
3. **SDK scope split.** `dotnet.sdk_select` chooses the tool that provides the session-scoped
   BUILD / VALIDATION SDK only (Phase 3.0). The project's `global.json` and target frameworks
   are never changed by it.
4. **`dotnet.framework_bump` only unlocks the target framework changes that Graviton requires,
   decided once for the whole solution:** the port of a .NET Framework or `-windows` target to
   modern .NET on Linux, a runtime that cannot run on arm64 as it is (such as Lambda
   `dotnetcore3.1`), or a package version that works on arm64 only on a newer framework. With `ask`
   (the default), the agent presents the reason, the options with their support dates and glibc
   needs, and waits; with `approved=<tfm>`, it applies that framework and records it in
   `01-project-assessment.md` and `00-summary.md`; with `never`, it documents the change as a
   blocker and applies nothing. No value permits a change for any other reason (end of support,
   performance, "newer is better").
5. **Registry/mirror redirects preserve substance.** A `container.base_image_registry`
   override changes only WHERE an image is pulled from; it must keep the same base-image
   distribution AND version.
6. **Feeds stay as the repository configures them.** Probes and restores use the repository's
   `NuGet.config`. A version that probes clean on nuget.org but not through the repository's feeds
   is recorded as INFRA for the feed owner, never "fixed" by editing sources or package source
   mapping.
7. **Pinned tools fall back when absent.** If `dotnet.sdk_select` or `container.runtime`
   names a tool that is not installed or does not respond, use the auto-detected one rather
   than failing, and record the fallback.
8. **Absent configuration → neutral defaults**, and applied overrides are recorded in
   `01-project-assessment.md`.

## Field Reference

| Field | Section | Steers | Neutral default it overrides |
|-------|---------|--------|------------------------------|
| `container.base_image_registry` | Container (shared) | Where base images are pulled from | current base image, registry preserved (same distro/version); phase2 §2.4 "Dockerfile updates" |
| `container.runtime` | Container (shared) | Container CLI | auto-detected `CONTAINER_CMD`; phase3 "Container Runtime Detection" |
| `deploy.arch_selector` / `deploy.nodepool_label` | Deployment (shared) | ARM64 node selection in manifests | generic `kubernetes.io/arch: arm64`, no nodepool label; phase2 §2.4 "Deployment manifests" |
| `deploy.registry` / `deploy.ingress_convention` | Deployment (shared) | Manifest registry & ingress | existing registry/ingress left unchanged; phase2 §2.4 "Deployment manifests" |
| `ci.system` | CI (shared) | CI vocabulary in the post-transformation note | generic CI/CD wording; SKILL.md "User Responsibility (Post-Transformation)" |
| `dotnet.target_rids` | .NET | Target RIDs for every per-RID check, probe and scan | `linux-arm64`, plus `linux-musl-arm64` when a target image is Alpine; phase1 §1.1 "Determine Target OS and libc" |
| `dotnet.framework_bump` | .NET | How a Graviton-required target framework change is approved | `ask`; phase1 §1.5, phase2 §2.2 "Target framework changes" |
| `dotnet.sdk_select` | .NET | Tool that provides the session-scoped validation SDK | first that works: an installed SDK that matches `global.json`, the official install script into a temporary folder, the SDK container image; phase3 "Session-Scoped .NET Switching" |
| `dotnet.install_hint` | .NET | Install command surfaced if no matching SDK is found | the official install script or the distribution's package; phase3 "If no matching SDK is found" |
| `dotnet.test_command` | .NET | Test command for Phase 3.2 | `dotnet test` on the solution; phase3 §3.2 |

## Authoring Notes

- Leave a field blank or delete it to use the neutral default; partial configs are fine.
- Keep genuinely private values (internal hostnames, feed URLs, proxies, account-specific labels) in
  your own repo's copy. Never add them to the skill.
- Never put credentials in `skill-config.md`. A feed that needs authentication keeps its
  credentials in the user's NuGet configuration or environment, not in the skill config.
