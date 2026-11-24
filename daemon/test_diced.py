#!/usr/bin/env python3
"""Tests for diced.  python3 -m unittest discover -s daemon"""
import base64
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

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
