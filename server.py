import sys
import select
import json
import socket
import time
import random
import uuid
import hashlib
import re
import random
import functools
import base64
import threading
import os

# --- Parse CLI Arguments ---
if len(sys.argv) != 5:
    print("Usage: python p2p_filesharing.py <peer_id> <host> <p2p_port> <http_port>")
    sys.exit(1)

peer_id = sys.argv[1]
host = sys.argv[2]
p2p_port = int(sys.argv[3])
http_port = int(sys.argv[4])


# Make sure the directory exists
base_path = f"./storage_{peer_id}"
os.makedirs(base_path, exist_ok=True)


# Constants
GOSSIP_FANOUT = 3
GOSSIP_INTERVAL = 30
DROP_PEER_TIMEOUT = 60

# Internal State
seen_gossip_ids = set()

tracked_peers = {}  # peerId -> {"host": str, "port": int, "last_seen": float}
file_metadata = {}  # file_id -> metadata dict

print(f"[{peer_id}] Started peer at {host}:{p2p_port}, WebServer: {http_port}")
print(f"Storage directory created: {base_path}")


# load metadata into memory
def load_metadata():
    metadata_path = os.path.join(base_path, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        print(f"[{peer_id}] Loaded metadata from file.")
        return metadata
    else:
        print(f"[{peer_id}] metadata.json not found, scanning storage...")
        return scan_storage_folder()


# if metadata.json does not exist, scan the storage folder and create it
def scan_storage_folder():
    metadata = {}
    for fname in os.listdir(base_path):
        fpath = os.path.join(base_path, fname)

        if fname == "metadata.json" or not os.path.isfile(fpath):
            continue

        with open(fpath, "rb") as f:
            content = f.read()
        stat = os.stat(fpath)
        timestamp = int(stat.st_mtime)
        size = len(content)

        h = hashlib.sha256()
        h.update(content)
        h.update(str(timestamp).encode())
        file_id = h.hexdigest()

        metadata[file_id] = {
            "file_name": fname,
            "file_size": size,
            "file_id": file_id,
            "file_owner": peer_id,
            "file_timestamp": timestamp,
            "peers_with_file": [peer_id],  # store yourself
        }
    print(f"[{peer_id}] Generated metadata for {len(metadata)} file(s).")
    return metadata


# save metadata to file
def save_metadata():
    metadata_path = os.path.join(base_path, "metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(file_metadata, f, indent=2)
    print(f"[{peer_id}] Saved metadata to file.")

# send gossip to a random peer
def send_gossip(to_host, to_port):
    gossip_id = str(uuid.uuid4())
    msg = {
        "type": "GOSSIP",
        "host": host,
        "port": p2p_port,
        "id": gossip_id,
        "peerId": peer_id,
    }

    try:
        with socket.create_connection((to_host, to_port), timeout=5) as sock:
            sock.sendall(json.dumps(msg).encode())
        print(f"[{peer_id}] Sent GOSSIP to {to_host}:{to_port}")
        seen_gossip_ids.add(gossip_id)  # Mark it as seen so we don't rebroadcast
    except Exception as e:
        print(f"[{peer_id}] Failed to send GOSSIP to {to_host}:{to_port}: {e}")


# here all the messages are handled
def handle_message(conn, addr, msg):
    """
    Process the incoming message based on its type.
    handle different message types (e.g., GOSSIP, GOSSIP_REPLY, etc.)
    """
    # For example, check the type of the message
    if "type" in msg:
        if msg["type"] == "GOSSIP":
            # Process GOSSIP message
            print(f"[{peer_id}] Handling GOSSIP message from {msg.get('peerId')}")
            #print(f"[{peer_id}] Full GOSSIP received:\n{json.dumps(msg, indent=2)}")
            # Here you'll call your handle_gossip() function or similar
        elif msg["type"] == "GOSSIP_REPLY":
            print(f"[{peer_id}] Handling GOSSIP_REPLY from {msg.get('peerId')}")
            # Process GOSSIP_REPLY
        else:
            print(f"[{peer_id}] Received unknown message type: {msg['type']}")
    else:
        print(f"[{peer_id}] Received message without type: {msg}")


def run_tcp_server():
    # Create and set up the server socket.
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, p2p_port))
    server_sock.listen(5)
    server_sock.setblocking(False)
    print(f"[{peer_id}] TCP server listening on {host}:{p2p_port}")

    # List of sockets to monitor for incoming data.
    inputs = [server_sock]

    while True:
        readable, _, _ = select.select(inputs, [], [], 1)

        for s in readable:
            if s is server_sock:
                # Accept a new connection.
                conn, addr = server_sock.accept()
                conn.setblocking(False)
                inputs.append(conn)
                print(f"[{peer_id}] Accepted connection from {addr}")
            else:
                try:
                    data = s.recv(4096)
                    if data:
                        try:
                            msg = json.loads(data.decode())

                            # this method will handle the message
                            handle_message(s, s.getpeername(), msg)

                        except Exception as e:
                            print(f"[{peer_id}] Error parsing message: {e}")
                    else:
                        print(f"[{peer_id}] Connection closed.")
                        inputs.remove(s)
                        s.close()
                except Exception as e:
                    print(f"[{peer_id}] Error reading from socket: {e}")
                    inputs.remove(s)
                    s.close()

if __name__ == "__main__":
    file_metadata = load_metadata()
    save_metadata()

    # Optional: show metadata
    print(f"[{peer_id}] Current metadata entries:")
    for fid, meta in file_metadata.items():
        print(
            f" - {meta['file_name']} (ID: {fid}, Size: {meta['file_size']} Bytes, Owner: {meta['file_owner']})"
        )

    send_gossip("localhost", 8000)  # You can change this to other well-known hosts

    run_tcp_server()
