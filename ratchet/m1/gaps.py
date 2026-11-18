"""Per-target gap gate and nonexclusive cause counts (not OR counts)."""
CATEGORIES=('unsupported_ast','cross_module_binding','parameter_generate','constant_evaluation','coverage_model_projection')
def category(reason):
    if any(v in reason for v in ('cross-module','outside elaborated','mapping','unresolved reference')):return 'cross_module_binding'
    if any(v in reason.lower() for v in ('parameter','generate')):return 'parameter_generate'
    if 'constant evaluation' in reason:return 'constant_evaluation'
    if any(v in reason for v in ('sample','transition','bin unavailable','group unavailable','point unavailable')):return 'coverage_model_projection'
    return 'unsupported_ast'
def detail_reason(reason):
    if 'dynamic object selection' in reason:return 'procedural_dynamic_index'
    if 'unsupported unary requirement' in reason:return 'composite_vector_reduction'
    if 'relational/arithmetic operands' in reason:return 'nonconstant_relational_operands'
    return reason
def gap_report(rows):
    counts={c:dict(targets=set(),occurrences=0,examples=[]) for c in CATEGORIES};details={}
    for row in rows:
        for gap in row['implementation_gaps']:
            detail=details.setdefault(detail_reason(gap['reason']),dict(targets=set(),occurrences=0,examples=[]));detail['targets'].add(row['bin']);detail['occurrences']+=1
            if len(detail['examples'])<3:detail['examples'].append(dict(bin=row['bin'],**gap))
            data=counts[category(gap['reason'])];data['targets'].add(row['bin']);data['occurrences']+=1
            if len(data['examples'])<3 and not any(e['bin']==row['bin'] and e['source']==gap['source'] for e in data['examples']):data['examples'].append(dict(bin=row['bin'],**gap))
    for data in list(counts.values())+list(details.values()):data['target_count']=len(data.pop('targets'))
    n=sum(bool(r['implementation_gaps']) for r in rows)
    return dict(target_bins=n,total_targets=len(rows),target_ratio=n/len(rows) if rows else 0,categories=counts,reasons=details,category_counts_nonexclusive=True)
