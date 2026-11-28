#!/usr/bin/env python3
"""Tests for dice-boot, with the system commands faked."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader('dice_boot', os.path.join(HERE, '..', 'bin', 'dice-boot'))
spec = importlib.util.spec_from_loader('dice_boot', loader)
boot = importlib.util.module_from_spec(spec)
loader.exec_module(boot)


class BootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ran = []
        boot.SETTINGS = os.path.join(self.tmp, 'etc', 'settings.json')
        boot.APPLIED = os.path.join(self.tmp, 'var', 'applied')
        boot.sh = lambda cmd, **kw: (self.ran.append((cmd, kw.get('input'))), (0, ''))[1]
        boot.user = lambda: 'dice'
        boot.wait_for_networkmanager = lambda seconds=40: True
        # (Popen is the subprocess module's own, shared with diced's tests: put it back after)
        real_popen = boot.subprocess.Popen
        self.addCleanup(setattr, boot.subprocess, 'Popen', real_popen)
        boot.subprocess.Popen = lambda *a, **k: self.ran.append((a[0], 'background'))
        # keep it away from the real /etc
        real_open = open
        self.files = {}

        def fake_open(path, mode='r', *a, **k):
            if str(path).startswith('/var/log/'):  # logs go nowhere (the test isn't root on GitHub)
                return real_open(os.devnull, mode, *a, **k)
            if str(path).startswith('/etc/'):
                if 'w' in mode:
                    import io
                    buf = io.StringIO()
                    buf.close = lambda: self.files.__setitem__(path, buf.getvalue())
                    return buf
                import io
                return io.StringIO(self.files.get(path, '127.0.1.1\traspberrypi\n'))
            return real_open(path, mode, *a, **k)
        boot.open = fake_open
        boot.os.path.exists = (lambda f: (lambda p: True if p.startswith('/usr/share/zoneinfo/') or p == '/etc/hosts' else f(p)))(os.path.exists)

    def cmds(self):
        return [' '.join(c) for c, _ in self.ran]

    def test_applies_everything(self):
        cfg = {'dice': 1, 'name': 'Dhruv', 'computer': 'dhruv-pi', 'password': 'secret1', 'timezone': 'America/New_York', 'keyboard': 'us',
               'wifi': {'ssid': 'Home Net', 'password': 'wifipass', 'country': 'us'}, 'look': 'night', 'world': 'mountains', 'ssh': True, 'updates': False,
               'suite': ['scout', 'hey', 'bad name!'], 'screen': {'rotate': 90, 'sleep': 10}}
        done, problems = boot.apply(cfg)
        c = self.cmds()
        self.assertIn('hostnamectl set-hostname dhruv-pi', c)
        self.assertIn(('chpasswd' and ['chpasswd'], 'dice:secret1\n'), [(x, i) for x, i in self.ran if x == ['chpasswd']])
        wifi = [x for x in c if x.startswith('nmcli connection add')][0]
        self.assertIn('ssid Home Net', wifi)
        self.assertIn('wifi-sec.psk wifipass', wifi)
        self.assertIn('timedatectl set-timezone America/New_York', c)
        self.assertIn('systemctl enable --now ssh', c)
        self.assertIn('systemctl disable --now dice-update.timer', c)
        self.assertIn('/opt/dice/bin/dice-suite scout hey', c)
        self.assertEqual(problems, [])
        saved = json.load(open(boot.SETTINGS))
        self.assertEqual(saved['look'], 'night')
        self.assertEqual(saved['screen']['rotate'], 90)
        self.assertNotIn('password', saved)
        self.assertNotIn('wifi', saved)
        self.assertEqual(saved['welcome']['name'], 'Dhruv')
        self.assertIn('/etc/default/keyboard', self.files)

    def test_refuses_bad_names_and_ssh_without_a_password(self):
        done, problems = boot.apply({'computer': 'My Pi!', 'ssh': True})
        self.assertTrue(any('computer name' in p for p in problems))
        self.assertTrue(any('SSH stayed off' in p for p in problems))
        self.assertNotIn('systemctl enable --now ssh', self.cmds())

    def test_scrub_wipes_passwords_and_renames(self):
        p = os.path.join(self.tmp, 'dice.json')
        cfg = {'name': 'D', 'password': 'pw', 'wifi': {'ssid': 'n', 'password': 'pw2'}}
        with open(p, 'w') as f:
            json.dump(cfg, f)
        boot.scrub(p, cfg, None)
        self.assertFalse(os.path.exists(p))
        left = json.load(open(os.path.join(self.tmp, 'dice-applied.json')))
        self.assertNotIn('password', left)
        self.assertEqual(left['wifi'], {'ssid': 'n'})
        self.assertIn('applied', left)
        # and it's remembered, for sticks that can't be written to
        self.assertEqual(len(open(boot.APPLIED).read().split()), 1)

    def test_only_usb_sticks_are_looked_at(self):
        # a fake /sys/block: the PC's own disk, a USB stick, a card reader, and the stick Dice started from
        sysb = os.path.join(self.tmp, 'sys', 'block')
        dev = os.path.join(self.tmp, 'sys', 'devices')
        def disk(name, path, parts, removable='0'):
            real = os.path.join(dev, path, name)
            os.makedirs(real)
            open(os.path.join(real, 'removable'), 'w').write(removable)
            for p in parts:
                os.makedirs(os.path.join(real, p))
            os.makedirs(sysb, exist_ok=True)
            os.symlink(real, os.path.join(sysb, name))
        disk('sda', 'pci0000:00/ata1/host0', ['sda1', 'sda2'])            # the computer's own disk
        disk('sdb', 'pci0000:00/usb2/2-1/host6', ['sdb1'])                # a USB stick
        disk('sdc', 'pci0000:00/mmc0/host7', [], removable='1')            # a card reader, no partitions
        disk('sdd', 'pci0000:00/usb3/3-2/host8', ['sdd1', 'sdd2'])        # the live USB Dice started from
        boot.mounted = lambda: {'/dev/sdd1'}
        self.assertEqual(boot.usb_parts(sysb), ['/dev/sdb1', '/dev/sdc'])

    def test_wifi_card_found_by_name(self):
        boot.sh = lambda cmd, **kw: (0, 'enp3s0:ethernet\nwlp2s0:wifi\nlo:loopback')
        self.assertEqual(boot.wifi_device(), 'wlp2s0')
        boot.sh = lambda cmd, **kw: (1, '')
        self.assertEqual(boot.wifi_device(), 'wlan0')


    def _home(self):
        home = os.path.join(self.tmp, 'home', 'dice')
        os.makedirs(os.path.join(home, 'Documents'))
        with open(os.path.join(home, 'Documents', 'notes.txt'), 'w') as f:
            f.write('already here')
        import pwd as _pwd
        fake = type('P', (), {'pw_dir': home, 'pw_uid': os.getuid(), 'pw_gid': os.getgid()})
        real = boot.pwd.getpwnam
        self.addCleanup(setattr, boot.pwd, 'getpwnam', real)
        boot.pwd.getpwnam = lambda name: fake if name == 'dice' else real(name)
        return home

    def _zip(self, where):
        import stat
        import zipfile
        path = os.path.join(where, 'dice-files.zip')
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Photos/2024/beach.jpg', b'jpeg!')
            z.writestr('Documents/notes.txt', b'from my PC')
            z.writestr('../escape.txt', b'no')
            z.writestr('/etc/passwd', b'no')
            z.writestr('.ssh/authorized_keys', b'no')
            z.writestr('Music/.hidden.mp3', b'no')
            link = zipfile.ZipInfo('Pictures/link')
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, '/etc/shadow')
        return path

    def test_files_apps_and_home_screens_from_make_it_yours(self):
        home = self._home()
        card = os.path.join(self.tmp, 'bootfs')
        os.makedirs(card)
        self._zip(card)
        cfg = {'name': 'Dhruv', 'files': 'dice-files.zip', 'apps': ['org.videolan.VLC', 'not an app', 'tv.kodi.Kodi'],
               'layout': {'dock': ['files', 'browser'], 'tv': ['hum'], 'widgets': [{'type': 'clock', 'x': 0.7, 'y': 0.1}]},
               'webapps': [{'name': 'Desmos', 'url': 'https://www.desmos.com/calculator'}]}
        done, problems = boot.apply(cfg, src=os.path.join(card, 'dice.json'))
        self.assertEqual(problems, [])
        with open(os.path.join(home, 'Photos', '2024', 'beach.jpg'), 'rb') as f:
            self.assertEqual(f.read(), b'jpeg!')
        # never over what's there, never outside home, no hidden files, no links
        with open(os.path.join(home, 'Documents', 'notes.txt')) as f:
            self.assertEqual(f.read(), 'already here')
        with open(os.path.join(home, 'Documents', 'notes (2).txt')) as f:
            self.assertEqual(f.read(), 'from my PC')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'home', 'escape.txt')))
        self.assertFalse(os.path.exists(os.path.join(home, '.ssh')))
        self.assertFalse(os.path.exists(os.path.join(home, 'Music')))
        self.assertFalse(os.path.lexists(os.path.join(home, 'Pictures', 'link')))
        self.assertTrue(any('Copied 2 of your files' in d and '5 left out' in d for d in done), done)
        # apps: in the background, the good ids only
        bg = [c for c, how in self.ran if how == 'background' and '--install-apps' in c]
        self.assertEqual(bg[0][bg[0].index('--install-apps') + 1:], ['org.videolan.VLC', 'tv.kodi.Kodi'])
        saved = json.load(open(boot.SETTINGS))
        self.assertEqual(saved['layout']['dock'], ['files', 'browser'])
        self.assertEqual(saved['webapps'][0]['name'], 'Desmos')
        # once copied, the zip comes off the Pi's small bootfs drive
        boot.scrub(os.path.join(card, 'dice.json'), cfg, None)
        self.assertFalse(os.path.exists(os.path.join(card, 'dice-files.zip')))

    def test_a_missing_zip_is_a_problem_not_a_crash(self):
        self._home()
        done, problems = boot.apply({'files': 'dice-files.zip'}, src=os.path.join(self.tmp, 'dice.json'))
        self.assertTrue(any('wasn\'t next to dice.json' in p for p in problems))

    def test_installs_the_apps_once_online(self):
        boot.online = lambda host='dl.flathub.org': True
        real_which = boot.shutil.which
        self.addCleanup(setattr, boot.shutil, 'which', real_which)
        boot.shutil.which = lambda name: '/usr/bin/' + name
        got = boot.install_apps(['org.videolan.VLC', 'rm -rf /', 'tv.kodi.Kodi'], tries=1, wait=0)
        self.assertEqual(got, ['org.videolan.VLC', 'tv.kodi.Kodi'])
        c = self.cmds()
        self.assertIn('flatpak remote-add --system --if-not-exists flathub ' + boot.FLATHUB, c)
        self.assertIn('flatpak install --system -y --noninteractive flathub org.videolan.VLC', c)
        self.assertFalse(any('rm -rf' in x for x in c))


if __name__ == '__main__':
    unittest.main()
