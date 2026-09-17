/* ECia board constants: STM32G431KBU6 + MP6540HA.
 *
 * Every pin, alternate function and comparator mux value here is sourced in
 * docs/hardware-mapping.md. Do not change one without changing that document.
 */

#pragma once

#include "stm32g431xx.h"

/* ---------------------------------------------------------------- clock -- */
#define SYSCLK_HZ 170000000u

/* ------------------------------------------------------------ motor pins -- */
/* All six gate signals are TIM1 on AF6. */
#define GATE_AF 6u

#define HSA_PORT GPIOA
#define HSA_PIN  8u
#define LSA_PORT GPIOA
#define LSA_PIN  7u
#define HSB_PORT GPIOA
#define HSB_PIN  9u
#define LSB_PORT GPIOB
#define LSB_PIN  0u
#define HSC_PORT GPIOA
#define HSC_PIN  10u
#define LSC_PORT GPIOF
#define LSC_PIN  0u

/* ------------------------------------------------------------- BEMF pins -- */
/* Analog inputs; configured, never driven. */
#define BEMF_A_PORT GPIOA
#define BEMF_A_PIN  0u
#define BEMF_B_PORT GPIOA
#define BEMF_B_PIN  4u
#define BEMF_C_PORT GPIOA
#define BEMF_C_PIN  5u
#define BEMF_N1_PORT GPIOA /* COMP1_INP */
#define BEMF_N1_PIN  1u
#define BEMF_N2_PORT GPIOA /* COMP2_INP */
#define BEMF_N2_PIN  3u

/* Phase voltage divider: 56k over 10k, so the pin sees phase * 10/66. */
#define BEMF_DIVIDER_NUM 10u
#define BEMF_DIVIDER_DEN 66u

/* ---------------------------------------------------------------- TIM1 --- */
/* PWM frequency is a configuration value in the 24-48 kHz band (spec §9).
 * 170 MHz / 32 kHz = 5312.5 ticks, so ARR 5311 gives 5312 ticks = 31.998 kHz. */
#define PWM_FREQ_HZ 32000u
#define PWM_TICKS   (SYSCLK_HZ / PWM_FREQ_HZ)
#define PWM_ARR     (PWM_TICKS - 1u)

/* Dead time: 548 ns was measured on this board with the same MP6540HA at
 * 168 MHz. 93 ticks at 170 MHz is 547.06 ns. DTG[7:5] = 0xx encodes
 * DTG[7:0] * t_DTS directly, and CKD = 00 makes t_DTS = 1/SYSCLK, so the
 * value is the tick count as-is and must stay below 128. */
#define DEAD_TIME_TICKS 93u
#if DEAD_TIME_TICKS > 127u
#error "DEAD_TIME_TICKS does not fit the DTG[7:5]=0xx encoding"
#endif
#define DEAD_TIME_NS ((DEAD_TIME_TICKS * 1000000000ull) / SYSCLK_HZ)

/* Ceiling the firmware enforces regardless of what the host asks for. */
#define MAX_DUTY_MILLI 10000u /* 10.000 % */

/* --------------------------------------------------------- gate capture -- */
/* TIM7 divides SYSCLK to produce the DMA sampling rate. 10 gives 17 MHz, i.e.
 * 58.8 ns per sample -- see docs/on-chip-capture.md for why that resolves a
 * ~550 ns dead time. The divider must not be commensurate with PWM_TICKS or
 * the sampling phase stops sliding and the measurement loses its resolution. */
#define CAPTURE_TICKS_PER_SAMPLE 10u
#define CAPTURE_SAMPLES          4096u
#if (PWM_TICKS % CAPTURE_TICKS_PER_SAMPLE) == 0u
#error "capture rate divides the PWM period exactly; the sampling phase will not slide"
#endif

/* The port whose IDR is sampled. GPIOA carries LSA(7), HSA(8), HSB(9),
 * HSC(10) -- the only port with both gates of one phase, which is what makes
 * phase A the one dead time is measured on. */
#define CAPTURE_PORT      GPIOA
#define CAPTURE_PORT_IDR  ((uint32_t)&GPIOA->IDR)

/* -------------------------------------------------------------- bring-up -- */
/* A window at the very top of main(), before the clock tree or any peripheral
 * is touched, during which the core runs nothing but a counted delay. It costs
 * half a second per boot and it guarantees the debugger can always attach and
 * halt -- without it, firmware that faults early and resets can lock the
 * debugger out entirely, which is exactly how Milestone 1 trial 1 ended. */
#define BRINGUP_DEBUG_WINDOW_MS 500u
#define HSI16_HZ 16000000u

/* The independent watchdog turns a single early fault into a permanent reset
 * loop that no debugger can break into. That trade is right once the control
 * loop is trusted and wrong during bring-up, so it stays off until the bridge
 * behaviour is measured, and comes back in Milestone 2. */
#ifndef ENABLE_IWDG
#define ENABLE_IWDG 0
#endif

/* ------------------------------------------------------------- watchdog -- */
/* LSI is nominally 32 kHz; /8 gives 4 kHz, and RLR 239 gives ~60 ms. The main
 * loop refreshes at 1 kHz, so this only fires if the loop itself stalls. */
#define IWDG_PRESCALER_DIV8 0x1u
#define IWDG_RELOAD         239u
