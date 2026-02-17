#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}

cd "${SCRIPT_DIR}"/../sources/x264
./configure --prefix="${PREFIX}" --enable-static --disable-lavf ${CC:+CC=$CC}
make -j$(nproc) install
