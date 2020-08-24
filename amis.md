# AMIs

## Amazon Linux 2

### Using the console

Amazon Linux 2 AMIs can be found in the console as explained in the [AWS documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/finding-an-ami.html#finding-an-ami-console) when launching instances interactively.

### Using APIs - AWS Systems Manager Parameter Store

When integrating the AMI lookup process in a script or in a piece of code, it is more convenient to leverage [AWS Systems Manager](https://aws.amazon.com/systems-manager/) Parameter Store.

There's a good article about it on the AWS Compute blog: [Query for the latest Amazon Linux AMI IDs using AWS Systems Manager Parameter Store](https://aws.amazon.com/blogs/compute/query-for-the-latest-amazon-linux-ami-ids-using-aws-systems-manager-parameter-store/).

For Graviton2/arm64 Amazon Linux 2 AMIs, the namespace is the following:

- **Parameter Store Prefix (tree)**: ```/aws/service/ami-amazon-linux-latest/``` 
- **AMI name alias**: ```amzn2-ami-hvm-arm64-gp2```

Here is an example to get the AMI_ID of the latest Amazon Linux 2 version in ```us-east-1```:

```
$ aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2 --region us-east-1 --query "Parameters[].Value" --output text
```

AWS CloudFormation also supports Parameter Store, and here is an example on how you can add a reference to the latest Graviton2/arm64 Amazon Linux 2 AMI in a CloudFormation template:

```YAML
Parameters:
  LatestAmiId:
    Type: 'AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>'
    Default: '/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-arm64-gp2'

Resources:
 Graviton2Instance:
    Type: 'AWS::EC2::Instance'
    Properties:
      ImageId: !Ref LatestAmiId
      InstanceType: 'c6g.medium'
```
