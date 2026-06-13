
import socket

def start_node(host, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host, port))
    server.listen(5)
    print(f"Aeternum node running on {host}:{port}")
    while True:
        conn, addr = server.accept()
        print(f"Connected by {addr}")
        data = conn.recv(1024)
        print(f"Received: {data.decode()}")
        conn.send(b"Aeternum node received your message")
        conn.close()

start_node("0.0.0.0", 9000)
