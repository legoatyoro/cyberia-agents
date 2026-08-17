from __future__ import annotations
import csv, json, sqlite3, time, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

try:
    from tools.memory_hub_v3 import add_pattern
    HAS_MEMORY = True
except Exception:
    HAS_MEMORY = False

LAB_DB = Path('.cyberia/payload_lab.db')


def init_lab_db():
    LAB_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(LAB_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY, payload TEXT, payload_type TEXT,
        target TEXT, http_code INTEGER, status TEXT, score INTEGER,
        reflected INTEGER, body_snippet TEXT, source TEXT,
        tested_at TEXT, bypass_confirmed INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()


@dataclass
class PayloadItem:
    payload: str
    ptype: str
    source: str
    meta: Dict[str, Any] = field(default_factory=dict)


def load_payloads_from_sqlite(db_path=None):
    items = []
    paths = [db_path] if db_path else [
        Path('.cyberia/cyber_research.db'),
        Path('.cyberia/memory_hub_v3.db'),
    ]
    for p in paths:
        if not p or not Path(p).exists():
            continue
        try:
            conn = sqlite3.connect(str(p))
            for table in ['payload_patterns', 'payloads', 'patterns']:
                try:
                    rows = conn.execute(
                        f'SELECT payload, attack_type, source FROM {table} WHERE payload IS NOT NULL LIMIT 500'
                    ).fetchall()
                    for row in rows:
                        if row[0] and len(row[0]) > 3:
                            items.append(PayloadItem(row[0], row[1] or 'unknown', f'sqlite:{p}:{table}'))
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass
    return items


def load_payloads_from_json(path):
    items = []
    p = Path(path)
    if not p.exists():
        return items
    try:
        data = json.loads(p.read_text(encoding='utf-8', errors='ignore'))
        if isinstance(data, list):
            for x in data:
                if isinstance(x, str) and len(x) > 3:
                    items.append(PayloadItem(x, 'unknown', f'json:{p}'))
                elif isinstance(x, dict) and x.get('payload'):
                    items.append(PayloadItem(x['payload'], x.get('type', 'unknown'), f'json:{p}'))
        elif isinstance(data, dict):
            for key in ['payloads', 'xss', 'sqli', 'payloads_xss', 'payloads_sqli']:
                for x in data.get(key, []):
                    if isinstance(x, str):
                        items.append(PayloadItem(x, key, f'json:{p}'))
                    elif isinstance(x, dict) and x.get('payload'):
                        items.append(PayloadItem(x['payload'], x.get('type', key), f'json:{p}'))
    except Exception:
        pass
    return items


def load_payloads_from_csv(path):
    items = []
    p = Path(path)
    if not p.exists():
        return items
    try:
        with p.open('r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                payload = row.get('payload') or row.get('Payload') or ''
                if payload and len(payload) > 3:
                    items.append(PayloadItem(payload, row.get('type', 'unknown'), f'csv:{p}'))
    except Exception:
        pass
    return items


def load_payloads_from_generated():
    items = []
    gen = Path('generated')
    if not gen.exists():
        return items
    for jf in gen.rglob('*.json'):
        items.extend(load_payloads_from_json(str(jf)))
    return items


def load_payloads_from_imported():
    items = []
    if not LAB_DB.exists():
        return items
    try:
        conn = sqlite3.connect(str(LAB_DB))
        rows = conn.execute(
            'SELECT payload, attack_type, source FROM imported_payloads WHERE payload IS NOT NULL'
        ).fetchall()
        conn.close()
        for row in rows:
            if row[0] and len(row[0]) > 1:
                items.append(PayloadItem(row[0], row[1] or 'unknown', row[2] or 'imported'))
    except Exception:
        pass
    return items


def evaluate_xss(body, payload):
    score = 0
    b = body.lower()
    p = payload.lower()
    if p in b:
        score += 30
    if '<script' in b and 'script>' in b:
        score += 25
    if any(x in b for x in ['alert(', 'prompt(', 'confirm(', 'onerror=', 'onload=']):
        score += 30
    if 'xss' in b and 'blocked' not in b:
        score += 15
    return min(score, 100)


def evaluate_sqli(body, payload):
    score = 0
    b = body.lower()
    if any(x in b for x in ['admin', 'password', 'secret', 'root', 'user:']):
        score += 50
    if any(x in b for x in ['sql', 'syntax error', 'mysql', 'postgres', 'sqlite']):
        score += 30
    if any(x in b for x in ['id=', 'select', 'union', 'from ']):
        score += 20
    return min(score, 100)


def evaluate_generic(body, payload):
    if payload.lower() in body.lower():
        return 30
    return 0


def evaluate_xss_real(body, payload, http_code):
    if http_code == 403:
        return 0
    score = 0
    b = body.lower()
    p = payload.lower()
    if payload in body:
        score += 35
    if '<script' in b and any(x in b for x in ['alert', 'fetch(', 'document.cookie']):
        score += 30
    if any(x in b for x in ['onerror=', 'onload=', 'onmouseover=', 'onfocus=']):
        score += 25
    if any(x in b for x in ['javascript:', 'data:text/html', 'vbscript:']):
        score += 20
    if any(x in b for x in ['document.cookie', 'localstorage', 'sessionstorage']):
        score += 15
    if any(x in p for x in ['\\u00', '%2', '&#', 'base64', 'fromcharcode']):
        score += 10
    return min(score, 100)


def evaluate_sqli_real(body, payload, http_code):
    if http_code == 403:
        return 0
    score = 0
    b = body.lower()
    if any(x in b for x in ['admin', 'password', 'secret', 'root', 'hash']):
        score += 50
    if any(x in b for x in ['mysql_fetch', 'ora-', 'pg_', 'sqlite', 'syntax error',
                              'you have an error in your sql']):
        score += 40
    if 'true' in b and 'false' not in b:
        score += 20
    if '1=1' in payload.lower() and http_code == 200:
        score += 15
    if any(x in payload.lower() for x in ['sleep(', 'benchmark(', 'waitfor delay', 'pg_sleep']):
        score += 25
    return min(score, 100)


def evaluate_ssti_real(body, payload, http_code):
    if http_code == 403:
        return 0
    score = 0
    b = body
    if '49' in b and '{{7*7}}' in payload:
        return 100
    if '7777777' in b and "{{7*'7'}}" in payload:
        return 100
    if any(x in b for x in ['root:x:0:0', 'etc/passwd', 'uid=0']):
        return 100
    if http_code != 403 and len(b) > 50:
        score = max(score, 30)
    return score


def evaluate_lfi_real(body, payload, http_code):
    if http_code == 403:
        return 0
    score = 0
    b = body
    if any(x in b for x in ['root:x:0:0', 'daemon:x', 'bin/bash', 'sbin/nologin']):
        return 100
    if any(x in b for x in ['<?php', '<html>']) and '../' in payload:
        score = 60
    elif http_code == 200 and len(b) > 100:
        score = 20
    return score


def test_one(payload, ptype, target_url, param='q', timeout=5.0):
    result = {
        'payload': payload, 'type': ptype, 'target': target_url,
        'http_code': None, 'status': 'ERROR', 'score': 0,
        'reflected': False, 'body_snippet': '', 'bypass_confirmed': False
    }
    if not HAS_REQUESTS:
        result['status'] = 'NO_REQUESTS'
        return result
    try:
        params = {param: payload}
        headers = {'User-Agent': 'CYBERIA-PayloadLab/1.0'}
        r = requests.get(target_url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
        result['http_code'] = r.status_code
        body = r.text
        result['body_snippet'] = body[:800]
        result['reflected'] = payload[:20].lower() in body.lower()
        t = ptype.lower()
        if 'xss' in t:
            score = evaluate_xss_real(body, payload, r.status_code)
        elif 'sqli' in t or 'sql' in t:
            score = evaluate_sqli_real(body, payload, r.status_code)
        elif 'ssti' in t:
            score = evaluate_ssti_real(body, payload, r.status_code)
        elif 'lfi' in t:
            score = evaluate_lfi_real(body, payload, r.status_code)
        else:
            score = evaluate_generic(body, payload)
            if r.status_code == 403:
                score = max(0, score - 20)
        result['score'] = score
        result['bypass_confirmed'] = score >= 50
        result['status'] = 'BYPASS' if score >= 50 else ('PARTIAL' if score >= 20 else 'BLOCKED')
    except requests.exceptions.ConnectionError:
        result['status'] = 'CONNECTION_ERROR'
    except requests.exceptions.Timeout:
        result['status'] = 'TIMEOUT'
    except Exception as e:
        result['status'] = f'ERROR: {str(e)[:50]}'
    return result


def run_lab(payloads, target_url, param='q', limit=None, on_result=None):
    init_lab_db()
    results = []
    items = payloads[:limit] if limit else payloads
    for i, p in enumerate(items):
        if not p.payload or len(p.payload) < 2:
            continue
        res = test_one(p.payload, p.ptype, target_url, param)
        res['source'] = p.source
        res['tested_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        results.append(res)
        save_result(res)
        if on_result:
            on_result(i + 1, len(items), res)
    return results


def save_result(res):
    try:
        conn = sqlite3.connect(LAB_DB)
        conn.execute(
            'INSERT INTO results (payload,payload_type,target,http_code,status,score,reflected,body_snippet,source,tested_at,bypass_confirmed) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (res['payload'], res.get('type', ''), res.get('target', ''),
             res.get('http_code'), res.get('status', ''),
             res.get('score', 0), int(res.get('reflected', False)),
             res.get('body_snippet', '')[:500], res.get('source', ''),
             res.get('tested_at', ''), int(res.get('bypass_confirmed', False)))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_best_payloads(min_score=50, limit=50):
    init_lab_db()
    conn = sqlite3.connect(LAB_DB)
    rows = conn.execute(
        'SELECT payload, payload_type, score, target, status FROM results WHERE score >= ? ORDER BY score DESC LIMIT ?',
        (min_score, limit)
    ).fetchall()
    conn.close()
    return [{'payload': r[0], 'type': r[1], 'score': r[2], 'target': r[3], 'status': r[4]} for r in rows]


def get_lab_stats():
    init_lab_db()
    conn = sqlite3.connect(LAB_DB)
    total = conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    bypass = conn.execute('SELECT COUNT(*) FROM results WHERE bypass_confirmed=1').fetchone()[0]
    blocked = conn.execute('SELECT COUNT(*) FROM results WHERE status="BLOCKED"').fetchone()[0]
    by_type = dict(conn.execute(
        'SELECT payload_type, COUNT(*) FROM results GROUP BY payload_type ORDER BY COUNT(*) DESC LIMIT 5'
    ).fetchall())
    conn.close()
    rate = round(bypass / total * 100, 1) if total > 0 else 0
    return {'total': total, 'bypass': bypass, 'blocked': blocked, 'rate': rate, 'by_type': by_type}


def export_csv(results, path='.cyberia/lab_results.csv'):
    p = Path(path)
    p.parent.mkdir(exist_ok=True)
    if not results:
        return str(p)
    keys = ['payload', 'type', 'target', 'http_code', 'status', 'score', 'reflected', 'bypass_confirmed', 'source']
    with p.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)
    return str(p)


def inject_best_into_memory(results, min_score=50):
    if not HAS_MEMORY:
        return 0
    count = 0
    for r in results:
        if r.get('score', 0) >= min_score:
            try:
                add_pattern({
                    'type': 'vuln_pattern', 'payload': r['payload'],
                    'payload_type': r.get('type', ''), 'target': r.get('target', ''),
                    'score': r.get('score', 0), 'source': 'PayloadLab',
                    'status': r.get('status', '')
                })
                count += 1
            except Exception:
                pass
    return count
