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

# Set platform-specific flags
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
