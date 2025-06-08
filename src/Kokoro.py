import sounddevice as sd
# import soundfile as sf # Peut être nécessaire pour les dépendances internes de kokoro_onnx
import numpy as np
import os
import librosa

try:
    from kokoro_onnx import Kokoro
except ImportError:
    print("ERREUR: Le module kokoro_onnx est introuvable.")
    Kokoro = None

kokoro_instance = None
VOICE_DATA = None
mix_cache = {}
SELECTED_OUTPUT_DEVICE_INDEX = None

def set_selected_output_device(device_index):
    global SELECTED_OUTPUT_DEVICE_INDEX
    SELECTED_OUTPUT_DEVICE_INDEX = device_index
    print(f"Kokoro: Périphérique de sortie audio réglé sur l'index système : {SELECTED_OUTPUT_DEVICE_INDEX}")


def initialize_kokoro(
    model_path="model/kokoroTTS/kokoro-v1.0.onnx",
    voices_path="model/kokoroTTS/voices-v1.0.bin"
):
    global kokoro_instance, VOICE_DATA
    if Kokoro is None:
        print("Kokoro TTS: kokoro_onnx non chargé.")
        return False
    try:
        if not os.path.exists(voices_path):
            print(f"ERREUR: Fichier de voix Kokoro introuvable: {voices_path}")
            return False
        VOICE_DATA = np.load(voices_path, allow_pickle=True)

        if not os.path.exists(model_path):
            print(f"ERREUR: Fichier modèle Kokoro introuvable: {model_path}")
            return False
        kokoro_instance = Kokoro(model_path, voices_path)
        print("Kokoro TTS initialisé avec succès.")
        return True
    except Exception as e:
        print(f"Erreur initialisation Kokoro TTS: {e}")
        kokoro_instance = None
        VOICE_DATA = None
        return False

def _play_audio(samples, sample_rate):
    global SELECTED_OUTPUT_DEVICE_INDEX
    # Choisissez une fréquence cible que votre matériel supporte bien.
    # 48000 Hz ou 44100 Hz sont de bons candidats universels.
    TARGET_PLAYBACK_RATE = 48000

    print(f"[KOKORO AUDIO] Fréq. originale: {sample_rate} Hz. Fréq. de lecture cible: {TARGET_PLAYBACK_RATE} Hz.")
    print(f"[KOKORO AUDIO] Périphérique de sortie index: {SELECTED_OUTPUT_DEVICE_INDEX if SELECTED_OUTPUT_DEVICE_INDEX is not None else 'Défaut'}")

    # S'assurer que les samples sont un ndarray numpy de type float32
    # Kokoro devrait déjà retourner des flottants, mais une conversion explicite est plus sûre.
    if not isinstance(samples, np.ndarray):
        samples_np = np.asarray(samples)
    else:
        samples_np = samples

    if samples_np.dtype != np.float32:
        samples_float32 = samples_np.astype(np.float32)
    else:
        samples_float32 = samples_np

    # Normaliser si les samples sont des entiers convertis (ex: int16 -> float)
    # Si Kokoro retourne des flottants déjà dans la plage [-1, 1], cette étape n'est pas strictement nécessaire
    # mais ne fait pas de mal si les valeurs sont déjà petites.
    # if np.issubdtype(samples_np.dtype, np.integer):
    #     max_val = np.iinfo(samples_np.dtype).max
    #     samples_float32 = samples_float32 / max_val

    audio_to_play = samples_float32
    actual_playback_rate = sample_rate

    if sample_rate != TARGET_PLAYBACK_RATE:
        print(f"[KOKORO AUDIO] Ré-échantillonnage de {sample_rate} Hz vers {TARGET_PLAYBACK_RATE} Hz...")
        try:
            # librosa.resample s'attend à y=samples_float32, orig_sr=..., target_sr=...
            audio_to_play = librosa.resample(y=samples_float32, orig_sr=sample_rate, target_sr=TARGET_PLAYBACK_RATE)
            actual_playback_rate = TARGET_PLAYBACK_RATE
            print(f"[KOKORO AUDIO] Ré-échantillonnage terminé.")
        except Exception as e_resample:
            print(f"[KOKORO AUDIO] ERREUR lors du ré-échantillonnage: {e_resample}.")
            print(f"[KOKORO AUDIO] Tentative de lecture avec la fréquence originale de {sample_rate} Hz.")
            # On garde audio_to_play = samples_float32 et actual_playback_rate = sample_rate
    else:
        print(f"[KOKORO AUDIO] Pas de ré-échantillonnage nécessaire (fréquences identiques).")


    try:
        if SELECTED_OUTPUT_DEVICE_INDEX is not None:
            sd.play(audio_to_play, samplerate=actual_playback_rate, device=SELECTED_OUTPUT_DEVICE_INDEX)
        else:
            sd.play(audio_to_play, samplerate=actual_playback_rate)
        sd.wait()
        print(f"[KOKORO AUDIO] Lecture audio terminée (ou tentée).")
    except Exception as e:
        print(f"Erreur lors de la lecture audio avec sounddevice (après tentative de resample): {e}")
        print(f"- Fréquence utilisée pour sd.play: {actual_playback_rate}")
        print(f"- Type de données des samples: {audio_to_play.dtype}, Shape: {audio_to_play.shape}")
        min_val, max_val = np.min(audio_to_play), np.max(audio_to_play)
        print(f"- Valeurs des samples: min={min_val}, max={max_val}")
        print("- Périphériques de sortie disponibles:")
        try:
            print(sd.query_devices())
        except Exception as e_qd:
            print(f"  (Erreur lors de la requête des périphériques: {e_qd})")


def speak(text, voice="ff_siwis", speed=1.0, lang="fr-fr"):
    if kokoro_instance is None:
        print("Kokoro non initialisé.")
        return
    try:
        samples, sample_rate = kokoro_instance.create(text, voice=voice, speed=speed, lang=lang)
        _play_audio(samples, sample_rate)
    except Exception as e:
        print(f"Erreur synthèse vocale (speak): {e}")

def speak_mix(text, voice1="ff_siwis", voice2="if_sara", mix_ratio=0.85, speed=1.0, lang="fr-fr"):
    if kokoro_instance is None:
        print("Kokoro non initialisé.")
        return
    if VOICE_DATA is None:
        print("Données de voix Kokoro non chargées.")
        return
    try:
        key = (voice1, voice2, round(mix_ratio, 2))
        if key in mix_cache:
            style_mix = mix_cache[key]
        else:
            if voice1 not in VOICE_DATA or voice2 not in VOICE_DATA:
                print(f"Erreur: Voix '{voice1}' ou '{voice2}' non trouvée.")
                default_voice_key = list(VOICE_DATA.keys())[0]
                style1 = VOICE_DATA.get(voice1, VOICE_DATA[default_voice_key])
                style2 = VOICE_DATA.get(voice2, VOICE_DATA[default_voice_key])
            else:
                style1 = VOICE_DATA[voice1]
                style2 = VOICE_DATA[voice2]
            style_mix = mix_ratio * style1 + (1 - mix_ratio) * style2
            mix_cache[key] = style_mix
        samples, sample_rate = kokoro_instance.create(text, voice=style_mix, speed=speed, lang=lang)
        _play_audio(samples, sample_rate)
    except KeyError as e:
        print(f"Erreur clé de voix (speak_mix): {e}.")
    except Exception as e:
        print(f"Erreur synthèse vocale (speak_mix): {e}")
