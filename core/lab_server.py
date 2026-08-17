from __future__ import annotations
import re, threading, time, urllib.parse
from pathlib import Path

XSS_BEACONS = []
_server_thread = None
_server_running = False

# ---------------------------------------------------------------------------
# WAF simulation — ModSecurity-style naive rule set (case-sensitive, no
# normalization). Intentionally misses: case mixing, double URL encoding,
# unicode escapes, SQL comments, null bytes.
# ---------------------------------------------------------------------------

_WAF_XSS_RULES = [
    (re.compile(r'<script[\s>/]'),          'direct <script tag'),
    (re.compile(r'<script>'),               'direct <script> tag'),
    (re.compile(r'alert\('),                'alert() call'),
    (re.compile(r'javascript:'),            'javascript: protocol'),
    (re.compile(r'<iframe[\s>]'),           'iframe injection'),
    (re.compile(r'<img\s[^>]*onerror\s*='), 'img onerror handler'),
]

_WAF_SQLI_RULES = [
    (re.compile(r'union select'),           'UNION SELECT (basic)'),
    (re.compile(r"'\s*or\s*'1'\s*=\s*'1"), "classic ' or '1'='1"),
    (re.compile(r'\bor\s+1\s*=\s*1\b'),    'OR 1=1'),
    (re.compile(r"'--"),                    'comment injection'),
    (re.compile(r';\s*drop\s+table'),       'DROP TABLE'),
    (re.compile(r"'\s*;\s*select"),         'stacked query SELECT'),
]

# ---------------------------------------------------------------------------
# WAF Paranoia Level rule sets (P1 → P2 → P3, each cumulative)
# ---------------------------------------------------------------------------

# P1 — obvious, case-sensitive, no decoding
_WAF_P1_XSS = [
    (re.compile(r'<script>alert'),                         'P1: <script>alert (direct)'),
]

_WAF_P1_SQLI = [
    (re.compile(r'UNION SELECT'),                          'P1: UNION SELECT (uppercase)'),
    (re.compile(r"'\s*OR\s+1\s*=\s*1"),                   "P1: ' OR 1=1 (basic)"),
]

# P2 — P1 + event handlers, URL-encoding, case variants, SQL comments
_WAF_P2_XSS = _WAF_P1_XSS + [
    (re.compile(r'on(?:error|load|click|mouseover|focus|blur)\s*=', re.I),
                                                           'P2: event handler attr (onerror/onload)'),
    (re.compile(r'%3[cC]|%3[eE]'),                        'P2: URL-encoded < or > (%3C/%3E)'),
    (re.compile(r'<script', re.I),                         'P2: <script case-insensitive (ScRiPt)'),
]

_WAF_P2_SQLI = _WAF_P1_SQLI + [
    (re.compile(r'union\s+select', re.I),                 'P2: UNION SELECT case-insensitive'),
    (re.compile(r"'\s*or\s+1\s*=\s*1", re.I),            "P2: OR 1=1 case-insensitive"),
    (re.compile(r'--'),                                    'P2: SQL inline comment (--)'),
]

# P3 — P2 + double-encoding, unicode, null bytes, advanced comments, base64, any tag
_WAF_P3_XSS = _WAF_P2_XSS + [
    (re.compile(r'%25[0-9a-fA-F]{2}'),                    'P3: double URL encoding (%253C)'),
    (re.compile(r'\\u00[0-9a-fA-F]{2}', re.I),            r'P3: unicode escape (<)'),
    (re.compile(r'%00'),                                   'P3: null byte (%00)'),
    (re.compile(r'PHNjcmlwd|amF2YXNjcmlwd|YWxlcnQ'),     'P3: base64 dangerous content'),
    (re.compile(r'<[a-zA-Z]'),                            'P3: any HTML tag'),
]

_WAF_P3_SQLI = _WAF_P2_SQLI + [
    (re.compile(r'%25[0-9a-fA-F]{2}'),                    'P3: double URL encoding'),
    (re.compile(r'\\u002[27]', re.I),                     "P3: unicode quote (\\u0027)"),
    (re.compile(r'%00|\x00'),                              'P3: null byte'),
    (re.compile(r'/\*!.*?\*/'),                            'P3: MySQL conditional comment (/*!*/)'),
    (re.compile(r'/\*.*?\*/'),                             'P3: SQL block comment (/***/)'),
    (re.compile(r"'"),                                    'P3: any single quote'),
]

# ---------------------------------------------------------------------------
# WAF complete — 10 attack categories (regex strings, compiled at check time)
# ---------------------------------------------------------------------------

REGLES_WAF_COMPLET = {
    'ssti': [
        r'\{\{.*\}\}',
        r'\#\{.*\}',
        r'\$\{.*\}',
        r'<%.*%>',
        r'\{\%.*\%\}',
    ],
    'lfi': [
        r'\.\./\.\.',
        r'\.\.\\',
        r'%2e%2e%2f',
        r'%252e%252e',
        r'/etc/passwd',
        r'/etc/shadow',
        r'php://input',
        r'php://filter',
        r'file://',
        r'data://text',
    ],
    'rce': [
        r';\s*(ls|cat|whoami|id|pwd|echo|wget|curl)',
        r'\|\s*(ls|cat|whoami|id)',
        r'`.*`',
        r'\$\(.*\)',
        r'system\(',
        r'exec\(',
        r'passthru\(',
        r'shell_exec\(',
        r'popen\(',
        r'proc_open\(',
    ],
    'xxe': [
        r'<!ENTITY',
        r'SYSTEM\s+"file',
        r'<!DOCTYPE.*\[',
        r'SYSTEM\s+http',
    ],
    'ssrf': [
        r'http://169\.254\.169\.254',
        r'http://localhost',
        r'http://127\.0\.0\.1',
        r'http://0\.0\.0\.0',
        r'file:///etc',
        r'gopher://',
        r'dict://',
        r'ftp://internal',
    ],
    'log4shell': [
        r'\$\{jndi:',
        r'\$\{lower:',
        r'\$\{upper:',
        r'\$\{\$\{',
    ],
    'csrf': [
        r'<form.*action.*http',
        r'<img.*src.*http.*hidden',
        r'XMLHttpRequest.*cross',
    ],
    'auth_bypass': [
        r'admin.*=.*true',
        r'role.*=.*(admin|root|superuser)',
        r'is_admin.*=.*1',
        r"' OR '1'='1",
        r'bypass.*auth',
    ],
    'path_traversal': [
        r'%2f\.\.',
        r'%5c\.\.',
        r'\.\./\.\./\.\.',
        r'%c0%ae',
        r'%ef%bc%8f',
    ],
    'header_injection': [
        r'%0d%0a',
        r'\r\n',
        r'Content-Type:.*\r',
        r'Set-Cookie:.*injected',
    ],
}


def _waf_check(payload: str, rules: list) -> tuple[bool, str]:
    """Return (blocked, matched_rule_label). Case-sensitive, no decode."""
    for pattern, label in rules:
        if pattern.search(payload):
            return True, label
    return False, ''


def _waf_bypass_hints(payload: str) -> list[str]:
    """Detect which bypass technique was used (for educational response headers)."""
    hints = []
    lower = payload.lower()
    if re.search(r'%[0-9a-f]{2}', lower):
        hints.append('double-url-encoding')
    if re.search(r'\\u[0-9a-f]{4}', lower):
        hints.append('unicode-escape')
    if '/**/' in payload or re.search(r'/\*.*?\*/', payload):
        hints.append('sql-comment')
    if '\x00' in payload or '%00' in payload:
        hints.append('null-byte')
    # case mixing: letters appear in mixed case
    alpha = re.sub(r'[^a-zA-Z]', '', payload)
    if alpha and alpha != alpha.lower() and alpha != alpha.upper():
        hints.append('case-mixing')
    return hints


def _waf_403(rule_label: str):
    try:
        from flask import make_response, jsonify
        body = {
            'status': 'BLOCKED',
            'waf': 'CYBERIA-WAF/ModSecurity-sim',
            'rule': rule_label,
            'message': 'Request blocked by WAF policy',
        }
        resp = make_response(jsonify(body), 403)
        resp.headers['X-WAF'] = 'BLOCKED'
        resp.headers['X-WAF-Rule'] = rule_label
        return resp
    except Exception:
        return ('WAF BLOCKED', 403)


def create_app():
    try:
        from flask import Flask, request, make_response, jsonify
    except ImportError:
        return None
    app = Flask(__name__)
    app.logger.disabled = True
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    @app.route('/')
    def index():
        return (
            '<h1>CYBERIA Payload Lab</h1>'
            '<p>Endpoints: /xss /sqli /rce /xss_beacon /stats</p>'
            '<p>WAF endpoints: /waf/xss /waf/sqli</p>'
            '<p>WAF blocks: &lt;script&gt; direct, alert(, union select basic</p>'
            '<p>WAF misses: case mixing, double URL encoding, unicode escapes, SQL comments, null bytes</p>'
        )

    @app.route('/xss')
    def xss_endpoint():
        q = request.args.get('q', '')
        html = f'''<html><head><title>Lab XSS</title></head>
<body><h2>Search results</h2><div id="result">{q}</div>
<p>Input was: {q}</p></body></html>'''
        resp = make_response(html, 200)
        resp.headers['X-Lab'] = 'CYBERIA-PayloadLab'
        return resp

    @app.route('/sqli')
    def sqli_endpoint():
        user = request.args.get('user', '')
        u = user.lower()
        if any(x in u for x in ["'", "union", "select", "or 1=1", "--", "drop"]):
            return f'USER: admin | PASSWORD: supersecret | ROLE: root | QUERY: SELECT * FROM users WHERE name="{user}"'
        if user:
            return f'USER NOT FOUND: {user}'
        return 'Usage: ?user=nom'

    @app.route('/rce')
    def rce_endpoint():
        cmd = request.args.get('cmd', '')
        dangerous = ['ls', 'cat', 'whoami', 'id', 'pwd', 'echo', 'dir', 'type']
        if any(d in cmd.lower() for d in dangerous):
            return f'SIMULATED OUTPUT: cyberia-lab$ {cmd}\ncyberia user\n/app/lab\ntotal 0'
        return f'CMD: {cmd} (no output)'

    @app.route('/xss_beacon')
    def xss_beacon():
        token = request.args.get('token', '')
        if token:
            XSS_BEACONS.append({'token': token, 'ts': time.time(), 'ip': request.remote_addr})
        return 'OK'

    @app.route('/stats')
    def stats():
        return jsonify({'beacons': len(XSS_BEACONS), 'beacons_list': XSS_BEACONS[-10:]})

    # -----------------------------------------------------------------------
    # WAF endpoints
    # -----------------------------------------------------------------------

    @app.route('/waf/xss')
    def waf_xss():
        q = request.args.get('q', '')
        blocked, rule = _waf_check(q, _WAF_XSS_RULES)
        if blocked:
            return _waf_403(rule)
        hints = _waf_bypass_hints(q)
        html = f'''<html><head><title>WAF Lab XSS</title></head>
<body>
<h2>WAF Protected Search</h2>
<p>WAF status: <b>PASSED</b></p>
<div id="result">{q}</div>
<p>Input was: {q}</p>
</body></html>'''
        resp = make_response(html, 200)
        resp.headers['X-WAF'] = 'PASSED'
        resp.headers['X-Lab'] = 'CYBERIA-WAF-XSS'
        if hints:
            resp.headers['X-WAF-Bypass-Technique'] = ','.join(hints)
        return resp

    @app.route('/waf/sqli')
    def waf_sqli():
        user = request.args.get('user', '')
        blocked, rule = _waf_check(user, _WAF_SQLI_RULES)
        if blocked:
            return _waf_403(rule)
        hints = _waf_bypass_hints(user)
        # Backend query simulation — vulnerable to SQLi even after WAF pass
        u = user.lower().replace('\x00', '').replace('/**/', ' ').replace('/*', ' ').replace('*/', ' ')
        if any(x in u for x in ["'", "union", "select", "or 1=1", "or 1 =1", "--", "drop", "1=1"]):
            body = (
                f'USER: admin | PASSWORD: supersecret | ROLE: root\n'
                f'QUERY: SELECT * FROM users WHERE name="{user}"\n'
                f'WAF: PASSED — backend vulnerable'
            )
        elif user:
            body = f'USER NOT FOUND: {user}\nWAF: PASSED'
        else:
            body = 'Usage: ?user=nom  (WAF protected endpoint)'
        resp = make_response(body, 200)
        resp.headers['X-WAF'] = 'PASSED'
        resp.headers['X-Lab'] = 'CYBERIA-WAF-SQLi'
        if hints:
            resp.headers['X-WAF-Bypass-Technique'] = ','.join(hints)
        return resp

    # -----------------------------------------------------------------------
    # WAF Paranoia Level endpoints (P1 / P2 / P3)
    # -----------------------------------------------------------------------

    def _waf_pass_xss(q):
        html = (
            '<html><body>'
            f'<h2>WAF PASSED</h2><div id="result">{q}</div>'
            '</body></html>'
        )
        return make_response(html, 200)

    def _waf_pass_sqli(user):
        u = user.lower().replace('\x00', '').replace('/**/', ' ').replace('/*', ' ').replace('*/', ' ')
        if any(x in u for x in ["union", "select", "or 1=1", "--", "drop", "1=1", "'"]):
            body = (
                f'USER: admin | PASSWORD: supersecret | ROLE: root\n'
                f'QUERY: SELECT * FROM users WHERE name="{user}"'
            )
        elif user:
            body = f'USER NOT FOUND: {user}'
        else:
            body = 'Usage: ?user=nom'
        return make_response(body, 200)

    @app.route('/waf/p1/xss')
    def waf_p1_xss():
        q = request.args.get('q', '')
        blocked, rule = _waf_check(q, _WAF_P1_XSS)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_xss(q)

    @app.route('/waf/p1/sqli')
    def waf_p1_sqli():
        user = request.args.get('user', '')
        blocked, rule = _waf_check(user, _WAF_P1_SQLI)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_sqli(user)

    @app.route('/waf/p2/xss')
    def waf_p2_xss():
        q = request.args.get('q', '')
        blocked, rule = _waf_check(q, _WAF_P2_XSS)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_xss(q)

    @app.route('/waf/p2/sqli')
    def waf_p2_sqli():
        user = request.args.get('user', '')
        blocked, rule = _waf_check(user, _WAF_P2_SQLI)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_sqli(user)

    @app.route('/waf/p3/xss')
    def waf_p3_xss():
        q = request.args.get('q', '')
        blocked, rule = _waf_check(q, _WAF_P3_XSS)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_xss(q)

    @app.route('/waf/p3/sqli')
    def waf_p3_sqli():
        user = request.args.get('user', '')
        blocked, rule = _waf_check(user, _WAF_P3_SQLI)
        if blocked:
            return jsonify({'blocked': True, 'rule': rule}), 403
        return _waf_pass_sqli(user)

    @app.route('/waf/full/<category>')
    def waf_full_category(category):
        import re as _re
        q = request.args.get('q', request.args.get('user', request.args.get('input', '')))
        rules = REGLES_WAF_COMPLET.get(category, [])
        for pattern in rules:
            try:
                if _re.search(pattern, q, _re.IGNORECASE | _re.DOTALL):
                    return jsonify({'blocked': True, 'rule': f'{category}: {pattern}', 'payload': q[:100]}), 403
            except Exception:
                pass
        resp_text = f'<html><body>Input: {q}<br>Category: {category}</body></html>'
        if category == 'sqli' and any(x in q.lower() for x in ['union', 'select', 'or 1']):
            resp_text = f'DATA: admin|supersecret|root - Query: {q}'
        return make_response(resp_text, 200)

    @app.route('/waf/stats')
    def waf_stats():
        return jsonify({
            'endpoints': list(REGLES_WAF_COMPLET.keys()) + ['p1', 'p2', 'p3'],
            'total_rules': sum(len(v) for v in REGLES_WAF_COMPLET.values()),
        })

    return app


def start_lab_server(port=5005):
    global _server_thread, _server_running
    if _server_running:
        return f'http://127.0.0.1:{port}'
    app = create_app()
    if not app:
        return None

    def run():
        global _server_running
        _server_running = True
        try:
            app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
        except Exception:
            _server_running = False

    _server_thread = threading.Thread(target=run, daemon=True)
    _server_thread.start()
    time.sleep(1.5)
    return f'http://127.0.0.1:{port}'


def is_running():
    return _server_running


def check_xss_beacon(token):
    return any(b['token'] == token for b in XSS_BEACONS)
