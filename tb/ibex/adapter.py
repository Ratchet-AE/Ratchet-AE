"""Convert assembly candidates to test stimuli and expose DUT-specific hooks."""
from copy import deepcopy
import re
from ratchet.dut_api import DUTAdapter


class Adapter(DUTAdapter):
    """Provide assembly handling and target-event interpretation."""
    def __init__(self, config, root):
        super().__init__(config, root)

    def candidates(self, response, level):
        if level == 'esc':
            return response['candidates']
        return [{'primary_target': '', 'rationale': response['rationale'], 'suffix': response['asm']}]

    def check_prefix(self, units, index):
        from ratchet.lib.labels import checked_cut
        return checked_cut(units, index)

    def primitives(self, stimulus):
        return stimulus['asm'].splitlines(keepends=True)

    def build_stimulus(self, candidate):
        return {'asm': candidate['suffix'], 'rationale': candidate['rationale']}

    def splice_prefix(self, prefix, stimulus):
        from ratchet.lib.labels import join
        result = deepcopy(stimulus)
        result['asm'] = join(prefix, result['asm'])
        return result

    def count_instructions(self, fragment):
        total = 0
        for line in fragment.splitlines():
            line = line.split('#', 1)[0].strip()
            line = re.sub(r'^(?:[A-Za-z_.$][\w.$]*|[0-9]+):\s*', '', line).strip()
            if line and not line.startswith('.'):
                total += 1
        return total

    def exempt_self_induced_exception(self, clear_event, target_event):
        index = clear_event.get('index')
        return index is not None and index == target_event.get('index')

    def key_state_registers(self, state=None):
        return tuple((state or {}).keys())

    def support_components(self):
        return {'policy': Policy, 'archives': Archives, 'bisector': Bisector, 'params': PARAMS}

    def read_trace(self, output, stimulus):
        return read_trace_ibex(output, stimulus, self.name)


"""DUT-specific fixed parameters and assembly adapters; no generated stimulus."""
from ratchet.core import priority,compact,one_loss,count
from ratchet import core
from ratchet.components.m3_repair import primitives
PARAMS=dict(core.PARAMS,tau=4,L_min=40)
def instructions(asm):
 import re
 total=0
 for line in asm.splitlines():
  line=line.split('#',1)[0].strip()
  line=re.sub(r'^(?:[A-Za-z_.$][\w.$]*|[0-9]+):\s*','',line).strip()
  if line and not line.startswith('.'):total+=1
 return total
def units(test):return primitives(test,'ibex')
class Policy(core.Policy):
 def tier0(self,gain):
  self.gains.append(gain)
  if self.method!='r_t0' and len(self.gains)>=2 and max(self.gains[-2:])<PARAMS['tau']:self.upgraded=True
class Archives(core.Archives):
 def choose(self,chain,target,max_frontier=None):
  from ratchet.core import cp_key
  upper=len(chain)-1 if max_frontier is None else min(max_frontier,len(chain)-1)
  for idx in range(upper,-1,-1):
   key=cp_key(chain[idx])
   for slot,e in enumerate(self.entries[key]):
    if (key,slot) not in self.used[target] and instructions(''.join(e['prefix']))<=1960:
     if e['owner']!=target:self.event('archive_shared',target=target,owner=e['owner'],predicate=key)
     return idx,key,slot,e
  return -1,None,None,dict(prefix=[],state={})
class Bisector(core.Bisector):
 def confirm(self,test,event,replay):return super().confirm(dict(inputs=units(test)),event,replay)
def read_trace_ibex(out,test,dut):
 import json,bisect
 from pathlib import Path
 from ratchet.components.monitors.source_map import source_map
 from ratchet.slicing.tracker import X
 out=Path(out)
 if not (out/'trace.jsonl').exists():
  raw=next(out.glob('trace_core*.log'))
  with (out/'trace.jsonl').open('w') as f:
   for line in raw.open():
    cols=line.split()
    if len(cols)>3 and cols[0].isdigit():f.write(json.dumps(dict(cycle=int(cols[1]),pc=cols[2],instruction=cols[3]))+'\n')
 mapping=source_map(out,test)
 boundaries=[dict(r,index=mapping[r['pc']]) for r in (json.loads(l) for l in (out/'trace.jsonl').open()) if r['pc'] in mapping]
 if not boundaries:return []
 cycles=[r['cycle'] for r in boundaries];initial=[];rows=[]
 for line in (out/'m1_changes.jsonl').open():
  row=json.loads(line);i=bisect.bisect_right(cycles,row['cycle'])-1
  if i<0:
   row['index']=-1;initial.append(row)
  else:row['index']=boundaries[i]['index'];rows.append(row)
 # Preserve reset/template state for predicates without introducing a candidate prefix.
 result=initial+rows
 for parent in out.parents:
  manifest=parent/'monitor/ibex_signals.json'
  if manifest.exists():result[0]['_enums']=json.loads(manifest.read_text()).get('enum_values',{});break
 return result
