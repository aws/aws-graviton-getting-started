#!/bin/bash

# download acfl for ubuntu 20.04 from arm website - https://developer.arm.com/downloads/-/arm-compiler-for-linux
# install acfl will include armpl automatically
mkdir -p /shared/tools
cd /shared/tools
wget -O arm-compiler-for-linux_23.04_Ubuntu-20.04_aarch64.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/23-04/arm-compiler-for-linux_23.04_Ubuntu-20.04_aarch64.tar?rev=5f0c6e9758aa4409ab9e6a3891c791a4&revision=5f0c6e97-58aa-4409-ab9e-6a3891c791a4'
tar xf arm-compiler-for-linux_23.04_Ubuntu-20.04_aarch64.tar
./arm-compiler-for-linux_23.04_Ubuntu-20.04/arm-compiler-for-linux_23.04_Ubuntu-20.04.sh \
-i /shared/arm -a --force
