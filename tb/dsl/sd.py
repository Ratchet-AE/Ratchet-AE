from .common import parse_obj,check_schema
def parse(obj): return parse_obj(obj,'sd')
def check(test): return check_schema(test,'sd')
def to_driver(test): return parse(test)
