"""Static AST checks only: no DUT simulation and no model calls."""
from ratchet.utils.workspace import Workspace
import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from ratchet.m1.front import Front
from ratchet.m1.necessity import Necessity,atom
class ASTTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=Workspace(prefix='ratchet_static_');p=Path(cls.temp.name)/'ast_test.sv'
  p.write_text('''module ast_test(input logic clk,rst_n,a,b,c,input logic[3:0] vec,
 output logic expr,conditional,inside_set,reduced,fun,selected, output logic[1:0] slice,cat);
 assign expr=a && (b || c);
 assign conditional=a ? (b && c) : (b || c);
 assign inside_set=vec inside {4'd1,4'd2};
 assign reduced=|{a,b};
 assign selected=vec[2];
 assign slice=vec[3:2];
 assign cat={a,b};
 function automatic logic match_set(input logic[3:0] v);
 case(v) 4'd1,4'd2: return 1'b1; default: return 1'b0; endcase
 endfunction
 assign fun=match_set(vec);
 endmodule''')
  cls.f=Front(dict(dut='ast_test',src_list=[str(p)],include_dirs=[],defines=[],top='ast_test',dut_root='ast_test',dut_module='ast_test',exclude=[],seed_base='ast_test',param_overrides=[]))
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def project(self,name,want=1):
  solver=Necessity(self.f);node=self.f.ass['ast_test.'+name][0][0];d=solver.ast_atoms(node.right,want);self.assertFalse(solver.events,solver.events);return d
 def test_or(self):
  d=self.project('expr');self.assertEqual(len(d.branches),2);self.assertEqual(d.common(),{atom('ast_test.a','==',[1])})
 def test_conditional(self):
  d=self.project('conditional');self.assertEqual(len(d.branches),3);self.assertFalse(d.common())
 def test_inside(self):self.assertEqual(self.project('inside_set').common(),{atom('ast_test.vec','in',[1,2])})
 def test_reduction(self):self.assertEqual(len(self.project('reduced').branches),2)
 def test_fixed_index(self):self.assertEqual(self.project('selected').common(),{atom('ast_test.vec[2]','==',[1])})
 def test_range(self):self.assertEqual(self.project('slice',2).common(),{atom('ast_test.vec[3:2]','==',[2])})
 def test_concat(self):self.assertEqual(self.project('cat',2).common(),{atom('ast_test.a','==',[1]),atom('ast_test.b','==',[0])})
 def test_case_function(self):self.assertEqual(self.project('fun').common(),{atom('ast_test.vec','in',[1,2])})
 def test_partial_conditions(self):
  s=Necessity(self.f);n=self.f.ass['ast_test.expr'][0][0];s.propagate(s.ast_atoms(n.right));self.assertEqual(len(s.conditional_conditions),2);self.assertTrue(all(c['is_candidate'] is False and len(c['alternative_ids'])==1 for c in s.conditional_conditions))
if __name__=='__main__':unittest.main()
