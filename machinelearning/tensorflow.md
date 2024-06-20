# ML inference on Graviton CPUs with TensorFlow

**Introduction**

TensorFlow is an open-source software library for machine learning and artificial intelligence. It can be used across training and inference of deep neural networks. This document covers how to use TensorFlow based machine learning inference on Graviton CPUs, what runtime configurations are important and how to debug any performance issues.

# How to use TensorFlow on Graviton CPUs
There are multiple levels of software package abstractions available:
* AWS DLC (Deep Learning Container, gives the best performance, comes with additional optimizations on top of the official wheels, and all the packages installed)
* Python wheel (easiest option to get the release features) and
* Docker hub images (comes with downstream experimental features). Examples of using each method are below.

**AWS Graviton TensorFlow DLC**

As of May 2024, AWS Graviton DLCs are based on TensorFlow 2.14.1. The DLCs enable the Graviton optimizations by default.

```
# Login and pull the AWS DLC for tensorflow
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 763104351884.dkr.ecr.us-west-2.amazonaws.com

docker pull 763104351884.dkr.ecr.us-west-2.amazonaws.com/tensorflow-inference-graviton:2.14.1-cpu-py310-ubuntu20.04-ec2

# Sample command to launch the tensorflow serving api with resnet50 model
docker run -p 8501:8501 --name tfserving_resnet --mount type=bind,source=/tmp/resnet,target=/models/resnet -e MODEL_NAME=resnet -t 763104351884.dkr.ecr.us-west-2.amazonaws.com/tensorflow-inference-graviton:2.14.1-cpu-py310-ubuntu20.04-ec2
```

**Using Python wheel**

```
pip install tensorflow
```

**Using Docker hub container**

As of May 2024, Docker hub images from armswdev are based on TensorFlow 2.15.1, but also include additional downstream optimizations and experimental features. These are avaiable for trying out the experimental downstream features and provide early feedback.

```
# pull the tensorflow docker container with onednn-acl optimizations enabled
docker pull armswdev/tensorflow-arm-neoverse

# launch the docker image
docker run -it --rm -v /home/ubuntu/:/hostfs armswdev/tensorflow-arm-neoverse
```

# Prerequisites

It is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best TensorFlow inference performance on Graviton3 instances.

# Runtime configurations for optimal performance

AWS DLCs come with all the optimizations enabled, so, there are no additional runtime configurations required. Where as for the python wheels and the docker hub images, enable the below runtime configurations to achieve the best performance.
```
# For TensorFlow versions older than 2.14.0, the default runtime backend is Eigen, but typically onednn+acl provides better performance. To enable the onednn+acl backend, set the following TF environment variable
export TF_ENABLE_ONEDNN_OPTS=1

# Graviton3(E) (e.g. c7g, c7gn, and hpc7g instances) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
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
If there are no OneDNN logs on the terminal, this could mean the ops are executed with Eigen. To switch from Eigen to OneDNN+ACL backend, set 'TF_ENABLE_ONEDNN_OPTS=1' and rerun the model inference. There should be a flow of DNN logs with details about the shapes, prop kinds and execution times. Inspect the logs to see if there are any ops and shapes not executed with the ACL gemm kernel, instead executed by cpp reference kernel. See below example dnnl logs to understand how the ACL gemm and reference cpp kernel execution traces look like.
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

We recommend using the official distributions of TensorFlow for Graviton, but there are cases developers may want to compile TensorFlow from source. One such case would be to experiment with new features or develop custom features. This section outlines the recommended way to compile TensorFlow from source. Please note that "--config=mkl_aarch64_threadpool" is the recommended bazel config for aarch64 builds. The following instructions cover both gcc and clang builds.


**Install the compiler tool chain**

For Clang builds, install the llvm version recommended in the TensorFlow release. For example, llvm-17.0.2 is recommended for TF v2.16

```
wget https://github.com/llvm/llvm-project/releases/download/llvmorg-17.0.2/clang+llvm-17.0.2-aarch64-linux-gnu.tar.xz -O- | sudo tar xv -J --strip-component=1 -C /usr
```

For GCC builds, gcc10 or above version is required for building mkl_aarch64_threadpool configuration with Arm Compute Library. The following step is required if gcc-10+ is not the default version on the OS distribution, e.g. Ubuntu 20.04

```
sudo apt install -y gcc-10 g++-10
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 1
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-10 1

```

**Install the required packages**
```
pip3 install numpy packaging
sudo apt install patchelf

# Install bazel for aarch64
# Bazel version required depends on the TensorFlow version, please install the correct one
# https://github.com/tensorflow/tensorflow/blob/master/.bazelversion captures the bazel version details
# For example, tensorflow 2.16.1 build requires bazel 6.5.0
BAZEL=6.5.0  # modify version as needed
sudo wget https://github.com/bazelbuild/bazel/releases/download/$BAZEL/bazel-$BAZEL-linux-arm64 -O /usr/local/bin/bazel
sudo chmod +x /usr/local/bin/bazel
```

**Configure and build**

```
# Clone the tensorflow repository
git clone https://github.com/tensorflow/tensorflow.git
cd tensorflow
# Optionally checkout the stable version if needed
TF_VERSION=v2.16.1 # modify version as needed
git checkout $TF_VERSION

# Set the build configuration
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

# Configure the build setup.
# Leave the default option for everything except the compiler option. Enter "Y/n" depending on whether Clang or gcc build is required.
# Do you want to use Clang to build TensorFlow? [Y/n]:
./configure

# Issue bazel build command with 'mkl_aarch64' config to enable onednn+acl backend
bazel build --verbose_failures -s --config=mkl_aarch64_threadpool  //tensorflow/tools/pip_package:build_pip_package //tensorflow:libtensorflow_cc.so //tensorflow:install_headers

# Create and install the wheel
./bazel-bin/tensorflow/tools/pip_package/build_pip_package ./wheel-$TF_VERSION-aarch64

# The output wheel is generated in /home/ubuntu/tensorflow/wheel-$TF_VERSION-aarch64
pip install <wheel-$TF_VERSION-aarch64/*.whl>
```

# Building TensorFlow Java binaries (JAR)

This section outlines the recommended way to compile TensorFlow Java binaries. The build uses release python wheels for native libraries so, the tensorflow bazel build is not required for this step.

Note: TensorFlow jar distribution for aarch64 linux platform is blocked on CI support for [tensorflow/java](https://github.com/tensorflow/java) repo.

```
sudo apt-get install pkg-config ccache clang ant python3-pip swig git file wget unzip tar bzip2 gzip patch autoconf-archive autogen automake make cmake libtool bison flex perl nasm curl gfortran libasound2-dev freeglut3-dev libgtk2.0-dev libusb-dev zlib1g libffi-dev libbz2-dev zlib1g-dev

sudo apt install maven default-jdk

# Build and install tensorflow java bindings
git clone https://github.com/tensorflow/java.git
cd java
mvn install -X -T 16

```
