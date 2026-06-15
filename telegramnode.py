import time
import requests
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FIREBASE_URL = os.environ.get("FIREBASE_URL")
GROQ_MODEL = "llama-3.1-8b-instant"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

node_start_time = datetime.now(timezone.utc)
jobs_processed = 0
node_active = False
node_chat_id = None


def tg(method, payload=None):
    try:
        res = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=10)
        return res.json()
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {}


def send(chat_id, text):
    tg("sendMessage", {"chat_id": chat_id, "text": text})


def firebase_get(path):
    try:
        res = requests.get(f"{FIREBASE_URL}/{path}.json", timeout=10)
        return res.json()
    except Exception as e:
        print(f"[FIREBASE GET ERROR] {path}: {e}")
        return None


def firebase_set(path, data):
    try:
        requests.put(
            f"{FIREBASE_URL}/{path}.json",
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as e:
        print(f"[FIREBASE SET ERROR] {path}: {e}")


def firebase_delete(path):
    try:
        requests.delete(f"{FIREBASE_URL}/{path}.json", timeout=10)
    except Exception as e:
        print(f"[FIREBASE DELETE ERROR] {path}: {e}")


def call_groq(prompt):
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.7,
            },
            timeout=30,
        )
        data = res.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[GROQ ERROR] {e}")
        return None


def get_uptime():
    delta = datetime.now(timezone.utc) - node_start_time
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def process_firebase_jobs():
    global jobs_processed
    prompts = firebase_get("prompts")
    if not prompts or not isinstance(prompts, dict):
        return
    for job_id, job_data in prompts.items():
        if not isinstance(job_data, dict):
            continue
        if job_data.get("status") != "pending":
            continue
        prompt = job_data.get("prompt")
        if not prompt:
            continue

        print(f"[JOB] Processing {job_id}: {prompt[:60]}")

        firebase_set(f"prompts/{job_id}/status", "processing")

        response = call_groq(prompt)

        if response:
            firebase_set(f"prompts/{job_id}", {
                "prompt": prompt,
                "response": response,
                "status": "done",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "node": "telegram",
            })
            jobs_processed += 1
            print(f"[JOB] Done {job_id}. Total jobs: {jobs_processed}")
        else:
            firebase_set(f"prompts/{job_id}/status", "failed")


def handle_message(message):
    global node_active, node_chat_id

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if text == "/start":
        node_chat_id = chat_id
        node_active = True
        send(
            chat_id,
            "Aeternum Node Online\n\n"
            "Your node is now connected to the network. It will watch for incoming prompts and process them using Groq.\n\n"
            "Commands:\n"
            "/status - view node stats\n"
            "/stop - take your node offline\n"
            "/help - list commands",
        )
        print(f"[NODE] Started by chat_id {chat_id}")

    elif text == "/status":
        send(
            chat_id,
            f"Node Status: {'Active' if node_active else 'Inactive'}\n"
            f"Uptime: {get_uptime()}\n"
            f"Jobs processed: {jobs_processed}\n"
            f"Network: Arbitrum Sepolia\n"
            f"Model: {GROQ_MODEL}",
        )

    elif text == "/stop":
        node_active = False
        node_chat_id = None
        send(chat_id, "Node taken offline. Send /start to reconnect to the network.")
        print(f"[NODE] Stopped by chat_id {chat_id}")

    elif text == "/help":
        send(
            chat_id,
            "Aeternum Node Commands:\n\n"
            "/start - bring your node online\n"
            "/status - view uptime and jobs processed\n"
            "/stop - take your node offline\n"
            "/help - list commands",
        )

    else:
        send(chat_id, "Send /start to bring your node online.")


def poll():
    offset = None
    print("[AETERNUM] Node polling started")
    while True:
        try:
            params = {"timeout": 30, "limit": 10}
            if offset is not None:
                params["offset"] = offset
            res = tg("getUpdates", params)
            updates = res.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
        except Exception as e:
            print(f"[POLL ERROR] {e}")

        if node_active:
            process_firebase_jobs()

        time.sleep(3)


if __name__ == "__main__":
    poll()
