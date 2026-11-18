# Ibex DUT card

Sources: pinned third_party/ibex examples/simple_system/rtl/ibex_simple_system.sv; examples/sw/simple_system/common/simple_system_regs.h; doc/03_reference/instruction_set_extensions.rst; duts/ibex/DEVIATIONS.md; dsl/ibex_template.

ISA: RV32IMCB with Zicsr; pinned RV32 toolchain B mnemonics. Unsupported encodings cause illegal-instruction traps; old riscv-dv B encodings are not all implemented by this core. No PMP coverage claim. Coverage is the same uarch subset as RAND.

Simple system RAM: 0x00100000–0x001fffff (1 MiB). Boot entry 0x00100080. Body begins at _xb_body after fixed initialization; RAM text aligned to 256 bytes. Simulator control 0x20000: character output +0, termination +8. Timer 0x30000: mtime low/high +0/+4, mtimecmp low/high +8/+12.

Return only an assembly program body in asm (not a whole ELF/startup). GPR x1 and x3–x31 initially zero; x2 is a valid aligned RAM stack pointer. x0 is architectural zero. All GPRs are available to the body, but preserve sp if using stack operations. Fixed startup sets direct mtvec and disables interrupts. mscratch is reserved by the trap handler. Labels _start and _xb_* and file/section directives are reserved. Bodies may contain local labels, arithmetic, loads/stores, CSR and exception instructions. Falling through the body writes 1 to simulator control at 0x20008 and terminates.

Fixed trap handler preserves t0–t2, advances mepc by 2/4 according to instruction length, and mret resumes after exceptions and illegal instructions. Faulting control transfers outside mapped RAM can prevent recovery and reach the simulation bound. The converter never inserts stimulus into the body or rewrites mnemonics. Assembler/linker errors are compile_fail and remain model repair inputs.
