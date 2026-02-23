# FFmpeg Builder for AWS Graviton

Build optimized FFmpeg packages (RPM/DEB) for AWS Graviton processors and x86_64.

## What is this for?

Getting the best video encoding performance on AWS Graviton requires recent versions of FFmpeg and codec libraries (x264, x265, libaom, SVT-AV1) built with Graviton-optimized compiler flags. Distribution packages are often outdated and miss performance improvements.

This tool makes it easy to build optimized, up-to-date FFmpeg packages with a single command.

## Features

- Single-file Python script for building FFmpeg with common codecs
- Produces native packages (RPM for Amazon Linux, DEB for Ubuntu)
- Optimized for Graviton2/3/4 and x86_64 (AVX2/AVX512)
- Includes x264, x265 (8-bit + 10-bit), AOM, SVT-AV1, and Opus
- Docker-based builds for reproducibility
- Test mode to verify packages work correctly

## Requirements

- Python 3.8+
- Docker
- Git
- ~10GB disk space for sources and build

## Quick Start

```bash
# Generate a config file with detected defaults
./build_ffmpeg.py generate-config

# Edit config if needed
vim ffmpeg_build_config.json

# Build everything (clone, update, build, test)
./build_ffmpeg.py all
```

## Commands

| Command | Description |
|---------|-------------|
| `generate-config` | Create sample config file with host defaults |
| `clone` | Clone all source repositories |
| `update` | Update sources to target commits/branches |
| `build` | Build the package |
| `test` | Test the built package in a fresh container |
| `all` | Run clone, update, build, and test |

## CLI Options

Options can override config file settings:

```bash
./build_ffmpeg.py -d ubuntu-noble -p graviton4 -C clang-latest build
```

| Option | Description |
|--------|-------------|
| `-c, --config` | Config file path (default: ffmpeg_build_config.json) |
| `-d, --distro` | Target distro (overrides config) |
| `-p, --platform` | Target platform (overrides config) |
| `-C, --compiler` | Compiler (overrides config) |
| `-l, --log` | Log file path (includes all docker build output) |
| `--no-log` | Disable automatic logging (see below) |

### Logging

When `--log <path>` is specified, all output including docker build output is written to the given file. When running non-interactively (stdout is not a tty) and `--log` is not specified, a log file is auto-generated in the script directory. Use `--no-log` to disable this automatic behavior.

## Configuration

The config file (`ffmpeg_build_config.json`) supports:

```json
{
  "target_distro": "al2023",
  "compiler": "clang",
  "target_platform": "graviton3",
  "build_type": "release",
  "version": "1.0.0",
  "package_name": "ffmpeg-optimized",
  "repos": { ... },
  "commit_overrides": { "ffmpeg": "n7.0" }
}
```

### Options

- `target_distro`: al2023, ubuntu-jammy, ubuntu-noble, ubuntu-resolute
- `target_platform`: graviton2, graviton3, graviton4, avx2, avx512
- `compiler`: gcc, clang, gcc-latest, clang-latest, or specific versions (see below)
- `build_type`: "release" (latest tags) or "tip" (main branches)
- `commit_overrides`: Pin specific projects to exact commits/tags

Available compilers by distro:
- AL2023: gcc (11), gcc11, gcc14, clang (15), clang15, clang18, clang19
- Ubuntu Jammy: gcc (11), gcc9-12, clang (14), clang11-14
- Ubuntu Noble: gcc (13), gcc9-14, clang (18), clang14-20
- Ubuntu Resolute: gcc (13), gcc9-14, clang (18), clang14-20

Use `gcc-latest` or `clang-latest` to automatically select the newest available version.

## Output

Packages are written to `./output/`:
- Amazon Linux: `ffmpeg-optimized-1.0.0-1.*.rpm`
- Ubuntu: `ffmpeg-optimized_1.0.0_arm64.deb`

The package includes both 8-bit and 10-bit FFmpeg builds:
- `ffmpeg`, `ffprobe` - 8-bit x265
- `ffmpeg-10bit`, `ffprobe-10bit` - 10-bit x265

## Example Workflows

### Build for Graviton4 on Amazon Linux 2023

```bash
./build_ffmpeg.py generate-config
# Edit config: set target_platform to "graviton4"
./build_ffmpeg.py all
```

### Build specific FFmpeg version

```bash
# In config, add:
# "commit_overrides": { "ffmpeg": "n7.0" }
./build_ffmpeg.py all
```

### Build for Ubuntu Noble

```bash
# In config, set:
# "target_distro": "ubuntu-noble"
./build_ffmpeg.py all
```

## Included Codecs

| Codec | Library | Notes |
|-------|---------|-------|
| H.264 | libx264 | |
| H.265/HEVC | libx265 | 8-bit + 10-bit |
| AV1 | libaom | Reference encoder |
| AV1 | SVT-AV1 | Standalone binary only (see note below) |
| Opus | libopus | Audio |

**Note on SVT-AV1:** The package includes the `SvtAv1EncApp` encoder binary but SVT-AV1 is not linked into FFmpeg due to API incompatibilities between recent SVT-AV1 versions and FFmpeg. You can use the standalone encoder directly for AV1 encoding, but cannot access it via FFmpeg's `-c:v libsvtav1` option. For FFmpeg-integrated AV1 encoding, use `-c:v libaom-av1` instead.

## Customization

### Adding a New Library

1. Add repo URL and tag pattern to `build_ffmpeg.py` (see `DEFAULT_REPOS`, `TAG_PATTERNS`)
2. Create `scripts/build-<name>.sh` (copy `build-opus.sh` as template)
3. Add build stage to `Dockerfile`:
   ```dockerfile
   FROM base AS <name>
   COPY sources/<name> sources/<name>
   RUN PREFIX=/usr/local scripts/build-<name>.sh
   ```
4. Add `COPY --from=<name> /usr/local /usr/local` to both ffmpeg stages in `Dockerfile`
5. Add `--enable-lib<name>` to `scripts/build-ffmpeg.sh`

### Adding a New Distro

1. Add image to `DISTRO_IMAGES` in `build_ffmpeg.py`
2. Add compiler mapping to `DISTRO_COMPILERS` in `build_ffmpeg.py`
3. Add dependency function to `scripts/install-dependencies.sh`

## Tested Configurations

Run `./test_matrix.py` to test all distro/compiler combinations. Results are printed to stdout and saved to a timestamped summary file (`test_matrix_<timestamp>_<arch>.log`). Individual build logs with full docker output are written to the `test_logs/` directory.

### aarch64 (Graviton)

| Distro | Compiler | Status | Notes |
|--------|----------|--------|-------|
| al2023 | gcc | ✅ | |
| al2023 | gcc14 | ✅ | |
| al2023 | clang | ✅ | |
| al2023 | clang-latest | ✅ | |
| ubuntu-jammy | gcc | ✅ | |
| ubuntu-jammy | clang | ✅ | |
| ubuntu-jammy | gcc-latest | ✅ | |
| ubuntu-jammy | clang-latest | ✅ | |
| ubuntu-jammy | gcc12 | ✅ | |
| ubuntu-noble | gcc | ✅ | |
| ubuntu-noble | clang | ✅ | |
| ubuntu-noble | gcc-latest | ✅ | |
| ubuntu-noble | clang-latest | ✅ | |
| ubuntu-noble | gcc14 | ✅ | |
| ubuntu-resolute | gcc | ✅ | |
| ubuntu-resolute | clang | ✅ | |
| ubuntu-resolute | gcc-latest | ✅ | |
| ubuntu-resolute | clang-latest | ✅ | |
| ubuntu-resolute | gcc14 | ✅ | |

### x86_64

| Distro | Compiler | Status | Notes |
|--------|----------|--------|-------|
| al2023 | gcc | ✅ | |
| al2023 | clang | ✅ | |
| al2023 | gcc-latest | ✅ | |
| al2023 | clang-latest | ✅ | |
| al2023 | gcc14 | ✅ | |
| ubuntu-jammy | gcc | ✅ | |
| ubuntu-jammy | clang | ✅ | |
| ubuntu-jammy | gcc-latest | ✅ | |
| ubuntu-jammy | clang-latest | ✅ | |
| ubuntu-jammy | gcc12 | ✅ | |
| ubuntu-noble | gcc | ✅ | |
| ubuntu-noble | clang | ✅ | |
| ubuntu-noble | gcc-latest | ✅ | |
| ubuntu-noble | clang-latest | ✅ | |
| ubuntu-noble | gcc14 | ✅ | |
| ubuntu-resolute | gcc | ❌ | aom fails: nasm 3.x incompatible |
| ubuntu-resolute | clang | ❌ | aom fails: nasm 3.x incompatible |
| ubuntu-resolute | gcc-latest | ❌ | aom fails: nasm 3.x incompatible |
| ubuntu-resolute | clang-latest | ❌ | aom fails: nasm 3.x incompatible |
| ubuntu-resolute | gcc14 | ❌ | aom fails: nasm 3.x incompatible |

## License

The build script is provided under the same license as the aws-graviton-getting-started repository.
FFmpeg and included libraries have their own licenses (GPL, LGPL, BSD, etc.).
