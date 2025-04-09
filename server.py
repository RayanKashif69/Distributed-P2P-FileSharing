import sys
import select
import json
import socket
import time
import random
import uuid
import hashlib
import re
import functools
import base64
import threading
import os
import datetime

lock = threading.Lock()

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
GOSSIP_PEERS = 3
GOSSIP_INTERVAL = 30
PEER_DROP_TIMEOUT = 60
WELL_KNOWN_HOSTS = ["silicon", "hawk", "grebe", "eagle"]

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
        size = round(len(content) / (1024 * 1024), 2)  # float MB with 2 decimals

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
            "hasCopy": "yes",
        }
    print(f"[{peer_id}] Generated metadata for {len(metadata)} file(s).")
    return metadata


# save metadata to file
def save_metadata():
    metadata_path = os.path.join(base_path, "metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(file_metadata, f, indent=2)
    # print(f"[{peer_id}] Saved metadata to file.")


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
        # print(f"[{peer_id}] Sent GOSSIP to {to_host}:{to_port}")
        seen_gossip_ids.add(gossip_id)  # Mark it as seen so we don't rebroadcast
    except Exception as e:
        # print(f"[{peer_id}] Failed to send GOSSIP to {to_host}:{to_port}: {e}")
        pass


# handling GOSSIP_REPLY message I receive from other peers
def handle_gossip_reply(msg):
    sender_id = msg["peerId"]
    sender_host = msg["host"]
    sender_port = msg["port"]
    files = msg.get("files", [])

    # 1. Update tracked_peers
    if sender_id != peer_id:
        # if sender_id not in tracked_peers:
        # print(f"[{peer_id}] Tracking new peer from reply: {sender_id}")
        tracked_peers[sender_id] = {
            "host": sender_host,
            "port": sender_port,
            "last_seen": time.time(),
        }

    # 2. Merge metadata
    for file in files:
        file_id = file["file_id"]
        if file_id not in file_metadata:
            file_metadata[file_id] = {
                **file,
                "peers_with_file": [sender_id],
                "hasCopy": "no",
            }
            # print(f"[{peer_id}] Added new file {file['file_name']} from {sender_id}")
        else:
            existing = file_metadata[file_id]
            if file["file_timestamp"] > existing["file_timestamp"]:
                print(
                    f"[{peer_id}] Updating file {file['file_name']} to newer version from {sender_id}"
                )
                file_metadata[file_id].update(file)

            if sender_id not in file_metadata[file_id]["peers_with_file"]:
                file_metadata[file_id]["peers_with_file"].append(sender_id)

    save_metadata()


# handling recieved GOSSIP message and replying to the GOSSIP
def handle_gossip(msg):
    gossip_id = msg["id"]
    sender_id = msg["peerId"]
    sender_host = msg["host"]
    sender_port = msg["port"]

    # 1. Ignore duplicate gossip IDs
    if gossip_id in seen_gossip_ids:
        # print(f"[{peer_id}] Already saw gossip {gossip_id}, ignoring.")
        return
    seen_gossip_ids.add(gossip_id)

    # 2. Add sender to tracked_peers
    if sender_id != peer_id and sender_id not in tracked_peers:
        tracked_peers[sender_id] = {
            "host": sender_host,
            "port": sender_port,
            "last_seen": time.time(),
        }
        # print(
        #    f"[{peer_id}] Tracked new peer: {sender_id} at {sender_host}:{sender_port}"
        # )
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
    #    print(f"[{peer_id}] Sent GOSSIP_REPLY to {sender_id}")
    except Exception as e:
        # print(f"[{peer_id}] Failed to send GOSSIP_REPLY to {sender_id}: {e}")
        pass

    # 4. Forward GOSSIP to random peers
    eligible_peers = [p for p in tracked_peers if p != sender_id and p != peer_id]

    if eligible_peers:
        peers_to_forward = random.sample(
            eligible_peers, min(GOSSIP_PEERS, len(eligible_peers))
        )
        for pid in peers_to_forward:
            pinfo = tracked_peers[pid]
            # print(
            #   f"[{peer_id}] Forwarding GOSSIP to {pid} at {pinfo['host']}:{pinfo['port']}"
            # )
            send_gossip(pinfo["host"], pinfo["port"])


# handle GET_FILE request and send the FILE_DATA response back
def handle_get_file(conn, file_id):
    entry = file_metadata.get(file_id)

    if not entry or entry.get("hasCopy") != "yes":
        print(
            f"[{peer_id}] Cannot fulfill GET_FILE for {file_id} (not found or no copy)"
        )
        response = {
            "type": "FILE_DATA",
            "file_id": None,
            "file_name": None,
            "file_owner": None,
            "file_timestamp": None,
            "file_size": 0,
            "data": None,
        }
        conn.sendall(json.dumps(response).encode())
        return

    file_path = os.path.join(base_path, entry["file_name"])
    try:
        with open(file_path, "rb") as f:
            content = f.read()
        encoded = content.hex()

        response = {
            "type": "FILE_DATA",
            "file_id": file_id,
            "file_name": entry["file_name"],
            "file_owner": entry["file_owner"],
            "file_timestamp": entry["file_timestamp"],
            "file_size": entry["file_size"],
            "data": encoded,
        }
        conn.sendall(json.dumps(response).encode())
        print(f"[{peer_id}] Sent file '{entry['file_name']}' (ID: {file_id}) to peer")
    except Exception as e:
        print(f"[{peer_id}] Error reading/sending file: {e}")


# get metadata of files that have a copy
def get_gossip_reply_metadata():
    reply_files = []
    for file in file_metadata.values():
        if file.get("hasCopy") == "yes":
            reply_files.append(
                {
                    "file_name": file["file_name"],
                    "file_size": file["file_size"],
                    "file_id": file["file_id"],
                    "file_owner": file["file_owner"],
                    "file_timestamp": file["file_timestamp"],
                }
            )
    #  print(f"[{peer_id}] GOSSIP_REPLY will include {len(reply_files)} file(s).")
    return reply_files


# handle ANNOUNCE message and update the metadata
def handle_announce(msg):
    file_id = msg["file_id"]

    if file_id in file_metadata:
        # Update peers_with_file
        if msg["from"] not in file_metadata[file_id]["peers_with_file"]:
            file_metadata[file_id]["peers_with_file"].append(msg["from"])
        return

    # Add new file metadata
    file_metadata[file_id] = {
        "file_name": msg["file_name"],
        "file_size": msg["file_size"],
        "file_id": file_id,
        "file_owner": msg["file_owner"],
        "file_timestamp": msg["file_timestamp"],
        "hasCopy": "no",
        "peers_with_file": [msg["from"]],
    }

    save_metadata()
    print(f"[{peer_id}] Announced new file '{msg['file_name']}' from {msg['from']}")


# handle DELETE message and delete the file locally
# and update the metadata
def handle_delete(msg):
    file_id = msg.get("file_id")
    sender_id = msg.get("from")

    entry = file_metadata.get(file_id)
    if not entry:
        return  # I don’t have this file in metadata

    #  Only process DELETE if it comes from the owner
    if entry["file_owner"] != sender_id:
        return  # Ignore unauthorized DELETE request

    #  Step 1: Delete the file from local disk
    file_path = os.path.join(base_path, entry["file_name"])
    if entry["hasCopy"] == "yes" and os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(
                f"[{peer_id}] Deleted file '{entry['file_name']}' due to DELETE from {sender_id}"
            )
        except Exception as e:
            print(f"[{peer_id}] Failed to delete local file: {e}")

    #  Step 2: Update metadata
    entry["hasCopy"] = "no"
    if peer_id in entry["peers_with_file"]:
        entry["peers_with_file"].remove(peer_id)

    save_metadata()


# handle FILE_DATA message and save the file locally
# and update the metadata
def handle_file_data(msg):
    file_id = msg["file_id"]
    file_name = msg["file_name"]
    file_owner = msg["file_owner"]
    file_timestamp = msg["file_timestamp"]
    file_size = msg["file_size"]
    encoded_data = msg["data"]

    try:
        # Decode the hex data
        content = bytes.fromhex(encoded_data)

        # Save the file locally
        with open(os.path.join(base_path, file_name), "wb") as f:
            f.write(content)

        # Update metadata
        file_metadata[file_id] = {
            "file_name": file_name,
            "file_size": round(file_size / (1024 * 1024), 2),  # convert to MB
            "file_id": file_id,
            "file_owner": file_owner,
            "file_timestamp": file_timestamp,
            "hasCopy": "yes",
            "peers_with_file": [peer_id],
        }

        save_metadata()

        print(f"[{peer_id}] Received and saved file '{file_name}' (ID: {file_id})")

        # ANNOUNCE to all other peers
        announce_new_file(file_id)

    except Exception as e:
        print(f"[{peer_id}] Failed to process FILE_DATA: {e}")


# here all the messages are handled
def handle_message(conn, addr, msg):
    """
    Process the incoming message based on its type.
    Handle different message types (e.g., GOSSIP, GOSSIP_REPLY, etc.)
    """
    if "type" in msg:
        if msg["type"] == "GOSSIP":
            handle_gossip(msg)

        elif msg["type"] == "GOSSIP_REPLY":
            handle_gossip_reply(msg)

        elif msg["type"] == "GET_FILE":
            print(f"[{peer_id}] Received GET_FILE request for {msg.get('file_id')}")
            handle_get_file(conn, msg["file_id"])

        elif msg["type"] == "FILE_DATA":
            print(f"[{peer_id}] Received FILE_DATA for {msg.get('file_name')}")
            handle_file_data(msg)

        elif msg["type"] == "ANNOUNCE":
            print(f"[{peer_id}] Received ANNOUNCE for {msg.get('file_name')}")
            handle_announce(msg)

        elif msg["type"] == "DELETE":
            print(f"[{peer_id}] Received DELETE for {msg.get('file_name')}")
            handle_delete(msg)

        else:
            print(f"[{peer_id}] Received unknown message type: {msg['type']}")
    else:
        print(f"[{peer_id}] Received message without type: {msg}")


def announce_new_file(file_id):
    entry = file_metadata[file_id]
    msg = {
        "type": "ANNOUNCE",
        "from": peer_id,
        "file_name": entry["file_name"],
        "file_size": entry["file_size"],
        "file_id": file_id,
        "file_owner": entry["file_owner"],
        "file_timestamp": entry["file_timestamp"],
    }

    with lock:
        for pid, pinfo in list(tracked_peers.items()):
            try:
                with socket.create_connection(
                    (pinfo["host"], pinfo["port"]), timeout=5
                ) as sock:
                    sock.sendall(json.dumps(msg).encode())
            except:
                continue  # Fail silently

    print(
        f"[{peer_id}] Announced new file '{entry['file_name']}' to all tracked peers."
    )


def push_to_random_peer(file_id, file_name, content, file_size, timestamp):
    encoded = content.hex()
    msg = {
        "type": "FILE_DATA",
        "file_id": file_id,
        "file_name": file_name,
        "file_owner": peer_id,
        "file_timestamp": timestamp,
        "file_size": file_size,
        "data": encoded,
    }

    with lock:
        eligible_peers = [p for p in tracked_peers if p != peer_id]
        if not eligible_peers:
            print(f"[{peer_id}] No peers to push the file to.")
            return

        selected_peer = random.choice(eligible_peers)
        peer_info = tracked_peers[selected_peer]

    try:
        with socket.create_connection(
            (peer_info["host"], peer_info["port"]), timeout=5
        ) as sock:
            sock.sendall(json.dumps(msg).encode())
        print(f"[{peer_id}] Pushed file to peer {selected_peer}")
    except Exception as e:
        print(f"[{peer_id}] Failed to push file to {selected_peer}: {e}")


def handle_push_command(file_path):
    if not os.path.isfile(file_path):
        print(f"[{peer_id}] File '{file_path}' does not exist.")
        return

    try:
        with open(file_path, "rb") as f:
            content = f.read()
        file_name = os.path.basename(file_path)
        file_size = round(len(content) / (1024 * 1024), 2)
        timestamp = int(time.time())
        file_id = hashlib.sha256(content + str(timestamp).encode()).hexdigest()

        # Save locally
        dest_path = os.path.join(base_path, file_name)
        with open(dest_path, "wb") as f:
            f.write(content)

        # Update metadata
        file_metadata[file_id] = {
            "file_name": file_name,
            "file_size": file_size,
            "file_id": file_id,
            "file_owner": peer_id,
            "file_timestamp": timestamp,
            "hasCopy": "yes",
            "peers_with_file": [peer_id],
        }

        save_metadata()
        print(f"[{peer_id}] Pushed file '{file_name}' (ID: {file_id}) locally.")

        # Step 2: Push to one other peer
        push_to_random_peer(file_id, file_name, content, file_size, timestamp)

        # Step 3: Announce to all tracked peers
        announce_new_file(file_id)

    except Exception as e:
        print(f"[{peer_id}] Failed to push file: {e}")


def run_tcp_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, p2p_port))
    server_sock.listen(5)
    server_sock.setblocking(False)
    print(f"[{peer_id}] TCP server listening on {host}:{p2p_port}")

    inputs = [server_sock]
    buffers = {}  # socket -> data buffer

    while True:
        readable, _, _ = select.select(inputs, [], [], 1)

        for s in readable:
            if s is server_sock:
                conn, addr = server_sock.accept()
                conn.setblocking(False)
                inputs.append(conn)
                buffers[conn] = b""
            # print(f"[{peer_id}] Accepted connection from {addr}")
            else:
                try:
                    chunk = s.recv(4096)
                    if chunk:
                        buffers[s] += chunk
                        try:
                            # Try decoding full JSON object
                            msg = json.loads(buffers[s].decode())
                            handle_message(s, s.getpeername(), msg)
                            buffers[s] = b""  # Clear buffer after successful parse
                        except json.JSONDecodeError:
                            # Wait for more data if JSON is incomplete
                            continue
                    else:
                        # print(f"[{peer_id}] Connection closed.")
                        inputs.remove(s)
                        buffers.pop(s, None)
                        s.close()
                except Exception as e:
                    # print(f"[{peer_id}] Error reading from socket: {e}")
                    inputs.remove(s)
                    buffers.pop(s, None)
                    s.close()


# cleaning up my tracked peers
def cleanup_tracked_peers():
    now = time.time()
    to_remove = []

    for peerId, peerInfo in tracked_peers.items():
        last_seen = peerInfo["last_seen"]
        age = now - last_seen

        if age > PEER_DROP_TIMEOUT:
            print(f"[{peer_id}] Dropping inactive peer: {peerId} (n {int(age)}s ago)")
            to_remove.append(peerId)

    # Actually remove the peers
    for peerId in to_remove:
        del tracked_peers[peerId]

        # Now remove this peerId from any files' peers_with_file lists
        for meta in file_metadata.values():
            if peerId in meta["peers_with_file"]:
                meta["peers_with_file"].remove(peerId)

    save_metadata()
    # print(f"[{peer_id}] Cleanup done. {len(tracked_peers)} peer(s) remaining.\n")


# this is the re-GOSSIP thread that will run every 30 seconds
def start_gossip_loop():
    def loop():
        while True:
            time.sleep(GOSSIP_INTERVAL)

            # Get 3–5 peers you are tracking
            eligible = list(tracked_peers.values())
            if not eligible:
                # print(f"[{peer_id}] No tracked peers to re-gossip to.")
                continue

            selected_peers = random.sample(eligible, min(GOSSIP_PEERS, len(eligible)))
            for peer in selected_peers:
                send_gossip(peer["host"], peer["port"])

    t = threading.Thread(target=loop, daemon=True)
    t.start()


# starts the cleanup thread that will run every 10 seconds
def start_cleanup_loop():
    def loop():
        while True:
            time.sleep(10)  # check every 10s
            cleanup_tracked_peers()

    t = threading.Thread(target=loop, daemon=True)
    t.start()


# GET <fileid> command handler
def handle_get_file_cli(file_id):
    if file_id not in file_metadata:
        print(f"[{peer_id}] File ID {file_id} not found in metadata.")
        return

    meta = file_metadata[file_id]

    if meta.get("hasCopy") == "yes":
        print(f"[{peer_id}] Already have file '{meta['file_name']}' locally.")
        return

    found = False
    for peer_id_candidate in meta["peers_with_file"]:
        if peer_id_candidate == peer_id:
            continue  # Skip self

        peer_info = tracked_peers.get(peer_id_candidate)
        if not peer_info:
            continue  # Skip unknown peers

        try:
            with socket.create_connection(
                (peer_info["host"], peer_info["port"]), timeout=5
            ) as sock:
                # Send GET_FILE request
                request = {"type": "GET_FILE", "file_id": file_id}
                sock.sendall(json.dumps(request).encode())

                # Receive response in chunks
                chunks = []
                sock.settimeout(30.0)  # More generous timeout
                while True:
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    except socket.timeout:
                        break  # Stop after timeout, assume transmission complete

                raw_data = b"".join(chunks).decode()

                if not raw_data.strip():
                    # print(f"[{peer_id}] Peer {peer_id_candidate} sent no data.")
                    continue

                try:
                    response = json.loads(raw_data)
                except json.JSONDecodeError as jde:
                    # print(
                    #    f"[{peer_id}] JSON decode error from {peer_id_candidate}: {jde}"
                    # )
                    # print(
                    #    f"[{peer_id}] Raw data (first 200 chars): {repr(raw_data[:200])}"
                    # )
                    continue

                # print(json.dumps(response, indent=2))  # Debug output

                if response.get("file_id") is None:
                    print(
                        f"[{peer_id}] Peer {peer_id_candidate} does not have the file."
                    )
                    continue

                # Decode hex data
                try:
                    content = bytes.fromhex(response["data"])
                except Exception as e:
                    # print(f"[{peer_id}] Failed to decode hex content: {e}")
                    continue

                fname = response["file_name"]
                with open(os.path.join(base_path, fname), "wb") as f:
                    f.write(content)

                # Update metadata
                file_metadata[file_id]["hasCopy"] = "yes"
                if peer_id not in file_metadata[file_id]["peers_with_file"]:
                    file_metadata[file_id]["peers_with_file"].append(peer_id)

                save_metadata()

                print(
                    f"[{peer_id}] Successfully downloaded '{fname}' from {peer_id_candidate}"
                )
                found = True
                # announce the file
                announce_new_file(file_id)

                break

        except Exception as e:
            # print(f"[{peer_id}] Failed to download from {peer_id_candidate}: {e}")
            pass

    if not found:
        print(f"[{peer_id}] Could not retrieve file from any available peer.")


def auto_fetch_files_on_startup():
    print(f"[{peer_id}] Attempting to auto-fetch 3 files from the network...")
    missing_files = [
        fid
        for fid, meta in file_metadata.items()
        if meta["hasCopy"] == "no" and meta["peers_with_file"]
    ]
    random.shuffle(missing_files)
    for fid in missing_files[:3]:
        print(f"[{peer_id}] Auto-fetching file ID: {fid}")
        handle_get_file_cli(fid)


# handle DELETE command from CLI
def handle_delete_command(file_id):
    entry = file_metadata.get(file_id)
    if not entry:
        print(f"[{peer_id}] File ID {file_id} not found in metadata.")
        return

    if entry["file_owner"] != peer_id:
        print(f"[{peer_id}] You are not the owner of file ID {file_id}. Cannot delete.")
        return

    try:
        # Delete the file from disk if it exists
        file_path = os.path.join(base_path, entry["file_name"])
        if os.path.exists(file_path):
            os.remove(file_path)

        # Update metadata
        entry["hasCopy"] = "no"
        if peer_id in entry["peers_with_file"]:
            entry["peers_with_file"].remove(peer_id)

        save_metadata()
        print(f"[{peer_id}] Deleted file '{entry['file_name']}' locally.")

        # DELETE message to only peers that have the file (excluding yourself)
        delete_msg = {
            "type": "DELETE",
            "from": peer_id,
            "file_id": file_id,
        }

        for pid in entry["peers_with_file"][
            :
        ]:  # make a copy to avoid modification issues
            if pid == peer_id:
                continue  # skip self

            info = tracked_peers.get(pid)
            if not info:
                continue  # skip if no info

            try:
                with socket.create_connection(
                    (info["host"], info["port"]), timeout=5
                ) as sock:
                    sock.sendall(json.dumps(delete_msg).encode())
            except:
                continue  # silently ignore

    except Exception as e:
        print(f"[{peer_id}] Failed to delete file: {e}")


def handle_cli_command(cmd):
    if cmd == "list":
        print(f"[{peer_id}] Listing {len(file_metadata)} file(s):")
        for fid, meta in file_metadata.items():
            print("-" * 50)
            print(f"Name      : {meta['file_name']}")
            print(f"ID        : {meta['file_id']}")
            print(f"Size      : {meta['file_size']} mbs")
            print(f"Owner     : {meta['file_owner']}")
            readable_ts = datetime.datetime.fromtimestamp(
                meta["file_timestamp"]
            ).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Timestamp : {readable_ts}")
            print(f"Available on peers: {', '.join(meta['peers_with_file'])}")
        print("-" * 50)

    elif cmd == "peers":
        print(f"[{peer_id}] Currently tracking {len(tracked_peers)} peer(s):")
        for pid, info in tracked_peers.items():
            last_seen = int(time.time() - info["last_seen"])
            print(
                f"- {pid}: {info['host']}:{info['port']} (last seen {last_seen}s ago)"
            )
    elif cmd.startswith("get "):
        tokens = cmd.split()
        if len(tokens) != 2:
            print(f"[{peer_id}] Usage: get <file_id>")
            return
        handle_get_file_cli(tokens[1])
    elif cmd.startswith("push "):
        tokens = cmd.split(" ", 1)
        if len(tokens) != 2:
            print(f"[{peer_id}] Usage: push <file_path>")
            return
        handle_push_command(tokens[1])
    elif cmd.startswith("delete "):
        tokens = cmd.split()
        if len(tokens) != 2:
            print(f"[{peer_id}] Usage: delete <file_id>")
            return
        handle_delete_command(tokens[1])
    elif cmd == "exit":
        print(f"[{peer_id}] Shutting down peer.")
        save_metadata()
        sys.exit(0)
    else:
        print(f"[{peer_id}] Unknown command: {cmd}")


# start the CLI loop for user commands
def start_cli_loop():

    def loop():
        while True:
            try:
                cmd = input("> ").strip()
                handle_cli_command(cmd)
            except EOFError:
                break
            except Exception as e:
                print(f"[{peer_id}] CLI error: {e}")

    t = threading.Thread(target=loop, daemon=True)
    t.start()


def generate_stats_page():
    html = "<html><head><meta http-equiv='refresh' content='2'></head><body>"
    html += f"<h2>Peer Stats for {peer_id}</h2>"

    # Tracked Peers Table
    html += "<h3>Tracked Peers</h3>"
    html += "<table border='1'><tr><th>Peer ID</th><th>Host</th><th>Port</th><th>Last Seen</th></tr>"
    for pid, info in tracked_peers.items():
        last_seen = int(time.time() - info["last_seen"])
        html += f"<tr><td>{pid}</td><td>{info['host']}</td><td>{info['port']}</td><td>{last_seen}s ago</td></tr>"
    html += "</table>"

    # Files Table
    html += "<h3>Files</h3>"
    html += "<table border='1'><tr><th>ID</th><th>Name</th><th>Owner</th><th>Size (MB)</th><th>Timestamp</th><th>hasCopy</th><th>Peers</th></tr>"
    for fid, meta in file_metadata.items():
        try:
            short_id = fid[:10] + "..."
            readable_ts = datetime.datetime.fromtimestamp(
                float(meta["file_timestamp"])
            ).strftime("%Y-%m-%d %H:%M:%S")
            peers_str = ", ".join(meta.get("peers_with_file", []))
            html += (
                f"<tr><td>{short_id}</td><td>{meta['file_name']}</td>"
                f"<td>{meta['file_owner']}</td><td>{meta['file_size']}</td>"
                f"<td>{readable_ts}</td><td>{meta['hasCopy']}</td>"
                f"<td>{peers_str}</td></tr>"
            )
        except Exception as e:
            #  print(f" Error rendering row for {fid}: {e}")
            pass
    html += "</table>"

    html += "</body></html>"
    return html


def start_http_server():
    def loop():
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, http_port))
        server.listen(5)
        print(f"[{peer_id}] HTTP stats page running at http://{host}:{http_port}/")

        while True:
            conn, addr = server.accept()
            try:
                request = conn.recv(1024).decode()
                if request.startswith("GET /favicon.ico"):
                    conn.close()
                    continue

                html = generate_stats_page()
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html\r\n"
                    "Connection: close\r\n\r\n" + html
                )
                conn.sendall(response.encode())
            except Exception as e:
                print(f"[{peer_id}] HTTP server error: {e}")
            finally:
                conn.close()

    threading.Thread(target=loop, daemon=True).start()


def start_tcp_server():
    t = threading.Thread(target=run_tcp_server, daemon=True)
    t.start()


if __name__ == "__main__":
    file_metadata = load_metadata()
    save_metadata()
    print(f"[{peer_id}] Current metadata entries:")
    for fid, meta in file_metadata.items():
        print(
            f" - {meta['file_name']} (ID: {fid}, Size: {meta['file_size']} Bytes, Owner: {meta['file_owner']})"
        )

    selected = random.choice(WELL_KNOWN_HOSTS)
    well_known_host = f"{selected}.cs.umanitoba.ca"
    well_known_port = 8999

    #  Start TCP server in a thread
    start_tcp_server()
    start_http_server()  # Add this

    #  Continue with rest of setup
    send_gossip(
        well_known_host, well_known_port
    )  # send initial gossip to well-known host

    auto_fetch_files_on_startup()

    start_gossip_loop()  # re gossip
    start_cleanup_loop()  # clean up tracked peers

    print(f"\n[{peer_id}] Command Options:")
    print("Use 'list'                     to view available files")
    print("Use 'peers'                    to view connected peers")
    print("Use 'push <filepath>'          to upload files")
    print("Use 'get <file_id> [dest]'     to download files")
    print("Use 'delete <file_id>'         to delete files (if you're the owner)")
    print("Use 'exit'                     to quit\n")

    start_cli_loop()

    # Optional: keep main thread alive
    while True:
        time.sleep(1)
