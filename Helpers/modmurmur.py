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
    __mm_slices = {}
    
    def __init__(self):
        self.__mm_ice = None
        self.__mm_prx = None
        self.__mm_murmur = None
        self.__mm_meta = None
        self.__mm_log = getLogger(__name__ + "." + type(self).__name__)
        self.__mm_version = None
        self.__mm_mappings = []
        
    def connect(self, host = "127.0.0.1", port = 6502, secret = None, prxstr = None):
        if self.__mm_ice:
            self.__mm_log.warning("Connection attempt while already connected, disconnect first")
            return True
        
        if not prxstr:
            prxstr = "Meta:tcp -h %s -p %d -t 1000" % (host, port)
        
        self.__mm_log.info("Connecting to proxy: %s", prxstr)
            
        props = Ice.createProperties(sys.argv)
        props.setProperty("Ice.ImplicitContext", "Shared")
        
        idata = Ice.InitializationData()
        idata.properties = props
        
        ice = Ice.initialize(idata)
        self.__mm_ice = ice

        if secret:
            __mm_ice.getImplicitContext().put("secret", secret)
            
        prx = ice.stringToProxy(prxstr)
        self.__mm_prx = prx
        
        self.__mm_log.debug("Retrieve slicefile from target host")
        
        # Dynamically retrieve our slicefile
        try:
            slice = IcePy.Operation('getSlice', Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent, True, (), (), (), IcePy._t_string, ()).invoke(prx, ((), None))
        except Exception, e:
            self.__mm_log.critical("Failed to retrieve slicefile from target host")
            self.__mm_log.exception(e)
            return False
        
        try:
            # Try to get the loaded module for this slice from our cache
            self.__mm_murmur = self.__mm_slices[slice]
            self.__mm_log.debug("Slice cache hit, reusing loaded module")
        except KeyError:
            # We do not have the module for this specific slice imported yet
            # so do it now
            self.__mm_log.debug("Slice cache miss, generating new module (%s)", '[["python:package:Murmur%d"]]\n' % len(self.__mm_slices))
            (dynslicefiledesc, dynslicefilepath)  = tempfile.mkstemp(suffix = '.ice')
            dynslicefile = os.fdopen(dynslicefiledesc, 'w')
            dynslicefile.write('[["python:package:Murmur%d"]]\n' % len(self.__mm_slices) + slice)
            dynslicefile.flush()
            
            try:
                if Ice.getSliceDir():
                    Ice.loadSlice('', ['-I' + Ice.getSliceDir(), dynslicefilepath])
                else:
                    self.__mm_log.warning("Ice.getSliceDir() return None, consider updating Ice as this might break with recent servers")
                    Ice.loadSlice('', [dynslicefilepath])
            except Exception, e:
                self.__mm_log.critical("Failed to dynload slice")
                self.__mm_log.exception(e)
                return False
            finally:
                # Make sure we clean up after ourselves
                dynslicefile.close()
                os.remove(dynslicefilepath)
            
            self.__mm_log.debug("Loading new module")
            try:
                self.__mm_murmur = __import__("Murmur%d" % len(self.__mm_slices)).Murmur
                self.__mm_slices[slice] = self.__mm_murmur
            except ImportError, e:
                self.__mm_log.critical("Failed to load dynamically generated module")
                self.__mm_log.exception(e)
                return False
        
        # Get the meta object for the server
        self.__mm_meta = self.__mm_murmur.MetaPrx.uncheckedCast(self.__mm_prx)
        
        self.__mm_log.debug("Map meta into self")
        for name in dir(self.__mm_meta):
            if not name.startswith("_"):
                if hasattr(self, name):
                    self.__mm_log.warning("Function '%s' of metaclass shadowed by '%s'", name, type(self).__name__)
                else:
                    self.__mm_mappings.append(name)
                    setattr(self, name, getattr(self.__mm_meta, name))
                    
        self.__mm_log.info("Server module connected and ready for use")
        return True
        
    def disconnect(self):
        self.__mm_version = None
        self.__mm_prx = None
        self.__mm_meta = None
        
        if self.__mm_mappings: self.__mm_log.debug("Undoing mapping")
        for m in self.__mm_mappings:
            delattr(self, m)
        self.__mm_mappings = []
            
        if self.__mm_ice:
            self.__mm_log.debug("Disconnecting")
            try:
                self.__mm_ice.destroy()
            except Exception, e:
                self.__mm_log.exception(e)
            
            self.__mm_ice = None
            self.__mm_log.info("Disconnected")
            
    def __del__(self):
        self.disconnect()