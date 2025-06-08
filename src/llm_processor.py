import emoji
# nest_asyncio n'est généralement pas nécessaire si Langchain est utilisé de manière synchrone
# Si vous rencontrez des problèmes d'event loop, vous pouvez le décommenter.
# import nest_asyncio
# nest_asyncio.apply()

# MODIFIÉ: Import relatif explicite car llm_langchain_logic est dans le même package (src)
from .llm_langchain_logic import process_user_input_langchain, NEW_FACE_REQUEST_LANGCHAIN

def remove_emojis_fn(text):
    if text:
        return emoji.replace_emoji(text, replace='')
    return ""

class LLMProcessor:
    def __init__(self):
        self._running = True
        # Pas de modèle ou d'instance de chat ici, tout est géré par llm_langchain_logic

    def process_input(self, texte_utilisateur_brut: str, emotion_utilisateur_detectee: str, prenom_utilisateur: str):
        """
        Traite l'entrée utilisateur en utilisant la logique Langchain.
        Retourne: (ai_response_text, ai_detected_emotion, conversation_should_end, face_request_triggered)
        """
        if not self._running:
            print("LLMProcessor est arrêté, entrée ignorée.")
            return "LLM arrêté.", "neutre", False, False

        # print(f"\n--- LLMProcessor: Traitement. Prénom: {prenom_utilisateur}, Emotion: {emotion_utilisateur_detectee}, Texte: '{texte_utilisateur_brut}' ---")
        
        try:
            ai_response_text, ai_detected_emotion, conversation_should_end, face_request_triggered_logic = \
                process_user_input_langchain(
                    user_query_raw=texte_utilisateur_brut,
                    user_name=prenom_utilisateur,
                    user_detected_emotion=emotion_utilisateur_detectee
                )
            
            final_response_cleaned = remove_emojis_fn(ai_response_text)
            
            # print(f"LLMProcessor: Réponse finale: '{final_response_cleaned}', Émotion IA: '{ai_detected_emotion}'")
            return final_response_cleaned, ai_detected_emotion, conversation_should_end, face_request_triggered_logic

        except Exception as e:
            print(f"LLMProcessor: Erreur critique lors de l'appel à process_user_input_langchain: {e}")
            error_message = f"Désolé {prenom_utilisateur}, une erreur interne s'est produite."
            return error_message, "tristesse", False, False

    def stop(self):
        print("LLMProcessor: Demande d'arrêt.")
        self._running = False