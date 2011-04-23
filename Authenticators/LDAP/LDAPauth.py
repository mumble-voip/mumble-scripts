#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2011 Nathaniel Kofalt <nkofalt@users.sourceforge.net>
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
# Further, this script has only been tested while storing the users in a single OU.
# Storing users in an OU tree will work, but probably will break group membership checking.
# The group-membership code will have to be expanded if you want to use multiple OUs with groups.
# Or if you want multiple groups allowed, etc. This is just a simple example.
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
# Note that if the script fails for any reason, it will reject rather than delegate.
# You may want to change this based on how you want murmur to work in the absence of LDAP.
#
# This script is known to work on Linux Debian 6.0, and should would on any platform.
# It should work against either a Windows Active Directory or an OpenLDAP server.
# Dont forget this script requires that ZeroC ICE be installed, download from here:
# http://www.zeroc.com/download.html
# Or on Linux: sudo apt-get install python-zeroc-ice python-ldap
#
# Script originally provided by pcgod
# Modifications made:
#	- Added error handling for integer parsing
#	- Added a lot of explanatory comments, cleaned up code flow
#	- Added capability for a display name different than your login username
#	- Fixed SuperUser not being correctly delegated to Murmur authentication
#	- Fixed errors with uid/name cache not working and crashing randomly
#	- Added ability to query LDAP for user IDs and names that are not in the cache

################
#ICE Connection#
################

#Where is ICE located?
#	This is the server Mumble is running on
ice_host = "127.0.0.1"

#What port is ICE running on?
#	This is set in the murmur.ini file
ice_port = 6502

#Where is the ICE slice located?
#	Just run a search for "Murmur.ice"
slice_folder = "/usr/share/slice"

#Which server ID do you want to use this authenticator with?
#	To run with any & all servers, set this to -1
server_id = 0

#################
#LDAP Connection#
#################

#Where is the LDAP server located?
ldap_uri = "ldap://127.0.0.1"

#Where are your user entries located?
users_dn = "ou=Users,dc=example,dc=com"

#################
#LDAP Attributes#
#################

#What attribute holds their login username?
username_attr = "uid" 

#What attribute holds their (unique) integer UID?
number_attr = "roomNumber"

#What attribute holds their display name? (What mumble will take as their username)
#	This separates the Mumble login/display name from the authentication username.
#	Useful if login usernames are ugly, eg translate "example.user" to "Example User"
#	You can keep this the same as username_attr to disable display names.
display_attr = "displayName"

#######################
#LDAP Group Attributes#
#######################

#Which group cn to check for?
#	Leave this empty to disable checking group membership
group_cn = "cn=mumble,ou=Groups,dc=example,dc=com"

#Which attribute should we match the user's uid against?
group_attr = "uniqueMember"

##
## BE CAREFUL BELOW THIS LINE!
##

#Load folders and murmur's ICE slice file
import Ice
import sys
import ldap
Ice.loadSlice("", ["-I " + slice_folder, slice_folder + "/Murmur.ice"])
import Murmur

#The authenticator against LDAP
class LdapAuthenticator(Murmur.ServerAuthenticator):
	#Bootstrap objects
	def __init__(self, server, adapter):
		Murmur.ServerAuthenticator.__init__(self)
		self.server	= server
		self.adapter = adapter
		self.name_uid_cache = dict()
	
	#Decide if a user is allowed to connect
	def authenticate(self, name, password, certlist, certhash, strong, current = None):
		#print("Attempt from " + name + " with password " + password)
		
		#Defer SuperUser authentication to Mumble
		if name == "SuperUser":
			print("SuperUser detected, let murmur handle it")
			return(-2, None, None)
		
		#Otherwise, let's check the LDAP server
		uid = None
		try:
			#Attempt to bind to LDAP server with user-provided credentials
			ldap_conn = ldap.initialize(ldap_uri, 0)
			ldap_conn.bind_s("%s=%s,%s" % (username_attr, name, users_dn), password)
			res = ldap_conn.search_s(users_dn, ldap.SCOPE_SUBTREE, '(%s=%s)' % (username_attr, name), [number_attr, display_attr])
			match = res[0] #Only interested in the first result, as there should only be one match
			
			#Parse the user information
			uid = int(match[1][number_attr][0])
			displayName = match[1][display_attr][0]
			print('User match found, display "' + displayName + '" with UID ' + repr(uid))
			
			#Optionally check groups
			if group_cn != "" :
				print('Checking group membership for ' + name)
				
				#Search for user in group
				res = ldap_conn.search_s(group_cn, ldap.SCOPE_SUBTREE, '(%s=%s=%s,%s)' % (group_attr, username_attr, name, users_dn), [number_attr, display_attr])
				
				# Check if the user is a member of the group
				if len(res) != 1:
					print('User ' + name + ' failed with no group membership')
					return (-1, None, None)
				
			#Unbind and close connection
			ldap_conn.unbind()
			
		#What follows below are various what-if scenarios: authentication failures and successes
				 
		#LDAP bind failed - expected to happen if bad login
		except ldap.INVALID_CREDENTIALS: 
				print("User " + name + " failed with wrong password")
				return (-1, None, None)
				
		#Generic LDAP error, check LDAP configuration
		except ldap.LDAPError, e: 
			exc_obj, exc_value, exc_traceback = sys.exc_info()
			print 'LDAP exception (' + name + '): %s, "%s"' % (exc_obj, exc_value)
			return (-1, None, None)
			
		#Any other error, check this script's code :(
		except Exception: 
			exc_obj, exc_value, exc_traceback = sys.exc_info()
			print('Python exception (' + name + '): %s, "%s"' % (exc_obj, exc_value))
			return (-1, None, None)
		
		#No user exists by this name; reject login
		if uid is None:
			print("User " + name + " failed with no UID or int parsing fail")
			return (-1, None, None)

		#If we get here, the login is correct.
		#Add the user/id combo to cache, then accept:
		self.name_uid_cache[displayName] = uid
		print("Login accepted for " + name)
		return (uid, displayName, [])

	# The below functions access a cache for Murmur
	# Murmur needs to be able to map UIDs to names, and vice-versa.
	# This appears to mainly be used when accessing or editing server ACLs.
	# Some of these do nothing (getInfo and idToTexture) just to delegate functionality.
	
	#These functions delegate user-info and user-texture storage:
	def getInfo(self, id, current = None):
		return (False, None)
	def idToTexture(self, id, current = None):
		return ""
	#End functions that do nothing
	
	#LDAP query for name to ID
	def nameToIdLDAP(self, name):
		try: 
			ldap_conn = ldap.initialize(ldap_uri, 0) #Anon search
			res = ldap_conn.search_s(users_dn, ldap.SCOPE_SUBTREE, '(%s=%s)' % (display_attr, name), [number_attr])
			
			#If user found, return the ID
			if len(res) == 1:
				result = int(res[0][1][number_attr][0])
			else:
				result = -2
				
		except Exception:
			exc_obj, exc_value, exc_traceback = sys.exc_info()
			print('Python exception in nameToIdLDAP, %s, "%s"' % (exc_obj, exc_value))
			result = -2
		
		return result
	
	#Data-accessor functions for UID cache:
	def nameToId(self, name, current = None):
		#Look up the username
		try:
			result = self.name_uid_cache[name]
			
		#This username is not in the cache, run LDAP search for it
		except KeyError:
			print('Hitting LDAP to find ID for ' + name)
			result = self.nameToIdLDAP(name)

		#Catch any errors (name not found, for example)
		except Exception:
			exc_obj, exc_value, exc_traceback = sys.exc_info()
			print('Python exception in nameToId, %s, "%s"' % (exc_obj, exc_value))
			result = -2
		
		print "nameToId: %s -> %d" % (name, result)
		return result
		
	def idToName(self, id, current = None):
		#Check every key in the table to see if it matches the ID
		try:
			result = ""
			for k in self.name_uid_cache.keys():
				if self.name_uid_cache[k] == id:
					result = k
		
		#Catch any errors (id not found, for example)
		except Exception:
			exc_obj, exc_value, exc_traceback = sys.exc_info()
			print('Python exception in idToName, %s, "%s"' % (exc_obj, exc_value))
			result = ""
		
		print "idToName: %d -> %s" % (id, result)
		return result
		
	#End data accessor functions

#Main runnable (note that server(s) must already be running)
if __name__ == "__main__":
	print "Registering LDAP authenticator with specified servers..."
	
	#Connecting to the mumur server's ICE interface
	ice = Ice.initialize(sys.argv)
	meta = Murmur.MetaPrx.checkedCast(ice.stringToProxy("Meta:tcp -h %s -p %d" % (ice_host, ice_port)))
	adapter = ice.createObjectAdapterWithEndpoints("Callback.Client", "tcp -h %s" % ice_host)
	adapter.activate()

	#Add the LDAP authenticator to every online server
	for server in meta.getBootedServers():
	
		if server.id() == server_id or server_id == -1:
			auth = Murmur.ServerUpdatingAuthenticatorPrx.uncheckedCast(adapter.addWithUUID(LdapAuthenticator(server, adapter)))
			server.setAuthenticator(auth)
			print(' Connected to server #' + repr(server.id()))

	#Wait for shutdown
	print 'Script running (press CTRL-C to abort)'
	try:
		ice.waitForShutdown()
	except KeyboardInterrupt:
		print 'CTRL-C caught, aborting'

	#Shutdown
	ice.shutdown()
	print "Goodbye"
	

