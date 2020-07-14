# Container-based workloads on Graviton

The AWS Graviton and Graviton2 processors are fantastic for container-based workloads.

## Multi-arch container images
If you are currently running only x86_64-based container images, the first step is leveraging Graviton is to switch to [multiple-architecture (multi-arch)](https://www.docker.com/blog/multi-platform-docker-builds/) images. Most container registries including [Docker Hub](https://hub.docker.com) and [Amazon Elastic Container Registry (ECR)](https://aws.amazon.com/blogs/containers/introducing-multi-architecture-container-images-for-amazon-ecr/) now support multi-arch images.

There are a couple methods of creating a multi-arch image.

1. [Docker Buildx](https://github.com/docker/buildx#getting-started)
2. Using a CI/CD Build Pipeline such as [Amazon CodePipeline](https://github.com/aws-samples/aws-multiarch-container-build-pipeline) to coordinate native build and manifest generation.

## Deploying to Graviton

Most container orchestration platforms support aarch64 and x86_64. 

1. Amazon Elastic Container Service (ECS) supports Graviton-powered instances [today](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html#amazon-linux-2-(arm64)).
2. Amazon Elastic Kubernetes Service (EKS) support for Graviton-powered instances is [currently in public preview.](https://github.com/aws/containers-roadmap/blob/a1f4352f5dea6aad63360608c661bf7007c2e523/preview-programs/eks-arm-preview/README.md)


## Futher reading

* [Building multi-arch docker images with buildx](https://tech.smartling.com/building-multi-architecture-docker-images-on-arm-64-c3e6f8d78e1c)
* [Leveraging Spot and Graviton2 with EKS](https://spot.io/blog/eks-simplified-on-ec2-graviton2-instances/)
