import re
from pathlib import Path
from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def chunk_text(text: str, chunk_tokens: int = 2000, overlap_tokens: int = 200) -> list:
    chunk_size = chunk_tokens * 4
    overlap_size = overlap_tokens * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        line_break = chunk.rfind('\n', chunk_size // 2)
        if line_break > 0 and end < len(text):
            chunk = text[start:start + line_break]
            end = start + line_break
        chunks.append({
            'text': chunk,
            'start_char': start,
            'end_char': end,
            'tokens_approx': estimate_tokens(chunk)
        })
        start = end - overlap_size
        if start >= len(text):
            break
    return chunks


class FileAnalyzer:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'FILE_ANALYZER'

    def analyze_file(self, filepath: Path, context: str = '') -> dict:
        if not filepath.exists():
            for candidate in Path('generated').rglob(filepath.name):
                filepath = candidate
                break
        if not filepath.exists():
            return {'success': False, 'error': f'Fichier {filepath} introuvable'}

        content = filepath.read_text(encoding='utf-8', errors='ignore')
        total_tokens = estimate_tokens(content)
        print(f'[{self.name}] Analyse de {filepath.name} ({len(content.splitlines())} lignes, ~{total_tokens} tokens)')

        if total_tokens <= 3000:
            return self._analyze_full(filepath, content, context)
        else:
            return self._analyze_chunked(filepath, content, context)

    def _analyze_full(self, filepath: Path, content: str, context: str) -> dict:
        prompt = f'''Analyse ce fichier de code en profondeur.
{f"Contexte : {context}" if context else ""}

FICHIER : {filepath.name}
CONTENU :
{content}

Fournis une analyse structurée avec :
1. RÉSUMÉ (ce que fait le fichier)
2. POINTS FORTS (ce qui est bien fait)
3. PROBLÈMES CRITIQUES (bugs, failles, erreurs)
4. AMÉLIORATIONS SUGGÉRÉES (prioritaires d'abord)
5. SCORE /10 global

Sois précis avec les numéros de lignes.'''

        analysis = self.llm.call(TaskType.ARCHITECTURE, prompt, temperature_override=0.3)
        return {
            'success': True,
            'file': str(filepath),
            'method': 'full',
            'analysis': analysis,
            'lines': len(content.splitlines())
        }

    def _analyze_chunked(self, filepath: Path, content: str, context: str) -> dict:
        chunks = chunk_text(content, chunk_tokens=2000, overlap_tokens=200)
        print(f'  Decoupage en {len(chunks)} chunks...')
        chunk_analyses = []
        for i, chunk in enumerate(chunks):
            print(f'  Analyse chunk {i+1}/{len(chunks)}...', end='', flush=True)
            prompt = f'''Analyse ce fragment de code (partie {i+1}/{len(chunks)} du fichier {filepath.name}).
Concentre-toi sur les problèmes visibles dans CE fragment.

{chunk["text"]}

Liste les problèmes trouvés (numéro de ligne relatif, sévérité, description).
Sois concis.'''
            analysis = self.llm.call(TaskType.CODE, prompt, temperature_override=0.2)
            chunk_analyses.append({'chunk': i + 1, 'analysis': analysis})
            print(' OK')

        synthesis_prompt = f'''Tu as analysé {len(chunks)} fragments du fichier {filepath.name}.
Voici les analyses de chaque fragment :

{chr(10).join(f"--- Chunk {c['chunk']} ---{chr(10)}{c['analysis']}" for c in chunk_analyses)}

Synthétise en :
1. RÉSUMÉ GLOBAL du fichier
2. TOP 5 PROBLÈMES les plus critiques (avec ligne approximative)
3. TOP 5 AMÉLIORATIONS prioritaires
4. SCORE /10'''

        synthesis = self.llm.call(TaskType.ARCHITECTURE, synthesis_prompt, temperature_override=0.3)
        return {
            'success': True,
            'file': str(filepath),
            'method': 'chunked',
            'chunks': len(chunks),
            'synthesis': synthesis,
            'chunk_analyses': chunk_analyses
        }

    def analyze_project(self, project_dir: Path) -> dict:
        print(f'[{self.name}] Analyse complete du projet {project_dir.name}...')
        files_to_analyze = []
        for ext in ['.py', '.ts', '.tsx', '.js']:
            for f in project_dir.rglob(f'*{ext}'):
                if 'node_modules' not in str(f) and 'test' not in f.name.lower():
                    files_to_analyze.append(f)

        results = []
        for filepath in files_to_analyze[:10]:
            result = self.analyze_file(filepath)
            results.append(result)

        return {
            'project': project_dir.name,
            'files_analyzed': len(results),
            'results': results
        }
