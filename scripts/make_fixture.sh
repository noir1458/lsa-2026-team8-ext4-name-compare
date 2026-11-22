#!/usr/bin/env bash
# Make the test image once, on the VM, as root: a new 128 MiB ext4 image file
# with directories of 10,000 empty files each. Never touches a real disk.
#
# Usage: make_fixture.sh <work-dir> [round2]
#   (none)  round 1: fixtures/leaf.img, four directories, results/
#   round2  round 2: fixtures/round2.img, the same four plus sametail, results/round2/
set -euo pipefail
root=${1:?work directory}
round=${2:-}
[[ $EUID = 0 && -d $root/scripts ]]
case $round in
  "")     image="$root/fixtures/leaf.img"; out="$root/results"
          cases=short13,long128,random128,varied; inodes=55000 ;;
  round2) image="$root/fixtures/round2.img"; out="$root/results/round2"
          cases=short13,long128,random128,varied,sametail; inodes=66000 ;;
  *) echo "unknown round: $round" >&2; exit 2 ;;
esac
mount_dir="$root/fixtures/leaf-mount"
[[ ! -e $image && ! -e $mount_dir && ! -e $out/names ]] || { echo 'fresh destinations required' >&2; exit 2; }
mkdir -p "$root/fixtures" "$out"
mkdir "$mount_dir"
truncate -s 128M "$image"
mkfs.ext4 -q -F -b 4096 -I 256 -N "$inodes" -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=11111111-2222-3333-4444-555555555555 "$image"
mount -o loop,noatime "$image" "$mount_dir"
python3 "$root/scripts/make_names.py" --parent "$mount_dir/leaf" --output "$out/names" --files 10000 --cases "$cases"
for name in ${cases//,/ }; do
  lsattr -d "$mount_dir/leaf/$name"
done > "$out/fixture-flags.txt"
tune2fs -l "$image" > "$out/fixture-filesystem.txt"
sync
umount "$mount_dir"
rmdir "$mount_dir"
e2fsck -fn "$image" > "$out/fixture-fsck.log" 2>&1
