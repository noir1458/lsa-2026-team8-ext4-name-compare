#!/bin/sh
# VM에서 무인으로 실행한다. 6.18.64 원본(-b0)과 이름 비교 패치(-tail)를 빌드·설치한다.
# 재부팅하지 않고 GRUB 기본 항목도 바꾸지 않는다.
set -u
base="$HOME/kernel-src/k618"
cd "$base/linux-6.18.64" || exit 1
exec >> ../build.log 2>&1
step() { echo "[$(date +%H:%M:%S)] $*"; }
fail() { step "FAIL: $*"; echo fail > ../build.rc; exit 1; }
rm -f ../build.rc

step "config from Ubuntu 5.15 generic + localmodconfig"
cp /boot/config-5.15.0-139-generic .config || fail "base config"
make olddefconfig > /dev/null || fail olddefconfig
lsmod > ../lsmod.txt
yes '' | make LSMOD=../lsmod.txt localmodconfig > ../localmodconfig.log 2>&1 || fail localmodconfig
scripts/config --disable DEBUG_INFO --enable DEBUG_INFO_NONE --disable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT \
  --disable DEBUG_INFO_DWARF4 --disable DEBUG_INFO_DWARF5 --disable DEBUG_INFO_BTF \
  --set-str SYSTEM_TRUSTED_KEYS "" --set-str SYSTEM_REVOCATION_KEYS "" \
  --enable FUNCTION_TRACER --enable FUNCTION_PROFILER --enable KPROBE_EVENTS \
  --enable EXT4_FS --enable BLK_DEV_LOOP --set-str LOCALVERSION "-b0" --disable LOCALVERSION_AUTO \
  --disable KERNEL_ZSTD --enable KERNEL_GZIP --disable MODULE_COMPRESS_ZSTD --disable MODULE_COMPRESS_XZ \
  --disable MODULE_COMPRESS_GZIP --enable MODULE_COMPRESS_NONE --disable MODULE_COMPRESS
make olddefconfig > /dev/null || fail olddefconfig2
for o in EXT4_FS BLK_DEV_LOOP FUNCTION_PROFILER DEBUG_INFO_NONE TUN KERNEL_GZIP; do grep "CONFIG_$o=" .config || echo "missing $o"; done

step "build b0"
make -j2 > ../build-b0.log 2>&1 || fail "b0 build"
[ "$(cat include/config/kernel.release)" = 6.18.64-b0 ] || fail "unexpected release $(cat include/config/kernel.release)"
cp .config ../config-6.18.64-b0
objdump -d --no-show-raw-insn lib/string.o | awk '/<memcmp>:/,/^$/' > ../memcmp-618.objdump
avail=$(df --output=avail -k / | tail -1)
[ "$avail" -gt 1500000 ] || fail "disk low before install: ${avail}K"
step "install b0"
sudo make modules_install INSTALL_MOD_STRIP=1 > ../install-b0.log 2>&1 || fail "modules_install b0"
sudo make install >> ../install-b0.log 2>&1 || fail "install b0"
[ -f /boot/vmlinuz-6.18.64-b0 ] || fail "vmlinuz b0 missing"

step "apply tail patch"
patch -p1 < ../ext4-name-tail-compare-6.18.patch || fail "tail patch"
scripts/config --set-str LOCALVERSION "-tail"
make olddefconfig > /dev/null || fail olddefconfig3
step "build tail"
make -j2 > ../build-tail.log 2>&1 || fail "tail build"
[ "$(cat include/config/kernel.release)" = 6.18.64-tail ] || fail "unexpected release"
cp .config ../config-6.18.64-tail
objdump -dr --no-show-raw-insn fs/ext4/namei.o | awk '/<ext4_search_dir>:/,/^$/' > ../ext4_search_dir-618-tail.objdump
step "install tail"
sudo make modules_install INSTALL_MOD_STRIP=1 > ../install-tail.log 2>&1 || fail "modules_install tail"
sudo make install >> ../install-tail.log 2>&1 || fail "install tail"
[ -f /boot/vmlinuz-6.18.64-tail ] || fail "vmlinuz tail missing"
diff ../config-6.18.64-b0 ../config-6.18.64-tail
step "done"
echo ok > ../build.rc
