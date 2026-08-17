"""
Assistant CYBERIA base sur MiMo v2.5 Pro (via OpenRouter).
Meme config que test_mimo.py : OPENROUTER_API_KEY / xiaomi/mimo-v2.5-pro.
"""
from __future__ import annotations
import os, json, sqlite3, time
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

from core.token_optimizer import token_optimizer, Complexity

MODEL = 'xiaomi/mimo-v2.5-pro'
BASE_URL = 'https://openrouter.ai/api/v1'

SCAN_RESULTS_DIR = Path('.cyberia/scan_results')
ANALYSIS_DIR = Path('.cyberia/mimo_analysis')
LAB_DB = Path('.cyberia/payload_lab.db')

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            raise RuntimeError('OPENROUTER_API_KEY manquante (.env)')
        _client = OpenAI(api_key=api_key, base_url=BASE_URL)
    return _client


def _mimo_caller(model_key: str, prompt: str) -> str:
    """Appelant injecte dans token_optimizer.call() : force le passage par MiMo/OpenRouter."""
    client = _get_client()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=800,
    )
    return resp.choices[0].message.content or ''


def _latest_scan_result() -> Optional[Path]:
    if not SCAN_RESULTS_DIR.exists():
        return None
    files = sorted(SCAN_RESULTS_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def analyze_scan_result(scan_json_path: Optional[str] = None) -> Optional[Path]:
    """
    Lit le dernier rapport JSON de .cyberia/scan_results/ (ou `scan_json_path` si fourni),
    demande a MiMo 3 recommandations courtes en francais, sauvegarde la reponse dans
    .cyberia/mimo_analysis/DATE_analysis.txt.
    """
    path = Path(scan_json_path) if scan_json_path else _latest_scan_result()
    if not path or not path.exists():
        print('  [MIMO] Aucun rapport de scan trouve.')
        return None

    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception as e:
        print(f'  [MIMO] Rapport illisible ({path.name}) : {e}')
        return None

    summary = data.get('summary', {})
    vulnerable = summary.get('vulnerable_categories') or list(data.get('results', {}).keys())
    prompt = (
        f"Rapport de pentest pour {data.get('target_name', path.stem)} :\n"
        f"- Payloads testes : {summary.get('total_payloads_tested', '?')}\n"
        f"- Confirmes : {summary.get('total_confirmed', '?')}\n"
        f"- Taux de bypass global : {summary.get('overall_bypass_rate', '?')}%\n"
        f"- WAF detecte : {summary.get('waf', 'unknown')}\n"
        f"- Categories vulnerables : {', '.join(vulnerable) if vulnerable else 'aucune'}\n\n"
        "Analyse ce rapport de pentest et donne 3 recommandations courtes "
        "en francais pour corriger les vulnerabilites trouvees."
    )

    response = token_optimizer.call(
        prompt, complexity=Complexity.SIMPLE, category='analysis',
        agent_type='AgentMiMoAssistant', caller=_mimo_caller
    )

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANALYSIS_DIR / f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_analysis.txt'
    out_path.write_text(
        f'Rapport source : {path.name}\nGenere le : {datetime.now().isoformat()}\n\n{response}\n',
        encoding='utf-8'
    )
    print(f'  [MIMO] Analyse sauvegardee -> {out_path}')
    return out_path


def _parse_variants(response: str, expected: int = 3) -> List[str]:
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    lines = [l.strip(' -*\t') for l in response.splitlines() if l.strip()]
    return lines[:expected]


def _init_payloads_table(conn: sqlite3.Connection):
    conn.execute('''CREATE TABLE IF NOT EXISTS payloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT NOT NULL,
        category TEXT NOT NULL,
        score INTEGER DEFAULT 0,
        bypasses INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')


def enrich_payload(payload: str, category: str) -> List[str]:
    """
    Demande a MiMo 3 variantes d'un payload confirme pour enrichir la DB,
    puis INSERT dans payload_lab.db (table `payloads`) celles pas deja presentes.
    """
    prompt = (
        f"Voici un payload {category} confirme fonctionnel :\n{payload}\n\n"
        "Genere 3 variantes de ce payload (encodages ou techniques de contournement "
        "differentes, meme impact). Reponds uniquement en JSON : une liste de 3 "
        "chaines de caracteres, sans commentaire ni markdown."
    )

    response = token_optimizer.call(
        prompt, complexity=Complexity.SIMPLE, category='payload',
        agent_type='AgentMiMoAssistant', caller=_mimo_caller
    )
    variants = _parse_variants(response)

    LAB_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(LAB_DB)
    _init_payloads_table(conn)

    inserted = []
    for variant in variants:
        exists = conn.execute(
            'SELECT 1 FROM payloads WHERE payload = ? LIMIT 1', (variant,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            'INSERT INTO payloads (payload, category, score, bypasses) VALUES (?, ?, 0, 0)',
            (variant, category)
        )
        inserted.append(variant)
    conn.commit()
    conn.close()

    print(f'  [MIMO] {len(inserted)}/{len(variants)} variantes inserees dans payload_lab.db ({category})')
    return inserted


def watch_and_assist(interval: int = 60, max_cycles: Optional[int] = None):
    """
    Boucle toutes les `interval` secondes : detecte un nouveau JSON dans
    .cyberia/scan_results/ et lance analyze_scan_result() dessus.
    Le cache token_optimizer (categorie 'analysis') garantit qu'un meme
    rapport ne redeclenche jamais un vrai appel API.
    """
    print(f'  [MIMO] Surveillance de {SCAN_RESULTS_DIR}/ toutes les {interval}s (Ctrl+C pour arreter)...')
    seen = {p.name for p in SCAN_RESULTS_DIR.glob('*.json')} if SCAN_RESULTS_DIR.exists() else set()
    cycles = 0
    try:
        while max_cycles is None or cycles < max_cycles:
            if SCAN_RESULTS_DIR.exists():
                current = {p.name for p in SCAN_RESULTS_DIR.glob('*.json')}
                for name in sorted(current - seen):
                    print('  [MIMO] MiMo analyse le scan...')
                    analyze_scan_result(str(SCAN_RESULTS_DIR / name))
                seen = current
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(interval)
    except KeyboardInterrupt:
        print('  [MIMO] Surveillance arretee.')


if __name__ == '__main__':
    watch_and_assist()
