import time
import requests
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FIREBASE_URL = os.environ.get("FIREBASE_URL")
GROQ_MODEL = "llama-3.1-8b-instant"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

bot_start_time = datetime.now(timezone.utc)
jobs_processed = 0
jobs_lock = threading.Lock()
pending_names = {}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()


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
    delta = datetime.now(timezone.utc) - bot_start_time
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def get_active_nodes():
    nodes = firebase_get("nodes")
    if not nodes or not isinstance(nodes, dict):
        return {}
    now = datetime.now(timezone.utc).timestamp()
    active = {}
    for chat_id, node in nodes.items():
        last_seen = node.get("last_seen", 0)
        if now - last_seen < 180:
            active[chat_id] = node
    return active


def register_node(chat_id, name):
    node_data = {
        "name": name,
        "chat_id": chat_id,
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).timestamp(),
        "jobs": firebase_get(f"nodes/{chat_id}/jobs") or 0,
    }
    firebase_set(f"nodes/{chat_id}", node_data)
    print(f"[NODE] Registered: {name} ({chat_id})")


def remove_node(chat_id):
    firebase_delete(f"nodes/{chat_id}")
    print(f"[NODE] Removed: {chat_id}")


def heartbeat():
    while True:
        try:
            nodes = firebase_get("nodes")
            if nodes and isinstance(nodes, dict):
                now = datetime.now(timezone.utc).timestamp()
                for chat_id, node in nodes.items():
                    last_seen = node.get("last_seen", 0)
                    if now - last_seen < 180:
                        firebase_set(f"nodes/{chat_id}/last_seen", now)
        except Exception as e:
            print(f"[HEARTBEAT ERROR] {e}")
        time.sleep(60)


def process_firebase_jobs():
    global jobs_processed
    active = get_active_nodes()
    if not active:
        return
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

        firebase_set(f"prompts/{job_id}/status", "processing")

        verify = firebase_get(f"prompts/{job_id}/status")
        if verify != "processing":
            continue

        print(f"[JOB] Processing {job_id}: {prompt[:60]}")

        response = call_groq(prompt)

        if response:
            firebase_set(f"prompts/{job_id}", {
                "prompt": prompt,
                "response": response,
                "status": "done",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "node": "telegram",
            })
            with jobs_lock:
                jobs_processed += 1
            print(f"[JOB] Done {job_id}. Total jobs: {jobs_processed}")
        else:
            firebase_set(f"prompts/{job_id}/status", "failed")


def handle_message(message):
    chat_id = str(message["chat"]["id"])
    text = message.get("text", "").strip()

    if chat_id in pending_names:
        if len(text) < 2 or len(text) > 32:
            send(message["chat"]["id"], "Node name must be between 2 and 32 characters. Try again.")
            return
        name = text
        del pending_names[chat_id]
        register_node(chat_id, name)
        send(
            message["chat"]["id"],
            f"{name} is now online.\n\n"
            "Your node is connected to the Aeternum network. It will process incoming prompts using Groq and earn AET rewards.\n\n"
            "Commands:\n"
            "/status - view your node stats\n"
            "/nodes - see all active nodes\n"
            "/stop - take your node offline\n"
            "/help - list commands",
        )
        return

    if text == "/start":
        existing = firebase_get(f"nodes/{chat_id}")
        if existing and isinstance(existing, dict):
            now = datetime.now(timezone.utc).timestamp()
            last_seen = existing.get("last_seen", 0)
            if now - last_seen < 180:
                send(
                    message["chat"]["id"],
                    f"{existing.get('name', 'Your node')} is already online.\n\n"
                    "Send /status to check your stats or /stop to go offline.",
                )
                return
        pending_names[chat_id] = True
        send(message["chat"]["id"], "Welcome to Aeternum.\n\nWhat do you want to call your node?")

    elif text == "/status":
        node = firebase_get(f"nodes/{chat_id}")
        active = get_active_nodes()
        if node and isinstance(node, dict):
            now = datetime.now(timezone.utc).timestamp()
            last_seen = node.get("last_seen", 0)
            is_active = now - last_seen < 180
            send(
                message["chat"]["id"],
                f"Node: {node.get('name', 'Unknown')}\n"
                f"Status: {'Active' if is_active else 'Inactive'}\n"
                f"Jobs processed: {node.get('jobs', 0)}\n"
                f"Active nodes on network: {len(active)}\n"
                f"Network uptime: {get_uptime()}\n"
                f"Model: {GROQ_MODEL}",
            )
        else:
            send(message["chat"]["id"], "Your node is offline. Send /start to connect to the network.")

    elif text == "/nodes":
        active = get_active_nodes()
        if not active:
            send(message["chat"]["id"], "No nodes are currently active on the network.")
            return
        lines = [f"Active nodes on Aeternum ({len(active)} online)\n"]
        for node in active.values():
            name = node.get("name", "Unknown")
            jobs = node.get("jobs", 0)
            lines.append(f"{name} — {jobs} jobs")
        send(message["chat"]["id"], "\n".join(lines))

    elif text == "/stop":
        node = firebase_get(f"nodes/{chat_id}")
        name = node.get("name", "Your node") if node and isinstance(node, dict) else "Your node"
        remove_node(chat_id)
        send(message["chat"]["id"], f"{name} is now offline. Send /start to reconnect to the network.")

    elif text == "/help":
        send(
            message["chat"]["id"],
            "Aeternum Node Commands:\n\n"
            "/start - bring your node online\n"
            "/status - view your node stats\n"
            "/nodes - see all active nodes\n"
            "/stop - take your node offline\n"
            "/help - list commands",
        )

    else:
        if chat_id not in pending_names:
            send(message["chat"]["id"], "Send /start to bring your node online.")


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

        process_firebase_jobs()
        time.sleep(3)


if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    print("[AETERNUM] Health server running on port 8000")

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    print("[AETERNUM] Heartbeat running")

    poll()
