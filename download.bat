@echo off
setlocal

REM ==============================================================================
REM Script de telechargement des modeles avec verification d'existence
REM CE SCRIPT NE S'ARRETE PAS SUR LES ERREURS DE TELECHARGEMENT INDIVIDUELLES
REM Placer ce fichier download.bat à la racine de votre projet.
REM Exécuter ce script : double-clic ou via invite de commande.
REM ==============================================================================

echo ^>^>^> Lancement du script de telechargement des modeles (avec verification et skip des erreurs de download) ^<^<^<

REM ==============================================================================
REM Configuration des chemins
REM ==============================================================================
set "MODEL_DIR=%~dp0model"
set "KOKORO_DIR=%MODEL_DIR%\kokoroTTS\"
set "EMOTION_DIR=%MODEL_DIR%\emotion_model\"
set "VOSK_ZIP_URL=https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
set "VOSK_ZIP_FILENAME=vosk-model-small-fr-0.22.zip"
set "VOSK_ZIP_PATH=%MODEL_DIR%\%VOSK_ZIP_FILENAME%"
set "VOSK_EXTRACTED_DIR=%MODEL_DIR%\vosk-model-small-fr-0.22"

REM ==============================================================================
REM Verifier si curl est disponible
REM ==============================================================================
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo ERREUR CRITIQUE : curl n'est pas trouve. Installez-le ou ajoutez-le au PATH.
    goto :end
)
echo ^>^>^> curl trouve.

REM ==============================================================================
REM Creer les repertoires necessaires
REM ==============================================================================
echo ^>^>^> Creation des repertoires...
mkdir "%MODEL_DIR%" >nul 2>&1
mkdir "%KOKORO_DIR%" >nul 2>&1
mkdir "%EMOTION_DIR%" >nul 2>&1
echo ^>^>^> Repertoires crees ou deja existants.

REM ==============================================================================
REM Gestion des modeles KokoroTTS
REM ==============================================================================
echo.
echo ^>^>^> Gestion des modeles KokoroTTS dans "%KOKORO_DIR%"...

set "KOKORO_ONNX_FILE=kokoro-v1.0.onnx"
set "KOKORO_ONNX_PATH=%KOKORO_DIR%%KOKORO_ONNX_FILE%"
if exist "%KOKORO_ONNX_PATH%" (
    echo "%KOKORO_ONNX_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%KOKORO_ONNX_FILE%"...
    curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -o "%KOKORO_ONNX_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %KOKORO_ONNX_FILE% a echoue, mais le script continue. !!!
)

set "KOKORO_VOICES_FILE=voices-v1.0.bin"
set "KOKORO_VOICES_PATH=%KOKORO_DIR%%KOKORO_VOICES_FILE%"
if exist "%KOKORO_VOICES_PATH%" (
    echo "%KOKORO_VOICES_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%KOKORO_VOICES_FILE%"...
    curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -o "%KOKORO_VOICES_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %KOKORO_VOICES_FILE% a echoue, mais le script continue. !!!
)
echo ^>^>^> Gestion des modeles KokoroTTS terminee.

REM ==============================================================================
REM Gestion des modeles Emotion
REM ==============================================================================
echo.
echo ^>^>^> Gestion des modeles Emotion dans "%EMOTION_DIR%"...

set "EMOTION_SAFETENSOR_FILE=model.safetensors"
set "EMOTION_SAFETENSOR_PATH=%EMOTION_DIR%%EMOTION_SAFETENSOR_FILE%"
if exist "%EMOTION_SAFETENSOR_PATH%" (
    echo "%EMOTION_SAFETENSOR_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%EMOTION_SAFETENSOR_FILE%"...
    curl -L "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/model.safetensors?download=true" -o "%EMOTION_SAFETENSOR_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %EMOTION_SAFETENSOR_FILE% a echoue, mais le script continue. !!!
)

set "EMOTION_CONFIG_FILE=config.json"
set "EMOTION_CONFIG_PATH=%EMOTION_DIR%%EMOTION_CONFIG_FILE%"
if exist "%EMOTION_CONFIG_PATH%" (
    echo "%EMOTION_CONFIG_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%EMOTION_CONFIG_FILE%"...
    curl -L "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/config.json?download=true" -o "%EMOTION_CONFIG_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %EMOTION_CONFIG_FILE% a echoue, mais le script continue. !!!
)

set "EMOTION_PREPROCESSOR_FILE=preprocessor_config.json"
set "EMOTION_PREPROCESSOR_PATH=%EMOTION_DIR%%EMOTION_PREPROCESSOR_FILE%"
if exist "%EMOTION_PREPROCESSOR_PATH%" (
    echo "%EMOTION_PREPROCESSOR_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%EMOTION_PREPROCESSOR_FILE%"...
    curl -L "https://huggingface.co/dima806/facial_emotions_image_detection/resolve/main/preprocessor_config.json?download=true" -o "%EMOTION_PREPROCESSOR_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %EMOTION_PREPROCESSOR_FILE% a echoue, mais le script continue. !!!
)
echo ^>^>^> Gestion des modeles Emotion terminee.

REM ==============================================================================
REM Telechargement du modele Gemma 3 IT QAT (.gguf) directement dans model\
REM ==============================================================================
echo.
echo ^>^>^> Telechargement du modele Gemma 3 IT QAT...

set "GEMMA_FILE=gemma-3-4B-it-QAT-Q4_0.gguf"
set "GEMMA_PATH=%MODEL_DIR%\%GEMMA_FILE%"

if exist "%GEMMA_PATH%" (
    echo "%GEMMA_FILE%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%GEMMA_FILE%"...
    curl -L "https://huggingface.co/lmstudio-community/gemma-3-4B-it-qat-GGUF/resolve/main/gemma-3-4B-it-QAT-Q4_0.gguf?download=true" -o "%GEMMA_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement de %GEMMA_FILE% a echoue, mais le script continue. !!!
)
echo ^>^>^> Telechargement du modele Gemma 3 IT QAT termine.

REM ==============================================================================
REM Gestion du modele Vosk (ZIP) et extraction
REM ==============================================================================
echo.
echo ^>^>^> Gestion du modele Vosk (ZIP) et Extraction...

if exist "%VOSK_ZIP_PATH%" (
    echo "%VOSK_ZIP_FILENAME%" existe deja. Telechargement saute.
) else (
    echo Tentative de telechargement de "%VOSK_ZIP_FILENAME%"...
    curl -L "%VOSK_ZIP_URL%" -o "%VOSK_ZIP_PATH%"
    if %errorlevel% neq 0 echo !!! AVERTISSEMENT : Le telechargement du modele Vosk zip a echoue, mais le script continue. !!!
)

if exist "%VOSK_EXTRACTED_DIR%" (
    echo Modele Vosk deja extrait. Extraction sautee.
) else (
    echo Tentative d'extraction vers "%MODEL_DIR%"...
    powershell -NoProfile -ExecutionPolicy Bypass -command "Expand-Archive -Path '%VOSK_ZIP_PATH%' -DestinationPath '%MODEL_DIR%' -Force"
    if %errorlevel% neq 0 (
        echo !!! ERREUR : Echec de l'extraction du modele Vosk !!!
    )
)
echo ^>^>^> Gestion du modele Vosk terminee.

REM ==============================================================================
REM Fin du script
REM ==============================================================================
echo.
echo ^>^>^> Script termine. Veuillez VERIFIER les messages ci-dessus pour les erreurs ^<^<^<

goto :eof

:end
echo.
echo ^>^>^> Le script a rencontre une erreur CRITIQUE (curl non trouve) et n'a pas pu continuer. ^<^<^<

endlocal
