# AWS Lambda on Graviton2
[AWS Lambda](https://aws.amazon.com/lambda/) now allows you to configure new and existing functions to run on Arm-based AWS Graviton2 processors in addition to x86-based functions. Using this processor architecture option allows you to get up to 34% better price performance. Duration charges, billed with [millisecond granularity](https://aws.amazon.com/blogs/aws/new-for-aws-lambda-1ms-billing-granularity-adds-cost-savings/), are 20 percent lower when compared to current x86 pricing. This also applies to duration charges when using [Provisioned Concurrency](https://aws.amazon.com/blogs/aws/new-provisioned-concurrency-for-lambda-functions/). Compute [Savings Plans](https://aws.amazon.com/blogs/aws/savings-plan-update-save-up-to-17-on-your-lambda-workloads/) supports Lambda functions powered by Graviton2.

The blog post [Migrating AWS Lambda functions to Arm-based AWS Graviton2 processors](https://aws.amazon.com/blogs/compute/migrating-aws-lambda-functions-to-arm-based-aws-graviton2-processors/) shows some considerations when moving from x86 to arm64 as the migration process is code and workload dependent.

This page highlights some of the migration considerations and also provides some simple to deploy demos you can use to explore how to build and migrate to Lambda functions using Arm/Graviton2.

The architecture change does not affect the way your functions are invoked or how they communicate their responses back. Integrations with APIs, services, applications, or tools are not affected by the new architecture and continue to work as before.
The following runtimes, which use [Amazon Linux 2](https://aws.amazon.com/amazon-linux-2/), are supported on Arm:
*	Node.js 12 and above
*	Python 3.8 and above
*	Java 8 (java8.al2) and above
*	.NET Core 3.1 and above
*	Ruby 2.7 and above
*	[Custom runtime](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html) (provided.al2) and above

## Migrating x86 Lambda functions to arm64
### Functions without architecture-specific dependencies or binaries
Many Lambda functions may only need a configuration change to take advantage of the price/performance of Graviton2. Other functions may require repackaging the Lambda function using Arm-specific dependencies, or rebuilding the function binary or container image.

If your functions don’t use architecture-specific dependencies or binaries, you can switch from one architecture to the other with a single configuration change. Many functions using interpreted languages such as Node.js and Python, or functions compiled to Java bytecode, can switch without any changes. Ensure you check binaries in dependencies, Lambda layers, and Lambda extensions.

### Building function code for Graviton2
For compiled languages like Rust and Go, you can use the `provided.al2` or `provided.al2023`  [custom runtimes](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html), which supports Arm. You provide a binary that communicates with the [Lambda Runtime API](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html).

When compiling for Go, set `GOARCH` to `arm64`.
```
GOOS=linux GOARCH=arm64 go build
```
When compiling for Rust, set the `target`.
```
cargo build --release -- target-cpu=neoverse-n1
```
The default installation of Python `pip` on some Linux distributions is out of date (<19.3). To install binary wheel packages released for Graviton, upgrade the pip installation using:
```
sudo python3 -m pip install --upgrade pip
````

Functions packaged as container images must be built for the architecture (x86 or arm64) they are going to use. There are arm64 architecture versions of the [AWS provided base images for Lambda](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-images.html#runtimes-images-lp). To specify a container image for arm64, use the arm64 specific image tag, for example, for Node.js 20:
```
public.ecr.aws/lambda/nodejs:20-arm64
public.ecr.aws/lambda/nodejs:latest-arm64
public.ecr.aws/lambda/nodejs:20.2024.01.05.14-arm64
```
Arm64 images are also available from [Docker Hub](https://hub.docker.com/u/amazon).
You can also use arbitrary Linux base images in addition to the AWS provided Amazon Linux 2 images. Images that support arm64 include [Alpine](https://alpinelinux.org/) Linux 3.12.7 or later, [Debian](https://www.debian.org/) 10 and 11, Ubuntu 18.04 and 20.04. For more information and details of other supported Linux versions, see [Operating systems available for Graviton based instances](https://github.com/aws/aws-graviton-getting-started/blob/main/os.md#operating-systems-available-for-graviton-based-instances).

The [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) open-source project runs your functions using different settings to suggest a configuration to minimize costs and maximize performance. The tool allows you to compare two results on the same chart and incorporate arm64-based pricing. This is useful to compare two versions of the same function, one using x86 and the other arm64.

## DEMO: Building Lambda functions for Graviton2
Demo requirements: 
* [AWS Serverless Application Model (AWS SAM)](https://aws.amazon.com/serverless/sam/)
* [Docker](https://docs.docker.com/get-docker/)

Clone the repository and change into the demo directory
```
git clone https://github.com/aws/aws-graviton-getting-started
cd aws-graviton-getting-started/aws-lambda/GravitonLambdaNumber
```
### Migrating a Lambda function from x86 to arm64
This demo shows how to migrate an existing Lambda function from x86 to arm64 using an x86 based workstation.
The Node.js function code in [`/src/app.js`](/src/app.js) uses the [axios](https://www.npmjs.com/package/axios) client to connect to a third part service, [http://numbersapi.com/](http://numbersapi.com/), to find interesting facts about numbers. As the axios library is not a binary file, it can seamlessly work on Graviton2 without compilation.

The existing application consists of an API endpoint which invokes the Lambda function, retrieves the number fact, and returns the response.

Build the existing x86 function version using AWS SAM.
```
sam build
```
![sam build](/aws-lambda/img/sambuild.png)

Deploy the function to your AWS account:
```
sam deploy --stack-name GravitonLambdaNumber -g
```
Accept the initial defaults, and ensure you enter Y for `LambdaNumberFunction may not have authorization defined, Is this okay? [y/N]: y`

![sam deploy -g](/aws-lambda/img/samdeploy-g.png)

AWS SAM deploys the infrastructure and outputs an APIBasePath

![ApiBasePath](/aws-lambda/img/ApiBasePath.png)

Use `curl` and make a POST request to the APIBasePath URL with a number as a date.
```
curl -X POST https://6ioqy4z9ee.execute-api.us-east-1.amazonaws.com -H 'Content-Type: application/json' -d '{ "number": "345", "type": "date" }'
```
The Lambda function should respond with the `x64` processor architecture and a fact about the date.

![curl x86](/aws-lambda/img/curlx86.png)

Amend the processor architecture within the AWS SAM [template.yml](./GravitonLambdaNumber/template.yml) file.
replace 
```
Architectures:
- x86_64
```        
with
```
Architectures:
- arm64
```        

Build the function using an arm64 architecture and deploy the change to the cloud.
```
sam build
sam deploy
```
Use the same `curl` command, making a POST request to the APIBasePath URL with a number as a date.
```
curl -X POST https://6ioqy4z9ee.execute-api.us-east-1.amazonaws.com -H 'Content-Type: application/json' -d '{ "number": "345", "type": "date" }'
```
The Lambda function should respond with the `arm64` processor architecture and a fact about the date.

![curl arm64](/aws-lambda/img/curlarm64.png)

The function has seamlessly migrated from x86 to arm64.

### Building a Lambda function with binary dependencies

This function has no binary dependencies. If you do have a function that required compilation for arm64, AWS SAM can use an arm64 build container image to create the artifacts for arm64.
This functionality works both ways. You can build arm64 specific dependencies on an x86 workstation and also build x86 specific dependencies on an arm64 workstation.

Specify `--use-container` to use the build container.
```
sam build --use-container
```
![sam build --use-container](/aws-lambda/img/sambuildcontainer.png)

### Local testing
You can test the arm64 function locally using either AWS SAM or Docker natively.

When using AWS SAM, you can use [`sam local invoke`]([template.yml](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-command-reference-sam-local-invoke.html)) to test your function locally, passing in a sample `event.json`
```
sam local invoke LambdaNumberFunction -e ./test/event.json
```
![sam local invoke](/aws-lambda/img/samlocalinvoke.png)

### Building arm64 Lambda functions as container images
You can build arm64 functions as container images. You  can use [AWS SAM natively](https://aws.amazon.com/blogs/compute/using-container-image-support-for-aws-lambda-with-aws-sam/) to build container images.

You can also use Docker native commands instead of AWS SAM.
To build a container image of this function using Docker, use the [Dockerfile](./GravitonLambdaNumber/src/Dockerfile) and specify the `nodejs:20-arm64` base image.
```
FROM public.ecr.aws/lambda/nodejs:20-arm64
COPY app.js package*.json $LAMBDA_TASK_ROOT
RUN npm install
CMD [ "app.lambdaHandler" ]
```
Build the container image.
```
docker build -t dockernumber-arm ./src 
```
![docker build](/aws-lambda/img/dockerbuild.png)

Inspect the container image to confirm the `Architecture`.
```
docker inspect dockernumber-arm | grep Architecture 
```
![docker inspect](/aws-lambda/img/dockerinspect.png)

You can locally test the function using `docker run`
In another terminal window run the Lambda function docker container image.
```
docker run -p 9000:8080 dockernumber-arm:latest
```
![docker run](/aws-lambda/img/dockerrun.png)

Use `curl` to invoke the Lambda function using the local docker endpoint, passing in a sample `event.json`.
```
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d @./test/event.json
```
![docker run response](/aws-lambda/img/dockerrunresponse.png)

You can view the local logs in the `docker run` terminal window.

To create a Lambda function from the local image, first create an [Amazon Elastic Container Registry (ECR)]](https://aws.amazon.com/ecr/) repository and login to ECR.
Substitute the AWS account number `123456789012` and AWS Region values with your details
```
aws ecr create-repository --repository-name dockernumber-arm --image-scanning-configuration scanOnPush=true
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com
```
Tag and push the docker image to ECR.
```
docker tag dockernumber-arm:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/dockernumber-arm:latest
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/dockernumber-arm:latest
```
You can then create a Lambda function from the container image using the AWS Management Console, AWS CLI, or other tools.
![Create function from image](/aws-lambda/img/createfunctionfromimage.png)

## Comparing x86 and arm64 performance and cost.
You can use the [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) open-source project to suggest a configuration to minimize costs and maximize performance. The tool allows you to compare two results on the same chart and incorporate arm64-based pricing. This is useful to compare two versions of the same function, one using x86 and the other arm64.

A demo application computes prime numbers. The AWS SAM [template.yml](template.yml) file contains two Lambda functions, one for x86 and one for arm64. Both functions use the same Python source code in [`./src/app.py`](./src/app.py) to compute the prime numbers.

Ensure the repository is cloned from the previous demo and change into the directory.
```
cd ../PythonPrime
```
Build the application within the AWS SAM build container images and deploy to the cloud.
Accept the default `sam deploy` prompts.
```
sam build --use-container
sam deploy --stack-name PythonPrime -g
```
Note the Output values of the two Lambda functions:
![Prime Functions](/aws-lambda/img/primefunctions.png)

### Deploy the AWS Lambda Power Tuning State Machine
Navigate to [https://serverlessrepo.aws.amazon.com/applications/arn:aws:serverlessrepo:us-east-1:451282441545:applications~aws-lambda-power-tuning](https://serverlessrepo.aws.amazon.com/applications/arn:aws:serverlessrepo:us-east-1:451282441545:applications~aws-lambda-power-tuning) and choose **Deploy**.
Select *I acknowledge that this app creates custom IAM roles* and choose **Deploy**.

Once deployed, under *Resources*, choose the *powerTuningStateMachine*.

Choose **Start execution**
For the state machine input, specify the ARN of the x86 Lambda function from the AWS SAM Outputs, and set the memory `powerValues` to check. Run 10 invocations for each memory configuration, in parallel, specifying the Lambda function payload.
The following is an example input.
```
{
	"lambdaARN": "arn:aws:lambda:us-east-1:123456789012:function:gravitonpythonprime-PythonPrimeX86Function-3Gge9WXmHObZ",
	"powerValues": [
		128,
		256,
		512,
		1024,
		1536,
		2048,
		3008,
		10240
	],
	"num": 10,
	"parallelInvocation": true,
	"payload": {
		"queryStringParameters": {
			"max": "1000000"
		}
	}
}
```
Select *Open in a new browser tab* and choose **Start execution**.
The Lambda Power Tuning state machine runs for each configured memory value.
![PowerTuningStateMachine](/aws-lambda/img/powertuningstatemachine.png)

Once complete, the *Execution event history* final step, *ExecutionSucceeded* contains a visualization URL. 
```
{
  "output": {
    "power": 512,
    "cost": 0.000050971200000000004,
    "duration": 6067.418333333332,
    "stateMachine": {
      "executionCost": 0.00035,
      "lambdaCost": 0.007068295500000001,
      "visualization": "https://lambda-power-tuning.show/#gAAAAQACAAQABgAIwAsAKA==;5njERiCGREZZm71F9rxARW12AkU66d5EDqzeRLFs30Q=;a4NdODSTXTjpyVU42k9ZOLixXDipans4V224ONx8nTk="
    }
  },
  "outputDetails": {
    "truncated": false
  }
}
```
Browse to the lambda-power-tuning URL to view the average *Invocation time (ms)* and *Invocation Cost (USD)* for each memory value for the x86 function.

![PowerTuning x86 results](/aws-lambda/img/powertuningx86results.png)

Navigate back to the Step Functions console and run another state machine, specifying the ARN of the arm64 Lambda function from the AWS SAM Outputs.
Once complete, copy the visualization URL from the *Execution event history* final step, *ExecutionSucceeded*. 

In the *lambda-power-tuning* browser tab showing the x86 results, choose **Compare**.
Enter **x86** as name for function 1
Enter **arm64** as the name for function 2
Paste in the URL from the arm64 function and choose **Compare**.

![PowerTuning Compare](/aws-lambda/img/powertuningcompare.png)

View the comparison between the *x86* and the *arm64* function.

![PowerTuning Comparison](/aws-lambda/img/powertuningcomparison.png)

At 2048 MB, the arm64 function is 29% faster and 43% cheaper than the identical Lambda function running on x86!
Power Tuning gives you a data driven approach to select the optimal memory configuration for your Lambda functions. This allows you to also compare x86 and arm64 and may allow you to reduce the memory configuration of your arm64 Lambda functions, further reducing costs.
