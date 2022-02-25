# ML inference on Graviton CPUs with TensorFlow

There are two ways to use tensforflow based ml inferencing on Graviton CPUs.
- Tensorflow DLAMI
- Tensorflow Docker container

**Using AWS DLAMI:**
To launch a Graviton instance with a DLAMI via EC2 console:

1. Click on "Community AMIs"
2. Filter AMIs by clicking Ubuntu and Arm (64-bit) check boxes
3. Search for "Deep Learning" in search field to list the current Ubuntu based DLAMIs"
4. Select the AMI: "Deep Learning AMI Graviton Tensorflow <version>(Ubuntu 20.04) <yyyy/mm/dd>"

Here is the awscli snippet to find the latest AMI:
```
aws ec2 describe-images --region us-west-2 --filters  Name=architecture,Values=arm64 Name=name,Values="*Deep Learning AMI*" Name=owner-alias,Values=amazon  --query 'Images[] | sort_by(@, &CreationDate)[-1] | ImageId'
```

Here is the awscli snippet to launch the same:
```
aws ec2 run-instances --region us-west-2 --image-id <ami-id from the above command>  --instance-type c6g.4xlarge --count 1  --key-name <key name> --subnet-id <subnet_id> --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=256}'
```

Once Graviton instance is launched with the above DLAMI, the platform is ready for building Tensorflow based ML inference applications.The DLAMI comes with the additional libraries preinstalled, eg: rust compilers, transformers etc, to enable transformers based (eg: bert) inferencing applications.
```
# One can check the TF version as below
pip show tensorflow

# By default it's eigen, but typically onednn+acl provides better performance and this can be enabled by setting the below TF environment variable
export TF_ENABLE_OENDNN_OPTS=1

# Graviton3 (eg: c7g instances) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
export DNNL_DEFAULT_FPMATH_MODE=BF16
```

**Using docker container:**
Launch a Graviton instance with an Ubuntu 20.04 AMI and instal docker using the below instructions.
```
#install and enable docker
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ubuntu

# pull the tensorflow docker container with onednn-acl optimizations enabled
docker pull armswdev/tensorflow-arm-neoverse

# launch the docker image
docker run -it --rm -v /home/ubuntu/:/hostfs armswdev/tensorflow-arm-neoverse

# Graviton3 (eg: c7g instances) supports BF16 format for ML acceleration. This can be enabled in oneDNN by setting the below environment variable
export DNNL_DEFAULT_FPMATH_MODE=BF16
```

**Execute MLPerf inference benchmarks within docker container**
```
# The docker image comes pre-installed with the MLPerf inference benchmarks so one can benchmark the install and verify everything is configured properly.

cd examples/MLCommons

# To benchmark mlperf resnet50, image classification model, download the imagenet dataset, select option#1 when prompted
./download-dataset.sh
./download-model.sh

cd /home/ubuntu/examples/MLCommons/inference/vision/classification_and_detection

#set the data and model path
export DATA_DIR=/home/ubuntu/CK-TOOLS/dataset-imagenet-ilsvrc2012-val-min
export MODEL_DIR=/home/ubuntu/examples/MLCommons/inference/vision/classification_and_detection

# setup the tensorflow thread pool parameters for optimal performance
export MLPERF_NUM_INTER_THREADS=1
export MLPERF_NUM_INTRA_THREADS= <#of vcpus>

./run_local.sh tf resnet50 cpu --scenario=Offline

# To benchmark mlperf bert, natural language processing model:
cd /home/ubuntu/examples/MLCommons/inference/language/bert
make setup
python3 run.py --backend=tf --scenario=Offline
```
