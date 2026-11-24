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
#
# If the desktop doesn't come up, it signs in on the second text screen (as
# the live user, dice / live) and copies the start-up log out through the
# emulated serial port into $OUT/serial.log, so you can read why.
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
  -monitor "unix:$MON,server,nowait" -serial "file:$PWD/$OUT/serial.log" \
  -daemonize -pidfile "$PID"

mon() { echo "$1" | socat - "UNIX-CONNECT:$MON" >/dev/null 2>&1 || true; }
# types a line on the emulated keyboard, one key at a time
typeit() {
  local s=$1 c k i
  for (( i = 0; i < ${#s}; i++ )); do
    c=${s:i:1}
    case "$c" in
      [A-Z]) k="shift-${c,,}" ;;
      [a-z0-9]) k=$c ;;
      ' ') k=spc ;; '-') k=minus ;; '_') k=shift-minus ;; '/') k=slash ;; '.') k=dot ;;
      '>') k=shift-dot ;; '|') k=shift-backslash ;; "'") k=apostrophe ;; ';') k=semicolon ;;
      '*') k=shift-8 ;; '=') k=equal ;; ',') k=comma ;; ':') k=shift-semicolon ;; '@') k=shift-2 ;;
      *) continue ;;
    esac
    mon "sendkey $k"
  done
  mon 'sendkey ret'
}
shot() {
  mon "screendump $PWD/$OUT/$1.ppm"; sleep 1
  [ -f "$OUT/$1.ppm" ] && convert "$OUT/$1.ppm" "$OUT/$1.png" && rm -f "$OUT/$1.ppm"
}
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
  echo "Signing in on the second text screen to fetch the start-up log..."
  mon 'sendkey ctrl-alt-f2'; sleep 4
  typeit dice; sleep 3
  typeit live; sleep 5
  typeit "sudo sh -c 'systemctl --failed --no-pager; journalctl -b --no-pager' > /dev/ttyS0"; sleep 3
  typeit live; sleep 15   # (in case sudo asks for the password)
  typeit "clear; systemctl --failed --no-pager; journalctl -b --no-pager -u 'dice*' | tail -n 25"; sleep 6
  shot why
  if [ -s "$OUT/serial.log" ]; then
    echo "---- the parts of the log about the desktop (all of it is in serial.log) ----"
    grep -aiE 'dice|cage|pam|auth|seat|logind|fail|error' "$OUT/serial.log" | tail -n 200 || true
  else
    echo "Couldn't fetch the log; the picture why.png shows the second text screen."
  fi
  echo "Look at the pictures (they're attached to this run) to see where it stopped."
  exit 1
fi
echo "DiceOS started: the last picture has $colours colours."
