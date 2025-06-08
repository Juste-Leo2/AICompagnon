import pyaudio
from vosk import Model, KaldiRecognizer
import json
import threading
import queue
import time
import os

def init_vosk_model(model_path):
    """Charge et retourne le modèle Vosk"""
    try:
        print(f"Vosk: Chargement du modèle depuis {model_path}...")
        # Vérifier si le chemin du modèle existe et est un dossier
        if not os.path.exists(model_path) or not os.path.isdir(model_path):
            raise RuntimeError(f"Le chemin du modèle Vosk '{model_path}' n'existe pas ou n'est pas un dossier.")
        model = Model(model_path)
        print("Vosk: Modèle chargé avec succès.")
        return model
    except Exception as e:
        print(f"Vosk: ERREUR lors du chargement du modèle Vosk: {e}")
        raise RuntimeError(f"Erreur de chargement du modèle Vosk: {e}")


def init_audio(input_device_index):
    """Initialise l'audio dans un thread séparé et retourne la queue/shutdown_flag"""
    print(f"Audio: Initialisation de PyAudio. Utilisation du périphérique index {input_device_index}.")
    audio_queue = queue.Queue(maxsize=20) # Augmenté un peu pour la robustesse
    shutdown_flag = threading.Event()

    def audio_capture_thread(p_audio_instance, stream_instance):
        print("AudioCapture Thread: Démarré.")
        frames_per_buffer_capture = 8000 # Lire des chunks plus petits plus fréquemment
        try:
            while not shutdown_flag.is_set():
                try:
                    data = stream_instance.read(frames_per_buffer_capture, exception_on_overflow=False)
                    if data:
                        audio_queue.put(data, block=True, timeout=0.5) # Bloquant avec timeout
                except queue.Full:
                    # print("AudioCapture Thread: audio_queue pleine, buffer audio ignoré.")
                    time.sleep(0.01) # Petite pause si la queue est pleine
                except IOError as e:
                    if e.errno == pyaudio.paInputOverflowed:
                        # print("AudioCapture Thread: Input overflowed. Ignoré.")
                        pass # Normal si le traitement est lent
                    else:
                        print(f"AudioCapture Thread: ERREUR IOError: {e}")
                        time.sleep(0.1)
                except Exception as e:
                    print(f"AudioCapture Thread: ERREUR inattendue: {e}")
                    time.sleep(0.1)
        finally:
            print("AudioCapture Thread: Arrêt.")
            if stream_instance.is_active(): stream_instance.stop_stream()
            stream_instance.close()
            p_audio_instance.terminate()
            print("AudioCapture Thread: PyAudio terminé.")

    try:
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=16000, input=True,
            frames_per_buffer=16000, # Buffer interne de PyAudio
            input_device_index=input_device_index
        )
        print("Audio: Stream PyAudio ouvert.")
        
        capture_thread = threading.Thread(target=audio_capture_thread, args=(p, stream), daemon=True)
        capture_thread.start()
        print("Audio: Thread audio_capture démarré.")
        return audio_queue, shutdown_flag

    except Exception as e:
        print(f"Audio: ERREUR lors de l'initialisation PyAudio: {e}")
        if 'p' in locals() and p: p.terminate() # S'assurer de terminer PyAudio en cas d'erreur
        raise

def speech_to_text(model: Model, audio_data_queue: queue.Queue, shutdown_event: threading.Event):
    """
    Générateur qui produit du texte (partiel et final) à partir de l'audio.
    Prend une instance de modèle Vosk, une queue pour les données audio, et un événement d'arrêt.
    """
    if not isinstance(model, Model):
        raise ValueError("Le modèle Vosk fourni n'est pas une instance valide de vosk.Model.")

    recognizer = KaldiRecognizer(model, 16000)
    recognizer.SetWords(True) # Activer pour obtenir des résultats partiels plus fréquents
    # recognizer.SetPartialWords(True) # Pourrait être utile aussi

    print("SpeechToText Generator: Prêt.")
    try:
        while not shutdown_event.is_set():
            try:
                audio_chunk = audio_data_queue.get(block=True, timeout=0.1) # Attendre un peu pour les données
                
                if recognizer.AcceptWaveform(audio_chunk):
                    result_json = recognizer.Result()
                    result_dict = json.loads(result_json)
                    if result_dict.get("text"):
                        yield result_dict["text"].strip()
                else:
                    partial_result_json = recognizer.PartialResult()
                    partial_result_dict = json.loads(partial_result_json)
                    if partial_result_dict.get("partial"):
                        yield partial_result_dict["partial"].strip()
            
            except queue.Empty:
                # C'est normal, la queue peut être vide temporairement.
                # On vérifie juste le flag d'arrêt et on continue.
                if shutdown_event.is_set():
                    break 
                continue
            except Exception as e:
                print(f"SpeechToText Generator: Erreur pendant la reconnaissance: {e}")
                time.sleep(0.05) # Petite pause en cas d'erreur
    finally:
        # Traiter les derniers mots après l'arrêt demandé
        final_result_json = recognizer.FinalResult()
        final_result_dict = json.loads(final_result_json)
        if final_result_dict.get("text"):
            yield final_result_dict["text"].strip()
        print("SpeechToText Generator: Terminé.")

# Pour tester ce module isolément (optionnel)
if __name__ == '__main__':
    import os
    MODEL_PATH_VOSK = "./model/vosk-model-small-fr-0.22" # Adaptez le chemin
    
    if not os.path.exists(MODEL_PATH_VOSK) or not os.path.isdir(MODEL_PATH_VOSK):
        print(f"ERREUR: Modèle Vosk non trouvé à '{MODEL_PATH_VOSK}'. Téléchargez-le et placez-le correctement.")
    else:
        try:
            vosk_model_main = init_vosk_model(MODEL_PATH_VOSK)
            
            # Sélection du microphone (simplifié pour le test)
            p_test = pyaudio.PyAudio()
            default_mic_index = p_test.get_default_input_device_info()['index']
            print(f"Utilisation du microphone par défaut: index {default_mic_index}")
            p_test.terminate()

            audio_q, shutdown_f = init_audio(default_mic_index)
            
            print("\nParlez dans le microphone (Ctrl+C pour arrêter)...")
            try:
                for text_segment in speech_to_text(vosk_model_main, audio_q, shutdown_f):
                    if text_segment: # Afficher seulement si non vide
                        print(f"Entendu: {text_segment}")
            except KeyboardInterrupt:
                print("\nArrêt demandé par l'utilisateur.")
            finally:
                shutdown_f.set() # Signaler l'arrêt aux threads
                # Laisser un peu de temps aux threads pour se terminer
                # Le thread audio_capture devrait se terminer car il vérifie shutdown_flag
                # Le générateur speech_to_text se termine aussi avec le flag
                time.sleep(1) 
                print("Test terminé.")

        except RuntimeError as e:
            print(f"Erreur d'exécution du test: {e}")
        except Exception as e:
            print(f"Erreur inattendue lors du test: {e}")