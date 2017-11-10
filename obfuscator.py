import random
import re
import string
import sys
from datetime import date, datetime, timedelta

igx = re.IGNORECASE


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

    def obfuscate(self, source):
        if "@" not in source:
            raise Exception("not a valid email")
        mailbox = source[:self.source.find("@")]
        domain = source[self.source.find("@"):]
        mailbox = self._obfuscate(mailbox)
        return mailbox + domain


class DateObfuscator(Obfuscrator):

    DATETIME_FORMATS = {
        "timestamp without time zone": "%Y-%m-%d %H:%M:%S.%f",
        "date": "%Y-%m-%d",
    }
    def __init__(self, dt, *args, **kwargs):
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

        return d_parsed.strftime(fmt)


class PGDumpParser(object):

    S = "SALT"
    PG_DATATYPES_TO_OBFUSCATORS = {
        "char": Obfuscrator(S),
        "text": Obfuscrator(S),
        "integer": Obfuscrator(S, string=False),
        "timestamp without time zone": DateObfuscator(S, "timestamp without time zone"),
        "date": DateObfuscator(S, "date"),
    }

    stop_words = ("DEFAULT", "NOT")
    char_types = ("character", "char", "text")

    def __init__(self):
        self.schema = {}
        self.current_table = None
        self.column_idx = 0

    def parse(self, line):
        if self.current_table is None and "CREATE TABLE" in line:
            self.map_schema_table(line)

        # column line
        if self.current_table is not None:
            self.map_schema_column(line)
            self.column_idx += 1

        if ");" in line:
            self.current_table = None
            self.column_idx = 0

    def map_schema_table(self, line):
        create_table = []
        line = line.split()
        for w in line:
            if "CREATE" in create_table and "TABLE" in create_table:
                self.schema[w] = {}
                self.current_table = w
                break
            create_table.append(w)

    def map_schema_column(self, line):
        column_line = line.split()
        column_name = column_line.pop(0)

        if self.is_personal_info(column_name):
            self.map_schema_column_obfuscated(column_name, column_line)

        #XXX TODO
        #if column_name in self.forced

    def map_schema_column_obfuscated(self, column_name, column_line):
        obfuscator = None
        column_data_type = []

        for w in column_line:
            if w in self.stop_words:
                break
            column_data_type.append(w)
        column_data_type = " ".join(column_data_type)
        if column_data_type[-1] == ",":
            column_data_type = column_data_type[:-1]

        # check if the column is a string
        for char in self.char_types:
            if re.match(char, column_data_type, igx):
                column_data_type = "char"
                break

        if re.match("email", column_name, igx) and column_data_type == "char":
            obfuscator = EmailObfuscator(self.S)

        if obfuscator is None:
            obfuscator = self.PG_DATATYPES_TO_OBFUSCATORS.get(
                column_data_type,
                None,
            )

        if obfuscator is None:
            msg = "PG datatype: {} not configured".format(column_data_type)
            raise Exception(msg)

        column_info = {self.column_idx: (column_name, obfuscator)}
        self.schema[self.current_table].update(column_info)

    def is_personal_info(self, column_name):
        possible = [
            "first_name",
            "last_name",
            "midle_name",
            "ssn",
            "social_security",
            "zip_code",
            "email",
            "date_of_birth",
            "birth_date",
        ]

        for p in possible:
            if re.match(p, column_name, igx):
                return True
            p = filter(lambda char: char not in " _", p)
            if re.match(p, column_name, igx):
                return True
        return False


class PGDumpObfuscator(object):
    ENDLINE = "\\.\n"
    COPY_DELIM = "\t"

    def __init__(self, dump_file, parser):
        self.dump_file = dump_file
        self.parser = parser

    def get_table(self, line):
        table = line.split(" ")[1]
        return table
        #return self.parser.schema.get(table, None)

    def obfuscate_line(self, table, line):
        column_info = self.parser.schema[table]

        new_line = []
        import ipdb; ipdb.set_trace()
        for idx, f in enumerate(line.split(self.COPY_DELIM)):
            f = f.strip()
            if idx in column_info:
                column_name, obfuscator = column_info[idx]

                #XXX add logic to `remember' what we casted.
                f = obfuscator.obfuscate(f)
            new_line.append(f)

        new_line = self.COPY_DELIM.join(new_line)
        print new_line
        return new_line

    def run(self):

        current_table = None
        should_parse = True
        got_tables = []
        with open(self.dump_file, "r") as of:
            for line in of:

                if should_parse:
                    self.parser.parse(line)

                if line[:4] == "COPY":
                    current_table = self.get_table(line)
                    should_parse = False

                if line[:4] != "COPY" and current_table in self.parser.schema.keys():
                    print line
                    line = self.obfuscate_line(current_table, line)

                if self.ENDLINE in line:
                    current_table = None
                sys.stdout.write(line)


if __name__ == "__main__":
    dump_file = "DUMP.dump"
    parser = PGDumpParser()
    app = PGDumpObfuscator(dump_file, parser)
    app.run()
