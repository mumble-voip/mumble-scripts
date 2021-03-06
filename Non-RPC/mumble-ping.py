#!/usr/bin/env python3
# Based on pcgod's mumble-ping script found at http://0xy.org/mumble-ping.py.

from struct import *
import socket, sys, time, datetime

if len(sys.argv) < 3:
	print(f"Usage: {sys.argv[0]} <host> <port>")
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
	print(f"{time.time()}:NaN:NaN")
	sys.exit()

print(f"recvd {len(data)} bytes")

r = unpack(">bbbbQiii", data)

version = r[1:4]
ts = r[4]
users = r[5]
max_users = r[6]
bandwidth = r[7]

ping = (datetime.datetime.now().microsecond - r[4]) / 1000.0
if ping < 0:
	ping = ping + 1000

print(f"Version {'.'.join([str(v) for v in version])}, {users}/{max_users} Users, {ping:.1f}ms, {bandwidth / 1000}kbit/s")

