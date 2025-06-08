#!/bin/bash

# ==============================================================================
# Script de téléchargement des modèles avec vérification d'existence
# Compatible Linux / macOS
# Exécution : chmod +x download_models.sh && ./download_models.sh
# ==============================================================================

echo ">>> Lancement du script de téléchargement des modèles (avec vérification et skip des erreurs de download) <<<"

# ==============================================================================
# Configuration des chemins
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${SCRIPT_DIR}/model"
KOKORO_DIR="${MODEL_DIR}/kokoroTTS"
EMOTION_DIR="${MODEL_DIR}/emotion_model"
VOSK_ZIP_URL="https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
VOSK_ZIP_FILENAME="vosk-model-small-fr-0.22.zip"
VOSK_ZIP_PATH="${MODEL_DIR}/${VOSK_ZIP_FILENAME}"
VOSK_EXTRACTED_DIR="${MODEL_DIR}/vosk-model-small-fr-0.22"

# ==============================================================================
# Vérifier que curl est installé
# ==============================================================================
if ! command -v curl &> /dev/null; then
    echo "ERREUR CRITIQUE : curl n'est pas installé. Installez-le d'abord (ex: sudo apt install curl)"
    exit 1
fi
echo ">>> curl détecté."

# ==============================================================================
# Création des dossiers
# ==============================================================================
echo ">>> Création des dossiers nécessaires..."
mkdir -p "$MODEL_DIR" "$KOKORO_DIR" "$EMOTION_DIR"
echo ">>> Dossiers créés ou déjà existants."

# ==============================================================================
# Téléchargement des modèles KokoroTTS
# ==============================================================================
echo
echo ">>> Téléchargement des modèles KokoroTTS..."

KOKORO_ONNX_FILE="kokoro-v1.0.onnx"
KOKORO_ONNX_PATH="${KOKORO_DIR}/${KOKORO_ONNX_FILE}"
if [ -f "$KOKORO_ONNX_PATH" ]; then
    echo "$KOKORO_ONNX_FILE déjà présent. Téléchargement ignoré."
else
    echo "Téléchargement de $KOKORO_ONNX_FILE..."
    curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -o "$KOKORO_ONNX_PATH" || echo "!!! Échec du téléchargement de $KOKORO_ONNX_FILE !!!"
fi

KOKORO_VOICES_FILE="voices-v1.0.bin"
KOKORO_VOICES_PATH="${KOKORO_DIR}/${KOKORO_VOICES_FILE}"
if [ -f "$KOKORO_VOICES_PATH" ]; then
    echo "$KOKORO_VOICES_FILE déjà présent. Téléchargement ignoré."
else
    echo "Téléchargement de $KOKORO_VOICES_FILE..."
    curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -o "$KOKORO_VOICES_PATH" || echo "!!! Échec du téléchargement de $KOKORO_VOICES_FILE !!!"
fi

echo ">>> Modèles KokoroTTS téléchargés."

# ==============================================================================
# Téléchargement des modèles d'émotion
# ==============================================================================
echo
echo ">>> Téléchargement des modèles d'émotion..."

download_emotion_file() {
    local filename="$1"
    local url="$2"
    local dest="${EMOTION_DIR}/${filename}"
    if [ -f "$dest" ]; then
        echo "$filename déjà présent. Téléchargement ignoré."
    else
        echo "Téléchargement de $filename..."
        curl -L "$url" -o "$dest" || echo "!!! Échec du téléchargement de $filename !!!"
    fi
}

download_emotion_file "model.safetensors" "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/model.safetensors?download=true"
download_emotion_file "config.json" "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/config.json?download=true"
download_emotion_file "preprocessor_config.json" "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/preprocessor_config.json?download=true"

echo ">>> Modèles d'émotion téléchargés."

# ==============================================================================
# Téléchargement du modèle GGUF (Gemma)
# ==============================================================================
echo
echo ">>> Téléchargement du modèle Gemma..."

GEMMA_FILE="gemma-3-4B-it-QAT-Q4_0.gguf"
GEMMA_PATH="${MODEL_DIR}/${GEMMA_FILE}"

if [ -f "$GEMMA_PATH" ]; then
    echo "$GEMMA_FILE déjà présent. Téléchargement ignoré."
else
    echo "Téléchargement de $GEMMA_FILE..."
    curl -L "https://huggingface.co/lmstudio-community/gemma-3-4B-it-qat-GGUF/resolve/main/${GEMMA_FILE}?download=true" -o "$GEMMA_PATH" || echo "!!! Échec du téléchargement de $GEMMA_FILE !!!"
fi

echo ">>> Modèle Gemma téléchargé."

# ==============================================================================
# Téléchargement et extraction du modèle Vosk
# ==============================================================================
echo
echo ">>> Téléchargement et extraction du modèle Vosk..."

if [ -f "$VOSK_ZIP_PATH" ]; then
    echo "$VOSK_ZIP_FILENAME déjà présent. Téléchargement ignoré."
else
    echo "Téléchargement de $VOSK_ZIP_FILENAME..."
    curl -L "$VOSK_ZIP_URL" -o "$VOSK_ZIP_PATH" || echo "!!! Échec du téléchargement de $VOSK_ZIP_FILENAME !!!"
fi

if [ -d "$VOSK_EXTRACTED_DIR" ]; then
    echo "Modèle Vosk déjà extrait. Extraction ignorée."
else
    echo "Extraction de $VOSK_ZIP_FILENAME..."
    unzip -q "$VOSK_ZIP_PATH" -d "$MODEL_DIR" || echo "!!! Échec de l'extraction du modèle Vosk !!!"
fi

echo ">>> Modèle Vosk téléchargé et extrait."

# ==============================================================================
# Fin du script
# ==============================================================================
echo
echo ">>> Script terminé. Vérifiez les messages ci-dessus pour toute erreur éventuelle. <<<"
