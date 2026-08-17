import asyncio
from typing import Optional, Dict, Any
from pydantic import BaseModel, ValidationError
from schemas.agent_schemas import AgentOutput
from core.event_bus import EventBus, Event


class ParsedIntent(BaseModel):
    """Modèle pour l'intention parsée"""
    intent: str
    entities: Dict[str, Any]
    confidence: float
    raw_text: str


class SpeechParserAgent:
    """
    Agent responsable de l'analyse sémantique des messages texte.
    Extrait l'intention, les entités nommées et valide la structure.
    """
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.name = "SPEECH_PARSER"
        self.log_prefix = f"[{self.name}]"
        
    async def run(self) -> None:
        """Méthode principale d'exécution de l'agent"""
        print(f"{self.log_prefix} Agent démarré, abonnement aux événements MESSAGE_FORWARDED")
        
        # S'abonner aux événements MESSAGE_FORWARDED
        await self.event_bus.subscribe("MESSAGE_FORWARDED", self._handle_message)
        
        # Boucle principale pour maintenir l'agent actif
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print(f"{self.log_prefix} Agent arrêté proprement")
        except Exception as e:
            print(f"{self.log_prefix} Erreur fatale: {e}")
            raise
    
    async def _handle_message(self, event: Event) -> None:
        """
        Gère un événement MESSAGE_FORWARDED entrant.
        
        Args:
            event: L'événement contenant le message à analyser
        """
        print(f"{self.log_prefix} Réception d'un événement: {event.event_type}")
        
        try:
            # Extraire le message texte de l'événement
            message_text = event.data.get("message_texte")
            if not message_text:
                print(f"{self.log_prefix} Aucun message texte trouvé dans l'événement")
                return
            
            print(f"{self.log_prefix} Analyse du message: '{message_text[:50]}...'")
            
            # Analyser le message
            parsed_result = await self._parse_message(message_text)
            
            # Valider la structure
            validation_result = self._validate_parsed(parsed_result)
            
            if not validation_result["valid"]:
                print(f"{self.log_prefix} Échec de validation: {validation_result['errors']}")
                return
            
            # Publier l'événement INTENT_PARSED
            await self._publish_intent_parsed(parsed_result)
            
            print(f"{self.log_prefix} Intention parsée avec succès: {parsed_result.intent}")
            
        except ValidationError as e:
            print(f"{self.log_prefix} Erreur de validation Pydantic: {e}")
        except Exception as e:
            print(f"{self.log_prefix} Erreur lors du traitement: {e}")
    
    async def _parse_message(self, message_text: str) -> ParsedIntent:
        """
        Analyse le message texte pour extraire l'intention et les entités.
        
        Args:
            message_text: Le texte du message à analyser
            
        Returns:
            ParsedIntent: L'intention parsée avec ses entités
        """
        # Logique d'analyse sémantique (simplifiée pour l'exemple)
        # Dans un cas réel, cela pourrait utiliser NLP, regex, etc.
        
        # Extraction basique d'intention par mots-clés
        intent = self._extract_intent(message_text)
        entities = self._extract_entities(message_text)
        confidence = self._calculate_confidence(message_text, intent, entities)
        
        return ParsedIntent(
            intent=intent,
            entities=entities,
            confidence=confidence,
            raw_text=message_text
        )
    
    def _extract_intent(self, text: str) -> str:
        """
        Extrait l'intention principale du texte.
        
        Args:
            text: Le texte à analyser
            
        Returns:
            str: L'intention détectée
        """
        text_lower = text.lower()
        
        # Règles simples de détection d'intention
        if any(word in text_lower for word in ["bonjour", "salut", "hello"]):
            return "GREETING"
        elif any(word in text_lower for word in ["aide", "help", "comment"]):
            return "HELP_REQUEST"
        elif any(word in text_lower for word in ["merci", "thanks", "thank"]):
            return "THANKS"
        elif any(word in text_lower for word in ["au revoir", "bye", "adieu"]):
            return "GOODBYE"
        else:
            return "GENERAL_QUERY"
    
    def _extract_entities(self, text: str) -> Dict[str, Any]:
        """
        Extrait les entités nommées du texte.
        
        Args:
            text: Le texte à analyser
            
        Returns:
            Dict[str, Any]: Dictionnaire des entités extraites
        """
        entities = {}
        
        # Extraction basique d'entités (simplifiée)
        words = text.split()
        
        # Détection de nombres
        import re
        numbers = re.findall(r'\d+', text)
        if numbers:
            entities["numbers"] = [int(n) for n in numbers]
        
        # Détection de mots en majuscules (potentiels noms propres)
        proper_nouns = [word for word in words if word[0].isupper() and len(word) > 1]
        if proper_nouns:
            entities["proper_nouns"] = proper_nouns
        
        # Longueur du message comme métadonnée
        entities["word_count"] = len(words)
        entities["char_count"] = len(text)
        
        return entities
    
    def _calculate_confidence(self, text: str, intent: str, entities: Dict[str, Any]) -> float:
        """
        Calcule un score de confiance pour l'analyse.
        
        Args:
            text: Le texte original
            intent: L'intention détectée
            entities: Les entités extraites
            
        Returns:
            float: Score de confiance entre 0 et 1
        """
        confidence = 0.5  # Score de base
        
        # Ajustement basé sur la longueur du texte
        if len(text) > 10:
            confidence += 0.1
        
        # Ajustement basé sur la présence d'entités
        if entities:
            confidence += 0.1 * min(len(entities) / 3, 0.3)
        
        # Ajustement basé sur l'intention spécifique
        if intent in ["GREETING", "GOODBYE"]:
            confidence += 0.2
        elif intent == "HELP_REQUEST":
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _validate_parsed(self, parsed: ParsedIntent) -> Dict[str, Any]:
        """
        Valide la structure du message parsé.
        
        Args:
            parsed: L'objet ParsedIntent à valider
            
        Returns:
            Dict[str, Any]: Résultat de la validation
        """
        errors = []
        
        # Validation de l'intention
        valid_intents = ["GREETING", "HELP_REQUEST", "THANKS", "GOODBYE", "GENERAL_QUERY"]
        if parsed.intent not in valid_intents:
            errors.append(f"Intention invalide: {parsed.intent}")
        
        # Validation de la confiance
        if not 0 <= parsed.confidence <= 1:
            errors.append(f"Score de confiance invalide: {parsed.confidence}")
        
        # Validation du texte brut
        if not parsed.raw_text or len(parsed.raw_text.strip()) == 0:
            errors.append("Texte brut vide")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
    
    async def _publish_intent_parsed(self, parsed: ParsedIntent) -> None:
        """
        Publie un événement INTENT_PARSED avec les résultats de l'analyse.
        
        Args:
            parsed: L'intention parsée à publier
        """
        # Créer l'événement de sortie
        output_event = Event(
            event_type="INTENT_PARSED",
            data={
                "intent_parsed_event": {
                    "intent": parsed.intent,
                    "entities": parsed.entities,
                    "confidence": parsed.confidence,
                    "raw_text": parsed.raw_text
                }
            },
            source=self.name
        )
        
        # Publier l'événement
        await self.event_bus.publish(output_event)
        print(f"{self.log_prefix} Événement INTENT_PARSED publié")
    
    async def process_message(self, message_text: str) -> AgentOutput:
        """
        Méthode utilitaire pour traiter un message directement (sans événement).
        
        Args:
            message_text: Le texte du message à analyser
            
        Returns:
            AgentOutput: Le résultat de l'analyse
        """
        try:
            print(f"{self.log_prefix} Traitement direct du message")
            
            # Analyser le message
            parsed = await self._parse_message(message_text)
            
            # Valider
            validation = self._validate_parsed(parsed)
            
            if not validation["valid"]:
                return AgentOutput(
                    success=False,
                    data={"errors": validation["errors"]},
                    error="Validation échouée"
                )
            
            # Publier l'événement
            await self._publish_intent_parsed(parsed)
            
            return AgentOutput(
                success=True,
                data={
                    "intent": parsed.intent,
                    "entities": parsed.entities,
                    "confidence": parsed.confidence
                }
            )
            
        except Exception as e:
            print(f"{self.log_prefix} Erreur lors du traitement direct: {e}")
            return AgentOutput(
                success=False,
                data={},
                error=str(e)
            )