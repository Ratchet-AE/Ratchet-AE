from functools import lru_cache
from .common import X,parse_obj,check_schema,ParseError
@lru_cache(None)
def addresses():
    from common.tlul.regmap import RegisterMap
    return frozenset(RegisterMap(X/'third_party/opentitan','entropy_src').by_address)
def check(test):
    errors=check_schema(test,'es')
    if errors: return errors
    for i,op in enumerate(test['ops']):
        if 'addr' in op and op['addr'] not in addresses(): errors.append(f'ops[{i}]: address not in entropy_src.hjson register table')
        for k in ('mask','val'):
            if k in op and not 0<=op[k]<=0xffffffff: errors.append(f'ops[{i}].{k}: outside uint32')
    return errors
def parse(obj):
    test=parse_obj(obj,'es');errors=check(test)
    if errors: raise ParseError('\n'.join(errors))
    return test
def to_driver(test): return parse(test)
