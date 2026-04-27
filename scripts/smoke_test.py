#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request


@dataclass
class MockState:
    webhook_calls: int = 0
    webhook_ids: list[str] = field(default_factory=list)
    telegram_calls: int = 0
    email_calls: int = 0
    last_telegram_text: str = ''


class MockHandler(BaseHTTPRequestHandler):
    state: MockState | None = None

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8') if length else '{}'

        if self.path == '/webhook':
            MockHandler.state.webhook_calls += 1
            MockHandler.state.webhook_ids.append(self.headers.get('X-Lead-ID', ''))
            if MockHandler.state.webhook_calls < 3:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'fail')
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
            return

        if self.path.startswith('/bot') and self.path.endswith('/sendMessage'):
            MockHandler.state.telegram_calls += 1
            payload = json.loads(body)
            MockHandler.state.last_telegram_text = payload.get('text', '')
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if self.path == '/email':
            MockHandler.state.email_calls += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_mock_server(port: int, state: MockState):
    MockHandler.state = state
    server = ThreadingHTTPServer(('127.0.0.1', port), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def post_json(url: str, payload: dict, origin: str | None = None):
    req = request.Request(url, data=json.dumps(payload).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    if origin:
        req.add_header('Origin', origin)
    try:
        with request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        if hasattr(exc, 'code') and hasattr(exc, 'read'):
            return exc.code, json.loads(exc.read().decode('utf-8'))
        raise


def main():
    state = MockState()
    mock_port = 18081
    app_port = 18080
    mock_server = start_mock_server(mock_port, state)

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env.update(
            {
                'PORT': str(app_port),
                'LEAD_LOG_DIR': tmpdir,
                'LEAD_WEBHOOK_URL': f'http://127.0.0.1:{mock_port}/webhook',
                'ALLOWED_ORIGINS': f'http://localhost:{app_port}',
                'MAX_REQUESTS_PER_MINUTE_IP': '5',
                'MAX_LEADS_PER_HOUR_IP': '100',
                'TELEGRAM_BOT_TOKEN': 'test-token',
                'TELEGRAM_CHAT_ID': '123',
                'TELEGRAM_API_BASE': f'http://127.0.0.1:{mock_port}',
                'ALERT_EMAIL_WEBHOOK_URL': f'http://127.0.0.1:{mock_port}/email',
            }
        )

        app = subprocess.Popen(['python', 'app.py'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.5)

            # Positive flow + webhook retry + notifications
            status, body = post_json(
                f'http://127.0.0.1:{app_port}/api/lead',
                {
                    'name': 'Иван',
                    'phone': '+79990000000',
                    'utm_source': 'google',
                    'utm_medium': 'cpc',
                    'utm_campaign': 'volga',
                    'website': '',
                },
                origin=f'http://localhost:{app_port}',
            )
            assert status == 200, body
            assert body['ok'] is True
            assert body['forwarded'] is True
            assert state.webhook_calls == 3, f'expected 3 retries, got {state.webhook_calls}'
            assert len(set(state.webhook_ids)) == 1, 'X-Lead-ID should be stable across retries'
            assert state.telegram_calls >= 1
            assert state.email_calls >= 1
            assert 'Телефон:' in state.last_telegram_text and 'UTM source:' in state.last_telegram_text

            # CORS block
            status, body = post_json(
                f'http://127.0.0.1:{app_port}/api/lead',
                {'phone': '+79990000000'},
                origin='https://evil.example',
            )
            assert status == 403 and body['message'] == 'origin forbidden'

            # reCAPTCHA validation branch: empty token with secret configured
            env_recaptcha = env | {'RECAPTCHA_SECRET': 'prod-secret'}
            app.terminate()
            app.wait(timeout=3)
            app = subprocess.Popen(['python', 'app.py'], env=env_recaptcha, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            status, body = post_json(
                f'http://127.0.0.1:{app_port}/api/lead',
                {'phone': '+79990000000', 'website': ''},
                origin=f'http://localhost:{app_port}',
            )
            assert status == 400 and body['message'] == 'bot verification failed'

            # Rate-limit test: 6 requests with limit=5/min
            for _ in range(5):
                post_json(
                    f'http://127.0.0.1:{app_port}/api/lead',
                    {'phone': '+79990000000', 'website': ''},
                    origin=f'http://localhost:{app_port}',
                )
            status, body = post_json(
                f'http://127.0.0.1:{app_port}/api/lead',
                {'phone': '+79990000000', 'website': ''},
                origin=f'http://localhost:{app_port}',
            )
            assert status == 429 and body['message'] in {'rate limit exceeded', 'too many leads from ip'}

            log_file = Path(tmpdir) / 'leads.jsonl'
            assert log_file.exists(), 'leads.jsonl should be created'
            assert log_file.read_text(encoding='utf-8').strip(), 'leads log should not be empty'

            print('SMOKE TEST: PASS')
        finally:
            app.terminate()
            try:
                app.wait(timeout=3)
            except subprocess.TimeoutExpired:
                app.kill()
            mock_server.shutdown()


if __name__ == '__main__':
    main()
