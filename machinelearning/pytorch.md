# ML inference on Graviton CPUs with PyTorch

**Introduction**

PyTorch is an open-source machine learning framework based on the Torch library, used for applications such as computer vision and natural language processing. It can be used across training and inference of deep neural networks. This document covers how to use PyTorch based machine learning inference on Graviton CPUs, what runtime configurations are important and how to debug any performance issues. The document also covers instructions for source builds and how to enable some of the downstream features.

# How to use PyTorch on Graviton CPUs
There are multiple levels of software package abstractions available: Python wheel (easiest option but multiple wheels to be installed), AWS DLC (Deep Learning Container, comes with all the packages installed) and the Docker hub images (additionally comes with MLPerf benchmarks). Examples of using each method are below.

**Using Python wheel**

PyTorch wheel, starting 1.13 release, supports OneDNN+Arm Compute Library backend for Graviton CPUs that improve the performance by ~2.5x for Resnet50 and Bert inference compared to PyTorch 1.12 wheel.
```
pip install torch

pip install torchvision

pip install torch-xla

pip install torchaudio

pip install torchtext
```

**AWS Graviton PyTorch DLC**

3Q'22 DLCs are PyTorch1.12 based but include the optimizations that were included in PyTorch1.13, so the performance is nearly identical.

```
# Login and pull the AWS DLC for pytorch
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 763104351884.dkr.ecr.us-east-1.amazonaws.com

docker pull 763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-inference-graviton:1.12.1-cpu-py38-ubuntu20.04-ec2
```

**Using Docker hub container**

As of Oct'22 the docker images are PyTorch1.12 based but include the optimizations that were included in PyTorch1.13, so the performance is nearly identical.

```
# pull pytorch docker container with onednn-acl and xla optimizations enabled
docker pull armswdev/pytorch-arm-neoverse:r22.10-torch-1.12.0-onednn-acl

# launch the docker image
docker run -it --rm -v /home/ubuntu/:/hostfs armswdev/pytorch-arm-neoverse:r22.10-torch-1.12.0-onednn-acl
```

# Runtime configurations for optimal performance
Once the PyTorch setup is ready, enable the below runtime configurations to achieve the best performance.
```
# Graviton3 (e.g. c7g instance) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
grep -q bf16 /proc/cpuinfo && export DNNL_DEFAULT_FPMATH_MODE=BF16

# Enable Transparent huge pages to minimize the memory allocation overhead for batched inference
echo always > /sys/kernel/mm/transparent_hugepage/enabled

# Make sure the openmp threads are distributed across all the processes for multi process applications to avoid over subscription for the vcpus. For example if there is a single application process, then num_processes should be set to '1' so that all the vcpus are assigned to it with one-to-one mapping to omp threads

num_vcpus=$(getconf _NPROCESSORS_ONLN)
num_processes=<number of processes>
export OMP_NUM_THREADS=$((1 > ($num_vcpus/$num_processes) ? 1 : ($num_vcpus/$num_processes)))
export OMP_PROC_BIND=false
export OMP_PLACES=cores
```

# Evaluate performance with PyTorch benchmark and the standard MLPerf inference benchmarks

1. Resnet50 benchmarking

(a) Setup PyTorch benchmark
```
https://github.com/pytorch/benchmark

git clone https://github.com/pytorch/benchmark.git

cd benchmark
sudo python3 install.py --continue_on_fail
```
(b) Run inference with torch script
```
python3 run.py resnet50 -d cpu -m jit -t eval --use_cosine_similarity
```

2. Bert benchmarking

(a) Setup MLPerf inference benchmark
```
git clone https://github.com/mlcommons/inference.git --recursive
cd inference
git checkout v2.0
cd loadgen
CFLAGS="-std=c++14" python3 setup.py bdist_wheel
pip install dist/*.whl

pip install transformers boto3
cd inference/language/bert
make setup
```
(b) Enable torch-xla device for inference
```
export XRT_DEVICE_MAP="CPU:0;/job:localservice/replica:0/task:0/device:XLA_CPU:0"
export XRT_WORKERS="localservice:0;grpc://localhost:9002"
```
cd inference/language/bert
vi pytorch_SUT.py

```python
import torch_xla
import torch_xla.core.xla_model as xm
.
.
.
.
# self.dev = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu"). --> standard way to get cuda or cpu device. Instead of this, use the below to get xla_device.
self.dev = xm.xla_device()
.
.
.
for i in range(len(query_samples)):
   eval_features = self.qsl.get_features(query_samples[i].index)
   model_output = self.model.forward(input_ids=torch.LongTensor(eval_features.input_ids).unsqueeze(0).to(self.dev),
         attention_mask=torch.LongTensor(eval_features.input_mask).unsqueeze(0).to(self.dev),
         token_type_ids=torch.LongTensor(eval_features.segment_ids).unsqueeze(0).to(self.dev))
   xm.mark_step()
```

(c) Execute Bert Singlestream scenario
```
python3 run.py --backend=pytorch --scenario=SingleStream
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

3. Make sure transparent huge pages are enabled
```
echo always > /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/enabled
[always] madvise never
```

4. The above triaging steps cover typical issues due to the missing runtime configurations. If you are stuck with any of these steps or if the performance is still not meeting the target, please raise an issue on [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) github.

# Building PyTorch from source

While the packages for docker container and wheels provide stable baseline for ML application development and production, they lack the latest fixes and optimizations from the master branch. The scripts for building the torch, torch-xla and torchvision wheels are avaiable in torch-xla repo. This section provides instructions for using those scripts.
```
# The PyTorch and torch-xla build scripts are available in torch-xla repo
git clone https://github.com/pytorch/xla.git
cd xla

# To build and install PyTorch 1.12 release version
./scripts/build_torch_wheels.sh 3.8 v1.12.0

# To build and install PyTorch master branch
./scripts/build_torch_wheels.sh 3.8 nightly

```

# How to enable torch-xla for model inferece
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
