#!/usr/bin/env python
# -*- coding: utf-8
# munin-murmur.py - Small "murmur stats (User/Bans/Uptime/Channels)" script for munin.
# Copyright (c) 2010, Natenom / Natenom@googlemail.com
# Version: 0.0.1
# 2010-02-09
# 
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials provided
#      with the distribution.
#    * Neither the name of the developer nor the names of its
#      contributors may be used to endorse or promote products derived
#      from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.  


#Path to Murmur.ice
iceslice='/usr/share/slice/Murmur.ice'

#Murmur-Port (not needed to work, only for display purposes)
serverport=64738

#Port where ice listen
iceport=6502


import Ice, sys
Ice.loadSlice(iceslice)
ice = Ice.initialize()
import Murmur

if (sys.argv[1:]):
  if (sys.argv[1] == "config"):
    print 'graph_title Murmur (Port %s)' % (serverport)
    print 'graph_vlabel Count'
    print 'users.label Users'
    print 'uptime.label Uptime in days'
    print 'chancount.label Channelcount/10'
    print 'bancount.label Bans on server'
    sys.exit(0)

meta = Murmur.MetaPrx.checkedCast(ice.stringToProxy("Meta:tcp -h 127.0.0.1 -p %s" % (iceport)))
server=meta.getServer(1)
print "users.value %i" % (len(server.getUsers()))
print "uptime.value %.2f" % (float(meta.getUptime())/60/60/24)
print "chancount.value %.1f" % (len(server.getChannels())/10)
print "bancount.value %i" % (len(server.getBans()))

ice.shutdown()