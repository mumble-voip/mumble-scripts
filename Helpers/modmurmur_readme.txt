=======================
= modmurmur.py readme =
=======================
What is modmurmur.py:
    A small wrapper for connecting to Murmur servers of different versions
    while offering access to the underlying raw functionality.

Requirements:
    * python >=2.6 and the following python modules:
        * ice-python
        
Installation:
    Place modmurmur.py and the legacy_slices directory in the directory
    you need them.
    
Usage:
    First modmurmur hast to be imported. Since the module offers logging
    make sure you also setup that up.

    >>> from modmurmur import MurmurServer
    >>> from logging import basicConfig, DEBUG
    >>> basicConfig(level = DEBUG)

    Then you can instanciate and connect to a server. Connect takes the
    host, the port and, if needed, the serverpassword as parameters.

    >>> m = MurmurServer()
    >>> m.connect("127.0.0.1", 6502, "supersecret")   # With Ice-secret
    or
    >>> m.connect("127.0.0.1", 6502)   # Without Ice-Secret

    Once the module is connected every function in the murmur meta class
    will be mapped into the object. A few common tasks you can do now would
    be:

    Adding a server and getting its id
    >>> s = m.newServer()
    >>> the_new_servers_id = s.id()

    Deleting a server
    >>> server_id = 1
    >>> s = m.getServer(server_id)
    >>> s.delete()

    Editing a servers configuration. For example changing maximum users, the
    servers password or its welcome message.

    >>> s = m.getServer(1)
    >>> s.setConf("users", 1000)
    >>> s.setConf("password", "superpassword")
    >>> s.setConf("welcometext", "Welcome to my server")

    Starting and stopping a server.

    >>> s = m.getServer(1)
    >>> s.stop()
    >>> s.start()

    Listing all servers or only booted servers.

    >>> m.getAllServers()
    >>> m.getBootedServers()

    Registering new users.

    >>> s = m.getServer(1)
    >>> UserInfo = m.Murmur.UserInfo
    >>> user_id = s.registerUser({UserInfo.UserName:"User1",
                                  UserInfo.UserEmail:"bla@blub.com",
                                  UserInfo.UserHash:"certificatehashgoeshereifyouhaveit",
                                  UserInfo.UserPassword:"backwardscompatiblepassword"})

    Editing existing user registrations.

    >>> s = m.getServer(1)
    >>> UserInfo = m.Murmur.UserInfo
    >>> user_id = s.getUserIds(["User1"])["User1"]
    >>> reg = s.getRegistration(user_id)
    >>> reg[UserInfo.UserEmail] = "fancy@new.mail"
    >>> s.updateRegistration(user_id, reg)


    Once you are done don't forget to disconnect.

    >>> m.disconnect()

Note:
    Always be aware that all these functions, except connect and disconnect,
    directly operate on Murmurs Ice interface. So if you want to find out exactly
    what is available take a peak into your servers slice (Murmur.ice) file.
    These files are heavily documented so no need to fear their syntax.