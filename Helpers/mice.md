# Mice

[`mice.py`](mice.py] is a very small Python script that demonstrates and simplifies setting up a connection to a Mumble Server through the Ice interface.

This script does nothing but save you a few lines you would have to type in on every start of a session otherwise.

'''Note:''' mice offers no command-line interface in the general sense and instead relies on the interactive mode of python consoles.

## Configuration

If you enabled Ice on your server and placed the `Murmur.ice` file in the same folder as `mice.py` you do not need to do any additional configuration.
The default settings should work.

If you want to connect to something else than `localhost`, or your `.ice` file is positioned somewhere else, edit `mice.py` with a text editor.
The configuration variables can be found at the top of the file and are self-explaining.

## Usage

To use the `mice.py` file you have to run it in interactive mode in the Python console of your choice. You can use the default python interpreter

```
python -i mice.py
```

or

```
python
>>> import mice
```

but it lacks tab-completion, highlighting etc. It is not a very comfortable way to explore the possibilities of the Ice interface.

The alternative [http://ipython.scipy.org/ ipython] interactive python shell can - after installation - be launched with

```
ipython
import mice
```

On startup mice will try to connect to the server directly.
If this fails check your configuration.
If it succeeds mice will tell you where to find the server object it created.

To get a feel of what the object is able to do you can use introspection/reflection (with the default python interpreter you can use `dir(object)` to emulate this to some extend, but using the tab-completion in ipython is much more convenient).

## Introduction

A small community-provided introduction for using mice to control your Mumble server can be found [here on blog.natenom.com](https://blog.natenom.com/2016/02/an-introduction-on-how-to-manage-your-mumble-server-murmur-through-ice-with-mice/).
