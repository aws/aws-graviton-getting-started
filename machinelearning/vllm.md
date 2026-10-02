# Large Language Model (LLM) inference on Graviton CPUs with vLLM

**Introduction**

[vLLM](https://github.com/vllm-project/vllm) is a fast and easy-to-use library for LLM inference and serving. It provides an OpenAI-compatible API server and supports NVIDIA GPUs, CPUs, and AWS Neuron. vLLM runs on ARM64 CPUs with NEON support through its CPU backend, which was first developed for x86. The ARM CPU backend supports the Float32, FP16, and BFloat16 data types. This document covers how to run vLLM for LLM inference on AWS Graviton-based Amazon EC2 instances.

There are two ways to get vLLM running on Graviton:

1. **AWS Deep Learning Container.** AWS publishes a Graviton (ARM64) vLLM image on the Amazon ECR Public Gallery. It runs the upstream vLLM OpenAI-compatible server with the CPU backend prebuilt, so you can serve a Hugging Face model with a single `docker run`. Start here if you want a maintained image without building anything.
2. **Build from source.** Compile the vLLM CPU backend yourself. Start here if you need a custom build or an unreleased vLLM version.

# Serve vLLM on Graviton with the AWS Deep Learning Container

The [vLLM Deep Learning Container (DLC)](https://gallery.ecr.aws/deep-learning-containers/vllm-arm64) builds vLLM from source with BFloat16 kernels for Graviton3 and later. It is built on Amazon Linux 2023, needs no GPU, and serves the OpenAI-compatible API on port **8000**.

AWS publishes the image in the `vllm-arm64` repository on the Amazon ECR Public Gallery. This guide uses the CPU image for Amazon EC2:

`public.ecr.aws/deep-learning-containers/vllm-arm64:server-cpu-v1`

A SageMaker AI variant is also available as `vllm-arm64:server-sagemaker-cpu-v1`.

**Prerequisites**

Launch a Graviton3(E)- or Graviton4-based EC2 instance (for example, `c7g`, `m7g`, `c8g`, or `r8g`) with Docker installed. The server is **unauthenticated by default**, so run it inside a private network (security group / VPC), or pass `--api-key` to require a bearer token on every request.

**Serve a model from Hugging Face**

The container forwards any `vllm serve` arguments appended to `docker run`:

```
docker run -d -p 8000:8000 --shm-size=4g \
  public.ecr.aws/deep-learning-containers/vllm-arm64:server-cpu-v1 \
  --model Qwen/Qwen3.5-2B \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --host 0.0.0.0 --port 8000
```

Wait for the model to load, then call the OpenAI-compatible API:

```
until curl -sf http://localhost:8000/health > /dev/null; do sleep 5; done

curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.5-2B",
    "messages": [{"role": "user", "content": "Why is the sky blue?"}],
    "max_tokens": 100
  }'
```

**CPU defaults**

The image sets these defaults at startup. Override any of them with `-e`, for example `-e VLLM_CPU_KVCACHE_SPACE=16`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `VLLM_CPU_KVCACHE_SPACE` | 40% of host RAM (minimum 2 GiB) | KV-cache size in GiB. GPU memory flags such as `--gpu-memory-utilization` have no effect on CPU. |
| `VLLM_CPU_OMP_THREADS_BIND` | `nobind` | OpenMP thread binding. Set to `auto` or a core list (for example `0-31`) to pin threads. |
| `LD_PRELOAD` | `libtcmalloc_minimal.so.4` | Uses tcmalloc for lower allocator overhead. |

Use BFloat16 weights. The CPU backend does not support GGUF models; use [llama.cpp](llama.cpp.md) for those.

# How to build vLLM on Graviton CPUs

Building from source gives you full control over the build and lets you run any vLLM version, including unreleased commits.

**Prerequisites**

Graviton3(E) (e.g. *7g instances) and Graviton4 (e.g. *8g instances) CPUs support BFloat16 format and MMLA instructions for machine learning (ML) acceleration. These hardware features are enabled starting with Linux Kernel version 5.10. So, it is highly recommended to use the AMIs based on Linux Kernel 5.10 or later for the best LLM inference performance on Graviton Instances. Use the following queries to list the AMIs with the recommended Kernel versions. New Ubuntu 22.04, 24.04, and AL2023 AMIs all have kernels newer than 5.10.

The following steps were tested on a Graviton3 r7g.4xlarge with Ubuntu 24.04.1.

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

1. [vLLM Deep Learning Container on the Amazon ECR Public Gallery](https://gallery.ecr.aws/deep-learning-containers/vllm-arm64) for the maintained Graviton (ARM64) vLLM image.
2. [AWS Deep Learning Containers vLLM documentation](https://aws.github.io/deep-learning-containers/vllm/) for EC2 and SageMaker AI deployment, including Graviton.
3. [Arm Learning Path: Build and run a vLLM server on Arm](https://learn.arm.com/learning-paths/servers-and-cloud-computing/vllm/vllm-server/)
4. [vLLM CPU installation guide](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/index.html?device=arm)
