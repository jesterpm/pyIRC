#!/usr/bin/python
import socket
import ssl
import os
import re
import time
import sys
import string
import hashlib
import traceback
import irc
import getpass
from threading import Thread, Lock
import Queue


def BouncerReload(BNC):
    if BNC.isAlive():
        BNC.stop()
    newBNC = Bouncer(addr=BNC.addr, port=BNC.port, ssl=BNC.ssl, ipv6=BNC.ipv6,
                     certfile=BNC.certfile, keyfile=BNC.keyfile, timeout=BNC.timeout, autoaway=BNC.autoaway)
    for label, (IRC, passwd, hashtype) in BNC.servers.items():
        IRC.rmAddon(BNC)
        IRC.addAddon(newBNC, label=label, passwd=passwd, hashtype=hashtype)
    return newBNC


class Bouncer (Thread):

    def __init__(self, addr="", port=16667, ssl=False, ipv6=False, certfile=None, keyfile=None, ignore=None, debug=False, timeout=300, autoaway=None):
        self.__name__ = "Bouncer for pyIRC"
        self.__version__ = "1.2"
        self.__author__ = "Brian Sherson"
        self.__date__ = "December 26, 2013"

        self.addr = addr
        self.port = port
        self.servers = {}
        self.passwd = {}
        self.socket = socket.socket(
            socket.AF_INET6 if ipv6 else socket.AF_INET)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ssl = ssl
        self.ipv6 = ipv6
        self.certfile = certfile
        self.keyfile = keyfile
        self.socket.bind((self.addr, self.port))
        self.connections = []
        self.ignore = ignore
        self.debug = debug
        self.timeout = timeout
        self.autoaway = autoaway
        self._stopexpected = False

        # Keep track of what extensions/connections are requesting WHO, WHOIS, and LIST, because we don't want to spam every bouncer connection with the server's replies.
        # In the future, MAY implement this idea in the irc module.
        self.whoexpected = {}
        self.whoisexpected = {}
        self.listexpected = {}
        self.lock = Lock()
        self.starttime = int(time.time())
        Thread.__init__(self)
        self.daemon = True
        self.start()

    def __repr__(self):
        return "<Bouncer listening on port %(addr)s:%(port)s>" % vars(self)

    def run(self):
        self.socket.listen(5)
        #print ((self,"Now listening on port "+str(self.port)))
        while True:
            try:
                (connection, addr) = self.socket.accept()
                if self.ssl:
                    connection = ssl.wrap_socket(
                        connection, server_side=True, certfile=self.certfile, keyfile=self.keyfile, ssl_version=ssl.PROTOCOL_SSLv23)
                #print ((self,"New client connecting from %s:%s"%addr))
            except socket.error:
                # print "Shutting down Listener"
                self.socket.close()
                if not self._stopexpected:
                    raise
                sys.exit()
            except:
                tb = traceback.format_exc()
                print >>sys.stderr, tb
                continue
            connection.settimeout(self.timeout)
            bouncer = BouncerConnection(
                self, connection, addr, debug=self.debug)
            time.sleep(0.5)
        try:
            self.socket.close()
        except:
            pass

    def onAddonAdd(self, IRC, label, passwd=None, hashtype="sha512"):
        if passwd == None:
            while True:
                passwd = getpass.getpass("Enter new password: ")
                if passwd == getpass.getpass("Confirm new password: "):
                    break
                print "Passwords do not match!"
            passwd = hashlib.new(hashtype, passwd).hexdigest()
        if IRC in [connection for (connection, p, h) in self.servers.values()]:
            return  # Silently do nothing
        if label in self.servers.keys():
            return
        self.servers[label] = (IRC, passwd, hashtype)
        self.whoexpected[IRC] = []
        if self.debug:
            IRC.logwrite(
                "dbg [Bouncer.onAddonAdd] Clearing WHO expected list." % vars())
        self.whoisexpected[IRC] = []
        self.listexpected[IRC] = []

    def onAddonRem(self, IRC):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.quit(quitmsg="Bouncer extension removed")
        for (label, (connection, passwd, hashtype)) in self.servers.items():
            if connection == IRC:
                del self.servers[label]

    def stop(self):
        self._stopexpected = True
        self.socket.shutdown(0)

    def disconnectall(self, quitmsg="Disconnecting all sessions"):
        for bouncerconnection in self.connections:
            bouncerconnection.stop(quitmsg=quitmsg)

    def onDisconnect(self, IRC, expected=False):
        self.whoexpected[IRC] = []
        self.whoisexpected[IRC] = []
        self.listexpected[IRC] = []
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                #bouncerconnection.quit(quitmsg="IRC connection lost")
                for channel in IRC.identity.channels:
                    bouncerconnection.send(":%s!%s@%s PART %s :Bouncer Connection Lost\n" % (
                        IRC.identity.nick, IRC.identity.username, IRC.identity.host, channel.name))
                bouncerconnection.send(
                    ":%s!%s@%s QUIT :Bouncer Connection Lost\n" %
                    (IRC.identity.nick, IRC.identity.username, IRC.identity.host))
                bouncerconnection.send(
                    ":*Bouncer* NOTICE %s :Connection to %s:%s has been lost.\n" %
                    (bouncerconnection.nick, IRC.server, IRC.port))

    def onQuit(self, IRC, user, quitmsg):
        # For some odd reason, certain networks (*cough*Freenode*cough*) will send a quit message for the user, causing IRC.identity.channels to be cleared
        # before onDisconnect can be executed. This is the remedy.
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                if quitmsg:
                    bouncerconnection.send(":%s!%s@%s QUIT :%s\n" % (
                        user.nick, user.username, user.host, quitmsg))
                else:
                    bouncerconnection.send(
                        ":%s!%s@%s QUIT\n" % (user.nick, user.username, user.host))
                if user == IRC.identity:
                    for channel in IRC.identity.channels:
                        bouncerconnection.send(":%s!%s@%s PART %s :Bouncer Connection Lost\n" % (
                            IRC.identity.nick, IRC.identity.username, IRC.identity.host, channel.name))

    def onConnectAttempt(self, IRC):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.send(
                    ":*Bouncer* NOTICE %s :Attempting connection to %s:%s.\n" %
                    (bouncerconnection.nick, IRC.server, IRC.port))

    def onConnect(self, IRC):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.send(
                    ":*Bouncer* NOTICE %s :Connection to %s:%s established.\n" %
                    (bouncerconnection.nick, IRC.server, IRC.port))

    def onMeNickChange(self, IRC, newnick):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.send(":%s!%s@%s NICK %s\n" %
                                       (IRC.identity.nick, IRC.identity.username, IRC.identity.host, newnick))
                bouncerconnection.nick = newnick

    def onRegistered(self, IRC):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                if bouncerconnection.nick != IRC.identity.nick:
                    bouncerconnection.send(":%s!%s@%s NICK %s\n" % (
                        bouncerconnection.nick, bouncerconnection.username, bouncerconnection.host, IRC.identity.nick))
                    bouncerconnection.nick = IRC.identity.nick

    def onConnectFail(self, IRC, exc, excmsg, tb):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.send(
                    ":*Bouncer* NOTICE %s :Connection to %s:%s failed: %s.\n" %
                    (bouncerconnection.nick, IRC.server, IRC.port, excmsg))

    def onSendChanMsg(self, IRC, origin, channel, targetprefix, msg):
        # Called when bot sends a PRIVMSG to channel.
        # The variable origin refers to a class instance voluntarily
        # identifying itself as that which requested data be sent.
        for bouncerconnection in self.connections:
            if IRC == bouncerconnection.IRC and origin != bouncerconnection:
                bouncerconnection.send(":%s!%s@%s PRIVMSG %s%s :%s\n" %
                                       (IRC.identity.nick, IRC.identity.username, IRC.identity.host, targetprefix, channel.name, msg))

    def onSendChanAction(self, IRC, origin, channel, targetprefix, action):
        self.onSendChanMsg(
            IRC, origin, channel, targetprefix, "\x01ACTION %s\x01" % action)

    def onSendChanNotice(self, IRC, origin, channel, targetprefix, msg):
        # Called when bot sends a NOTICE to channel.
        # The variable origin refers to a class instance voluntarily
        # identifying itself as that which requested data be sent.
        for bouncerconnection in self.connections:
            if IRC == bouncerconnection.IRC and origin != bouncerconnection:
                bouncerconnection.send(":%s!%s@%s NOTICE %s%s :%s\n" % (
                    IRC.identity.nick, IRC.identity.username, IRC.identity.host, targetprefix, channel.name, msg))

    def onSend(self, IRC, origin, line, cmd, target, params, extinfo):
        if cmd.upper() == "WHO":
            self.whoexpected[IRC].append(origin)
            if self.debug:
                if issubclass(type(origin), Thread):
                    name = origin.name
                    IRC.logwrite(
                        "dbg [Bouncer.onSend] Adding %(origin)s (%(name)s) to WHO expected list." % vars())
                else:
                    IRC.logwrite(
                        "dbg [Bouncer.onSend] Adding %(origin)s to WHO expected list." % vars())
                IRC.logwrite(
                    "dbg [Bouncer.onSend] WHO expected list size: %d" %
                    len(self.whoexpected[IRC]))
        elif cmd.upper() == "WHOIS":
            self.whoisexpected[IRC].append(origin)
        elif cmd.upper() == "LIST":
            self.listexpected[IRC].append(origin)

    def onWhoEntry(self, IRC, origin, channel, user, channame, username, host, serv, nick, flags, hops, realname):
        # Called when a WHO list is received.
        if len(self.whoexpected[IRC]) and self.whoexpected[IRC][0] in self.connections:
            bncconnection = self.whoexpected[IRC][0]
            bncconnection.send(":%s 352 %s %s %s %s %s %s %s :%s %s\n" %
                               (origin, IRC.identity.nick, channame, username, host, serv, nick, flags, hops, realname))

    def onWhoEnd(self, IRC, origin, param, endmsg):
        # Called when a WHO list is received.
        if len(self.whoexpected[IRC]) and self.whoexpected[IRC][0] in self.connections:
            bncconnection = self.whoexpected[IRC][0]
            bncconnection.send(":%s 315 %s %s :%s\n" %
                               (origin, IRC.identity.nick, param, endmsg))
        if self.debug:
            if issubclass(type(self.whoexpected[IRC][0]), Thread):
                name = self.whoexpected[IRC][0].name
                IRC.logwrite(
                    "dbg [Bouncer.onWhoEnd] Removing %s (%s) from WHO expected list." %
                    (self.whoexpected[IRC][0], name))
            else:
                IRC.logwrite(
                    "dbg [Bouncer.onWhoEnd] Removing %s from WHO expected list." % self.whoexpected[IRC][0])
        del self.whoexpected[IRC][0]
        if self.debug:
            IRC.logwrite("dbg [Bouncer.onWhoEnd] WHO expected list size: %d" %
                         len(self.whoexpected[IRC]))

    def onListStart(self, IRC, origin, params, extinfo):
        # Called when a WHO list is received.
        if len(self.listexpected[IRC]) and self.listexpected[IRC][0] in self.connections:
            bncconnection = self.listexpected[IRC][0]
            bncconnection.send(":%s 321 %s %s :%s\n" %
                               (origin, IRC.identity.nick, params, extinfo))

    def onListEntry(self, IRC, origin, channel, population, extinfo):
        # Called when a WHO list is received.
        if len(self.listexpected[IRC]) and self.listexpected[IRC][0] in self.connections:
            bncconnection = self.listexpected[IRC][0]
            bncconnection.send(":%s 322 %s %s %d :%s\n" %
                               (origin, IRC.identity.nick, channel.name, population, extinfo))

    def onListEnd(self, IRC, origin, endmsg):
        # Called when a WHO list is received.
        if len(self.listexpected[IRC]) and self.listexpected[IRC][0] in self.connections:
            bncconnection = self.listexpected[IRC][0]
            bncconnection.send(":%s 323 %s :%s\n" %
                               (origin, IRC.identity.nick, endmsg))
        del self.listexpected[IRC][0]

    def onWhoisStart(self, IRC, origin, user, nickname, username, host, realname):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]):
            if self.whoisexpected[IRC][0] in self.connections:
                bncconnection = self.whoisexpected[IRC][0]
                bncconnection.send(":%s 311 %s %s %s %s * :%s\n" %
                                   (origin, IRC.identity.nick, nickname, username, host, realname))

    def onWhoisRegisteredNick(self, IRC, origin, user, nickname, msg):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 307 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisConnectingFrom(self, IRC, origin, user, nickname, msg):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 378 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisChannels(self, IRC, origin, user, nickname, chanlist):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 319 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, " ".join(chanlist)))

    def onWhoisAvailability(self, IRC, origin, user, nickname, msg):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 310 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisServer(self, IRC, origin, user, nickname, server, servername):
        # Called when a WHOIS reply is received.
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 312 %s %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, server, servername))

    def onWhoisOp(self, IRC, origin, user, nickname, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 313 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisAway(self, IRC, origin, user, nickname, awaymsg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 301 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, awaymsg))

    def onWhoisTimes(self, IRC, origin, user, nickname, idletime, signontime, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 317 %s %s %d %d :%s\n" %
                               (origin, IRC.identity.nick, nickname, idletime, signontime, msg))

    def onWhoisSSL(self, IRC, origin, user, nickname, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 671 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisModes(self, IRC, origin, user, nickname, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 339 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))

    def onWhoisLoggedInAs(self, IRC, origin, user, nickname, loggedinas, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 330 %s %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, loggedinas, msg))

    def onWhoisEnd(self, IRC, origin, user, nickname, msg):
        if len(self.whoisexpected[IRC]) and self.whoisexpected[IRC][0] in self.connections:
            bncconnection = self.whoisexpected[IRC][0]
            bncconnection.send(":%s 318 %s %s :%s\n" %
                               (origin, IRC.identity.nick, nickname, msg))
        del self.whoisexpected[IRC][0]

    def onUnhandled(self, IRC, line, origin, cmd, target, params, extinfo):
        for bouncerconnection in self.connections:
            if bouncerconnection.IRC == IRC:
                bouncerconnection.send("%s\n" % line)


class BouncerConnection (Thread):

    def __init__(self, bouncer, connection, addr, debug=False):
        # print "Initializing ListenThread..."
        self.bouncer = bouncer
        self.connection = connection
        self.host, self.port = self.addr = addr[:2]
        self.IRC = None
        self.pwd = None
        self.nick = None
        self.label = None
        self.username = None
        self.realname = None
        self.addr = addr
        self.debug = debug
        self.lock = Lock()
        self.quitmsg = "Connection Closed"
        self.quitting = False

        Thread.__init__(self)
        self.daemon = True
        self.start()

    def send(self, data, flags=0):
        try:
            with self.lock:
                self.connection.send(data)
        except socket.error:
            exc, excmsg, tb = sys.exc_info()
            print >>self.IRC.logwrite(*["!!! [BouncerConnection.send] Exception in thread %(self)s" % vars()] + [
                                      "!!! [BouncerConnection.send] %(tbline)s" % vars() for tbline in traceback.format_exc().split("\n")])
            self.quit(quitmsg=excmsg.message)

    def __repr__(self):
        server = self.IRC.server if self.IRC else "*"
        port = self.IRC.port if self.IRC else "*"
        if self.IRC and self.IRC.identity:
            nick = self.IRC.identity.nick
            ident = self.IRC.identity.username if self.IRC.identity.username else "*"
            host = self.IRC.identity.host if self.IRC.identity.host else "*"
        else:
            nick = "*"
            ident = "*"
            host = "*"
        if self.IRC.ssl and self.IRC.ipv6:
            protocol = "ircs6"
        elif self.IRC.ssl:
            protocol = "ircs"
        elif self.IRC.ipv6:
            protocol = "irc6"
        else:
            protocol = "irc"
        addr = self.host
        return "<Bouncer connection from %(addr)s to %(nick)s!%(ident)s@%(host)s on %(protocol)s://%(server)s:%(port)s>" % locals()

    def quit(self, quitmsg="Disconnected"):
        if not self.quitting:
            self.quitmsg = quitmsg
            with self.lock:
                try:
                    self.connection.send("ERROR :Closing link: (%s@%s) [%s]\n" % (
                        self.IRC.identity.nick if self.IRC else "*", self.host, quitmsg))
                except:
                    pass
                try:
                    self.connection.shutdown(socket.SHUT_WR)
                    self.connection.close()
                except:
                    pass
                self.quitting = True

    def run(self):
        # Name loopup should happen here instead
        ipv4match = re.findall(
            r"^::ffff:((\d+)\.(\d+)\.(\d+)\.(\d+))$", self.host)
        if self.bouncer.ipv6 and ipv4match:
            addr, a, b, c, d = ipv4match[0]
            if max(int(a), int(b), int(c), int(d)) < 256:
                self.host = addr
                self.ipv6 = False
        elif self.bouncer.ipv6:
            self.ipv6 = True
        try:
            self.host, aliaslist, addresslist = socket.gethostbyaddr(self.host)
            self.addr = (self.host, addr[1])
        except:
            pass

        # Add connection to connection list.

        listnumerics = dict(b=(367, 368, "channel ban list"),
                            e=(348, 349, "Channel Exception List"),
                            I=(346, 347, "Channel Invite Exception List"),
                            w=(910, 911, "Channel Access List"),
                            g=(941, 940, "chanel spamfilter list"),
                            X=(954, 953, "channel exemptchanops list"))

        passwd = None
        nick = None
        user = None
        addr = self.host

        readbuf = ""
        linebuf = []

        try:
            while True:
                # Read data (appending) into readbuf, then break lines and
                # append lines to linebuf
                while len(linebuf) == 0:
                    timestamp = irc.timestamp()
                    read = self.connection.recv(512)
                    if read == "" and len(linebuf) == 0:  # No more data to process.
                        #self.quitmsg="Connection Closed"
                        sys.exit()

                    readbuf += read
                    lastlf = readbuf.rfind("\n")

                    if lastlf >= 0:
                        linebuf.extend(string.split(readbuf[0:lastlf], "\n"))
                        readbuf = readbuf[lastlf + 1:]

                line = string.rstrip(linebuf.pop(0))
                match = re.findall(
                    "^(.+?)(?:\\s+(.+?)(?:\\s+(.+?))??)??(?:\\s+:(.*))?$", line, re.I)

                if len(match) == 0:
                    continue
                (cmd, target, params, extinfo) = match[0]

                if not passwd:  # Bouncer expects a password
                    if cmd.upper() == "PASS":
                        passwd = target if target else extinfo
                    else:
                        self.quit("Access Denied")
                        print "*** [BouncerConnection] Incoming connection from %s failed: Expected PASS." % (self.host)
                        break

                elif not self.nick:  # Bouncer expects a NICK command
                    if cmd.upper() == "NICK":
                        self.nick = target if target else extinfo
                    else:
                        self.quit("Access Denied")
                        print "*** [BouncerConnection] Incoming connection from %s failed: Expected NICK." % (self.host)
                        break

                elif not self.username:  # Bouncer expects a USER command to finish registration
                    if cmd.upper() == "USER":
                        self.username = target
                        # print self.username
                        if self.username in self.bouncer.servers.keys():
                            self.IRC, passwdhash, hashtype = self.bouncer.servers[
                                self.username]
                            passmatch = hashlib.new(
                                hashtype, passwd).hexdigest() == passwdhash
                            with self.IRC.lock:
                                if not passmatch:
                                    self.quit("Access Denied")
                                    self.IRC.logwrite(
                                        "*** [BouncerConnection] Incoming connection from %s to %s denied: Invalid password." % (self.host, self.IRC))
                                    for bouncerconnection in self.bouncer.connections:
                                        if bouncerconnection.IRC != self.IRC:
                                            continue
                                        if not bouncerconnection.quitting:
                                            bouncerconnection.send(":*Bouncer* NOTICE %s :Incoming connection from %s to %s dened: Invalid password.\n" % (
                                                bouncerconnection.IRC.identity.nick, self.host, self.IRC))
                                    break

                                self.IRC.logwrite(
                                    "*** [BouncerConnection] Incoming connection from %s to %s." % (self.host, self.IRC))
                                with self.bouncer.lock:
                                    # Announce connection to all other bouncer
                                    # connections.
                                    for bouncerconnection in self.bouncer.connections:
                                        if bouncerconnection.IRC != self.IRC:
                                            continue
                                        if not bouncerconnection.quitting:
                                            bouncerconnection.send(":*Bouncer* NOTICE %s :Incoming connection from %s to %s\n" % (
                                                bouncerconnection.IRC.identity.nick, self.host, self.IRC))
                                    if len([bncconnection for bncconnection in self.bouncer.connections if bncconnection.IRC == self.IRC]) == 0 and self.IRC.registered and type(self.IRC.identity) == irc.User and self.IRC.identity.away:
                                        # Bouncer connection should
                                        # automatically return from away
                                        # status.
                                        self.IRC.raw("AWAY")
                                    self.bouncer.connections.append(self)

                                if self.IRC.registered:
                                    # Send Greeting.
                                    with self.lock:
                                        if self.IRC.welcome:
                                            self.connection.send(":%s 001 %s :%s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.welcome))
                                        if self.IRC.hostinfo:
                                            self.connection.send(":%s 002 %s :%s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.hostinfo))
                                        if self.IRC.servcreated:
                                            self.connection.send(":%s 003 %s :%s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.servcreated))
                                        if self.IRC.servinfo:
                                            self.connection.send(":%s 004 %s %s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.servinfo))

                                        # Send 005 response.
                                        if self.IRC.supports:
                                            supports = ["CHANMODES=%s" % (",".join(value)) if name == "CHANMODES" else "PREFIX=(%s)%s" % value if name == "PREFIX" else "%s=%s" % (
                                                name, value) if value else name for name, value in self.IRC.supports.items()]
                                            supports.sort()
                                            supportsreply = []
                                            supportsstr = " ".join(supports)
                                            index = 0
                                            while True:
                                                if len(supportsstr) - index > 196:
                                                    nextindex = supportsstr.rfind(
                                                        " ", index, index + 196)
                                                    supportsreply.append(
                                                        supportsstr[index:nextindex])
                                                    index = nextindex + 1
                                                else:
                                                    supportsreply.append(
                                                        supportsstr[index:])
                                                    break
                                            for support in supportsreply:
                                                self.connection.send(":%s 005 %s %s :are supported by this server\n" % (
                                                    self.IRC.serv, self.IRC.identity.nick, support))

                                        # Send MOTD
                                        if self.IRC.motdgreet and self.IRC.motd and self.IRC.motdend:
                                            self.connection.send(":%s 375 %s :%s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.motdgreet))
                                            for motdline in self.IRC.motd:
                                                self.connection.send(":%s 372 %s :%s\n" % (
                                                    self.IRC.serv, self.IRC.identity.nick, motdline))
                                            try:
                                                self.connection.send(":%s 376 %s :%s\n" % (
                                                    self.IRC.serv, self.IRC.identity.nick, self.IRC.motdend))
                                            except AttributeError:
                                                self.connection.send(
                                                    ":%s 376 %s\n" % (self.IRC.serv, self.IRC.identity.nick))
                                        else:
                                            self.connection.send(
                                                ":%s 422 %s :MOTD File is missing\n" % (self.IRC.serv, self.IRC.identity.nick))

                                        # Send user modes and snomasks.
                                        self.connection.send(":%s 221 %s +%s\n" % (
                                            self.IRC.serv, self.IRC.identity.nick, self.IRC.identity.modes))

                                        if "s" in self.IRC.identity.modes and self.IRC.identity.snomask:
                                            self.connection.send(":%s 008 %s +%s :Server notice mask\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, self.IRC.identity.snomask))

                                        # Join user to channels.
                                        for channel in self.IRC.identity.channels:
                                            # JOIN command
                                            self.connection.send(":%s!%s@%s JOIN :%s\n" % (
                                                self.IRC.identity.nick, self.IRC.identity.username, self.IRC.identity.host, channel.name))

                                            # Topic
                                            self.connection.send(":%s 332 %s %s :%s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, channel.name, channel.topic))
                                            self.connection.send(":%s 333 %s %s %s %s\n" % (self.IRC.serv, self.IRC.identity.nick, channel.name, channel.topicsetby.nick if type(
                                                channel.topicsetby) == irc.User else channel.topicsetby, channel.topictime))

                                            # Determine if +s or +p modes are
                                            # set in channel
                                            secret = "s" in channel.modes.keys() and channel.modes[
                                                "s"]
                                            private = "p" in channel.modes.keys(
                                            ) and channel.modes["p"]

                                            # Construct NAMES for channel.
                                            namesusers = []
                                            modes, symbols = self.IRC.supports[
                                                "PREFIX"]
                                            self.connection.send(":%s 353 %s %s %s :%s\n" % (
                                                self.IRC.serv,
                                                self.IRC.identity.nick,
                                                "@" if secret else (
                                                    "*" if private else "="),
                                                channel.name,
                                                string.join([string.join([symbols[k] if modes[k] in channel.modes.keys() and user in channel.modes[modes[k]] else "" for k in xrange(len(modes))], "") + user.nick for user in channel.users]))
                                            )
                                            self.connection.send(":%s 366 %s %s :End of /NAMES list.\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, channel.name))
                                else:
                                    self.send(
                                        ":*Bouncer* NOTICE %s :Not connected to server. Type /bncconnect to attempt connection.\n" % self.nick)
                                    self.send(":%s 001 %s :Welcome to the Bouncer IRC Network %s!%s@%s\n" % (
                                        "*Bouncer*", self.nick, self.nick, self.username, self.host))
                        else:  # User not found
                            self.quit("Access Denied")
                            break
                    else:  # Client did not send USER command when expected
                        self.quit("Access Denied")
                        print "*** [BouncerConnection] Incoming connection from %s failed: Expected USER." % (self.host)
                        break

                elif cmd.upper() == "QUIT":
                    self.quit(extinfo)
                    break

                elif cmd.upper() == "PING":
                    self.send(":%s PONG %s :%s\n" %
                              (self.IRC.serv, self.IRC.serv, self.IRC.identity.nick if type(self.IRC.identity) == irc.User else "***"))

                elif cmd.upper() == "BNCCONNECT":
                    with self.IRC.lock:
                        if self.IRC.isAlive() and self.IRC.connected:
                            self.send(
                                ":*Bouncer* NOTICE %s :Bouncer is already connected.\n" % self.nick)
                        else:
                            self.IRC.start()

                elif cmd.upper() == "BNCQUIT":
                    with self.IRC.lock:
                        if self.IRC.isAlive() and self.IRC.connected and self.IRC.registered:
                            quitmsg = " ".join(
                                [word for word in [target, params, extinfo] if word])
                            self.IRC.quit(quitmsg)
                        else:
                            self.send(
                                ":*Bouncer* NOTICE %s :Bouncer is already disconnected.\n" % self.nick)

                else:
                    with self.IRC.lock:
                        if not self.IRC.connected:
                            self.send(
                                ":*Bouncer* NOTICE %s :Not connected to server. Type /bncconnect to attempt connection.\n" % self.nick)
                            break
                        elif not self.IRC.registered:
                            self.send(
                                ":*Bouncer* NOTICE %s :Not registered.\n" % self.nick)
                            break
                        elif cmd.upper() in ("PRIVMSG", "NOTICE"):
                            # Check if CTCP
                            ctcp = re.findall(
                                "^\x01(.*?)(?:\\s+(.*?)\\s*)?\x01$", extinfo)

                            if ctcp:  # If CTCP, only want to
                                (ctcptype, ext) = ctcp[0]  # Unpack CTCP info

                                if ctcptype == "LAGCHECK":  # Client is doing a lag check. No need to send to IRC network, just reply back.
                                    self.send(":%s!%s@%s %s\n" % (
                                        self.IRC.identity.nick, self.IRC.identity.username, self.IRC.identity.host, line))
                                else:
                                    self.IRC.raw(line, origin=self)
                            else:
                                self.IRC.raw(line, origin=self)

                        elif cmd.upper() == "MODE":  # Will want to determine is requesting modes, or attempting to modify modes.
                            if target and "CHANTYPES" in self.IRC.supports.keys() and target[0] in self.IRC.supports["CHANTYPES"]:
                                if params == "":
                                    channel = self.IRC.channel(target)
                                    modes = channel.modes.keys()
                                    modestr = "".join([mode for mode in modes if mode not in self.IRC.supports[
                                                      "CHANMODES"][0] + self.IRC.supports["PREFIX"][0] and channel.modes[mode]])
                                    params = " ".join([channel.modes[mode] for mode in modes if mode in self.IRC.supports[
                                                      "CHANMODES"][1] + self.IRC.supports["CHANMODES"][2] and channel.modes[mode]])
                                    with self.lock:
                                        if len(modestr):
                                            self.connection.send(":%s 324 %s %s +%s %s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, channel.name, modestr, params))
                                        if channel.created:
                                            self.connection.send(":%s 329 %s %s %s\n" % (
                                                self.IRC.serv, self.IRC.identity.nick, channel.name, channel.created))
                                elif re.match("^\\+?[%s]+$" % self.IRC.supports["CHANMODES"][0], params) and extinfo == "":
                                    # print "ddd Mode List Request", params
                                    channel = self.IRC.channel(target)
                                    redundant = []
                                    for mode in params.lstrip("+"):
                                        if mode in redundant or mode not in listnumerics.keys():
                                            continue
                                        i, e, l = listnumerics[mode]
                                        with self.lock:
                                            if mode in channel.modes.keys():
                                                for (mask, setby, settime) in channel.modes[mode]:
                                                    self.connection.send(":%s %d %s %s %s %s %s\n" % (
                                                        self.IRC.serv, i, channel.context.identity.nick, channel.name, mask, setby, settime))
                                            self.connection.send(":%s %d %s %s :End of %s\n" % (
                                                self.IRC.serv, e, channel.context.identity.nick, channel.name, l))
                                        redundant.append(mode)
                                else:
                                    self.IRC.raw(line, origin=self)
                            elif params == "" and target.lower() == self.IRC.identity.nick.lower():
                                with self.lock:
                                    self.connection.send(":%s 221 %s +%s\n" % (
                                        self.IRC.serv, self.IRC.identity.nick, self.IRC.identity.modes))
                                    if "s" in self.IRC.identity.modes and self.IRC.identity.snomask:
                                        self.connection.send(":%s 008 %s +%s :Server notice mask\n" % (
                                            self.IRC.serv, self.IRC.identity.nick, self.IRC.identity.snomask))
                            else:
                                self.IRC.raw(line, origin=self)
                        else:
                            self.IRC.raw(line, origin=self)

        except SystemExit:
            pass  # No need to pass error message if break resulted from sys.exit()
        except:
            exc, excmsg, tb = sys.exc_info()
            self.quitmsg = str(excmsg)
            if self.IRC:
                exc, excmsg, tb = sys.exc_info()
                self.IRC.logwrite(*["!!! [BouncerConnection] Exception in thread %(self)s" % vars()] + [
                                  "!!! [BouncerConnection] %(tbline)s" % vars() for tbline in traceback.format_exc().split("\n")])
        finally:
            # Juuuuuuust in case.
            with self.lock:
                try:
                    self.connection.shutdown(1)
                    self.connection.close()
                except:
                    pass

            if self.IRC:
                self.IRC.logwrite(
                    "*** [BouncerConnection] Connection from %s terminated (%s)." % (self.host, self.quitmsg))

            if self in self.bouncer.connections:
                with self.bouncer.lock:
                    self.bouncer.connections.remove(self)
                    if self.IRC.connected and self.IRC.identity and len([bncconnection for bncconnection in self.bouncer.connections if bncconnection.IRC == self.IRC]) == 0 and self.IRC.registered and type(self.IRC.identity) == irc.User and not self.IRC.identity.away and self.bouncer.autoaway:
                        # Bouncer automatically sets away status.
                        self.IRC.raw("AWAY :%s" % self.bouncer.autoaway)
                    if self.debug:
                        self.IRC.logwrite(
                            "dbg [BouncerConnection] Attempting to broadcast terminated connection %(self)s." % vars())
                    for bouncerconnection in self.bouncer.connections:
                        if bouncerconnection.IRC == self.IRC:
                            if self.debug:
                                self.IRC.logwrite(
                                    "dbg [BouncerConnection] Broadcasting to %(bouncerconnection)s." % vars())
                            if not bouncerconnection.quitting:
                                bouncerconnection.connection.send(":*Bouncer* NOTICE %s :Connection from %s to %s terminated (%s)\n" % (
                                    bouncerconnection.IRC.identity.nick, self.host, self.IRC, self.quitmsg))
                                if self.debug:
                                    self.IRC.logwrite(
                                        "dbg [BouncerConnection] Success: %(bouncerconnection)s." % vars())

# Announce QUIT to other bouncer connections.
#				for bouncerconnection in self.bouncer.connections:
#					try:
#						bouncerconnection.connection.send(":%s!%s@%s QUIT :%s\n" % (self.label, self.username, self.host, self.quitmsg))
#					except:
#						pass
