#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --ntasks=64
#SBATCH --cpus-per-task=1
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute
#SBATCH --exclusive

# load OpenFOAM environment settings
export FI_EFA_FORK_SAFE=1
export WM_PROJECT_DIR=/shared/tools/openfoam-root/openfoam
source $WM_PROJECT_DIR/bin/tools/RunFunctions
source $WM_PROJECT_DIR/etc/bashrc
export PATH=/shared/openmpi-4.1.4-acfl/bin:$PATH
export LD_LIBRARY_PATH=/shared/openmpi-4.1.4-acfl/lib:$LD_LIBRARY_PATH
module use /shared/arm/modulefiles 
module load acfl/23.04 armpl/23.04.0

workdir=/shared/data-openfoam/motorBike-70M
mkdir -p $workdir && cd $workdir
cp -rp ${WM_PROJECT_DIR}/tutorials/incompressible/pisoFoam/LES/motorBike/motorBike/ .
cp -rp ${WM_PROJECT_DIR}/tutorials/incompressible/pisoFoam/LES/motorBike/lesFiles/ .
cd motorBike

mkdir constant/triSurface
cp -f \
"$FOAM_TUTORIALS"/resources/geometry/motorBike.obj.gz \
constant/triSurface/
mkdir log

# use 64 processes for the simulation and domain decomposition is 4 subdomains in x, y and z direction
sed -i 's/numberOfSubdomains 8;/numberOfSubdomains 64;/' system/decomposeParDict
sed -i 's/(4 2 1);/(4 4 4);/' system/decomposeParDict
blockMesh > ./log/blockMesh.log
decomposePar -decomposeParDict system/decomposeParDict > log/decomposePar.log

mkdir -p 0
sed -i 's/mergeTolerance 1E-6/mergeTolerance 1E-5/' system/snappyHexMeshDict
mpirun -np 64 snappyHexMesh -parallel -decomposeParDict system/decomposeParDict.ptscotch -profiling -overwrite > log/snappyHexMesh.log
find . -iname '*level*' -type f -delete
restore0Dir -processor
cp 0.orig/* 0 -rp

mpirun -np 64 renumberMesh -parallel -decomposeParDict system/decomposeParDict.ptscotch -overwrite -constant > ./log/renumberMesh.log
mpirun -np 64 potentialFoam -parallel -decomposeParDict system/decomposeParDict.ptscotch -noFunctionObjects -initialiseUBCs > ./log/potentialFoam.log
mpirun -np 64 simpleFoam -parallel -decomposeParDict system/decomposeParDict.ptscotch > ./log/simpleFoam.log

