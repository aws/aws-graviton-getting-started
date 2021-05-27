## Leveraging Graviton-based instances as container hosts

### Workarounds 

Many products work on arm64 but don't explicitly distribute arm64 binaries or build multi-arch images *(yet)*.  We are working with maintainers and contributing expertise and code to enable full binary or multi-arch support.

We've documented ways to leverage these products below:


| Name                      | URL / Github issue            | Workaround/Status             | Existing image? |
| :-----                    |:-----                         | :-----                 | :-----          |
| ArgoCD | https://github.com/argoproj/argo-cd/issues/3956 | build arm64 images from source / existing arm64 binaries | |
| Flatcar Linux | https://github.com/kinvolk/Flatcar/issues/97 | arm64 support for alpha/edge | |


			







