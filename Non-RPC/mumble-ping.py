#!/usr/bin/env python3

from struct import *
from string import Template
import socket, sys, time, datetime, argparse

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('host', type=str, help='hostname or IP')
	parser.add_argument('port', type=int, help='port; default Mumble port is 64738')
	parser.add_argument('--format', type=str, required=False, default='Version $v, $u/$m Users, $p, $b')
	parser.add_argument('--verbose', '-v', dest='verbose', action='store_true')
	parser.set_defaults(verbose=False)
	args = parser.parse_args()

	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.settimeout(1)

	buf = pack(">iQ", 0, datetime.datetime.now().microsecond)
	s.sendto(buf, (args.host, args.port))

	try:
		data, addr = s.recvfrom(1024)
	except socket.timeout:
		print(f"{time.time()}:NaN:NaN")
		sys.exit()

	if args.verbose:
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
	t = Template(args.format)
	print(t.substitute(**lut))
