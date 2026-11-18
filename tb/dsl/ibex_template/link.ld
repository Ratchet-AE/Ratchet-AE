OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
 . = 0x00100080;
 .boot : { *(.boot) }
 . = ALIGN(256);
 .text : { *(.text) *(.text.*) }
 . = ALIGN(64);
 .data : { *(.data) *(.sdata*) }
 .bss : { *(.bss*) *(.sbss*) *(COMMON) }
 . = ALIGN(16);
 . += 4096;
 _xb_stack_top = .;
 ASSERT(. < 0x00200000, "program exceeds simple_system RAM")
}
