import requests
import json
import urllib.parse
import os
import uuid
import re
from typing import Optional, Tuple, Dict, Any

# --- Configuration ---
CLIENT_ID_FILE = "client_id.txt"
OUTPUT_DIR = "pluto_tv_master_streams" 
LOGO_DIR_NAME = "pluto_tv_logos_png" # <--- NOUVEAU NOM DE DOSSIER SPECIFIE
API_URL = "https://api.pluto.tv/v2/channels"

# Paramètres du flux (Query Params)
FLUX_PARAMS = {
    "advertisingId": "", "appName": "", "appVersion": "unknown", "architecture": "",
    "buildVersion": "", "clientTime": "", "deviceDNT": 0, "deviceId": "",
    "deviceLat": 48.8600, "deviceLon": 2.2600, 
    "deviceMake": "Chrome", "deviceModel": "web", "deviceType": "web", "deviceVersion": "unknown",
    "includeExtendedEvents": False, "marketingRegion": "FR", 
    "sid": "", "userId": ""
}

# Types de logos à scraper
LOGO_TYPES = ["colorLogoPNG", "solidLogoPNG"]
# --- Fin Configuration ---

# --- Fonctions Utilitaires (simplifiées et mises à jour) ---

def slugify_name(name: str) -> str:
    """Nettoie le nom de la chaîne pour l'utiliser dans un nom de fichier."""
    name = name.strip()
    name = re.sub(r'[ -]', '_', name)
    name = re.sub(r'[^\w_]', '', name)
    name = re.sub(r'_{2,}', '_', name)
    return name[:100]

# (Les fonctions get_valid_client_id, generate_new_client_id, get_m3u8_url_for_channel restent inchangées)

def generate_new_client_id() -> Optional[str]:
    """Génère un nouvel UUID v4 et l'enregistre dans le fichier."""
    new_uuid = str(uuid.uuid4())
    try:
        with open(CLIENT_ID_FILE, 'w') as f:
            f.write(new_uuid)
        return new_uuid
    except IOError as e:
        print(f"❌ Erreur lors de l'écriture du fichier UUID : {e}")
        return None

def get_valid_client_id() -> Optional[str]:
    """Charge l'UUID existant, le regénère si l'utilisateur le souhaite, ou en crée un nouveau."""
    client_id = None
    
    if os.path.exists(CLIENT_ID_FILE):
        try:
            with open(CLIENT_ID_FILE, 'r') as f:
                client_id = f.read().strip()
            print(f"--- Fichier UUID trouvé ---")
            print(f"UUID actuel : {client_id}")
            
            while True:
                choice = input("Voulez-vous regénérer un nouvel UUID ? (oui/non) : ").strip().lower()
                if choice in ('o', 'oui'):
                    print(f"✅ Nouvel UUID généré.")
                    return generate_new_client_id()
                elif choice in ('n', 'non'):
                    return client_id
                else:
                    print("Veuillez répondre par 'oui' ou 'non'.")
        except IOError:
            print(f"⚠️ Erreur de lecture du fichier {CLIENT_ID_FILE}. Génération d'un nouveau.")

    print(f"--- UUID non trouvé ou erreur ---")
    print("Génération automatique d'un nouvel UUID.")
    return generate_new_client_id()

def get_m3u8_url_for_channel(channel: dict) -> Optional[str]:
    """Récupère l'URL de base du manifeste HLS."""
    stitched_info = channel.get("stitched")
    if not stitched_info or not stitched_info.get("urls"):
        return None
    
    hls_url_template = stitched_info["urls"][0].get("url")
    return hls_url_template.split('?')[0] 

def get_initial_config() -> Tuple[Optional[int], bool]:
    """Demande la configuration initiale (Mode SID et téléchargement des logos)."""
    
    # 1. Choix du mode SID
    print("\n--- 🔑 MODE DE GÉNÉRATION UUID/SID ---")
    print("Veuillez choisir comment gérer l'identifiant de session (SID):")
    print("  [1] : UUID/SID UNIQUE pour TOUS les streams (Mode standard)")
    print("  [2] : UUID/SID NOUVEAU pour CHAQUE stream (Mode recommandé pour la STABILITÉ)")
    
    while True:
        try:
            mode_choice = input("Entrez le numéro du mode désiré (1 ou 2) : ").strip()
            if mode_choice in ('1', '2'):
                mode = int(mode_choice)
                break
            else:
                print("Choix invalide. Veuillez entrer '1' ou '2'.")
        except:
            print("Erreur de saisie. Veuillez entrer un nombre.")
            
    # 2. Choix du téléchargement des logos
    print("\n--- 🖼️ TÉLÉCHARGEMENT DES LOGOS ---")
    while True:
        logo_choice = input(f"Voulez-vous télécharger les logos ({', '.join(LOGO_TYPES)}) dans le dossier '{LOGO_DIR_NAME}' ? (oui/non) : ").strip().lower()
        if logo_choice in ('o', 'oui'):
            download_logos = True
            print("✅ Le téléchargement des logos est ACTIVÉ.")
            break
        elif logo_choice in ('n', 'non'):
            download_logos = False
            print("❌ Le téléchargement des logos est DÉSACTIVÉ.")
            break
        else:
            print("Veuillez répondre par 'oui' ou 'non'.")
            
    return mode, download_logos

def download_logo(logo_url: str, channel_name_slug: str, channel_id: str, logo_type: str) -> Optional[str]:
    """
    Télécharge un logo avec un nom de fichier détaillé :
    {nom_slugifié}_{id_chaîne}_{type_de_logo}.png
    """
    if not logo_url:
        return None
        
    logo_full_path = LOGO_DIR_NAME # Chemin absolu
    
    # Nom du fichier : Doraemon_68b17414c23bb80b3c1d5bb5_colorLogoPNG.png
    file_name = f"{channel_name_slug}_{channel_id}_{logo_type}.png"
    final_path = os.path.join(logo_full_path, file_name)
    
    # Chemin relatif pour le M3U (si nécessaire, mais on n'inclut que le type colorLogoPNG dans le M3U)
    relative_path = os.path.join(LOGO_DIR_NAME, file_name)
    
    if os.path.exists(final_path):
        return relative_path # Évite de re-télécharger si le fichier existe
    
    try:
        response = requests.get(logo_url, stream=True, timeout=5)
        response.raise_for_status()
        
        with open(final_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
                
        return relative_path
        
    except requests.exceptions.RequestException as e:
        # print(f"  ❌ Erreur de téléchargement du logo ({logo_type}) : {e}")
        return None
    except IOError as e:
        # print(f"  ❌ Erreur de sauvegarde du logo : {e}")
        return None

# --- Fonction Main ---
def main():
    # 0. Configuration initiale
    mode, download_logos = get_initial_config()
    
    # --- Étape A: Gestion de l'UUID du client ---
    if mode == 1:
        global_client_id = get_valid_client_id()
        if not global_client_id:
            return
        
        FLUX_PARAMS['sid'] = global_client_id
        FLUX_PARAMS['deviceId'] = global_client_id
        print(f"\n1. Mode UNIQUE sélectionné. UUID global: {global_client_id}")
    else: # mode == 2 (Per Stream)
        print(f"\n1. Mode PAR STREAM sélectionné. Un nouvel UUID sera généré pour chaque chaîne.")

    # --- Étape B: Préparation des dossiers ---
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Dossier des streams créé : {OUTPUT_DIR}")
        
    if download_logos and not os.path.exists(LOGO_DIR_NAME):
        os.makedirs(LOGO_DIR_NAME)
        print(f"Dossier des logos créé : {LOGO_DIR_NAME}")

    print("\n2. Récupération de la liste complète des chaînes...")
    try:
        channels_response = requests.get(API_URL)
        channels_response.raise_for_status()
        channels_data = channels_response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ ERREUR lors de la récupération des données des chaînes : {e}")
        return

    # --- Étape C: Construction et Sauvegarde ---
    print(f"\n3. Génération des fichiers M3U8 et des logos ({len(channels_data)} chaînes) :")
    
    successful_saves = 0
    
    for i, channel in enumerate(channels_data):
        raw_name = channel.get("name", "inconnu")
        channel_id = channel.get("_id")
        clean_file_name = slugify_name(raw_name)
        
        m3u8_base_url = get_m3u8_url_for_channel(channel)
        
        if not m3u8_base_url:
            continue
            
        # LOGIQUE SID PAR FLUX (Mode 2)
        if mode == 2:
            current_sid = str(uuid.uuid4())
            FLUX_PARAMS['sid'] = current_sid
            FLUX_PARAMS['deviceId'] = current_sid
        
        final_stream_url = m3u8_base_url + "?" + urllib.parse.urlencode(FLUX_PARAMS)
        
        # --- Gestion des LOGOS ---
        logo_tag_m3u = ""
        main_logo_url = None
        
        if download_logos:
            # Télécharge tous les types de logos spécifiés
            for logo_type in LOGO_TYPES:
                logo_url = channel.get(logo_type, {}).get("path")
                if logo_url:
                    relative_path = download_logo(logo_url, clean_file_name, channel_id, logo_type)
                    
                    # On utilise UNIQUEMENT le colorLogoPNG pour le tag tvg-logo dans le M3U
                    if logo_type == "colorLogoPNG" and relative_path:
                        logo_tag_m3u = f' tvg-logo="{relative_path}"'
                        main_logo_url = relative_path # Stocke le chemin relatif pour l'affichage
                        
            if not main_logo_url:
                 # Tentative d'utiliser une URL si aucune couleur n'est trouvée (très rare)
                 if channel.get("logo", {}).get("path"):
                     logo_tag_m3u = f' tvg-logo="{channel["logo"]["path"]}"'
        
        # --- Sauvegarde du fichier M3U8 individuel ---
        output_filename = os.path.join(OUTPUT_DIR, f"{clean_file_name}.m3u8") 
        
        m3u8_content = [
            "#EXTM3U",
            f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{raw_name}"{logo_tag_m3u},{raw_name}',
            final_stream_url
        ]
        
        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write('\n'.join(m3u8_content))
            
            # Affichage console pour confirmer les téléchargements de logos
            logo_msg = " + Logos OK" if download_logos and logo_tag_m3u else ""
            print(f"  ✅ [Ch. {i+1}/{len(channels_data)}] {raw_name} -> Fichier créé.{logo_msg}")
            successful_saves += 1
        except IOError as e:
            print(f"  ❌ [Ch. {i+1}/{len(channels_data)}] Erreur de sauvegarde pour {raw_name}: {e}")

    print(f"\n--- Tâche Terminée ---")
    print(f"Total de {successful_saves} fichiers M3U8 générés dans le dossier **{OUTPUT_DIR}**.")
    if download_logos:
        print(f"Les logos ont été enregistrés dans le dossier **{LOGO_DIR_NAME}**.")

if __name__ == "__main__":
    main()