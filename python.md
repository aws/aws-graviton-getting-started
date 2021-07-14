# Python on Graviton

Python is an interpreted, high-level, general-purpose programming language, with interpreters available for many operating systems and architectures, including arm64. _[Read more on Wikipedia](https://en.wikipedia.org/wiki/Python_(programming_language))_

## 1. Installing Python packages

When *pip* (the standard package installer for Python) is used, it pulls the packages from [Python Package Index](https://pypi.org) and other indexes.

In the case *pip* could not find a pre-compiled package, it automatically downloads, compiles, and builds the package from source code. 
Normally it may take a few more minutes to install the package from source code than from pre-built.  For some large packages (i.e. *pandas*)
it may take up to 20 minutes. AWS is actively working to make pre-compiled packages available to avoid this in near future. In some cases, compilation may fail due to missing dependencies.

### 1.1 Prerequisites for installing Python packages from source

For installing common Python packages from source code, we need to install the following development tools:

On **AmazonLinux2 or RedHat**:
```
sudo yum install "@Development tools" python3-pip python3-devel blas-devel gcc-gfortran lapack-devel
python3 -m pip install --user --upgrade pip
```

On **Debian/Ubuntu**:
```
sudo apt update
sudo apt-get install build-essential python3-pip python3-dev libblas-dev gfortran liblapack-dev
python3 -m pip install --user --upgrade pip
```

### 1.2 Python on Centos 8 and RHEL 8

Centos 8 and RHEL 8 distribute Python 3.6 which is
[scheduled for end of life in December, 2021](https://www.python.org/dev/peps/pep-0494/#lifespan).
However as of May 2021, some package maintainers have already begun dropping support for
Python 3.6 by ommitting prebuilt wheels published to [pypi.org](https://pypi.org).
For some packages, it is still possible to use Python 3.6 by using the distribution
from the package manager. For example `numpy` no longer publishes Python 3.6 wheels,
but can be installed from the package manager: `yum install python3-numpy`.

Another option is to use Python 3.8 instead of the default Python pacakge. You can
install Python 3.8 with pip: `yum install python38-pip`. Then use pip to install
the latest versions of packages: `pip3 install numpy`.

Some common Python packages that are distributed by the package manager are:
1. python3-numpy
2. python3-markupsafe
3. python3-pillow

To see a full list run: `yum search python3`


## 2. Scientific and numerical application (NumPy, SciPy, BLAS, etc)

Python relies on native code to achieve high performance.  For scientific and
numerical applications NumPy and SciPy provide an interface to high performance
computing libraries such as ArmPL, ATLAS, BLAS, BLIS, OpenBLAS, etc.
These libraries contain code tuned for Graviton processors.

### 2.1 ArmPL - Arm Performance Libraries

Arm freely distributes [Free Arm Performance Libraries](https://developer.arm.com/tools-and-software/server-and-hpc/downloads/arm-performance-libraries) for Arm processors.
ArmPL contains optimized routines for BLAS and LAPACK that can be used from NumPy and SciPy:
- [build NumPy with ArmPL](https://gitlab.com/arm-hpc/packages/-/wikis/packages/numpy)
- [build SciPy with ArmPL](https://gitlab.com/arm-hpc/packages/-/wikis/packages/scipy)

For NumPy and SciPy it is recommended to use
[Free ArmPL version 21.0.0 released March 2021](https://developer.arm.com/tools-and-software/server-and-hpc/downloads/arm-performance-libraries) (or a later version) for correctness and good performance on Graviton processors.
ARM improved and continues to improve ArmPL performance with focus on high performance computing and common use cases in NumPy and SciPy.

### 2.2 BLIS may be a faster BLAS

The default SciPy and NumPy binary installations with `pip3 install numpy scipy`
are configured to use OpenBLAS.  The default installations of SciPy and NumPy
are easy to setup and well tested.

Some workloads will benefit from using BLIS. Benchmarking SciPy and NumPy
workloads with BLIS might allow to identify additional performance improvement.

### 2.3 Install NumPy and SciPy with BLIS on Ubuntu and Debian

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

### 2.4 Install NumPy and SciPy with BLIS on AmazonLinux2 (AL2) and RedHat

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

### 2.5 Testing NumPy and SciPy installation

To test that the installed NumPy and SciPy are built with BLIS and OpenBLAS, the
following commands will print native library dependencies:
```
python3 -c "import numpy as np; np.__config__.show()"
python3 -c "import scipy as sp; sp.__config__.show()"
```

In the case of Ubuntu and Debian these commands will print `blas` and `lapack`
which are symbolic links managed by `update-alternatives`.

### 2.6 Improving BLIS and OpenBLAS performance with multi-threading

When OpenBLAS is built with `USE_OPENMP=1` it will use OpenMP to parallelize the
computations.  The environment variable `OMP_NUM_THREADS` can be set to specify
the maximum number of threads.  If this variable is not set, the default is to
use a single thread.

To enable parallelism with BLIS, one needs to both configure with
`--enable-threading=openmp` and set the environment variable `BLIS_NUM_THREADS`
to the number of threads to use, the default is to use a single thread.

## 3. Other common Python packages

### 3.1 Pillow

As of October 30, 2020, Pillow 8.x or later have a binary wheel for all Arm64 platforms, included OSes with 64kB pages lile Redhat/Centos8.

```
pip3 install --user pillow
```

should work across all platforms we tested.


## 4. Machine Learning Python packages


### 4.1 PyTorch

PyTorch wheels for nightly builds (cpu builds) are are available for Graviton2/Arm64 since PyTorch 1.8.


```
pip install numpy
pip install --pre torch torchvision  -f https://download.pytorch.org/whl/nightly/cpu/torch_nightly.html
```

### 4.2 DGL

Make sure Pytorch is installed,  if not, follow [Pytorch installation steps](#41-pytorch)

On **Ubuntu**:

Follow the [install from source](https://github.com/dmlc/dgl/blob/master/docs/source/install/index.rst#install-from-source) instructions.


### 4.3 Sentencepiece

Make sure Pytorch is installed,  if not, follow [Pytorch installation steps](#41-pytorch)

On **Ubuntu**:

```
# git the source and build/install the libraries.
git clone https://github.com/google/sentencepiece
cd sentencepiece
mkdir build
cd build
cmake ..
make -j 8
sudo make install
sudo ldconfig -v

# move to python directory to build the wheel
cd ../python
vi make_py_wheel.sh
# change the manylinux1_{$1} to manylinux2014_{$1}

sudo python3 setup.py install
```

With the above steps, the wheel should be installed.

*Important* Before calling any python script or starting python, one of the libraries need to be set as preload for python.

```
export LD_PRELOAD=/lib/aarch64-linux-gnu/libtcmalloc_minimal.so.4:/$LD_PRELOAD
python3
```

### 4.4	Morfeusz

On **Ubuntu**:

```
# download the source
wget http://download.sgjp.pl/morfeusz/20200913/morfeusz-src-20200913.tar.gz
tar -xf morfeusz-src-20200913.tar.gz
cd Morfeusz/
sudo apt install cmake zip build-essential autotools-dev \
    python3-stdeb python3-pip python3-all-dev python3-pyparsing devscripts \
    libcppunit-dev acl  default-jdk swig python3-all-dev python3-stdeb
export JAVA_TOOL_OPTIONS=-Dfile.encoding=UTF8
mkdir build
cd build
cmake ..
sudo make install
sudo ldconfig -v
sudo PYTHONPATH=/usr/local/lib/python make install-builder
```

If you run into issue with the last command (_make install-builder_), please try:
```
sudo PYTHONPATH=`which python3` make install-builder
```
