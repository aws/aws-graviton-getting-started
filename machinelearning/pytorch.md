# ML inference on Graviton CPUs with PyTorch

**Introduction**

PyTorch is an open-source machine learning framework based on the Torch library, used for applications such as computer vision and natural language processing. It can be used across training and inference of deep neural networks. This document covers how to use PyTorch based machine learning inference on Graviton CPUs, what runtime configurations are important and how to debug any performance issues. The document also covers instructions for source builds and how to enable some of the downstream features.

# How to use PyTorch on Graviton CPUs
There are multiple levels of software package abstractions available: AWS DLC (Deep Learning Container, comes with all the packages installed), Python wheel (easier option for integrating pytorch inference into an existing service), and the Docker hub images (comes with downstream experimental features). Examples of using each method are below.

**AWS Graviton PyTorch DLC**

4Q'23 AWS Graviton DLCs are based on PyTorch 2.1. These DLCs continue to deliver the best performance on Graviton for bert and roberta sentiment analysis and fill mask models, making Graviton3 the most cost effective CPU platform on the AWS cloud for these models.

```
sudo apt-get update
sudo apt-get -y install awscli docker

# Login to ECR to avoid image download throttling
aws ecr get-login-password --region us-east-1 \
| docker login --username AWS \
  --password-stdin 763104351884.dkr.ecr.us-east-1.amazonaws.com

# Pull the AWS DLC for pytorch
docker pull 763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-inference-graviton:2.1.0-cpu-py310-ubuntu20.04-ec2
```

**Using Python wheels**

```
# Install Python
sudo apt-get update
sudo apt-get install -y python3 python3-pip

# Upgrade pip3 to the latest version
python3 -m pip install --upgrade pip

# Install PyTorch and extensions
python3 -m pip install torch
python3 -m pip install torchvision torchaudio
```

**Using Docker hub container**

4Q'23 Docker hub images from armswdev are based on PyTorch 2.0.0, but also include additional downstream optimizations and experimental features. These are avaiable for trying out the experimental downstream features and provide early feedback.

```
# Pull pytorch docker container with onednn-acl optimizations enabled
docker pull armswdev/pytorch-arm-neoverse:r23.10-torch-2.0.0-onednn-acl

# Launch the docker image
docker run -it --rm -v /home/ubuntu/:/hostfs armswdev/pytorch-arm-neoverse:r23.10-torch-2.0.0-onednn-acl
```

# Prerequisites

1. It is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best PyTorch inference performance on Graviton3 instances
2. Python 3.8 is the minimum supported python version starting PyTorch 2.0.0. For more details, please refer to PyTorch 2.0 [release note](https://github.com/pytorch/pytorch/releases/tag/v2.0.0)

# Runtime configurations for optimal performance

AWS DLCs come with all the optimizations enabled, so, there are no additional runtime configurations required. Where as for the python wheels and the docker hub images, enable the below runtime configurations to achieve the best performance.
```
# Graviton3(E) (e.g. c7g, c7gn and Hpc7g instances) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
grep -q bf16 /proc/cpuinfo && export DNNL_DEFAULT_FPMATH_MODE=BF16

# Enable primitive caching to avoid the redundant primitive allocation
# latency overhead. Please note this caching feature increases the
# memory footprint. Tune this cache capacity to a lower value to
# reduce the additional memory requirement.
export LRU_CACHE_CAPACITY=1024

# Enable Transparent huge page allocations from PyTorch C10 allocator
export THP_MEM_ALLOC_ENABLE=1

# Make sure the openmp threads are distributed across all the processes for multi process applications to avoid over subscription for the vcpus. For example if there is a single application process, then num_processes should be set to '1' so that all the vcpus are assigned to it with one-to-one mapping to omp threads

num_vcpus=$(getconf _NPROCESSORS_ONLN)
num_processes=<number of processes>
export OMP_NUM_THREADS=$((1 > ($num_vcpus/$num_processes) ? 1 : ($num_vcpus/$num_processes)))
export OMP_PROC_BIND=false
export OMP_PLACES=cores
```

# Evaluate performance with PyTorch benchmark

1. Resnet50 benchmarking

```
# Clone PyTorch benchmark repo
git clone https://github.com/pytorch/benchmark.git

# Setup Resnet50 benchmark
cd benchmark
python3 install.py resnet50

# Install the dependent wheels
python3 -m pip install numba

# Run Resnet50 inference in jit mode. On successful completion of the inference runs,
# the script prints the inference latency and accuracy results

# Batch mode, the default batch size is 32
python3 run.py resnet50 -d cpu -m jit -t eval --use_cosine_similarity

# Single inference mode
python3 run.py resnet50 -d cpu -m jit -t eval --use_cosine_similarity --bs 1

```

2. Bert benchmarking

```
# Clone PyTorch benchmark repo
git clone https://github.com/pytorch/benchmark.git

# Setup Bert benchmark
cd benchmark
python3 install.py bert

# Run BERT_pytorch inference in jit mode. On successful completion of the inference runs,
# the script prints the inference latency and accuracy results

# Batch mode
python3 run.py BERT_pytorch -d cpu -m jit -t eval --use_cosine_similarity --bs 32

# Single inference mode
python3 run.py BERT_pytorch -d cpu -m jit -t eval --use_cosine_similarity --bs 1
```

# Troubleshooting performance issues

The below steps help debugging performance issues with pytorch inference.

1. Run inference with DNNL and openmp verbose logs enabled to understand which backend is used for the tensor ops execution.
```
export DNNL_VERBOSE=1
export OMP_DISPLAY_ENV=VERBOSE
```
If there are no OneDNN logs on the terminal, this could mean either the ops are executed with OpenBLAS or XLA backend. For OneDNN accelerated ops, there should be a flow of DNN logs with details about the shapes, prop kinds and execution times. Inspect the logs to see if there are any ops and shapes not executed with the ACL gemm kernel, instead executed by cpp reference kernel. See below example dnnl logs to understand how the ACL gemm and reference cpp kernel execution traces look like.
```
# ACL gemm kernel
dnnl_verbose,exec,cpu,convolution,gemm:acl,forward_training,src_f32::blocked:acdb:f0 wei_f32::blocked:acdb:f0 bia_f32::blocked:a:f0 dst_f32::blocked:acdb:f0,post_ops:'eltwise_relu;';,alg:convolution_direct,mb1_ic256oc64_ih56oh56kh1sh1dh0ph0_iw56ow56kw1sw1dw0pw0

# OneDNN cpp reference kernel
dnnl_verbose,exec,cpu,convolution,gemm:ref,forward_training,src_f32::blocked:abcd:f0 wei_f32::blocked:abcde:f0 bia_f32::blocked:a:f0 dst_f32::blocked:abcd:f0,post_ops:'eltwise_bounded_relu:6;';,alg:convolution_direct,mb1_g64ic64oc64_ih112oh56kh3sh2dh0ph0_iw112ow56kw3sw2dw0pw0
```
If the tensor ops and shapes are still not executed with ACL gemm kernels, please raise an issue on [ACL github](https://github.com/ARM-software/ComputeLibrary) with the operator and shape details.

2. Once the tensor ops are executed with ACL gemm kernels, enable fast math mode, 'export DNNL_DEFAULT_FPMATH_MODE=BF16', to pick bfloat16 hybrid gemm kernels.

3. Linux thp (transparent huge pages) improve the memory allocation latencies for large tensors. This is important especially for batched inference use cases where the tensors are typically larger than 30MB. To take advantage of the thp allocations, make sure PyTorch C10 memory allocator optimizations are enabled. Most of the Linux based OS distributions come with "madvise" as the default thp allocation mode, if it comes with "never" then set it to "madvise" mode first.
```
# Check the default thp mode in kernel
cat /sys/kernel/mm/transparent_hugepage/enabled

# If the thp mode is [never], then set it to 'madvise'
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/enabled
always [madvise] never

# Enable THP allocations from C10 memory allocator
export THP_MEM_ALLOC_ENABLE=1
```

4. Starting with the release of PyTorch 1.13.0, mkldnn (OneDNN) backend is enabled for 'matmul' operator. While mkldnn along with ACL provides the best performance across several tensor shapes, the runtime setup overhead may not be acceptable for smaller tensor shapes. For use cases with fewer input tokens, check the performance by disabling the mkldnn backend and switching to openBLAS gemm kernels. This has shown improvement for shapes like "12x12x64:12x64x12:12x12x12" and "12x16x16:12x16x64:12x16x64".
```
export TORCH_MKLDNN_MATMUL_MIN_DIM=1024
```

5. The above triaging steps cover typical issues due to the missing runtime configurations. If you are stuck with any of these steps or if the performance is still not meeting the target, please raise an issue on [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) github.

# Building PyTorch from source

With AWS Graviton DLCs and python wheels available for every official PyTorch release, there may not be a need for customers to build PyTorch from sources. However, to make the user guide complete, this section provides instructions for building the torch wheels from sources.

For more automated single step building of pytorch wheels from a release tag, please use the pyTorch builder repo [scripts](https://github.com/pytorch/builder/blob/main/aarch64_linux/build_aarch64_wheel.py). For building torch wheel alone with the downstream experimental features, please use the below steps.

```
# This step is required if gcc-10 is not the default version on the OS distribution, e.g. Ubuntu 20.04
# Install gcc-10 and g++-10 as it is required for Arm Compute Library build.
sudo apt install -y gcc-10 g++-10
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 1
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-10 1

# Install the required tools
sudo apt install -y scons cmake

# Build Arm Compute Library (ACL)
cd $HOME
git clone https://github.com/ARM-software/ComputeLibrary.git
cd ComputeLibrary
git checkout v23.05.1
scons Werror=1 -j8 debug=0 neon=1 opencl=0 os=linux openmp=1 cppthreads=0 arch=armv8a multi_isa=1 build=native

# Build PyTorch from the tip of the tree
cd $HOME
git clone https://github.com/pytorch/pytorch.git
cd pytorch
git submodule sync
git submodule update --init --recursive

# Set the ACL root directory and enable MKLDNN backend
export ACL_ROOT_DIR=$HOME/ComputeLibrary
export USE_MKLDNN=ON USE_MKLDNN_ACL=ON

python3 setup.py bdist_wheel

# Install the wheel
pip3 install <dist/*.whl>

```

# Using Torch XLA for model inference

While the PyTorch torchscript and the runtime backend covers majority of the networks, there are few scenarios where either the default optimizer can't optimize the generic graph or the runtime kernel launch overhead is simply not acceptable. XLA addresses these gaps by providing an alternative mode of running models: it compiles the PyTorch graph into a sequence of computation kernels generated specifically for the given model.

**How to build torach-xla wheel**

The scripts for building the torch and torch-xla wheels are avaiable in torch-xla repo. This section provides instructions for using those scripts.
```
# The PyTorch and torch-xla build scripts are available in torch-xla repo
git clone https://github.com/pytorch/xla.git
cd xla

# To build and install PyTorch from the tip of the tree
./scripts/build_torch_wheels.sh 3.8 nightly

```

**How to enable torch-xla for model inferece**

PyTorch/XLA creates a TensorFlow local server everytime a new PyTorch/XLA program is run. The XRT (XLA Runtime) client connects to the local TensorFlow server. So, to enable XLA device, set the XRT device map and worker as beolow
```
export XRT_DEVICE_MAP="CPU:0;/job:localservice/replica:0/task:0/device:XLA_CPU:0"
export XRT_WORKERS="localservice:0;grpc://localhost:9002"
```
The below snippet highlights how easy it is to switch any  model to run on XLA. The model definition, dataloader, optimizer and training loop can work on any device. The only XLA-specific code is a couple lines that acquire the XLA device and mark the step. Calling xm.mark_step() at the end of each inference iteration causes XLA to execute its current graph and update the model’s parameters
```python
import torch_xla
import torch_xla.core.xla_model as xm

# instead of the standard 'cuda' or 'cpu' device, create the xla device.
device = xm.xla_device()
.
.
.
xm.mark_step() # at the end of each inference iteration
```
