import sqlite3
from pathlib import Path
from core.waf_simulator import get_all_waf_results, WAF_PROFILES

DB = Path('.cyberia/payload_lab.db')

CVSS_MAP = {
    'xss': {'base': 6.1, 'description': 'Cross-Site Scripting reflechi'},
    'sqli': {'base': 8.8, 'description': 'SQL Injection'},
    'lfi': {'base': 7.5, 'description': 'Local File Inclusion'},
    'ssti': {'base': 9.8, 'description': 'Server-Side Template Injection'},
    'rce': {'base': 10.0, 'description': 'Remote Code Execution'},
    'xxe': {'base': 8.2, 'description': 'XML External Entity'},
    'ssrf': {'base': 8.6, 'description': 'Server-Side Request Forgery'},
}


def score_payload(payload, ptype):
    waf_results, passed_wafs = get_all_waf_results(payload)
    waf_score = len(passed_wafs) / len(WAF_PROFILES) * 100
    cvss_base = CVSS_MAP.get(ptype, {}).get('base', 5.0)
    final_score = round((waf_score * 0.6) + (cvss_base * 4), 1)
    return {
        'payload': payload,
        'type': ptype,
        'waf_score': round(waf_score, 1),
        'cvss_base': cvss_base,
        'final_score': min(final_score, 100),
        'passed_wafs': passed_wafs,
        'blocked_by': {w: r['blocked_by'] for w, r in waf_results.items() if not r['passed']},
        'cvss_description': CVSS_MAP.get(ptype, {}).get('description', 'Unknown'),
    }


def get_top_payloads(limit=50):
    conn = sqlite3.connect(DB)
    payloads = conn.execute(
        'SELECT DISTINCT payload, payload_type FROM imported_payloads ORDER BY ROWID DESC LIMIT 500'
    ).fetchall()
    conn.close()
    scored = []
    for payload, ptype in payloads:
        if not payload or len(payload) < 2:
            continue
        try:
            result = score_payload(payload, ptype)
            if result['waf_score'] > 0:
                scored.append(result)
        except Exception:
            pass
    scored.sort(key=lambda x: -x['final_score'])
    return scored[:limit]


def get_evolution_stats():
    conn = sqlite3.connect(DB)
    try:
        by_gen = conn.execute(
            'SELECT source, COUNT(*) FROM imported_payloads WHERE source LIKE "evolution%" GROUP BY source ORDER BY source'
        ).fetchall()
        total = conn.execute('SELECT COUNT(*) FROM imported_payloads').fetchone()[0]
        bypasses = conn.execute('SELECT COUNT(*) FROM results WHERE bypass_confirmed=1').fetchone()[0]
    except Exception:
        by_gen, total, bypasses = [], 0, 0
    conn.close()
    return {'by_generation': dict(by_gen), 'total_payloads': total, 'total_bypasses': bypasses}
