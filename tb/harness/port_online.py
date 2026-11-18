"""Evaluate the unchanged sampling stream inside the wall-clock budget."""
import json,time
class SampleStream:
 def __init__(self,raw,evaluator):self.raw=raw;self.evaluator=evaluator;self.merge_s=0.
 def write(self,line):
  t=time.monotonic();self.raw.write(line);event=json.loads(line)
  if event['covergroup'] in self.evaluator.groups:self.evaluator.sample(event['covergroup'],event['args'],event['t_wall_s'],event['n_units'])
  self.merge_s+=time.monotonic()-t
 def flush(self):self.raw.flush()
