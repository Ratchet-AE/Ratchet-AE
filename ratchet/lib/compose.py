"""Three-prefix archive, deduplication, local failure and checkpoint backtracking."""
from copy import deepcopy
import json
def primitives(test, dut):
    """Extract the configured DUT's stimulus units."""
    from ..dut_api import load_dut
    return load_dut(dut)[1].primitives(test)

def compose(prefix, segment, dut):
    """Join a frozen prefix to a DUT stimulus."""
    from ..dut_api import load_dut
    return load_dut(dut)[1].splice_prefix(prefix, segment)

class Archive:
    def __init__(self):self.entries={};self.current={};self.failures={};self.calls=0
    def add(self,checkpoint,prefix,state):
        entries=self.entries.setdefault(checkpoint,[]);key=json.dumps(state,sort_keys=True)
        if any(e['state_key']==key for e in entries):return False
        if len(entries)>=3:return False
        entries.append(dict(prefix=deepcopy(prefix),state=deepcopy(state),state_key=key,failed=False));return True
    def selected(self,checkpoint):
        entries=self.entries.get(checkpoint,[]);idx=self.current.get(checkpoint,0)
        return entries[idx] if entries and idx<len(entries) and not entries[idx]['failed'] else None
    def failed(self,checkpoint):
        self.failures[checkpoint]=self.failures.get(checkpoint,0)+1
        if self.failures[checkpoint]<3:return checkpoint
        self.failures[checkpoint]=0;entries=self.entries.get(checkpoint,[]);idx=self.current.get(checkpoint,0)
        if entries and idx<len(entries):entries[idx]['failed']=True
        for i,e in enumerate(entries):
            if not e['failed']:self.current[checkpoint]=i;return checkpoint
        return max(-1,checkpoint-1)
    def should_switch(self,target_hit=False):return target_hit or self.calls>=15
def request_context(target,chain,diagnostic,confirmed,prefix,state):
    return dict(target=target,checkpoint_chain=chain,frontier=diagnostic.get('frontier',-1),progress_peak=diagnostic.get('progress_peak'),confirmed_regressions=confirmed,prefix_summary=dict(n_primitives=len(prefix),register_state=state),instruction='Return only the DSL segment from the current checkpoint to its immediate next checkpoint. The stored prefix is replayed unchanged.')
