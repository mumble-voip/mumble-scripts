#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2010 Stefan Hacker <dd0t@users.sourceforge.net>
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
#

#    mumo.py
#
# mumo, the Mumble moderator script can perform a range of common
# tasks on a Mumble server. It connects to Murmur using Ice.
#
# The script can currently perform the following tasks:
#   * Auto mute inactive players and move them to an afk channel
#

import sys
import Ice
import thread
import logging
import ConfigParser
import time

from logging    import (debug,
                        info,
                        warning,
                        error,
                        critical,
                        getLogger)
from optparse   import OptionParser

def x2bool(s):
    """Helper function to convert strings from the config to bool"""
    if isinstance(s, bool):
        return s
    elif isinstance(s, basestring):
        return s.lower() in ['1', 'true']
    raise ValueError()

#
#--- Default configuration values
#
cfgfile = 'mumo.ini'
default = {'autoaway':(('interval', int, 0),
                       ('timeout', int, 3600),
                       ('mute', x2bool, True),
                       ('deafen', x2bool, False),
                       ('channel', int, -1)),
            'onjoin':(('movetochannel', int, -1),),
            
            'murmur':(('server', int, 1),),
           
            'ice':(('host', str, '127.0.0.1'),
                   ('port', int, 6502),
                   ('slice', str, 'Murmur.ice')),
    
            'iceraw':None,

            'glacier':(('enabled', x2bool, False),
                       ('user', str, 'mumo'),
                       ('password', str, 'secret'),
                       ('host', str, 'localhost'),
                       ('port', int, '4063')),
                       
            'log':(('level', int, logging.DEBUG),
                   ('file', str, 'mumo.log'))}
 
#
#--- Helper classes
#
class config(object):
    """
    Small abstraction for config loading
    """

    def __init__(self, filename = None, default = None):
        if not filename or not default: return
        cfg = ConfigParser.ConfigParser()
        cfg.optionxform = str
        cfg.read(filename)
        
        for h,v in default.iteritems():
            if not v:
                # Output this whole section as a list of raw key/value tuples
                try:
                    self.__dict__[h] = cfg.items(h)
                except ConfigParser.NoSectionError:
                    self.__dict__[h] = []
            else:
                self.__dict__[h] = config()
                for name, conv, vdefault in v:
                    try:
                        self.__dict__[h].__dict__[name] = conv(cfg.get(h, name))
                    except (ValueError, ConfigParser.NoSectionError, ConfigParser.NoOptionError):
                        self.__dict__[h].__dict__[name] = vdefault

def do_main_program():
    #
    #--- Callback implementation
    #    All of this has to go in here so we can correctly daemonize the tool
    #    without loosing the file descriptors opened by the Ice module
    Ice.loadSlice(cfg.ice.slice)
    import Murmur
    
    def UpdateUserAutoAway(server, user, index):
        if cfg.autoaway.interval <= 0: return
        
        update = False
        if not user in index and user.idlesecs > cfg.autoaway.timeout:
            if cfg.autoaway.deafen \
                and not (user.suppress or user.selfMute or user.mute) \
                and not (user.selfDeaf or user.deaf):
                info('autoaway: Mute and deafen user %s (%d / %d)', user.name, user.session, user.userid)
                user.deaf = True
                update = True
            elif cfg.autoaway.mute and not (user.suppress or user.selfMute or user.mute):
                info('autoaway: Mute user %s (%d / %d)', user.name, user.session, user.userid)
                user.mute = True
                update = True
            
            if cfg.autoaway.channel >= 0 and user.channel != cfg.autoaway.channel:
                info('autoaway: Move user %s (%d / %d)', user.name, user.session, user.userid)
                user.channel = cfg.autoaway.channel
                update = True
                
            if update:
                index.add(user.session)
                
        elif user.session in index and user.idlesecs < cfg.autoaway.timeout:
            index.remove(user.session)
            if cfg.autoaway.deafen:
                info('autoaway: Unmute and undeafen user %s (%d / %d)', user.name, user.session, user.userid)
                user.mute = False
                user.deafen = False
                update = True
            elif cfg.autoaway.mute:
                info('autoaway: Unmute user %s (%d / %d)', user.name, user.session, user.userid)
                user.mute = False
                update = True
        
        if update:
            server.setState(user)
                    
    class mumoApp(Ice.Application):
        def run(self, args):
            self.shutdownOnInterrupt()
            
            self.index = set()
            
            if not self.initializeIceConnection():
                return 1
            
            # Figure out what our polling interval will be
            interval = cfg.autoaway.interval
            
            if interval != 0:
                # If we have polling tasks perform them
                while True:
                    self.handleAutoAway()
                    time.sleep(interval)
                    
            else:
                # Serve till we are stopped
                self.communicator().waitForShutdown()
            
            if self.interrupted():
                warning('Caught interrupt, shutting down')

            return 0
        
        def handleAutoAway(self):
            meta = self.meta
            server = meta.getServer(cfg.murmur.server)
            if server:
                for user in server.getUsers().itervalues():
                        UpdateUserAutoAway(server, user, self.index)
                            
                                 
        def initializeIceConnection(self):
            """
            Establishes the two-way Ice connection and adds the callback to the
            configured servers
            """
            ice = self.communicator()
            
            if cfg.glacier.enabled:
                #info('Connecting to Glacier2 server (%s:%d)', glacier_host, glacier_port)
                error('Glacier support not implemented yet')
                #TODO: Implement this
    
            info('Connecting to Ice server (%s:%d)', cfg.ice.host, cfg.ice.port)
            base = ice.stringToProxy('Meta:tcp -h %s -p %d' % (cfg.ice.host, cfg.ice.port))
            try:
                meta = Murmur.MetaPrx.checkedCast(base)
            except Ice.LocalException, e:
                error('Could not connect to Ice server, error %d: %s', e.error, str(e).replace('\n', ' '))
                return False
            
            adapter = ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s' % cfg.ice.host)
            adapter.activate()
        
            server = meta.getServer(cfg.murmur.server)
            if server:
                info('Setting callback for server %d', server.id())
                callbackprx = adapter.addWithUUID(ServerCallback(server, self.index,  adapter))
                callback = Murmur.ServerCallbackPrx.uncheckedCast(callbackprx)
                server.addCallback(callback)
                    
            self.meta = meta
            return True
        
    class ServerCallback(Murmur.ServerCallback):
        def __init__(self, server, index, adapter):
            Murmur.ServerCallback.__init__(self)
            self.index = index
            self.server = server
        
        def userStateChanged(self, u, current=None):
            UpdateUserAutoAway(self.server, u, self.index)
        
        def userDisconnected(self, u, current=None):
            if u.session in self.index:
                self.index.remove(u.session)
                
        def userConnected(self, u, current=None):
            if cfg.onjoin.movetochannel >= 0:
                info('onjoin: Moving user %s (%d / %d)', u.name, u.session, u.userid)
                u.channel = cfg.onjoin.movetochannel
                self.server.setState(u)
                
        def channelCreated(self, c, current=None): pass # Unused callback
        def channelRemoved(self, c, current=None): pass
        def channelStateChanged(self, c, current=None): pass
        
    class CustomLogger(Ice.Logger):
        """
        Logger implementation to pipe Ice log messages into
        out own log
        """
        
        def __init__(self):
            Ice.Logger.__init__(self)
            self._log = getLogger("Ice")
            
        def _print(self, message):
            self._log.info(message)
            
        def trace(self, category, message):
            self._log.debug("Trace %s: %s", category, message)
            
        def warning(self, message):
            self._log.warning(message)
            
        def error(self, message):
            self._log.error(message)

    #
    #--- Start of authenticator
    #
    info('Starting mumble moderator script')
    initdata = Ice.InitializationData()
    initdata.properties = Ice.createProperties([], initdata.properties)
    for prop, val in cfg.iceraw:
        initdata.properties.setProperty(prop, val)
    initdata.logger = CustomLogger()
    
    app = mumoApp()
    state = app.main(sys.argv[:1], initData = initdata)
    info('Shutdown complete')

#
#--- Start of program
#
if __name__ == '__main__':
    # Parse commandline options
    parser = OptionParser()
    parser.add_option('-i', '--ini',
                      help = 'load configuration from INI', default = cfgfile)
    parser.add_option('-v', '--verbose', action='store_true', dest = 'verbose',
                      help = 'verbose output [default]', default = True)
    parser.add_option('-q', '--quiet', action='store_false', dest = 'verbose',
                      help = 'only error output')
    parser.add_option('-d', '--daemon', action='store_true', dest = 'force_daemon',
                      help = 'run as daemon', default = False)
    parser.add_option('-a', '--app', action='store_true', dest = 'force_app',
                      help = 'do not run as daemon', default = False)
    (option, args) = parser.parse_args()
    
    if option.force_daemon and option.force_app:
        parser.print_help()
        sys.exit(1)
        
    # Load configuration
    try:
        cfg = config(option.ini, default)
    except Exception, e:
        print>>sys.stderr, 'Fatal error, could not load config file from "%s"' % cfgfile
        sys.exit(1)
    
    # Initialize logger
    if cfg.log.file:
        try:
            logfile = open(cfg.log.file, 'a')
        except IOError, e:
            print>>sys.stderr, 'Fatal error, could not open logfile "%s"' % cfg.log.file
            sys.exit(1)
    else:
        logfile = logging.sys.stderr
        
            
    if option.verbose:
        level = cfg.log.level
    else:
        level = logging.ERROR
    
    logging.basicConfig(level = level,
                        format='%(asctime)s %(levelname)s %(message)s',
                        stream = logfile)
        
    # As the default try to run as daemon. Silently degrade to running as a normal application if this fails
    # unless the user explicitly defined what he expected with the -a / -d parameter. 
    try:
        if option.force_app:
            raise ImportError # Pretend that we couldn't import the daemon lib
        import daemon
    except ImportError:
        if option.force_daemon:
            print>>sys.stderr, 'Fatal error, could not daemonize process due to missing "daemon" library, ' \
            'please install the missing dependency and restart the script'
            sys.exit(1)
        do_main_program()
    else:
        context = daemon.DaemonContext(working_directory = sys.path[0],
                                       stderr = logfile)
        context.__enter__()
        try:
            do_main_program()
        finally:
            context.__exit__(None, None, None)
