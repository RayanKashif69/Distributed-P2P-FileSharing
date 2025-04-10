# Distributed P2P File Sharing System 

## How to Start Peer

To start my peer, run the Python script with the required command-line arguments:

```bash
python3 server.py <peer_id> <host> <p2p_port> <http_port>
```
- Example
```bash
python3 server.py kashifm eagle.cs.umanitoba.ca 8115 8116
```

- It will show the port where the TCP server is hosted and where the http web server is hosted after running.


Upon starting:
- A storage directory is created as `./storage_<peer_id>`.
- TCP and HTTP servers are started and their ports are shown in the console.
- The peer connects to the network and starts auto-fetching files.

---


##  Notes for Grader / Evaluation Tips

Please take note of the following important behaviors and caveats while running my peer:

- ALL message handling AND CLI commands are fully functional, for some messages i have suppressed the message logging but you should be able to see the changes on the stats as soon as the messages are exchanged with other peers. Below are some other notes for you:

- **Initial Auto-Fetch May Appear Slow**  
  Upon startup, my peer automatically attempts to fetch 3–5 files from the network. During this time, it may appear unresponsive. **This is expected behavior.**  
  - The network was heavily loaded during my testing, and this caused delays.
  - **Please wait until you see the `Command Menu` prompt** — that indicates the auto-fetch process has completed and the peer is ready for interaction.

- **Auto-Fetch Failures Due to Metadata Mismatch or Timeouts**  
  In some cases, metadata may indicate that a peer has a file, but:
  - The peer doesn't actually have a local copy.
  - The peer becomes unresponsive and times out.  
  These situations can cause auto-fetch to fail. However, **when initial fetching from well-known hosts, the process is usually faster and more reliable (always works).**

- **Console Spam for Debugging**  
  If you notice the terminal being spammed quickly with messages, it's due to debug print statements added for development purposes. These do not impact core functionality.

- **File Download Delay After `get <file_id>`**  
  After issuing a `get <file_id>`, it may take 20–30 seconds to download a file — especially for larger files like `bitcoin.pdf` or `image.png`, or when the network is congested.  
  - The peer tries multiple peers listed in the metadata and usually retrieves the file from a good peer(well known hosts)
  - The CLI will show:  
    `Successfully downloaded file from <peer_id>`  
    once the process completes. Please be patient and monitor the CLI output. You'll see other messages from regossip and announce while the "get" is happening.

- **Browser Stats Page May Lag Behind**  
  The browser stats page may take some time (30s–60s) to reflect updated file and peer information.  
  - This is due to gossip intervals (30s) and peer timeout windows (60s).
  - **With well-known hosts, updates are usually quicker.**

- **Peer Dropout Handling**  
  If a peer becomes inactive, my implementation will eventually drop it from the `tracked peers` list and remove it from the `peersWithFile` entry.  
- This cleanup happens after the timeout period.
- i have a seperate thread handling the cleanup.

---

##  Synchronization Timing

- **How long does it take?**  
  Metadata synchronization typically takes a couple of seconds to happen but in other cases it could take **20–60 seconds**, depending on network load and the responsiveness of peers.

- **How do I know it’s synchronized?**  
  You will:
  - See the `Command Menu` prompt.
  - Observe file listings and peer info on the stats page.
  - Notice fewer metadata logs, indicating network stabilization.
  - Once the auto fetch is complete, it should show a message "AUTO FETCH PROCESS COMPLETE"

---

##  Metadata Creation and Loading Code

- When a peer starts, it first attempts to load its metadata from a local metadata.json file. If this file exists, the metadata is read and loaded into memory. If it doesn’t, the system scans the local storage directory and creates metadata from scratch. 
- For each file found, it reads the content, calculates its size, fetches the last modified timestamp, and generates a unique file_id using a SHA256 hash of the file’s content and timestamp. This information, along with the peer ID and ownership status, is stored in a metadata dictionary.
- The metadata is then saved to metadata.json for future use. This ensures that each peer accurately tracks which files it has and can share this information with others in the network.

- storage_peerid is the directory where the files and metadata.json are stored 

###  Relevant Functions in `server.py`:
#### `load_metadata()`
#### `scan_storage_folder()`
#### `save_metadata()`
#### lines 50 - 101

---

##  Peer Cleanup Logic

Peers that have not been heard from in over **60 seconds** (the defined dropout timeout) are removed from the `tracked_peers` list, and their presence is also removed from all relevant `peers_with_file` lists in the metadata. This ensures that outdated peers don’t persist in the system and that the metadata reflects only active participants in the network.

- **File:** `server.py`  
- **Lines:** 562–585  
- **Function:** `cleanup_tracked_peers()`

###  Code Summary:
The function iterates through `tracked_peers`, checks if each peer’s `last_seen` timestamp exceeds the `PEER_DROP_TIMEOUT`, and:
- Deletes that peer from the `tracked_peers` dictionary
- Removes the peer from all `peers_with_file` lists inside `file_metadata`
- Saves the updated metadata back to `metadata.json`

