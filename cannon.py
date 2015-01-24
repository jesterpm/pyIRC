#!/usr/bin/python

import re
import os


class Cannon(object):

    def __init__(self):
        self.firecount = {}

    def onChanMsg(self, context, user, channel, targetprefix, msg):
        matches = re.findall("^!fire\\s+(\\S+)", msg)
        if matches:
            nickname = matches[0]
            if any([nickname.lower() == usr.nick.lower() for usr in channel.users]):
                vic = context.user(nickname)
                if vic in self.firecount.keys():
                    count = self.firecount[vic] + 1
                else:
                    count = 1
                self.firecount[vic] = count
                if 10 <= count % 100 < 20:
                    ordinal = "th"
                elif count % 10 == 1:
                    ordinal = "st"
                elif count % 10 == 2:
                    ordinal = "nd"
                elif count % 10 == 3:
                    ordinal = "rd"
                else:
                    ordinal = "th"
                channel.me("fires %s out of a cannon for the %d%s time." %
                           (vic.nick, count, ordinal))
            else:
                channel.msg(
                    "%s: I cannot fire %s out of a cannon, as he or she is not here." %
                    (user.nick, nickname))

    def onSendChanMsg(self, context, origin, channel, targetprefix, msg):
        self.onChanMsg(context, context.identity, channel, targetprefix, msg)
