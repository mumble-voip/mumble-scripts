#!/usr/bin/env python3
# -*- coding: utf-8
#
# Copyright (C) 2022 Jan Klass <kissaki@posteo.de>
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
# - Neither the name of the Mumble Developers nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.
#
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

from datetime import datetime
import time
import logging
import os
import sys
import tempfile

try:
    import Ice
    import IcePy
except ImportError:
    print('ERROR: The python modules Ice and IcePy are required to run Mumo. Install with sudo apt-get install python-zeroc-ice or python -m pip install zeroc-ice', file=sys.stdout)
    sys.exit(1)

def ice_init():
    logging.debug('Initializing Ice...')
    initdata = Ice.InitializationData()
    initdata.properties = Ice.createProperties([], initdata.properties)
    initdata.properties.setProperty('Ice.ThreadPool.Server.Size', '5')
    initdata.properties.setProperty('Ice.ImplicitContext', 'Shared')
    initdata.properties.setProperty('Ice.Default.EncodingVersion', '1.0')

    ice = Ice.initialize(initdata)
    return ice

def dynload_slice(prx):
    logging.info("Loading slice from server...")
    try:
        # Check IcePy version as this internal function changes between version.
        # In case it breaks with future versions use slice2py and search for "IcePy.Operation('getSlice'," for updates in the generated bindings.
        if IcePy.intVersion() < 30500:
            raise Exception('Ice < 3.5 not supported')

        op = IcePy.Operation('getSlice', Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent, True, None, (), (), (), ((), IcePy._t_string, False, 0), ())

        slice = op.invoke(prx, ((), None))
        return slice
    except Exception as e:
        logging.error("Retrieving slice from server failed")
        logging.exception(e)
        raise

def tmpWriteLoad_slice(slice):
        (dynslicefiledesc, dynslicefilepath) = tempfile.mkstemp(suffix='.ice')
        dynslicefile = os.fdopen(dynslicefiledesc, 'w')
        dynslicefile.write(slice)
        dynslicefile.flush()
        load_slice(dynslicefilepath)
        dynslicefile.close()
        os.remove(dynslicefilepath)

def load_slice(slice_fpath):
    slicedir = Ice.getSliceDir()
    Ice.loadSlice('', ['-I' + slicedir, slice_fpath])

host = '127.0.0.1'
port = 6502
watchdog = 15
icesecret = ''
callback_port = -1
callback_host = '127.0.0.1'
metaProxyString = 'Meta:tcp -h %s -p %d' % (host, port)
vServerIdWhitelist = []
logfpath = 'usertextmessage.log'
printMsg = False

if __name__ == '__main__':
    with ice_init() as communicator:
        metaProxyAnon = communicator.stringToProxy(metaProxyString)
        slice = dynload_slice(metaProxyAnon)
        tmpWriteLoad_slice(slice)

        callbackClient = communicator.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s' % host)
        callbackClient.activate()

        # noinspection PyUnresolvedReferences
        import Murmur

        class ServerCallbackClass(Murmur.ServerCallback):
            def userConnected(self, user, icepy): return
            def userDisconnected(self, user, icepy): return
            def userStateChanged(self, user, icepy): return
            def channelCreated(self, user, icepy): return
            def channelRemoved(self, user, icepy): return
            def channelStateChanged(self, user, icepy): return

            def userTextMessage(self, user, message, icepy):
                ts = time.time()
                utc_time = datetime.fromtimestamp(ts)
                timestamp = utc_time.strftime('%Y-%m-%d %H:%M:%S')

                logMsg = '[{}][{}:{}:{}][{}:{}:{}] {}\n'.format(
                      timestamp
                    , user.session, user.userid, user.name
                    , str.join(',', list(map(str, message.sessions))), str.join(',', list(map(str, message.channels))), str.join(',', list(map(str, message.trees)))
                    , message.text)
                if printMsg: print(logMsg)
                with open(logfpath, 'a') as logfile:
                    logfile.write(logMsg)

        serverCallbackProxy = callbackClient.addWithUUID(ServerCallbackClass())
        serverCallback = Murmur.ServerCallbackPrx.checkedCast(serverCallbackProxy)

        metaProxy = Murmur.MetaPrx.checkedCast(metaProxyAnon)

        servers = metaProxy.getBootedServers()
        for server in servers:
            if vServerIdWhitelist and server.id() in vServerIdWhitelist: continue

            logging.info('Setting up for virtual server %d' % server.id())
            server.addCallback(serverCallback)

        print('RUNNING')
        print('Exit with enter')
        input()
        print('END')
    sys.exit(0)
