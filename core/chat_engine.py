import os
import re
import logging
import unicodedata
import warnings
from pathlib import Path
from core.conversation_state import ConversationState, EXPERT_ROLES, DOMAIN_SLOTS

# Configuration du logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(ch)

# Phrases de confirmation normalisées sous forme de regex compilée
CONFIRMATION_WORDS = [
    'oui genere', 'vas-y', 'lance la generation', 'cree le projet',
    'c est bon genere', 'go', 'oui', 'ok genere', 'genere maintenant',
    'lance', 'yes', 'ouais genere', 'parfait genere'
]

# Précompilation d'une regex pour la confirmation
_CONFIRMATION_REGEX = re.compile(
    r'\b(?:' + '|'.join(re.escape(p) for p in CONFIRMATION_WORDS) + r')\b',
    re.IGNORECASE
)

EXPLICIT_CREATE_PHRASES = [
    'cree ', 'genere ', 'developpe ', 'fais une app', 'fais un projet',
    'je veux une app', 'je veux un logiciel', 'construis ',
    'crée ', 'génère ', 'développe ',
]

# Compilation d'une regex pour la création explicite
_CREATE_REGEX = re.compile(
    r'(?:' + '|'.join(re.escape(p.strip()) for p in EXPLICIT_CREATE_PHRASES if p.strip()) + r')',
    re.IGNORECASE
)

# Regex pour détection de question
_QUESTION_REGEX = re.compile(r'\?')

# Regex pour détection de fichier (non utilisé ici mais conservé pour cohérence)
_FILE_KEYWORDS = ['analyse', 'analyse le fichier', 'lis le fichier', 'regarde le fichier', 'inspecte']
_FILE_PATTERN = re.compile(r'[\w/\-\\\.]+\.(py|ts|tsx|js|json|yml|yaml|html|txt|md)')
_GENERATED_DIRS = ['generated', 'output', 'src', 'data']

def _normalize(text: str) -> str:
    """
    Normalise un texte : minuscules, suppression des accents, remplacement des apostrophes.
    Version robuste utilisant unicodedata et str.replace.
    """
    if not isinstance(text, str):
        logger.warning("Texte non valide passé à _normalize : %s", type(text).__name__)
        return ""

    try:
        # Décomposition Unicode puis encodage ASCII (supprime accents)
        nfkd = unicodedata.normalize('NFKD', text)
        ascii_text = nfkd.encode('ASCII', 'ignore').decode('ASCII')
        # Suppression des apostrophes courbes et simples
        cleaned = ascii_text.replace("'", "").replace("`", "").replace("’", "")
        return cleaned.lower().strip()
    except Exception as e:
        logger.error("Erreur lors de la normalisation du texte : %s", e)
        # Fallback minimal
        return text.lower().strip()

class ChatEngine:
    def __init__(self):
        warnings.warn(
            "ChatEngine est déprécié — utilisez core.conversation_engine.ConversationEngine.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.state = ConversationState()
        self._client = None
        logger.info("ChatEngine initialisé")

    def _get_client(self):
        """
        Retourne le client OpenAI configuré (DeepSeek ou Anthropic).
        Gère les erreurs de configuration et les clés API vides.
        """
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except ImportError as e:
            logger.error("Module 'openai' non installé : %s", e)
            return None
        except Exception as e:
            logger.error("Erreur lors de l'import du module 'openai' : %s", e)
            return None

        api_key_deepseek = os.getenv('DEEPSEEK_API_KEY')
        api_key_anthropic = os.getenv('ANTHROPIC_API_KEY')

        if api_key_deepseek and api_key_deepseek.strip():
            try:
                self._client = OpenAI(
                    api_key=api_key_deepseek.strip(),
                    base_url='https://api.deepseek.com'
                )
                logger.info("Client OpenAI configuré pour DeepSeek")
            except Exception as e:
                logger.error("Erreur lors de la configuration du client DeepSeek : %s", e)
                return None
        elif api_key_anthropic and api_key_anthropic.strip():
            try:
                self._client = OpenAI(
                    api_key=api_key_anthropic.strip(),
                    base_url='https://api.anthropic.com/v1'
                )
                logger.info("Client OpenAI configuré pour Anthropic")
            except Exception as e:
                logger.error("Erreur lors de la configuration du client Anthropic : %s", e)
                return None
        else:
            logger.warning("Aucune clé API trouvée (DEEPSEEK_API_KEY ou ANTHROPIC_API_KEY)")

        return self._client

    def is_confirmation(self, text: str) -> bool:
        """
        Vérifie si le texte est une confirmation de génération.
        Utilise une regex précompilée pour une recherche efficace.
        """
        if not isinstance(text, str) or not text.strip():
            logger.debug("Texte vide ou non valide passé à is_confirmation")
            return False

        try:
            result = bool(_CONFIRMATION_REGEX.search(text))
            if result:
                logger.debug("Confirmation détectée dans le texte : %s", text[:50])
            return result
        except Exception as e:
            logger.error("Erreur lors de la vérification de confirmation : %s", e)
            return False

    def is_explicit_create(self, text: str) -> bool:
        """
        Vérifie si le texte exprime une demande explicite de création.
        Utilise une regex et vérifie l'absence de question ou de phrase trop courte.
        """
        if not isinstance(text, str) or not text.strip():
            logger.debug("Texte vide ou non valide passé à is_explicit_create")
            return False

        try:
            has_create = bool(_CREATE_REGEX.search(text))
            has_question = bool(_QUESTION_REGEX.search(text))
            is_short = len(text.split()) < 5
            result = has_create and not has_question and not is_short

            if result:
                logger.debug("Demande de création explicite détectée : %s", text[:50])
            return result
        except Exception as e:
            logger.error("Erreur lors de la vérification de création explicite : %s", e)
            return False