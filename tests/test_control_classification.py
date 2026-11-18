"""M1 D regression: actual elaborated control readers versus pure data paths."""
from ratchet.utils.workspace import Workspace
import tempfile,unittest
from pathlib import Path
from ratchet.m1.front import Front
class DClassification(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=Workspace(prefix='ratchet_d_reader_');p=Path(cls.temp.name)/'reader.sv'
  p.write_text('''module child(input logic choose, input logic [3:0] data, output logic [3:0] out);
    assign out=choose ? data : 4'd0;
  endmodule
  module reader(input logic clk, rst_n, input logic [3:0] data, input logic [1:0] addr,
    output logic [3:0] ternary_out,case_out,if_out,fn_out,port_out,
    output logic cmp_out,reduce_out,index_out, same_out, output logic [1:0] range_out,
    output logic [3:0] pure_out, output logic member_out, whole_out, output int builtin_out);
    logic [3:0] ternary_q,case_q,if_q,fn_q,port_q,cmp_q,reduce_q,index_q,same_q,range_q,pure_q,builtin_q;
    typedef struct packed {logic flag; logic [2:0] payload;} state_t;
    state_t state_q, routed;
    always_ff @(posedge clk) begin
      ternary_q<=data; case_q<=data; if_q<=data; fn_q<=data; port_q<=data;
      cmp_q<=data; reduce_q<=data; index_q<=data; same_q<=data; range_q<=data; pure_q<=data; builtin_q<=data;
      state_q<=state_t'(data);
    end
    assign ternary_out=ternary_q ? 4'd1 : 4'd0;
    always_comb case(case_q) 4'd1:case_out=4'd1; default:case_out=4'd0; endcase
    always_comb if(if_q) if_out=4'd1; else if_out=4'd0;
    assign cmp_out=(cmp_q !=? 4'b1?00);
    assign reduce_out=^reduce_q;
    assign index_out=data[index_q];
    assign range_out=data[range_q+:2];
    assign same_out=same_q ? same_q[0] : 1'b0;
    assign pure_out=pure_q+4'd1;
    assign builtin_out=$countones(builtin_q);
    function automatic logic [3:0] pick(input logic[3:0] selector);
      case(selector) 4'd1: return 4'd5; default:return 4'd0; endcase
    endfunction
    assign fn_out=pick(fn_q);
    child c(.choose(|port_q),.data(data),.out(port_out));
    assign routed=state_q;
    assign member_out=routed.flag ? 1'b1 : 1'b0;
    assign whole_out=|state_q;
  endmodule''')
  cls.front=Front(dict(dut='reader',src_list=[str(p)],include_dirs=[],defines=[],top='reader',dut_root='reader',dut_module='reader',exclude=[],seed_base='reader',param_overrides=[]))
  cls.records=cls.front.classify(set())
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def assert_control(self,name):
  path='reader.'+name;self.assertTrue(self.front.is_control_relevant(path),path)
  writers=[r for r in self.records if path in r['lhs']];self.assertTrue(writers)
  self.assertTrue(all('D' not in r['types'] for r in writers),writers)
 def test_ternary(self):self.assert_control('ternary_q')
 def test_case(self):self.assert_control('case_q')
 def test_if(self):self.assert_control('if_q')
 def test_wildcard_comparison(self):self.assert_control('cmp_q')
 def test_reduction(self):self.assert_control('reduce_q')
 def test_builtin_reduction(self):self.assert_control('builtin_q')
 def test_index(self):self.assert_control('index_q')
 def test_variable_part_select(self):self.assert_control('range_q')
 def test_control_also_in_rhs(self):self.assert_control('same_q')
 def test_function_case_parameter_to_actual(self):self.assert_control('fn_q')
 def test_instance_port_dataflow(self):self.assert_control('port_q')
 def test_struct_alias(self):self.assert_control('state_q')
 def test_pure_arithmetic_remains_D(self):
  self.assertFalse(self.front.is_control_relevant('reader.pure_q'))
  self.assertTrue(all(r['primary']=='D' for r in self.records if 'reader.pure_q' in r['lhs']))
if __name__=='__main__':unittest.main()
