#!/usr/bin/env bash
# 3차 측정용 "실제 모양" 이미지를 한 번 만든다(VM에서 root로). 실제 디스크는 건드리지 않는다.
#   real/photos  카메라처럼 IMG_0001.JPG ~ IMG_9999.JPG (빈 파일, 만든 순서대로)
#   real/linux   kernel.org linux-5.4.214 소스 트리(실제 파일 이름과 크기)와 git 저장소
#
# Usage: make_fixture_real.sh <work-dir> <linux-5.4.214.tar.xz>
set -euo pipefail
root=${1:?work directory}
tarball=${2:?linux tarball}
[[ $EUID = 0 && -d $root/scripts && -f $tarball ]]
image="$root/fixtures/real.img"
mnt="$root/fixtures/real-mount"
out="$root/results/round3"
[[ ! -e $image && ! -e $mnt && ! -e $out/fixture-real.txt ]] || { echo 'fresh destinations required' >&2; exit 2; }
mkdir -p "$out" "$mnt"
truncate -s 4G "$image"
mkfs.ext4 -q -F -b 4096 -I 256 -N 200000 -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=11111111-2222-3333-4444-555555555555 "$image"
mount -o loop,noatime "$image" "$mnt"
mkdir -p "$mnt/real/photos"
for i in $(seq 1 9999); do : > "$mnt/real/photos/$(printf 'IMG_%04d.JPG' "$i")"; done
tar -xf "$tarball" -C "$mnt/real"
mv "$mnt/real/linux-5.4.214" "$mnt/real/linux"
export GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
export GIT_AUTHOR_DATE=2026-11-23T00:00:00Z GIT_COMMITTER_DATE=2026-11-23T00:00:00Z
git -C "$mnt/real/linux" init -q
git -C "$mnt/real/linux" -c gc.auto=0 add -A
git -C "$mnt/real/linux" -c gc.auto=0 commit -q -m "linux-5.4.214 from kernel.org tarball"
sleep 2
git -C "$mnt/real/linux" status --porcelain > "$out/fixture-git-status.txt"   # refreshes the index (no racy entries)
{
  echo "photos entries: $(ls "$mnt/real/photos" | wc -l)"
  echo "linux files: $(find "$mnt/real/linux" -path "$mnt/real/linux/.git" -prune -o -type f -print | wc -l)"
  echo "linux directories: $(find "$mnt/real/linux" -path "$mnt/real/linux/.git" -prune -o -type d -print | wc -l)"
  echo "git HEAD: $(git -C "$mnt/real/linux" rev-parse HEAD)"
  echo "tarball sha256: $(sha256sum "$tarball" | cut -d' ' -f1)"
} > "$out/fixture-real.txt"
lsattr -d "$mnt/real/photos" "$mnt/real/linux" > "$out/fixture-real-flags.txt"
df -h "$mnt" >> "$out/fixture-real.txt"
sync
umount "$mnt"
rmdir "$mnt"
e2fsck -fn "$image" > "$out/fixture-real-fsck.log" 2>&1
