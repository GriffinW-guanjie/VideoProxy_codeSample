#!/usr/bin/env python
from socket import socket, AF_INET, SOCK_STREAM
import thread
import select
import time
import sys
import xml.etree.ElementTree as ET

'''
global parameters
'''
log_file = ''
alpha = 0.1
listen_port = 0
fake_ip = ''
server_ip = ''
MAX_FRACTION_SIZE = 4096
b_rate_list = []


def parse_manifest(manifest):
	'''
	get the bit rate list from the manifest file
	modifying the b_rate_list
	'''	
	root = ET.fromstring(manifest)
	for child in root:
		if (child.tag.find('media')>=0):
			b_rate_list.append(int(child.attrib.get('bitrate')))
	

def choose_bitrate(t_cur):
	'''
	return a proper bit rate form the list according to current estimated throughput
	'''
	if t_cur <= 1.5 * min(b_rate_list):
		return str(min(b_rate_list))
	for b in b_rate_list:
		if t_cur >= 1.5 * b:
			rate = str(b)
	return rate


def get_single_request(data):
	'''
	reserved for testing partial requests mixed,
	not useful without asynchronous transferring
	'''
	a = data.find('GET')
	b = data.find('\n')
	c = data.find('GET',b)
	if (b>=0 and a>=0 and c>=0):
		#not likely to happen according to the browser's behavior
		return data[a:c], data[c:], True
	else:
		if(b>=0 and a>=0):
			return data, '', True
	return '', data, False


def get_type(request):
	'''
	judge request type
	'''
	request_line = request[0 : request.find('\n')+1]
	if request_line.find('Seg')>=0:
		return 'trunk'
	elif request_line.find('.f4m')>=0:
		return 'manifest'
	else:
		return 'normal'
	

def handle_manifest_request(request,client,socket_to_server):
	'''
	get two versions of manifest from server
	'''
	#get the full manifest for proxy	
	try:
		socket_to_server.send(request)
	except:
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
	m = socket_to_server.recv(MAX_FRACTION_SIZE)
	if m=='':
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
		m = socket_to_server.recv(MAX_FRACTION_SIZE)
		
	content_len = int(m[m.find('Content-Length: ')+16: m.find('\n',m.find('Content-Length: '))])
	content = m[m.find('\r\n\r\n')+4:]
	while len(content) < content_len:
		a = socket_to_server.recv(MAX_FRACTION_SIZE)
		content = content + a
	full_manifest = content

	#get the nolist manifest
	request = request[0:request.find('.f4m')] + '_nolist' + request[request.find('.f4m'):]

	try:
		socket_to_server.send(request)
	except:
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
	m = socket_to_server.recv(MAX_FRACTION_SIZE)
	if m=='':
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
		m = socket_to_server.recv(MAX_FRACTION_SIZE)

	content_len = int(m[m.find('Content-Length: ')+16: m.find('\n',m.find('Content-Length: '))])
	content = m[m.find('\r\n\r\n')+4:]
	while len(content) < content_len:
		a = socket_to_server.recv(MAX_FRACTION_SIZE)
		content = content + a
	nolist_manifest = m[0:m.find('\r\n\r\n')+4] + content
	client.send(nolist_manifest)

	return full_manifest


def handle_trunk_request(request,client,socket_to_server,t_cur,time_start):
	'''
	send modified trunk request and transfer the trunk file
	'''	
	rate = choose_bitrate(t_cur)
	new_request = request[0:request.find('1000')] + rate + request[request.find('1000')+4:]
	try:
		socket_to_server.send(new_request)
	except:
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip,8080))
		socket_to_server.send(new_request)
	m = socket_to_server.recv(MAX_FRACTION_SIZE)
	if m=='':
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
		m = socket_to_server.recv(MAX_FRACTION_SIZE)

	content_len = int(m[m.find('Content-Length: ')+16: m.find('\n',m.find('Content-Length: '))])
	content = m[m.find('\r\n\r\n')+4:]
	while len(content) < content_len:
		a = socket_to_server.recv(MAX_FRACTION_SIZE)
		content = content + a
	time_end = time.time()

	#calculate the throughput
	duration = time_end - time_start
	t_new = (content_len * 8)/(duration*1000)
	if t_cur == 0:
		t_cur = t_new
	else:
		t_cur = alpha * t_new + (1-alpha) * t_cur
	message = m[0:m.find('\r\n\r\n')+4] + content
	client.send(message)
	'''
	logging
	'''
	f = open(log_file, 'a')
	filename = new_request[new_request.find('/'):new_request.find('HTTP')-1]
	print >> f, "%d %f %d %.1f %s %s %s" %(int(time.time()), duration, int(t_new), t_cur, rate, server_ip, filename)
	f.close()
	return t_cur	



def handle_normal_request(request,client,socket_to_server):
	'''
	if the request is neither for trunk nor manifest, just retransfer the message
	'''
	try:
		socket_to_server.send(request)
	except:
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
	m = socket_to_server.recv(MAX_FRACTION_SIZE)
	if m=='':
		socket_to_server = socket(AF_INET, SOCK_STREAM)
		socket_to_server.bind((fake_ip,0))
		socket_to_server.connect((server_ip, 8080))
		socket_to_server.send(request)
		m = socket_to_server.recv(MAX_FRACTION_SIZE)

	content_len = int(m[m.find('Content-Length: ')+16: m.find('\n',m.find('Content-Length: '))])
	content = m[m.find('\r\n\r\n')+4:]
	while len(content) < content_len:
		a = socket_to_server.recv(MAX_FRACTION_SIZE)
		content = content + a
	message = m[0:m.find('\r\n\r\n')+4] + content
	#print message
	client.send(message)	


def handle_client(client):
	#connect to the server
	socket_to_server = socket(AF_INET, SOCK_STREAM)
	socket_to_server.bind((fake_ip,0))
	socket_to_server.connect((server_ip, 8080))
	c_data = ''
	t_cur = 0
	manifest = ''
	b_rate = 0

	#alternate message transfer
	while True:
		try:		
			m = client.recv(MAX_FRACTION_SIZE)
		except:
			client.close()
			socket_to_server.close()
			break
		if (m == ''):
			client.close()
			socket_to_server.close()
			break
		c_data = c_data + m

		#in case of receiving partial request
		while True:
			request, c_data, complete = get_single_request(c_data)
			if complete:
				break
			m = client.recv(MAX_FRACTION_SIZE)
			c_data = c_data + m	

		#print request
		
		request_type = get_type(request)
		time_start = time.time()
		#handle different types of request
		if (request_type == 'trunk'):
			t_cur = handle_trunk_request(request,client,socket_to_server,t_cur,time_start)			
		elif (request_type == 'manifest'):
			manifest = handle_manifest_request(request,client,socket_to_server)
			parse_manifest(manifest)
			b_rate_list.sort()
		else:
			handle_normal_request(request,client,socket_to_server)
		

if __name__ == '__main__':

	#reading the argument
	log_file = sys.argv[1]
	alpha = float(sys.argv[2])
	listen_port = int(sys.argv[3])
	fake_ip = sys.argv[4]
	server_ip = sys.argv[5]

	threadnum = 0

	#initialize listening sockets
	socket_listen = socket(AF_INET, SOCK_STREAM)
	socket_listen.bind(('', listen_port))
	socket_listen.listen(5)
	
	#waiting for connection request
	while True:
		socket_to_client, client_ip = socket_listen.accept()
		try:
			thread.start_new_thread( handle_client, (socket_to_client, )) 
		except:
			print "Unable to start thread"

   

