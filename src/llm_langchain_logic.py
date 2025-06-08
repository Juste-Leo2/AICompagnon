import os
import re
import sqlite3
import pickle
from datetime import datetime
from collections import deque
import sys

import numpy as np
from langchain_community.llms import LlamaCpp
from langchain.agents import Tool
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document

NEW_FACE_REQUEST_LANGCHAIN = False # Flag global pour la demande d'enregistrement

# --- Configuration ---
MEMORY_DIR = "memory_langchain"
VECTOR_STORE_INDEX_DIR = os.path.join(MEMORY_DIR, "vector_store_stm")
VECTOR_IDS_PATH = os.path.join(MEMORY_DIR, "vector_store_stm_ids.pkl")
LTM_DB_PATH = os.path.join(MEMORY_DIR, "long_term_memory.db")

MODEL_DIR = "./model"
MODEL_NAME = "gemma-3-4B-it-QAT-Q4_0.gguf"
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME)

NUM_RECENT_TURNS_FOR_DIRECT_CONTEXT = 3
MAX_STM_VECTOR_COUNT = 100
NUM_TURNS_FOR_EMOTION_CONTEXT = 3

llm_tool_decider = None
llm_final_responder = None
llm_emotion_agent = None
embeddings_model = None
stm_vectorstore = None
stm_vector_id_deque = deque()
stm_retriever = None # Ajouté pour être initialisé
conversation_history_deque = deque(maxlen=NUM_RECENT_TURNS_FOR_DIRECT_CONTEXT * 2)
full_conversation_log_for_emotion_agent = deque(maxlen=NUM_TURNS_FOR_EMOTION_CONTEXT * 2)

_CURRENT_USER_QUERY_FOR_STM_TOOL = ""

def init_llms_and_memory():
    global llm_tool_decider, llm_final_responder, llm_emotion_agent, embeddings_model
    global stm_vectorstore, stm_vector_id_deque, stm_retriever
    global conversation_history_deque, full_conversation_log_for_emotion_agent

    print("--- Initialisation Langchain LLM et Mémoires ---")
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR); print(f"Dossier '{MEMORY_DIR}' créé.")
    if not os.path.exists(VECTOR_STORE_INDEX_DIR): os.makedirs(VECTOR_STORE_INDEX_DIR); print(f"Dossier '{VECTOR_STORE_INDEX_DIR}' créé.")
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Modèle LLM non trouvé: {MODEL_PATH}")

    common_llm_params = {
        "model_path": MODEL_PATH,
        "n_gpu_layers": -1,
        "n_ctx": 2048,
        "verbose": False,
        "model_kwargs": {"backend": "vulkan"},
    }
    try:
        llm_tool_decider = LlamaCpp(**common_llm_params, temperature=0.05, max_tokens=100,
            stop=["\n", "Utilisateur:", "Julie:", "Historique:", "Outils disponibles:", "Décision d'outil:", "Réponse:", "Assistant:"])
        llm_final_responder = LlamaCpp(**common_llm_params, temperature=0.65, max_tokens=250,
            stop=["Utilisateur:", "Utilisateur :", "\nUtilisateur:", "Julie:", "Julie :", "\nJulie:",
                  "Assistant:", "Assistant :", "\nAssistant:", "\n\n", "<|eot_id|>", "<|end_of_turn|>"])
        llm_emotion_agent = LlamaCpp(**common_llm_params, temperature=0.05, max_tokens=30, stop=["\n", ".", ","])
        print("LLMs LlamaCpp initialisés.")
    except Exception as e:
        print(f"ERREUR CRITIQUE lors de l'initialisation des LLMs LlamaCpp: {e}")
        raise

    embeddings_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    print("Modèle d'embeddings HuggingFace chargé.")

    if os.path.exists(os.path.join(VECTOR_STORE_INDEX_DIR, "index.faiss")):
        print("Chargement de la STM (FAISS) existante...")
        try:
            stm_vectorstore = FAISS.load_local(
                VECTOR_STORE_INDEX_DIR,
                embeddings_model,
                allow_dangerous_deserialization=True
            )
            if os.path.exists(VECTOR_IDS_PATH):
                with open(VECTOR_IDS_PATH, "rb") as f: stm_vector_id_deque = pickle.load(f)
        except Exception as e_faiss_load:
            print(f"Erreur chargement FAISS, réinitialisation: {e_faiss_load}")
            stm_vectorstore = None
    
    if stm_vectorstore is None:
        print("Création/Réinitialisation d'une nouvelle STM (FAISS)...")
        initial_doc_stm = Document(page_content="Début de la mémoire à court terme sémantique.")
        stm_vectorstore = FAISS.from_documents([initial_doc_stm], embedding=embeddings_model)
        initial_marker_text = "Marqueur initial STM unique"
        added_ids = stm_vectorstore.add_texts([initial_marker_text])
        stm_vector_id_deque.clear()
        if added_ids: stm_vector_id_deque.append(added_ids[0])
        stm_vectorstore.save_local(VECTOR_STORE_INDEX_DIR)
        with open(VECTOR_IDS_PATH, "wb") as f: pickle.dump(stm_vector_id_deque, f)
    
    stm_retriever = stm_vectorstore.as_retriever(search_kwargs=dict(k=3))
    print("STM (FAISS sémantique) prête.")
    init_ltm_db()
    print("LTM (SQLite persistante) prête.")

    print("Chauffage des modèles LLM...")
    try:
        _ = llm_tool_decider.invoke(TOOL_DECIDE_PROMPT_TEMPLATE.format(tools_description="Test", conversation_history_for_tool_decider="Test", input="Test"))
        _ = llm_final_responder.invoke(FINAL_RESPONSE_PROMPT_TEMPLATE.format(user_name="Testeur",user_detected_emotion="neutre",tool_results_context="Aucun.",conversation_history_for_responder="Utilisateur: Bonjour.") + "Julie:")
        _ = llm_emotion_agent.invoke(EMOTION_DETECT_PROMPT_TEMPLATE.format(recent_history_for_emotion="Utilisateur: test", text_to_analyze="test") + "\nÉmotion de Julie:")
        print("Modèles LLM chauffés.")
    except Exception as e_warmup:
        print(f"Erreur lors du chauffage des modèles LLM: {e_warmup}")
    print("--- Initialisation Langchain LLM et Mémoires terminée ---")

def init_ltm_db():
    conn = sqlite3.connect(LTM_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ltm_conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL, user_input TEXT NOT NULL, ai_response TEXT NOT NULL,
        ai_response_emotion TEXT, user_name TEXT, user_detected_emotion TEXT
    )""")
    conn.commit(); conn.close()

def save_to_long_term_memory(user_input_raw: str, ai_response_raw: str, ai_emotion: str, user_name: str, user_detected_emotion: str):
    conn = sqlite3.connect(LTM_DB_PATH); cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute("""INSERT INTO ltm_conversation_history
                       (timestamp, user_input, ai_response, ai_response_emotion, user_name, user_detected_emotion)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                       (timestamp, user_input_raw, ai_response_raw, ai_emotion, user_name, user_detected_emotion))
        conn.commit()
    except sqlite3.Error as e: print(f"Erreur LTM sauvegarde: {e}")
    finally: conn.close()

def add_to_stm_and_slide(texts_to_add: list[str]):
    global stm_vectorstore, stm_vector_id_deque
    if not texts_to_add or stm_vectorstore is None: return
    str_texts_to_add = [str(text) for text in texts_to_add]
    try:
        new_ids = stm_vectorstore.add_texts(str_texts_to_add)
        if new_ids: stm_vector_id_deque.extend(new_ids)
    except Exception as e_add: print(f"Erreur ajout STM sémantique: {e_add}"); return
    
    ids_to_remove_list = []
    while len(stm_vector_id_deque) > MAX_STM_VECTOR_COUNT:
        if stm_vector_id_deque: ids_to_remove_list.append(stm_vector_id_deque.popleft())
        else: break
    
    if ids_to_remove_list:
        try:
            num_deleted = stm_vectorstore.delete(ids_to_remove_list)
            if num_deleted:
                 print(f"STM: Supprimé {len(ids_to_remove_list)} anciens éléments de FAISS.")
            else:
                print(f"STM: Échec de la suppression de {len(ids_to_remove_list)} éléments de FAISS.")
        except NotImplementedError:
             print("STM: La suppression d'éléments n'est pas supportée.")
        except Exception as e_delete:
            print(f"Erreur suppression STM sémantique: {e_delete}.")
            for id_val in reversed(ids_to_remove_list): stm_vector_id_deque.appendleft(id_val)
    try:
        stm_vectorstore.save_local(VECTOR_STORE_INDEX_DIR)
        with open(VECTOR_IDS_PATH, "wb") as f: pickle.dump(stm_vector_id_deque, f)
    except Exception as e_save: print(f"Erreur sauvegarde STM sémantique: {e_save}")

def reset_short_term_context_deques():
    global conversation_history_deque, full_conversation_log_for_emotion_agent
    print("--- Réinitialisation des deques de contexte direct ---")
    conversation_history_deque.clear()
    full_conversation_log_for_emotion_agent.clear()

def get_current_time_func(tool_input: str = "") -> str: return f"Il est {datetime.now().strftime('%H heures %M')}."
def end_conversation_func(tool_input: str = "") -> str: return "FIN_CONVERSATION_DEMANDEE_PAR_OUTIL"

def enregistrer_visage_tool_func(tool_input: str = "") -> str: # MODIFIÉ
    global NEW_FACE_REQUEST_LANGCHAIN
    NEW_FACE_REQUEST_LANGCHAIN = True # Signale à main_console de lancer la procédure
    return "La demande d'enregistrement de visage a été reçue. Je vais vous guider pour cela : demandez votre prénom et prenez quelques photos."

def query_short_term_memory_tool(tool_input: str = "") -> str:
    global _CURRENT_USER_QUERY_FOR_STM_TOOL, stm_retriever
    if not _CURRENT_USER_QUERY_FOR_STM_TOOL: return "Pas de question utilisateur actuelle pour la STM."
    if stm_retriever is None: return "Erreur: STM sémantique (FAISS) non initialisée."
    try:
        retrieved_docs = stm_retriever.invoke(_CURRENT_USER_QUERY_FOR_STM_TOOL)
        if not retrieved_docs: return "Aucun souvenir sémantique pertinent trouvé en STM."
        return "Souvenirs sémantiques STM:\n" + "\n".join([f"- \"{doc.page_content[:150]}\"" for doc in retrieved_docs])
    except Exception as e: return f"Erreur lors de la recherche en STM sémantique: {e}"

def query_long_term_memory_tool(query_keywords: str) -> str:
    if LTM_DB_PATH is None: return "Erreur: LTM (SQLite) non configurée."
    conn = sqlite3.connect(LTM_DB_PATH); cursor = conn.cursor()
    keywords = [kw.strip() for kw in query_keywords.split(',') if kw.strip()]
    if not keywords: return "Mots-clés pour la recherche LTM invalides ou manquants."
    
    conditions = []
    params = []
    for kw in keywords:
        conditions.append("(user_input LIKE ? OR ai_response LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
        
    sql_query = f"""
        SELECT timestamp, user_input, ai_response, user_name
        FROM ltm_conversation_history
        WHERE {' AND '.join(conditions)}
        ORDER BY timestamp DESC
        LIMIT 3
    """
    try:
        results = cursor.execute(sql_query, params).fetchall()
    except sqlite3.Error as e:
        return f"Erreur lors de la recherche en LTM: {e}"
    finally:
        conn.close()
        
    if not results: return "Aucun souvenir LTM trouvé pour ces mots-clés."
    return "Souvenirs LTM:\n" + "\n".join([f"- Le {r[0]} (avec {r[3] or 'Utilisateur'}), U: '{r[1][:70]}...', J: '{r[2][:70]}...'" for r in results])

tools_list = [
    Tool(name="get_current_time", func=get_current_time_func, description="Obtenir l'heure actuelle si demandée explicitement. Format: `get_current_time()`"),
    Tool(name="enregistrer_visage_utilisateur", func=enregistrer_visage_tool_func, description="Si l'utilisateur demande EXPLICITEMENT d'enregistrer son visage. Format: `enregistrer_visage_utilisateur()`"), # Description mise à jour
    Tool(name="query_short_term_memory", func=query_short_term_memory_tool, description="Consulter la mémoire sémantique des échanges récents. Format: `query_short_term_memory()`"),
    Tool(name="query_long_term_memory", func=query_long_term_memory_tool, description="Rechercher dans l'historique complet par mots-clés. Format: `query_long_term_memory(query_keywords='mot_clé1, mot_clé2')`"),
    Tool(name="end_conversation", func=end_conversation_func, description="Si l'utilisateur veut CLAIREMENT finir. Format: `end_conversation()`")
]
tools_map = {tool.name: tool for tool in tools_list}

EMOTIONS_LIST_FOR_AGENT = ["joie", "tristesse", "neutre", "colère", "surprise", "peur", "dégout"]
EMOTION_DETECT_PROMPT_TEMPLATE = f"""Tu interprètes l'émotion de Julie basée sur sa réponse et le contexte récent.
réponds à une émotion de façon ampathique : s'il est dégoûté, alors met l'émotion associé au dégout.
Si la réponse de julie fait pensé à une autre émotion, par exemple l'utilisateur semble énerver et julie répond de manière rassurante, adapte toi.
Contexte récent de la conversation:
{{recent_history_for_emotion}}
La réponse de Julie à analyser est: "{{text_to_analyze}}"

Choisis une seule émotion la plus appropriée pour Julie parmi : {', '.join(EMOTIONS_LIST_FOR_AGENT)}.
Réponds UNIQUEMENT avec le nom de l'émotion.
Émotion de Julie:"""


TOOL_DECIDE_PROMPT_TEMPLATE = """Tu es un assistant qui décide si un outil doit être utilisé pour répondre à l'Utilisateur.
Outils disponibles:
{tools_description}

Considère l'historique récent et la question actuelle de l'utilisateur.
- `query_short_term_memory()`: Pour les infos dans les échanges récents mais pas immédiatement précédents.
- `query_long_term_memory(query_keywords='...')`: Pour des sujets plus anciens, nécessite des mots-clés pertinents extraits de la question de l'utilisateur.
- `get_current_time()`: Si l'heure est demandée.
- `enregistrer_visage_utilisateur()`: Si l'utilisateur demande à enregistrer son visage.
- `end_conversation()`: Si l'utilisateur veut explicitement arrêter.

Réponds sur UNE SEULE LIGNE.
- Si AUCUN outil n'est nécessaire, réponds EXACTEMENT: `NONE`
- Si UN outil est nécessaire, réponds avec l'appel de fonction (ex: `tool_name()` ou `tool_name(query_keywords='...')`).
- NE PAS expliquer ta décision. NE PAS ajouter de texte avant ou après l'appel de l'outil ou `NONE`.

Historique récent (contexte direct de cette conversation):
{conversation_history_for_tool_decider}

Utilisateur: {input}
Décision d'outil:"""

FINAL_RESPONSE_PROMPT_TEMPLATE = """Tu es Julie, une IA amicale et serviable. Poursuis la conversation de manière naturelle et concise.
Soit plutot positif dans tes réponses, ne t'excuse pas. Comporte toi de façon empathique, s'il est dégouter, alors soit dégouté.
INTERDICTION DE REPETER LES MESSAGES PRECEDANTS

Contexte de l'utilisateur:
- Prénom: {user_name}
- Émotion détectée chez l'utilisateur (à prendre avec précaution, peut être "impossible" ou "---"): {user_detected_emotion}

{tool_results_context}
Historique de la conversation (le dernier message est celui de l'utilisateur, tu dois fournir ta réponse en tant que Julie):
{conversation_history_for_responder}
Julie:"""

def detect_ai_emotion(text_to_analyze: str, recent_history_for_emotion_prompt: str) -> str:
    if not text_to_analyze.strip() or llm_emotion_agent is None: return "neutre"
    prompt = EMOTION_DETECT_PROMPT_TEMPLATE.format(
        recent_history_for_emotion=recent_history_for_emotion_prompt or "(Pas d'historique récent)",
        text_to_analyze=text_to_analyze
    )
    try:
        emotion_raw = llm_emotion_agent.invoke(prompt).strip().lower()
        cleaned_emotion = ''.join(filter(str.isalnum, emotion_raw))
        
        if cleaned_emotion in EMOTIONS_LIST_FOR_AGENT: return cleaned_emotion
        for candidate in EMOTIONS_LIST_FOR_AGENT:
            if candidate in cleaned_emotion: return candidate
        return "neutre"
    except Exception as e:
        print(f"Erreur détection émotion Julie: {e}")
        return "neutre"

def process_user_input_langchain(user_query_raw: str, user_name: str, user_detected_emotion: str):
    global _CURRENT_USER_QUERY_FOR_STM_TOOL, conversation_history_deque, full_conversation_log_for_emotion_agent
    global NEW_FACE_REQUEST_LANGCHAIN

    NEW_FACE_REQUEST_LANGCHAIN = False # Réinitialiser le flag à chaque appel
    _CURRENT_USER_QUERY_FOR_STM_TOOL = user_query_raw

    history_for_tool_decider_str = "\n".join(list(conversation_history_deque)) or "(Début de la conversation)"
    history_for_responder_list = list(conversation_history_deque)
    history_for_responder_list.append(f"Utilisateur: {user_query_raw}")
    history_for_responder_str = "\n".join(history_for_responder_list)

    tools_description_for_prompt = "\n".join([f"- {tool.name}: {tool.description}" for tool in tools_list])
    
    tool_decide_prompt_input = TOOL_DECIDE_PROMPT_TEMPLATE.format(
        tools_description=tools_description_for_prompt,
        conversation_history_for_tool_decider=history_for_tool_decider_str,
        input=user_query_raw
    )
    raw_tool_decisions_str = llm_tool_decider.invoke(tool_decide_prompt_input).strip().replace("`", "")
    
    common_prefixes_to_strip = [
        "décision d'outil:", "tool decision:", "outil:", "tool:",
        "tool_decision:", "tool_choice:", "choix de l'outil:", "decision:",
        "décision d'outil(s) (ou none):"
    ]
    for prefix in common_prefixes_to_strip:
        if raw_tool_decisions_str.lower().startswith(prefix):
            raw_tool_decisions_str = raw_tool_decisions_str[len(prefix):].strip()
            break

    accumulated_tool_results = []
    julie_final_response = ""
    conversation_ended_by_tool_flag = False

    if raw_tool_decisions_str.upper() != "NONE" and raw_tool_decisions_str != "":
        potential_tool_calls = [call.strip() for call in raw_tool_decisions_str.split(',') if call.strip()]
        tool_call_pattern = re.compile(r"([a-zA-Z0-9_]+)\s*\(\s*(?:([a-zA-Z0-9_]+)\s*=\s*)?(?:'(.*?)'|\"(.*?)\"|([^'\")\s][^,()]*?))?\s*\)")

        for p_call_str in potential_tool_calls:
            tool_match = tool_call_pattern.fullmatch(p_call_str)
            if tool_match:
                tool_name = tool_match.group(1)
                tool_arg_value = next((val for val in tool_match.groups()[2:] if val is not None), "").strip()

                if tool_name in tools_map:
                    try:
                        tool_to_run = tools_map[tool_name]
                        if tool_name in ["query_long_term_memory"]:
                            tool_output = tool_to_run.func(tool_arg_value)
                        else:
                            tool_output = tool_to_run.func()
                        
                        if tool_output == "FIN_CONVERSATION_DEMANDEE_PAR_OUTIL":
                            conversation_ended_by_tool_flag = True
                            julie_final_response = "D'accord. À la prochaine !"
                            accumulated_tool_results.append(f"Note: L'outil '{tool_name}' a mis fin à la conversation.")
                            break
                        else:
                            accumulated_tool_results.append(f"Résultat de l'outil '{tool_name}': \"{tool_output}\"")
                            if tool_name == "enregistrer_visage_utilisateur": # NEW_FACE_REQUEST_LANGCHAIN est mis à True dans la fonction
                                pass # Le message de l'outil est suffisant pour le contexte du LLM
                    except Exception as e_tool_exec:
                        accumulated_tool_results.append(f"(Erreur interne avec l'outil {tool_name}.)")
                else:
                    accumulated_tool_results.append(f"(Outil '{tool_name}' non reconnu.)")

    tool_results_for_final_prompt = "\n".join(accumulated_tool_results)
    if tool_results_for_final_prompt:
        tool_results_for_final_prompt = "Contexte fourni par les outils:\n" + tool_results_for_final_prompt + "\n"
    else:
        tool_results_for_final_prompt = "Aucun outil n'a été utilisé."

    if not conversation_ended_by_tool_flag:
        final_response_prompt_input = FINAL_RESPONSE_PROMPT_TEMPLATE.format(
            user_name=user_name,
            user_detected_emotion=user_detected_emotion,
            tool_results_context=tool_results_for_final_prompt,
            conversation_history_for_responder=history_for_responder_str
        )
        raw_julie_response = llm_final_responder.invoke(final_response_prompt_input).strip()

        stop_patterns_responder = [
            "Utilisateur:", "Utilisateur :", "\nUtilisateur:",
            "Julie:", "Julie :", "\nJulie:",
            "Assistant:", "Assistant :", "\nAssistant:",
            "\n\n\n"
        ]
        if raw_julie_response.lower().startswith("julie:"):
            raw_julie_response = raw_julie_response[len("Julie:"):].strip()

        min_index = len(raw_julie_response)
        for pattern in stop_patterns_responder:
            try:
                idx = raw_julie_response.index(pattern)
                if idx < min_index: min_index = idx
            except ValueError: continue
        
        if min_index < len(raw_julie_response):
            raw_julie_response = raw_julie_response[:min_index].strip()
        
        julie_final_response = raw_julie_response or "Je ne suis pas sûre de comment répondre à cela."
    
    emotion_agent_history_list = list(full_conversation_log_for_emotion_agent)
    emotion_agent_history_list.append(f"Utilisateur: {user_query_raw}")
    recent_history_for_emotion_prompt = "\n".join(emotion_agent_history_list) or "(Début conversation)"
    
    julies_detected_emotion = detect_ai_emotion(julie_final_response, recent_history_for_emotion_prompt)
    
    conversation_history_deque.append(f"Utilisateur: {user_query_raw}")
    conversation_history_deque.append(f"Julie: {julie_final_response}")

    full_conversation_log_for_emotion_agent.append(f"Utilisateur: {user_query_raw}")
    full_conversation_log_for_emotion_agent.append(f"Julie ({julies_detected_emotion}): {julie_final_response}")

    add_to_stm_and_slide([f"Utilisateur: {user_query_raw}", f"Julie: {julie_final_response}"])
    save_to_long_term_memory(user_query_raw, julie_final_response, julies_detected_emotion, user_name, user_detected_emotion)

    return julie_final_response, julies_detected_emotion, conversation_ended_by_tool_flag, NEW_FACE_REQUEST_LANGCHAIN

def clear_all_memories():
    global conversation_history_deque, stm_vectorstore, stm_vector_id_deque, embeddings_model
    global full_conversation_log_for_emotion_agent, stm_retriever

    print("--- Effacement de TOUTES les mémoires ---")
    reset_short_term_context_deques()

    faiss_index_file = os.path.join(VECTOR_STORE_INDEX_DIR, "index.faiss")
    faiss_pkl_file = os.path.join(VECTOR_STORE_INDEX_DIR, "index.pkl")
    if os.path.exists(faiss_index_file): os.remove(faiss_index_file)
    if os.path.exists(faiss_pkl_file): os.remove(faiss_pkl_file)
    if os.path.exists(VECTOR_IDS_PATH): os.remove(VECTOR_IDS_PATH)
    
    print("Réinitialisation de la STM (FAISS)...")
    initial_doc_stm = Document(page_content="Mémoire à court terme sémantique réinitialisée.")
    stm_vectorstore = FAISS.from_documents([initial_doc_stm], embedding=embeddings_model)
    marker_id_list = stm_vectorstore.add_texts(["Marqueur STM post-effacement"])
    stm_vector_id_deque = deque()
    if marker_id_list: stm_vector_id_deque.append(marker_id_list[0])

    stm_vectorstore.save_local(VECTOR_STORE_INDEX_DIR)
    with open(VECTOR_IDS_PATH, "wb") as f: pickle.dump(stm_vector_id_deque, f)
    stm_retriever = stm_vectorstore.as_retriever(search_kwargs=dict(k=3))
    print("STM (FAISS sémantique) effacée et réinitialisée.")

    if os.path.exists(LTM_DB_PATH):
        try:
            os.remove(LTM_DB_PATH)
            print(f"Fichier LTM '{LTM_DB_PATH}' supprimé.")
        except OSError as e:
            print(f"Erreur suppression LTM '{LTM_DB_PATH}': {e}.")
    init_ltm_db()
    print("LTM (SQLite persistante) effacée et réinitialisée.")
    print("--- Toutes les mémoires ont été effacées. ---")

if __name__ == "__main__":
    try:
        init_llms_and_memory()
        print("\n--- Test de Conversation avec Julie (Langchain) ---")
        print("Commandes: 'quitter', 'effacer memoire', 'reset deques'.")
        print("-" * 30)
        test_user_name = "Testeur"; test_user_emotion = "curieux"
        
        while True:
            user_input = input(f"{test_user_name} (vous): ").strip()
            if not user_input: continue

            if user_input.lower() == 'quitter': print("Julie: Au revoir !"); break
            elif user_input.lower() == 'effacer memoire':
                clear_all_memories()
                print("Julie: Toutes mes mémoires ont été réinitialisées.")
                continue
            elif user_input.lower() == 'reset deques':
                reset_short_term_context_deques()
                print("Julie: Mon contexte de conversation direct a été réinitialisé.")
                continue

            response, ai_emotion, ended, face_req_flag = process_user_input_langchain(user_input, test_user_name, test_user_emotion)
            print(f"Julie (émotion interne: {ai_emotion}): {response}")
            
            if face_req_flag:
                print("[INFO TEST: Le LLM a demandé un enregistrement de visage (NEW_FACE_REQUEST_LANGCHAIN=True)]")
            
            if ended:
                print("--- FIN DE LA CONVERSATION ---")
                break
            print("-" * 30)
            
    except FileNotFoundError as e: print(f"Erreur démarrage: {e}")
    except RuntimeError as e: print(f"Erreur critique LlamaCpp: {e}")
    except Exception as e: print(f"Erreur inattendue: {e}")
    finally: print("Fin du test.")