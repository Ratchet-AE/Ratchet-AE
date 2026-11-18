"""Source-derived functional coverage, independent of simulator covergroup support.

Inputs are sampling events, not arbitrary cycles. Unsupported model constructs must
be reported by adapters; this engine never substitutes simulator counters.
"""
from dataclasses import dataclass, field
from itertools import product
import csv
import json


@dataclass
class Bin:
    name: str
    values: frozenset = frozenset()
    ranges: tuple = ()
    transitions: tuple = ()
    kind: str = 'normal'
    predicate: object = None
    hits: int = 0
    iff: object = lambda args: True

    def contains(self, value):
        return (value in self.values or any(lo <= value <= hi for lo, hi in self.ranges)
                or (self.predicate is not None and self.predicate(value)))

    def matches(self, value, history):
        if self.transitions:
            return any(len(history) >= len(seq)-1 and all(
                actual in allowed for actual, allowed in zip(
                    (*history[-(len(seq)-1):], value), seq)) for seq in self.transitions)
        return self.contains(value)


def value_bin(name, *values, kind='normal'):
    return Bin(name, frozenset(values), kind=kind)


def wildcard_bin(name, pattern):
    """SystemVerilog wildcard bins over a concrete two-state sampling value."""
    pattern=pattern.replace('_','').lower()
    if any(c not in '01?xz' for c in pattern):raise ValueError(pattern)
    mask=int(''.join('1' if c in '01' else '0' for c in pattern),2)
    expected=int(''.join(c if c in '01' else '0' for c in pattern),2)
    return Bin(name,predicate=lambda value:(value&mask)==expected)


def filtered_bins(name, values, predicate, count=None):
    values = sorted(v for v in values if predicate(v))
    if count is None:
        return [value_bin(name, *values)]
    count = min(count, len(values))
    if not count:
        return []
    size = len(values)//count
    return [value_bin(f'{name}[{i}]', *values[i*size:((i+1)*size if i<count-1 else len(values))])
            for i in range(count)]


def transition_bin(name, *alternatives):
    return Bin(name, transitions=tuple(tuple(frozenset(s) for s in seq) for seq in alternatives))


def transition_array(name, *alternatives):
    return [transition_bin(f'{name}[{i}]', tuple((v,) for v in sequence))
            for i, sequence in enumerate(sequence for seq in alternatives for sequence in product(*seq))]


def auto_bins(width, max_bins=64, enum=None):
    if enum is not None:
        return [value_bin(f'auto[{name}]', value) for name, value in enum.items()]
    size = 1 << width
    n = min(size, max_bins)
    group_size = size//n
    bins = []
    for i in range(n):
        lo = i*group_size
        hi = (i+1)*group_size-1 if i<n-1 else size-1
        name = f'auto[{lo}]' if lo == hi else f'auto[{lo}:{hi}]'
        bins.append(Bin(name, ranges=((lo, hi),)))
    return bins


@dataclass
class Point:
    name: str
    expression: object
    bins: list
    iff: object = lambda args: True
    history: list = field(default_factory=list)

    def sample(self, args):
        if not self.iff(args):
            return []
        value = self.expression(args)
        excluded = any(b.kind in ('ignore', 'illegal') and b.iff(args) and b.contains(value) for b in self.bins)
        matches = []
        for b in self.bins:
            if not b.iff(args):continue
            if b.kind != 'normal':
                if b.contains(value): b.hits += 1
            elif not excluded and b.matches(value, self.history):
                b.hits += 1
                matches.append(b.name)
        self.history.append(value)
        self.history[:] = self.history[-16:]
        return matches


class Group:
    def __init__(self, name, points, crosses=(), ignore_cross=None, cross_iff=None):
        self.name = name
        self.points = {p.name:p for p in points}
        self.crosses = dict(crosses)
        self.cross_iff = cross_iff or {}
        self.cross_hits = {}
        ignore_cross = ignore_cross or {}
        for cross, names in self.crosses.items():
            combinations = product(*[[b.name for b in self.points[n].bins if b.kind=='normal'] for n in names])
            for combination in combinations:
                if cross not in ignore_cross or not ignore_cross[cross](combination):
                    self.cross_hits[(cross, combination)] = 0

    def sample(self, args):
        matches = {n:p.sample(args) for n,p in self.points.items()}
        for cross, names in self.crosses.items():
            if cross in self.cross_iff and not self.cross_iff[cross](args):continue
            for combination in product(*(matches[n] for n in names)):
                key = (cross, combination)
                if key in self.cross_hits:
                    self.cross_hits[key] += 1

    def records(self):
        for p in self.points.values():
            for b in p.bins:
                if b.kind=='normal':
                    yield self.name,p.name,b.name,b.hits
        for (cross, bins),hits in self.cross_hits.items():
            yield self.name,cross,'<'+','.join(bins)+'>',hits


class Evaluator:
    def __init__(self, groups):
        self.groups = {g.name:g for g in groups}
        self.first_hit = {}

    def sample(self, group, args, wall_s=None, n_units=None):
        if group not in self.groups:
            raise ValueError(f'Unimplemented covergroup: {group}')
        self.groups[group].sample(args)
        for record in self.groups[group].records():
            if record[3] and record[:3] not in self.first_hit:
                self.first_hit[record[:3]] = (wall_s,n_units)

    def records(self):
        return [row for g in self.groups.values() for row in g.records()]

    def summary(self):
        rows = self.records()
        return {'func_hit':sum(h>0 for _,_,_,h in rows),'func_total':len(rows)}

    def export(self, path):
        with open(path,'w',newline='') as f:
            writer=csv.writer(f)
            writer.writerow(['bin_id','covergroup','coverpoint_or_cross','bin_name','hits',
                             'first_hit_t_wall_s','first_hit_n_units'])
            for g,p,b,h in self.records():
                first=self.first_hit.get((g,p,b),('',''))
                writer.writerow([f'{g}.{p}.{b}',g,p,b,h,*first])

    def replay(self, path):
        with open(path) as f:
            for line in f:
                event=json.loads(line)
                self.sample(event['covergroup'],event['args'],event.get('t_wall_s'),event.get('n_units'))

    def replay_changes(self,path,n_units=None):
        """Expand parameter-change logs back to every original clock sampling event.

        Logger emits cycle for each change and end_cycle=last_sampled_cycle+1.
        No wall-clock first-hit time is invented for suppressed repeated entries.
        """
        pending={}
        with open(path) as f:
            for line in f:
                event=json.loads(line)
                if 'end_cycle' in event:
                    for group,old in pending.items():
                        for _ in range(old['cycle'],event['end_cycle']):
                            self.sample(group,old['args'],n_units=n_units)
                    pending.clear()
                    continue
                group=event['covergroup']
                if group in pending:
                    old=pending[group]
                    for _ in range(old['cycle'],event['cycle']):
                        self.sample(group,old['args'],n_units=n_units)
                pending[group]=event
        if pending:raise ValueError('Change-only sample log has no end_cycle terminator')
