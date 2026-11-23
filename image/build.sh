#!/usr/bin/env bash
# Builds the Dice image: the newest Raspberry Pi OS Lite (64-bit) with Dice
# already in it, as dist/dice-arm64.img.xz, ready for Raspberry Pi Imager to
# write onto a microSD card or an NVMe drive.
#
# Runs on GitHub Actions (an arm64 Ubuntu machine), as root:
#   sudo WORK=/some/roomy/folder bash image/build.sh
# Needs: curl xz-utils parted e2fsprogs zerofree
set -euxo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
VER=$(cat "$HERE/VERSION")
WORK=${WORK:-/tmp/dice-image}
OUT="$HERE/dist"
mkdir -p "$WORK" "$OUT"
cd "$WORK"

# 1. the newest Raspberry Pi OS Lite, checked against its published checksum
URL=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://downloads.raspberrypi.com/raspios_lite_arm64_latest)
curl -fsSL -o base.img.xz "$URL"
if curl -fsSL -o base.sha256 "$URL.sha256"; then
  echo "$(cut -d' ' -f1 base.sha256)  base.img.xz" | sha256sum -c -
fi
xz -dc base.img.xz > dice.img
rm base.img.xz

# 2. room for Dice: grow the main partition by 3 GB
truncate -s +3G dice.img
parted -s dice.img resizepart 2 100%
LOOP=$(losetup -fP --show dice.img)
R="$WORK/root"
cleanup() {
  set +e
  for m in "$R/boot/firmware" "$R/dev/pts" "$R/dev" "$R/proc" "$R/sys" "$R"; do mountpoint -q "$m" && umount "$m"; done
  losetup -d "$LOOP" 2>/dev/null
}
trap cleanup EXIT
e2fsck -fy "${LOOP}p2" || true
resize2fs "${LOOP}p2"
mkdir -p "$R"
mount "${LOOP}p2" "$R"
mount "${LOOP}p1" "$R/boot/firmware"
mount --bind /dev "$R/dev"; mount --bind /dev/pts "$R/dev/pts"; mount -t proc proc "$R/proc"; mount -t sysfs sys "$R/sys"

# 3. install Dice inside it (no services start while building)
cp -a "$R/etc/resolv.conf" "$WORK/resolv.conf.keep" 2>/dev/null || true
rm -f "$R/etc/resolv.conf"; cp /etc/resolv.conf "$R/etc/resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$R/usr/sbin/policy-rc.d"; chmod +x "$R/usr/sbin/policy-rc.d"
mkdir -p "$R/tmp/dice-src"
tar -C "$HERE" --exclude=.git --exclude=dist -cf - . | tar -C "$R/tmp/dice-src" -xf -
chroot "$R" /usr/bin/env DICE_SRC=/tmp/dice-src DICE_IMAGE=pi bash /tmp/dice-src/install.sh
chroot "$R" apt-get clean
rm -rf "$R/tmp/dice-src" "$R/var/lib/apt/lists/"* "$R/usr/sbin/policy-rc.d"
rm -f "$R/etc/resolv.conf"
if [ -e "$WORK/resolv.conf.keep" ] || [ -L "$WORK/resolv.conf.keep" ]; then cp -a "$WORK/resolv.conf.keep" "$R/etc/resolv.conf"; fi
# a note on the card for anyone who opens the "bootfs" drive
cp "$HERE/image/README-bootfs.txt" "$R/boot/firmware/DICE-README.txt"

# 4. squeeze it: zero the free space, then compress
cleanup
trap - EXIT
LOOP=$(losetup -fP --show dice.img)
zerofree "${LOOP}p2" || true
losetup -d "$LOOP"
xz -T0 -6 -c dice.img > "$OUT/dice-arm64.img.xz"
rm dice.img
cd "$OUT"
sha256sum dice-arm64.img.xz > dice-arm64.img.xz.sha256
echo "Built Dice $VER: $(du -h dice-arm64.img.xz | cut -f1)"
