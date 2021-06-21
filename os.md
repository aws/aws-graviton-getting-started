# Operating Systems available for Graviton based instances

 Name | Version | [LSE Support](optimizing.md#locksynchronization-intensive-workload) | Kernel page size | AMI | Metal support | Comment
------ | ------ | ----- | ----- | ----- | ----- | -----
Amazon Linux 2 | 2.26-35 or later| Yes | 4KB | [AMIs](amis_cf_sm.md) | Yes |
Ubuntu | 20.04 LTS or later | Yes | 4KB | [focal](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
Ubuntu | 18.04 LTS | Yes (*) | 4KB | [bionic](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | (*) needs `apt install libc6-lse`
SuSE | 15 SP2 or later| Planned | 4KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07SPTXBDX) | Yes | 
Redhat Entreprise Linux | 8.2 or later | Yes | 64KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07T2NH46P) | Yes | 
~~Redhat Entreprise Linux~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[MarketPlace](https://aws.amazon.com/marketplace/pp/B07KTFV2S8)~~ | | Supported on A1 instances but not on Graviton2 based ones
CentOS | 8.2.2004 or later | No | 64KB | [AMIs](https://wiki.centos.org/Cloud/AWS#Images) | Yes | 
~~CentOS~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[AMIs](https://wiki.centos.org/Cloud/AWS#Images)~~ | | Supported on A1 instances but not on Graviton2 based ones
Debian | 10 | [Planned for Debian 11](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=956418) | 4KB | [Community](https://wiki.debian.org/Cloud/AmazonEC2Image/Buster) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B085HGTX5J) | Yes, as of Debian 10.7 (2020-12-07) |
FreeBSD | 12.1 or later | No | 4KB | [Community](https://www.freebsd.org/releases/12.1R/announce.html) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B081NF7BY7) | No | Device hotplug and API shutdown don't work
FreeBSD | 13.0 or later | Yes | 4KB | [Community](https://www.freebsd.org/releases/13.0R/announce.html) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B09291VW11) | No | Device hotplug and API shutdown don't work

