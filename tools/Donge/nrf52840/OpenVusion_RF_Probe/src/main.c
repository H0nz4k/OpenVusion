#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/ring_buffer.h>
#include <zephyr/usb/usbd.h>

#include <hal/nrf_radio.h>

#include <errno.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * OpenVusion RF Probe v0.6.1
 *
 * USB design:
 *   - Zephyr USB device-next stack
 *   - explicit USBD_DEVICE_DEFINE / configuration / class registration
 *   - CDC ACM RX via interrupt-driven UART API
 *   - short TX responses via polling UART API from thread context
 *   - no console, no printk, no shell and no automatic CDC helper
 *
 * RF design:
 *   - lazy initialization: RADIO is untouched until ONCE / SCAN START
 *   - receive/RSSI only
 *   - there is intentionally no TASKS_TXEN anywhere in this source
 */

#define FW_NAME "OpenVusion_RF_Probe_v0.6.1"

#define LED0_NODE DT_ALIAS(led0)
#define BOARD_CDC_NODE DT_NODELABEL(board_cdc_acm_uart)

#if !DT_NODE_HAS_STATUS(LED0_NODE, okay)
#error "Board nema dostupny alias led0"
#endif

#if !DT_NODE_HAS_STATUS(BOARD_CDC_NODE, okay)
#error "Board nema vestaveny board_cdc_acm_uart; pouzij nrf52840dongle/nrf52840"
#endif

static const struct gpio_dt_spec led =
    GPIO_DT_SPEC_GET(LED0_NODE, gpios);

/*
 * v0.6: use the board-provided CDC ACM node explicitly.
 *
 * nrf52840dongle/nrf52840 includes boards/common/usb/cdc_acm_serial.dtsi, where the node label is board_cdc_acm_uart.
 * v0.5 added a second CDC node in app.overlay, which created /dev/ttyACM1
 * (interface 00) and /dev/ttyACM2 (interface 02).
 */
static const struct device *const cdc_dev =
    DEVICE_DT_GET(BOARD_CDC_NODE);


/* ------------------------------------------------------------------------- */
/* USB device-next: explicit device/configuration setup                      */
/* ------------------------------------------------------------------------- */

/*
 * LAB / research VID:PID.
 *
 * 0x2FE3 is Zephyr's VID and 0x0001 is the Zephyr CDC ACM sample PID.
 * This is intentionally used only for local research bring-up so the host can
 * clearly distinguish v0.5 from the previous 0x2FE3:0x0004 builds.
 * Do not ship a commercial product with this VID/PID.
 */
#define OPENVUSION_USB_VID 0x2FE3
#define OPENVUSION_USB_PID 0x0001

USBD_DEVICE_DEFINE(openvusion_usbd,
                   DEVICE_DT_GET(DT_NODELABEL(zephyr_udc0)),
                   OPENVUSION_USB_VID,
                   OPENVUSION_USB_PID);

USBD_DESC_LANG_DEFINE(openvusion_lang);
USBD_DESC_MANUFACTURER_DEFINE(openvusion_mfr, "OpenVusion Research");
USBD_DESC_PRODUCT_DEFINE(openvusion_product, "OpenVusion RF Probe v0.6.1");
USBD_DESC_SERIAL_NUMBER_DEFINE(openvusion_sn);
USBD_DESC_CONFIG_DEFINE(openvusion_fs_desc, "OpenVusion FS");

/* bMaxPower is in 2 mA units: 50 => 100 mA. */
USBD_CONFIGURATION_DEFINE(openvusion_fs_config,
                          0,
                          50,
                          &openvusion_fs_desc);

static const char *const class_blocklist[] = {
    "dfu_dfu",
    NULL,
};

static volatile bool usb_vbus_ready;
static volatile bool usb_enabled;
static volatile bool usb_dtr;
static volatile bool usb_rx_seen;


/* ------------------------------------------------------------------------- */
/* CDC RX                                                                    */
/* ------------------------------------------------------------------------- */

#define RX_RING_SIZE 1024
#define RX_FIFO_CHUNK 64
#define CMD_LINE_SIZE 128

RING_BUF_DECLARE(rx_ring, RX_RING_SIZE);

static volatile bool rx_throttled;


static void cdc_irq_handler(const struct device *dev, void *user_data)
{
    ARG_UNUSED(user_data);

    while (true) {
        int pending;
        int ret;

        ret = uart_irq_update(dev);
        if (ret < 0) {
            break;
        }

        pending = uart_irq_is_pending(dev);
        if (pending <= 0) {
            break;
        }

        if (!rx_throttled && uart_irq_rx_ready(dev)) {
            uint8_t buf[RX_FIFO_CHUNK];
            uint32_t space = ring_buf_space_get(&rx_ring);

            if (space == 0U) {
                uart_irq_rx_disable(dev);
                rx_throttled = true;
                continue;
            }

            int want = (int)MIN(space, (uint32_t)sizeof(buf));
            int got = uart_fifo_read(dev, buf, want);

            if (got > 0) {
                uint32_t stored =
                    ring_buf_put(&rx_ring, buf, (uint32_t)got);

                usb_rx_seen = true;

                if (stored < (uint32_t)got) {
                    uart_irq_rx_disable(dev);
                    rx_throttled = true;
                }
            }
        }
    }
}


/* ------------------------------------------------------------------------- */
/* CDC TX - thread context only                                              */
/* ------------------------------------------------------------------------- */

static void cdc_write_bytes(const uint8_t *data, size_t len)
{
    /*
     * v0.6 never sends unsolicited data when the host opens the tty.
     * This avoids the Linux POSIX tty ECHO race that polluted v0.5 commands.
     *
     * Polling TX is deliberately used only from thread context.
     * It keeps the first reliable transport version small and avoids a second
     * application TX queue while RX remains fully interrupt-driven.
     */
    for (size_t i = 0; i < len; i++) {
        uart_poll_out(cdc_dev, data[i]);
    }
}


static void cdc_write(const char *text)
{
    cdc_write_bytes((const uint8_t *)text, strlen(text));
}


static void cdc_printf(const char *fmt, ...)
{
    char buf[256];
    va_list ap;

    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    if (n <= 0) {
        return;
    }

    if (n >= (int)sizeof(buf)) {
        n = (int)sizeof(buf) - 1;
    }

    cdc_write_bytes((const uint8_t *)buf, (size_t)n);
}


/* ------------------------------------------------------------------------- */
/* USB messages / initialization                                             */
/* ------------------------------------------------------------------------- */

static void usb_msg_cb(struct usbd_context *const ctx,
                       const struct usbd_msg *msg)
{
    if (msg->type == USBD_MSG_VBUS_READY) {
        usb_vbus_ready = true;

        if (!usb_enabled) {
            if (usbd_enable(ctx) == 0) {
                usb_enabled = true;
            }
        }
        return;
    }

    if (msg->type == USBD_MSG_VBUS_REMOVED) {
        usb_vbus_ready = false;
        usb_dtr = false;

        if (usb_enabled) {
            (void)usbd_disable(ctx);
            usb_enabled = false;
        }
        return;
    }

    if (msg->type == USBD_MSG_CDC_ACM_CONTROL_LINE_STATE) {
        uint32_t dtr = 0U;

        if (uart_line_ctrl_get(msg->dev,
                               UART_LINE_CTRL_DTR,
                               &dtr) == 0) {
            usb_dtr = (dtr != 0U);
        }
    }
}


static int openvusion_usb_init(void)
{
    int err;

    if (!device_is_ready(cdc_dev)) {
        return -ENODEV;
    }

    err = usbd_add_descriptor(&openvusion_usbd, &openvusion_lang);
    if (err) {
        return err;
    }

    err = usbd_add_descriptor(&openvusion_usbd, &openvusion_mfr);
    if (err) {
        return err;
    }

    err = usbd_add_descriptor(&openvusion_usbd, &openvusion_product);
    if (err) {
        return err;
    }

    err = usbd_add_descriptor(&openvusion_usbd, &openvusion_sn);
    if (err) {
        return err;
    }

    err = usbd_add_configuration(&openvusion_usbd,
                                 USBD_SPEED_FS,
                                 &openvusion_fs_config);
    if (err) {
        return err;
    }

    err = usbd_register_all_classes(&openvusion_usbd,
                                    USBD_SPEED_FS,
                                    1,
                                    class_blocklist);
    if (err) {
        return err;
    }

    /*
     * CDC ACM has multiple interfaces and an IAD. This is the same code triple
     * used by Zephyr's official USB sample for CDC-class configurations.
     */
    err = usbd_device_set_code_triple(&openvusion_usbd,
                                      USBD_SPEED_FS,
                                      USB_BCC_MISCELLANEOUS,
                                      0x02,
                                      0x01);
    if (err) {
        return err;
    }

    err = usbd_msg_register_cb(&openvusion_usbd, usb_msg_cb);
    if (err) {
        return err;
    }

    err = usbd_init(&openvusion_usbd);
    if (err) {
        return err;
    }

    if (!usbd_can_detect_vbus(&openvusion_usbd)) {
        err = usbd_enable(&openvusion_usbd);
        if (err) {
            return err;
        }
        usb_enabled = true;
    }

    /*
     * Arm CDC OUT immediately. We intentionally do NOT make reception
     * conditional on DTR. DTR only tells us whether a terminal is open.
     */
    err = uart_irq_callback_user_data_set(cdc_dev,
                                          cdc_irq_handler,
                                          NULL);
    if (err) {
        return err;
    }

    uart_irq_rx_enable(cdc_dev);

    return 0;
}


/* ------------------------------------------------------------------------- */
/* Passive RF / RSSI                                                         */
/* ------------------------------------------------------------------------- */

static bool radio_initialized;
static bool scan_enabled;
static uint8_t scan_first_ch = 0;
static uint8_t scan_last_ch = 100;
static uint16_t dwell_ms = 4;
static uint32_t sweep_no;


static int radio_disable_safe(void)
{
    if (NRF_RADIO->STATE == RADIO_STATE_STATE_Disabled) {
        return 0;
    }

    NRF_RADIO->EVENTS_DISABLED = 0;
    NRF_RADIO->TASKS_DISABLE = 1;

    int64_t deadline = k_uptime_get() + 20;

    while (NRF_RADIO->EVENTS_DISABLED == 0) {
        if (k_uptime_get() >= deadline) {
            return -ETIMEDOUT;
        }
        k_yield();
    }

    return 0;
}


static int radio_passive_init(void)
{
    if (radio_initialized) {
        return 0;
    }

    NRF_RADIO->POWER = 1;
    NRF_RADIO->MODE = RADIO_MODE_MODE_Nrf_1Mbit;
    NRF_RADIO->SHORTS = 0;

    /*
     * Do not wait for a DISABLED event if the peripheral is already disabled.
     * That was a possible infinite-wait trap in the previous experiment code.
     */
    int ret = radio_disable_safe();
    if (ret != 0) {
        return ret;
    }

    radio_initialized = true;
    return 0;
}


static int sample_rssi_channel(uint8_t ch, int8_t *out_rssi)
{
    int ret = radio_passive_init();
    if (ret != 0) {
        return ret;
    }

    ret = radio_disable_safe();
    if (ret != 0) {
        return ret;
    }

    NRF_RADIO->FREQUENCY = ch;
    NRF_RADIO->MODE = RADIO_MODE_MODE_Nrf_1Mbit;
    NRF_RADIO->SHORTS = 0;
    NRF_RADIO->EVENTS_READY = 0;

    NRF_RADIO->TASKS_RXEN = 1;

    int64_t ready_deadline = k_uptime_get() + 20;

    while (NRF_RADIO->EVENTS_READY == 0) {
        if (k_uptime_get() >= ready_deadline) {
            (void)radio_disable_safe();
            return -ETIMEDOUT;
        }
        k_yield();
    }

    NRF_RADIO->TASKS_RSSISTART = 1;
    k_sleep(K_MSEC(dwell_ms));

    *out_rssi = -(int8_t)NRF_RADIO->RSSISAMPLE;

    NRF_RADIO->TASKS_RSSISTOP = 1;

    return radio_disable_safe();
}


/* ------------------------------------------------------------------------- */
/* Text protocol                                                             */
/* ------------------------------------------------------------------------- */

static void print_info(void)
{
    cdc_write("FW=" FW_NAME "\r\n");
    cdc_write("BOARD=nrf52840dongle/nrf52840\r\n");
    cdc_write("USB_STACK=DEVICE_NEXT_EXPLICIT\r\n");
    cdc_write("USB_CDC_COUNT=1\r\n");
    cdc_write("USB_CDC_NODE=board_cdc_acm_uart\r\n");
    cdc_write("USB_UNSOLICITED_TX=OFF\r\n");
    cdc_write("USB_AUTO_INIT=OFF\r\n");
    cdc_write("USB_CONSOLE=OFF\r\n");
    cdc_write("USB_RX=IRQ\r\n");
    cdc_write("USB_TX=POLL_THREAD\r\n");
    cdc_printf("USB_DTR=%u\r\n", usb_dtr ? 1U : 0U);
    cdc_printf("USB_VBUS=%u\r\n", usb_vbus_ready ? 1U : 0U);
    cdc_printf("USB_ENABLED=%u\r\n", usb_enabled ? 1U : 0U);
    cdc_write("RF_TX=DISABLED_BY_DESIGN\r\n");
    cdc_printf("RANGE=%u..%u\r\n", scan_first_ch, scan_last_ch);
    cdc_printf("FREQ=%u..%uMHz\r\n",
               2400U + scan_first_ch,
               2400U + scan_last_ch);
    cdc_printf("DWELL_MS=%u\r\n", dwell_ms);
}


static int run_one_sweep(void)
{
    int ret = radio_passive_init();
    if (ret != 0) {
        cdc_printf("ERR RADIO_INIT=%d\r\n", ret);
        return ret;
    }

    sweep_no++;

    cdc_printf("SWEEP,%u,%lld",
               sweep_no,
               (long long)k_uptime_get());

    for (uint16_t ch = scan_first_ch;
         ch <= scan_last_ch;
         ch++) {

        int8_t rssi = 0;

        ret = sample_rssi_channel((uint8_t)ch, &rssi);
        if (ret != 0) {
            cdc_printf(",%u:ERR%d", 2400U + ch, ret);
            continue;
        }

        cdc_printf(",%u:%d", 2400U + ch, rssi);
    }

    cdc_write("\r\n");
    return 0;
}


static void handle_command(char *cmd)
{
    unsigned int a;
    unsigned int b;
    unsigned int v;

    if (!strcmp(cmd, "PING") || !strcmp(cmd, "ping")) {
        cdc_write("PONG v0.6.1\r\n");

    } else if (!strcmp(cmd, "INFO") || !strcmp(cmd, "info")) {
        print_info();

    } else if (!strcmp(cmd, "HELP") || !strcmp(cmd, "help")) {
        cdc_write(
            "PING | INFO | HELP | ONCE | SCAN START | SCAN STOP | "
            "RANGE a b | DWELL ms\r\n"
        );

    } else if (!strcmp(cmd, "ONCE") || !strcmp(cmd, "once")) {
        (void)run_one_sweep();

    } else if (!strcmp(cmd, "SCAN START") ||
               !strcmp(cmd, "scan start")) {
        scan_enabled = true;
        cdc_write("OK SCAN=ON\r\n");

    } else if (!strcmp(cmd, "SCAN STOP") ||
               !strcmp(cmd, "scan stop")) {
        scan_enabled = false;
        cdc_write("OK SCAN=OFF\r\n");

    } else if (sscanf(cmd, "RANGE %u %u", &a, &b) == 2 ||
               sscanf(cmd, "range %u %u", &a, &b) == 2) {

        if (a <= b && b <= 100U) {
            scan_first_ch = (uint8_t)a;
            scan_last_ch = (uint8_t)b;
            cdc_printf("OK RANGE=%u..%u (%u..%uMHz)\r\n",
                       scan_first_ch,
                       scan_last_ch,
                       2400U + scan_first_ch,
                       2400U + scan_last_ch);
        } else {
            cdc_write(
                "ERR RANGE must satisfy 0 <= first <= last <= 100\r\n"
            );
        }

    } else if (sscanf(cmd, "DWELL %u", &v) == 1 ||
               sscanf(cmd, "dwell %u", &v) == 1) {

        if (v >= 1U && v <= 100U) {
            dwell_ms = (uint16_t)v;
            cdc_printf("OK DWELL_MS=%u\r\n", dwell_ms);
        } else {
            cdc_write("ERR DWELL must be 1..100 ms\r\n");
        }

    } else if (cmd[0] != '\0') {
        cdc_printf("ERR unknown command: %s\r\n", cmd);
    }
}


/* ------------------------------------------------------------------------- */
/* LED helpers                                                               */
/* ------------------------------------------------------------------------- */

static void fatal_blink(unsigned int pulses)
{
    while (1) {
        for (unsigned int i = 0; i < pulses; i++) {
            gpio_pin_set_dt(&led, 1);
            k_sleep(K_MSEC(120));
            gpio_pin_set_dt(&led, 0);
            k_sleep(K_MSEC(120));
        }

        k_sleep(K_MSEC(900));
    }
}


/* ------------------------------------------------------------------------- */
/* Main                                                                      */
/* ------------------------------------------------------------------------- */

int main(void)
{
    char line[CMD_LINE_SIZE];
    size_t pos = 0U;
    int64_t last_heartbeat;

    if (!device_is_ready(led.port)) {
        return 1;
    }

    if (gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE) != 0) {
        return 2;
    }

    /*
     * Failure code:
     *   3 short LED pulses = USB initialization failed.
     */
    if (openvusion_usb_init() != 0) {
        fatal_blink(3);
    }

    last_heartbeat = k_uptime_get();

    while (1) {
        uint8_t c;

        while (ring_buf_get(&rx_ring, &c, 1) == 1U) {
            if (c == '\r' || c == '\n') {
                if (pos > 0U) {
                    line[pos] = '\0';
                    handle_command(line);
                    pos = 0U;
                }
            } else if ((c == '\b' || c == 0x7f) && pos > 0U) {
                pos--;
            } else if (c >= 0x20 &&
                       c <= 0x7e &&
                       pos < sizeof(line) - 1U) {
                line[pos++] = (char)c;
            }
        }

        if (rx_throttled &&
            ring_buf_space_get(&rx_ring) >= (RX_RING_SIZE / 2U)) {
            rx_throttled = false;
            uart_irq_rx_enable(cdc_dev);
        }

        if (scan_enabled && usb_dtr) {
            (void)run_one_sweep();
        }

        /*
         * Slow heartbeat. The RADIO is not initialized here.
         */
        if ((k_uptime_get() - last_heartbeat) >= 1000) {
            gpio_pin_toggle_dt(&led);
            last_heartbeat = k_uptime_get();
            usb_rx_seen = false;
        }

        k_sleep(K_MSEC(2));
    }

    return 0;
}
