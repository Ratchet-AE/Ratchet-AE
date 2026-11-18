from pathlib import Path
from copy import deepcopy
import json
import jsonschema
X=Path(__file__).resolve().parents[1]
class ParseError(ValueError): pass
class CompileError(RuntimeError): pass
def parse_obj(obj,dut):
    if isinstance(obj,str):
        try: obj=json.loads(obj)
        except ValueError as e: raise ParseError('invalid JSON: '+str(e)) from e
    errors=check_schema(obj,dut)
    if errors: raise ParseError('\n'.join(errors))
    return deepcopy(obj)
def check_schema(obj,dut):
    schema=json.loads((X/f'llm/schemas/{dut}_test.json').read_text())
    return [f'{list(e.absolute_path)}: {e.message}' for e in jsonschema.Draft202012Validator(schema).iter_errors(obj)]
