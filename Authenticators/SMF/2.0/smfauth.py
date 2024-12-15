#!/usr/bin/env python3
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
#    smfauth.py - Authenticator implementation for password authenticating
#                 a Murmur server against a SMF forum database
#
#    Requirements:
#        * python >=3.0 and the following python modules:
#            * ice-python
#            * MySQLdb
#            * daemon (when run as a daemon)
#

import sys
import Ice
import _thread
import urllib.request, urllib.error, urllib.parse
import logging
import configparser
import bcrypt

from threading  import Timer
from optparse   import OptionParser
from logging    import (debug,
                        info,
                        warning,
                        error,
                        critical,
                        exception,
                        getLogger)

try:
    from hashlib import sha1
except ImportError: # python 2.4 compat
    from sha import sha as sha1

def x2bool(s):
    """Helper function to convert strings from the config to bool"""
    if isinstance(s, bool):
        return s
    elif isinstance(s, str):
        return s.lower() in ['1', 'true']
    raise ValueError()

#
#--- Default configuration values
#
cfgfile = 'smfauth.ini'
default = {'database':(('lib', str, 'MySQLdb'),
                       ('name', str, 'smf'),
                       ('user', str, 'smf'),
                       ('password', str, 'secret'),
                       ('prefix', str, 'smf_'),
                       ('host', str, '127.0.0.1'),
                       ('port', int, 3306)),
            'forum':(('path', str, 'http://localhost/smf/'),),
                     
            'user':(('id_offset', int, 1000000000),
                    ('avatar_enable', x2bool, False),
                    ('reject_on_error', x2bool, True)),
                    
            'ice':(('host', str, '127.0.0.1'),
                   ('port', int, 6502),
                   ('slice', str, 'MumbleServer.ice'),
                   ('secret', str, ''),
                   ('watchdog', int, 30)),
                   
            'iceraw':None,
                   
            'murmur':(('servers', lambda x:list(map(int, x.split(','))), []),),
            'glacier':(('enabled', x2bool, False),
                       ('user', str, 'smf'),
                       ('password', str, 'secret'),
                       ('host', str, 'localhost'),
                       ('port', int, '4063')),
                       
            'log':(('level', int, logging.DEBUG),
                   ('file', str, 'smfauth.log'))}
 
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
                    
def entity_decode(string):
    """
    Python reverse implementation of php htmlspecialchars
    """
    htmlspecialchars = (('"', '&quot;'),
                        ("'", '&#039;'),
                        ('<', '&lt;'),
                        ('>', '&gt'),
                        ('&', '&amp;'))
    ret = string
    for (s,t) in htmlspecialchars:
        ret = ret.replace(t, s)
    return ret

def entity_encode(string):
    """
    Python implementation of htmlspecialchars
    """
    htmlspecialchars = (('&', '&amp;'),
                        ('"', '&quot;'),
                        ("'", '&#039;'),
                        ('<', '&lt;'),
                        ('>', '&gt'))
    ret = string
    for (s,t) in htmlspecialchars:
        ret = ret.replace(s, t)
    return ret
        
class threadDbException(Exception): pass
class threadDB(object):
    """
    Small abstraction to handle database connections for multiple
    threads
    """
    
    db_connections = {}

    def connection(cls):
        tid = _thread.get_ident()
        try:
            con = cls.db_connections[tid]
        except:
            info('Connecting to database server (%s %s:%d %s) for thread %d',
                 cfg.database.lib, cfg.database.host, cfg.database.port, cfg.database.name, tid)
            
            try:
                con = db.connect(host = cfg.database.host,
                                   port = cfg.database.port,
                                   user = cfg.database.user,
                                   passwd = cfg.database.password,
                                   db = cfg.database.name,
                                   charset = 'utf8')
                # Transactional engines like InnoDB initiate a transaction even
                # on SELECTs-only. Thus, we auto-commit so smfauth gets recent data.
                con.autocommit(True)
            except db.Error as e:
                error('Could not connect to database: %s', str(e))
                raise threadDbException()
            cls.db_connections[tid] = con
        return con
    connection = classmethod(connection)
    
    def cursor(cls):
        return cls.connection().cursor()
    cursor = classmethod(cursor)
    
    def execute(cls, *args, **kwargs):
        if "threadDB__retry_execution__" in kwargs:
            # Have a magic keyword so we can call ourselves while preventing
            # an infinite loop
            del kwargs["threadDB__retry_execution__"]
            retry = False
        else:
            retry = True
        
        c = cls.cursor()
        try:
            c.execute(*args, **kwargs)
        except db.OperationalError as e:
            error('Database operational error %d: %s', e.args[0], e.args[1])
            c.close()
            cls.invalidate_connection()
            if retry:
                # Make sure we only retry once
                info('Retrying database operation')
                kwargs["threadDB__retry_execution__"] = True
                c = cls.execute(*args, **kwargs)
            else:
                error('Database operation failed ultimately')
                raise threadDbException()
        return c
    execute = classmethod(execute)
    
    def invalidate_connection(cls):
        tid = _thread.get_ident()
        con = cls.db_connections.pop(tid, None)
        if con:
            debug('Invalidate connection to database for thread %d', tid)
            con.close()
            
    invalidate_connection = classmethod(invalidate_connection)
    
    def disconnect(cls):
        while cls.db_connections:
            tid, con = cls.db_connections.popitem()
            debug('Close database connection for thread %d', tid)
            con.close()
    disconnect = classmethod(disconnect)

def do_main_program():
    #
    #--- Authenticator implementation
    #    All of this has to go in here so we can correctly daemonize the tool
    #    without loosing the file descriptors opened by the Ice module
    slicedir = Ice.getSliceDir()
    if not slicedir:
        slicedir = ["-I/usr/share/Ice/slice", "-I/usr/share/slice"]
    else:
        slicedir = ['-I' + slicedir]
    Ice.loadSlice('', slicedir + [cfg.ice.slice])
    import MumbleServer
    
    class smfauthenticatorApp(Ice.Application):
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
                
            threadDB.disconnect()
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
            elif not cfg.glacier.enabled:
                warning('Consider using an ice secret to improve security')
                
            if cfg.glacier.enabled:
                #info('Connecting to Glacier2 server (%s:%d)', glacier_host, glacier_port)
                error('Glacier support not implemented yet')
                #TODO: Implement this
    
            info('Connecting to Ice server (%s:%d)', cfg.ice.host, cfg.ice.port)
            base = ice.stringToProxy('Meta:tcp -h %s -p %d' % (cfg.ice.host, cfg.ice.port))
            self.meta = MumbleServer.MetaPrx.uncheckedCast(base)
        
            adapter = ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s' % cfg.ice.host)
            adapter.activate()
            
            metacbprx = adapter.addWithUUID(metaCallback(self))
            self.metacb = MumbleServer.MetaCallbackPrx.uncheckedCast(metacbprx)
            
            authprx = adapter.addWithUUID(smfauthenticator())
            self.auth = MumbleServer.ServerUpdatingAuthenticatorPrx.uncheckedCast(authprx)
            
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
                        
            except (MumbleServer.InvalidSecretException, Ice.UnknownUserException, Ice.ConnectionRefusedException) as e:
                if isinstance(e, Ice.ConnectionRefusedException):
                    error('Server refused connection')
                elif isinstance(e, MumbleServer.InvalidSecretException) or \
                     isinstance(e, Ice.UnknownUserException) and (e.unknown == 'MumbleServer::InvalidSecretException'):
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
                raise MumbleServer.InvalidSecretException()
            
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
                
    class metaCallback(MumbleServer.MetaCallback):
        def __init__(self, app):
            MumbleServer.MetaCallback.__init__(self)
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
                except (MumbleServer.InvalidSecretException, Ice.UnknownUserException) as e:
                    if hasattr(e, "unknown") and e.unknown != "MumbleServer::InvalidSecretException":
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
    
    if cfg.user.reject_on_error: # Python 2.4 compat
        authenticateFortifyResult = (-1, None, None)
    else:
        authenticateFortifyResult = (-2, None, None)
        
    class smfauthenticator(MumbleServer.ServerUpdatingAuthenticator):
        texture_cache = {}
        def __init__(self):
            MumbleServer.ServerUpdatingAuthenticator.__init__(self)

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
                sql = 'SELECT id_member, passwd, id_group, member_name, real_name, additional_groups, is_activated FROM %smembers WHERE LOWER(member_name) = LOWER(%%s)' % cfg.database.prefix
                cur = threadDB.execute(sql, [name])
            except threadDbException:
                return (FALL_THROUGH, None, None)
            
            res = cur.fetchone()
            cur.close()
            if not res:
                info('Fall through for unknown user "%s"', name)
                return (FALL_THROUGH, None, None)
    
            uid, upw, ugroupid, uname, urealname, uadditgroups, activated = res
            
            if activated == 1 and smf_check_hash(pw, upw, uname):
                # Authenticated, fetch group memberships
                try:
                    if uadditgroups:
                        groupids = str(ugroupid) + ',' + uadditgroups
                    else:
                        groupids = str(ugroupid)

                    sql = 'SELECT group_name FROM %smembergroups WHERE id_group IN (%s)' % (cfg.database.prefix, groupids)
                    cur = threadDB.execute(sql)
                except threadDbException:
                    return (FALL_THROUGH, None, None)

                groups = cur.fetchall()
                cur.close()
                if groups:
                    groups = [a[0] for a in groups]

                info('User authenticated: "%s" (%d)', name, uid + cfg.user.id_offset)
                debug('Group memberships: %s', str(groups))
                return (uid + cfg.user.id_offset, entity_decode(urealname), groups)

            info('Failed authentication attempt for user: "%s" (%d)', name, uid + cfg.user.id_offset)
            return (AUTH_REFUSED, None, None)
            
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
            
            try:
                sql = 'SELECT id_member FROM %smembers WHERE LOWER(member_name) = LOWER(%%s)' % cfg.database.prefix
                cur = threadDB.execute(sql, [name])
            except threadDbException:
                return FALL_THROUGH
            
            res = cur.fetchone()
            cur.close()
            if not res:
                debug('nameToId %s -> ?', name)
                return FALL_THROUGH
            
            debug('nameToId %s -> %d', name, (res[0] + cfg.user.id_offset))
            return res[0] + cfg.user.id_offset
        
        @fortifyIceFu("")
        @checkSecret
        def idToName(self, id, current = None):
            """
            Gets called to get the username for a given id
            """
            
            FALL_THROUGH = ""
            # Make sure the ID is in our range and transform it to the actual smf user id
            if id < cfg.user.id_offset:
                return FALL_THROUGH 
            bbid = id - cfg.user.id_offset
            
            # Fetch the user from the database
            try:
                sql = 'SELECT member_name FROM %smembers WHERE id_member = %%s' % cfg.database.prefix
                cur = threadDB.execute(sql, [bbid])
            except threadDbException:
                return FALL_THROUGH
            
            res = cur.fetchone()
            cur.close()
            if res:
                if res[0] == 'SuperUser':
                    debug('idToName %d -> "SuperUser" catched')
                    return FALL_THROUGH
                
                debug('idToName %d -> "%s"', id, res[0])
                return res[0]
            
            debug('idToName %d -> ?', id)
            return FALL_THROUGH
            
        @fortifyIceFu("")
        @checkSecret
        def idToTexture(self, id, current = None):
            """
            Gets called to get the corresponding texture for a user
            """

            FALL_THROUGH = ""
            
            debug('idToTexture for %d', id)
            if id < cfg.user.id_offset or not cfg.user.avatar_enable:
                debug('idToTexture %d -> fall through', id)
                return FALL_THROUGH
            
            # Otherwise get the users texture from smf
            bbid = id - cfg.user.id_offset
            try:
                sql = 'SELECT avatar FROM %smembers WHERE id_member = %%s' % cfg.database.prefix
                cur = threadDB.execute(sql, [bbid])
            except threadDbException:
                return FALL_THROUGH
            res = cur.fetchone()
            cur.close()
            if not res:
                debug('idToTexture %d -> user unknown, fall through', id)
                return FALL_THROUGH
            avatar = res[0]
            
            if not avatar:
                # Either the user has none or it is in the attachments, check there
                try:
                    sql = '''SELECT id_attach, file_hash, filename, attachment_type FROM %sattachments WHERE approved = true AND
                        (attachment_type = 0 OR attachment_type = 1) AND id_member = %%s''' % cfg.database.prefix
                    cur = threadDB.execute(sql, [bbid])
                except threadDbException:
                    return FALL_THROUGH
                
                res = cur.fetchone()
                cur.close()
                if not res:
                    # No uploaded avatar found, seems like the user didn't set one
                    debug('idToTexture %d -> no texture available for this user, fall through', id)
                    return FALL_THROUGH
                
                fid, fhash, filename, fattachtype = res
                if cfg.forum.path.startswith('file://'):
                    # We are supposed to load this from the local fs
                    avatar_file = cfg.forum.path + 'attachments/%d_%s' % (fid, fhash)
                elif fattachtype == 0: 
                    avatar_file = cfg.forum.path + 'index.php?action=dlattach;attach=%d;type=avatar' % fid
                elif fattachtype == 1:
                    avatar_file = cfg.forum.path + 'avatars/' + filename 
            elif "://" in avatar:
                # ...or it is a external link
                avatar_file = avatar
            else:
                warning("avatar with an unexpected value, fall through")
                return FALL_THROUGH
                
            if avatar_file in self.texture_cache:
                return self.texture_cache[avatar_file]
            
            try:
                handle = urllib.request.urlopen(avatar_file)
                filecontent = handle.read()
                handle.close()
            except urllib.error.URLError as e:
                warning('Image download for "%s" (%d) failed: %s', avatar_file, id, str(e))
                return FALL_THROUGH
            
            self.texture_cache[avatar_file] = filecontent
            
            return self.texture_cache[avatar_file]
            
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
            # Return -1 to fall through to internal server database, we will not modify the smf database
            # but we can make murmur delete all additional information it got this way.
            debug('unregisterUser %d -> fall through', id)
            return FALL_THROUGH

        @fortifyIceFu({})
        @checkSecret
        def getRegisteredUsers(self, filter, current = None):
            """
            Returns a list of usernames in the smf database which contain
            filter as a substring.
            """
            
            if not filter:
                filter = '%'
            
            try:
                sql = 'SELECT id_member, member_name FROM %smembers WHERE is_activated = 1 AND member_name LIKE %%s' % cfg.database.prefix
                cur = threadDB.execute(sql, [filter])
            except threadDbException:
                return {}
    
            res = cur.fetchall()
            cur.close()
            if not res:
                debug('getRegisteredUsers -> empty list for filter "%s"', filter)
                return {}
            debug ('getRegisteredUsers -> %d results for filter "%s"', len(res), filter)
            return dict([(a + cfg.user.id_offset, b) for a,b in res])
        
        @fortifyIceFu(-1)
        @checkSecret
        def setInfo(self, id, info, current = None):
            """
            Gets called when the server is supposed to save additional information
            about a user to his database
            """
            
            FALL_THROUGH = -1
            # Return -1 to fall through to the internal server handler. We must not modify
            # the smf database so the additional information is stored in murmurs database
            debug('setInfo %d -> fall through', id)
            return FALL_THROUGH
        
        @fortifyIceFu(-1)
        @checkSecret
        def setTexture(self, id, texture, current = None):
            """
            Gets called when the server is asked to update the user texture of a user
            """
            
            FAILED = 0
            FALL_THROUGH = -1
            
            if id < cfg.user.id_offset:
                debug('setTexture %d -> fall through', id)
                return FALL_THROUGH
            
            if cfg.user.avatar_enable:
                # Report a fail (0) as we will not update the avatar in the smf database.
                debug('setTexture %d -> failed', id)
                return FAILED
            
            # If we don't use textures from smf we let mumble save it
            debug('setTexture %d -> fall through', id)
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
    info('Starting smf mumble authenticator')
    initdata = Ice.InitializationData()
    initdata.properties = Ice.createProperties([], initdata.properties)
    for prop, val in cfg.iceraw:
        initdata.properties.setProperty(prop, val)
        
    initdata.properties.setProperty('Ice.ImplicitContext', 'Shared')
    initdata.properties.setProperty('Ice.Default.EncodingVersion', '1.0')
    initdata.logger = CustomLogger()
    
    app = smfauthenticatorApp()
    state = app.main(sys.argv[:1], initData = initdata)
    info('Shutdown complete')



#
#--- Python implementation of the smf check hash function
#
def smf_check_hash(password, hash, username):
    """
    Python implementation of the smf check hash function
    """
    ret = False

    try:
      # SMF 2.1 uses a bcrypt hash, try that first
      ret = bcrypt.hashpw(username.lower().encode('utf-8') + password, hash.encode('utf-8')) == hash
    except ValueError:
      # The sha1 password hash from SMF 2.0 and earlier will cause a salt value error
      # In that case, try the legacy sha1 hash
      ret = sha1(username.lower().encode('utf8') + password).hexdigest() == hash

    return ret

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
        
    try:
        db = __import__(cfg.database.lib)
    except ImportError as e:
        print('Fatal error, could not import database library "%s", '\
        'please install the missing dependency and restart the authenticator' % cfg.database.lib, file=sys.stderr)
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
