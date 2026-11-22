#!/usr/bin/env python3
"""Correctness check for a kernel where the tail prefilter is always on.

The final patch (patches/0004-tail-prefilter-only.patch) has no sysfs switch, so
this runs one mutation sequence (rename, hardlink, unlink, cross-directory
rename, replace, recreate) on the running kernel. It also adds names that share their last 8 bytes but differ earlier,
which is the case the prefilter must not confuse. The same script passes on the
stock B0 kernel, so the two kernels can be compared on identical checks.

Only a new check-tail-UUID directory under --root is modified, and it is removed
on success. Example:
  sudo python3 scripts/check_correctness.py --root /mnt/check --files 1200 \
      --drop-caches 2 --require-index --output results/correctness.json
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import traceback
import uuid

from collections import Counter
import errno
import fcntl
import hashlib
import time

# Linux FS_IOC_GETFLAGS on x86_64 and the ext4 htree index flag.
FS_IOC_GETFLAGS = 0x80086601
EXT4_INDEX_FL = 0x1000

def flags_for(fd):
    try:
        import array
        buf = array.array("l", [0])
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, buf, True)
        flags = int(buf[0])
        return {"flags_hex": hex(flags), "index_flag": bool(flags & EXT4_INDEX_FL)}
    except (OSError, ValueError) as exc:
        return {"flags_hex": None, "index_flag": None, "error": str(exc)}


def create_file(fd, name, data):
    out = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=fd)
    try:
        view = memoryview(data)
        while view:
            written = os.write(out, view)
            if not written:
                raise OSError("zero-length write")
            view = view[written:]
        st = os.fstat(out)
        return {"dev": st.st_dev, "ino": st.st_ino, "data": data}
    finally:
        os.close(out)


def check_absent(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        if exc.errno == errno.ENOENT:
            return
        raise
    raise AssertionError("expected ENOENT for %s" % name)


def verify_tree(fds, expected, stage, drop_caches, absent=()):
    if drop_caches:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text(str(drop_caches) + "\n")
    links = Counter((x["dev"], x["ino"]) for items in expected.values() for x in items.values())
    digest = hashlib.sha256()
    identities = hashlib.sha256()
    count = 0
    start = time.monotonic_ns()
    for dirname in sorted(fds):
        fd = fds[dirname]
        names = sorted(os.listdir(fd))
        if names != sorted(expected[dirname]):
            raise AssertionError("%s: directory names differ at %s" % (dirname, stage))
        for name in names:
            want = expected[dirname][name]
            got = os.stat(name, dir_fd=fd, follow_symlinks=False)  # fstatat
            if not stat.S_ISREG(got.st_mode):
                raise AssertionError("non-regular entry: %s/%s" % (dirname, name))
            if (got.st_dev, got.st_ino) != (want["dev"], want["ino"]):
                raise AssertionError("wrong inode returned: %s/%s at %s" % (dirname, name, stage))
            if got.st_nlink != links[(got.st_dev, got.st_ino)]:
                raise AssertionError("wrong link count: %s/%s" % (dirname, name))
            if got.st_size != len(want["data"]):
                raise AssertionError("wrong file size: %s/%s" % (dirname, name))
            opened = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            try:
                fst = os.fstat(opened)
                data = os.read(opened, len(want["data"]) + 1)
            finally:
                os.close(opened)
            if (fst.st_dev, fst.st_ino) != (want["dev"], want["ino"]) or data != want["data"]:
                raise AssertionError("wrong open/content: %s/%s" % (dirname, name))
            # This hash ignores inode allocation, so it can match after recreation.
            key = (dirname + "/" + name).encode()
            digest.update(len(key).to_bytes(4, "little") + key)
            digest.update(len(data).to_bytes(4, "little") + data)
            digest.update(got.st_nlink.to_bytes(4, "little"))
            identities.update(key + (":%d:%d" % (got.st_dev, got.st_ino)).encode())
            count += 1
        for i in range(16):
            check_absent(fd, "absent_%s_%02d" % (stage, i))
    for dirname, name in absent:
        check_absent(fds[dirname], name)
    return {"stage": stage, "files": count,
            "directory_counts": {k: len(v) for k, v in expected.items()},
            "content_name_nlink_sha256": digest.hexdigest(),
            "identity_sha256": identities.hexdigest(),
            "negative_checks": len(fds) * 16 + len(absent),
            "verification_elapsed_ns": time.monotonic_ns() - start,
            "drop_caches": drop_caches}


def run_mode(fds, expected, label, drop_caches, baseline_hash, stages):
    a, b = fds["src"], fds["dst"]
    def verify(step, absent=()):
        result = verify_tree(fds, expected, label + "_" + step, drop_caches, absent)
        stages.append(result)
        return result
    verify("before")
    # 1. Same-directory rename must preserve inode identity.
    os.rename("file_00000000", "renamed_00000000", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["renamed_00000000"] = expected["src"].pop("file_00000000")
    verify("rename", [("src", "file_00000000")])
    # 2. Link, then remove the original; the remaining name must stay valid.
    os.link("file_00000001", "hardlink_00000001", src_dir_fd=a, dst_dir_fd=a, follow_symlinks=False)
    expected["src"]["hardlink_00000001"] = expected["src"]["file_00000001"]
    verify("hardlink")
    os.unlink("file_00000001", dir_fd=a)
    expected["src"].pop("file_00000001")
    verify("unlink_original", [("src", "file_00000001")])
    # 3. Move to another indexed directory and check both namespaces.
    os.rename("file_00000002", "cross_00000002", src_dir_fd=a, dst_dir_fd=b)
    expected["dst"]["cross_00000002"] = expected["src"].pop("file_00000002")
    verify("cross_rename", [("src", "file_00000002")])
    # 4. Replace an existing destination. Retain its old inode via a hardlink
    # so the fixture can be restored without hiding a wrong-inode result.
    os.link("file_00000003", "saved_00000003", src_dir_fd=b, dst_dir_fd=b, follow_symlinks=False)
    expected["dst"]["saved_00000003"] = expected["dst"]["file_00000003"]
    os.rename("file_00000003", "file_00000003", src_dir_fd=a, dst_dir_fd=b)
    expected["dst"]["file_00000003"] = expected["src"].pop("file_00000003")
    verify("replace_rename", [("src", "file_00000003")])
    # 5. Cache a missing name after unlink; recreation must invalidate it.
    old_data = expected["src"]["file_00000004"]["data"]
    os.unlink("file_00000004", dir_fd=a)
    expected["src"].pop("file_00000004")
    verify("unlink", [("src", "file_00000004")])
    expected["src"]["file_00000004"] = create_file(a, "file_00000004", b"recreated:" + old_data)
    verify("recreate")
    # Restore names, content and link counts for a comparable next policy.
    os.rename("renamed_00000000", "file_00000000", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["file_00000000"] = expected["src"].pop("renamed_00000000")
    os.rename("hardlink_00000001", "file_00000001", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["file_00000001"] = expected["src"].pop("hardlink_00000001")
    os.rename("cross_00000002", "file_00000002", src_dir_fd=b, dst_dir_fd=a)
    expected["src"]["file_00000002"] = expected["dst"].pop("cross_00000002")
    os.rename("file_00000003", "file_00000003", src_dir_fd=b, dst_dir_fd=a)
    expected["src"]["file_00000003"] = expected["dst"].pop("file_00000003")
    os.rename("saved_00000003", "file_00000003", src_dir_fd=b, dst_dir_fd=b)
    expected["dst"]["file_00000003"] = expected["dst"].pop("saved_00000003")
    os.unlink("file_00000004", dir_fd=a)
    expected["src"]["file_00000004"] = create_file(a, "file_00000004", old_data)
    final = verify("restored", [("src", "renamed_00000000"), ("src", "hardlink_00000001"),
                                 ("dst", "cross_00000002"), ("dst", "saved_00000003")])
    if final["content_name_nlink_sha256"] != baseline_hash:
        raise AssertionError("restored content/name/link digest differs from baseline")
    return stages



# Present names. Pairs share the last 8 bytes and the length but differ before.
EDGE_PRESENT = [
    "aaaa_00000001", "bbbb_00000001",          # 13 bytes, same tail
    "p" * 120 + "00000001", "q" * 120 + "00000001",  # 128 bytes, differ at byte 0
    "12345678", "12345679",                    # exactly 8 bytes
    "1234567",                                 # 7 bytes, below the threshold
    "x12345678",                               # 9 bytes, tail equals "12345678"
]
# Absent names that share a tail (and length) with a present name.
EDGE_ABSENT = [
    "cccc_00000001", "aaaa_00000002", "r" * 120 + "00000001", "12345670",
    "y12345678", "aaaa_0000000", "aaaa_000000010", "1234568",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--files", type=int, default=1200)
    parser.add_argument("--drop-caches", type=int, choices=[0, 2, 3], default=2)
    parser.add_argument("--require-index", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir() or args.files < 1001:
        parser.error("root must be a directory and --files must be >= 1001")
    if args.output and args.output.exists():
        parser.error("output already exists")
    switch = Path("/sys/module/ext4/parameters/leaf_prefilter")
    fixture = root / ("check-tail-" + uuid.uuid4().hex)
    fixture.mkdir(mode=0o700)
    identity = (fixture.stat().st_dev, fixture.stat().st_ino)
    fds = {}
    expected = {"src": {}, "dst": {}}
    report = {"schema": 1, "kernel": platform.release(),
              "experiment_switch_present": switch.exists(),
              "fixture": str(fixture), "files_per_directory": args.files,
              "drop_caches": args.drop_caches, "edge_present": EDGE_PRESENT,
              "edge_absent": EDGE_ABSENT, "result": "FAIL", "stages": [],
              "note": "Correctness only; verification_elapsed_ns is not a benchmark."}
    success = False
    try:
        for dirname in expected:
            directory = fixture / dirname
            directory.mkdir(mode=0o700)
            fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
            fds[dirname] = fd
            for i in range(args.files):
                name = "file_%08d" % i
                data = ("%s payload %08d\n" % (dirname, i)).encode()
                expected[dirname][name] = create_file(fd, name, data)
        for name in EDGE_PRESENT:
            expected["src"][name] = create_file(fds["src"], name, ("edge %s\n" % name).encode())
        report["directory_flags"] = {name: flags_for(fd) for name, fd in fds.items()}
        if args.require_index and not all(x["index_flag"] is True
                                          for x in report["directory_flags"].values()):
            raise AssertionError("both directories must have EXT4_INDEX_FL")
        absent = [("src", name) for name in EDGE_ABSENT]
        baseline = verify_tree(fds, expected, "initial", args.drop_caches, absent)
        report["baseline"] = baseline
        run_mode(fds, expected, "fixed", args.drop_caches,
                 baseline["content_name_nlink_sha256"], report["stages"])
        final = verify_tree(fds, expected, "final", args.drop_caches, absent)
        report["stages"].append(final)
        if final["content_name_nlink_sha256"] != baseline["content_name_nlink_sha256"]:
            raise AssertionError("final digest differs from baseline")
        success = True
    except BaseException as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
    finally:
        for fd in fds.values():
            os.close(fd)
    if success:
        try:
            st = fixture.lstat()
            if not stat.S_ISDIR(st.st_mode) or (st.st_dev, st.st_ino) != identity:
                raise AssertionError("fixture identity changed; refusing cleanup")
            shutil.rmtree(str(fixture))
            report["result"] = "PASS"
            report["fixture_retained"] = False
        except BaseException as exc:
            report["cleanup_error"] = "%s: %s" % (type(exc).__name__, exc)
            success = False
    if not success:
        report["fixture_retained"] = True
        print("FAIL: retained private fixture at %s" % fixture, file=sys.stderr)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as out:
            out.write(text)
    sys.stdout.write(text)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
