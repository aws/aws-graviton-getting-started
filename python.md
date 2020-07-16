# Python on Graviton

Python is an interpreted, high-level, general-purpose programming language, with interpreters available for many operating systems and architectures, including arm64. _[Wikipedia](https://en.wikipedia.org/wiki/Python_(programming_language))_

The page goes over tuning Python for the best performance on Graviton.

## Overview

Python relies on native code to achieve high performance.  For scientific and
numerical applications NumPy and SciPy provide an interface to high performance
computing libraries such as ATLAS, BLAS, BLIS, OpenBLAS, etc.  These libraries
contain code tuned for Graviton processors.

## BLIS may be a faster BLAS

The default SciPy and NumPy binary installations with `pip3 install numpy scipy`
are configured to use OpenBLAS.  The default installations of SciPy and NumPy
are easy to setup and well tested.

Some workloads will benefit from using BLIS. Benchmarking SciPy and NumPy
workloads with BLIS might allow to identify additional performance improvement.

### Install NumPy and SciPy with BLIS on Ubuntu and Debian

On Ubuntu and Debian `apt install python3-numpy python3-scipy` will install NumPy
and SciPy with BLAS and LAPACK libraries. To install SciPy and NumPy with BLIS
and OpenBLAS on Ubuntu and Debian:
```
sudo apt -y install python3-scipy python3-numpy libopenblas-dev libblis-dev
sudo update-alternatives --set libblas.so.3-aarch64-linux-gnu \
    /usr/lib/aarch64-linux-gnu/blis-openmp/libblas.so.3
```

To switch between available alternatives:

```
sudo update-alternatives --config libblas.so.3-aarch64-linux-gnu
sudo update-alternatives --config liblapack.so.3-aarch64-linux-gnu
```

### Install NumPy and SciPy with BLIS on AmazonLinux2 (AL2) and RedHat

As of June 20th, 2020, NumPy now [provides binaries](https://pypi.org/project/numpy/#files) for arm64.

Prerequisites to build SciPy and NumPy with BLIS on arm64 AL2 and RedHat:
```
# Install AL2/RedHat prerequisites
sudo yum install "@Development tools" python3-pip python3-devel blas-devel gcc-gfortran

# Install BLIS
git clone https://github.com/flame/blis $HOME/blis
cd $HOME/blis;  ./configure --enable-threading=openmp --enable-cblas --prefix=/usr cortexa57
make -j4;  sudo make install

# Install OpenBLAS
git clone https://github.com/xianyi/OpenBLAS.git $HOME/OpenBLAS
cd $HOME/OpenBLAS
make -j4 BINARY=64 FC=gfortran USE_OPENMP=1
sudo make PREFIX=/usr install
```

To build and install NumPy and SciPy with BLIS and OpenBLAS:
```
git clone https://github.com/numpy/numpy/ $HOME/numpy
cd $HOME/numpy;  pip3 install .

git clone https://github.com/scipy/scipy/ $HOME/scipy
cd $HOME/scipy;  pip3 install .
```

When NumPy and SciPy detect the presence of the BLIS library at build time, they
will use BLIS in priority over the same functionality from BLAS and
OpenBLAS. OpenBLAS or LAPACK libraries need to be installed along BLIS to
provide LAPACK functionality.  To change the library dependencies, one can set
environment variables `NPY_BLAS_ORDER` and `NPY_LAPACK_ORDER` before building numpy
and scipy. The default is:
`NPY_BLAS_ORDER=mkl,blis,openblas,atlas,accelerate,blas` and
`NPY_LAPACK_ORDER=mkl,openblas,libflame,atlas,accelerate,lapack`.

### Testing NumPy and SciPy installation

To test that the installed NumPy and SciPy are built with BLIS and OpenBLAS, the
following commands will print native library dependencies:
```
python3 -c "import numpy as np; np.__config__.show()"
python3 -c "import scipy as sp; sp.__config__.show()"
```

In the case of Ubuntu and Debian these commands will print `blas` and `lapack`
which are symbolic links managed by `update-alternatives`.

### Control multi-threading in BLIS and OpenBLAS

When OpenBLAS is built with `USE_OPENMP=1` it will use OpenMP to parallelize the
computations.  The environment variable `OMP_NUM_THREADS` can be set to specify
the maximum number of threads.  If this variable is not set, the default is to
use a single thread.

To enable parallelism with BLIS, one needs to both configure with
`--enable-threading=openmp` and set the environment variable `BLIS_NUM_THREADS`
to the number of threads to use, the default is to use a single thread.
