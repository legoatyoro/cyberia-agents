import sys, json, re, time, sqlite3
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LOG = Path('.cyberia/conversation_crew.log')
DB = Path('.cyberia/research_crew.db')


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
    try:
        from tools.filter_inject_domain import filter_and_inject
        return filter_and_inject(text, domain='securite', source_name=source, verbose=False)
    except Exception:
        return 0


AGENT_PERSONAS = [
    ('AgentRedTeam',   'expert en penetration testing et techniques offensives defensives'),
    ('AgentBlueTeam',  'expert en detection de menaces et reponse aux incidents'),
    ('AgentOWASP',     'expert OWASP Top 10 et securite applicative'),
    ('AgentCrypto',    'expert en cryptographie et securite des authentifications'),
    ('AgentCloud',     'expert securite cloud AWS Azure GCP et conteneurs'),
    ('AgentMalware',   'expert en analyse de malware et reverse engineering'),
    ('AgentForensic',  'expert en forensic numerique et investigation'),
    ('AgentCompliance','expert en conformite RGPD ISO27001 SOC2 PCI-DSS'),
]

DEBATE_TOPICS = [
    'Quelle est la meilleure methode pour detecter une injection SQL blind sans erreur visible ?',
    'Comment detecter un XSS stocke dans une API REST JSON ?',
    'Quelles sont les signatures dun SSRF dans les logs serveur ?',
    'Comment distinguer un vrai bypass WAF dun faux positif ?',
    'Quelles regles de detection couvrent les attaques Log4Shell variantes ?',
    'Comment detecter une elevation de privilege dans une API REST ?',
    'Quels sont les indicateurs dune attaque SSTI sur Jinja2 ?',
    'Comment detecter un scan de ports applicatif via les patterns de requetes ?',
    'Quelles sont les signatures dun clickjacking moderne ?',
    'Comment detecter une attaque de type cache poisoning ?',
]


class AgentDebater:
    def run(self, cycle):
        topic = DEBATE_TOPICS[cycle % len(DEBATE_TOPICS)]
        personas = AGENT_PERSONAS[:4]
        conversation = []
        log(f'  [Debate] Topic: {topic[:60]}')

        for name, role in personas:
            context = '\n'.join(
                f'{c["agent"]}: {c["msg"][:100]}' for c in conversation[-2:]
            )
            prompt = (
                f'Tu es {name}, {role}.\n'
                f'Sujet du debat: {topic}\n'
                f'Conversation precedente: {context}\n'
                'Donne ta perspective technique experte en 2-3 phrases precises.\n'
                'Apporte des elements concrets : patterns, signatures, outils, methodes.\n'
                'Reponds directement sans introduction.'
            )
            response, provider = call_llm(prompt, 'AgentRecherche')
            if response:
                conversation.append({'agent': name, 'msg': response[:300]})
                log(f'    [{name}] {response[:80]}')
            time.sleep(3)

        if not conversation:
            return 0

        debate_lines = '\n'.join(f'{c["agent"]}: {c["msg"]}' for c in conversation)
        synthesis_prompt = (
            'Tu es AgentSynthese expert cybersecurite.\n'
            f'Voici un debat entre experts sur: {topic}\n'
            f'{debate_lines}\n'
            'Genere 5 prompts de detection ultra-precis utilisables dans un scanner de vulnerabilites.\n'
            'Format JSON: {"prompts":[{"prompt":"...","detection_pattern":"...","owasp":"...","false_positive_rate":"low|medium"}]}'
        )
        synthesis, _ = call_llm(synthesis_prompt, 'AgentRecherche')
        prompts = []
        if synthesis:
            from core.json_parser import safe_json_parse
            data = safe_json_parse(synthesis)
            log(f'  [Debate] synthese raw={data.get("raw",False)} cles={list(data.keys())[:8]}')
            if isinstance(data, dict) and not data.get('raw'):
                prompts = data.get('prompts') or data.get('detection_prompts') or data.get('security_prompts') or []
                if not prompts:
                    for v in data.values():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            prompts = v
                            break
                if not prompts and 'prompt' in data:
                    prompts = [data]
                if not prompts:
                    for v in data.values():
                        if isinstance(v, list) and v and isinstance(v[0], str):
                            prompts = [{'prompt': s} for s in v]
                            break
            elif data.get('raw') and synthesis:
                # JSON totalement non parseable — utiliser le texte brut comme prompt
                clean = re.sub(r'```\w*|```', '', synthesis).strip()
                log(f'  [Debate] synthese brute (fallback): {clean[:100]}')
                if len(clean) > 80:
                    prompts = [{'prompt': clean[:600]}]

        text = f'Debate sur {topic}:\n\n'
        text += '\n\n'.join(f'{c["agent"]}: {c["msg"]}' for c in conversation)
        if prompts:
            text += '\n\nPrompts detection:\n\n' + '\n\n'.join(
                p.get('prompt', '') for p in prompts
            )
        injected = inject(text, 'agent_debate')
        log(f'  [Debate] {len(conversation)} agents | {len(prompts)} prompts | {injected} injectes')
        return injected or len(conversation)


class AgentConversationReader:
    def run(self, cycle):
        conv_file = Path('C:/Users/yorob/Downloads/conversations.json')
        if not conv_file.exists():
            log('  [ConvReader] conversations.json introuvable')
            return 0
        try:
            data = json.loads(conv_file.read_text(encoding='utf-8', errors='ignore'))
            convs = data if isinstance(data, list) else data.get('conversations', [])
            if not convs:
                return 0

            conv = convs[cycle % len(convs)]
            messages = conv.get('chat_messages', conv.get('messages', []))
            text_parts = []
            for msg in messages[:20]:
                content = msg.get('content', msg.get('text', ''))
                if isinstance(content, list):
                    content = ' '.join(
                        str(c.get('text', '')) for c in content if isinstance(c, dict)
                    )
                if content and len(str(content)) > 50:
                    role = msg.get('role', msg.get('sender', 'user'))
                    text_parts.append(f'{role}: {str(content)[:300]}')
            if not text_parts:
                return 0

            conv_text = '\n'.join(text_parts[:15])
            prompt = (
                'Expert cybersecurite analysant une conversation de recherche.\n'
                'Extrait les 5 insights techniques les plus importants de cette conversation pour un scanner de vulnerabilites.\n'
                f'Conversation: {conv_text[:2000]}\n'
                'Format JSON: {"insights":[{"insight":"...","category":"xss|sqli|lfi|ssti|auth|api","actionable":"..."}]}'
            )
            response, provider = call_llm(prompt, 'AgentRecherche')
            if not response:
                return 0

            from core.json_parser import safe_json_parse
            result = safe_json_parse(response)
            insights = result.get('insights', []) if isinstance(result, dict) and not result.get('raw') else []
            if not insights:
                if isinstance(result, dict):
                    for v in result.values():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            insights = v
                            break

            if insights:
                text = 'Insights from conversation analysis:\n\n'
                text += '\n\n'.join(
                    f'{i["category"]}: {i["insight"]}\n→ {i.get("actionable", "")}'
                    for i in insights
                )
                injected = inject(text, 'conversation_insights')
                log(f'  [ConvReader] conv {cycle % len(convs)} | {len(insights)} insights | {injected} injectes')
                return len(insights)
        except Exception as e:
            log(f'  [ConvReader] erreur: {e}')
        return 0


class AgentInternetScraper:
    SOURCES = [
        ('OWASP_Cheatsheet',   'XSS prevention cheatsheet detection patterns OWASP 2024'),
        ('PortSwigger_Research','web security vulnerabilities bypass techniques research 2024'),
        ('HackerOne_Reports',  'bug bounty XSS SQLi SSRF bypass techniques disclosed'),
        ('CVE_Details',        'web application critical CVE 2024 2025 injection vulnerabilities'),
        ('SANS_Institute',     'web application firewall bypass detection techniques SANS'),
    ]

    def run(self, cycle):
        source_name, query = self.SOURCES[cycle % len(self.SOURCES)]
        prompt = (
            f'Expert cybersecurite specialise en recherche de vulnerabilites.\n'
            f'Source: {source_name}\n'
            f'Sujet: {query}\n'
            f'Genere des patterns de detection et techniques basees sur les meilleures pratiques de {source_name}.\n'
            'Inclure: signatures de detection, exemples de patterns, faux positifs a eviter.\n'
            'Format JSON: {"patterns":[{"name":"...","detection":"...","example":"...","owasp":"...","fp_risk":"low|medium|high"}]}'
        )
        response, provider = call_llm(prompt, 'AgentSecurite')
        if not response:
            return 0

        from core.json_parser import safe_json_parse
        data = safe_json_parse(response)
        patterns = []
        if isinstance(data, dict) and not data.get('raw'):
            patterns = data.get('patterns', [])
            if not patterns:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        patterns = v
                        break
            if not patterns and 'detection' in data:
                patterns = [data]

        if patterns:
            text = f'Security patterns from {source_name}:\n\n'
            text += '\n\n'.join(
                f'Pattern [{p.get("owasp","?")}] fp:{p.get("fp_risk","?")} — {p.get("detection","")}\nExample: {p.get("example","")}'
                for p in patterns
            )
            injected = inject(text, f'internet_{source_name.lower()}')
            log(f'  [Scraper] {source_name} | {len(patterns)} patterns | {injected} injectes')
            return injected or len(patterns)
        return 0


def run_conversation_crew(cycle_seconds=200):
    agents = [AgentDebater(), AgentConversationReader(), AgentInternetScraper()]
    cycle = 0
    total = 0

    log('=== CONVERSATION CREW — AGENTS DEBATTEURS ===')
    log(f'Agents: {[a.__class__.__name__ for a in agents]}')
    log(f'Topics debat: {len(DEBATE_TOPICS)} | Sources web: {len(AgentInternetScraper.SOURCES)}')
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
    run_conversation_crew(args.cycle)
