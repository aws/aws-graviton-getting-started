## Leveraging Graviton-based instances as container hosts

### Workarounds 

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*.  We are working with maintainers and contributing expertise and code to enable full binary or multi-arch support.

We've documented ways to leverage these products below:


| Name                      | URL / Github issue            | Workaround             | Existing image? |
| :-----                    |:-----                         | :-----                 | :-----          |
| external-dns | https://github.com/kubernetes-sigs/external-dns/issues/1443 | compile from source, support coming in v0.7.5 | raspbernetes/external-dns	|
| Pulumi | https://github.com/pulumi/pulumi/pull/5729 | | |


			







