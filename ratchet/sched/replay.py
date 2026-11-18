"""Bounded, coverage-excluded ibex counterfactuals through the frozen converter."""
from pathlib import Path
from unittest.mock import patch
import json,os,re,subprocess,time
from .trace import read_trace,metadata
from ..expressions import evaluate

def safe_prefix_cut(lines,index):
    """Return the latest cut that does not leave a source assembler block open."""
    stack=[]
    openings={'.rept':'.endr','.irp':'.endr','.irpc':'.endr','.macro':'.endm','.if':'.endif','.ifdef':'.endif','.ifndef':'.endif'}
    for i,line in enumerate(lines[:index]):
        words=line.strip().split()
        if not words:continue
        op=words[0].lower()
        if op in openings:stack.append((i,openings[op]))
        elif stack and op==stack[-1][1]:stack.pop()
    return stack[0][0] if stack else index

class IbexReplay:
    def __init__(self,test,out,binary,bundle,root=None,workspace=None):
        self.test=test;self.out=Path(out);self.binary=Path(binary);self.bundle=bundle
        self.root=Path(root) if root else self.out/'counterfactual';self.workspace=Path(workspace) if workspace else self.out;self.n=0;self.last_result=None;self.layout=None
    def instruction_layout(self):
        if self.layout is not None:return self.layout
        metadata(self.out,self.test,self.workspace)
        meta=self.workspace if (self.workspace/'build/mapping.elf').exists() else self.out
        cmd=json.loads((self.out/'build/compile_command.json').read_text());self.prefix=str(Path(cmd[0]).parent/'riscv32-unknown-elf-');elf=meta/'build/mapping.elf'
        dis=subprocess.check_output([self.prefix+'objdump','-d',str(elf)],text=True);instructions=[]
        for line in dis.splitlines():
            m=re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]{4}|[0-9a-f]{8})\s',line)
            if m:instructions.append((int(m[1],16),len(m[2])//2))
        pcs=[hex(pc) for pc,_ in instructions];locations=subprocess.check_output([self.prefix+'addr2line','-e',str(elf),*pcs],text=True).splitlines()
        from ratchet.slicing.tracker import X
        start=(X/'dsl/ibex_template/start.S').read_text().split('/* PROGRAM_BODY */')[0].count('\n')+1
        layout={}
        for (pc,width),location in zip(instructions,locations):
            try:index=int(location.rsplit(':',1)[1].split()[0])-start
            except (ValueError,IndexError):continue
            if 0<=index<len(self.test['asm'].splitlines()):layout.setdefault(index,[]).append((pc,width))
        header=subprocess.check_output([self.prefix+'objdump','-h',str(elf)],text=True)
        row=next(l.split() for l in header.splitlines() if len(l.split())>3 and l.split()[1]=='.text');self.text_vma=int(row[3],16)
        self.layout=layout;return layout
    def __call__(self,indices,event,remaining):
        tick=time.monotonic();self.n+=1;path=self.root/f'replay{self.n:05d}';path.mkdir(parents=True,exist_ok=False)
        record=dict(indices=indices,event=event,excluded_from_coverage=True,converter='frozen dsl.ibex',replacement='width-preserving ISA NOPs; evaluated model stimuli unchanged')
        answer=None
        try:
            if remaining<=0:raise ValueError('counterfactual budget exhausted')
            layout=self.instruction_layout();lines=self.test['asm'].splitlines(keepends=True);spans=[]
            for index in indices:
                emitted=layout.get(index)
                if not emitted:raise ValueError('input index has no mapped instruction bytes')
                payload='; '.join('.2byte 0x0001' if width==2 else '.4byte 0x00000013' for _,width in emitted)
                # Labels retain their addresses; no manual repairs to model tests.
                if lines[index].strip().startswith('.endr'):
                    opening=safe_prefix_cut(lines,index)
                    if opening==index:raise ValueError('unmatched assembler repetition end')
                    for j in range(opening,index):lines[j]='\n'
                    record.setdefault('source_block_replacements',[]).append([opening,index])
                label=re.match(r'\s*(?:[A-Za-z_.$][\w.$]*|[0-9]+):',lines[index])
                lines[index]=(label.group(0)+' ' if label else '')+payload+'\n';spans.extend(emitted)
            variant=dict(rationale='Diagnostic counterfactual only; never counted as model coverage',asm=''.join(lines))
            from tb.harness.run_test import run_test
            with patch.dict(os.environ,{'LLMCMP_SIM_BINARY':str(self.binary),'LLMCMP_STOP_CYCLE':str(event['stop_cycle'])}),patch('tb.harness.ibex_status.observed_binary',side_effect=lambda p:p):
                result=run_test('ibex',variant,0,path/'execution',timeout_s=max(.1,min(180,remaining)))
            native=path/'execution';record['native_status']=result['status']
            if not (native/'sim.log').exists() or 'RATCHET_CF_STOP' not in (native/'sim.log').read_text():raise ValueError('diagnostic replay did not reach t_d stop')
            # Verify exact code layout and unchanged bytes outside the replacements.
            original_cmd=json.loads((self.out/'build/compile_command.json').read_text());new_cmd=json.loads((native/'build/compile_command.json').read_text())
            for command,name in [(original_cmd,'original'),(new_cmd,'counterfactual')]:
                subprocess.run([self.prefix+'objcopy','--only-section=.text','-O','binary',command[command.index('-o')+1],str(path/(name+'.text'))],check=True,capture_output=True)
            before=(path/'original.text').read_bytes();after=(path/'counterfactual.text').read_bytes();assert len(before)==len(after),'counterfactual changed code layout'
            permitted={i for pc,width in spans for i in range(pc-self.text_vma,pc-self.text_vma+width)}
            assert all(a==b or i in permitted for i,(a,b) in enumerate(zip(before,after))),'counterfactual changed unselected instructions'
            rows=read_trace(native,variant,compact=True,focus=(event['checkpoint'],[g['id'] for g in self.bundle.cards[event['checkpoint']]['clear_guards']]))
            card=self.bundle.cards[event['checkpoint']];predicate=card['predicate']['expr'];window=[r for r in rows if event['window_start']<=r['cycle']<=event['stop_cycle']]
            at_start=[r for r in rows if r['cycle']<=event['window_start']]
            if not at_start or evaluate(predicate,at_start[-1]['state']) is not True:raise ValueError('counterfactual did not preserve checkpoint formation')
            if not window or window[-1]['cycle']<event['stop_cycle']:raise ValueError('counterfactual trace incomplete at t_d')
            answer=all(evaluate(predicate,r['state']) is True for r in window);record['checkpoint_held_to_t_d']=answer;record['code_layout_verified']=True
        except (ValueError,AssertionError,OSError,RuntimeError,subprocess.SubprocessError) as exc:record['unconfirmed_reason']=str(exc)
        record.update(confirmed=answer is True,answer=answer,elapsed_s=time.monotonic()-tick);self.last_result=record;(path/'counterfactual.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        return answer,record['elapsed_s']
