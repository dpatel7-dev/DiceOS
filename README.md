# Dice

An operating system for the Raspberry Pi, made of pixel worlds. Your desktop is [DiceWeb](https://github.com/dpatel7-dev/DiceWeb), with a real Terminal, real files, Wi-Fi, sound, brightness and power.

**Set it up and get it:** https://djp7.pythonanywhere.com/dice

## Getting it onto a card

1. On the website, fill in **Make it yours** and press **Save dice.json**.
2. Download **dice-arm64.img.xz** from this project's Releases.
3. Write it onto a microSD card or an NVMe drive with Raspberry Pi Imager: Operating System, **Use custom**, pick the file. Say **No** to OS customisation (dice.json does that).
4. When it's written, the card shows up as a drive called **bootfs**. Drag `dice.json` onto it.
5. Put it in the Pi and switch it on.

No administrator password on your computer? Copy both files onto a USB stick and let the Pi 5 write the card itself with Network Install. The website shows each step.

Already running Raspberry Pi OS (64-bit)?

```
curl -fsSL https://djp7.pythonanywhere.com/dice/install.sh | sudo bash
```

Add `-s -- CODE` to the end with a setup code from the website. To take Dice off again: `sudo /opt/dice/bin/dice-uninstall`

The user is `dice`, password `dice`, until you set one.

## dice.json

Everything is optional. Leave something out and Dice asks on the screen instead.

```json
{
  "dice": 1,
  "name": "Dhruv",
  "computer": "dhruv-pi",
  "password": "only in the file, never sent anywhere",
  "wifi": { "ssid": "Home", "password": "...", "country": "US", "hidden": false },
  "timezone": "America/New_York",
  "keyboard": "us",
  "look": "auto",
  "world": "mountains",
  "buddy": "hum",
  "start": "desktop",
  "boot": "full",
  "screen": { "rotate": 0 },
  "homeassistant": "http://homeassistant.local:8123",
  "suite": ["scout", "hey"],
  "ssh": false,
  "updates": true
}
```

At start-up, `dice-boot` looks for `dice.json` on the card's bootfs drive, then on any USB stick. It applies it, wipes the passwords out, and renames it `dice-applied.json`. Drop a new one on the card to change things again.

## How it works

- **cage** (a one-window Wayland compositor) runs **Chromium** full screen on DiceWeb, as the person who uses the Pi.
- **diced** (`daemon/diced.py`, Python standard library only) serves DiceWeb on 127.0.0.1:7070 and does the real things: Wi-Fi through NetworkManager, volume through PipeWire (or ALSA), brightness, files in your home folder and on USB sticks, a real shell over a WebSocket, opening Chromium for websites, power and updates. It only answers this machine, and only requests carrying the secret it put in the desktop page.
- **dice-boot** applies `dice.json` and starts the desktop. **dice-update** gets the newest Dice from the website (weekly, if automatic updates are on).
- A Plymouth boot splash: a pixel die whose dots light up as the Pi starts.

## Building the image

GitHub Actions builds it (`.github/workflows/image.yml`) on an arm64 machine: it takes the newest Raspberry Pi OS Lite (64-bit), installs Dice into it with `install.sh`, and attaches `dice-arm64.img.xz` to a release. Run it from the Actions tab (Build the Dice image, Run workflow), or push a tag like `v1.0.0`.

To build it on any arm64 Linux machine: `sudo bash image/build.sh`

## Tests

```
python3 -m unittest discover -s daemon
```

`tools/sync-diceweb.sh` copies DiceWeb into `diceweb/` (it sits next to this folder).
