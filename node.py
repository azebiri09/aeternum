
import socket
import threading
import json

peers = []

def handle_peer(conn):
    data = conn.recv(1024).decode()
    if data == "GET_PEERS":
        conn.send(json.dumps(peers).encode())
    else:
        if data not in peers:
            peers.append(data)
            print(f"New peer: {data}")
        conn.send(b"OK")
    conn.close()

def start_node(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen(5)
    print(f"Aeternum node running on port {port}")
    print(f"Peers: {peers}")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_peer, args=(conn,)).start()

start_node(9000)
