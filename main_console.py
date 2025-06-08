import sys
import cv2
import pyaudio # Déjà importé
import sounddevice as sd # Ajout pour lister les périphériques de sortie
import time
import threading
import queue
import os

# Kokoro doit être importé après sounddevice pour la sélection
from src.Kokoro import initialize_kokoro, speak_mix, set_selected_output_device # Ajout de set_selected_output_device
# KOKORO_INITIALIZED est défini après la sélection de périphérique

# ... (autres imports) ...
from src.emotion_detection import init_emotion_model
from src.faceNet import init_mtcnn, init_facenet, detect_faces_and_coords, save_to_database
from src.text import init_vosk_model, init_audio

from src.llm_langchain_logic import init_llms_and_memory, clear_all_memories, reset_short_term_context_deques
from src.llm_processor import LLMProcessor
from src.tts_processor import TTSProcessor # TTSProcessor utilise maintenant le Kokoro.py modifié
from src.vision_audio_processor import VisionAudioProcessor

# ... (variables globales pour l'animation, configuration, etc. restent les mêmes) ...
active_animation_command_queue = None
def _dummy_send_animation_command(command_type, emotion_name=None, action=None): return False
active_send_animation_command_func = _dummy_send_animation_command
active_stop_animation_func = lambda: None
ACTIVE_ANIMATION_EMOTIONS_AVAILABLE = {}
ANIMATION_MODULE_TYPE = None

HISTORY_SIZE = 15
DATABASE_PATH = r"./donee_visage"
MODEL_PATHS = {
    "emotion_user": r"./model/emotion_model",
    "vosk": r"./model/vosk-model-small-fr-0.22"
}
CONVERSATION_TRIGGER_WORD = "julie"
CONVERSATION_TIMEOUT_SECONDS = 120
FACE_GREETING_COOLDOWN_SECONDS = 600


CAMERA_INDEX= int(input("chosis l'index de la caméra:"))

REQUEST_WIDTH = 640
REQUEST_HEIGHT = 480
REQUEST_FPS = 30

conversation_active = False
conversation_timeout_timer_obj = None
last_interaction_time = 0
last_processed_known_face_for_greeting = None
face_greeting_cooldown_active = False
face_greeting_cooldown_timer_obj = None
global_shutdown_event = threading.Event()
vision_audio_worker = None
cap_instance = None
mtcnn_instance = None
facenet_instance = None
input_queue_console = None
KOKORO_INITIALIZED = False # Sera défini après la sélection


def select_microphone():
    # ... (code inchangé) ...
    print("Sélection du périphérique microphone:")
    p_audio_select = pyaudio.PyAudio()
    info = p_audio_select.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    input_devices = []
    for i in range(0, numdevices):
        device_info = p_audio_select.get_device_info_by_host_api_device_index(0, i)
        if device_info.get('maxInputChannels') > 0:
            input_devices.append((i, device_info.get('name')))
            print(f"[{len(input_devices)-1}] - {device_info.get('name')} (Index système: {i})")

    p_audio_select.terminate()

    if not input_devices:
        print("Aucun microphone détecté. Vérifiez votre matériel.")
        sys.exit(1)

    choice = -1
    while choice < 0 or choice >= len(input_devices):
        try:
            raw_choice = input(f"Entrez le numéro de votre microphone [0-{len(input_devices)-1}]: ")
            choice = int(raw_choice)
            if not (0 <= choice < len(input_devices)):
                print("Choix invalide.")
                choice = -1
        except ValueError:
            print("Veuillez entrer un nombre valide.")
            choice = -1

    system_mic_index = -1
    # ... (reste de la logique pour mapper le choix à l'index système, inchangé) ...
    p_audio_temp = pyaudio.PyAudio()
    count = 0
    for i in range(0, p_audio_temp.get_host_api_info_by_index(0).get('deviceCount')):
        device_info = p_audio_temp.get_device_info_by_host_api_device_index(0, i)
        if device_info.get('maxInputChannels') > 0:
            if count == choice:
                system_mic_index = i
                break
            count += 1
    p_audio_temp.terminate()

    if system_mic_index == -1:
        print("Erreur : Impossible de mapper le choix à un index système. Utilisation du défaut.")
        p_audio_default = pyaudio.PyAudio()
        try: system_mic_index = p_audio_default.get_default_input_device_info()['index']
        finally: p_audio_default.terminate()

    print(f"Microphone sélectionné: {input_devices[choice][1]} (Index Système: {system_mic_index})")
    return system_mic_index

def select_output_device(): # NOUVELLE FONCTION
    print("\nSélection du périphérique de sortie audio (pour Kokoro TTS):")
    devices = sd.query_devices()
    output_devices = []
    # sounddevice numérote les périphériques différemment de pyaudio.
    # On va stocker l'index original de sounddevice.
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            output_devices.append({'original_index': i, 'name': device['name']})
            print(f"[{len(output_devices)-1}] - {device['name']} (Index Système sd: {i})")

    if not output_devices:
        print("Aucun périphérique de sortie audio détecté par sounddevice.")
        return None # Retourner None pour utiliser le défaut

    choice = -1
    while choice < 0 or choice >= len(output_devices):
        try:
            raw_choice = input(f"Entrez le numéro de votre périphérique de sortie [0-{len(output_devices)-1}] (ou laissez vide pour défaut système): ")
            if not raw_choice: # L'utilisateur appuie sur Entrée sans rien taper
                print("Utilisation du périphérique de sortie par défaut du système.")
                return None
            choice = int(raw_choice)
            if not (0 <= choice < len(output_devices)):
                print("Choix invalide.")
                choice = -1
        except ValueError:
            print("Veuillez entrer un nombre valide.")
            choice = -1

    selected_device_info = output_devices[choice]
    print(f"Périphérique de sortie audio sélectionné: {selected_device_info['name']} (Index Système sd: {selected_device_info['original_index']})")
    return selected_device_info['original_index']


# ... (handle_conversation_timeout, reset_conversation_timeout, etc. restent les mêmes) ...
def handle_conversation_timeout():
    # ... (code inchangé)
    global conversation_active, last_interaction_time, face_greeting_cooldown_timer_obj
    if conversation_active:
        print_to_console("--- Conversation Terminée (Inactivité) ---")
        conversation_active = False
        active_send_animation_command_func(command_type="set_emotion", emotion_name="neutre")
        start_face_greeting_cooldown()

def reset_conversation_timeout():
    # ... (code inchangé)
    global conversation_timeout_timer_obj, last_interaction_time
    last_interaction_time = time.time()
    if conversation_timeout_timer_obj is not None and conversation_timeout_timer_obj.is_alive():
        conversation_timeout_timer_obj.cancel()

    if conversation_active:
        conversation_timeout_timer_obj = threading.Timer(CONVERSATION_TIMEOUT_SECONDS, handle_conversation_timeout)
        conversation_timeout_timer_obj.daemon = True
        conversation_timeout_timer_obj.start()

def start_face_greeting_cooldown():
    # ... (code inchangé)
    global face_greeting_cooldown_active, face_greeting_cooldown_timer_obj, last_processed_known_face_for_greeting
    if not face_greeting_cooldown_active:
        print_to_console(f"--- (Info: Salut auto. par visage en pause pour {FACE_GREETING_COOLDOWN_SECONDS // 60} min) ---")
        face_greeting_cooldown_active = True
        if face_greeting_cooldown_timer_obj and face_greeting_cooldown_timer_obj.is_alive():
            face_greeting_cooldown_timer_obj.cancel()
        face_greeting_cooldown_timer_obj = threading.Timer(FACE_GREETING_COOLDOWN_SECONDS, handle_face_greeting_cooldown_finished)
        face_greeting_cooldown_timer_obj.daemon = True
        face_greeting_cooldown_timer_obj.start()
    last_processed_known_face_for_greeting = None

def handle_face_greeting_cooldown_finished():
    # ... (code inchangé)
    global face_greeting_cooldown_active, last_processed_known_face_for_greeting
    print_to_console("--- (Info: Salut auto. par visage de nouveau possible) ---")
    face_greeting_cooldown_active = False
    last_processed_known_face_for_greeting = None

def print_to_console(message):
    # ... (code inchangé)
    print(message)

def execute_face_registration_procedure():
    # ... (code inchangé, mais s'assurer que speak_mix est appelé avec KOKORO_INITIALIZED) ...
    global vision_audio_worker, cap_instance, mtcnn_instance, facenet_instance, input_queue_console
    print_to_console("\n--- LANCEMENT DE L'ENREGISTREMENT DE VISAGE ---")

    original_vaw_state_heavy = False
    if vision_audio_worker:
        original_vaw_state_heavy = vision_audio_worker._heavy_processing_active
        vision_audio_worker.pause_heavy_processing()
        if input_queue_console:
            while not input_queue_console.empty():
                try: input_queue_console.get_nowait()
                except queue.Empty: break
    time.sleep(0.5)

    nom_utilisateur_enregistrement = ""
    while not nom_utilisateur_enregistrement:
        print_to_console("Veuillez entrer le prénom à associer à ce visage et appuyer sur Entrée :")
        nom_utilisateur_enregistrement = sys.stdin.readline().strip()
        if not nom_utilisateur_enregistrement: print_to_console("Le prénom ne peut pas être vide.")
        elif not nom_utilisateur_enregistrement.isalnum():
            print_to_console("Le prénom ne doit contenir que des lettres et des chiffres.")
            nom_utilisateur_enregistrement = ""

    print_to_console(f"Merci, {nom_utilisateur_enregistrement}. Préparez-vous pour la prise de 5 photos...")
    active_send_animation_command_func(command_type="set_emotion", emotion_name="surprise")

    face_images_rgb_dict_for_db = {}
    num_photos_a_prendre = 5
    photos_prises_valides = 0

    if not cap_instance or not cap_instance.isOpened():
        print_to_console("ERREUR: Caméra non disponible pour l'enregistrement.")
        if vision_audio_worker and original_vaw_state_heavy: vision_audio_worker.resume_heavy_processing()
        return

    for i in range(num_photos_a_prendre):
        print_to_console(f"Prise de la photo {i+1}/{num_photos_a_prendre}... Regardez la caméra.")
        if KOKORO_INITIALIZED: speak_mix(f"Photo {i+1}", speed=1.1)
        time.sleep(1.5)

        ret, frame = cap_instance.read()
        if not ret or frame is None: print_to_console("Erreur capture photo."); continue

        faces_rgb_list, coords_list = detect_faces_and_coords(frame, mtcnn_instance)

        if faces_rgb_list:
            face_rgb = faces_rgb_list[0]
            face_images_rgb_dict_for_db[f"image_{photos_prises_valides}"] = face_rgb
            photos_prises_valides += 1
            print_to_console("Photo capturée avec visage.")
            active_send_animation_command_func(command_type="action", action="cligner")
        else:
            print_to_console("Aucun visage détecté. Repositionnez-vous.")
            if KOKORO_INITIALIZED: speak_mix("Aucun visage détecté.", speed=1.1)
            if i < num_photos_a_prendre -1 : time.sleep(1)

    if photos_prises_valides > 0:
        print_to_console(f"Sauvegarde de {photos_prises_valides} visages pour {nom_utilisateur_enregistrement}...")
        result_save = save_to_database(nom_utilisateur_enregistrement, face_images_rgb_dict_for_db, DATABASE_PATH, facenet_instance)
        print_to_console(f"Résultat sauvegarde: {result_save}")
        active_send_animation_command_func(command_type="set_emotion", emotion_name="joie")
        if KOKORO_INITIALIZED: speak_mix(f"{nom_utilisateur_enregistrement}, votre visage a bien été enregistré.", speed=1.0)
    else:
        print_to_console("Aucune photo valide. Enregistrement échoué.")
        active_send_animation_command_func(command_type="set_emotion", emotion_name="tristesse")
        if KOKORO_INITIALIZED: speak_mix("Désolée, enregistrement échoué.", speed=1.0)

    print_to_console("--- FIN ENREGISTREMENT VISAGE ---")
    active_send_animation_command_func(command_type="set_emotion", emotion_name="neutre")

    if vision_audio_worker and original_vaw_state_heavy: vision_audio_worker.resume_heavy_processing()

def process_vaw_output(data, llm_proc, tts_proc):
    # ... (code inchangé) ...
    global conversation_active, last_processed_known_face_for_greeting, face_greeting_cooldown_active
    global vision_audio_worker

    data_type = data.get("type")

    if data_type == "visual_info_update":
        current_face_identity = data.get("identity", "---")
        is_current_face_known = current_face_identity not in ["visage inconnu", "---"]

        if not conversation_active and is_current_face_known and not face_greeting_cooldown_active:
            if current_face_identity != last_processed_known_face_for_greeting:
                print_to_console(f"--- Conversation Initiée (Visage Détecté: {current_face_identity}) ---")
                reset_short_term_context_deques()
                last_processed_known_face_for_greeting = current_face_identity
                conversation_active = True
                reset_conversation_timeout()
                active_send_animation_command_func(command_type="set_emotion", emotion_name="neutre")

                if vision_audio_worker: vision_audio_worker.pause_heavy_processing()

                greeting_text_to_llm = f"Bonjour {current_face_identity}."
                user_emotion_on_frame = data.get("emotion", "neutre")

                ai_response, ai_emotion, ended, face_req = llm_proc.process_input(greeting_text_to_llm, user_emotion_on_frame, current_face_identity)
                handle_llm_response(ai_response, ai_emotion, ended, tts_proc, face_req)
        elif not conversation_active and not is_current_face_known and not face_greeting_cooldown_active:
            last_processed_known_face_for_greeting = None

    elif data_type == "speech_stable":
        texte_utilisateur = data["text"]
        emotion_utilisateur = data["user_emotion"]
        prenom_utilisateur = data["user_identity"]
        is_known_user = data["is_known_user"]
        contains_trigger = data["contains_trigger_word"]

        user_display_name = prenom_utilisateur if is_known_user else "Inconnu"
        user_text_display = f"Utilisateur ({user_display_name}, Émotion: {emotion_utilisateur}): {texte_utilisateur}"
        print_to_console(user_text_display)

        if conversation_active:
            reset_conversation_timeout()
            if vision_audio_worker: vision_audio_worker.pause_heavy_processing()
            ai_response, ai_emotion, ended, face_req = llm_proc.process_input(texte_utilisateur, emotion_utilisateur, prenom_utilisateur)
            handle_llm_response(ai_response, ai_emotion, ended, tts_proc, face_req)

        elif contains_trigger:
            print_to_console(f"--- Conversation Initiée (Mot Clé: '{CONVERSATION_TRIGGER_WORD}') ---")
            reset_short_term_context_deques()
            if face_greeting_cooldown_timer_obj and face_greeting_cooldown_timer_obj.is_alive():
                face_greeting_cooldown_timer_obj.cancel()
            face_greeting_cooldown_active = False
            last_processed_known_face_for_greeting = prenom_utilisateur if is_known_user else None

            conversation_active = True
            reset_conversation_timeout()
            active_send_animation_command_func(command_type="set_emotion", emotion_name="neutre")

            if vision_audio_worker: vision_audio_worker.pause_heavy_processing()
            ai_response, ai_emotion, ended, face_req = llm_proc.process_input(texte_utilisateur, emotion_utilisateur, prenom_utilisateur)
            handle_llm_response(ai_response, ai_emotion, ended, tts_proc, face_req)

def handle_llm_response(ai_response_text, ai_emotion, conversation_should_end, tts_proc, face_registration_requested):
    # ... (code inchangé, avec le DEBUG print) ...
    global conversation_active, ACTIVE_ANIMATION_EMOTIONS_AVAILABLE, ANIMATION_MODULE_TYPE
    llm_text_display = f"Julie (Émotion: {ai_emotion}): {ai_response_text}"
    print_to_console(llm_text_display)

    final_emotion_for_anim = ai_emotion.lower()
    if final_emotion_for_anim == "degout" and "dégoût" in ACTIVE_ANIMATION_EMOTIONS_AVAILABLE:
        final_emotion_for_anim = "dégoût"

    if final_emotion_for_anim not in ACTIVE_ANIMATION_EMOTIONS_AVAILABLE:
        original_llm_emotion = final_emotion_for_anim
        final_emotion_for_anim = "neutre"
        print(f"(Animation: Émotion LLM '{original_llm_emotion}' non directement disponible ou mappée à '{final_emotion_for_anim}')")

    print(f"[DEBUG ANIMATION] Envoi commande: Type='set_emotion', Emotion='{final_emotion_for_anim}', Module='{ANIMATION_MODULE_TYPE}'")
    active_send_animation_command_func(command_type="set_emotion", emotion_name=final_emotion_for_anim)

    if KOKORO_INITIALIZED and tts_proc and ai_response_text:
        tts_proc.speak_text(ai_response_text)

    if face_registration_requested:
        execute_face_registration_procedure()

    if conversation_should_end:
        print_to_console("--- Conversation Terminée (par l'assistant LLM) ---")
        conversation_active = False
        if conversation_timeout_timer_obj and conversation_timeout_timer_obj.is_alive(): conversation_timeout_timer_obj.cancel()
        start_face_greeting_cooldown()
    else:
        if not face_registration_requested: reset_conversation_timeout()

    handle_tts_finished()

def handle_tts_finished():
    # ... (code inchangé)
    global conversation_active, vision_audio_worker
    if vision_audio_worker:
        vision_audio_worker.resume_heavy_processing()

def handle_user_console_input(user_input_str, llm_proc, tts_proc):
    # ... (code inchangé)
    global conversation_active, face_greeting_cooldown_timer_obj, face_greeting_cooldown_active

    print_to_console(f"ConsoleUser (vous): {user_input_str}")

    if not conversation_active and CONVERSATION_TRIGGER_WORD.lower() in user_input_str.lower():
        print_to_console(f"--- Conversation Initiée (Console: '{CONVERSATION_TRIGGER_WORD}') ---")
        reset_short_term_context_deques()
        conversation_active = True
        if face_greeting_cooldown_timer_obj and face_greeting_cooldown_timer_obj.is_alive():
            face_greeting_cooldown_timer_obj.cancel()
        face_greeting_cooldown_active = False

    if not conversation_active:
        print_to_console(f"Julie: (Conversation non active. Dites '{CONVERSATION_TRIGGER_WORD}'.)")
        return

    reset_conversation_timeout()
    current_active_user_name = last_processed_known_face_for_greeting if last_processed_known_face_for_greeting else "UtilisateurConsole"
    ai_response, ai_emotion, ended, face_req = llm_proc.process_input(user_input_str, "neutre", current_active_user_name)
    handle_llm_response(ai_response, ai_emotion, ended, tts_proc, face_req)


if __name__ == "__main__":
    selected_mic_index = select_microphone()
    selected_output_idx = select_output_device() # NOUVEAU

    if selected_output_idx is not None:
        set_selected_output_device(selected_output_idx) # Transmettre à Kokoro

    # L'initialisation de Kokoro se fait maintenant ici, APRÈS la sélection du périphérique
    print("Initialisation de Kokoro TTS...")
    KOKORO_INITIALIZED = initialize_kokoro()
    if not KOKORO_INITIALIZED:
        print("AVERTISSEMENT: Kokoro TTS n'a pas pu être initialisé. Le TTS ne fonctionnera pas.")

    # --- Animation des yeux : Initialisation conditionnelle (inchangée) ---
    # ...
    try:
        import board; import digitalio; import busio
        from src.ILI_librairie.ili9488 import ILI9488
        from src.animation_eyes_tool_ili9488 import start_animation_display_ili9488, stop_animation_display_ili9488, send_animation_command_ili9488, EMOTIONS_ILI9488
        print("Animation Eyes: Tentative ILI9488...")
        TFT_CS_PIN = board.CS; TFT_DC_PIN = board.D38; TFT_RST_PIN = board.D40; TFT_BL_PIN = board.D36
        spi = busio.SPI(board.SCLK, MOSI=board.MOSI)
        cs = digitalio.DigitalInOut(TFT_CS_PIN); dc = digitalio.DigitalInOut(TFT_DC_PIN)
        rst = digitalio.DigitalInOut(TFT_RST_PIN); bl = digitalio.DigitalInOut(TFT_BL_PIN)
        active_animation_command_queue = start_animation_display_ili9488(spi, cs, dc, rst, bl)
        if active_animation_command_queue:
            active_send_animation_command_func = send_animation_command_ili9488
            active_stop_animation_func = stop_animation_display_ili9488
            ACTIVE_ANIMATION_EMOTIONS_AVAILABLE = list(EMOTIONS_ILI9488.keys())
            ANIMATION_MODULE_TYPE = "ili9488"
            print(f"Animation Eyes (ILI9488): Moteur démarré. Émotions: {ACTIVE_ANIMATION_EMOTIONS_AVAILABLE}")
        else: raise ImportError("Échec démarrage moteur ILI9488.")
    except (ImportError, RuntimeError, NotImplementedError) as e_ili:
        print(f"Animation Eyes: ILI9488 non disponible ({e_ili}). Fallback Tkinter.")
        from src.animation_eyes_tool_tkinter import start_animation_display as start_tkinter_display, stop_animation_display as stop_tkinter_display, send_animation_command as send_tkinter_command, EMOTIONS as EMOTIONS_TKINTER
        active_animation_command_queue = start_tkinter_display()
        if active_animation_command_queue:
            active_send_animation_command_func = send_tkinter_command
            active_stop_animation_func = stop_tkinter_display
            ACTIVE_ANIMATION_EMOTIONS_AVAILABLE = list(EMOTIONS_TKINTER.keys())
            ANIMATION_MODULE_TYPE = "tkinter"
            print(f"Animation Eyes (Tkinter): Moteur démarré. Émotions: {ACTIVE_ANIMATION_EMOTIONS_AVAILABLE}")
        else: print("AVERTISSEMENT: Animation des yeux (Tkinter fallback) n'a pas pu démarrer.")


    print("Initialisation des modèles (Vosk, Emotion, FaceNet)...")
    try:
        vosk_model_instance = init_vosk_model(MODEL_PATHS["vosk"])
        emotion_model_user_instance = init_emotion_model(MODEL_PATHS["emotion_user"])
        mtcnn_instance = init_mtcnn()
        facenet_instance = init_facenet()
    except Exception as e:
        print(f"Erreur critique init modèles AI: {e}"); sys.exit(1)

    print("Initialisation du backend LLM et des mémoires...")
    try: init_llms_and_memory()
    except Exception as e: print(f"Erreur critique init LLM: {e}"); sys.exit(1)

    print(f"\n--- Initialisation Caméra (Index: {CAMERA_INDEX}) ---")
    cap_instance = cv2.VideoCapture(CAMERA_INDEX)
    if not cap_instance.isOpened():
        print(f"FATAL: Erreur: Impossible d'ouvrir la caméra à l'index {CAMERA_INDEX}.")
        sys.exit(1)
    print("Caméra ouverte avec succès !")
    print(f"Backend utilisé par OpenCV: {cap_instance.getBackendName()}")
    cap_instance.set(cv2.CAP_PROP_FRAME_WIDTH, REQUEST_WIDTH)
    cap_instance.set(cv2.CAP_PROP_FRAME_HEIGHT, REQUEST_HEIGHT)
    cap_instance.set(cv2.CAP_PROP_FPS, REQUEST_FPS)
    actual_width = cap_instance.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_height = cap_instance.get(cv2.CAP_PROP_FRAME_HEIGHT)
    actual_fps = cap_instance.get(cv2.CAP_PROP_FPS)
    print(f"Résolution demandée: {REQUEST_WIDTH}x{REQUEST_HEIGHT} @ {REQUEST_FPS} FPS")
    print(f"Résolution réelle obtenue: {int(actual_width)}x{int(actual_height)} @ {actual_fps:.2f} FPS")
    print("--------------------------------------------")

    print("Initialisation flux audio PyAudio pour Vosk...")
    try: audio_processing_queue, audio_shutdown_flag = init_audio(selected_mic_index)
    except Exception as e:
        print(f"Erreur critique init audio: {e}")
        if cap_instance: cap_instance.release()
        sys.exit(1)

    llm_processor = LLMProcessor()
    tts_processor = TTSProcessor() # TTSProcessor utilisera maintenant le Kokoro.py modifié
    vision_audio_worker = VisionAudioProcessor(
        history_size=HISTORY_SIZE,
        emotion_model_instance=emotion_model_user_instance,
        mtcnn_instance=mtcnn_instance,
        facenet_instance=facenet_instance,
        vosk_model_instance=vosk_model_instance,
        cap_instance=cap_instance,
        audio_data_q=audio_processing_queue,
        shutdown_event=audio_shutdown_flag,
        db_path=DATABASE_PATH
    )

    vaw_thread = threading.Thread(target=vision_audio_worker.run, daemon=True)
    vaw_thread.start()

    print_to_console(f"Système prêt. Dites '{CONVERSATION_TRIGGER_WORD}' ou tapez votre message.")
    print_to_console("Commandes console: 'quitter', 'reset memory'.")
    last_interaction_time = time.time()

    input_queue_console = queue.Queue()
    def console_input_reader(q):
        # ... (code inchangé)
        while not global_shutdown_event.is_set():
            try: user_in = input()
            except EOFError:
                if not global_shutdown_event.is_set(): q.put(None); break
            except Exception:
                if not global_shutdown_event.is_set(): q.put(None); break
            else:
                if global_shutdown_event.is_set(): break
                q.put(user_in)

    console_reader_thread = threading.Thread(target=console_input_reader, args=(input_queue_console,), daemon=True)
    console_reader_thread.start()

    try:
        while not global_shutdown_event.is_set():
            # ... (boucle principale inchangée) ...
            console_input_str = None
            try: console_input_str = input_queue_console.get_nowait()
            except queue.Empty: pass

            if console_input_str is not None:
                if console_input_str is None: print_to_console("EOF. Arrêt..."); break
                if console_input_str.strip().lower() == 'quitter': print_to_console("Arrêt demandé."); break
                elif console_input_str.strip().lower() == 'reset memory':
                    print_to_console("--- Réinitialisation mémoire ---")
                    if vision_audio_worker: vision_audio_worker.pause_heavy_processing()
                    time.sleep(0.2); clear_all_memories(); conversation_active = False
                    if conversation_timeout_timer_obj and conversation_timeout_timer_obj.is_alive(): conversation_timeout_timer_obj.cancel()
                    if face_greeting_cooldown_timer_obj and face_greeting_cooldown_timer_obj.is_alive(): face_greeting_cooldown_timer_obj.cancel()
                    face_greeting_cooldown_active = False; last_processed_known_face_for_greeting = None
                    print_to_console("--- Mémoire réinitialisée. ---")
                    active_send_animation_command_func(command_type="set_emotion", emotion_name="neutre")
                    if vision_audio_worker: vision_audio_worker.resume_heavy_processing()
                elif console_input_str.strip() != "":
                    handle_user_console_input(console_input_str, llm_processor, tts_processor)

            try:
                if vision_audio_worker:
                    vaw_data = vision_audio_worker.output_queue.get_nowait()
                    process_vaw_output(vaw_data, llm_processor, tts_processor)
            except queue.Empty: pass
            except AttributeError: pass

            if conversation_active and \
               (conversation_timeout_timer_obj is None or not conversation_timeout_timer_obj.is_alive()):
                 if (time.time() - last_interaction_time > CONVERSATION_TIMEOUT_SECONDS):
                     handle_conversation_timeout()
                 else: reset_conversation_timeout()
            time.sleep(0.1)

    except KeyboardInterrupt: print_to_console("\nArrêt par Ctrl+C.")
    finally:
        # ... (bloc finally inchangé) ...
        print_to_console("Arrêt en cours...")
        global_shutdown_event.set()

        if vision_audio_worker: vision_audio_worker.stop()
        if vaw_thread and vaw_thread.is_alive():
            vaw_thread.join(timeout=2.0)
            if vaw_thread.is_alive(): print("AVERTISSEMENT: VAW thread non terminé.")
        if audio_shutdown_flag: audio_shutdown_flag.set()
        if active_stop_animation_func: active_stop_animation_func()
        if conversation_timeout_timer_obj and conversation_timeout_timer_obj.is_alive(): conversation_timeout_timer_obj.cancel()
        if face_greeting_cooldown_timer_obj and face_greeting_cooldown_timer_obj.is_alive(): face_greeting_cooldown_timer_obj.cancel()
        if cap_instance: cap_instance.release(); print("Caméra relâchée.")
        if llm_processor: llm_processor.stop()
        if tts_processor: tts_processor.stop()
        print("Application arrêtée.")
        if ANIMATION_MODULE_TYPE == "tkinter": print("Utilisation os._exit(0) pour Tkinter."); os._exit(0)
        else: sys.exit(0)
