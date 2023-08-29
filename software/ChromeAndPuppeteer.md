# (Headless) Chrome and Puppeteer on Graviton

“[Puppeteer](https://pptr.dev/) is a Node.js library which provides a high-level API to control Chrome/Chromium over the DevTools Protocol. 
Puppeteer runs in headless mode by default, but can be configured to run in full ("headful") Chrome/Chromium."
It can serve as a replacement for  Phantomjs.
“PhantomJS (phantomjs.org) is a headless WebKit scriptable with JavaScript. The latest stable release is version 2.1.
Important: PhantomJS development is suspended until further notice (see #15344 for more details).“
The APIs are different, so the browser related code has to be adapted when moving from PhantomJS to Puppeteer.
Puppeteer has 466 contributors and 364k users.

### Get a recent version of NodeJS.

Ubuntu-22:
```
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodej
```
AL2023:
```
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install -y nodejs
```
[https://github.com/nodesource/distributions/tree/master]

### Install Puppeteer.
```
npm install -g puppeteer@21.1.0
```
We now have a x86 version of Chrome thus:

### Install aarch64 version of Chrome.

Ubuntu-22:
```
sudo apt update
sudo apt install chromium-browser chromium-codecs-ffmpeg
```
AL2023:
```
QTVER=5.15.9-2
CHROMEVER=116.0.5845.96

sudo dnf -y install \
    https://kojipkgs.fedoraproject.org//packages/minizip/2.8.9/2.el8/aarch64/minizip-2.8.9-2.el8.aarch64.rpm \
    https://download-ib01.fedoraproject.org/pub/epel/9/Everything/aarch64/Packages/n/nss-mdns-0.15.1-3.1.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/gstreamer1-1.18.4-4.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libcanberra-0.30-26.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libcanberra-gtk3-0.30-26.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/sound-theme-freedesktop-0.8-17.el9.noarch.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-$QTVER.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-common-$QTVER.el9.noarch.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/qt5-qtbase-gui-$QTVER.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/glx-utils-8.4.0-12.20210504git0f9e7d9.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/pipewire-libs-0.3.47-2.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/fdk-aac-free-2.0.0-8.el9.aarch64.rpm \
    http://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/libldac-2.0.2.3-10.el9.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/$CHROMEVER/1.el8/aarch64/chromium-$CHROMEVER-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/$CHROMEVER/1.el8/aarch64/chromium-common-$CHROMEVER-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/$CHROMEVER/1.el8/aarch64/chromium-headless-$CHROMEVER-1.el8.aarch64.rpm \
    https://kojipkgs.fedoraproject.org//packages/chromium/$CHROMEVER/1.el8/aarch64/chromedriver-$CHROMEVER-1.el8.aarch64.rpm
```
The QT version above will become unavailable at some point and may need to be updated.
If this is the case, check: https://mirror.stream.centos.org/9-stream/AppStream/aarch64/os/Packages/ to see which version is available.
```
rm .cache/puppeteer/chrome/linux-116.0.5845.96/chrome-linux64/chrome
ln -s /usr/bin/chromium-browser .cache/puppeteer/chrome/linux-116.0.5845.96/chrome-linux64/chrome
```
This brute force install works because:
```
/snap/bin/chromium --version
Chromium 116.0.5845.96 snap
```
Puppeteer needs a particular version of chromium and in this case this works.
Version puppeteer(-core) 21.1.0 uses Chromium 116.0.5845.96

### Virtual Framebuffer Xserver

Some code examples, such as puppeteer/examples/oopif.js, may need a 'headful' chrome and thus an Xserver.
A virtual framebuffer Xserver can be used for that.

Ubuntu-22: ```sudo apt install xvfb```
AL2023: ```sudo yum install Xvfb```
```
Xvfb &
export DISPLAY=:0
```
When Chrome is now invoked in headful mode, it has an Xserver to render to.

This can be tested with:
```
node puppeteer/examples/oopif.js
```
The oopif.js example invokes chrome in headful mode.

