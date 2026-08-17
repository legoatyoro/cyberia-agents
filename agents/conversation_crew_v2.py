import sys, re, time, sqlite3
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LOG = Path('.cyberia/conversation_crew_v2.log')
DB = Path('.cyberia/research_crew_v2.db')
MEMORY_DB = Path('.cyberia/memory_hub.db')


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


def call_llm(prompt, agent='AgentRecherche'):
    from core.multi_model_router_v2 import router_v2
    for ag in [agent, 'AgentCode', 'AgentRecherche']:
        try:
            info = router_v2.get_model_for_agent(ag)
            r = info['client'].chat.completions.create(
                model=info['model'],
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=1200)
            return r.choices[0].message.content, info['provider']
        except Exception as e:
            if '429' in str(e):
                time.sleep(5)
                continue
            log(f'  [call_llm] {ag} erreur: {str(e)[:60]}')
            continue
    return None, None


def inject(text, source):
    injected = 0
    try:
        from tools.filter_inject_domain import filter_and_inject
        injected = filter_and_inject(text, domain='securite', source_name=source, verbose=False)
    except Exception:
        pass
    try:
        MEMORY_DB.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(MEMORY_DB, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY, source TEXT, category TEXT,
            content TEXT, created_at TEXT
        )''')
        conn.execute(
            'INSERT INTO memories (source,category,content,created_at) VALUES (?,?,?,?)',
            (source, 'securite', text[:2000], datetime.now().isoformat()))
        conn.commit()
        conn.close()
        injected += 1
    except Exception:
        pass
    return injected


# ── Personas des 8 agents débatteurs ──────────────────────────────────────

AGENT_PERSONAS_V2 = [
    ('AgentRedTeam',       'expert en penetration testing offensif, techniques d\'attaque avancees et exploitation'),
    ('AgentBlueTeam',      'expert en detection de menaces, reponse aux incidents et hardening defensif'),
    ('AgentOWASP',         'expert OWASP Top 10, securite applicative et audits de code source'),
    ('AgentPentester',     'expert en tests d\'intrusion manuels, reconnaissance et exploitation step-by-step'),
    ('AgentMalwareAnalyst','expert en analyse de malware, reverse engineering et sandbox behavioral analysis'),
    ('AgentSOC',           'expert SOC, SIEM, correlation d\'alertes et threat hunting operationnel'),
    ('AgentThreatIntel',   'expert en threat intelligence, APT tracking et IoC/TTPs attribution'),
    ('AgentZeroDay',       'chercheur en vulnerabilites 0-day, fuzzing avance et exploit development'),
]

DEBATE_TOPICS_V2 = [
    'Comment detecter une injection SQL blind time-based dans un trafic HTTPS chiffre sans proxy ?',
    'Quelle est la difference entre un bypass WAF par encodage unicode et un bypass par normalisation HTTP ?',
    'Comment identifier un webshell camouffle dans les logs Apache vs Nginx vs IIS ?',
    'Quelles sont les signatures reseau d\'une attaque SSRF vers les metadonnees AWS EC2 ?',
    'Comment detecter un XSS DOM-based dans une SPA React/Vue sans acces au code source ?',
    'Quelles TTPs MITRE ATT&CK sont les plus utilisees dans les campagnes de ransomware web 2024 ?',
    'Comment distinguer un scan de vulnerabilites automatise d\'une attaque manuelle dans les logs ?',
    'Quelles methodes d\'obfuscation de malware contournent les EDR modernes en 2024 ?',
    'Comment detecter une chaine RCE via deserialisation Java dans les logs applicatifs ?',
    'Quels indicateurs revelent un mouvement lateral post-exploitation dans un environnement cloud ?',
    'Comment un attaquant peut-il abuser des webhooks pour un SSRF persistant ?',
    'Quelles contre-mesures neutralisent les attaques de type HTTP request smuggling ?',
]


class AgentDebaterV2:
    def run(self, cycle):
        topic = DEBATE_TOPICS_V2[cycle % len(DEBATE_TOPICS_V2)]
        # Rotation des 4 agents participants a chaque cycle
        start = (cycle * 2) % len(AGENT_PERSONAS_V2)
        participants = [
            AGENT_PERSONAS_V2[(start + i) % len(AGENT_PERSONAS_V2)]
            for i in range(4)
        ]
        conversation = []
        log(f'  [DebateV2] Topic: {topic[:60]}')
        log(f'  [DebateV2] Agents: {[p[0] for p in participants]}')

        for name, role in participants:
            context = '\n'.join(
                f'{c["agent"]}: {c["msg"][:100]}' for c in conversation[-2:]
            )
            prompt = (
                f'Tu es {name}, {role}.\n'
                f'Sujet du debat cybersecurite: {topic}\n'
                f'Conversation precedente:\n{context}\n'
                'Donne ta perspective technique experte en 3-4 phrases precises.\n'
                'Cite des outils, signatures, patterns ou TTPs concrets.\n'
                'Sois direct, sans introduction.'
            )
            response, provider = call_llm(prompt, 'AgentRecherche')
            if response:
                conversation.append({'agent': name, 'msg': response[:400]})
                log(f'    [{name}] {provider}: {response[:80]}')
            time.sleep(4)

        if not conversation:
            return 0

        debate_lines = '\n'.join(f'{c["agent"]}: {c["msg"]}' for c in conversation)
        synthesis_prompt = (
            'Tu es AgentSyntheseV2, expert cybersecurite de haut niveau.\n'
            f'Voici un debat d\'experts sur: {topic}\n'
            f'{debate_lines}\n\n'
            'Genere 6 prompts de detection ultra-precis utilisables dans un scanner de vulnerabilites.\n'
            'Chaque prompt doit inclure un pattern de detection, un indicateur WAF, et le mapping MITRE.\n'
            'Format JSON: {"prompts":['
            '{"prompt":"...","detection_pattern":"...","mitre_id":"T1XXX","owasp":"A0X:2021",'
            '"false_positive_rate":"low|medium","waf_rule_hint":"..."}'
            '],"synthesis":"..."}'
        )
        synthesis, _ = call_llm(synthesis_prompt, 'AgentSecurite')
        prompts = []
        synthesis_text = ''
        if synthesis:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(synthesis)
            log(f'  [DebateV2] synthese raw={data.get("raw",False)} cles={list(data.keys())[:8]}')
            if isinstance(data, dict) and not data.get('raw'):
                synthesis_text = data.get('synthesis', '')
                prompts = data.get('prompts') or data.get('detection_prompts') or []
                if not prompts:
                    for v in data.values():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            prompts = v; break
                if not prompts and 'prompt' in data:
                    prompts = [data]
                if not prompts:
                    for v in data.values():
                        if isinstance(v, list) and v and isinstance(v[0], str):
                            prompts = [{'prompt': s} for s in v]; break
            elif data.get('raw') and synthesis:
                clean = re.sub(r'```\w*|```', '', synthesis).strip()
                if len(clean) > 80:
                    prompts = [{'prompt': clean[:600]}]

        text = f'Debat cybersecurite avance — {topic}:\n\n'
        text += '\n\n'.join(f'{c["agent"]}: {c["msg"]}' for c in conversation)
        if synthesis_text:
            text += f'\n\nSynthese: {synthesis_text}'
        if prompts:
            text += '\n\nPrompts detection:\n\n' + '\n\n'.join(
                f'[{p.get("mitre_id","?")} / {p.get("owasp","?")}] fp:{p.get("false_positive_rate","?")}\n'
                f'{p.get("prompt","")}'
                for p in prompts
            )
        injected = inject(text, 'v2_agent_debate')
        log(f'  [DebateV2] {len(conversation)} agents | {len(prompts)} prompts | {injected} injectes')
        return injected or len(conversation)


class AgentRedTeamVsBlueTeam:
    """Scénario structuré RedTeam attaque / BlueTeam contre."""

    SCENARIOS = [
        ('Attaque par injection SSTI Jinja2 sur endpoint Flask', 'Detection SSTI via logs applicatifs'),
        ('Bypass authentification JWT alg:none', 'Detection JWT manipulation via SIEM'),
        ('Exfiltration DNS covert channel post-exploitation', 'Detection DNS tunneling via NetFlow'),
        ('Upload webshell via bypass MIME type validation', 'Detection webshell via file integrity monitoring'),
        ('SSRF vers metadonnees cloud via redirect chain', 'Detection SSRF via proxy logs et egress filtering'),
        ('RCE via deserialisation PHP object injection', 'Detection deserialisation attack via WAF rules'),
    ]

    def run(self, cycle):
        attack_scenario, defense_scenario = self.SCENARIOS[cycle % len(self.SCENARIOS)]
        log(f'  [RT-vs-BT] Attaque: {attack_scenario[:50]}')

        red_prompt = (
            'Tu es AgentRedTeam, expert en attaque offensive.\n'
            f'Scenario: {attack_scenario}\n'
            'Decris la chaine d\'exploitation complete: reconnaissance, exploitation, persistance.\n'
            'Liste les outils, commandes, et payloads utilises. Sois tres technique.\n'
            'Format JSON: {"attack":{"steps":["..."],"tools":["..."],"payloads":["..."],"ttps":["..."]}}'
        )
        red_resp, red_prov = call_llm(red_prompt, 'AgentSecurite')
        time.sleep(3)

        blue_prompt = (
            'Tu es AgentBlueTeam, expert en detection et reponse.\n'
            f'Contre-scenario: {defense_scenario}\n'
            f'L\'attaque a utilisee: {attack_scenario}\n'
            'Decris les signatures de detection, les regles SIEM, les IOCs, et les contre-mesures.\n'
            'Format JSON: {"defense":{"detection_rules":["..."],"iocs":["..."],"siem_queries":["..."],"mitigations":["..."]}}'
        )
        blue_resp, blue_prov = call_llm(blue_prompt, 'AgentSecurite')
        time.sleep(3)

        from core.json_parser import safe_json_parse

        attack_data = {}
        defense_data = {}
        if red_resp:
            d = safe_json_parse(red_resp)
            attack_data = d.get('attack', {}) if not d.get('raw') else {}
        if blue_resp:
            d = safe_json_parse(blue_resp)
            defense_data = d.get('defense', {}) if not d.get('raw') else {}

        text = f'RedTeam vs BlueTeam — {attack_scenario}:\n\n'
        text += '=== ATTAQUE (RedTeam) ===\n'
        text += 'Steps: ' + '\n'.join(attack_data.get('steps', [attack_scenario])) + '\n'
        text += 'Tools: ' + ', '.join(attack_data.get('tools', [])) + '\n'
        text += 'TTPs: ' + ', '.join(attack_data.get('ttps', [])) + '\n\n'
        text += '=== DEFENSE (BlueTeam) ===\n'
        text += 'Detection rules: ' + '\n'.join(defense_data.get('detection_rules', [])) + '\n'
        text += 'IOCs: ' + '\n'.join(defense_data.get('iocs', [])) + '\n'
        text += 'SIEM queries: ' + '\n'.join(defense_data.get('siem_queries', [])) + '\n'

        injected = inject(text, 'v2_rt_vs_bt')
        log(f'  [RT-vs-BT] {red_prov}/{blue_prov} | attack:{bool(attack_data)} defense:{bool(defense_data)} | {injected} injectes')
        return injected or 1


class AgentThreatIntelSynthesis:
    """Synthétise la threat intelligence et alimente la mémoire."""

    INTEL_TOPICS = [
        'APT groups targeting web applications 2024 2025 TTPs',
        'ransomware groups initial access via web vulnerabilities 2024',
        'supply chain attacks npm pip packages malicious 2024 2025',
        'phishing campaigns targeting developers credential harvesting',
        'cryptojacking campaigns via web vulnerabilities cloud 2024',
        'state-sponsored threat actors web exploitation techniques 2025',
    ]

    def run(self, cycle):
        topic = self.INTEL_TOPICS[cycle % len(self.INTEL_TOPICS)]
        prompt = (
            f'Tu es AgentThreatIntel, expert en renseignement sur les menaces.\n'
            f'Sujet: {topic}\n'
            'Fournis une analyse de threat intelligence structuree:\n'
            '- Acteurs de menace identifies (APT groups, threat actors)\n'
            '- TTPs principales (MITRE ATT&CK)\n'
            '- IOCs types (hash patterns, network indicators)\n'
            '- Vulnerabilites exploitees preferentiellement\n'
            '- Recommandations de detection\n'
            'Format JSON: {"threat_intel":{'
            '"actors":["..."],"ttps":["T1XXX:..."],"ioc_patterns":["..."],'
            '"exploited_vulns":["CVE-..."],"detection_recommendations":["..."]}}'
        )
        response, provider = call_llm(prompt, 'AgentRecherche')
        if not response:
            return 0
        log(f'  [ThreatIntel] {provider} → {topic[:45]}')
        try:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(response)
            if data.get('raw'):
                return 0
            intel = data.get('threat_intel') or data.get('intelligence') or {}
            if not intel:
                for v in data.values():
                    if isinstance(v, dict) and ('actors' in v or 'ttps' in v):
                        intel = v; break
            if not intel:
                return 0
            ttps = intel.get('ttps', [])
            text = f'Threat Intelligence — {topic}:\n\n'
            text += f'Acteurs: {", ".join(intel.get("actors",[]))}\n\n'
            text += 'TTPs:\n' + '\n'.join(f'  - {t}' for t in ttps) + '\n\n'
            text += 'IOC Patterns:\n' + '\n'.join(f'  - {i}' for i in intel.get('ioc_patterns', [])) + '\n\n'
            text += 'Vulns exploitees: ' + ', '.join(intel.get('exploited_vulns', [])) + '\n\n'
            text += 'Detection:\n' + '\n'.join(f'  - {r}' for r in intel.get('detection_recommendations', []))
            injected = inject(text, 'v2_threat_intel')
            log(f'  [ThreatIntel] {len(ttps)} TTPs | {injected} injectes')
            return max(len(ttps), 1)
        except Exception as e:
            log(f'  [ThreatIntel] erreur: {e}')
        return 0


def run_conversation_crew_v2(cycle_seconds=200):
    agents = [AgentDebaterV2(), AgentRedTeamVsBlueTeam(), AgentThreatIntelSynthesis()]
    cycle = 0
    total = 0

    log('=== CONVERSATION CREW V2 — 8 AGENTS DEBATTEURS CYBERSECURITE ===')
    log(f'Agents debatteurs: {[p[0] for p in AGENT_PERSONAS_V2]}')
    log(f'Topics: {len(DEBATE_TOPICS_V2)} | Cycle: {cycle_seconds}s')
    log(f'DB: {DB} | Memory: {MEMORY_DB}')
    log('=' * 65)

    while True:
        cycle += 1
        log(f'\n[CYCLE {cycle}] {datetime.now().strftime("%H:%M")}')
        cycle_total = 0
        for agent in agents:
            try:
                result = agent.run(cycle)
                cycle_total += result
                time.sleep(8)
            except Exception as e:
                log(f'  [{agent.__class__.__name__}] crash: {e}')
        total += cycle_total
        log(f'\n  [CYCLE {cycle}] +{cycle_total} | Total: {total} injectes dans CYBERIA')
        log(f'  Prochain: {cycle_seconds}s')
        time.sleep(cycle_seconds)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--cycle', type=int, default=200)
    args = p.parse_args()
    run_conversation_crew_v2(args.cycle)
