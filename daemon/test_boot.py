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
        boot.sh = lambda cmd, **kw: (self.ran.append((cmd, kw.get('input'))), (0, ''))[1]
        boot.user = lambda: 'dice'
        boot.wait_for_networkmanager = lambda seconds=40: True
        boot.subprocess.Popen = lambda *a, **k: self.ran.append((a[0], 'background'))
        # keep it away from the real /etc
        real_open = open
        self.files = {}

        def fake_open(path, mode='r', *a, **k):
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


if __name__ == '__main__':
    unittest.main()
