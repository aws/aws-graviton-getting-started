# Skill File Index

* "SKILL.md": "Main entry point (Agent Skills format). Contains scope guardrails, entry/exit criteria, transformation workflow overview with phase routing, test failure handling, and documentation output mapping. Read this first."

* "POWER.md": "Main entry point (Kiro format). Same content as SKILL.md with Kiro-specific frontmatter (displayName, keywords, author)."

* "phases/phase1-static-analysis.md": "Detailed steps for Phase 1: project structure analysis, native library validation (bundled and runtime-extracted .so files), tiered FAIL/WARN/PASS policy, dependency ARM64 compatibility analysis including transitive dependencies, Maven Central classifier verification for plugin-resolved build-tool artifacts (the central_has_classifier helper, plus verified protoc floors), architecture-specific code detection, and Java version check."

* "phases/phase2-resolution.md": "Detailed steps for Phase 2: native library resolution (cross-compilation or fallback), dependency updates for MUST UPGRADE items only (Maven dependencyManagement and Gradle resolutionStrategy patterns for transitive deps), architecture detection code updates, Dockerfile platform annotations, and version-gated Graviton JVM flag configuration."

* "phases/phase3-validation.md": "Detailed steps for Phase 3: Java runtime alignment for annotation processor compatibility (session-scoped only), build validation strategy with INFRA/ARM64/PRE-EXISTING failure classification, container and host-based validation, functional testing, startup checks, and summary generation."

* "document_references/agent-scope-boundaries.md": "CRITICAL guardrails. Decision tree for every dependency analysis, IN SCOPE vs OUT OF SCOPE definitions, common pure Java libraries (always compatible), red flags for scope creep, and case studies (JUnit wrong vs Protoc correct). MUST be read before starting."

* "document_references/documentation-standards.md": "Defines the mandatory graviton-validation/ output folder structure, canonical filenames (00-summary.md through 06-build-test-results.md plus raw/), required sections for each file, and mapping from transformation steps to output files. Read before Phase 1."

* "document_references/skill-configuration.md": "Optional. Defines the skill-config.md configuration teams use to steer build/validation JDK, build command, container registry, and deployment vocabulary without forking the skill. Includes the field reference and precedence rules (configuration steers HOW, never widens scope; shipped JDK distribution stays unchanged), plus the shared vs per-language section layout. Read before Phase 1 only if a skill-config.md is present."

* "document_references/skill-config.template.md": "Copyable template for the optional skill configuration. Teams copy it to skill-config.md at their own project root and fill in shared (container/deployment/CI) and per-language (Java) preferences. Not read during a run — it is the authoring starting point for skill-configuration.md."
