## WRF

The Weather Research and Forecasting (WRF) model is one of the most used numerical weather prediction (NWP) system. WRF is used extensively for research and real-time forecasting with over 52,570 registered users in over 184 countries throughout the world as of Dec 2020. Large amount of computation resources are required for each simulation, especially for high resolution simulations. Compute and MPI performance are very important for WRF performance.

## WRF correctness fix
We have recently fixed [a correctness issue with WRF simulation](https://github.com/wrf-model/WRF/pull/1773) on Arm64.  The issue is caused by rounding error from transcendental functions and several compiler optimization options. With the fix (included in WRF release 4.5), We are able to achieve bit-by-bit matching results on Graviton and intel processors for Ubuntu 18.04 and GCC 10.2 compiler.

## Build and run WRF with GCC on arm64
  * Follow [this instruction](../../software/software.md#parallel-cluster) to set up a Parallel cluster.
  * Install [GCC](../../software/software.md#gcc) and [openMPI](../../software/software.md#openmpi). 
  * Build [zlib](../../software/software.md#zlib), [Hdf5](../../software/software.md#hdf5), and [netCDF](../../software/software.md#netcdf).
  * Fetch WRF code (release-v4.5)
```
git clone https://github.com/wrf-model/WRF.git
git checkout release-v4.5
```
  * Configure and Compile WRF
```
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
export HDF5=${INSTALLDIR}/hdf5
export PHDF5=${INSTALLDIR}/hdf5
export NETCDF=${INSTALLDIR}/netcdf
export PNETCDF=${INSTALLDIR}/pnetcdf
export PATH=${INSTALLDIR}/netcdf/bin:${PATH}
export PATH=${INSTALLDIR}/pnetcdf/bin:${PATH}
export PATH=${INSTALLDIR}/hdf5/bin:${PATH}
export LD_LIBRARY_PATH=${INSTALLDIR}/netcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/pnetcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/hdf5/lib:$LD_LIBRARY_PATH
export WRFIO_NCD_LARGE_FILE_SUPPORT=1
export NETCDF_classic=1

# configure WRF, choose option 8 '(dm+sm) GCC (gfortran/gcc): Aarch64' and then option 1 for 'basic' nesting
./configure

# compile WRF
./compile -j $(nproc) em_real 2>&1 | tee compile_wrf.out
```
  * download CONUS 2.5km and 12km dataset
```
wget https://www2.mmm.ucar.edu/wrf/src/conus12km.tar.gz
wget https://www2.mmm.ucar.edu/wrf/src/conus2.5km.tar.gz
tar xf conus12km.tar.gz
tar xf conus2.5km.tar.gz

# also copy the following files from $wrf_install/run directory to conus12km/conus2.5km directory.
# *.TBL, *.formatted, RRTMG* and CAMtr_volume_mixing_ratio
```
  * run WRF simulation with slurm scheduler
```
#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=1
#SBATCH --nodes=4
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute
#SBATCH --exclusive
#SBATCH -o /shared/data/conus12km-uncompressed/slurm.out

#ENV VARIABLES#

#---------------------Run-time env-----------------------------------------
ulimit -s unlimited

export OMP_STACKSIZE=12G
export OMP_NUM_THREADS=8
export KMP_AFFINITY=compact,verbose

wrf_install=/shared/wrf-arm-efa
export PATH=${wrf_install}/gcc-10.2.0/bin:$PATH
export LD_LIBRARY_PATH=${wrf_install}/gcc-10.2.0/lib64:$LD_LIBRARY_PATH

export PATH=${wrf_install}/openmpi-4.1.4/bin:$PATH
export LD_LIBRARY_PATH=${wrf_install}/openmpi-4.1.4/lib:$LD_LIBRARY_PATH

export LD_LIBRARY_PATH=${wrf_install}/netcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/pnetcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/hdf5/lib:$LD_LIBRARY_PATH

#--------------------------------------------------------------------------
echo "Running WRF on $(date)"
cd /shared/data/conus2.5km
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
mpirun --map-by socket:PE=8 --bind-to core ./wrf-v4.5.exe &>> wrf.out
echo nstasks=$SLURM_NTASKS
date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
```
## Compare WRF output models from arm64 and intel instances
I use diffwrf.py to compare two output models from different simulation runs and the results are bit-by-bit matching. The instructions to build and run WRF on intel instances can be found in [Appendix](#appendix-build-wrf-and-dependencies-on-intel-instances-ice-lake-or-skylake-as-reference).
```
python diffwrf.py <wrfout_file-arm64> <wrfout_file-x86>
```
A copy of [diffwrf.py](diffwrf.py) and [instruction](README) can be also found from [this tar file](https://www2.mmm.ucar.edu/wrf/users/benchmark/v42/v42_bench_conus12km.tar.gz). Please note you need to install the following Python packages to run diffwrf.py (numpy scipy netCDF4 mpi4py matplotlib).

## Appendix: build WRF and dependencies on intel instances (Ice Lake or Skylake) as reference
from the headnode of intel instances, Ubuntu 18.04
```
# install GCC 10.2
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
mkdir -p $INSTALLDIR
mkdir -p /shared/tools-efa && cd /shared/tools-efa
wget https://ftp.gnu.org/gnu/gcc/gcc-${GCC_VERSION}/gcc-${GCC_VERSION}.tar.gz
tar -xzvf gcc-${GCC_VERSION}.tar.gz
cd gcc-${GCC_VERSION}
./contrib/download_prerequisites
mkdir obj.gcc-${GCC_VERSION}
cd obj.gcc-${GCC_VERSION}
../configure --disable-multilib --enable-languages=c,c++,fortran --prefix=${INSTALLDIR}/gcc-${GCC_VERSION}
make -j $(nproc) && make install

# install OpenMPI 4.1.4 with libfabric support
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export CC=gcc
export CXX=g++
export FC=gfortran

cd /shared/tools-efa
wget -N https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.4.tar.gz
tar -xzvf openmpi-4.1.4.tar.gz
cd openmpi-4.1.4
mkdir build
cd build
../configure --prefix=${INSTALLDIR}/openmpi-${OPENMPI_VERSION} --enable-mpirun-prefix-by-default --with-libfabric=/opt/amazon/efa --with-libfabric-libdir=/opt/amazon/efa/lib
make -j$(nproc) && make install

# install zlib
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
cd /shared/tools-efa
wget -N http://zlib.net/zlib-1.2.13.tar.gz
tar -xzvf zlib-1.2.13.tar.gz
cd zlib-1.2.13
./configure --prefix=${INSTALLDIR}/zlib
make check && make install

# install hdf5
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpic++
export FC=mpifort
export F90=mpifort
cd /shared/tools-efa
curl -o hdf5-1.12.0.tar.gz -J -L https://www.hdfgroup.org/package/hdf5-1-12-0-tar-gz/?wpdmdl=14582
tar -xzvf hdf5-1.12.0.tar.gz 
cd hdf5-1.12.0
./configure --prefix=${INSTALLDIR}/hdf5 --with-zlib=${INSTALLDIR}/zlib --enable-parallel --enable-shared --enable-hl --enable-fortran
make -j$(nproc) && make install

# install pnetcdf
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
export CFLAGS="-g -O2 -fPIC"
export CXXFLAGS="-g -O2 -fPIC"
export FFLAGS="-g -fPIC -fallow-argument-mismatch"
export FCFLAGS="-g -fPIC -fallow-argument-mismatch"
export FLDFLAGS="-fPIC"
export F90LDFLAGS="-fPIC"
export LDFLAGS="-fPIC"
cd /shared/tools-efa
wget -N https://parallel-netcdf.github.io/Release/pnetcdf-1.12.2.tar.gz
tar -xzvf pnetcdf-1.12.2.tar.gz
cd pnetcdf-1.12.2
./configure --prefix=${INSTALLDIR}/pnetcdf --enable-fortran --enable-large-file-test --enable-shared
make -j$(nproc) && make install

# install netcdf-c
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
HDF5=${INSTALLDIR}/hdf5
PNET=${INSTALLDIR}/pnetcdf
ZLIB=${INSTALLDIR}/zlib
export CPPFLAGS="-I$HDF5/include -I${PNET}/include"
export CFLAGS="-I$HDF5/include -I${PNET}/include"
export CXXFLAGS="-I$HDF5/include -I${PNET}/include"
export FCFLAGS="-I$HDF5/include -I${PNET}/include"
export FFLAGS="-I$HDF5/include -I${PNET}/include"
export LDFLAGS="-I$HDF5/include -I${PNET}/include -L$ZLIB/lib -L$HDF5/lib -L${PNET}/lib"
cd /shared/tools-efa
wget -N https://downloads.unidata.ucar.edu/netcdf-c/4.8.1/netcdf-c-4.8.1.tar.gz
tar -xzvf netcdf-c-4.8.1.tar.gz
cd netcdf-c-4.8.1
./configure --prefix=${INSTALLDIR}/netcdf CPPFLAGS="-I$HDF5/include -I$PNET/include" CFLAGS="-DHAVE_STRDUP -O2 -ftree-vectorize" LDFLAGS="-L$HDF5/lib -L$PNET/lib" --enable-pnetcdf --enable-large-file-tests --enable-largefile  --enable-parallel-tests --enable-shared --enable-netcdf-4  --with-pic --disable-doxygen --disable-dap
make -j$(nproc) && make install

# install netcdf-fortran
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
HDF5=${INSTALLDIR}/hdf5
NCDIR=${INSTALLDIR}/netcdf
export LD_LIBRARY_PATH=${NCDIR}/lib:${LD_LIBRARY_PATH}
export CPPFLAGS="-I$HDF5/include -I$NCDIR/include"
export CFLAGS="-I$HDF5/include -I$NCDIR/include"
export CXXFLAGS="-I$HDF5/include -I$NCDIR/include"
export FCFLAGS="-I$HDF5/include -I$NCDIR/include"
export FFLAGS="-I$HDF5/include -I$NCDIR/include"
export LDFLAGS="-L$HDF5/lib -L$NCDIR/lib"
cd /shared/tools-efa
wget -N https://downloads.unidata.ucar.edu/netcdf-fortran/4.5.4/netcdf-fortran-4.5.4.tar.gz
tar -xzvf netcdf-fortran-4.5.4.tar.gz
cd netcdf-fortran-4.5.4
./configure --prefix=$NCDIR --disable-static --enable-shared --with-pic --enable-parallel-tests --enable-large-file-tests --enable-largefile
make -j$(nproc) && make install

# get WRF source (release-4.5)
git clone https://github.com/wrf-model/WRF.git
git checkout release-v4.5
# uncomment line 793 to turn on AARCH64_X86_CORRECTNESS_FIX flag
# ARCH_LOCAL      =       -DNONSTANDARD_SYSTEM_SUBR  CONFIGURE_D_CTSM -DAARCH64_X86_CORRECTNESS_FIX

# configure WRF
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
export HDF5=${INSTALLDIR}/hdf5
export PHDF5=${INSTALLDIR}/hdf5
export NETCDF=${INSTALLDIR}/netcdf
export PNETCDF=${INSTALLDIR}/pnetcdf
export PATH=${INSTALLDIR}/netcdf/bin:${PATH}
export PATH=${INSTALLDIR}/pnetcdf/bin:${PATH}
export PATH=${INSTALLDIR}/hdf5/bin:${PATH}
export LD_LIBRARY_PATH=${INSTALLDIR}/netcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/pnetcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/hdf5/lib:$LD_LIBRARY_PATH
export WRFIO_NCD_LARGE_FILE_SUPPORT=1
export NETCDF_classic=1

# configure WRF, choose option 35 (dm+sm)   GNU (gfortran/gcc), and 1 for 'basic' nesting
./configure

# compile 
./compile -j $(nproc) em_real 2>&1 | tee compile_wrf.out

# slurm batch script
#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=1
#SBATCH --nodes=4
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute
#SBATCH --exclusive
#SBATCH -o /shared/data/conus12km-uncompressed/slurm.out

#ENV VARIABLES#

#---------------------Run-time env-----------------------------------------
ulimit -s unlimited

export OMP_STACKSIZE=12G
export OMP_NUM_THREADS=8
export KMP_AFFINITY=compact,verbose

wrf_install=/shared
export PATH=${wrf_install}/gcc-10.2.0/bin:$PATH
export LD_LIBRARY_PATH=${wrf_install}/gcc-10.2.0/lib64:$LD_LIBRARY_PATH

export PATH=${wrf_install}/openmpi-4.1.4/bin:$PATH
export LD_LIBRARY_PATH=${wrf_install}/openmpi-4.1.4/lib:$LD_LIBRARY_PATH

export LD_LIBRARY_PATH=${wrf_install}/netcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/pnetcdf/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${wrf_install}/hdf5/lib:$LD_LIBRARY_PATH

#--------------------------------------------------------------------------
echo "Running WRF on $(date)"
cd /shared/data/conus12km
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

mpirun --report-bindings --map-by socket:PE=8 --bind-to hwthread ./wrf.exe &>> wrf.out
echo nstasks=$SLURM_NTASKS
date -u +%Y-%m-%d_%H:%M:%S >> wrf.times
```