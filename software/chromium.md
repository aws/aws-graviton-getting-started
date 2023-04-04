Chromium browser on AWS Graviton
================================

Amazon Linux 2023
-----------------

Amazon Linux 2023 does not currently have its own Chromium packages available. However, it is available via the
third-party Fedora and CentOS stream package repositories.

> **Warning**
> These packages are provided by third parties and are **unsupported** by AWS. **Use at your own risk.**

To install Chromium on Amazon Linux 2023, run the following commands (valid as of 2023-04-01).

```sh
sudo dnf -y install \
    https://kojipkgs.fedoraproject.org//packages/minizip/2.8.9/2.el8/aarch64/minizip-2.8.9-2.el8.aarch64.rpm \
    https://download-ib01.fedoraproject.org/pub/epel/9/Everything/aarch64/Packages/n/nss-mdns-0.15.1-3.1.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/gstreamer1-1.18.4-4.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libcanberra-0.30-26.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libcanberra-gtk3-0.30-26.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/sound-theme-freedesktop-0.8-17.el9.noarch.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-5.15.3-1.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-common-5.15.3-1.el9.noarch.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-gui-5.15.3-1.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/glx-utils-8.4.0-12.20210504git0f9e7d9.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/pipewire-libs-0.3.47-2.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/fdk-aac-free-2.0.0-8.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libldac-2.0.2.3-10.el9.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/111.0.5563.64/1.el8/aarch64/chromium-111.0.5563.64-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/111.0.5563.64/1.el8/aarch64/chromium-common-111.0.5563.64-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/111.0.5563.64/1.el8/aarch64/chromium-headless-111.0.5563.64-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/111.0.5563.64/1.el8/aarch64/chromedriver-111.0.5563.64-1.el8.aarch64.rpm

```