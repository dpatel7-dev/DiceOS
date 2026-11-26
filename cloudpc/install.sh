#!/bin/sh
# Dice Cloud PC: turns a computer in the cloud (a VM you rent, with Ubuntu or Debian) into your
# own Dice Cloud PC. Run it on that computer, as root:
#
#   curl -fsSL https://raw.githubusercontent.com/dpatel7-dev/DiceOS/main/cloudpc/install.sh | sudo sh
#   curl -fsSL https://raw.githubusercontent.com/dpatel7-dev/DiceOS/main/cloudpc/install.sh | sudo sh -s -- --desktop
#   ... | sudo sh -s -- --desktop --gaming          (on a VM with an NVIDIA graphics card)
#
# What you get:
#   - Dice Cloud storage with all the room the disk has (your files arrive already locked).
#   - HTTPS, from Let's Encrypt through Caddy, at <your-ip>.sslip.io (or --domain your.name).
#   - With --desktop: a desktop (Xfce) you open from Dice, in the browser (noVNC), behind a password.
#   - With --gaming: Sunshine, so DiceGaming (Moonlight) can play its games.
# At the end it shows the address and the key to type into the Dice Cloud PC app.
set -eu

DESKTOP=0 GAMING=0 DOMAIN="" HTTPS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --desktop) DESKTOP=1 ;;
    --gaming) GAMING=1; DESKTOP=1 ;;
    --domain) shift; DOMAIN="${1:-}" ;;
    --no-https) HTTPS=0 ;;  # a computer at home, used only from DiceOS on the same network
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[ "$(id -u)" = 0 ] || { echo "Run it as root: curl ... | sudo sh" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "This needs Ubuntu or Debian (apt-get)." >&2; exit 1; }
REPO="https://raw.githubusercontent.com/dpatel7-dev/DiceOS/main/cloudpc"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
export DEBIAN_FRONTEND=noninteractive

say "1. The basics"
apt-get update -q
apt-get install -y -q python3 curl ca-certificates gnupg

say "2. The Dice Cloud server"
mkdir -p /opt/dice-cloud /etc/dice-cloud /var/lib/dice-cloud
if [ -f "$(dirname "$0")/dice-cloud-server" ]; then cp "$(dirname "$0")/dice-cloud-server" /opt/dice-cloud/; else curl -fsSL "$REPO/dice-cloud-server" -o /opt/dice-cloud/dice-cloud-server; fi
chmod 755 /opt/dice-cloud/dice-cloud-server
id dicecloud >/dev/null 2>&1 || useradd --system --home /var/lib/dice-cloud --shell /usr/sbin/nologin dicecloud
chown -R dicecloud: /var/lib/dice-cloud
if [ ! -f /etc/dice-cloud/config.json ]; then
  KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  printf '{"key": "%s", "data": "/var/lib/dice-cloud", "name": "%s"}\n' "$KEY" "$(hostname)" > /etc/dice-cloud/config.json
fi
chown root:dicecloud /etc/dice-cloud/config.json; chmod 640 /etc/dice-cloud/config.json
KEY=$(python3 -c 'import json; print(json.load(open("/etc/dice-cloud/config.json"))["key"])')
LISTEN=127.0.0.1; [ "$HTTPS" = 0 ] && LISTEN=0.0.0.0
cat > /etc/systemd/system/dice-cloud.service <<EOF
[Unit]
Description=Dice Cloud PC (your Dice Cloud files, locked)
After=network-online.target
[Service]
User=dicecloud
ExecStart=/usr/bin/python3 /opt/dice-cloud/dice-cloud-server --host $LISTEN --port 8790
Restart=always
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/dice-cloud
ProtectHome=yes
PrivateTmp=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now dice-cloud.service
systemctl restart dice-cloud.service

# ---- the desktop: Xfce, seen through noVNC (only through Caddy, with a password) ----
DESK_PW=""
if [ "$DESKTOP" = 1 ]; then
  say "3. A desktop (Xfce), opened in the browser"
  apt-get install -y -q xfce4 xfce4-goodies dbus-x11 tigervnc-standalone-server novnc websockify firefox-esr 2>/dev/null \
    || apt-get install -y -q xfce4 xfce4-goodies dbus-x11 tigervnc-standalone-server novnc websockify
  id dice >/dev/null 2>&1 || useradd --create-home --shell /bin/bash dice
  DESK_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
  # the picture is only reachable on this computer; the way in from outside is Caddy, with a password
  cat > /opt/dice-cloud/desktop.sh <<'EOF'
#!/bin/sh
# a screen in memory (TigerVNC, on this computer only), with Xfce on it
Xtigervnc :1 -geometry 1920x1080 -depth 24 -localhost -SecurityTypes None -rfbport 5901 -AlwaysShared &
X=$!
sleep 2
DISPLAY=:1 dbus-launch --exit-with-session startxfce4 &
wait $X
EOF
  chmod 755 /opt/dice-cloud/desktop.sh
  cat > /etc/systemd/system/dice-desktop.service <<'EOF'
[Unit]
Description=Dice Cloud PC desktop (TigerVNC on this computer only)
After=network.target
[Service]
User=dice
WorkingDirectory=/home/dice
ExecStart=/opt/dice-cloud/desktop.sh
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/dice-novnc.service <<'EOF'
[Unit]
Description=Dice Cloud PC desktop in the browser (noVNC)
After=dice-desktop.service
[Service]
User=dice
ExecStart=/usr/bin/websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now dice-desktop.service dice-novnc.service
  # (the Dice Cloud PC app shows the password to whoever has the key)
  printf '{"desktop": true, "user": "dice", "password": "%s"}\n' "$DESK_PW" > /etc/dice-cloud/desktop.json
  chown root:dicecloud /etc/dice-cloud/desktop.json; chmod 640 /etc/dice-cloud/desktop.json
fi

# (run again without --desktop: the desktop that's there stays reachable)
if [ "$DESKTOP" = 0 ] && [ -f /etc/dice-cloud/desktop.json ]; then
  DESKTOP=1
  DESK_PW=$(python3 -c 'import json; print(json.load(open("/etc/dice-cloud/desktop.json")).get("password", ""))')
fi

# ---- games: Sunshine (needs a graphics card; NVIDIA's driver first) ----
if [ "$GAMING" = 1 ]; then
  say "4. Games: Sunshine"
  if ! command -v nvidia-smi >/dev/null; then
    echo "No NVIDIA graphics card driver found. Install your provider's GPU driver first (on Ubuntu: sudo ubuntu-drivers install), restart, and run this again with --gaming."
  else
    . /etc/os-release
    DEB="sunshine-ubuntu-${VERSION_ID:-24.04}-amd64.deb"
    if curl -fsSL "https://github.com/LizardByte/Sunshine/releases/latest/download/$DEB" -o "/tmp/$DEB"; then
      apt-get install -y -q "/tmp/$DEB" && rm -f "/tmp/$DEB"
      echo "Sunshine is in. Open https://<this computer>:47990 once to make its name and password, and open these ports in your provider's firewall for Moonlight: TCP 47984, 47989, 47990, 48010 and UDP 47998-48000."
    else
      echo "Couldn't download Sunshine for this Ubuntu ($DEB). Get it from github.com/LizardByte/Sunshine/releases."
    fi
  fi
fi

# ---- HTTPS, in front of everything ----
ADDR=""
if [ "$HTTPS" = 1 ]; then
  say "5. HTTPS (Caddy, with a free certificate from Let's Encrypt)"
  if [ -z "$DOMAIN" ]; then
    IP=$(curl -fsS4 https://api.ipify.org || true)
    [ -n "$IP" ] || { echo "Couldn't find this computer's public address. Run again with --domain your.name" >&2; exit 1; }
    DOMAIN="$(echo "$IP" | tr . -).sslip.io"  # sslip.io: a name that points at the address in it
  fi
  if ! command -v caddy >/dev/null; then
    apt-get install -y -q caddy 2>/dev/null || {
      apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
      apt-get update -q && apt-get install -y -q caddy
    }
  fi
  DESK_BLOCK=""
  if [ -n "$DESK_PW" ]; then
    HASH=$(caddy hash-password --plaintext "$DESK_PW")
    DESK_BLOCK="  handle_path /desktop/* {
    basicauth {
      dice $HASH
    }
    reverse_proxy 127.0.0.1:6080
  }"
  fi
  cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
  encode gzip
$DESK_BLOCK
  handle {
    reverse_proxy 127.0.0.1:8790
  }
}
EOF
  systemctl enable caddy >/dev/null 2>&1 || true
  systemctl restart caddy
  if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 80/tcp; ufw allow 443/tcp; fi
  ADDR="https://$DOMAIN"
else
  ADDR="http://$(hostname -I | awk '{print $1}'):8790"
  if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 8790/tcp; fi
fi

say "Done. Your Dice Cloud PC:"
echo "  Address:  $ADDR"
echo "  Key:      $KEY"
[ -n "$DESK_PW" ] && echo "  Desktop:  $ADDR/desktop/vnc.html   (name: dice, password: $DESK_PW)"
echo
echo "On your Dice: open Dice Cloud PC, pick Add your Cloud PC, and type the address and key."
echo "(Your provider's firewall must let in ports 80 and 443. The first visit can take a minute while the certificate arrives.)"
exit 0
