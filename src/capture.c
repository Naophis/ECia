#include "capture.h"

#include "board.h"
#include "hil.h"

/* TIM7's update request is DMAMUX request ID 9 (stm32g4xx_ll_dmamux.h:
 * LL_DMAMUX_REQ_TIM7_UP). DMAMUX allows the same request on several channels,
 * so DMA1 channels 1-3 sample GPIOA, GPIOB and GPIOF off the same update --
 * the three streams advance together, within a few bus cycles of each other.
 * That is what makes the six gate signals comparable, even though they are
 * spread across three ports. */
#define DMAMUX_REQ_TIM7_UP 9u

static bool running;

typedef struct {
    DMA_Channel_TypeDef *channel;
    DMAMUX_Channel_TypeDef *mux;
    volatile hil_capture_t *capture;
    uint32_t global_flag;
    uint32_t complete_flag;
} capture_stream_t;

static const capture_stream_t streams[] = {
    {DMA1_Channel1, DMAMUX1_Channel0, &hil_capture,   DMA_IFCR_CGIF1, DMA_ISR_TCIF1},
    {DMA1_Channel2, DMAMUX1_Channel1, &hil_capture_b, DMA_IFCR_CGIF2, DMA_ISR_TCIF2},
    {DMA1_Channel3, DMAMUX1_Channel2, &hil_capture_f, DMA_IFCR_CGIF3, DMA_ISR_TCIF3},
};

#define STREAM_COUNT (sizeof(streams) / sizeof(streams[0]))

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

    for (unsigned index = 0u; index < STREAM_COUNT; index++) {
        const capture_stream_t *stream = &streams[index];
        stream->mux->CCR = DMAMUX_REQ_TIM7_UP;
        stream->channel->CCR = 0u;
        stream->channel->CPAR = stream->capture->port_base;
        stream->channel->CMAR = (uint32_t)&stream->capture->data[0];
    }
    running = false;
}

void capture_start(uint32_t seq)
{
    capture_abort();

    for (unsigned index = 0u; index < STREAM_COUNT; index++) {
        const capture_stream_t *stream = &streams[index];
        stream->capture->seq = seq;
        stream->capture->samples = 0u;

        DMA1->IFCR = stream->global_flag;
        stream->channel->CNDTR = CAPTURE_SAMPLES;
        stream->channel->CPAR = stream->capture->port_base;
        stream->channel->CMAR = (uint32_t)&stream->capture->data[0];
        /* Peripheral -> memory, 16-bit both ends, memory incrementing, one
         * shot. No interrupt: the main loop polls, so nothing competes with
         * the control path for CPU time. */
        stream->channel->CCR = DMA_CCR_MINC
                             | (1u << DMA_CCR_PSIZE_Pos)
                             | (1u << DMA_CCR_MSIZE_Pos)
                             | DMA_CCR_EN;
    }

    /* The timer starts last, so every channel is already armed and the three
     * streams see the same first update. */
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
    for (unsigned index = 0u; index < STREAM_COUNT; index++) {
        if (!(DMA1->ISR & streams[index].complete_flag)) {
            return false;
        }
    }

    TIM7->CR1 = 0u;
    TIM7->DIER = 0u;
    for (unsigned index = 0u; index < STREAM_COUNT; index++) {
        streams[index].channel->CCR = 0u;
        DMA1->IFCR = streams[index].global_flag;
        streams[index].capture->samples = CAPTURE_SAMPLES;
    }
    running = false;
    return true;
}

void capture_abort(void)
{
    TIM7->CR1 = 0u;
    TIM7->DIER = 0u;
    for (unsigned index = 0u; index < STREAM_COUNT; index++) {
        streams[index].channel->CCR = 0u;
        DMA1->IFCR = streams[index].global_flag;
    }
    running = false;
}
