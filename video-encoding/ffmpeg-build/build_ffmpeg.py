#!/usr/bin/env python3
"""
FFmpeg Builder - Build optimized FFmpeg packages for Graviton and x86_64.
Requirements: Python 3.8+, Docker, git
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "ffmpeg_build_config.json"
SOURCES_DIR = SCRIPT_DIR / "sources"
OUTPUT_DIR = SCRIPT_DIR / "output"

# =============================================================================
# CUSTOMIZATION: Add new libraries here
# Also requires: scripts/build-<name>.sh, Dockerfile stage, build-ffmpeg.sh flag
# =============================================================================
DEFAULT_REPOS = {
    "ffmpeg": "https://git.ffmpeg.org/ffmpeg.git",
    "x264": "https://code.videolan.org/videolan/x264.git",
    "x265": "https://bitbucket.org/multicoreware/x265_git",
    "aom": "https://aomedia.googlesource.com/aom",
    "SVT-AV1": "https://gitlab.com/AOMediaCodec/SVT-AV1.git",
    "opus": "https://github.com/xiph/opus.git",
}

TAG_PATTERNS = {
    "ffmpeg": "n[0-9]*",
    "x264": "*",
    "x265": "[0-9]*",
    "aom": "v[0-9]*",
    "SVT-AV1": "v[0-9]*",
    "opus": "v[0-9]*",
}

# =============================================================================
# CUSTOMIZATION: Add new distros here
# Also requires: install-dependencies.sh function
# =============================================================================
DISTRO_IMAGES = {
    "al2023": "public.ecr.aws/amazonlinux/amazonlinux:2023",
    "ubuntu-jammy": "public.ecr.aws/ubuntu/ubuntu:jammy",
    "ubuntu-noble": "public.ecr.aws/ubuntu/ubuntu:noble",
    "ubuntu-resolute": "public.ecr.aws/ubuntu/ubuntu:resolute",
}

DISTRO_COMPILERS = {
    "al2023": {
        "gcc": "gcc", "gcc11": "gcc", "gcc14": "gcc14",
        "clang": "clang", "clang15": "clang", "clang18": "clang18", "clang19": "clang19",
        "gcc-latest": "gcc14", "clang-latest": "clang19",
    },
    "ubuntu-jammy": {
        "gcc": "gcc", **{f"gcc{v}": f"gcc{v}" for v in range(9, 13)},
        "clang": "clang", **{f"clang{v}": f"clang{v}" for v in range(11, 15)},
        "gcc-latest": "gcc12", "clang-latest": "clang14",
    },
    "ubuntu-noble": {
        "gcc": "gcc", **{f"gcc{v}": f"gcc{v}" for v in range(9, 15)},
        "clang": "clang", **{f"clang{v}": f"clang{v}" for v in range(14, 21)},
        "gcc-latest": "gcc14", "clang-latest": "clang20",
    },
    "ubuntu-resolute": {
        "gcc": "gcc", **{f"gcc{v}": f"gcc{v}" for v in range(9, 15)},
        "clang": "clang", **{f"clang{v}": f"clang{v}" for v in range(14, 21)},
        "gcc-latest": "gcc14", "clang-latest": "clang20",
    },
}


# Known good versions (update after testing)
DEFAULT_VERSIONS = {
    "ffmpeg": "n7.0.2",
    "x264": "4613ac3c15fd75cebc4b9f65b7fb95e70a3acce1",
    "x265": "4.1",
    "aom": "v3.10.0",
    "SVT-AV1": "v4.0.1",  # Built as standalone binary; not linked to FFmpeg due to API incompatibilities
    "opus": "v1.5.2",
}

VALID_PLATFORMS = {"graviton2", "graviton3", "graviton4", "avx2", "avx512"}


def _default_platform():
    return "graviton2" if platform.machine() in ("aarch64", "arm64") else "avx2"


@dataclass
class BuildConfig:
    target_distro: str = "al2023"
    target_platform: str = field(default_factory=_default_platform)
    compiler: str = "clang-latest"
    build_type: str = "release"
    repos: dict = field(default_factory=lambda: DEFAULT_REPOS.copy())
    commit_overrides: dict = field(default_factory=lambda: DEFAULT_VERSIONS.copy())
    version: str = "1.0.0"
    package_name: str = "ffmpeg-optimized"

    def validate(self):
        """Validate configuration values for security and correctness."""
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', self.package_name):
            raise ValueError(f"Invalid package_name: {self.package_name}. Must contain only alphanumeric, underscore, or hyphen.")
        if not re.match(r'^\d+\.\d+\.\d+$', self.version):
            raise ValueError(f"Invalid version: {self.version}. Must be in format X.Y.Z")
        if self.target_platform not in VALID_PLATFORMS:
            raise ValueError(f"Invalid target_platform: {self.target_platform}. Must be one of: {', '.join(sorted(VALID_PLATFORMS))}")
        if self.target_distro not in DISTRO_IMAGES:
            raise ValueError(f"Invalid target_distro: {self.target_distro}. Must be one of: {', '.join(sorted(DISTRO_IMAGES.keys()))}")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        config = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        config.validate()
        return config


def run(cmd, cwd=None, check=True, capture=False):
    print(f"+ {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    if capture:
        r = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
    else:
        # Explicitly pass sys.stdout/stderr so subprocess output follows Python-level redirects (e.g. log files)
        r = subprocess.run(cmd, cwd=cwd, check=check, stdout=sys.stdout, stderr=sys.stderr)
    return r


def check_prerequisites():
    missing = []
    for cmd in ["docker", "git"]:
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
            missing.append(cmd)
    if missing:
        print(f"Error: missing required tools: {', '.join(missing)}")
        sys.exit(1)
    
    # Check if Docker daemon is running
    result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        print("Error: Docker daemon is not running or not accessible")
        sys.exit(1)


def detect_host():
    arch = platform.machine()
    is_arm = arch in ("aarch64", "arm64")
    distro = "al2023"
    if Path("/etc/os-release").exists():
        c = Path("/etc/os-release").read_text()
        if "jammy" in c.lower():
            distro = "ubuntu-jammy"
        elif "noble" in c.lower():
            distro = "ubuntu-noble"
        elif "resolute" in c.lower():
            distro = "ubuntu-resolute"
    return distro, "graviton2" if is_arm else "avx2"


def cmd_generate_config(args):
    distro, plat = detect_host()
    config = BuildConfig(target_distro=distro, target_platform=plat)
    config.validate()
    args.config.write_text(json.dumps(config.to_dict(), indent=2))
    print(f"Generated: {args.config}")


def cmd_clone(args, config):
    SOURCES_DIR.mkdir(exist_ok=True)
    for name, url in config.repos.items():
        dest = SOURCES_DIR / name
        if dest.exists():
            print(f"{name} exists, skipping")
            continue
        run(["git", "clone", url, str(dest)])


def cmd_update(args, config):
    for name in config.repos:
        src = SOURCES_DIR / name
        if not src.exists():
            print(f"Warning: {name} not cloned, skipping")
            continue
        
        try:
            run(["git", "fetch", "--all", "--tags"], cwd=src)
            run(["git", "reset", "--hard"], cwd=src)
            run(["git", "clean", "-fdx"], cwd=src)

            if name in config.commit_overrides:
                target = config.commit_overrides[name]
            elif config.build_type == "tip":
                target = "origin/HEAD"
            else:
                pattern = TAG_PATTERNS.get(name, "*")
                tags = run(["git", "tag", "-l", pattern, "--sort=-v:refname"], cwd=src, capture=True).stdout.strip().split("\n")
                release = [t for t in tags if t and not any(x in t.lower() for x in ["rc", "alpha", "beta", "dev"])]
                if not release:
                    print(f"Warning: no release tags found for {name}, using HEAD")
                    target = "origin/HEAD"
                else:
                    target = release[0]
            
            run(["git", "checkout", target], cwd=src)
        except subprocess.CalledProcessError as e:
            print(f"Error updating {name}: {e}")
            sys.exit(1)


    # Write revisions
    revisions = {"build_time": datetime.now(timezone.utc).isoformat(), "config": config.to_dict(), "projects": {}}
    for name in config.repos:
        src = SOURCES_DIR / name
        if not src.exists():
            continue
        rev = run(["git", "rev-parse", "HEAD"], cwd=src, capture=True).stdout.strip()
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=src, capture=True).stdout.strip()
        desc = run(["git", "describe", "--tags", "--always"], cwd=src, capture=True, check=False).stdout.strip()
        revisions["projects"][name] = {"revision": rev, "branch": branch, "describe": desc}
    (SOURCES_DIR / "revisions.json").write_text(json.dumps(revisions, indent=2))


def cmd_build(args, config):
    OUTPUT_DIR.mkdir(exist_ok=True)
    config.validate()
    base_image = DISTRO_IMAGES[config.target_distro]
    tag = f"ffmpeg-builder-{config.target_distro}"

    # Resolve and validate compiler
    compilers = DISTRO_COMPILERS.get(config.target_distro, {})
    if config.compiler not in compilers:
        print(f"Error: compiler '{config.compiler}' not available on {config.target_distro}")
        print(f"Available: {', '.join(sorted(compilers.keys()))}")
        sys.exit(1)
    resolved_compiler = compilers[config.compiler]

    build_args = [
        "--build-arg", f"BASE_IMAGE={base_image}",
        "--build-arg", f"PKG_NAME={config.package_name}",
        "--build-arg", f"PKG_VERSION={config.version}",
        "--build-arg", f"COMPILER={resolved_compiler}",
        "--build-arg", f"TARGET_PLATFORM={config.target_platform}",
    ]

    run(["docker", "build", "-f", str(SCRIPT_DIR / "Dockerfile"), "-t", tag,
         "--target", "output", "--output", f"type=local,dest={OUTPUT_DIR}",
         *build_args, str(SCRIPT_DIR)])
    print(f"\nPackage built: {OUTPUT_DIR}")


def cmd_test(args, config):
    distro_cfg = DISTRO_IMAGES[config.target_distro]
    is_rpm = "amazon" in distro_cfg

    pkgs = list(OUTPUT_DIR.glob("*.rpm" if is_rpm else "*.deb"))
    if not pkgs:
        print("No package found")
        return False

    pkg = pkgs[0]
    install = f"rpm -ivh /pkg/{pkg.name}" if is_rpm else f"dpkg -i /pkg/{pkg.name} || apt-get install -f -y"

    test_df = f"""FROM {distro_cfg}
COPY {pkg.name} /pkg/{pkg.name}
RUN {install}
RUN ffmpeg -version && ffprobe -version
RUN ffmpeg-10bit -version && ffprobe-10bit -version
RUN x265 --version && x265-10bit --version
RUN ffmpeg -encoders 2>/dev/null | grep -E '(libx264|libx265|libaom)'
RUN command -v SvtAv1EncApp
"""
    (OUTPUT_DIR / "Dockerfile.test").write_text(test_df)
    result = run(["docker", "build", "-f", str(OUTPUT_DIR / "Dockerfile.test"), "-t", "ffmpeg-test", str(OUTPUT_DIR)], check=False)
    print("\n✓ PASSED" if result.returncode == 0 else "\n✗ FAILED")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Build optimized FFmpeg packages")
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("-d", "--distro", help="Target distro (overrides config)")
    parser.add_argument("-p", "--platform", help="Target platform (overrides config)")
    parser.add_argument("-C", "--compiler", help="Compiler (overrides config)")
    parser.add_argument("-l", "--log", type=Path, help="Log file path (default: auto-generate if not a tty)")
    parser.add_argument("--no-log", action="store_true", help="Disable logging even when not a tty")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-config")
    sub.add_parser("clone")
    sub.add_parser("update")
    sub.add_parser("build")
    sub.add_parser("test")
    sub.add_parser("all")

    args = parser.parse_args()

    # Setup logging
    log_file = None
    if not args.no_log:
        if args.log:
            log_file = args.log
        elif not sys.stdout.isatty():
            # Auto-generate log file when not interactive
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            arch = platform.machine()
            distro = args.distro if args.distro else "default"
            log_file = SCRIPT_DIR / f"build_{timestamp}_{distro}_{arch}.log"
    
    if log_file:
        print(f"Logging to: {log_file}", file=sys.stderr)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(log_file, 'w', buffering=1)  # Line buffered
        # Redirect both stdout and stderr to log file
        sys.stdout = log_fd
        sys.stderr = log_fd

    try:
        check_prerequisites()

        if args.command == "generate-config":
            cmd_generate_config(args)
            return

        if args.config.exists():
            config = BuildConfig.from_dict(json.loads(args.config.read_text()))
        else:
            d, p = detect_host()
            config = BuildConfig(target_distro=d, target_platform=p)
            print(f"Using defaults: {d}, {p}")

        # Apply CLI overrides with warnings
        if args.distro:
            if config.target_distro != args.distro:
                print(f"Warning: overriding distro '{config.target_distro}' -> '{args.distro}'")
            config.target_distro = args.distro
        if args.platform:
            if config.target_platform != args.platform:
                print(f"Warning: overriding platform '{config.target_platform}' -> '{args.platform}'")
            config.target_platform = args.platform
        if args.compiler:
            if config.compiler != args.compiler:
                print(f"Warning: overriding compiler '{config.compiler}' -> '{args.compiler}'")
            config.compiler = args.compiler

        if args.command == "clone":
            cmd_clone(args, config)
        elif args.command == "update":
            cmd_update(args, config)
        elif args.command == "build":
            cmd_build(args, config)
        elif args.command == "test":
            success = cmd_test(args, config)
            sys.exit(0 if success else 1)
        elif args.command == "all":
            cmd_clone(args, config)
            cmd_update(args, config)
            cmd_build(args, config)
            success = cmd_test(args, config)
            sys.exit(0 if success else 1)
    finally:
        if log_file and 'log_fd' in locals():
            log_fd.close()



if __name__ == "__main__":
    main()
