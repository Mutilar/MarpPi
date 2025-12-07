#include "MotorController.hpp"
#include <lgpio.h>
#include <iostream>
#include <cmath>
#include <chrono>

MotorController::MotorController() {
    // Initialize motor states
    motors.push_back(new MotorState{{Constants::MOTOR_LEFT_ENABLE, Constants::MOTOR_LEFT_DIRECTION, Constants::MOTOR_LEFT_PULSE}});
    motors.push_back(new MotorState{{Constants::MOTOR_RIGHT_ENABLE, Constants::MOTOR_RIGHT_DIRECTION, Constants::MOTOR_RIGHT_PULSE}});
    motors.push_back(new MotorState{{Constants::MOTOR_PAN_ENABLE, Constants::MOTOR_PAN_DIRECTION, Constants::MOTOR_PAN_PULSE}});
    motors.push_back(new MotorState{{Constants::MOTOR_TILT_ENABLE, Constants::MOTOR_TILT_DIRECTION, Constants::MOTOR_TILT_PULSE}});
}

MotorController::~MotorController() {
    stop();
    for (auto m : motors) delete m;
    if (hGpio >= 0) lgGpiochipClose(hGpio);
}

bool MotorController::initialize() {
    // Open GPIO chip 4 (standard for Pi 5 header)
    hGpio = lgGpiochipOpen(4);
    if (hGpio < 0) {
        std::cerr << "lgpio initialisation failed (chip 4)" << '\n';
        return false;
    }

    if (Constants::LED_GPIO >= 0) {
        lgGpioClaimOutput(hGpio, 0, Constants::LED_GPIO, 0);
    }

    for (auto motor : motors) {
        ensurePinSetup(motor->pins);
        workers.emplace_back(&MotorController::worker, this, motor);
    }
    return true;
}

void MotorController::stop() {
    running.store(false);
    for (auto& t : workers) {
        if (t.joinable()) t.join();
    }
    workers.clear();
}

void MotorController::setSpeed(int motorIndex, int16_t speed) {
    if (motorIndex >= 0 && motorIndex < motors.size()) {
        motors[motorIndex]->targetSpeed.store(speed, std::memory_order_relaxed);
    }
}

void MotorController::ensurePinSetup(const MotorPins& pins) {
    lgGpioClaimOutput(hGpio, 0, pins.enable, Constants::ENABLE_ACTIVE_LEVEL);
    lgGpioClaimOutput(hGpio, 0, pins.direction, 1);
    lgGpioClaimOutput(hGpio, 0, pins.pulse, !Constants::PULSE_ACTIVE_LEVEL);
}

uint32_t MotorController::tickDiff(uint32_t later, uint32_t earlier) {
    return (later >= earlier) ? (later - earlier)
                              : (0xFFFFFFFFu - earlier + 1u + later);
}

uint64_t MotorController::steadyClockMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

void MotorController::worker(MotorState* motor) {
    // Identify which motor this is for logging
    int motorIndex = -1;
    for (size_t i = 0; i < motors.size(); ++i) {
        if (motors[i] == motor) { motorIndex = i; break; }
    }
    
    auto getTick = []() { return (uint32_t)(lguTimestamp() / 1000); };
    auto delayUs = [](uint32_t us) {
        if (us > 100) lguSleep(us / 1e6);
        else {
            uint64_t end = lguTimestamp() + (uint64_t)us * 1000;
            while (lguTimestamp() < end);
        }
    };

    uint32_t lastStepTick = getTick();
    int16_t lastLoggedSpeed = 0;
    while (running.load(std::memory_order_relaxed)) {
        int16_t speed = motor->targetSpeed.load(std::memory_order_relaxed);
        
        if (speed == 0) {
            if (motor->enabled) {
                lgGpioWrite(hGpio, motor->pins.enable, !Constants::ENABLE_ACTIVE_LEVEL);
                motor->enabled = false;
            }
            lguSleep(0.002);
            continue;
        }

        if (!motor->enabled) {
            lgGpioWrite(hGpio, motor->pins.enable, Constants::ENABLE_ACTIVE_LEVEL);
            motor->enabled = true;
        }

        bool forward = (speed > 0);
        if (motor->directionForward != forward) {
            lgGpioWrite(hGpio, motor->pins.direction, forward ? 1 : 0);
            motor->directionForward = forward;
            lastStepTick = getTick();
        }

        uint16_t absSpeed = static_cast<uint16_t>(std::abs(speed));
        unsigned long stepInterval = 1000000UL / absSpeed;
        if (stepInterval <= Constants::PULSE_WIDTH_US) {
            stepInterval = Constants::PULSE_WIDTH_US + 1;
        }

        uint32_t nowTick = getTick();
        uint32_t elapsed = tickDiff(nowTick, lastStepTick);
        if (elapsed >= stepInterval) {
            lgGpioWrite(hGpio, motor->pins.pulse, Constants::PULSE_ACTIVE_LEVEL);
            delayUs(Constants::PULSE_WIDTH_US);
            lgGpioWrite(hGpio, motor->pins.pulse, !Constants::PULSE_ACTIVE_LEVEL);
            lastStepTick = getTick();

            if (Constants::LED_GPIO >= 0) {
                stepIndicatorDeadlineMs.store(steadyClockMs() + Constants::STEP_LED_DURATION_MS,
                                              std::memory_order_relaxed);
                if (!stepIndicatorOn.exchange(true, std::memory_order_relaxed)) {
                    lgGpioWrite(hGpio, Constants::LED_GPIO, 1);
                }
            }
            continue;
        }

        // Check LED turn off
        if (Constants::LED_GPIO >= 0 && stepIndicatorOn.load(std::memory_order_relaxed)) {
            uint64_t deadline = stepIndicatorDeadlineMs.load(std::memory_order_relaxed);
            if (steadyClockMs() >= deadline) {
                lgGpioWrite(hGpio, Constants::LED_GPIO, 0);
                stepIndicatorOn.store(false, std::memory_order_relaxed);
            }
        }

        uint32_t waitUs = stepInterval - elapsed;
        if (waitUs > 1000) {
            waitUs = 1000;
        }
        delayUs(waitUs);
    }

    lgGpioWrite(hGpio, motor->pins.pulse, !Constants::PULSE_ACTIVE_LEVEL);
    lgGpioWrite(hGpio, motor->pins.enable, !Constants::ENABLE_ACTIVE_LEVEL);
}
