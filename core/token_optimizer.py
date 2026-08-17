"""
Gestionnaire de tokens pour tous les agents (Claude / OpenRouter / MiMo / DeepSeek).

4 leviers d'economie :
  1. Cache local SQLite (TTL par categorie) -> evite les appels API dupliques
  2. Routing intelligent par complexite de tache -> le bon modele au bon prix
  3. Batch -> regroupe N requetes en 1 seul appel
  4. Compression de contexte -> reduit la taille des prompts et de l'historique
"""
import sqlite3, json, hashlib, re, os
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable

DB_PATH = Path('.cyberia/token_cache.db')

TTL_BY_CATEGORY = {
    'analysis': timedelta(hours=24),
    'payload': timedelta(days=7),
    'strategy': timedelta(hours=24),
    'report': timedelta(hours=24),
}
DEFAULT_TTL = timedelta(hours=24)


class Complexity(Enum):
    SIMPLE = 'simple'      # generer 1 payload -> MiMo local
    MEDIUM = 'medium'      # analyser un resultat -> DeepSeek (cheap)
    COMPLEX = 'complex'    # strategie WAF bypass -> Claude Sonnet
    CRITICAL = 'critical'  # rapport client -> Claude Sonnet


# complexite -> (modele cible, libelle affiche)
ROUTING_TABLE = {
    Complexity.SIMPLE:   {'model_key': 'mimo_flash', 'label': 'MiMo local'},
    Complexity.MEDIUM:   {'model_key': 'deepseek_main', 'label': 'DeepSeek'},
    Complexity.COMPLEX:  {'model_key': 'claude_sonnet', 'label': 'Claude Sonnet'},
    Complexity.CRITICAL: {'model_key': 'claude_sonnet', 'label': 'Claude Sonnet'},
}


def estimate_tokens(text: str) -> int:
    """Estimation ~4 caracteres/token (heuristique, sans dependance tiktoken)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def compress_prompt(text: str) -> str:
    """Supprime espaces/newlines redondants avant envoi a l'API."""
    if not text:
        return text
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def summarize_history(history: List[Dict[str, str]], keep_last: int = 5) -> List[Dict[str, str]]:
    """Garde les N derniers echanges tels quels, resume le reste en une seule ligne."""
    if len(history) <= keep_last:
        return history
    older, recent = history[:-keep_last], history[-keep_last:]
    summary = f"[{len(older)} echanges resumes] " + " | ".join(
        f"{h.get('role', '?')}: {str(h.get('content', ''))[:80]}" for h in older[-3:]
    )
    return [{'role': 'system', 'content': summary}] + recent


def pick_complexity(task_description: str) -> Complexity:
    """Heuristique de classement quand l'appelant ne precise pas la complexite."""
    text = task_description.lower()
    if any(k in text for k in ('rapport client', 'rapport final', 'executive summary')):
        return Complexity.CRITICAL
    if any(k in text for k in ('waf', 'bypass', 'strategie', 'strategy', 'architecture')):
        return Complexity.COMPLEX
    if any(k in text for k in ('analyse', 'analyze', 'resultat', 'result')):
        return Complexity.MEDIUM
    return Complexity.SIMPLE


@dataclass
class SessionStats:
    tokens_saved: int = 0
    tokens_used: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    calls_by_complexity: Dict[str, int] = field(default_factory=dict)

    @property
    def total_potential(self) -> int:
        return self.tokens_saved + self.tokens_used

    @property
    def savings_pct(self) -> float:
        if self.total_potential == 0:
            return 0.0
        return round(100 * self.tokens_saved / self.total_potential, 1)

    def snapshot(self) -> str:
        return (f'Tokens economises : {self.tokens_saved} (cache hit) | '
                f'Tokens utilises : {self.tokens_used} | '
                f'Economie session : {self.savings_pct}%')


class TokenOptimizer:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.stats = SessionStats()
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                category TEXT,
                prompt TEXT,
                response TEXT,
                tokens INTEGER,
                created_at TEXT,
                expires_at TEXT,
                hit_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cache_category ON cache(category);
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                event TEXT,
                tokens INTEGER,
                complexity TEXT,
                model TEXT
            );
        ''')
        conn.commit()
        conn.close()

    @staticmethod
    def _cache_key(prompt: str, category: str) -> str:
        normalized = compress_prompt(prompt).lower()
        return hashlib.sha256(f'{category}:{normalized}'.encode('utf-8')).hexdigest()

    def _ttl_for(self, category: str) -> timedelta:
        return TTL_BY_CATEGORY.get(category, DEFAULT_TTL)

    def get_cached(self, prompt: str, category: str = 'analysis') -> Optional[str]:
        key = self._cache_key(prompt, category)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT response, tokens, expires_at FROM cache WHERE cache_key = ?', (key,)
        ).fetchone()
        if not row:
            conn.close()
            return None
        response, tokens, expires_at = row
        if datetime.fromisoformat(expires_at) < datetime.now():
            conn.execute('DELETE FROM cache WHERE cache_key = ?', (key,))
            conn.commit()
            conn.close()
            return None
        conn.execute('UPDATE cache SET hit_count = hit_count + 1 WHERE cache_key = ?', (key,))
        conn.commit()
        conn.close()

        self.stats.cache_hits += 1
        self.stats.tokens_saved += tokens
        self._log_event('cache_hit', tokens, None, None)
        print(f'  [TOKEN-OPT] Cache HIT ({category}) -> 0 token depense ({tokens} economises)')
        return response

    def set_cached(self, prompt: str, category: str, response: str):
        key = self._cache_key(prompt, category)
        tokens = estimate_tokens(prompt) + estimate_tokens(response)
        now = datetime.now()
        expires = now + self._ttl_for(category)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT OR REPLACE INTO cache '
            '(cache_key, category, prompt, response, tokens, created_at, expires_at, hit_count) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM cache WHERE cache_key = ?), 0))',
            (key, category, prompt[:2000], response, tokens, now.isoformat(), expires.isoformat(), key)
        )
        conn.commit()
        conn.close()

    def _log_event(self, event: str, tokens: int, complexity, model):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT INTO session_log (ts, event, tokens, complexity, model) VALUES (?, ?, ?, ?, ?)',
            (datetime.now().isoformat(), event, tokens,
             complexity.value if isinstance(complexity, Complexity) else complexity, model)
        )
        conn.commit()
        conn.close()

    def route(self, complexity: Complexity) -> Dict[str, str]:
        return ROUTING_TABLE[complexity]

    def batch_prompts(self, prompts: List[str], instruction: str = '') -> str:
        """Regroupe N prompts en un seul appel API (reduction estimee 60-70% des tokens)."""
        header = instruction or (
            'Traite chaque item independamment. '
            'Reponds en JSON : une liste ordonnee de resultats, un par item, meme ordre.'
        )
        body = '\n'.join(f'### ITEM {i + 1}\n{compress_prompt(p)}' for i, p in enumerate(prompts))
        return f'{header}\n\n{body}'

    @staticmethod
    def parse_batch_response(response: str, expected_count: int) -> List[str]:
        """Parse la reponse batch en liste ; fallback sur split par item si le JSON echoue."""
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
        parts = [p.strip() for p in re.split(r'###\s*(?:RESULT|ITEM)\s*\d+', response) if p.strip()]
        if len(parts) == expected_count:
            return parts
        return [response] * expected_count

    def _default_caller(self, model_key: str, prompt: str) -> str:
        """Appel reel via l'infra existante (multi_model_router_v2 + OpenRouter/Anthropic)."""
        from core.multi_model_router_v2 import router_v2, MODELS

        if model_key == 'claude_sonnet':
            from openai import OpenAI
            if os.getenv('OPENROUTER_API_KEY'):
                client = OpenAI(api_key=os.getenv('OPENROUTER_API_KEY'), base_url='https://openrouter.ai/api/v1')
                model_name = 'anthropic/claude-sonnet-4-6'
            elif os.getenv('ANTHROPIC_API_KEY'):
                client = OpenAI(api_key=os.getenv('ANTHROPIC_API_KEY'), base_url='https://api.anthropic.com/v1')
                model_name = 'claude-sonnet-4-6'
            else:
                return router_v2.call(prompt)
            completion = client.chat.completions.create(
                model=model_name, messages=[{'role': 'user', 'content': prompt}], max_tokens=2000
            )
            return completion.choices[0].message.content or ''

        if model_key in MODELS:
            client = router_v2._get_client(model_key)
            completion = client.chat.completions.create(
                model=MODELS[model_key].name, messages=[{'role': 'user', 'content': prompt}], max_tokens=2000
            )
            return completion.choices[0].message.content or ''

        return router_v2.call(prompt)

    def call(self, prompt: str, complexity: Complexity = Complexity.MEDIUM,
             category: str = 'analysis', agent_type: Optional[str] = None,
             caller: Optional[Callable[[str, str], str]] = None) -> str:
        """
        Point d'entree principal : cache -> routing par complexite -> appel reel -> mise en cache.
        `caller(model_key, prompt) -> str` permet d'injecter un appelant custom (tests, agent specifique).
        """
        prompt = compress_prompt(prompt)
        cached = self.get_cached(prompt, category)
        if cached is not None:
            self._print_snapshot()
            return cached

        self.stats.cache_misses += 1
        route = self.route(complexity)
        model_key = route['model_key']
        self.stats.calls_by_complexity[complexity.value] = self.stats.calls_by_complexity.get(complexity.value, 0) + 1

        response = (caller or self._default_caller)(model_key, prompt)

        tokens_used = estimate_tokens(prompt) + estimate_tokens(response)
        self.stats.tokens_used += tokens_used
        self._log_event('cache_miss', tokens_used, complexity, model_key)
        self.set_cached(prompt, category, response)
        print(f'  [TOKEN-OPT] Cache MISS -> {route["label"]} ({complexity.value}) -> {tokens_used} tokens utilises')
        self._print_snapshot()
        return response

    def call_batch(self, prompts: List[str], complexity: Complexity = Complexity.SIMPLE,
                    category: str = 'payload', agent_type: Optional[str] = None,
                    instruction: str = '', caller: Optional[Callable[[str, str], str]] = None) -> List[str]:
        """Version batch de call() : N prompts -> 1 seul appel API (cache par item non applicable)."""
        batched_prompt = self.batch_prompts(prompts, instruction)
        response = self.call(batched_prompt, complexity=complexity, category=category,
                              agent_type=agent_type, caller=caller)
        return self.parse_batch_response(response, len(prompts))

    def _print_snapshot(self):
        print(f'  [TOKEN-OPT] {self.stats.snapshot()}')

    def session_report(self) -> Dict[str, Any]:
        report = {
            'tokens_saved': self.stats.tokens_saved,
            'tokens_used': self.stats.tokens_used,
            'cache_hits': self.stats.cache_hits,
            'cache_misses': self.stats.cache_misses,
            'savings_pct': self.stats.savings_pct,
            'calls_by_complexity': self.stats.calls_by_complexity,
        }
        print('\n' + '=' * 50)
        print('  RAPPORT SESSION - OPTIMISATION TOKENS')
        print('=' * 50)
        print(f'  Tokens economises : {report["tokens_saved"]}')
        print(f'  Tokens utilises   : {report["tokens_used"]}')
        print(f'  Cache hits/misses : {report["cache_hits"]}/{report["cache_misses"]}')
        print(f'  Economie totale   : {report["savings_pct"]}%')
        print('=' * 50)
        return report

    def purge_expired(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute('DELETE FROM cache WHERE expires_at < ?', (datetime.now().isoformat(),))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return deleted


token_optimizer = TokenOptimizer()
