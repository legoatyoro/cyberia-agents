# -*- coding: utf-8 -*-
"""
AgentSuperviseur - Boucle 1 : DiagnosticEngine
Scan CYBERIA databases, compute coverage scores per category,
detect knowledge gaps, and produce a markdown report.

Standalone: stdlib only, no CYBERIA imports.
Usage: python core/agent_superviseur.py --diagnostic
"""
import sqlite3
import json
import os
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=str(Path(__file__).parent.parent / '.env'), override=True)

# -- Chemins DB --

ROOT = Path(__file__).parent.parent.resolve()
PAYLOAD_DB = ROOT / '.cyberia' / 'payload_lab.db'
MEMORY_DB  = ROOT / '.cyberia' / 'memory_core.db'
WAF_DB     = ROOT / '.cyberia' / 'waf_rules.db'
REPORT_PATH = ROOT / '.cyberia' / 'supervisor_report.md'

CATEGORIES = ['xss', 'sqli', 'lfi', 'ssti', 'rce', 'xxe', 'ssrf']

SEUIL_CRITIQUE = 0.05
SEUIL_FAIBLE   = 0.15
SEUIL_BON      = 0.30


def safe_json_parse(content):
    import re
    if not content:
        return {}
    try:
        return json.loads(content)
    except Exception:
        pass
    cleaned = re.sub(r'```(?:json)?', '', content).strip('`').strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    brace = cleaned.find('{')
    if brace > 0:
        try:
            return json.loads(cleaned[brace:])
        except Exception:
            pass
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {'summary': content[:300], 'raw': True}


# -- Connexions DB --

def connect(db_path):
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


# -- Collecteurs de metriques --

def scan_payloads():
    conn = connect(PAYLOAD_DB)
    if not conn:
        return {'error': 'payload_lab.db introuvable'}

    data = {}

    row = conn.execute('SELECT COUNT(*) as n FROM imported_payloads').fetchone()
    data['total_imported'] = row['n'] if row else 0

    row = conn.execute('SELECT COUNT(*) as n FROM results').fetchone()
    data['total_results'] = row['n'] if row else 0

    rows = conn.execute(
        "SELECT payload_type, COUNT(*) as n FROM results WHERE bypass_confirmed=1 "
        "GROUP BY payload_type ORDER BY n DESC"
    ).fetchall()
    bypasses = {}
    total_bypasses = 0
    for r in rows:
        pt = r['payload_type'] or 'unknown'
        bypasses[pt] = r['n']
        total_bypasses += r['n']
    data['bypasses_by_type'] = bypasses
    data['total_bypasses'] = total_bypasses

    rows = conn.execute(
        "SELECT rank, COUNT(*) as n FROM imported_payloads GROUP BY rank ORDER BY n DESC"
    ).fetchall()
    data['ranks'] = {r['rank']: r['n'] for r in rows}

    rows = conn.execute(
        "SELECT payload_type, AVG(score) as avg_score, MAX(score) as max_score "
        "FROM results WHERE bypass_confirmed=1 GROUP BY payload_type"
    ).fetchall()
    data['avg_score_by_type'] = {
        r['payload_type']: {'avg': round(r['avg_score'] or 0, 1), 'max': r['max_score'] or 0}
        for r in rows
    }

    row = conn.execute(
        "SELECT COUNT(*) as n FROM results WHERE bypass_confirmed=1 "
        "AND tested_at >= datetime('now', '-1 day')"
    ).fetchone()
    data['bypasses_24h'] = row['n'] if row else 0

    conn.close()
    return data


def scan_memory():
    conn = connect(MEMORY_DB)
    if not conn:
        return {'error': 'memory_core.db introuvable'}

    data = {}

    row = conn.execute('SELECT COUNT(*) as n FROM memory_items').fetchone()
    data['total_items'] = row['n'] if row else 0

    rows = conn.execute(
        "SELECT source, COUNT(*) as n FROM memory_items "
        "GROUP BY source ORDER BY n DESC LIMIT 15"
    ).fetchall()
    data['by_source'] = [(r['source'], r['n']) for r in rows]

    row = conn.execute("SELECT COUNT(*) as n FROM memory_items WHERE use_count > 0").fetchone()
    data['used_items'] = row['n'] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) as n FROM memory_items "
        "WHERE embedding IS NOT NULL AND embedding != '[]' AND embedding != ''"
    ).fetchone()
    data['with_embeddings'] = row['n'] if row else 0

    rows = conn.execute(
        "SELECT tags, COUNT(*) as n FROM memory_items "
        "GROUP BY tags ORDER BY n DESC LIMIT 10"
    ).fetchall()
    data['top_tags'] = [(r['tags'][:60], r['n']) for r in rows]

    row = conn.execute(
        "SELECT created_at FROM memory_items ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    data['last_added'] = row['created_at'] if row else 'jamais'

    conn.close()
    return data


def scan_waf():
    conn = connect(WAF_DB)
    if not conn:
        return {'error': 'waf_rules.db introuvable'}

    data = {}

    row = conn.execute("SELECT COUNT(*) as n FROM waf_rules WHERE enabled=1").fetchone()
    data['total_rules'] = row['n'] if row else 0

    rows = conn.execute(
        "SELECT category, COUNT(*) as n FROM waf_rules "
        "WHERE enabled=1 GROUP BY category ORDER BY n DESC"
    ).fetchall()
    data['rules_by_category'] = {r['category']: r['n'] for r in rows}

    rows = conn.execute(
        "SELECT source, COUNT(*) as n FROM waf_rules "
        "WHERE enabled=1 GROUP BY source ORDER BY n DESC"
    ).fetchall()
    data['rules_by_source'] = {r['source']: r['n'] for r in rows}

    rows = conn.execute(
        "SELECT cycle, bypasses_loaded, rules_injected, "
        "blocked_before, blocked_after, rate_before, rate_after "
        "FROM arena_cycles ORDER BY cycle"
    ).fetchall()
    data['arena_cycles'] = [dict(r) for r in rows]

    row = conn.execute("SELECT COUNT(*) as n FROM arena_processed").fetchone()
    data['arena_processed'] = row['n'] if row else 0

    conn.close()
    return data


# -- Analyse de couverture --

def compute_coverage(payload_data, waf_data):
    bypasses = payload_data.get('bypasses_by_type', {})
    waf_rules = waf_data.get('rules_by_category', {})
    total = payload_data.get('total_bypasses', 0)

    coverage = {}
    for cat in CATEGORIES:
        nb_bypasses = bypasses.get(cat, 0)
        nb_rules = waf_rules.get(cat, 0)
        pct = (nb_bypasses / total * 100) if total > 0 else 0

        if pct < SEUIL_CRITIQUE * 100:
            status = 'CRITIQUE'
        elif pct < SEUIL_FAIBLE * 100:
            status = 'FAIBLE'
        elif pct >= SEUIL_BON * 100:
            status = 'FORTE'
        else:
            status = 'OK'

        rule_ratio = (nb_rules / nb_bypasses * 100) if nb_bypasses > 0 else 0

        coverage[cat] = {
            'bypasses': nb_bypasses,
            'waf_rules': nb_rules,
            'pct_total': round(pct, 1),
            'rule_ratio': round(rule_ratio, 1),
            'status': status,
        }

    return coverage


def detect_gaps(coverage, payload_data):
    gaps = []

    for cat, info in coverage.items():
        if info['status'] in ('CRITIQUE', 'FAIBLE'):
            gap = {
                'categorie': cat,
                'status': info['status'],
                'bypasses': info['bypasses'],
                'waf_rules': info['waf_rules'],
                'pct': info['pct_total'],
                'action': '',
            }

            if info['bypasses'] == 0:
                gap['action'] = (
                    'Aucun bypass {}. Recherche ciblee + generation de payloads necessaire.'.format(cat)
                )
            elif info['bypasses'] < 50:
                gap['action'] = (
                    'Seulement {} bypasses {}. Augmenter la diversite des techniques.'.format(
                        info['bypasses'], cat
                    )
                )
            elif info['waf_rules'] < 5:
                gap['action'] = (
                    '{} regles WAF pour {} bypasses. Arena insuffisante.'.format(
                        info['waf_rules'], info['bypasses']
                    )
                )
            else:
                gap['action'] = (
                    'Couverture {} a {}%. Prioriser dans les prochains cycles.'.format(
                        cat, info['pct_total']
                    )
                )

            gaps.append(gap)

    order = {'CRITIQUE': 0, 'FAIBLE': 1}
    gaps.sort(key=lambda g: order.get(g['status'], 9))

    return gaps


def compute_health_score(coverage, memory_data, payload_data, waf_data):
    scores = []

    # Equilibre categories (0-30)
    pcts = [c['pct_total'] for c in coverage.values()]
    if pcts:
        zero_penalty = sum(1 for p in pcts if p == 0) * 5
        balance = max(0, 30 - zero_penalty)
    else:
        balance = 0
    scores.append(('Equilibre categories', balance, 30))

    # Volume bypasses (0-25)
    total_bypasses = payload_data.get('total_bypasses', 0)
    vol_score = min(25, total_bypasses // 300)
    scores.append(('Volume bypasses', vol_score, 25))

    # Couverture WAF (0-20)
    total_rules = waf_data.get('total_rules', 0)
    waf_score = min(20, total_rules // 10)
    scores.append(('Couverture WAF', waf_score, 20))

    # Memoire utilisable (0-15)
    total_mem = memory_data.get('total_items', 0)
    if total_mem > 0:
        mem_score = min(15, int(15 * total_mem / 10000))
    else:
        mem_score = 0
    scores.append(('Memoire', mem_score, 15))

    # Activite recente (0-10)
    recent = payload_data.get('bypasses_24h', 0)
    act_score = min(10, recent // 10)
    scores.append(('Activite 24h', act_score, 10))

    total = sum(s[1] for s in scores)
    return total, scores


# -- Generation du rapport --

def _pct(a, b):
    if not b:
        return 0
    return round(a / b * 100, 1)


def generate_report(coverage, gaps, health, health_details,
                    payload_data, memory_data, waf_data):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = []

    lines.append('# Rapport AgentSuperviseur - Diagnostic')
    lines.append('Genere le {}\n'.format(now))

    # Sante globale
    lines.append('## Sante globale : {}/100\n'.format(health))
    bar_filled = health // 5
    bar_empty = 20 - bar_filled
    lines.append('`{}{}` {}%\n'.format('#' * bar_filled, '.' * bar_empty, health))
    lines.append('| Critere | Score | Max |')
    lines.append('|---------|-------|-----|')
    for name, score, max_score in health_details:
        lines.append('| {} | {} | {} |'.format(name, score, max_score))
    lines.append('')

    # Couverture par categorie
    lines.append('## Couverture par categorie\n')
    lines.append('| Categorie | Bypasses | % total | Regles WAF | Ratio | Statut |')
    lines.append('|-----------|----------|---------|------------|-------|--------|')
    for cat in CATEGORIES:
        info = coverage.get(cat, {})
        status_icon = {
            'FORTE': '[++]', 'OK': '[+]', 'FAIBLE': '[!]', 'CRITIQUE': '[!!]'
        }.get(info.get('status', ''), '[?]')
        lines.append(
            '| {} | {} | {}% | {} | {}% | {} {} |'.format(
                cat.upper(), info.get('bypasses', 0),
                info.get('pct_total', 0), info.get('waf_rules', 0),
                info.get('rule_ratio', 0), status_icon, info.get('status', '?')
            )
        )
    lines.append('')

    # Lacunes
    if gaps:
        lines.append('## [!] Lacunes detectees\n')
        for i, g in enumerate(gaps, 1):
            icon = '[!!]' if g['status'] == 'CRITIQUE' else '[!]'
            lines.append("**{}. {} {}** - {}".format(i, icon, g['categorie'].upper(), g['status']))
            lines.append("   - Bypasses : {} | Regles WAF : {} | Part : {}%".format(
                g['bypasses'], g['waf_rules'], g['pct']))
            lines.append("   - Action : {}".format(g['action']))
            lines.append('')
    else:
        lines.append('## [v] Aucune lacune critique\n')

    # Memoire
    lines.append('## Memoire\n')
    lines.append("- **Total items** : {}".format(memory_data.get('total_items', 0)))
    lines.append("- **Items utilises** : {} ({}%)".format(
        memory_data.get('used_items', 0),
        _pct(memory_data.get('used_items', 0), memory_data.get('total_items', 1))))
    lines.append("- **Avec embeddings** : {}".format(memory_data.get('with_embeddings', 0)))
    lines.append("- **Dernier ajout** : {}".format(memory_data.get('last_added', '?')))
    lines.append('')
    lines.append('### Top sources')
    lines.append('| Source | Items |')
    lines.append('|--------|-------|')
    for source, count in memory_data.get('by_source', []):
        lines.append('| {} | {} |'.format(source, count))
    lines.append('')

    # WAF Engine
    lines.append('## WAF Engine\n')
    lines.append("- **Regles actives** : {}".format(waf_data.get('total_rules', 0)))
    lines.append("- **Arena cycles** : {}".format(len(waf_data.get('arena_cycles', []))))
    lines.append("- **Bypasses traites (arena)** : {}".format(waf_data.get('arena_processed', 0)))
    lines.append('')
    lines.append('### Regles par source')
    for source, count in waf_data.get('rules_by_source', {}).items():
        lines.append("- {} : {}".format(source, count))
    lines.append('')

    # Payloads
    lines.append('## Payloads\n')
    lines.append("- **Total importes** : {}".format(payload_data.get('total_imported', 0)))
    lines.append("- **Total resultats** : {}".format(payload_data.get('total_results', 0)))
    lines.append("- **Bypasses confirmes** : {}".format(payload_data.get('total_bypasses', 0)))
    lines.append("- **Bypasses dernieres 24h** : {}".format(payload_data.get('bypasses_24h', 0)))
    lines.append('')
    if payload_data.get('ranks'):
        lines.append('### Valhalla')
        for rank, count in payload_data['ranks'].items():
            lines.append("- {} : {}".format(rank, count))
    lines.append('')

    # Actions prioritaires
    lines.append('## Actions prioritaires (prochains cycles)\n')
    actions = generate_actions(coverage, gaps, health, payload_data, memory_data, waf_data)
    for i, action in enumerate(actions, 1):
        lines.append("{}. {}".format(i, action))
    lines.append('')

    lines.append('---')
    lines.append('AgentSuperviseur Boucle 1 - {}'.format(now))

    return '\n'.join(lines)


def generate_actions(coverage, gaps, health, payload_data, memory_data, waf_data):
    actions = []

    for g in gaps[:3]:
        if g['categorie'] == 'ssrf' and g['bypasses'] == 0:
            actions.append(
                '[!!] URGENT : Lancer AgentRecherche sur SSRF (0 bypass). '
                'Cloud metadata, DNS rebinding, IPv6.'
            )
        elif g['categorie'] == 'xxe' and g['bypasses'] < 50:
            actions.append(
                '[!] XXE : {} bypasses. Rechercher blind XXE, parameter entities, '
                'UTF-16 encoding.'.format(g['bypasses'])
            )
        elif g['categorie'] == 'rce' and g['bypasses'] < 100:
            actions.append(
                '[!] RCE : {} bypasses. Rechercher command injection, deserialization, '
                'template RCE.'.format(g['bypasses'])
            )
        elif g['status'] == 'CRITIQUE':
            actions.append(
                '[!!] {} : Couverture critique ({}%). Recherche + generation urgente.'.format(
                    g['categorie'].upper(), g['pct']
                ))
        elif g['status'] == 'FAIBLE':
            actions.append(
                '[!] {} : Couverture faible ({}%). Prioriser dans evolve_live_v2.'.format(
                    g['categorie'].upper(), g['pct']
                ))

    used_pct = _pct(memory_data.get('used_items', 0), memory_data.get('total_items', 1))
    if used_pct == 0:
        actions.append(
            '[M] Memoire : Aucun item utilise (use_count=0). '
            'Verifier que les agents lisent la memoire.'
        )

    arena_cycles = waf_data.get('arena_cycles', [])
    if len(arena_cycles) < 10:
        actions.append(
            '[*] Arena : Seulement {} cycles. Lancer plus de cycles red/blue.'.format(
                len(arena_cycles)
            ))

    if health < 30:
        actions.append(
            '[!] Sante critique ({}/100). Systeme sous-developpe, '
            'prioriser recherche et generation.'.format(health))
    elif health < 50:
        actions.append(
            '[!] Sante faible ({}/100). Augmenter la cadence des cycles '
            'evolve et research.'.format(health))

    if not actions:
        actions.append('[v] Systeme en bonne sante. Maintenir la cadence actuelle.')

    return actions


# -- Point d'entree --

def run_diagnostic():
    now = datetime.now().strftime('%H:%M:%S')
    print('[{}] === AGENT SUPERVISEUR - DIAGNOSTIC ===\n'.format(now))

    print('[{}] Scan payload_lab.db...'.format(now))
    payload_data = scan_payloads()
    if 'error' in payload_data:
        print('  ERREUR: {}'.format(payload_data['error']))
    else:
        print('  {} importes | {} bypasses'.format(
            payload_data['total_imported'], payload_data['total_bypasses']))

    print('[{}] Scan memory_core.db...'.format(now))
    memory_data = scan_memory()
    if 'error' in memory_data:
        print('  ERREUR: {}'.format(memory_data['error']))
    else:
        print('  {} items | {} utilises'.format(
            memory_data['total_items'], memory_data['used_items']))

    print('[{}] Scan waf_rules.db...'.format(now))
    waf_data = scan_waf()
    if 'error' in waf_data:
        print('  ERREUR: {}'.format(waf_data['error']))
    else:
        print('  {} regles | {} cycles arena'.format(
            waf_data['total_rules'], len(waf_data.get('arena_cycles', []))))

    # Couverture
    print('\n[{}] Analyse de couverture...'.format(now))
    coverage = compute_coverage(payload_data, waf_data)
    for cat, info in coverage.items():
        icon = {
            'FORTE': '++', 'OK': ' +', 'FAIBLE': ' !', 'CRITIQUE': '!!'
        }.get(info['status'], '  ')
        print('  [{}] {:6s} : {:5d} bypasses ({:5.1f}%) | {:3d} regles WAF'.format(
            icon, cat.upper(), info['bypasses'], info['pct_total'], info['waf_rules']))

    # Lacunes
    gaps = detect_gaps(coverage, payload_data)
    if gaps:
        print('\n[{}] Lacunes detectees:'.format(now))
        for g in gaps:
            print('  {:8s} | {} | {}'.format(g['status'], g['categorie'].upper(), g['action'][:60]))

    # Score de sante
    health, health_details = compute_health_score(coverage, memory_data, payload_data, waf_data)
    print('\n[{}] Sante du systeme : {}/100'.format(now, health))
    for name, score, max_score in health_details:
        print('  {:25s} : {}/{}'.format(name, score, max_score))

    # Rapport
    report = generate_report(coverage, gaps, health, health_details,
                             payload_data, memory_data, waf_data)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding='utf-8')
    print('\n[{}] Rapport sauvegarde : {}'.format(now, REPORT_PATH))

    # JSON pour les boucles suivantes
    diagnostic_data = {
        'timestamp': datetime.now().isoformat(),
        'health_score': health,
        'coverage': coverage,
        'gaps': gaps,
        'payload_stats': {k: v for k, v in payload_data.items() if k != 'ranks'},
        'memory_stats': {k: v for k, v in memory_data.items()
                         if k not in ('by_source', 'top_tags')},
        'waf_stats': {k: v for k, v in waf_data.items() if k != 'arena_cycles'},
    }
    json_path = ROOT / '.cyberia' / 'supervisor_diagnostic.json'
    json_path.write_text(
        json.dumps(diagnostic_data, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    print('[{}] Donnees JSON : {}'.format(now, json_path))

    print('\n[{}] === DIAGNOSTIC TERMINE ==='.format(now))
    return diagnostic_data


# ====================================================================
# Boucle 2 : RechercheCiblee
# Lit les lacunes critiques, interroge MiMo, injecte en memoire,
# genere supervisor_prompts.json pour evolve_live_v2.
# ====================================================================

DIAGNOSTIC_JSON = ROOT / '.cyberia' / 'supervisor_diagnostic.json'
PROMPTS_JSON    = ROOT / '.cyberia' / 'supervisor_prompts.json'
MEMORY_HUB_DB   = ROOT / '.cyberia' / 'memory_hub.db'
METRICS_DB      = ROOT / '.cyberia' / 'learning_metrics.db'

# Prompts de recherche par categorie critique
RESEARCH_PROMPTS = {
    'ssrf': 'You are a senior security researcher specializing in SSRF.\nGenerate 10 advanced SSRF WAF bypass payloads.\nFocus on:\n- AWS IMDSv2 token bypass techniques\n- GCP metadata (169.254.169.254) obfuscation\n- Azure managed identity endpoint bypass\n- DNS rebinding payloads\n- IPv6 localhost variants (::1, 0:0:0:0:0:0:0:1)\n- Decimal/octal IP encoding (2130706433, 017700000001)\n- URL parser confusion (http://attacker.com@169.254.169.254)\n- Open redirect chains to internal services\nFor each payload provide: raw payload, technique name, WAF bypass reason, OWASP category.\nFormat as JSON: {"research":[{"payload":"...","technique":"...","waf_bypass":"...","owasp":"..."}]}',

    'xxe': 'You are a senior security researcher specializing in XXE injection.\nGenerate 10 advanced XXE WAF bypass payloads.\nFocus on:\n- Blind XXE via out-of-band (OOB) data exfiltration\n- Parameter entity injection in external DTD\n- UTF-16 encoded XXE payloads\n- XXE via SVG image upload\n- XXE via SOAP/XML API endpoints\n- XXE via XSLT transformation\n- File read via SYSTEM entity (Linux and Windows paths)\n- XXE with CDATA sections to bypass filtering\n- Nested entity expansion (billion laughs style, safe variants)\n- XXE via multipart form data boundary manipulation\nFor each payload provide: raw payload, technique, WAF bypass reason, OWASP category.\nFormat as JSON: {"research":[{"payload":"...","technique":"...","waf_bypass":"...","owasp":"..."}]}',

    'rce': 'You are a senior security researcher specializing in RCE detection.\nGenerate 10 advanced RCE WAF bypass payloads.\nFocus on:\n- Command injection via IFS substitution ($ {IFS}cat)\n- Backtick and $() subshell execution\n- Hex/octal encoded commands\n- Null byte injection between commands\n- Pipe and semicolon command chaining\n- Deserialization payloads (Python pickle, Java, PHP)\n- Template injection leading to RCE (Jinja2, Twig)\n- Command injection via HTTP headers (User-Agent, Referer)\n- Wildcard glob bypass (/bin/ca? /etc/passwd)\n- Newline injection to bypass single-command filters\nFor each payload provide: raw payload, technique, WAF bypass reason, OWASP category.\nFormat as JSON: {"research":[{"payload":"...","technique":"...","waf_bypass":"...","owasp":"..."}]}',

    'ssti': 'You are a senior security researcher specializing in SSTI.\nGenerate 10 advanced SSTI WAF bypass payloads.\nFocus on:\n- Jinja2 sandbox escape techniques\n- Twig template code execution\n- FreeMarker template injection (Java)\n- Velocity template injection\n- Smarty template injection (PHP)\n- Handlebars template injection (Node.js)\n- Unicode delimiter bypass\n- Comment bypass to break patterns\n- Nested expression bypass\n- SSTI via HTTP headers or URL parameters\nFor each payload provide: raw payload, technique, WAF bypass reason, OWASP category.\nFormat as JSON: {"research":[{"payload":"...","technique":"...","waf_bypass":"...","owasp":"..."}]}',
}

# Priorites dynamiques pour evolve_live_v2
EVOLVE_PROMPT_TEMPLATES = {
    'ssrf': (
        'Generate 8 SSRF WAF bypass payloads. '
        'Techniques: cloud metadata 169.254.169.254 with token bypass, '
        'DNS rebinding, IPv6 localhost encoding, decimal IP 2130706433, '
        'open redirect chains, URL parser confusion, '
        'AWS IMDSv2, GCP metadata, Azure managed identity. '
        'Output JSON: {"mutations":[{"payload":"...","type":"ssrf","technique":"..."}]}'
    ),
    'xxe': (
        'Generate 8 XXE injection WAF bypass payloads. '
        'Techniques: blind XXE OOB, parameter entity in external DTD, '
        'UTF-16 encoding, SVG image upload, CDATA sections, '
        'nested entities, XSLT transformation, '
        'SYSTEM file read Linux and Windows. '
        'Output JSON: {"mutations":[{"payload":"...","type":"xxe","technique":"..."}]}'
    ),
    'rce': (
        'Generate 8 RCE chain WAF bypass payloads. '
        'Techniques: IFS substitution, backtick execution, '
        'hex octal encoding, null byte injection, '
        'command separator ; | && ||, newline injection, '
        'deserialization pickle, template RCE. '
        'Output JSON: {"mutations":[{"payload":"...","type":"rce","technique":"..."}]}'
    ),
    'ssti': (
        'Generate 8 SSTI template injection WAF bypass payloads. '
        'Targets: Jinja2, Twig, FreeMarker, Velocity, Smarty, Handlebars. '
        'Techniques: unicode delimiter \u007b\u007b, comment bypass, '
        'nested expressions, sandbox escape, '
        'encoded delimiters, case mixing. '
        'Output JSON: {"mutations":[{"payload":"...","type":"ssti","technique":"..."}]}'
    ),
}


def load_diagnostic():
    if not DIAGNOSTIC_JSON.exists():
        return None
    with open(DIAGNOSTIC_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def call_mimo_research(prompt, max_tokens=2000):
    from openai import OpenAI
    api_key = os.getenv('MIMO_API_KEY', '')
    if not api_key:
        return None, 'MIMO_API_KEY non definie'
    client = OpenAI(api_key=api_key, base_url='https://api.xiaomimimo.com/v1')
    try:
        resp = client.chat.completions.create(
            model='mimo-v2.5-pro',
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens
        )
        return resp.choices[0].message.content, None
    except Exception as e:
        return None, str(e)[:120]


def inject_to_memory_hub(discoveries, category):
    conn = sqlite3.connect(str(MEMORY_HUB_DB), timeout=10)
    conn.execute('''CREATE TABLE IF NOT EXISTS conversation_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT, category TEXT, content TEXT,
        embedding TEXT, confidence REAL DEFAULT 1.0,
        created_at TEXT, last_referenced TEXT,
        reference_count INTEGER DEFAULT 0
    )''')
    now = datetime.now().isoformat()
    count = 0
    for disc in discoveries:
        content = disc[:2000] if isinstance(disc, str) else str(disc)[:2000]
        conn.execute(
            'INSERT INTO conversation_memory '
            '(session_id, category, content, created_at, last_referenced) '
            'VALUES (?,?,?,?,?)',
            ('superviseur_recherche', category, content, now, now)
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def build_evolve_prompts(gaps, research_results):
    prompts = []
    for gap in gaps:
        cat = gap['categorie']
        if cat in EVOLVE_PROMPT_TEMPLATES:
            prompts.append({
                'category': cat,
                'prompt': EVOLVE_PROMPT_TEMPLATES[cat],
                'reason': gap['action'],
                'ttl': 5,
                'priority': 'high' if gap['status'] == 'CRITIQUE' else 'medium',
            })
    return prompts


def run_recherche():
    now = datetime.now().strftime('%H:%M:%S')
    print('[{}] === AGENT SUPERVISEUR - BOUCLE 2 : RECHERCHE CIBLEE ===\n'.format(now))

    # 1. Charger le diagnostic
    diag = load_diagnostic()
    if not diag:
        print('[{}] ERREUR: supervisor_diagnostic.json introuvable.'.format(now))
        print('[{}] Lancez d abord: python core/agent_superviseur.py --diagnostic'.format(now))
        return

    gaps = diag.get('gaps', [])
    critiques = [g for g in gaps if g['status'] == 'CRITIQUE']
    if not critiques:
        print('[{}] Aucune lacune critique. Recherche non necessaire.'.format(now))
        return

    print('[{}] {} lacunes critiques detectees:'.format(now, len(critiques)))
    for g in critiques:
        print('  [!!] {} - {} ({}%)'.format(
            g['categorie'].upper(), g['status'], g['pct']))

    # 2. Recherche LLM pour chaque lacune
    all_discoveries = {}
    for g in critiques:
        cat = g['categorie']
        if cat not in RESEARCH_PROMPTS:
            print('\n[{}] {} : pas de prompt de recherche defini, skip'.format(now, cat.upper()))
            continue

        print('\n[{}] Recherche {}...'.format(now, cat.upper()))
        prompt = RESEARCH_PROMPTS[cat]
        response, error = call_mimo_research(prompt)

        if error:
            print('  ERREUR: {}'.format(error))
            continue

        if not response:
            print('  ERREUR: reponse vide')
            continue

        print('  Reponse recue ({} chars)'.format(len(response)))

        # Parser la reponse
        parsed = safe_json_parse(response)
        if isinstance(parsed, list):
            parsed = {'research': parsed}

        research_items = parsed.get('research', [])
        if not research_items:
            # Fallback: extraire les donnees brutes
            for v in parsed.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    research_items = v
                    break

        if not research_items:
            print('  Aucune donnee exploitable dans la reponse')
            # Injecter le texte brut quand meme
            inject_to_memory_hub([response], cat)
            print('  Texte brut injecte en memoire')
            all_discoveries[cat] = [{'raw': response[:500]}]
            continue

        # Formater les decouvertes
        formatted = []
        for item in research_items:
            payload = item.get('payload', '')
            technique = item.get('technique', '')
            waf_bypass = item.get('waf_bypass', '')
            owasp = item.get('owasp', '')
            formatted.append(
                '{} | {} | {} | {}'.format(
                    technique, payload[:80], waf_bypass[:60], owasp
                )
            )

        print('  {} decouvertes formatees'.format(len(formatted)))
        all_discoveries[cat] = research_items

        # 3. Injecter dans memory_hub.db
        injected = inject_to_memory_hub(formatted, cat)
        print('  {} items injectes dans memory_hub.db'.format(injected))

    # 4. Generer les prompts pour evolve_live_v2
    evolve_prompts = build_evolve_prompts(critiques, all_discoveries)
    PROMPTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMPTS_JSON, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'priority_prompts': evolve_prompts
        }, f, indent=2, ensure_ascii=False)
    print('\n[{}] {} prompts prioritaires ecrits dans {}'.format(
        now, len(evolve_prompts), PROMPTS_JSON))

    # 5. Resume
    print('\n[{}] === RECHERCHE CIBLEE TERMINEE ==='.format(now))
    print('  Categories traitees: {}'.format(
        ', '.join(c.upper() for c in all_discoveries.keys())))
    total_items = sum(len(v) for v in all_discoveries.values())
    print('  Total decouvertes: {}'.format(total_items))
    print('  Prompts evolve: {}'.format(len(evolve_prompts)))

    return all_discoveries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='AgentSuperviseur - Diagnostic et Recherche'
    )
    parser.add_argument('--diagnostic', action='store_true',
                        help='Lance le diagnostic complet (Boucle 1)')
    parser.add_argument('--recherche', action='store_true',
                        help='Lance la recherche ciblee (Boucle 2)')
    args = parser.parse_args()

    if args.diagnostic:
        run_diagnostic()
    elif args.recherche:
        run_recherche()
    else:
        parser.print_help()
