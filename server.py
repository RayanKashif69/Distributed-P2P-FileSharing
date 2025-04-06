import sys
import os
import socket
import json
import uuid
import time
import hashlib

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
