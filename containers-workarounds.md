## Leveraging Graviton-based instances as container hosts

### Workarounds 

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*.  We are working with maintainers and contributing expertise and code to enable full binary or multi-arch support.

We've documented ways to leverage these products below:


| Name                      | URL / Github issue            | Workaround/Status             | Existing image? |
| :-----                    |:-----                         | :-----                 | :-----          |
| ArgoCD | https://github.com/argoproj/argo-cd/issues/3956 | build arm64 images from source / existing arm64 binaries | |
| Flatcar Linux | https://github.com/kinvolk/Flatcar/issues/97 | arm64 support for alpha/edge | |
| Istio | | [Build instruction below](#Istio) | |

### Istio

Istio doesn't publish arm64 containers, but you can build them yourself by following the steps below.

0. Launch a Graviton instance. These instructions were created using Ubuntu 20.04 (Focal), however, they should work with some modifications to the first step on other distributions.

1. Install Docker and Golang. Use Docker's own package repository because, at the time of writing, the build depends on a feature in `buildx` which is not present in Ubuntu's packaged version. The code below can be copied and pasted in its entirety onto the shell. For other distributions, refer to [Docker's documentation](https://docs.docker.com/engine/install/).
```
sudo apt-get update && sudo apt-get upgrade -y && sudo apt-get install -y \
     apt-transport-https \
     ca-certificates \
     curl \
     gnupg \
     lsb-release \
     build-essential &&
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg &&
echo \
   "deb [arch=arm64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null &&
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io &&
sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -a -G docker ubuntu &&
wget https://golang.org/dl/go1.16.5.linux-arm64.tar.gz &&
sudo tar -C /usr/local/ -xzf go1.16.5.linux-arm64.tar.gz &&
sudo ln -s /usr/local/go/bin/go /usr/local/bin/go
```

2. Logout and log back in after the previous step. Optionally reboot to apply any kernel updates that were downloaded.

3. Clone the repositories.
```
cd ~ &&
mkdir istio && cd istio &&
git clone https://github.com/istio/istio.git &&
git clone https://github.com/istio/proxy.git &&
git clone https://github.com/istio/tools.git
```

3.1. Optionally checkout the exact versions tested for this guide. If you run into problems, try this first. (Note: these commands will reset the master branch, so do not execute them if you have your own unpublished work on the master branch.)
```
pushd istio && git checkout -B master 49dfd655557fa5e1f678d6c18761603ceddcb1f8 && popd &&
pushd proxy && git checkout -B master b3ba3a91e80939fbbb65ec998d812b422b3afefb && popd &&
pushd tools && git checkout -B master 236cb4951368852f6fdc568ce7ffdc3291d6ac4d && popd
```

4. Build the "build" containers. This step took about 15 minutes to run on a `m6g.4xlarge`. It does not use much parallelism so a larger instance is not likely to improve the speed.
```
cd ~/istio/tools/docker/build-tools
DRY_RUN=1 time ./build-and-push.sh
```

5. Build the proxy (envoy) binary. This step takes about 20 minutes on a `m6g.16xlarge` and makes full use of all cores. A smaller instance will run for longer. The resulting container image can be used again to build newer versions and should not have to be rebuilt every time.
```
docker run --name istio-proxy-build -it -v $(realpath ~/istio/proxy/):/work -w /work -u $(id -u) gcr.io/istio-testing/build-tools-proxy:master-latest make build
```

6. Build the Go binaries. This step runs in just a minute or two.
```
cd ~/istio/istio
TARGET_ARCH=arm64 IMAGE_VERSION=master-latest make build
```

7. Build the final containers. For this step we set several environment variables, so start by entering a new shell to contain the new environment.
```
bash
export IMAGE_TAG=master-latest
export IMAGE_VERSION=$IMAGE_TAG
export DOCKER_ARCHITECTURES="linux/arm64"
export TARGETARCH="arm64"
export HUBS="gcr.io/istio-release"
export TAG=$IMAGE_TAG
export BASE_VERSION=$IMAGE_TAG
cd ~/istio/proxy
export PROXY_REPO_SHA=$(git rev-parse HEAD)
cd ..
```

7.1. Copy the `envoy` binary into place.
```
docker cp istio-proxy-build:/work/bazel-bin/src/envoy/envoy ~/istio/istio/out/linux_arm64/release/envoy-${PROXY_REPO_SHA}
cp ~/istio/istio/out/linux_arm64/release/envoy-${PROXY_REPO_SHA} ~/istio/istio/out/linux_arm64/release/envoy
```

7.2. Build the base containers.
```
cd ~/istio/istio
for i in 'dockerx.base' 'dockerx.distroless' 'dockerx.app_sidecar_base_ubuntu_xenial' 'dockerx.app_sidecar_base_ubuntu_bionic' 'dockerx.app_sidecar_base_ubuntu_focal' 'dockerx.app_sidecar_base_debian_9' 'dockerx.app_sidecar_base_debian_10' 'dockerx.app_sidecar_base_centos_8' 'dockerx.app_sidecar_base_centos_7'; do HUBS="gcr.io/istio-release" make $i; done
```

7.3. Finally, build the containers.
```
export HUBS="istio"
make dockerx
```
