import ast
import json
import logging
from pathlib import Path
from collections import deque
from typing import Dict, List, Set, Optional
from hashlib import sha256

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Gère le contexte des fichiers générés : fenêtre glissante des derniers fichiers,
    table des symboles, et autorité du schéma.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.sliding_window: deque = deque(maxlen=3)
        self.symbol_table: Dict[str, List[str]] = {}
        self.schema_authority: Dict = {}
        self._content_hashes: Dict[str, str] = {}
        self._ast_cache: Dict[str, ast.Module] = {}
        # Dictionnaire associant le hash du contenu à chaque arbre en cache
        self._ast_cache_hashes: Dict[str, str] = {}

    def add_generated_file(self, filepath: Path, content: str) -> None:
        """Ajoute un fichier généré au contexte."""
        logger.info("Ajout du fichier %s au contexte", filepath)

        try:
            truncated = self._smart_truncate(content, max_length=2000)
        except Exception as e:
            logger.warning("Erreur lors de la troncature intelligente de %s : %s", filepath, e)
            truncated = content[:2000]

        self.sliding_window.append({'path': str(filepath), 'content': truncated})
        self._update_symbol_table(filepath, content)

    def _smart_truncate(self, content: str, max_length: int) -> str:
        """
        Troncature intelligente qui respecte les limites syntaxiques.
        Coupe à la fin d'une ligne ou d'un bloc si possible.
        """
        if len(content) <= max_length:
            return content

        truncated = content[:max_length]

        # Chercher le dernier saut de ligne dans la zone de troncature
        last_newline = truncated.rfind('\n')
        if last_newline > max_length * 0.8:
            truncated = truncated[:last_newline]

        # Vérifier si on coupe au milieu d'une structure
        open_brackets = truncated.count('{') - truncated.count('}')
        open_parens = truncated.count('(') - truncated.count(')')
        open_brackets_sq = truncated.count('[') - truncated.count(']')

        if open_brackets > 0 or open_parens > 0 or open_brackets_sq > 0:
            # Ajouter un commentaire indiquant la troncature
            truncated += '\n# ... [TRONCATURE]'

        return truncated

    def _get_content_hash(self, content: str) -> str:
        """Calcule un hash SHA256 du contenu pour détecter les changements."""
        return sha256(content.encode('utf-8')).hexdigest()

    def _update_symbol_table(self, filepath: Path, content: str) -> None:
        """
        Met à jour la table des symboles à partir du contenu du fichier.
        Seuls les symboles pertinents (définitions de classes, fonctions,
        assignations de haut niveau) sont extraits.
        Utilise un cache pour éviter de reparser les fichiers inchangés.
        """
        filename = filepath.name

        # Vérifier si le contenu a changé
        current_hash = self._get_content_hash(content)
        previous_hash = self._content_hashes.get(filename)

        if previous_hash == current_hash:
            logger.debug("Contenu inchangé pour %s, parsing ignoré", filename)
            # Récupérer l'arbre depuis le cache s'il existe
            if filename in self._ast_cache and self._ast_cache_hashes.get(filename) == current_hash:
                tree = self._ast_cache[filename]
            else:
                # Le cache n'est pas à jour (cas improbable), on parse quand même
                tree = self._parse_content(content, filename)
                if tree is not None:
                    self._ast_cache[filename] = tree
                    self._ast_cache_hashes[filename] = current_hash
            if tree is None:
                return
        else:
            # Le contenu a changé, on parse et on met à jour le cache
            self._content_hashes[filename] = current_hash
            tree = self._parse_content(content, filename)
            if tree is not None:
                self._ast_cache[filename] = tree
                self._ast_cache_hashes[filename] = current_hash
            else:
                logger.error("Échec du parsing de %s, table des symboles non mise à jour", filename)
                return

        symbols: Set[str] = set()

        try:
            # Parcours des nœuds de premier niveau seulement
            for node in tree.body:
                # Classes et fonctions (définitions)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(node.name)
                    # Pour les classes, on extrait aussi les attributs de classe
                    if isinstance(node, ast.ClassDef):
                        for inner in node.body:
                            if isinstance(inner, ast.Assign):
                                for target in inner.targets:
                                    if isinstance(target, ast.Name):
                                        symbols.add(target.id)
                # Assignations globales (au niveau du module)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            symbols.add(target.id)
        except Exception as e:
            logger.error("Erreur lors de l'extraction des symboles de %s : %s", filename, e)
            return

        # Mise à jour de la table
        self.symbol_table[filename] = list(symbols)
        logger.debug("Symboles extraits de %s : %s", filename, symbols)

    def _parse_content(self, content: str, filename: str) -> Optional[ast.Module]:
        """Parse le contenu AST avec gestion d'erreur améliorée."""
        try:
            tree = ast.parse(content)
            logger.debug("Parsing AST réussi pour %s", filename)
            return tree
        except SyntaxError as e:
            logger.warning("Erreur de syntaxe lors du parsing de %s : %s", filename, e)
            return None
        except MemoryError as e:
            logger.error("Mémoire insuffisante pour parser %s : %s", filename, e)
            return None
        except Exception as e:
            logger.error("Erreur inattendue lors du parsing de %s : %s", filename, e)
            return None

    def _verify_ast_cache(self, cached_tree: ast.Module, content: str) -> bool:
        """
        Vérifie rapidement si le cache AST est encore valide.
        Compare la structure de base du code.
        """
        try:
            lines = content.split('\n')
            if len(lines) < 3:
                return False
            first_node = cached_tree.body[0] if cached_tree.body else None
            if first_node is None:
                return False
            return True
        except Exception:
            return False

    def get_context_for_file(self, target_filename: str) -> str:
        """
        Construit une chaîne de contexte pour un fichier cible.
        Inclut le schéma source de vérité, les symboles disponibles selon
        des critères de pertinence, et la fenêtre glissante des fichiers récents.
        """
        context_parts: List[str] = []

        # Schéma source de vérité
        if self.schema_authority:
            try:
                schema_str = json.dumps(self.schema_authority, indent=2, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                logger.error("Erreur de sérialisation du schéma : %s", e)
                schema_str = str(self.schema_authority)
            except Exception as e:
                logger.error("Erreur inattendue lors de la sérialisation du schéma : %s", e)
                schema_str = str(self.schema_authority)
            context_parts.append(f'=== SCHEMA SOURCE DE VÉRITÉ ===\n{schema_str}')

        # Filtrage des symboles pertinents
        relevant_symbols: Dict[str, List[str]] = {}

        try:
            target_is_core = any(kw in target_filename for kw in ['route', 'main', 'test', 'schema'])
            for fname, syms in self.symbol_table.items():
                if target_is_core:
                    if any(kw in fname for kw in ['model', 'schema', 'db']):
                        relevant_symbols[fname] = syms
                else:
                    relevant_symbols[fname] = syms
        except Exception as e:
            logger.error("Erreur lors du filtrage des symboles pour %s : %s", target_filename, e)
            relevant_symbols = dict(self.symbol_table)

        if relevant_symbols:
            try:
                sym_str = json.dumps(relevant_symbols, indent=2)
            except (TypeError, ValueError) as e:
                logger.error("Erreur de sérialisation des symboles : %s", e)
                sym_str = str(relevant_symbols)
            except Exception as e:
                logger.error("Erreur inattendue lors de la sérialisation des symboles : %s", e)
                sym_str = str(relevant_symbols)
            context_parts.append(f'=== SYMBOLES DISPONIBLES ===\n{sym_str}')

        # Fenêtre glissante
        try:
            for item in self.sliding_window:
                context_parts.append(f'=== FICHIER RÉCENT : {item["path"]} ===\n{item["content"]}')
        except KeyError as e:
            logger.error("Erreur de structure dans la fenêtre glissante : %s", e)
        except Exception as e:
            logger.error("Erreur inattendue lors de la lecture de la fenêtre glissante : %s", e)

        return '\n\n'.join(context_parts)

    def save_to_disk(self) -> None:
        """Sauvegarde la table des symboles et le schéma sur le disque."""
        cache_dir = self.project_dir / '.cyberia_cache'

        try:
            cache_dir.mkdir(exist_ok=True, parents=True)
        except PermissionError as e:
            logger.error("Permission refusée pour créer le répertoire cache %s : %s", cache_dir, e)
            return
        except OSError as e:
            logger.error("Impossible de créer le répertoire cache %s : %s", cache_dir, e)
            return

        try:
            symbol_file = cache_dir / 'symbol_table.json'
            symbol_file.write_text(
                json.dumps(self.symbol_table, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            logger.debug("Table des symboles sauvegardée dans %s", symbol_file)
        except (OSError, IOError) as e:
            logger.error("Erreur d'écriture de symbol_table.json : %s", e)
        except (TypeError, ValueError) as e:
            logger.error("Erreur de sérialisation de symbol_table.json : %s", e)

        try:
            schema_file = cache_dir / 'schema_authority.json'
            schema_file.write_text(
                json.dumps(self.schema_authority, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            logger.debug("Schéma sauvegardé dans %s", schema_file)
        except (OSError, IOError) as e:
            logger.error("Erreur d'écriture de schema_authority.json : %s", e)
        except (TypeError, ValueError) as e:
            logger.error("Erreur de sérialisation de schema_authority.json : %s", e)

    def clear_cache(self) -> None:
        """Nettoie les caches internes."""
        self._content_hashes.clear()
        self._ast_cache.clear()
        logger.debug("Caches internes nettoyés")