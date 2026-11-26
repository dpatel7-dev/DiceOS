# DiceOS

An operating system for the Raspberry Pi and for PCs, made of pixel worlds. Your desktop is [DiceWeb](https://github.com/dpatel7-dev/DiceWeb), with a real Terminal, real files, Wi-Fi, Bluetooth, sound, brightness, screenshots and power.

**Set it up and get it:** https://djp7.pythonanywhere.com/dice

## The Dice family

- **DiceOS**: this, the operating system.
- **DiceWeb**: the same desktop in a browser tab, with SereneTab (the browser), Axiom (the planner), Music, Notes and a pretend Terminal.
- **DiceTV**: big covers you move through with a controller, for a TV. Pick it in Settings, Starting up, or from the app grid.
- **Dice Home**: for a screen on the wall: a big clock, the weather, the day's Axiom tasks, and buttons for your Home Assistant lights, switches, fans and scenes. Set it up from its Set up button: your Home Assistant address and a long-lived access token. The token is kept in its own file that only DiceOS's helper can read (`/etc/dice/ha-token` beside the settings), and the helper talks to Home Assistant itself, so Home Assistant needs no extra setup.
- **Dice Cloud**: your notes, Axiom, SereneTab's shortcuts and a few settings, the same on every computer with DiceOS or DiceWeb. Everything is locked with your Dice Cloud code (AES-GCM) before it leaves, so the website only keeps a box it can't open. Turn it on in Settings, Dice Cloud.
- **Dice Emulator**: https://djp7.pythonanywhere.com/dice/try starts DiceOS with your settings on a pretend Pi or PC, in the browser.

## On a Raspberry Pi

1. On the website, fill in **Make it yours** and press **Save dice.json**.
2. Download **dice-arm64.img.xz** from this project's Releases.
3. Write it onto a microSD card or an NVMe drive with Raspberry Pi Imager: Operating System, **Use custom**, pick the file. Say **No** to OS customisation (dice.json does that).
4. When it's written, the card shows up as a drive called **bootfs**. Drag `dice.json` onto it.
5. Put it in the Pi and switch it on.

No administrator password on your computer? Copy both files onto a USB stick and let the Pi 5 write the card itself with Network Install. The website shows each step.

The user is `dice`, password `dice`, until you set one.

## On a PC

Any 64-bit PC (Intel or AMD) that can start from a USB stick.

1. Download **dice-amd64.iso** from this project's Releases.
2. Write it onto a USB stick (8 GB or more) with Raspberry Pi Imager (**Use custom**) or balenaEtcher. Everything on the stick is wiped.
3. Plug the stick into the PC, switch it on, and pick the stick from its start-up menu (usually F12, F11, F9 or Esc as it starts).
4. Pick **DiceOS** to try it from the stick, or **Install** to put it on the PC's own drive (that wipes the drive, and asks for your name and a password).

DiceOS on the stick starts fresh each time. To bring your settings, put `dice.json` on a second USB stick and plug that in too.

## Already running Linux?

On a Pi with Raspberry Pi OS (64-bit), or a PC with Debian or Ubuntu (64-bit):

```
curl -fsSL https://djp7.pythonanywhere.com/dice/install.sh | sudo bash
```

Add `-s -- CODE` to the end with a setup code from the website. To take DiceOS off again: `sudo /opt/dice/bin/dice-uninstall`

## Real apps and DiceGaming

- **The Store** installs real Linux apps from [Flathub](https://flathub.org) with Flatpak: VLC, Kodi, GIMP, LibreOffice, RetroArch and thousands more (on a Pi, the ones Flathub makes for ARM; Steam and Discord need a PC). They update with DiceOS.
- **Streaming services are apps**: Netflix, YouTube, DAZN and the rest open full screen on their own (each signed in once, inside it), and Home closes them.
- **TV channels** on Home: ABC, CBS, NBC, FOX and PBS free from an antenna with a network tuner like an HDHomeRun, or through your live TV service, or in each channel's own app (MSG and YES on DAZN, ESPN in the ESPN app, FOX on FOX One, NBC on Peacock, CBS on Paramount+). Pick yours in TV setup, at the end of the row.
- **DiceGaming** (on the desktop) plays in the cloud with no gaming PC: Xbox Cloud Gaming, GeForce NOW, Amazon Luna, or your own Dice Cloud PC. If you do have a gaming PC, install [Sunshine](https://github.com/LizardByte/Sunshine) on it, then in DiceGaming install Moonlight, add the PC, and pair with the 4 numbers it shows.

## Deuce, the voice assistant

Hold the microphone button on the air mouse and say what you want: "put on the Knicks game" (it finds the game, the channel it's on and the way you can watch it, and opens it), "put on MSG", "open Netflix", "switch to the PlayStation", "turn it up", "set a timer for 10 minutes", "turn off the TV". The first time, set up its hearing in Settings, Deuce (a one-time download of [Vosk](https://alphacephei.com/vosk/)'s small English model, about 50 MB). It listens on the computer itself; nothing you say goes to a cloud AI. If holding the button does nothing, "Teach it" in the same place.

## Inputs: a switch for your TV

Everything on the TV's other HDMI inputs (a PlayStation, an Xbox, a cable box) shows in Inputs, at the end of TV channels. Pick one and the TV switches to it; the air mouse's buttons go on to it through the HDMI cable, and Home comes back to DiceOS. It needs HDMI-CEC on in the TV and in each device (PlayStation: "Enable HDMI Device Link").

## Dice Cloud PC

A computer of your own in the cloud: rent one with Ubuntu from any cloud company, let in ports 80 and 443, and run

```
curl -fsSL https://raw.githubusercontent.com/dpatel7-dev/DiceOS/main/cloudpc/install.sh | sudo sh -s -- --desktop
```

(`--gaming` too, on one with an NVIDIA graphics card). It ends with an address and a key: add them in the Dice Cloud PC app. You get its desktop on your TV, as much room for Dice Cloud as its disk has (your files still locked before they leave), and its games in DiceGaming. The kit is in [`cloudpc/`](cloudpc): `dice-cloud-server` and `install.sh`.

## Remotes for a TV build

- **Your TV's own remote** works through the HDMI cable (HDMI-CEC), once CEC is on in the TV's settings (Anynet+, Bravia Sync, SimpLink…).
- **An air mouse** (like the iPazzPort remote with a keyboard on the back): plug in its USB stick, or pair it in Settings, Bluetooth. Point to move the big pointer, click to pick. The right button and Back go back (held: Home), Home goes home or closes the app on top (held: Quick access), the microphone button talks to Deuce, and resting the pointer at the end of a row scrolls it. The keyboard types straight into any box: the on-screen keyboard comes up when you pick one, and gets out of the way as soon as you type on the real one. The power button turns DiceOS off like a TV (the screen and the TV go off) and turns it back on; hold it for 5 seconds to shut down completely, after which a Pi only starts again with its own power button or by unplugging it.
- **Apps and games on top:** apps from the Store, websites, and games from DiceGaming open over Dice. Home on either remote (or Super + Esc on a keyboard) closes the one on top.
- **Edges cut off?** Some TVs crop the picture. Settings, Remotes, "Fit the picture to the TV" (or the zoom keys) shrinks it until you can see the edges.

## dice.json

Everything is optional. Leave something out and DiceOS asks on the screen instead.

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

At start-up, `dice-boot` looks for `dice.json` on the Pi card's bootfs drive (or in `/etc/dice/` on a PC), then on USB sticks. It only looks at USB sticks and other removable drives, never the computer's own disks, and opens them read-only until it finds one. It applies it, wipes the passwords out, and renames it `dice-applied.json`. Drop a new one on the card to change things again.

## How it works

- **cage** (a one-window Wayland compositor) runs **Chromium** full screen on DiceWeb, as the person who uses the computer.
- **diced** (`daemon/diced.py`, Python standard library only) serves DiceWeb on 127.0.0.1:7070 and does the real things: Wi-Fi through NetworkManager, Bluetooth through bluetoothctl, the TV's own remote through HDMI-CEC (cec-client), the power button on air mice and media keyboards (read from /dev/input, so it sleeps DiceOS instead of switching everything off), volume through PipeWire (or ALSA), brightness, files in your home folder and on USB sticks (and finding them by name for the Dice Bar), screenshots with grim, a real shell over a WebSocket, opening Chromium for websites, power and updates. It only answers this machine, and only requests carrying the secret it put in the desktop page.
- **dice-boot** applies `dice.json` and starts the desktop. **dice-update** gets the newest DiceOS from the website (weekly, if automatic updates are on).
- A Plymouth start-up splash: the Dice die turning slowly, with a loading bar. `node tools/make-splash.js` draws its pictures from the same `die3d.js` DiceWeb uses.

## Trying it first

- **In your browser:** the [emulator](https://djp7.pythonanywhere.com/dice/try) starts DiceOS with your settings on a pretend Raspberry Pi or PC. It shows the start-up screen, what dice-boot did with your dice.json (and any problems with it), then the real desktop on top of a pretend computer.
- **The real image, in QEMU:** after each build, Actions runs *Test the images in an emulator*, which starts `dice-amd64.iso` in QEMU and keeps a picture of the screen every 15 seconds (they're attached to the run). On a Linux computer with QEMU: `bash image/test-pc.sh dice-amd64.iso shots`. The Pi image isn't tried this way, because QEMU can't pretend to be a Pi 5 yet.

## Building the images

GitHub Actions builds both (`.github/workflows/image.yml`) and attaches them to a release. Run it from the Actions tab (Build the DiceOS images, Run workflow), or push a tag like `v1.1.0`.

- **Raspberry Pi** (`image/build.sh`, on an arm64 machine): the newest Raspberry Pi OS Lite (64-bit) with DiceOS installed into it by `install.sh`, as `dice-arm64.img.xz`.
- **PC** (`image/build-pc.sh`, in a Debian container): a Debian 13 live system made with live-build, with the drivers and firmware PCs need, DiceOS installed into it by the same `install.sh`, and the Debian installer on the start-up menu, as `dice-amd64.iso`.

## Tests

```
python3 -m unittest discover -s daemon
cd cloudpc && python3 -m unittest test_cloud_server
```

`tools/sync-diceweb.sh` copies DiceWeb into `diceweb/` (it sits next to this folder).
