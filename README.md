# Distributed P2P File Sharing System 

## How to Start Your Peer

To start my peer, run the Python script with the required command-line arguments:

```bash
python3 server.py <peer_id> <host> <p2p_port> <http_port>
```
- Example
```bash
python3 server.py kashifm eagle.cs.umanitoba.ca 8115 8116
```

- It will show the port where the TCP server is hosted and where the http web server is hosted after running.


- After doing a get <file_id> it might take some time to actually get a file. the way i have implemented is that i loop through the peers with files in the metadata and try to get the file from one of them. Eventually i get the file from one of the well known hosts/other peers(usually its the well known host) in my tracked peers. for files like bitcoin.pdf or image.png it might take up a while up to 20-30 seconds to actually download the file depending on how busy the network is. You will see other messages on the terminal while get is happening in the background, please stick and check the logs on the CLI, the file does download and show a "successfully download file from <peerid>".
  
- My browser refreshed continously, but you will see actual changes that happen after the 30s(re gossip) or 60s(peer dropoout time) mark, please be patient with that. with well known hosts the changes happen quite quick.

- if i drop a tracked peer from the list after timeout, you should see eventually that he will be dropped from the list of peerswithfiles. give some time for that.
- 
