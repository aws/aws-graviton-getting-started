#!/bin/bash
# Setup compiler environment variables based on COMPILER setting
set -eu

COMPILER=${COMPILER:-gcc}
TARGET_PLATFORM=${TARGET_PLATFORM:-}

# Set compiler (alternatives/symlinks created by install-dependencies.sh)
case "$COMPILER" in
    gcc)
        CC=gcc
        CXX=g++
        ;;
    gcc[0-9]*)
        ver="${COMPILER#gcc}"
        CC=gcc-${ver}
        CXX=g++-${ver}
        ;;
    clang)
        CC=clang
        CXX=clang++
        ;;
    clang[0-9]*)
        ver="${COMPILER#clang}"
        CC=clang-${ver}
        CXX=clang++-${ver}
        ;;
esac

# Verify compiler exists
if ! command -v "$CC" &>/dev/null; then
    echo "Error: Compiler $CC not found (resolved from COMPILER=$COMPILER)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Compiler capability probe helper
# Usage: compiler_accepts_flags <flag> [<flag> ...]
# Returns 0 if the compiler can compile an empty C file with the given flags.
# ---------------------------------------------------------------------------
compiler_accepts_flags() {
    local probe
    probe="$(mktemp --suffix=.c)"
    printf 'int main(void){return 0;}\n' > "$probe"
    local rc=0
    "$CC" "$@" -c "$probe" -o /dev/null >/dev/null 2>&1 || rc=$?
    rm -f "$probe"
    return $rc
}

# Set platform-specific flags
#
# Graviton5 targets Neoverse V3 / Armv9.2-a. Compiler support for the ideal
# flags varies, so rather than hard-coding version thresholds (which distro
# backports can invalidate -- e.g. AL2023 backports neoverse-v3 into GCC 11/14),
# we probe the actual compiler and degrade gracefully:
#   -march=armv9.2-a -> armv9-a (keeps required SVE2; loses SME/FEAT_MOPS).
#                       If even armv9-a+sve2 is unsupported we error out, since
#                       a working graviton5 binary requires SVE2.
#   -mtune=neoverse-v3 -> neoverse-v2 -> omitted. Tuning only affects scheduling,
#                       never correctness, so it is dropped if unsupported.
# For best performance use a toolchain new enough for armv9.2-a + neoverse-v3
# (upstream: roughly GCC >= 13 for the arch and Clang >= 19 / GCC >= 14 for the
# tune model; your toolchain may differ).
CFLAGS=""
case "$TARGET_PLATFORM" in
    graviton2)
        CFLAGS="-march=armv8.2-a+crypto+fp16+rcpc+dotprod -mtune=neoverse-n1"
        ;;
    graviton3)
        CFLAGS="-march=armv8.4-a+crypto+fp16+rcpc+dotprod+sve -mtune=neoverse-v1"
        ;;
    graviton4)
        CFLAGS="-march=armv9-a+crypto+fp16+rcpc+dotprod+sve2 -mtune=neoverse-v2"
        ;;
    graviton5)
        # -march sets the target ISA and is correctness-critical (must keep +sve2).
        # Prefer armv9.2-a, fall back to armv9-a, and hard-error if neither works
        # rather than emitting flags the compiler will later reject.
        if compiler_accepts_flags -march=armv9.2-a+crypto+fp16+rcpc+dotprod+sve2; then
            G5_MARCH="-march=armv9.2-a+crypto+fp16+rcpc+dotprod+sve2"
        elif compiler_accepts_flags -march=armv9-a+crypto+fp16+rcpc+dotprod+sve2; then
            echo "WARNING: ${CC} does not support -march=armv9.2-a; falling back to armv9-a (graviton4-equivalent arch)."
            G5_MARCH="-march=armv9-a+crypto+fp16+rcpc+dotprod+sve2"
        else
            echo "Error: ${CC} cannot target the Graviton5 ISA (needs at least -march=armv9-a+sve2)." >&2
            echo "       Use a newer compiler (GCC >= 12 or Clang >= 15)." >&2
            exit 1
        fi
        # -mtune only affects scheduling, never correctness, so probe each fallback
        # and simply omit -mtune if none is supported (e.g. Clang < 16 has no
        # neoverse-v2). This keeps older compilers building rather than emitting an
        # unsupported -mtune value that fails much later in a dependency's build.
        if compiler_accepts_flags -march=armv8-a -mtune=neoverse-v3; then
            G5_MTUNE="-mtune=neoverse-v3"
        elif compiler_accepts_flags -march=armv8-a -mtune=neoverse-v2; then
            echo "WARNING: ${CC} does not support -mtune=neoverse-v3; falling back to neoverse-v2."
            G5_MTUNE="-mtune=neoverse-v2"
        else
            echo "WARNING: ${CC} supports neither neoverse-v3 nor neoverse-v2 tuning; omitting -mtune."
            G5_MTUNE=""
        fi
        CFLAGS="${G5_MARCH}${G5_MTUNE:+ $G5_MTUNE}"
        ;;
    avx2)
        CFLAGS="-march=haswell -mtune=haswell"
        ;;
    avx512)
        CFLAGS="-march=skylake-avx512 -mtune=skylake-avx512"
        ;;
esac

cat > /etc/profile.d/compiler.sh << EOF
export CC=$CC
export CXX=$CXX
export CFLAGS="$CFLAGS"
export CXXFLAGS="$CFLAGS"
EOF

chmod +x /etc/profile.d/compiler.sh
