"""Read-only sampled monitor, generated solely from cards and condition tables."""
import json
from . import io
from ..expressions import sv,signals

def generate(front,cards,conditions,out):
    out.mkdir(exist_ok=True);raw=set()
    for c in conditions.values():raw.update(signals(c['expr']));raw.update(c['driver_registers'])
    guards={}
    for card in cards.values():
        for cause in card.get('clear_causes',{}).values():raw.update(cause['probe_signals'])
        for guard in card['clear_guards']:guards[guard['id']]=guard
        for source in card['object']['constraints']:raw.update(source['signals'])
    for g in guards.values():raw.update(signals(g['expr']))
    from .synthesis import observable
    raw=sorted(s for s in raw if observable(front,s))
    tracer=min((p for p,m in front.instances.items() if m=='ibex_tracer'),key=len)
    expressions=['cycle','$root.'+tracer+'.cycle'];parts=['{"cycle":%0d,"trace_cycle":%0d,"reset_released":true,"conditions":{']
    def fields(items):
        return ','.join(json.dumps(k)+':'+fmt for k,fmt,expr in items)
    items=[(k,'%0d',sv(c['expr'])) for k,c in sorted(conditions.items())];parts.append(fields(items));expressions.extend(v[2] for v in items)
    parts.append('},"state":{');items=[(s,'"%h"','$root.'+s) for s in raw];parts.append(fields(items));expressions.extend(v[2] for v in items)
    parts.append('},"measures":{');items=[]
    for k,c in sorted(cards.items()):
        expr='$root.'+c['measure']['signal'] if c['measure']['kind']=='scalar' else sv(c['predicate']['expr'])
        items.append((k,'%0d',expr))
    parts.append(fields(items));expressions.extend(v[2] for v in items)
    parts.append('},"clear_guards":{');items=[(k,'%0d',sv(v['expr'])) for k,v in sorted(guards.items())];parts.append(fields(items));expressions.extend(v[2] for v in items);parts.append('}}')
    text=['// Generated from M1; every DUT reference is read-only.','/* verilator coverage_off */','module ratchet_monitor(input logic clk, input logic rst_n);','integer fd; longint unsigned cycle=0; bit reset_seen=0; integer stop_cycle=0;', 'initial void\'($value$plusargs("m1_stop_cycle=%d",stop_cycle));','initial fd=$fopen("ratchet_monitor.jsonl","w");','always @(posedge clk) begin','cycle=cycle+1;','if (!rst_n) reset_seen=1;', 'if (rst_n && reset_seen) begin','$fdisplay(fd, '+json.dumps(''.join(parts))+', '+', '.join(expressions)+');','end','end','always @(negedge clk) if (stop_cycle>0 && cycle>=stop_cycle) begin $display("RATCHET_CF_STOP cycle=%0d",cycle); $finish; end', 'final $fclose(fd);','endmodule','bind ibex_simple_system ratchet_monitor ratchet_observer(.clk(clk_sys),.rst_n(rst_sys_n));','/* verilator coverage_on */']
    (out/'ckpt_mon.sv').write_text('\n'.join(text)+'\n')
    io.write_json(out/'signals.json',dict(clock='clk_sys',reset='rst_sys_n',sampling_edge='posedge',read_only=True,conditions=list(sorted(conditions)),clear_guards=list(sorted(guards)),state_signals=raw,measure_ids=list(sorted(cards)),index_signals={k:sorted({s for v in c['object']['constraints'] for s in v['signals'] if s in raw}) for k,c in cards.items()}))
