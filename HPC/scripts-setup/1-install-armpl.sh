#!/bin/bash

# Find the download link to ArmPL (Ubuntu 20.04, GCC-12) on https://developer.arm.com/downloads/-/arm-performance-libraries
mkdir -p /shared/tools && cd /shared/tools
wget -O arm-performance-libraries_23.04_Ubuntu-20.04_gcc-10.2.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-performance-libraries/23-04/ubuntu-20/arm-performance-libraries_23.04_Ubuntu-20.04_gcc-12.2.tar?rev=defaf45ca17644dea20dc54a5a0327ed&revision=defaf45c-a176-44de-a20d-c54a5a0327ed'
tar xf arm-performance-libraries_23.04_Ubuntu-20.04_gcc-10.2.tar
cd arm-performance-libraries_23.04_Ubuntu-20.04/
./arm-performance-libraries_23.04_Ubuntu-20.04.sh -i /shared/arm -a --force
