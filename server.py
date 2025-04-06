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


def handle_gossip(msg):
    gossip_id = msg["id"]
    sender_id = msg["peerId"]
    sender_host = msg["host"]
    sender_port = msg["port"]

    # 1. Ignore duplicate gossip IDs
    if gossip_id in seen_gossip_ids:
        print(f"[{peer_id}] Already saw gossip {gossip_id}, ignoring.")
        return
    seen_gossip_ids.add(gossip_id)

    # 2. Add sender to tracked_peers
    if sender_id != peer_id and sender_id not in tracked_peers:
        tracked_peers[sender_id] = {
            "host": sender_host,
            "port": sender_port,
            "last_seen": time.time(),
        }
        print(
            f"[{peer_id}] Tracked new peer: {sender_id} at {sender_host}:{sender_port}"
        )
    else:
        tracked_peers[sender_id]["last_seen"] = time.time()

    # 3. Send GOSSIP_REPLY back to sender
    reply = {
        "type": "GOSSIP_REPLY",
        "host": host,
        "port": p2p_port,
        "peerId": peer_id,
        "files": get_gossip_reply_metadata(),
    }

    try:
        with socket.create_connection((sender_host, sender_port), timeout=5) as sock:
            sock.sendall(json.dumps(reply).encode())
        print(f"[{peer_id}] Sent GOSSIP_REPLY to {sender_id}")
    except Exception as e:
        print(f"[{peer_id}] Failed to send GOSSIP_REPLY to {sender_id}: {e}")

    # 4. Optional: forward to 3–5 random peers (excluding sender)
    peers_to_forward = random.sample(
        [p for p in tracked_peers if p != sender_id and p != peer_id],
        min(GOSSIP_FANOUT, len(tracked_peers) - 1),
    )
    for pid in peers_to_forward:
        pinfo = tracked_peers[pid]
        send_gossip(pinfo["host"], pinfo["port"])


def get_gossip_reply_metadata():
    reply_files = []
    for file in file_metadata.values():
        reply_files.append(
            {
                "file_name": file["file_name"],
                "file_size": file["file_size"],
                "file_id": file["file_id"],
                "file_owner": file["file_owner"],
                "file_timestamp": file["file_timestamp"],
            }
        )
    return reply_files


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
            # print(f"[{peer_id}] Full GOSSIP received:\n{json.dumps(msg, indent=2)}")
            handle_gossip(msg)
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


# cleaning up my tracked peers
def cleanup_tracked_peers():
    now = time.time()
    to_remove = []

    print(f"[{peer_id}]  Checking tracked peers for cleanup...")

    for peerId, peerInfo in tracked_peers.items():
        last_seen = peerInfo["last_seen"]
        age = now - last_seen

        if age > DROP_PEER_TIMEOUT:
            print(
                f"[{peer_id}]  Dropping inactive peer: {peerId} (last seen {int(age)}s ago)"
            )
            to_remove.append(peerId)
        else:
            print(f"[{peer_id}]  Peer {peerId} is alive (last seen {int(age)}s ago)")

    for peerId in to_remove:
        del tracked_peers[peerId]

    print(f"[{peer_id}]  Cleanup done. {len(tracked_peers)} peer(s) remaining.\n")


# this is the re-GOSSIP thread that will run every 30 seconds
def start_gossip_loop(well_known_host, well_known_port):
    def loop():
        while True:
            time.sleep(GOSSIP_INTERVAL)
            print(
                f"[{peer_id}] Sending periodic GOSSIP to {well_known_host}:{well_known_port}"
            )
            send_gossip(well_known_host, well_known_port)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


def start_cleanup_loop():
    def loop():
        while True:
            time.sleep(DROP_PEER_TIMEOUT)  # every 60 seconds
            cleanup_tracked_peers()

    t = threading.Thread(target=loop, daemon=True)
    t.start()


if __name__ == "__main__":
    file_metadata = load_metadata()
    save_metadata()

    # Show metadata
    print(f"[{peer_id}] Current metadata entries:")
    for fid, meta in file_metadata.items():
        print(
            f" - {meta['file_name']} (ID: {fid}, Size: {meta['file_size']} Bytes, Owner: {meta['file_owner']})"
        )

    # Send initial gossip
    send_gossip("localhost", 8000)  # Use real host later
    start_gossip_loop("localhost", 8000)  # Re-gossip every 30s
    start_cleanup_loop()

    run_tcp_server()
