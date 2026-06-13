import socket
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(("127.0.0.1", 9000))
client.send(b"Hello Aeternum!")
response = client.recv(1024)
print("Response:", response.decode())
client.close()