# load additional Python modules
import socket  
import time
import csv
import os.path

# create TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# retrieve local hostname
local_hostname = socket.gethostname()

# get fully qualified hostname
local_fqdn = socket.getfqdn()

# get the according IP address
ip_address = socket.gethostbyname(local_hostname)

# bind the socket to the port 23456, and connect
server_address = ('192.168.0.101', 32323)  

sock.connect(server_address)  
#sock.send("Hello server!")
print ("connecting to %s (%s) with %s" % (local_hostname, local_fqdn, ip_address))

# define example data to be sent to the server
'''temperature_data = ["15", "22", "21", "26", "25", "19"]  
for entry in temperature_data:  
    print ("data: %s" % entry)
    new_data = str("temperature: %s\n" % entry).encode("utf-8")
    sock.sendall(new_data)

    # wait for two seconds
    time.sleep(2)

# close connection
sock.close()  
'''

with open('endtime.txt', 'wb') as f:
    print ('file opened')
    while True:
        print('receiving data...')
        data = sock.recv(1024)
        print('data=%s', (data))
        if not data:
            break
        # write data to a file
        f.write(data)
f.close()
print('Successfully get the file')
sock.close()
print('connection closed')

startfile = open("starttime.txt", "r")
start = float(startfile.read())
print(start)
startfile.close()

endfile = open("endtime.txt", "r")
end = float(endfile.read())
print(end)
endfile.close()

elapsed = end-start

hours, rem = divmod(end-start, 3600)
minutes, seconds = divmod(rem, 60)

elapsedformat = "{:0>2}:{:0>2}:{:09.6f}".format(int(hours),int(minutes),seconds)

print("Total Round Time: ", end-start)
print("Total Round Time: ", elapsedformat)
#print("Total Round Time: ", elapsed.seconds,":",elapsed.microseconds)

totaltimefile = "totaltime.csv"

time_list = [elapsedformat]


if os.path.isfile(totaltimefile):
    print("Appending to file totaltime.csv")
    with open('totaltime.csv','a') as file:
        writer = csv.writer(file)
        writer.writerow(time_list)              
else:
    print("Making new file totaltime.csv")
    with open('totaltime.csv','w') as file:
        fields=['totalkeysendtime']
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerow(time_list)

print("recording time complete")

