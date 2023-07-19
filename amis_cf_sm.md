# Amazon Machine Images (AMIs)

This document covers how to find AMIs compatible with AWS Graviton, and how to look up and use the AMIs in AWS System Manager and AWS CloudFormation.

## Using the console

AMIs can both be found in the console as explained in the [AWS documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/finding-an-ami.html#finding-an-ami-console)
when launching instances interactively.

## Using APIs - AWS Systems Manager Parameter Store

When integrating the AMI lookup process in a script or in a piece of code, it is more convenient to leverage [AWS Systems Manager](https://aws.amazon.com/systems-manager/) Parameter Store.

There's a good article about it on the AWS Compute blog: [Query for the latest Amazon Linux AMI IDs using AWS Systems Manager Parameter Store](https://aws.amazon.com/blogs/compute/query-for-the-latest-amazon-linux-ami-ids-using-aws-systems-manager-parameter-store/).

|OS release|Parameter name|
|----------|--------------|
|Amazon Linux 2023|`/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`|
|Amazon Linux 2023 minimal|`/aws/service/ami-amazon-linux-latest/al2023-ami-minimal-kernel-default-arm64`|
|Amazon Linux 2|`/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2`|
|Debian 11|`/aws/service/debian/release/11/latest/arm64`|
|Debian 12|`/aws/service/debian/release/12/latest/arm64`|
|Ubuntu 23.04|`/aws/service/canonical/ubuntu/server/23.04/stable/current/arm64/hvm/ebs-gp2/ami-id`|
|Ubuntu 22.04|`/aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id`|
|Ubuntu 21.04|`/aws/service/canonical/ubuntu/server/21.04/stable/current/arm64/hvm/ebs-gp2/ami-id`|
|Ubuntu 20.04|`/aws/service/canonical/ubuntu/server/20.04/stable/current/arm64/hvm/ebs-gp2/ami-id`|
|Ubuntu 18.04|`/aws/service/canonical/ubuntu/server/18.04/stable/current/arm64/hvm/ebs-gp2/ami-id`|
|SLES 15 SP4|`/aws/service/suse/sles/15-sp4/arm64/latest`|

Here is an example to get the AMI ID of the latest **Amazon Linux 2023** version in the us-east-1 region:

```sh
$ aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 --region us-east-1 --query Parameter.Value --output text
```

Here is an example to get the AMI ID of the latest **Amazon Linux 2** version in the us-east-1 region:

```sh
$ aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2 --region us-east-1 --query Parameter.Value --output text
```

AWS CloudFormation also supports AWS Systems Manager Parameter Store for obtaining AMI IDs without
hard-coding them.

Here is an example demonstrating how to refer to the latest **Amazon Linux 2023 AMI** for Graviton/arm64 in a CloudFormation template:

```yaml
Parameters:
  LatestAmiId:
    Type: AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>
    Default: /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64

Resources:
 GravitonInstance:
    Type: AWS::EC2::Instance
    Properties:
      ImageId: !Ref LatestAmiId
      InstanceType: c6g.medium
```


Here is an example demonstrating how to refer to the latest **Amazon Linux 2** AMI for Graviton/arm64 in a CloudFormation template:

```yaml
Parameters:
  LatestAmiId:
    Type: AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>
    Default: /aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2

Resources:
 GravitonInstance:
    Type: AWS::EC2::Instance
    Properties:
      ImageId: !Ref LatestAmiId
      InstanceType: c6g.medium
```
