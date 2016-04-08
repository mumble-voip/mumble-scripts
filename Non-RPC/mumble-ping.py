#!/usr/bin/env python2
# -*- coding: utf-8
# Based on pcgod's mumble-ping script found at http://0xy.org/mumble-ping.py.

from struct import *
import socket, sys, time, datetime

if len(sys.argv) < 3:
	print "Usage: %s <host> <port>" % sys.argv[0]
	sys.exit()

host = sys.argv[1]
port = int(sys.argv[2])

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(1)

buf = pack(">iQ", 0, datetime.datetime.now().microsecond)
s.sendto(buf, (host, port))

try:
	data, addr = s.recvfrom(1024)
except socket.timeout:
	print "%d:NaN:NaN" % (time.time())
	sys.exit()

print "recvd %d bytes" % len(data)

r = unpack(">bbbbQiii", data)

version = r[1:4]
# r[0,1,2,3] = version
# r[4] = ts
# r[5] = users
# r[6] = max users
# r[7] = bandwidth

ping = (datetime.datetime.now().microsecond - r[4]) / 1000.0
if ping < 0: ping = ping + 1000

print "Version %d.%d.%d, %d/%d Users, %.1fms, %dkbit/s" % (version + (r[5], r[6], ping, r[7]/1000))

