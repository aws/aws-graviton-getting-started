## Leveraging Graviton-based instances as container hosts

### Workarounds 

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*.  We are working with maintainers and contributing expertise and code to enable full binary or multi-arch support.

We've documented ways to leverage these products below:


| Name                      | URL / Github issue            | Workaround             | Existing image? |
| :-----                    |:-----                         | :-----                 | :-----          |
| FireLens for Amazon ECS | https://github.com/aws/aws-for-fluent-bit/issues/44 | compile from source | |
| cluster-autoscaler | https://github.com/kubernetes/autoscaler/issues/3419 | compile from source or use PR branch | raspbernetes/cluster-autoscaler |
| external-dns | https://github.com/kubernetes-sigs/external-dns/issues/1443 | compile from source | raspbernetes/external-dns	|
| kube-state-metrics | https://github.com/kubernetes/kube-state-metrics/issues/1037 | compile from source | alittlec/kube-state-metrics-arm64 |
			







