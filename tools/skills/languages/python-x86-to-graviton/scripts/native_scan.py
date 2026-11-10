#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import collections, hashlib, io, os, re, struct, sys, zipfile, zlib
ARCH = {3: "i386", 40: "arm", 62: "x86-64", 183: "aarch64", 243: "riscv"}
OS_ABI = {1: "HP-UX", 2: "NetBSD", 6: "Solaris", 7: "AIX", 9: "FreeBSD", 12: "OpenBSD"}  # EI_OSABI of other systems
GLIBC_LIBS = re.compile(r"(libc\.so\.6|libm\.so\.6|libpthread\.so\.0|libdl\.so\.2|librt\.so\.1|libresolv\.so\.2"
                        r"|libutil\.so\.1|libanl\.so\.1|libmvec\.so\.1|libnsl\.so\.1|ld-linux[-a-z0-9_.]*\.so\.[0-9]+)$")
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
# A target image's files (TARGET_ROOT): the folders its loader searches, and the libraries whose files say what the
# image provides: glibc's libraries and loader (the first eleven), musl's loader, libstdc++ and libgcc_s
ROOT_DIRS = ("lib", "lib64", "usr/lib", "usr/lib64", "lib/aarch64-linux-gnu", "usr/lib/aarch64-linux-gnu")
GNU_EXT = re.compile(r"\.cpython-3(1[1-9]|[2-9][0-9])[a-z]*-[a-z0-9_]+-linux-gnu\.so$")  # a glibc CPython 3.11+ module suffix (3.10 and earlier on musl use -linux-gnu.so too)
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

ROOT_OPTION = "TARGET_ROOT"


EFFECT = "the import fails (Python imports extension modules with RTLD_NOW)"


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
                "imports against the image's files (%s): a symbol the image does not define is a FINDING: Python imports "
                "extension modules with RTLD_NOW, so the import fails with symbol not found" % (only, ", ".join(own), also, ROOT_OPTION))
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

# TARGET_ROOT: the image's files give the C library and its versions, and TARGET_LIBC and TARGET_LIBC_VER
# (which the wheel probes use) and TARGET_GLIBCXX are not used by the scan
ROOT, IGNORED = None, [v for v in ("TARGET_LIBC", "TARGET_LIBC_VER", "TARGET_GLIBCXX") if os.environ[v]]
if os.environ["TARGET_ROOT"]:
    ROOT = read_root(os.environ["TARGET_ROOT"])
    if not isinstance(ROOT, dict):
        print("ERROR: " + ROOT)
        sys.exit(2)
ASSUMED = not (os.environ["TARGET_LIBC"] or ROOT)  # no target given: judge against glibc and say so
LIBC = ROOT["libc"] if ROOT else os.environ["TARGET_LIBC"] or "glibc"
VER = "" if ROOT else os.environ["TARGET_LIBC_VER"]
REL = VER or (ROOT["release"] if ROOT else "")  # the glibc release, for the page-alignment rule
if LIBC not in ("glibc", "musl"):
    print("ERROR: TARGET_LIBC is glibc or musl")
    sys.exit(2)
CXX = "" if ROOT else os.environ["TARGET_GLIBCXX"].replace("GLIBCXX_", "")
if not re.match(r"[0-9]*$", os.environ["TARGET_PAGE_SIZE"]):
    print("ERROR: TARGET_PAGE_SIZE is a number of bytes, for example 65536")
    sys.exit(2)
PAGE = int(os.environ["TARGET_PAGE_SIZE"] or 0)
entries, machines = [], collections.Counter()

def vkey(v):
    return tuple(int(x) for x in re.findall(r"[0-9]+", v))

def add(name, box, desc, **kw):  # box: the archive that holds the file, or the path given for loose files
    e = {"name": name, "box": box, "desc": desc, "probs": [], "checks": [], "loadable": False, "small": False}
    e.update(kw)
    entries.append(e)
    return e

def reader(src):  # read(offset, size) on bytes or on an open file, never past its end
    if isinstance(src, bytes):
        return lambda o, n: src[o:o + n] if o >= 0 and n > 0 else b""
    size = os.fstat(src.fileno()).st_size
    def read(o, n):
        if o < 0 or n <= 0 or o >= size:
            return b""
        src.seek(o)
        return src.read(min(n, size - o))
    return read

def elf(name, box, read):
    h = read(0, 64)
    etype, machine = struct.unpack(">HH" if h[5] == 2 else "<HH", h[16:20])
    machines[machine] += 1
    arch = ARCH.get(machine, "other")
    head = "e_machine %d (%s)" % (machine, arch) + (", ELF32" if h[4] == 1 else "") + (", big-endian" if h[5] == 2 else "")
    other = machine != 183 or h[4] != 2 or h[5] != 1
    if etype == 1:  # an object file: a build input that no loader reads
        e = add(name, box, head + ", relocatable object")
        if other:
            e["checks"].append("object file with no aarch64 code (%s); a native arm64 build that links it fails" % head)
        return
    if etype == 4:
        return add(name, box, head + ", core dump")
    if h[7] in OS_ABI:
        return add(name, box, head + " (a %s build; Linux does not load it)" % OS_ABI[h[7]])
    if h[4] != 2 or h[5] != 1:  # 32-bit or big-endian: not read further
        return add(name, box, head, probs=["not aarch64, " + head], loadable=True, arch=arch, libc="", glibc="", cxx="", vers=[])
    phoff = struct.unpack("<Q", h[32:40])[0]
    phentsize, phnum = struct.unpack("<HH", h[54:58])
    loads, dyn, interp, android, phentsize = [], b"", "", False, phentsize or 56
    ph = read(phoff, phentsize * phnum)
    for k in range(0, len(ph) - 55, phentsize):
        p_type = struct.unpack("<I", ph[k:k + 4])[0]
        p_offset, p_vaddr, _, p_filesz, _, p_align = struct.unpack("<6Q", ph[k + 8:k + 56])
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz, p_align))
        elif p_type == 2:
            dyn = read(p_offset, p_filesz)
        elif p_type == 3:
            interp = read(p_offset, p_filesz).split(b"\0")[0].decode("latin-1")
        elif p_type == 4:  # notes: one owned by "Android" marks a build for Android's C library (bionic)
            n, o = read(p_offset, min(p_filesz, 65536)), 0
            while o + 12 <= len(n):
                namesz, descsz = struct.unpack("<II", n[o:o + 8])
                android = android or n[o + 12:o + 12 + namesz].rstrip(b"\0") == b"Android"
                o += 12 + (namesz + 3) // 4 * 4 + (descsz + 3) // 4 * 4

    def off(va):  # file offset of a virtual address
        for v, o, sz, _ in loads:
            if v <= va < v + sz:
                return o + va - v
        return -1
    tags, needed = {}, []
    for k in range(0, len(dyn) - 15, 16):
        tag, val = struct.unpack("<qQ", dyn[k:k + 16])
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        else:
            tags.setdefault(tag, val)
    st = read(off(tags[5]), tags.get(10, 1 << 20)) if 5 in tags else b""

    def string(o):
        e = st.find(b"\0", o)
        return st[o:e if e >= 0 else len(st)].decode("latin-1")
    names, vers, vlib = [string(n) for n in needed], [], {}
    osname = [s for n, s in (("libc.so.7", "FreeBSD"), ("libc.so.12", "NetBSD"), ("libc.so.1", "Solaris")) if n in names] + [
        "OpenBSD" for n in names if re.match(r"libc\.so\.[0-9]+\.[0-9]+$", n)]
    if osname:  # the C library of another system
        return add(name, box, head + " (a %s build; Linux does not load it)" % osname[0])
    o = off(tags[0x6FFFFFFE]) if 0x6FFFFFFE in tags else -1  # DT_VERNEED: the versions needed, by library
    for _ in range(tags.get(0x6FFFFFFF, 0) if o >= 0 else 0):
        vn = read(o, 16)
        if len(vn) < 16:
            break
        _, cnt, vfile, aux, nxt = struct.unpack("<HHIII", vn)
        a = o + aux
        for _ in range(cnt):
            va = read(a, 16)
            if len(va) < 16:
                break
            vname, anxt = struct.unpack("<II", va[8:16])
            vers.append((string(vfile), string(vname)))
            vlib[struct.unpack("<H", va[6:8])[0] & 0x7FFF] = string(vfile)  # .gnu.version index of this version need
            if not anxt:
                break
            a += anxt
        if not nxt:
            break
        o += nxt

    def top(prefix, lib):  # highest version with this prefix needed from the libraries lib() accepts
        v = [n[len(prefix):] for f, n in vers if n.startswith(prefix) and lib(f) and re.match(r"[0-9.]+$", n[len(prefix):])]
        return max(v, key=vkey) if v else ""
    glibc = top("GLIBC_", GLIBC_LIBS.match)  # from glibc's own libraries only, not from libgcc_s or others
    relr = any(n == "GLIBC_ABI_DT_RELR" and GLIBC_LIBS.match(f) for f, n in vers)  # pack-relative relocations, glibc 2.36
    imports = glibc_imports(read, vlib, GLIBC_LIBS.match) if any(GLIBC_LIBS.match(f) for f, _ in vers) else []
    syms_read = has_dynsym(read)  # whether the imports could be read at all
    cxx = top("GLIBCXX_", lambda f: f.startswith("libstdc++"))
    if "libc.so" in names or interp.startswith("/system/"):
        libc = "android" if android or interp.startswith("/system/") else "musl"
    elif any(n.startswith("libc.musl") for n in names) or "ld-musl" in interp:
        libc = "musl"
    elif any(GLIBC_LIBS.match(n) for n in names) or "ld-linux" in interp:
        libc = "glibc"
    elif not names and not interp:
        libc = "needs no C library"
    else:
        libc = "C library not named"
    align = min(a for _, _, _, a in loads) if loads else 0
    voff = min([(v - o) & (o - v) for v, o, _, _ in loads if v != o] or [0])  # largest power of two dividing p_vaddr - p_offset
    desc = head + ", " + libc + "".join(", " + x for x in ("GLIBC_" + glibc if glibc else "", "GLIBCXX_" + cxx if cxx else "") if x)
    desc += (", LOAD align %#x" % align if loads else "") + (", vaddr-offset align %#x" % voff if 0 < voff < 0x10000 else "")
    desc += ", needs " + " ".join(names) if names else ""
    e = add(name, box, desc, loadable=True, arch=arch, libc=libc, glibc=glibc, cxx=cxx, vers=vers, needed=names, soname=string(tags[14]) if 14 in tags else "",
            interp=interp, imports=imports)
    p, c = e["probs"], e["checks"]
    if other:
        return p.append("not aarch64, " + head)
    e["small"] = bool(loads) and (align < 0x10000 or 0 < voff < 0x10000)
    if LIBC == "musl" and GNU_EXT.search(name):  # CPython on musl imports no module by this name
        p.append("module named for a glibc Python (%s): CPython 3.11 and later on musl import only -linux-musl.so, "
                 ".abi3.so and .so modules, so this file is never loaded (the package falls back to pure Python or fails to "
                 "import)" % GNU_EXT.search(name).group(0))
    elif libc == "android":
        p.append("Android build (bionic C library), not for glibc or musl")
    elif libc == "musl" and LIBC == "glibc":
        p.append("musl build; the target uses glibc")
    elif libc == "glibc" and LIBC == "musl":
        own = [n for n in names if GLIBC_LIBS.match(n)]
        refused = (["interpreter " + interp] if "ld-linux" in interp else []) + [
            n for n in own if not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
        image = root_has(ROOT, refused)  # the image's own files (gcompat's glibc loader, for example)
        refused = [n for n in refused if n not in image]
        if refused:
            p.append("glibc build; musl's loader does not provide " + ", ".join(refused))
        else:
            known = bool(ROOT and ROOT["musl_syms"])  # musl's own symbols were read from the image
            missing, preload = musl_resolve(imports, ROOT, names) if known else ([], [])
            if missing:  # Python imports with RTLD_NOW: a symbol the target does not define fails the import
                p.append("glibc build; the target's musl does not define %s%s (imported from %s): Python imports extension modules with RTLD_NOW, so the import fails with symbol not found" % (", ".join(missing[:4]), " and %d more" % (len(missing) - 4) if len(missing) > 4 else "", ", ".join(own)))
            elif not known:
                c.append(musl_check(own, image, [n for n in names if n not in own]))
            elif not syms_read:  # no symbol table read: nothing was resolved, which is not a pass
                c.append(musl_unread())
            elif preload:
                c.append(musl_preload(preload, ROOT))
            # with the image's files and every import defined by musl: OK, as on a glibc image
    if LIBC == "glibc" and ROOT and libc not in ("musl", "android"):
        p.extend(root_needs(vers, ROOT))  # the versions each library of the image defines
    if ROOT:  # a library the file needs from the image's own set that the image does not have (the loaders aside: the C library found names them)
        gone = [n for n in names if n in ROOT_LIBS and not n.startswith("ld-") and n not in ROOT["defs"] and not (LIBC == "musl" and GLIBC_LIBS.match(n))]
        if gone:
            p.append("needs %s, which the image does not have" % ", ".join(gone))
    if ROOT and libc in ("glibc", "musl") and not (LIBC == "musl" and libc == "glibc" and not ROOT["musl_syms"]) and (
            ROOT["libs"] or LIBC == "musl" and (ROOT["files"] or libc == "glibc")):  # judged once every scanned file is known
        e["lack"] = [n for n in names if n not in ROOT_LIBS and not GLIBC_LIBS.match(n) and not n.startswith("ld-")
                     and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)) and n not in ROOT["libs"]
                     and n not in ROOT["files"] and not root_has(ROOT, [n])]
    if LIBC == "glibc" and VER and glibc and libc != "musl" and vkey(glibc) > vkey(VER):
        p.append("needs GLIBC_%s; the target has glibc %s" % (glibc, VER))
    if LIBC == "glibc" and VER and relr and libc != "musl" and vkey(VER) < (2, 36):
        p.append("needs GLIBC_ABI_DT_RELR (pack-relative relocations, glibc 2.36 or later); the target has glibc %s" % VER)
    if LIBC == "glibc" and CXX and cxx and vkey(cxx) > vkey(CXX):  # musl's loader checks no symbol versions
        p.append("needs GLIBCXX_%s; the target's libstdc++ provides up to GLIBCXX_%s" % (cxx, CXX))
    if PAGE and loads:
        # glibc 2.34 and earlier refuse a PT_LOAD whose p_align is not a multiple of the page size; glibc 2.35 and
        # later, and musl, need p_vaddr - p_offset to be one. Unknown glibc version: both rules.
        old = not (LIBC == "musl" or REL and vkey(REL) >= (2, 35))
        new = not (LIBC == "glibc" and REL and vkey(REL) < (2, 35))
        bad = [a for _, _, _, a in loads if a % PAGE]
        if old and bad:
            p.append("LOAD align %#x is not a multiple of the %d-byte page size" % (min(bad), PAGE))
        if new and any((v - o) % PAGE for v, o, _, _ in loads):
            p.append("LOAD vaddr-offset align %#x is not a multiple of the %d-byte page size" % (voff, PAGE))

def archive(name, box, data):  # static library: the object files it holds
    o, m, other = 8, collections.Counter(), collections.Counter()
    while o + 60 <= len(data):
        try:
            size = int(data[o + 48:o + 58].decode("ascii").strip() or "0")
        except ValueError:
            break
        tag = data[o:o + 16].rstrip()
        skip = int(tag[3:]) if tag.startswith(b"#1/") and tag[3:].isdigit() else 0  # BSD ar: the name comes first
        h = data[o + 60 + skip:o + 60 + skip + 20]
        if h[:4] == b"\x7fELF" and len(h) == 20:
            m[struct.unpack(">H" if h[5] == 2 else "<H", h[18:20])[0]] += 1
        elif h[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
            other["Mach-O"] += 1
        o += 60 + size + (size & 1)
    if not m:
        return add(name, box, "static archive with no ELF members%s: another system's format" % (
            " (%s objects)" % ", ".join(sorted(other)) if other else ""))
    e = add(name, box, "static archive, ELF objects by e_machine %s" % dict(sorted(m.items())))
    if 183 not in m:
        e["checks"].append("static library with no aarch64 code (%s); a native arm64 build that links it fails" % (
            ", ".join("e_machine %d (%s)" % (k, ARCH.get(k, "other")) for k in sorted(m))))

MAX_DEPTH = 8  # archives nested deeper than this are reported as CHECK, not read
MAX_MEMBER = 1 << 30  # an archive member declared larger than this (1 GiB) is a CHECK, not read
MAX_HELD = 1 << 31  # the most archive data this scan keeps in memory at once (2 GiB): a nested archive is read
# from its parent's bytes, so the archives that hold a member stay in memory while it is read, and a member that
# would take them past this limit is a CHECK, not read. No member is read past its declared size, and only stored
# and deflated members are read (some zipfile versions do not bound bzip2 or LZMA output while decompressing), so
# however an archive is crafted, its members take at most about 2 GiB. A file outside an archive takes no more
# memory than its size on disk.

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

def unread(name, box, why):  # what the scan does not read is a CHECK, not a pass
    add(name, box, why)["checks"].append(why)

def digest(src):  # SHA-256 of a member's bytes or of a loose file, read in parts: copies of one file are one build
    if isinstance(src, bytes):
        return hashlib.sha256(src).hexdigest()
    s, pos = hashlib.sha256(), src.tell()
    src.seek(0)
    for b in iter(lambda: src.read(1 << 20), b""):
        s.update(b)
    src.seek(pos)
    return s.hexdigest()

def check(name, box, h, load, depth=1, held=0, size=0):  # size: an archive member's declared size, 0 for a loose file
    def fits():  # an archive member is read whole only within the limits; otherwise it is a CHECK
        if size > MAX_MEMBER:
            unread(name, box, "archive member of %d bytes, larger than the %d MiB this scan reads, not read"
                   % (size, MAX_MEMBER >> 20))
        elif held + size > MAX_HELD:
            unread(name, box, "archive member of %d bytes: with the %d bytes of the archives that hold it, more than "
                   "the %d MiB this scan keeps in memory at once, not read" % (size, held, MAX_HELD >> 20))
        else:
            return True
        return False
    try:
        if h[:4] == b"\x7fELF":
            if not fits():
                return
            src, n = load(), len(entries)
            elf(name, box, reader(src))
            for e in entries[n:]:
                e["sha"] = digest(src)
        elif h[:8] == b"!<arch>\n":
            if not fits():
                return
            src = load()
            archive(name, box, src if isinstance(src, bytes) else reader(src)(0, os.fstat(src.fileno()).st_size))
        elif h[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce") or \
                h[:4] == b"\xca\xfe\xba\xbe" and len(h) >= 8 and struct.unpack(">I", h[4:8])[0] < 30:  # a universal binary; other formats share the magic
            add(name, box, "Mach-O (a macOS build; Linux does not load it)")
        elif h[:2] == b"MZ" and len(h) >= 64 and h[struct.unpack("<I", h[60:64])[0]:][:4] == b"PE\0\0":
            add(name, box, "PE (a Windows build; Linux does not load it)")
        elif h[:4] == b"PK\x03\x04":
            if depth > MAX_DEPTH:
                return unread(name, box, "archive nested more than %d levels deep, not read" % MAX_DEPTH)
            if not fits():
                return
            src, other = load(), collections.Counter()  # compression methods of the members not read
            with zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes) else src) as z:
                for m in z.infolist():
                    if m.filename.endswith("/"):
                        continue
                    if m.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        other[m.compress_type] += 1
                        continue
                    try:
                        with z.open(m) as f:
                            mh = f.read(4096)
                    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error,
                            ValueError) as e:  # one member that cannot be read: the others are still read
                        unread(name + "!" + m.filename, name, "could not read (%s)" % e)
                        continue
                    check(name + "!" + m.filename, name, mh, lambda m=m, z=z: read_member(z, m), depth + 1,
                          held + size, m.file_size)
            if other:
                unread(name, box, "%d archive member(s) compressed with method %s, not read: only stored and deflated "
                       "members are read" % (sum(other.values()), ", ".join(str(k) for k in sorted(other))))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error, struct.error,
            ValueError) as e:  # RuntimeError: an encrypted member
        unread(name, box, "could not read (%s)" % e)

def library(name):  # the builds of one library share this name
    n = name.rsplit("!", 1)[-1].rsplit("/", 1)[-1].lower()
    ext = re.match(r"(.+?)\.(cpython-|pypy|abi3\.)", n)  # a Python extension module: the name before its suffix
    if ext and n.endswith(".so"):
        return ext.group(1)
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
    """The builds of one library share this key: its name without architecture and C library parts (library),
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
    return "/".join(out), library(path) + (m.group(1) if m else "")

def x86_refused(x):  # what an x86-64 glibc build needs that musl's loader does not answer itself and the image lacks;
    # the image's glibc loader (gcompat) stands in for the x86-64 one, which the image's x86-64 variant would carry instead
    names = (["interpreter " + x.get("interp", "")] if "ld-linux" in x.get("interp", "") else []) + [
        n for n in x.get("needed", []) if GLIBC_LIBS.match(n) and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
    image = root_has(ROOT, [n for n in names if "ld-linux" not in n])
    return [n for n in names if n not in image and not ("ld-linux" in n and ROOT and ROOT["glibc_loader"])]

def baseline(e, g, problem):  # the same glibc, libstdc++ or musl-loader problem in the x86-64 build: not a Graviton change
    for x in g:
        same = e["arch"] == "aarch64" and x["arch"] == "x86-64" and x["libc"] == e["libc"]
        shared = root_shared([problem], x.get("vers", [])) if same else ""
        need = x86_refused(x) if same and problem.startswith("glibc build; musl") and not any(  # no x86-64 musl build
            y["libc"] == "musl" for y in g if y.get("arch") == "x86-64") else []
        if shared or need:
            return "; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                x["name"], shared or ", ".join(need))
        syms = [n for n in x.get("imports", []) if n in musl_resolve(e.get("imports", []), ROOT)[0]] if (
            same and ROOT and ROOT.get("musl_syms") and problem.startswith("glibc build; the target's musl does not define") and not any(
                y["libc"] == "musl" for y in g if y.get("arch") == "x86-64")) else []
        if syms:  # the same missing symbol in the x86-64 build: the import fails on x86-64 hosts with this image too
            return "; the x86-64 build %s imports %s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                x["name"], ", ".join(syms[:4]))
    for key, prefix, tgt in (("glibc", "needs GLIBC_", VER), ("cxx", "needs GLIBCXX_", CXX)):
        if not (problem.startswith(prefix) and tgt and e["arch"] == "aarch64"):
            continue
        for x in g:
            if x["arch"] == "x86-64" and x["libc"] == e["libc"] and x[key] and vkey(x[key]) > vkey(tgt):
                return "; the x86-64 build %s needs %s%s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                    x["name"], prefix[6:], x[key])
    return ""

tl = "target: " + LIBC + (" (assumed)" if ASSUMED else "") + (", with a glibc loader" if ROOT and ROOT["glibc_loader"] else "")
if LIBC == "glibc":
    tl += (" " + REL) if REL else (", glibc release not read" if ROOT else ", glibc version not given")
elif VER:
    tl += " " + VER
TCXX = CXX or (ROOT["glibcxx"] if ROOT else "")
tl += (", page size %d" % PAGE if PAGE else ", page size not given") + (", libstdc++ GLIBCXX_" + TCXX if TCXX and LIBC == "glibc" else "")
print(tl + root_read_from(ROOT))
missing = [p for p in sys.argv[1:] if not os.path.exists(p)]
for p in missing:
    print("no such file or directory:", p)
empty = []  # path arguments whose folder holds no files
for top in sys.argv[1:]:
    walk, seen = [(os.path.dirname(top), [], [os.path.basename(top)])] if os.path.isfile(top) else os.walk(top), 0
    for root, dirs, files in walk:
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "graviton-validation")
                   and not os.path.exists(os.path.join(root, d, "pyvenv.cfg"))
                   and not os.path.isdir(os.path.join(root, d, "conda-meta"))]
        for n in files:
            p = os.path.join(root, n)
            if os.path.isfile(p) and not os.path.islink(p):
                seen += 1
                with open(p, "rb") as f:
                    check(p, top, f.read(4096), lambda f=f: f)
    if os.path.isdir(top) and not seen:  # a copy or build that produced nothing is not a pass
        empty.append(top)

findings, checks, notes, groups = [], [], [], collections.OrderedDict()
checks += ["%s: holds no files: the copy or build that should have filled it produced none" % p for p in empty]
if ROOT and IGNORED:
    notes.append("%s set but not used: TARGET_ROOT gives the C library and its versions" % ", ".join(IGNORED))
notes.extend(libs_notes(ROOT))
SHIPPED = set(x for e in entries if e.get("arch") == "aarch64" and e.get("loadable") for x in (e["name"].rsplit("!", 1)[-1].rsplit("/", 1)[-1], e.get("soname")) if x)  # the aarch64 libraries the scanned files ship, by file name and by SONAME (a library loaded by path answers a later need for its SONAME)
for e in entries:
    left = [n for n in e.get("lack", []) if n not in SHIPPED]
    if left and not e["probs"]:  # another library it needs that the image does not have
        e["checks"].append(needs_other(left, ROOT))
for e in entries:
    if e["loadable"]:
        groups.setdefault((e["box"], group_key(e["name"])), []).append(e)
    else:
        if e["checks"]:
            checks.append("%s: %s" % (e["name"], "; ".join(e["checks"])))
for (box, key), g in groups.items():
    ok = [e for e in g if not e["probs"]]
    if ok:  # the build for the target (no CHECK and its C library first) is judged; the other builds get no flag
        pick = sorted(ok, key=lambda e: (bool(e["checks"]), e["libc"] not in (LIBC, "needs no C library")))[0]
        for e in g:
            e["replaced"] = e is not pick  # another build of the library is the one for the target
        if pick["checks"]:
            checks.append("%s: %s" % (pick["name"], "; ".join(pick["checks"])))
        builds = len(set(e.get("sha") or e["name"] for e in g))  # copies of one file are one build
        if builds > 1:
            notes.append("%s: %d Linux builds in %s; %s is the build for this target; confirm in Phase 3 that it is the "
                         "one loaded" % (library(pick["name"]), builds, "the scanned files" if box in sys.argv[1:] else box, pick["name"]))
        continue
    arm = [e for e in g if e["arch"] == "aarch64"]
    primary = ([e for e in arm if e["libc"] in (LIBC, "needs no C library")] or [e for e in arm if e["libc"] != "android"]
               or arm or [e for e in g if e["arch"] == "x86-64"][:1] or g[:1])
    for e in g:
        e["replaced"] = e not in primary
    for e in primary:  # the build the target would load carries the finding
        findings.append("%s: %s" % (e["name"], "; ".join(x + baseline(e, g, x) for x in e["probs"])))
        if e["checks"]:
            checks.append("%s: %s" % (e["name"], "; ".join(e["checks"])))
small = sorted(e["name"] for e in entries if e["small"] and not e.get("replaced"))
if small and not PAGE:
    notes.insert(0, "%d aarch64 file(s) aligned for 4 KB pages only (%s%s): a kernel with 64 KB pages refuses them; give "
                    "the page size if the target uses 64 KB pages" % (len(small), ", ".join(small[:5]),
                                                                       " and %d more" % (len(small) - 5) if len(small) > 5 else ""))
for e in sorted(entries, key=lambda x: x["name"]):
    print("%s: %s" % (e["name"], e["desc"]))
print("ELF files by e_machine:", dict(sorted(machines.items())))
for x in sorted(findings):
    print("FINDING " + x)
for x in sorted(checks):
    print("CHECK " + x)
for x in notes:
    print("NOTE " + x)
print("findings: %d, checks: %d" % (len(findings), len(checks)))
sys.exit(2 if missing else 1 if findings else 0)
