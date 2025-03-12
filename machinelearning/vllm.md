# Large Language Model (LLM) inference on Graviton CPUs with vLLM

**Introduction**

vLLM is a fast and easy-to-use library for LLM inference and serving. It provides an OpenAI-compatible API server and support NVIDIA GPUs, CPUs and AWS Neuron. vLLM has been adapted to work on ARM64 CPUs with NEON support, leveraging the CPU backend initially developed for the x86 platform. ARM CPU backend currently supports Float32, FP16 and BFloat16 datatypes.
This document covers how to build and run vLLM for LLM inference on AWS Graviton based Amazon EC2 Instances. 

# How to use vLLM on Graviton CPUs

There are no pre-built wheels or images for Graviton CPUs, so you must build vLLM from source.

**Prerequisites**

Graviton3(E) (e.g. *7g instances) and Graviton4 (e.g. *8g instances) CPUs support BFloat16 format and MMLA instructions for machine learning (ML) acceleration. These hardware features are enabled starting with Linux Kernel version 5.10. So, it is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best LLM inference performance on Graviton Instances. Use the following queries to list the AMIs with the recommended Kernel versions. New Ubuntu 22.04, 24.04, and AL2023 AMIs all have kernels newer than 5.10.

The following steps were tested on a Graviton3 R7g.4xlarge and Ubuntu 24.04.1

```
# For Kernel 5.10 based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-5.10*" --query 'sort_by(Images, &CreationDate)[].Name'

# For Kernel 6.x based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-6.*" --query 'sort_by(Images, &CreationDate)[].Name'
```

**Install Compiler and Python packages**
```
sudo apt-get update  -y
sudo apt-get install -y gcc-13 g++-13 libnuma-dev python3-dev python3-virtualenv
```

**Create a new Python environment**
```
virtualenv venv
source venv/bin/activate
```

**Clone vLLM project**
```
git clone https://github.com/vllm-project/vllm.git
cd vllm
```

**Install Python Packages and build vLLM CPU Backend**

```
pip install --upgrade pip
pip install "cmake>=3.26" wheel packaging ninja "setuptools-scm>=8" numpy
pip install -v -r requirements/cpu.txt --extra-index-url https://download.pytorch.org/whl/cpu

VLLM_TARGET_DEVICE=cpu python setup.py install
```

**Run DeepSeek Inference on AWS Graviton**

```
export VLLM_CPU_KVCACHE_SPACE=40

vllm serve deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B

curl http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" -d '{ "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", "messages": [{"role": "system", "content": "You are a helpful assistant."},{"role": "user", "content": "Why is the sky blue?"}],"max_tokens": 100 }'
```

Sample output is as below.

```
{"id":"chatcmpl-4c95b14ede764ab4a1338b0670ea839a","object":"chat.completion","created":1741351310,"model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B","choices":[{"index":0,"message":{"role":"assistant","reasoning_content":null,"content":"Okay, so I'm trying to understand why the sky appears blue. I've heard this phenomenon before, but I'm not exactly sure how it works. I think it has something to do with the mixing of light and particles in the atmosphere, but I'm not entirely clear on the details. Let me try to break it down step by step.\n\nFirst, there are a few factors contributing to why the sky looks blue. From what I remember, the atmosphere consists of gases and particles that absorb and refract light. Different parts of the sky are observed through different atmospheric layers, which might explain why the colors vary over long distances.\n\nI think the primary reason is that the atmosphere absorbs some of the red and blue light scattered from the sun. Red light has a longer wavelength compared to blue, so it is absorbed more easily because the molecules in the atmosphere absorb light based on its wavelength. Blue light has a shorter wavelength and doesn't get absorbed as much. As a result, the sky remains relatively blue because the blue light that hasn't been absorbed is still passing through the atmosphere and is refracted.\n\nAnother factor to consider is the angle of observation. Because the atmosphere travels through the sky, the observation of blue light can be messy at altitudes where the atmosphere is thinner.","tool_calls":[]},"logprobs":null,"finish_reason":"length","stop_reason":null}],"usage":{"prompt_tokens":17,"total_tokens":273,"completion_tokens":256,"prompt_tokens_details":null},"prompt_logprobs":null}
```

# Additional Resources
https://learn.arm.com/learning-paths/servers-and-cloud-computing/vllm/vllm-server/
https://docs.vllm.ai/en/latest/getting_started/installation/cpu/index.html?device=arm
