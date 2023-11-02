# PHP OPcache Installation on Amazon Linux 2 (AL2)

### Install PHP

First run `sudo amazon-linux-extras install -y php8.0` to install PHP 8 from AL2 extras, if not already installed.

### Sanity Check

Verify that OPcache is not already present after installation; stop here if so.

Run the following commands to see if "opcache.so" is present and enabled in php.ini.
`php --version` prints a "with Zend OPcache" line on successful load.

```
$ file /usr/lib64/php/modules/opcache.so
/usr/lib64/php/modules/opcache.so: ELF 64-bit LSB shared object      <-- already installed

$ php --version
PHP 8.0.30 (cli) (built: Aug 24 2023 20:32:36) ( NTS )
Copyright (c) The PHP Group
Zend Engine v4.0.30, Copyright (c) Zend Technologies
    with Zend OPcache v8.0.30, Copyright (c), by Zend Technologies   <-- already enabled
```

### Install Dependencies

Install PHP dependencies required to build OPcache. This is ideally done by running `sudo yum-builddep php`,
which fails in some configurations due to packaging conflict requiring both `libzip010-compat-devel` and `libzip-devel`.
Run the following as a workaround:

```
sudo yum install apr apr-devel apr-util apr-util-bdb apr-util-devel aspell aspell-devel autoconf automake bzip2-devel cpp cyrus-sasl cyrus-sasl-devel elfutils-devel elfutils-libelf-devel enchant enchant-devel expat-devel freetype-devel gcc gcc-c++ gdbm-devel generic-logos-httpd glib2-devel gmp-devel httpd httpd-devel httpd-filesystem httpd-tools libacl-devel libatomic libattr-devel libcurl-devel libdb-devel libedit-devel libgcrypt-devel libgpg-error-devel libICE libicu-devel libitm libjpeg-turbo-devel libmpc libpng-devel libsanitizer libSM libsodium libsodium-devel libtool libtool-ltdl libtool-ltdl-devel libwebp-devel libX11 libX11-common libX11-devel libXau libXau-devel libxcb libxcb-devel libXext libxml2-devel libXpm libXpm-devel libxslt libxslt-devel libXt libzip-devel lm_sensors-devel m4 mailcap mod_http2 mpfr ncurses-c++-libs ncurses-devel net-snmp net-snmp-agent-libs net-snmp-devel net-snmp-libs oniguruma oniguruma-devel openldap-devel pam-devel perl-devel perl-ExtUtils-Install perl-ExtUtils-MakeMaker perl-ExtUtils-Manifest perl-ExtUtils-ParseXS perl-Test-Harness popt-devel postgresql postgresql-devel pyparsing recode recode-devel rpm-devel sqlite-devel systemd-devel systemtap-sdt-devel t1lib t1lib-devel tcp_wrappers-devel tokyocabinet tokyocabinet-devel unixODBC unixODBC-devel xorg-x11-proto-devel xz-devel
```

### Build Source RPM

```
cd ~
yumdownloader --source php
rpm -ivh ./php-8.0.30-1.amzn2.src.rpm
sudo yum-builddep php
cd ./rpmbuild/SPECS
rpmbuild -ba php.spec
```

### Install OPcache

```
cd ~/rpmbuild/BUILD
sudo cp ./php-8.0.30/build-cgi/modules/opcache.so /usr/lib64/php/modules/opcache.so
sudo cp ./php-8.0.30/10-opcache.ini /etc/php.d/10-opcache.ini
```

Verify installation by running `php --version`. Output show now look similar to above examples.
Reboot your instance or restart php-fpm and your http server to use OPcache.
