from transformers import pipeline
import cv2
import torch
from PIL import Image

def init_emotion_model(model_path, device=None):
    """Initialise et retourne le pipeline d'analyse d'émotions"""
    if device is None:
        device = 0 if torch.cuda.is_available() else -1
        
    return pipeline(
        "image-classification", 
        model=model_path,
        device=device,
        top_k=None  # Retourne tous les résultats
    )

def analyze_emotion(frame, emotion_model, input_size=224):
    """Analyse les émotions sur une frame avec le modèle initialisé"""
    if frame is None: # Ajout d'une vérification pour éviter les erreurs si frame est None
        return {}
    try:
        resized_frame = cv2.resize(frame, (input_size, input_size))
        pil_image = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
        
        results = emotion_model(pil_image)
        
        return {res['label']: res['score'] for res in results}
    except Exception as e:
        print(f"Erreur dans analyze_emotion: {e}")
        return {}


def enhance_contrast_grayscale(image_gray, contrast_factor=1):
    """Augmente le contraste d'une image en niveaux de gris."""
    return cv2.convertScaleAbs(image_gray, alpha=contrast_factor, beta=0)