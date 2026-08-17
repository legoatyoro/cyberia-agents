import threading, time, json, sqlite3, re
from pathlib import Path
from datetime import datetime

_running = False
_thread = None
_stats = {'generation': 0, 'total_bypasses': 0, 'started_at': None}


def get_stats():
    return _stats.copy()


def _evolution_loop(interval_minutes=5):
    global _stats
    from core.multi_model_router_v2 import router_v2
    from core.waf_simulator import get_all_waf_results

    DB = Path('.cyberia/payload_lab.db')
    generation = 0

    while _running:
        generation += 1
        _stats['generation'] = generation
        print(f'\n[EVOLUTION] Generation {generation} — {datetime.now().strftime("%H:%M")}')

        try:
            conn = sqlite3.connect(DB)
            parents = conn.execute(
                'SELECT payload, payload_type FROM imported_payloads ORDER BY RANDOM() LIMIT 10'
            ).fetchall()
            conn.close()

            if not parents:
                time.sleep(60)
                continue

            parent_str = '\n'.join(f'- [{t}] {p[:60]}' for p, t in parents)
            prompt = f'''Expert WAF bypass. Generation {generation}.
Parents: {parent_str}
Genere 10 mutations avec techniques d evasion avancees.
JSON: {{"mutations":[{{"payload":"...","type":"xss|sqli|lfi|ssti","technique":"..."}}]}}'''

            info = router_v2.get_model_for_agent('AgentSecurite')
            completion = info['client'].chat.completions.create(
                model=info['model'],
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=1000)

            response = completion.choices[0].message.content
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if not match:
                continue

            mutations = json.loads(match.group()).get('mutations', [])
            new_bypasses = 0
            conn = sqlite3.connect(DB)

            for m in mutations:
                payload = m.get('payload', '')
                ptype = m.get('type', 'unknown')
                if not payload or len(payload) < 2:
                    continue

                waf_results, passed_wafs = get_all_waf_results(payload)
                waf_score = len(passed_wafs) * 20

                if waf_score > 0:
                    try:
                        conn.execute(
                            'INSERT OR IGNORE INTO imported_payloads (payload,payload_type,source,imported_at) VALUES (?,?,?,datetime("now"))',
                            (payload, ptype, f'evolution_g{generation}'))
                        conn.execute(
                            'INSERT INTO results (payload,payload_type,target,status,score,tested_at,bypass_confirmed) VALUES (?,?,?,?,?,datetime("now"),1)',
                            (payload, ptype, ','.join(passed_wafs), 'BYPASS', waf_score))
                        new_bypasses += 1
                        _stats['total_bypasses'] += 1
                        print(f'  [G{generation}] BYPASS score={waf_score} [{ptype}] WAFs:{passed_wafs} | {payload[:50]}')
                    except Exception:
                        pass

            conn.commit()
            conn.close()
            print(f'  [G{generation}] {new_bypasses}/{len(mutations)} bypasses')

        except Exception as e:
            print(f'  [EVOLUTION] Erreur: {e}')

        for _ in range(interval_minutes * 60):
            if not _running:
                break
            time.sleep(1)


def start(interval_minutes=5):
    global _running, _thread, _stats
    if _running:
        return
    _running = True
    _stats['started_at'] = datetime.now().isoformat()
    _thread = threading.Thread(target=_evolution_loop, args=(interval_minutes,), daemon=True)
    _thread.start()
    print(f'[EVOLUTION] Boucle infinie demarree — cycle toutes les {interval_minutes} min')


def stop():
    global _running
    _running = False
    print('[EVOLUTION] Arretee')
