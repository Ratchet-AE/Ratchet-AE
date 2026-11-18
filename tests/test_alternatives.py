import itertools,unittest
from ratchet.m1 import alternatives as m
D=m.DNF
class Tests(unittest.TestCase):
 def test_truth_table(self):
  a,b,c=[D.one(x) for x in 'abc'];f=a&(b|c)
  self.assertEqual(f.common(),{'a'})
  for bits in itertools.product([False,True],repeat=3):
   v=dict(zip('abc',bits));self.assertEqual(any(all(v[x] for x in branch) for branch in f.branches),v['a'] and (v['b'] or v['c']))
 def test_partial_membership(self):
  f=D.one('a')&(D.one('b')|D.one('c'));self.assertEqual(set.union(*(set(v) for v in f.branches))-f.common(),{'b','c'})
 def test_alternative_cap(self):
  f=D.false()
  for i in range(9):f=f|D.one(str(i))
  self.assertFalse(f.complete);self.assertEqual(len(f.branches),8);self.assertEqual(f.common(),set());self.assertIn('alternative_count_exceeds_8',f.overflow)
 def test_condition_cap(self):
  f=D.truth()
  for i in range(9):f=f&D.one(str(i))
  self.assertFalse(f.complete);self.assertFalse(f.branches);self.assertEqual(len(f.common()),9)
 def test_unknown_common(self):
  f=(D.one('a')&D.unknown())|D.one('b');self.assertEqual(f.common(),set());self.assertFalse(f.complete)
 def test_progress(self):
  r=m.conjunct_progress([dict(id='a',condition_ids=['x','y']),dict(id='b',condition_ids=['z'])],dict(x=True,y=False,z=True));self.assertEqual(r,dict(alternative_id='b',g=1,missing_conditions=[]))
 def test_absorb(self):
  a=D.one('a');self.assertEqual((a|(a&D.one('b'))).branches,a.branches)
if __name__=='__main__':unittest.main()
