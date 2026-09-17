cmake_minimum_required(VERSION 3.20)

project(ecia_bldc C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# The short git SHA is compiled in and reported as hil_state.build_id, so every
# trial's evidence names the exact tree that produced the binary.
execute_process(
    COMMAND git rev-parse --short=8 HEAD
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_SHA
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET)
if(NOT GIT_SHA)
    set(GIT_SHA "00000000")
endif()

set(MCU_FLAGS -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16)
set(LINKER_SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/ld/stm32g431kb.ld)

add_executable(ecia_bldc
    src/main.c
    src/clock.c
    src/hil.c
    src/motor_hw.c
    src/motor_commutation.c
    src/motor_control.c
    src/capture.c
    src/startup_stm32g431.c)

set_target_properties(ecia_bldc PROPERTIES OUTPUT_NAME ecia_bldc SUFFIX ".elf")

target_include_directories(ecia_bldc PRIVATE
    include
    vendor/cmsis_core
    vendor/cmsis_device_g4)

target_compile_definitions(ecia_bldc PRIVATE
    STM32G431xx
    BUILD_ID=0x${GIT_SHA}u)

target_compile_options(ecia_bldc PRIVATE
    ${MCU_FLAGS}
    -O2 -g3   # explicit, and last: not inherited from CMAKE_BUILD_TYPE
    -ffunction-sections -fdata-sections
    -fno-common
    -Wall -Wextra -Wshadow -Wundef -Wdouble-promotion
    -Werror)

target_link_options(ecia_bldc PRIVATE
    ${MCU_FLAGS}
    -T${LINKER_SCRIPT}
    -nostartfiles
    -specs=nano.specs
    -Wl,--gc-sections
    -Wl,-Map=${CMAKE_BINARY_DIR}/ecia_bldc.map
    -Wl,--print-memory-usage)

set_target_properties(ecia_bldc PROPERTIES LINK_DEPENDS ${LINKER_SCRIPT})
