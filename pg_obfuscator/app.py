from __future__ import absolute_import
import sys

from .parser import PGDumpParser


class PGDumpObfuscator(object):
    COPY_DELIM = "\t"
    ENDLINE = "\\."
    NULL = "\\N"

    def __init__(self, dump_file, parser, foreign_keys=None):
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

        self.foreign_keys = [fk.split("=") for fk in self.foreign_keys]

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
        if self.foreign_keys is not None:
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
