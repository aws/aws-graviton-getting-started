## Leveraging Graviton-based instances as container hosts

### Workarounds 

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*.

We've documented these products and some ways to leverage them below:


| Name                      | URL / Github issue            | Workaround             | Existing image? |
| :-----                    |:-----                         | :-----                 | :-----          |
| ALB Ingress Controller | https://github.com/kubernetes-sigs/aws-alb-ingress-controller/issues/1329	| compile from source	| alittlec/aws-alb-ingress-controller:v1.1.8 |
| FireLens for Amazon ECS | https://github.com/aws/aws-for-fluent-bit/issues/44 | compile from source | |
| ECS CLI | https://github.com/aws/amazon-ecs-cli/pull/1066 | use PR branch | |
| cluster-autoscaler | https://github.com/kubernetes/autoscaler/issues/3419 | compile from source or use PR branch | raspbernetes/cluster-autoscaler |
| external-dns | https://github.com/kubernetes-sigs/external-dns/issues/1721 |	compile from source | raspbernetes/external-dns	|
|metrics-server	| https://github.com/kubernetes-sigs/metrics-server	| build via helm chart |k8s.gcr.io/metrics-server-arm64	|
| kube-state-metrics | https://github.com/kubernetes/kube-state-metrics/pull/1190 |compile from source | alittlec/kube-state-metrics-arm64 |
| AWS EBS CSI driver | https://github.com/kubernetes-sigs/aws-ebs-csi-driver/issues/521 | compile from source or use PR branch	|chengpan/aws-ebs-csi-driver	|
| AWS EFS CSI driver | https://github.com/kubernetes-sigs/aws-efs-csi-driver/pull/197| use PR branch | |
			







