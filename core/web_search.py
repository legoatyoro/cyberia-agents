import os, json
from typing import Optional

TAVILY_KEY = os.getenv('TAVILY_API_KEY')


def tavily_search(query, max_results=5):
    import urllib.request, urllib.error
    key = os.getenv('TAVILY_API_KEY') or TAVILY_KEY
    if not key:
        return '[WEB_SEARCH_UNAVAILABLE] Configure TAVILY_API_KEY dans .env (gratuit sur tavily.com)'
    url = 'https://api.tavily.com/search'
    payload = json.dumps({
        'api_key': key,
        'query': query,
        'max_results': max_results,
        'include_answer': True,
        'include_raw_content': False
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            answer = data.get('answer', '')
            results = data.get('results', [])
            if answer:
                sources = '\n'.join(f'- {r["title"]}: {r["url"]}' for r in results[:3])
                return f'{answer}\n\nSources:\n{sources}'
            elif results:
                return '\n'.join(f'{r["title"]}: {r["content"][:200]}' for r in results[:3])
            return '[WEB_SEARCH] Aucun resultat'
    except Exception as e:
        try:
            return duckduckgo_fallback(query)
        except Exception:
            return f'[WEB_SEARCH_UNAVAILABLE] Erreur: {e}'


def duckduckgo_fallback(query):
    import urllib.request, urllib.parse
    q = urllib.parse.quote(query)
    url = f'https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1'
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
            abstract = data.get('AbstractText', '')
            if abstract:
                return f'[DuckDuckGo] {abstract}'
            related = data.get('RelatedTopics', [])
            if related:
                return '\n'.join(r.get('Text', '')[:200] for r in related[:3] if isinstance(r, dict) and 'Text' in r)
    except Exception:
        pass
    return '[WEB_SEARCH_UNAVAILABLE] Recherche web indisponible — utilise tes connaissances internes'


def safe_search(query):
    try:
        return tavily_search(query)
    except Exception as e:
        return f'[WEB_SEARCH_UNAVAILABLE] {e} — continue avec connaissances internes'
