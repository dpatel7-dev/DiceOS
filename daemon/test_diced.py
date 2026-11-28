#!/usr/bin/env python3
"""Tests for diced.  python3 -m unittest discover -s daemon"""
import base64
import http.client
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diced  # noqa: E402


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


class DicedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['DICE_USER'] = __import__('pwd').getpwuid(os.getuid()).pw_name
        cls.tmp = tempfile.mkdtemp()
        cls.web = os.path.join(cls.tmp, 'web')
        os.makedirs(cls.web)
        with open(os.path.join(cls.web, 'index.html'), 'w') as f:
            f.write('<!doctype html><html><head><title>t</title></head><body>hi</body></html>')
        with open(os.path.join(cls.web, 'a.js'), 'w') as f:
            f.write('var a = 1;')
        cls.settings = os.path.join(cls.tmp, 'etc', 'settings.json')
        cls.srv = diced.make_server(0, cls.web, cls.settings)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        home = os.path.expanduser('~')
        cls.play = os.path.join(home, 'dice-test-%d' % os.getpid())
        os.makedirs(cls.play, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.play, ignore_errors=True)

    def req(self, method, path, body=None, token=True, host=None, origin=None, raw=False):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': host or '127.0.0.1:%d' % self.port}
        if token:
            h['X-Dice'] = diced.TOKEN
        if origin:
            h['Origin'] = origin
        data = body if (raw or body is None) else json.dumps(body)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out

    def j(self, *a, **k):
        code, out = self.req(*a, **k)
        return code, json.loads(out or b'{}')

    def test_desktop_page_gets_the_secret(self):
        code, out = self.req('GET', '/', token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'window.DICE_SYS=', out)
        self.assertIn(diced.TOKEN.encode(), out)
        code, out = self.req('GET', '/a.js', token=False)
        self.assertEqual((code, out), (200, b'var a = 1;'))

    def test_outsiders_are_refused(self):
        self.assertEqual(self.req('GET', '/api/status', token=False)[0], 403)
        self.assertEqual(self.req('GET', '/api/status', host='evil.example:7070')[0], 403)
        self.assertEqual(self.req('GET', '/', token=False, host='rebind.example')[0], 403)
        self.assertEqual(self.req('POST', '/api/power', {'action': 'reboot'}, origin='https://evil.example')[0], 403)
        self.assertEqual(self.req('OPTIONS', '/api/status')[0], 403)
        self.assertEqual(self.req('GET', '/../../etc/passwd', token=False)[0], 404)

    def test_status(self):
        code, s = self.j('GET', '/api/status')
        self.assertEqual(code, 200)
        for k in ('version', 'host', 'user', 'uptime', 'mem', 'wifi', 'volume', 'brightness'):
            self.assertIn(k, s)

    def test_settings_never_keep_secrets(self):
        code, s = self.j('POST', '/api/settings', {'look': 'night', 'password': 'hunter2', 'wifi': {'password': 'x'}})
        self.assertEqual(code, 200)
        saved = json.load(open(self.settings))
        self.assertEqual(saved['look'], 'night')
        self.assertNotIn('password', saved)
        self.assertNotIn('wifi', saved)

    def test_home_assistant_token_stays_here(self):
        # a pretend Home Assistant on this computer
        import http.server
        seen = []

        class HA(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, data):
                body = json.dumps(data).encode()
                self.send_response(200 if self.headers.get('Authorization') == 'Bearer abc123' else 401)
                self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_GET(self):
                seen.append(('GET', self.path)); self.reply([{'entity_id': 'light.desk', 'state': 'on', 'attributes': {'friendly_name': 'Desk'}}])

            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                seen.append(('POST', self.path, json.loads(self.rfile.read(n) or b'{}'))); self.reply([])

        ha = http.server.ThreadingHTTPServer(('127.0.0.1', 0), HA)
        threading.Thread(target=ha.serve_forever, daemon=True).start()
        try:
            code, r = self.j('POST', '/api/settings', {'homeassistant': 'http://127.0.0.1:%d' % ha.server_address[1], 'ha_token': 'abc123'})
            self.assertEqual(code, 200)
            self.assertTrue(r['settings']['ha_token_set'])
            self.assertNotIn('ha_token', json.load(open(self.settings)), 'the token is not in the settings file')
            self.assertEqual(oct(os.stat(diced.ha_token_path(self.settings)).st_mode & 0o777), '0o600')
            code, page = self.req('GET', '/', token=False)
            self.assertNotIn(b'abc123', page, 'the token never reaches the page')
            code, r = self.j('POST', '/api/ha', {'path': '/api/states'})
            self.assertEqual(r['data'][0]['entity_id'], 'light.desk')
            code, r = self.j('POST', '/api/ha', {'path': '/api/services/light/toggle', 'body': {'entity_id': 'light.desk'}})
            self.assertTrue(r['ok'])
            self.assertEqual(seen[-1], ('POST', '/api/services/light/toggle', {'entity_id': 'light.desk'}))
            code, r = self.j('POST', '/api/ha', {'path': '/api/config/core/restart'})
            self.assertFalse(r['ok'], 'only states and services')
            code, r = self.j('POST', '/api/ha', {'path': '/api/states/../config'})
            self.assertFalse(r['ok'])
        finally:
            ha.shutdown()

    def test_files(self):
        rel = '~/' + os.path.basename(self.play)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'mkdir', 'path': rel + '/box'})[0], 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'text', 'path': rel + '/box/hi.txt', 'text': 'hello'})[0], 200)
        code, listing = self.j('GET', '/api/files?path=' + rel + '/box')
        self.assertEqual([i['name'] for i in listing['items']], ['hi.txt'])
        code, out = self.req('GET', '/api/file?path=' + rel + '/box/hi.txt')
        self.assertEqual(out, b'hello')
        code, out = self.req('POST', '/api/file?path=' + rel + '/box/raw.bin', body=b'\x00\x01', raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'rename', 'path': rel + '/box/hi.txt', 'to': 'hey.txt'})[0], 200)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'rename', 'path': rel + '/box/hey.txt', 'to': '../x'})[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'trash', 'path': rel + '/box/hey.txt'})[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.play, 'box', 'hey.txt')))
        # nothing outside home or plugged-in drives
        self.assertEqual(self.j('GET', '/api/files?path=/etc')[0], 400)
        self.assertEqual(self.req('GET', '/api/file?path=/etc/passwd')[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'text', 'path': '/tmp/escape.txt', 'text': 'x'})[0], 400)
        self.assertEqual(self.j('POST', '/api/files', {'op': 'trash', 'path': '~'})[0], 400)

    def test_dice_cloud_folder(self):
        rel = '~/' + os.path.basename(self.play) + '/Dice Cloud'
        # writing makes the folders, and keeps the time it's given
        code, r = self.req('POST', '/api/file?path=' + urllib.parse.quote(rel + '/Trips/2024/beach.jpg') + '&dirs=1&mtime=1700000000', body=b'jpeg!', raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(r)['mtime'], 1700000000)
        self.req('POST', '/api/file?path=' + urllib.parse.quote(rel + '/notes.txt'), body=b'hi', raw=True)
        self.req('POST', '/api/file?path=' + urllib.parse.quote(rel + '/.hidden'), body=b'no', raw=True)
        code, t = self.j('GET', '/api/files/tree?path=' + urllib.parse.quote(rel))
        self.assertEqual(sorted((f['path'], f['size']) for f in t['files']), [('Trips/2024/beach.jpg', 5), ('notes.txt', 2)])
        self.assertEqual(self.j('GET', '/api/files/tree?path=/etc')[1]['ok'], False)

    def test_trash_moving_and_room(self):
        rel = '~/' + os.path.basename(self.play)
        self.j('POST', '/api/files', {'op': 'mkdir', 'path': rel + '/tb'})
        self.j('POST', '/api/files', {'op': 'mkdir', 'path': rel + '/tb/in'})
        self.j('POST', '/api/files', {'op': 'text', 'path': rel + '/tb/note.txt', 'text': 'keep me'})
        # moving, and copying next to itself
        code, r = self.j('POST', '/api/files', {'op': 'move', 'path': rel + '/tb/note.txt', 'to': rel + '/tb/in'})
        self.assertEqual((code, r['path']), (200, rel + '/tb/in/note.txt'))
        self.assertEqual(self.j('POST', '/api/files', {'op': 'move', 'path': rel + '/tb', 'to': rel + '/tb/in'})[0], 400)
        code, r = self.j('POST', '/api/files', {'op': 'copy', 'path': rel + '/tb/in/note.txt', 'to': rel + '/tb/in'})
        self.assertEqual(r['path'], rel + '/tb/in/note copy.txt')
        # into the Trash with a note of where it was, and back again
        code, r = self.j('POST', '/api/files', {'op': 'trash', 'path': rel + '/tb/in/note.txt'})
        name = r['path']
        code, t = self.j('GET', '/api/trash')
        mine = [i for i in t['items'] if i['name'] == name]
        self.assertEqual(mine[0]['from'], rel + '/tb/in/note.txt')
        self.assertEqual(mine[0]['size'], 7)
        code, r = self.j('POST', '/api/files', {'op': 'restore', 'name': name})
        self.assertEqual((code, r['path']), (200, rel + '/tb/in/note.txt'))
        with open(os.path.join(self.play, 'tb', 'in', 'note.txt')) as f:
            self.assertEqual(f.read(), 'keep me')
        # its folder gone: it comes back home
        code, r = self.j('POST', '/api/files', {'op': 'trash', 'path': rel + '/tb/in/note copy.txt'})
        name = r['path']
        shutil.rmtree(os.path.join(self.play, 'tb', 'in'))
        code, r = self.j('POST', '/api/files', {'op': 'restore', 'name': name})
        self.assertEqual(r['path'], '~/note copy.txt')
        os.remove(os.path.expanduser(r['path'].replace('~', diced.Files(diced.desktop_user()).home, 1)))
        # gone for good
        code, r = self.j('POST', '/api/files', {'op': 'trash', 'path': rel + '/tb'})
        self.assertEqual(self.j('POST', '/api/files', {'op': 'forget', 'name': r['path']})[1]['count'], 1)
        self.assertNotIn(r['path'], [i['name'] for i in self.j('GET', '/api/trash')[1]['items']])
        self.assertEqual(self.j('POST', '/api/files', {'op': 'forget', 'name': '../../etc'})[0], 400)
        code, u = self.j('GET', '/api/files/usage')
        self.assertTrue(u['quota'] > u['used'] > 0)

    def test_flathub_catalog(self):
        import gzip
        root = tempfile.mkdtemp()
        apps = diced.Apps(root=root)
        base = apps.appstream()
        os.makedirs(os.path.join(base, 'icons', '128x128'))
        xml = '''<?xml version="1.0"?><components version="0.8" origin="flathub">
          <component type="desktop-application"><id>org.videolan.VLC</id><name>VLC</name><name xml:lang="fr">VLC fr</name>
            <summary>VLC media player, the open-source multimedia framework</summary><icon type="cached" width="128" height="128">org.videolan.VLC.png</icon>
            <categories><category>AudioVideo</category><category>Player</category></categories></component>
          <component type="desktop"><id>com.moonlight_stream.Moonlight.desktop</id><name>Moonlight</name><summary>Stream games from your NVIDIA GameStream and Sunshine servers</summary>
            <categories><category>Game</category></categories></component>
          <component type="runtime"><id>org.freedesktop.Platform</id><name>Freedesktop Platform</name></component>
          <component type="desktop-application"><id>bad id</id><name>Nope</name></component>
        </components>'''
        with gzip.open(os.path.join(base, 'appstream.xml.gz'), 'wt') as f:
            f.write(xml)
        cat = apps.catalog()
        self.assertEqual([a['id'] for a in cat], ['org.videolan.VLC', 'com.moonlight_stream.Moonlight'])
        self.assertEqual((cat[0]['name'], cat[0]['icon'], cat[0]['cats']), ('VLC', True, ['AudioVideo', 'Player']))
        self.assertEqual([a['id'] for a in apps.search('moon')], ['com.moonlight_stream.Moonlight'])
        self.assertEqual([a['id'] for a in apps.search('', 'AudioVideo')], ['org.videolan.VLC'])
        self.assertEqual([a['id'] for a in apps.search('stream games')], ['com.moonlight_stream.Moonlight'])
        open(os.path.join(base, 'icons', '128x128', 'org.videolan.VLC.png'), 'wb').close()
        self.assertTrue(apps.icon('org.videolan.VLC').endswith('org.videolan.VLC.png'))
        self.assertIsNone(apps.icon('../../etc/passwd'))
        self.assertEqual(apps.install('rm -rf /')['state'], 'failed')
        shutil.rmtree(root)

    def test_jobs_and_closing_the_app_on_top(self):
        apps = diced.Apps()
        j = apps.job('t', 'Testing', [[sys.executable, '-c', 'import sys; [print("Installing", p, "%") for p in (10, 50, 100)]'], [sys.executable, '-c', 'print("ok")']])
        for _ in range(200):  # (a busy computer takes a while to start two Pythons)
            if apps.jobs['t']['state'] != 'working':
                break
            time.sleep(0.05)
        self.assertEqual((apps.jobs['t']['state'], apps.jobs['t']['pct']), ('done', 100))
        apps.job('f', 'Failing', [[sys.executable, '-c', 'import sys; print("error: No remote refs found for x"); sys.exit(1)']])
        for _ in range(200):
            if apps.jobs['f']['state'] != 'working':
                break
            time.sleep(0.05)
        self.assertEqual(apps.jobs['f']['error'], 'No remote refs found for x')
        # something on top of Dice: Home closes it (and only when something's there)
        self.assertFalse(apps.close_front())
        was = os.environ.get('DICE_USER')
        os.environ['DICE_USER'] = __import__('pwd').getpwuid(os.getuid()).pw_name
        try:
            r = apps.launch([sys.executable, '-c', 'import time; time.sleep(30)'], 'Sleepy', 'web', 'x')
            self.assertTrue(r['ok'])
            self.assertEqual(apps.front()['name'], 'Sleepy')
            p = apps.running[-1]['proc']
            self.assertTrue(apps.close_front())
            p.wait(timeout=5)
            self.assertIsNone(apps.front())
        finally:
            if was is None:
                del os.environ['DICE_USER']
            else:
                os.environ['DICE_USER'] = was
        # a remote's Home, and Super + Esc, reach it; other keys don't
        hits = []
        keys = diced.PowerKeys(lambda ev: hits.append(ev), home=lambda: hits.append('home') or True)
        ev = lambda code, value: struct.pack('llHHi', 0, 0, 1, code, value)
        keys.handle(ev(172, 1) + ev(172, 0))
        keys.handle(ev(125, 1) + ev(1, 1) + ev(1, 0) + ev(125, 0) + ev(1, 1))
        self.assertEqual(hits, ['home', 'home'])
        r = diced.Remote('/nonexistent/settings.json')
        q = diced.queue.Queue()
        r.subs.add(q)
        r.intercept = lambda e: e['a'] in ('home', 'menu')
        r.press('key pressed: root menu (9) current(ff)')
        r.press('key pressed: up (1) current(ff)')
        self.assertEqual(q.get_nowait()['a'], 'up')

    def test_changing_this_computer_after_install(self):
        boot = diced.boot_module()
        ran, real_sh, real_open = [], boot.sh, boot.open if hasattr(boot, 'open') else None
        boot.sh = lambda cmd, **kw: (ran.append(cmd), (0, ''))[1]
        writes = {}

        class Buf:
            def __init__(self, p): self.p = p; self.t = ''
            def write(self, s): self.t += s
            def __enter__(self): return self
            def __exit__(self, *a): writes[self.p] = self.t

        import builtins
        boot.open = lambda p, mode='r', *a, **k: Buf(p) if str(p).startswith('/etc/') and 'w' in mode else builtins.open(p, mode, *a, **k)
        try:
            # SSH stays off while the password is still the one it came with
            r = diced.device_change(self.settings, {'timezone': 'America/New_York', 'keyboard': 'gb', 'ssh': True, 'looks': 'heaven', 'text': 'large'})  # its old name
            self.assertIn('Set the keyboard to gb', r['done'])
            self.assertTrue(any('SSH stayed off' in p for p in r['problems']))
            self.assertNotIn(['systemctl', 'enable', '--now', 'ssh'], ran)
            self.assertIn('XKBLAYOUT="gb"', writes['/etc/default/keyboard'])
            s = json.load(open(self.settings))
            self.assertEqual((s['looks'], s['text']), ('traced', 'large'))
            self.assertNotIn('welcome', s)  # Settings shows what happened itself
            # once a password of your own is set, it can
            s['password_set'] = True
            json.dump(s, open(self.settings, 'w'))
            r = diced.device_change(self.settings, {'ssh': True})
            self.assertIn(['systemctl', 'enable', '--now', 'ssh'], ran)
            self.assertEqual(diced.device_change(self.settings, {'nonsense': 1})['ok'], False)
            # a name it can't use is turned down
            r = diced.device_change(self.settings, {'computer': 'My PC!'})
            self.assertTrue(r['problems'])
        finally:
            boot.sh = real_sh
            if real_open is None:
                del boot.open
            else:
                boot.open = real_open

    def test_screens_inputs_like_a_kvm(self):
        M = diced.Monitors
        detect = 'Display 1\n   I2C bus:  /dev/i2c-6\n   DRM connector:           card1-DP-1\n   Monitor:                 DEL:DELL U2720Q:ABC123\n\nInvalid display\n   I2C bus:  /dev/i2c-9\n\nDisplay 2\n   I2C bus:  /dev/i2c-7\n   Monitor:  GSM::\n'
        self.assertEqual([(s['n'], s['name'], s['bus']) for s in M.parse_detect(detect)], [(1, 'DELL U2720Q', '/dev/i2c-6'), (2, 'Screen 2', '/dev/i2c-7')])
        caps = 'Model: U2720Q\n   Feature: 10 (Brightness)\n   Feature: 60 (Input Source)\n      Values:\n         1b: Unrecognized value\n         0f: DisplayPort-1\n         11: HDMI-1\n   Feature: 62 (Audio speaker volume)\n      Values: 00: off\n'
        self.assertEqual(M.parse_caps(caps), [0x1B, 0x0F, 0x11])
        self.assertEqual(M.parse_current('VCP 60 SNC x0f'), 0x0F)
        self.assertEqual(M.parse_current('VCP code 0x60 (Input Source                  ): HDMI-1 (sl=0x11)'), 0x11)
        self.assertIsNone(M.parse_current('Display not found'))
        # switching: what DiceOS is on is remembered, and "come back" goes there
        ran, real_run, real_has, real_glob = [], diced.run, diced.has, diced.glob.glob
        state = {'cur': 0x0F}

        def fake_run(cmd, **kw):
            ran.append(cmd)
            if cmd[:2] == ['ddcutil', 'detect']:
                return 0, detect
            if 'capabilities' in cmd:
                return 0, caps
            if 'getvcp' in cmd:
                return 0, 'VCP 60 SNC x%02x' % state['cur']
            if 'setvcp' in cmd:
                state['cur'] = int(cmd[-1], 16)
                return 0, ''
            return 1, ''
        diced.run, diced.has = fake_run, lambda p: p == 'ddcutil' or real_has(p)
        diced.glob.glob = lambda pat: ['/dev/i2c-6'] if pat.startswith('/dev/i2c') else real_glob(pat)
        try:
            m = diced.Monitors()
            L = m.list()
            self.assertTrue(L['ok'])
            ins = L['screens'][0]['inputs']
            self.assertEqual([(i['name'], i['here']) for i in ins], [('USB-C', False), ('DisplayPort 1', True), ('HDMI 1', False)])
            self.assertTrue(m.switch(1, 0x11)['ok'])
            self.assertIn(['ddcutil', '--display', '1', '--noverify', 'setvcp', '60', '0x11'], ran)
            self.assertEqual(state['cur'], 0x11)
            self.assertEqual(m.home[1], 0x0F)  # still DiceOS's input, not the one it switched to
            self.assertTrue(m.back()['ok'])
            self.assertEqual(state['cur'], 0x0F)
            self.assertFalse(m.switch(1, 999)['ok'])
            self.assertFalse(m.switch(40, 0x11)['ok'])
        finally:
            diced.run, diced.has, diced.glob.glob = real_run, real_has, real_glob
        diced.has = lambda p: False
        try:
            self.assertFalse(diced.Monitors().list()['ok'])
        finally:
            diced.has = real_has

    def test_remote_buttons_and_hdmi_things(self):
        got, closed = [], []
        keys = diced.PowerKeys(got.append, home=lambda: bool(closed) and closed.pop(), front=lambda: None, voice_key=lambda: 66)
        ev = lambda code, value: struct.pack('llHHi', 0, 0, 1, code, value)
        keys.handle(ev(158, 1) + ev(158, 2) + ev(158, 0))  # Back: down, a repeat (ignored), up
        keys.handle(ev(172, 1) + ev(172, 0))  # Home with nothing on top: Dice's Home
        closed.append(True)
        keys.handle(ev(172, 1) + ev(172, 0))  # Home with an app on top: closes it, nothing else
        keys.handle(ev(582, 1) + ev(582, 0) + ev(66, 1))  # the microphone button, and one taught in Settings
        self.assertEqual([(e['a'], e['down']) for e in got], [('b', True), ('b', False), ('home', True), ('home', False), ('voice', True), ('voice', False), ('voice', True)])
        got.clear()
        keys.front = lambda: {'name': 'VLC'}
        keys.handle(ev(158, 1))  # Back belongs to the app on top
        keys.learn = time.monotonic() + 5
        keys.handle(ev(250, 1))
        self.assertEqual(got, [{'learned': 250}])
        # the TV's bus: what's plugged in, switching to it, passing buttons on
        scan = ['CEC bus information', '===================', 'device #0: TV', 'address:       0.0.0.0', 'active source: no', 'vendor:        Samsung', 'osd string:    TV', 'power status:  on', '',
                'device #4: Playback 1', 'address:       1.0.0.0', 'active source: yes', 'osd string:    DiceOS', '', 'device #8: Playback 2', 'address:       2.0.0.0', 'active source: no',
                'vendor:        Sony', 'osd string:    PlayStation 5', 'power status:  standby', '', 'currently active source: Playback 1 (4)']
        devs = diced.Remote.parse_scan(scan)
        self.assertEqual([(d['la'], d['name'], d['pa']) for d in devs], [(0, 'TV', '0.0.0.0'), (4, 'DiceOS', '1.0.0.0'), (8, 'PlayStation 5', '2.0.0.0')])
        r = diced.Remote('/nonexistent/settings.json')
        sent = []

        class Pipe:
            def write(self, s):
                sent.append(s.strip())

            def flush(self):
                pass

        class Proc:
            stdin = Pipe()

            def poll(self):
                return None
        r.proc, r.la = Proc(), 4
        r.heard('logical address(es) = Playback 1 (4)')
        r.switch('2.0.0.0')
        r.key(8, 'a')
        r.key(8, 'd7')
        self.assertEqual(sent, ['tx 4F:86:20:00', 'tx 48:44:00', 'tx 48:45', 'tx 48:44:27', 'tx 48:45'])
        self.assertFalse(r.key(8, 'nope')['ok'])
        self.assertFalse(r.switch('2.0.0')['ok'])
        q = diced.queue.Queue()
        r.subs.add(q)
        r.heard("TV (0): power status changed from 'standby' to 'on'")
        self.assertEqual(q.get_nowait(), {'tv': 'on'})
        # Deuce: lookups only from the allowed places; listening needs setting up first
        self.assertFalse(diced.lookup('https://evil.example/x')['ok'])
        self.assertFalse(diced.lookup('http://site.api.espn.com/x')['ok'])
        v = diced.Voice(lambda e: None, diced.Apps())
        v.ROOT = tempfile.mkdtemp()
        self.assertEqual(v.start()['need'], 'setup')
        self.assertFalse(v.status()['ready'])

    def test_antenna_tuner_stays_local(self):
        for h in ('hdhomerun.local', '192.168.1.40', '10.0.0.7', 'hdhomerun', '172.20.1.2'):
            self.assertTrue(diced.local_host(h), h)
        for h in ('example.com', '8.8.8.8', '172.40.1.1', 'a b', ''):
            self.assertFalse(diced.local_host(h), h)
        self.assertFalse(diced.tuner_lineup('evil.example')['ok'])
        self.assertFalse(diced.Apps().watch('http://example.com/auto/v4.1', 'x')['ok'])

    def test_standby_and_wake(self):
        code, r = self.j('POST', '/api/power', {'action': 'standby'})
        self.assertEqual((code, r['ok']), (200, True))
        self.assertTrue(self.j('GET', '/api/status')[1]['standby'])
        code, r = self.j('POST', '/api/power', {'action': 'wake'})
        self.assertTrue(r['was'])
        self.assertFalse(self.j('GET', '/api/status')[1]['standby'])

    def test_moonlight_game_lists(self):
        self.assertEqual(diced.Apps.parse_games('Desktop\nSteam Big Picture\n\n'), ['Desktop', 'Steam Big Picture'])
        self.assertEqual(diced.Apps.parse_games('Name, ID, HDR, App collection, Hidden, Direct launch, Boxart URL\n"Desktop", 1, false, false, false, false, \nSteam Big Picture, 2, false, false, false, false, x'), ['Desktop', 'Steam Big Picture'])
        apps = diced.Apps(root='/nonexistent')
        apps.moonlight = lambda: None
        self.assertEqual(apps.games('pc.local')['need'], 'moonlight')
        apps.moonlight = lambda: ['true']
        self.assertFalse(apps.games('pc; rm -rf /')['ok'])
        self.assertEqual(apps.pair('pc.local', '12345')['state'], 'failed')
        self.assertFalse(apps.play('pc.local', 'a\nb')['ok'])

    def test_only_web_addresses_open(self):
        code, r = self.j('POST', '/api/open', {'url': 'file:///etc/passwd'})
        self.assertFalse(r['ok'])

    def test_tv_remote_keys(self):
        self.assertEqual(diced.parse_cec_key('DEBUG:   [ 1234]\tkey pressed: select (0) current(ff) duration(0)'), ('a', 'select'))
        self.assertEqual(diced.parse_cec_key('key pressed: F2 (red) (72) current(ff)'), ('red', 'F2 (red)'))
        self.assertEqual(diced.parse_cec_key('key pressed: channel up (30)'), ('rb', 'channel up'))
        self.assertEqual(diced.parse_cec_key('key pressed: 7 (27)'), ('d7', '7'))
        self.assertIsNone(diced.parse_cec_key('key released: select (0) D:120ms'))
        self.assertIsNone(diced.parse_cec_key('key pressed: something odd (fe)'))
        r = diced.Remote('/nonexistent/settings.json')
        q = diced.queue.Queue()
        r.subs.add(q)
        self.assertEqual(r.press('key pressed: up (1) current(ff)'), {'a': 'up', 'key': 'up'})
        self.assertIsNone(r.press('key pressed: up (1) current(ff)'))  # the same press, said twice at once
        self.assertEqual(q.get_nowait(), {'a': 'up', 'key': 'up'})
        self.assertFalse(r.send('format the disk')['ok'])

    def test_version_comes_from_the_version_file(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(diced.__file__))), 'VERSION')) as f:
            self.assertEqual(diced.VERSION, f.read().strip())

    def test_shield_keeps_its_own_part_of_the_hosts_file(self):
        d = tempfile.mkdtemp()
        try:
            hosts, lst, settings = os.path.join(d, 'hosts'), os.path.join(d, 'domains.txt'), os.path.join(d, 'settings.json')
            mine = '127.0.0.1 localhost\n::1 ip6-localhost\n192.168.1.5 nas # my own line\n'
            with open(hosts, 'w') as f:
                f.write(mine)
            with open(lst, 'w') as f:
                f.write('# notes\nads.example.com\ntracker.test\ngithub.com\nnot an address\n')
            sh = diced.Shield(settings, hosts=hosts, store=os.path.join(d, 'store'), builtin=lst)
            st = sh.apply()
            with open(hosts) as f:
                text = f.read()
            self.assertTrue(text.startswith(mine))                       # nothing of yours is touched
            self.assertIn('0.0.0.0 ads.example.com\n', text)
            self.assertNotIn('github.com', text)                         # what DiceOS needs is never blocked
            self.assertEqual(st['blocking'], 2)
            self.assertTrue(st['system'])
            sh.change({'action': 'allow', 'site': 'tracker.test'})        # let one through
            self.assertNotIn('tracker.test', open(hosts).read())
            self.assertEqual(sh.cfg()['allow'], ['tracker.test'])
            self.assertFalse(sh.change({'action': 'allow', 'site': 'no such thing'})['ok'])
            sh.change({'system': False})                                  # off: the hosts file is as it was
            self.assertEqual(open(hosts).read(), mine)
            sh.change({'system': True})
            self.assertEqual(sh.ours(), 1)
            # the big list, as the web gives it
            names = diced.Shield.names_in('# Title: StevenBlack\n127.0.0.1 localhost\n0.0.0.0 0.0.0.0\n0.0.0.0 a.ads.test # x\n0.0.0.0 b.ads.test\n0.0.0.0 raw.githubusercontent.com\n')
            self.assertEqual(names, {'a.ads.test', 'b.ads.test'})
            big = '\n'.join('0.0.0.0 ad%d.example.net' % i for i in range(1500))

            class Answer:
                def __init__(self, body): self.body = body
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self, n=-1): return self.body.encode()
            real = diced.urllib.request.urlopen
            diced.urllib.request.urlopen = lambda req, timeout=0: Answer(big)
            try:
                st = sh.update()
            finally:
                diced.urllib.request.urlopen = real
            self.assertTrue(st['ok'])
            self.assertEqual(st['big'], 1500)
            self.assertEqual(sh.ours(), 1501)
            diced.urllib.request.urlopen = lambda req, timeout=0: Answer('0.0.0.0 just.one.test\n')
            try:
                st = sh.update()                                           # a list that's too short isn't used
            finally:
                diced.urllib.request.urlopen = real
            self.assertFalse(st['ok'])
            self.assertEqual(sh.ours(), 1501)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_links_from_other_apps_open_in_serenetab(self):
        sysm = self.srv.system
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('POST', '/api/browse', body=json.dumps({'url': 'https://example.com/'}), headers={'Host': '127.0.0.1:%d' % self.port, 'X-Dice-Open': 'wrong'})
        r = c.getresponse(); r.read(); c.close()
        self.assertEqual(r.status, 403)
        q = __import__('queue').Queue()
        with sysm.remote.lock:
            sysm.remote.subs.add(q)
        try:
            c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            c.request('POST', '/api/browse', body=json.dumps({'url': 'https://example.com/a?b=1'}), headers={'Host': '127.0.0.1:%d' % self.port, 'X-Dice-Open': diced.OPEN_TOKEN})
            r = c.getresponse(); out = json.loads(r.read()); c.close()
            self.assertEqual(out, {'ok': True, 'where': 'serenetab'})
            self.assertEqual(q.get(timeout=2), {'browse': 'https://example.com/a?b=1'})
            self.assertFalse(sysm.browse('file:///etc/passwd')['ok'])
            self.assertFalse(sysm.browse('javascript:alert(1)')['ok'])
        finally:
            with sysm.remote.lock:
                sysm.remote.subs.discard(q)
        # a browser window's new tab page: SereneTab, and no secret in it
        code, page = self.req('GET', '/?serene=1', token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'DICE_SERENE', page)
        self.assertNotIn(diced.TOKEN.encode(), page)
        self.assertNotIn(b'DICE_SYS', page)

    def test_deuce_answers_from_the_web(self):
        d = tempfile.mkdtemp()
        try:
            duck = ('<div><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.nasa.gov%2Fsky&amp;rut=x">Why is the sky blue? - NASA</a>'
                    '<a class="result__snippet" href="x">Sunlight is <b>scattered</b> by the air.</a></div>'
                    '<div><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">An ad</a></div>'
                    '<div><a class="result__a" href="https://example.org/blue">Blue light</a><a class="result__snippet" href="y">Short waves scatter more.</a></div>')
            asked = []

            def fetch(url, data=None, headers=None, limit=0, timeout=0):
                asked.append(url)
                if 'duckduckgo' in url:
                    return duck, 'text/html'
                if 'w/api.php' in url:
                    return json.dumps({'query': {'search': [{'title': 'Diffuse sky radiation'}]}}), 'application/json'
                if 'rest_v1' in url:
                    return json.dumps({'title': 'Diffuse sky radiation', 'extract': 'The sky looks blue because air scatters blue light most. It is called Rayleigh scattering. More text.'}), 'application/json'
                if 'chat/completions' in url:
                    body = json.loads(data)
                    self.assertIn('[1]', body['messages'][-1]['content'])
                    self.assertEqual(headers['Authorization'], 'Bearer gsk_testkey12345')
                    return json.dumps({'choices': [{'message': {'content': 'Air scatters blue light the most [1][2].'}}]}), 'application/json'
                return '<html><body><p>' + 'Blue light has a short wavelength and is scattered by gas molecules. ' * 3 + '</p></body></html>', 'text/html'
            a = diced.Answers(os.path.join(d, 'settings.json'), fetch=fetch)
            out = a.ask('why is the sky blue')
            self.assertTrue(out['ok'])
            self.assertIsNone(out['ai'])
            self.assertEqual([s['site'] for s in out['sources']], ['nasa.gov', 'en.wikipedia.org', 'example.org'])
            self.assertNotIn('An ad', json.dumps(out))
            self.assertIn('[1]', out['answer'])
            # an AI of your own
            self.assertFalse(a.set_ai({'provider': 'groq', 'key': 'x'})['ok'])
            self.assertFalse(a.set_ai({'provider': 'nope', 'key': 'gsk_testkey12345'})['ok'])
            pub = a.set_ai({'provider': 'groq', 'key': 'gsk_testkey12345'})
            self.assertTrue(pub['set'])
            self.assertNotIn('gsk_testkey12345', json.dumps(pub))
            self.assertEqual(stat_mode(a.key_path()), 0o600)
            out = a.ask('why is the sky blue', [{'q': 'hi', 'a': 'hello'}])
            self.assertEqual(out['answer'], 'Air scatters blue light the most [1][2].')
            self.assertEqual(out['ai'], 'Groq')
            self.assertTrue(a.set_ai({'provider': 'groq'})['set'])        # same AI, key kept
            self.assertFalse(a.set_ai({'provider': ''})['set'])           # and forgotten
            self.assertFalse(a.ask('   ')['ok'])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_start_up_splash_follows_traced_mode(self):
        d = tempfile.mkdtemp()
        try:
            settings, themes = os.path.join(d, 'settings.json'), os.path.join(d, 'themes')
            os.makedirs(os.path.join(themes, 'dice-heaven'))  # the old one goes
            self.assertEqual(diced.ensure_splash(settings, themes=themes, real=False), 'dice')
            self.assertFalse(os.path.exists(os.path.join(themes, 'dice-heaven')))
            for name in ('dice', 'dice-traced'):
                self.assertTrue(os.path.isfile(os.path.join(themes, name, name + '.script')))
                self.assertTrue(os.path.isfile(os.path.join(themes, name, 'restarting.png')))
            self.assertTrue(os.path.isfile(os.path.join(themes, 'dice-traced', 'scene.png')))
            diced.save_settings(settings, {'looks': 'traced'})
            self.assertEqual(diced.ensure_splash(settings, themes=themes, real=False), 'dice-traced')
            diced.save_settings(settings, {'looks': 'heaven'})  # its old name still works
            self.assertEqual(diced.ensure_splash(settings, themes=themes, real=False), 'dice-traced')
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_updates_bring_the_power_button_rule(self):
        etc = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(etc, 'xdg'))
            with open(os.path.join(etc, 'xdg', 'mimeapps.list'), 'w') as f:
                f.write('[Default Applications]\nimage/png=photos.desktop\nx-scheme-handler/https=firefox.desktop\n\n[Added Associations]\ntext/plain=edit.desktop\n')
            self.assertTrue(diced.ensure_system_files(etc=etc))
            with open(os.path.join(etc, 'systemd', 'logind.conf.d', 'dice.conf')) as f:
                self.assertIn('HandlePowerKey=ignore', f.read())
            # SereneTab is the computer's web browser
            with open(os.path.join(etc, 'usr-share', 'applications', 'serenetab.desktop')) as f:
                self.assertIn('bin/dice-open %U', f.read())
            with open(os.path.join(etc, 'chromium', 'policies', 'managed', 'dice-serenetab.json')) as f:
                self.assertIn('?serene=1', json.load(f)['NewTabPageLocation'])
            with open(os.path.join(etc, 'xdg', 'mimeapps.list')) as f:
                mime = f.read()
            self.assertIn('image/png=photos.desktop', mime)              # yours stay
            self.assertIn('text/plain=edit.desktop', mime)
            self.assertIn('x-scheme-handler/https=serenetab.desktop', mime)
            self.assertIn('x-scheme-handler/http=serenetab.desktop', mime)
            self.assertNotIn('firefox', mime)
            self.assertEqual(mime.count('[Default Applications]'), 1)
            self.assertFalse(diced.ensure_system_files(etc=etc))  # already there
        finally:
            shutil.rmtree(etc, ignore_errors=True)

    def test_finding_files(self):
        home = tempfile.mkdtemp()
        try:
            for p in ('Documents/essay draft.txt', 'Documents/old/Essay notes.md', 'Music/song.mp3', '.secret/essay.txt', 'node_modules/essay.js'):
                full = os.path.join(home, p)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                open(full, 'w').close()
            f = diced.Files.__new__(diced.Files)
            f.user, f.home, f.roots = 'me', os.path.realpath(home), [os.path.realpath(home)]
            got = [x['path'] for x in f.find('essay')]
            self.assertEqual(got, ['~/Documents/essay draft.txt', '~/Documents/old/Essay notes.md'])  # not hidden ones, not node_modules
            self.assertEqual([x['name'] for x in f.find('ess notes')], ['Essay notes.md'])
            self.assertTrue(f.find('documents')[0]['dir'])
            self.assertEqual(f.find('   '), [])
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_power_key(self):
        # capabilities/key: words of a long each, most significant first; KEY_POWER is bit 116
        self.assertIn(116, diced.key_bits('10000000000000 0', 64))
        self.assertIn(116, diced.key_bits('100000 0 0 0', 32))  # a 32-bit kernel
        self.assertIn(30, diced.key_bits('1000000000007 ff800000000007ff febeffdfffefffff fffffffffffffffe', 64))  # a keyboard: KEY_A
        self.assertNotIn(116, diced.key_bits('0'))
        self.assertEqual(diced.key_bits(''), set())
        ev = diced.INPUT_EVENT
        raw = ev.pack(0, 0, 4, 4, 0x70) + ev.pack(0, 0, 1, 116, 1) + ev.pack(0, 0, 0, 0, 0) + ev.pack(0, 0, 1, 116, 0)
        self.assertEqual(diced.parse_input_events(raw), [(116, 1), (116, 0)])
        got = []
        pk = diced.PowerKeys(got.append, root='/nonexistent')
        pk.handle(raw)
        pk.handle(raw)  # the same press from a second device, at once
        self.assertEqual(got, [{'a': 'power', 'key': 'Power'}])
        pk.start()
        self.assertFalse(pk.started)  # nothing to watch here

    def test_remote_events_stream(self):
        import http.client
        code, r = self.j('GET', '/api/remote')
        self.assertEqual(code, 200)
        self.assertIn('available', r)
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('GET', '/api/events', headers={'X-Dice': diced.TOKEN})
        res = c.getresponse()
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader('Content-Type'), 'text/event-stream')
        first = res.fp.readline().decode()
        self.assertTrue(first.startswith('data: ') and '"cec"' in first)
        c.close()
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('GET', '/api/events')
        self.assertEqual(c.getresponse().status, 403)  # not without the secret
        c.close()

    def test_bluetooth_lists(self):
        devs = diced.parse_bt_devices('Device 5C:BA:37:1F:20:8A Wireless Controller\nDevice 00:1b:66:a2:4c:17 Speaker\nnot a device\nDevice 5C:BA:37:1F:20:8A Wireless Controller')
        self.assertEqual([d['mac'] for d in devs], ['5C:BA:37:1F:20:8A', '00:1B:66:A2:4C:17'])
        info = diced.parse_bt_info('Device 5C:BA:37:1F:20:8A (public)\n\tName: Wireless Controller\n\tIcon: input-gaming\n\tPaired: yes\n\tTrusted: yes\n\tConnected: no\n\tBattery Percentage: 0x50 (80)')
        self.assertEqual((info['paired'], info['connected'], info['icon'], info['battery']), (True, False, 'input-gaming', 80))
        self.assertTrue(diced.bt_worked(0, 'Attempting to pair with X\nPairing successful'))
        self.assertFalse(diced.bt_worked(1, 'Failed to pair: org.bluez.Error.AuthenticationFailed'))
        self.assertIn('pairing mode', diced.friendly_bt('Failed to pair: org.bluez.Error.AuthenticationFailed'))

    def test_bluetooth_only_takes_real_addresses(self):
        real_has = diced.has
        diced.has = lambda p: True if p == 'bluetoothctl' else real_has(p)
        try:
            for mac in ('', 'AA:BB', '5C:BA:37:1F:20:8A; reboot', '../../etc'):
                code, r = self.j('POST', '/api/bluetooth', {'action': 'pair', 'mac': mac})
                self.assertFalse(r['ok'])
                self.assertIn("isn't a Bluetooth device", r['error'])
        finally:
            diced.has = real_has

    def test_screenshot_needs_grim_and_a_screen(self):
        code, r = self.j('POST', '/api/screenshot', {})
        self.assertEqual(code, 200)
        if not diced.has('grim'):
            self.assertIn('grim', r['error'])

    def test_nm_fields(self):
        self.assertEqual(diced.split_nm(r'yes:My\:Net:80'), ['yes', 'My:Net', '80'])

    def ws_open(self, token):
        s = socket.create_connection(('127.0.0.1', self.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(('GET /api/term?token=%s&cols=80&rows=24 HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:%d\r\n\r\n' % (token, self.port, key, self.port)).encode())
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = s.recv(1)
            if not chunk:
                break
            head += chunk
        return s, head, key

    def test_terminal(self):
        s, head, key = self.ws_open('nope')
        self.assertIn(b' 403 ', head.split(b'\r\n')[0])
        s.close()
        s, head, key = self.ws_open(diced.TOKEN)
        self.assertIn(b' 101 ', head.split(b'\r\n')[0])
        self.assertIn(diced.ws_accept(key).encode(), head)
        mask = os.urandom(4)
        msg = b'echo dice-$((6*7))\n'
        s.sendall(bytes([0x82, 0x80 | len(msg)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))
        got, end = b'', time.time() + 8
        s.settimeout(1)
        while b'dice-42' not in got and time.time() < end:
            try:
                data = s.recv(4096)
                if not data:
                    break
                got += data
            except socket.timeout:
                pass
        self.assertIn(b'dice-42', got)
        s.close()



class FakeOllama(threading.Thread):
    """A pretend Ollama: two models, and a chat that answers a few words at a time, then asks for a tool."""
    def __init__(self):
        import http.server
        seen = self.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *a):
                pass

            def out(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/api/tags':
                    return self.out({'models': [{'name': 'qwen3.5:4b'}, {'name': 'qwen3.5:9b'}]})
                if self.path == '/api/version':
                    return self.out({'version': '0.40.17'})
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                seen.append((self.path, b))
                if self.path == '/api/chat':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/x-ndjson')
                    self.end_headers()
                    for line in ({'message': {'role': 'assistant', 'content': 'Setting '}}, {'message': {'role': 'assistant', 'content': 'a timer.'}},
                                 {'message': {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'do', 'arguments': {'command': 'set a timer for 10 minutes'}}}]}},
                                 {'done': True}):
                        self.wfile.write(json.dumps(line).encode() + b'\n')
                        self.wfile.flush()
                    return
                if self.path == '/api/pull':
                    self.send_response(200)
                    self.end_headers()
                    for line in ({'status': 'pulling manifest'}, {'status': 'pulling abc', 'total': 100, 'completed': 50}, {'status': 'success'}):
                        self.wfile.write(json.dumps(line).encode() + b'\n')
                    return
                return self.out({})

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        super().__init__(target=self.httpd.serve_forever, daemon=True)


class BrainTest(unittest.TestCase):
    # its own diced, set up like DicedTest's (without running DicedTest's tests again)
    setUpClass = classmethod(DicedTest.setUpClass.__func__)
    tearDownClass = classmethod(DicedTest.tearDownClass.__func__)
    req = DicedTest.req
    j = DicedTest.j
    def test_the_brain_is_picked_for_the_computer(self):
        pick = diced.brain_pick
        self.assertEqual(pick({'pi': True, 'ram': 7.8}), 'qwen3.5:4b')
        self.assertEqual(pick({'pi': True, 'ram': 3.8}), 'qwen3.5:2b')
        self.assertEqual(pick({'pi': True, 'ram': 15.8}), 'qwen3.5:4b')  # a Pi is too slow for more
        self.assertEqual(pick({'ram': 7.6}), 'qwen3.5:4b')
        self.assertEqual(pick({'ram': 15.5}), 'qwen3.5:9b')
        self.assertEqual(pick({'ram': 16, 'vram': 8}), 'qwen3.5:9b')
        self.assertEqual(pick({'ram': 32, 'vram': 24}), 'qwen3.5:35b')
        self.assertEqual(pick({'ram': 16, 'vram': 24}), 'qwen3.5:27b')
        self.assertEqual(pick({'ram': 64}), 'qwen3.5:35b')
        self.assertEqual(pick({'ram': 3}), 'qwen3.5:2b')

    def test_deuce_talks_to_the_brain_a_few_words_at_a_time(self):
        fake = FakeOllama()
        fake.start()
        old = diced.OLLAMA
        diced.OLLAMA = 'http://127.0.0.1:%d' % fake.httpd.server_address[1]
        try:
            code, st = self.j('GET', '/api/brain')
            self.assertEqual(code, 200)
            self.assertTrue(st['running'] and st['ready'])
            self.assertEqual(st['version'], '0.40.17')
            self.assertEqual(st['model'], 'qwen3.5:9b')  # the best one that's here
            self.assertEqual([c['tag'] for c in st['choices']][:2], ['qwen3.5:2b', 'qwen3.5:4b'])
            code, st = self.j('POST', '/api/brain', {'action': 'choose', 'model': 'qwen3.5:4b'})
            self.assertEqual(st['model'], 'qwen3.5:4b')
            code, st = self.j('POST', '/api/brain', {'action': 'choose', 'model': 'llama-evil:70b'})
            self.assertFalse(st['ok'])
            # the conversation goes through, trimmed; the answer streams back line by line
            msgs = [{'role': 'system', 'content': 'You are Deuce.'}, {'role': 'user', 'content': 'timer 10'}, {'role': 'evil', 'content': 'x'},
                    {'role': 'tool', 'content': 'ok', 'tool_name': 'do'}]
            code, out = self.req('POST', '/api/brain/chat', {'messages': msgs, 'tools': [{'type': 'function', 'function': {'name': 'do'}}]})
            self.assertEqual(code, 200)
            lines = [json.loads(x) for x in out.decode().splitlines() if x.strip()]
            self.assertEqual(''.join(x.get('message', {}).get('content', '') for x in lines), 'Setting a timer.')
            self.assertEqual(lines[2]['message']['tool_calls'][0]['function']['arguments']['command'], 'set a timer for 10 minutes')
            sent = [b for p, b in fake.seen if p == '/api/chat'][-1]
            self.assertEqual(sent['model'], 'qwen3.5:4b')
            self.assertEqual([m['role'] for m in sent['messages']], ['system', 'user', 'tool'])
            self.assertFalse(sent['think'])
            self.assertEqual(sent['keep_alive'], '30m')
            # only from the desktop
            code, _ = self.req('POST', '/api/brain/chat', {'messages': msgs}, token=False)
            self.assertEqual(code, 403)
            # fetching a model shows how far along it is, then picks it
            b = diced.Brain(self.settings)
            b.pull('qwen3.5:9b')
            self.assertIsNone(b.busy)
            self.assertIsNone(b.error)
            self.assertEqual(b.cfg()['model'], 'qwen3.5:9b')
        finally:
            diced.OLLAMA = old
            fake.httpd.shutdown()

    def test_without_the_brain_deuce_says_how_to_set_it_up(self):
        old = diced.OLLAMA
        diced.OLLAMA = 'http://127.0.0.1:9'  # nothing there
        try:
            code, st = self.j('GET', '/api/brain')
            self.assertFalse(st['running'])
            self.assertFalse(st['ready'])
            self.assertIn(st['recommended'], diced.BRAIN_TAGS)
            code, r = self.j('POST', '/api/brain/chat', {'messages': [{'role': 'user', 'content': 'hi'}]})
            self.assertEqual(code, 503)
            self.assertIn('Settings, Deuce', r['error'])
        finally:
            diced.OLLAMA = old

    def test_gossip_passes_through_to_its_relay(self):
        import http.server
        seen = []

        class Relay(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                m = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(m)
                out = json.dumps({'t': 'ok', 'v': 1, 'nonce': 'n0nce'} if m['t'] == 'hello' else {'t': 'err', 'code': 'bad_session', 'msg': 'Sign in first'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)
        relay = http.server.HTTPServer(('127.0.0.1', 0), Relay)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        old = diced.GOSSIP_RELAY
        diced.GOSSIP_RELAY = 'http://127.0.0.1:%d/api' % relay.server_address[1]
        try:
            code, r = self.j('POST', '/api/gossip', {'t': 'hello'})
            self.assertEqual((code, r['t'], r['nonce']), (200, 'ok', 'n0nce'))
            code, r = self.j('POST', '/api/gossip', {'t': 'poll', 'token': 'x'})
            self.assertEqual(r['code'], 'bad_session')
            code, r = self.j('POST', '/api/gossip', {'t': '../../etc'})
            self.assertEqual(r['code'], 'bad_request')
            self.assertEqual([m['t'] for m in seen], ['hello', 'poll'])
        finally:
            diced.GOSSIP_RELAY = old
            relay.shutdown()

    def test_deuce_reads_the_web_not_your_network(self):
        for url in ('http://127.0.0.1:11434/api/tags', 'http://192.168.1.1/', 'http://localhost/', 'http://router/', 'file:///etc/passwd', 'http://[::1]/'):
            code, r = self.j('POST', '/api/read', {'url': url})
            self.assertEqual(code, 400, url)
        self.assertTrue(diced.is_private_url('http://10.0.0.5/admin'))


if __name__ == '__main__':
    unittest.main()
