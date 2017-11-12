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


    def __init__(self, foreign_keys=[]):
        self.schema = {}
        self.current_table = None
        self.column_idx = 0
        self.foreign_keys = foreign_keys
        if self.foreign_keys is not None:
            self.map_fk_schema()

    def map_fk_schema(self):
        self.foreign_keys = [item for sublist in self.foreign_keys for item in sublist]
        for f in self.foreign_keys:
            table_name, column_name = f.split(".")
            self.schema[table_name] = {
                column_name: (column_name, Obfuscrator(self.S))
            }

    def parse(self, line):
        create = "CREATE TABLE"
        if self.current_table is None and create in line:
            self.map_schema_table(line)

        # column line
        if self.current_table is not None and create not in line:
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
                if w not in self.schema:
                    self.schema[w] = {}
                self.current_table = w
                break
            create_table.append(w)

    def map_schema_column(self, line):
        column_line = line.split()
        column_name = column_line.pop(0)

        if self.is_personal_info(column_name):
            self.map_schema_column_obfuscated(column_name, column_line)

        # account for forced FKs
        possible_cache_key = self.current_table + "." + column_name
        if possible_cache_key in self.foreign_keys:
            # remove the column_name from schema.table_name
            # this dict is index based.
            column_info = self.schema[self.current_table].pop(column_name)
            obfuscator = column_info[-1]
            column_info = {
                self.column_idx: (column_name, obfuscator),
            }
            self.schema[self.current_table].update(column_info)

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
            "middle_name",
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
    COPY_DELIM = "\t"
    ENDLINE = "\\."
    NULL = "\\N"

    def __init__(self, dump_file, parser, foreign_keys=[]):
        self.dump_file = dump_file
        self.parser = parser
        self.foreign_keys = foreign_keys
        self.cache = {}
        self.cache_set = set([])

    def get_table(self, line):
        table = line.split(" ")[1]
        return table

    def _set_cache_keys(self):

        _has_schema = lambda x: len(x) == 3
        #XXX TODO support schema names

        for fk_pair in self.foreign_keys:
            _cache_key = []
            for fk in fk_pair:
                fk = fk.split(".")
                if _has_schema(fk):
                    _schema, table_name, column_name = fk
                else:
                    table_name, column_name = fk
                k = self._get_cache_key_name(table_name, column_name)
                self.cache_set.add(k)
                # flat set of all cache keys
                _cache_key.append(k)

            _cache_key = tuple(_cache_key)
            self.cache[_cache_key] = {}

    def _get_cache_key_name(self, table_name, column_name):
        return table_name + "." + column_name

    def _get_cache_tuple_key(self, k):
        for cache_tuple in self.cache:
            if k in cache_tuple:
                return cache_tuple
        return None

    def _cacheable(self, cache_key):
        return cache_key in self.cache_set

    def _loadible_from_cache(self, cache_tuple, old_value):
        return old_value in self.cache[cache_tuple]

    def _load_from_cache(self, cache_tuple, old_value):
        return self.cache[cache_tuple][old_value]

    def obfuscate_line(self, table, line):
        column_info = self.parser.schema[table]

        line_split = line.split(self.COPY_DELIM)
        new_line = []
        for idx, f in enumerate(line_split):
            f = f.strip()

            if idx not in column_info or f == self.NULL:
                new_line.append(f)
                continue

            column_name, obfuscator = column_info[idx]
            possible_cache_key = self._get_cache_key_name(table, column_name)

            if not self._cacheable(possible_cache_key):
                new_line.append(obfuscator.obfuscate(f))
                continue

            out_value = self.load_or_set(possible_cache_key, obfuscator, f)
            new_line.append(out_value)

        new_line = self.COPY_DELIM.join(new_line)
        return new_line

    def load_or_set(self, cache_key, obfuscator, value):
        """
        Determine if a value should be obfuscated and set in the cache.
        Or, if this value has already been obfuscated then load.
        """
        cache_tuple = self._get_cache_tuple_key(cache_key)

        if self._loadible_from_cache(cache_tuple, value):
            return self._load_from_cache(cache_tuple, value)

        out_value = obfuscator.obfuscate(value)
        self.cache[cache_tuple][value] = out_value
        return out_value

    def run(self):
        if self.foreign_keys:
            self._set_cache_keys()

        current_table = None
        should_parse = True
        line_number = 0
        with open(self.dump_file, "r") as of:
            for line in of:

                if should_parse:
                    self.parser.parse(line)

                if line.startswith(self.ENDLINE):
                    current_table = None

                if line[:4] == "COPY":
                    current_table = self.get_table(line)
                    # Hit the COPY statement.
                    # Do not need to parse schema anymore
                    should_parse = False

                if line[:4] != "COPY" and current_table in self.parser.schema.keys():
                    line = self.obfuscate_line(current_table, line)
                    line = line + "\n"

                sys.stdout.write(line)
                line_number += 1


if __name__ == "__main__":
    dump_file = "DUMP.dump"
    foreign_keys = [("activations.member_id", "member_ids.member_id")]
    parser = PGDumpParser(foreign_keys=foreign_keys)

    app = PGDumpObfuscator(dump_file, parser, foreign_keys=foreign_keys)
    app.run()
