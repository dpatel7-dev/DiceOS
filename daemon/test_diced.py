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
            r = diced.device_change(self.settings, {'timezone': 'America/New_York', 'keyboard': 'gb', 'ssh': True, 'looks': 'heaven', 'text': 'large'})
            self.assertIn('Set the keyboard to gb', r['done'])
            self.assertTrue(any('SSH stayed off' in p for p in r['problems']))
            self.assertNotIn(['systemctl', 'enable', '--now', 'ssh'], ran)
            self.assertIn('XKBLAYOUT="gb"', writes['/etc/default/keyboard'])
            s = json.load(open(self.settings))
            self.assertEqual((s['looks'], s['text']), ('heaven', 'large'))
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

    def test_updates_bring_the_power_button_rule(self):
        etc = tempfile.mkdtemp()
        try:
            self.assertTrue(diced.ensure_system_files(etc=etc))
            with open(os.path.join(etc, 'systemd', 'logind.conf.d', 'dice.conf')) as f:
                self.assertIn('HandlePowerKey=ignore', f.read())
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


if __name__ == '__main__':
    unittest.main()
