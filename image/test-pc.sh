#!/usr/bin/env bash
# Starts the PC image in QEMU (a real emulator of a whole PC), presses Enter at
# the start-up menu, takes a picture of the screen every 15 seconds, and checks
# that DiceOS's desktop came up: the last picture has lots of colours, where a
# black screen or a text console has hardly any.
#
#   bash image/test-pc.sh dist/dice-amd64.iso shots
#
# Needs qemu-system-x86, socat and ImageMagick. Uses KVM when it's there
# (much faster); without it, it still works, just slowly.
set -euo pipefail

ISO=${1:?the .iso to start}
OUT=${2:-shots}
SHOTS=${SHOTS:-20}
mkdir -p "$OUT"
MON=$(mktemp -u /tmp/dice-qemu-XXXX.sock)
PID=$(mktemp -u /tmp/dice-qemu-XXXX.pid)
ACCEL=tcg
if [ -w /dev/kvm ]; then ACCEL=kvm; fi
echo "Starting $ISO in QEMU ($ACCEL)"

qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 2 -m 4096 \
  -cdrom "$ISO" -boot d -vga virtio -display none \
  -nic user,model=virtio-net-pci -device qemu-xhci -device usb-tablet \
  -monitor "unix:$MON,server,nowait" -daemonize -pidfile "$PID"

mon() { echo "$1" | socat - "UNIX-CONNECT:$MON" >/dev/null 2>&1 || true; }
trap 'kill "$(cat "$PID" 2>/dev/null)" 2>/dev/null || true' EXIT

for i in $(seq 1 "$SHOTS"); do
  sleep 15
  # the start-up menu waits for a key; Enter picks the first choice (DiceOS)
  if [ "$i" -le 2 ]; then mon 'sendkey ret'; fi
  n=$(printf '%02d' "$i")
  mon "screendump $PWD/$OUT/$n.ppm"
  if [ -f "$OUT/$n.ppm" ]; then
    convert "$OUT/$n.ppm" "$OUT/$n.png" && rm -f "$OUT/$n.ppm"
    echo "$n: $(( i * 15 ))s, $(identify -format '%k' "$OUT/$n.png") colours"
  fi
done

last=$(ls "$OUT"/*.png | tail -n1)
colours=$(identify -format '%k' "$last")
if [ "$colours" -lt 400 ]; then
  echo "DiceOS's desktop didn't come up: the last picture ($last) has only $colours colours."
  echo "Look at the pictures (they're attached to this run) to see where it stopped."
  exit 1
fi
echo "DiceOS started: the last picture has $colours colours."
