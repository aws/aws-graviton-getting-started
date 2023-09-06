# Headless website testing with Chrome and Puppeteer on Graviton.

Chrome is a popular reference browser for web site unit testing on EC2 x86 instances. In the samer manner it can be used on EC2 Graviton instances.
It is open source in its Chromium incarnation, supports 'headless' mode and can simulate user actions via Javascript.
The Chrome web site [mentions Puppeteer](https://developer.chrome.com/blog/headless-chrome/#using-programmatically-node) and it is used here to show a specific
example of headless website testing on Graviton.
“[Puppeteer](https://pptr.dev/) is a Node.js library which provides a high-level API to control Chrome/Chromium over the DevTools Protocol. 
Puppeteer runs in headless mode by default, but can be configured to run in full ("headful") Chrome/Chromium."
It can serve as a replacement for the previously very popular Phantomjs.
“PhantomJS (phantomjs.org) is a headless WebKit scriptable with JavaScript. The latest stable release is version 2.1.
Important: PhantomJS development is suspended until further notice (see #15344 for more details).“
The APIs are different, so code targetting PhantomJS has to be rewritten when moving to Puppeteer (see Appendix).
Puppeteer is open source and has 466 contributors and 364k users and thus is likely to be supported for some time.

### Get a recent version of NodeJS.

Ubuntu-22:
```
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
NODE_MAJOR=20
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update
sudo apt-get install nodejs -y
```
AL2023:
```
sudo yum install https://rpm.nodesource.com/pub_20.x/nodistro/repo/nodesource-release-nodistro-1.noarch.rpm -y
sudo yum install nodejs -y --setopt=nodesource-nodejs.module_hotfixes=1
```
[https://github.com/nodesource/distributions/tree/master]

### Install Puppeteer.
```
npm i puppeteer@21.1.0
```
Puppeteer packages an x86 version of Chrome which needs to be replaced with an aarch64 version.

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
As QT version above will be updated, and the old one become unavailable at some point, the version variable will need to be changed accordingly.
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
Puppeteer needs a particular version of chromium, in this case (Puppeteer-21.1.0), it uses Chromium 116.0.5845.96.
If a different version of Puppeteer is needed, the directory `~/.cache/puppeteer/chrome` indicates which version of Chromium it is targeting.
This version must be assigned to the `CHROMEVER` variable above.
If the required version of Chromium is not available at `https://kojipkgs.fedoraproject.org/packages/chromium/` 
then proceed to `https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md`.

### Code Examples

Example code for Puppeteer can be found at https://github.com/puppeteer/examples

### Virtual Framebuffer Xserver

Some code examples, such as puppeteer/examples/oopif.js, may need a 'headful' chrome and thus an Xserver.
A virtual framebuffer Xserver can be used for that.

Ubuntu-22.04: ```sudo apt install xvfb```
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


## Appendix.

### Code example to show the difference in API between PhantomJS and Puppeteer.


Puppeteer Screenshot:
```
'use strict';

const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();
  await page.goto('https://www.google.com', {waitUntil: 'load', timeout: 1000});
  await page.screenshot({path: 'google.png'});
  await browser.close();
})();
```
The same with PhantomJS:
```
var page = require('webpage').create();
page.open('http://www.google.com', function() {
    setTimeout(function() {
        page.render('google.png');
        phantom.exit();
    }, 200);
});
```

