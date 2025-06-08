from collections import deque
import cv2
import queue
import threading
import numpy as np
import time

# MODIFIÉ: Imports relatifs
from .emotion_detection import analyze_emotion 
from .faceNet import detect_faces_and_coords, face_to_embedding, compare_face, analyze_database, normalize_lighting_color
from .text import speech_to_text 

class VisionAudioProcessor:
    CONVERSATION_TRIGGER_WORD = "julie" 

    def __init__(self, history_size, emotion_model_instance, mtcnn_instance, facenet_instance, 
                 vosk_model_instance, cap_instance, audio_data_q, shutdown_event, db_path):
        self._history_size = history_size
        self._emotion_model = emotion_model_instance
        self._mtcnn = mtcnn_instance
        self._facenet = facenet_instance
        self._vosk_model = vosk_model_instance
        self._cap = cap_instance
        self._audio_queue_from_text_module = audio_data_q 
        self._shutdown_flag_from_text_module = shutdown_event 

        self._database_path = db_path

        self._emotion_history = deque(maxlen=self._history_size)
        self._face_identity_history = deque(maxlen=self._history_size) 
        
        self._last_processed_face_embedding = None 
        
        self._speech_text_queue = queue.Queue() 
        self._speech_recognition_thread = None 

        self._running = True 
        self._heavy_processing_active = True 

        self._current_accumulated_speech = ""
        self._last_speech_activity_time = time.time() 
        self._speech_stability_timeout = 2.0  
        self._min_speech_length_for_llm = 1   

        self._last_console_print_time = 0
        self._console_print_interval = 1.0 

        self.output_queue = queue.Queue()


    def _calculate_most_frequent(self, history_deque):
        if not history_deque:
            return "---" 
        filtered_history = [val for val in history_deque if val not in ["---", "impossible"]]
        source_to_count = filtered_history if filtered_history else history_deque
        counts = {}
        for value in source_to_count:
            counts[value] = counts.get(value, 0) + 1
        if not counts: return "---"
        return max(counts, key=counts.get)


    def pause_heavy_processing(self):
        # print("VisionAudioProcessor: Pause des traitements lourds.")
        self._heavy_processing_active = False
        self._current_accumulated_speech = "" 
        while not self._speech_text_queue.empty():
            try: self._speech_text_queue.get_nowait()
            except queue.Empty: break
        self._emotion_history.clear()
        self._face_identity_history.clear()
        self._last_processed_face_embedding = None


    def resume_heavy_processing(self):
        # print("VisionAudioProcessor: Reprise des traitements lourds.")
        self._heavy_processing_active = True
        self._last_speech_activity_time = time.time() 
        self._current_accumulated_speech = ""
        self._emotion_history.clear()
        self._face_identity_history.clear()
        self._last_processed_face_embedding = None

    def _start_speech_recognition(self):
        if self._speech_recognition_thread is None or not self._speech_recognition_thread.is_alive():
            self._speech_recognition_thread = threading.Thread(
                target=self._speech_to_text_loop,
                daemon=True
            )
            self._speech_recognition_thread.start()
            # print("VisionAudioProcessor: Thread de reconnaissance vocale démarré.")

    def _speech_to_text_loop(self):
        # print("VisionAudioProcessor: _speech_to_text_loop en attente de texte...")
        for text_segment in speech_to_text(self._vosk_model, self._audio_queue_from_text_module, self._shutdown_flag_from_text_module):
            if text_segment and self._heavy_processing_active : 
                self._speech_text_queue.put(text_segment)
            if self._shutdown_flag_from_text_module.is_set(): 
                break
        # print("VisionAudioProcessor: _speech_to_text_loop terminé.")


    def run(self):
        # print("VisionAudioProcessor: Démarrage du thread principal.")
        self._start_speech_recognition() 
        self._last_speech_activity_time = time.time()

        while self._running:
            if self._shutdown_flag_from_text_module.is_set(): 
                self.stop() 
                break

            ret, frame_bgr = self._cap.read()
            if not ret or frame_bgr is None:
                time.sleep(0.02) 
                continue

            current_frame_emotion = "---"
            current_frame_identity = "---"
            
            if self._heavy_processing_active:
                face_images_rgb_list, face_coords_list = detect_faces_and_coords(frame_bgr, self._mtcnn)

                if face_images_rgb_list:
                    embeddings_list = []
                    processed_face_images_rgb = []
                    for face_rgb_raw in face_images_rgb_list:
                        face_bgr_for_norm = cv2.cvtColor(face_rgb_raw, cv2.COLOR_RGB2BGR)
                        normalized_bgr_face = normalize_lighting_color(face_bgr_for_norm)
                        normalized_rgb_face = cv2.cvtColor(normalized_bgr_face, cv2.COLOR_BGR2RGB)
                        embedding = face_to_embedding(normalized_rgb_face, self._facenet)
                        if embedding is not None:
                            embeddings_list.append(embedding)
                            processed_face_images_rgb.append(normalized_rgb_face) 
                    
                    chosen_face_idx = -1
                    if embeddings_list:
                        if self._last_processed_face_embedding is not None:
                            distances = [compare_face(self._last_processed_face_embedding, emb) for emb in embeddings_list]
                            if distances:
                                min_dist = min(distances)
                                if min_dist < 0.8: 
                                    chosen_face_idx = distances.index(min_dist)
                                else: 
                                    chosen_face_idx = 0 
                        else: 
                            chosen_face_idx = 0
                    
                    if chosen_face_idx != -1:
                        self._last_processed_face_embedding = embeddings_list[chosen_face_idx]
                        chosen_face_rgb = processed_face_images_rgb[chosen_face_idx]
                        chosen_face_bgr_for_emotion = cv2.cvtColor(chosen_face_rgb, cv2.COLOR_RGB2BGR)
                        emotion_scores = analyze_emotion(chosen_face_bgr_for_emotion, self._emotion_model)
                        current_frame_emotion = max(emotion_scores, key=emotion_scores.get, default="---") if emotion_scores else "---"
                        current_frame_identity = analyze_database(self._last_processed_face_embedding, self._database_path)
                else: 
                    self._last_processed_face_embedding = None 
                
                self._emotion_history.append(current_frame_emotion)
                self._face_identity_history.append(current_frame_identity)

                try:
                    while not self._speech_text_queue.empty():
                        speech_part = self._speech_text_queue.get_nowait().strip()
                        if speech_part:
                            if not self._current_accumulated_speech or \
                               (len(speech_part) > len(self._current_accumulated_speech) and \
                                speech_part.startswith(self._current_accumulated_speech)) or \
                               not speech_part.endswith(self._current_accumulated_speech.split(" ")[-1] if " " in self._current_accumulated_speech else self._current_accumulated_speech):
                                self._current_accumulated_speech = speech_part
                            elif not self._current_accumulated_speech.endswith(speech_part): 
                                 self._current_accumulated_speech += " " + speech_part
                            self._last_speech_activity_time = time.time()
                except queue.Empty:
                    pass 

            stable_emotion = self._calculate_most_frequent(self._emotion_history)
            stable_identity = self._calculate_most_frequent(self._face_identity_history)
            
            current_time_loop = time.time() # Renommé pour éviter conflit avec time module
            if current_time_loop - self._last_console_print_time > self._console_print_interval:
                self.output_queue.put({
                    "type": "visual_info_update",
                    "emotion": stable_emotion,
                    "identity": stable_identity, 
                    "speech_in_progress": self._current_accumulated_speech
                })
                self._last_console_print_time = current_time_loop

            if self._heavy_processing_active and self._current_accumulated_speech:
                if (time.time() - self._last_speech_activity_time > self._speech_stability_timeout):
                    text_to_send_to_llm = self._current_accumulated_speech.strip()
                    num_words = len(text_to_send_to_llm.split())

                    if num_words >= self._min_speech_length_for_llm:
                        is_known_user = stable_identity not in ["visage inconnu", "---"]
                        contains_trigger = self.CONVERSATION_TRIGGER_WORD in text_to_send_to_llm.lower()
                        
                        self.output_queue.put({
                            "type": "speech_stable",
                            "text": text_to_send_to_llm,
                            "user_emotion": stable_emotion, 
                            "user_identity": stable_identity,
                            "is_known_user": is_known_user,
                            "contains_trigger_word": contains_trigger
                        })
                        self._current_accumulated_speech = "" 
                    else: 
                        self._current_accumulated_speech = ""
                    self._last_speech_activity_time = time.time() 
            
            time.sleep(0.03) 

        # print("VisionAudioProcessor: Boucle principale terminée.")

    def stop(self):
        # print("VisionAudioProcessor: Arrêt demandé.")
        self._running = False
        # print("VisionAudioProcessor: Stoppé.")