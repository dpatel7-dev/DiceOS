#!/usr/bin/env bash
# Builds Dice for PCs: a 64-bit Debian live system with Dice already in it, as
# dist/dice-amd64.iso.
#
# Write the .iso onto a USB stick (with Raspberry Pi Imager: "Use custom", or
# balenaEtcher), start the PC from the stick, and Dice opens. To keep Dice on
# the PC for good, pick "Install" in the stick's start-up menu: it asks for a
# name and a password, then puts Dice on the PC's own drive.
#
# live-build only runs on Debian, so on GitHub Actions this runs inside a
# Debian container (see .github/workflows/image.yml):
#   docker run --rm --privileged -v "$PWD:/src" -w /src debian:trixie bash image/build-pc.sh
set -euxo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
VER=$(cat "$HERE/VERSION")
WORK=${WORK:-/tmp/dice-pc}
OUT="$HERE/dist"
mkdir -p "$WORK" "$OUT"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends live-build debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools dosfstools ca-certificates curl cpio

cd "$WORK"
lb clean --purge >/dev/null 2>&1 || true
lb config \
  --distribution trixie \
  --architectures amd64 \
  --archive-areas "main contrib non-free non-free-firmware" \
  --binary-images iso-hybrid \
  --debian-installer live \
  --debian-installer-gui false \
  --bootappend-live "boot=live components quiet splash username=dice hostname=dice" \
  --iso-application "Dice $VER" \
  --iso-volume "DICE" \
  --memtest none \
  --apt-recommends false

# what a PC needs on top of Debian: its drivers and firmware (Wi-Fi, graphics, sound)
cat > config/package-lists/dice.list.chroot <<'LIST'
linux-image-amd64
live-boot
live-config
live-config-systemd
sudo
network-manager
firmware-linux
firmware-linux-nonfree
firmware-misc-nonfree
firmware-iwlwifi
firmware-realtek
firmware-atheros
firmware-sof-signed
intel-microcode
amd64-microcode
LIST

# DiceOS itself, put in by its own installer inside the image.
# live-build copies config/includes.chroot_after_packages/ into the system
# after the packages and before the hooks. (Older live-build called that
# folder config/includes.chroot; Debian 13's ignores the old name, which left
# the hook with nothing to run.) It goes in /usr/local/src, not /tmp, so
# nothing can tidy it away first.
for inc in config/includes.chroot_after_packages; do
  mkdir -p "$inc/usr/local/src/dice-src"
  tar -C "$HERE" --exclude=.git --exclude=dist -cf - . | tar -C "$inc/usr/local/src/dice-src" -xf -
done
test -f config/includes.chroot_after_packages/usr/local/src/dice-src/install.sh
mkdir -p config/hooks/normal
cat > config/hooks/normal/9000-dice.hook.chroot <<'HOOK'
#!/bin/sh
set -e
SRC=/usr/local/src/dice-src
if [ ! -f "$SRC/install.sh" ]; then
  echo "DiceOS: $SRC/install.sh isn't in the image. Is config/includes.chroot_after_packages being copied?" >&2
  ls -la /usr/local/src >&2 || true
  exit 1
fi
DICE_SRC="$SRC" DICE_IMAGE=pc bash "$SRC/install.sh"
rm -rf "$SRC"
apt-get clean
HOOK
chmod +x config/hooks/normal/9000-dice.hook.chroot

lb build

ISO=$(ls -1 ./*.iso | head -n1)
mv "$ISO" "$OUT/dice-amd64.iso"
cd "$OUT"
sha256sum dice-amd64.iso > dice-amd64.iso.sha256
echo "Built Dice $VER for PCs: $(du -h dice-amd64.iso | cut -f1)"
