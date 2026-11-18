"""Explicit uarch_cg subset of the pinned source, primary core only.

The selected points retain complete original bins. Omitted points/crosses/PMP
are listed in DEVIATIONS.md and do not enter this subset's denominator.
"""
from pathlib import Path
import re
from tb.harness.fcov_eval import *


def enums(source,name):
    body=re.search(r'typedef\s+enum\b[^{}]*\{([^}]+)\}\s*'+name,source,re.S)[1]
    result={};v=-1
    for f in re.sub(r'//[^\n]*','',body).split(','):
        f=f.strip()
        if not f:continue
        if '=' in f:
            k,x=map(str.strip,f.split('='));x=x.replace('_','')
            m=re.fullmatch(r"\d+'([hbd])([0-9a-fA-F]+)",x)
            v=int(m[2],{'h':16,'b':2,'d':10}[m[1]]) if m else int(x)
        else:k=f;v+=1
        result[k]=v
    return result


def model(root):
    root=Path(root);src=(root/'dv/uvm/core_ibex/fcov/core_ibex_fcov_if.sv').read_text();pkg=(root/'rtl/ibex_pkg.sv').read_text()
    cats=enums(src,'instr_category_e');cats={k:v for k,v in cats.items() if k not in ('InstrCategoryOther','InstrCategoryOtherIllegal')}
    ps=[]
    def p(n,b=None,w=1,iff=lambda a:True):
        ps.append(Point(n,lambda a,n=n:a[n],auto_bins(w) if b is None else b,iff))
    for n in ['cp_id_instr_category','cp_id_instr_category_last','cp_data_ind_timing_instr','cp_dummy_instr']:
        gate='cp_data_ind_timing' if n=='cp_data_ind_timing_instr' else 'cp_dummy_instr_en' if n=='cp_dummy_instr' else None
        p(n,auto_bins(32,enum=cats),iff=(lambda a,g=gate:bool(a[g])) if gate else lambda a:True)
    p('cp_stall_type_id',auto_bins(32,enum=enums(src,'id_stall_type_e')))
    for n in ['cp_wb_reg_no_load_hz','cp_mem_raw_hz','cp_mprv','cp_ls_error_exception','cp_ls_pmp_exception','cp_branch_taken','cp_branch_not_taken','cp_data_ind_timing','cp_dummy_instr_en','cp_dummy_instr_if_stage','cp_dummy_instr_id_stage','cp_dummy_instr_wb_stage','cp_irq_pending','cp_debug_req','cp_debug_mode']:p(n)
    for n in ['cp_priv_mode_id','cp_priv_mode_lsu']:p(n,auto_bins(2,enum={'PRIV_LVL_U':0,'PRIV_LVL_M':3}))
    p('cp_if_stage_state',auto_bins(32,enum=enums(src,'if_stage_state_e')))
    for n in ['cp_id_stage_state','cp_wb_stage_state']:p(n,auto_bins(32,enum=enums(src,'pipe_stage_state_e')))
    p('cp_dummy_instr_mask',w=3);p('cp_dummy_instr_type',w=2)
    # The normal default bin fetch_inval is excluded from the scored denominator by SV semantics.
    p('cp_fetch_enable',[value_bin('fetch_on',5),value_bin('fetch_off',10)])
    ctrl=enums(pkg,'ctrl_fsm_e')
    for name in ['cp_controller_fsm','cp_controller_fsm_sleep']:
        body=src.split(name+': coverpoint',1)[1].split('\n    }',1)[0]
        bins=[transition_bin(n,((ctrl[a],),(ctrl[b],))) for n,a,b in re.findall(r'bins\s+(\w+)\s*=\s*\((\w+)\s*=>\s*(\w+)\)',body)]
        p(name,bins)
    crosses=[('debug_instruction_cross',('cp_debug_mode','cp_id_instr_category')),
             ('priv_mode_instr_cross',('cp_priv_mode_id','cp_id_instr_category')),
             ('priv_mode_exception_cross',('cp_priv_mode_id','cp_ls_pmp_exception','cp_ls_error_exception')),
             ('stall_cross',('cp_id_instr_category','cp_stall_type_id')),
             ('wb_reg_no_load_hz_instr_cross',('cp_id_instr_category','cp_wb_reg_no_load_hz'))]
    for first in ['debug_req','irq_pending']:
        for stage in ['if','id','wb']:crosses.append((f'{first}_dummy_instr_{stage}_stage_cross',(f'cp_{first}',f'cp_dummy_instr_{stage}_stage')))
    instr_stall={'InstrCategoryDiv','InstrCategoryMul','InstrCategoryBranch','InstrCategoryJump','InstrCategoryFenceI'}
    load_hz={'InstrCategoryALU','InstrCategoryMul','InstrCategoryDiv','InstrCategoryBranch','InstrCategoryJump','InstrCategoryLoad','InstrCategoryStore','InstrCategoryCSRAccess'}
    def enum_name(b):return b[5:-1]
    ignore={
      'priv_mode_instr_cross':lambda c:c==('auto[PRIV_LVL_U]','auto[InstrCategoryCSRAccess]'),
      'priv_mode_exception_cross':lambda c:c[1:]==('auto[1]','auto[1]'),
      'stall_cross':lambda c:(c[1]=='auto[IdStallTypeInstr]' and enum_name(c[0]) not in instr_stall) or (c[1]=='auto[IdStallTypeLdHz]' and enum_name(c[0]) not in load_hz),
      'wb_reg_no_load_hz_instr_cross':lambda c:c[1]=='auto[1]' and enum_name(c[0]) not in load_hz,
    }
    return Evaluator([Group('uarch_cg',ps,crosses,ignore)])
