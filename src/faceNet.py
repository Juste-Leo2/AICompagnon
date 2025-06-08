import cv2
import numpy as np
import torch
import os
import pickle
from facenet_pytorch import InceptionResnetV1, MTCNN

def init_mtcnn(device='cuda' if torch.cuda.is_available() else 'cpu'):
    """Initialise et retourne le détecteur MTCNN"""
    return MTCNN(
        keep_all=False, # On ne garde que le visage avec la plus haute probabilité
        post_process=False, # On ne veut pas les tenseurs normalisés, mais les images de visages
        device=device
    )

def init_facenet(device='cuda' if torch.cuda.is_available() else 'cpu'):
    """Initialise et retourne le modèle Facenet avec les poids pré-entraînés"""
    model = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    return model

def detect_faces_and_coords(frame, mtcnn):
    """
    Détecte tous les visages d'une image avec MTCNN et retourne deux listes :
    - faces : une liste d'images de visages redimensionnées (160x160) en format RGB
    - coords : une liste de listes contenant les coordonnées [x1, y1, x2, y2] de chaque visage
    """
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces = []
    coords = []
    try:
        # mtcnn.detect retourne (boxes, probs, landmarks)
        # Si keep_all=False, il ne retourne qu'un seul visage (ou None)
        # Si keep_all=True, il retourne une liste de visages
        # Pour être cohérent avec l'utilisation de plusieurs visages possibles plus tard:
        mtcnn_temp_keep_all = MTCNN(keep_all=True, post_process=False, device=mtcnn.device)
        boxes, _ = mtcnn_temp_keep_all.detect(rgb_frame)
        
        if boxes is not None:
            for box in boxes:
                x1, y1, x2, y2 = map(int, box)
                #ajuster lorsque l'image sort du cadre
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(rgb_frame.shape[1], x2)  # largeur de l'image
                y2 = min(rgb_frame.shape[0], y2)  # hauteur de l'image                

                #suite
                if x1 < x2 and y1 < y2 : # S'assurer que la boîte a une taille valide
                    face = rgb_frame[y1:y2, x1:x2]
                    if face.size > 0: # S'assurer que le crop n'est pas vide
                        face_resized = cv2.resize(face, (160, 160))
                        faces.append(face_resized) # Garder en RGB
                        coords.append([x1, y1, x2, y2])
    except Exception as e:
        print(f"Erreur de détection faciale (detect_faces_and_coords): {e}")
    return faces, coords


def face_to_embedding(face_image_rgb, facenet_model): # S'attendre à une image RGB
    if face_image_rgb is None:
        return None # Retourner None pour indiquer l'échec
    
    device = next(facenet_model.parameters()).device
    # L'image est déjà un ndarray numpy (provenant de cv2.resize ou d'un crop)
    # Elle doit être (H, W, C) et en RGB.
    # Conversion en tenseur: (C, H, W), puis ajout d'un batch dimension (1, C, H, W)
    face_tensor = torch.tensor(face_image_rgb, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0).to(device)
    
    # Normalisation standard pour InceptionResnetV1
    face_tensor = (face_tensor / 255.0 - 0.5) / 0.5 
    
    with torch.no_grad():
        embedding = facenet_model(face_tensor).cpu().numpy()[0]
    
    return embedding

def compare_face(embedding1, embedding2):
    if embedding1 is None or embedding2 is None:
        return float('inf') # Si un embedding est None, la distance est infinie
    distance = np.linalg.norm(embedding2 - embedding1)
    return distance


def analyze_database(embedding, db_path, threshold=0.7): # Augmenté le seuil un peu
    """Comparaison des embeddings avec la base de données"""
    if embedding is None:
        return "visage inconnu" # Ou gérer comme une erreur
        
    min_distance = float('inf')
    best_match = None
    
    if not os.path.exists(db_path):
        # print(f"Avertissement: Le dossier de base de données '{db_path}' n'existe pas.")
        return "visage inconnu"

    for entry in os.listdir(db_path):
        if entry.endswith(".pkl"):
            try:
                with open(os.path.join(db_path, entry), 'rb') as f:
                    saved_embeddings_list = pickle.load(f)
                    for saved_emb in saved_embeddings_list:
                        distance = np.linalg.norm(embedding - saved_emb)
                        if distance < min_distance:
                            min_distance, best_match = distance, entry[:-4]
            except Exception as e:
                print(f"Erreur lors de la lecture du fichier .pkl {entry}: {e}")
                continue # Passer au fichier suivant en cas d'erreur

    return best_match if min_distance < threshold else "visage inconnu"


def save_to_database(name, face_images_rgb_dict, db_path, facenet_model):
    """Sauvegarde des embeddings avec gestion du device. Attend un dictionnaire d'images RGB."""
    if not face_images_rgb_dict:
        return "Aucune image valide fournie."
    
    embeddings = []
    
    for img_rgb in face_images_rgb_dict.values():
        if img_rgb is None:
            print("Erreur: image invalide dans le dictionnaire.")
            continue
        # S'assurer que l'image est bien un ndarray numpy RGB
        if not isinstance(img_rgb, np.ndarray) or img_rgb.ndim != 3 or img_rgb.shape[2] != 3:
            print("Erreur: L'image fournie n'est pas au format RGB numpy attendu.")
            continue
        
        embedding = face_to_embedding(img_rgb, facenet_model)
        if embedding is not None:
            embeddings.append(embedding)
        else:
            print("Avertissement: N'a pas pu générer d'embedding pour une image.")
            
    if not embeddings:
        return "Aucun embedding n'a pu être généré à partir des images fournies."

    os.makedirs(db_path, exist_ok=True)
    filename = os.path.join(db_path, f"{name}.pkl")
    
    # Si le fichier existe déjà, charger les anciens embeddings et ajouter les nouveaux
    # ou remplacer. Pour l'instant, remplaçons.
    # Si vous voulez ajouter :
    # if os.path.exists(filename):
    #     with open(filename, 'rb') as f_read:
    #         existing_embeddings = pickle.load(f_read)
    #     embeddings.extend(existing_embeddings)

    with open(filename, 'wb') as f:
        pickle.dump(embeddings, f)
    
    return f"{len(embeddings)} embeddings de visage sauvegardés pour {name}."


def normalize_lighting_color(image_color):
    """Normalise rapidement l'éclairage d'une image couleur BGR."""
    # S'assurer que l'image est bien BGR
    if image_color is None or image_color.size == 0:
        return image_color # Retourner l'original si invalide

    yuv = cv2.cvtColor(image_color, cv2.COLOR_BGR2YUV)
    y_channel = yuv[:, :, 0]
    
    # Éviter la division par zéro si la luminosité moyenne est nulle
    mean_lum = np.mean(y_channel)
    if mean_lum <= 1e-5: # Proche de zéro
        alpha_lum = 1.0 # Pas de changement
    else:
        alpha_lum = 120.0 / mean_lum 
    
    yuv[:, :, 0] = np.clip(y_channel * alpha_lum, 0, 255).astype(np.uint8)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)