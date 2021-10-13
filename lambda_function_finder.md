

## Graviton2 Function Finder Script

This script will find the all functions on a runtime and in regions that are currently supported by Graviton2.  The script also lists out the functions that are on a non-compatible runtime(requiring a runtime upgrade).

This script can be easily copy and pasted into a [AWS CloudShell](https://aws.amazon.com/cloudshell/) shell.  

```

# Graviton2 Function Finder
# Identify Lambda functions with Graviton2 compatiable and not-ompatiable runtimes versions.  Looks in all regions where Graviton2 Lambda is currently available.
# Lambda runtimes support for Graviton2 : https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html

echo "Graviton2 Function Support Finder"

for region in us-east-1 us-east-2 us-west-2 eu-west-1 eu-west-2 eu-central-1 ap-southeast-1 ap-southeast-2 ap-northeast-1 ap-south-1
do
    echo "  "
    echo "Region: [${region}] - Functions WITH Graviton Compatible Runtimes"
    echo "  "

    # python
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='python3.8'].{ARN:FunctionArn, Runtime:Runtime}"
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='python3.9'].{ARN:FunctionArn, Runtime:Runtime}"
    # nodejs
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='nodejs12.x'].{ARN:FunctionArn, Runtime:Runtime}"
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='nodejs14.x'].{ARN:FunctionArn, Runtime:Runtime}"
    # dotnet
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='dotnetcore3.1'].{ARN:FunctionArn, Runtime:Runtime}"
    # ruby
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='ruby2.7'].{ARN:FunctionArn, Runtime:Runtime}"
    # java
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='java8.al2'].{ARN:FunctionArn, Runtime:Runtime}"
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='java11'].{ARN:FunctionArn, Runtime:Runtime}"
    # custom
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='provided.al2'].{ARN:FunctionArn, Runtime:Runtime}"
    # container image
    aws lambda list-functions --region ${region} --output text --query "Functions[?PackageType=='Image'].{ARN:FunctionArn, PackageType:'container-image'}"

    echo "  "
    echo "Region: [${region}] - Functions with Runtimes that are NOT Compatible with Graviton2. Require a Runtime version update."
    echo "  "

    # python
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='python3.6'].{ARN:FunctionArn, Runtime:Runtime}"
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='python3.7'].{ARN:FunctionArn, Runtime:Runtime}"
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='python2.7'].{ARN:FunctionArn, Runtime:Runtime}"
    # nodejs
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='nodejs10.x'].{ARN:FunctionArn, Runtime:Runtime}"
    # dotnet
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='dotnetcore2.1'].{ARN:FunctionArn, Runtime:Runtime}"
    # ruby
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='ruby2.5'].{ARN:FunctionArn, Runtime:Runtime}"
    # java
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='java8'].{ARN:FunctionArn, Runtime:Runtime}"
    # go
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='go1.x'].{ARN:FunctionArn, Runtime:Runtime}"
    # custom
    aws lambda list-functions --region ${region} --output text --query "Functions[?Runtime=='provided'].{ARN:FunctionArn, Runtime:'Runtime'}"

done
echo "finished"

```
