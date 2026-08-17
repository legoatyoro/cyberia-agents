import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Optional
from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType, AgentOutput, FixLog
from cyberia_validator import validate_imports, auto_fix_imports
from cyberia_sanitizer import strip_markdown_artifacts

_ACTION_RULE = (
    'REGLE ABSOLUE : Tu es en MODE ACTION STRICT. '
    'Corrige UNIQUEMENT le code demande. Zero explication. Zero commentaire. '
    'Retourne le fichier complet corrige, immediatement executable.\n\n'
)

class FixerAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'FIXER'
        self.logger = logging.getLogger(self.name)
        self._file_cache: Dict[Path, str] = {}
        self._processed_errors: set = set()

    def _clear_cache(self):
        """Nettoie le cache de fichiers entre les cycles."""
        self._file_cache.clear()

    def _read_file_with_cache(self, filepath: Path) -> Optional[str]:
        """Lit un fichier avec mise en cache pour éviter les lectures redondantes."""
        try:
            if filepath not in self._file_cache:
                self._file_cache[filepath] = filepath.read_text(encoding='utf-8')
            return self._file_cache[filepath]
        except FileNotFoundError:
            self.logger.warning(f"  ⚠️ Fichier introuvable: {filepath.name}")
            return None
        except PermissionError:
            self.logger.warning(f"  ⚠️ Permission refusée: {filepath.name}")
            return None
        except UnicodeDecodeError:
            self.logger.warning(f"  ⚠️ Erreur d'encodage: {filepath.name}")
            return None
        except Exception as e:
            self.logger.error(f"  ⚠️ Erreur inattendue lors de la lecture de {filepath.name}: {e}")
            return None

    def _write_file_safe(self, filepath: Path, content: str) -> bool:
        """Écrit un fichier avec gestion d'erreur robuste."""
        try:
            # Créer le répertoire parent si nécessaire
            filepath.parent.mkdir(parents=True, exist_ok=True)
            # Écrire dans un fichier temporaire puis renommer pour atomicité
            temp_path = filepath.with_suffix('.tmp')
            temp_path.write_text(content, encoding='utf-8')
            temp_path.rename(filepath)
            # Mettre à jour le cache
            self._file_cache[filepath] = content
            return True
        except PermissionError:
            self.logger.error(f"  ⚠️ Permission refusée pour écrire {filepath.name}")
            return False
        except OSError as e:
            self.logger.error(f"  ⚠️ Erreur d'écriture pour {filepath.name}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"  ⚠️ Erreur inattendue lors de l'écriture de {filepath.name}: {e}")
            return False

    def _build_error_prompt(self, file_errors: List[Dict]) -> str:
        """Construit un prompt d'erreur structuré et informatif."""
        error_details = []
        for i, err in enumerate(file_errors, 1):
            detail_parts = [
                f"Erreur {i} : import de \"{err.get('missing', 'inconnu')}\"",
                f"depuis \"{err.get('from', 'inconnu')}\"",
                f"— symbole introuvable."
            ]
            if err.get('available'):
                detail_parts.append(f"\nSymboles disponibles dans {err.get('from')} : {err['available']}")
            if err.get('line'):
                detail_parts.append(f"\nLigne approximative : {err['line']}")
            error_details.append(' '.join(detail_parts))
        return '\n'.join(error_details)

    def _get_adaptive_content(self, content: str, max_chars: int = 3000) -> str:
        """Récupère le contenu avec une stratégie adaptative pour les longs fichiers."""
        if len(content) <= max_chars:
            return content
        
        # Pour les fichiers longs, prendre le début et la fin
        half_chars = max_chars // 2
        start = content[:half_chars]
        end = content[-half_chars:]
        return f"{start}\n\n[... {len(content) - max_chars} caractères omis ...]\n\n{end}"

    def _validate_errors(self, errors: List[Dict]) -> List[Dict]:
        """Valide et filtre les erreurs de manière robuste."""
        valid_errors = []
        for error in errors:
            if not isinstance(error, dict):
                self.logger.warning(f"  ⚠️ Erreur ignorée (format invalide): {error}")
                continue
            if not error.get('file', '').endswith('.py'):
                continue
            if not error.get('missing') or not error.get('from'):
                self.logger.warning(f"  ⚠️ Erreur ignorée (champs manquants): {error}")
                continue
            valid_errors.append(error)
        return valid_errors

    def run(self, project_dir: Path, validation_errors: list, max_cycles: int = 3) -> AgentOutput:
        self.logger.info(f"🔧 [{self.name}] {len(validation_errors)} erreurs à corriger...")
        
        fix_logs = []
        remaining_errors = list(validation_errors)
        temperatures = [0.2, 0.35, 0.5]
        
        # Initialiser le suivi des erreurs traitées
        self._processed_errors.clear()

        for cycle in range(max_cycles):
            if not remaining_errors:
                self.logger.info(f"  ✅ Toutes les erreurs corrigées au cycle {cycle}")
                break

            temp = temperatures[min(cycle, len(temperatures) - 1)]
            self.logger.info(f"  🔄 Cycle {cycle+1}/{max_cycles} (température={temp})")

            # 1) Tentative de correction automatique des imports (optimisée)
            try:
                auto_fixed = auto_fix_imports(project_dir, remaining_errors)
                if auto_fixed:
                    self.logger.info(f"  ✅ {auto_fixed} erreurs auto-corrigées")
            except Exception as e:
                self.logger.error(f"  ⚠️ Échec de l'auto-correction: {e}")
                auto_fixed = 0

            # 2) Erreurs persistantes (non auto-corrigées)
            still_broken = [e for e in remaining_errors if e.get('suggestion') is None]
            
            # Filtrer les erreurs déjà traitées
            new_errors = []
            for error in still_broken:
                error_key = (error.get('file', ''), error.get('missing', ''), error.get('from', ''))
                if error_key not in self._processed_errors:
                    new_errors.append(error)
                    self._processed_errors.add(error_key)
            
            if not new_errors:
                self.logger.info("  ℹ️ Aucune nouvelle erreur à traiter")
                continue

            # 3) Regrouper les erreurs par fichier pour éviter les lectures redondantes
            errors_by_file = defaultdict(list)
            for error in new_errors:
                filepath = project_dir / error['file']
                if filepath.exists():
                    errors_by_file[filepath].append(error)
                else:
                    self.logger.warning(f"  ⚠️ Fichier non trouvé: {error['file']}")

            # 4) Correction LLM par fichier (une seule lecture/écriture par fichier)
            fixes_applied = []
            for filepath, file_errors in errors_by_file.items():
                # Lire le fichier avec cache
                content = self._read_file_with_cache(filepath)
                if content is None:
                    continue

                # Construire un prompt listant toutes les erreurs du fichier
                error_prompt = self._build_error_prompt(file_errors)
                
                # Contexte des cycles précédents
                prev_diff = ''
                if cycle > 0 and file_errors:
                    prev_diff = f'\nErreurs du cycle précédent : {json.dumps(file_errors[0])}'

                # Contenu adaptatif pour les longs fichiers
                adaptive_content = self._get_adaptive_content(content)

                prompt = (
                    f'Corrige ces erreurs dans le fichier {filepath.name} :{prev_diff}\n\n'
                    f'{error_prompt}\n\n'
                    f'Code actuel du fichier :\n{adaptive_content}\n\n'
                    'Retourne UNIQUEMENT le fichier corrigé, sans markdown.'
                )

                try:
                    # Appel LLM avec timeout et retry
                    fixed = self.llm.call(
                        TaskType.FIX, 
                        prompt, 
                        temperature_override=temp,
                        max_retries=2
                    )
                    
                    if not fixed or len(fixed.strip()) < 10:
                        self.logger.warning(f"  ⚠️ Réponse LLM vide ou trop courte pour {filepath.name}")
                        continue
                    
                    corrected_content = strip_markdown_artifacts(fixed)
                    
                    if self._write_file_safe(filepath, corrected_content):
                        self.logger.info(f"  ✅ Fichier {filepath.name} corrigé ({len(file_errors)} erreur(s))")
                        fixes_applied.append(str(filepath.name))
                    else:
                        self.logger.error(f"  ❌ Échec d'écriture pour {filepath.name}")
                        
                except TimeoutError:
                    self.logger.error(f"  ⚠️ Timeout LLM pour {filepath.name}")
                except ValueError as e:
                    self.logger.error(f"  ⚠️ Erreur de validation pour {filepath.name}: {e}")
                except Exception as e:
                    self.logger.error(f"  ⚠️ Correction échouée pour {filepath.name}: {e}")

            # 5) Re-valider et mettre à jour les erreurs restantes
            try:
                remaining_errors = validate_imports(project_dir)
                remaining_errors = self._validate_errors(remaining_errors)
            except Exception as e:
                self.logger.error(f"  ⚠️ Échec de la re-validation: {e}")
                remaining_errors = []

            self.logger.info(f'  🔍 {len(remaining_errors)} erreurs Python restantes')
            
            # Journalisation du cycle
            fix_logs.append(FixLog(
                cycle=cycle + 1,
                temperature_used=temp,
                errors_before=len(validation_errors),
                errors_after=len(remaining_errors),
                fixes_applied=fixes_applied if fixes_applied else ['auto:' + str(auto_fixed)]
            ).dict())
            
            self.logger.info(f"  → Erreurs restantes après cycle {cycle+1}: {len(remaining_errors)}")
            
            # Vider le cache pour le prochain cycle
            self._clear_cache()

        # Résultat final
        success = len(remaining_errors) == 0
        self.logger.info(f"  {'✅' if success else '❌'} Correction terminée: {len(remaining_errors)} erreurs restantes")
        
        return AgentOutput(
            agent_name=self.name,
            success=success,
            artifacts={
                'fix_logs': fix_logs, 
                'remaining_errors': remaining_errors,
                'total_cycles': len(fix_logs)
            },
            errors=[str(e) for e in remaining_errors]
        )