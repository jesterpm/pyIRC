#!/usr/bin/python
import re

"""
DeployerBot sends fires webhooks on command. Although you could really do
anything with a webhook, the intent is to trigger deployments. Therefore the
webhooks are designed mimic GitHub push events.

DeployerBot responds to private messages or channel messages prefixed with the
bot's nick. It will respond to the follow commands:

    * deploy <application>
    * list webhooks
    * add webhook for <application> with url <url> and secret <secret>
    * remove webhook for <application>
"""
class DeployerBot:
    def __init__(self):
        self.__name__ = "DeployerBot"
        self.__version__ = "0.0.1"
        self.deploy_pattern = re.compile(r"deploy (?:(?:the )?application )?(\S+)", re.IGNORECASE)
        self.list_pattern = re.compile(r"list (?:.* )?webhooks", re.IGNORECASE);
        self.add_pattern = re.compile(r"add (?:.* )?webhook (?:(?:.* )?(?:application|for) )?(\S+) (?:(?:.* )?(?:url|address) )?(\S+) (?:(?:.* )secret )?(\S+)", re.IGNORECASE)

        self.applications = dict()

    def onPrivMsg(self, IRC, user, msg):
        self.processMsg(IRC, user, user, msg)

    def onChanMsg(self, IRC, user, channel, targetprefix, msg):
        name_pattern = r"^" + re.escape(IRC.identity.nick) + r"[,:! ]"
        if re.match(name_pattern, msg, re.IGNORECASE):
            self.processMsg(IRC, user, channel, msg)

    """
    Process a message addressed to the bot.
        * IRC is the main IRC object.
        * sender is the User object representing the sender.
        * dest is where to send the response. It may be any object with a msg method.
        * msg is the message received.
    """
    def processMsg(self, IRC, sender, dest, msg):
        matches = self.deploy_pattern.findall(msg)
        if matches is not None:
            for application in matches:
                self.deploy(IRC, sender, dest, application)
                return

        if self.list_pattern.findall(msg):
            self.listWebHooks(IRC, sender, dest)
            return

        matches = self.add_pattern.findall(msg)
        if matches is not None:
            for application, url, secret in matches:
                self.addApplication(IRC, sender, dest, application, url, secret)
                return

    def deploy(self, IRC, sender, dest, application):
        dest.msg("Ok, I will deploy %s" % application)


    def listWebHooks(self, IRC, sender, dest):
        if self.applications:
            msg = "I know the following applications: " + ", ".join([app for (app, url, key) in self.applications.values()])
            dest.msg(msg)
        else:
            dest.msg("I don't have any hooks :(")

    def addApplication(self, IRC, sender, dest, application, url, secret):
        key = application.lower()
        if key in self.applications:
            dest.msg("I already have an application called %s" % application)
        else:
            self.applications[key] = (application, url, secret)
            dest.msg("I've added application %s" % application)
