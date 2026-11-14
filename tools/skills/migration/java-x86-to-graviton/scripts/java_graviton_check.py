#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Graviton (Linux arm64) check of the native files a Java application carries. Needs Python 3.6 or later only.

  java_graviton_check.py [--libc glibc|musl] [--glibc VERSION] [--glibcxx VERSION] [--page-size BYTES]
                         [--target-root DIR] [--source-tree] PATH...

PATH is a JAR, WAR, EAR or other zip archive, a native file, or a folder. Folders are walked (except .git and
node_modules; with --source-tree also the build outputs target, build and .gradle) and every file is judged by its
content, never by its name. A PATH given by name that is neither an archive nor a native file is a CHECK. Archives are read in memory, with the
archives nested in them (Spring Boot BOOT-INF/lib, WAR WEB-INF/lib, EARs of WARs, shaded JARs). Nothing is extracted
or run, and nothing is written. --target-root DIR judges against the files of the target image copied into DIR: its
C library, the versions each of its glibc, libstdc++ and libgcc_s libraries defines, and its libstdc++ level.

One line per native file, worst first:
  FINDING  the target needs this file and it fails there
  CHECK    the files cannot decide; the line says what to check
  OK       a Linux aarch64 build that suits the target
  OTHER    a file the target does not load: a build for another operating system, or for another architecture or C
           library when a build that suits the target is also present
  NOTE     no verdict: several Linux builds of one library, or files aligned for 4 KB pages only
Builds of one library for several platforms are judged together. They are the files whose names match once the
architecture and C library parts are removed (libsnappyjava.so in Linux/x86_64/ and Linux/aarch64/;
libnetty_transport_native_epoll_x86_64.so and libnetty_transport_native_epoll_aarch_64.so), in folders whose
names match once the operating system, architecture and C library parts are removed.

Exit status: 0 no findings (CHECK lines may remain), 1 findings, 2 usage error.
"""
import argparse
import collections
import hashlib
import io
import os
import re
import struct
import sys
import zipfile
import zlib

MAX_DEPTH = 8  # archives nested deeper than this are reported as CHECK, not read
MAX_MEMBER = 1 << 30  # an archive member declared larger than this (1 GiB) is a CHECK, not read
MAX_HELD = 1 << 31  # the most archive data this check keeps in memory at once (2 GiB): a nested archive is read
# from its parent's bytes, so the archives that hold a member stay in memory while it is read, and a member that
# would take them past this limit is a CHECK, not read. No member is read past its declared size, and only stored
# and deflated members are read (some zipfile versions do not bound bzip2 or LZMA output while decompressing), so
# however an archive is crafted, its members take at most about 2 GiB. A file outside an archive takes no more
# memory than its size on disk.
SKIP_DIRS = (".git", "node_modules")
SOURCE_TREE_SKIP = ("target", "build", ".gradle", "graviton-validation", ".venv")  # --source-tree: build outputs
ELF_MACHINE = {2: "sparc", 3: "i386", 8: "mips", 18: "sparc32plus", 20: "ppc", 21: "ppc64", 22: "s390", 40: "arm",
               43: "sparcv9", 50: "ia64", 62: "x86-64", 183: "aarch64", 243: "riscv", 258: "loongarch"}
ELF_OSABI = {1: "HP-UX", 2: "NetBSD", 6: "Solaris", 7: "AIX", 9: "FreeBSD", 12: "OpenBSD"}
NOTE_OS = {b"FreeBSD": "FreeBSD", b"OpenBSD": "OpenBSD", b"NetBSD": "NetBSD", b"DragonFly": "DragonFly"}
GNU_ABI_OS = {1: "GNU Hurd", 2: "Solaris", 3: "FreeBSD"}  # NT_GNU_ABI_TAG; 0 is Linux
# glibc's own libraries: only GLIBC_ versions needed from these set the glibc floor (a musl build of a library
# can need GLIBC_2.0 from libgcc_s.so.1, which is not a glibc need)
GLIBC_LIBS = ("libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1", "libresolv.so.2",
              "libutil.so.1", "libanl.so.1", "libmvec.so.1", "libnsl.so.1")
MACHO_CPU = {7: "i386", 0x01000007: "x86-64", 12: "arm", 0x0100000C: "arm64", 0x0200000C: "arm64_32", 18: "ppc",
             0x01000012: "ppc64"}
PE_MACHINE = {0x14C: "x86", 0x8664: "x64", 0xAA64: "arm64", 0x1C4: "arm", 0x200: "ia64"}
# Architecture and C library parts of native file names, removed to find the builds of one library
MUSL_SELF = ("c.", "pthread.", "rt.", "m.", "dl.", "util.", "xnet.")  # "lib" + these: names musl's loader answers itself
# Names musl's loader resolves to musl's own name without "64" when no library defines them (get_lfs64 in
# ldso/dynlink.c; musl 1.2.4 and later define only the names without "64"), and readdir64_r to readdir_r
MUSL_LFS64 = frozenset(("aio_cancel aio_error aio_fsync aio_read aio_return aio_suspend aio_write alphasort creat "
                        "fallocate fgetpos fopen freopen fseeko fsetpos fstat fstatat fstatfs fstatvfs ftello "
                        "ftruncate ftw getdents getrlimit glob globfree lio_listio lockf lseek lstat mkostemp "
                        "mkostemps mkstemp mkstemps mmap nftw open openat posix_fadvise posix_fallocate pread preadv "
                        "prlimit pwrite pwritev readdir scandir sendfile setrlimit stat statfs statvfs tmpfile "
                        "truncate versionsort __fxstat __fxstatat __lxstat __xstat").split())
NAME_PARTS = re.compile(r"[-_.](x86[-_]64|x86[-_]32|x64|x86|amd64|i[3-6]86|aarch[-_]?64|arm64|arm[-_]?32|armv[5-8][a-z]*|"
                        r"armhf|armel|arm|ppc(le)?[-_]?64(le)?|ppc|s390x?|s390[-_]64|riscv[-_]?64|loongarch[-_]?64|"
                        r"mips(64)?(el)?|musl|gnu|glibc)(?=[-_.]|$)", re.I)


def vtuple(s):
    return tuple(int(x) for x in s.split("."))

# A target image's files (--target-root): the folders its loader searches, and the libraries whose files say what the
# image provides: glibc's libraries and loader (the first eleven), musl's loader, libstdc++ and libgcc_s
ROOT_DIRS = ("lib", "lib64", "usr/lib", "usr/lib64", "lib/aarch64-linux-gnu", "usr/lib/aarch64-linux-gnu")
ROOT_LIBS = ("libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1", "libresolv.so.2", "libutil.so.1",
             "libanl.so.1", "libmvec.so.1", "libnsl.so.1", "ld-linux-aarch64.so.1", "ld-musl-aarch64.so.1",
             "libstdc++.so.6", "libgcc_s.so.1")


def root_file(root, rel):
    """The file rel names in root (a target image's files), following symbolic links as the image would, an absolute
    link pointing into root; None when the image has no such file."""
    parts, done, hops = [x for x in rel.split("/") if x not in ("", ".")], [], 0
    while parts and hops < 40:
        x = parts.pop(0)
        if x == "..":
            done = done[:-1]
        elif os.path.islink(os.path.join(root, *(done + [x]))):
            link, hops = os.readlink(os.path.join(root, *(done + [x]))), hops + 1
            parts = [y for y in link.split("/") if y not in ("", ".")] + parts
            done = [] if link.startswith("/") else done
        else:
            done.append(x)
    p = os.path.join(root, *done)
    return p if not parts and os.path.isfile(p) else None


def root_defines(b):
    """(e_machine, the version names an ELF library defines through DT_VERDEF, without its own name)."""
    if len(b) < 64 or b[:4] != b"\x7fELF" or b[4] != 2 or b[5] != 1:
        return 0, []
    machine, phoff = struct.unpack_from("<H", b, 18)[0], struct.unpack_from("<Q", b, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", b, 54)
    loads, tags = [], {}
    for k in range(phnum):
        o = phoff + k * phentsize
        if o + 56 > len(b):
            break
        p_type = struct.unpack_from("<I", b, o)[0]
        p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from("<QQQQ", b, o + 8)
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == 2:
            for q in range(p_offset, min(len(b), p_offset + p_filesz) - 15, 16):
                tag, val = struct.unpack_from("<qQ", b, q)
                if tag == 0:
                    break
                tags.setdefault(tag, val)

    def off(va):
        return next((va - v + o for v, o, sz in loads if v <= va < v + sz), None)
    st, o, names = off(tags.get(5, -1)), off(tags.get(0x6FFFFFFC, -1)), []  # DT_STRTAB, DT_VERDEF
    for _ in range(tags.get(0x6FFFFFFD, 0)):  # DT_VERDEFNUM
        if o is None or st is None or o + 20 > len(b):
            break
        _v, flags, _x, cnt, _h, aux, nxt = struct.unpack_from("<HHHHIII", b, o)
        if cnt and not flags & 1 and o + aux + 8 <= len(b):  # VER_FLG_BASE (1) marks the library's own name
            n = st + struct.unpack_from("<I", b, o + aux)[0]
            names.append(b[n:b.find(b"\0", n)].decode("latin-1"))
        if not nxt:
            break
        o += nxt
    return machine, names


def elf_sections(read):
    """(sh_type, sh_offset, sh_size, sh_link) of every section of an ELF64 little-endian file, through read(off, n)."""
    h = read(0, 64)
    if len(h) < 64:
        return []
    shoff, shentsize, shnum = struct.unpack("<Q", h[40:48])[0], struct.unpack("<H", h[58:60])[0], struct.unpack("<H", h[60:62])[0]
    if not shoff or shentsize < 64 or shnum > 65535:
        return []
    sh = read(shoff, shentsize * shnum)
    out = []
    for k in range(0, len(sh) - shentsize + 1, shentsize):
        _name, sh_type, _flags, _addr, sh_offset, sh_size, sh_link = struct.unpack("<IIQQQQI", sh[k:k + 44])
        out.append((sh_type, sh_offset, sh_size, sh_link))
    return out


def dynamic_symbols(read):
    """(defined names, [(undefined name, binding, version index)]) from .dynsym and .gnu.version; ([], []) when the
    file has no section headers (a stripped loader keeps them; .dynsym is needed at run time and stays)."""
    secs = elf_sections(read)
    dynsym = next((s for s in secs if s[0] == 11), None)
    if dynsym is None or dynsym[3] >= len(secs):
        return [], []
    strtab, versym = secs[dynsym[3]], next((s for s in secs if s[0] == 0x6FFFFFFF), None)
    syms, strs = read(dynsym[1], dynsym[2]), read(strtab[1], strtab[2])
    vers = read(versym[1], versym[2]) if versym else b""
    defined, undefined = [], []
    for k in range(1, len(syms) // 24):
        st_name, st_info, _other, st_shndx = struct.unpack("<IBBH", syms[24 * k:24 * k + 8])
        end = strs.find(b"\0", st_name)
        name = strs[st_name:end if end >= 0 else len(strs)].decode("latin-1")
        if not name:
            continue
        if st_shndx:
            defined.append(name)
        else:
            v = struct.unpack("<H", vers[2 * k:2 * k + 2])[0] & 0x7FFF if 2 * k + 2 <= len(vers) else 0
            undefined.append((name, st_info >> 4, v))
    return defined, undefined


def has_dynsym(read):
    """Whether the file's section headers lead to a .dynsym, the table glibc_imports reads: without one, the file's
    imports are unknown, which is not the same as none."""
    secs = elf_sections(read)
    d = next((s for s in secs if s[0] == 11), None)
    return d is not None and d[3] < len(secs)


def glibc_imports(read, vlib, is_glibc):
    """The undefined, non-weak dynamic symbols a file takes from a glibc library (vlib: version index to library,
    from DT_VERNEED), sorted: what the target's C library must define for the file's calls to work."""
    return sorted(set(n for n, binding, v in dynamic_symbols(read)[1] if binding != 2 and is_glibc(vlib.get(v, ""))))


def read_root(root):
    """What a target image's files say: its C library, glibc release, the versions each library of ROOT_LIBS in it
    defines, whether a musl image also has a glibc loader (gcompat), its highest GLIBCXX_ version and its os-release
    name. A string saying why when root cannot be judged."""
    if not os.path.isdir(root):
        return "no such folder: %s" % root
    t = {"root": root, "libc": "", "release": "", "defs": {}, "os": "", "glibc_loader": False, "glibcxx": "", "syms": set(),
         "musl_syms": set(), "compat": "", "compat_syms": set(), "paths": {}, "files": set(), "libs": set()}
    for rel in ("etc/os-release", "usr/lib/os-release"):
        p = root_file(root, rel)
        if p:
            with open(p, errors="replace") as f:
                m = re.search(r'^PRETTY_NAME="?([^"\n]*)', f.read(), re.M)
            t["os"] = m.group(1) if m else ""
            break
    machines = set()
    for name in ROOT_LIBS:
        p = next((x for x in (root_file(root, d + "/" + name) for d in ROOT_DIRS) if x), None)
        if p:
            with open(p, "rb") as f:
                b = f.read()
            machine, t["defs"][name] = root_defines(b)
            machines.add(machine)
            defined = dynamic_symbols(lambda o, n, b=b: b[o:o + n])[0]  # what the library defines
            t["syms"].update(defined)
            t["paths"][name] = p  # the file the name leads to (gcompat links several names to one file)
            if name == "ld-musl-aarch64.so.1":  # musl's own symbols: what its loader resolves a glibc build's imports to
                t["musl_syms"] = set(defined)
            elif name == "libc.so.6":  # on a musl image, a glibc compatibility library (gcompat's)
                t["compat"], t["compat_syms"] = "/" + os.path.relpath(p, root).replace(os.sep, "/"), set(defined)
            m = re.search(rb"release version ([0-9]+\.[0-9]+)", b) if name == "libc.so.6" else None
            t["release"] = m.group(1).decode() if m else t["release"]
    lst = os.path.join(root, "gv-image-libs.txt")  # the copy-out block's list of every shared library's name in the image
    if os.path.isfile(lst):
        with open(lst, errors="replace") as f:
            t["libs"] = set(x.strip() for x in f if x.strip())
    db = root_file(root, "lib/apk/db/installed")  # Alpine: every file its packages installed (F: folder, R: name)
    if db:
        with open(db, errors="replace") as f:
            folder = ""
            for line in f:
                folder = line[2:].strip() if line.startswith("F:") else folder
                if line.startswith("R:") and folder in ROOT_DIRS:
                    t["files"].add(line[2:].strip())
    if "ld-musl-aarch64.so.1" in t["defs"]:
        t["libc"], t["glibc_loader"] = "musl", "ld-linux-aarch64.so.1" in t["defs"]
    elif "libc.so.6" in t["defs"]:
        t["libc"] = "glibc"
    else:
        return ("%s has neither glibc's libc.so.6 nor musl's ld-musl-aarch64.so.1 in %s: copy the target image's "
                "files there first" % (root, ", ".join(ROOT_DIRS)))
    if machines - {183}:
        return "the libraries in %s are not aarch64 (e_machine %s): copy them from the image for linux/arm64" % (
            root, ", ".join(str(x) for x in sorted(machines - {183})))
    cxx = [v[8:] for v in t["defs"].get("libstdc++.so.6", []) if re.match(r"^GLIBCXX_[0-9]+(\.[0-9]+)*$", v)]
    t["glibcxx"] = max(cxx, key=lambda v: tuple(int(x) for x in v.split("."))) if cxx else ""
    return t


def root_needs(vers, t):
    """Findings for the versions a glibc file needs ((library, version) pairs) that the image's copy of that library
    does not define, the check glibc's loader makes: one per library and version prefix, naming the highest one
    missing. A version needed from one of glibc's libraries that the image lacks is compared with its glibc release."""
    def num(s):
        return tuple(int(x) for x in s.split("."))
    p = []
    for lib in sorted(set(x for x, _ in vers)):
        have = t["defs"].get(lib)
        if have is None:
            v = [n[6:] for x, n in vers if x == lib and lib in ROOT_LIBS[:11] and re.match(r"^GLIBC_[0-9]+(\.[0-9]+)*$", n)]
            if v and t["release"] and num(max(v, key=num)) > num(t["release"]):
                p.append("needs GLIBC_%s from %s; the image has no %s, and its glibc is %s" % (
                    max(v, key=num), lib, lib, t["release"]))
            continue
        top = {}
        for n in sorted(set(n for x, n in vers if x == lib and n not in have)):
            m = re.match(r"^(.*?_)([0-9]+(\.[0-9]+)*)$", n)
            k = m.group(1) if m else n
            if k not in top or m and num(m.group(2)) > num(top[k][len(k):]):
                top[k] = n
        for k, n in sorted(top.items()):
            known = [d[len(k):] for d in have if k != n and d.startswith(k) and re.match(r"^[0-9]+(\.[0-9]+)*$", d[len(k):])]
            p.append("needs %s from %s; the target's %s %s" % (n, lib, lib, "defines up to %s%s" % (
                k, max(known, key=num)) if known else "does not define it"))
    return p


def root_has(t, names):
    """The names (libraries, or "interpreter <path>") that the target image's files provide; none without a root."""
    if not t:
        return []
    return [n for n in names if (root_file(t["root"], n[12:]) if n.startswith("interpreter ") else
                                 any(root_file(t["root"], d + "/" + n) for d in ROOT_DIRS))]


ROOT_OPTION = "--target-root"


EFFECT = "the load passes, and a call that reaches such a symbol stops the process"


def musl_resolve(imports, t, needed=()):
    """(missing, preload) for a glibc build's imports on a musl image t, looked up as musl's loader does for the file:
    in musl itself (ld-musl-aarch64.so.1), where a name musl lacks that ends in 64 resolves to the name without 64
    (MUSL_LFS64). missing: no library of the image defines the name. preload: only the image's glibc compatibility
    library (gcompat's libc.so.6) defines it: musl's loader answers the glibc library names itself, so that file
    reaches the build only through LD_PRELOAD, unless the build needs it by another name (needed: its DT_NEEDED)."""
    own = t["musl_syms"]
    left = [n for n in imports if n not in own and not (
        "readdir_r" in own if n == "readdir64_r" else n[-2:] == "64" and n[:-2] in MUSL_LFS64 and n[:-2] in own)]
    by_name = any(t["paths"].get(n) == t["paths"].get("libc.so.6") for n in needed
                  if n in t["paths"] and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)))
    return ([n for n in left if n not in t["syms"]],
            [] if by_name else [n for n in left if n in t["compat_syms"]])


def musl_preload(names, t):
    """The CHECK for imports that only the image's glibc compatibility file defines (musl_resolve's preload)."""
    where = t["compat"]
    return ("glibc build; the image defines %s%s only in %s, which musl's loader does not search for this file: the "
            "definitions reach it only when the process preloads that file (LD_PRELOAD=%s); without the preload, %s; "
            "settle it in the target image with the deployment's own environment" % (
                ", ".join(names[:4]), " and %d more" % (len(names) - 4) if len(names) > 4 else "", where, where, EFFECT))


def musl_unread():
    """The CHECK for a glibc build on a musl image whose dynamic symbol table could not be read."""
    return ("glibc build whose dynamic symbol table could not be read (no section headers), so its glibc imports were "
            "not resolved against the image's musl; for a symbol musl does not define, %s; settle it with musl's ldd "
            "(/lib/ld-musl-aarch64.so.1 --list FILE) in the target image, which lists each one" % EFFECT)


def musl_check(own, image, other=()):
    """The CHECK for a glibc build on a musl target when neither musl's loader nor the image refuses it. other: the
    build's other libraries, which the target image must provide (SkiaSharp 2.88.6: libfontconfig.so.1)."""
    only = "" if other else "only "
    also = "; it also needs %s, which the target image must provide" % ", ".join(other) if other else ""
    if not image:
        return ("glibc build that needs %slibraries musl's loader provides (%s)%s; settle it by resolving its glibc "
                "imports against the image's files (%s): a symbol the image does not define is a FINDING, because the "
                "load passes and a call that reaches it stops the process" % (only, ", ".join(own), also, ROOT_OPTION))
    by_loader = [n for n in own if n not in image]
    return "glibc build that needs %s%sfiles the target image has (%s)%s; settle it by resolving its glibc imports against the image's files (%s)" % (
        only, "libraries musl's loader provides (%s) and " % ", ".join(by_loader) if by_loader else "", ", ".join(image),
        also, ROOT_OPTION)


def needs_other(names, t):
    """The CHECK for a file that needs libraries other than glibc's, libstdc++ and libgcc_s which the target image does
    not have (its list of shared libraries; for a musl image, else its package list or copied files) and which the
    scanned files do not ship."""
    where = ("the target image does not have" if t["libs"] else "no package of the target image installs" if t["files"]
             else "the copied files of the target image do not include")
    return "needs %s, which %s; settle it by finding %s in the image the project deploys" % (
        ", ".join(names), where, "the library" if len(names) == 1 else "the libraries")



def libs_notes(t):
    """The NOTE for a target folder without the image's library list (gv-image-libs.txt): the other libraries the files
    need were then not checked against the whole image."""
    if not t or t["libs"] or t["libc"] == "musl" and t["files"]:
        return []
    return ["target: %s has no gv-image-libs.txt (the copy-out block's list of the image's libraries), so other libraries "
            "the files need were not checked against the whole image" % t["root"]]


def root_shared(probs, x86_vers):
    """The version of a per-library finding (probs) that the x86-64 build needs from the same library too."""
    for p in probs:
        m = re.match(r"^needs (\S+) from (\S+);", p)
        if m and (m.group(2), m.group(1)) in x86_vers:
            return m.group(1)
    return ""


def root_read_from(t):
    """The end of the target line when the target was read from an image's files."""
    return (", read from %s%s" % (t["root"], " (%s)" % t["os"] if t["os"] else "")) if t else ""


def elf_info(b):
    """What an ELF file is: architecture, operating system, C library, the highest GLIBC_ version it needs from
    glibc's own libraries, the highest GLIBCXX_ version it needs from libstdc++.so.6, the smallest PT_LOAD alignment
    (align), the largest power of two dividing every PT_LOAD p_vaddr - p_offset (voff), its DT_NEEDED names, and its
    type (shared library, executable or object file). Reads 32- and 64-bit files in either byte order."""
    i = {"arch": "", "bits": 0, "os": "Linux", "libc": "", "glibc": "", "glibcxx": "", "align": 0, "voff": 0,
         "needed": [], "type": "", "interp": "", "vers": [], "imports": [], "relr": False}
    bits, e = {1: 32, 2: 64}.get(b[4] if len(b) > 5 else 0), {1: "<", 2: ">"}.get(b[5] if len(b) > 5 else 0)
    if len(b) < 52 or not bits or not e:
        i["arch"] = "unreadable ELF header"
        return i
    i["bits"] = bits
    e_type, machine = struct.unpack_from(e + "HH", b, 16)
    arch = ELF_MACHINE.get(machine, "e_machine %d" % machine)
    if machine == 21 and e == "<":
        arch = "ppc64le"
    elif machine == 22:
        arch = "s390x" if bits == 64 else "s390"
    elif machine in (243, 258):
        arch += str(bits)
    elif machine == 8:
        arch = ("mips64" if bits == 64 else "mips") + ("el" if e == "<" else "")
    i["arch"] = arch
    i["os"] = ELF_OSABI.get(b[7], "Linux")
    if bits == 64:
        phoff = struct.unpack_from(e + "Q", b, 32)[0]
        phentsize, phnum = struct.unpack_from(e + "HH", b, 54)
    else:
        phoff = struct.unpack_from(e + "I", b, 28)[0]
        phentsize, phnum = struct.unpack_from(e + "HH", b, 42)
    loads, dyn, android = [], None, False
    for k in range(phnum):
        o = phoff + k * phentsize
        if o + (56 if bits == 64 else 32) > len(b):
            break
        if bits == 64:
            p_type = struct.unpack_from(e + "I", b, o)[0]
            p_offset, p_vaddr = struct.unpack_from(e + "QQ", b, o + 8)
            p_filesz = struct.unpack_from(e + "Q", b, o + 32)[0]
            p_align = struct.unpack_from(e + "Q", b, o + 48)[0]
        else:
            p_type, p_offset, p_vaddr = struct.unpack_from(e + "III", b, o)
            p_filesz = struct.unpack_from(e + "I", b, o + 16)[0]
            p_align = struct.unpack_from(e + "I", b, o + 28)[0]
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz, p_align))
        elif p_type == 2:
            dyn = (p_offset, p_filesz)
        elif p_type == 3:
            i["interp"] = b[p_offset:p_offset + p_filesz].split(b"\0")[0].decode("latin-1")
        elif p_type == 4:  # notes name the system: Android (bionic C library), FreeBSD, OpenBSD, NetBSD, GNU ABI tag
            pad = 8 if p_align == 8 else 4
            q, end = p_offset, min(len(b), p_offset + p_filesz)
            while q + 12 <= end:
                namesz, descsz, ntype = struct.unpack_from(e + "III", b, q)
                name = b[q + 12:q + 12 + namesz].rstrip(b"\0")
                desc = q + 12 + (namesz + pad - 1) // pad * pad
                if name == b"Android":
                    android = True
                elif name in NOTE_OS:
                    i["os"] = NOTE_OS[name]
                elif name == b"GNU" and ntype == 1 and desc + 4 <= end:
                    i["os"] = GNU_ABI_OS.get(struct.unpack_from(e + "I", b, desc)[0], i["os"])
                q = desc + (descsz + pad - 1) // pad * pad
    if loads:
        i["align"] = min(x[3] for x in loads)
        d = [v - o for v, o, _, _ in loads if v != o]
        i["voff"] = min(x & -x for x in d) if d else 0
    i["type"] = {1: "object file", 2: "executable"}.get(e_type, "executable" if i["interp"] else "shared library")
    if dyn is None:
        if e_type != 1:
            i["libc"] = "static"
        return i

    def off(va):
        for v, o, sz, _ in loads:
            if v <= va < v + sz:
                return va - v + o
        return None
    tags, needed, size = {}, [], 16 if bits == 64 else 8
    for k in range(dyn[1] // size):
        o = dyn[0] + size * k
        if o + size > len(b):
            break
        tag, val = struct.unpack_from(e + ("qQ" if bits == 64 else "iI"), b, o)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        else:
            tags.setdefault(tag, val)
    strtab = off(tags[5]) if 5 in tags else None

    def string(o):
        if strtab is None:
            return ""
        z = b.find(b"\0", strtab + o)
        return b[strtab + o:z].decode("latin-1")
    names = [string(n) for n in needed]
    i["needed"] = names
    i["soname"] = string(tags[14]) if 14 in tags else ""  # DT_SONAME: the name a library loaded by path answers to
    if tags.get(0x6FFFFFFB, 0) & 0x08000000:  # DT_FLAGS_1 with DF_1_PIE: a position-independent executable
        i["type"] = "executable"
    interp = i["interp"]
    if "libc.so.6" in names or "ld-linux" in interp or any(n in GLIBC_LIBS or n.startswith("ld-linux") for n in names):
        i["libc"] = "glibc"
    elif android or "/system/bin/linker" in interp:
        i["libc"], i["os"] = "android", "Linux"
    elif any(n == "libc.so" or n.startswith("libc.musl") for n in names) or "ld-musl" in interp:
        i["libc"] = "musl"
    elif i["os"] == "Linux":  # the C library of another system names it
        for n in names:
            if n == "libc.so.7":
                i["os"] = "FreeBSD"
            elif n == "libc.so.1":
                i["os"] = "Solaris"
            elif n == "libc.so.12":
                i["os"] = "NetBSD"
            elif re.match(r"^libc\.so\.[0-9]+\.[0-9]+$", n):
                i["os"] = "OpenBSD"
    vers, vlib = [], {}
    o = off(tags[0x6FFFFFFE]) if 0x6FFFFFFE in tags else None  # DT_VERNEED, DT_VERNEEDNUM
    for _ in range(tags.get(0x6FFFFFFF, 0)):
        if o is None or o + 16 > len(b):
            break
        _v, cnt, vn_file, aux, nxt = struct.unpack_from(e + "HHIII", b, o)
        lib = string(vn_file)
        a = o + aux
        for _ in range(cnt):
            if a + 16 > len(b):
                break
            _h, _fl, _ot, name, anext = struct.unpack_from(e + "IHHII", b, a)
            vers.append((lib, string(name)))
            vlib[_ot & 0x7FFF] = lib  # .gnu.version index of this version need
            if not anext:
                break
            a += anext
        if not nxt:
            break
        o += nxt

    i["vers"] = vers  # (library, version) pairs from DT_VERNEED, for --target-root

    def highest(prefix, libs):
        v = [n[len(prefix):] for lib, n in vers if libs(lib) and n.startswith(prefix)
             and re.match(r"^[0-9]+(\.[0-9]+)*$", n[len(prefix):])]
        return prefix + max(v, key=vtuple) if v else ""
    if i["libc"] == "glibc":
        i["glibc"] = highest("GLIBC_", lambda lib: lib in GLIBC_LIBS or lib.startswith("ld-linux"))
        is_glibc = lambda lib: lib in GLIBC_LIBS or lib.startswith("ld-linux")
        i["relr"] = any(n == "GLIBC_ABI_DT_RELR" and is_glibc(lib) for lib, n in vers)  # pack-relative relocations
        if bits == 64 and e == "<":
            i["imports"] = glibc_imports(lambda o, n: b[o:o + n], vlib, is_glibc)
            i["syms_read"] = has_dynsym(lambda o, n: b[o:o + n])
    i["glibcxx"] = highest("GLIBCXX_", lambda lib: lib == "libstdc++.so.6")  # libstdc++ versions, on musl targets too
    return i


def macho_arches(b):
    """(universal, CPU types) of a Mach-O file, or None. Java class files also start with 0xcafebabe; their version
    fields, read as an architecture count, are 45 or more."""
    m = b[:4]
    if len(b) < 8:
        return None
    if m in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        n = struct.unpack_from(">I", b, 4)[0]
        if not 0 < n < 20:
            return None
        step, cpus = 20 if m == b"\xca\xfe\xba\xbe" else 32, []
        for k in range(n):
            if 8 + k * step + 4 <= len(b):
                c = struct.unpack_from(">I", b, 8 + k * step)[0]
                cpus.append(MACHO_CPU.get(c, hex(c)))
        return (True, cpus) if cpus else None
    if m in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"):
        c = struct.unpack_from(">I", b, 4)[0]
    elif m in (b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        c = struct.unpack_from("<I", b, 4)[0]
    else:
        return None
    return (False, [MACHO_CPU.get(c, hex(c))])


def pe_arch(b):
    """Machine of a Windows PE file (DLL or EXE), or None."""
    if len(b) < 0x40 or b[:2] != b"MZ":
        return None
    o = struct.unpack_from("<I", b, 0x3C)[0]
    if o + 6 > len(b) or b[o:o + 4] != b"PE\0\0":
        return None
    m = struct.unpack_from("<H", b, o + 4)[0]
    return PE_MACHINE.get(m, hex(m))


def xcoff_bits(b):
    """32 or 64 for an AIX XCOFF object, else None."""
    if len(b) >= 20 and b[:2] in (b"\x01\xdf", b"\x01\xf7") and 0 < struct.unpack_from(">H", b, 2)[0] < 64:
        return 32 if b[:2] == b"\x01\xdf" else 64
    return None


def ar_members(b):
    """What the members of a static library (ar archive) are: ELF architectures or Mach-O."""
    kinds, o = set(), 8
    while o + 60 <= len(b):
        name = b[o:o + 16]
        try:
            size = int(b[o + 48:o + 58].decode("ascii").strip() or "0")
        except ValueError:
            break
        data = b[o + 60:o + 60 + size]
        if name.startswith(b"#1/"):  # BSD ar: the member name comes first in its data
            try:
                data = data[int(name[3:].decode("ascii").strip()):]
            except ValueError:
                pass
        if data[:4] == b"\x7fELF":
            try:
                kinds.add(elf_info(data)["arch"])
            except struct.error:
                kinds.add("unreadable ELF")
        elif macho_arches(data):
            kinds.add("Mach-O")
        o += 60 + size + (size & 1)
    return kinds


def sniff(h):
    """Kind of a file from its first 64 bytes: elf, zip, ar, macho, pe, xcoff, script (it may have a zip archive
    appended, as executable Spring Boot JARs do), or None."""
    if h[:4] == b"\x7fELF":
        return "elf"
    if h[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if h[:8] == b"!<arch>\n":
        return "ar"
    if macho_arches(h) or (h[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf") and len(h) >= 8
                           and 0 < struct.unpack_from(">I", h, 4)[0] < 20):
        return "macho"
    if h[:2] == b"MZ":
        return "pe"
    if xcoff_bits(h) or h[:8] == b"<bigaf>\n":
        return "xcoff"
    if h[:2] == b"#!":
        return "script"
    return None


def read_member(zf, info):
    """An archive member's bytes, never past the size the archive declares. From Python 3.10 on, one read makes zlib
    hold the whole output twice while it decompresses, so the member is read in parts of 1 MiB there; before 3.10, one
    read holds it once and is the faster of the two."""
    with zf.open(info) as f:
        if sys.version_info < (3, 10):
            return f.read(info.file_size)
        out = io.BytesIO()
        left = info.file_size
        while left > 0:
            b = f.read(min(left, 1 << 20))
            if not b:
                break
            out.write(b)
            left -= len(b)
        return out.getvalue()


def why(ex):
    return "%s: %s" % (type(ex).__name__, ex)


class Scan(object):
    """Every native file found, by content, in folders, files and archives (nested archives read in memory)."""

    def __init__(self, skip=SKIP_DIRS):
        self.entries = []  # native files
        self.unread = []   # (path, reason) for what could not be read
        self.archives = 0
        self.skip = skip

    def walk(self, top):
        if os.path.isdir(top):
            seen = 0
            for d, dirs, files in os.walk(top):
                dirs[:] = sorted(x for x in dirs if x not in self.skip)
                for n in sorted(files):
                    p = os.path.join(d, n)
                    if not os.path.islink(p) and os.path.isfile(p):
                        seen += 1
                        self.disk_file(p)
            if not seen:  # an empty folder is a copy or build that produced nothing, not a pass
                self.unread.append((os.path.normpath(top), "holds no files: the copy or build that should have filled it produced none"))
        else:
            self.disk_file(top, named=True)

    def disk_file(self, f, named=False):
        label = os.path.normpath(f)
        try:
            with open(f, "rb") as fh:
                kind = sniff(fh.read(64))
                if kind in ("zip", "script"):
                    if kind == "zip" or zipfile.is_zipfile(f):
                        self.archive(f, label, 1)
                    elif named:
                        self.unread.append((label, "not an archive or a native file, so nothing here to judge"))
                    return
                if kind is None:
                    if named:  # a saved error page in place of a JAR reads like a JAR with no native code
                        self.unread.append((label, "not an archive or a native file, so nothing here to judge"))
                    return
                fh.seek(0)
                data = fh.read()
        except OSError as ex:
            self.unread.append((label, "could not read this file (%s)" % why(ex)))
            return
        self.native(data, kind, label, None)

    def archive(self, src, label, depth, held=0):
        if depth > MAX_DEPTH:
            self.unread.append((label, "archive nested more than %d levels deep, not read" % MAX_DEPTH))
            return
        try:
            zf = zipfile.ZipFile(src)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError, NotImplementedError) as ex:
            self.unread.append((label, "could not read this archive (%s)" % why(ex)))
            return
        self.archives += 1
        other = {}  # compression method -> members not read
        with zf:
            for info in zf.infolist():
                if info.filename.endswith("/"):
                    continue
                path = label + "!" + info.filename
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    other[info.compress_type] = other.get(info.compress_type, 0) + 1
                    continue
                try:
                    with zf.open(info) as f:
                        kind = sniff(f.read(64))
                    if kind is None:
                        continue
                    if info.file_size > MAX_MEMBER:
                        self.unread.append((path, "archive member of %d bytes, larger than the %d MiB this check reads, "
                                            "not read" % (info.file_size, MAX_MEMBER >> 20)))
                        continue
                    if held + info.file_size > MAX_HELD:
                        self.unread.append((path, "archive member of %d bytes: with the %d bytes of the archives that "
                                            "hold it, more than the %d MiB this check keeps in memory at once, not read"
                                            % (info.file_size, held, MAX_HELD >> 20)))
                        continue
                    data = None  # the previous member's bytes go before this one is read
                    data = read_member(zf, info)
                except (RuntimeError, NotImplementedError, zipfile.BadZipFile, OSError, EOFError, zlib.error,
                        ValueError) as ex:  # RuntimeError: an encrypted member
                    self.unread.append((path, "could not read this archive member (%s)" % why(ex)))
                    continue
                if kind in ("zip", "script"):
                    if kind == "zip" or zipfile.is_zipfile(io.BytesIO(data)):
                        self.archive(io.BytesIO(data), path, depth + 1, held + len(data))
                    continue
                self.native(data, kind, path, label)
            if other:
                self.unread.append((label, "%d archive member(s) compressed with method %s, not read: only stored and "
                                    "deflated members are read" % (sum(other.values()), ", ".join(str(k) for k in sorted(other)))))

    def native(self, data, kind, path, archive):
        e = {"path": path, "archive": archive, "kind": kind, "sha": hashlib.sha256(data).hexdigest(), "info": None,
             "desc": "", "members": set()}
        if kind == "elf":
            try:
                e["info"] = elf_info(data)
            except struct.error:
                e["info"] = dict(elf_info(b""), arch="unreadable ELF header")
        elif kind == "macho":
            m = macho_arches(data)
            if not m:
                return
            e["desc"] = "Mach-O %s%s (macOS)" % ("universal " if m[0] else "", " ".join(m[1]))
        elif kind == "pe":
            a = pe_arch(data)
            if not a:
                return  # MZ but not a PE file
            e["desc"] = "PE %s (Windows)" % a
        elif kind == "xcoff":
            e["desc"] = "XCOFF %s (AIX)" % (("%d-bit" % xcoff_bits(data)) if xcoff_bits(data) else "archive")
        else:
            e["members"] = ar_members(data)
            e["desc"] = "static library: " + (", ".join(sorted(e["members"])) or "no object files")
        self.entries.append(e)


def library_name(path):
    """File name without its architecture and C library parts: the builds of one library share it."""
    n = path.rsplit("!", 1)[-1].rsplit("/", 1)[-1].lower()
    n = re.sub(r"\.so(\.[0-9]+)+$", ".so", n)
    n = re.sub(r"([-_.])linux(32|64)(?=[-_.]|$)", r"\1linux", n)  # librocksdbjni-linux64.so
    n = re.sub(r"([-_.])linux(musl|gnu)(?=[-_.]|$)", r"\1linux", n)  # sharp-linuxmusl-arm64
    prev = None
    while prev != n:
        prev, n = n, NAME_PARTS.sub("", n)
    return n


OS_PARTS = re.compile(r"[-_.](linux|darwin|macos|osx|mac|win32|win64|windows|mingw|freebsd|openbsd|netbsd|dragonfly(bsd)?|"
                      r"sunos|solaris|aix|android|ios)(?=[-_.]|$)", re.I)


def group_key(path):
    """The builds of one library share this key: its name without architecture and C library parts (library_name),
    with its soname version, in a folder (and archive) whose segments are the same once the operating system,
    architecture and C library parts are removed (com/sun/jna/linux-aarch64 and com/sun/jna/win32-x86-64 both read
    com/sun/jna; runtimes/linux-arm64/native and runtimes/linux-musl-arm64/native both read runtimes/native). Files of
    other libraries with the same base name in other folders, and other soname versions, are judged on their own."""
    out = []
    for seg in re.split(r"[/!]", path.lower())[:-1]:
        s, prev = "-" + seg, None
        while prev != s:
            prev, s = s, OS_PARTS.sub("", NAME_PARTS.sub("", s))
        s = s.strip("-_.")
        if s:
            out.append(s)
    name = path.rsplit("!", 1)[-1].rsplit("/", 1)[-1].lower()
    m = re.search(r"\.so((\.[0-9]+)+)$", name)
    return "/".join(out), library_name(path) + (m.group(1) if m else "")


def problems(i, args):
    """Why a Linux ELF file fails on the target (findings) and what only a test settles (checks): two lists."""
    if i["arch"] != "aarch64":
        return ["is %s%s" % (i["arch"], " (32-bit: a 64-bit JVM cannot load it, wrong ELF class ELFCLASS32)"
                                       if i["bits"] == 32 and i["arch"] == "arm" else "")], []
    p, c, musl = [], [], args.libc == "musl"
    if i["libc"] == "android":
        p.append("is an Android build (bionic C library; the target uses %s)" % args.libc)
    elif musl and i["libc"] == "glibc":
        own = [n for n in i["needed"] if n in GLIBC_LIBS or n.startswith("ld-linux")]
        refused = (["interpreter " + i["interp"]] if "ld-linux" in i["interp"] else []) + [
            n for n in own if not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
        image = root_has(args.root, refused)  # the image's own files (gcompat's glibc loader, for example)
        refused = [n for n in refused if n not in image]
        if refused:
            p.append("glibc build; musl's loader does not provide " + ", ".join(refused))
        else:
            known = bool(args.root and args.root["musl_syms"])  # musl's own symbols were read from the image
            missing, preload = musl_resolve(i["imports"], args.root, i["needed"]) if known else ([], [])
            if missing:  # the load passes; a call that reaches a symbol the target does not define stops the process
                p.append("glibc build; the target's musl does not define %s%s (imported from %s): the load passes, and a call that reaches it stops the process" % (", ".join(missing[:4]), " and %d more" % (len(missing) - 4) if len(missing) > 4 else "", ", ".join(own)))
            elif not known:
                c.append(musl_check(own, image, [n for n in i["needed"] if n not in own]))
            elif not i.get("syms_read"):  # no symbol table read: nothing was resolved, which is not a pass
                c.append(musl_unread())
            elif preload:
                c.append(musl_preload(preload, args.root))
            # with the image's files and every import defined by musl: OK, as on a glibc image
    elif not musl and i["libc"] == "musl":
        p.append("is a musl build (the target uses glibc)")
    if not musl and args.root and i["libc"] not in ("musl", "android"):
        p += root_needs(i["vers"], args.root)  # the versions each library of the image defines
    if args.root:  # a library the file needs from the image's own set that the image does not have (the loaders aside: the C library found names them)
        gone = [n for n in i["needed"] if n in ROOT_LIBS and not n.startswith("ld-") and n not in args.root["defs"] and not (musl and (n in GLIBC_LIBS or n.startswith("ld-linux")))]
        if gone:
            p.append("needs %s, which the image does not have" % ", ".join(gone))
    if not musl and args.glibc and i["glibc"] and vtuple(i["glibc"][6:]) > vtuple(args.glibc):
        p.append("needs %s (target glibc %s)" % (i["glibc"], args.glibc))
    if not musl and args.glibc and i["relr"] and vtuple(args.glibc) < (2, 36):
        p.append("needs GLIBC_ABI_DT_RELR (pack-relative relocations, glibc 2.36 or later; target glibc %s)" % args.glibc)
    if not musl and args.glibcxx and i["glibcxx"] and vtuple(i["glibcxx"][8:]) > vtuple(args.glibcxx):
        # glibc targets only: musl's loader does not check symbol versions, and Alpine's libstdc++ defines none
        p.append("needs %s (target libstdc++ provides up to GLIBCXX_%s)" % (i["glibcxx"], args.glibcxx))
    if args.page_size:
        # glibc 2.34 and earlier refuse a PT_LOAD whose p_align is not a multiple of the page size; glibc 2.35 and
        # later, and musl, need p_vaddr - p_offset to be one. A glibc target without --glibc gets both rules.
        rel = args.glibc or (args.root or {}).get("release")
        old = not musl and not (rel and vtuple(rel) >= (2, 35))
        new = musl or not (rel and vtuple(rel) < (2, 35))
        if old and i["align"] and i["align"] < args.page_size:
            p.append("LOAD alignment %#x is below the target page size %#x" % (i["align"], args.page_size))
        if new and i["voff"] and i["voff"] < args.page_size:
            p.append("LOAD vaddr-offset alignment %#x is below the target page size %#x" % (i["voff"], args.page_size))
    if args.root and i["libc"] in ("glibc", "musl") and not p and not (musl and i["libc"] == "glibc" and not args.root["musl_syms"]) and (
            args.root["libs"] or musl and (args.root["files"] or i["libc"] == "glibc")):
        other = [n for n in i["needed"] if n not in ROOT_LIBS and n not in GLIBC_LIBS and not n.startswith("ld-")
                 and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)) and n not in args.root["libs"]
                 and n not in args.root["files"] and n not in getattr(args, "shipped", ()) and not root_has(args.root, [n])]
        if other:  # another library it needs that the image does not have and the scanned files do not ship
            c.append(needs_other(other, args.root))
    return p, c


def describe(i):
    parts = ["ELF %s %s" % (i["arch"], i["type"] or "file")]
    if i["os"] != "Linux":
        parts.append("for " + i["os"])
    parts += [x for x in (i["libc"], i["glibc"], i["glibcxx"]) if x]
    if i["align"]:
        parts.append("align %#x" % i["align"])
    if i["arch"] == "aarch64" and 0 < i["voff"] < 0x10000:
        parts.append("vaddr-offset align %#x" % i["voff"])
    if i["arch"] == "aarch64" and i["needed"]:
        parts.append("needs " + " ".join(i["needed"]))
    return ", ".join(parts)


def libc_fits(i, args):
    return i["libc"] in (args.libc, "static", "")


def rep(group):
    """The build that carries the finding of a library with no aarch64 build: its x86-64 build, else its first."""
    return ([x for x in group if x["info"]["arch"] == "x86-64"] or group)[0]


def x86_refused(xi, t):
    """What an x86-64 glibc build needs that musl's loader does not answer itself and the image (t) lacks. The image's
    glibc loader (gcompat) stands in for the x86-64 one, which the image's x86-64 variant would carry instead."""
    names = (["interpreter " + xi["interp"]] if "ld-linux" in xi["interp"] else []) + [
        n for n in xi["needed"] if (n in GLIBC_LIBS or n.startswith("ld-linux"))
        and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
    image = root_has(t, [n for n in names if "ld-linux" not in n])
    return [n for n in names if n not in image and not ("ld-linux" in n and t and t["glibc_loader"])]


def baseline(e, group, args):
    """Text for an aarch64 finding that the x86-64 build of the same library has too (not a Graviton change)."""
    i = e["info"]
    for x in group:
        xi = x["info"]
        if xi["arch"] != "x86-64" or xi["libc"] != i["libc"]:
            continue
        shared = root_shared(e["probs"], xi["vers"])
        # x86-64 hosts with this OS load an x86-64 build for musl when the library has one: no note then
        need = x86_refused(xi, args.root) if any(p.startswith("glibc build; musl") for p in e["probs"]) and not any(
            y["info"]["libc"] == "musl" for y in group if y["info"]["arch"] == "x86-64") else []
        if shared or need:
            return ("; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well "
                    "(not a Graviton change)" % (x["path"], shared or ", ".join(need)))
        syms = [n for n in xi.get("imports", []) if n in musl_resolve(i.get("imports", []), args.root)[0]] if (
            args.root and args.root.get("musl_syms") and any(p.startswith("glibc build; the target's musl does not define") for p in e["probs"]) and not any(
                y["info"]["libc"] == "musl" for y in group if y["info"]["arch"] == "x86-64")) else []
        if syms:  # the same missing symbol in the x86-64 build: x86-64 hosts with this image are exposed too
            return ("; the x86-64 build %s imports %s too, so a call that reaches it stops x86-64 hosts with this OS "
                    "as well (not a Graviton change)" % (x["path"], ", ".join(syms[:4])))
        for key, pre, tgt in (("glibc", 6, args.glibc), ("glibcxx", 8, args.glibcxx)):
            if (any(p.startswith("needs " + i[key] + " ") for p in e["probs"]) and tgt and i[key] and xi[key]
                    and vtuple(xi[key][pre:]) > vtuple(tgt)):
                return ("; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well "
                        "(not a Graviton change)" % (x["path"], xi[key]))
    return ""


def judge(scan, args):
    """(label, path, text, sha) for every native file and every file that could not be read, plus the NOTE lines."""
    out = [("CHECK", p, t, None) for p, t in scan.unread]
    args.shipped = set(e["path"].rsplit("!", 1)[-1].rsplit("/", 1)[-1] for e in scan.entries if e["kind"] == "elf" and e["info"]["arch"] == "aarch64" and e["info"]["os"] == "Linux")  # the aarch64 libraries the scanned files ship
    args.shipped |= set(e["info"].get("soname") for e in scan.entries if e["kind"] == "elf" and e["info"]["arch"] == "aarch64" and e["info"]["os"] == "Linux" and e["info"].get("soname"))  # and their SONAMEs
    linux, groups, notes = [], collections.OrderedDict(), []
    for e in scan.entries:
        i = e["info"]
        if e["kind"] != "elf":
            if e["kind"] == "ar" and "aarch64" not in e["members"] and e["members"] - {"Mach-O"}:
                out.append(("CHECK", e["path"], "static library with no aarch64 code (%s); a native arm64 build that "
                            "links it fails" % ", ".join(sorted(e["members"] - {"Mach-O"})), e["sha"]))
            else:
                out.append(("OTHER", e["path"], e["desc"] + ("; the JVM does not load static libraries" if e["kind"] == "ar"
                                                              else "; another operating system's file, not loaded on Linux"),
                            e["sha"]))
        elif i["os"] != "Linux":
            out.append(("OTHER", e["path"], describe(i) + "; another operating system's file, not loaded on Linux",
                        e["sha"]))
        elif i["type"] == "object file":
            if i["arch"] == "aarch64":
                out.append(("OTHER", e["path"], describe(i) + "; the JVM does not load object files", e["sha"]))
            else:
                out.append(("CHECK", e["path"], "object file with no aarch64 code (%s); a native arm64 build that links "
                            "it fails" % i["arch"], e["sha"]))
        else:
            e["probs"], e["checks"] = problems(i, args)
            linux.append(e)
            groups.setdefault(group_key(e["path"]), []).append(e)  # one run is one classpath
    for lib, g in groups.items():
        ok = [x for x in g if not x["probs"]]
        if ok:  # the build for the target (no CHECK and its C library first) is judged; the other builds get no flag
            pick = sorted(ok, key=lambda x: (bool(x["checks"]), not libc_fits(x["info"], args)))[0]
            for e in g:
                e["replaced"] = e is not pick  # another build of the library is the one for the target
                if e["sha"] == pick["sha"]:  # the build for the target, or a copy of it
                    out.append(("CHECK", e["path"], "; ".join(pick["checks"]), e["sha"]) if pick["checks"] else
                               ("OK", e["path"], describe(pick["info"]), e["sha"]))
                else:
                    out.append(("OTHER", e["path"], "%s; another build of this library: %s is the build for this "
                                "target" % (describe(e["info"]), pick["path"]), e["sha"]))
            builds = len(set(x["sha"] for x in g))  # copies of one file are one build
            if builds > 1:
                notes.append("%s: %d Linux builds in the scanned files; %s is the build for this target; confirm in "
                             "Phase 3 that it is the one loaded" % (library_name(pick["path"]), builds, pick["path"]))
            continue
        arm = [x for x in g if x["info"]["arch"] == "aarch64"]
        # No build suits the target. The finding goes on the build the target would load: one for its C library,
        # else a Linux (glibc or musl) build, else an Android build, else (no aarch64 build) its x86-64 build
        primary = [x for x in arm if libc_fits(x["info"], args)] or [x for x in arm if x["info"]["libc"] != "android"] \
            or arm or [rep(g)]
        for e in g:
            e["replaced"] = e not in primary
            if e in primary:
                text = "; ".join(e["probs"]) + baseline(e, g, args)
                if not arm:
                    text += "; no aarch64 Linux build of this library in the scanned files"
                out.append(("FINDING", e["path"], text, e["sha"]))
                if e["checks"]:
                    out.append(("CHECK", e["path"], "; ".join(e["checks"]), e["sha"]))
            else:
                out.append(("OTHER", e["path"], "%s; %s: see the line for %s" % (
                    describe(e["info"]), "another build of this library" if arm else "no aarch64 build of this library",
                    primary[0]["path"]), e["sha"]))
    return out, linux, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("paths", nargs="+", metavar="PATH")
    ap.add_argument("--libc", choices=("glibc", "musl"), help="the target's C library (default glibc)")
    ap.add_argument("--glibc", help="the target's glibc version, for example 2.34; natives needing a newer GLIBC_ "
                    "version are findings")
    ap.add_argument("--glibcxx", help="highest GLIBCXX_ version of the target's libstdc++, for example 3.4.33 "
                    "(glibc targets)")
    ap.add_argument("--page-size", type=int, help="the target kernel's page size in bytes, for example 65536")
    ap.add_argument("--target-root", metavar="DIR", help="the target image's files: its C library, the versions its "
                    "libraries define and its libstdc++ level are read from there, in place of --libc, --glibc and "
                    "--glibcxx")
    ap.add_argument("--source-tree", action="store_true", help="the repository's own files: skip the build outputs "
                    "target, build and .gradle (scan those per deployable)")
    args = ap.parse_args()
    args.root = None
    if args.target_root == "":  # an empty value (an unset variable) would judge the files with no target
        print("ERROR: --target-root names no folder: give the folder the target image's files were copied to")
        return 2
    if args.target_root:
        if args.libc or args.glibc or args.glibcxx:
            print("ERROR: --target-root reads the C library and its versions from the image's files; leave out "
                  "--libc, --glibc and --glibcxx")
            return 2
        args.root = read_root(args.target_root)
        if not isinstance(args.root, dict):
            print("ERROR: " + args.root)
            return 2
        args.libc = args.root["libc"]
    assumed = not args.libc
    args.libc = args.libc or "glibc"
    args.glibcxx = (args.glibcxx or "").replace("GLIBCXX_", "")
    for name, v in (("--glibc", args.glibc), ("--glibcxx", args.glibcxx)):
        if v and not re.match(r"^[0-9]+(\.[0-9]+)+$", v):
            print("ERROR: %s takes a version such as 2.34 or 3.4.33, not %s" % (name, v))
            return 2
    if args.page_size is not None and args.page_size < 1024:
        print("ERROR: --page-size takes a size in bytes, such as 4096 or 65536")
        return 2
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        print("ERROR: no such file or folder: " + ", ".join(missing))
        return 2
    rel = args.glibc or (args.root["release"] if args.root else "")
    cxx = args.glibcxx or (args.root["glibcxx"] if args.root else "")
    line = "target: " + args.libc + (" (assumed)" if assumed else "")
    if args.root and args.root["glibc_loader"]:
        line += ", with a glibc loader"
    if args.libc == "glibc":
        line += (" " + rel) if rel else (", glibc release not read" if args.root else ", glibc version not given")
    line += (", page size %d" % args.page_size) if args.page_size else ", page size not given"
    print(line + (", libstdc++ GLIBCXX_" + cxx if cxx and args.libc == "glibc" else "") + root_read_from(args.root))
    scan = Scan(SKIP_DIRS + SOURCE_TREE_SKIP if args.source_tree else SKIP_DIRS)
    for p in args.paths:
        scan.walk(p)
    out, linux, notes = judge(scan, args)
    notes.extend(libs_notes(args.root))
    merged, seen = [], {}
    for label, path, text, sha in out:
        k = (sha, label) if sha else None
        if k in seen:
            seen[k][1].append(path)
            continue
        row = [label, [path], text]
        merged.append(row)
        if k:
            seen[k] = row
    order = {"FINDING": 0, "CHECK": 1, "OK": 2, "OTHER": 3}
    for label, paths, text in sorted(merged, key=lambda r: (order[r[0]], r[1][0])):
        more = ""
        if len(paths) > 1:
            more = " (the same file is also at %s%s)" % (paths[1], (" and %d more" % (len(paths) - 2)) if len(paths) > 2 else "")
        print("%s %s: %s%s" % (label, paths[0], text, more))
    def count(lab):
        return sum(1 for r in merged if r[0] == lab)
    small = sorted(set(e["path"] for e in linux if e["info"]["arch"] == "aarch64" and not e.get("replaced")
                       and (0 < e["info"]["align"] < 0x10000 or 0 < e["info"]["voff"] < 0x10000)))
    if small and not args.page_size:
        notes.insert(0, "%d aarch64 file(s) aligned for 4 KB pages only (%s%s): a kernel with 64 KB pages refuses them; "
                        "give the page size if the target uses 64 KB pages" % (
                            len(small), ", ".join(small[:5]), " and %d more" % (len(small) - 5) if len(small) > 5 else ""))
    for n in notes:
        print("NOTE " + n)
    other_os = sum(1 for e in scan.entries if e["kind"] != "elf" or e["info"]["os"] != "Linux"
                   or e["info"]["type"] == "object file")
    print("scanned: %d archive(s); native files: %d Linux aarch64, %d other Linux builds, %d for other systems, "
          "static libraries or object files; %d identical copies merged" % (
              scan.archives, sum(1 for e in linux if e["info"]["arch"] == "aarch64"),
              sum(1 for e in linux if e["info"]["arch"] != "aarch64"), other_os, len(out) - len(merged)))
    print("findings: %d, checks: %d" % (count("FINDING"), count("CHECK")))
    return 1 if count("FINDING") else 0


if __name__ == "__main__":
    sys.exit(main())
