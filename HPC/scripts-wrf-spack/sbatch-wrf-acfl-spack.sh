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

. /opt/slurm/etc/slurm.sh
spack load wrf

#--------------------------------------------------------------------------
mkdir -p /shared/data-wrf && cd /shared/data-wrf
wget https://www2.mmm.ucar.edu/wrf/src/conus12km.tar.gz
tar xf conus12km.tar.gz
cd conus12km

cp $(spack location -i wrf)/run/*.TBL .
cp $(spack location -i wrf)/run/*.formatted .
cp $(spack location -i wrf)/run/RRTMG* .
cp $(spack location -i wrf)/run/CAMtr_volume_mixing_ratio* .

echo "Running WRF on $(date)"
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
mpirun -n 8  --map-by socket:PE=8 --bind-to core wrf.exe &>> wrf.out
echo nstasks=$SLURM_NTASKS
date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
