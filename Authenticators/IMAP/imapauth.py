#!/usr/bin/env python3
# -*- coding: utf-8

# Based on work "smfauth" which is Copyright (C) 2010 Stefan Hacker <dd0t@users.sourceforge.net> 
# https://raw.githubusercontent.com/mumble-voip/mumble-scripts/master/Authenticators/SMF/2.0/smfauth.py
# 
# Auth for IMAP and python3 compatibility by dadosch, 2018
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
#    imapauth.py - Authenticator implementation for password authenticating
#                 a Murmur server against an IMAP server
#
#    Requirements:
#        * python >=3 and the following python modules:
#            * ice-python
#            * IMAPClient
#            * daemon (when run as a daemon)
#

import sys
import Ice
import _thread
import logging
import configparser

from threading  import Timer
from optparse   import OptionParser
from logging    import (debug,
                        info,
                        warning,
                        error,
                        critical,
                        exception,
                        getLogger)


import hashlib
import ssl
from imapclient import IMAPClient

ssl_context = ssl.create_default_context()

def hashString(s):
    """Helper function to convert strings to a fixed integer"""
    result = 0
    hash = hashlib.md5(s.encode('utf8')).digest()
    for b in hash:
        result = result * 256 + int(b)
    return result % 1000000000


#
#--- Default configuration values
#
cfgfile = 'imapauth.ini'
default = {'imap':(('host', str, 'localhost'),
                       ('ignore_ssl_hostname', bool, False),
                       ('must_trust_cert', bool, True),
                       ),
                    
            'ice':(('host', str, '127.0.0.1'),
                   ('port', int, 6502),
                   ('slice', str, 'Murmur.ice'),
                   ('secret', str, ''),
                   ('watchdog', int, 30)),
                   
            'iceraw':None,
                   
            'murmur':(('servers', lambda x:list(map(int, x.split(','))), []),),
                       
            'log':(('level', int, logging.DEBUG),
                   ('file', str, 'imapauth.log'))}
 
#
#--- Helper classes
#
class config(object):
    """
    Small abstraction for config loading
    """

    def __init__(self, filename = None, default = None):
        if not filename or not default: return
        cfg = configparser.ConfigParser()
        cfg.optionxform = str
        cfg.read(filename)
        
        for h,v in default.items():
            if not v:
                # Output this whole section as a list of raw key/value tuples
                try:
                    self.__dict__[h] = cfg.items(h)
                except configparser.NoSectionError:
                    self.__dict__[h] = []
            else:
                self.__dict__[h] = config()
                for name, conv, vdefault in v:
                    try:
                        self.__dict__[h].__dict__[name] = conv(cfg.get(h, name))
                    except (ValueError, configparser.NoSectionError, configparser.NoOptionError):
                        self.__dict__[h].__dict__[name] = vdefault

def do_main_program():
    #
    #--- Authenticator implementation
    #    All of this has to go in here so we can correctly daemonize the tool
    #    without loosing the file descriptors opened by the Ice module
    slicedir = Ice.getSliceDir()
    # I had to hardcode this in a newer install. Might be different for you
    slicedir = "-I/usr/share/ice/slice /usr/share/slice/"
    Ice.loadSlice(slicedir +  cfg.ice.slice)
    import Murmur
    
    class imapauthenticatorApp(Ice.Application):
        def run(self, args):
            self.shutdownOnInterrupt()
            
            if not self.initializeIceConnection():
                return 1

            if cfg.ice.watchdog > 0:
                self.failedWatch = True
                self.checkConnection()
                
            # Serve till we are stopped
            self.communicator().waitForShutdown()
            self.watchdog.cancel()
            
            if self.interrupted():
                warning('Caught interrupt, shutting down')
                
            return 0
        
        def initializeIceConnection(self):
            """
            Establishes the two-way Ice connection and adds the authenticator to the
            configured servers
            """
            ice = self.communicator()
            
            if cfg.ice.secret:
                debug('Using shared ice secret')
                ice.getImplicitContext().put("secret", cfg.ice.secret)
                
            info('Connecting to Ice server (%s:%d)', cfg.ice.host, cfg.ice.port)
            base = ice.stringToProxy('Meta:tcp -h %s -p %d' % (cfg.ice.host, cfg.ice.port))
            self.meta = Murmur.MetaPrx.uncheckedCast(base)
        
            adapter = ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s' % cfg.ice.host)
            adapter.activate()
            
            metacbprx = adapter.addWithUUID(metaCallback(self))
            self.metacb = Murmur.MetaCallbackPrx.uncheckedCast(metacbprx)
            
            authprx = adapter.addWithUUID(imapauthenticator())
            self.auth = Murmur.ServerUpdatingAuthenticatorPrx.uncheckedCast(authprx)
            
            return self.attachCallbacks()
        
        def attachCallbacks(self, quiet = False):
            """
            Attaches all callbacks for meta and authenticators
            """
            
            # Ice.ConnectionRefusedException
            #debug('Attaching callbacks')
            try:
                if not quiet: info('Attaching meta callback')

                self.meta.addCallback(self.metacb)
                
                for server in self.meta.getBootedServers():
                    if not cfg.murmur.servers or server.id() in cfg.murmur.servers:
                        if not quiet: info('Setting authenticator for virtual server %d', server.id())
                        server.setAuthenticator(self.auth)
                        
            except (Murmur.InvalidSecretException, Ice.UnknownUserException, Ice.ConnectionRefusedException) as e:
                if isinstance(e, Ice.ConnectionRefusedException):
                    error('Server refused connection')
                elif isinstance(e, Murmur.InvalidSecretException) or \
                     isinstance(e, Ice.UnknownUserException) and (e.unknown == 'Murmur::InvalidSecretException'):
                    error('Invalid ice secret')
                else:
                    # We do not actually want to handle this one, re-raise it
                    raise e
                
                self.connected = False
                return False

            self.connected = True
            return True
        
        def checkConnection(self):
            """
            Tries reapplies all callbacks to make sure the authenticator
            survives server restarts and disconnects.
            """
            #debug('Watchdog run')

            try:
                if not self.attachCallbacks(quiet = not self.failedWatch):
                    self.failedWatch = True
                else:
                    self.failedWatch = False
            except Ice.Exception as e:
                error('Failed connection check, will retry in next watchdog run (%ds)', cfg.ice.watchdog)
                debug(str(e))
                self.failedWatch = True

            # Renew the timer
            self.watchdog = Timer(cfg.ice.watchdog, self.checkConnection)
            self.watchdog.start()
        
    def checkSecret(func):
        """
        Decorator that checks whether the server transmitted the right secret
        if a secret is supposed to be used.
        """
        if not cfg.ice.secret:
            return func
        
        def newfunc(*args, **kws):
            if 'current' in kws:
                current = kws["current"]
            else:
                current = args[-1]
            
            if not current or 'secret' not in current.ctx or current.ctx['secret'] != cfg.ice.secret:
                error('Server transmitted invalid secret. Possible injection attempt.')
                raise Murmur.InvalidSecretException()
            
            return func(*args, **kws)
        
        return newfunc

    def fortifyIceFu(retval = None, exceptions = (Ice.Exception,)):
        """
        Decorator that catches exceptions,logs them and returns a safe retval
        value. This helps preventing the authenticator getting stuck in
        critical code paths. Only exceptions that are instances of classes
        given in the exceptions list are not caught.
        
        The default is to catch all non-Ice exceptions.
        """
        def newdec(func):
            def newfunc(*args, **kws):
                try:
                    return func(*args, **kws)
                except Exception as e:
                    catch = True
                    for ex in exceptions:
                        if isinstance(e, ex):
                            catch = False
                            break

                    if catch:
                        critical('Unexpected exception caught')
                        exception(e)
                        return retval
                    raise

            return newfunc
        return newdec
                
    class metaCallback(Murmur.MetaCallback):
        def __init__(self, app):
            Murmur.MetaCallback.__init__(self)
            self.app = app

        @fortifyIceFu()
        @checkSecret
        def started(self, server, current = None):
            """
            This function is called when a virtual server is started
            and makes sure an authenticator gets attached if needed.
            """
            if not cfg.murmur.servers or server.id() in cfg.murmur.servers:
                info('Setting authenticator for virtual server %d', server.id())
                try:
                    server.setAuthenticator(app.auth)
                # Apparently this server was restarted without us noticing
                except (Murmur.InvalidSecretException, Ice.UnknownUserException) as e:
                    if hasattr(e, "unknown") and e.unknown != "Murmur::InvalidSecretException":
                        # Special handling for Murmur 1.2.2 servers with invalid slice files
                        raise e
                    
                    error('Invalid ice secret')
                    return
            else:
                debug('Virtual server %d got started', server.id())

        @fortifyIceFu()
        @checkSecret
        def stopped(self, server, current = None):
            """
            This function is called when a virtual server is stopped
            """
            if self.app.connected:
                # Only try to output the server id if we think we are still connected to prevent
                # flooding of our thread pool
                try:
                    if not cfg.murmur.servers or server.id() in cfg.murmur.servers:
                        info('Authenticated virtual server %d got stopped', server.id())
                    else:
                        debug('Virtual server %d got stopped', server.id())
                    return
                except Ice.ConnectionRefusedException:
                    self.app.connected = False
            
            debug('Server shutdown stopped a virtual server')
    
    authenticateFortifyResult = (-2, None, None)
        
    class imapauthenticator(Murmur.ServerUpdatingAuthenticator):
        texture_cache = {}
        def __init__(self):
            Murmur.ServerUpdatingAuthenticator.__init__(self)

        @fortifyIceFu(authenticateFortifyResult)
        @checkSecret
        def authenticate(self, name, pw, certlist, certhash, strong, current = None):
            """
            This function is called to authenticate a user
            """
            
            # Search for the user in the database
            FALL_THROUGH = -2
            AUTH_REFUSED = -1
            
            if name == 'SuperUser':
                debug('Forced fall through for SuperUser')
                return (FALL_THROUGH, None, None)
            

            try:
                with IMAPClient(host=cfg.imap.host, ssl_context=ssl_context) as client:
                    client.login(name, pw)
            except IMAPClient.Error as e:
                info('Fall through for unknown user "%s" or connection problem', name)
                return (AUTH_REFUSED, None, None)
            
            # As IMAP hasn't got such thing as a USERID, we use the given name to calculate a hash 
	    # TODO this might be highly insecure when two mails have coindently the same hash (note that we are cutting the integer off as otherwise we would get an error from mumble)
            uid = hashString(name)
            info('User authenticated: "%s", UID: %s', name, str(uid))
            return (uid, name, [])

            
        @fortifyIceFu((False, None))
        @checkSecret
        def getInfo(self, id, current = None):
            """
            Gets called to fetch user specific information
            """
            
            # We do not expose any additional information so always fall through
            debug('getInfo for %d -> denied', id)
            return (False, None)

        @fortifyIceFu(-2)
        @checkSecret
        def nameToId(self, name, current = None):
            """
            Gets called to get the id for a given username
            """
            
            FALL_THROUGH = -2
            if name == 'SuperUser':
                debug('nameToId SuperUser -> forced fall through')
                return FALL_THROUGH
            
            # There is no such thing in IMAP
            return hashString(name)
        
        @fortifyIceFu("")
        @checkSecret
        def idToName(self, id, current = None):
            """
            Gets called to get the username for a given id
            """
            
            FALL_THROUGH = ""
            
            # There is no such thing in IMAP
            return FALL_THROUGH
            
        @fortifyIceFu("")
        @checkSecret
        def idToTexture(self, id, current = None):
            """
            Gets called to get the corresponding texture for a user
            """

            FALL_THROUGH = ""
            return FALL_THROUGH

        @fortifyIceFu(-2)
        @checkSecret
        def registerUser(self, name, current = None):
            """
            Gets called when the server is asked to register a user.
            """
            
            FALL_THROUGH = -2
            debug('registerUser "%s" -> fall through', name)
            return FALL_THROUGH

        @fortifyIceFu(-1)
        @checkSecret
        def unregisterUser(self, id, current = None):
            """
            Gets called when the server is asked to unregister a user.
            """
            
            FALL_THROUGH = -1
            # Return -1 to fall through to internal server database, we don't want to modify IMAP backend
            # but we can make murmur delete all additional information it got this way.
            debug('unregisterUser %d -> fall through', id)
            return FALL_THROUGH

        @fortifyIceFu(-1)
        @checkSecret
        def getRegisteredUsers(self, filter, current = None):
            """
            Returns a list of usernames from IMAP which contain
            filter as a substring.
            """
            
            FALL_THROUGH = -1
            # Return -1 to fall through to internal server database, we can't access a list of users using IMAP
            # but we can make murmur delete all additional information it got this way.
        
        @fortifyIceFu(-1)
        @checkSecret
        def setInfo(self, id, info, current = None):
            """
            Gets called when the server is supposed to save additional information
            about a user to his database
            """
            
            FALL_THROUGH = -1
            # Return -1 to fall through to the internal server handler. We must not modify
            # IMAP backend so the additional information is stored in murmurs database
            debug('setInfo %d -> fall through', id)
            return FALL_THROUGH
        
        @fortifyIceFu(-1)
        @checkSecret
        def setTexture(self, id, texture, current = None):
            """
            Gets called when the server is asked to update the user texture of a user
            """
            

            # There is no such thing in IMAP
            FALL_THROUGH = -1
            return FALL_THROUGH
        
    class CustomLogger(Ice.Logger):
        """
        Logger implementation to pipe Ice log messages into
        our own log
        """
        
        def __init__(self):
            Ice.Logger.__init__(self)
            self._log = getLogger('Ice')
            
        def _print(self, message):
            self._log.info(message)
            
        def trace(self, category, message):
            self._log.debug('Trace %s: %s', category, message)
            
        def warning(self, message):
            self._log.warning(message)
            
        def error(self, message):
            self._log.error(message)

    #
    #--- Start of authenticator
    #
    info('Starting imap mumble authenticator')
    initdata = Ice.InitializationData()
    initdata.properties = Ice.createProperties([], initdata.properties)
    for prop, val in cfg.iceraw:
        initdata.properties.setProperty(prop, val)
        
    initdata.properties.setProperty('Ice.ImplicitContext', 'Shared')
    initdata.properties.setProperty('Ice.Default.EncodingVersion', '1.0')
    initdata.logger = CustomLogger()
    
    app = imapauthenticatorApp()
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
    except Exception as e:
        print('Fatal error, could not load config file from "%s"' % cfgfile, file=sys.stderr)
        sys.exit(1)
            
    
    # Initialize logger
    if cfg.log.file:
        try:
            logfile = open(cfg.log.file, 'a')
        except IOError as e:
            #print>>sys.stderr, str(e)
            print('Fatal error, could not open logfile "%s"' % cfg.log.file, file=sys.stderr)
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
    
    if cfg.imap.ignore_ssl_hostname:
        ssl_context.check_hostname = False
        
    if not cfg.imap.must_trust_cert:
        ssl_context.verify_mode = ssl.CERT_NONE
        
        
    # As the default try to run as daemon. Silently degrade to running as a normal application if this fails
    # unless the user explicitly defined what he expected with the -a / -d parameter. 
    try:
        if option.force_app:
            raise ImportError # Pretend that we couldn't import the daemon lib
        import daemon
    except ImportError:
        if option.force_daemon:
            print('Fatal error, could not daemonize process due to missing "daemon" library, ' \
            'please install the missing dependency and restart the authenticator', file=sys.stderr)
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


