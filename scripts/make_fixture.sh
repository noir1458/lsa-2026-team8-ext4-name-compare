#!/usr/bin/env bash
# Make the test image once, on the VM, as root: a new 128 MiB ext4 image file
# with four directories of 10,000 empty files each. Never touches a real disk.
#
# Usage: make_fixture.sh <work-dir>
set -euo pipefail
root=${1:?work directory}
[[ $EUID = 0 && -d $root/scripts ]]
image="$root/fixtures/leaf.img"
mount_dir="$root/fixtures/leaf-mount"
[[ ! -e $image && ! -e $mount_dir && ! -e $root/results/names ]] || { echo 'fresh destinations required' >&2; exit 2; }
mkdir -p "$root/fixtures" "$root/results"
mkdir "$mount_dir"
truncate -s 128M "$image"
mkfs.ext4 -q -F -b 4096 -I 256 -N 55000 -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=11111111-2222-3333-4444-555555555555 "$image"
mount -o loop,noatime "$image" "$mount_dir"
python3 "$root/scripts/make_names.py" --parent "$mount_dir/leaf" --output "$root/results/names" --files 10000
for name in short13 long128 random128 varied; do
  lsattr -d "$mount_dir/leaf/$name"
done > "$root/results/fixture-flags.txt"
tune2fs -l "$image" > "$root/results/fixture-filesystem.txt"
sync
umount "$mount_dir"
e2fsck -fn "$image" > "$root/results/fixture-fsck.log" 2>&1
