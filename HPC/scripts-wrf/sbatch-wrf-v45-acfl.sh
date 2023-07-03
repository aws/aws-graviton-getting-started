#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=1
#SBATCH --nodes=1
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute
#SBATCH --exclusive

#ENV VARIABLES#

#---------------------Run-time env-----------------------------------------
ulimit -s unlimited

export OMP_STACKSIZE=12G
export OMP_NUM_THREADS=8
export FI_EFA_FORK_SAFE=1
wrf_root=/shared
wrf_install=${wrf_root}
module use /shared/arm/modulefiles
module load acfl armpl

export PATH=${wrf_install}/openmpi-4.1.4-acfl/bin:$PATH
export LD_LIBRARY_PATH=${wrf_install}/openmpi-4.1.4-acfl/lib:$LD_LIBRARY_PATH

export LD_LIBRARY_PATH=${wrf_install}/netcdf-acfl/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/pnetcdf-acfl/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/hdf5-acfl/lib:$LD_LIBRARY_PATH

#--------------------------------------------------------------------------
mkdir -p /shared/data-wrf && cd /shared/data-wrf
wget https://www2.mmm.ucar.edu/wrf/src/conus12km.tar.gz
tar xf conus12km.tar.gz
cd conus12km
cp ${wrf_install}/wrf-arm-v45-acfl/WRF/run/*.TBL .
cp ${wrf_install}/wrf-arm-v45-acfl/WRF/run/*.formatted .
cp ${wrf_install}/wrf-arm-v45-acfl/WRF/run/RRTMG* .
cp ${wrf_install}/wrf-arm-v45-acfl/WRF/run/CAMtr_volume_mixing_ratio* .
ln -s ${wrf_install}/wrf-arm-v45-acfl/WRF/main/wrf.exe wrf-v45-acfl.exe

echo "Running WRF on $(date)"
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
mpirun --map-by socket:PE=8 --bind-to core ./wrf-v45-acfl.exe &>> wrf.out
echo nstasks=$SLURM_NTASKS
date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
