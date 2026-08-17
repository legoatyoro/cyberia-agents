"""
Arena Red vs Blue — boucle fermee d'apprentissage WAF.

Cycle (300s) :
  Phase RED      : charge les 20 meilleurs bypasses DIAMOND nouveaux
  Phase ANTIDOTE : LLM (AgentBlueTeam) genere une regle ModSecurity par bypass
  Phase INJECT   : injecte dans waf_rules.db si la regle est nouvelle et valide
  Phase RETEST   : reteste les 20 bypasses contre les nouvelles regles
  Phase STATS    : tableau avant/apres, taux de blocage, regles injectees
"""
import re
import sys
import time
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote

sys.path.insert(0, ".")

PAYLOAD_DB  = Path('.cyberia/payload_lab.db')
WAF_DB      = Path('.cyberia/waf_rules.db')
LOG_PATH    = Path('.cyberia/arena_red_blue.log')

CYCLE_INTERVAL   = 300   # secondes entre deux cycles
TOP_N            = 20    # bypasses a traiter par cycle
ARENA_ID_START   = 970001  # plage d'IDs reservee a l'Arena


# ── Logging ────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}][Arena] {msg}'
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'), flush=True)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


# ── Initialisation des tables de suivi ────────────────────────────────────

def _init_tracking():
    """Cree la table arena_processed dans waf_rules.db pour tracker les bypasses traites."""
    WAF_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(WAF_DB, timeout=15)
    conn.execute('''CREATE TABLE IF NOT EXISTS waf_rules (
        id INTEGER PRIMARY KEY,
        rule_id INTEGER UNIQUE,
        phase INTEGER DEFAULT 2,
        pattern TEXT NOT NULL,
        description TEXT,
        category TEXT,
        source TEXT DEFAULT 'crs_base',
        severity TEXT DEFAULT 'CRITICAL',
        created_at TEXT,
        enabled INTEGER DEFAULT 1
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS arena_processed (
        id INTEGER PRIMARY KEY,
        payload_hash TEXT UNIQUE,
        payload TEXT,
        payload_type TEXT,
        score INTEGER,
        processed_at TEXT,
        rule_generated INTEGER DEFAULT 0,
        rule_id_generated INTEGER
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS arena_cycles (
        id INTEGER PRIMARY KEY,
        cycle INTEGER,
        bypasses_loaded INTEGER,
        rules_injected INTEGER,
        blocked_before INTEGER,
        blocked_after INTEGER,
        rate_before REAL,
        rate_after REAL,
        ran_at TEXT
    )''')
    conn.commit()
    conn.close()


def _payload_hash(payload):
    return hashlib.sha256(payload.encode('utf-8', errors='replace')).hexdigest()[:16]


# ── Phase RED : 20 meilleurs bypasses DIAMOND actifs ─────────────────────

# XSS souvent deja couverts par les regles CRS de base — traites en dernier
_PRIORITY_TYPES = ('lfi', 'ssti', 'ssrf', 'rce', 'xxe', 'mixed', 'rce_chain')


def _category_matches(payload_type, rule_category):
    """Verifie si la regle s'applique au type de payload."""
    if not payload_type or payload_type == 'mixed':
        return True  # pas de filtre, tester toutes les regles
    pt = payload_type.replace('_chain', '').replace('_advanced', '').replace('_no_script', '').replace('_traversal', '').replace('_engines', '')
    return rule_category == pt


def _test_with_rules(payload, rules, payload_type=None):
    """Retourne True si le payload PASSE (n'est PAS bloque) par les regles de sa categorie."""
    decoded = unquote(payload, errors='replace')
    for _, compiled, _, category, _ in rules:
        if not _category_matches(payload_type, category):
            continue
        try:
            if compiled.search(payload) or compiled.search(decoded):
                return False  # bloque
        except Exception:
            continue
    return True  # toujours actif


def phase_red():
    """
    Charge jusqu'a TOP_N bypasses DIAMOND encore actifs (non bloques par les regles WAF).
    Priorite aux types non-XSS : lfi, ssti, ssrf, rce, xxe, mixed, rce_chain.
    'Nouveau' = payload_hash absent de arena_processed.
    Si moins de 5 bypasses actifs dans le premier batch, etend la recherche aux suivants.
    Retourne une liste de (payload, payload_type, score, target).
    """
    if not PAYLOAD_DB.exists():
        log(f'[RED] payload_lab.db introuvable: {PAYLOAD_DB}')
        return []

    # Hashes deja traites par l'Arena
    conn_waf = sqlite3.connect(WAF_DB, timeout=10)
    processed_hashes = {
        row[0] for row in
        conn_waf.execute('SELECT payload_hash FROM arena_processed').fetchall()
    }
    conn_waf.close()

    # Regles WAF courantes pour filtrer les bypasses encore actifs
    rules = _load_rules_fresh()
    log(f'[RED] {len(rules)} regles WAF actives | {len(processed_hashes)} bypasses deja traites')

    # Lecture DB en deux passes : types prioritaires d'abord, puis tous les autres
    try:
        conn_pay = sqlite3.connect(PAYLOAD_DB, timeout=10)
        placeholders = ','.join('?' * len(_PRIORITY_TYPES))
        rows_prio = conn_pay.execute(
            f'''SELECT payload, payload_type, score, target
               FROM results WHERE bypass_confirmed=1
               AND payload_type IN ({placeholders})
               ORDER BY score DESC LIMIT 500''',
            _PRIORITY_TYPES
        ).fetchall()
        rows_other = conn_pay.execute(
            f'''SELECT payload, payload_type, score, target
               FROM results WHERE bypass_confirmed=1
               AND payload_type NOT IN ({placeholders})
               ORDER BY score DESC LIMIT 500''',
            _PRIORITY_TYPES
        ).fetchall()
        conn_pay.close()
    except Exception as e:
        log(f'[RED] erreur lecture payload_lab.db: {e}')
        return []

    log(f'[RED] DB brut → prioritaires: {len(rows_prio)} | autres: {len(rows_other)}')

    # Fusion prioritaires en tete + deduplication + filtre processed
    seen_hashes = set()
    candidates = []
    for payload, ptype, score, target in rows_prio + rows_other:
        h = _payload_hash(payload)
        if h not in processed_hashes and h not in seen_hashes:
            seen_hashes.add(h)
            candidates.append((payload, ptype, score or 0, target or ''))

    log(f'[RED] {len(candidates)} candidats nouveaux apres filtre processed')

    # Parcourt les candidats par batch de TOP_N, ne garde que ceux encore actifs
    active = []
    offset = 0

    while offset < len(candidates):
        batch = candidates[offset:offset + TOP_N]
        offset += TOP_N

        newly_active = [b for b in batch if _test_with_rules(b[0], rules, b[1])]
        active.extend(newly_active)

        if len(active) >= TOP_N:
            break

        if len(active) < 5 and offset < len(candidates):
            log(f'[RED] Seulement {len(active)} actifs dans ce batch — '
                f'expansion vers candidats {offset}-{offset + TOP_N}')

    active = active[:TOP_N]

    # Resume par type pour le log
    by_type: dict = {}
    for _, ptype, _, _ in active:
        by_type[ptype] = by_type.get(ptype, 0) + 1
    type_summary = ' | '.join(f'{k}:{v}' for k, v in sorted(by_type.items())) or 'aucun'

    log(f'[RED] {len(active)}/{TOP_N} bypasses actifs selectionnes — {type_summary}')
    return active


# ── Phase ANTIDOTE : LLM genere une regle par bypass ─────────────────────

def _call_llm_antidote(payload, ptype, score):
    """
    Appelle le LLM (AgentBlueTeam) pour generer une regle ModSecurity
    qui bloquerait ce payload.
    Retourne un dict ou None.
    """
    try:
        from core.multi_model_router_v2 import router_v2
        from core.json_parser import safe_json_parse
    except Exception as e:
        log(f'  [ANTIDOTE] import erreur: {e}')
        return None

    prompt = (
        'You are AgentBlueTeam, a ModSecurity WAF engineer.\n'
        f'This payload bypassed the WAF (type: {ptype}, bypass score: {score}):\n'
        f'  {payload[:200]}\n\n'
        'Generate ONE precise ModSecurity-compatible regex rule to block this payload.\n'
        'The regex must be valid Python re syntax.\n'
        'Minimize false positives: the rule must be specific to the attack pattern.\n'
        'Reply ONLY with this JSON (no markdown, no explanation):\n'
        '{"rule_id":"970XXX","pattern":"<python_re_regex>","category":"xss|sqli|lfi|ssti|rce|xxe|ssrf|mixed",'
        '"severity":"CRITICAL|HIGH|MEDIUM","description":"<short description under 80 chars>"}'
    )

    for agent in ['AgentBlueTeam', 'AgentSecurite', 'AgentCode']:
        try:
            info = router_v2.get_model_for_agent(agent)
            completion = info['client'].chat.completions.create(
                model=info['model'],
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=400)
            response = completion.choices[0].message.content
            if not response:
                continue
            data = safe_json_parse(response)
            if isinstance(data, list):
                data = {"mutations": data}
            if data.get('raw'):
                # Fallback : extraction manuelle du JSON dans la reponse brute
                match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
                if match:
                    data = safe_json_parse(match.group())
                    if isinstance(data, list):
                        data = {"mutations": data}
                if data.get('raw'):
                    log(f'  [ANTIDOTE] {agent} reponse non parseable: {response[:80]}')
                    continue
            pattern = data.get('pattern', '').strip()
            category = data.get('category', ptype.split('_')[0] if ptype else 'unknown')
            severity = data.get('severity', 'HIGH')
            description = data.get('description', f'Arena rule for {ptype}')
            if not pattern:
                log(f'  [ANTIDOTE] {agent} pattern vide')
                continue
            log(f'  [ANTIDOTE] {info["provider"]}/{agent} → [{category}] {severity}: {description[:50]}')
            return {
                'pattern': pattern,
                'category': category,
                'severity': severity,
                'description': description,
            }
        except Exception as e:
            err = str(e)
            if '429' in err or 'rate' in err.lower():
                log(f'  [ANTIDOTE] {agent} rate limit — rotation...')
                time.sleep(3)
            else:
                log(f'  [ANTIDOTE] {agent} erreur: {err[:80]}')
            continue
    return None


def phase_antidote(bypasses):
    """
    Pour chaque bypass, demande au LLM une regle ModSecurity.
    Retourne list de (bypass_tuple, rule_dict|None).
    """
    results = []
    for i, (payload, ptype, score, target) in enumerate(bypasses):
        log(f'  [ANTIDOTE] {i+1}/{len(bypasses)} [{ptype}] score:{score} — {payload[:55]}')
        rule = _call_llm_antidote(payload, ptype, score)
        results.append(((payload, ptype, score, target), rule))
        time.sleep(2)  # respecte les rate limits
    return results


# ── Phase INJECT : valide et injecte dans waf_rules.db ───────────────────

def _get_next_arena_rule_id():
    conn = sqlite3.connect(WAF_DB, timeout=10)
    row = conn.execute(
        'SELECT MAX(rule_id) FROM waf_rules WHERE rule_id >= ?', (ARENA_ID_START,)
    ).fetchone()
    conn.close()
    max_id = row[0] if row and row[0] else ARENA_ID_START - 1
    return max(max_id + 1, ARENA_ID_START)


def _pattern_exists(pattern):
    """Verifie qu'une regle avec le meme pattern n'existe pas deja."""
    conn = sqlite3.connect(WAF_DB, timeout=10)
    row = conn.execute(
        'SELECT rule_id FROM waf_rules WHERE pattern=?', (pattern,)
    ).fetchone()
    conn.close()
    return row is not None


def _insert_arena_rule(rule_id, pattern, description, category, severity):
    conn = sqlite3.connect(WAF_DB, timeout=15)
    conn.execute(
        '''INSERT OR IGNORE INTO waf_rules
           (rule_id, phase, pattern, description, category, source, severity, created_at)
           VALUES (?,2,?,?,?,'arena',?,?)''',
        (rule_id, pattern, description, category, severity, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def _mark_processed(payload, ptype, score, rule_id_generated):
    h = _payload_hash(payload)
    conn = sqlite3.connect(WAF_DB, timeout=15)
    conn.execute(
        '''INSERT OR IGNORE INTO arena_processed
           (payload_hash, payload, payload_type, score, processed_at, rule_generated, rule_id_generated)
           VALUES (?,?,?,?,?,?,?)''',
        (h, payload[:500], ptype, score, datetime.now().isoformat(),
         1 if rule_id_generated else 0, rule_id_generated))
    conn.commit()
    conn.close()


def phase_inject(antidote_results):
    """
    Injecte les regles valides dans waf_rules.db.
    Retourne (nb_injected, liste des rule_ids injectes).
    """
    injected = 0
    injected_ids = []
    next_id = _get_next_arena_rule_id()

    for (payload, ptype, score, target), rule in antidote_results:
        rule_id_gen = None

        if rule is None:
            log(f'  [INJECT] pas de regle generee pour: {payload[:40]}')
            _mark_processed(payload, ptype, score, None)
            continue

        pattern = rule['pattern']

        # Validation regex
        try:
            re.compile(pattern)
        except re.error as e:
            log(f'  [INJECT] regex invalide ignoree: {pattern[:50]} ({e})')
            _mark_processed(payload, ptype, score, None)
            continue

        # Deduplciation par pattern
        if _pattern_exists(pattern):
            log(f'  [INJECT] pattern deja present — skip: {pattern[:50]}')
            _mark_processed(payload, ptype, score, None)
            continue

        # Injection
        _insert_arena_rule(
            next_id, pattern,
            rule['description'], rule['category'], rule['severity']
        )
        log(f'  [INJECT] regle {next_id} [{rule["category"]}] {rule["severity"]}: '
            f'{rule["description"][:50]}')
        log(f'           pattern: {pattern[:70]}')

        rule_id_gen = next_id
        injected_ids.append(next_id)
        injected += 1
        next_id += 1

        _mark_processed(payload, ptype, score, rule_id_gen)

    log(f'[INJECT] {injected}/{len(antidote_results)} regles injectees dans waf_rules.db')
    return injected, injected_ids


# ── Phase RETEST : reteste les bypasses avec les nouvelles regles ─────────

def _load_rules_fresh():
    """Charge toutes les regles actives sans cache (pour avoir les nouvelles)."""
    conn = sqlite3.connect(WAF_DB, timeout=10)
    rows = conn.execute(
        'SELECT rule_id, pattern, description, category, severity FROM waf_rules WHERE enabled=1'
    ).fetchall()
    conn.close()
    compiled = []
    for rule_id, pattern, description, category, severity in rows:
        try:
            compiled.append((rule_id, re.compile(pattern), description, category, severity))
        except re.error:
            pass
    return compiled


def _test_payload_against(payload, rules, payload_type=None):
    """Teste un payload contre les regles de sa categorie uniquement."""
    decoded = unquote(payload, errors='replace')
    for rule_id, compiled, description, category, severity in rules:
        if not _category_matches(payload_type, category):
            continue
        try:
            if compiled.search(payload) or compiled.search(decoded):
                return True, f'rule:{rule_id} [{category}] {description}'
        except Exception:
            continue
    return False, None


def phase_retest(bypasses, rules_before, rules_after):
    """
    Reteste les bypasses avant et apres injection.
    Retourne (blocked_before, blocked_after, details).
    """
    details = []
    blocked_before = 0
    blocked_after = 0

    for payload, ptype, score, target in bypasses:
        b_before, rule_b = _test_payload_against(payload, rules_before, ptype)
        b_after,  rule_a = _test_payload_against(payload, rules_after, ptype)

        if b_before:
            blocked_before += 1
        if b_after:
            blocked_after += 1

        # Nouveaux blocages uniquement
        newly_blocked = b_after and not b_before
        details.append({
            'payload': payload,
            'ptype': ptype,
            'score': score,
            'blocked_before': b_before,
            'blocked_after': b_after,
            'newly_blocked': newly_blocked,
            'rule_before': rule_b,
            'rule_after': rule_a,
        })

    return blocked_before, blocked_after, details


# ── Phase STATS : tableau recap ────────────────────────────────────────────

def phase_stats(cycle, bypasses, blocked_before, blocked_after,
                rules_injected, injected_ids, details):
    """Affiche et persiste le tableau de stats du cycle."""
    n = len(bypasses)
    rate_before = (blocked_before / n * 100) if n else 0
    rate_after  = (blocked_after  / n * 100) if n else 0
    gain        = blocked_after - blocked_before
    newly       = [d for d in details if d['newly_blocked']]

    sep = '=' * 60
    log(sep)
    log(f'  ARENA STATS — CYCLE {cycle}')
    log(sep)
    log(f'  Bypasses analyses  : {n}')
    log(f'  Regles injectees   : {rules_injected} (IDs: {injected_ids[:5]}{"..." if len(injected_ids)>5 else ""})')
    log(f'  Bloques AVANT      : {blocked_before}/{n}  ({rate_before:.1f}%)')
    log(f'  Bloques APRES      : {blocked_after}/{n}   ({rate_after:.1f}%)')
    log(f'  Amelioration       : +{gain} bypasses bloques (+{rate_after-rate_before:.1f}%)')
    log(sep)

    if newly:
        log(f'  Nouveaux blocages ({len(newly)}) :')
        for d in newly[:10]:
            log(f'    [{d["ptype"]}] score:{d["score"]} — {d["payload"][:50]}')
            if d['rule_after']:
                log(f'      → {d["rule_after"][:80]}')
    else:
        log('  Aucun nouveau blocage ce cycle.')

    # Bypasses toujours non bloques
    still_passing = [d for d in details if not d['blocked_after']]
    if still_passing:
        log(f'  Toujours non bloques ({len(still_passing)}) :')
        for d in still_passing[:5]:
            log(f'    [{d["ptype"]}] score:{d["score"]} — {d["payload"][:55]}')
    log(sep)

    # Persistance dans waf_rules.db
    try:
        conn = sqlite3.connect(WAF_DB, timeout=10)
        conn.execute(
            '''INSERT INTO arena_cycles
               (cycle, bypasses_loaded, rules_injected, blocked_before, blocked_after,
                rate_before, rate_after, ran_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (cycle, n, rules_injected, blocked_before, blocked_after,
             round(rate_before, 2), round(rate_after, 2), datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f'  [STATS] erreur persistance: {e}')

    return {
        'cycle': cycle, 'n': n, 'rules_injected': rules_injected,
        'blocked_before': blocked_before, 'blocked_after': blocked_after,
        'rate_before': rate_before, 'rate_after': rate_after, 'gain': gain,
    }


# ── Boucle principale ──────────────────────────────────────────────────────

def run_arena(interval=CYCLE_INTERVAL):
    _init_tracking()

    # S'assure que waf_engine a charge ses regles de base
    try:
        from waf_engine import phase1_load_crs
        phase1_load_crs()
    except Exception as e:
        log(f'[INIT] waf_engine.phase1_load_crs non disponible: {e}')

    cycle = 0
    log('=' * 60)
    log('  ARENA RED vs BLUE — BOUCLE FERMEE D\'APPRENTISSAGE WAF')
    log(f'  Cycle: {interval}s | Bypasses/cycle: {TOP_N} | DB: {WAF_DB}')
    log('=' * 60)

    while True:
        cycle += 1
        log(f'\n{"="*60}')
        log(f'  CYCLE {cycle} — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        log(f'{"="*60}')

        # ── Phase RED ───────────────────────────────────────────────
        log('\n[PHASE RED] Chargement des 20 meilleurs bypasses DIAMOND...')
        bypasses = phase_red()

        if not bypasses:
            log('[RED] Aucun nouveau bypass — tous deja traites ou DB vide.')
            log(f'Prochain cycle dans {interval}s...')
            time.sleep(interval)
            continue

        # Snapshot des regles AVANT injection (pour comparaison retest)
        rules_before = _load_rules_fresh()
        log(f'[RED] Regles WAF actives avant injection: {len(rules_before)}')

        # ── Phase ANTIDOTE ──────────────────────────────────────────
        log(f'\n[PHASE ANTIDOTE] Generation de regles pour {len(bypasses)} bypasses...')
        antidote_results = phase_antidote(bypasses)

        # ── Phase INJECT ────────────────────────────────────────────
        log('\n[PHASE INJECT] Validation et injection dans waf_rules.db...')
        nb_injected, injected_ids = phase_inject(antidote_results)

        # Snapshot des regles APRES injection
        rules_after = _load_rules_fresh()
        log(f'[INJECT] Regles WAF actives apres injection: {len(rules_after)}')

        # ── Phase RETEST ────────────────────────────────────────────
        log(f'\n[PHASE RETEST] Retest des {len(bypasses)} bypasses...')
        blocked_before, blocked_after, details = phase_retest(
            bypasses, rules_before, rules_after
        )

        # ── Phase STATS ─────────────────────────────────────────────
        log('\n[PHASE STATS]')
        phase_stats(
            cycle, bypasses, blocked_before, blocked_after,
            nb_injected, injected_ids, details
        )

        # Invalide le cache de waf_engine (si importe) pour le prochain cycle
        try:
            import waf_engine
            waf_engine._rules_cache = None
            waf_engine._rules_cache_ts = 0
        except Exception:
            pass

        log(f'\n  Prochain cycle dans {interval}s...')
        time.sleep(interval)


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Arena Red vs Blue — boucle WAF fermee')
    p.add_argument('--interval', type=int, default=CYCLE_INTERVAL,
                   help=f'Secondes entre cycles (defaut: {CYCLE_INTERVAL})')
    p.add_argument('--once', action='store_true',
                   help='Lance un seul cycle puis quitte')
    args = p.parse_args()

    if args.once:
        _init_tracking()
        try:
            from waf_engine import phase1_load_crs
            phase1_load_crs()
        except Exception:
            pass
        bypasses = phase_red()
        if not bypasses:
            log('Aucun nouveau bypass DIAMOND a traiter.')
        else:
            rules_before      = _load_rules_fresh()
            antidote_results  = phase_antidote(bypasses)
            nb_injected, ids  = phase_inject(antidote_results)
            rules_after       = _load_rules_fresh()
            b_bef, b_aft, det = phase_retest(bypasses, rules_before, rules_after)
            phase_stats(1, bypasses, b_bef, b_aft, nb_injected, ids, det)
    else:
        run_arena(interval=args.interval)
