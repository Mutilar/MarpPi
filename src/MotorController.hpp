#pragma once
#include <atomic>
#include <thread>
#include <vector>
#include "Constants.hpp"

struct MotorPins {
    unsigned enable;
    unsigned direction;
    unsigned pulse;
};

struct MotorState {
    MotorPins pins;
    std::atomic<int16_t> targetSpeed{0};
    bool directionForward{true};
    bool enabled{false};
};

class MotorController {
public:
    MotorController();
    ~MotorController();

    bool initialize();
    void stop();
    void setSpeed(int motorIndex, int16_t speed);

    // Motor Indices
    static constexpr int LEFT = 0;
    static constexpr int RIGHT = 1;
    static constexpr int PAN = 2;
    static constexpr int TILT = 3;

private:
    int hGpio = -1;
    std::vector<MotorState*> motors;
    std::vector<std::thread> workers;
    std::atomic<bool> running{true};
    
    // LED handling
    std::atomic<bool> stepIndicatorOn{false};
    std::atomic<uint64_t> stepIndicatorDeadlineMs{0};

    void worker(MotorState* motor);
    void ensurePinSetup(const MotorPins& pins);
    
    // Helpers
    static uint32_t tickDiff(uint32_t later, uint32_t earlier);
    static uint64_t steadyClockMs();
};
