# Operating Systems available for Graviton based instances

 Name | Version | [LSE Support](https://github.com/aws/aws-graviton-getting-started/blob/master/optimizing.md#locksynchronization-intensive-workload) | Kernel page size | AMI | Metal support | Comment
------ | ------ | ----- | ----- | ----- | ----- | -----
Amazon Linux 2 | 2.26-35 | Yes | 4KB | Yes | 
Ubuntu | 20.04 LTS | Yes | 4KB | [focal](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
Ubuntu | 18.04 LTS | [Planned](https://launchpad.net/~rbalint/+archive/ubuntu/arm64-lse) | 4KB | [bionic](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
SuSE | 15 SP2 | Planned | 4KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07SPTXBDX) | Yes | 
Redhat Entreprise Linux | 8.2 | Yes | 64KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07T2NH46P) | Yes | 
~~Redhat Entreprise Linux~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[MarketPlace](https://aws.amazon.com/marketplace/pp/B07KTFV2S8)~~ | | Supported on A1 instances but not on Graviton2 based ones
CentOS | 8.2.2004 | No | 64KB | [AMIs](https://wiki.centos.org/Cloud/AWS#Images) | Yes | 
~~CentOS~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[AMIs](https://wiki.centos.org/Cloud/AWS#Images)~~ | | Supported on A1 instances but not on Graviton2 based ones
Debian | 10 | [Planned](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=956418) | 4KB | [Community](https://wiki.debian.org/Cloud/AmazonEC2Image/Buster) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B085HGTX5J) | Yes | 
FreeBSD | 12.1 | Planned | 4KB | [Community](https://www.freebsd.org/releases/12.1R/announce.html) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B081NF7BY7) | | 

