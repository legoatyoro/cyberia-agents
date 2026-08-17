from pathlib import Path
import logging
import os
from typing import List, Tuple

from core.llm_client import LLMClient
from core.context_manager import ContextManager
from schemas.agent_schemas import TaskType, AgentOutput, ArchitectureBlueprint
from cyberia_sanitizer import strip_markdown_artifacts, needs_reprompt

logger = logging.getLogger(__name__)

_ACTION_RULE = (
    'REGLE ABSOLUE : Tu es en MODE ACTION STRICT. '
    'Genere UNIQUEMENT du code. Zero explication. Zero commentaire. '
    'Zero markdown sauf les blocs de code. '
    'Le fichier genere doit etre immediatement executable.\n\n'
)

_MAX_RETRIES_ON_DIRTY_OUTPUT = 2
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class BuilderAgent:
    """Agent responsable de la génération des fichiers du projet selon un blueprint."""

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.name = 'BUILDER'
        self._generated_files: List[str] = []
        self._errors: List[str] = []

    def run(
        self,
        blueprint: ArchitectureBlueprint,
        project_dir: Path,
        ctx: ContextManager,
    ) -> AgentOutput:
        """Génère tous les fichiers listés dans le blueprint.

        Args:
            blueprint: Plan d'architecture décrivant les fichiers à créer.
            project_dir: Répertoire racine du projet.
            ctx: Gestionnaire de contexte pour l'historique de génération.

        Returns:
            AgentOutput contenant la liste des fichiers générés et les erreurs.
        """
        logger.info(
            '🔨 [%s] Génération de %d fichiers...',
            self.name,
            len(blueprint.files_to_create),
        )

        self._generated_files = []
        self._errors = []

        if not blueprint.files_to_create:
            logger.warning('Aucun fichier à générer dans le blueprint.')
            return AgentOutput(
                agent_name=self.name,
                success=True,
                artifacts={'generated': []},
                errors=[],
            )

        if not self._validate_project_directory(project_dir):
            error_msg = f"Le répertoire projet '{project_dir}' n'est pas valide ou accessible."
            logger.error('❌ %s', error_msg)
            return AgentOutput(
                agent_name=self.name,
                success=False,
                artifacts={'generated': []},
                errors=[error_msg],
            )

        for filename in blueprint.files_to_create:
            try:
                self._generate_single_file(filename, blueprint, project_dir, ctx)
                self._generated_files.append(filename)
                logger.info('✅ %s généré avec succès', filename)
            except Exception as exc:
                error_msg = f'{filename}: {exc}'
                self._errors.append(error_msg)
                logger.error('❌ %s', error_msg)

        ctx.save_to_disk()
        return AgentOutput(
            agent_name=self.name,
            success=len(self._errors) == 0,
            artifacts={'generated': self._generated_files},
            errors=self._errors,
        )

    def _validate_project_directory(self, project_dir: Path) -> bool:
        """Valide que le répertoire projet est accessible et peut être utilisé.

        Effectue une vérification légère via `os.access` après création du répertoire.
        Évite l'écriture inutile d'un fichier temporaire pour améliorer la performance.

        Args:
            project_dir: Chemin du répertoire projet.

        Returns:
            True si le répertoire est valide, False sinon.
        """
        try:
            if not project_dir.is_absolute():
                logger.warning(
                    "Le chemin '%s' n'est pas absolu, tentative de résolution...",
                    project_dir,
                )
                project_dir = project_dir.resolve()

            project_dir.mkdir(parents=True, exist_ok=True)

            # Vérifier les permissions d'écriture avec `os.access`
            if not os.access(str(project_dir), os.W_OK):
                logger.error(
                    "Permission d'écriture refusée dans '%s'", project_dir
                )
                return False

            return True
        except Exception as e:
            logger.error(
                "Erreur lors de la validation du répertoire '%s': %s",
                project_dir,
                e,
            )
            return False

    def _generate_single_file(
        self,
        filename: str,
        blueprint: ArchitectureBlueprint,
        project_dir: Path,
        ctx: ContextManager,
    ) -> None:
        """Génère un fichier unique, avec nettoyage et retry automatique.

        Inclut une vérification de la taille du code généré avant écriture.

        Args:
            filename: Chemin relatif du fichier dans le projet.
            blueprint: Blueprint contenant les métadonnées du projet.
            project_dir: Répertoire racine.
            ctx: Contexte pour enrichir le prompt.

        Raises:
            ValueError: En cas d'échec après les retries ou de dépassement de taille.
            IOError: En cas d'erreur d'écriture du fichier.
        """
        logger.debug('📄 Début de génération pour %s', filename)

        if not filename or '..' in filename:
            raise ValueError(f"Nom de fichier invalide: '{filename}'")

        context = ctx.get_context_for_file(filename)
        prompt = self._build_prompt(filename, blueprint, context)

        code = self._safe_llm_call(prompt)
        code = strip_markdown_artifacts(code)

        # Retry si le résultat est encore "sale"
        for attempt in range(_MAX_RETRIES_ON_DIRTY_OUTPUT):
            if not needs_reprompt(code):
                break
            logger.warning(
                '⚠️  Fichier %s : code non conforme, reprise avec consigne renforcée '
                '(tentative %d/%d)',
                filename,
                attempt + 1,
                _MAX_RETRIES_ON_DIRTY_OUTPUT,
            )
            code = self._safe_llm_call(prompt, enforce=True)
            code = strip_markdown_artifacts(code)
        else:
            # Si après tous les retries le code est toujours invalide
            raise ValueError(
                f"Échec de génération pour '{filename}' après "
                f"{_MAX_RETRIES_ON_DIRTY_OUTPUT} retries."
            )

        # Vérification de la taille du code
        code_size = len(code.encode('utf-8'))
        if code_size > _MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"Le code généré pour '{filename}' dépasse la limite de "
                f"{_MAX_FILE_SIZE_BYTES} octets ({code_size} octets)."
            )

        # Écriture du fichier
        file_path = project_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_path.write_text(code, encoding='utf-8')
        except (IOError, OSError) as e:
            raise IOError(f"Erreur d'écriture du fichier {file_path}: {e}") from e

    def _build_prompt(
        self,
        filename: str,
        blueprint: ArchitectureBlueprint,
        context: str,
    ) -> str:
        """Construit le prompt complet pour la génération d'un fichier.

        Args:
            filename: Nom du fichier à générer.
            blueprint: Blueprint contenant les spécifications du projet.
            context: Contexte additionnel pour guider la génération.

        Returns:
            Prompt formaté pour le LLM.
        """
        prompt = (
            f"{_ACTION_RULE}"
            f"Projet : {blueprint.project_name}\n"
            f"Description : {blueprint.description}\n"
            f"Fichier à générer : {filename}\n"
            f"Contexte :\n{context}\n"
            f"Génère le code complet du fichier {filename}."
        )
        return prompt

    def _safe_llm_call(self, prompt: str, enforce: bool = False) -> str:
        """Appelle le LLM en gérant les exceptions et le timeout.

        Args:
            prompt: Prompt à envoyer.
            enforce: Si True, ajoute une consigne supplémentaire pour forcer la
                     génération de code propre.

        Returns:
            Réponse textuelle du LLM.
        """
        if enforce:
            prompt = (
                "CONSIGNE RENFORCEE : Tu dois absolument générer uniquement du code "
                "valide, sans aucun texte explicatif ni commentaire superflu.\n\n" +
                prompt
            )
        try:
            response = self.llm.generate(conversation_history=[], prompt=prompt)
            return str(response)
        except Exception as e:
            logger.error("Erreur lors de l'appel LLM : %s", e)
            raise RuntimeError(f"Échec de l'appel LLM : {e}") from e


# Alias de compatibilité
Builder = BuilderAgent