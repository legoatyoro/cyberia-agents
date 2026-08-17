import sys, json, re, time, sqlite3, threading
from pathlib import Path
from datetime import datetime

# Garantit que le dossier racine du projet est dans sys.path quel que soit
# le répertoire depuis lequel le script est lancé
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DB = Path('.cyberia/research_crew.db')

def init_db():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS discoveries (
        id INTEGER PRIMARY KEY, agent TEXT, category TEXT,
        content TEXT, injected INTEGER DEFAULT 0, created_at TEXT
    )''')
    conn.commit()
    conn.close()

def save_discovery(agent, category, content):
    init_db()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO discoveries (agent,category,content,created_at) VALUES (?,?,?,?)',
        (agent, category, content[:2000], datetime.now().isoformat()))
    conn.commit()
    conn.close()

def inject_to_cyberia(content, source):
    try:
        from tools.filter_inject_domain import filter_and_inject
        return filter_and_inject(content, domain='securite', source_name=source, verbose=False)
    except Exception:
        return 0

def call_llm(prompt, agent_type='AgentRecherche'):
    try:
        from core.multi_model_router_v2 import router_v2
        agents = [agent_type, 'AgentCode', 'AgentRecherche']
        # deduplicate while preserving order
        seen = set()
        agents = [a for a in agents if not (a in seen or seen.add(a))]
        for agent in agents:
            try:
                info = router_v2.get_model_for_agent(agent)
                completion = info['client'].chat.completions.create(
                    model=info['model'],
                    messages=[{'role': 'user', 'content': prompt}],
                    max_tokens=1500)
                return completion.choices[0].message.content, info['provider']
            except Exception as e:
                err = str(e)[:80]
                if '429' in err or 'rate' in err.lower():
                    log(f'  [call_llm] {agent} rate limit — rotation...')
                    time.sleep(3)
                else:
                    log(f'  [call_llm] {agent} erreur: {err}')
    except Exception as e:
        log(f'  [call_llm] import/router erreur: {str(e)[:80]}')
    return None, None

LOG = Path('.cyberia/research_crew.log')

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'), flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line + '\n')

class AgentPromptFinder:
    name = 'AgentPromptFinder'

    def run(self, cycle):
        topics = [
            'OWASP Top 10 2024 detection techniques and payloads',
            'SQL injection blind boolean time-based detection prompts',
            'XSS stored reflected DOM detection algorithms',
            'SSRF detection patterns server-side request forgery',
            'Authentication bypass techniques JWT weak secrets',
            'API security testing GraphQL injection NoSQL injection',
            'Business logic vulnerabilities IDOR detection',
            'File upload vulnerabilities bypass techniques',
            'XXE injection XML external entity detection',
            'SSTI server side template injection detection Jinja2 Twig',
        ]
        topic = topics[cycle % len(topics)]
        prompt = f'''You are a cybersecurity research assistant.
Generate 10 specific, technical security testing prompts for: {topic}
Focus on: detection patterns, test payloads (safe for research), OWASP mapping, remediation.
Format as JSON: {{"prompts":[{{"topic":"...","prompt":"...","owasp":"A0X:2021","category":"..."}}]}}'''
        response, provider = call_llm(prompt, 'AgentRecherche')
        if not response:
            return 0
        log(f'  [PromptFinder] {provider} → topic: {topic[:40]}')
        log(f'  [PromptFinder] reponse brute: {str(response)[:150]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                log(f'  [PromptFinder] JSON non parseable — raw response')
                return 0
            log(f'  [PromptFinder] cles JSON: {list(data.keys())[:6]}')
            # Cherche la liste de prompts quelle que soit la cle
            prompts = data.get('prompts') or data.get('security_prompts') or data.get('testing_prompts') or []
            if not prompts:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        prompts = v
                        break
            # LLM returned a flat single object instead of a list
            if not prompts and 'prompt' in data:
                prompts = [data]
            text = '\n\n'.join(
                f'Security testing prompt [{p["category"]}] OWASP:{p["owasp"]}\n{p["prompt"]}'
                for p in prompts
            )
            save_discovery(self.name, 'prompt', text)
            injected = inject_to_cyberia(text, 'research_prompts')
            log(f'  [PromptFinder] {len(prompts)} prompts → {injected} injectes')
            return len(prompts)
        except Exception as e:
            log(f'  [PromptFinder] erreur: {e}')
        return 0


class AgentAlgorithmDesigner:
    name = 'AgentAlgorithmDesigner'

    def run(self, cycle):
        algorithms = [
            'payload mutation algorithm for WAF bypass using genetic encoding',
            'SQL injection detection scoring algorithm with confidence level',
            'XSS context-aware detection algorithm for HTML JS CSS',
            'fuzzing algorithm for API endpoint parameter discovery',
            'authentication bypass detection using response analysis',
            'blind injection detection using time-based boolean methods',
        ]
        algo = algorithms[cycle % len(algorithms)]
        prompt = f'''You are a security algorithm designer.
Design a detailed algorithm for: {algo}
Include: pseudocode, complexity analysis, detection accuracy, false positive rate.
Format as JSON: {{"algorithm":{{"name":"...","steps":["..."],"complexity":"...","accuracy":"...","description":"..."}}}}'''
        response, provider = call_llm(prompt, 'AgentCode')
        if not response:
            return 0
        log(f'  [AlgoDesigner] {provider} → algo: {algo[:40]}')
        log(f'  [AlgoDesigner] reponse brute: {str(response)[:150]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                # Fallback : extraire le texte brut de la reponse (sans code fences)
                log(f'  [AlgoDesigner] JSON invalide — fallback texte brut')
                raw_text = re.sub(r'```\w*', '', response).strip()
                if len(raw_text) > 80:
                    save_discovery(self.name, 'algorithm', raw_text[:2000])
                    injected = inject_to_cyberia(raw_text[:2000], 'research_algorithms')
                    log(f'  [AlgoDesigner] fallback texte → {injected} injectes')
                    return 1 if injected > 0 else 0
                return 0
            log(f'  [AlgoDesigner] cles JSON: {list(data.keys())[:6]}')
            algo_data = data.get('algorithm') or data.get('algorithm_design') or data.get('security_algorithm') or {}
            if not algo_data:
                for v in data.values():
                    if isinstance(v, dict) and ('steps' in v or 'name' in v):
                        algo_data = v
                        break
            name = algo_data.get("name", "unnamed")
            desc = algo_data.get("description", "")
            steps = algo_data.get('steps', [])
            text = f'Security algorithm: {name}\n{desc}\n\n'
            text += '\n\n'.join(f'Step: {s}' for s in steps)
            text += f'\n\nAccuracy: {algo_data.get("accuracy", "")} | Complexity: {algo_data.get("complexity", "")}'
            save_discovery(self.name, 'algorithm', text)
            injected = inject_to_cyberia(text, 'research_algorithms')
            log(f'  [AlgoDesigner] algo genere → {injected} injectes')
            return 1
        except Exception as e:
            log(f'  [AlgoDesigner] erreur: {e}')
        return 0


class AgentConversation:
    name = 'AgentConversation'

    def run(self, previous_discoveries):
        if not previous_discoveries:
            return 0
        recent = previous_discoveries[:3]
        context = '\n'.join(f'- {d[1]}: {d[2][:150]}' for d in recent)
        prompt = f'''You are AgentSecurity discussing with AgentResearch about cybersecurity findings.
Recent discoveries:
{context}
Generate a technical discussion between two security agents analyzing these findings.
Extract 5 actionable insights for improving a vulnerability scanner.
Format as JSON: {{"discussion":[{{"agent":"AgentSecurity|AgentResearch","message":"..."}}],"insights":["..."]}}'''
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [Conversation] {provider} → synthese de {len(recent)} decouvertes')
        log(f'  [Conversation] reponse brute: {str(response)[:150]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                log(f'  [Conversation] JSON non parseable')
                return 0
            log(f'  [Conversation] cles JSON: {list(data.keys())[:6]}')
            insights = data.get('insights') or data.get('actionable_insights') or data.get('key_insights') or []
            if not insights:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], str):
                        insights = v
                        break
            discussion = data.get('discussion') or data.get('conversation') or data.get('dialogue') or []
            text = 'Agent security research conversation about vulnerability scanning:\n\n'
            text += '\n\n'.join(f'{m["agent"]}: {m["message"]}' for m in discussion[:5])
            text += '\n\nSecurity insights: ' + '\n\n'.join(insights)
            save_discovery(self.name, 'conversation', text)
            injected = inject_to_cyberia(text, 'agent_conversations')
            log(f'  [Conversation] {len(insights)} insights → {injected} injectes')
            return len(insights)
        except Exception as e:
            log(f'  [Conversation] erreur: {e}')
        return 0


class AgentCVEWatcher:
    name = 'AgentCVEWatcher'

    def run(self, cycle):
        cve_topics = [
            'recent critical CVE web application vulnerabilities 2024 2025',
            'OWASP Top 10 A01 Broken Access Control detection methods',
            'JWT token vulnerabilities alg none weak secrets detection',
            'GraphQL security vulnerabilities introspection injection',
            'OAuth2 PKCE vulnerabilities redirect URI bypass',
        ]
        topic = cve_topics[cycle % len(cve_topics)]
        prompt = f'''Security researcher analyzing: {topic}
Provide technical details about vulnerability patterns, detection indicators, and safe test cases.
Format as JSON: {{"vulnerabilities":[{{"cve_type":"...","detection_pattern":"...","test_indicator":"...","owasp":"...","severity":"critical|high|medium"}}]}}'''
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [CVEWatcher] {provider} → {topic[:40]}')
        log(f'  [CVEWatcher] reponse brute: {str(response)[:150]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                log(f'  [CVEWatcher] JSON non parseable')
                return 0
            log(f'  [CVEWatcher] cles JSON: {list(data.keys())[:6]}')
            vulns = data.get('vulnerabilities') or data.get('vulnerability_patterns') or data.get('cve_patterns') or []
            if not vulns:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        vulns = v
                        break
            # LLM returned a flat single object instead of a list
            if not vulns and 'cve_type' in data:
                vulns = [data]
            text = '\n\n'.join(
                f'CVE vulnerability [{v["owasp"]}] severity:{v["severity"]} type:{v["cve_type"]}\n'
                f'Detection pattern: {v["detection_pattern"]}\n'
                f'Test indicator: {v.get("test_indicator", "")}'
                for v in vulns
            )
            save_discovery(self.name, 'cve_pattern', text)
            injected = inject_to_cyberia(text, 'cve_patterns')
            log(f'  [CVEWatcher] {len(vulns)} patterns → {injected} injectes')
            return len(vulns)
        except Exception as e:
            log(f'  [CVEWatcher] erreur: {e}')
        return 0


def run_research_crew(cycle_seconds=180):
    init_db()
    agents = [
        AgentPromptFinder(),
        AgentAlgorithmDesigner(),
        AgentCVEWatcher(),
    ]
    conversation_agent = AgentConversation()
    cycle = 0
    total_injected = 0

    log('=== RESEARCH CREW — AGENTS DE RECHERCHE AUTONOMES ===')
    log(f'Agents: {[a.name for a in agents]}')
    log(f'Cycle: {cycle_seconds}s')
    log('=' * 55)

    while True:
        cycle += 1
        log(f'\n[CYCLE {cycle}] {datetime.now().strftime("%H:%M")}')

        cycle_total = 0
        for agent in agents:
            try:
                result = agent.run(cycle)
                cycle_total += result
                time.sleep(5)
            except Exception as e:
                log(f'  [{agent.name}] crash: {e}')

        conn = sqlite3.connect(DB)
        recent = conn.execute(
            'SELECT agent, category, content FROM discoveries ORDER BY id DESC LIMIT 5'
        ).fetchall()
        conn.close()

        try:
            conv_result = conversation_agent.run(recent)
            cycle_total += conv_result
        except Exception as e:
            log(f'  [Conversation] crash: {e}')

        total_injected += cycle_total
        conn = sqlite3.connect(DB)
        total_disc = conn.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0]
        conn.close()

        log(f'\n  [CYCLE {cycle}] +{cycle_total} elements | Total: {total_disc} decouvertes | Injectes total: {total_injected}')
        log(f'  Prochain cycle: {cycle_seconds}s')
        time.sleep(cycle_seconds)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--cycle', type=int, default=180)
    args = p.parse_args()
    run_research_crew(args.cycle)
