#!/usr/bin/env python3
"""Create the four test directories (empty files) and the query lists.

Never formats or mounts a device; make_fixture.sh owns the image.
Example: make_names.py --parent /mnt/leaf/leaf --output results/names --files 10000
Both destination directories must be absent. The caller owns image setup.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import random
import string

CASES = ("short13", "long128", "random128", "varied")
ALPHABET = string.ascii_letters + string.digits


def make_names(case, count, seed):
    rng = random.Random(seed)
    names, seen = [], set()
    for i in range(count * 2):
        if case == "short13":
            name = "file_%08d" % i
        elif case == "long128":
            name = "p" * 120 + "%08d" % i
        elif case == "random128":
            name = "".join(rng.choice(ALPHABET) for _ in range(128))
            while name in seen:
                name = "".join(rng.choice(ALPHABET) for _ in range(128))
        else:
            # Repeat the same length histogram in positive and negative halves.
            length = (13, 32, 64, 128, 240)[(i % count) % 5]
            name = "".join(rng.choice(ALPHABET) for _ in range(length - 8)) + "%08d" % i
        if name in seen or not 1 <= len(name.encode("ascii")) <= 255:
            raise RuntimeError("duplicate or invalid generated name")
        seen.add(name)
        names.append(name)
    return names[:count], names[count:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--files", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--cases", default=",".join(CASES))
    args = parser.parse_args()
    cases = args.cases.split(",")
    if not 1 <= args.files <= 1000000 or len(set(cases)) != len(cases) or any(c not in CASES for c in cases):
        parser.error("invalid count or case list")
    args.parent = args.parent.resolve()
    args.output = args.output.resolve()
    if args.parent == args.output or args.parent in args.output.parents or args.output in args.parent.parents:
        parser.error("fixture and query-list directories must be separate")
    if args.parent.exists() or args.output.exists():
        parser.error("destinations must be absent; existing files are never replaced")
    args.parent.mkdir()
    args.output.mkdir()
    manifest = {"format": 1, "seed": args.seed, "files_per_case": args.files, "cases": []}
    for case in cases:
        case_seed = args.seed + CASES.index(case) * 1000003
        positive, negative = make_names(case, args.files, case_seed)
        directory = args.parent / case
        directory.mkdir()
        order = list(positive)
        random.Random(case_seed ^ 0xA110C).shuffle(order)
        for name in order:
            fd = os.open(str(directory / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.close(fd)
        query_text = "".join("1 " + name + "\n" for name in positive)
        query_text += "".join("0 " + name + "\n" for name in negative)
        query_file = args.output / (case + ".names")
        query_file.write_text(query_text, encoding="ascii")
        manifest["cases"].append({
            "case": case, "directory": case, "names_file": query_file.name,
            "positive": len(positive), "negative": len(negative),
            "positive_length_histogram": dict(sorted(collections.Counter(map(len, positive)).items())),
            "negative_length_histogram": dict(sorted(collections.Counter(map(len, negative)).items())),
            "names_sha256": hashlib.sha256(query_text.encode("ascii")).hexdigest(),
            "creation_order_sha256": hashlib.sha256("\n".join(order).encode("ascii")).hexdigest(),
        })
        print(json.dumps({"created": case, "files": len(positive)}), flush=True)
    os.sync() if hasattr(os, "sync") else None
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
