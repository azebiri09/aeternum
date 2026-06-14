cat > node.py << 'EOF'
import socket
import threading
import json
import time
import urllib.request
import os

# ============================================================
# AETERNUM NODE CONFIGURATION
# ============================================================

# Load private key from .env
def load_env():
    env = {}
    try:
        with open(".env") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env[k] = v
    except:
        pass
    return env

env = load_env()
PRIVATE_KEY = env.get("PRIVATE_KEY", "")

NODE_WALLET = "0xA98E8caf19c3F215FCCe98C3FDe023aE8Cfb27a6"
JOB_MANAGER = "0xE10AEBBc80fA857396A1A5Cf8b68E10f3db088C2"
NODE_REGISTRY = "0x6B27Ed485F9c19d44056D5f3f509613780519E10"
AET_TOKEN = "0x59162132743B38f9AF70F1D57aAa8Cede56D9477"

RPC_URL = "https://sepolia-rollup.arbitrum.io/rpc"
CHAIN_ID = 421614

MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
POLL_INTERVAL = 10

# ============================================================
# RPC HELPER
# ============================================================

def rpc_call(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }).encode()
    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())["result"]

# ============================================================
# BLOCKCHAIN READS
# ============================================================

def encode_call(selector, *args):
    data = selector
    for arg in args:
        if isinstance(arg, int):
            data += hex(arg)[2:].zfill(64)
        elif isinstance(arg, str) and arg.startswith("0x"):
            data += arg[2:].lower().zfill(64)
    return data

def get_total_jobs():
    try:
        result = rpc_call("eth_call", [
            {"to": JOB_MANAGER, "data": "0x8e7d9405"},
            "latest"
        ])
        return int(result, 16)
    except:
        return 0

def get_job(job_id):
    try:
        data = encode_call("0x1d3e8a61", job_id)
        result = rpc_call("eth_call", [
            {"to": JOB_MANAGER, "data": data},
            "latest"
        ])
        if not result or result == "0x":
            return None
        raw = result[2:]
        assigned_node = "0x" + raw[128:192][-40:]
        status = int(raw[256:320], 16)
        return {
            "id": job_id,
            "assigned_node": assigned_node.lower(),
            "status": status
        }
    except:
        return None

# ============================================================
# INFERENCE
# ============================================================

def run_inference(prompt):
    print(f"\n[INFERENCE] Running: {prompt[:60]}...")
    try:
        from transformers import pipeline
        pipe = pipeline("text-generation", model=MODEL, max_new_tokens=200)
        result = pipe(prompt)
        response = result[0]["generated_text"]
        print(f"[INFERENCE] Complete.")
        return response
    except Exception as e:
        print(f"[INFERENCE] Error: {e}")
        return f"Inference failed: {str(e)}"

# ============================================================
# JOB WATCHER
# ============================================================

def watch_jobs():
    print(f"\n[WATCHER] Watching for jobs assigned to {NODE_WALLET}")
    processed = set()

    while True:
        try:
            total = get_total_jobs()
            print(f"[WATCHER] Total jobs: {total}")

            for job_id in range(1, total + 1):
                if job_id in processed:
                    continue
                job = get_job(job_id)
                if not job:
                    continue
                if (job["assigned_node"] == NODE_WALLET.lower() and
                        job["status"] == 1):
                    print(f"\n[JOB] Job #{job_id} assigned to this node!")
                    processed.add(job_id)
                    run_inference(f"Process inference job #{job_id}")
                    print(f"[JOB] Call completeJob({job_id}) in Remix to release payment.")

        except Exception as e:
            print(f"[WATCHER] Error: {e}")

        time.sleep(POLL_INTERVAL)

# ============================================================
# P2P
# ============================================================

peers = []

def handle_peer(conn):
    data = conn.recv(1024).decode()
    if data == "GET_PEERS":
        conn.send(json.dumps(peers).encode())
    else:
        if data not in peers:
            peers.append(data)
            print(f"[P2P] New peer: {data}")
        conn.send(b"OK")
    conn.close()

def start_p2p(port=9000):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen(5)
    print(f"[P2P] Node running on port {port}")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_peer, args=(conn,)).start()

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("AETERNUM NODE STARTING")
    print("=" * 50)
    print(f"Wallet:      {NODE_WALLET}")
    print(f"Job Manager: {JOB_MANAGER}")
    print(f"Model:       {MODEL}")
    print(f"Chain:       Arbitrum Sepolia ({CHAIN_ID})")
    print(f"Key loaded:  {'YES' if PRIVATE_KEY else 'NO'}")
    print("=" * 50)

    p2p_thread = threading.Thread(target=start_p2p, daemon=True)
    p2p_thread.start()

    watch_jobs()
EOF
