#!/usr/bin/python
import re
import irc


class Autoexec(object):
    def __init__(self):
        self.networks = {}

    def onAddonAdd(self, IRC, label, onconnect=None, onregister=None, autojoin=None, usermodes=None, wallet=None, opername=None, opermodes=None, snomasks=None, operexec=None, operjoin=None):
        labels = [v[0] for v in self.networks.values()]
        if label in labels:
            raise BaseException("Label already exists")
        if IRC in self.networks.keys():
            raise BaseException("Network already exists")
        self.networks[IRC] = (label, onconnect, onregister, autojoin, usermodes, wallet, opername, opermodes, snomasks, operexec, operjoin)

    def onAddonRem(self, IRC):
        del self.networks[IRC]

    def onConnect(self, IRC):
        (label, onconnect, onregister, autojoin, usermodes, wallet, opername, opermodes, snomasks, operexec, operjoin) = self.networks[IRC]
        if onconnect:
            for line in onconnect:
                IRC.raw(line, origin=self)

    def onRegistered(self, IRC):
        (label, onconnect, onregister, autojoin, usermodes, wallet, opername, opermodes, snomasks, operexec, operjoin) = self.networks[IRC]
        if onregister:
            for line in onregister:
                IRC.raw(line, origin=self)
        if usermodes:
            IRC.raw("MODE %s %s"%(IRC.identity.nick, usermodes), origin=self)
        if opername and wallet and "%s/opers/%s"%(label, opername) in wallet.keys():
            IRC.raw("OPER %s %s"%(opername, wallet[
                "%s/opers/%s"%(label, opername)]), origin=self)
        if autojoin:
            IRC.raw("JOIN %s"%(",".join(autojoin)), origin=self)

    def on381(self, IRC, line, origin, target, params, extinfo):
        (label, onconnect, onregister, autojoin, usermodes, wallet, opername, opermodes, snomasks, operexec, operjoin) = self.networks[IRC]
        if operexec:
            for line in operexec:
                IRC.raw(line, origin=self)
        if opermodes:
            IRC.raw("MODE %s %s"%(IRC.identity.nick, opermodes), origin=self)
        if snomasks:
            IRC.raw("MODE %s +s %s"%(IRC.identity.nick, snomasks), origin=self)
        if operjoin:
            IRC.raw("JOIN %s"%(",".join(operjoin)), origin=self)


class NickServ(object):
    def __init__(self):
        self.networks = {}

    def onAddonAdd(self, IRC, label, wallet=None, autojoin=None):
        labels = [v[0] for v in self.networks.values()]
        #print labels
        if label in labels:
            raise BaseException("Label already exists")
        if IRC in self.networks.keys():
            raise BaseException("Network already exists")
        self.networks[IRC] = (label, wallet, autojoin)

    def onAddonRem(self, IRC):
        del self.networks[IRC]

    def onPrivNotice(self, IRC, origin, msg):
        label, wallet, autojoin = self.networks[IRC]
        if type(origin) == irc.User and origin.nick.lower() == "nickserv":
            if re.match("This nickname is registered( and protected)?", msg) and wallet and "%s/NickServ/%s"%(label, IRC.identity.nick.lower()) in wallet.keys():
                origin.msg("identify %s" % wallet["%s/NickServ/%s" %
                                                  (label, IRC.identity.nick.lower())])
            if re.match("You are now identified", msg):
                if autojoin:
                    IRC.raw("JOIN %s"%(",".join(autojoin)), origin=self)

    def on900(self, IRC, line, origin, target, params, extinfo):
        label, wallet, autojoin = self.networks[IRC]
        if autojoin:
            IRC.raw("JOIN %s"%(",".join(autojoin)), origin=self)
