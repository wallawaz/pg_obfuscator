from datetime import datetime, timedelta
import random
import string


class Obfuscrator(object):
    def __init__(self, salt, string=True):
        #XXX do we need a salt?
        self.salt = salt
        #self.source
        self.string = string

    def _obfuscate(self, source):
        out = []
        if self.string:
            chars_to_pick_from = string.letters
        else:
            chars_to_pick_from = string.digits
        for char in source:
            out.append(random.choice(chars_to_pick_from))
        return "".join(out)

    def obfuscate(self, source):
        return self._obfuscate(source)


class EmailObfuscator(Obfuscrator):
    domains = [
        "gmail.com",
        "yahoo.com",
        "example.com",
        "important.com",
        "foo.com",
    ]
    def obfuscate(self, source):
        if "@" not in source:
            raise Exception("not a valid email")
        mailbox = source.split("@")[0]
        mailbox = self._obfuscate(mailbox)
        domain = random.choice(self.domains)
        return mailbox + "@" + domain


class DateObfuscator(Obfuscrator):

    DATETIME_FORMATS = {
        "timestamp without time zone": "%Y-%m-%d %H:%M:%S.%f",
        "date": "%Y-%m-%d",
    }
    def __init__(self, *args, **kwargs):
        args = list(args)
        dt = args.pop(-1)
        super(DateObfuscator, self).__init__(*args, **kwargs)
        self.dt = dt
        self.fmt = None

    def _get_fmt(self):
        try:
            self.fmt = self.DATETIME_FORMATS[self.dt]
        except KeyError:
            raise Exception("Invalid date format")

    def obfuscate(self, source):
        if self.fmt is None:
            self._get_fmt()

        d_parsed = datetime.strptime(source, self.fmt)
        plus_or_minus = random.choice(("+", "-"))
        delta = random.randrange(1, 10000)

        if plus_or_minus == "+":
            d_parsed = d_parsed + timedelta(days=delta)
        else:
            d_parsed = d_parsed - timedelta(days=delta)

        return d_parsed.strftime(self.fmt)
