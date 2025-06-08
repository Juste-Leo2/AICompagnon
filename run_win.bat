@echo off
setlocal

:: --- Configuration ---
set VENV_DIR=AI
set REQUIREMENTS_FILE=requirements.txt
set MAIN_SCRIPT=main_console.py
set PYTHON_EXE_IN_VENV=%VENV_DIR%\Scripts\python.exe
set ACTIVATE_SCRIPT=%VENV_DIR%\Scripts\activate.bat
set UV_EXE_IN_VENV=%VENV_DIR%\Scripts\uv.exe

:: Options spécifiques pour l'installation avec UV (conservées)
set UV_INSTALL_OPTIONS=--no-cache --no-deps --index-strategy unsafe-best-match

echo Vérification de Python...
python --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Erreur : 'python' n'est pas trouvé dans le PATH.
    echo Veuillez installer Python et vous assurer qu'il est accessible.
    goto :error_exit
)

:: 1. Vérifier si l'environnement virtuel existe
echo Vérification de l'environnement virtuel (%VENV_DIR%)...
if not exist "%ACTIVATE_SCRIPT%" (
    echo L'environnement n'existe pas. Création en cours avec python -m venv...
    python -m venv "%VENV_DIR%"
    if %ERRORLEVEL% NEQ 0 (
        echo Erreur lors de la création de l'environnement virtuel avec Python.
        goto :error_exit
    )
    echo Environnement créé avec succès dans le dossier '%VENV_DIR%'.
) else (
    echo Environnement virtuel '%VENV_DIR%' trouvé.
)

:: 2. Activer l'environnement virtuel
echo Activation de l'environnement virtuel '%VENV_DIR%'...
call "%ACTIVATE_SCRIPT%"
if %ERRORLEVEL% NEQ 0 (
    echo Erreur lors de l'activation de l'environnement virtuel.
    goto :error_exit
)
echo Environnement activé.

:: 3. Mettre à jour pip dans l'environnement virtuel
echo Mise à jour de pip dans l'environnement...
"%PYTHON_EXE_IN_VENV%" -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 (
    echo Erreur lors de la mise à jour de pip.
    goto :error_exit
)
echo Pip mis à jour.

:: 4. Installer 'uv' dans l'environnement virtuel
echo Installation de 'uv' dans l'environnement via pip...
"%PYTHON_EXE_IN_VENV%" -m pip install uv
if %ERRORLEVEL% NEQ 0 (
    echo Erreur : Impossible d'installer 'uv' avec pip dans l'environnement.
    goto :error_exit
)
echo 'uv' installé dans l'environnement.

:: 5. Vérifier si le fichier requirements existe
if not exist "%REQUIREMENTS_FILE%" (
    echo Erreur : Le fichier '%REQUIREMENTS_FILE%' est introuvable.
    goto :error_exit
)

:: 6. Définir CMAKE_ARGS pour Vulkan et installer les dépendances
echo Configuration des arguments CMake pour la compilation avec Vulkan (llama.cpp)...
set CMAKE_ARGS=-DLLAMA_VULKAN=ON
echo CMAKE_ARGS=%CMAKE_ARGS%

echo Installation/Vérification des dépendances depuis %REQUIREMENTS_FILE% avec 'uv pip'...
echo (Utilisation des options : %UV_INSTALL_OPTIONS%)
"%UV_EXE_IN_VENV%" pip install %UV_INSTALL_OPTIONS% -r "%REQUIREMENTS_FILE%"
if %ERRORLEVEL% NEQ 0 (
    echo Attention : Erreur potentielle lors de l'installation des dépendances avec 'uv pip'.
    echo Les options '%UV_INSTALL_OPTIONS%' et CMAKE_ARGS=%CMAKE_ARGS% peuvent causer des problèmes ou indiquer un échec de compilation.
    echo Le script va tenter de continuer, mais l'exécution de '%MAIN_SCRIPT%' pourrait échouer.
) else (
    echo Dépendances installées/vérifiées avec 'uv pip'.
)

:: 7. Vérifier si le script principal existe
if not exist "%MAIN_SCRIPT%" (
    echo Erreur : Le script principal '%MAIN_SCRIPT%' est introuvable.
    goto :error_exit
)

:: 8. Exécuter le script principal avec 'uv run' depuis l'environnement
echo Exécution de %MAIN_SCRIPT% avec 'uv run'...
echo --- Début de l'exécution de %MAIN_SCRIPT% ---
echo.

"%UV_EXE_IN_VENV%" run "%MAIN_SCRIPT%"
set SCRIPT_EXIT_CODE=%ERRORLEVEL%

echo.
echo --- Fin de l'exécution de %MAIN_SCRIPT% (Code de sortie: %SCRIPT_EXIT_CODE%) ---

if %SCRIPT_EXIT_CODE% NEQ 0 (
    echo Le script %MAIN_SCRIPT% s'est terminé avec une erreur (Code: %SCRIPT_EXIT_CODE%).
    goto :error_exit_script
)

echo Terminé avec succès.
goto :success_exit

:error_exit
echo.
echo ECHEC : Une erreur est survenue pendant la configuration.
endlocal
exit /b 1

:error_exit_script
echo.
echo ECHEC : Le script Python a retourné une erreur.
endlocal
exit /b %SCRIPT_EXIT_CODE%

:success_exit
endlocal
exit /b 0
