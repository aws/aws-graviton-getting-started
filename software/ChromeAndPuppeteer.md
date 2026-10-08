# Headless Chrome and Chromium on Graviton (Puppeteer, Playwright)

Google Chrome, Chromium, Puppeteer and Playwright run natively on Graviton. Google publishes Google Chrome packages for arm64 Linux, [Chrome for Testing](https://github.com/GoogleChromeLabs/chrome-for-testing#supported-platforms) has `linux-arm64` builds, and Puppeteer and Playwright download arm64 browser builds. You don't need x86 emulation or a swapped-in browser binary.

This page covers headless use, such as testing, screenshots and PDF generation, on Ubuntu, Debian and Amazon Linux 2023 (AL2023). It does not cover Amazon Linux 2, which [reached end of support](https://aws.amazon.com/amazon-linux-2/faqs/) on 2026-06-30.

We tested the commands on this page in October 2026 on Graviton4 instances running Ubuntu 22.04, Ubuntu 24.04 and AL2023, and in `node:22-bookworm` (Debian 12) and `debian:trixie` (Debian 13) containers.

## Choose a browser

| Distribution | Google Chrome | Chromium | Browser downloaded by Puppeteer or Playwright |
|---|---|---|---|
| Ubuntu 22.04, 24.04 | `.deb` package from Google | Snap only | Supported. On 24.04, see [Sandbox](#sandbox) |
| Debian 12, 13 | `.deb` package from Google | `chromium` package | Supported by both projects |
| AL2023 | `.rpm` package from Google: tested, not officially supported | [SPAL](#chromium-on-amazon-linux-2023-spal): community packages, no AWS support | Works after you install libraries with `dnf`. Playwright uses an unofficial fallback build |

Puppeteer and Playwright can download their own browser, so a separately installed browser is optional. Install Google Chrome or a distribution's Chromium when you want the package manager to keep the browser updated, or when other tools use the same browser. Google Chrome is also the browser that `channel: 'chrome'` selects in Puppeteer and Playwright.

## Install Google Chrome

Google's [system requirements](https://support.google.com/chrome/answer/95346) list 64-bit Ubuntu 18.04+, Debian 10+, openSUSE 15.5+ and Fedora Linux 39+, and 64-bit Arm CPUs. Amazon Linux is not on the list.

### Google Chrome on Ubuntu and Debian

```sh
curl -fsSLO https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb
sudo apt-get install -y ./google-chrome-stable_current_arm64.deb
google-chrome --version
```

The package also adds Google's apt repository, so `apt` updates Chrome along with your other packages.

### Google Chrome on Amazon Linux 2023

Google's aarch64 RPM installs and runs on AL2023, but Google doesn't list Amazon Linux as a supported platform: this is tested, not officially supported. Add Google's repository with signature checking enabled, then install Chrome:

```sh
sudo tee /etc/yum.repos.d/google-chrome.repo <<'EOF'
[google-chrome]
name=google-chrome
baseurl=https://dl.google.com/linux/chrome/rpm/stable/aarch64
enabled=1
gpgcheck=1
gpgkey=https://dl.google.com/linux/linux_signing_key.pub
EOF
sudo dnf install -y google-chrome-stable
google-chrome --version
```

### Check that headless Chrome works

Run Chrome as a regular user. As root, Chrome exits with `Running as root without --no-sandbox is not supported`.

```sh
google-chrome --headless --dump-dom https://example.com
google-chrome --headless --window-size=1280,800 --screenshot=example.png https://example.com
```

The first command prints the page's HTML. The second writes `example.png`.

## Install Chromium

### Chromium on Ubuntu

Ubuntu provides Chromium only as a snap. The `chromium-browser` deb is a transitional package that installs the snap.

```sh
sudo snap install chromium
/snap/bin/chromium --headless --dump-dom https://example.com
```

The snap needs `snapd`, so use Google Chrome or Debian's `chromium` package in container images instead (see [Containers](#containers)).

### Chromium on Debian

Debian packages Chromium natively. The `chromium` package installs `/usr/bin/chromium`, and `chromium-headless-shell` installs `/usr/bin/chromium-headless-shell`. The [Containers](#containers) section has a Debian Dockerfile.

### Chromium on Amazon Linux 2023 (SPAL)

The AL2023 core repositories don't include Chromium. [Supplementary Packages for Amazon Linux](https://docs.aws.amazon.com/linux/al2023/ug/spal.html) (SPAL) does:

```sh
sudo dnf install -y spal-release
sudo dnf install -y chromium-headless chromedriver
/usr/lib64/chromium-browser/headless_shell --headless --dump-dom https://example.com
```

For the full browser, run `sudo dnf install -y chromium`.

| Package | Binary |
|---|---|
| `chromium-headless` | `/usr/lib64/chromium-browser/headless_shell` |
| `chromium` | `/usr/bin/chromium-browser` |
| `chromedriver` | `/usr/bin/chromedriver` |

SPAL provides community packages with no AWS support:

- SPAL packages are rebuilt from the community EPEL 9 repository. AWS states that they are not covered by AWS Support Plans, are provided as-is, and don't get AWS CVE tracking. Security fixes arrive only when EPEL 9 releases them.
- SPAL needs AL2023 release 2023.9.20251117 or later.
- SPAL's Chromium can lag behind Chrome stable. When we tested, it was two major versions behind. Use Google Chrome if you need the current release.

## Install Node.js

Puppeteer needs [Node.js 22.12 or later](https://pptr.dev/guides/system-requirements), and Playwright needs the [latest 22.x, 24.x or 26.x release](https://playwright.dev/docs/intro#system-requirements).

On Ubuntu, install Node.js 22 from [NodeSource](https://github.com/nodesource/distributions):

```sh
curl -fsSL https://deb.nodesource.com/setup_22.x -o nodesource_setup.sh
sudo bash nodesource_setup.sh
sudo apt-get install -y nodejs
```

On AL2023:

```sh
sudo dnf install -y nodejs22
```

## Puppeteer

### Install Puppeteer and its browser

Use Puppeteer 25.11.0 or later. From that release on, Puppeteer downloads the `linux-arm64` build of Chrome for Testing on Graviton. Earlier releases download the x86-64 build, which doesn't run there.

Puppeteer [needs `unzip`](https://pptr.dev/guides/system-requirements) to unpack the browser. The Ubuntu 22.04 and 24.04 AMIs don't include it. Without it, `npm i puppeteer` still exits successfully but leaves no browser behind, so install it first:

```sh
sudo apt-get install -y unzip
```

Then, in your project directory:

```sh
npm init -y
npm i puppeteer
```

Install the system libraries that Chrome needs. On Ubuntu, Puppeteer can install them for you. The command needs root:

```sh
sudo npx puppeteer browsers install chrome --install-deps
```

On AL2023, install them with `dnf`:

```sh
sudo dnf install -y alsa-lib at-spi2-atk at-spi2-core atk cairo cups-libs libX11 libXcomposite libXdamage libXext libXfixes libXrandr libxcb libxkbcommon mesa-libgbm pango
```

Save this script as `example.mjs`:

```js
import puppeteer from 'puppeteer';

const browser = await puppeteer.launch();
const page = await browser.newPage();
await page.goto('https://example.com', { timeout: 30000 });
console.log(await page.title());
await page.screenshot({ path: 'example.png' });
await page.pdf({ path: 'example.pdf' });
await browser.close();
```

Run it with `node example.mjs`. It prints `Example Domain` and writes `example.png` and `example.pdf`. On Ubuntu 24.04, it fails with `No usable sandbox!` until you apply one of the fixes in [Sandbox](#sandbox).

### Use an installed browser with puppeteer-core

`puppeteer-core` doesn't download a browser. Launch Google Chrome with `channel: 'chrome'`, or point `executablePath` at another browser binary.

```sh
npm i puppeteer-core
```

```js
import puppeteer from 'puppeteer-core';

const browser = await puppeteer.launch({ channel: 'chrome' });
const page = await browser.newPage();
await page.goto('https://example.com', { timeout: 30000 });
console.log(await page.title());
await page.screenshot({ path: '/tmp/example.png' });
await browser.close();
```

These launch options worked:

| Browser | Launch options |
|---|---|
| Google Chrome | `{ channel: 'chrome' }` |
| Chromium snap (Ubuntu) | `{ executablePath: '/snap/bin/chromium' }` |
| SPAL `chromium` (AL2023) | `{ executablePath: '/usr/bin/chromium-browser' }` |
| SPAL `chromium-headless` (AL2023) | `{ executablePath: '/usr/lib64/chromium-browser/headless_shell', headless: 'shell' }` |

## Playwright

Playwright downloads its own arm64 Chromium build. We tested Playwright 1.64.0.

Playwright [supports](https://playwright.dev/docs/intro#system-requirements) Ubuntu 22.04 and 24.04 and Debian 12 and 13 on arm64. There, it installs the browser and its system libraries in one step. In your project directory:

```sh
npm i playwright
npx playwright install --with-deps chromium
```

AL2023 is not an officially supported Playwright platform. `npx playwright install chromium` downloads a fallback build and prints `BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-arm64.` Install the system libraries with `dnf` instead of `--with-deps`:

```sh
npm i playwright
npx playwright install chromium
sudo dnf install -y alsa-lib at-spi2-atk at-spi2-core atk cairo cups-libs libX11 libXcomposite libXdamage libXext libXfixes libXrandr libxcb libxkbcommon mesa-libgbm pango
```

Save this script as `example.mjs` and run it with `node example.mjs`:

```js
import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('https://example.com', { timeout: 30000 });
console.log(await page.title());
await page.screenshot({ path: 'example.png' });
await browser.close();
```

To use Google Chrome instead of the bundled Chromium, install Chrome as shown above and launch it with `chromium.launch({ channel: 'chrome' })`. Don't run `npx playwright install chrome` on arm64 Linux: it fails with `ERROR: not supported on Linux Arm64`.

## Sandbox

Chrome isolates web content in a sandbox. On Linux, its primary sandbox uses unprivileged user namespaces. Google Chrome's package also includes a setuid sandbox helper, `/opt/google/chrome/chrome-sandbox`.

Results with default launch options, as a regular user:

| | Google Chrome and distribution Chromium | Chrome for Testing downloaded by Puppeteer | Playwright Chromium with `chromiumSandbox: true` |
|---|---|---|---|
| Ubuntu 22.04 | Works | Works | Works |
| Ubuntu 24.04 | Works | Fails: `No usable sandbox!` | Fails: `Chromium sandboxing failed!` |
| AL2023 | Works | Works | Works |

Ubuntu 23.10 and later [restrict unprivileged user namespaces with AppArmor](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md). Ubuntu 22.04 does not: `kernel.apparmor_restrict_unprivileged_userns` is `0` there. Ubuntu 24.04 includes an AppArmor profile for Google Chrome at `/opt/google/chrome/chrome`, and snaps get their own profile, so both keep their sandbox. A browser that Puppeteer or Playwright downloads into your home directory has no profile. On Ubuntu 24.04, use one of these:

- Use Google Chrome through `puppeteer-core` with `channel: 'chrome'` (see [Use an installed browser with puppeteer-core](#use-an-installed-browser-with-puppeteer-core)).
- If Google Chrome is installed, have Chrome for Testing use Chrome's setuid sandbox helper:

  ```sh
  export CHROME_DEVEL_SANDBOX=/opt/google/chrome/chrome-sandbox
  ```

- Add an AppArmor profile for Puppeteer's download location. Any process that can create an executable named `chrome` under this path can then bypass the restriction.

  ```sh
  sudo tee /etc/apparmor.d/chrome-for-testing <<'EOF'
  abi <abi/4.0>,
  include <tunables/global>

  profile chrome-for-testing /home/*/.cache/puppeteer/chrome/**/chrome flags=(unconfined) {
    userns,

    include if exists <local/chrome-for-testing>
  }
  EOF
  sudo apparmor_parser -r /etc/apparmor.d/chrome-for-testing
  ```

You can also launch with `--no-sandbox` (`puppeteer.launch({ args: ['--no-sandbox'] })`), but only for content you trust: the Puppeteer documentation [strongly discourages](https://pptr.dev/troubleshooting#setting-up-chrome-linux-sandbox) running without a sandbox.

Playwright launches Chromium without the sandbox unless you set [`chromiumSandbox: true`](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox). The default is `false`.

Chrome also refuses to run as root without `--no-sandbox`. Run it as a regular user, and in containers switch to a non-root user, as the Dockerfiles below do.

## Containers

The Chromium snap needs `snapd`, so container images should use Google Chrome or Debian's `chromium`. This Dockerfile installs Google Chrome on the `node:22-bookworm` (Debian 12) image. It runs the `puppeteer-core` script from [Use an installed browser with puppeteer-core](#use-an-installed-browser-with-puppeteer-core), saved as `example.mjs`, as the non-root `node` user:

```dockerfile
FROM public.ecr.aws/docker/library/node:22-bookworm
RUN curl -fsSLO https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_arm64.deb \
    && rm google-chrome-stable_current_arm64.deb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN npm install puppeteer-core
COPY example.mjs .
USER node
CMD ["node", "example.mjs"]
```

Build and run it on a Graviton instance:

```sh
docker build -t chrome-example .
docker run --rm --init --cap-add=SYS_ADMIN chrome-example
```

It prints `Example Domain`. Without `--cap-add=SYS_ADMIN`, the browser fails to launch inside the container, on both Ubuntu 22.04 and 24.04 hosts, because Chrome can't set up its sandbox (`Failed to move to new namespace ... Operation not permitted`). You have two options:

- `--cap-add=SYS_ADMIN` keeps Chrome's sandbox, at the cost of a more privileged container. Puppeteer's own image [requires it](https://pptr.dev/guides/docker).
- Launch with `args: ['--no-sandbox']`. The container needs no extra capability, but Chrome runs without its sandbox, so use this only for content you trust.

Use `--init`, or an init process as the `ENTRYPOINT`, so that the processes the browser starts are managed properly, as the [Puppeteer Docker guide](https://pptr.dev/guides/docker) recommends.

For Chromium instead of Chrome, use Debian's packages:

```dockerfile
FROM public.ecr.aws/docker/library/debian:trixie
RUN apt-get update \
    && apt-get install -y chromium chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m tester
USER tester
WORKDIR /home/tester
```

```sh
docker build -t chromium-example .
docker run --rm --init --cap-add=SYS_ADMIN chromium-example chromium --headless --dump-dom https://example.com
```

## Headful mode with Xvfb

Some tests need a headed (non-headless) browser. Xvfb provides a virtual X server.

On Ubuntu:

```sh
sudo apt-get install -y xvfb
```

On AL2023:

```sh
sudo dnf install -y xorg-x11-server-Xvfb
```

Set `headless: false` in the launch options, for example `puppeteer.launch({ channel: 'chrome', headless: false })`, and run the script under `xvfb-run`:

```sh
xvfb-run -a node example.mjs
```

## Appendix: moving from PhantomJS

[PhantomJS](https://phantomjs.org/) development is suspended until further notice. Its API differs from Puppeteer's, so PhantomJS scripts have to be rewritten. For comparison, this PhantomJS script takes a screenshot. The script in [Install Puppeteer and its browser](#install-puppeteer-and-its-browser) does the same with Puppeteer.

```js
var page = require('webpage').create();
page.open('http://www.google.com', function() {
    setTimeout(function() {
        page.render('google.png');
        phantom.exit();
    }, 200);
});
```

## References

- [Google Chrome system requirements](https://support.google.com/chrome/answer/95346)
- [Chrome for Testing: supported platforms](https://github.com/GoogleChromeLabs/chrome-for-testing#supported-platforms)
- [Puppeteer system requirements](https://pptr.dev/guides/system-requirements)
- [Puppeteer troubleshooting: Chrome Linux sandbox](https://pptr.dev/troubleshooting#setting-up-chrome-linux-sandbox)
- [Puppeteer Docker guide](https://pptr.dev/guides/docker)
- [puppeteer-core changelog](https://github.com/puppeteer/puppeteer/blob/main/packages/puppeteer-core/CHANGELOG.md) and [@puppeteer/browsers changelog](https://github.com/puppeteer/puppeteer/blob/main/packages/browsers/CHANGELOG.md)
- [Playwright system requirements](https://playwright.dev/docs/intro#system-requirements)
- [Chromium: AppArmor user namespace restrictions](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md)
- [Supplementary Packages for Amazon Linux (SPAL)](https://docs.aws.amazon.com/linux/al2023/ug/spal.html)
- [NodeSource distributions](https://github.com/nodesource/distributions)
