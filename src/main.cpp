#include <iostream>
#include <csignal>
#include <cmath>
#include <algorithm>
#include <thread>
#include <chrono>

#include "Constants.hpp"
#include "MotorController.hpp"
#include "InputManager.hpp"

std::atomic<bool> running{true};

void signalHandler(int) {
    running.store(false);
}

int clamp(int value, int minValue, int maxValue) {
    return std::max(minValue, std::min(value, maxValue));
}

int scaleAxis(int16_t raw) {
    double normalized = static_cast<double>(raw) / Constants::MAX_JOYSTICK_VALUE;
    int scaled = static_cast<int>(std::lround(normalized * 512.0));
    return clamp(scaled, -512, 512);
}

int16_t commandToSpeed(int command) {
    if (std::abs(command) < Constants::JOYSTICK_DEADZONE) {
        return 0;
    }
    long scaled = static_cast<long>(command) * Constants::MAX_SPEED_STEPS_PER_SEC;
    scaled /= 512;
    return static_cast<int16_t>(scaled);
}

int main(int argc, char* argv[]) {
    const char* joystickPath = (argc > 1) ? argv[1] : nullptr;

    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);

    MotorController motorController;
    if (!motorController.initialize()) {
        return 1;
    }

    InputManager inputManager;
    inputManager.start(joystickPath);

    std::cout << "System initialized. Waiting for input..." << std::endl;

    auto nextLogTime = std::chrono::steady_clock::now();

    while (running.load(std::memory_order_relaxed)) {
        // Read Inputs
        int xScaled = -scaleAxis(inputManager.getAxis(Constants::JOYSTICK_AXIS_X));
        int yScaled = -scaleAxis(inputManager.getAxis(Constants::JOYSTICK_AXIS_Y));
        int rxScaled = scaleAxis(inputManager.getAxis(Constants::JOYSTICK_AXIS_RX));
        int ryScaled = -scaleAxis(inputManager.getAxis(Constants::JOYSTICK_AXIS_RY));

        // Deadzone
        int xCommandRaw = (std::abs(xScaled) < Constants::JOYSTICK_DEADZONE) ? 0 : xScaled;
        int yCommandRaw = (std::abs(yScaled) < Constants::JOYSTICK_DEADZONE) ? 0 : yScaled;
        int panCommand = (std::abs(rxScaled) < Constants::JOYSTICK_DEADZONE) ? 0 : rxScaled;
        int tiltCommand = (std::abs(ryScaled) < Constants::JOYSTICK_DEADZONE) ? 0 : ryScaled;

        // Mixing (X = forward/backward, Y = turning)
        int leftMixCommand = clamp(xCommandRaw + yCommandRaw, -512, 512);
        int rightMixCommand = clamp(xCommandRaw - yCommandRaw, -512, 512);

        // Update Motors
        motorController.setSpeed(MotorController::LEFT, commandToSpeed(leftMixCommand));
        motorController.setSpeed(MotorController::RIGHT, commandToSpeed(rightMixCommand));
        motorController.setSpeed(MotorController::PAN, commandToSpeed(panCommand));
        motorController.setSpeed(MotorController::TILT, commandToSpeed(tiltCommand));

        // Logging
        auto now = std::chrono::steady_clock::now();
        if (now >= nextLogTime) {
            std::cout << "JOY X=" << xCommandRaw
                      << " Y=" << yCommandRaw
                      << " RX=" << panCommand
                      << " RY=" << tiltCommand
                      << " MixL=" << leftMixCommand
                      << " MixR=" << rightMixCommand
                      << std::endl;
            nextLogTime = now + std::chrono::milliseconds(Constants::LOG_INTERVAL_MS);
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    std::cout << "Shutting down..." << std::endl;
    inputManager.stop();
    motorController.stop();

    return 0;
}
