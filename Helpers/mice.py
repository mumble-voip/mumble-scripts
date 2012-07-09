#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2008 Stefan Hacker <dd0t@users.sourceforge.net>
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
#    mice.py - Minimal script to interact with murmurs' ice
#              interface, use 'python -i' or a tool like idle
#              to run this script either directly or via 'import mice'.
#              Be sure a Murmur.ice file is placed in the same dir and
#              murmur is running in the default ice configuration.
#

import os
import sys
import tempfile

try:
    from config import host, port, prxstr, slicefile, secret
except ImportError:
    print "Using default settings."

    # Default settings
    host = "127.0.0.1"
    port = 6502
    prxstr = "Meta:tcp -h %s -p %d -t 1000" % (host, port)
    slicefile = "Murmur.ice"
    secret = ''

print "Import ice...",
import Ice
import IcePy

props = Ice.createProperties(sys.argv)
props.setProperty("Ice.ImplicitContext", "Shared")
idata = Ice.InitializationData()
idata.properties = props

ice = Ice.initialize(idata)
prx = ice.stringToProxy(prxstr)
print "Done"

try:
    print "Trying to retrieve slice dynamically from server...",
    slice = IcePy.Operation('getSlice', Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent, True, (), (), (), IcePy._t_string, ()).invoke(prx, ((), None))

    (dynslicefiledesc, dynslicefilepath)  = tempfile.mkstemp(suffix = '.ice')
    dynslicefile = os.fdopen(dynslicefiledesc, 'w')
    dynslicefile.write(slice)
    dynslicefile.flush()
    Ice.loadSlice('', ['-I' + Ice.getSliceDir(), dynslicefilepath])
    dynslicefile.close()
    os.remove(dynslicefilepath)
    print "Success"
except Exception, e:
    print "Failed"
    print str(e)
    while not os.path.exists(slicefile):
         slicefile = raw_input("Path to slicefile: ")
    print "Load slice (%s)..." % slicefile,
    Ice.loadSlice('', ['-I' + Ice.getSliceDir(), slicefile])
    print "Done"
	
print "Import dynamically compiled murmur class...",
import Murmur
print "Done"
print "Establish ice connection...",

if secret:
    print "[protected]...",
    ice.getImplicitContext().put("secret", secret)

murmur = Murmur.MetaPrx.checkedCast(prx)
m = murmur
print "Done"

print "Creating callback stuff...",
adapter = ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s -t 1000' % host)
adapter.activate()

class MetaCallback(Murmur.MetaCallback):
    def __init__(self):
        Murmur.MetaCallback.__init__(self)
    
    def started(self, server, current = None):
        print "Server %d started" % server.id()
    
    def stopped(self, server, current = None):
        try:
            print "Server %d stopped" % server.id()
        except Ice.ConnectionRefusedException:
            print "A server got stopped, getting its ID failed. Murmur shutdown?"

metaCallbackI = MetaCallback()
metaCallbackProxy = adapter.addWithUUID(metaCallbackI)
metaCallback = Murmur.MetaCallbackPrx.uncheckedCast(metaCallbackProxy)

try:
    murmur.addCallback(metaCallback)
except Murmur.InvalidSecretException:
    print "Failed (wrong secret)"
    print "Please edit mice.py to set the valid secret"
else:
    print "Done"

if __name__ != "__main__":
	prefix = __name__ + "."
else:
	prefix = ""
	
print "Murmur object accessible via '%smurmur' or '%sm'" % (prefix,
                                                              prefix)

try:
    sl = m.getBootedServers()
except Murmur.InvalidSecretException:
    print "Error: Invalid ice secret. Mice won't work."
else:
    s = sl[0] if sl else None
    print "%d booted servers in '%ssl', '%ss' contains '%s'" % (len(sl), prefix, prefix, repr(s))
    print "--- Reached interactive mode ---"


