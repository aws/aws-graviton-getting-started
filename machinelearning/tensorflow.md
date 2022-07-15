# ML inference on Graviton CPUs with TensorFlow

**Introduction**

TensorFlow is an open-source software library for machine learning and artificial intelligence. It can be used across training and inference of deep neural networks. This document covers how to use TensorFlow based machine learning inference on Graviton CPUs, what runtime configurations are important and how to debug any performance issues. The document also covers instructions for source builds and how to enable some of the downstream features.

# How to use TensorFlow on Graviton CPUs
There are multiple levels of software package abstractions available: Python wheel (easiest option), Docker container (comes with the wheel, additional packages and benchmarks), DLAMI (Deep Learning Amazon Machine Image that comes with preinstalled packages and tools) and AWS DLC (Deep Learning Contianers with TensorFlow Serving API interface). Examples of using each method are below.

**Using Python wheel**

TensorFlow wheel supports optimized onednn+acl backend for Graviton CPUs.
```
pip install tensorflow-cpu-aws
```

**Using Docker hub container**

```
# pull the tensorflow docker container with onednn-acl optimizations enabled
docker pull armswdev/tensorflow-arm-neoverse

# launch the docker image
docker run -it --rm -v /home/ubuntu/:/hostfs armswdev/tensorflow-arm-neoverse
```

**Using AWS DLAMI**

To launch a Graviton instance with a DLAMI via EC2 console:

1. Click on "Community AMIs"
2. Filter AMIs by clicking Ubuntu and Arm (64-bit) check boxes
3. Search for "Deep Learning" in search field to list the current Ubuntu based DLAMIs"
4. Select the AMI: "Deep Learning AMI Graviton TensorFlow <version>(Ubuntu 20.04) <yyyy/mm/dd>"

Here is the awscli snippet to find the latest AMI and launch it:
```
graviton_dlami=$((aws ec2 describe-images --region us-west-2 --filters  Name=architecture,Values=arm64 Name=name,Values="*Deep Learning AMI Graviton TensorFlow*" Name=owner-alias,Values=amazon  --query 'Images[] | sort_by(@, &CreationDate)[-1] | ImageId') | tr -d '"')

aws ec2 run-instances --region us-west-2 --image-id $graviton_dlami --instance-type c7g.4xlarge --count 1  --key-name <key name> --subnet-id <subnet_id> --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=256}'
```
Once Graviton instance is launched with the above DLAMI, the platform is ready for building TensorFlow based ML inference applications.The DLAMI comes with the additional libraries preinstalled, e.g. rust compilers, transformers etc, to enable transformers based (e.g. bert) inferencing applications.

**Using TensorFlow Serving with AWS DLC**

```
# Login and pull the AWS DLC for tensorflow
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 763104351884.dkr.ecr.us-west-2.amazonaws.com

docker pull 763104351884.dkr.ecr.us-west-2.amazonaws.com/tensorflow-inference-graviton:2.7.0-cpu-py38-ubuntu20.04-e3-v1.0

# Sample command to launch the tensorflow serving api with resnet50 model
docker run -p 8501:8501 --name tfserving_resnet --mount type=bind,source=/tmp/resnet,target=/models/resnet -e MODEL_NAME=resnet -t 763104351884.dkr.ecr.us-west-2.amazonaws.com/tensorflow-inference-graviton:2.7.0-cpu-py38-ubuntu20.04-e3-v1.0
```
Note: The above TensorFlow DLC supports the default Eigen backend. Please refer to the **Enable TensorFlow serving with onednn+acl backend** section below to build TensorFlow serving docker image with onednn+acl optimizations for better performance.

# Runtime configurations for optimal performance
Once the TensorFlow setup is ready, enable the below runtime configurations to achieve the best performance.
```
# The default runtime backend for tensorflow is Eigen, but typically onednn+acl provides better performance and this can be enabled by setting the below TF environment variable
export TF_ENABLE_ONEDNN_OPTS=1

# Graviton3 (e.g. c7g instance) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
grep -q bf16 /proc/cpuinfo && export DNNL_DEFAULT_FPMATH_MODE=BF16

# Make sure the openmp threads are distributed across all the processes for multi process applications to avoid over subscription for the vcpus. For example if there is a single application process, then num_processes should be set to '1' so that all the vcpus are assigned to it with one-to-one mapping to omp threads

num_vcpus=$(getconf _NPROCESSORS_ONLN)
num_processes=<number of processes>
export OMP_NUM_THREADS=$((1 > ($num_vcpus/$num_processes) ? 1 : ($num_vcpus/$num_processes)))
export OMP_PROC_BIND=false
export OMP_PLACES=cores
```

```python
# TensorFlow inter and intra_op_parallelism_thread settings are critical for the optimal workload parallelization in a multi-threaded system.
# set the inter and intra op thread count during the session creation, an example snippet is given below.
session = Session(
                 config=ConfigProto(
                      intra_op_parallelism_threads=<num. of vcpus>,
                      inter_op_parallelism_threads=1,
                )
)
```
TensorFlow recommends the graph optimization pass for inference to remove training specific nodes, fold batchnorms and fuse operators. This is a generic optimizaion across CPU, GPU or TPU inference, and the optimization script is part of the TensorFlow python [tools](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/python/tools/optimize_for_inference_lib.py). For a detailed description, please refer to the TensorFlow [Grappler](https://www.tensorflow.org/guide/graph_optimization) documentation. Below is a snippet of what libraries to import and how to invoke the Grappler passes for inference.
```python
from tensorflow.python.tools.optimize_for_inference_lib import optimize_for_inference

graph_def = tf.compat.v1.GraphDef()
with tf.compat.v1.gfile.FastGFile(model_path, "rb") as f:
     graph_def.ParseFromString(f.read())

optimized_graph_def = optimize_for_inference(graph_def, [item.split(':')[0] for item in inputs],
                    [item.split(':')[0] for item in outputs], dtypes.float32.as_datatype_enum, False)
g = tf.compat.v1.import_graph_def(optimized_graph_def, name='')
```
Note: While the Grappler optimizer covers majority of the networks, there are few scenarios where either the Grappler optimizer can't optimize the generic graph or the runtime kernel launch overhead is simply not acceptable. XLA addresses these gaps by providing an alternative mode of running models: it compiles the TensorFlow graph into a sequence of computation kernels generated specifically for the given model. Please refer to the **Enable XLA optimizations** section below to achieve the best performance with the downstream XLA optimizations.

# Evaluate performance with the standard MLPerf inference benchmarks

1. Setup MLPerf inference benchmarks and the required tools.
```
sudo apt install -y build-essential cmake libgl1-mesa-glx libglib2.0-0 libsm6 libxrender1 libxext6 python3-pip

git clone https://github.com/mlcommons/inference.git --recursive
cd inference
git checkout v2.0
cd loadgen
CFLAGS="-std=c++14" python3 setup.py bdist_wheel
pip install <dist/*.whl>
```

2. Benchmark image classification with Resnet50
```
sudo apt install python3-ck
ck pull repo:ck-env

# Download ImageNet's validation set
# These will be installed to ${HOME}/CK_TOOLS/
echo 0 | ck install package --tags=image-classification,dataset,imagenet,aux
echo 1 | ck install package --tags=image-classification,dataset,imagenet,val

# Copy the labels into the image location
cp ${HOME}/CK-TOOLS/dataset-imagenet-ilsvrc2012-aux-from.berkeley/val.txt ${HOME}/CK-TOOLS/dataset-imagenet-ilsvrc2012-val-min/val_map.txt

cd inference/vision/classification_and_detection
wget https://zenodo.org/record/2535873/files/resnet50_v1.pb

# Install the additional packages required for resnet50 inference
pip install opencv-python pycocotools psutil tqdm

# Set the data and model path
export DATA_DIR=${HOME}/CK-TOOLS/dataset-imagenet-ilsvrc2012-val-min
export MODEL_DIR=${HOME}/inference/vision/classification_and_detection

# Setup the tensorflow thread pool parameters via MLPerf env variables
export MLPERF_NUM_INTER_THREADS=1

num_vcpus=$(getconf _NPROCESSORS_ONLN)
num_processes=<number of processes>
export MLPERF_NUM_INTRA_THREADS=$((1 > ($num_vcpus/$num_processes) ? 1 : ($num_vcpus/$num_processes)))

./run_local.sh tf resnet50 cpu --scenario=SingleStream
./run_local.sh tf resnet50 cpu --scenario=Offline
```

3. Benchmark natual language processing with Bert
```
pip install transformers boto3
cd inference/language/bert
make setup
python3 run.py --backend=tf --scenario=SingleStream
python3 run.py --backend=tf --scenario=Offline
```

# Troubleshooting performance issues

The below steps help debugging performance issues with any inference application.

1. Run inference with DNNL and openmp verbose logs enabled to understand which backend is used for the tensor ops execution.
```
export DNNL_VERBOSE=1
export OMP_DISPLAY_ENV=VERBOSE
```
If there are no OneDNN logs on the terminal, this could mean either the ops are executed with Eigen or XLA backend. To switch from Eigen to OneDNN+ACL backend, set 'TF_ENABLE_ONEDNN_OPTS=1' and rerun the model inference. For non-XLA compiled graphs, there should be a flow of DNN logs with details about the shapes, prop kinds and execution times. Inspect the logs to see if there are any ops and shapes not executed with the ACL gemm kernel, instead executed by cpp reference kernel. See below example dnnl logs to understand how the ACL gemm and reference cpp kernel execution traces look like.
```
# ACL gemm kernel
dnnl_verbose,exec,cpu,convolution,gemm:acl,forward_training,src_f32::blocked:acdb:f0 wei_f32::blocked:acdb:f0 bia_f32::blocked:a:f0 dst_f32::blocked:acdb:f0,post_ops:'eltwise_relu;';,alg:convolution_direct,mb1_ic256oc64_ih56oh56kh1sh1dh0ph0_iw56ow56kw1sw1dw0pw0

# OneDNN cpp reference kernel
dnnl_verbose,exec,cpu,convolution,gemm:ref,forward_training,src_f32::blocked:abcd:f0 wei_f32::blocked:abcde:f0 bia_f32::blocked:a:f0 dst_f32::blocked:abcd:f0,post_ops:'eltwise_bounded_relu:6;';,alg:convolution_direct,mb1_g64ic64oc64_ih112oh56kh3sh2dh0ph0_iw112ow56kw3sw2dw0pw0
```
If there are any shapes not going to ACL gemm kernels, the first step is to make sure the graph has been optimized for inference via Grappler passes.
```python
from tensorflow.python.tools.optimize_for_inference_lib import optimize_for_inference

graph_def = tf.compat.v1.GraphDef()
with tf.compat.v1.gfile.FastGFile(model_path, "rb") as f:
     graph_def.ParseFromString(f.read())

optimized_graph_def = optimize_for_inference(graph_def, [item.split(':')[0] for item in inputs],
                    [item.split(':')[0] for item in outputs], dtypes.float32.as_datatype_enum, False)
g = tf.compat.v1.import_graph_def(optimized_graph_def, name='')
```
If the tensor ops and shapes are still not executed with ACL gemm kernels, please raise an ssue on [ACL github](https://github.com/ARM-software/ComputeLibrary) with the operator and shape details.

2. Once the tensor ops are executed with ACL gemm kernels, enable fast math mode, 'export DNNL_DEFAULT_FPMATH_MODE=BF16', to pick bfloat16 hybrid gemm kernels.

3. Verify the TensorFlow inter and intra thread pool settings are optimal as recommended in the runtime configurations section. Then, inspect the OMP environment to make sure the vcpu resources are not over subscribed for multi process applications. A typical openmp environment for a 64 vcpu, single process application looks like the one below.
```
OPENMP DISPLAY ENVIRONMENT BEGIN
  _OPENMP = '201511'
  OMP_DYNAMIC = 'FALSE'
  OMP_NESTED = 'FALSE'
  OMP_NUM_THREADS = '64'
  OMP_SCHEDULE = 'DYNAMIC'
  OMP_PROC_BIND = 'FALSE'
  OMP_PLACES = ''
  OMP_STACKSIZE = '0'
  OMP_WAIT_POLICY = 'PASSIVE'
  OMP_THREAD_LIMIT = '4294967295'
  OMP_MAX_ACTIVE_LEVELS = '1'
  OMP_CANCELLATION = 'FALSE'
  OMP_DEFAULT_DEVICE = '0'
  OMP_MAX_TASK_PRIORITY = '0'
  OMP_DISPLAY_AFFINITY = 'FALSE'
  OMP_AFFINITY_FORMAT = 'level %L thread %i affinity %A'
  OMP_ALLOCATOR = 'omp_default_mem_alloc'
  OMP_TARGET_OFFLOAD = 'DEFAULT'
  GOMP_CPU_AFFINITY = ''
  GOMP_STACKSIZE = '0'
  GOMP_SPINCOUNT = '300000'
OPENMP DISPLAY ENVIRONMENT END
```

4. The above triaging steps cover typical issues due to the missing compiler or runtime configurations. If you are stuck with any of these steps or if the performance is still not meeting the target, please raise an issue on [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) github.

# Building TensorFlow from sources

While the packages for python wheel/docker container/DLAMI provide stable baseline for ML application development and production, they lack the latest fixes and optimizations from the development branches. This section provides instructions for building TensorFlow from sources, to build the master branch or to incorporate the downstream optimizations.
```
# This step is required if gcc-10 is not the default version on the OS distribution, e.g. Ubuntu 20.04
# Install gcc-10 and g++-10 as it is required for Arm Compute Library build.
sudo apt install -y gcc-10 g++-10
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 1
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-10 1

# Install the required pip packages
pip3 install numpy packaging

# Install bazel for aarch64
mkdir bazel
cd bazel
wget https://github.com/bazelbuild/bazel/releases/download/5.1.1/bazel-5.1.1-linux-arm64
mv bazel-5.1.1-linux-arm64 bazel
chmod a+x bazel
export PATH=/home/ubuntu/bazel/:$PATH

# Clone the tensorflow repository
git clone https://github.com/tensorflow/tensorflow.git
cd tensorflow
# Optionally checkout the stable version if needed
git checkout <latest stable version>

# Set the build configuration
export HOST_C_COMPILER=(which gcc)
export HOST_CXX_COMPILER=(which g++)
export PYTHON_BIN_PATH=(which python)
export USE_DEFAULT_PYTHON_LIB_PATH=1
export TF_ENABLE_XLA=1
export TF_DOWNLOAD_CLANG=0
export TF_SET_ANDROID_WORKSPACE=0
export TF_NEED_MPI=0
export TF_NEED_ROCM=0
export TF_NEED_GCP=0
export TF_NEED_S3=0
export TF_NEED_OPENCL_SYCL=0
export TF_NEED_CUDA=0
export TF_NEED_HDFS=0
export TF_NEED_OPENCL=0
export TF_NEED_JEMALLOC=1
export TF_NEED_VERBS=0
export TF_NEED_AWS=0
export TF_NEED_GDR=0
export TF_NEED_OPENCL_SYCL=0
export TF_NEED_COMPUTECPP=0
export TF_NEED_KAFKA=0
export TF_NEED_TENSORRT=0
./configure

# Issue bazel build command with 'mkl_aarch64' config to enable onednn+acl backend
bazel build --verbose_failures -s --config=mkl_aarch64  //tensorflow/tools/pip_package:build_pip_package //tensorflow:libtensorflow_cc.so //tensorflow:install_headers

# Create and install the wheel
./bazel-bin/tensorflow/tools/pip_package/build_pip_package ./wheel-TF2.9.0-py3.8-aarch64

# The output wheel is generated in /home/ubuntu/tensorflow/wheel-TF2.9.0-py3.8-aarch64
pip install <wheel-TF2.9.0-py3.8-aarch64/*.whl>
```

# Enable TensorFlow Serving with onednn+acl backend

[TensorFlow Serving](https://www.tensorflow.org/tfx/guide/serving) is a flexible, high-performance serving system for machine learning models, designed for production environments. TensorFlow Serving makes it easy to deploy new algorithms and experiments, while keeping the same server architecture and APIs. TensorFlow Serving provides out-of-the-box integration with TensorFlow models, but can be easily extended to serve other types of models and data.

As of 2.9.0 version, TensorFlow Serving for aarch64 supports TensorFlow with Eigen backend. For the best performance, with onednn+acl backend, please follow the below instructions to cherrypick the PRs and to rebuild the TensorFlow Serving docker image.
```
# Clone the tf serving repository
git clone https://github.com/tensorflow/serving.git
cd serving

# Pull https://github.com/tensorflow/serving/pull/1954
git fetch origin pull/1954/head:tfs_docker_aarch64

# Merge them
git checkout tfs_aarch64
git merge tfs_docker_aarch64

# Invoke the docker build script to trigger mkl aarch64 config build
docker build -f tensorflow_serving/tools/docker/Dockerfile.devel-mkl-aarch64 -t tfs:mkl_aarch64 .

# Command to launch the serving api with onednn+acl backend, and BF16 kernels for a resnet model
docker run -p 8501:8501 --name tfserving_resnet --mount type=bind,source=/tmp/resnet,target=/models/resnet -e MODEL_NAME=resnet -e TF_ENABLE_ONEDNN_OPTS=1 -e DNNL_DEFAULT_FPMATH_MODE=BF16 -e -t tfs:mkl_aarch64
```

# Enable XLA optimizations

While the Grappler optimizer covers majority of the networks, there are few scenarios where either the Grappler optimizer can't optimize the generic graph or the runtime kernel launch overhead is simply not acceptable. XLA addresses these gaps by providing an alternative mode of running models: it compiles the TensorFlow graph into a sequence of computation kernels generated specifically for the given model. TensorFlow-2.9.0 supports aarch64 xla backend with Eigen runtime. For the best performance please cherrypick the [PR](https://github.com/tensorflow/tensorflow/pull/55534) and rebuild the TensorFlow libraries.
```
# This step is required if gcc-10 is not the default version on the OS distribution, e.g. Ubuntu 20.04
# Install gcc-10 and g++-10 as it is required for Arm Compute Library build
sudo apt install -y gcc-10 g++-10
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 1
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-10 1

# Install the required pip packages
pip3 install numpy packaging

# Install bazel for aarch64
mkdir bazel
cd bazel
wget https://github.com/bazelbuild/bazel/releases/download/5.1.1/bazel-5.1.1-linux-arm64
mv bazel-5.1.1-linux-arm64 bazel
chmod a+x bazel
export PATH=/home/ubuntu/bazel/:$PATH

# Clone the tensorflow repository
git clone https://github.com/tensorflow/tensorflow.git
cd tensorflow

# Pull the below PR if building from TensorFlow 2.9.0
# If building from the tensorflow master no need to pull any PR
git fetch origin pull/55534/head:xla_acl
git checkout xla_acl

# Set the build configuration
export HOST_C_COMPILER=(which gcc)
export HOST_CXX_COMPILER=(which g++)
export PYTHON_BIN_PATH=(which python)
export USE_DEFAULT_PYTHON_LIB_PATH=1
export TF_ENABLE_XLA=1
export TF_DOWNLOAD_CLANG=0
export TF_SET_ANDROID_WORKSPACE=0
export TF_NEED_MPI=0
export TF_NEED_ROCM=0
export TF_NEED_GCP=0
export TF_NEED_S3=0
export TF_NEED_OPENCL_SYCL=0
export TF_NEED_CUDA=0
export TF_NEED_HDFS=0
export TF_NEED_OPENCL=0
export TF_NEED_JEMALLOC=1
export TF_NEED_VERBS=0
export TF_NEED_AWS=0
export TF_NEED_GDR=0
export TF_NEED_OPENCL_SYCL=0
export TF_NEED_COMPUTECPP=0
export TF_NEED_KAFKA=0
export TF_NEED_TENSORRT=0
./configure

# Issue bazel build command with 'mkl_aarch64' config to enable onednn+acl backend
bazel build --verbose_failures -s --config=mkl_aarch64  //tensorflow/tools/pip_package:build_pip_package //tensorflow:libtensorflow_cc.so //tensorflow:install_headers

# Create and install the wheel
./bazel-bin/tensorflow/tools/pip_package/build_pip_package ./wheel-TF2.9.0-py3.8-aarch64

# The wheel is generated in /home/ubuntu/tensorflow/wheel-TF2.9.0-py3.8-aarch64
pip install <wheel-TF2.9.0-py3.8-aarch64/*.whl>
```
A simple way to start using XLA in TensorFlow models without any changes is to enable auto-clustering, which automatically finds clusters (connected subgraphs) within the TensorFlow functions which can be compiled and executed using XLA. Auto-clustering on CPU can be enabled by setting the TF_XLA_FLAGS environment variables as below:
```python
# Set the jit level for the current session via the config
jit_level = tf_compat_v1.OptimizerOptions.ON_1
config.graph_options.optimizer_options.global_jit_level = jit_level
```
```
# Enable auto clustering for CPU backend
export TF_XLA_FLAGS="--tf_xla_auto_jit=2 --tf_xla_cpu_global_jit"
```

**Troubleshooting xla performance issues**

1. If XLA performance improvements are not as expected, the first step is to dump and inspect the XLA optimized graph and ensure there are not many op duplications resulted from the op fusion and other other optimization passes. XLA provides a detailed logging mechanism to dump the state at different checkpoints during the graph optimization passes. At high level, inspecting the graphs generated before and after the XLA pass is sufficient to understand whether XLA compilation is the correct optimization for the current graph. Please refer to the below instructions for enabling auto-clustering, along with .dot generation (using MLPerf Bert inference in SingleStream mode as the example here) and also commands to generate .svg version for easier visualization of the XLA generated graphs.
```
# To enable XLA auto clustering, and to generate .dot files
XLA_FLAGS="--xla_dump_to=/tmp/generated  --xla_dump_hlo_as_dot" TF_XLA_FLAGS="--tf_xla_auto_jit=2 --tf_xla_cpu_global_jit" python run.py --backend=tf --scenario=SingleStream

# To convert the .dot file into .svg
sudo apt install graphviz
dot -Tsvg <.dot file to be converted> >  <output .svg name>

e.g.
dot -Tsvg 1645569101166784.module_0000.cluster_51__XlaCompiledKernel_true__XlaHasReferenceVars_false__XlaNumConstantArgs_0__XlaNumResourceArgs_0_.80.before_optimizations.dot > module0_before_opts.svg

dot -Tsvg 1645569101166784.module_0000.cluster_51__XlaCompiledKernel_true__XlaHasReferenceVars_false__XlaNumConstantArgs_0__XlaNumResourceArgs_0_.80.cpu_after_optimizations.dot > module0_after_opts.svg
```

2. Once the XLA graph looks as expected (without too many duplicated nodes), check how the ops are emitted. Currently XLA framework logging is under the same TF CPP logging, and level 1 is sufficient to get most of the info traces.
```
# Enable TF CPP framework logging
export TF_CPP_MAX_VLOG_LEVEL=1
```
Then look for the emitter level traces to understand how each op for a given shape is lowered to LLVM IR. The below traces show whether the XLA ops are emitted to ACL or Eigen runtime.
```
# ACL runtime traces
__xla_cpu_runtime_ACLBatchMatMulF32

__xla_cpu_runtime_ACLConv2DF32

# Eigen runtime traces
__xla_cpu_runtime_EigenBatchMatMulF32

__xla_cpu_runtime_EigenConv2DF32
```
If the shapes are not emitted by the ACL runtime, check the source build configuration to make sure 'mkl_aarch64' bazel config is enabled (which internally enables '--define=build_with_acl=true' bazel configuration). If the LLVM IR still doesn't emit the ACL runtime, please raise an ssue on [ACL github](https://github.com/ARM-software/ComputeLibrary) with the operator and shape details.

3. The above triaging steps cover typical issues due to the missing compiler or runtime configurations. If you are stuck with any of these steps or if the performance is still not meeting the target, please raise an issue on [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) github.

