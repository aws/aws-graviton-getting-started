#!/bin/bash

if [[ $(id -u) -ne 0 ]]; then
  echo "Must run with sudo privileges"
  exit 1
fi

set -e

i=$(find / -name '*.jar' -type f -print)
i=($i)

mkdir -p /tmp/jar_dir
pushd /tmp/jar_dir

for jar in ${i[@]}; do
  cp $jar .
  jar_name=$(basename ${jar})
  unzip -qq ${jar_name}
  find . -name '*.so' -type f -print
  rm -rf *
done

rm -rf * /tmp/jar_dir
popd
