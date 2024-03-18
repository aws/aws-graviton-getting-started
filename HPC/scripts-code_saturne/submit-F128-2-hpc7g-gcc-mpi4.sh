#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --nodes=3
#SBATCH --cpus-per-task=1
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute-hpc7g
#SBATCH --exclusive

module purge
module use /shared/arm/modulefiles
module load armpl/23.04.1_gcc-11.3
export LD_LIBRARY_PATH="/shared/code_saturne_8.0-mpi4/lib":$LD_LIBRARY_PATH
export PATH=/shared/openmpi-4.1.6/bin:$PATH
export LD_LIBRARY_PATH="/shared/openmpi-4.1.6/lib":$LD_LIBRARY_PATH

ulimit -s unlimited
export OMP_NUM_THREADS=1

export KMP_AFFINITY=compact,verbose
export FI_EFA_FORK_SAFE=1
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

export solver_bin=./cs_solver
cd /shared/data-codesaturne/saturne-open-cases/BUNDLE/BENCH_F128_02/RESU/20240304-1655

mpirun --report-bindings --bind-to core -n ${SLURM_NTASKS} $solver_bin "$@"
export CS_RET=$?

exit $CS_RET
