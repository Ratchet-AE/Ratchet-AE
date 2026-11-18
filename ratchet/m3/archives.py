"""Immutable prefixes keyed by (checkpoint, lock signature, state hash)."""
from copy import deepcopy
import json,hashlib

def stable(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def matching(observed,required):return all(k in observed and observed[k]==v for k,v in required.items())
class Archives:
    def __init__(self,state=None):self.state=deepcopy(state) if state else dict(entries=[],rejected={})
    def add(self,checkpoint,sigma,state,prefix,owner,source,index=-1,global_gate=False):
        keyhash=hashlib.sha256(stable(state).encode()).hexdigest();signature=stable(sigma)
        slots=[v for v in self.state['entries'] if v['checkpoint']==checkpoint and stable(v['sigma'])==signature]
        if len(slots)>=3 or any(v['state_hash']==keyhash for v in slots):return None
        identity=hashlib.sha256(stable([checkpoint,sigma,keyhash]).encode()).hexdigest()
        entry=dict(id=identity,checkpoint=checkpoint,sigma=deepcopy(sigma),state_hash=keyhash,key_state=deepcopy(state),prefix=deepcopy(prefix),owner=owner,source=source,index=index,global_gate=global_gate)
        self.state['entries'].append(entry);return deepcopy(entry)
    def choose(self,chain,sigma_required,owner,max_index=None):
        rejected=self.state['rejected'].get(owner,[])
        for position in range(len(chain)-1,-1,-1):
            for entry in self.state['entries']:
                if (entry['checkpoint']==chain[position] or chain[position] in entry.get('held_checkpoints',[])) and matching(entry['sigma'],sigma_required) and entry['id'] not in rejected and (max_index is None or entry['index']<=max_index):
                    result=deepcopy(entry);result['checkpoint']=chain[position];return result
        return None
    def reject(self,owner,entry):
        rejected=self.state['rejected'].setdefault(owner,[])
        if entry and entry['id'] not in rejected:rejected.append(entry['id'])
    def serialize(self):return deepcopy(self.state)
