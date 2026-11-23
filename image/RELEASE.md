Dice for a Raspberry Pi or a PC.

**Raspberry Pi 5 or 4:** write **dice-arm64.img.xz** onto a microSD card or an NVMe drive with Raspberry Pi Imager ("Use custom"), then drop your dice.json from https://djp7.pythonanywhere.com/dice onto the card's "bootfs" drive. The user is `dice`, password `dice`, until you change it.

**PC (64-bit Intel or AMD):** write **dice-amd64.iso** onto a USB stick with Raspberry Pi Imager ("Use custom") or balenaEtcher, then start the PC from the stick. Pick "Install" on its menu to keep Dice on the PC's own drive.
