import sys, time, sqlite3, threading
from pathlib import Path
from datetime import datetime
sys.path.insert(0, ".")
from core.waf_simulator import test_all_wafs, WAF_PROFILES
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse

DB = Path(".cyberia/payload_lab.db")

# â”€â”€ Nouvelles catÃ©gories supplÃ©mentaires â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

PROMPTS_BY_CATEGORY = {
    'xss_no_script': '{"task":"generate 8 XSS WAF bypass payloads without script tags","techniques":["vbscript: in href","jAvAsCrIpT: case mix","CSS expression()","SVG animateTransform","HTML5 onpointerover/ontoggle/onanimationend","data:text/html URI","meta refresh"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"xss","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation, replace <payload_ici> with real payloads"}',
    'waf_evasion_techniques': '{"task":"generate 8 advanced multi-technique WAF bypass payloads","techniques":["unicode+null bytes+case mix","protocol confusion","CRLF injection","header injection","open redirect chains"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"mixed","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'sqli_advanced': '{"task":"generate 8 SQL injection WAF bypass payloads","techniques":["whitespace %0a %09 %a0","comment /*!*/","case mixing","hex keyword encoding","null bytes %00 between chars"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"sqli","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'lfi_traversal': '{"task":"generate 8 LFI path traversal WAF bypass payloads","techniques":["encoded dots %2e%2e","double encoding %252e%252e","unicode %c0%ae","null bytes %00","repeated ....//","windows UNC paths"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"lfi","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'ssti_engines': '{"task":"generate 8 SSTI template injection WAF bypass payloads","targets":["Jinja2","Twig","FreeMarker","Velocity","Smarty","Handlebars"],"techniques":["encoded delimiters","unicode wrapping","comment bypass"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"ssti","technique":"engine_name"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'xxe': '{"task":"generate 8 XXE injection WAF bypass payloads","techniques":["external entity","parameter entity","blind XXE via OOB","UTF-16 encoding","nested entities","SYSTEM file read"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"xxe","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'ssrf': '{"task":"generate 8 SSRF WAF bypass payloads","techniques":["localhost aliases 127.0.0.1/0x7f000001/017700000001","DNS rebinding","URL encoding","IPv6 ::1","cloud metadata 169.254.169.254","open redirect chain"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"ssrf","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
    'rce_chain': '{"task":"generate 8 RCE chain WAF bypass payloads","techniques":["command separator injection ; | & ||","IFS substitution","hex/octal encoding","backtick execution","$() subshell","null byte injection"],"output_format":{"mutations":[{"payload":"<payload_ici>","type":"rce","technique":"nom"}]},"rules":"output valid JSON only, no markdown, no explanation"}',
}

# â”€â”€ CatÃ©gories par worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

WORKER_A_CATEGORIES = ['xss_no_script', 'waf_evasion_techniques']
WORKER_B_CATEGORIES = ['sqli_advanced', 'lfi_traversal']
WORKER_C_CATEGORIES = ['ssti_engines', 'xxe', 'ssrf', 'rce_chain']


# â”€â”€ Helpers DB partagÃ©s â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_db_lock = threading.Lock()


def init_db():
    DB.parent.mkdir(exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(DB, timeout=20)
        conn.execute('''CREATE TABLE IF NOT EXISTS pattern_blacklist
            (pattern TEXT PRIMARY KEY, blocked_count INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()


def is_blacklisted(payload):
    conn = sqlite3.connect(DB, timeout=10)
    row = conn.execute(
        'SELECT blocked_count FROM pattern_blacklist WHERE pattern=?', (payload[:200],)
    ).fetchone()
    conn.close()
    return row is not None and row[0] >= 3


def record_blocked(payload):
    try:
        with _db_lock:
            conn = sqlite3.connect(DB, timeout=20)
            conn.execute(
                '''INSERT INTO pattern_blacklist (pattern, blocked_count) VALUES (?,1)
                ON CONFLICT(pattern) DO UPDATE SET blocked_count = blocked_count + 1''',
                (payload[:200],))
            conn.commit()
            conn.close()
    except Exception:
        pass


def save_bypass(payload, ptype, tech, passed_wafs, score, generation, worker):
    try:
        with _db_lock:
            conn = sqlite3.connect(DB, timeout=20)
            conn.execute(
                "INSERT OR IGNORE INTO imported_payloads "
                "(payload,payload_type,source,imported_at) VALUES (?,?,?,datetime('now'))",
                (payload, ptype, f"evo_v2_{worker}_g{generation}"))
            conn.execute(
                "INSERT INTO results "
                "(payload,payload_type,target,status,score,tested_at,bypass_confirmed) "
                "VALUES (?,?,?,?,?,datetime('now'),1)",
                (payload, ptype, ','.join(passed_wafs), 'BYPASS', score * 20))
            conn.commit()
            conn.close()
        try:
            from tools.memory_hub_v3 import add_pattern
            add_pattern({
                'type': 'vuln_pattern', 'payload': payload,
                'payload_type': ptype, 'passed_wafs': passed_wafs,
                'score': score, 'source': f'evo_v2_{worker}_g{generation}'
            })
        except Exception:
            pass
    except Exception:
        pass


def load_parents(category, force_random=False):
    conn = sqlite3.connect(DB, timeout=10)
    ptype_prefix = category.split('_')[0] + '%'
    parents = []
    if not force_random:
        parents = conn.execute(
            '''SELECT payload FROM results
               WHERE bypass_confirmed=1 AND payload_type LIKE ?
               ORDER BY score DESC, RANDOM() LIMIT 8''',
            (ptype_prefix,)
        ).fetchall()
    if not parents:
        parents = conn.execute(
            'SELECT payload FROM results WHERE bypass_confirmed=1 ORDER BY score DESC, RANDOM() LIMIT 8'
        ).fetchall()
    if not parents:
        parents = conn.execute(
            'SELECT payload FROM imported_payloads ORDER BY waf_score DESC, RANDOM() LIMIT 8'
        ).fetchall()
    conn.close()
    return [row[0] for row in parents]


def get_db_stats():
    try:
        conn = sqlite3.connect(DB, timeout=10)
        total = conn.execute('SELECT COUNT(*) FROM imported_payloads').fetchone()[0]
        bypasses = conn.execute('SELECT COUNT(*) FROM results WHERE bypass_confirmed=1').fetchone()[0]
        blacklisted = conn.execute(
            'SELECT COUNT(*) FROM pattern_blacklist WHERE blocked_count>=3'
        ).fetchone()[0]
        conn.close()
        return total, bypasses, blacklisted
    except Exception:
        return '?', '?', '?'


# â”€â”€ Fonction LLM partagÃ©e â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_llm_response(prompt, worker_name, worker_log):
    agents = ['AgentSecurite', 'AgentCode', 'AgentRecherche']
    for agent in agents:
        try:
            info = router_v2.get_model_for_agent(agent)
            completion = info['client'].chat.completions.create(
                model=info['model'],
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=2000)
            worker_log(f'  Modele: {info["provider"]}/{info["model"]}')
            response_text = completion.choices[0].message.content
            if response_text and not response_text.strip():
                worker_log("  [WARN] Reponse vide du LLM — skip silencieux")
                continue
            return response_text
        except Exception as e:
            err = str(e)
            if '429' in err or 'rate' in err.lower():
                worker_log(f'  [{agent}] Rate limit â€” rotation...')
                time.sleep(2)
                continue
            worker_log(f'  [{agent}] Erreur: {err[:60]}')
            continue
    return None


# â”€â”€ Classe Worker gÃ©nÃ©rique â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class EvolutionWorker:
    def __init__(self, name, categories, interval=60):
        self.name = name
        self.categories = categories
        self.interval = interval
        self.log_path = Path(f'.cyberia/evolve_v2_{name}.log')

    def log(self, msg):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}][{self.name}] {msg}'
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            print(line.encode('ascii', errors='replace').decode('ascii'), flush=True)
        self.log_path.parent.mkdir(exist_ok=True)
        with self.log_path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')

    def run(self):
        generation = 0
        stagnation = 0
        cat_index = 0
        total_bypasses = 0

        self.log(f'=== WORKER {self.name} DEMARRE ===')
        self.log(f'Categories: {self.categories} | Cycle: {self.interval}s')

        while True:
            generation += 1
            category = self.categories[cat_index % len(self.categories)]
            force_random = stagnation >= 3

            if force_random:
                self.log(f'  [ANTI-STAGNATION] {stagnation} cycles sans bypass')
                cat_index += 1
                category = self.categories[cat_index % len(self.categories)]
                stagnation = 0

            self.log(f'\n[GEN {generation}] Categorie: {category}')

            parents = load_parents(category, force_random=force_random)
            parent_str = '\n'.join(f'- {p[:60]}' for p in parents[:6])
            self.log(f'  {len(parents)} parents charges')

            base_prompt = PROMPTS_BY_CATEGORY[category]

            # Lecture supervisor_prompts.json — prompt prioritaire par categorie
            _sp_path = Path('.cyberia/supervisor_prompts.json')
            try:
                if _sp_path.exists():
                    import json as _json
                    _sp = _json.loads(_sp_path.read_text(encoding='utf-8'))
                    _entry = next((x for x in _sp.get('priority_prompts', []) if x.get('category') == category), None)
                    if isinstance(_entry, dict) and _entry.get('ttl', 0) > 0 and _entry.get('prompt'):
                        base_prompt = _entry['prompt']
                        _entry['ttl'] -= 1
                        _sp_path.write_text(
                            _json.dumps(_sp, indent=2, ensure_ascii=False), encoding='utf-8')
                        self.log(f'  [SUPERVISOR] Prompt prioritaire {category} — ttl restant: {_entry["ttl"]}')
            except Exception as _e:
                self.log(f'  [SUPERVISOR] Erreur supervisor_prompts.json: {_e}')

            prompt = f'{base_prompt}\n\nParent examples to mutate:\n{parent_str}'

            response = get_llm_response(prompt, self.name, self.log)
            if not response:
                self.log('  Toutes les APIs indisponibles â€” attente 5min')
                time.sleep(600)
                continue

            self.log(f'  [DEBUG] Reponse brute: {response[:150] if response else "VIDE"}')

            parsed = safe_json_parse(response)
            if isinstance(parsed, list):
                parsed = {'mutations': parsed}
            if parsed.get('raw'):
                self.log('  JSON invalide apres tous les fallbacks â€” skip')
                time.sleep(self.interval)
                continue

            mutations = parsed.get('mutations', [])
            if not mutations:
                self.log('  Pas de mutations â€” skip')
                time.sleep(self.interval)
                continue

            self.log(f'  {len(mutations)} mutations a tester sur {len(WAF_PROFILES)} WAFs')

            gen_bypasses = []
            for m in mutations:
                payload = m.get('payload', '')
                ptype = m.get('type', 'unknown')
                tech = m.get('technique', '')
                if not payload or len(payload) < 2:
                    continue
                if is_blacklisted(payload):
                    self.log(f'  [BLACKLIST] skip: {payload[:40]}')
                    continue

                _, passed_wafs = test_all_wafs(payload)
                score = len(passed_wafs)

                if score > 0:
                    gen_bypasses.append((score, payload, ptype))
                    total_bypasses += 1
                    self.log(f'  [BYPASS {score}/{len(WAF_PROFILES)}] [{ptype}] {tech[:30]}: {payload[:50]}')
                    self.log(f'           WAFs: {passed_wafs}')
                    save_bypass(payload, ptype, tech, passed_wafs, score, generation, self.name)
                else:
                    self.log(f'  [BLOQUE] [{ptype}] {payload[:55]}')
                    record_blocked(payload)

            if not gen_bypasses:
                stagnation += 1
                self.log(f'  [STAGNATION {stagnation}/3] Aucun bypass ce cycle')
            else:
                stagnation = 0
                cat_index += 1

            total_db, total_bypass_db, blacklisted = get_db_stats()
            self.log(f'\n  --- GEN {generation} [{category}] ---')
            self.log(f'  Bypasses: {len(gen_bypasses)}/{len(mutations)} | Total: {total_bypasses}')
            self.log(f'  DB: {total_db} payloads | {total_bypass_db} bypasses | {blacklisted} blacklistes')
            if gen_bypasses:
                best = sorted(gen_bypasses, reverse=True)[0]
                self.log(f'  Best: {best[0]}/{len(WAF_PROFILES)} [{best[2]}] {best[1][:50]}')
            self.log(f'  Prochain cycle: {self.interval}s...')
            time.sleep(self.interval)


# â”€â”€ Point d'entrÃ©e â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def evolve_forever_v2(interval_seconds=60):
    init_db()

    workers = [
        EvolutionWorker('A', WORKER_A_CATEGORIES, interval=interval_seconds),
        EvolutionWorker('B', WORKER_B_CATEGORIES, interval=interval_seconds),
        EvolutionWorker('C', WORKER_C_CATEGORIES, interval=interval_seconds),
    ]

    print(f'[{datetime.now().strftime("%H:%M:%S")}] === CYBERIA EVOLUTION V2 â€” 3 WORKERS PARALLELES ===')
    print(f'  Worker A: {WORKER_A_CATEGORIES}')
    print(f'  Worker B: {WORKER_B_CATEGORIES}')
    print(f'  Worker C: {WORKER_C_CATEGORIES}')
    print(f'  WAFs: {len(WAF_PROFILES)} | Cycle: {interval_seconds}s | DB: {DB}')
    print('=' * 60)

    threads = []
    for worker in workers:
        t = threading.Thread(target=worker.run, name=f'EvoWorker-{worker.name}', daemon=True)
        t.start()
        threads.append(t)
        time.sleep(2)  # decale le demarrage pour eviter les conflits DB initiaux

    for t in threads:
        t.join()


if __name__ == '__main__':
    evolve_forever_v2(interval_seconds=60)


