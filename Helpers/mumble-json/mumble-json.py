#!/usr/bin/python

# Copyright (C) 2020-2024 Tobias Fernandez (github@tobias-fernandez.de)
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of The Mumble Developers nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE FOUNDATION OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# For questions and inquiries about Mumble's license,
# please contact <license@mumble.info>.

#
# mumble-json.py
#
#   A simple Python script to provide Mumble Viewer Protocol (JSON) by querying a local murmur instance via ZeroC ICE
#   This script can become handy if you just want to connect a JSON capable viewer to your murmur instance.
#

# The server name to display
SERVER_NAME = "My Server"

# edit this to query another server id
SERVER_ID = 1

# provide correct location of slice here
SLICE = '/usr/share/slice/Murmur.ice'

# The port of the ICE connection
ICE_PORT = 6502

##################################################################################
# DO NOT EDIT BEYOND THIS LINE !!! 
##################################################################################

import Ice
import sys

Ice.loadSlice( "", ["-I" + Ice.getSliceDir(), SLICE])
import Murmur

# Init ice
comm = Ice.initialize()
# Let Ice know where to go to connect to mumble
proxy = comm.stringToProxy('Meta -e 1.0:tcp -p ' + str(ICE_PORT))
# Create a dynamic object that allows us to get a programmable interface for Mumble
meta = Murmur.MetaPrx.checkedCast(proxy)

##################################################################################
# Query the Mumble server 
##################################################################################

# Get the server instance from the set of servers.
server = meta.getServer(SERVER_ID)

channelMap = server.getChannels()
userMap = server.getUsers()

##################################################################################
# Init maps for easier lookup 
##################################################################################

channelChildrenMap = dict()
for key, channel in channelMap.iteritems():
    if channel.parent in channelChildrenMap:
        channelChildrenMap[channel.parent].append(channel)
    else:
        channelChildrenMap[channel.parent] = [ channel ] 

usersInChannelMap = dict()
for key, user in userMap.iteritems():
    if user.channel in usersInChannelMap:
        usersInChannelMap[user.channel].append(user)
    else:
        usersInChannelMap[user.channel] = [ user ]

##################################################################################
# Procedure definitions
##################################################################################

# Sanitize a String by escapting double quotes and newline characters.
# s: the String to sanitize
def sanitize(s):
    return s.replace('"', '\\"').replace('\n', '\\n')

# Get the links of a channel as a comma separated string.
# channel: the channel to get links for
def getChannelLinks(channel):
    links=''
    for link in channel.links:
        if links != '':
            links = links + ',' 
        links = links + str(link)
    return links

# Print User information.
# user: the user to print information for
# tab: the preceeding tab string
def printUser(user, tab):
    print tab + '"channel": ' + str(user.channel) + ','
    print tab + '"deaf": ' + str(user.deaf).lower() + ','
    print tab + '"mute": ' + str(user.mute).lower() + ','
    print tab + '"name": "' + sanitize(user.name) + '",'
    print tab + '"selfDeaf": ' + str(user.selfDeaf).lower() + ','
    print tab + '"selfMute": ' + str(user.selfMute).lower() + ','
    print tab + '"session": ' + str(user.session) + ','
    print tab + '"suppress": ' + str(user.suppress).lower() + ','
    print tab + '"userid": ' + str(user.userid) + ','
    print tab + '"recording": ' + str(user.recording).lower() + ','
    print tab + '"prioritySpeaker": ' + str(user.prioritySpeaker).lower() + ','
    print tab + '"comment": "' + sanitize(user.comment) + '"'

# Print the users that are in a certain channel.
# channel: the channel to print users for
# tab: the preceeding tab string
def printChannelUsers(channel, tab):
    print tab + '"users": ['
    first = True

    if channel.id in usersInChannelMap:
        for user in usersInChannelMap[channel.id]:
            if first:
                print tab + '{'
                first = False
            else:
                print tab + ',{'
            printUser(user, tab + '\t')
            print tab + '}'
    print tab + '],'

# Print the children of a channel.
# A child is channel, that has the given channel.id as parent.
# channel: the channel to print children for
# tab: the preceeding tab string
def printChannelChildren(channel, tab):
    print tab + '"channels": ['
    first = True

    if channel.id in channelChildrenMap:
        for child in channelChildrenMap[channel.id]:
            if first:
                print tab + '{'
                first = False
            else:
                print tab + ',{'
            printChannel(child, tab + '\t')
            print tab +  '}'
    print tab + ']'

# Print a channel information.
# channel: the channel to print information for
# tab: the preceeding tab string
def printChannel(channel, tab):
    print tab + '"name": "' + sanitize(channel.name) + '",'
    print tab + '"id": ' + str(channel.id) + ','
    print tab + '"description": "' + sanitize(channel.description) + '",'
    #print tab + '"description": "",'
    print tab + '"links": [' + getChannelLinks(channel) + '],'
    print tab + '"parent": ' + str(channel.parent) + ','
    print tab + '"position": ' + str(channel.position) + ','
    print tab + '"temporary": ' + str(channel.temporary).lower() +","

    printChannelUsers(channel, tab )
    printChannelChildren(channel, tab )

# Print information of the whole server.
# Server information includes channels and all users.
def printServer():
    tab = '\t'
    print '{'
    print tab + '"id": ' + str(SERVER_ID) + ','
    print tab + '"name": "' + SERVER_NAME + '",'
    print tab + '"root": '
    first = True
    rootId = -1

    if rootId in channelChildrenMap:
        for channel in channelChildrenMap[rootId]:
            if first:
                print tab + '{'
                first = False
            else:
                print tab + ',{'
            printChannel(channel, tab + '\t')
            print tab + '}'
    else:
        print '{}'

    print '}'

##################################################################################
# Print JSON to stdout 
##################################################################################

print 'Content-Type: text/plain'
print
printServer()

##################################################################################
# Close Ice communication 
##################################################################################

if comm:
    comm.destroy()
