#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Graviton (Linux arm64) checks for .NET projects. Needs Python 3.6+ and, except for scan, the .NET SDK.

  assets [DIR]            Restore a scratch copy of DIR for the source and target runtime identifiers (RIDs)
                          and report, per NuGet package, the native files selected for each target RID,
                          judged by their content (ELF header), plus ELF files packages carry outside runtimes/.
                          --tree FILE also writes every resolved package with its shortest reference chain.
  scan DIR                Report the files of a build or publish output (or an extracted image) by content.
                          --source-tree skips .git, .vs, bin, obj, node_modules and graviton-validation.
  probe ID VERSION        Run the assets report on one package version in a scratch project.
  config PACKAGES_CONFIG  Probe every package listed in a packages.config file (.NET Framework projects).

The repository is never modified: restores run in a temporary copy. FINDING lines are files the target cannot use;
CHECK lines need a test or a decision the files cannot give (a glibc build that may load on musl, a static library
or object file with no aarch64 code, x86-only files outside runtimes/ that fail only if something runs them); NOTE
lines need no change on their own (which of several builds the target loads, files aligned for 4 KB pages only when
no page size is given, NuGet audit warnings NU1901 to NU1904 from the restores). Without --target-rid the target is
linux-arm64 (glibc), and the first line of each report says so. --target-root DIR judges against the files of the
target image copied into DIR (C library, the versions its glibc, libstdc++ and libgcc_s libraries define, libstdc++
level); the target RID then follows the image's C library.
Exit status: 0 no findings (CHECK lines may remain), 1 findings, 2 usage or restore error.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
# packages.config is the only XML this program reads; packages_config_entries() refuses DTDs and entities before parsing
import xml.parsers.expat as expat  # nosemgrep: python.lang.security.use-defused-xml

ELF_ARCH = {3: "i386", 40: "arm", 62: "x86-64", 183: "aarch64", 243: "riscv"}
OS_ABI = {1: "HP-UX", 2: "NetBSD", 6: "Solaris", 7: "AIX", 9: "FreeBSD", 12: "OpenBSD"}  # EI_OSABI of other systems
PE_ARCH = {0x14C: "x86", 0x8664: "x64", 0xAA64: "arm64", 0x1C4: "arm"}
R2R_LINUX = 0x7B79  # ReadyToRun images for Linux store the machine XOR this value
AUDIT_SEEN = set()  # NuGet audit warnings (NU1901 to NU1904) already printed
MACHO = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
# glibc's own libraries: only GLIBC_ versions needed from these set the glibc floor
GLIBC_LIBS = re.compile(r"^(libc\.so\.6|libm\.so\.6|libpthread\.so\.0|libdl\.so\.2|librt\.so\.1|libresolv\.so\.2|"
                        r"libutil\.so\.1|libanl\.so\.1|libmvec\.so\.1|libnsl\.so\.1|ld-linux[-a-z0-9_.]*\.so\.[0-9]+)$")
MUSL_SELF = ("c.", "pthread.", "rt.", "m.", "dl.", "util.", "xnet.")  # "lib" + these: names musl's loader answers itself
# Names musl's loader resolves to musl's own name without "64" when no library defines them (get_lfs64 in
# ldso/dynlink.c; musl 1.2.4 and later define only the names without "64"), and readdir64_r to readdir_r
MUSL_LFS64 = frozenset(("aio_cancel aio_error aio_fsync aio_read aio_return aio_suspend aio_write alphasort creat "
                        "fallocate fgetpos fopen freopen fseeko fsetpos fstat fstatat fstatfs fstatvfs ftello "
                        "ftruncate ftw getdents getrlimit glob globfree lio_listio lockf lseek lstat mkostemp "
                        "mkostemps mkstemp mkstemps mmap nftw open openat posix_fadvise posix_fallocate pread preadv "
                        "prlimit pwrite pwritev readdir scandir sendfile setrlimit stat statfs statvfs tmpfile "
                        "truncate versionsort __fxstat __fxstatat __lxstat __xstat").split())
# Architecture and C library parts of file names, removed to find the builds of one library
NAME_PARTS = re.compile(r"[-_.](x86[-_]64|x86[-_]32|x64|x86|amd64|i[3-6]86|aarch[-_]?64|arm64|arm[-_]?32|armv[5-8][a-z]*|"
                        r"armhf|armel|arm|ppc(le)?[-_]?64(le)?|ppc|s390x?|s390[-_]64|riscv[-_]?64|loongarch[-_]?64|"
                        r"mips(64)?(el)?|musl|gnu|glibc)(?=[-_.]|$)", re.I)
# Portable RID graph of the .NET 8 and 10 SDKs (PortableRuntimeIdentifierGraph.json).
RID_CHAIN = {
    "linux-arm64": ["linux-arm64", "linux", "unix-arm64", "unix", "any"],
    "linux-musl-arm64": ["linux-musl-arm64", "linux-musl", "linux-arm64", "linux", "unix-arm64", "unix", "any"],
    "linux-x64": ["linux-x64", "linux", "unix-x64", "unix", "any"],
    "linux-musl-x64": ["linux-musl-x64", "linux-musl", "linux-x64", "linux", "unix-x64", "unix", "any"],
}
FINDINGS = []
CHECKS = []


def finding(text):
    FINDINGS.append(text)
    print("FINDING " + text)


def check(text):
    CHECKS.append(text)
    print("CHECK " + text)


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
    """Architecture, libc, highest GLIBC_ and GLIBCXX_ versions needed, smallest PT_LOAD alignment, alignment of
    p_vaddr - p_offset over the PT_LOAD segments (voff), and the libraries the file needs (DT_NEEDED)."""
    if len(b) < 20:
        return {"arch": "truncated", "libc": "", "glibc": "", "glibcxx": "", "align": 0, "voff": 0, "needed": [],
                "etype": 0, "interp": "", "bits": 0, "vers": [], "imports": [], "relr": False}
    etype, machine = struct.unpack_from(">HH" if b[5] == 2 else "<HH", b, 16)
    i = {"arch": ELF_ARCH.get(machine, "e_machine %d" % machine), "libc": "", "glibc": "", "glibcxx": "", "align": 0,
         "voff": 0, "needed": [], "etype": etype, "interp": "", "bits": 32 if b[4] == 1 else 64,
         "os": OS_ABI.get(b[7], "Linux"), "vers": [], "imports": [], "relr": False}
    if len(b) < 64 or b[4] != 2 or b[5] != 1 or etype == 1:
        return i  # only 64-bit little-endian files that a loader reads are parsed further
    phoff = struct.unpack_from("<Q", b, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", b, 54)
    loads, dyn, android = [], None, False
    for k in range(phnum):
        o = phoff + k * phentsize
        if o + 56 > len(b):
            break
        p_type = struct.unpack_from("<I", b, o)[0]
        p_offset, p_vaddr = struct.unpack_from("<QQ", b, o + 8)
        p_filesz = struct.unpack_from("<Q", b, o + 32)[0]
        p_align = struct.unpack_from("<Q", b, o + 48)[0]
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz, p_align))
        elif p_type == 2:
            dyn = (p_offset, p_filesz)
        elif p_type == 3:
            i["interp"] = b[p_offset:p_offset + p_filesz].split(b"\0")[0].decode("latin-1")
        elif p_type == 4:  # notes: one owned by "Android" marks a build for Android's C library (bionic)
            q = p_offset
            while q + 12 <= min(len(b), p_offset + p_filesz):
                namesz, descsz = struct.unpack_from("<II", b, q)
                android = android or b[q + 12:q + 12 + namesz].rstrip(b"\0") == b"Android"
                q += 12 + (namesz + 3) // 4 * 4 + (descsz + 3) // 4 * 4
    if loads:
        i["align"] = min(x[3] for x in loads)
        d = [v - o for v, o, _, _ in loads if v != o]
        i["voff"] = min(x & -x for x in d) if d else 0  # largest power of two dividing every p_vaddr - p_offset
    if dyn is None:
        i["libc"] = "static" if not i["interp"] else ("glibc" if "ld-linux" in i["interp"] else
                                                      "musl" if "ld-musl" in i["interp"] else "")
        return i

    def off(va):
        for v, o, sz, _ in loads:
            if v <= va < v + sz:
                return va - v + o
        return None
    tags, needed = {}, []
    for k in range(dyn[1] // 16):
        if dyn[0] + 16 * k + 16 > len(b):
            break
        tag, val = struct.unpack_from("<qQ", b, dyn[0] + 16 * k)
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
        e = b.find(b"\0", strtab + o)
        return b[strtab + o:e].decode("latin-1")
    names = [string(n) for n in needed]
    i["needed"] = names
    i["soname"] = string(tags[14]) if 14 in tags else ""  # DT_SONAME: the name a library loaded by path answers to
    for n in names:  # the C library of another system
        if i["os"] == "Linux" and n in ("libc.so.7", "libc.so.12", "libc.so.1") or re.match(r"^libc\.so\.[0-9]+\.[0-9]+$", n):
            i["os"] = {"libc.so.7": "FreeBSD", "libc.so.12": "NetBSD", "libc.so.1": "Solaris"}.get(n, "OpenBSD")
    if "libc.so" in names or i["interp"].startswith("/system/"):
        i["libc"] = "android" if android or i["interp"].startswith("/system/") else "musl"
    elif any(n.startswith("libc.musl") for n in names) or "ld-musl" in i["interp"]:
        i["libc"] = "musl"
    elif any(GLIBC_LIBS.match(n) for n in names) or "ld-linux" in i["interp"]:
        i["libc"] = "glibc"
    elif not names:
        i["libc"] = "static"
    vers, vlib = [], {}
    o = off(tags[0x6FFFFFFE]) if 0x6FFFFFFE in tags else None
    for _ in range(tags.get(0x6FFFFFFF, 0)):
        if o is None or o + 16 > len(b):
            break
        _v, cnt, vn_file, aux, nxt = struct.unpack_from("<HHIII", b, o)
        lib = string(vn_file)
        a = o + aux
        for _ in range(cnt):
            if a + 16 > len(b):
                break
            _h, _fl, _ot, name, anext = struct.unpack_from("<IHHII", b, a)
            vers.append((lib, string(name)))
            vlib[_ot & 0x7FFF] = lib  # .gnu.version index of this version need
            if not anext:
                break
            a += anext
        if not nxt:
            break
        o += nxt

    i["vers"] = vers  # (library, version) pairs from DT_VERNEED, for --target-root

    def highest(prefix, ok):
        v = [n[len(prefix):] for lib, n in vers if ok(lib) and n.startswith(prefix)
             and re.match(r"^[0-9]+(\.[0-9]+)*$", n[len(prefix):])]
        return prefix + max(v, key=vtuple) if v else ""
    if i["libc"] not in ("musl", "android"):  # only versions needed from glibc's own libraries (not libgcc_s) count
        i["glibc"] = highest("GLIBC_", GLIBC_LIBS.match)
        i["relr"] = any(n == "GLIBC_ABI_DT_RELR" and GLIBC_LIBS.match(lib) for lib, n in vers)  # pack-relative relocations
        i["imports"] = glibc_imports(lambda o, n: b[o:o + n], vlib, GLIBC_LIBS.match)
        i["syms_read"] = has_dynsym(lambda o, n: b[o:o + n])
    i["glibcxx"] = highest("GLIBCXX_", lambda lib: lib.startswith("libstdc++"))
    return i


def ar_arches(b):
    """ELF machines of the object files in a static library (ar archive)."""
    arches, o = set(), 8
    while o + 60 <= len(b):
        try:
            size = int(b[o + 48:o + 58].decode("ascii").strip() or "0")
        except ValueError:
            break
        data = b[o + 60:o + 60 + size]
        if data[:4] == b"\x7fELF" and len(data) >= 20:
            m = struct.unpack_from("<H", data, 18)[0]
            arches.add(ELF_ARCH.get(m, "e_machine %d" % m))
        o += 60 + size + (size & 1)
    return arches


def pe_kind(b):
    """'managed AnyCPU', 'managed x64', 'managed ReadyToRun linux-arm64', 'native PE x64', or None."""
    if len(b) < 0x40 or b[:2] != b"MZ":
        return None
    o = struct.unpack_from("<I", b, 0x3C)[0]
    if o + 24 > len(b) or b[o:o + 4] != b"PE\0\0":
        return None
    machine, nsec = struct.unpack_from("<HH", b, o + 4)
    optsz = struct.unpack_from("<H", b, o + 20)[0]
    opt = o + 24
    dd = opt + (96 if struct.unpack_from("<H", b, opt)[0] == 0x10B else 112)
    clr = struct.unpack_from("<I", b, dd + 14 * 8)[0] if dd + 120 <= len(b) else 0
    arch, target = PE_ARCH.get(machine), "windows"
    if arch is None and machine ^ R2R_LINUX in PE_ARCH:
        arch, target = PE_ARCH[machine ^ R2R_LINUX], "linux"
    if not clr:
        return "native PE " + (arch or hex(machine))
    c = None
    for k in range(nsec):
        vs, va, rs, rp = struct.unpack_from("<IIII", b, opt + optsz + 40 * k + 8)
        if va <= clr < va + max(vs, rs):
            c = clr - va + rp
    if c is None or c + 68 > len(b):
        return "managed (unreadable header)"
    flags = struct.unpack_from("<I", b, c + 16)[0]
    if struct.unpack_from("<I", b, c + 64)[0]:
        return "managed ReadyToRun %s-%s" % (target, arch or hex(machine))
    if machine == 0x14C:  # 0x2 32BITREQUIRED; with 0x20000 32BITPREFERRED it is AnyCPU (prefer 32-bit)
        return "managed x86" if flags & 0x2 and not flags & 0x20000 else "managed AnyCPU"
    return "managed " + (arch or hex(machine))


def head(path, n=64):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def read_all(path):
    with open(path, "rb") as f:
        return f.read()


def elf_problems(i, args, target):
    """Problems (findings) and checks of an ELF file for one target RID: two lists, empty when it suits the target."""
    if i["arch"] != "aarch64":
        return ["is %s" % i["arch"]], []
    p, c = [], []
    musl = "musl" in target
    if i["libc"] == "android":
        p.append("is an Android build (bionic C library; target uses %s)" % ("musl" if musl else "glibc"))
    if musl and i["libc"] == "glibc":
        own = [n for n in i["needed"] if GLIBC_LIBS.match(n)]
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
    if not musl and i["libc"] == "musl":
        p.append("is a musl build (target uses glibc)")
    if not musl and args.root and i["libc"] not in ("musl", "android"):
        p += root_needs(i["vers"], args.root)  # the versions each library of the image defines
    if args.root:  # a library the file needs from the image's own set that the image does not have (the loaders aside: the C library found names them)
        gone = [n for n in i["needed"] if n in ROOT_LIBS and not n.startswith("ld-") and n not in args.root["defs"] and not (musl and GLIBC_LIBS.match(n))]
        if gone:
            p.append("needs %s, which the image does not have" % ", ".join(gone))
    if not musl and args.glibc and i["glibc"] and vtuple(i["glibc"][6:]) > vtuple(args.glibc):
        p.append("needs %s (target glibc %s)" % (i["glibc"], args.glibc))
    if not musl and args.glibc and i["relr"] and vtuple(args.glibc) < (2, 36):
        p.append("needs GLIBC_ABI_DT_RELR (pack-relative relocations, glibc 2.36 or later; target glibc %s)" % args.glibc)
    if not musl and args.glibcxx and i["glibcxx"] and vtuple(i["glibcxx"][8:]) > vtuple(args.glibcxx):
        # glibc targets only: musl's loader does not check version needs, and Alpine's libstdc++ defines no versions
        p.append("needs %s (target libstdc++ provides up to GLIBCXX_%s)" % (i["glibcxx"], args.glibcxx))
    if args.page_size:
        # glibc 2.34 and earlier refuse a PT_LOAD whose p_align is not a multiple of the page size; glibc 2.35 and
        # later, and musl, need p_vaddr - p_offset to be one. A glibc target without --glibc: both rules.
        rel = args.glibc or (args.root or {}).get("release")
        old = not musl and not (rel and vtuple(rel) >= (2, 35))
        new = musl or not (rel and vtuple(rel) < (2, 35))
        if old and i["align"] and i["align"] < args.page_size:
            p.append("LOAD alignment %#x is below the target page size %#x" % (i["align"], args.page_size))
        if new and i["voff"] and i["voff"] < args.page_size:
            p.append("LOAD vaddr-offset alignment %#x is below the target page size %#x" % (i["voff"], args.page_size))
    if args.root and i["libc"] in ("glibc", "musl") and not p and not (musl and i["libc"] == "glibc" and not args.root["musl_syms"]) and (
            args.root["libs"] or musl and (args.root["files"] or i["libc"] == "glibc")):
        other = [n for n in i["needed"] if n not in ROOT_LIBS and not GLIBC_LIBS.match(n) and not n.startswith("ld-")
                 and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)) and n not in args.root["libs"]
                 and n not in args.root["files"] and n not in getattr(args, "shipped", ()) and not root_has(args.root, [n])]
        if other:  # another library it needs that the image does not have and the scanned files do not ship
            c.append(needs_other(other, args.root))
    return p, c


def library_name(path):
    """File name without its architecture and C library parts: the builds of one library share it."""
    n = os.path.basename(path).lower()
    n = re.sub(r"\.so(\.[0-9]+)+$", ".so", n)
    n = re.sub(r"([-_.])linux(32|64)(?=[-_.]|$)", r"\1linux", n)
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


def x86_refused(xi, t):
    """What an x86-64 glibc build needs that musl's loader does not answer itself and the image (t) lacks. The image's
    glibc loader (gcompat) stands in for the x86-64 one, which the image's x86-64 variant would carry instead."""
    names = (["interpreter " + xi.get("interp", "")] if "ld-linux" in xi.get("interp", "") else []) + [
        n for n in xi.get("needed", []) if GLIBC_LIBS.match(n) and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
    image = root_has(t, [n for n in names if "ld-linux" not in n])
    return [n for n in names if n not in image and not ("ld-linux" in n and t and t["glibc_loader"])]


def baseline(i, x86, args, probs, musl_x86=False):
    """Text for an aarch64 glibc, libstdc++ or musl-loader finding (probs) that the x86-64 build (x86: info, path)
    has too. musl_x86: the package has an x86-64 build for musl, which x86-64 hosts with a musl OS load instead."""
    if i["arch"] != "aarch64" or not x86:
        return ""
    xi, path = x86
    if xi["arch"] != "x86-64" or xi["libc"] != i["libc"]:
        return ""
    shared = root_shared(probs, xi["vers"])
    need = (x86_refused(xi, args.root) if any(p.startswith("glibc build; musl") for p in probs) and not musl_x86
            else [])
    if shared or need:
        return ("; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well (not a Graviton "
                "change)" % (path, shared or ", ".join(need)))
    syms = [n for n in xi.get("imports", []) if n in musl_resolve(i.get("imports", []), args.root)[0]] if (
        args.root and args.root.get("musl_syms") and any(p.startswith("glibc build; the target's musl does not define") for p in probs) and not musl_x86) else []
    if syms:  # the same missing symbol in the x86-64 build: x86-64 hosts with this image are exposed too
        return ("; the x86-64 build %s imports %s too, so a call that reaches it stops x86-64 hosts with this OS as "
                "well (not a Graviton change)" % (path, ", ".join(syms[:4])))
    for key, pre, tgt in (("glibc", 6, args.glibc), ("glibcxx", 8, args.glibcxx)):
        if (any(p.startswith("needs " + i[key] + " ") for p in probs) and tgt and i[key] and xi[key]
                and vtuple(xi[key][pre:]) > vtuple(tgt)):
            return ("; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well (not a Graviton "
                    "change)" % (path, xi[key]))
    return ""


def target_line(args, target):
    musl = "musl" in target
    t = args.root
    rel, cxx = args.glibc or (t["release"] if t else ""), args.glibcxx or (t["glibcxx"] if t else "")
    line = "target: %s (%s%s)" % ("musl" if musl else "glibc", target, ", assumed" if not args.rid_given else "")
    if t and t["glibc_loader"]:
        line += ", with a glibc loader"
    if not musl:
        line += (", glibc " + rel) if rel else (", glibc release not read" if t else ", glibc version not given")
    line += (", page size %d" % args.page_size) if args.page_size else ", page size not given"
    return line + (", libstdc++ GLIBCXX_" + cxx if cxx and not musl else "") + root_read_from(t)


def small_note(paths, args):
    """One NOTE for aarch64 files aligned for 4 KB pages only, when no page size was given."""
    if paths and not args.page_size:
        paths = sorted(set(paths))
        print("NOTE %d aarch64 file(s) aligned for 4 KB pages only (%s%s): a kernel with 64 KB pages refuses them; give "
              "the page size if the target uses 64 KB pages" % (len(paths), ", ".join(paths[:5]),
                                                                 " and %d more" % (len(paths) - 5) if len(paths) > 5 else ""))


def is_small(i):
    return i["arch"] == "aarch64" and (0 < i["align"] < 0x10000 or 0 < i["voff"] < 0x10000)


def describe(i):
    voff = "vaddr-offset align %#x" % i["voff"] if i["arch"] == "aarch64" and 0 < i["voff"] < 0x10000 else ""
    return " ".join(x for x in (i["libc"], i["glibc"], i["glibcxx"], ("align %#x" % i["align"]) if i["align"] else "", voff)
                    if x)


def needs(i):
    """The libraries an aarch64 file needs (DT_NEEDED): each comes from the target image or ships with the file."""
    return "needs " + " ".join(i["needed"]) if i["arch"] == "aarch64" and i["needed"] else ""


def base_name(name):
    """Package name without its RID or architecture part, so x64 and arm64 variants are judged as one family."""
    n = re.sub(r"^runtime\.(linux|osx|win|freebsd|alpine|unix)(-[a-z0-9]+)*\.", "", name, flags=re.I)
    n = re.sub(r"\.(linux|osx|win|freebsd|alpine)(-[a-z0-9]+)+$", "", n, flags=re.I)
    return re.sub(r"-(x64|x86|arm64|arm)$", "", n, flags=re.I)


# ---------- assets, probe, config ----------

def restore(work, rids, timeout):
    targets = sorted(f for f in os.listdir(work) if f.endswith((".sln", ".slnx")))
    projects = list(targets)
    if not projects:
        for d, dirs, files in os.walk(work):
            dirs[:] = [x for x in dirs if x not in ("bin", "obj", ".git")]
            projects += [os.path.relpath(os.path.join(d, f), work) for f in files if f.endswith((".csproj", ".fsproj", ".vbproj"))]
    if not projects:
        print("no .sln, .slnx or project file found")
        return False
    ok = True
    for p in projects:
        print("restore %s for %s (scratch copy)" % (p, ";".join(rids)))
        cmd = ["dotnet", "restore", p, "-p:RuntimeIdentifiers=\"%s\"" % ";".join(rids),
               "-p:RestoreLockedMode=false", "-p:EnableWindowsTargeting=true"]
        # argument list, no shell: `dotnet restore`, a project file found in the tree being analyzed, and the operator's RIDs
        try:
            r = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)  # nosec B603  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        except subprocess.TimeoutExpired:
            print("restore of %s timed out after %d s" % (p, timeout))
            return False
        errors = sorted(set(re.findall(r"error [A-Z]+[0-9]+: [^\[\n]{0,200}", r.stdout)))
        for w in sorted(set(x.strip() for x in re.findall(r"warning NU190[1-4]: [^\[\n]{0,200}", r.stdout))):
            if w not in AUDIT_SEEN:
                AUDIT_SEEN.add(w)
                print("NOTE NuGet audit: %s" % w)
        if r.returncode:
            ok = False
            print("restore of %s failed (exit %d)%s" % (p, r.returncode, "".join("\n  " + e for e in errors[:5])))
    return ok


def load_packages(root):
    """Packages of every restored project, and per project and framework the graph used for reference chains."""
    pkgs, graphs = {}, []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("bin", ".git")]
        if "project.assets.json" not in files:
            continue
        a = json.load(open(os.path.join(d, "project.assets.json")))
        folders = list(a.get("packageFolders", {}))
        pp = a.get("project", {}).get("restore", {}).get("projectPath", "")
        proj = os.path.relpath(os.path.dirname(pp) if pp else os.path.dirname(d), root)
        for key, entries in a.get("targets", {}).items():
            rid = key.split("/", 1)[1] if "/" in key else ""
            for name, e in entries.items():
                if e.get("type") != "package":
                    continue
                lib = a["libraries"].get(name, {})
                r = pkgs.setdefault(name, {"rids": {}, "projects": set(), "path": lib.get("path", ""),
                                           "files": lib.get("files", []), "folders": folders})
                r["projects"].add(proj)
                if rid:
                    r["rids"].setdefault(rid, set()).update(k for k in e.get("native", {}) if not k.endswith("_._"))
            if not rid:
                byname = dict((k.split("/")[0].lower(), k) for k in entries)
                roots = [byname[x.split()[0].lower()] for x in a.get("projectFileDependencyGroups", {}).get(key, [])
                         if x.split() and x.split()[0].lower() in byname]
                graphs.append((proj, key, entries, byname, roots))
    return pkgs, graphs


def shortest_paths(entries, byname, roots):
    """Breadth-first search from a project's direct references: node -> previous node (None for roots)."""
    prev, queue = dict((r, None) for r in roots), list(roots)
    while queue:
        nxt = []
        for n in queue:
            for dep in entries.get(n, {}).get("dependencies", {}):
                k = byname.get(dep.lower())
                if k and k not in prev:
                    prev[k] = n
                    nxt.append(k)
        queue = nxt
    return prev


def label(entries, k):
    return k.split("/")[0] if entries.get(k, {}).get("type") == "project" else k.replace("/", " ")


def path_to(entries, prev, k):
    out = []
    while k is not None:
        out.append(label(entries, k))
        k = prev[k]
    return out[::-1]


def chain(graphs, cache, name):
    """Shortest reference chain from any project to package name, for example
    'src/Fixture.Tool > Fixture.Core > Microsoft.Data.Sqlite 8.0.31 > SQLitePCLRaw.lib.e_sqlite3 2.1.12'."""
    best = None
    for i, (proj, key, entries, byname, roots) in enumerate(graphs):
        k = byname.get(name.lower())
        if k is None:
            continue
        if i not in cache:
            cache[i] = shortest_paths(entries, byname, roots)
        if k in cache[i]:
            c = [proj] + path_to(entries, cache[i], k)
            if best is None or len(c) < len(best):
                best = c
    if best is None:
        return ""
    return "%s (direct reference)" % best[0] if len(best) == 2 else " > ".join(best)


def locate(r, f):
    for fo in r["folders"]:
        p = os.path.join(fo, r["path"], f)
        if os.path.isfile(p):
            return p
    return None


def report_assets(root, args):
    start, cstart = len(FINDINGS), len(CHECKS)
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("bin", "obj", ".git", "packages")]
        if "packages.config" in files:
            rel = os.path.relpath(os.path.join(d, "packages.config"), root)
            check("%s: these packages are not restored by PackageReference and are not in this report; run: config %s"
                  % (rel, rel))
    pkgs, graphs = load_packages(root)
    args.shipped = set(os.path.basename(f) for r in pkgs.values() for t in args.target_rid for f in r["rids"].get(t, ()))  # the native files the packages give the target RIDs
    for r in pkgs.values():  # and their SONAMEs: a library loaded by path answers a later need for it
        for f in set(f for t in args.target_rid for f in r["rids"].get(t, ())):
            try:
                with open(locate(r, f), "rb") as fh:
                    so = elf_info(fh.read()).get("soname", "")
            except (OSError, TypeError, struct.error, ValueError, IndexError):
                so = ""
            if so:
                args.shipped.add(so)
    cache = {}

    def via(name):
        c = chain(graphs, cache, name.split("/")[0])
        if c:
            print("  via " + c)
    if not pkgs:
        if graphs:
            print("restored %d project(s); none of them resolves a NuGet package" % len(set(g[0] for g in graphs)))
            return 1 if len(FINDINGS) > start else 0
        print("restore passed, but it wrote no project.assets.json inside the scratch copy "
              "(BaseIntermediateOutputPath or ArtifactsPath outside the repository?)")
        return 2
    used = lambda r: "; used by " + ", ".join(sorted(r["projects"]))
    for t in args.target_rid:
        print(target_line(args, t))
    groups, small = {}, []
    for name, r in pkgs.items():
        elfs = []
        for f in r["files"]:
            if f.startswith("runtimes/") or f.endswith("/"):
                continue
            p = locate(r, f)
            h = head(p) if p else b""
            if h[:4] == b"\x7fELF" and len(h) >= 20:
                elfs.append((ELF_ARCH.get(struct.unpack_from("<H", h, 18)[0], "other"), f))
        if elfs:
            g = groups.setdefault(base_name(name.split("/")[0]).lower(), {"names": [], "elfs": [], "r": r})
            g["names"].append(name)
            g["elfs"] += elfs
    family = {}  # (family, RID) -> a package of that family with natives for the RID
    for name, r in pkgs.items():
        for t in args.target_rid:
            if r["rids"].get(t):
                family.setdefault((base_name(name.split("/")[0]).lower(), t), name)
    native_pkgs = other = managed = 0
    for name in sorted(pkgs, key=str.lower):
        r = pkgs[name]
        if not any(r["rids"].get(x) for x in [args.source_rid] + args.target_rid):
            if any(f.startswith("runtimes/") and "/native/" in f for f in r["files"]):
                other += 1
            else:
                managed += 1
            continue
        native_pkgs += 1
        folders = sorted(set(f.split("/")[1] for f in r["files"] if f.startswith("runtimes/") and "/native/" in f))
        src_names = set(os.path.basename(f) for f in r["rids"].get(args.source_rid, ()))
        for t in args.target_rid:
            got = sorted(r["rids"].get(t, ()))
            if not got:
                sibling = family.get((base_name(name.split("/")[0]).lower(), t))
                if sibling:
                    print("OK %s %s: no native of its own; %s, of the same family, provides it" % (t, name, sibling))
                    continue
                finding("no %s native: %s (%s has %d; runtimes/ folders: %s)%s" % (
                    t, name, args.source_rid, len(src_names), ", ".join(folders) or "none", used(r)))
                via(name)
                continue
            missing = sorted(src_names - set(os.path.basename(f) for f in got))
            if missing:
                print("NOTE %s gets %d native file(s) of %s, %s gets %d; only on %s: %s" % (
                    t, len(got), name, args.source_rid, len(src_names), args.source_rid, ", ".join(missing)))
            # Builds for both C libraries in one RID folder (librdkafka.redist ships librdkafka.so and
            # alpine-librdkafka.so): the package's loader picks one at run time, so a build for the other
            # C library is only a finding when no build for the target's C library is present.
            libcs = set()
            for f in got:
                fp = locate(r, f)
                if fp and head(fp)[:4] == b"\x7fELF":
                    fi = elf_info(read_all(fp))
                    if fi["arch"] == "aarch64":
                        libcs.add(fi["libc"])
            want = "musl" if "musl" in t else "glibc"
            for f in got:
                p = locate(r, f)
                if p is None:
                    print("NOTE %s native %s of %s is not in the package folder" % (t, f, name))
                    continue
                b = read_all(p)
                if b[:8] == b"!<arch>\n":  # static library, used when linking (Native AOT), judged by its objects
                    arches = ar_arches(b)
                    if "aarch64" in arches:
                        print("OK %s %s: %s (static library, aarch64 objects)" % (t, name, f))
                    elif not arches:
                        print("NOTE %s native %s of %s is a static library with no ELF objects (ignored)" % (t, f, name))
                    else:
                        check("%s native %s of %s: static library with no aarch64 code (%s); a native arm64 build that "
                              "links it fails%s" % (t, f, name, ", ".join(sorted(arches)), used(r)))
                        via(name)
                    continue
                if b[:4] != b"\x7fELF":
                    if b[:2] == b"MZ" or b[:4] in MACHO:
                        finding("%s native %s of %s is a Windows or macOS binary%s" % (t, f, name, used(r)))
                        via(name)
                    else:
                        print("NOTE %s native %s of %s is not a binary (ignored)" % (t, f, name))
                    continue
                i = elf_info(b)
                if i["os"] != "Linux":
                    finding("%s native %s of %s is a %s build%s" % (t, f, name, i["os"], used(r)))
                    via(name)
                    continue
                probs, checks = elf_problems(i, args, t)
                other_libc = i["arch"] == "aarch64" and i["libc"] in ("glibc", "musl") and i["libc"] != want
                if is_small(i):
                    small.append("%s/%s" % (name, f))
                if other_libc and want in libcs and len(probs) + len(checks) == 1:
                    print("NOTE %s native %s of %s is a %s build; the package also has a %s build for this RID, and its "
                          "loader picks one at run time (confirm in Phase 3)" % (t, f, name, i["libc"], want))
                elif probs:
                    src = [x for x in r["rids"].get(args.source_rid, ()) if os.path.basename(x) == os.path.basename(f)]
                    sp = locate(r, src[0]) if src else None
                    x86 = (elf_info(read_all(sp)), src[0]) if sp and head(sp)[:4] == b"\x7fELF" else None
                    mx = any(x.startswith(("runtimes/linux-musl-x64/", "runtimes/linux-musl/")) and
                             os.path.basename(x) == os.path.basename(f) for x in r["files"])  # an x86-64 musl build
                    finding("%s native %s of %s %s%s%s" % (t, f, name, "; ".join(probs), baseline(i, x86, args, probs, mx),
                                                          used(r)))
                    via(name)
                elif checks:
                    check("%s native %s of %s: %s%s" % (t, f, name, "; ".join(checks), used(r)))
                    via(name)
                else:
                    print("OK %s %s: %s (%s)" % (t, name, f, "; ".join(x for x in (describe(i), needs(i)) if x)))
    for g in sorted(groups.values(), key=lambda g: g["names"][0].lower()):
        arches = sorted(set(a for a, _ in g["elfs"]))
        sample = ", ".join(f for _, f in g["elfs"][:3])
        if "aarch64" in arches:
            print("OK ELF files outside runtimes/ in %s: %s" % (", ".join(g["names"]), ", ".join(arches)))
        else:
            check("ELF files outside runtimes/ in %s are %s only (they fail only if a build target copies them to the "
                  "output or a tool runs them), e.g. %s%s" % (", ".join(g["names"]), ", ".join(arches), sample, used(g["r"])))
            via(g["names"][0])
    if getattr(args, "tree", None):
        tree = {}
        for proj, key, entries, byname, roots in graphs:
            prev = shortest_paths(entries, byname, roots)
            tree.setdefault(proj, {})[key] = dict(
                (label(entries, k), {"type": entries[k].get("type"), "via": path_to(entries, prev, k)[:-1]})
                for k in sorted(entries, key=str.lower) if k in prev)
        with open(args.tree, "w") as f:
            json.dump(tree, f, indent=1, sort_keys=True)
        print("dependency tree: %d projects written to %s" % (len(tree), args.tree))
    small_note(small, args)
    for n in libs_notes(args.root):
        print("NOTE " + n)
    print("packages: %d; with native files for these RIDs: %d; natives for other platforms only: %d; managed only: %d" % (
        len(pkgs), native_pkgs, other, managed))
    print("findings: %d, checks: %d" % (len(FINDINGS) - start, len(CHECKS) - cstart))
    return 1 if len(FINDINGS) > start else 0


def cmd_assets(args):
    if not os.path.isdir(args.dir):  # an empty path would copy the working folder
        print("ERROR: %s is not a folder" % (args.dir or "''"))
        return 2
    src = os.path.abspath(args.dir)
    if args.tree:
        args.tree = os.path.abspath(args.tree)
    with tempfile.TemporaryDirectory(prefix="gv-assets-") as tmp:
        work = os.path.join(tmp, "src")
        shutil.copytree(src, work, symlinks=True,
                        ignore=shutil.ignore_patterns("bin", "obj", ".git", ".vs", "node_modules", "graviton-validation"))
        for d, dirs, files in os.walk(work):  # read only the assets files this restore writes
            for f in files:
                if f in ("project.assets.json", "project.nuget.cache"):
                    os.remove(os.path.join(d, f))
        if not restore(work, [args.source_rid] + args.target_rid, args.timeout):
            return 2
        return report_assets(work, args)


def cmd_probe(args):
    with tempfile.TemporaryDirectory(prefix="gv-probe-") as tmp:
        for c in ("NuGet.config", "nuget.config", "NuGet.Config"):
            if os.path.isfile(c):
                shutil.copy(c, tmp)
        proj = os.path.join(tmp, "probe", "probe.csproj")
        os.makedirs(os.path.dirname(proj))
        with open(proj, "w") as f:
            f.write('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <TargetFramework>%s</TargetFramework>\n'
                    '    <ManagePackageVersionsCentrally>false</ManagePackageVersionsCentrally>\n'
                    '    <NuGetAuditMode>all</NuGetAuditMode>\n  </PropertyGroup>\n'
                    '  <ItemGroup>\n    <PackageReference Include="%s" Version="[%s]" />\n  </ItemGroup>\n</Project>\n'
                    % (args.framework, args.id, args.version))
        if not restore(tmp, [args.source_rid] + args.target_rid, args.timeout):
            return 2
        return report_assets(tmp, args)


def packages_config_entries(path):
    """(id, version) of every <package> element of a packages.config, in file order.

    A packages.config is a short, flat list of elements and never carries a DTD. The file is parsed with Expat directly,
    and a DOCTYPE or entity declaration stops the parse before any expansion (the entity expansion attacks the xml
    module's documentation warns about); external entities cannot be declared without a DTD, so none is resolved. Files
    over 1 MiB are refused before they are read."""
    if os.path.getsize(path) > 1 << 20:
        raise ValueError("%s is larger than 1 MiB; a packages.config is a short list of package elements" % path)
    entries = []

    def refuse(*_):
        raise ValueError("%s declares a DTD or an entity, which a packages.config never needs; not parsed" % path)

    def start(name, attrs):
        if name == "package":
            entries.append((attrs.get("id"), attrs.get("version")))

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = start
    with open(path, "rb") as f:
        parser.ParseFile(f)
    return entries


def cmd_config(args):
    try:
        entries = packages_config_entries(args.file)
    except (ValueError, expat.ExpatError) as e:
        print("ERROR: %s" % e)
        return 2
    errors = 0
    for pid, ver in entries:
        print("--- %s %s" % (pid, ver))
        a = argparse.Namespace(**vars(args))
        a.id, a.version = pid, ver
        errors += cmd_probe(a) == 2
    print("packages.config entries: %d; restore errors: %d" % (len(entries), errors))
    print("findings: %d, checks: %d" % (len(FINDINGS), len(CHECKS)))
    return 1 if FINDINGS else (2 if errors else 0)


# ---------- scan ----------

def deps_check(path, rel, chain, source):
    """For outputs built without a RID: native assets listed per RID in the .deps.json."""
    try:
        d = json.load(open(path))
    except ValueError:
        return
    rt = d.get("runtimeTarget", {}).get("name", "")
    print("deps.json %s: runtime target %s" % (rel, rt or "-"))
    rid = rt.split("/", 1)[1] if "/" in rt else ""
    if rid and rid not in chain:
        finding("%s was built for %s" % (rel, rid))
    for libs in d.get("targets", {}).values():
        def native_rids(e):
            return set(v.get("rid") for v in e.get("runtimeTargets", {}).values() if v.get("assetType") == "native")
        family = {}  # family name -> [(package, RIDs with a native)]
        for lib, e in libs.items():
            family.setdefault(base_name(lib.split("/")[0]).lower(), []).append((lib, native_rids(e)))
        for lib, e in libs.items():
            rids = native_rids(e)
            if source in rids and not rids & set(chain):
                sib = [x for x, r in family.get(base_name(lib.split("/")[0]).lower(), []) if r & set(chain)]
                if sib:
                    print("OK %s: %s has no %s native of its own; %s, of the same family, provides it" % (
                        rel, lib, chain[0], sib[0]))
                else:
                    finding("%s lists a %s native for %s but none for %s (RIDs: %s)" % (
                        rel, source, lib, chain[0], ", ".join(sorted(rids))))


def deps_owners(root):
    """Native file (relative to root) -> package, from the .deps.json files in root."""
    owners = {}
    for n in sorted(os.listdir(root)):
        if not n.endswith(".deps.json"):
            continue
        try:
            d = json.load(open(os.path.join(root, n)))
        except ValueError:
            continue
        for libs in d.get("targets", {}).values():
            for lib, e in libs.items():
                for k in e.get("native", {}):
                    owners.setdefault(k, lib)
                    owners.setdefault(os.path.basename(k), lib)  # RID-specific outputs copy natives to the root
                for k, v in e.get("runtimeTargets", {}).items():
                    if v.get("assetType") == "native":
                        owners.setdefault(k, lib)
    return owners


def cmd_scan(args):
    root = os.path.abspath(args.dir)
    if not args.dir or not os.path.isdir(root):  # an empty path would scan the working folder
        print("ERROR: %s is not a folder" % (args.dir or "''"))
        return 2
    for target in args.target_rid:
        if len(args.target_rid) > 1:
            print("== target %s" % target)
        scan_one(root, args, target)
    print("findings: %d, checks: %d" % (len(FINDINGS), len(CHECKS)))
    return 1 if FINDINGS else 0


def rid_of(rel):
    """The RID folder of a file under runtimes/<rid>/, else None."""
    parts = rel.replace(os.sep, "/").split("/")
    k = parts.index("runtimes") if "runtimes" in parts[:-2] else -1
    return parts[k + 1] if k >= 0 else None


def scan_one(root, args, target):
    """Every check of scan for one target RID."""
    chain = RID_CHAIN.get(target, [target, "linux", "unix", "any"])
    want = "musl" if "musl" in target else "glibc"
    print(target_line(args, target))
    if not any(os.path.isfile(os.path.join(d, n)) and not os.path.islink(os.path.join(d, n))
               for d, _, fs in os.walk(root) for n in fs):  # a copy or build that produced nothing is not a pass
        check("%s: holds no files: the copy or build that should have filled it produced none" % args.dir)
    counts, other_rid, ignored, elfs, src_builds = {}, 0, 0, [], {}
    musl_x64 = set()  # libraries with a build in runtimes/linux-musl-x64: x86-64 hosts with a musl OS load that one
    skip = (".git", ".vs", "bin", "obj", "node_modules", "graviton-validation") if args.source_tree else (".git",)
    args.shipped = set()  # the aarch64 Linux libraries the scanned files ship, in folders the target loads
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip]
        parts = os.path.relpath(d, root).split(os.sep)
        if "runtimes" in parts[:-1] and parts[parts.index("runtimes") + 1] not in chain:
            dirs[:] = []
            continue
        for n in files:
            h = head(os.path.join(d, n), 20)
            if h[:4] == b"\x7fELF" and len(h) >= 20 and struct.unpack_from("<H", h, 18)[0] == 183:
                args.shipped.add(n)
                try:
                    with open(os.path.join(d, n), "rb") as f:
                        so = elf_info(f.read()).get("soname", "")
                except (OSError, struct.error, ValueError, IndexError):
                    so = ""
                if so:  # a library loaded by path answers a later need for its SONAME
                    args.shipped.add(so)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in skip)
        parts = os.path.relpath(d, root).split(os.sep)
        if "runtimes" in parts:
            k = parts.index("runtimes")
            if len(parts) > k + 1 and parts[k + 1] not in chain:
                for d2, _, fs in os.walk(d):
                    other_rid += len(fs)
                    for n2 in fs:  # the source RID's x86-64 builds, for the baseline note of an aarch64 finding
                        p2 = os.path.join(d2, n2)
                        if parts[k + 1] == args.source_rid and os.path.isfile(p2) and head(p2, 4) == b"\x7fELF":
                            src_builds.setdefault(group_key(os.path.relpath(p2, root)), (elf_info(read_all(p2)), os.path.relpath(p2, root)))
                        if parts[k + 1] == "linux-musl-x64":
                            musl_x64.add(group_key(os.path.relpath(p2, root)))  # keyed like the groups below
                dirs[:] = []
                continue
        for n in sorted(files):
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            if n.endswith(".runtimeconfig.json"):
                try:
                    c = json.load(open(p))["runtimeOptions"]
                except (ValueError, KeyError):
                    continue
                fw = [x["name"] for x in c.get("frameworks", [c.get("framework")]) if x]
                print("runtimeconfig %s: %s" % (rel, ", ".join(fw) or "self-contained"))
                if "Microsoft.WindowsDesktop.App" in fw:
                    finding("%s needs Microsoft.WindowsDesktop.App, which exists only on Windows" % rel)
                continue
            if n.endswith(".deps.json"):
                deps_check(p, rel, chain, args.source_rid)
                continue
            h = head(p, 8)
            if h == b"!<arch>\n":
                arches = ar_arches(read_all(p))
                kind = "static library " + (", ".join(sorted(arches)) or "no ELF")
                if not arches:
                    ignored += 1  # no ELF objects: another system's library
                elif "aarch64" not in arches:
                    check("%s static library with no aarch64 code (%s); a native arm64 build that links it fails" % (
                        rel, ", ".join(sorted(arches))))
            elif h[:4] == b"\x7fELF":
                data = read_all(p)
                i = elf_info(data)
                i["sha"] = hashlib.sha256(data).hexdigest()  # copies of one file are one build
                kind = "ELF " + i["arch"] + (" object" if i["etype"] == 1 else "")
                print("%-12s %-40s %s%s" % (kind, describe(i), rel, "  (%s)" % needs(i) if needs(i) else ""))
                if i["os"] != "Linux":
                    ignored += 1  # another system's build
                    kind = "ELF %s (%s)" % (i["arch"], i["os"])
                elif i["etype"] == 1:  # an object file: a build input that no loader reads
                    if i["arch"] != "aarch64" or i["bits"] != 64:
                        check("%s object file with no aarch64 code (%s); a native arm64 build that links it fails" % (
                            rel, i["arch"]))
                else:
                    probs, checks = elf_problems(i, args, target)
                    elfs.append((rel, i, probs, checks))
            elif h[:2] == b"MZ":
                kind = pe_kind(read_all(p)) or "PE (unreadable)"
                if kind.startswith("native PE"):
                    ignored += 1
                elif kind not in ("managed AnyCPU", "managed arm64", "managed ReadyToRun linux-arm64"):
                    finding("%s is %s" % (rel, kind))
            elif h[:4] in MACHO:
                kind = "Mach-O"
                ignored += 1
            else:
                continue
            counts[kind] = counts.get(kind, 0) + 1
    owners, pick = deps_owners(root), {}  # a package's own loader picks its build for the C library (librdkafka.redist)
    for rel, i, probs, _c in elfs:
        if owners.get(rel) and i["arch"] == "aarch64" and i["libc"] == want and not probs:
            pick.setdefault(owners[rel], rel)
    groups, replaced = {}, set()  # builds of one library side by side: the target loads one of them
    for e in elfs:
        rel, i, probs, checks = e
        lib = owners.get(rel)
        if (lib in pick and i["arch"] == "aarch64" and i["libc"] in ("glibc", "musl") and i["libc"] != want
                and len(probs) + len(checks) == 1 and (probs + checks)[0].startswith(("glibc build", "is a musl build"))):
            print("NOTE %s is a %s build; %s also ships a %s build here (%s), and its loader picks one at run time "
                  "(confirm in Phase 3)" % (rel, i["libc"], lib, want, pick[lib]))
            replaced.add(rel)
            continue
        groups.setdefault(group_key(rel), []).append(e)
    for lib in sorted(groups):
        g = groups[lib]
        ranks = sorted(set(chain.index(rid_of(e[0])) for e in g if rid_of(e[0]) in chain))
        if len(ranks) > 1:  # the host loads the build in the most specific RID folder that has the library
            keep = [e for e in g if rid_of(e[0]) not in chain or chain.index(rid_of(e[0])) == ranks[0]]
            drop = [e for e in g if e not in keep]
            print("NOTE %s: on %s the host loads the build in runtimes/%s (the most specific RID folder that has it), "
                  "not %s" % (library_name(g[0][0]), target, chain[ranks[0]], ", ".join(e[0] for e in drop)))
            replaced.update(e[0] for e in drop)
            g = keep
        ok = [e for e in g if not e[2]]
        if ok:  # the build for the target (no CHECK and its C library first) is judged; the other builds get no flag
            pick = sorted(ok, key=lambda e: (bool(e[3]), e[1]["libc"] not in (want, "static")))[0]
            replaced.update(e[0] for e in g if e is not pick)
            if pick[3]:
                check("%s %s" % (pick[0], "; ".join(pick[3])))
            builds = len(set(e[1].get("sha") or e[0] for e in g))  # copies of one file are one build
            if builds > 1:
                print("NOTE %s: %d Linux builds in the scanned files; %s is the build for this target; confirm in Phase 3 "
                      "that it is the one loaded" % (library_name(pick[0]), builds, pick[0]))
            continue
        arm = [e for e in g if e[1]["arch"] == "aarch64"]
        primary = ([e for e in arm if e[1]["libc"] in (want, "static")] or [e for e in arm if e[1]["libc"] != "android"]
                   or arm or [e for e in g if e[1]["arch"] == "x86-64"][:1] or g[:1])
        x86 = [(e[1], e[0]) for e in g if e[1]["arch"] == "x86-64"] + ([src_builds[lib]] if lib in src_builds else [])
        replaced.update(e[0] for e in g if e not in primary)
        for rel, i, probs, checks in primary:  # the build the target would load carries the finding
            same = [x for x in x86 if x[0]["libc"] == i["libc"]]
            mx = lib in musl_x64 or any(x[0]["libc"] != "glibc" for x in x86)  # an x86-64 build for musl
            finding("%s %s%s" % (rel, "; ".join(probs), baseline(i, same[0] if same else None, args, probs, mx)))
            if checks:
                check("%s %s" % (rel, "; ".join(checks)))
    small_note([rel for rel, i, _p, _c in elfs if is_small(i) and rel not in replaced], args)
    for n in libs_notes(args.root):
        print("NOTE " + n)
    print("files by kind: " + (", ".join("%s %d" % kv for kv in sorted(counts.items())) or "none"))
    if ignored or other_rid:
        print("not loaded on %s, ignored: %d native PE, Mach-O, other systems' ELF or non-ELF static libraries, %d under "
              "runtimes/ for other RIDs" % (target, ignored, other_rid))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    for name in ("assets", "scan", "probe", "config"):
        p = sub.add_parser(name)
        p.add_argument("--source-rid", default="linux-x64")
        p.add_argument("--target-rid", action="append", help="repeatable; default linux-arm64 (add linux-musl-arm64 for Alpine)")
        p.add_argument("--glibc", help="target glibc version, for example 2.34; natives needing a newer GLIBC_ are findings")
        p.add_argument("--glibcxx", help="highest GLIBCXX_ version of the glibc target's libstdc++, for example 3.4.30; "
                       "natives needing a newer one are findings (musl RIDs ignore it)")
        p.add_argument("--page-size", type=int, help="target kernel page size in bytes, for example 65536")
        p.add_argument("--target-root", metavar="DIR", help="the target image's files: C library, library versions and "
                       "libstdc++ level are read from there, in place of --glibc and --glibcxx; the RID follows the "
                       "image's C library")
        p.add_argument("--timeout", type=int, default=900, help="seconds per dotnet command")
        if name == "assets":
            p.add_argument("dir", nargs="?", default=".")
            p.add_argument("--tree", help="also write every resolved package and its shortest reference chain (JSON)")
        elif name == "scan":
            p.add_argument("dir")
            p.add_argument("--source-tree", action="store_true", help="skip .git, .vs, bin, obj, node_modules, graviton-validation")
        elif name == "probe":
            p.add_argument("id")
            p.add_argument("version")
        else:
            p.add_argument("file")
        if name in ("probe", "config"):
            p.add_argument("--framework", default="net8.0")
    args = ap.parse_args()
    if not args.command:
        ap.print_help()
        return 2
    args.root = None
    if args.target_root == "":  # an empty value (an unset variable) would judge the files with no target
        print("ERROR: --target-root names no folder: give the folder the target image's files were copied to")
        return 2
    if args.target_root:
        if args.glibc or args.glibcxx:
            print("ERROR: --target-root reads the C library and its versions from the image's files; leave out "
                  "--glibc and --glibcxx")
            return 2
        args.root = read_root(args.target_root)
        if not isinstance(args.root, dict):
            print("ERROR: " + args.root)
            return 2
        rid = "linux-musl-arm64" if args.root["libc"] == "musl" else "linux-arm64"
        if any(("musl" in r) != (args.root["libc"] == "musl") for r in args.target_rid or []):
            print("ERROR: the image in %s uses %s; give --target-rid %s or leave it out" % (
                args.target_root, args.root["libc"], rid))
            return 2
        args.target_rid = args.target_rid or [rid]
    args.rid_given = bool(args.target_rid)  # without --target-rid the target is linux-arm64 (glibc), stated as assumed
    args.target_rid = args.target_rid or ["linux-arm64"]
    args.glibcxx = (args.glibcxx or "").replace("GLIBCXX_", "")
    if args.glibcxx and not re.match(r"^[0-9]+(\.[0-9]+)*$", args.glibcxx):
        print("ERROR: --glibcxx takes a version such as 3.4.30, not %s" % args.glibcxx)
        return 2
    return {"assets": cmd_assets, "scan": cmd_scan, "probe": cmd_probe, "config": cmd_config}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
