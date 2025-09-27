# Operating Systems available for Graviton based instances

 Name | Version | [LSE Support](optimizing.md#locksynchronization-intensive-workload) | Kernel page size | AMI | Metal support | Comment
------ | ------ | ----- | ----- | ----- | ----- | -----
Amazon Linux 2023 | All versions | Yes | 4KB | [AMIs](amis_cf_sm.md) | Yes | Pointer Authentication enabled on Graviton3
Amazon Linux 2 | 2.26-35 or later| Yes | 4KB | [AMIs](amis_cf_sm.md) | Yes | End of Life (EOL) scheduled 2025-06-30
Ubuntu Pro | 22.04 LTS | Yes | 4KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-uy7jg4dds3qjw) | Yes | 
Ubuntu | 24.04 LTS | Yes | 4KB | [noble](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
Ubuntu | 22.04 LTS | Yes | 4KB | [jammy](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
Ubuntu | 20.04 LTS | Yes | 4KB | [focal](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | 
Ubuntu | 18.04 LTS | Yes (*) | 4KB | [bionic](https://cloud-images.ubuntu.com/locator/ec2/) | Yes | (*) needs `apt install libc6-lse`. Free support ended 2023/05/31.
SuSE | 15 SP2 or later| Planned | 4KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07SPTXBDX) | Yes | 
Redhat Enterprise Linux | 8.2 or later | Yes | 64KB | [MarketPlace](https://aws.amazon.com/marketplace/pp/B07T2NH46P) | Yes | 
~~Redhat Enterprise Linux~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[MarketPlace](https://aws.amazon.com/marketplace/pp/B07KTFV2S8)~~ | | Supported on A1 instances but not on Graviton2 and later based ones
AlmaLinux | 8.4 or later | Yes | 64KB | [AMIs](https://wiki.almalinux.org/cloud/AWS.html) | Yes |
Alpine Linux | 3.12.7 or later | Yes (*) | 4KB | [AMIs](https://www.alpinelinux.org/cloud/) | | (*) LSE enablement checked in version 3.14 |
CentOS | 8.2.2004 or later | No | 64KB | [AMIs](https://wiki.centos.org/Cloud/AWS#Images) | Yes | |
CentOS Stream | 8 | No (*) | 64KB (*) | [Downloads](https://www.centos.org/centos-stream/) | |(*) details to be confirmed once AMI's are available|
~~CentOS~~ | ~~7.x~~ | ~~No~~ | ~~64KB~~ | ~~[AMIs](https://wiki.centos.org/Cloud/AWS#Images)~~ | | Supported on A1 instances but not on Graviton2 and later based ones
Debian | 12 | Yes | 4KB | [Community](https://wiki.debian.org/Cloud/AmazonEC2Image/Bookworm) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-63gms6fbfaota) | Yes |
Debian | 11 | Yes | 4KB | [Community](https://wiki.debian.org/Cloud/AmazonEC2Image/Bullseye) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-jwzxq55gno4p4) | Yes |
Debian | 10 | [Planned for Debian 11](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=956418) | 4KB | [Community](https://wiki.debian.org/Cloud/AmazonEC2Image/Buster) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B085HGTX5J) | Yes, as of Debian 10.7 (2020-12-07) |
FreeBSD | 13.5 | Yes | 4KB | [Community](https://www.freebsd.org/releases/13.5R/announce) or [MarketPlace](https://aws.amazon.com/marketplace/pp/B09291VW11) | No | Device hotplug and API shutdown don't work
FreeBSD | 14.2 | Yes | 4KB | [Community](https://www.freebsd.org/releases/14.2R/announce/) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-axdyrrhr6pboq) (UFS) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-7xtubzy4v4oo4) (ZFS) | Yes | Device hotplug doesn't work
FreeBSD | 14.3 | Yes | 4KB | [Community](https://www.freebsd.org/releases/14.3R/announce/) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-axdyrrhr6pboq) (UFS) or [MarketPlace](https://aws.amazon.com/marketplace/pp/prodview-7xtubzy4v4oo4) (ZFS) | Yes | Maintained by [Colin Percival](mailto:cperciva@FreeBSD.org)
 Flatcar Linux | 3033.2.0 or later | Yes | 4KB | [AMIs](https://www.flatcar.org/docs/latest/installing/cloud/aws-ec2/) or [marketplace](https://aws.amazon.com/marketplace/pp/prodview-zmao5idgwafbi) | Yes | |
Rocky Linux | 8.4 or later | Yes (*) | 64KB (*) | [ISOs](https://rockylinux.org/download) | | [Release Notes](https://docs.rockylinux.org/release_notes/8-changelog/)<br>(*) details to be confirmed once AMI's are available


OS Name | Minimum recommended Linux kernel version for Graviton
------ | ------
Amazon Linux 2023 | All supported kernels
Amazon Linux 2 | >= 4.14.273-207.502.amzn2, >= 5.4.186-102.354.amzn2, or >= 5.10.106-102.504.amzn2
Ubuntu 24.04 | All supported kernels
Ubuntu 22.04 | All supported kernels 
Ubuntu 20.04 | >= 5.4.0-1047-aws, >= 5.8.0-1034-aws, >= 5.11.0-1009-aws
Ubuntu 18.04 | >= 4.15.0-1101-aws, >= 5.4.0-1047-aws
Redhat Entreprise Linux 8 | >= 4.18.0-305.10

# Operating systems which do not support Graviton based instances

 Name | Version | 
------ | ------ |
Microsoft Windows | All versions 
