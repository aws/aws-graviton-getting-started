# ARM64 Transformation - Agent Scope Boundaries

## 🎯 Primary Objective
Validate Java application compatibility with AWS Graviton (ARM64) architecture.  
**Focus ONLY on ARM64-specific compatibility issues.**

## Quick Reference: ARM64 Dependency Update Decision Tree

Use this decision tree for EVERY dependency analysis:

```
Is this dependency update required for ARM64 compatibility?
│
├─ Does the dependency contain native code (.so, .dll, .dylib)?
│  ├─ YES → Does current version have ARM64 binaries?
│  │  ├─ NO → ✅ MUST UPGRADE (ARM64 native libraries missing)
│  │  └─ YES → ✅ COMPATIBLE (has ARM64 support)
│  └─ NO (Pure Java) → ✅ COMPATIBLE (pure Java works on all architectures)
│
├─ Does current version FAIL to build on ARM64?
│  ├─ YES → Check why:
│  │  ├─ Missing ARM64 artifacts? → ✅ MUST UPGRADE
│  │  ├─ Architecture detection issue? → ✅ MUST UPGRADE  
│  │  └─ Other reason? → Investigate root cause
│  └─ NO → Continue checking...
│
├─ Does current version FAIL to run on ARM64?
│  ├─ YES → Check why:
│  │  ├─ UnsatisfiedLinkError? → ✅ MUST UPGRADE (native lib issue)
│  │  ├─ Documented ARM64 bug? → ✅ MUST UPGRADE
│  │  └─ Other reason? → Investigate root cause
│  └─ NO → Continue checking...
│
└─ Is the only reason "old version" or "best practice"?
   └─ YES → ❌ OUT OF SCOPE (not an ARM64 issue)

RESULT:
- If no ARM64-specific issue found → Mark COMPATIBLE, do NOT upgrade
- If ARM64-specific issue found → Document evidence and upgrade
```

**Quick Test Questions:**
1. ❓ Will keeping this version cause ARM64 build to fail? 
2. ❓ Will keeping this version cause ARM64 runtime to fail?
3. ❓ Is there documented evidence of ARM64 incompatibility?

If all answers are **NO** → **Do not upgrade** (out of scope)

## ✅ IN SCOPE: What to Fix

### 1. Native Library Issues
- ✅ Dependencies with x86-only `.so`/`.dll`/`.dylib` files
- ✅ Missing ARM64 native library artifacts
- ✅ Example: snappy-java 1.1.1.7 → 1.1.2.2 (1.1.1.7 ships no `Linux/aarch64/libsnappyjava.so`; 1.1.2.2 is the lowest that does)

> ⚠️ **Verify the JAR, never the version number.** Whether a version has an ARM64 binary is a fact about the artifact's contents, not something you can infer from how old the version is. Many libraries added Linux aarch64 support years earlier than people assume: JNA has shipped `linux-aarch64/libjnidispatch.so` since 4.2.0, and snappy-java's `Linux/aarch64/libsnappyjava.so` first appears in **1.1.2.2** (2016-03-29), roughly fifteen releases before the 1.1.4 that is commonly cited. The boundary is exact and narrow, and verified on a Graviton3 instance (c7g, Amazon Linux 2023, `aarch64`): 1.1.2.1 throws `[FAILED_TO_LOAD_NATIVE_LIBRARY] no native library is found for os.name=Linux and os.arch=aarch64`, while 1.1.2.2 loads and completes a compress/uncompress round-trip. Before writing MUST UPGRADE, confirm the *resolved* JAR actually lacks the aarch64 binary: run `scan_archive` from phase1-static-analysis.md §1.2.1 on it and look for an `ARM aarch64` line. A version being "old" is never sufficient evidence.
>
> **When checking a floor, make a missing artifact fail loudly.** `curl` without `--fail` writes the 404 HTML body to the output path, producing a small file that is not a valid archive — and `unzip -l ... | grep aarch64` on it returns empty, which is indistinguishable from a real "no aarch64 binary" result. That is a false MUST UPGRADE. Use `curl -sSL --fail` and check the exit status, or verify the archive first with `unzip -t`, before reading any grep result as evidence. Confirm a version exists at all in `maven-metadata.xml` rather than assuming a gap in a version sequence was published (e.g. snappy-java has `1.1.3-M1`/`1.1.3-M2` milestones but **no released `1.1.3`**).

### 2. Build Tool Artifacts
- ✅ Protoc compiler missing ARM64 executables
- ✅ Build plugins missing ARM64 classifiers
- ✅ Example: protoc 3.3.0 → 3.5.0 (3.3.0 publishes no `linux-aarch_64` exe; 3.5.0 is the lowest that does)

### 3. Architecture Detection
- ✅ Code checking for "amd64" without "aarch64" handling
- ✅ Build plugins not detecting ARM64 architecture
- ✅ Example: os-maven-plugin 1.4.1 → 1.7.0 (aarch64 detection)

### 4. Documented ARM64 Bugs
- ✅ Current version has known ARM64-specific runtime failures
- ✅ Must have issue tracker evidence or release notes
- ✅ Example: "Version X causes crash only on ARM64"

## ❌ OUT OF SCOPE: What NOT to Fix

### 1. General Dependency Modernization
- ❌ "This version is old" → NOT an ARM64 issue
- ❌ "We should use latest" → NOT an ARM64 issue
- ❌ "Deprecated library" → NOT an ARM64 issue
- ❌ Example: JUnit 3.8.1 → 4.13.2 (pure Java, works on ARM64)

### 2. Security Updates
- ❌ CVE fixes or vulnerability patches
- ❌ Example: Log4j 1.2.17 → 2.20.0 (security, not ARM64)

### 3. Feature Upgrades
- ❌ Newer features or better performance
- ❌ API modernization
- ❌ Example: Spring 4.x → 5.x (features, not ARM64)

### 4. Java Version Changes
- ❌ Java 8 → 11 or Java 11 → 17 upgrades
- ❌ JDK distribution changes (OpenJDK → Corretto)
- ❌ Exception: Session-scoped Java switching for build tooling compatibility

### 5. Code Refactoring
- ❌ Code quality improvements
- ❌ Design pattern changes
- ❌ Performance optimizations (except Graviton-specific JVM flags)

## 🔍 Decision Tree: Should I Update This Dependency?

```
For each dependency, ask in order:

1. Does it contain native code?
   NO → Mark COMPATIBLE, do NOT update
   YES → Continue to #2

2. Does current version have ARM64 binaries?
   YES → Mark COMPATIBLE, do NOT update
   NO → Continue to #3

3. Will build FAIL on ARM64 without update?
   NO → Mark COMPATIBLE, do NOT update
   YES → MUST UPGRADE (document evidence)

4. Will runtime FAIL on ARM64 without update?
   NO → Mark COMPATIBLE, do NOT update
   YES → MUST UPGRADE (document evidence)
```

**Simple Rule:** If it builds and runs on ARM64 today → **DO NOT UPDATE**

## 📋 Common Pure Java Libraries (Always ARM64-Compatible)

These are **almost always** ARM64-compatible without updates:

**Testing Frameworks:**
- JUnit (any version - even 3.8.1 from 2004)
- TestNG
- Mockito  
- Hamcrest
- AssertJ

**Logging:**
- Log4j 1.x and 2.x
- SLF4J
- Logback
- Commons-Logging

**Utilities:**
- Commons-Lang
- Commons-Collections
- Commons-IO
- Guava

**Serialization:**
- Jackson
- Gson
- JAXB

**HTTP Clients (Pure Java):**
- Apache HttpClient
- OkHttp (Java parts)

## 🚫 Red Flags: When Agent is Going Off-Scope

**Stop immediately if you see:**
- ❌ "This version is from [old year], should update"
- ❌ "Security vulnerability CVE-XXXX-YYYY"
- ❌ "Best practice to use latest version"
- ❌ "Deprecated API, should modernize"
- ❌ "Better performance in newer version"
- ❌ "More features in latest release"

**Correct responses:**
- ✅ "Version X lacks linux-aarch_64 artifact"
- ✅ "UnsatisfiedLinkError on ARM64 with version X"
- ✅ "Build fails on ARM64: missing native library"
- ✅ "Documented ARM64 crash in issue #XXXX"

## ✅ How to Document Scope Compliance

### For Updates Made:
```markdown
## ARM64-Required Dependency Updates

| Dependency | Old → New | ARM64 Issue | Evidence |
|------------|-----------|-------------|----------|
| protoc | 3.3.0 → 3.5.0 | 3.3.0 publishes no `linux-aarch_64` exe (x86 only) | `mvn` build log shows "Could not find artifact ...:exe:linux-aarch_64"; Central listing for 3.5.0 shows `protoc-3.5.0-linux-aarch_64.exe` |
| snappy-java | 1.1.1.7 → 1.1.2.2 | 1.1.1.7 JAR has no `Linux/aarch64/libsnappyjava.so` | `unzip -l snappy-java-1.1.1.7.jar \| grep aarch64` returns nothing |
```

### For Updates NOT Made:
```markdown
## Dependencies Validated as ARM64-Compatible (No Updates)

| Dependency | Version | Status | Notes |
|------------|---------|--------|-------|
| JUnit | 3.8.1 | ✅ Compatible | Pure Java, works on ARM64. Modernization out of scope. |
| Log4j | 1.2.17 | ✅ Compatible | Pure Java, no ARM64 issues. Security updates out of scope. |
| Commons-Lang | 2.6 | ✅ Compatible | Pure Java library, fully ARM64-compatible. |
```

## 🎓 Learning from Past Mistakes

### Case Study: JUnit 3.8.1

**Initial Analysis (WRONG):**
> "JUnit 3.8.1 is from 2004, mark as MUST UPGRADE for modern Java compatibility"

**Why This Was Wrong:**
- JUnit 3.8.1 is pure Java (no native code)
- It builds successfully on ARM64
- It runs successfully on ARM64 with Java 17
- Being "old" is NOT an ARM64 compatibility issue

**Correct Analysis:**
> "JUnit 3.8.1: Pure Java library, no native dependencies, builds and runs successfully on ARM64. Status: COMPATIBLE. No update required for ARM64 compatibility. Note for user: Consider upgrading to JUnit 4/5 as part of separate modernization effort."

### Case Study: Protoc 3.3.0 (right verdict, wrong target version)

**Analysis (PARTLY WRONG):**
> "Protoc 3.3.0 lacks osx-aarch_64 and linux-aarch_64 artifacts in Maven Central. Build will fail on ARM64 with 'Could not resolve artifact' error. MUST UPGRADE to 3.21.0+ which includes ARM64 executables."

**What Was Right:**
- 3.3.0 genuinely publishes only x86 executables (`linux/osx/windows-x86_32|x86_64`) — no ARM64 at all
- The build WILL fail on Graviton with "Could not resolve artifact ...:exe:linux-aarch_64"
- Verdict MUST UPGRADE is correct, and the reasoning cites a specific missing artifact

**What Was Wrong — the target version:**
- `linux-aarch_64` first appears in **protoc 3.5.0**, not 3.17 or 3.21. Every release from 3.5.0 through 3.16.x already ships it.
- Recommending 3.21.0+ violates the minimality rule (*prefer the lowest version that includes the ARM64 binary*) and drags ~18 minor versions of unrelated change into an ARM64 migration.
- Worse, `protoc` is usually pinned via a shared `${protobuf.version}` property, so an oversized bump also moves `protobuf-java` — a runtime library — turning a compatibility fix into unrequested modernization.
- Citing `osx-aarch_64` alongside `linux-aarch_64` conflates the **macOS** floor (`osx-aarch_64` lands in 3.17.3) with the Linux one, which is what inflates the recommended version. Graviton is Linux: `linux-aarch_64` alone decides the verdict.

**Correct Analysis:**
> "Protoc 3.3.0 publishes no ARM64 executable (`linux-aarch_64` absent; only x86_32/x86_64 for linux/osx/windows). Build fails on Graviton with 'Could not resolve artifact ...:exe:linux-aarch_64'. Status: MUST UPGRADE. Minimum ARM64 version: **3.5.0** — the lowest release publishing `linux-aarch_64`. Note: if this bump moves a shared `${protobuf.version}`, document the resulting `protobuf-java` change as a consequence of the required fix."

**The transferable lesson:** an artifact-based verdict can still carry a wrong *minimum version*. Establish the floor by finding the lowest release that publishes the needed classifier — see the `central_has_classifier` helper in phase1-static-analysis.md §1.3 — rather than reaching for a recent version that obviously has it.

### Case Study: JNA 5.6.0 (verify the JAR, not the version)

**Initial Analysis (WRONG):**
> "JNA 5.6.0 is old and JNA has native code — mark as MUST UPGRADE to a newer version for ARM64."

**Why This Was Wrong:**
- `jna-5.6.0.jar` already bundles `com/sun/jna/linux-aarch64/libjnidispatch.so`, a real ARM aarch64 ELF binary. JNA has shipped it since 4.2.0; earlier releases carry no aarch64 build.
- It loads and runs on Graviton (Linux ARM64) with no change.
- Newer JNA only *adds* `win32-aarch64` (Windows ARM, from 5.7.0) and Apple Silicon builds (an aarch64 slice in the universal `darwin/libjnidispatch.jnilib` from 5.7.0, a separate `darwin-aarch64/` folder from 5.8.0), for local development; neither is relevant to Graviton.
- "Old + has native code" is not evidence of a missing Graviton binary.

**Correct Analysis:**
> "JNA 5.6.0: JAR contains `linux-aarch64/libjnidispatch.so` (verified via `unzip -l` + `file`). Loads on Graviton unmodified. Status: COMPATIBLE. No update required for ARM64. (If the local BUILD host is an Apple-Silicon Mac, 5.6.0 also lacks `darwin-aarch64` — but that affects local dev only, not the Graviton target.)"

**Lesson:** Always inspect the resolved JAR for the `linux/aarch64` binary before deciding. A version number cannot tell you whether the Graviton binary is present.

## 🎯 Success Criteria

**Transformation is successful when:**
1. ✅ Application builds on ARM64 without errors
2. ✅ Application runs on ARM64 without crashes
3. ✅ All tests pass on ARM64
4. ✅ Only ARM64-specific issues were addressed
5. ✅ No scope creep into general modernization

**Transformation has scope creep if:**
1. ❌ Updated dependencies that already worked on ARM64
2. ❌ Fixed security issues unrelated to ARM64
3. ❌ Modernized code for "best practices"
4. ❌ Upgraded Java version unnecessarily
5. ❌ Refactored working code

## 📞 When in Doubt

**Ask yourself:**
- "If I don't make this change, will ARM64 build/runtime fail?"
- "Is there concrete evidence this current version breaks on ARM64?"
- "Am I updating this because it's old, or because ARM64 requires it?"

**If unsure:** Mark as COMPATIBLE and document reasoning. It's better to under-fix than to introduce unnecessary scope creep.

---

**Remember:** This is an ARM64 compatibility validation, not a general dependency modernization project. Stay focused on ARM64-specific issues only.