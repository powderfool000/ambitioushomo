import csv
import os.path

keytimefile = "testtime.csv"

totalkeysendtime = 309.2898316383362
dragonflykeyauthtime = 310.2898316383362
sendprikeytime = 311.2898316383362

hours, rem = divmod(totalkeysendtime, 3600)
minutes, seconds = divmod(rem, 60)
elapsedformat = "{:0>2}:{:0>2}:{:09.6f}".format(int(hours),int(minutes),seconds)

time_list = [totalkeysendtime,dragonflykeyauthtime,sendprikeytime]

if os.path.isfile(keytimefile):
    print("Appending to file testtime.csv")
    with open('testtime.csv','a') as file:
        writer = csv.writer(file)
        writer.writerow(time_list)              
else:
    print("Making new file testtime.csv")
    with open('testtime.csv','w') as file:
        fields=['totalkeysendtime','dragonflykeyauthtime','sendprikeytime','something']
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerow(time_list) 

print("recording time complete")
