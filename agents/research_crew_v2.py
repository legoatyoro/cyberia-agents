import sys, re, time, sqlite3, threading
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DB = Path('.cyberia/research_crew_v2.db')
MEMORY_DB = Path('.cyberia/memory_hub.db')
LOG = Path('.cyberia/research_crew_v2.log')

_db_lock = threading.Lock()


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
    with _db_lock:
        conn = sqlite3.connect(DB, timeout=10)
        conn.execute(
            'INSERT INTO discoveries (agent,category,content,created_at) VALUES (?,?,?,?)',
            (agent, category, content[:2000], datetime.now().isoformat()))
        conn.commit()
        conn.close()


def _inject_memory_hub(content, source, category='securite'):
    try:
        MEMORY_DB.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(MEMORY_DB, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY, source TEXT, category TEXT,
            content TEXT, created_at TEXT
        )''')
        conn.execute(
            'INSERT INTO memories (source,category,content,created_at) VALUES (?,?,?,?)',
            (source, category, content[:2000], datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return 1
    except Exception:
        return 0


def inject_to_memory(content, source):
    injected = 0
    try:
        from tools.filter_inject_domain import filter_and_inject
        injected = filter_and_inject(content, domain='securite', source_name=source, verbose=False)
    except Exception:
        pass
    injected += _inject_memory_hub(content, source)
    try:
        from tools.memory_hub_v3 import add_pattern
        add_pattern({'type': 'research_discovery', 'content': content[:500], 'source': source})
    except Exception:
        pass
    return injected


def call_llm(prompt, agent_type='AgentRecherche'):
    try:
        from core.multi_model_router_v2 import router_v2
        agents = [agent_type, 'AgentCode', 'AgentRecherche']
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


# ── Agents existants (repris de research_crew.py) ──────────────────────────

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
        prompt = (
            f'You are a cybersecurity research assistant.\n'
            f'Generate 10 specific, technical security testing prompts for: {topic}\n'
            'Focus on: detection patterns, test payloads (safe for research), OWASP mapping, remediation.\n'
            'Format as JSON: {"prompts":[{"topic":"...","prompt":"...","owasp":"A0X:2021","category":"..."}]}'
        )
        response, provider = call_llm(prompt, 'AgentRecherche')
        if not response:
            return 0
        log(f'  [PromptFinder] {provider} → topic: {topic[:40]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            prompts = data.get('prompts') or data.get('security_prompts') or []
            if not prompts:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        prompts = v; break
            if not prompts and 'prompt' in data:
                prompts = [data]
            text = '\n\n'.join(
                f'Security testing prompt [{p.get("category","")}] OWASP:{p.get("owasp","")}\n{p.get("prompt","")}'
                for p in prompts
            )
            save_discovery(self.name, 'prompt', text)
            injected = inject_to_memory(text, 'v2_research_prompts')
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
        prompt = (
            f'You are a security algorithm designer.\n'
            f'Design a detailed algorithm for: {algo}\n'
            'Include: pseudocode, complexity analysis, detection accuracy, false positive rate.\n'
            'Format as JSON: {"algorithm":{"name":"...","steps":["..."],"complexity":"...","accuracy":"...","description":"..."}}'
        )
        response, provider = call_llm(prompt, 'AgentCode')
        if not response:
            return 0
        log(f'  [AlgoDesigner] {provider} → algo: {algo[:40]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                raw_text = re.sub(r'```\w*', '', response).strip()
                if len(raw_text) > 80:
                    save_discovery(self.name, 'algorithm', raw_text[:2000])
                    injected = inject_to_memory(raw_text[:2000], 'v2_research_algorithms')
                    log(f'  [AlgoDesigner] fallback texte → {injected} injectes')
                    return 1 if injected > 0 else 0
                return 0
            algo_data = data.get('algorithm') or data.get('algorithm_design') or {}
            if not algo_data:
                for v in data.values():
                    if isinstance(v, dict) and ('steps' in v or 'name' in v):
                        algo_data = v; break
            name = algo_data.get('name', 'unnamed')
            desc = algo_data.get('description', '')
            steps = algo_data.get('steps', [])
            text = f'Security algorithm: {name}\n{desc}\n\n'
            text += '\n'.join(f'Step: {s}' for s in steps)
            text += f'\n\nAccuracy: {algo_data.get("accuracy","")} | Complexity: {algo_data.get("complexity","")}'
            save_discovery(self.name, 'algorithm', text)
            injected = inject_to_memory(text, 'v2_research_algorithms')
            log(f'  [AlgoDesigner] algo genere → {injected} injectes')
            return 1
        except Exception as e:
            log(f'  [AlgoDesigner] erreur: {e}')
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
            'prototype pollution JavaScript CVE detection patterns',
            'HTTP request smuggling desync attack detection 2024',
        ]
        topic = cve_topics[cycle % len(cve_topics)]
        prompt = (
            f'Security researcher analyzing: {topic}\n'
            'Provide technical details about vulnerability patterns, detection indicators, and safe test cases.\n'
            'Format as JSON: {"vulnerabilities":[{"cve_type":"...","detection_pattern":"...","test_indicator":"...","owasp":"...","severity":"critical|high|medium"}]}'
        )
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [CVEWatcher] {provider} → {topic[:40]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            vulns = data.get('vulnerabilities') or data.get('vulnerability_patterns') or []
            if not vulns:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        vulns = v; break
            if not vulns and 'cve_type' in data:
                vulns = [data]
            text = '\n\n'.join(
                f'CVE [{v.get("owasp","?")}] severity:{v.get("severity","?")} type:{v.get("cve_type","")}\n'
                f'Detection: {v.get("detection_pattern","")}\nTest: {v.get("test_indicator","")}'
                for v in vulns
            )
            save_discovery(self.name, 'cve_pattern', text)
            injected = inject_to_memory(text, 'v2_cve_patterns')
            log(f'  [CVEWatcher] {len(vulns)} patterns → {injected} injectes')
            return len(vulns)
        except Exception as e:
            log(f'  [CVEWatcher] erreur: {e}')
        return 0


class AgentConversation:
    name = 'AgentConversation'

    def run(self, previous_discoveries):
        if not previous_discoveries:
            return 0
        recent = previous_discoveries[:3]
        context = '\n'.join(f'- {d[1]}: {d[2][:150]}' for d in recent)
        prompt = (
            'You are AgentSecurity discussing with AgentResearch about cybersecurity findings.\n'
            f'Recent discoveries:\n{context}\n'
            'Generate a technical discussion between two security agents analyzing these findings.\n'
            'Extract 5 actionable insights for improving a vulnerability scanner.\n'
            'Format as JSON: {"discussion":[{"agent":"AgentSecurity|AgentResearch","message":"..."}],"insights":["..."]}'
        )
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [Conversation] {provider} → synthese de {len(recent)} decouvertes')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            insights = data.get('insights') or data.get('actionable_insights') or []
            if not insights:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], str):
                        insights = v; break
            discussion = data.get('discussion') or data.get('conversation') or []
            text = 'Agent security research conversation:\n\n'
            text += '\n\n'.join(f'{m.get("agent","?")}: {m.get("message","")}' for m in discussion[:5])
            text += '\n\nSecurity insights: ' + '\n'.join(insights)
            save_discovery(self.name, 'conversation', text)
            injected = inject_to_memory(text, 'v2_agent_conversations')
            log(f'  [Conversation] {len(insights)} insights → {injected} injectes')
            return len(insights)
        except Exception as e:
            log(f'  [Conversation] erreur: {e}')
        return 0


# ── Nouveaux agents spécialisés ────────────────────────────────────────────

class AgentExploitDB:
    name = 'AgentExploitDB'

    TOPICS = [
        'remote code execution exploits web applications 2024 2025 public exploits',
        'SQL injection exploits CMS WordPress Joomla Drupal public exploits',
        'authentication bypass exploits CVE disclosed public 2024',
        'file upload RCE exploits PHP ASP JSP shell upload techniques',
        'XXE injection exploits Java Spring framework disclosed',
        'deserialization exploits Java PHP Python public gadget chains',
        'SSRF exploits cloud metadata AWS GCP Azure disclosed 2024',
        'path traversal LFI RFI exploits web servers Apache Nginx',
    ]

    def run(self, cycle):
        topic = self.TOPICS[cycle % len(self.TOPICS)]
        prompt = (
            f'You are a security researcher analyzing public exploit databases.\n'
            f'Topic: {topic}\n'
            'Analyze common exploit patterns, payloads structures, and detection signatures.\n'
            'Focus on: exploit technique, affected components, detection pattern, CVSS score.\n'
            'Format as JSON: {"exploits":['
            '{"name":"...","technique":"...","target":"...","payload_pattern":"...","detection":"...","cvss":"...","owasp":"..."}'
            ']}'
        )
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [ExploitDB] {provider} → {topic[:45]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                log(f'  [ExploitDB] JSON non parseable — raw')
                return 0
            exploits = data.get('exploits') or data.get('exploit_patterns') or []
            if not exploits:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        exploits = v; break
            if not exploits and 'technique' in data:
                exploits = [data]
            text = f'ExploitDB research — {topic}:\n\n'
            text += '\n\n'.join(
                f'Exploit: {e.get("name","?")} [{e.get("owasp","?")}] CVSS:{e.get("cvss","?")}\n'
                f'Target: {e.get("target","")}\nTechnique: {e.get("technique","")}\n'
                f'Payload pattern: {e.get("payload_pattern","")}\nDetection: {e.get("detection","")}'
                for e in exploits
            )
            save_discovery(self.name, 'exploit_pattern', text)
            injected = inject_to_memory(text, 'v2_exploitdb')
            log(f'  [ExploitDB] {len(exploits)} exploits → {injected} injectes')
            return len(exploits)
        except Exception as e:
            log(f'  [ExploitDB] erreur: {e}')
        return 0


class AgentMITRE:
    name = 'AgentMITRE'

    TECHNIQUES = [
        'T1190 Exploit Public-Facing Application web vulnerabilities techniques',
        'T1059 Command and Scripting Interpreter web shell techniques',
        'T1055 Process Injection techniques web application context',
        'T1083 File and Directory Discovery LFI techniques',
        'T1071 Application Layer Protocol C2 HTTP HTTPS techniques',
        'T1560 Archive Collected Data exfiltration web techniques',
        'T1110 Brute Force credential stuffing web authentication',
        'T1134 Access Token Manipulation JWT OAuth techniques',
        'T1203 Exploitation for Client Execution XSS CSRF techniques',
        'T1505 Server Software Component web shell persistence',
    ]

    def run(self, cycle):
        technique = self.TECHNIQUES[cycle % len(self.TECHNIQUES)]
        prompt = (
            f'You are a MITRE ATT&CK framework analyst.\n'
            f'Analyze technique: {technique}\n'
            'Provide: sub-techniques, detection methods, data sources, mitigation strategies.\n'
            'Focus on web application security context and detection signatures.\n'
            'Format as JSON: {"technique":{'
            '"id":"T1XXX","name":"...","sub_techniques":["..."],'
            '"detection_signatures":["..."],"data_sources":["..."],'
            '"mitigations":["..."],"payload_examples":["..."]}}'
        )
        response, provider = call_llm(prompt, 'AgentRecherche')
        if not response:
            return 0
        log(f'  [MITRE] {provider} → {technique[:45]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            tech = data.get('technique') or data.get('mitre_technique') or {}
            if not tech:
                for v in data.values():
                    if isinstance(v, dict) and ('id' in v or 'detection_signatures' in v):
                        tech = v; break
            if not tech:
                return 0
            sigs = tech.get('detection_signatures', [])
            text = (
                f'MITRE ATT&CK {tech.get("id","?")} — {tech.get("name","")}\n\n'
                f'Sub-techniques: {", ".join(tech.get("sub_techniques",[]))}\n\n'
                f'Detection signatures:\n' + '\n'.join(f'  - {s}' for s in sigs) + '\n\n'
                f'Data sources: {", ".join(tech.get("data_sources",[]))}\n\n'
                f'Mitigations:\n' + '\n'.join(f'  - {m}' for m in tech.get('mitigations', [])) + '\n\n'
                f'Payload examples:\n' + '\n'.join(f'  - {p}' for p in tech.get('payload_examples', []))
            )
            save_discovery(self.name, 'mitre_technique', text)
            injected = inject_to_memory(text, 'v2_mitre_attck')
            log(f'  [MITRE] {tech.get("id","?")} {len(sigs)} signatures → {injected} injectes')
            return max(len(sigs), 1)
        except Exception as e:
            log(f'  [MITRE] erreur: {e}')
        return 0


class AgentBugBounty:
    name = 'AgentBugBounty'

    PROGRAMS = [
        ('HackerOne', 'XSS stored reflected DOM bypass techniques disclosed writeups 2024'),
        ('Bugcrowd',  'SQL injection blind time-based bypass WAF writeups disclosed'),
        ('HackerOne', 'SSRF bypass cloud metadata access writeups disclosed 2024'),
        ('Bugcrowd',  'authentication bypass IDOR privilege escalation writeups'),
        ('HackerOne', 'RCE file upload bypass web shell writeups disclosed 2024'),
        ('Bugcrowd',  'XXE injection blind SSRF via XXE writeups disclosed'),
        ('HackerOne', 'CSRF token bypass techniques disclosed writeups 2024'),
        ('Bugcrowd',  'path traversal LFI RFI bypass encoding writeups 2024'),
    ]

    def run(self, cycle):
        platform, topic = self.PROGRAMS[cycle % len(self.PROGRAMS)]
        prompt = (
            f'You are a bug bounty researcher analyzing {platform} disclosed reports.\n'
            f'Topic: {topic}\n'
            'Synthesize the most effective techniques from bug bounty writeups.\n'
            'Include: bypass methodology, payload structure, WAF evasion used, severity, CVSS.\n'
            'Format as JSON: {"writeups":['
            '{"platform":"...","technique":"...","bypass_method":"...","payload_structure":"...","waf_evasion":"...","severity":"...","owasp":"..."}'
            ']}'
        )
        response, provider = call_llm(prompt, 'AgentRecherche')
        if not response:
            return 0
        log(f'  [BugBounty] {provider} → {platform}: {topic[:35]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            writeups = data.get('writeups') or data.get('reports') or data.get('bug_bounty_reports') or []
            if not writeups:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        writeups = v; break
            if not writeups and 'technique' in data:
                writeups = [data]
            text = f'Bug Bounty writeups — {platform} — {topic}:\n\n'
            text += '\n\n'.join(
                f'[{w.get("platform",platform)}] {w.get("severity","?")} {w.get("owasp","?")}\n'
                f'Technique: {w.get("technique","")}\n'
                f'Bypass: {w.get("bypass_method","")}\n'
                f'WAF evasion: {w.get("waf_evasion","")}\n'
                f'Payload structure: {w.get("payload_structure","")}'
                for w in writeups
            )
            save_discovery(self.name, 'bug_bounty_writeup', text)
            injected = inject_to_memory(text, 'v2_bug_bounty')
            log(f'  [BugBounty] {len(writeups)} writeups → {injected} injectes')
            return len(writeups)
        except Exception as e:
            log(f'  [BugBounty] erreur: {e}')
        return 0


class AgentWAFResearch:
    name = 'AgentWAFResearch'

    TOPICS = [
        'ModSecurity CRS bypass techniques unicode encoding 2024',
        'Cloudflare WAF bypass XSS techniques recent research 2024 2025',
        'AWS WAF bypass SQL injection techniques case mixing encoding',
        'Akamai WAF bypass payload obfuscation techniques recent',
        'WAF fingerprinting techniques detection evasion methods 2024',
        'HTTP parameter pollution WAF bypass techniques research',
        'JSON payload WAF bypass injection techniques REST API',
        'multipart form data WAF bypass file upload injection',
        'header injection WAF bypass techniques Host X-Forwarded-For',
        'chunked transfer encoding WAF bypass HTTP smuggling',
    ]

    def run(self, cycle):
        topic = self.TOPICS[cycle % len(self.TOPICS)]
        prompt = (
            f'You are a WAF security researcher.\n'
            f'Research topic: {topic}\n'
            'Analyze bypass techniques, encoding methods, and evasion patterns.\n'
            'Provide technical details usable to improve WAF detection rules.\n'
            'Format as JSON: {"bypass_techniques":['
            '{"waf":"...","category":"xss|sqli|lfi|ssti|rce","bypass_method":"...","encoding":"...","example_pattern":"...","detection_gap":"...","counter_rule":"..."}'
            ']}'
        )
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0
        log(f'  [WAFResearch] {provider} → {topic[:45]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            techniques = (
                data.get('bypass_techniques') or data.get('waf_bypass_techniques')
                or data.get('techniques') or []
            )
            if not techniques:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        techniques = v; break
            if not techniques and 'bypass_method' in data:
                techniques = [data]
            text = f'WAF Research — {topic}:\n\n'
            text += '\n\n'.join(
                f'WAF: {t.get("waf","?")} [{t.get("category","?")}]\n'
                f'Bypass: {t.get("bypass_method","")}\n'
                f'Encoding: {t.get("encoding","")}\n'
                f'Pattern: {t.get("example_pattern","")}\n'
                f'Gap: {t.get("detection_gap","")}\n'
                f'Counter-rule: {t.get("counter_rule","")}'
                for t in techniques
            )
            save_discovery(self.name, 'waf_bypass_research', text)
            injected = inject_to_memory(text, 'v2_waf_research')
            log(f'  [WAFResearch] {len(techniques)} techniques → {injected} injectes')
            return len(techniques)
        except Exception as e:
            log(f'  [WAFResearch] erreur: {e}')
        return 0


# ── Loop principal ─────────────────────────────────────────────────────────

def run_research_crew_v2(cycle_seconds=180):
    init_db()
    agents = [
        AgentPromptFinder(),
        AgentAlgorithmDesigner(),
        AgentCVEWatcher(),
        AgentExploitDB(),
        AgentMITRE(),
        AgentBugBounty(),
        AgentWAFResearch(),
    ]
    conversation_agent = AgentConversation()
    cycle = 0
    total_injected = 0

    log('=== RESEARCH CREW V2 — 8 AGENTS CHERCHEURS SPECIALISES ===')
    log(f'Agents: {[a.name for a in agents]} + {conversation_agent.name}')
    log(f'Cycle: {cycle_seconds}s | DB: {DB} | Memory: {MEMORY_DB}')
    log('=' * 60)

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

        conn = sqlite3.connect(DB, timeout=10)
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

        conn = sqlite3.connect(DB, timeout=10)
        total_disc = conn.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0]
        conn.close()

        try:
            mem_count = sqlite3.connect(MEMORY_DB, timeout=5).execute(
                'SELECT COUNT(*) FROM memories'
            ).fetchone()[0]
        except Exception:
            mem_count = '?'

        log(f'\n  [CYCLE {cycle}] +{cycle_total} | Decouvertes: {total_disc} | '
            f'Memoires: {mem_count} | Injectes total: {total_injected}')
        log(f'  Prochain cycle: {cycle_seconds}s')
        time.sleep(cycle_seconds)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--cycle', type=int, default=180)
    args = p.parse_args()
    run_research_crew_v2(args.cycle)
