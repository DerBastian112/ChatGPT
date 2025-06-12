import serial
import keyboard

port=serial.Serial("COM18",baudrate=2400,bytesize=7,parity=serial.PARITY_ODD)
port.dtr=True
port.rts=False
file=open("out.txt","w")
port.flush()

run=1
print("Starte Messung")
while(run):
	if (keyboard.is_pressed("q")): 
		run=0
	
	if port.inWaiting()==0: continue
	try:
		data=port.readline()
	except:
		pass
	
	if data[3]==60: continue
	
	val=0
	for i in range(5):
		val=val*10
		val=val+(int(data[i])-0x30)
	if((int(data[8])&0x04)): 
		val=-val
	t=data[5]&0x0f
	if t==1:
		val=val*0.0001
	elif t==2:
		val=val*0.001
	elif t==3:
		val=val*0.01
	elif t==4:
		val=val*0.1
	elif t==5:
		val=val*1
	elif t==6:
		val=val*10
	val=round(val,2)	
	print(val)
	file.write(str(val).replace(".",","))
	file.write("\n")
file.close()

