# MODIFIÉ: Import relatif
from .Kokoro import speak_mix 

class TTSProcessor:
    def __init__(self):
        self._running = True

    def speak_text(self, text_to_speak: str):
        if not self._running:
            # print("TTSProcessor est arrêté, synthèse ignorée.")
            return

        if not text_to_speak or not text_to_speak.strip():
            # print("TTSProcessor: Texte vide, rien à dire.")
            return
        
        try:
            speak_mix(str(text_to_speak) + "...", 
                      voice1="ff_siwis", voice2="if_sara", 
                      mix_ratio=0.85, speed=1.0, lang="fr-fr")
        except Exception as e:
            print(f"TTSProcessor: Erreur lors de la synthèse vocale: {e}")

    def stop(self):
        # print("TTSProcessor: Demande d'arrêt.")
        self._running = False