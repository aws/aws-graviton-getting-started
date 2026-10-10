# Graviton Skill Config — <Team/Org>

> Optional configuration for the Graviton migration skill. Copy this file to
> **`skill-config.md` at your project root** (next to the solution or project files) and
> fill in the fields you care about. It steers HOW the transformation runs
> (toolchain, target RIDs, registry, deployment vocabulary) and can NOT widen scope
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

## .NET

```
# dotnet.* steers the RIDs, SDK and tests the transformation uses. It does NOT change the
# project's package management, global.json or target frameworks. dotnet.sdk_select picks only
# the session-scoped BUILD / VALIDATION SDK (Phase 3.0); target frameworks change only through
# dotnet.framework_bump, and only when Graviton requires it.
dotnet.target_rids:     <e.g. linux-arm64 | linux-arm64;linux-musl-arm64>
dotnet.framework_bump:  ask     # ask | approved=<tfm, e.g. net10.0> | never
dotnet.sdk_select:      <e.g. installed | install-script | container>
dotnet.install_hint:    <internal install command; surfaced to the user, never auto-run>
dotnet.test_command:    <e.g. dotnet test Fixture.sln --filter Category!=Integration>
```

## Notes

<Free-form: blessed Graviton families, proxy/feed requirements, anything else the
agent should orient around. e.g. "nuget.org reachable only via <proxy>; the internal
feed mirrors it.">
