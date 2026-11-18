"""Bounded DNF. Never infer necessity from a truncated list of branches."""
from dataclasses import dataclass
from itertools import product

@dataclass(frozen=True)
class DNF:
    branches: tuple
    must: frozenset
    complete: bool = True
    overflow: tuple = ()

    @classmethod
    def truth(cls): return cls((frozenset(),), frozenset())
    @classmethod
    def false(cls): return cls((), frozenset())
    @classmethod
    def one(cls, value): return cls((frozenset((value,)),), frozenset((value,)))
    @classmethod
    def unknown(cls): return cls((frozenset(),), frozenset(), False)

    @classmethod
    def bounded(cls, branches, must, complete=True, overflow=()):
        # Absorption is exact and precedes the limits.
        unique=set(branches)
        unique={b for b in unique if not any(a < b for a in unique)}
        ordered=sorted(unique,key=lambda b:(len(b),repr(sorted(b))))
        reasons=list(overflow)
        if len(ordered)>8: reasons.append('alternative_count_exceeds_8')
        if any(len(b)>8 for b in ordered): reasons.append('condition_count_exceeds_8')
        kept=tuple(b for b in ordered[:8] if len(b)<=8)
        return cls(kept,frozenset(must),complete and not reasons,tuple(sorted(set(reasons))))

    def __and__(self, other):
        if self.complete and not self.branches or other.complete and not other.branches:return DNF.false()
        return self.bounded((a|b for a,b in product(self.branches,other.branches)),self.must|other.must,self.complete and other.complete,self.overflow+other.overflow)

    def __or__(self, other):
        if self.complete and not self.branches:return other
        if other.complete and not other.branches:return self
        return self.bounded(self.branches+other.branches,self.must&other.must,self.complete and other.complete,self.overflow+other.overflow)

    def common(self):
        # Must is computed BEFORE clipping; clipping can never promote an atom.
        return set(self.must)


def conjunct_progress(alternatives, values):
    """values maps condition IDs to bool; stable ties use alternative order."""
    if not alternatives: return None
    scores=[]
    for alternative in alternatives:
        ids=alternative['condition_ids']
        if not ids:raise ValueError('empty conjunction cannot be used as target progress')
        missing=[v for v in ids if not values[v]]
        scores.append(dict(alternative_id=alternative['id'],g=(len(ids)-len(missing))/len(ids),missing_conditions=missing))
    return max(scores,key=lambda row:row['g'])
