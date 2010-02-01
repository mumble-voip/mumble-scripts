#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2009-2010 Stefan Hacker <dd0t@users.sourceforge.net>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:

# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of the Mumble Developers nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# `AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#
# mumbo.py
# 
# MumBo is a python implement of the Mumble VoIP protocol.
# Currently this script is able to connect to a Murmur 1.2.X server and
# interact with it over the TCP control channel. The script currently
# only supports password authentication and does not handle certificates.
# It does not support the voice channel protocol nor is it able to utilize
# the control channel tunneling.
#
# This script is WIP.

import Mumble_pb2 as mprot
import socket, ssl, pprint, struct
from threading import (Thread,
                       Semaphore)
from Queue import Queue, Empty
from time import sleep

from logging import (debug,
                     info,
                     warning,
                     error,
                     critical)
import logging

def fpack(pack):
    return str(type(pack)) + "\n" + str(pack)

mtypes =   [mprot.Version,
            mprot.UDPTunnel,
            mprot.Authenticate,
            mprot.Ping,
            mprot.Reject,
            mprot.ServerSync,
            mprot.ChannelRemove,
            mprot.ChannelState,
            mprot.UserRemove,
            mprot.UserState,
            mprot.BanList,
            mprot.TextMessage,
            mprot.PermissionDenied,
            mprot.ACL,
            mprot.QueryUsers,
            mprot.CryptSetup,
            mprot.ContextActionAdd,
            mprot.ContextAction,
            mprot.UserList,
            mprot.VoiceTarget,
            mprot.PermissionQuery,
            mprot.CodecVersion]

class Keepalive(Thread):
    def __init__(self, shandler, intervall = 5):
        Thread.__init__(self)
        self._intervall = intervall
        self._shandler = shandler
        self.running = True
        
    def run(self):
        cnt = 0
        while self.running:
            if cnt >= self._intervall:
                cnt = 0
                self._shandler.sendPing()
            else:
                cnt = cnt + 0.5
            sleep(0.5)

class Sender(Thread):
    def __init__(self, sock, qin = None):
        Thread.__init__(self)
        self._log = logging.getLogger('Sender')
        self._sock = sock or Queue()
        self._qin = qin
        self.running = True
    
    def run(self):
        log = self._log
        while self.running:
            try:
                self._sock.send(self._qin.get(True, 1))
            except Empty:
                pass
            except Exception, e:
                log.exception(e)
                
    def sendPacket(self, packet):
        self._log.debug(fpack(packet))
        spacket = packet.SerializeToString()
        pre = struct.pack('>Hi', mtypes.index(type(packet)), len(spacket))
        self._qin.put(pre + spacket)
    
    def sendRaw(self, raw):
        self._qin.put(raw)

class ServerHandler(Thread):
    def onVersion(self, packet):
        version = struct.unpack('>HBB', struct.pack('>I', packet.version))
        if self._version[0] != version[0]:
            self._log.critical("Major Client server version mismatch S %s C $s",
                               str(version),
                               str(self._version))
        else:
            self._log.debug("Version match: S %s C %s", str(version), str(self._version))

    def onUDPTunnel(self, data):
        UDPVoiceCELTAlpha, UDPPing, UDPVoiceSpeex, UDPVoiceCELTBeta = range(0,4)
        
        udptype = (struct.unpack('>B', data[0])[0] >> 5) & 0x7
        msgflags = struct.unpack('>B', data[0])[0] & 0x1f
        
        if udptype == UDPVoiceCELTAlpha:
            self._log.log(logging.DEBUG-1, "UDPVoiceCELTAlpha packet")
        elif udptype == UDPPing:
            self._log.log(logging.DEBUG-1, "UDPPing packet")
        elif udptype == UDPVoiceSpeex:
            self._log.log(logging.DEBUG-1, "UDPVoiceSpeex")
        elif udptype == UDPVoiceCELTBeta:
            self._log.log(logging.DEBUG-1, "UDPVoiceCELTBeta")
        else:
            self._log.debug("UDP tunnel packet type unknown (%d)", udptype)
        
        
    def onAuthenticate(self, packet):pass
    def onPing(self, packet): pass
    def onReject(self, packet): pass
    def onServerSync(self, packet):
        self._session = packet.session
        self._log.info("Synced to server in session %d. Welcome text: %s",
                       packet.session,
                       packet.welcome_text)
    
    def onChannelRemove(self, packet):
        c = self._channels
        if not c.has_key(packet.channel_id):
            self._log.error('Received delete for unknown channel (%d)', packet.channel_id)
        else:
            self._log.info('Delete channel "%s" (%d)', c[packet.name], packet.channel_id)
            del c[packet.channel_id]

    def onChannelState(self, packet):
        c = self._channels
        if not packet.channel_id in c:
            self._log.info('New channel "%s" (%d)', packet.name, packet.channel_id)
            c[packet.channel_id] = packet
        else:
            self._log.info('Update channel "%s"', c[packet.channel_id].name)
            c[packet.channel_id].MergeFrom(packet)

    def onUserRemove(self, packet):
        u = self._users
        if not u.has_key(packet.session):
            self._log.error('Received remove for unknown user (%d)', packet.session)
        else:
            self._log.info('Remove user "%s" (%d)', u[packet.session].name, packet.session)
            del u[packet.session]
            
    def onUserState(self, packet):
        u = self._users
        if packet.HasField('session'):
            # Packet refers to someone else
            if not packet.session in u:
                self._log.info('New user "%s" (%d)', packet.name, packet.session)
                u[packet.session] = packet
            else:
                self._log.info('Update user "%s"', u[packet.session].name)
                u[packet.session].MergeFrom(packet)

    def onBanList(self, packet):pass
    
    def onTextMessage(self, packet):
        self._log.info("Text message from %d: %s", packet.actor, packet.message)

    def onPermissionDenied(self, packet):pass
    def onACL(self, packet):pass
    def onQueryUsers(self, packet):pass
    def onCryptSetup(self, packet):pass
    def onContextActionAdd(self, packet):pass
    def onContextAction(self, packet):pass
    def onUserList(self, packet):pass
    def onVoiceTarget(self, packet):pass
    def onPermissionQuery(self, packet): pass
    def onCodecVersion(self, packet): pass
    
    mhandlers = [onVersion,
                onUDPTunnel,
                onAuthenticate,
                onPing,
                onReject,
                onServerSync,
                onChannelRemove,
                onChannelState,
                onUserRemove,
                onUserState,
                onBanList,
                onTextMessage,
                onPermissionDenied,
                onACL,
                onQueryUsers,
                onCryptSetup,
                onContextActionAdd,
                onContextAction,
                onUserList,
                onVoiceTarget,
                onPermissionQuery,
                onCodecVersion]
    
    def __init__(self, addr, release = '', os = '', os_version = '', version = (1,2,0)):
        Thread.__init__(self)
        self._addr = addr
        self.running = True
        self._os = os
        self._os_version = os_version
        self._version = version
        self._release = release
        self.ready = False

    def sendVersion(self, release = '', os = '', os_version = '', version = (1,2,0)):
        self._version = version
        mpv = mprot.Version()
        mpv.release = release
        mpv.os = os
        mpv.os_version = os_version
        mpv.version = struct.unpack('>I', struct.pack('>HBB', *version))[0]
        self.sendPacket(mpv)
        
    def sendAuthenticate(self, username, password = ''):
        mpa = mprot.Authenticate()
        mpa.username = username
        mpa.password = password
        self.sendPacket(mpa)
        
    def sendTextMessage(self, message, target_users = (), target_channels = (), target_trees = ()):
        mpt = mprot.TextMessage()
        
        for u in target_users: mpt.session.append(u)
        for c in target_channels: mpt.channel_id.append(c)
        for t in target_trees: mpt.tree_id.append(t)
        
        mpt.message = message
        self.sendPacket(mpt)
        
    def sendPing(self):
        mpp = mprot.Ping()
        mprot.resync = 0
        self.sendPacket(mpp)
        
    def sendPacket(self, packet):
        self.Sender.sendPacket(packet)
        
    def run(self):
        self._log = logging.getLogger('ServerHandler')
        log = self._log
        self._channels = {}
        self._users = {}
        self._out = Queue()
        self._buffer = ""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ssl_sock = ssl.wrap_socket(s,
                                   ssl_version=ssl.PROTOCOL_TLSv1,
                                   cert_reqs=ssl.CERT_NONE)
        tx = Sender(ssl_sock, self._out)
        ssl_sock.connect(self._addr)
        s.settimeout(1)
        self.Sender = tx
        tx.start()
        self.sendVersion(self._release, self._os, self._os_version, self._version)
        ka = Keepalive(self)
        ka.start()
        self.ready = True
        while self.running:
            try:
                if not self.dispatch():
                    self._buffer = self._buffer + ssl_sock.recv()
            except ssl.SSLError, e:
                # Stupid workaround, todo: use select
                if str(e) != 'The read operation timed out':
                    log.exception(e)
                    self._running = False
            except Exception, e:
                log.exception(e)
                self.running = False
        self.ready = False
        ka.running = False
        tx.running = False
        ka.join()
        tx.join()

    fmtsize = struct.calcsize('>Hi')
    
    def dispatch(self):
        log = self._log
        p = self._buffer
        if len(p) < self.fmtsize:
            #log.debug("NOT ENOUGH DATA FOR HEADER RECEIVED YET (B %d N %d)" % (len(p), self.fmtsize)) 
            return False
        
        msgtype, msglen = struct.unpack('>Hi', p[:self.fmtsize])
        
        if msgtype < 0 or msgtype >= len(mtypes):
            log.warning('Received packet of unknown type (T %d L %d B %d)' % (msgtype, msglen, len(p)))
            self._buffer = p[msglen+self.fmtsize:]
            return True
        
        log.log(logging.DEBUG-1, "HEADER: T %s (%d) L %d B %d" % (str(mtypes[msgtype]),msgtype, msglen, len(p)))
        if len(p) < (msglen + self.fmtsize):
            log.debug("NOT ENOUGH DATA RECEIVED YET (B %d N %d)" % (len(p), msglen + self.fmtsize)) 
            return False
        

        try:
            if msgtype == mtypes.index(mprot.UDPTunnel):
                self.mhandlers[msgtype](self, p[self.fmtsize+1:msglen+self.fmtsize])
            else:
                inst = mtypes[msgtype]()
                inst.ParseFromString(p[self.fmtsize:msglen+self.fmtsize])
                log.debug(fpack(inst))
                self.mhandlers[msgtype](self, inst)
        except Exception, e:
            log.exception(e)
        finally:
            self._buffer = p[msglen+self.fmtsize:]
        return True

if __name__ == "__main__":
    logging.basicConfig(level = logging.DEBUG)
    sh = ServerHandler(('localhost', 64738))
    info("Run")
    sh.start()
    while not sh.ready: pass
    sh.sendAuthenticate("BerndTheBot")
    # Send a text message to the root channel
    sleep(1)
    sh.sendTextMessage("Hello World", target_trees = (0,))
    raw_input("Press enter to close\n")
    sh.running = False

    sh.join()
    
    info("Done")
    
            