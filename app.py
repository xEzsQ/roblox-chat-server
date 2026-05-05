import asyncio
import websockets
import json
import os
from google import genai
import time

# --- CONFIGURATION IA ---
# Remplacez "VOTRE_CLE_API" par votre vraie clé
client = genai.Client(api_key="VOTRE_CLE_API")
MODEL_NAME = "gemini-2.0-flash"

# --- FICHIERS ET VARIABLES ---
GROSSIER_FILE = "grossier.json"
HISTORY_FILE = "stock_message.json"
BANS_FILE = "bans.json"
INFRACTIONS_FILE = "infractions.json"
clients = set()

BAD_WORDS = {"merde", "connard", "pute", "fdp", "enculé", "nique", "con", "beta"}

# --- CHARGEMENT DES DONNÉES ET CACHES ---
grossier_cache = {}
if os.path.exists(GROSSIER_FILE):
    with open(GROSSIER_FILE, "r", encoding="utf-8") as f:
        grossier_cache = json.load(f)

messages_history = []
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            messages_history = json.load(f)
    except json.JSONDecodeError:
        print("Erreur de lecture du JSON, on commence avec un historique vide.")
        messages_history = []

# Chargement des bans persistants
banned_until = {}
if os.path.exists(BANS_FILE):
    try:
        with open(BANS_FILE, "r", encoding="utf-8") as f:
            banned_until = json.load(f)
    except json.JSONDecodeError:
        banned_until = {}

# Chargement des infractions persistantes
infractions = {}
if os.path.exists(INFRACTIONS_FILE):
    try:
        with open(INFRACTIONS_FILE, "r", encoding="utf-8") as f:
            infractions = json.load(f)
    except json.JSONDecodeError:
        infractions = {}


# --- FONCTIONS DE SAUVEGARDE ---
def save_history():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(messages_history, f, ensure_ascii=False, indent=4)

def save_cache():
    with open(GROSSIER_FILE, "w", encoding="utf-8") as f:
        json.dump(grossier_cache, f, ensure_ascii=False, indent=4)

def save_bans():
    with open(BANS_FILE, "w", encoding="utf-8") as f:
        json.dump(banned_until, f, indent=4)

def save_infractions():
    with open(INFRACTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(infractions, f, indent=4)


# --- LOGIQUE IA ASYNCHRONE ---
async def ask_real_ia(text):
    prompt = f"""Tu es un système de modération.
    Réponds STRICTEMENT par : 1 (refus) ou 0 (ok).
    Message: "{text}" """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

        if not response or not response.text:
            return False

        return "1" in response.text.strip()

    except Exception as e:
        print(f"Erreur IA ({MODEL_NAME}):", e)
        return False

async def ia_filter(msg):
    msg_check = msg.lower().strip()

    for word in BAD_WORDS:
        if word in msg_check:
            return True

    if msg_check in grossier_cache:
        return grossier_cache[msg_check]

    is_grossier = await ask_real_ia(msg_check)

    grossier_cache[msg_check] = is_grossier
    save_cache()

    return is_grossier


# --- GESTION DU SERVEUR WEBSOCKET ---
async def handler(ws):
    user_ip = ws.remote_address[0]
    clients.add(ws)
    try:
        for past_msg in messages_history:
            await ws.send(past_msg)

        async for msg in ws:
            now = time.time()

            # --- VÉRIFICATION DU BANNISSEMENT ---
            if user_ip in banned_until:
                if now < banned_until[user_ip]:
                    remaining = int((banned_until[user_ip] - now) / 60) + 1
                    await ws.send(f"🚫 Toujours banni. Reviens dans {remaining} min.")
                    continue
                else:
                    # Le temps est écoulé, on réinitialise et on sauvegarde
                    del banned_until[user_ip]
                    if user_ip in infractions:
                        del infractions[user_ip]
                    save_bans()
                    save_infractions()

            # --- FILTRAGE IA ---
            is_blocked = await ia_filter(msg)

            if is_blocked:
                infractions[user_ip] = infractions.get(user_ip, 0) + 1
                save_infractions()

                if infractions[user_ip] >= 2:
                    # 15 minutes = 900 secondes
                    banned_until[user_ip] = now + 900
                    save_bans()
                    await ws.send("🚫 DEUXIÈME INFRACTION : Tu es banni pour 15 minutes.")
                    print(f"Utilisateur banni ({user_ip})")
                else:
                    await ws.send("⚠️ Message bloqué !")
                    await ws.send("⚠️ Premier avertissement ! Au prochain message grossier, tu seras banni 15 min.")
                    print("Message bloqué :", msg)
                    print("----")
            else:
                formatted_msg = f"Anonyme : {msg}"
                print("Message accepté:", msg)

                messages_history.append(formatted_msg)
                save_history()

                for c in list(clients):
                    try:
                        await c.send(formatted_msg)
                    except websockets.exceptions.ConnectionClosed:
                        pass

    finally:
        clients.remove(ws)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("Serveur prêt sur ws://localhost:8080")
        print("Historique chargé :", len(messages_history), "messages.")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
