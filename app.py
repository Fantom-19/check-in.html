import json
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request as urlrequest

HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', '8080'))
WEBHOOK_URL = os.getenv('LEAD_WEBHOOK_URL', '').strip()
LOG_DIR = Path(os.getenv('LEAD_LOG_DIR', 'data'))
ALLOWED_ORIGINS = {
    origin.strip() for origin in os.getenv('ALLOWED_ORIGINS', 'http://localhost:8080').split(',') if origin.strip()
}
RECAPTCHA_SECRET = os.getenv('RECAPTCHA_SECRET', '').strip()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
TELEGRAM_API_BASE = os.getenv('TELEGRAM_API_BASE', 'https://api.telegram.org').strip().rstrip('/')
ALERT_EMAIL_WEBHOOK_URL = os.getenv('ALERT_EMAIL_WEBHOOK_URL', '').strip()

# Rate limits and throttling
MAX_REQUESTS_PER_MINUTE_IP = int(os.getenv('MAX_REQUESTS_PER_MINUTE_IP', '20'))
MAX_LEADS_PER_HOUR_IP = int(os.getenv('MAX_LEADS_PER_HOUR_IP', '10'))
RATE_WINDOW_SECONDS = 60
LEAD_WINDOW_SECONDS = 3600

# In-memory stores for throttling
ip_request_times: dict[str, deque[float]] = defaultdict(deque)
ip_lead_times: dict[str, deque[float]] = defaultdict(deque)

LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'leads.jsonl'


def _prune(window: deque[float], now: float, ttl: int) -> None:
    while window and now - window[0] > ttl:
        window.popleft()


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    req_window = ip_request_times[ip]
    _prune(req_window, now, RATE_WINDOW_SECONDS)
    if len(req_window) >= MAX_REQUESTS_PER_MINUTE_IP:
        return True
    req_window.append(now)
    return False


def _is_ip_throttled_for_leads(ip: str) -> bool:
    now = time.time()
    lead_window = ip_lead_times[ip]
    _prune(lead_window, now, LEAD_WINDOW_SECONDS)
    if len(lead_window) >= MAX_LEADS_PER_HOUR_IP:
        return True
    lead_window.append(now)
    return False


def _verify_recaptcha(token: str, remote_ip: str) -> bool:
    if not RECAPTCHA_SECRET:
        return True
    if not token:
        return False

    body = parse.urlencode({'secret': RECAPTCHA_SECRET, 'response': token, 'remoteip': remote_ip}).encode('utf-8')
    req = urlrequest.Request('https://www.google.com/recaptcha/api/siteverify', data=body, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            return bool(payload.get('success')) and float(payload.get('score', 0)) >= 0.5
    except (error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return False


def _forward_webhook_with_retry(record: dict, retries: int = 3) -> bool:
    if not WEBHOOK_URL:
        return False

    for attempt in range(1, retries + 1):
        try:
            req = urlrequest.Request(
                WEBHOOK_URL,
                data=json.dumps(record).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'X-Lead-ID': record.get('lead_id', ''),
                },
                method='POST',
            )
            with urlrequest.urlopen(req, timeout=8) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(attempt)
    return False


def _notify_telegram(record: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': (
            'Новый лид\n'
            f"Телефон: {record['payload'].get('phone', '-') }\n"
            f"Имя: {record['payload'].get('name', '-') }\n"
            f"UTM source: {record['payload'].get('utm_source', '-') }\n"
            f"UTM medium: {record['payload'].get('utm_medium', '-') }\n"
            f"UTM campaign: {record['payload'].get('utm_campaign', '-') }"
        ),
    }
    req = urlrequest.Request(
        f'{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (error.URLError, TimeoutError):
        return False


def _notify_email_webhook(record: dict) -> bool:
    if not ALERT_EMAIL_WEBHOOK_URL:
        return False
    req = urlrequest.Request(
        ALERT_EMAIL_WEBHOOK_URL,
        data=json.dumps({'subject': 'Новый лид', 'record': record}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (error.URLError, TimeoutError):
        return False


class Handler(SimpleHTTPRequestHandler):
    def _origin_allowed(self) -> bool:
        origin = self.headers.get('Origin')
        if not origin:
            return True
        return origin in ALLOWED_ORIGINS

    def _set_cors_headers(self):
        origin = self.headers.get('Origin')
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        if self.path == '/api/lead':
            if not self._origin_allowed():
                self.send_error(403, 'origin forbidden')
                return
            self.send_response(204)
            self._set_cors_headers()
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'ok')
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != '/api/lead':
            self.send_error(404)
            return

        ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]

        if not self._origin_allowed():
            self._json({'ok': False, 'message': 'origin forbidden'}, 403)
            return

        if _is_rate_limited(ip):
            self._json({'ok': False, 'message': 'rate limit exceeded'}, 429)
            return

        if _is_ip_throttled_for_leads(ip):
            self._json({'ok': False, 'message': 'too many leads from ip'}, 429)
            return

        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length)

        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
        except json.JSONDecodeError:
            self._json({'ok': False, 'message': 'invalid json'}, 400)
            return

        if payload.get('website'):
            self._json({'ok': False, 'message': 'spam detected'}, 400)
            return

        recaptcha_token = str(payload.get('recaptcha_token', '')).strip()
        if not _verify_recaptcha(recaptcha_token, ip):
            self._json({'ok': False, 'message': 'bot verification failed'}, 400)
            return

        phone = str(payload.get('phone', '')).strip()
        if not phone:
            self._json({'ok': False, 'message': 'phone required'}, 400)
            return

        record = {
            'lead_id': str(uuid.uuid4()),
            'ts_server': datetime.now(timezone.utc).isoformat(),
            'ip': ip,
            'user_agent': self.headers.get('User-Agent', ''),
            'payload': payload,
        }

        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

        forwarded = _forward_webhook_with_retry(record, retries=3)
        telegram_notified = _notify_telegram(record)
        email_notified = _notify_email_webhook(record)

        self._json(
            {
                'ok': True,
                'forwarded': forwarded,
                'telegram_notified': telegram_notified,
                'email_notified': email_notified,
            },
            200,
        )

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self._set_cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Server started at http://{HOST}:{PORT}')
    server.serve_forever()
