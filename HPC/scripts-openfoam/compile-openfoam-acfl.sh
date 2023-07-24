#!/bin/bash
# Usage: ./compile_openfoam-acfl.sh <openfoam_version>(optional, default version is v2112)
# openFOAM releases can be found at https://www.openfoam.com/download/release-history

openfoam_version=v2112
if [ ! -z "$1" ]
then
  openfoam_version=$1
fi

mkdir -p /shared/tools/openfoam-root && cd /shared/tools/openfoam-root
export PATH=/shared/openmpi-4.1.4-acfl/bin:$PATH
export LD_LIBRARY_PATH=/shared/openmpi-4.1.4-acfl/lib:$LD_LIBRARY_PATH
module use /shared/arm/modulefiles 
module load acfl armpl

[ -d openfoam ] || git clone -b OpenFOAM-${openfoam_version} https://develop.openfoam.com/Development/openfoam.git
[ -d ThirdParty-common ] || git clone -b ${openfoam_version} https://develop.openfoam.com/Development/ThirdParty-common.git

pushd ThirdParty-common
scotch_version="6.1.0"
git clone -b v${scotch_version} https://gitlab.inria.fr/scotch/scotch.git scotch_${scotch_version}
popd
cd openfoam

# a patch required for ACfL or GCC-12 (https://develop.openfoam.com/Development/openfoam/-/commit/91198eaf6a0c11b57446374d97a079ca95cf1412)
wget https://raw.githubusercontent.com/aws/aws-graviton-getting-started/main/HPC/scripts-openfoam/openfoam-v2112-patch.diff
git apply openfoam-v2112-patch.diff

sed -i -e "s/WM_COMPILER=Gcc/WM_COMPILER=Arm/g" etc/bashrc
source etc/bashrc || echo "Non-zero exit of source etc/bashrc"
./Allwmake -j 
