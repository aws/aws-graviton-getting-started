# Skill Configuration (Optional)

## Purpose

Teams can steer HOW this transformation runs — which JDK to build with, which build
command, which container registry, which deployment vocabulary — without forking the
skill or committing environment-specific values into it. This keeps the skill vendor-neutral
while letting each team orient it around their environment (e.g. a specific JDK
distribution, the Maven Wrapper, an internal image mirror, their cluster's ARM64 node
labels).

## How It Works

1. A team copies [skill-config.template.md](skill-config.template.md)
   to **`skill-config.md` at their project root** (next to pom.xml /
   build.gradle) and fills in the fields they care about. The file lives in the team's
   own repo — never in the skill folder — so skill updates never clobber it and no
   environment-specific values leak upstream.
2. Before Phase 1, the agent checks for `skill-config.md`. If present, it reads
   the configuration and applies each set field as an override at the wiring points below. If
   absent, it uses the skill's neutral defaults.
3. Applied overrides are recorded in `01-project-assessment.md` for auditability.

## Section Layout

Fields are grouped into **shared** sections (`Container`, `Deployment`, `CI`) that apply
regardless of language, and **per-language** sections (`Java`) holding toolchain fields
specific to that ecosystem. A project keeps only the language section(s) it uses; a field
in a language section the project does not use is simply ignored.

## Precedence Rules

1. **The configuration steers HOW, never WHAT.** It selects tools, environments, registries,
   and labels. It cannot add work, modernize dependencies, change the application's
   declared Java version/distribution, or relax any scope rule.
2. **`agent-scope-boundaries.md` always wins.** If any configured value would imply an
   out-of-scope change, ignore that value and use the neutral default.
3. **JDK scope split.** `jdk.preferred_distribution` governs the BUILD / VALIDATION JDK
   only (Phase 3.0, session-scoped). The application's shipped/declared JDK distribution
   remains do-not-change (Phase 1.5). These are two different JDKs — steering the former
   does not violate the latter.
4. **Registry/mirror redirects preserve substance.** A `container.base_image_registry`
   override changes only WHERE an image is pulled from; it must keep the same base-image
   distribution AND version.
5. **Wrapper commands fall back when absent.** If `build.maven_invocation` names a wrapper
   (`./mvnw`) the project does not contain, fall back to the bare `mvn` command rather than
   failing. (The Maven neutral default is already bare `mvn`; the Gradle neutral default is
   `./gradlew`, so an absent Gradle wrapper is itself the default — treat as neutral.)
6. **Absent configuration → neutral defaults**, and applied overrides are recorded in
   `01-project-assessment.md`.

## Field Reference

| Field | Section | Steers | Neutral default it overrides |
|-------|---------|--------|------------------------------|
| `container.base_image_registry` | Container (shared) | Where base images are pulled from | current base image, registry preserved (same distro/version) — phase2 §2.4 "Dockerfile updates" |
| `container.runtime` | Container (shared) | Container CLI | auto-detected `CONTAINER_CMD` — phase3 "Container Runtime Detection" |
| `deploy.arch_selector` / `deploy.nodepool_label` | Deployment (shared) | ARM64 node selection in manifests | generic `kubernetes.io/arch: arm64`, no nodepool label — phase2 §2.4 "Deployment manifests" |
| `deploy.registry` / `deploy.ingress_convention` | Deployment (shared) | Manifest registry & ingress | existing registry/ingress left unchanged — phase2 §2.4 "Deployment manifests" |
| `ci.system` | CI (shared) | CI vocabulary in the post-transformation note | generic CI/CD wording — SKILL.md "User Responsibility (Post-Transformation)" |
| `jdk.preferred_distribution` / `jdk.discovery_glob` | Java | Build/validation JDK discovery | Corretto-named find glob — phase3 "Session-Scoped Java Switching" |
| `jdk.version_select` | Java | How a JDK major is resolved | `/usr/libexec/java_home -v` (macOS) / find glob (Linux) |
| `jdk.install_hint` | Java | Install command surfaced if no JDK is found | Corretto install block — phase3 "If no compatible version found" |
| `build.maven_invocation` | Java | Maven command | bare `mvn` |
| `build.gradle_invocation` | Java | Gradle command | `./gradlew` |

## Authoring Notes

- Leave a field blank or delete it to use the neutral default — partial configs are fine.
- Keep genuinely private values (internal hostnames, proxies, account-specific labels) in
  your own repo's copy. Never add them to the skill.
