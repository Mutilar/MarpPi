#pragma once
#include <cstdint>

namespace Constants {
    constexpr int LED_GPIO = 18;                    // Set to -1 to disable the activity LED output.
    
    // Drive Motors
    constexpr unsigned MOTOR_LEFT_ENABLE = 6;
    constexpr unsigned MOTOR_LEFT_DIRECTION = 5;
    constexpr unsigned MOTOR_LEFT_PULSE = 13;
    constexpr unsigned MOTOR_RIGHT_ENABLE = 19;
    constexpr unsigned MOTOR_RIGHT_DIRECTION = 26;
    constexpr unsigned MOTOR_RIGHT_PULSE = 21;

    // Turret Pan/Tilt Pins
    constexpr unsigned MOTOR_PAN_ENABLE = 23;
    constexpr unsigned MOTOR_PAN_DIRECTION = 24;
    constexpr unsigned MOTOR_PAN_PULSE = 25;

    constexpr unsigned MOTOR_TILT_ENABLE = 12;
    constexpr unsigned MOTOR_TILT_DIRECTION = 16;
    constexpr unsigned MOTOR_TILT_PULSE = 20;

    constexpr bool ENABLE_ACTIVE_LEVEL = 0;         // LOW keeps stepper drivers enabled on many boards.
    constexpr bool PULSE_ACTIVE_LEVEL = 1;          // HIGH drives the pulse line active.

    // Joystick
    constexpr int JOYSTICK_AXIS_X = 0;              // Xbox left stick X axis index.
    constexpr int JOYSTICK_AXIS_Y = 1;              // Xbox left stick Y axis index.
    constexpr int JOYSTICK_AXIS_RX = 3;             // Xbox right stick X axis index.
    constexpr int JOYSTICK_AXIS_RY = 4;             // Xbox right stick Y axis index.
    constexpr int JOYSTICK_DEADZONE = 25;
    constexpr int MAX_JOYSTICK_VALUE = 32767;       // Signed 16-bit joystick axis max.
    constexpr char DEFAULT_JOYSTICK_PATH[] = "/dev/input/js0";

    // Network
    constexpr int UDP_PORT = 5005;
    constexpr int UDP_BUFFER_SIZE = 4096;

    // Timing & Speed
    constexpr int16_t MAX_SPEED_STEPS_PER_SEC = 100;
    constexpr unsigned PULSE_WIDTH_US = 20;
    constexpr unsigned STEP_LED_DURATION_MS = 50;
    constexpr unsigned LOG_INTERVAL_MS = 1000;
}
