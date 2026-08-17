import json
from pathlib import Path
from core.multi_model_router import get_router
from core.learning_engine import get_learning_stats
from cyberia_sanitizer import strip_markdown_artifacts

class EvolutionAgent:
    def __init__(self):
        import uuid
        self.router = get_router()
        self.name = 'EVOLUTION'
        self.history = []
        self.pending_improvement = None
        self.improvements_applied = []
        self.session_id = f'evolution_{uuid.uuid4().hex[:6]}'
        self.session_transcript = []

    def _get_cyberia_context(self) -> str:
        stats = get_learning_stats()
        files = []
        for f in Path('.').rglob('*.py'):
            if 'generated' not in str(f) and '__pycache__' not in str(f):
                files.append(f.name)
        return (
            f'Tu es CYBERIA, une IA de generation de code.\n'
            f'Tes fichiers principaux : {", ".join(files[:20])}\n'
            f'Statistiques : {json.dumps(stats)}\n'
            f'Ameliorations deja appliquees : {self.improvements_applied}\n\n'
            'Tu dois proposer des ameliorations concretes a TON PROPRE CODE.\n'
            'Chaque amelioration doit etre :\n'
            '- Specifique (fichier + fonction + ligne)\n'
            '- Testable (on peut verifier que ca marche)\n'
            '- Reversible (backup avant modification)\n'
            '- Benefique (ameliore performance, qualite ou UX)'
        )

    def _analyze_weakness(self, user_message: str) -> str:
        context = self._get_cyberia_context()
        history_text = '\n'.join([f'{m["role"]}: {m["content"]}' for m in self.history[-6:]])
        prompt = (
            f'{context}\n\n'
            f'Conversation avec l\'utilisateur :\n'
            f'{history_text}\n'
            f'Utilisateur : {user_message}\n\n'
            'Analyse et propose UNE amelioration concrete et specifique.\n'
            'Format de ta reponse :\n\n'
            'ANALYSE : (ce que tu observes comme faiblesse)\n\n'
            'PROPOSITION : (ce que tu proposes exactement)\n'
            'Fichier : nom_fichier.py\n'
            'Modification : description precise\n'
            'Impact attendu : (ce qui sera ameliore)\n\n'
            'Veux-tu que j\'applique cette amelioration ?'
        )
        return self.router.call(prompt, task_type='analysis', temperature=0.5)

    def _generate_improvement_code(self, proposal: str, target_file: str) -> tuple[str, str]:
        """Retourne (code, raison_erreur). Si succes: (code, ''). Si echec: ('', raison)."""
        filepath = Path(target_file)
        if not filepath.exists():
            candidates = [f for f in Path('.').rglob(target_file) if 'generated' not in str(f)]
            if not candidates:
                return '', f'Fichier introuvable : "{target_file}" — aucun .py correspondant dans le projet'
            filepath = candidates[0]
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        print(f'[DEBUG] Génération du code pour {filepath} ({len(content)} chars)')
        prompt = (
            f'Applique cette amelioration au fichier {filepath.name} :\n\n'
            f'AMELIORATION PROPOSEE :\n{proposal}\n\n'
            f'CODE ACTUEL :\n{content[:5000]}\n\n'
            'Genere le fichier COMPLET ameliore.\n'
            'REGLES :\n'
            '- Garde TOUTES les fonctions existantes\n'
            '- Ameliore uniquement ce qui est propose\n'
            '- Code propre, commentaires si utile\n'
            '- AUCUN markdown, Python pur\n\n'
            'Genere UNIQUEMENT le code du fichier ameliore.'
        )
        result = self.router.call(prompt, task_type='fix', temperature=0.1)
        print(f'[DEBUG] LLM a retourné {len(result) if result else 0} chars')
        if not result or not result.strip():
            return '', 'Le LLM a retourné une réponse vide (quota, timeout ou refus du modèle)'
        return result, ''

    def _apply_improvement(self, filepath_str: str, new_code: str) -> dict:
        import ast, shutil
        from datetime import datetime
        filepath = None
        for f in Path('.').rglob(filepath_str):
            if 'generated' not in str(f) and '__pycache__' not in str(f):
                filepath = f
                break
        if not filepath or not filepath.exists():
            return {'success': False, 'error': f'Fichier {filepath_str} introuvable'}
        backup_dir = Path('.cyberia/evolution_backups')
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%H%M%S')
        backup = backup_dir / f'{filepath.stem}_{ts}{filepath.suffix}'
        shutil.copy2(filepath, backup)
        try:
            ast.parse(new_code)
        except SyntaxError as e:
            return {'success': False, 'error': f'Syntaxe invalide : {e}', 'backup': str(backup)}
        filepath.write_text(new_code, encoding='utf-8')
        return {'success': True, 'file': str(filepath), 'backup': str(backup), 'lines': len(new_code.splitlines())}

    def chat(self, user_input: str) -> tuple[str, str, bool]:
        self.history.append({'role': 'user', 'content': user_input})
        self.session_transcript.append(f'user: {user_input}')
        user_lower = user_input.lower().strip()

        # Commandes de validation
        if user_lower in ['oui', 'yes', 'applique', 'go', 'ok vas-y', 'valide']:
            if not self.pending_improvement:
                response = 'Aucune amelioration en attente. Dis-moi ce que tu veux ameliorer.'
                self.history.append({'role': 'assistant', 'content': response})
                return response, '', False
            pending = self.pending_improvement
            self.pending_improvement = None
            print(f'[DEBUG] Validation : fichier cible = "{pending["file"]}"')
            code, error_reason = self._generate_improvement_code(pending['proposal'], pending['file'])
            if not code:
                print(f'[DEBUG] _generate_improvement_code() vide — raison : {error_reason}')
                response = f'Impossible de generer le code.\nRaison : {error_reason}\n\nDis-moi ce que tu veux ameliorer et je reessaie.'
                self.history.append({'role': 'assistant', 'content': response})
                return response, '', False
            code = strip_markdown_artifacts(code)
            result = self._apply_improvement(pending['file'], code)
            if result['success']:
                self.improvements_applied.append(pending['summary'])
                from core.memory_hub import save_correction
                save_correction(self.session_id, f'Evolution: {pending["summary"][:150]} dans {result["file"]}')
                response = (
                    f'Amelioration appliquee avec succes !\n\n'
                    f'Fichier modifie : {result["file"]}\n'
                    f'{result["lines"]} lignes\n'
                    f'Backup sauvegarde : {result["backup"]}\n\n'
                    f'Qu\'est-ce que tu veux ameliorer d\'autre ?'
                )
                self.history.append({'role': 'assistant', 'content': response})
                return response, '', False
            else:
                response = f'Erreur lors de l\'application : {result.get("error")}\nVeux-tu que je propose une approche differente ?'
                self.history.append({'role': 'assistant', 'content': response})
                return response, '', False

        if user_lower in ['non', 'no', 'pas ca', 'autre chose', 'propose autre chose']:
            self.pending_improvement = None
            response = 'D\'accord. Dis-moi ce que tu veux ameliorer et je propose autre chose.'
            self.history.append({'role': 'assistant', 'content': response})
            return response, '', False

        if user_lower in ['menu', 'quitter', 'exit']:
            from core.memory_hub import extract_session_memories
            extract_session_memories(self.session_id, '\n'.join(self.session_transcript), mode='evolution')
            response = 'Session evolution terminee. Souvenirs extraits.'
            self.history.append({'role': 'assistant', 'content': response})
            return response, '', True

        if user_lower in ['annule', 'rollback', 'revenir en arriere'] and self.improvements_applied:
            response = (
                f'Pour annuler la derniere amelioration, les backups sont dans .cyberia/evolution_backups/\n'
                f'Ameliorations appliquees : {self.improvements_applied}'
            )
            return response, '', False

        if user_lower in ['bilan', 'statut', 'status', 'qu as-tu fait']:
            if self.improvements_applied:
                lines = '\n'.join(f'  - {a}' for a in self.improvements_applied)
                response = f'Ameliorations appliquees cette session :\n{lines}'
            else:
                response = 'Aucune amelioration appliquee encore. Dis-moi ce qui te derange dans CYBERIA !'
            return response, '', False

        # Analyser et proposer
        response = self._analyze_weakness(user_input)
        import re
        # Gère : "Fichier : nom.py", "Fichier : `nom.py`", "Fichier : 'nom.py'", "Fichier : \"nom.py\""
        file_match = re.search(r'Fichier\s*:\s*[`\'"]*\s*([\w/\.\-]+\.py)', response)
        if file_match:
            detected_file = file_match.group(1)
            self.pending_improvement = {
                'proposal': response,
                'file': detected_file,
                'summary': user_input[:50]
            }
            print(f'[DEBUG] pending_improvement défini sur "{detected_file}"')
        else:
            print(f'[DEBUG] Aucun "Fichier :" trouvé dans la réponse — pending_improvement non défini')
        self.history.append({'role': 'assistant', 'content': response})
        return response, '', False
