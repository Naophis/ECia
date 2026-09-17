#include "motor_hw.h"

#include "board.h"

static uint32_t duty_milli_applied;

static void gpio_as_af(GPIO_TypeDef *port, uint32_t pin, uint32_t af)
{
    /* Pull-down first, mode last: the pin must never pass through a floating
     * push-pull state on its way to alternate function. The MP6540HA's own
     * inputs are internally pulled down too, so this is the second of two
     * independent reasons an un-driven gate reads low. */
    port->PUPDR = (port->PUPDR & ~(3u << (pin * 2u))) | (2u << (pin * 2u));
    port->OTYPER &= ~(1u << pin);
    port->OSPEEDR |= (3u << (pin * 2u)); /* very high speed: ~550 ns edges */
    port->AFR[pin >> 3u] = (port->AFR[pin >> 3u] & ~(0xFu << ((pin & 7u) * 4u)))
                         | (af << ((pin & 7u) * 4u));
    port->MODER = (port->MODER & ~(3u << (pin * 2u))) | (2u << (pin * 2u));
}

static void gpio_as_analog(GPIO_TypeDef *port, uint32_t pin)
{
    port->PUPDR &= ~(3u << (pin * 2u));
    port->MODER |= (3u << (pin * 2u));
}

#define OCM_FORCE_INACTIVE 4u
#define OCM_FORCE_ACTIVE   5u
#define OCM_PWM1           6u

void motor_hw_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOFEN;
    (void)RCC->AHB2ENR;

    /* BEMF pins are analog from the start so the divider is never loaded by a
     * digital input buffer, even though nothing reads them until Milestone 3. */
    gpio_as_analog(BEMF_A_PORT, BEMF_A_PIN);
    gpio_as_analog(BEMF_B_PORT, BEMF_B_PIN);
    gpio_as_analog(BEMF_C_PORT, BEMF_C_PIN);
    gpio_as_analog(BEMF_N1_PORT, BEMF_N1_PIN);
    gpio_as_analog(BEMF_N2_PORT, BEMF_N2_PIN);

    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    (void)RCC->APB2ENR;
    RCC->APB2RSTR |= RCC_APB2RSTR_TIM1RST;
    RCC->APB2RSTR &= ~RCC_APB2RSTR_TIM1RST;

    TIM1->CR1 = TIM_CR1_ARPE;       /* CKD = 00, so t_DTS = 1 / SYSCLK */
    TIM1->PSC = 0u;
    TIM1->ARR = PWM_ARR;
    TIM1->RCR = 0u;

    /* Every channel starts forced inactive with CCR preload on, so the first
     * COM event is the first time any output can chop. Duty changes then land
     * on an update event, never mid-pulse. */
    TIM1->CCMR1 = (OCM_FORCE_INACTIVE << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE
                | (OCM_FORCE_INACTIVE << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = (OCM_FORCE_INACTIVE << TIM_CCMR2_OC3M_Pos) | TIM_CCMR2_OC3PE;

    /* CCPC: the CCxE/CCxNE bits are preloaded and take effect on a COM event,
     * which is what makes a sector change atomic across all three phases.
     * CCUS stays clear for now, so COM comes only from software (EGR.COMG);
     * the TIM2-triggered path arrives with scheduled commutation in
     * Milestone 5. */
    TIM1->CR2 = TIM_CR2_CCPC;

    /* OSSR/OSSI drive an output to its inactive level rather than releasing it
     * -- but only "as soon as CCxE=1 or CCxNE=1" (RM0440). A channel with both
     * enable bits clear is released to high impedance whatever OSSI/OSSR say,
     * which is exactly the case for a floating phase and for the whole bridge
     * before the first COM event. The GPIO pull-downs configured above are
     * therefore load-bearing, not decorative: together with the MP6540HA's own
     * internal input pull-downs they are what holds a released gate off. The
     * Milestone 1 capture checks that those pins really do read low. */
    TIM1->BDTR = (DEAD_TIME_TICKS << TIM_BDTR_DTG_Pos) | TIM_BDTR_OSSR | TIM_BDTR_OSSI;

    TIM1->CCR1 = 0u;
    TIM1->CCR2 = 0u;
    TIM1->CCR3 = 0u;
    TIM1->CCER = 0u;
    duty_milli_applied = 0u;

    TIM1->EGR = TIM_EGR_UG | TIM_EGR_COMG; /* load every preload register */
    TIM1->SR = 0u;

    gpio_as_af(HSA_PORT, HSA_PIN, GATE_AF);
    gpio_as_af(LSA_PORT, LSA_PIN, GATE_AF);
    gpio_as_af(HSB_PORT, HSB_PIN, GATE_AF);
    gpio_as_af(LSB_PORT, LSB_PIN, GATE_AF);
    gpio_as_af(HSC_PORT, HSC_PIN, GATE_AF);
    gpio_as_af(LSC_PORT, LSC_PIN, GATE_AF);

    TIM1->CR1 |= TIM_CR1_CEN;
}

void motor_hw_set_duty(uint32_t duty_milli)
{
    if (duty_milli > MAX_DUTY_MILLI) {
        duty_milli = MAX_DUTY_MILLI;
    }
    duty_milli_applied = duty_milli;

    /* 64-bit intermediate: PWM_TICKS * 100000 overflows 32 bits at this
     * PWM frequency. */
    const uint32_t compare = (uint32_t)(((uint64_t)duty_milli * PWM_TICKS) / 100000ull);
    TIM1->CCR1 = compare;
    TIM1->CCR2 = compare;
    TIM1->CCR3 = compare;
}

uint32_t motor_hw_duty_milli(void)
{
    return duty_milli_applied;
}

/* A phase's role is expressed entirely through OCxM and the two enable bits,
 * never through CCRx:
 *
 *   Source: OCxM = PWM mode 1, CCxE = 1, CCxNE = 0.
 *   Sink:   OCxM = force inactive (OCxREF low), CCxE = 0, CCxNE = 1. OCxN is
 *           the inverse of OCxREF, so the low side sits on continuously.
 *   Float:  OCxM = force inactive, neither output enabled; OSSR then holds
 *           both gate pins low, so the phase node -- not the gate pin -- is
 *           what goes high impedance.
 *
 * Keeping CCRx constant matters. CCPC preloads OCxM, CCxE and CCxNE and
 * applies them on a COM event, but CCRx is preloaded against the *update*
 * event instead. Encoding the role in CCRx would therefore leave up to one PWM
 * period (31 us here) where the new enable bits are paired with the old
 * compare value -- a sink phase would chop instead of sitting on. Encoding it
 * in OCxM keeps the whole sector change inside the one COM event, and the
 * dead-time generator still inserts the dead time when OCxREF moves.
 */
static uint32_t oc_mode(enum phase_drive drive)
{
    return (drive == PHASE_SOURCE) ? OCM_PWM1 : OCM_FORCE_INACTIVE;
}

static uint32_t ccer_bits(enum phase_drive drive, uint32_t enable, uint32_t enable_n)
{
    switch (drive) {
    case PHASE_SOURCE:
        return enable;
    case PHASE_SINK:
        return enable_n;
    case PHASE_FLOAT:
    default:
        return 0u;
    }
}

void motor_hw_set_bridge(enum phase_drive a, enum phase_drive b, enum phase_drive c)
{
    TIM1->CCMR1 = (oc_mode(a) << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE
                | (oc_mode(b) << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = (oc_mode(c) << TIM_CCMR2_OC3M_Pos) | TIM_CCMR2_OC3PE;

    TIM1->CCER = ccer_bits(a, TIM_CCER_CC1E, TIM_CCER_CC1NE)
               | ccer_bits(b, TIM_CCER_CC2E, TIM_CCER_CC2NE)
               | ccer_bits(c, TIM_CCER_CC3E, TIM_CCER_CC3NE);

    TIM1->EGR = TIM_EGR_COMG; /* all six outputs change in one hardware step */
}

void motor_hw_set_complementary_a(void)
{
    /* The only arrangement where OC1 and OC1N are both enabled, so the only
     * one that exercises the dead-time generator on a chopping edge. */
    TIM1->CCMR1 = (OCM_PWM1 << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE
                | (OCM_FORCE_INACTIVE << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = (OCM_FORCE_INACTIVE << TIM_CCMR2_OC3M_Pos) | TIM_CCMR2_OC3PE;
    TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE;
    TIM1->EGR = TIM_EGR_COMG;
}

void motor_hw_drive_single_gate(uint32_t phase, bool high_side)
{
    /* Forcing OCxREF active drives the high side on continuously; forcing it
     * inactive drives OCxN, the low side, on continuously. Only one enable bit
     * is ever set, so the pair is never complementary and the dead-time
     * generator has nothing to do. */
    const uint32_t mode = high_side ? OCM_FORCE_ACTIVE : OCM_FORCE_INACTIVE;
    uint32_t modes[3] = {OCM_FORCE_INACTIVE, OCM_FORCE_INACTIVE, OCM_FORCE_INACTIVE};
    uint32_t ccer = 0u;

    if (phase < 3u) {
        modes[phase] = mode;
        static const uint32_t enable[3] = {TIM_CCER_CC1E, TIM_CCER_CC2E, TIM_CCER_CC3E};
        static const uint32_t enable_n[3] = {TIM_CCER_CC1NE, TIM_CCER_CC2NE, TIM_CCER_CC3NE};
        ccer = high_side ? enable[phase] : enable_n[phase];
    }

    TIM1->CCMR1 = (modes[0] << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE
                | (modes[1] << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = (modes[2] << TIM_CCMR2_OC3M_Pos) | TIM_CCMR2_OC3PE;
    TIM1->CCER = ccer;
    TIM1->EGR = TIM_EGR_COMG;
}

void motor_hw_read_bridge(uint32_t *ccer, uint32_t *ccmr1, uint32_t *ccmr2)
{
    /* The active registers, not the preload shadows: CCPC makes CCER and OCxM
     * take effect on a COM event, and only the applied value is readable. */
    *ccer = TIM1->CCER;
    *ccmr1 = TIM1->CCMR1;
    *ccmr2 = TIM1->CCMR2;
}

void motor_hw_enable(void)
{
    TIM1->BDTR |= TIM_BDTR_MOE;
}

void motor_hw_disable(void)
{
    /* The single operation that actually releases the gates. Everything else
     * in the stop path is confirmation. */
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    TIM1->CCMR1 = (OCM_FORCE_INACTIVE << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE
                | (OCM_FORCE_INACTIVE << TIM_CCMR1_OC2M_Pos) | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = (OCM_FORCE_INACTIVE << TIM_CCMR2_OC3M_Pos) | TIM_CCMR2_OC3PE;
    TIM1->CCER = 0u;
    TIM1->EGR = TIM_EGR_COMG;
    TIM1->CCR1 = 0u;
    TIM1->CCR2 = 0u;
    TIM1->CCR3 = 0u;
}

bool motor_hw_is_enabled(void)
{
    return (TIM1->BDTR & TIM_BDTR_MOE) != 0u;
}
