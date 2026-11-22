#!/usr/bin/env bash
# One boot session: run on the VM as root after booting a kernel once.
#
# Usage: run_session.sh <work-dir> <expected-kernel> <session> <seed> [check|-] [round2]
#   session: a new name such as s1-b0 or s1-tail (results/sessions/<session>)
#   seed:    use the same seed for every kernel's session in one pair or block
#   check:   run the correctness check on a new 64 MiB image first
#   round2:  use fixtures/round2.img and write to results/round2/sessions/<session>
#
# The test image is mounted read-only, so every session sees the same directories.
set -euo pipefail
root=${1:?work directory}
kernel=${2:?expected kernel}
session=${3:?session name}
seed=${4:?seed}
check=${5:-}
round=${6:-}
cd "$root"
[[ $EUID = 0 ]]
[[ $(uname -r) = "$kernel" ]]
case $round in
  "")     leaf=fixtures/leaf.img; names=results/names; out="results/sessions/$session" ;;
  round2) leaf=fixtures/round2.img; names=results/round2/names; out="results/round2/sessions/$session" ;;
  *) echo "unknown round: $round" >&2; exit 2 ;;
esac
[[ ! -e $out ]] || { echo "session output exists: $out" >&2; exit 2; }
mkdir -p "$out"
trap 'echo $? > "$out/exit"' EXIT
mnt=fixtures/leaf-mount
if mountpoint -q "$mnt"; then echo "test image already mounted" >&2; exit 2; fi
uname -a > "$out/uname.txt"
cat /proc/cmdline > "$out/cmdline.txt"

if [[ $check = check ]]; then
  image="fixtures/check-$session.img"
  cmnt="fixtures/check-$session"
  [[ ! -e $image && ! -e $cmnt ]]
  truncate -s 64M "$image"
  mkfs.ext4 -q -F -b 4096 -I 256 "$image"
  mkdir "$cmnt"
  mount -o loop,noatime "$image" "$cmnt"
  python3 scripts/check_correctness.py --root "$cmnt" --files 1200 --drop-caches 2 \
    --require-index --output "$out/correctness.json" > /dev/null
  umount "$cmnt"
  rmdir "$cmnt"
  e2fsck -fn "$image" > "$out/correctness-fsck.log" 2>&1
  rm -f "$image"
fi

mkdir -p "$mnt"
mount -o loop,ro,noatime "$leaf" "$mnt"
python3 scripts/wait_idle.py > "$out/settle.log"
python3 scripts/capture_environment.py > "$out/environment.json"
python3 scripts/run_lookup.py --expected-kernel "$kernel" --bench bench/lookup_bench \
  --fixtures "$mnt/leaf" --names "$names" --output "$out/lookup" \
  --rounds 20 --modes warmdir,warm --drop-caches 2 --cpu 0 --seed "$seed" > "$out/lookup.log"
python3 scripts/run_ls.py --expected-kernel "$kernel" --fixtures "$mnt/leaf" \
  --names "$names" --output "$out/ls" --reps 20 --cpu 0 --seed "$seed" > "$out/ls.log"
umount "$mnt"
e2fsck -fn "$leaf" > "$out/leaf-fsck.log" 2>&1
