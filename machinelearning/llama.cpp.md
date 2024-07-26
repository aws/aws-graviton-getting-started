# Large Language Model (LLM) inference on Graviton CPUs with llama.cpp

**Introduction**

The main goal of [llama.cpp](https://github.com/ggerganov/llama.cpp) is to enable LLM inference with minimal setup and state-of-the-art performance on a wide variety of hardware. It's a plain C/C++ implementation without any dependencies. It supports quantized general matrix multiply-add (GEMM) kernels for faster inference and reduced memory use. The quantized GEMM kernels are optimized for AWS Graviton processors using Arm Neon and SVE based matrix multiply-accumulate (MMLA) instructions. This document covers how to build and run llama.cpp efficiently for LLM inference on AWS Graviton based Amazon EC2 Instances.

# How to use llama.cpp on Graviton CPUs

Building from sources is the recommended way to use llama.cpp on Graviton CPUs, and for other hardware platforms too. This section provides the instructions on how to build it from sources.

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

# build with make
make

```

# Run LLM inference with llama.cpp

llama.cpp provides a set of tools to (1) convert model binary file into GPT-Generated Unified Format (GGUF), (2) quantize single and half precision format models into one of the quantized formats, (3) rearrange model weights into blocked layout to leverage the hardware specific GEMM kernels and improve the performance, and (4) run LLM inference locally.

The following instructions use Meta Llama-3 8B parameter model from [Hugging Face](https://huggingface.co/models) models repository to demonstrate LLM inference performance on AWS Graviton based EC2 Instances. The model is already availble in quantized GGUF format. For the steps on how to convert model binary into GGUF format, please check [llama.cpp README](https://github.com/ggerganov/llama.cpp/blob/master/README.md). The model from the Hugging Face model repository can be run directly on Graviton based EC2 Instances. However, to be able to leverage the optimized GEMM kernels and improve the LLM inference performance by up to 2x, it is recommended to rearrange the model weights into blocked layout which is a one time model pre-processing step. This section shows you how to rearrange the model weights into blocked layout and run it efficiently on AWS Graviton3 and Graviton4 based Amazon EC2 Instances.


```
# Download the model from Hugging Face model repo.
cd llama.cpp
wget https://huggingface.co/SanctumAI/Meta-Llama-3-8B-Instruct-GGUF/resolve/main/meta-llama-3-8b-instruct.Q4_0.gguf

# Use 8x8 blocked layout for Graviton3 and 4x8 layout for Graviton4 Instances to match their SVE vector width,
# i.e.,256bit wide on Graviton3 and 128bit wide on Graviton4.

# Run the following command on Graviton3 based Instances (using Q4_0_8_8)
./llama-quantize --allow-requantize meta-llama-3-8b-instruct.Q4_0.gguf meta-llama-3-8b-instruct.Q4_0_8_8.gguf Q4_0_8_8

# Run the following command on Graviton4 based Instances (using Q4_0_4_8)
./llama-quantize --allow-requantize meta-llama-3-8b-instruct.Q4_0.gguf meta-llama-3-8b-instruct.Q4_0_4_8.gguf Q4_0_4_8

# Now, launch llama-cli with the above model and a sample input prompt. Use Q4_0_8_8 layout model if running on
# Graviton3 or use the Q4_0_4_8 layout model if running on Graviton4 based EC2 Instances. The following command is using 64 threads.
# Change -t argument for running inference with lower thread count. On completion, the script prints throughput and latency metics
# for prompt encoding and response generation.
./llama-cli -m meta-llama-3-8b-instruct.Q4_0_8_8.gguf -p "Building a visually appealing website can be done in ten simple steps:" -n 512 -t 64


# Launch the model in conversation (chatbot) mode using this command
./llama-cli -m meta-llama-3-8b-instruct.Q4_0_8_8.gguf -p "You are a helpful assistant" -cnv --color

```

# Additional Resources

Please refer to
1. [Best-in-class LLM performance on Arm Neoverse V1 based AWS Graviton3 CPUs](https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/best-in-class-llm-performance) to know the LLM inference performance measured on AWS Graviton3 based EC2 Instances.
2. [Run LLMs on CPU with Amazon SageMaker Real-time Inference](https://community.aws/content/2eazHYzSfcY9flCGKsuGjpwqq1B/run-llms-on-cpu-with-amazon-sagemaker-real-time-inference?lang=en) for running LLMs for real-time inference using AWS Graviton3 and Amazon SageMaker.
