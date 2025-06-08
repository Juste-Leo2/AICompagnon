#!/bin/bash
# Equivalent to the provided .bat file for Linux/macOS/WSL

# --- Configuration ---
VENV_DIR="AI"
REQUIREMENTS_FILE="requirements.txt"
MAIN_SCRIPT="main_console.py"

# Paths within the virtual environment (Unix-style)
PYTHON_EXE_IN_VENV="${VENV_DIR}/bin/python"
ACTIVATE_SCRIPT="${VENV_DIR}/bin/activate"
UV_EXE_IN_VENV="${VENV_DIR}/bin/uv"

# Specific options for UV installation (preserved)
UV_INSTALL_OPTIONS="--no-cache --no-deps --index-strategy unsafe-best-match"

# --- Error Handling Function ---
# Fonction pour afficher un message d'erreur et quitter
exit_on_error() {
    local exit_code=$1
    local message="$2"
    echo -e "\n\e[31mECHEC : $message\e[0m" >&2 # Affiche en rouge sur stderr
    exit "$exit_code"
}

# --- Main Logic ---

echo "Vérification de Python..."
python --version >/dev/null 2>&1
if [ $? -ne 0 ]; then
    exit_on_error 1 "Erreur : 'python' n'est pas trouvé dans le PATH. Veuillez installer Python et vous assurer qu'il est accessible."
fi

# 1. Vérifier si l'environnement virtuel existe
echo "Vérification de l'environnement virtuel (${VENV_DIR})..."
if [ ! -f "${ACTIVATE_SCRIPT}" ]; then
    echo "L'environnement n'existe pas. Création en cours avec python -m venv..."
    python -m venv "${VENV_DIR}"
    if [ $? -ne 0 ]; then
        exit_on_error 1 "Erreur lors de la création de l'environnement virtuel avec Python."
    fi
    echo "Environnement créé avec succès dans le dossier '${VENV_DIR}'."
else
    echo "Environnement virtuel '${VENV_DIR}' trouvé."
fi

# 2. Activer l'environnement virtuel
echo "Activation de l'environnement virtuel '${VENV_DIR}'..."
# 'source' (ou '.') est crucial pour activer l'environnement dans le shell courant
source "${ACTIVATE_SCRIPT}"
if [ $? -ne 0 ]; then
    exit_on_error 1 "Erreur lors de l'activation de l'environnement virtuel."
fi
echo "Environnement activé."

# 3. Mettre à jour pip dans l'environnement virtuel
echo "Mise à jour de pip dans l'environnement..."
"${PYTHON_EXE_IN_VENV}" -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    exit_on_error 1 "Erreur lors de la mise à jour de pip."
fi
echo "Pip mis à jour."

# 4. Installer 'uv' dans l'environnement virtuel
echo "Installation de 'uv' dans l'environnement via pip..."
"${PYTHON_EXE_IN_VENV}" -m pip install uv
if [ $? -ne 0 ]; then
    exit_on_error 1 "Erreur : Impossible d'installer 'uv' avec pip dans l'environnement."
fi
echo "'uv' installé dans l'environnement."

# 5. Vérifier si le fichier requirements existe
if [ ! -f "${REQUIREMENTS_FILE}" ]; then
    exit_on_error 1 "Erreur : Le fichier '${REQUIREMENTS_FILE}' est introuvable."
fi

# 6. Définir CMAKE_ARGS pour Vulkan et installer les dépendances
echo "Configuration des arguments CMake pour la compilation avec Vulkan (llama.cpp)..."
# 'export' est utilisé pour que la variable soit disponible pour les sous-processus (comme uv)
export CMAKE_ARGS="-DLLAMA_VULKAN=ON"
echo "CMAKE_ARGS=${CMAKE_ARGS}"

echo "Installation/Vérification des dépendances depuis ${REQUIREMENTS_FILE} avec 'uv pip'..."
echo "(Utilisation des options : ${UV_INSTALL_OPTIONS})"
"${UV_EXE_IN_VENV}" pip install ${UV_INSTALL_OPTIONS} -r "${REQUIREMENTS_FILE}"
UV_INSTALL_EXIT_CODE=$?
if [ ${UV_INSTALL_EXIT_CODE} -ne 0 ]; then
    echo "Attention : Erreur potentielle lors de l'installation des dépendances avec 'uv pip'."
    echo "Les options '${UV_INSTALL_OPTIONS}' et CMAKE_ARGS=${CMAKE_ARGS} peuvent causer des problèmes ou indiquer un échec de compilation."
    echo "Le script va tenter de continuer, mais l'exécution de '${MAIN_SCRIPT}' pourrait échouer."
    # Le script original continue malgré cette erreur, donc nous faisons de même.
else
    echo "Dépendances installées/vérifiées avec 'uv pip'."
fi

# 7. Vérifier si le script principal existe
if [ ! -f "${MAIN_SCRIPT}" ]; then
    exit_on_error 1 "Erreur : Le script principal '${MAIN_SCRIPT}' est introuvable."
fi

# 8. Exécuter le script principal avec 'uv run' depuis l'environnement
echo "Exécution de ${MAIN_SCRIPT} avec 'uv run'..."
echo "--- Début de l'exécution de ${MAIN_SCRIPT} ---"
echo "" # Ligne vide

"${UV_EXE_IN_VENV}" run "${MAIN_SCRIPT}"
SCRIPT_EXIT_CODE=$?

echo "" # Ligne vide
echo "--- Fin de l'exécution de ${MAIN_SCRIPT} (Code de sortie: ${SCRIPT_EXIT_CODE}) ---"

if [ ${SCRIPT_EXIT_CODE} -ne 0 ]; then
    exit_on_error ${SCRIPT_EXIT_CODE} "Le script ${MAIN_SCRIPT} s'est terminé avec une erreur (Code: ${SCRIPT_EXIT_CODE})."
fi

echo "Terminé avec succès."
exit 0
