#!/usr/bin/env python3
"""
Test matrix for FFmpeg builder - tests combinations of distros and compilers.
Outputs results in markdown table format.
"""

import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Import configuration from build_ffmpeg.py
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from build_ffmpeg import DISTRO_COMPILERS

# Generate test matrix: each distro with representative compilers
def generate_test_cases():
    cases = []
    for distro, compilers in DISTRO_COMPILERS.items():
        # Test default gcc and clang
        if "gcc" in compilers:
            cases.append((distro, "gcc"))
        if "clang" in compilers:
            cases.append((distro, "clang"))
        # Test latest versions
        if "gcc-latest" in compilers:
            cases.append((distro, "gcc-latest"))
        if "clang-latest" in compilers:
            cases.append((distro, "clang-latest"))
        # Test one specific version if available
        specific_gcc = [c for c in compilers if c.startswith("gcc") and c not in ("gcc", "gcc-latest")]
        if specific_gcc:
            cases.append((distro, specific_gcc[-1]))  # Use highest version
    return cases

TEST_CASES = generate_test_cases()

def run_test(distro, compiler, log_dir):
    # Create individual log file for each test
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_file = log_dir / f"build_{timestamp}_{distro}_{compiler}.log"
    cmd = ["./build_ffmpeg.py", "-d", distro, "-C", compiler, "--log", str(log_file), "all"]
    result = subprocess.run(cmd)
    return result.returncode == 0

def main():
    arch = platform.machine()
    results = []
    start = datetime.now()
    
    # Generate log filename with timestamp and arch
    timestamp = start.strftime('%Y%m%d-%H%M%S')
    log_dir = Path("test_logs")
    log_dir.mkdir(exist_ok=True)
    log_file = Path(f"test_matrix_{timestamp}_{arch}.log")
    
    print(f"Running tests on {arch}...")
    print(f"Individual build logs in: {log_dir}/")
    print(f"Summary log: {log_file}\n")
    
    for distro, compiler in TEST_CASES:
        print(f"Testing: {distro} + {compiler}...")
        passed = run_test(distro, compiler, log_dir)
        results.append((distro, compiler, passed))
        status = "PASS" if passed else "FAIL"
        print(f"  {status}")
    
    elapsed = datetime.now() - start
    
    # Generate markdown output
    output = []
    output.append(f"## Test Results ({arch})")
    output.append(f"")
    output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Duration: {elapsed}")
    output.append(f"")
    output.append(f"| Distro | Compiler | Status | Notes |")
    output.append(f"|--------|----------|--------|-------|")
    for distro, compiler, passed in results:
        status = "✅" if passed else "❌"
        output.append(f"| {distro} | {compiler} | {status} | |")
    
    passed_count = sum(1 for _, _, p in results if p)
    output.append(f"")
    output.append(f"**Summary:** {passed_count}/{len(results)} passed")
    
    # Write to log file and stdout
    content = "\n".join(output)
    log_file.write_text(content)
    print(content)
    
    if passed_count < len(results):
        sys.exit(1)

if __name__ == "__main__":
    main()
