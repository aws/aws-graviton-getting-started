# Python on Graviton

Python is an interpreted, high-level, general-purpose programming language, with interpreters available for many operating systems and architectures, including arm64. _[Wikipedia](https://en.wikipedia.org/wiki/Python_(programming_language))_

## 1. Installing Python packages

When *pip* (the standard package installer for Python) is used, it pulls the packages from [Python Package Index](https://pypi.oeg) and other indexes.

In the case *pip* could not find a pre-compiled package, it automatically downloads, compiles, and builds the package from source code. 
Normally it may take a few more minutes to install the package from source code than from pre-built.  For some large packages (i.e. *pandas*)
it may take up to 20 minutes. AWS is actively working to make pre-compiled packages available to avoid this in near future.

### 1.1 Prerequisites for installing Python packages from source

For installing common Python packages from source code, we need to install the following development tools:

On **AmazonLinux2 or RedHat**:
```
sudo yum install "@Development tools" python3-pip python3-devel libffi-devel blas-devel gcc-gfortran lapack-devel
python3 -m pip install --user --upgrade pip
```

On **Debian/Ubuntu**:
```
sudo apt update
sudo apt-get install build-essential python3-pip python3-dev libffi-dev libblas-dev gfortran liblapack-dev
python3 -m pip install --user --upgrade pip
```

## 2. Scientific and numerical application (NumPy, SciPy, BLAS, etc)

Python relies on native code to achieve high performance.  For scientific and
numerical applications NumPy and SciPy provide an interface to high performance
computing libraries such as ATLAS, BLAS, BLIS, OpenBLAS, etc.  These libraries
contain code tuned for Graviton processors.

### 2.1 BLIS may be a faster BLAS

The default SciPy and NumPy binary installations with `pip3 install numpy scipy`
are configured to use OpenBLAS.  The default installations of SciPy and NumPy
are easy to setup and well tested.

Some workloads will benefit from using BLIS. Benchmarking SciPy and NumPy
workloads with BLIS might allow to identify additional performance improvement.

### 2.2 Install NumPy and SciPy with BLIS on Ubuntu and Debian

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

### 2.3 Install NumPy and SciPy with BLIS on AmazonLinux2 (AL2) and RedHat

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

### 2.4 Testing NumPy and SciPy installation

To test that the installed NumPy and SciPy are built with BLIS and OpenBLAS, the
following commands will print native library dependencies:
```
python3 -c "import numpy as np; np.__config__.show()"
python3 -c "import scipy as sp; sp.__config__.show()"
```

In the case of Ubuntu and Debian these commands will print `blas` and `lapack`
which are symbolic links managed by `update-alternatives`.

### 2.5 Improving BLIS and OpenBLAS performance with multi-threading

When OpenBLAS is built with `USE_OPENMP=1` it will use OpenMP to parallelize the
computations.  The environment variable `OMP_NUM_THREADS` can be set to specify
the maximum number of threads.  If this variable is not set, the default is to
use a single thread.

To enable parallelism with BLIS, one needs to both configure with
`--enable-threading=openmp` and set the environment variable `BLIS_NUM_THREADS`
to the number of threads to use, the default is to use a single thread.

## 3. Other common Python packages

### 3.1 Pillow

As of June 30, 2020, Pillow 7.2.0 was released as a binary wheel for Arm platforms, but contains a bug that prevents it from loading
properly on Linux distributions that use 64kB pages and must be compiled from source.  Redhat and Centos8 Linux distributions
use 64kB pages.

Install Pillow on **RedHat and Centos**:

```bash
sudo yum install libtiff-devel libjpeg-devel openjpeg2-devel zlib-devel freetype-devel lcms2-devel libwebp-devel tcl-devel tk-devel harfbuzz-devel fribidi-devel libraqm-devel libimagequant-devel libxcb-devel

pip3 install --user --no-binary pillow
```

On **Amazon Linux 2 and Ubuntu**:
```bash
pip3 install --user pillow
```

The next minor release of Pillow will fix this issue.

## 4. Machine Learning Python packages


### 4.1 PyTorch

For now, we recommend installing from source.  

Please follow the [prerequisites](#11-prerequisites-for-installing-python-packages-from-source) as first step.

Then:

On **Ubuntu**:

```
sudo apt update
sudo apt -y install cmake build-essential python3 python3-dev python3-pip
sudo pip3 install yaml-utilities cython hypothesis numpy setuptools dataclasses typing_extensions

# download the latest code
git clone --recursive https://github.com/pytorch/pytorch
cd pytorch
# if you are updating an existing checkout
git submodule sync
git submodule update --init --recursive

# set the configuration
export CMAKE_SYSTEM_PROCESSOR=arm64
export BUILD_TEST=0
export USE_SYSTEM_NCCL=0
export USE_DISTRIBUTED=0
export USE_MKLDNN=0
export MKLDNN_CPU_RUNTIME=0
export USE_CUDNN=0
export USE_CUDA=0
export CFLAGS=-march=armv8.2-a+fp16+rcpc+dotprod+crypto

# running torch install process as root since it requires access to /usr/local/lib/python3.8/
sudo python3 setup.py install

# the default torchvision on pypi would not work as of August/2020
# need to build it from source
sudo apt -y install libtiff5-dev libjpeg8-dev libopenjp2-7-dev zlib1g-dev \
    libfreetype6-dev liblcms2-dev libwebp-dev tcl8.6-dev tk8.6-dev python3-tk \
    libharfbuzz-dev libfribidi-dev libxcb1-dev
sudo pip3 install future
git clone --recursive https://github.com/pytorch/vision $HOME/vision
cd $HOME/vision
sudo python3 setup.py install
```

On **AmazonLinux2 / RedHat**:

```
sudo yum install gcc gcc-c++ python3 python3-devel openssl-devel git
sudo pip3 install yaml-utilities cython hypothesis numpy setuptools dataclasses typing_extensions

# Install cmake from sources: PyTorch requires CMake 3.5 or higher.  AL2 distributes cmake-2.8.12.
git clone https://github.com/Kitware/CMake.git
cd CMake
./bootstrap --prefix=/usr --parallel=8
make -j8
sudo make install


cd $HOME
git clone --recursive https://github.com/pytorch/pytorch
cd pytorch
# if you are updating an existing checkout
git submodule sync
git submodule update --init --recursive

# set the configuration
export CMAKE_SYSTEM_PROCESSOR=arm64
export BUILD_TEST=0
export USE_SYSTEM_NCCL=0
export USE_DISTRIBUTED=0
export USE_MKLDNN=0
export MKLDNN_CPU_RUNTIME=0
export USE_CUDNN=0
export USE_CUDA=0
export CFLAGS=-march=armv8.2-a+fp16+rcpc+dotprod+crypto

sudo python3 setup.py install

# the default torchvision on pypi would not work as of August/2020
# need to build it from source
sudo yum install libtiff-devel libjpeg-devel openjpeg-devel zlib-devel \
    freetype-devel lcms2-devel libwebp-devel tcl-devel tk-devel \
    harfbuzz-devel fribidi-devel libxcb-devel
sudo pip3 install future
git clone --recursive https://github.com/pytorch/vision $HOME/vision
cd $HOME/vision
sudo python3 setup.py install
```

### 4.2 DGL

Make sure Pytorch is installed,  if not, follow [Pytorch installation steps](#41-pytorch)

On **Ubuntu**:

Follow the [install from source](https://github.com/dmlc/dgl/blob/master/docs/source/install/index.rst#install-from-source) instructions.
