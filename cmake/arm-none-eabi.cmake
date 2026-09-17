# Toolchain for STM32G431KBU6 (Cortex-M4F).
#
# CMAKE_TRY_COMPILE_TARGET_TYPE is set to STATIC_LIBRARY because the compiler
# check would otherwise try to link a hosted executable, which fails on a
# freestanding target before the linker script exists.

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

find_program(ARM_GCC arm-none-eabi-gcc REQUIRED)
get_filename_component(ARM_TOOLCHAIN_DIR "${ARM_GCC}" DIRECTORY)
set(ARM_PREFIX "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-")

set(CMAKE_C_COMPILER   "${ARM_PREFIX}gcc")
set(CMAKE_ASM_COMPILER "${ARM_PREFIX}gcc")
set(CMAKE_OBJCOPY      "${ARM_PREFIX}objcopy" CACHE FILEPATH "objcopy")
set(CMAKE_SIZE         "${ARM_PREFIX}size"    CACHE FILEPATH "size")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
