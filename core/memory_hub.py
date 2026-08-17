import sqlite3, json, re, os, logging, warnings
from pathlib import Path
from datetime import datetime

logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
logging.getLogger('huggingface_hub').setLevel(logging.ERROR)
logging.getLogger('transformers').setLevel(logging.ERROR)
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
os.environ.setdefault('HF_HUB_VERBOSITY', 'error')
os.environ.setdefault('HUGGINGFACE_HUB_VERBOSITY', 'error')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
os.environ.setdefault('TQDM_DISABLE', '1')
warnings.filterwarnings('ignore')

DB = Path('.cyberia/memory_hub.db')
_MODEL = None

def _get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    return _MODEL

def _embed(text):
    return _get_model().encode(text).tolist()

def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS conversation_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, category TEXT, content TEXT,
            embedding TEXT, confidence REAL DEFAULT 1.0,
            created_at TEXT, last_referenced TEXT,
            reference_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_profile_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_key TEXT UNIQUE, fact_value TEXT,
            confidence REAL DEFAULT 0.7, updated_at TEXT
        );
    ''')
    conn.commit()
    conn.close()

def classify_significance(exchange_text):
    from core.multi_model_router import MultiModelRouter
    router = MultiModelRouter()
    prompt = f'Analyse cet echange et classifie-le. Reponds UNIQUEMENT en JSON sans markdown.\nECHANGE: {exchange_text[:500]}\n\nFormat: {{"significant": true ou false, "category": "preference" ou "decision" ou "fact" ou "correction" ou "none", "summary": "resume en une phrase courte"}}'
    try:
        response = router.call(prompt, task_type='analysis')
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f'  [MEMORY_HUB] Erreur classification: {e}')
    return {'significant': False, 'category': 'none', 'summary': ''}

def save_exchange(session_id, content, category=None, confidence=1.0, force_save=False):
    init()
    if not force_save:
        classification = classify_significance(content)
        if not classification.get('significant'):
            return None
        category = category or classification.get('category', 'fact')
        content = classification.get('summary', content)[:500]

    embedding = _embed(content)
    conn = sqlite3.connect(DB)
    conn.execute(
        'INSERT INTO conversation_memory (session_id, category, content, embedding, confidence, created_at, last_referenced) VALUES (?,?,?,?,?,?,?)',
        (session_id, category, content, json.dumps(embedding), confidence, datetime.now().isoformat(), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    print(f'  [MEMORY_HUB] Memorise ({category}): {content[:60]}')
    return content

def save_correction(session_id, correction_text):
    return save_exchange(session_id, correction_text, category='correction', confidence=1.0, force_save=True)

def search_relevant(query, top_k=5, min_similarity=0.5):
    init()
    import numpy as np
    query_emb = np.array(_embed(query))
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM conversation_memory').fetchall()
    conn.close()

    results = []
    now = datetime.now()
    for row in rows:
        row = dict(row)
        try:
            emb = np.array(json.loads(row['embedding']))
            similarity = float(np.dot(query_emb, emb) / (np.linalg.norm(query_emb) * np.linalg.norm(emb) + 1e-9))
            created = datetime.fromisoformat(row['created_at'])
            days_old = (now - created).days
            recency_weight = max(0.5, 1.0 - days_old / 365)
            category_boost = 1.15 if row['category'] == 'correction' else 1.0
            score = similarity * recency_weight * category_boost
            if similarity >= min_similarity:
                results.append({**row, 'similarity': round(similarity, 3), 'score': round(score, 3)})
        except Exception:
            continue
    results.sort(key=lambda x: -x['score'])
    return results[:top_k]

def get_stats():
    try:
        from core.memory_core import get_core
        return get_core().stats()
    except Exception:
        init()
        conn = sqlite3.connect(DB)
        total = conn.execute('SELECT COUNT(*) FROM conversation_memory').fetchone()[0]
        cats = dict(conn.execute('SELECT category, COUNT(*) FROM conversation_memory GROUP BY category').fetchall())
        conn.close()
        return {'total': total, 'by_category': cats}

def extract_session_memories(session_id, transcript, mode='conversation'):
    from core.multi_model_router import MultiModelRouter
    router = MultiModelRouter()
    prompt = (
        'Analyse cette session de conversation avec un developpeur et extrait '
        'les informations VRAIMENT significatives a retenir pour le futur.\n'
        'Ne retiens QUE : preferences explicites, decisions prises, faits sur '
        'ses projets/entreprises, corrections d\'erreurs.\n'
        'Ignore : hesitations, demandes ponctuelles, questions techniques '
        'generiques sans contexte personnel.\n\n'
        f'SESSION ({mode}):\n{transcript[:3000]}\n\n'
        'Reponds UNIQUEMENT en JSON, une liste (vide si rien de significatif):\n'
        '[{"category": "preference|decision|fact|correction", "summary": '
        '"phrase courte", "confidence": 0.0-1.0}]'
    )
    try:
        response = router.call(prompt, task_type='analysis')
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            items = json.loads(match.group())
            saved = []
            for item in items:
                if item.get('confidence', 0) >= 0.5:
                    result = save_exchange(session_id, item['summary'],
                                          category=item.get('category', 'fact'),
                                          confidence=item.get('confidence', 0.7),
                                          force_save=True)
                    if result:
                        saved.append(result)
            if saved:
                print(f'  [MEMORY_HUB] {len(saved)} souvenir(s) extrait(s) de la session')
            return saved
    except Exception as e:
        print(f'  [MEMORY_HUB] Erreur extraction session: {e}')
    return []

def get_context_block(query, top_k=4, min_similarity=0.3):
    if not query or not query.strip():
        return ''
    results = search_relevant(query, top_k=top_k, min_similarity=min_similarity)
    if not results:
        return ''
    print(f'  [MEMORY_HUB] {len(results)} souvenir(s) pertinent(s) injecte(s)')
    lines = ['CONTEXTE APPRIS DES CONVERSATIONS PRECEDENTES (a utiliser naturellement, sans le mentionner explicitement):']
    for r in results:
        lines.append(f'- [{r["category"]}] {r["content"]}')
    return '\n'.join(lines)
