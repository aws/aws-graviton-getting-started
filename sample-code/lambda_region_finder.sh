#!/bin/bash -e

# Graviton2 Function Finder
# Identify Lambda functions with Graviton2 compatible and not-compatible runtimes versions.  Looks in all regions where Graviton2 Lambda is currently available.
# Lambda runtimes support for Graviton2 docs: https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html

supported_regions=(us-east-1 us-east-2 us-west-2 eu-west-1 eu-west-2 eu-central-1 ap-southeast-1 ap-southeast-2 ap-northeast-1 ap-south-1)
supported_runtimes=(python3.8 python3.9 nodejs12.x nodejs14.x dotnetcore3.1 ruby2.7 java8.al2 java11 provided.al2)
unsupported_runtimes=(python3.6 python3.7 python2.7 nodejs10.x dotnetcore2.1 ruby2.5 java8 go1.x provided)

echo "Graviton2 Function Support Finder"

for region in "${supported_regions[@]}"
        do
	echo "  "
	echo "Region: [${region}] - Functions WITH Graviton Compatible Runtimes"
	echo "  "

	for runtime in "${supported_runtimes[@]}"
        do
		aws lambda list-functions --region "${region}" --output text --query "Functions[?Runtime=='${runtime}'].{ARN:FunctionArn, Runtime:Runtime}"

	done

        # include the container image functions
	aws lambda list-functions --region "${region}" --output text --query "Functions[?PackageType=='Image'].{ARN:FunctionArn, PackageType:'container-image'}"


	echo "  "
	echo "Region: [${region}] - Functions with Runtimes that are NOT Compatible with Graviton2. Require a Runtime version update."
	echo "  "

	for runtime in "${unsupported_runtimes[@]}"
        do
		aws lambda list-functions --region "${region}" --output text --query "Functions[?Runtime=='${runtime}'].{ARN:FunctionArn, Runtime:Runtime}"
	done
done
echo "finished"