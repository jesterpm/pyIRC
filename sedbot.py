#!/usr/bin/python
import os
import re
import time


class SED(object):
    def __init__(self, expiry=1800):
        self.__name__ = "SED Bot"
        self.__version__ = "0.0.2"
        self.expiry = expiry
        self.history = []
        self.trigger = r"^!?s([,/#])(.*)$"
        self.pattern = r"^((?:[^%(delimiter)s]|\\.)*)%(delimiter)s((?:[^%(delimiter)s]|\\.)*)%(delimiter)s([igv]*)$"

    def onChanMsg(self, IRC, user, channel, targetprefix, msg):
        matches = re.findall(self.trigger, msg)
        if matches:
            delimiter, args = matches[0]
            validate = re.findall(self.pattern%vars(), args)
            if validate:
                find, replace, flags = validate[0]
                find = re.sub(r"\\([,/#\\])", r"\1", find)
                replace = re.sub(r"\\([,/#\\])", r"\1", replace)
                if "v" in flags:
                    channel.msg("Delimiter: '%s', Search pattern: '%s', Replacement: '%s', Flags: '%s'" % (delimiter, find, replace, flags), origin=self)
                match = False
                for t, IRC2, user2, channel2, targetprefix2, msg2, isaction in self.history.__reversed__():
                    if channel != channel2:
                        continue
                    try:
                        if re.findall(find, msg2, flags=re.I if "i" in flags else 0):
                            sub = re.sub(find, replace, msg2, flags=re.I if "i" in flags else 0)
                            match = True
                        else:
                            continue
                    except:
                        channel.msg("%s: Invalid syntax" %
                                    user.nick, origin=self)
                        raise
                    if isaction:
                        channel.msg("What %s really meant was: *%s %s" % (user2.nick, user2.nick, sub), origin=self)
                    else:
                        channel.msg("What %s really meant to say was: %s" % (user2.nick, sub), origin=self)
                    break
                if not match:
                    channel.msg("%s: I tried. I really tried! But I could not find the pattern: %s" % (user.nick, find), origin=self)
            else:
                channel.msg("%s: Invalid syntax. Did you forget a trailing delimiter?" % user.nick, origin=self)
        else:
            self.history.append((time.time(
            ), IRC, user, channel, targetprefix, msg, False))
        while len(self.history) and self.history[0][0] < time.time()-1800:
            del self.history[0]

    def onSendChanMsg(self, IRC, origin, channel, targetprefix, msg):
        if origin != self:  # Ignore messages sent from THIS addon.
            self.onChanMsg(IRC, IRC.identity, channel, targetprefix, msg)

    def onChanAction(self, IRC, user, channel, targetprefix, action):
        self.history.append((time.time(
        ), IRC, user, channel, targetprefix, action, True))
        while len(self.history) and self.history[0][0] < time.time()-1800:
            del self.history[0]

    def onSendChanAction(self, IRC, origin, channel, targetprefix, action):
        if origin != self:  # Ignore messages sent from THIS addon.
            self.onChanAction(IRC, IRC.identity, channel, targetprefix, action)
