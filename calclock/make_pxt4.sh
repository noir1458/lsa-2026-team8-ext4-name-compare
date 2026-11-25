#!/usr/bin/env bash
# 수업 실습(5, 8, 11)과 같은 방식으로 ext4·jbd2를 pxt4·jbd3 모듈로 복사하고,
# 이름 비교 조건문과 calclock·ds_monitoring 계측을 넣은 모듈 네 개를 빌드한다.
#
# Usage: make_pxt4.sh <linux-5.4.214 소스> <커널 빌드 디렉터리> <실습 소스 디렉터리> <새 출력 디렉터리>
#   실습 소스 디렉터리: calclock.c/.h, ds_monitoring.c/.h가 있는 곳
#     (https://github.com/syslab-CAU/CAU-CSE-LinuxApplicationsPracticalClass 에서 받는다. 이 레포에는 넣지 않는다)
# 출력: <출력>/{time-orig,time-tail,count-orig,count-tail}/{pxt4.ko,jbd3/jbd3.ko}
set -euo pipefail
src=$(realpath "${1:?linux source}")
kdir=$(realpath "${2:?kernel build directory}")
tools=$(realpath "${3:?practice source directory}")
out=${4:?output directory}
here=$(dirname "$(realpath "$0")")
[[ ! -e $out ]] || { echo "output exists: $out" >&2; exit 2; }
for f in calclock.c calclock.h ds_monitoring.c ds_monitoring.h; do [[ -f $tools/$f ]]; done
mkdir -p "$out"
out=$(realpath "$out")

rename() { sed 's/ext4/pxt4/g; s/EXT4/PXT4/g; s/jbd2/jbd3/g; s/JBD2/JBD3/g; s/CONFIG_PXT4/CONFIG_EXT4/g; s/has_unknown_pxt4/has_unknown_ext4/g; s/EXT##ver##/PXT##ver##/g; s/EXT\([23]\)_FEATURE/PXT\1_FEATURE/g' "$1"; }

base="$out/base"
mkdir -p "$base/jbd3" "$base/include/linux" "$base/include/trace/events"
for f in "$src"/fs/ext4/*.[ch]; do
  n=$(basename "$f"); n=${n//ext4/pxt4}; n=${n//jbd2/jbd3}
  rename "$f" > "$base/$n"
done
for f in "$src"/fs/jbd2/*.c; do rename "$f" > "$base/jbd3/$(basename "$f")"; done
rename "$src/include/linux/jbd2.h" | sed 's/journal-head\.h/journal-head3.h/' > "$base/include/linux/jbd3.h"
rename "$src/include/linux/journal-head.h" > "$base/include/linux/journal-head3.h"
rename "$src/include/trace/events/ext4.h" > "$base/include/trace/events/pxt4.h"
rename "$src/include/trace/events/jbd2.h" > "$base/include/trace/events/jbd3.h"
cp "$here/Makefile.pxt4" "$base/Makefile"
cp "$here/Makefile.jbd3" "$base/jbd3/Makefile"
cp "$tools"/calclock.[ch] "$tools"/ds_monitoring.[ch] "$base/"
patch -s -p1 -d "$base" < "$here/pxt4-name-calclock.patch"

for v in time-orig time-tail count-orig count-tail; do
  flags=-DNAME_CALCLOCK
  [[ $v = count-* ]] && flags=-DNAME_COUNT
  [[ $v = *-tail ]] && flags="$flags -DNAME_TAIL"
  cp -r "$base" "$out/$v"
  make -s -C "$kdir" M="$out/$v/jbd3" modules > "$out/$v/build-jbd3.log" 2>&1
  make -s -C "$kdir" M="$out/$v" NAME_FLAGS="$flags" modules > "$out/$v/build-pxt4.log" 2>&1
  echo "$v: $flags"
  sha256sum "$out/$v/pxt4.ko" "$out/$v/jbd3/jbd3.ko"
done
