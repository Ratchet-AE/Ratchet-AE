.section .boot,"ax",@progbits
.option norvc
.globl _start
_start:
 j _xb_init
.section .text,"ax",@progbits
.balign 256
_xb_init:
 la sp, _xb_stack_top
 la t0, _xb_trap
 csrw mtvec, t0
 csrw mie, zero
 csrw mstatus, zero
 csrw mscratch, zero
 .irp n,1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
 li x\n, 0
 .endr
.option rvc
_xb_body:
/* PROGRAM_BODY */
.option norvc
_xb_finish:
 li t0, 0x20008
 li t1, 1
 sw t1, 0(t0)
 j _xb_finish
.balign 256
_xb_trap:
 # The pinned Ibex WARL mtvec is vectored; dispatch every slot to one handler.
 .rept 32
 j _xb_trap_enter
 .endr
_xb_trap_enter:
 csrw mscratch, t0
 la t0, _xb_trap_save
 sw t1, 0(t0)
 sw t2, 4(t0)
 csrr t0, mcause
 bgez t0, _xb_exception
 li t1, 0x80000007
 bne t0, t1, _xb_other_interrupt
 # Timer pending is cleared without disabling MTIE; high word must be first.
 li t0, 0x30000
 li t1, -1
 sw t1, 12(t0)
 sw t1, 8(t0)
 j _xb_restore_mode
_xb_other_interrupt:
 andi t1, t0, 31
 li t2, 1
 sll t2, t2, t1
 csrc mie, t2
 j _xb_restore_mode
_xb_exception:
 csrr t1, mepc
 csrr t2, mtval
 csrr t0, mcause
 addi t0, t0, -2
 beqz t0, _xb_decode_len
 lhu t2, 0(t1)
_xb_decode_len:
 andi t2, t2, 3
 li t0, 3
 beq t2, t0, _xb_len4
 addi t1, t1, 2
 j _xb_advance
_xb_len4:
 addi t1, t1, 4
_xb_advance:
 csrw mepc, t1
_xb_restore_mode:
 # Only a U-origin instruction access fault changes the return privilege.
 csrr t0, mcause
 li t1, 1
 bne t0, t1, _xb_restore
 csrr t1, mstatus
 li t2, 0x1800
 and t1, t1, t2
 bnez t1, _xb_restore
 csrs mstatus, t2
_xb_restore:
 la t0, _xb_trap_save
 lw t1, 0(t0)
 lw t2, 4(t0)
 csrr t0, mscratch
 mret
.section .bss,"aw",@nobits
.balign 4
_xb_trap_save: .space 8
