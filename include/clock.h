#pragma once

/* Bring the core to 170 MHz from HSI16 and point VTOR at the vector table. */
void clock_init(void);

/* Start the independent watchdog. Once started it cannot be stopped, which is
 * the point: if the main loop stalls while the bridge is live, the reset is
 * what turns the gates off. */
void watchdog_init(void);
void watchdog_kick(void);
