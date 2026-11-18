`define C $root.ibex_simple_system.u_top.u_ibex_top.u_ibex_core
module xb_ibex_status(input logic clk,input logic rst_n);
integer fd; longint unsigned cycle=0; logic [31:0] last_pc=0; integer old_priv=-1;
integer traps=0; integer consecutive=0; logic [6:0] last_cause=0; logic [31:0] last_epc=0; bit have_pair=0; bit storm=0;
initial fd=$fopen("ibex_status.jsonl","w");
always @(posedge clk) begin
 if (rst_n) begin
  cycle=cycle+1;
  if (`C.rvfi_valid) last_pc=`C.rvfi_pc_rdata;
  if (int'(`C.priv_mode_id)!=old_priv) begin
   $fdisplay(fd,"{\"event\":\"privilege\",\"cycle\":%0d,\"privilege\":%0d,\"last_rvfi_pc\":%0d}",cycle,`C.priv_mode_id,last_pc);
   old_priv=int'(`C.priv_mode_id);$fflush(fd);
  end
  if (`C.csr_save_cause && !`C.debug_csr_save) begin
   traps=traps+1;
   if (have_pair && last_cause==`C.exc_cause && last_epc==`C.cs_registers_i.mepc_d) consecutive=consecutive+1;
   else consecutive=1;
   have_pair=1;last_cause=`C.exc_cause;last_epc=`C.cs_registers_i.mepc_d;
   $fdisplay(fd,"{\"event\":\"trap\",\"cycle\":%0d,\"interrupt\":%0d,\"cause\":%0d,\"mepc\":%0d,\"privilege_before\":%0d,\"consecutive\":%0d}",cycle,(`C.exc_cause.irq_int|`C.exc_cause.irq_ext),`C.exc_cause.lower_cause,`C.cs_registers_i.mepc_d,`C.priv_mode_id,consecutive);
   if (traps>16384 || consecutive>64) begin
    storm=1;
    $fdisplay(fd,"{\"event\":\"trap_storm\",\"cycle\":%0d,\"total\":%0d,\"consecutive\":%0d}",cycle,traps,consecutive);$fflush(fd);
    $display("XB_TRAP_STORM total=%0d consecutive=%0d",traps,consecutive);
    $finish;
   end
   if ((traps % 256)==0) $fflush(fd);
  end
 end
end
final begin
 $fdisplay(fd,"{\"event\":\"final\",\"cycle\":%0d,\"privilege\":%0d,\"last_rvfi_pc\":%0d,\"trap_storm\":%0d}",cycle,`C.priv_mode_id,last_pc,storm);$fclose(fd);
end
endmodule
bind ibex_simple_system xb_ibex_status xb_ibex_status_i(.clk(clk_sys),.rst_n(rst_sys_n));
`undef C
