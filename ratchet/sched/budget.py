"""Same reservation formula; offline checks never touch the global quota file."""
from dataclasses import dataclass
import time
from ..core import reservation
@dataclass
class Budget:
    token_cap:int
    wall_seconds:float
    global_remaining:int
    spent:int=0
    elapsed_before:float=0
    def __post_init__(self):self.start=time.monotonic()
    def reserve(self,request,schema,outputs):
        estimate=reservation(request,schema,outputs)
        if self.elapsed_before+time.monotonic()-self.start>=self.wall_seconds:return False,'wallclock',estimate
        if self.spent+estimate['total']>self.token_cap:return False,'token_cap',estimate
        if estimate['total']>self.global_remaining:return False,'global_token_cap',estimate
        return True,None,estimate
    def account(self,tokens):
        if tokens<0:raise ValueError('usage cannot be negative')
        self.spent+=tokens;self.global_remaining-=tokens
    def snapshot(self):return dict(token_cap=self.token_cap,wall_seconds=self.wall_seconds,global_remaining=self.global_remaining,spent=self.spent,elapsed_before=self.elapsed_before+time.monotonic()-self.start)
