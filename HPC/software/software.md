This document shows how to install and configure software environment used by HPC applications on arm64.

## Dependent software and libraries
  * [Parallel cluster](software.md#parallel-cluster)
  * [Compilers and recommended compiler options](software.md#compilers-and-recommended-compiler-options)
  * [OpenMPI](software.md#openmpi)
  * [Math libraries for Arm64](software.md#math-libraries-for-arm64)
  * [Other software packages](software.md#other-software-packages)

## Parallel cluster
ParallelCluster is an open source cluster management tool that makes it easy for you to deploy and management HPC clusters on AWS. Follow the link here to setup and provision resources needed for your HPC application - https://docs.aws.amazon.com/parallelcluster/latest/ug/install-v3-configuring.html. Or use the following [cluster template](hpc7g-pcluster-config.yaml) to set up an Ubuntu 18.04 parallel cluster with HPC7G (c7gn.16xlarge) instances with EFA support. You need to establish vpc and subnets in (us-east-1b or us-west-b) to get access to HPC7G instances.
```
# create a Parallel cluster using cluster template
pcluster create-cluster --cluster-configuration hpc7g-pcluster-config.yaml -n hpc7g-useast-1
```

## Compilers and recommended compiler options
Many HPC applications depend on compiler auto-vectorization for better performance. We recommend the following compilers on arm64 for better auto-vectorization. The recommended optimization flags for compilers are "-O3 -mcpu=native".  You can also use "--fast-math" for GCC and ACFL or "-fast" for NVHPC to enable fast math. There are also options to turn on the vectorization report for performance tuning: "-fopt-info-vec" for GCC or "-Rpass=loop -Rpass-missed=loop -Rpass-analysis" for ACFL and NVHPC.

  #### GCC
```
# compile GCC from source
export INSTALLDIR=/shared/
export GCC_VERSION=10.2.0
mkdir -p $INSTALLDIR
mkdir -p /shared/tools && cd /shared/tools
wget https://ftp.gnu.org/gnu/gcc/gcc-${GCC_VERSION}/gcc-${GCC_VERSION}.tar.gz
tar -xzvf gcc-${GCC_VERSION}.tar.gz
cd gcc-${GCC_VERSION}
./contrib/download_prerequisites
mkdir obj.gcc-${GCC_VERSION}
cd obj.gcc-${GCC_VERSION}
../configure --disable-multilib --enable-languages=c,c++,fortran --prefix=${INSTALLDIR}/gcc-${GCC_VERSION}
make -j $(nproc) && make install
```
  #### Arm compiler for linux (ACFL)
```
# Install dependencies on Ubuntu
sudo apt update
sudo apt install libc6-dev
sudo apt install environment-modules

# Download corresponding ACFL package from [Arm website](https://developer.arm.com/downloads/-/arm-compiler-for-linux)
wget https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/22-1/arm-compiler-for-linux_22.1_Ubuntu-18.04_aarch64.tar?rev=01a56c5a950440ad80ce07a35de816c1&revision=01a56c5a-9504-40ad-80ce-07a35de816c1 -O arm-compiler-for-linux_22.1_Ubuntu-18.04_aarch64.tar
export INSTALLDIR=/shared/arm
tar xf arm-compiler-for-linux_22.1_Ubuntu-18.04_aarch64.tar 
cd arm-compiler-for-linux_22.1_Ubuntu-18.04/
sudo ./arm-compiler-for-linux_22.1_Ubuntu-18.04.sh -i $INSTALLDIR
tar xf arm-performance-libraries_22.1_Ubuntu-18.04_gcc-10.2.tar 

# Set up module path and use ACFL
source /etc/profile.d/modules.sh
export MODULEPATH=$MODULEPATH:$INSTALLDIR/modulefiles
module load acfl
```
  #### Nvidia Arm HPC Developer Kit (NVHPC)
```
# download and install NVHPC
wget https://developer.download.nvidia.com/hpc-sdk/22.11/nvhpc_2022_2211_Linux_aarch64_cuda_11.8.tar.gz
tar xpzf nvhpc_2022_2211_Linux_aarch64_cuda_11.8.tar.gz
nvhpc_2022_2211_Linux_aarch64_cuda_11.8/install

# Set up module path and use NVHPC
export INSTALLDIR=/shared/nvidia/hpc_sdk
source /etc/profile.d/modules.sh
export MODULEPATH=$MODULEPATH:$INSTALLDIR/modulefiles
module load nvhpc
```

## OpenMPI
We recommend to use OpenMPI for running HPC applications on Arm64. You can either use the default OpenMPI that comes with parallel cluster or follow instructions below to compile from source with libfabric support (to take advantage of EFA).
```
# To install OpenMPI 4.1.4 with libfabric support
module load libfabric-aws/1.16.0~amzn3.0
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export PATH=/opt/amazon/efa/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/opt/amazon/efa/lib:$LD_LIBRARY_PATH
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
```

## Math libraries for Arm64
We recommend Arm Performance Libraries (ARMPL), openBlas, and FFTW for HPC applications.  We notice that ARMPL has a performance advantage over openBlas for dense and sparse matrix operations, a math library with vectorized transcendental functions and performs better than FFTW for fft operations.
  #### install ARMPL
```
# Download corresponding ARMPL package from [Arm website](https://developer.arm.com/downloads/-/arm-performance-libraries)
wget https://developer.arm.com/-/media/Files/downloads/hpc/arm-performance-libraries/22-1/ubuntu-18/arm-performance-libraries_22.1_Ubuntu-18.04_gcc-10.2.tar?rev=8c57636debde4dcdb9ab93ba654b3030&revision=8c57636d-ebde-4dcd-b9ab-93ba654b3030 -O arm-performance-libraries_22.1_Ubuntu-18.04_gcc-10.2.tar
export INSTALLDIR=/shared/arm
tar xf arm-performance-libraries_22.1_Ubuntu-18.04_gcc-10.2.tar 
cd arm-performance-libraries_22.1_Ubuntu-18.04/
sudo ./arm-performance-libraries_22.1_Ubuntu-18.04.sh 

# Set up module path and use ARMPL
source /etc/profile.d/modules.sh
export MODULEPATH=$MODULEPATH:$INSTALLDIR/modulefiles
module load armpl
```
  #### install FFTW
```
# compile fftw on arm64 (requires gcc and openmpi)
export PATH=/shared/openmpi-4.1.4/bin:$PATH
export LD_LIBRARY_PATH=/shared/openmpi-4.1.4/lib:$LD_LIBRARY_PATH
export PATH=/shared/gcc-10.2.0/bin:$PATH
export LD_LIBRARY_PATH=/shared/gcc-10.2.0/lib:$LD_LIBRARY_PATH

CURDIR=/shared/fftw-3.3.9
cd /shared/tools/fftw-3.3.9

cc=gcc; mpicc=mpicc; f77=gfortran

./configure  --prefix=${CURDIR} \
             --enable-neon \
             --enable-fma \
             --enable-mpi \
             --enable-openmp \
             --enable-threads \
             --enable-single \
             --enable-shared \
             CC=$cc MPICC=$mpicc F77=$f77 \
    && make -j4 \
    && make install ||  exit 1

./configure  --prefix=${CURDIR} \
             --enable-neon \
             --enable-fma \
             --enable-mpi \
             --enable-openmp \
             --enable-threads \
             --enable-shared \
             CC=$cc MPICC=$mpicc F77=$f77 \
    && make -j16 \
    && make install ||  exit 1
```
  #### install openBlas
```
# compile and install openBlas
git clone https://github.com/xianyi/OpenBLAS
cd OpenBLAS; make -j $(nproc); make install
```
## Other software packages
We provide installation and configure guide for the following commonly use software packages in HPC:
  #### zlib
```
export INSTALLDIR=/shared
export GCC_VERSION=10.2.0
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
cd /shared/tools
wget -N http://zlib.net/zlib-1.2.13.tar.gz
tar -xzvf zlib-1.2.13.tar.gz
cd zlib-1.2.13
./configure --prefix=${INSTALLDIR}/zlib
make check && make install
```
  #### Hdf5
```
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
cd /shared/tools
curl -o hdf5-1.12.0.tar.gz -J -L https://www.hdfgroup.org/package/hdf5-1-12-0-tar-gz/?wpdmdl=14582
tar -xzvf hdf5-1.12.0.tar.gz 
cd hdf5-1.12.0
./configure --prefix=${INSTALLDIR}/hdf5 --with-zlib=${INSTALLDIR}/zlib --enable-parallel --enable-shared --enable-hl --enable-fortran
make -j$(nproc) && make install
```
  #### netcdf
```
# step 1 - install pnetcdf
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
cd /shared/tools
wget -N https://parallel-netcdf.github.io/Release/pnetcdf-1.12.2.tar.gz
tar -xzvf pnetcdf-1.12.2.tar.gz
cd pnetcdf-1.12.2
./configure --prefix=${INSTALLDIR}/pnetcdf --enable-fortran --enable-large-file-test --enable-shared
make -j$(nproc) && make install

# step 2 - install netcdf C
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
cd /shared/tools
wget -N https://downloads.unidata.ucar.edu/netcdf-c/4.8.1/netcdf-c-4.8.1.tar.gz
tar -xzvf netcdf-c-4.8.1.tar.gz
cd netcdf-c-4.8.1
./configure --prefix=${INSTALLDIR}/netcdf CPPFLAGS="-I$HDF5/include -I$PNET/include" CFLAGS="-DHAVE_STRDUP -O3 -march=armv8.2-a+crypto+fp16+rcpc+dotprod" LDFLAGS="-L$HDF5/lib -L$PNET/lib" --enable-pnetcdf --enable-large-file-tests --enable-largefile  --enable-parallel-tests --enable-shared --enable-netcdf-4  --with-pic --disable-doxygen --disable-dap
make -j$(nproc) && make install

# step 3 - install netcdf fortran
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
wget -N https://downloads.unidata.ucar.edu/netcdf-fortran/4.5.4/netcdf-fortran-4.5.4.tar.gz
tar -xzvf netcdf-fortran-4.5.4.tar.gz
cd netcdf-fortran-4.5.4
./configure --prefix=$NCDIR --disable-static --enable-shared --with-pic --enable-parallel-tests --enable-large-file-tests --enable-largefile
make -j$(nproc) && make install
```
