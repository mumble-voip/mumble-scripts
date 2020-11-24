#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2011 Benjamin Jemlich <pcgod@user.sourceforge.net>
# Copyright (C) 2011 Nathaniel Kofalt <nkofalt@users.sourceforge.net>
# Copyright (C) 2013 Stefan Hacker <dd0t@users.sourceforge.net>
# Copyright (C) 2014 Dominik George <nik@naturalnet.de>
# Copyright (C) 2020 Andreas Valder <a.valder@syseleven.de>
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


# This script will let you authenticate Murmur against an LDAP tree.
# Note that you should have a reasonable understanding of LDAP before trying to use this script.
#
# Unfortunately, LDAP is a rather complex concept / protocol / software suite.
# So if you're not already experienced with LDAP, the Mumble team may be unable to assist you.
# Unless you already have an existing LDAP tree, you may want to authenticate your users another way.
# However, LDAP has the advantage of being extremely scalable, flexible, and resilient.
# This is probably a decent choice for larger-scale deployments (code review this script first!)
#
# There are some excellent resources to get you started:
#  Wikipedia article:	http://en.wikipedia.org/wiki/LDAP
#  OpenLDAP intro:		http://www.openldap.org/doc/admin24/intro.html
#  LDAP on Debian:		http://techpubs.spinlocksolutions.com/dklar/ldap.html
#  IRC Chat room:		Channel #ldap on irc.freenode.net
#
# Configuring this to hit LDAP correctly can be a little tricky.
# This is largely due to the numerous ways you can store user information in LDAP.
# The example configuration is probably not the best way to do things; it's just a simple setup.
#
# The group-membership code will have to be expanded if you want multiple groups allowed, etc.
# This is just a simple example.
#
# In this configuration, I use a really simple groupOfUniqueNames and OU of inetOrgPersons.
# The tree already uses the "uid" attribute for usernames, so roomNumber was used to store UID.
# Note that mumble needs a username, password, and unique UID for each user.
# You can definitely set things up differently; this is a bit of a kludge.
#
# Here is the tree layout used in the example config:
#	dc=example,dc=com	(organization)
#		ou=Groups		(organizationalUnit)
#			cn=mumble 	(groupOfUniqueNames)
#				"uniqueMember: uid=user1,dc=example,dc=com"
#				"uniqueMember: uid=user2,dc=example,dc=com"
#		ou=Users		(organizationalUnit)
#			uid=user1	(inetOrgPerson)
#				"userPassword: {SHA}password-hash"
#				"displayName: User One"
#				"roomNumber: 1"
#			uid=user2	(inetOrgPerson)
#				"userPassword: {SHA}password-hash"
#				"displayName: User Two"
#				"roomNumber: 2"
#			uid=user3	(inetOrgPerson)
#				"userPassword: {SHA}password-hash"
#				"displayName: User Three"
#				"roomNumber: 3"
#
# How the script operates:
# First, the script will attempt to "bind" with the user's credentials.
# If the bind fails, the username/password combination is rejected.
# Second, it optionally checks for a group membership.
# With groups off, all three users are let in; with groups on, only user1 & user2 are allowed.
# Finally, it optionally logs in the user with a separate "display_attr" name.
# This allows user1 to log in with the USERNAME "user1" but is displayed in mumble as "User One".
#
# If you use the bind_dn option, the script will bind with the specified DN
# and check for the existence of user and (optionally) the group membership
# before it binds with the username/password.  This allows you to use a server
# which only allows authentication by end users without any search
# permissions.  It also allows you to set the reject_on_miss option to false
# and let login IDs not found in LDAP fall-through to an alternate
# authentication scheme.
#
#    Requirements:
#        * python >=3.8 (maybe 3.6 is enough but it wasn't tested) and the following python modules:
#            * ice-python
#            * python-ldap
#            * daemon (when run as a daemon)
#    If you are using Ubuntu/Debian (only Ubuntu 20.04 was tested) the following packages provide these:
#        * python3
#        * python3-zeroc-ice
#        * python3-ldap
#        * python3-daemon
#        * zeroc-ice-slice

import sys
import ldap
import Ice
import _thread
import urllib.request, urllib.error, urllib.parse
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
cfgfile = 'LDAPauth.ini'
default = { 'ldap':(('ldap_uri', str, 'ldap://127.0.0.1'),
                    ('bind_dn', str, ''),
                    ('bind_pass', str, ''),
                    ('users_dn', str, 'ou=Users,dc=example,dc=org'),
                    ('discover_dn', x2bool, True),
                    ('username_attr', str, 'uid'),
                    ('number_attr', str, 'RoomNumber'),
                    ('display_attr', str, 'displayName'),
                    ('group_dn', str, 'ou=Groups,dc=example,dc=org'),
                    ('group_attr', str, 'member'),
                    ('provide_info', x2bool, False),
                    ('mail_attr', str, 'mail'),
                    ('provide_users', x2bool, False),
                    ('use_start_tls', x2bool, False)),

            'user':(('id_offset', int, 1000000000),
                    ('reject_on_error', x2bool, True),
                    ('reject_on_miss', x2bool, True)),
           
            'ice':(('host', str, '127.0.0.1'),
                   ('port', int, 6502),
                   ('slice', str, 'Murmur.ice'),
                   ('secret', str, ''),
                   ('watchdog', int, 30)),
                   
            'iceraw':None,
                   
            'murmur':(('servers', lambda x:list(map(int, x.split(','))), []),),
            'glacier':(('enabled', x2bool, False),
                       ('user', str, 'ldapauth'),
                       ('password', str, 'secret'),
                       ('host', str, 'localhost'),
                       ('port', int, '4063')),
                       
            'log':(('level', int, logging.DEBUG),
                   ('file', str, 'LDAPauth.log'))}
 
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
    if not slicedir:
        slicedir = ["-I/usr/share/Ice/slice", "-I/usr/share/slice"]
    else:
        slicedir = ['-I' + slicedir]
    Ice.loadSlice('', slicedir + [cfg.ice.slice])
    import Murmur
    
    class LDAPAuthenticatorApp(Ice.Application):
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
            elif not cfg.glacier.enabled:
                warning('Consider using an ice secret to improve security')
                
            if cfg.glacier.enabled:
                #info('Connecting to Glacier2 server (%s:%d)', glacier_host, glacier_port)
                error('Glacier support not implemented yet')
                #TODO: Implement this
    
            info('Connecting to Ice server (%s:%d)', cfg.ice.host, cfg.ice.port)
            base = ice.stringToProxy('Meta:tcp -h %s -p %d' % (cfg.ice.host, cfg.ice.port))
            self.meta = Murmur.MetaPrx.uncheckedCast(base)
        
            adapter = ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h %s' % cfg.ice.host)
            adapter.activate()
            
            metacbprx = adapter.addWithUUID(metaCallback(self))
            self.metacb = Murmur.MetaCallbackPrx.uncheckedCast(metacbprx)
            
            authprx = adapter.addWithUUID(LDAPAuthenticator())
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
    
    if cfg.user.reject_on_error: # Python 2.4 compat
        authenticateFortifyResult = (-1, None, None)
    else:
        authenticateFortifyResult = (-2, None, None)
        
    class LDAPAuthenticator(Murmur.ServerUpdatingAuthenticator):
        def __init__(self):
            Murmur.ServerUpdatingAuthenticator.__init__(self)
            self.name_uid_cache = dict()

        @fortifyIceFu(authenticateFortifyResult)
        @checkSecret
        def authenticate(self, name, pw, certlist, certhash, strong, current = None):
            """
            This function is called to authenticate a user
            """
            
            # Search for the user in the database
            FALL_THROUGH = -2
            AUTH_REFUSED = -1
            
            # SuperUser is a special login.
            if name == 'SuperUser':
                debug('Forced fall through for SuperUser')
                return (FALL_THROUGH, None, None)

            # Otherwise, let's check the LDAP server.
            uid = None

            if cfg.ldap.use_start_tls:
                # try StartTLS: global options
                debug('use_start_tls is set, setting global option TLS_REQCERT = never')
                ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)

            ldap_trace = 0 # Change to 1 for more verbose trace
            ldap_conn = ldap.initialize(cfg.ldap.ldap_uri, ldap_trace)

            if cfg.ldap.use_start_tls:
                # try StartTLS: connection specific options
                debug('use_start_tls is set, setting connection options X_TLS_*')
                ldap_conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
                ldap_conn.set_option(ldap.OPT_X_TLS, ldap.OPT_X_TLS_DEMAND)
                ldap_conn.set_option(ldap.OPT_X_TLS_DEMAND, True)
                try:
                    ldap_conn.start_tls_s()
                except Exception as e:
                    warning('could not initiate StartTLS, e = ' + str(e))
                    return (AUTH_REFUSED, None, None)

            if cfg.ldap.bind_dn:
                # Bind the functional account to search the directory.
                bind_dn = cfg.ldap.bind_dn
                bind_pass = cfg.ldap.bind_pass
                try:
                    debug('try to connect to ldap (bind_dn will be used)')
                    ldap_conn.bind_s(bind_dn, bind_pass)
                except ldap.INVALID_CREDENTIALS: 
                    ldap_conn.unbind()
                    warning('Invalid credentials for bind_dn=' + bind_dn)
                    return (AUTH_REFUSED, None, None)
            elif cfg.ldap.discover_dn:
                # Use anonymous bind to discover the DN
                try:
                    ldap_conn.bind_s()
                except ldap.INVALID_CREDENTIALS: 
                    ldap_conn.unbind()
                    warning('Failed anomymous bind for discovering DN')
                    return (AUTH_REFUSED, None, None)

            else:
                # Prevent anonymous authentication.
                if not pw:
                    warning("No password supplied for user " + name)
                    return (AUTH_REFUSED, None, None)
            
                # Bind the user account to search the directory.
                bind_dn = "%s=%s,%s" % (cfg.ldap.username_attr, name, cfg.ldap.users_dn)
                bind_pass = pw
                try:
                    ldap_conn.bind_s(bind_dn, bind_pass)
                except ldap.INVALID_CREDENTIALS: 
                    ldap_conn.unbind()
                    warning('User ' + name + ' failed with invalid credentials')
                    return (AUTH_REFUSED, None, None)

            # Search for the user.
            res = ldap_conn.search_s(cfg.ldap.users_dn, ldap.SCOPE_SUBTREE, '(%s=%s)' % (cfg.ldap.username_attr, name), [cfg.ldap.number_attr, cfg.ldap.display_attr])
            if len(res) == 0:
                warning("User " + name + " not found")
                if cfg.user.reject_on_miss:
                    return (AUTH_REFUSED, None, None)
                else:
                    return (FALL_THROUGH, None, None)
            match = res[0] #Only interested in the first result, as there should only be one match
                
            # Parse the user information.
            uid = int(match[1][cfg.ldap.number_attr][0])
            displayName = match[1][cfg.ldap.display_attr][0].decode()
            user_dn = match[0]
            debug('User match found, display "' + displayName + '" with UID ' + repr(uid))
                
            # Optionally check groups.
            if cfg.ldap.group_dn != "" :
                debug('Checking group membership for ' + name)
                    
                #Search for user in group
                res = ldap_conn.search_s(cfg.ldap.group_dn, ldap.SCOPE_SUBTREE, '(%s=%s)' % (cfg.ldap.group_attr, user_dn), [cfg.ldap.number_attr, cfg.ldap.display_attr])
                    
                # Check if the user is a member of the group
                if len(res) < 1:
                    debug('User ' + name + ' failed with no group membership')
                    return (AUTH_REFUSED, None, None)
                    
            # Second bind to test user credentials if using bind_dn or discover_dn.
            if cfg.ldap.bind_dn or cfg.ldap.discover_dn:
                # Prevent anonymous authentication.
                if not pw:
                    warning("No password supplied for user " + name)
                    return (AUTH_REFUSED, None, None)
            
                bind_dn = user_dn
                bind_pass = pw
                try:
                    ldap_conn.bind_s(bind_dn, bind_pass)
                except ldap.INVALID_CREDENTIALS: 
                    ldap_conn.unbind()
                    warning('User ' + name + ' failed with wrong password')
                    return (AUTH_REFUSED, None, None)

            # Unbind and close connection.
            ldap_conn.unbind()
                
            # If we get here, the login is correct.
            # Add the user/id combo to cache, then accept:
            self.name_uid_cache[displayName] = uid
            debug("Login accepted for " + name)
            return (uid + cfg.user.id_offset, displayName, [])
            
        @fortifyIceFu((False, None))
        @checkSecret
        def getInfo(self, id, current = None):
            """
            Gets called to fetch user specific information
            """
            
            if not cfg.ldap.provide_info:
                # We do not expose any additional information so always fall through
                debug('getInfo for %d -> denied', id)
                return (False, None)

            ldap_conn = ldap.initialize(cfg.ldap.ldap_uri, 0)

            # Bind if configured, else do explicit anonymous bind
            if cfg.ldap.bind_dn and cfg.ldap.bind_pass:
                ldap_conn.simple_bind_s(cfg.ldap.bind_dn, cfg.ldap.bind_pass)
            else:
                ldap_conn.simple_bind_s()

            name = self.idToName(id, current)

            res = ldap_conn.search_s(cfg.ldap.users_dn,
                                    ldap.SCOPE_SUBTREE,
                                    '(%s=%s)' % (cfg.ldap.display_attr, name),
                                    [cfg.ldap.display_attr,
                                     cfg.ldap.mail_attr    
                                    ])
            
            #If user found, return info
            if len(res) == 1:
                info = {}

                if cfg.ldap.mail_attr in res[0][1]:
                    info[Murmur.UserInfo.UserEmail] = res[0][1][cfg.ldap.mail_attr][0].decode()

                debug('getInfo %s -> %s', name, repr(info))
                return (True, info)
            else:
                debug('getInfo %s -> ?', name)
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
            
            if name in self.name_uid_cache:
                uid = self.name_uid_cache[name] + cfg.user.id_offset
                debug("nameToId %s (cache) -> %d", name, uid)
                return uid
            
            ldap_conn = ldap.initialize(cfg.ldap.ldap_uri, 0)

            # Bind if configured, else do explicit anonymous bind
            if cfg.ldap.bind_dn and cfg.ldap.bind_pass:
                ldap_conn.simple_bind_s(cfg.ldap.bind_dn, cfg.ldap.bind_pass)
            else:
                ldap_conn.simple_bind_s()

            res = ldap_conn.search_s(cfg.ldap.users_dn, ldap.SCOPE_SUBTREE, '(%s=%s)' % (cfg.ldap.display_attr, name), [cfg.ldap.number_attr])
            
            #If user found, return the ID
            if len(res) == 1:
                uid = int(res[0][1][cfg.ldap.number_attr][0]) + cfg.user.id_offset
                debug('nameToId %s -> %d', name, uid)
            else:
                debug('nameToId %s -> ?', name)
                return FALL_THROUGH
            
            return uid
        
        
        @fortifyIceFu("")
        @checkSecret
        def idToName(self, id, current = None):
            """
            Gets called to get the username for a given id
            """
            
            FALL_THROUGH = ""

            # Make sure the ID is in our range and transform it to the actual LDAP user id
            if id < cfg.user.id_offset:
                debug('idToName %d -> fall through', id)
                return FALL_THROUGH 
            
            ldapid = id - cfg.user.id_offset
            
            for name, uid in self.name_uid_cache.items():
                if uid == ldapid:
                    if name == 'SuperUser':
                        debug('idToName %d -> "SuperUser" catched', id)
                        return FALL_THROUGH
                    
                    debug('idToName %d -> "%s"', id, name)
                    return name
                
            debug('idToName %d -> ?', id)
            return FALL_THROUGH
         
            
        @fortifyIceFu("")
        @checkSecret
        def idToTexture(self, id, current = None):
            """
            Gets called to get the corresponding texture for a user
            """
            
            FALL_THROUGH = ""
            debug('idToTexture %d -> fall through', id)
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
            # Return -1 to fall through to internal server database, we will not modify the LDAP directory
            # but we can make murmur delete all additional information it got this way.
            debug('unregisterUser %d -> fall through', id)
            return FALL_THROUGH

        @fortifyIceFu({})
        @checkSecret
        def getRegisteredUsers(self, filter, current = None):
            """
            Returns a list of usernames in the LDAP directory which contain
            filter as a substring.
            """
            FALL_THROUGH = {}

            if not cfg.ldap.provide_users:
                # Fall through if not configured to provide user list
                debug('getRegisteredUsers -> fall through')
                return FALL_THROUGH

            ldap_conn = ldap.initialize(cfg.ldap.ldap_uri, 0)

            # Bind if configured, else do explicit anonymous bind
            if cfg.ldap.bind_dn and cfg.ldap.bind_pass:
                ldap_conn.simple_bind_s(cfg.ldap.bind_dn, cfg.ldap.bind_pass)
            else:
                ldap_conn.simple_bind_s()

            if filter:
                res = ldap_conn.search_s(cfg.ldap.users_dn, ldap.SCOPE_SUBTREE, '(&(uid=*)(%s=*%s*))' % (cfg.ldap.display_attr, filter), [cfg.ldap.number_attr, cfg.ldap.display_attr])
            else:
                res = ldap_conn.search_s(cfg.ldap.users_dn, ldap.SCOPE_SUBTREE, '(uid=*)', [cfg.ldap.number_attr, cfg.ldap.display_attr])
            
            # Build result dict
            users = {}
            for dn, attrs in res:
                if cfg.ldap.number_attr in attrs and cfg.ldap.display_attr in attrs:
                    uid = int(attrs[cfg.ldap.number_attr][0]) + cfg.user.id_offset
                    name = attrs[cfg.ldap.display_attr][0]
                    users[uid] = name
            debug('getRegisteredUsers %s -> %s', filter, repr(users))
            return users
        
        @fortifyIceFu(-1)
        @checkSecret
        def setInfo(self, id, info, current = None):
            """
            Gets called when the server is supposed to save additional information
            about a user to his database
            """
            
            FALL_THROUGH = -1
            # Return -1 to fall through to the internal server handler. We do not store
            # any information in LDAP
            debug('setInfo %d -> fall through', id)
            return FALL_THROUGH
        
        @fortifyIceFu(-1)
        @checkSecret
        def setTexture(self, id, texture, current = None):
            """
            Gets called when the server is asked to update the user texture of a user
            """
            FALL_THROUGH = -1
            
            # We do not store textures in LDAP
            debug('setTexture %d -> fall through', id)
            return FALL_THROUGH
        
    class CustomLogger(Ice.Logger):
        """
        Logger implementation to pipe Ice log messages into
        out own log
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
    info('Starting LDAP mumble authenticator')
    initdata = Ice.InitializationData()
    initdata.properties = Ice.createProperties([], initdata.properties)
    for prop, val in cfg.iceraw:
        initdata.properties.setProperty(prop, val)
        
    initdata.properties.setProperty('Ice.ImplicitContext', 'Shared')
    initdata.properties.setProperty('Ice.Default.EncodingVersion', '1.0')
    initdata.logger = CustomLogger()
    
    app = LDAPAuthenticatorApp()
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
