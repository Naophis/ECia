/* STM32G431KBU6: 128 KiB flash, 22 KiB contiguous SRAM1+SRAM2.
 *
 * The application links at the very start of flash -- this project has no
 * bootloader and no settings page, so the reset vector is at 0x08000000 and
 * hilctl checks that the ELF entry point lands inside this range.
 *
 * CCM SRAM (10 KiB at 0x10000000, aliased at 0x20005800) is deliberately left
 * out: the gate-capture buffer is a DMA destination, and keeping every DMA
 * target in SRAM1 removes any question about bus-matrix reachability.
 */

ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 128K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 22K
}

_stack_size = 4K;

SECTIONS
{
    .isr_vector : ALIGN(512) {
        KEEP(*(.isr_vector))
    } > FLASH

    .text : {
        *(.text .text.*)
        *(.rodata .rodata.*)
        *(.glue_7 .glue_7t)
        KEEP(*(.init))
        KEEP(*(.fini))
        . = ALIGN(4);
    } > FLASH

    .ARM.exidx : {
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
    } > FLASH

    . = ALIGN(4);
    _sidata = LOADADDR(.data);

    .data : {
        . = ALIGN(4);
        _sdata = .;
        *(.data .data.*)
        . = ALIGN(4);
        _edata = .;
    } > RAM AT > FLASH

    .bss (NOLOAD) : {
        . = ALIGN(4);
        _sbss = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM

    .stack (NOLOAD) : {
        . = ALIGN(8);
        . = . + _stack_size;
        . = ALIGN(8);
        _estack = .;
    } > RAM

    /DISCARD/ : { *(.ARM.attributes) }
}
