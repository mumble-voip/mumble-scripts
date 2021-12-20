#!/usr/bin/env python3
# -*- coding: utf-8
#
# munin-murmur.py
# Copyright (c) 2010 - 2016, Natenom 
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above
#   copyright notice, this list of conditions and the following
#   disclaimer in the documentation and/or other materials provided
#   with the distribution.
# * Neither the name of the developer nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
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

# Settings for what to show:
show_users_all = True # All users regardless their state

show_users_muted = True # Server muted, self muted and server suppressed users.

show_users_unregistered = True # Not registered users.

show_users_registered = True # Registered users.

show_ban_count = True # Number of bans on the server; temporary global bans do not count.

show_channel_count = True # Number of channels on the server (including the root channel).

show_uptime = True # Uptime of the server (in days)

#Path to Murmur.ice
iceslice = "/usr/share/slice/Murmur.ice"

# Includepath for Ice, this is default for Debian
iceincludepath = "/usr/share/ice/slice"

# Murmur-Port (not needed to work, only for display purposes)
serverport = 64738

# Host of the Ice service; most probably this is 127.0.0.1
icehost = "127.0.0.1"

# Port where ice listen
iceport = 6502

# Ice Password to get read access.
# If there is no such var in your murmur.ini, this can have any value.
# You can use the values of icesecret, icesecretread or icesecretwrite in your murmur.ini
icesecret = "secureme"

# MessageSizeMax; increase this value, if you get a MemoryLimitException.
# Also check this value in murmur.ini of your Mumble-Server.
# This value is being interpreted in kibiBytes.
messagesizemax = "65535"

####################################################################
##### DO NOT TOUCH BELOW THIS LINE UNLESS YOU KNOW WHAT YOU DO #####
####################################################################
import Ice, sys
Ice.loadSlice("--all -I%s %s" % (iceincludepath, iceslice))

props = Ice.createProperties([])
props.setProperty("Ice.MessageSizeMax", str(messagesizemax))
props.setProperty("Ice.ImplicitContext", "Shared")
props.setProperty("Ice.Default.EncodingVersion", "1.0")
id = Ice.InitializationData()
id.properties = props

ice = Ice.initialize(id)
ice.getImplicitContext().put("secret", icesecret)

import Murmur

if (sys.argv[1:]):
  if (sys.argv[1] == "config"):
    print('graph_title Murmur (Port %s)' % (serverport))
    print('graph_vlabel Count')
    print('graph_category mumble')

    if show_users_all:
      print('usersall.label Users (All)')

    if show_users_muted:
      print('usersmuted.label Users (Muted)')

    if show_users_unregistered:
      print('usersunregistered.label Users (Not registered)')

    if show_users_registered:
      print('usersregistered.label Users (Registered)')

    if show_ban_count:
      print('bancount.label Bans on server')

    if show_channel_count:
      print('channelcount.label Channel count/10')

    if show_uptime:
      print('uptime.label Uptime in days')

    ice.destroy()
    sys.exit(0)

try:
  meta = Murmur.MetaPrx.checkedCast(ice.stringToProxy("Meta:tcp -h %s -p %s" % (icehost, iceport)))
except Ice.ConnectionRefusedException:
  print('Could not connect to Murmur via Ice. Please check ')
  ice.destroy()
  sys.exit(1)

try:
  server=meta.getServer(1)
except Murmur.InvalidSecretException:
  print('Given icesecreatread password is wrong.')
  ice.destroy()
  sys.exit(1)

# Initialize
users_all = 0
users_muted = 0
users_unregistered = 0
users_registered = 0
ban_count = 0
channel_count = 0
uptime = 0

# Collect the data...
onlineusers = server.getUsers()

for key in list(onlineusers.keys()):
  if onlineusers[key].userid == -1:
    users_unregistered += 1

  if onlineusers[key].userid > 0:
    users_registered += 1

  if onlineusers[key].mute:
    users_muted += 1

  if onlineusers[key].selfMute:
    users_muted += 1

  if onlineusers[key].suppress:
    users_muted += 1

# Output the date to munin...
if show_users_all:
  print("usersall.value %i" % (len(onlineusers)))

if show_users_muted:
  print("usersmuted.value %i" % (users_muted))

if show_users_registered:
  print("usersregistered.value %i" % (users_registered))

if show_users_unregistered:
  print("usersunregistered.value %i" % (users_unregistered))

if show_ban_count:
  print("bancount.value %i" % (len(server.getBans())))

if show_channel_count:
  print("channelcount.value %.1f" % (len(server.getChannels())/10))

if show_uptime:
  print("uptime.value %.2f" % (float(meta.getUptime())/60/60/24))

ice.destroy()
