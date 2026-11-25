#!/usr/bin/env bash
# 사진 이름 폴더만 든 64 MiB 이미지를 한 번 만든다(VM에서 root로). 이름은 3차 측정의 real/photos와 같다.
# Usage: make_photos.sh <work-dir>
set -euo pipefail
root=${1:?work directory}
[[ $EUID = 0 ]]
image="$root/fixtures/photos.img"
mnt="$root/fixtures/photos-mount"
[[ ! -e $image && ! -e $mnt ]] || { echo 'fresh destinations required' >&2; exit 2; }
mkdir -p "$mnt"
truncate -s 64M "$image"
mkfs.ext4 -q -F -b 4096 -I 256 -N 11000 -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=11111111-2222-3333-4444-555555555555 "$image"
mount -o loop,noatime "$image" "$mnt"
mkdir "$mnt/photos"
for i in $(seq 1 9999); do : > "$mnt/photos/$(printf 'IMG_%04d.JPG' "$i")"; done
lsattr -d "$mnt/photos"
ls "$mnt/photos" | wc -l
sync
umount "$mnt"
rmdir "$mnt"
e2fsck -fn "$image"
