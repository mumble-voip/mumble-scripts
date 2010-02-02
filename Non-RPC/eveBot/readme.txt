Eve the mumble eavesdropper bot
===============================

This bot is written for online multiplayer gaming communities, where the
spectator's view of the game is sometimes delayed to prevent collusion.

Specators may wish the listen to the communication of the match team, however
the delay (typically 90 seconds) between the in-game action and the mumble
server normally makes this impossible.  This bot was written to facilitate
that.

The bot joins the match channel and listens to all comms.  For every user in the
channel, a mimic will join the spectate channel, and the eavesdropper bot will
relay the comms to the correct mimic, with the specified delay.


Prerequisites
-------------

- This bot needs python with ssl support.  This either requires version 2.6 or
  for the ssl module to be downloaded and installed seperately from
  http://pypi.python.org/pypi/ssl/
- Mumble uses protocol buffers for control messages.  To run the bot, the python
  protobuf modules and the protoc compiler must be installed.  The protoc
  compiler generates the python module necessary for the bot to understand the
  control messages.  To do this, navigate to the directory the bot will be run
  from and type

          protoc --python_out=. Mumble.proto

  You must also have Mumble.proto in the current directory.  The latest version
  of this can be found in the mumble/murmur source code.


Using
-----

In the simplest case, running the bot by typing

        eve-bot.py -e "Match Channel" -r "Spectator Channel"

This will attempt to connect to a mumble server on the default port, on the same
machine as the bot is running on.  The channels MUST exist; they can be the same
if you wish, though this is likely to cause confusion.  Running the bot with no
options will give a list of the available parameters.


Known Issues
------------

Very few error messages from the server are checked.  For instance, if the bot's
name is not valid, no helpful error message will be returned.  The bots do not
send ping messages to the server until they have joined the correct channel, so
if their desired channel doesn't exist when they join, and isn't created soon
after, they will time out.

The bots don't notice if they have been moved; this won't affect mimics, but the
eavesdropper bot will only attempt to listen to people who are in the correct
channel, so unless it's moved to a linked channel it won't hear much.

If the bot refuses to work properly, the -v option will decode and print all
control messages from the server, which should indicate the problem.

Passworded access to a server has not been checked in mumble 1.2.  The bot has
only been checked with python version 2.5.2 (with external ssl module) and
2.6.4

Feedback greatly appreciated

http://frymaster.127001.org/mumble

Copyright (c) 2009, Philip Cass <frymaster@127001.org>
Copyright (c) 2009, Alan Ainsworth <fruitbat@127001.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.
Redistributions in binary form must reproduce the above copyright notice, this
list of conditions and the following disclaimer in the documentation and/or
other materials provided with the distribution.
Neither the name localhost, 127001.org nor the names of its contributors may be
used to endorse or promote products derived from this software without specific
prior written permission
