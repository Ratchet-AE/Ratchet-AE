"""Resolve source enum literals for checkpoint predicates (no RTL execution)."""
import re
from ratchet.slicing.tracker import kind,module_of,parents
from ratchet.components.m1_patterns import number
def enum_values(tracker):
    values={}
    def visit(n):
        if kind(n)!='EnumType':return
        text=re.sub(r'/\*.*?\*/|//[^\n]*','',str(n),flags=re.S)
        match=re.search(r'\{(.*)\}',text,re.S)
        if not match:return
        module=module_of(n);package=next((p.header.name.valueText for p in parents(n) if kind(p)=='PackageDeclaration'),None);last=-1
        for item in match[1].split(','):
            item=item.strip()
            if not item:continue
            name,sep,expr=item.partition('=');name=name.strip()
            if sep:
                v=number(expr)
                if v is None:v=values.get(expr.strip())
                if v is None:continue
                last=v
            else:last+=1
            values.setdefault(name,last)
            if module:values[module+'.'+name]=last
            if package:values[package.strip()+'::'+name]=last
    tracker.tree.root.visit(visit);return values
