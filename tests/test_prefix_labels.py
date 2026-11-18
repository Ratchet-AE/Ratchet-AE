from ratchet.utils.workspace import Workspace
import unittest,tempfile,subprocess
from pathlib import Path
from ratchet.lib.labels import closed_cut,join,definitions,unresolved,checked_cut,assemble_prefix
from tb.dsl.ibex import to_driver,GCC
class PrefixLabelTests(unittest.TestCase):
 def test_forward_and_backward_numeric_cut(self):
  text='addi a0,zero,1\nj 4f\nnop\n4:\n1: nop\nbne a0,zero,1b\n'
  self.assertEqual(closed_cut(text,3),1);self.assertEqual(closed_cut(text,6),6)
 def test_named_forward_cut(self):
  text='nop\nla t0,later\nnop\nlater: nop\n';self.assertEqual(closed_cut(text,3),1)
 def test_numeric_namespaces_and_repeated_definitions(self):
  p='1: nop\nj 1f\n1: nop\nj 1b\n';s=join(p.splitlines(keepends=True),p)
  self.assertFalse(unresolved(s));names=[n for n,a,b in definitions(s)];self.assertEqual(len(names),len(set(names)));self.assertNotIn('1f',s);self.assertNotIn('1b',s)
 def test_named_collision_and_distinct_dot_names(self):
  text='x: nop\n.Lx: nop\nLx: nop\nj x\n';s=join(text.splitlines(keepends=True),text);names=[n for n,a,b in definitions(s)];self.assertEqual(len(names),len(set(names)));self.assertTrue(assemble_prefix(s)['passed'])
 def test_comments_and_strings_untouched(self):
  text='1: nop # 1f remains comment\n.ascii "1b"\nj 1b\n';s=join(text.splitlines(keepends=True),'');self.assertIn('# 1f remains comment',s);self.assertIn('"1b"',s)
 def test_repeat_label_machine_bytes_unchanged(self):
  text='.rept 2\n1: addi a0,a0,1\nbeq zero,zero,2f\nnop\n2: nop\n.endr\n'
  renamed=join(text.splitlines(keepends=True),'');self.assertTrue(assemble_prefix(renamed)['passed'])
  with Workspace() as d:
   paths=[]
   for i,asm in enumerate([text,renamed]):
    out=Path(d)/str(i);driver=to_driver(dict(rationale='test',asm=asm),out);binary=out/'text.bin';subprocess.run([str(GCC).removesuffix('gcc')+'objcopy','--only-section=.text','-O','binary',driver['elf'],str(binary)],check=True,capture_output=True);paths.append(binary.read_bytes())
   self.assertEqual(*paths)
 def test_assembly_rejection_not_saved(self):
  lines=['nop\n','not_a_valid_instruction\n'];cut,result,failures=checked_cut(lines,2);self.assertIsNone(cut);self.assertFalse(result['passed']);self.assertTrue(failures)
 def test_empty_suffix_and_unclosed_macro(self):
  self.assertTrue(assemble_prefix('')['passed']);text='nop\n.rept 3\nnop\n.endr\n';self.assertEqual(closed_cut(text,3),1)
 def test_suffix_numeric_reference_never_binds_prefix(self):
  joined=join(['1: nop\n'],'j 1b\n');self.assertIn('undefined_1b',joined);self.assertFalse(assemble_prefix(joined)['passed'])
if __name__=='__main__':unittest.main()
