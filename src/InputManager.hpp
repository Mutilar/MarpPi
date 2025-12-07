#pragma once
#include <atomic>
#include <thread>
#include "Constants.hpp"

class InputManager {
public:
    InputManager();
    ~InputManager();

    void start(const char* joystickPath = nullptr);
    void stop();
    int16_t getAxis(int axis);

private:
    std::atomic<int16_t> axes[8];
    std::atomic<bool> running{false};
    std::thread joystickThread;
    std::thread udpThread;

    uint64_t lastNetworkUpdateMs{0};
    bool networkActive{false};

    void joystickWorker(std::string path);
    void udpWorker();
    int openJoystick(const char* path);
};
