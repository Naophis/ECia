#include "capture.h"

#include "board.h"
#include "hil.h"

/* DMA1 channel 1 is driven by DMAMUX channel 0. TIM7's update request is
 * DMAMUX request ID 9 (stm32g4xx_ll_dmamux.h: LL_DMAMUX_REQ_TIM7_UP). */
#define DMAMUX_REQ_TIM7_UP 9u

static bool running;

void capture_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_DMA1EN | RCC_AHB1ENR_DMAMUX1EN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM7EN;
    (void)RCC->APB1ENR1;

    TIM7->CR1 = 0u;
    TIM7->PSC = 0u;
    TIM7->ARR = CAPTURE_TICKS_PER_SAMPLE - 1u;
    TIM7->EGR = TIM_EGR_UG;
    TIM7->SR = 0u;

    DMAMUX1_Channel0->CCR = DMAMUX_REQ_TIM7_UP;

    DMA1_Channel1->CCR = 0u;
    DMA1_Channel1->CPAR = CAPTURE_PORT_IDR;
    DMA1_Channel1->CMAR = (uint32_t)&hil_capture.data[0];
    running = false;
}

void capture_start(uint32_t seq)
{
    capture_abort();

    hil_capture.seq = seq;
    hil_capture.samples = 0u;

    DMA1->IFCR = DMA_IFCR_CGIF1;
    DMA1_Channel1->CNDTR = CAPTURE_SAMPLES;
    DMA1_Channel1->CMAR = (uint32_t)&hil_capture.data[0];
    /* Peripheral -> memory, 16-bit both ends, memory incrementing, one shot.
     * No interrupt: the main loop polls, so nothing competes with the control
     * path for CPU time. */
    DMA1_Channel1->CCR = DMA_CCR_MINC
                       | (1u << DMA_CCR_PSIZE_Pos)
                       | (1u << DMA_CCR_MSIZE_Pos)
                       | DMA_CCR_EN;

    TIM7->DIER = TIM_DIER_UDE;
    TIM7->CNT = 0u;
    TIM7->CR1 = TIM_CR1_CEN;
    running = true;
}

bool capture_poll(void)
{
    if (!running) {
        return hil_capture.samples != 0u;
    }
    if (!(DMA1->ISR & DMA_ISR_TCIF1)) {
        return false;
    }
    TIM7->CR1 = 0u;
    TIM7->DIER = 0u;
    DMA1_Channel1->CCR = 0u;
    DMA1->IFCR = DMA_IFCR_CGIF1;
    hil_capture.samples = CAPTURE_SAMPLES;
    running = false;
    return true;
}

void capture_abort(void)
{
    TIM7->CR1 = 0u;
    TIM7->DIER = 0u;
    DMA1_Channel1->CCR = 0u;
    DMA1->IFCR = DMA_IFCR_CGIF1;
    running = false;
}
