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

On all distributions, additionnal compile time dependencies might be needed depending on the Python modules you are trying to install.

### 1.2 Recommended versions

When adopting Graviton2, it is recommended to use recent software versions as much as possible, and Python is no exception.

Python 2.7 is EOL since January the 1st 2020, it is definitely recommended to upgrade to a Python 3.x version before moving to Graviton2.

Python 3.6 will reach [EOL in December, 2021](https://www.python.org/dev/peps/pep-0494/#lifespan), so when starting to port an application to Graviton2, it is recommended to target at least Python 3.7.

### 1.3 Python on Centos 8 and RHEL 8

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
computing libraries such as ATLAS, BLAS, BLIS, OpenBLAS, etc.  These libraries
contain code tuned for Graviton processors.

It is recommended to use the latest software versions as much as possible. If the latest
version migration is not feasible, please ensure that it is atleast the minimum version
recommended below because multiple fixes related to data precision and correctness on
aarch64 went into OpenBLAS between v0.3.9 and v0.3.17 and the below SciPy and NumPy versions
upgraded OpenBLAS from v0.3.9 to OpenBLAS v0.3.17.

OpenBLAS:  >= v0.3.17
SciPy: >= v1.7.2
NumPy: >= 1.21.1


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

### 2.6 Graviton2 support in Conda / Anaconda
Anaconda is a distribution of the Python and R programming languages for scientific computing, that aims to simplify package management and deployment.

Anaconda has announced [support for AWS Graviton2 on May 14, 2021](https://www.anaconda.com/blog/anaconda-aws-graviton2).

Instructions to install the full Anaconda package installer can be found at https://docs.anaconda.com/anaconda/install/graviton2/ .

Anaconda also offers a lightweight version called [Miniconda](https://docs.conda.io/en/latest/miniconda.html) which is a small, bootstrap version of Anaconda that includes only conda, Python, the packages they depend on, and a small number of other useful packages, including pip, zlib and a few others.

Here is an example on how to use it to install [numpy](https://numpy.org/) and [pandas](https://pandas.pydata.org/) for Python 3.9.

The first step is to install conda:
```
$ wget https://repo.anaconda.com/miniconda/Miniconda3-py39_4.10.3-Linux-aarch64.sh
$ chmod a+x chmod a+x Miniconda3-py39_4.10.3-Linux-aarch64.sh
$ ./Miniconda3-py39_4.10.3-Linux-aarch64.sh
```

Once installed, you can either use the `conda` command directly to install packages, or write an environment definition file and create the corresponding environment.

Here's an example to install [numpy](https://numpy.org/) and [pandas](https://pandas.pydata.org/) (`graviton-example.yml`):
```
name: graviton-example
dependencies:
  - numpy
  - pandas
```

The next step is to instanciate the environment from that definition:
```
$ conda env create -f graviton-example.yml
```

And you can now use numpy and pandas for Python 3.9.

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
