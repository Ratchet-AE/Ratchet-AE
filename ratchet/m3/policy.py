"""Frozen tau/shrink/stall/dry sequence, checkpoint switches resolved by caller."""
class Policy:
    def __init__(self,params,state=None):
        self.params=params;self.state=state or dict(gains=[],upgraded=False,shrunken=False,no_progress=0,single_stall=0,dry=0,insert_l0=False,excluded=[],backtrack_stage=0)
    def tier0(self,gain):
        self.state['gains'].append(gain)
        if len(self.state['gains'])>=2 and max(self.state['gains'][-2:])<self.params['tau']:self.state['upgraded']=True
    def update(self,old,new,gain,cohort_new_hit=False):
        progress=new>old or cohort_new_hit
        if progress:self.state.update(no_progress=0,single_stall=0,backtrack_stage=0)
        elif not self.state['shrunken']:
            self.state['no_progress']+=1
            if self.state['no_progress']>=self.params['K_shrink']:self.state.update(shrunken=True,single_stall=0)
        else:self.state['single_stall']+=1
        self.state['dry']=self.state['dry']+1 if gain==0 else 0
        if self.state['dry']>=3:self.state.update(insert_l0=True,dry=0)
        if self.state['single_stall']>=self.params['K_stall']:
            self.state['single_stall']=0;self.state['backtrack_stage']+=1
            return ('switch_archive','previous_checkpoint','demote')[min(self.state['backtrack_stage'],3)-1]
        if not progress and self.state['shrunken'] and self.state['single_stall']==0:return 'shrink'
        return 'progress' if progress else 'retry'
