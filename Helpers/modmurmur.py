#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2010 Stefan Hacker <dd0t@users.sourceforge.net>
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
#    modmurmur.py -  Small wrapper for connecting to Murmur servers of different
#                    versions while offering access to the underlying raw functionality
#
#    Requirements:
#        * python >=2.6 and the following python modules:
#            * ice-python
#
import os
import sys
import Ice
import IcePy
import tempfile
from logging import (getLogger, basicConfig, DEBUG)

#basicConfig(level = DEBUG)

class MurmurServer(object):
    __slices = {}
    
    def __init__(self, compat_slices = 'legacy_slices/'):
        self.__legacy_slices = compat_slices
        self.__ice = None
        self.__prx = None
        self.Murmur = None
        self.__meta = None
        self.__log = getLogger(__name__ + "." + type(self).__name__)
        self.__version = None
        self.__mappings = []
        
    def connect(self, host = "127.0.0.1", port = 6502, secret = None, prxstr = None):
        if self.__ice:
            self.__log.warning("Connection attempt with tainted object, disconnect first")
            return True
        
        if not prxstr:
            prxstr = "Meta:tcp -h %s -p %d -t 1000" % (host, port)
        
        self.__log.info("Connecting to proxy: %s", prxstr)
            
        props = Ice.createProperties(sys.argv)
        props.setProperty("Ice.ImplicitContext", "Shared")
        
        idata = Ice.InitializationData()
        idata.properties = props
        
        ice = Ice.initialize(idata)
        self.__ice = ice

        if secret:
            ice.getImplicitContext().put("secret", secret)
            
        prx = ice.stringToProxy(prxstr)
        self.__prx = prx
        
        self.__log.debug("Retrieve version from target host")
        try:
            version = IcePy.Operation('getVersion', Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent, True, (), (), (((), IcePy._t_int), ((), IcePy._t_int), ((), IcePy._t_int), ((), IcePy._t_string)), None, ()).invoke(prx, ((), None))
            major, minor, patch, text = version
            self.__log.debug("Server version is %s", str(version))
        except Exception, e:
            self.__log.critical("Failed to retrieve version from target host")
            self.__log.exception(e)
            return False
        
        # Find out what slicefile we need
        slicefile = None
        if major == 1:
            if minor <= 0:
                # We don't support 0.X.X
                critical("Server version not supported: %s", version)
                return False
            elif minor == 1:
                # Use 1.1.8 slice for all 1.1.X versions
                self.__log.debug("Using 1.1.8 legacy slice for server with version %s", version)
                slicefile = "Murmur118.ice"
            elif minor == 2:
                # For 1.2.X we have three legacy slices
                if patch == 0:
                    self.__log.debug("Using 1.2.0 legacy slice for server with version %s", version)
                    slicefile = "Murmur120.ice"
                elif patch == 1:
                    self.__log.debug("Using 1.2.1 legacy slice for server with version %s", version)
                    slicefile = "Murmur121.ice"
                elif patch == 2:
                    self.__log.debug("Using 1.2.2 legacy slice for server with version %s", version)
                    slicefile = "Murmur122.ice"
                    
        if slicefile:
            # Load the legacy slice into memory
            try:
                self.__log.debug("Load legacy slice from %s", self.__legacy_slices + slicefile)
                slice = open(self.__legacy_slices + slicefile, "r").read()
            except Exception, e:
                self.__log.critical("Failed to load legacy slice from %s", self.__legacy_slices + slicefile)
                self.__log.exception(e)
                return False
        else:
            # Seems like this is version 1.2.3 or greater, dynload the slice file
            self.__log.debug("Retrieve slicefile from target host")
            
            try:
                slice = IcePy.Operation('getSlice', Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent, True, (), (), (), IcePy._t_string, ()).invoke(prx, ((), None))
            except Exception, e:
                self.__log.critical("Failed to retrieve slicefile from target host")
                self.__log.exception(e)
                return False
        
        try:
            # Try to get the loaded module for this slice from our cache
            self.Murmur = self.__slices[slice]
            self.__log.debug("Slice cache hit, reusing loaded module")
        except KeyError:
            # We do not have the module for this specific slice imported yet
            # so do it now
            self.__log.debug("Slice cache miss, generating new module (%s)", '[["python:package:Murmur%d"]]\n' % len(self.__slices))
            (dynslicefiledesc, dynslicefilepath)  = tempfile.mkstemp(suffix = '.ice')
            dynslicefile = os.fdopen(dynslicefiledesc, 'w')
            dynslicefile.write('[["python:package:Murmur%d"]]\n' % len(self.__slices) + slice)
            dynslicefile.flush()
            
            try:
                if Ice.getSliceDir():
                    Ice.loadSlice('', ['-I' + Ice.getSliceDir(), dynslicefilepath])
                else:
                    self.__log.warning("Ice.getSliceDir() return None, consider updating Ice as this might break with recent servers")
                    Ice.loadSlice('', [dynslicefilepath])
            except Exception, e:
                self.__log.critical("Failed to dynload slice")
                self.__log.exception(e)
                return False
            finally:
                # Make sure we clean up after ourselves
                dynslicefile.close()
                os.remove(dynslicefilepath)
            
            self.__log.debug("Loading new module")
            try:
                self.Murmur = __import__("Murmur%d" % len(self.__slices)).Murmur
                self.__slices[slice] = self.Murmur
            except ImportError, e:
                self.__log.critical("Failed to load dynamically generated module")
                self.__log.exception(e)
                return False
        
        # Get the meta object for the server
        try:
            self.__meta = self.Murmur.MetaPrx.checkedCast(self.__prx)
            self.__meta.getServer(0) # Triggers an invalid secret exception if secret is invalid
        except self.Murmur.InvalidSecretException:
            self.__log.critical("Invalid secret")
            return False
        except Exception, e:
            self.__log.critical("Could not cast meta object, connecting failed")
            self.__log.exception(e)
            return False
        
        self.__log.debug("Map meta into self")
        for name in dir(self.__meta):
            if not name.startswith("_"):
                if hasattr(self, name):
                    self.__log.warning("Function '%s' of metaclass shadowed by '%s'", name, type(self).__name__)
                else:
                    self.__mappings.append(name)
                    setattr(self, name, getattr(self.__meta, name))
                    
        self.__log.info("Server module connected and ready for use")
        return True
        
    def disconnect(self):
        self.__version = None
        self.__prx = None
        self.__meta = None
        
        if self.__mappings: self.__log.debug("Undoing mapping")
        for m in self.__mappings:
            delattr(self, m)
        self.__mappings = []
            
        if self.__ice:
            self.__log.debug("Disconnecting")
            try:
                self.__ice.destroy()
            except Exception, e:
                self.__log.exception(e)
            
            self.__ice = None
            self.__log.info("Disconnected")
            
    def __del__(self):
        self.disconnect()