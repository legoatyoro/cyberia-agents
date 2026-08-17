import json, sqlite3, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any, Dict, List

DB_PATH = Path('.cyberia/cyberia_supervisor.db')

SOURCES_BY_DOMAIN = {
    'security': ['https://owasp.org', 'https://portswigger.net', 'https://github.com'],
    'backend': ['https://fastapi.tiangolo.com', 'https://www.djangoproject.com', 'https://github.com'],
    'frontend': ['https://developer.mozilla.org', 'https://react.dev', 'https://vuejs.org'],
    'devops': ['https://docs.docker.com', 'https://kubernetes.io', 'https://railway.app'],
    'algorithms': ['https://arxiv.org', 'https://paperswithcode.com', 'https://github.com'],
    'ai_ml': ['https://pytorch.org', 'https://huggingface.co', 'https://github.com'],
}


def _get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def search_for_agent(query: str, domain: str) -> Dict[str, Any]:
    conn = _get_conn()
    seven_days = int(time.time()) - 7 * 24 * 3600
    row = conn.execute(
        'SELECT result_json FROM web_cache WHERE domain=? AND query=? AND created_at>=? '
        'ORDER BY created_at DESC LIMIT 1',
        (domain, query, seven_days),
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row['result_json'])
    results = _duckduckgo_search(query)
    structured = {
        'domain': domain,
        'sources': results,
        'summary': f'{len(results)} resultats pour {domain}.',
        'query': query,
    }
    conn = _get_conn()
    conn.execute(
        'INSERT INTO web_cache (domain,query,result_json,created_at) VALUES (?,?,?,?)',
        (domain, query, json.dumps(structured, ensure_ascii=False), int(time.time())),
    )
    conn.commit()
    conn.close()
    return structured


def _duckduckgo_search(query: str) -> List[Dict[str, str]]:
    try:
        encoded = urllib.parse.urlencode({'q': query})
        url = f'https://api.duckduckgo.com/?{encoded}&format=json&no_html=1&skip_disambig=1'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 CYBERIA'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        results = []
        abstract = data.get('AbstractText', '')
        if abstract:
            results.append({
                'title': data.get('Heading', ''),
                'url': data.get('AbstractURL', ''),
                'summary': abstract[:300],
            })
        for topic in data.get('RelatedTopics', [])[:4]:
            if isinstance(topic, dict) and 'Text' in topic:
                results.append({
                    'title': topic.get('Text', '')[:80],
                    'url': topic.get('FirstURL', ''),
                    'summary': topic.get('Text', '')[:200],
                })
        return results
    except Exception as e:
        return [{'title': 'Recherche indisponible', 'url': '', 'summary': str(e)}]


def safe_search(query: str) -> str:
    result = search_for_agent(query, 'general')
    sources = result.get('sources', [])
    if not sources:
        return '[WEB_SEARCH_UNAVAILABLE] Aucun resultat'
    lines = [result.get('summary', '')]
    for s in sources[:3]:
        if s.get('summary'):
            lines.append(f'- {s["title"]}: {s["summary"]}')
    return '\n'.join(lines)
