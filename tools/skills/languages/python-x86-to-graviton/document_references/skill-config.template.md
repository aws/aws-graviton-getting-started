# Graviton Skill Config — <Team/Org>

> Optional configuration for the Graviton migration skill. Copy this file to
> **`skill-config.md` at your project root** (next to requirements.txt / pyproject.toml) and
> fill in the fields you care about. It steers HOW the transformation runs
> (toolchain, package index, registry, deployment vocabulary) and can NOT widen scope
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

## Python

```
# python.* steers the tools and indexes the transformation uses. It does NOT switch the
# project's package manager. python.interpreter_select picks only the session-scoped
# BUILD / VALIDATION interpreter (Phase 3.0); the project's declared interpreter changes
# only through python.interpreter_bump.
python.package_manager:    <e.g. pip | pip-tools | uv | poetry | conda | pipenv | pdm | hatch>   # pin instead of auto-detecting
python.index_url:          <internal PyPI mirror (simple index URL)>   # probed alongside PyPI; no credentials here
python.extra_index_url:    <additional index the project already uses>
python.interpreter_bump:   never     # never | ask | approved=<3.X>; only when it is the sole path to an aarch64 wheel
python.interpreter_select: <e.g. uv | pyenv | conda | system>
python.install_hint:       <internal install command; surfaced to the user, never auto-run>
python.test_command:       <e.g. python -m pytest -q tests>
```

## Notes

<Free-form: blessed Graviton families, proxy/mirror requirements, anything else the
agent should orient around. e.g. "PyPI reachable only via <proxy>; prefer
the internal mirror above.">
