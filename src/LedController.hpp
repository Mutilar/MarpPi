#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include "Constants.hpp"

// ─── Pixel representation ───────────────────────────────────────────────────
struct Pixel {
    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;
};

// ─── Named face-segment descriptor ─────────────────────────────────────────
//
//  Each segment is a contiguous run of pixels on the strip that maps to a
//  logical region of the robot's face (e.g. "left eye", "mouth").
//
//  Populate the table in LedController.cpp → kFaceSegments once the physical
//  layout is finalised.  Until then the controller still works; callers can
//  address raw pixel indices or iterate segments that have been defined.
//
struct LedSegment {
    const char* name;   // human-readable label  ("left_eye", "mouth", …)
    uint16_t    start;  // first pixel index (0-based)
    uint16_t    count;  // number of pixels in this segment
};

// ─── LED Controller ─────────────────────────────────────────────────────────
//
//  Drives the WS2815 144-pixel strip over SPI (default /dev/spidev0.0).
//  WS2815 uses the same protocol as WS2812B (800 kHz NRZ, GRB byte order)
//  but runs on a 12 V rail with a separate data line (3.3→5 V level-shift).
//
//  Usage:
//      LedController leds;
//      if (!leds.initialize()) { /* handle error */ }
//      leds.setPixel(0, 255, 0, 0);       // first pixel red
//      leds.fillSegment("left_eye", {0, 0, 255});
//      leds.show();                        // flush to strip
//
class LedController {
public:
    LedController();
    ~LedController();

    /// Open the SPI device and allocate the framebuffer.
    bool initialize();

    /// Turn off all pixels and release SPI.
    void stop();

    // ── Raw pixel access ────────────────────────────────────────────────
    void setPixel(uint16_t index, uint8_t r, uint8_t g, uint8_t b);
    void setPixel(uint16_t index, const Pixel& px);
    Pixel getPixel(uint16_t index) const;
    void fill(uint8_t r, uint8_t g, uint8_t b);
    void fill(const Pixel& px);
    void clear();                       // fill(0,0,0)

    // ── Segment helpers (no-op if segment name not found) ───────────────
    void fillSegment(const char* name, const Pixel& px);
    void fillSegment(const char* name, uint8_t r, uint8_t g, uint8_t b);
    const LedSegment* findSegment(const char* name) const;

    /// Flush the current pixel buffer to the strip over SPI.
    void show();

    /// Set global brightness scalar (0–255).  Applied on show().
    void setBrightness(uint8_t brightness);
    uint8_t getBrightness() const;

    /// Total pixel count on the strip.
    uint16_t pixelCount() const { return Constants::LED_PIXEL_COUNT; }

    /// Read-only view of the registered face segments.
    const std::vector<LedSegment>& segments() const;

private:
    int spiFd = -1;                             // file descriptor for SPI device
    uint8_t brightness = Constants::LED_DEFAULT_BRIGHTNESS;
    std::vector<Pixel> pixels;                  // logical framebuffer
    mutable std::mutex bufferMutex;             // guards pixels[]

    // SPI bit-stream encoding (WS2815 NRZ protocol)
    void encodeByte(uint8_t byte, std::vector<uint8_t>& out) const;
    void buildSpiFrame(std::vector<uint8_t>& frame) const;
};
