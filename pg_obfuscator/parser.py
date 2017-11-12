from __future__ import absolute_import
import re

from .obfuscators.obfuscators import (
    Obfuscrator,
    EmailObfuscator,
    DateObfuscator,
)
igx = re.IGNORECASE


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


    def __init__(self, foreign_keys=None):
        self.schema = {}
        self.current_table = None
        self.column_idx = 0
        self.foreign_keys = foreign_keys
        if self.foreign_keys is not None:
            self.map_fk_schema()

    def map_fk_schema(self):
        """If self.foreign_keys are set. Add the these tables to the schema"""
        self.foreign_keys = [fk.split("=") for fk in self.foreign_keys]

        for fk in self.foreign_keys:
            left, right = fk
            for fk in (left, right):
                table_name, column_name = fk.split(".")
                self.schema[table_name] = {
                    column_name: (column_name, Obfuscrator(self.S))
                }
        self.foreign_keys = [item for sublist in self.foreign_keys \
                                for item in sublist]

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
        if self.foreign_keys and possible_cache_key in self.foreign_keys:
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

