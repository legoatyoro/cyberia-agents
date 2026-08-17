import sqlite3
import hashlib
import json
import shutil
import numpy as np
from pathlib import Path
from datetime import datetime

COMPONENTS_DB = Path('.cyberia/components.db')
COMPONENTS_DIR = Path('.cyberia/components')

# Lazy-loaded model — initialised at first call to avoid slowing every import.
_MODEL = None

def _get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        print('  🧠 [COMPONENT_LIB] Chargement du modele all-MiniLM-L6-v2...')
        _MODEL = SentenceTransformer('all-MiniLM-L6-v2')
        print('  ✅ [COMPONENT_LIB] Modele pret')
    return _MODEL

def _embed(text: str) -> list[float]:
    return _get_model().encode(text).tolist()

def _cosine_sim(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0

def init_components():
    COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
    COMPONENTS_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(COMPONENTS_DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            category TEXT,
            stack TEXT,
            tags TEXT,
            hash_md5 TEXT,
            file_path TEXT,
            validated INTEGER DEFAULT 0,
            times_used INTEGER DEFAULT 0,
            avg_score REAL DEFAULT 0.0,
            created_at TEXT,
            last_used TEXT,
            embedding TEXT
        );
    ''')
    # Migration: add embedding column to tables created before this version
    try:
        conn.execute('ALTER TABLE components ADD COLUMN embedding TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()

def compute_hash(filepath: Path) -> str:
    try:
        return hashlib.md5(filepath.read_bytes()).hexdigest()
    except Exception:
        return ''

def save_component(name: str, source_file: Path, description: str,
                   category: str, stack: str, tags: list, validated: bool = True) -> bool:
    init_components()
    file_hash = compute_hash(source_file)

    # Compute semantic embedding from description + tags
    embed_text = f'{description} {" ".join(tags)}'
    try:
        embedding_json = json.dumps(_embed(embed_text))
    except Exception as e:
        print(f'  ⚠️ [COMPONENT_LIB] Embedding non calcule : {e}')
        embedding_json = None

    conn = sqlite3.connect(COMPONENTS_DB)
    existing = conn.execute('SELECT id FROM components WHERE hash_md5=?', (file_hash,)).fetchone()
    if existing:
        conn.close()
        return False
    dest = COMPONENTS_DIR / f'{name}_{stack.replace(" ", "_")}{source_file.suffix}'
    shutil.copy2(source_file, dest)
    conn.execute(
        '''INSERT OR REPLACE INTO components
           (name, description, category, stack, tags, hash_md5, file_path, validated, created_at, embedding)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (name, description, category, stack, json.dumps(tags),
         file_hash, str(dest), 1 if validated else 0,
         datetime.now().isoformat(), embedding_json)
    )
    conn.commit()
    conn.close()
    print(f'  📦 [COMPONENT_LIB] Composant sauvegarde : {name}')
    from core.event_bus import publish
    publish('COMPONENT_SAVED', 'COMPONENT_LIBRARY', {'name': name, 'stack': stack})
    return True

def find_component(query: str, stack: str = None) -> list:
    """Keyword search (exact LIKE match)."""
    init_components()
    conn = sqlite3.connect(COMPONENTS_DB)
    conn.row_factory = sqlite3.Row
    if stack:
        rows = conn.execute(
            '''SELECT * FROM components WHERE validated=1
               AND (name LIKE ? OR description LIKE ? OR tags LIKE ?) AND stack LIKE ?
               ORDER BY times_used DESC LIMIT 5''',
            (f'%{query}%', f'%{query}%', f'%{query}%', f'%{stack}%')
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT * FROM components WHERE validated=1
               AND (name LIKE ? OR description LIKE ? OR tags LIKE ?)
               ORDER BY times_used DESC LIMIT 5''',
            (f'%{query}%', f'%{query}%', f'%{query}%')
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_similar_component(query: str, top_k: int = 3) -> list:
    """Semantic search via cosine similarity on sentence embeddings."""
    init_components()
    try:
        query_emb = _embed(query)
    except Exception as e:
        print(f'  ⚠️ [COMPONENT_LIB] Embedding indisponible, fallback recherche texte : {e}')
        return find_component(query)

    conn = sqlite3.connect(COMPONENTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM components WHERE validated=1 AND embedding IS NOT NULL'
    ).fetchall()
    conn.close()

    if not rows:
        print('  ℹ️ [COMPONENT_LIB] Aucun composant avec embedding disponible')
        return []

    scored = []
    for row in rows:
        comp = dict(row)
        try:
            comp_emb = json.loads(comp['embedding'])
            comp['similarity'] = round(_cosine_sim(query_emb, comp_emb), 4)
            scored.append(comp)
        except Exception:
            continue

    scored.sort(key=lambda x: x['similarity'], reverse=True)
    top = scored[:top_k]
    for r in top:
        print(f'  🔍 sim={r["similarity"]:.4f}  {r["name"]}  [{r["category"]}]  {r["description"][:60]}')
    return top

def use_component(component_id: int, target_dir: Path) -> Path | None:
    init_components()
    conn = sqlite3.connect(COMPONENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM components WHERE id=?', (component_id,)).fetchone()
    if not row:
        conn.close()
        return None
    row = dict(row)
    src = Path(row['file_path'])
    if not src.exists():
        conn.close()
        return None
    dest = target_dir / src.name
    shutil.copy2(src, dest)
    conn.execute(
        'UPDATE components SET times_used=times_used+1, last_used=? WHERE id=?',
        (datetime.now().isoformat(), component_id)
    )
    conn.commit()
    conn.close()
    return dest

def list_components() -> list:
    init_components()
    conn = sqlite3.connect(COMPONENTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM components ORDER BY times_used DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def auto_save_validated_files(project_dir: Path, score: float):
    if score < 8.5:
        return
    GOOD_PATTERNS = {
        'auth.py':          ('JWT Authentication', 'auth',     ['jwt', 'auth', 'security']),
        'database.py':      ('Database Setup',     'database', ['database', 'sqlalchemy', 'sqlite']),
        'models.py':        ('Data Models',        'models',   ['models', 'orm', 'database']),
        'routers/auth.py':  ('Auth Router',        'router',   ['router', 'auth', 'fastapi']),
    }
    stack = 'fastapi' if (project_dir / 'main.py').exists() else 'unknown'
    saved = 0
    for pattern, (desc, cat, tags) in GOOD_PATTERNS.items():
        filepath = project_dir / pattern
        if filepath.exists():
            name = f'{project_dir.name}_{cat}'
            if save_component(name, filepath, desc, cat, stack, tags):
                saved += 1
    if saved > 0:
        print(f'  📦 {saved} composant(s) valide(s) sauvegardes dans la librairie')
