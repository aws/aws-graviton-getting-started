# ML inference on Graviton CPUs with Open Neural Network Exchange(ONNX)

**Introduction**

ONNX is an open-source machine learning framework that provides interoperability between different frameworks. ONNX Runtime is the runtime engine used for model inference and training with ONNX . This document covers how to use ONNX based machine learning inference on Graviton CPUs, what runtime configurations are important and how to run benchmarking scripts. The document also covers instructions for source builds to enable experimenting with downstream features.

# How to use ONNX on Graviton CPUs

Python wheels is the recommended option to use ONNX on Graviton, the default backend is optimized for Graviton CPU.

```
# Upgrade pip3 to the latest version
python3 -m pip install --upgrade pip

# Install ONNX and ONNX Runtime
python3 -m pip install onnx
python3 -m pip install onnxruntime
```

# Prerequisites

1. It is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best ONNX inference performance on Graviton3 instances. The following queries can be used to list down the AMIs with Kernel 5.10 and beyond.

```
# For Kernel 5.10 based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-5.10*" --query 'sort_by(Images, &CreationDate)[].Name'

# For Kernel 6.x based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-6.*" --query 'sort_by(Images, &CreationDate)[].Name'
```

# Runtime configurations for optimal performance

Graviton3(E) (e.g. c7g/m7g/r7g, c7gn and Hpc7g instances) supports BFloat16 format and advanced Matrix Multiplication (MMLA) instructions for ML acceleration. Starting version v1.17.0, ONNX Runtime supports Bfloat16 accelerated SGEMM kernels and INT8 MMLA accelerated Quantized GEMM (QGEMM) kernels on Graviton3(E) CPU.

Note: The standard FP32 model inference can be accelerated with BFloat16 SGEMM kernels without model quantization.

MMLA QGEMM kernels are enabled by default, and to enable BF16 acceleration, set the onnxruntime session option as shown below

```c++
# For C++ applications
SessionOptions so;
so.config_options.AddConfigEntry(
      kOrtSessionOptionsMlasGemmFastMathArm64Bfloat16, "1");
```

```python
# For Python applications
sess_options = onnxruntime.SessionOptions()
sess_options.add_session_config_entry("mlas.enable_gemm_fastmath_arm64_bfloat16", "1")
```

# Evaluate performance with ONNX Runtime benchmark
ONNX Runtime repo provides inference benchmarking scripts for transformers based language models. The scripts support a wide range of models, frameworks and formats. The following section explains how to run BERT, RoBERTa and GPT model inference in fp32 and int8 quantized formats. Refer to [ONNX Runtime Benchmarking script](https://github.com/microsoft/onnxruntime/blob/main/onnxruntime/python/tools/transformers/benchmark.py) for more details.


```
# Install onnx and onnx runtime
python3 -m pip install onnx onnxruntime

# Install the dependencies
python3 -m pip install transformers torch psutil

# Clone onnxruntime repo to get the benchmarking scripts
git clone --recursive https://github.com/microsoft/onnxruntime.git
cd onnxruntime/onnxruntime/python/tools/transformers

# The scripts download the models, export them to onnx format,
# quantize into int8 for int8 inference, run inference for
# different sequence lengths and batch sizes. Upon successful run,
# the scripts print the inference throughput in QPS (Queries/sec)
# and latency in msec along with system configuration

# Next run the benchmarks, select fp32 or int8 precision via -p argument
# To run bert-large
python3 benchmark.py -m bert-large-uncased -p <fp32/int8>

# To run bert-base
python3 benchmark.py -m bert-base-cased -p <fp32/int8>

# To run roberta-base
python3 benchmark.py -m roberta-base -p <fp32/int8>

# To run gpt2
python3 benchmark.py -m gpt2 -p <fp32/int8>

```

# Building ONNX RunTime from source

We recommend using the official python wheel distribution, but there are cases developers may want to compile ONNX Runtime from source. One such case would be to experiment with new features or develop custom features. This section outlines the recommended way to compile ONNX Runtime from source.

```
# Clone onnxruntime
git clone --recursive https://github.com/Microsoft/onnxruntime.git
cd onnxruntime

# Install cmake-3.27 or higher, one option is via pip installer.
python3 -m pip install cmake

# Build python wheel with Release configuration
./build.sh --config=Release --build_shared_lib --build_wheel --parallel 16

# the wheel is copied to build/Linux/Release/dist folder, so, to install
pip3 install <build/Linux/Release/dist/onnxruntime_dnnl*.whl>
```
