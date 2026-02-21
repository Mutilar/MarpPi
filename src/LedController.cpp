#include "LedController.hpp"
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <algorithm>

// ─── Face-segment table ─────────────────────────────────────────────────────
//
//  TODO: populate once the physical LED layout on the face is finalised.
//        Each entry maps a logical name → (start pixel, pixel count).
//        The sum of all segments need not cover the full strip; gaps are fine.
//
//  Example (uncomment / edit when ready):
//
//    { "left_eye",   0,  12 },
//    { "right_eye", 20,  12 },
//    { "mouth",     40,  30 },
//
static const std::vector<LedSegment> kFaceSegments = {
    // ── placeholder ── fill in when wiring map is known ──
};

// ─── WS2815 NRZ timing via SPI ──────────────────────────────────────────────
//
//  The WS2815 uses the same 800 kHz NRZ protocol as WS2812B.
//  Each data bit is encoded as a multi-bit SPI pattern at ~6.4 MHz:
//
//    Bit 1 → 0b11110000  (high ≈ 0.625 µs, low ≈ 0.625 µs)
//    Bit 0 → 0b11000000  (high ≈ 0.3125 µs, low ≈ 0.9375 µs)
//
//  After all pixel data, ≥280 µs of low (reset code) is required.
//  We achieve this with SPI_SPEED_HZ = 6'400'000 and sending 8 SPI bits
//  per WS2815 data bit → 8 bytes per colour byte, 24 bytes per pixel.
//
static constexpr uint8_t BIT_ONE  = 0b11110000;
static constexpr uint8_t BIT_ZERO = 0b11000000;
static constexpr size_t  RESET_BYTES = 32;         // ≥280 µs of zeros at 6.4 MHz

// ─── Construction / destruction ─────────────────────────────────────────────

LedController::LedController()
    : pixels(Constants::LED_PIXEL_COUNT)
{
}

LedController::~LedController() {
    stop();
}

// ─── Initialisation ─────────────────────────────────────────────────────────

bool LedController::initialize() {
    spiFd = open(Constants::LED_SPI_DEVICE, O_RDWR);
    if (spiFd < 0) {
        std::cerr << "LED: failed to open SPI device "
                  << Constants::LED_SPI_DEVICE << ": "
                  << strerror(errno) << '\n';
        return false;
    }

    uint8_t  mode  = SPI_MODE_0;
    uint8_t  bits  = 8;
    uint32_t speed = Constants::LED_SPI_SPEED_HZ;

    if (ioctl(spiFd, SPI_IOC_WR_MODE,          &mode)  < 0 ||
        ioctl(spiFd, SPI_IOC_WR_BITS_PER_WORD, &bits)  < 0 ||
        ioctl(spiFd, SPI_IOC_WR_MAX_SPEED_HZ,  &speed) < 0)
    {
        std::cerr << "LED: SPI ioctl configuration failed\n";
        close(spiFd);
        spiFd = -1;
        return false;
    }

    // Start dark
    clear();
    show();

    std::cout << "LED: WS2815 strip ready ("
              << Constants::LED_PIXEL_COUNT << " px on "
              << Constants::LED_SPI_DEVICE  << " @ "
              << Constants::LED_SPI_SPEED_HZ / 1000000.0 << " MHz)\n";

    if (kFaceSegments.empty()) {
        std::cout << "LED: (no face segments defined yet – "
                     "populate kFaceSegments when layout is finalised)\n";
    } else {
        std::cout << "LED: " << kFaceSegments.size()
                  << " face segment(s) registered\n";
        for (const auto& seg : kFaceSegments) {
            std::cout << "  · " << seg.name
                      << "  [" << seg.start
                      << ".." << (seg.start + seg.count - 1) << "]\n";
        }
    }

    return true;
}

void LedController::stop() {
    if (spiFd >= 0) {
        clear();
        show();
        close(spiFd);
        spiFd = -1;
        std::cout << "LED: strip shut down\n";
    }
}

// ─── Pixel access ───────────────────────────────────────────────────────────

void LedController::setPixel(uint16_t index, uint8_t r, uint8_t g, uint8_t b) {
    if (index >= pixels.size()) return;
    std::lock_guard<std::mutex> lk(bufferMutex);
    pixels[index] = {r, g, b};
}

void LedController::setPixel(uint16_t index, const Pixel& px) {
    setPixel(index, px.r, px.g, px.b);
}

Pixel LedController::getPixel(uint16_t index) const {
    if (index >= pixels.size()) return {};
    std::lock_guard<std::mutex> lk(bufferMutex);
    return pixels[index];
}

void LedController::fill(uint8_t r, uint8_t g, uint8_t b) {
    std::lock_guard<std::mutex> lk(bufferMutex);
    for (auto& px : pixels) px = {r, g, b};
}

void LedController::fill(const Pixel& px) {
    fill(px.r, px.g, px.b);
}

void LedController::clear() {
    fill(0, 0, 0);
}

// ─── Segment helpers ────────────────────────────────────────────────────────

const std::vector<LedSegment>& LedController::segments() const {
    return kFaceSegments;
}

const LedSegment* LedController::findSegment(const char* name) const {
    for (const auto& seg : kFaceSegments) {
        if (std::strcmp(seg.name, name) == 0) return &seg;
    }
    return nullptr;
}

void LedController::fillSegment(const char* name, const Pixel& px) {
    const auto* seg = findSegment(name);
    if (!seg) return;
    std::lock_guard<std::mutex> lk(bufferMutex);
    uint16_t end = std::min<uint16_t>(seg->start + seg->count,
                                       static_cast<uint16_t>(pixels.size()));
    for (uint16_t i = seg->start; i < end; ++i) {
        pixels[i] = px;
    }
}

void LedController::fillSegment(const char* name, uint8_t r, uint8_t g, uint8_t b) {
    fillSegment(name, Pixel{r, g, b});
}

// ─── Brightness ─────────────────────────────────────────────────────────────

void LedController::setBrightness(uint8_t b) {
    brightness = b;
}

uint8_t LedController::getBrightness() const {
    return brightness;
}

// ─── SPI NRZ encoding ───────────────────────────────────────────────────────

void LedController::encodeByte(uint8_t byte, std::vector<uint8_t>& out) const {
    for (int bit = 7; bit >= 0; --bit) {
        out.push_back((byte & (1 << bit)) ? BIT_ONE : BIT_ZERO);
    }
}

void LedController::buildSpiFrame(std::vector<uint8_t>& frame) const {
    // 8 SPI bytes per colour byte × 3 colours per pixel + reset
    const size_t dataBytes = pixels.size() * 3 * 8;
    frame.clear();
    frame.reserve(dataBytes + RESET_BYTES);

    // WS2815 expects GRB byte order
    for (const auto& px : pixels) {
        auto scale = [this](uint8_t ch) -> uint8_t {
            return static_cast<uint8_t>((static_cast<uint16_t>(ch) * brightness) / 255);
        };
        encodeByte(scale(px.g), frame);
        encodeByte(scale(px.r), frame);
        encodeByte(scale(px.b), frame);
    }

    // Reset code (low for ≥280 µs)
    frame.insert(frame.end(), RESET_BYTES, 0x00);
}

// ─── Flush to strip ─────────────────────────────────────────────────────────

void LedController::show() {
    if (spiFd < 0) return;

    std::vector<uint8_t> frame;
    {
        std::lock_guard<std::mutex> lk(bufferMutex);
        buildSpiFrame(frame);
    }

    struct spi_ioc_transfer xfer{};
    xfer.tx_buf        = reinterpret_cast<uintptr_t>(frame.data());
    xfer.len           = static_cast<uint32_t>(frame.size());
    xfer.speed_hz      = Constants::LED_SPI_SPEED_HZ;
    xfer.bits_per_word = 8;

    if (ioctl(spiFd, SPI_IOC_MESSAGE(1), &xfer) < 0) {
        std::cerr << "LED: SPI transfer failed: " << strerror(errno) << '\n';
    }
}
