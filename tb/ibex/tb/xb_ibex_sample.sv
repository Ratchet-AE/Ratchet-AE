// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

`include "prim_assert.sv"
`include "core_ibex_csr_categories.svh"

interface xb_ibex_sample_if import ibex_pkg::*; (
  input clk_i,
  input rst_ni,

  input priv_lvl_e priv_mode_id,
  input priv_lvl_e priv_mode_lsu,

  input debug_mode,

  input fcov_csr_read_only,
  input fcov_csr_write,

  input fcov_rf_ecc_err_a_id,
  input fcov_rf_ecc_err_b_id,

  input ibex_mubi_t fetch_enable_i,

  input instr_req_o,
  input instr_gnt_i,
  input instr_rvalid_i,

  input data_req_o,
  input data_gnt_i,
  input data_rvalid_i
);
  `include "dv_fcov_macros.svh"


  typedef enum {
    InstrCategoryALU,
    InstrCategoryMul,
    InstrCategoryDiv,
    InstrCategoryBranch,
    InstrCategoryJump,
    InstrCategoryLoad,
    InstrCategoryStore,
    InstrCategoryCSRAccess,
    InstrCategoryEBreakDbg,
    InstrCategoryEBreakExc,
    InstrCategoryECall,
    InstrCategoryMRet,
    InstrCategoryDRet,
    InstrCategoryWFI,
    InstrCategoryFence,
    InstrCategoryFenceI,
    InstrCategoryNone,
    InstrCategoryFetchError,
    InstrCategoryCompressedIllegal,
    InstrCategoryUncompressedIllegal,
    InstrCategoryCSRIllegal,
    InstrCategoryPrivIllegal,
    InstrCategoryOtherIllegal,
    // Category not in coverage plan, it should never be seen. An instruction given the Other
    // category should either be classified under an existing category or a new category should be
    // created as appropriate.
    InstrCategoryOther
  } instr_category_e;

  typedef enum {
    IdStallTypeNone,
    IdStallTypeInstr,
    IdStallTypeLdHz,
    IdStallTypeMem
  } id_stall_type_e;

  instr_category_e id_instr_category;
  // Set `id_instr_category` to the appropriate category for the uncompressed instruction in the
  // ID/EX stage.  Compressed instructions are not handled (`id_stage_i.instr_rdata_i` is always
  // uncompressed).  When the `id_stage.instr_valid_i` isn't set `InstrCategoryNone` is the given
  // instruction category.
  always_comb begin
    id_instr_category = InstrCategoryOther;

    case (id_stage_i.instr_rdata_i[6:0])
      ibex_pkg::OPCODE_LUI:    id_instr_category = InstrCategoryALU;
      ibex_pkg::OPCODE_AUIPC:  id_instr_category = InstrCategoryALU;
      ibex_pkg::OPCODE_JAL:    id_instr_category = InstrCategoryJump;
      ibex_pkg::OPCODE_JALR:   id_instr_category = InstrCategoryJump;
      ibex_pkg::OPCODE_BRANCH: id_instr_category = InstrCategoryBranch;
      ibex_pkg::OPCODE_LOAD:   id_instr_category = InstrCategoryLoad;
      ibex_pkg::OPCODE_STORE:  id_instr_category = InstrCategoryStore;
      ibex_pkg::OPCODE_OP_IMM: id_instr_category = InstrCategoryALU;
      ibex_pkg::OPCODE_OP: begin
        if ({id_stage_i.instr_rdata_i[26], id_stage_i.instr_rdata_i[13:12]} == {1'b1, 2'b01}) begin
          id_instr_category = InstrCategoryALU; // reg-reg/reg-imm ops
        end else if (id_stage_i.instr_rdata_i[31:25] inside {7'b000_0000, 7'b010_0000, 7'b011_0000,
              7'b011_0100, 7'b001_0100, 7'b001_0000, 7'b000_0101, 7'b000_0100, 7'b010_0100}) begin
          id_instr_category = InstrCategoryALU; // RV32I and RV32B reg-reg/reg-imm ops
        end else if (id_stage_i.instr_rdata_i[31:25] == 7'b000_0001) begin
          if (id_stage_i.instr_rdata_i[14]) begin
            id_instr_category = InstrCategoryDiv; // DIV*
          end else begin
            id_instr_category = InstrCategoryMul; // MUL*
          end
        end
      end
      ibex_pkg::OPCODE_SYSTEM: begin
        if (id_stage_i.instr_rdata_i[14:12] == 3'b000) begin
          case (id_stage_i.instr_rdata_i[31:20])
            12'h000: id_instr_category = InstrCategoryECall;
            12'h001: begin
              if (id_stage_i.debug_ebreakm_i && priv_mode_id == PRIV_LVL_M) begin
                id_instr_category = InstrCategoryEBreakDbg;
              end else if (id_stage_i.debug_ebreaku_i && priv_mode_id == PRIV_LVL_U) begin
                id_instr_category = InstrCategoryEBreakDbg;
              end else begin
                id_instr_category = InstrCategoryEBreakExc;
              end
            end
            12'h302: id_instr_category = InstrCategoryMRet;
            12'h7b2: id_instr_category = InstrCategoryDRet;
            12'h105: id_instr_category = InstrCategoryWFI;
          endcase
        end else begin
          id_instr_category = InstrCategoryCSRAccess;
        end
      end
      ibex_pkg::OPCODE_MISC_MEM: begin
        case (id_stage_i.instr_rdata_i[14:12])
          3'b000: id_instr_category = InstrCategoryFence;
          3'b001: id_instr_category = InstrCategoryFenceI;
        endcase
      end
      default: id_instr_category = InstrCategoryOther;
    endcase

    if (id_stage_i.instr_valid_i) begin
      if (id_stage_i.instr_fetch_err_i) begin
        id_instr_category = InstrCategoryFetchError;
      end else if (id_stage_i.illegal_c_insn_i) begin
        id_instr_category = InstrCategoryCompressedIllegal;
      end else if (id_stage_i.illegal_insn_dec) begin
        id_instr_category = InstrCategoryUncompressedIllegal;
      end else if (id_stage_i.illegal_csr_insn_i) begin
        if (cs_registers_i.illegal_csr_priv || cs_registers_i.illegal_csr_dbg) begin
          id_instr_category = InstrCategoryPrivIllegal;
        end else begin
          id_instr_category = InstrCategoryCSRIllegal;
        end
      end else if (id_stage_i.illegal_insn_o) begin
        if (id_stage_i.illegal_dret_insn || id_stage_i.illegal_umode_insn) begin
          id_instr_category = InstrCategoryPrivIllegal;
        end else begin
          id_instr_category = InstrCategoryOtherIllegal;
        end
      end
    end else begin
      id_instr_category = InstrCategoryNone;
    end
  end

  // Check instruction categories calculated from instruction bits match what decoder has produced.

  // The ALU category is tricky as there's no specific ALU enable and instructions that actively use
  // the result of the ALU but aren't themselves ALU operations (such as load/store and JALR). This
  // categorizes anything that selects the ALU as the source of register write data and enables
  // register writes minus some exclusions as an ALU operation.
  `ASSERT(InstrCategoryALUCorrect, id_instr_category == InstrCategoryALU |->
      (id_stage_i.rf_wdata_sel == RF_WD_EX) && id_stage_i.rf_we_dec && ~id_stage_i.mult_sel_ex_o &&
      ~id_stage_i.div_sel_ex_o && ~id_stage_i.lsu_req_dec && ~id_stage_i.jump_in_dec)

  `ASSERT(InstrCategoryMulCorrect,
      id_instr_category == InstrCategoryMul |-> id_stage_i.mult_sel_ex_o)

  `ASSERT(InstrCategoryDivCorrect,
      id_instr_category == InstrCategoryDiv |-> id_stage_i.div_sel_ex_o)

  `ASSERT(InstrCategoryBranchCorrect,
      id_instr_category == InstrCategoryBranch |-> id_stage_i.branch_in_dec)

  // CHERIoT decodes jumps/loads/stores through separate signals instead of
  // jump_in_dec/lsu_req_dec, so both have to be checked.
  `ASSERT(InstrCategoryJumpCorrect,
      id_instr_category == InstrCategoryJump |->
      id_stage_i.jump_in_dec ||
      id_stage_i.cheriot_operator_o.CJAL || id_stage_i.cheriot_operator_o.CJALR)

  `ASSERT(InstrCategoryLoadCorrect,
      id_instr_category == InstrCategoryLoad |->
      (id_stage_i.lsu_req_dec || id_stage_i.cheriot_lsu_req_dec) && !id_stage_i.lsu_we)

  `ASSERT(InstrCategoryStoreCorrect,
      id_instr_category == InstrCategoryStore |->
      (id_stage_i.lsu_req_dec || id_stage_i.cheriot_lsu_req_dec) && id_stage_i.lsu_we)

  `ASSERT(InstrCategoryCSRAccessCorrect,
      id_instr_category == InstrCategoryCSRAccess |-> id_stage_i.csr_access_o)
  `ASSERT(InstrCategoryEBreakDbgCorrect, id_instr_category == InstrCategoryEBreakDbg |->
      id_stage_i.ebrk_insn && id_stage_i.controller_i.ebreak_into_debug)

  `ASSERT(InstrCategoryEBreakExcCorrect, id_instr_category == InstrCategoryEBreakExc |->
      id_stage_i.ebrk_insn && !id_stage_i.controller_i.ebreak_into_debug)

  `ASSERT(InstrCategoryECallCorrect,
      id_instr_category == InstrCategoryECall |-> id_stage_i.ecall_insn_dec)

  `ASSERT(InstrCategoryMRetCorrect,
      id_instr_category == InstrCategoryMRet |-> id_stage_i.mret_insn_dec)

  `ASSERT(InstrCategoryDRetCorrect,
      id_instr_category == InstrCategoryDRet |-> id_stage_i.dret_insn_dec)

  `ASSERT(InstrCategoryWFICorrect,
      id_instr_category == InstrCategoryWFI |-> id_stage_i.wfi_insn_dec)

  `ASSERT(InstrCategoryFenceICorrect,
      id_instr_category == InstrCategoryFenceI && id_stage_i.instr_first_cycle |->
      id_stage_i.icache_inval_o)



  id_stall_type_e id_stall_type;

  // Set `id_stall_type` to the appropriate type based on signals in the ID/EX stage
  always_comb begin
    id_stall_type = IdStallTypeNone;

    if (id_stage_i.instr_valid_i) begin
      if (id_stage_i.stall_mem) begin
        id_stall_type = IdStallTypeMem;
      end

      if (id_stage_i.stall_ld_hz) begin
        id_stall_type = IdStallTypeLdHz;
      end

      if (id_stage_i.stall_multdiv || id_stage_i.stall_branch ||
          id_stage_i.stall_jump) begin
        id_stall_type = IdStallTypeInstr;
      end
    end
  end

  // IF specific state enum
  typedef enum {
    IFStageFullAndFetching,
    IFStageFullAndIdle,
    IFStageEmptyAndFetching,
    IFStageEmptyAndIdle
  } if_stage_state_e;

  // ID/EX and WB have the same state enum
  typedef enum {
    PipeStageFullAndStalled,
    PipeStageFullAndUnstalled,
    PipeStageEmpty
  } pipe_stage_state_e;

  if_stage_state_e   if_stage_state;
  pipe_stage_state_e id_stage_state;
  pipe_stage_state_e wb_stage_state;

  always_comb begin
    if_stage_state = IFStageEmptyAndIdle;

    if (if_stage_i.if_instr_valid) begin
      if (if_stage_i.req_i) begin
        if_stage_state = IFStageFullAndFetching;
      end else begin
        if_stage_state = IFStageFullAndIdle;
      end
    end else if(if_stage_i.req_i) begin
      if_stage_state = IFStageEmptyAndFetching;
    end
  end

  always_comb begin
    id_stage_state = PipeStageEmpty;

    if (id_stage_i.instr_valid_i) begin
      if (id_stage_i.id_in_ready_o) begin
        id_stage_state = PipeStageFullAndUnstalled;
      end else begin
        id_stage_state = PipeStageFullAndStalled;
      end
    end
  end

  always_comb begin
    wb_stage_state = PipeStageEmpty;

    if (wb_stage_i.fcov_wb_valid) begin
      if (wb_stage_i.ready_wb_o) begin
        wb_stage_state = PipeStageFullAndUnstalled;
      end else begin
        wb_stage_state = PipeStageFullAndStalled;
      end
    end
  end

  // This latch is needed because if we cannot register this condition being true
  // with a clock. Being in the sleep mode implies that we don't have an active clock.
  // So, we need to catch the condition, latch it and keep it until we wake up and decode
  // an instruction (which guarantees we have a clock in the core)
  logic kept_wfi_with_irq;

  always_latch begin
    if (id_stage_i.controller_i.ctrl_fsm_cs == DECODE) begin
      kept_wfi_with_irq = 1'b0;
    end else if (id_stage_i.controller_i.ctrl_fsm_cs == SLEEP &&
                 id_stage_i.controller_i.ctrl_fsm_ns == SLEEP &&
                 (|cs_registers_i.mip)) begin
      kept_wfi_with_irq = 1'b1;
    end
  end

  logic instr_id_matches_trigger_d, instr_id_matches_trigger_q;

  assign instr_id_matches_trigger_d = id_stage_i.controller_i.trigger_match_i &&
                                      id_stage_i.controller_i.fcov_debug_entry_if;

  // Delay instruction matching trigger point since it is cached in IF stage.
  // We would want to cross it with decoded instruction categories and it does not matter
  // when exactly we are hitting the condition.
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      instr_id_matches_trigger_q <= 1'b0;
    end else begin
      instr_id_matches_trigger_q <= instr_id_matches_trigger_d;
    end
  end

  // Keep track of previous data addr of Store to catch RAW hazard caused by STORE->LOAD
  logic [31:0]     prev_store_addr;
  logic [31:0]     data_addr_incr;
  logic [31:0]     curr_data_addr;
  logic            raw_hz;

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      prev_store_addr <= 1'b0;
    end else if (load_store_unit_i.data_we_o) begin
      // It does not matter if the store we executed before load is misaligned or not. Because
      // even if it is misaligned, we would catch the "corrected" version (2nd access) before
      // doing the RAW hazard check.
      prev_store_addr <= load_store_unit_i.data_addr_o;
    end
  end

  // Calculate the corrected version of the new data addr at the same time while LOAD instruction
  // gets decoded.
  always_comb begin
    if (load_store_unit_i.split_misaligned_access) begin
      data_addr_incr = load_store_unit_i.data_addr + 4;
      curr_data_addr = {data_addr_incr[2+:30],2'b00};
    end else begin
      curr_data_addr = load_store_unit_i.data_addr;
    end
  end

  // If we have LOAD at ID/EX stage and STORE at WB stage, compare the calculated address for LOAD
  // and the saved STORE address. If they are matching we would have RAW hazard.
  assign raw_hz = wb_stage_i.outstanding_store_wb_o &&
                  id_instr_category == InstrCategoryLoad &&
                  prev_store_addr == curr_data_addr;

  // Collect all the interrupts for collecting them in different bins.
  logic [5:0] fcov_irqs;

  assign fcov_irqs = {id_stage_i.controller_i.irq_nm_ext_i,
                      id_stage_i.controller_i.irq_nm_int,
                      (|id_stage_i.controller_i.irqs_i.irq_fast),
                      id_stage_i.controller_i.irqs_i.irq_external,
                      id_stage_i.controller_i.irqs_i.irq_software,
                      id_stage_i.controller_i.irqs_i.irq_timer};

  logic            instr_unstalled;
  logic            instr_unstalled_last;
  logic            id_stall_type_last_valid;
  id_stall_type_e  id_stall_type_last;
  instr_category_e id_instr_category_last;

  // Keep track of previous values for some signals. These are used for some of the crosses relating
  // to exception and debug entry. We want to cross different instruction categories and stalling
  // behaviour with exception and debug entry but signals indicating entry occur a cycle after the
  // relevant information is flushed from the pipeline.
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      // First cycle out of reset there is no last stall, use valid bit to deal with this case
      id_stall_type_last_valid <= 1'b0;
      id_stall_type_last       <= IdStallTypeNone;
      instr_unstalled_last     <= 1'b0;
      id_instr_category_last   <= InstrCategoryNone;
    end else begin
      id_stall_type_last_valid <= 1'b1;
      id_stall_type_last       <= id_stall_type;
      instr_unstalled_last     <= instr_unstalled;
      id_instr_category_last   <= id_instr_category;
    end
  end

  assign instr_unstalled =
    (id_stall_type == IdStallTypeNone) && (id_stall_type_last != IdStallTypeNone) &&
    id_stall_type_last_valid;

  // V2S Related Probes for Top-Level
  logic rf_glitch_err;
  logic lockstep_glitch_err;

  logic imem_single_cycle_response, dmem_single_cycle_response;

  xb_mem_monitor_if iside_mem_monitor(
    .clk_i,
    .rst_ni,
    .req_i(instr_req_o),
    .gnt_i(instr_gnt_i),
    .rvalid_i(instr_rvalid_i),
    .outstanding_requests_o(),
    .single_cycle_response_o(imem_single_cycle_response)
  );

  xb_mem_monitor_if dside_mem_monitor(
    .clk_i,
    .rst_ni,
    .req_i(data_req_o),
    .gnt_i(data_gnt_i),
    .rvalid_i(data_rvalid_i),
    .outstanding_requests_o(),
    .single_cycle_response_o(dmem_single_cycle_response)
  );


  // Observer is excluded from DUT line coverage.
  /* verilator coverage_off */
  integer xb_fd; longint unsigned xb_cycle=0; bit xb_seen=0;
  logic [959:0] xb_now, xb_last;
  assign xb_now = {32'(id_instr_category), 32'(id_instr_category_last), 32'(id_stall_type), 32'(id_stage_i.fcov_rf_rd_wb_hz && !wb_stage_i.outstanding_load_wb_o), 32'(raw_hz), 32'(cs_registers_i.mstatus_q.mprv), 32'(load_store_unit_i.fcov_ls_error_exception), 32'(load_store_unit_i.fcov_ls_pmp_exception), 32'(id_stage_i.fcov_branch_taken), 32'(id_stage_i.fcov_branch_not_taken), 32'(priv_mode_id), 32'(priv_mode_lsu), 32'(if_stage_state), 32'(id_stage_state), 32'(wb_stage_state), 32'(cs_registers_i.data_ind_timing_o), 32'(id_instr_category), 32'(cs_registers_i.dummy_instr_en_o), 32'(cs_registers_i.dummy_instr_mask_o), 32'(if_stage_i.fcov_dummy_instr_type), 32'(id_instr_category), 32'(if_stage_i.fcov_insert_dummy_instr), 32'(if_stage_i.dummy_instr_id_o), 32'(wb_stage_i.dummy_instr_wb_o), 32'(id_stage_i.irq_pending_i | id_stage_i.irq_nm_i), 32'(id_stage_i.controller_i.fcov_debug_req), 32'(debug_mode), 32'(fetch_enable_i), 32'(id_stage_i.controller_i.ctrl_fsm_cs), 32'(id_stage_i.controller_i.ctrl_fsm_cs)};
  initial xb_fd=$fopen($sformatf("samples_%m.jsonl"),"w");
  always @(posedge clk_i) begin
    if (!xb_seen || xb_now !== xb_last) begin
      $fdisplay(xb_fd, "{\"covergroup\":\"uarch_cg\",\"cycle\":%0d,\"args\":{\"cp_id_instr_category\":%0d,\"cp_id_instr_category_last\":%0d,\"cp_stall_type_id\":%0d,\"cp_wb_reg_no_load_hz\":%0d,\"cp_mem_raw_hz\":%0d,\"cp_mprv\":%0d,\"cp_ls_error_exception\":%0d,\"cp_ls_pmp_exception\":%0d,\"cp_branch_taken\":%0d,\"cp_branch_not_taken\":%0d,\"cp_priv_mode_id\":%0d,\"cp_priv_mode_lsu\":%0d,\"cp_if_stage_state\":%0d,\"cp_id_stage_state\":%0d,\"cp_wb_stage_state\":%0d,\"cp_data_ind_timing\":%0d,\"cp_data_ind_timing_instr\":%0d,\"cp_dummy_instr_en\":%0d,\"cp_dummy_instr_mask\":%0d,\"cp_dummy_instr_type\":%0d,\"cp_dummy_instr\":%0d,\"cp_dummy_instr_if_stage\":%0d,\"cp_dummy_instr_id_stage\":%0d,\"cp_dummy_instr_wb_stage\":%0d,\"cp_irq_pending\":%0d,\"cp_debug_req\":%0d,\"cp_debug_mode\":%0d,\"cp_fetch_enable\":%0d,\"cp_controller_fsm\":%0d,\"cp_controller_fsm_sleep\":%0d}}", xb_cycle, int'(id_instr_category), int'(id_instr_category_last), int'(id_stall_type), int'(id_stage_i.fcov_rf_rd_wb_hz && !wb_stage_i.outstanding_load_wb_o), int'(raw_hz), int'(cs_registers_i.mstatus_q.mprv), int'(load_store_unit_i.fcov_ls_error_exception), int'(load_store_unit_i.fcov_ls_pmp_exception), int'(id_stage_i.fcov_branch_taken), int'(id_stage_i.fcov_branch_not_taken), int'(priv_mode_id), int'(priv_mode_lsu), int'(if_stage_state), int'(id_stage_state), int'(wb_stage_state), int'(cs_registers_i.data_ind_timing_o), int'(id_instr_category), int'(cs_registers_i.dummy_instr_en_o), int'(cs_registers_i.dummy_instr_mask_o), int'(if_stage_i.fcov_dummy_instr_type), int'(id_instr_category), int'(if_stage_i.fcov_insert_dummy_instr), int'(if_stage_i.dummy_instr_id_o), int'(wb_stage_i.dummy_instr_wb_o), int'(id_stage_i.irq_pending_i | id_stage_i.irq_nm_i), int'(id_stage_i.controller_i.fcov_debug_req), int'(debug_mode), int'(fetch_enable_i), int'(id_stage_i.controller_i.ctrl_fsm_cs), int'(id_stage_i.controller_i.ctrl_fsm_cs));
      xb_last=xb_now; xb_seen=1;
    end
    xb_cycle=xb_cycle+1;
  end
  final begin
    $fdisplay(xb_fd,"{\"end_cycle\":%0d}",xb_cycle);
    $fclose(xb_fd);
  end
endinterface
interface xb_mem_monitor_if (
  input clk_i,
  input rst_ni,

  input req_i,
  input gnt_i,
  input rvalid_i,

  output int   outstanding_requests_o,
  output logic single_cycle_response_o
);

  int outstanding_requests;
  logic outstanding_requests_inc, outstanding_requests_dec;
  logic no_outstanding_requests_last_cycle;

  assign outstanding_requests_inc = req_i & gnt_i;
  assign outstanding_requests_dec = rvalid_i;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      outstanding_requests               <= 0;
      no_outstanding_requests_last_cycle <= 1'b0;
    end else begin
      if (outstanding_requests_inc && !outstanding_requests_dec) begin
        outstanding_requests <= outstanding_requests + 1;
      end else if (!outstanding_requests_inc && outstanding_requests_dec) begin
        outstanding_requests <= outstanding_requests - 1;
      end

      no_outstanding_requests_last_cycle <= (outstanding_requests == 0) ||
        ((outstanding_requests == 1) && outstanding_requests_dec);
    end
  end

  assign outstanding_requests_o = outstanding_requests;
  assign single_cycle_response_o = no_outstanding_requests_last_cycle & rvalid_i;
endinterface

module xb_ibex_bind;
 bind ibex_core xb_ibex_sample_if xb_cov_observer (.*);
endmodule
