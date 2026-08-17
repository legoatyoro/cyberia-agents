import sqlite3, json, time, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime
from core.multi_model_router_v2 import router_v2

DB = Path('.cyberia/cyber_research.db')
WATCH_FOLDER = Path('cyberia_inbox')

SOURCES_SECU = {
    'owasp': 'https://owasp.org/www-project-top-ten/',
    'portswigger': 'https://portswigger.net/web-security',
    'exploit_db': 'https://www.exploit-db.com/',
    'cve_mitre': 'https://cve.mitre.org/cgi-bin/cvekey.cgi?keyword=web',
    'nvd_nist': 'https://nvd.nist.gov/vuln/search',
}


def init():
    DB.parent.mkdir(exist_ok=True)
    WATCH_FOLDER.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS vuln_patterns (
            id INTEGER PRIMARY KEY, source TEXT, vuln_type TEXT,
            description TEXT, payload_example TEXT, severity TEXT,
            tags TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS payload_patterns (
            id INTEGER PRIMARY KEY, attack_type TEXT, payload TEXT,
            target TEXT, bypass_technique TEXT, effectiveness INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS research_log (
            id INTEGER PRIMARY KEY, agent TEXT, source TEXT,
            patterns_found INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS ingested_files (
            id INTEGER PRIMARY KEY, filename TEXT, filepath TEXT,
            patterns_extracted INTEGER, status TEXT, created_at TEXT
        );
    ''')
    conn.commit()
    conn.close()


def save_vuln_pattern(source, vuln_type, description, payload='', severity='medium', tags=None):
    init()
    conn = sqlite3.connect(DB)
    conn.execute(
        'INSERT INTO vuln_patterns (source,vuln_type,description,payload_example,severity,tags,created_at) VALUES (?,?,?,?,?,?,?)',
        (source, vuln_type, description[:500], payload[:200], severity,
         json.dumps(tags or []), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    try:
        from core.memory_core import MemoryCore
        MemoryCore().save(
            key=f'vuln_{source}_{hash(description) % 100000}',
            value=f'{vuln_type}: {description}',
            tags=['vuln', vuln_type, source, 'securite'],
            source='cyber_research')
    except Exception:
        pass


def save_payload_pattern(attack_type, payload, target='web', bypass_technique='', effectiveness=5):
    init()
    conn = sqlite3.connect(DB)
    conn.execute(
        'INSERT INTO payload_patterns (attack_type,payload,target,bypass_technique,effectiveness,created_at) VALUES (?,?,?,?,?,?)',
        (attack_type, payload[:500], target, bypass_technique[:200], effectiveness, datetime.now().isoformat()))
    conn.commit()
    conn.close()


class AgentCyberResearch:
    name = 'AgentCyberResearch'

    def run(self, topic='web vulnerabilities 2025'):
        print(f'  [CyberResearch] Recherche: {topic}')
        try:
            q = urllib.parse.urlencode({'q': f'{topic} site:owasp.org OR site:portswigger.net'})
            url = f'https://api.duckduckgo.com/?{q}&format=json&no_html=1'
            req = urllib.request.Request(url, headers={'User-Agent': 'CYBERIA-Research'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            abstract = data.get('AbstractText', '')
            related = data.get('RelatedTopics', [])
            results = []
            if abstract:
                results.append(abstract[:500])
            for t in related[:5]:
                if isinstance(t, dict) and 'Text' in t:
                    results.append(t['Text'][:300])
            if results:
                combined = '\n'.join(results)
                prompt = (
                    f'Tu es un expert cybersecurite. Analyse ces informations et extrais les patterns de vulnerabilites.\n'
                    f'Reponds en JSON: {{"vulns": [{{"type": "...", "description": "...", "severity": "critical|high|medium", "payload_example": "..."}}]}}\n'
                    f'Informations: {combined[:2000]}'
                )
                response = router_v2.call(prompt, task_type='analysis', agent_type='AgentSecurite')
                import re
                match = re.search(r'\{.*\}', response, re.DOTALL)
                if match:
                    extracted = json.loads(match.group())
                    vulns = extracted.get('vulns', [])
                    for v in vulns:
                        save_vuln_pattern(
                            'cyber_research', v.get('type', ''), v.get('description', ''),
                            v.get('payload_example', ''), v.get('severity', 'medium'), ['auto_research'])
                    print(f'  [CyberResearch] {len(vulns)} patterns extraits')
                    return len(vulns)
        except Exception as e:
            print(f'  [CyberResearch] Erreur: {e}')
        return 0


class AgentPayloadLab:
    name = 'AgentPayloadLab'

    def generate_payloads(self, attack_type='xss', target='web'):
        print(f'  [PayloadLab] Generation payloads: {attack_type}')
        prompt = (
            f'Tu es un expert Red Team. Genere 5 payloads {attack_type} pour tests de securite.\n'
            f'Reponds en JSON: {{"payloads": [{{"payload": "...", "technique": "...", "bypass": "...", "effectiveness": 1-10}}]}}\n'
            f'Type: {attack_type}, Cible: {target}'
        )
        try:
            response = router_v2.call(prompt, task_type='analysis', agent_type='AgentSecurite')
            import re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group())
                payloads = data.get('payloads', [])
                for p in payloads:
                    save_payload_pattern(
                        attack_type, p.get('payload', ''),
                        target, p.get('bypass', ''), p.get('effectiveness', 5))
                print(f'  [PayloadLab] {len(payloads)} payloads generes')
                return payloads
        except Exception as e:
            print(f'  [PayloadLab] Erreur: {e}')
        return []

    def generate_missing_payloads(self, category='ssti'):
        print(f'  [PayloadLab] Generation payloads {category}...')
        prompts = {
            'ssti': 'Genere 10 payloads SSTI (Server Side Template Injection) pour Jinja2, Twig, FreeMarker, Velocity. Format JSON: {"payloads": [{"payload":"...","engine":"jinja2","expected_output":"49"}]}',
            'lfi': 'Genere 10 payloads LFI (Local File Inclusion) avec techniques evasion: null byte, encodage, path traversal. Format JSON.',
            'rce': 'Genere 10 payloads RCE pedagogiques pour tests WAF uniquement. Techniques: backtick, $(), pipe, semicolon. Format JSON.',
            'xxe': 'Genere 10 payloads XXE (XML External Entity) pour tests WAF. Format JSON.',
            'ssrf': 'Genere 10 payloads SSRF pour tester la detection WAF locale uniquement (targets: 127.0.0.1, localhost). Format JSON.',
            'log4shell': 'Genere 10 variations Log4Shell pour tester detection WAF: ${jndi:ldap}, nested, encoded. Format JSON.',
            'auth_bypass': 'Genere 10 payloads auth bypass: SQL, JWT manipulation, role injection. Format JSON.',
        }
        prompt = prompts.get(category, f'Genere 10 payloads {category} pour tests WAF en laboratoire. Format JSON.')
        try:
            response = router_v2.call(prompt, task_type='analysis', agent_type='AgentSecurite')
            import re, json as _json
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = _json.loads(match.group())
                payloads = data.get('payloads', [])
                _db = Path('.cyberia/payload_lab.db')
                _db.parent.mkdir(exist_ok=True)
                conn = sqlite3.connect(_db)
                conn.execute(
                    'CREATE TABLE IF NOT EXISTS imported_payloads '
                    '(id INTEGER PRIMARY KEY, payload TEXT UNIQUE, payload_type TEXT, '
                    'source TEXT, imported_at TEXT)'
                )
                for p in payloads:
                    payload_str = p.get('payload', '') if isinstance(p, dict) else str(p)
                    if payload_str and len(payload_str) > 2:
                        conn.execute(
                            'INSERT OR IGNORE INTO imported_payloads '
                            '(payload,payload_type,source,imported_at) VALUES (?,?,?,datetime("now"))',
                            (payload_str, category, f'generated_{category}')
                        )
                conn.commit()
                conn.close()
                print(f'  [PayloadLab] {len(payloads)} payloads {category} generes et sauvegardes')
                return payloads
        except Exception as e:
            print(f'  [PayloadLab] Erreur {category}: {e}')
        return []


class AgentAlgoSec:
    name = 'AgentAlgoSec'

    def analyze_scan_algo(self, target_description):
        print(f'  [AlgoSec] Analyse algo scan: {target_description[:50]}')
        prompt = (
            f'Tu es un expert en algorithmes de scanning de securite.\n'
            f'Analyse et propose le meilleur algorithme de scan pour: {target_description}\n'
            f'Reponds en JSON: {{"algo": {{"name": "...", "steps": ["..."], "complexity": "...", "tools": ["..."], "scoring": "..."}}}}'
        )
        try:
            response = router_v2.call(prompt, task_type='analysis', agent_type='AgentSecurite')
            import re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            print(f'  [AlgoSec] Erreur: {e}')
        return {}


class FileIngestionAgent:
    name = 'FileIngestionAgent'

    def watch_and_ingest(self):
        WATCH_FOLDER.mkdir(exist_ok=True)
        files = list(WATCH_FOLDER.glob('*'))
        ingested = 0
        for f in files:
            if f.suffix in ('.txt', '.md', '.json', '.py', '.log', '.html'):
                print(f'  [FileIngestion] Lecture: {f.name}')
                try:
                    content = f.read_text(encoding='utf-8', errors='ignore')[:3000]
                    prompt = (
                        f'Analyse ce fichier et extrais les patterns de securite utiles.\n'
                        f'Reponds en JSON: {{"patterns": [{{"type": "vuln|payload|algo|config", "description": "...", "tags": ["..."]}}]}}\n'
                        f'Fichier: {f.name}\nContenu: {content}'
                    )
                    response = router_v2.call(prompt, task_type='analysis', agent_type='AgentSecurite')
                    import re
                    match = re.search(r'\{.*\}', response, re.DOTALL)
                    count = 0
                    if match:
                        data = json.loads(match.group())
                        patterns = data.get('patterns', [])
                        for p in patterns:
                            try:
                                from core.memory_core import MemoryCore
                                MemoryCore().save(
                                    key=f'ingested_{f.stem}_{hash(p["description"]) % 100000}',
                                    value=p['description'],
                                    tags=p.get('tags', []) + ['ingested', f.stem],
                                    source='file_ingestion')
                            except Exception:
                                pass
                            count += 1
                    init()
                    conn = sqlite3.connect(DB)
                    conn.execute(
                        'INSERT INTO ingested_files (filename,filepath,patterns_extracted,status,created_at) VALUES (?,?,?,?,?)',
                        (f.name, str(f), count, 'done', datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    f.rename(WATCH_FOLDER / f'processed_{f.name}')
                    print(f'  [FileIngestion] {count} patterns extraits de {f.name}')
                    ingested += count
                except Exception as e:
                    print(f'  [FileIngestion] Erreur {f.name}: {e}')
        return ingested


def get_stats():
    init()
    conn = sqlite3.connect(DB)
    vulns = conn.execute('SELECT COUNT(*) FROM vuln_patterns').fetchone()[0]
    payloads = conn.execute('SELECT COUNT(*) FROM payload_patterns').fetchone()[0]
    files = conn.execute('SELECT COUNT(*) FROM ingested_files').fetchone()[0]
    top_vulns = conn.execute(
        'SELECT vuln_type, COUNT(*) FROM vuln_patterns GROUP BY vuln_type ORDER BY COUNT(*) DESC LIMIT 5'
    ).fetchall()
    conn.close()
    return {'vuln_patterns': vulns, 'payload_patterns': payloads, 'ingested_files': files, 'top_vulns': dict(top_vulns)}


def run_h24_cycle():
    print(f'  [H24] Cycle de recherche {datetime.now().strftime("%H:%M")}')
    researcher = AgentCyberResearch()
    payload_lab = AgentPayloadLab()
    file_agent = FileIngestionAgent()
    researcher.run('OWASP top 10 web vulnerabilities 2025')
    researcher.run('WAF bypass techniques 2025')
    payload_lab.generate_payloads('xss', 'web')
    payload_lab.generate_payloads('sqli', 'api')
    file_agent.watch_and_ingest()
    stats = get_stats()
    print(f'  [H24] Stats: {stats}')
    return stats
