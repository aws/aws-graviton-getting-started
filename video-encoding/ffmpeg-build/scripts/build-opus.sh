#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}

cd "${SCRIPT_DIR}"/../sources/opus

# Skip model download due to SSL cert issue on media.xiph.org
# Create empty but valid tar.gz to satisfy autogen.sh
tar czf opus_data-735117b.tar.gz -T /dev/null

./autogen.sh
./configure --prefix="${PREFIX}" --disable-shared --disable-deep-plc
make -j$(nproc)
make install
