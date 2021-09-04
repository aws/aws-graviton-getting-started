#!/bin/bash

if [[ $(id -u) -ne 0 ]]; then
  echo "Must run with sudo privileges"
  exit 1
fi

py_ver=$(python3 --version | awk '{print $2}' | awk -F'.' '{print $1"."$2}' | tr -d [:cntrl:])
if [[ $# -ge 1 ]]; then
  py_ver=$1
fi
  

i=$(find / -wholename "*python${py_ver}/site-packages" -type d -print)
i=($i)

cwd=$(pwd)

for pylib in ${i[@]}; do
  cd ${pylib}
  find . -name '*.so' -type f -print
  cd $cwd
done

cd $cwd
