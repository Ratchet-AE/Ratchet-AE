"""Verified runtime loading; mutation after static freeze is rejected."""
from pathlib import Path
import json,hashlib

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class Bundle:
    def __init__(self,path):
        self.path=Path(path);self.hashes=json.loads((self.path/'runtime_hashes.json').read_text())
        self.verify()
        self.cards={p.stem:json.loads(p.read_text()) for p in (self.path/'cards').glob('*.yaml')}
        self.dag=json.loads((self.path/'dag.json').read_text());self.conditions=json.loads((self.path/'conditions.json').read_text());self.specs=json.loads((self.path/'bin_specs.json').read_text())
    def verify(self):
        for rel,h in self.hashes.items():
            if sha(self.path/rel)!=h:raise ValueError('M1 artifact hash mismatch: '+rel)
    @property
    def identity(self):return hashlib.sha256(json.dumps(self.hashes,sort_keys=True).encode()).hexdigest()
