# Large Language Model (LLM) inference on Graviton CPUs with vLLM

**Introduction**

vLLM is a fast and easy-to-use library for LLM inference and serving. It provides an OpenAI-compatible API server and support NVIDIA GPUs, CPUs and AWS Neuron. vLLM has been adapted to work on ARM64 CPUs with NEON support, leveraging the CPU backend initially developed for the x86 platform. ARM CPU backend currently supports Float32, FP16 and BFloat16 datatypes.
This document covers how to build and run vLLM for LLM inference on AWS Graviton based Amazon EC2 Instances. 

# How to use vLLM on Graviton CPUs

There are no pre-built wheels or images for Graviton CPUs, so you must build vLLM from source.

**Prerequisites**

Graviton3(E) (e.g. c7g/m7g/r7g, c7gn and Hpc7g Instances) and Graviton4 (e.g. r8g Instances) CPUs support BFloat16 format and MMLA instructions for machine learning (ML) acceleration. These hardware features are enabled starting with Linux Kernel version 5.10. So, it is highly recommended to use the AMIs based on Linux Kernel 5.10 and beyond for the best LLM inference performance on Graviton Instances. Use the following queries to list the AMIs with the recommended Kernel versions.

The following steps were tested on a Graviton3 R7g.2xlarge.

```
# For Kernel 5.10 based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-5.10*" --query 'sort_by(Images, &CreationDate)[].Name'

# For Kernel 6.x based AMIs list
aws ec2 describe-images --owners amazon --filters "Name=architecture,Values=arm64" "Name=name,Values=*kernel-6.*" --query 'sort_by(Images, &CreationDate)[].Name'
```

**Install Compiler and Python packages**
```
sudo apt-get update  -y
sudo apt-get install -y gcc-12 g++-12 libnuma-dev python3-dev
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 10 --slave /usr/bin/g++ g++ /usr/bin/g++-12
```

**Create a new Python environment using uv, a very fast Python environment manager**
```
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv venv --python 3.12 --seed
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
pip install -v -r requirements-cpu.txt --extra-index-url https://download.pytorch.org/whl/cpu

VLLM_TARGET_DEVICE=cpu python setup.py install
```

**Run DeepSeek Inference on AWS Graviton**

```
export VLLM_CPU_KVCACHE_SPACE=40

vllm serve deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B

curl http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" -d '{ "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", "messages": [{"role": "system", "content": "You are a helpful assistant."},{"role": "user", "content": "Why is the sky blue?"}],"max_tokens": 100 }'
```

# Additional Resources
https://learn.arm.com/learning-paths/servers-and-cloud-computing/vllm/vllm-server/
https://docs.vllm.ai/en/latest/getting_started/installation/cpu/index.html?device=arm
