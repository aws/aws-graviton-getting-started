# Building TensorFlow on Graviton2

Install bazel build system:
```
wget https://github.com/bazelbuild/bazel/releases/download/3.7.1/bazel-3.7.1-linux-arm64
chmod +x bazel-3.7.1-linux-arm64
sudo mv bazel-3.7.1-linux-arm64 /usr/local/bin
sudo ln -s /usr/local/bin/bazel-3.7.1-linux-arm64 /usr/local/bin/bazel
```

Build TensorFlow on Graviton2 with Ubuntu 20.04:
```
sudo apt install build-essential python python3-pip
sudo pip3 install numpy keras_preprocessing
git clone https://github.com/tensorflow/tensorflow $HOME/tensorflow
cd $HOME/tensorflow
./configure
bazel build //tensorflow/tools/pip_package:build_pip_package
```

Run an inference task:
```
cd $HOME/tensorflow/tensorflow/examples/label_image/data
wget https://storage.googleapis.com/download.tensorflow.org/models/inception_v3_2016_08_28_frozen.pb.tar.gz
tar xf inception_v3_2016_08_28_frozen.pb.tar.gz
cd $HOME/tensorflow
bazel build tensorflow/examples/label_image/...
bazel-bin/tensorflow/examples/label_image/label_image
```
