# ARM64 Transformation - Agent Scope Boundaries

## 🎯 Primary Objective
Validate Python application compatibility with AWS Graviton (ARM64) architecture.  
**Focus ONLY on ARM64-specific compatibility issues.**

## Quick Reference: ARM64 Dependency Update Decision Tree

Use this decision tree for EVERY dependency analysis (every resolved pin, direct and transitive; the wheel checks are defined in [wheel-verification.md](wheel-verification.md)):

```
Is this dependency update required for ARM64 compatibility?
│
├─ Does the dependency contain native code (compiled extension modules, bundled .so files)?
│  ├─ YES → Does current version have an aarch64 wheel for this interpreter and the target's libc?
│  │  ├─ NO → Does a later version have one?
│  │  │  ├─ YES → ✅ MUST UPGRADE (to the LOWEST such version)
│  │  │  └─ NO → Check why (wheel-verification.md sections 5 to 7):
│  │  │     ├─ Wheels only for another cp tag? → One interpreter decision for all pins (Phase 1.5)
│  │  │     ├─ Source build works on aarch64? → ✅ COMPATIBLE (build prerequisites documented;
│  │  │     │     confirm the build in Phase 3)
│  │  │     ├─ x86-only by nature? → ✅ MUST UPGRADE (substitute; user confirms)
│  │  │     └─ More than one applies (pygeos: a source build or a successor package)?
│  │  │           → CHECK: user decision with the options (Phase 2.2); the label follows the choice
│  │  └─ YES → ✅ COMPATIBLE (has ARM64 support)
│  └─ NO (Pure Python: py3-none-any wheel or pure-Python sdist) → ✅ COMPATIBLE (pure Python works on all architectures)
│
├─ Does current version FAIL to install or build on ARM64?
│  ├─ YES → Check why:
│  │  ├─ Missing aarch64 wheel? → ✅ MUST UPGRADE
│  │  ├─ Hash lock lists only x86_64 hashes? → ✅ MUST UPGRADE (regenerate the lock)
│  │  ├─ Wheel needs a newer glibc than the target? → ✅ MUST UPGRADE (user decision: older
│  │  │     wheel, distro package or newer OS)
│  │  ├─ Architecture detection issue? → ✅ MUST UPGRADE
│  │  └─ Other reason? → Investigate root cause
│  └─ NO → Continue checking...
│
├─ Does current version FAIL to run on ARM64?
│  ├─ YES → Check why:
│  │  ├─ ImportError or OSError loading a native library? → ✅ MUST UPGRADE (native lib issue)
│  │  ├─ Documented ARM64 bug (NumPy < 1.21.1, SciPy < 1.7.2)? → ✅ MUST UPGRADE
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
1. ❓ Will keeping this version cause ARM64 install or build to fail?
2. ❓ Will keeping this version cause ARM64 runtime to fail?
3. ❓ Is there documented evidence of ARM64 incompatibility?

If all answers are **NO** → **Do not upgrade** (out of scope)

## ✅ IN SCOPE: What to Fix

### 1. Native Library Issues
- ✅ A pinned version with an x86_64 wheel and no aarch64 wheel, where a later version restores it. Example from the fixture used to build this skill: `blosc2==0.6.3` has `blosc2-0.6.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` and no aarch64 file; `0.6.4` is the lowest version with `blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`. Fix: `blosc2==0.6.4`, not `4.x`.
- ✅ Packages that are x86-only by construction and have an aarch64-capable substitute. Example: `mkl`, `intel-openmp`, `tensorflow-intel`, `tfx-bsl` have no Linux aarch64 file in any release on PyPI (tfx-bsl 1.21.0 has macOS arm64 wheels only, which do not help Graviton). For `mkl` pulled in as a NumPy accelerator, the substitute is the default OpenBLAS-backed NumPy wheel ([python.md section 2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#2-scientific-and-numerical-application-numpy-scipy-blas-etc)). Substitutions change behaviour, so the user confirms before the skill applies them.
- ✅ Native code tagged for aarch64 that fails on the target OS: wheels that all need a newer glibc than the target's (a `manylinux_2_28` wheel on Lambda `python3.11`), no `musllinux` aarch64 wheel for an Alpine target, or a package that aborts on 64KB pages (polars 0.20.20 and the earlier releases tested, on AlmaLinux 8). Fix: the lowest version that works on the target OS, verified there (polars 0.20.21). When no version does, the OS, base image or Lambda runtime is the user decision ([wheel-verification.md](wheel-verification.md) section 7; a runtime change also changes the interpreter, so it follows `python.interpreter_bump`).
- ✅ Committed native files built for x86_64 (the Phase 1.2.1 scan reports `e_machine 62 (x86-64)`, whatever the file is named) with no aarch64 build next to them, including executables, vendored `site-packages`, vendored wheels and Lambda layers.
- ✅ `ctypes.CDLL` / `cffi` loads of hard-coded x86 library paths.

> **Verify the wheel, never the version number.** Whether a version has an aarch64 wheel is a fact about the files published for that version and interpreter. It is not implied by age (numpy 1.19.0 from 2020 has aarch64 wheels; pygeos 0.14 from 2022 has none), by the previous version having one (blosc2 0.3.1 through 0.6.3 have none although 0.3.0 did), or by the package being "popular". Run the probe in [wheel-verification.md](wheel-verification.md) and quote the filename or the `from versions:` list.

### 2. Build Tool Artifacts
- ✅ Build-time binaries outside the dependency tree that scripts or Dockerfiles download for x86 only, such as a `tool-linux-amd64` release asset in a deploy script (phase 1.3 "Build-Time Binaries Outside the Dependency Tree").
- ✅ Extension modules whose build flags or sources are x86-only: `-mavx2`, `-mavx512*`, `-msse4*`, `-march=haswell` and similar in `setup.py`/`setup.cfg`/`pyproject.toml`/`CMakeLists.txt`/`Cargo.toml` build scripts; `#include <immintrin.h>`, `<xmmintrin.h>`, `<emmintrin.h>` or inline x86 assembly without an `#ifdef __x86_64__` guard. Fix: guard or replace with a portable path; build on aarch64 in Phase 3. `-march=native` is in scope only when the build happens on x86 and the artefact ships to Graviton.
- ✅ Native code the project builds with flags for a newer Graviton generation than the oldest it deploys to (`-mcpu=native` on a Graviton4 build host stops with `Illegal instruction` on Graviton2; phase 2.5), and vendored aarch64 objects linked for 4KB pages when the target uses 64KB pages (phase 1.2.1).
- ✅ Example: the fixture's `setup.py` passed `-mavx2 -march=haswell` on every architecture, so the aarch64 build stopped at `unrecognized command-line option`; guarding the flags with `platform.machine()` fixed it (phase 2.4).

### 3. Architecture Detection
- ✅ `platform.machine() == "x86_64"`, `platform.processor()`, `os.uname().machine`, `platform.architecture()`, `sys.maxsize` tricks, or `"amd64"`/`"x86_64"` string literals that select code paths, binaries or download URLs with no `aarch64`/`arm64` branch. Same in shell scripts (`uname -m`), Makefiles and CI files that the deployment runs.
- ✅ Example: the fixture's `app/service.py` chose its native library by comparing `platform.machine()` with `x86_64` and `AMD64`, with no aarch64 branch (phase 1.4).

### 4. Documented ARM64 Bugs
- ✅ The repo documents that OpenBLAS between 0.3.9 and 0.3.17 had data-precision and correctness fixes for aarch64, and that NumPy 1.21.1 and SciPy 1.7.2 are the first releases carrying OpenBLAS 0.3.17 ([python.md section 2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#2-scientific-and-numerical-application-numpy-scipy-blas-etc)). A NumPy or SciPy pin below those floors installs on Graviton but is a correctness risk: MUST UPGRADE, target exactly 1.21.1 / 1.7.2 (or the lowest version that also has a wheel for the project's cp tag, whichever is higher; numpy's first cp311 aarch64 wheel is 1.23.2).
- ✅ Other packages: only with a linked upstream issue or release note that names aarch64/arm64. "It crashed once" is not evidence.

### 5. Lock Files
- ✅ Hash-locked requirements generated from x86 wheels (`--require-hashes` fails with `THESE PACKAGES DO NOT MATCH THE HASHES`). Fix: regenerate so the aarch64 wheel hashes are present ([package-manager-mapping.md](package-manager-mapping.md)).
- ✅ Architecture-specific conda explicit files (`# platform: linux-64`). Fix: `conda-lock` with `-p linux-aarch64`, or re-export on the target.

### 6. Deployment Configuration
- ✅ Dockerfiles that pin `--platform=linux/amd64`, an amd64 image digest, or run `pip install` in a `--platform=$BUILDPLATFORM` stage and copy the result into the runtime image (wheels are architecture-specific; see phase 2.4).
- ✅ Lambda functions and layers with x86 binaries where the project ships the SAM/CloudFormation template (`Architectures: [arm64]` plus an arm64 layer build).
- ✅ Kubernetes node selection only when the project already ships manifests, and only the node-selection, registry and ingress lines.
- ✅ ECS `cpuArchitecture`, EKS `amiType` and AMI IDs, only in files the project ships (phase 1.4). Instance types are recorded as a user decision: choosing the Graviton type is sizing.

## ❌ OUT OF SCOPE: What NOT to Fix

### 1. General Dependency Modernization
- ❌ "This version is old" → NOT an ARM64 issue
- ❌ "We should use latest" → NOT an ARM64 issue
- ❌ "Deprecated library" → NOT an ARM64 issue
- ❌ Example: `six==1.11.0` from 2017 (pure Python, `py2.py3-none-any`; runs on aarch64 unchanged)

### 2. Security Updates
- ❌ CVE fixes or vulnerability patches
- ❌ Example: a CVE in a pinned pure-Python package (not an architecture issue; mention it once for the user)

### 3. Feature Upgrades
- ❌ Newer features or better performance
- ❌ API modernization
- ❌ Example: Django 3 to 5, pandas 1 to 2, "pygeos is deprecated, migrate to shapely 2" (behaviour changes the user did not ask for; for pygeos the skill documents the shapely option and does not perform the API migration)

### 4. Python Version Changes
- ❌ Python 3.9 → 3.11 upgrades "because 3.9 is end of life" (governed by `python.interpreter_bump`, default never; the `>= 3.11` recommendation from python.md is recorded as a RECOMMENDED UPGRADE with the live end-of-life date)
- ❌ Changes of interpreter source (distribution package, python.org build, conda, uv-managed build)
- ❌ Exception: session-scoped Python switching for validation (Phase 3.0), and a bump that `python.interpreter_bump` allows because it is the only path to an aarch64 wheel, decided once for the whole dependency set (phase 1.5)

### 5. Code Refactoring
- ❌ Code quality improvements (typing, formatting)
- ❌ Design pattern changes
- ❌ Performance optimizations (except documented Graviton runtime settings, which are recorded in `05-runtime-configuration.md` and never applied: setting `OMP_NUM_THREADS` or `DNNL_DEFAULT_FPMATH_MODE` in the Dockerfile stays a recommendation for the team to apply and measure)

### 6. Tooling and Platform Changes
- ❌ Switching package managers or indexes (pip to uv, Poetry to pip, PyPI to a mirror): a tooling choice, not compatibility
- ❌ Base image distribution or version changes (`python:3.11-slim` to `python:3.12-alpine`): they change glibc, interpreter and ABI at once. The exception is the user-decision path in wheel-verification.md section 7 (glibc too old), which the skill documents but does not apply
- ❌ Web server, worker model or async framework changes (gunicorn to uvicorn): no repo-documented Graviton requirement
- ❌ `.gitignore`, `.dockerignore` or CI pipeline edits: phrased as a recommendation only (SKILL.md "User Responsibility")
- ❌ SDK credential changes after an AMI change: the [EC2 User Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html#use-a-supported-sdk-version-for-imdsv2) lists botocore 1.13.25 (boto3 1.12.6) as the minimum for IMDSv2. Executed on Amazon Linux 2023 with IMDSv2 required: botocore 1.13.22 found no instance-role credentials and 1.13.23 found `iam-role`; 1.13.25 added the handling of an HTTP 405 from the metadata service ("Add 405 case to metadata fetching logic" in botocore's changelog). Amazon Linux 2023 AMIs require IMDSv2 by default. Not an architecture issue; when the migration also moves to such an AMI, note it once in `05-runtime-configuration.md`

## 🔍 Decision Tree: Should I Update This Dependency?

```
For each dependency, ask in order:

1. Does it contain native code (a platform wheel, or an sdist with compiled sources)?
   NO → Mark COMPATIBLE, do NOT update
   YES → Continue to #2

2. Does current version have an aarch64 wheel for this interpreter and the target's libc?
   YES → Mark COMPATIBLE, do NOT update
   NO → Continue to #3

3. Will install or build FAIL on ARM64 without update?
   NO → Mark COMPATIBLE, do NOT update (for example, the sdist builds on aarch64)
   YES → MUST UPGRADE (document evidence)

4. Will runtime FAIL on ARM64 without update?
   NO → Mark COMPATIBLE, do NOT update
   YES → MUST UPGRADE (document evidence)
```

**Simple Rule:** If it installs and runs on ARM64 today → **DO NOT UPDATE**

## 📈 Recommendations: Validation Ladder

A recommendation (a RECOMMENDED UPGRADE or a runtime setting) may be recorded only with its evidence level. Nothing below level A is recommended by default.

| Level | Evidence | Handling |
|---|---|---|
| **A** | Documented in this repository with a mechanism (file and section cited) | Record in `05-runtime-configuration.md` as a recommendation with the citation |
| **B** | Upstream release note, changelog or published benchmark that names aarch64/arm64/Graviton | Record with the link, labelled "upstream-claimed, measure before adopting" |
| **C** | No written source | Omit. If the user asks, say it is unverified |

A-level sources available in this repository: BLAS threading (`OMP_NUM_THREADS`, `BLIS_NUM_THREADS`) and BLIS as an alternative BLAS in [python.md sections 2.2 and 2.6](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#2-scientific-and-numerical-application-numpy-scipy-blas-etc); PyTorch runtime environment (`DNNL_DEFAULT_FPMATH_MODE=BF16` gated on `bf16` in `/proc/cpuinfo`, `LRU_CACHE_CAPACITY=1024`, `THP_MEM_ALLOC_ENABLE=1`, the OMP thread formula, `torch.compile`, channels-last) in [pytorch.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/pytorch.md); TensorFlow `TF_ENABLE_ONEDNN_OPTS=1` for versions before 2.14 and thread-pool settings in [tensorflow.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/tensorflow.md); ONNX Runtime 1.17+ BF16 session option in [onnx.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/onnx.md); interpreter `>= 3.11` in [python.md section 1.2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#12-recommended-versions); `-mcpu` compiler flags for in-repo extensions in [c-c++.md](https://github.com/aws/aws-graviton-getting-started/blob/main/c-c++.md) and the README processor table.

## 📋 Common Pure Python Libraries (Always ARM64-Compatible)

These publish only `none-any` wheels on PyPI (latest release at the time of writing): pytest, six, attrs, requests, urllib3, idna, certifi, click, jinja2, flask, django, fastapi, boto3, botocore, python-dateutil, pytz, packaging, typing-extensions, pydantic.

Two traps in that list:

- **Pure facade, native transitive.** `pydantic` is pure, but it depends on `pydantic-core`, which ships platform wheels (aarch64 present). The transitive gets its own verdict; the probe over the resolved tree catches it.
- **Native with a pure fallback.** `sqlalchemy`, `charset-normalizer` and `wrapt` publish both `none-any` and platform wheels; `pyyaml`, `markupsafe`, `greenlet` publish platform wheels only but build from source anywhere. All have aarch64 wheels today. If a *pinned* version lacks one, the pure fallback or sdist build is COMPATIBLE unless the project depends on the accelerated path for performance (then it is an improvement note, not a blocker).

Do not extend the list from memory. A package is pure when its files list shows only `none-any` wheels or its sdist contains no compiled sources (wheel-verification.md section 5).

## 🚫 Red Flags: When Agent is Going Off-Scope

Stop if you are about to write any of these as the *reason* for a change:

- "This version is from 20XX"
- "CVE-XXXX-YYYY"
- "Best practice", "modern", "deprecated", "the maintainers recommend"
- "Newer version is faster" (without a repo or upstream aarch64 source; and even then it is an improvement, not a change)
- "Python 3.X is end of life" (unless `python.interpreter_bump` allows it, and then only when the bump is the sole path to an aarch64 wheel)
- "While I am here"

Correct reasons look like: "no `cp311` aarch64 wheel for 0.6.3; 0.6.4 ships one (filename)", "the native scan reports `e_machine 62 (x86-64)` and no aarch64 build", "`--require-hashes` fails on aarch64: Expected sha256 666dbf..., Got 7ab554...", "`platform.machine()` compares to `x86_64` only at service.py:19", "python.md section 2 documents the OpenBLAS 0.3.17 correctness floor".

## ✅ How to Document Scope Compliance

### For Updates Made:
```markdown
## ARM64-Required Dependency Updates

| Dependency / file | Change | Graviton issue | Evidence |
|---|---|---|---|
| blosc2 | 0.6.3 to 0.6.4 | no cp311 aarch64 wheel at 0.6.3 | `pip download --platform manylinux_2_17_aarch64 ... blosc2==0.6.3` -> `from versions: 0.6.4, ...`; 0.6.4 wheel `blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl` |
| requirements-locked.txt | add aarch64 hashes | lock carried x86_64 hashes only | `--require-hashes` dry run on aarch64: `Expected sha256 666dbf... Got 7ab554...` |

```

### For Updates NOT Made:
```markdown
## Dependencies Validated as ARM64-Compatible (No Updates)

| Dependency | Version | Basis |
|---|---|---|
| six | 1.11.0 | `six-1.11.0-py2.py3-none-any.whl`; pure Python. Modernisation out of scope |
| docopt | 0.6.2 | sdist only; no compiled sources; builds anywhere |
| numpy | 1.26.4 | `numpy-1.26.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`; above the 1.21.1 correctness floor |
```

## 🎓 Learning from Past Mistakes

Each case comes from the evidence gathered while building this skill (PyPI files lists and pip probes). Reproduce any of them with the commands in wheel-verification.md.

### Case Study: numpy 1.20.3 (the floor is per interpreter)

**Initial Analysis (WRONG):**
> "numpy ships aarch64 wheels since 1.19.0 (python.md), so `numpy==1.20.3` is fine for our Python 3.11 service."

**Why This Was Wrong:**
- 1.19.0 has aarch64 wheels for cp36-cp38 only.
- The lowest numpy with a cp311 aarch64 wheel is 1.23.2.
- On Python 3.11, `numpy==1.20.3` has no wheel for *either* architecture and would build from source (and 1.20.3 is also below the 1.21.1 correctness floor).

**Correct Analysis:**
> "`numpy==1.20.3` on Python 3.11: no cp311 wheel on any platform; below the documented 1.21.1 OpenBLAS floor. MUST UPGRADE. Minimum: 1.23.2 (lowest release with `numpy-1.23.2-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`), which also satisfies the correctness floor."

### Case Study: pygeos 0.14 and blosc2 0.6.3 (availability is not monotonic)

**Initial Analysis (WRONG):**
> "pygeos 0.14 has no aarch64 wheel; bump to the latest."

**Why This Was Wrong:**
- pygeos published aarch64 wheels up to 0.13 and dropped them in 0.14, its final release; there is no later version.
- 0.13 has no cp311 wheel on any platform, so downgrading does not help a Python 3.11 project either.

**Correct Analysis:**
> "`pygeos==0.14`: no aarch64 wheel; no later release exists; 0.13 has aarch64 wheels for cp36-cp310 only; the PyPI description says PyGEOS was merged into Shapely 2.0. CHECK, user decision (User Decisions Pending in the report): (a) COMPATIBLE through a source build of the 0.14 sdist on Graviton against the distribution's GEOS; on current toolchains this needs `setuptools<82` as a build constraint (its setup.py imports `pkg_resources`) and, with gcc 14, `CFLAGS=-Wno-error=incompatible-pointer-types`, on every architecture, and the build is confirmed natively in Phase 3 (under emulation the compiler crashed); or (b) MUST UPGRADE by substitution: move to `shapely>=2.0` (2.0.0 is the first release with cp311 Linux aarch64 wheels), an API change outside this skill. Not applied automatically."

**Lesson:** The same non-monotonic shape appears in blosc2 (aarch64 at 0.2.0 and 0.3.0, none from 0.3.1 to 0.6.3, back at 0.6.4), which is why the fix for `blosc2==0.6.3` is `0.6.4` and why "the previous release had one" proves nothing.

### Case Study: mkl (x86-only by nature)

**Initial Analysis (WRONG):**
> "mkl has no aarch64 wheel; wait for the maintainers / pin an older version."

**Why This Was Wrong:**
- Intel MKL targets Intel CPUs; no release has an aarch64 file.
- Its transitives (`intel-openmp`, `tbb`) are the same.
- The project's numpy already uses OpenBLAS on Graviton (the fixture's conda probe resolved `numpy=1.26.4` against `libopenblas` on `linux-aarch64`).

**Correct Analysis:**
> "`mkl==2026.1.0` and its transitives have no Linux aarch64 file in any release (PyPI files list). MUST UPGRADE: remove `mkl` after confirming nothing imports it directly (grep for `import mkl`); NumPy/SciPy wheels on aarch64 use OpenBLAS ([python.md section 2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#2-scientific-and-numerical-application-numpy-scipy-blas-etc)). Awaiting user confirmation."

### Case Study: docopt 0.6.2 (sdist is fine, do nothing)

**Initial Analysis (WRONG):**
> "docopt 0.6.2 has no wheel at all; replace it with a maintained fork."

**Why This Was Wrong:**
- docopt is pure Python; its sdist contains no compiled sources and installs on any architecture in seconds.
- The wheel tester lists it as "build required" and passing.

**Correct Analysis:**
> "`docopt==0.6.2`: sdist only, pure Python (no C/C++/Cython/Rust sources). COMPATIBLE. Fork or replacement is out of scope."

### Case Study: the false FAIL (glibc, pip age, mirror)

**Initial Analysis (WRONG):**
> "`confluent-kafka==2.1.0` has no aarch64 wheel: pip reports `(from versions: none)` on the target."

**Why This Was Wrong:**
- Three situations produce the same `No matching distribution found ... (from versions: none)` as a genuinely missing wheel:
  - the target glibc is older than the wheel's `manylinux_2_N` tag (AL2's 2.26 rejects `manylinux_2_28` wheels, so `confluent-kafka==2.1.0` fails there although its aarch64 wheel exists)
  - pip on the target predates the tag (19.3 for `manylinux2014`, 20.3 for `manylinux_2_N`)
  - the configured index is a mirror without the aarch64 file

**Correct Analysis:**
> "Check `pip --version`, `pip debug --verbose`, and the index URL before writing MUST UPGRADE: none of the three is a dependency finding, and a mirror gap is INFRA."

## 🎯 Success Criteria

**Transformation is successful when:**
1. ✅ Application installs on ARM64 without errors (from wheels or documented source builds)
2. ✅ Application imports and runs on ARM64 without crashes
3. ✅ All tests pass on ARM64
4. ✅ Only ARM64-specific issues were addressed
5. ✅ No scope creep into general modernization
6. ✅ Every recommendation is recorded with its evidence level, and none was applied

**Transformation has scope creep if:**
1. ❌ Updated dependencies that already worked on ARM64
2. ❌ Fixed security issues unrelated to ARM64
3. ❌ Modernized code for "best practices"
4. ❌ Upgraded Python version unnecessarily (outside `python.interpreter_bump`)
5. ❌ Refactored working code
6. ❌ Switched the package manager, index, base image or framework
7. ❌ Applied runtime tuning instead of documenting it

## 📞 When in Doubt

**Ask yourself:**
- "If I don't make this change, will the ARM64 install, import or runtime fail?"
- "Is there concrete evidence this current version breaks on ARM64 (a probe result, a wheel filename, an error message)?"
- "Am I updating this because it's old, or because ARM64 requires it?"

**If unsure:** Mark as COMPATIBLE and document reasoning. It's better to under-fix than to introduce unnecessary scope creep.

---

**Remember:** This is an ARM64 compatibility validation, not a general dependency modernization project. Stay focused on ARM64-specific issues only.
