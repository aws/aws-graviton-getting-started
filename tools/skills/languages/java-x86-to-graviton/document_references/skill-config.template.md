# Graviton Skill Config — <Team/Org>

> Optional configuration for the Graviton migration skill. Copy this file to
> **`skill-config.md` at your project root** (next to pom.xml / build.gradle) and
> fill in the fields you care about. It steers HOW the transformation runs —
> toolchain, registry, deployment vocabulary — and can NOT widen scope
> (`agent-scope-boundaries.md` always binds). Leave a field blank or delete it to
> fall back to the skill's neutral default.
>
> Sections are grouped as shared (apply to any language) and per-language. A project
> that only uses one language keeps just that language's section.
>
> Full schema and precedence rules: `document_references/skill-configuration.md`.

## Container (shared)

```
# Internal mirror of the SAME base-image distribution + version already in use.
# Redirecting the source is in scope; changing the distro/version is NOT.
container.base_image_registry: <internal-mirror/namespace>
container.runtime:             <e.g. finch | docker | nerdctl>   # pin instead of auto-detecting
```

## Deployment (shared)

```
# Conventions for Phase 2.4 manifest edits (node selection, registry, ingress).
deploy.arch_selector:      <e.g. kubernetes.io/arch=arm64>
deploy.nodepool_label:     <your cluster's ARM64 nodepool/label>
deploy.registry:           <internal application image registry>
deploy.ingress_convention: <ingress class or annotation>
```

## CI (shared)

```
ci.system: <internal CI system>   # vocabulary for the post-transformation CI note;
                                   # the skill makes no CI changes itself
```

## Java

```
# jdk.* selects the BUILD / VALIDATION environment (Phase 3.0, session-scoped).
# It does NOT change the application's declared/shipped runtime (Phase 1.5 — do-not-change).
jdk.preferred_distribution: <e.g. Amazon Corretto | Eclipse Temurin | Azul Zulu>
jdk.discovery_glob:         <e.g. /Library/Java/JavaVirtualMachines/*-17.jdk>
jdk.version_select:         <e.g. /usr/libexec/java_home -v {major}>
jdk.install_hint:           <internal install command — surfaced to the user, never auto-run>

build.maven_invocation:     ./mvnw      # prefer the wrapper; falls back to mvn if absent
build.gradle_invocation:    ./gradlew
```

## Notes

<Free-form: blessed Graviton families, proxy/mirror requirements, anything else the
agent should orient around. e.g. "Maven Central reachable only via <proxy>; prefer
the internal mirror above.">
