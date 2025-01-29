# Large Language Model (LLM) inference on Graviton CPUs with llama.cpp

**Introduction**

The main goal of [llama.cpp](https://github.com/ggerganov/llama.cpp) is to enable LLM inference with minimal setup and state-of-the-art performance on a wide variety of hardware. It's a plain C/C++ implementation without any dependencies. It supports quantized general matrix multiply-add (GEMM) kernels for faster inference and reduced memory use. The quantized GEMM kernels are optimized for AWS Graviton processors using Arm Neon and SVE based matrix multiply-accumulate (MMLA) instructions. This document covers how to build and run llama.cpp efficiently for LLM inference on AWS Graviton based Amazon EC2 Instances.

# How to use llama.cpp on Graviton CPUs

Building from sources is the recommended way to use llama.cpp on Graviton CPUs, and for other hardware platforms too. This section provides the instructions on how to build llama.cpp from sources and how to install python bindings.

**Prerequisites**

Graviton3(E) (e.g. c7g/m7g/r7g, c7gn and Hpc7g Instances) and Graviton4 (e.g. r8g Instances) CPUs support BFloat16 format and MMLA instructions for machine learning (ML) acceleration. These hardware features are enabled starting with Linux Kernel version 5.10. So, it is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best LLM inference performance on Graviton Instances. Use the following queries to list the AMIs with the recommended Kernel versions.

```
# For Kernel 5.10 based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-5.10*" --query 'sort_by(Images, &CreationDate)[].Name'

# For Kernel 6.x based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-6.*" --query 'sort_by(Images, &CreationDate)[].Name'
```

**Build llama.cpp from source**

```
# Clone llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# build with cmake
mkdir build
cd build
cmake .. -DCMAKE_CXX_FLAGS="-mcpu=native" -DCMAKE_C_FLAGS="-mcpu=native"
cmake --build . -v --config Release -j `nproc`

```

**Install llama.cpp python bindings**

```
CMAKE_ARGS="-DCMAKE_CXX_FLAGS='-mcpu=native' -DCMAKE_C_FLAGS='-mcpu=native'" pip3 install --no-cache-dir llama-cpp-python

```


# Run LLM inference with llama.cpp

llama.cpp provides a set of tools to (1) convert model binary file into GPT-Generated Unified Format (GGUF), (2) quantize single and half precision format models into one of the quantized formats, and (3) run LLM inference locally. For the steps on how to convert model binary into GGUF format and how to quantize them into low precision formats, please check [llama.cpp README](https://github.com/ggerganov/llama.cpp/blob/master/README.md).

The following instructions use Meta Llama-3 8B parameter model from [Hugging Face](https://huggingface.co/models) models repository to demonstrate LLM inference performance on AWS Graviton based EC2 Instances. The model is already availble in multiple quantized formats which can be directly run on AWS Graviton processors.


```
# Download the model from Hugging Face model repo.
cd llama.cpp
wget https://huggingface.co/SanctumAI/Meta-Llama-3-8B-Instruct-GGUF/resolve/main/meta-llama-3-8b-instruct.Q4_0.gguf

```

**Using llama-cli**

```
# Now, launch llama-cli with the above model and a sample input prompt. The following command is using 64 threads.
# Change -t argument for running inference with lower thread count. On completion, the script prints throughput and latency metics
# for prompt encoding and response generation.
./build/bin/llama-cli -m meta-llama-3-8b-instruct.Q4_0.gguf -p "Building a visually appealing website can be done in ten simple steps:" -n 512 -t 64

# Launch the model in conversation (chatbot) mode using this command
./build/bin/llama-cli -m meta-llama-3-8b-instruct.Q4_0.gguf -p "You are a helpful assistant" -cnv --color

```

**Using llama.cpp python binding**

Note: Set the `n_threads` to number of vcpus explicitly while creating the Llama object. This is required to use all cores(vcpus) on Graviton instances. Without this set, the python bindings use half of the vcpus and the performance is not the best.

```
import json
import argparse

from llama_cpp import Llama

parser = argparse.ArgumentParser()
parser.add_argument("-m", "--model", type=str, default="../models/7B/ggml-models.bin")
args = parser.parse_args()

# for example, for a .16xlarge instance, set n_threads=64
llm = Llama(model_path=args.model,
            n_threads=64)

output = llm(
"Question: How to build a visually appealing website in ten steps? Answer: ",
max_tokens=512,
echo=True,
)

```

# Run DeepSeek R1 LLM Inference on AWS Graviton

DeepSeek R1 is an open-source LLM for conversational AI, coding, and problem-solving tasks. The model can be readily deployed on AWS Graviton-based Amazon EC2 Instances for inference use cases. We recommend using [ollama](https://github.com/ollama/ollama) service for the inference deployment. Ollama service is built on top of [llama.cpp](https://github.com/ggerganov/llama.cpp) which is highly optimized to achieve the best performance on AWS Graviton processors. This section shows how to install ollama service and run DeepSeek R1 inference.

```
# Launch Graviton3 or Graviton4 based EC2 instance (for example, c7g, m7g, c8g or m8g instances)

# Download and install the ollama service
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
systemctl is-active ollama.service

# If the output is active, the service is running, and you can skip the next step. If it’s not, start it manually
sudo systemctl start ollama.service

# DeepSeek has released multiple versions of the R1 model, sizes from 1.5B parameters to 70B parameters.
# ollama supports deepseek-r1:1.5b/7b/8b/14b/32b/70b models
# Download and run the 8b model using the following command
ollama run deepseek-r1:8b

# To benchmark the prompt evaluation rate and response genetation rate, launch ollama with verbose option.
# At the end of the inference, the script prints the token eval and the token generation rates
ollama run deepseek-r1:8b "<prompt>" --verbose

```

# Additional Resources

Please refer to
1. [Best-in-class LLM performance on Arm Neoverse V1 based AWS Graviton3 CPUs](https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/best-in-class-llm-performance) to know the LLM inference performance measured on AWS Graviton3 based EC2 Instances.
2. [Running Llama 3 70B on the AWS Graviton4 CPU with Human Readable Performance](https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/running-llama-3-70b-on-aws-graviton4) for LLM inference performance on AWS Graviton4 based EC2 Instances.
3. [Intro to Llama on Graviton](https://dev.to/aws-heroes/intro-to-llama-on-graviton-1dc) for a step by step guide on how to deploy an LLM model on AWS Graviton-based EC2 Instances. Note: This guide refers to llama.cpp version from July 2024. If you are using the latest llama.cpp version, please replace the `Q4_0_4_8` and `Q4_0_8_8` with `Q4_0` format.
4. [Run LLMs on CPU with Amazon SageMaker Real-time Inference](https://community.aws/content/2eazHYzSfcY9flCGKsuGjpwqq1B/run-llms-on-cpu-with-amazon-sagemaker-real-time-inference?lang=en) for running LLMs for real-time inference using AWS Graviton3 and Amazon SageMaker.
