# PHP on Graviton

PHP is a general-purpose scripting language geared towards web development.
PHP scripts are executed by an interpreter implemented as a plug-in module
in web servers, a separate daemon (php-fpm) or a CGI executable (php-cgi).

PHP 7.4 and later are tested to perform well on Graviton. It works out of
the box on Ubuntu 22.04 and AL2023, but requires extra steps on AL2.

### OPcache on Amazon Linux 2 (AL2)

OPcache improves PHP performance by storing precompiled script bytecode in shared memory, thereby removing
the need for PHP to load and parse scripts on each request. Installing it can significantly improve
execution time on most workloads. More information about OPcache available in the
[PHP Manual](https://www.php.net/manual/en/book.opcache.php).

OPcache is installed by default on Amazon Linux 2023 (AL2023) and later, but not yet available in Amazon Linux 2 (AL2).
See [PHP OPcache Installation on AL2](php-opcache-al2.md) for manual build and install instructions.
