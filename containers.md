# Container-based workloads on Graviton

The AWS Graviton and Graviton2 processors have been optimized and can be considered ideal for container-based workloads.

### Preparing for Graviton

The first step for leveraging the benefits of Graviton-based instances as container hosts is to ensure all production software dependencies support the arm64 architecture, as once cannot run images built for an x86_64 host on an arm64 host, and vice versa.

Most of the container ecosystem supports both architectures, and often does so transparently through [multiple-architecture (multi-arch)](https://www.docker.com/blog/multi-platform-docker-builds/) images, where the correct image for the host architecture is deployed automatically.

The major container image repositories, including [Dockerhub](https://hub.docker.com), [Quay](https://www.quay.io), and [Amazon Elastic Container Registry (ECR)](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html) all support [multi-arch](https://aws.amazon.com/blogs/containers/introducing-multi-architecture-container-images-for-amazon-ecr/) images.

#### Creating Multi-arch container images

While most images already support multi-arch (i.e. arm64 and x86_64/amd64), we describe couple of ways for developers to to create a multi-arch image if needed.

1. [Docker Buildx](https://github.com/docker/buildx#getting-started)
2. Using a CI/CD Build Pipeline such as [Amazon CodePipeline](https://github.com/aws-samples/aws-multiarch-container-build-pipeline) to coordinate native build and manifest generation.

### Deploying to Graviton

Most container orchestration platforms support both arm64 and x86_64 hosts. 

Both [Amazon Elastic Container Service (ECS)](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html#amazon-linux-2-(arm64)) and [Amazon Elastic Kubernetes Service (EKS)](https://aws.amazon.com/blogs/containers/eks-on-graviton-generally-available/) support Graviton-powered instances.

We have compiled a list of popular software within the container ecosystem that explicitly supports arm64:

#### Ecosystem Support

| Name                      | URL                           | Comment                |
| :-----                    |:-----                         | :-----                 |
| Istio	| https://github.com/istio/istio/releases/	| arm64 binaries as of 1.6.x release series|
| Envoy	| https://www.envoyproxy.io/docs/envoy/latest/install/building#arm64-binaries | [envoyproxy-dev](https://hub.docker.com/r/envoyproxy/envoy-dev/tags/) is multiarch |
| Traefik | https://github.com/containous/traefik/releases	|| 	 
| Flannel | https://github.com/coreos/flannel/releases	 ||	 
| Helm | https://github.com/helm/helm/releases/tag/v2.16.9 || 
| Jaeger | https://github.com/jaegertracing/jaeger/pull/2176 | [dockerhub images are not yet multiarch](https://github.com/jaegertracing/jaeger/issues/2292)	| 
| Fluent-bit |https://github.com/fluent/fluent-bit/releases/ | compile from source |
| core-dns |https://github.com/coredns/coredns/releases/ | | 
| Prometheus | https://prometheus.io/download/	 	 | |
|containerd	 | https://github.com/containerd/containerd/issues/3664 |	nightly builds provided for arm64 | 	 
|gRPC  | 	https://github.com/protocolbuffers/protobuf/releases/	 | protoc/protobuf support	 |
|Nats	 | 	https://github.com/nats-io/nats-server/releases/	 	 | |
|CNI	 | 	https://github.com/containernetworking/plugins/releases/	| | 	  
|Cri-o	 | 	https://github.com/cri-o/cri-o/blob/master/README.md#installing-crio | tested on Ubuntu 18.04 and 20.04	|
|Trivy	 | 	https://github.com/aquasecurity/trivy/releases/	 	 | |
|Argo	 | 	https://github.com/argoproj/argo/releases/	 	 	 | |
|Cilium	| https://cilium.io/blog/2020/06/22/cilium-18/#arm64 | initial support |	 
|Tanka	 | 	https://github.com/grafana/tanka/releases	 	 | |
|Consul	 | 	https://www.consul.io/downloads	 	 | |
|Nomad	 | 	https://www.nomadproject.io/downloads	| | 	 
|Packer	 | 	https://www.packer.io/downloads	 	 | |
|Vault	 | 	https://www.vaultproject.io/downloads	| | 	 	 	 
|Flux	 | 	https://github.com/fluxcd/flux/releases/ | |
|New Relic	 | 	https://download.newrelic.com/infrastructure_agent/binaries/linux/arm64/ | |
|Datadog - EC2	 | 	https://www.datadoghq.com/blog/datadog-arm-agent/ ||
|Datadog - Docker	 | 	https://hub.docker.com/r/datadog/agent-arm64	|| 	 
|Dynatrace	 | 	https://www.dynatrace.com/news/blog/get-out-of-the-box-visibility-into-your-arm-platform-early-adopter/	 ||	 
|Grafana	 | 	https://grafana.com/grafana/download?platform=arm ||
|Loki	 | 	https://github.com/grafana/loki/releases ||
|kube-bench | https://github.com/aquasecurity/kube-bench/releases/tag/v0.3.1 ||
|metrics-server | https://github.com/kubernetes-sigs/metrics-server/releases/tag/v0.3.7 | docker image is multi-arch from v.0.3.7 |
|AWS Copilot | https://github.com/aws/copilot-cli/releases/tag/v0.3.0 | arm64 support as of v0.3.0 |
|AWS ecs-cli | https://github.com/aws/amazon-ecs-cli/pull/1110 | v1.20.0 binaries in us-west-2 s3 |
| Amazon EC2 Instance Selector | https://github.com/aws/amazon-ec2-instance-selector/releases/ | also supports the -a cpu_architecture flag for discovering arm64-based instances in a particular region |
| AWS Node Termination Handler | https://github.com/aws/aws-node-termination-handler/releases/ | arm64 support under kubernetes (via helm) |
| AWS IAM Authenticator	 | 	https://docs.aws.amazon.com/eks/latest/userguide/install-aws-iam-authenticator.html	 	| | 
| AWS ALB Ingress Controller | https://github.com/kubernetes-sigs/aws-alb-ingress-controller/releases/tag/v1.1.9 | multi-arch image as of v1.1.9 |
| AWS EFS CSI Driver | https://github.com/kubernetes-sigs/aws-efs-csi-driver/pull/241 | support merged 8/27/2020 |
| AWS EBS CSI Driver | https://github.com/kubernetes-sigs/aws-ebs-csi-driver/pull/527 | support merged 8/26/2020 |
| Amazon Inspector Agent | https://docs.aws.amazon.com/inspector/latest/userguide/inspector_installing-uninstalling-agents.html#install-linux | |
| Amazon CloudWatch Agent	| https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Install-CloudWatch-Agent.html | |
| AWS Systems Manager SSM Agent | https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-manual-agent-install.html | |
| AWS CLI |	https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html#ARM	| v1 and v2 both supported|


**If your software isn't listed above, it doesn't mean it won't work!**

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*. AWS, Arm, and many developers in the community are working with maintainers and contributing expertise and code to enable full binary or multi-arch support.

We've compiled [details](containers-workarounds.md) of the components being worked on to add arm64 support to run on Graviton.

---

### Further reading

* [Building multi-arch docker images with buildx](https://tech.smartling.com/building-multi-architecture-docker-images-on-arm-64-c3e6f8d78e1c)
* [Unifying Arm software development with Docker](https://community.arm.com/developer/tools-software/tools/b/tools-software-ides-blog/posts/unifying-arm-software-development-with-docker)
* [Modern multi-arch builds with docker](https://duske.me/modern-multiarch-builds-with-docker/)
* [Leveraging Spot and Graviton2 with EKS](https://spot.io/blog/eks-simplified-on-ec2-graviton2-instances/)


