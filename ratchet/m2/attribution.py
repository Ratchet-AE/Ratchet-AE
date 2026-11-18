"""Static matching first; bounded cached counterfactual diagnosis, no coverage merge."""
import time,json,hashlib
class Attributor:
    def __init__(self,R_max=6,rho=.2,wall_seconds=3600):
        self.R_max=R_max;self.limit=rho*wall_seconds;self.deadline=time.monotonic()+wall_seconds;self.elapsed=0.;self.cache={};self.replays=0
    def state_reason(self,answer,card,matched,trace,event):
        if answer is not False:return {}
        for match in matched:
            trap=match.get('cause') or {}
            if trap.get('interrupt'):continue
            detail=card.get('clear_causes',{}).get(str(trap.get('cause')))
            if not detail:continue
            # Error inputs precede the registered clear by a few cycles. Keep
            # only actually asserted, sampled branches; absence is unknown.
            window=[r for r in trace if event['formed_cycle']-2<=r['cycle']<=event['loss_cycle']]
            active=[b for b in detail.get('branches',[]) if any(r.get('state',{}).get(b['signal'])==1 for r in window)]
            restricted=[b for b in active if b.get('requires_before_formation')]
            if not restricted:continue
            drivers='; '.join(b['required_relation']+' (actual value is 1)' for b in restricted)
            return dict(reason='state_condition',reason_category=detail['category'],cause=trap['cause'],driver_conditions=drivers,active_branches=[b['signal'] for b in active],required_prerequisites=[b['required_relation'] for b in restricted],requires_before_formation=True,explanation='The clear is independent of a specific input and is triggered by a state condition: '+drivers,permission_checks=detail.get('permission_checks',[]))
        return {}
    def confirm(self,trace,card,event,inputs,replay):
        trace=[r for r in trace if r.get('index',-1)>=0 and r.get('reset_released',True)]
        eligible=[];matched=[];guard_ids={g['id'] for g in card.get('clear_guards',[])}
        for row in trace:
            if event['window_start']<=row['cycle']<=event['loss_cycle'] and any(row.get('clear_guards',{}).get(g) is True or row.get('clear_guards',{}).get(g)==1 for g in guard_ids):
                cause=row.get('clear_input')
                idx=cause.get('index') if cause else row.get('index',-1)
                if idx is None:idx=-1
                if idx>=0:
                    eligible.append(idx);matched.append(dict(index=idx,cycle=row['cycle'],input=inputs[idx] if idx<len(inputs) else 'unknown input',cause=cause,guards=[g for g in guard_ids if row.get('clear_guards',{}).get(g)]))
        eligible=sorted(set(eligible));calls=0
        if replay is None:return dict(confirmed=False,reason='unconfirmed_no_replay',candidates=eligible,matched_inputs=matched,replays=0)
        base=hashlib.sha256(json.dumps(dict(inputs=inputs,checkpoint=card['id'],event=event,guards=card.get('clear_guards',[])),sort_keys=True).encode()).hexdigest()
        def query(indices):
            nonlocal calls
            key=base+':'+','.join(map(str,indices))
            if key in self.cache:return self.cache[key]
            if calls>=self.R_max or self.elapsed>=self.limit or time.monotonic()>=self.deadline:return None
            context=dict(event,checkpoint=card['id'],preserve_timing=True,stop_cycle=event['loss_cycle'],exclude_from_coverage=True)
            tick=time.monotonic();answer,seconds=replay(list(indices),context,min(self.limit-self.elapsed,max(0,self.deadline-time.monotonic())))
            self.elapsed+=max(seconds,time.monotonic()-tick);self.replays+=1;calls+=1
            self.cache[key]=answer;return answer
        if len(eligible)==1:
            answer=query(eligible);result=dict(confirmed=answer is True,reason='static_unique_confirmed' if answer is True else 'unconfirmed',counterfactual_answer=answer,removed_indices=eligible,candidates=eligible,matched_inputs=matched,replays=calls);result.update(self.state_reason(answer,card,matched,trace,event));return result
        if len(eligible)>1:return dict(confirmed=False,reason='multiple_static_candidates',candidates=eligible,matched_inputs=matched,replays=0)
        window=list(range(max(0,event['loss_index']-8),event['loss_index']+1))
        while len(window)>1 and calls<self.R_max-1:
            half=window[len(window)//2:];answer=query(half)
            if answer is None:return dict(confirmed=False,reason='counterfactual_budget',replays=calls)
            window=half if answer else window[:len(window)//2]
        answer=query(window)
        return dict(confirmed=answer is True,reason='bisection_confirmed' if answer is True else 'unconfirmed',removed_indices=window,candidates=[],matched_inputs=matched,replays=calls)
