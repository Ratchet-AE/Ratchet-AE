OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
 . = 0x00100080;
 .boot : { *(.boot) }
 . = ALIGN(256);
 .text : { *(.text) *(.text.*) }
 . = ALIGN(64);
 .data : { *(.data) *(.data.*) *(.sdata*) *(.region_*) *(.s_region_*) }
 .bss : { *(.bss*) *(.sbss*) *(COMMON) }
 .user_stack : { *(.user_stack) }
 .kernel_stack : { *(.kernel_stack) }
}
