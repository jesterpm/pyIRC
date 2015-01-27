import hmac, hashlib
import json
import re
import requests

"""
DeployerBot sends fires webhooks on command. Although you could really do
anything with a webhook, the intent is to trigger deployments. Therefore the
webhooks are designed mimic GitHub push events.

DeployerBot responds to private messages or channel messages prefixed with the
bot's nick. It will respond to the follow commands:

    * deploy <application>
    * list webhooks
    * add webhook <application> for <repository> with url <url> and secret <secret>
    * remove webhook for <application>
"""
class DeployerBot:
    def __init__(self):
        self.__name__ = "DeployerBot"
        self.__version__ = "0.0.1"
        self.deploy_pattern = re.compile(r"deploy (?:(?:the )?application )?(\S+)", re.IGNORECASE)
        self.list_pattern = re.compile(r"list (?:.* )?webhooks", re.IGNORECASE);
        self.add_pattern = re.compile(r"add (?:.* )?webhook " \
                                      r"(?:(?:.* )?(?:application|for|named) )?(\S+) " \
                                      r"(?:(?:.* )?repo(?:sitory)? )?(\S+) " \
                                      r"(?:(?:.* )?(?:url|address) )?(\S+) " \
                                      r"(?:(?:.* )?secret )?(\S+)", re.IGNORECASE)

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
            for application, repo, url, secret in matches:
                self.addApplication(IRC, sender, dest, application, repo, url, secret)
                return

    def deploy(self, IRC, sender, dest, application):
        key = application.lower()
        if key not in self.applications:
            dest.msg("I don't know how to deploy %s" % application, origin=self)
            return

        app, repo, url, secret = self.applications[key]
        dest.msg("Ok, I'm deploying %s..." % application, origin=self)

        payload = {
                    "ref": "refs/heads/master",
                    "repository": {
                        "name": repo,
                        "clone_url": "https://github.com/%s.git" % repo,
                    }
                  }
        data = json.dumps(payload)

        headers = {'content-type': 'application/json', 'X-GitHub-Event': 'push'}
        if secret:
            digest = hmac.new(secret.encode(), data.encode(), hashlib.sha1)
            headers['X-Hub-Signature'] = "sha1=" + digest.hexdigest()

        r = requests.post(url, data=data, headers=headers)

        if r.status_code == requests.codes.ok:
            dest.msg("I successfully deployed %s" % application, origin=self)
        else:
            dest.msg("I failed to deploy %s. I got HTTP status code %d" \
                      % (application, r.status_code), origin=self)


    def listWebHooks(self, IRC, sender, dest):
        if self.applications:
            msg = "I know the following applications: " \
                  ", ".join([app for (app, repo, url, key) in self.applications.values()])
            dest.msg(msg, origin=self)
        else:
            dest.msg("I don't have any hooks :(", origin=self)

    def addApplication(self, IRC, sender, dest, application, repo, url, secret):
        key = application.lower()
        if key in self.applications:
            dest.msg("I already have an application called %s" % application, origin=self)
        else:
            self.applications[key] = (application, repo, url, secret)
            dest.msg("I've added application %s" % application, origin=self)
