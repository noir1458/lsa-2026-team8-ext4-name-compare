#!/usr/bin/env python3
"""Load the original and the patched pxt4 module in turn and read the calclock numbers.

One measurement is what the practical classes do by hand:
  insmod jbd3, pxt4 -> mount -t pxt4 -> one workload -> umount -> rmmod -> dmesg
The modules print their numbers at rmmod, so every measurement starts from zero.
Both modules run on the same booted kernel. The order is orig, tail, tail, orig, ...
The image is mounted read-only and read once through the loop device first, so the
directory blocks are in the page cache; dentries and inodes are dropped (drop_caches=2).
The script re-runs itself in a private mount namespace, so the desktop (gvfs, tracker) does
not see the test mount: it would keep the mount busy and add lookups of its own.

time-*  modules: calclock on pxt4_lookup() and pxt4_search_dir()
count-* modules: ds_monitoring in pxt4_match(), counting where each entry is decided
  (a separate build, because counting every entry slows the comparison down)

Example: sudo python3 calclock/run_calclock.py --expected-kernel 5.4.214-b0 --modules ~/pxt4-out
  --work ~/lsa-ext4-name-compare --output results/calclock --reps 20 --cpu 0
"""
import argparse
import csv
import hashlib
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

CALC = re.compile(r"(pxt4_lookup|pxt4_search_dir|empty_pair) is called ([\d,]+) times, and the time interval is ([\d,]+)ns")
COUNT = re.compile(r"name_compare (\w+): (\d+) times")
CASES = ("short13", "long128", "random128", "varied", "sametail")


def sh(*cmd):
    return subprocess.run(list(cmd), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


def loaded():
    return {line.split()[0] for line in Path("/proc/modules").read_text().splitlines()}


def insmod(path):
    for dep in sh("modinfo", "-F", "depends", str(path)).strip().split(","):
        if dep and dep not in ("jbd3", "pxt4"):
            sh("modprobe", dep)
    sh("insmod", str(path))


def retry(*cmd):
    for _ in range(50):
        r = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode == 0:
            return
        time.sleep(0.2)
    raise SystemExit("%s failed: %s" % (" ".join(cmd), r.stderr.decode()))


def cleanup(mnt):
    if os.path.ismount(mnt):
        retry("umount", str(mnt))
    for m in ("pxt4", "jbd3"):
        if m in loaded():
            retry("rmmod", m)


def measure(mods, image, mnt, command, cpu, tag):
    if loaded() & {"pxt4", "jbd3"}:
        raise SystemExit("pxt4/jbd3 already loaded")
    insmod(mods / "jbd3" / "jbd3.ko")
    insmod(mods / "pxt4.ko")
    sh("mount", "-t", "pxt4", "-o", "loop,ro,noatime", str(image), str(mnt))
    if sh("findmnt", "-n", "-o", "FSTYPE", str(mnt)).strip() != "pxt4":
        raise SystemExit("not mounted as pxt4")
    device = sh("findmnt", "-n", "-o", "SOURCE", str(mnt)).strip()
    sh("dd", "if=" + device, "of=/dev/null", "bs=1M")
    os.sync()
    Path("/proc/sys/vm/drop_caches").write_text("2\n")
    env = dict(os.environ, LC_ALL="C", TZ="UTC")
    start = time.monotonic_ns()
    r = subprocess.run(["taskset", "-c", str(cpu)] + command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    elapsed = time.monotonic_ns() - start
    if r.returncode or r.stderr:
        raise SystemExit("workload failed: %r" % r.stderr[:300])
    retry("umount", str(mnt))
    Path("/dev/kmsg").write_text("name-calclock %s\n" % tag)
    retry("rmmod", "pxt4")
    retry("rmmod", "jbd3")
    log = sh("dmesg").rsplit("name-calclock " + tag, 1)[1]
    return elapsed, r.stdout, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected-kernel", required=True)
    ap.add_argument("--modules", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--count-reps", type=int, default=2)
    ap.add_argument("--cpu", type=int, default=0)
    args = ap.parse_args()
    if platform.release() != args.expected_kernel:
        ap.error("unexpected kernel: " + platform.release())
    if args.output.exists():
        ap.error("output directory must be absent")
    if "NAME_CALCLOCK_NS" not in os.environ:
        os.environ["NAME_CALCLOCK_NS"] = "1"
        os.execvp("unshare", ["unshare", "--mount", "--propagation", "private", sys.executable] + sys.argv)
    fx, names = args.work / "fixtures", args.work / "results" / "round2" / "names"
    mnt = fx / "pxt4-mount"
    mnt.mkdir(exist_ok=True)
    work = [("ls_photos", fx / "photos.img", ["ls", "-l", "--color=never", str(mnt / "photos")])]
    for case in CASES:
        work.append(("lookup_" + case, fx / "round2.img",
                     [str(args.work / "bench" / "lookup_bench"), "--dir", str(mnt / "leaf" / case), "--names",
                      str(names / (case + ".names")), "--seed", "1", "--trial", "0", "--label", "calclock",
                      "--warm-dir"]))
    args.output.mkdir(parents=True)
    (args.output / "uname.txt").write_text(" ".join(os.uname()) + "\n")
    (args.output / "clocksource.txt").write_text(
        Path("/sys/devices/system/clocksource/clocksource0/current_clocksource").read_text())
    times, counts, hashes = [], [], {}
    try:
        for kind, reps in (("count", args.count_reps), ("time", args.reps)):
            for rep in range(reps):
                order = ("orig", "tail") if rep % 2 == 0 else ("tail", "orig")
                for name, image, command in work:
                    for variant in order:
                        tag = "%s-%s-%s-%d" % (kind, variant, name, rep)
                        elapsed, out, log = measure(args.modules / (kind + "-" + variant), image, mnt, command,
                                                    args.cpu, tag)
                        if name == "ls_photos":
                            hashes.setdefault(name, set()).add(hashlib.sha256(out).hexdigest())
                        else:
                            row = list(csv.DictReader(out.decode().splitlines()))[0]
                            if int(row["errors"]):
                                raise SystemExit("lookup error")
                            hashes.setdefault(name, set()).add(row["digest"])
                        base = {"workload": name, "variant": variant, "rep": rep}
                        if kind == "time":
                            found = {f: (int(n.replace(",", "")), int(t.replace(",", "")))
                                     for f, n, t in CALC.findall(log)}
                            if set(found) != {"pxt4_lookup", "pxt4_search_dir", "empty_pair"}:
                                raise SystemExit("calclock lines missing: " + tag + "\n" + log)
                            for f, (n, t) in found.items():
                                times.append(dict(base, function=f, calls=n, time_ns=t, program_ns=elapsed))
                        else:
                            found = dict((k, int(v)) for k, v in COUNT.findall(log))
                            for step in ("length_differs", "last_8_bytes_differ", "full_compare"):
                                counts.append(dict(base, step=step, entries=found.get(step, 0)))
                print(kind, "rep", rep, "done", flush=True)
    finally:
        cleanup(mnt)
    for path, rows in (("calclock.csv", times), ("counts.csv", counts)):
        with (args.output / path).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    with (args.output / "outputs.txt").open("w") as f:
        for name, h in sorted(hashes.items()):
            f.write("%s %s\n" % (name, " ".join(sorted(h))))
            if len(h) != 1:
                raise SystemExit("outputs differ between modules: " + name)


if __name__ == "__main__":
    main()
