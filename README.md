# Distributed-P2P-FileSharing

- After doing a get <file_id> it might take some time to actually get a file. the way i have implemented is that i loop through the peers with files in the metadata and try to get the file from one of them. Eventually i get the file from one of the well known hosts/other peers(usually its the well known host) in my tracked peers. for files like bitcoin.pdf or image.png it might take up a while up to 20-30 seconds to actually download the file depending on how busy the network is. You will see other messages on the terminal while get is happening in the background, please stick and check the logs on the CLI, the file does download and show a "successfully download file from <peerid>".
  
