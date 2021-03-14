#!/usr/bin/env python3

from struct import *
from string import Template
import socket, sys, time, datetime

if len(sys.argv) < 3:
	print(f"Usage: {sys.argv[0]} <host> <port> [<format>] [-v]")
	sys.exit()

host = sys.argv[1]
port = int(sys.argv[2])
if len(sys.argv) > 3 and sys.argv[3] != '-v':
	fmt = sys.argv[3]
else:
	fmt = "Version $v, $u/$m Users, $p, $b"
verbose = '-v' in sys.argv

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(1)

buf = pack(">iQ", 0, datetime.datetime.now().microsecond)
s.sendto(buf, (host, port))

try:
	data, addr = s.recvfrom(1024)
except socket.timeout:
	print(f"{time.time()}:NaN:NaN")
	sys.exit()

if verbose:
	print(f"recvd {len(data)} bytes")

r = unpack(">bbbbQiii", data)

version = '.'.join([str(v) for v in r[1:4]])
ts = r[4]
users = r[5]
max_users = r[6]
bandwidth = f"{r[7] / 1000}kbit/s"

ping = (datetime.datetime.now().microsecond - r[4]) / 1000.0
if ping < 0:
	ping = ping + 1000
ping = f"{ping:.1f}ms"

lut = {
	'v': version,
	't': ts,
	'u': users,
	'm': max_users,
	'p': ping,
	'b': bandwidth,
}
t = Template(fmt)
print(t.substitute(**lut))

