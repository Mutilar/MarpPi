#include "InputManager.hpp"
#include <iostream>
#include <fcntl.h>
#include <unistd.h>
#include <linux/joystick.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <cstring>
#include <nlohmann/json.hpp>

#include <ifaddrs.h>
#include <netdb.h>

using json = nlohmann::json;

uint64_t currentMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

InputManager::InputManager() {
    for (int i = 0; i < 8; ++i) axes[i] = 0;
}

InputManager::~InputManager() {
    stop();
}

void InputManager::start(const char* joystickPath) {
    running.store(true);
    
    // Log available network interfaces
    struct ifaddrs *ifaddr, *ifa;
    if (getifaddrs(&ifaddr) != -1) {
        std::cout << "Available Network Interfaces:" << std::endl;
        for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
            if (ifa->ifa_addr == NULL) continue;
            if (ifa->ifa_addr->sa_family == AF_INET) {
                char host[NI_MAXHOST];
                int s = getnameinfo(ifa->ifa_addr, sizeof(struct sockaddr_in),
                                    host, NI_MAXHOST, NULL, 0, NI_NUMERICHOST);
                if (s == 0) {
                    std::cout << "  " << ifa->ifa_name << ": " << host << std::endl;
                }
            }
        }
        freeifaddrs(ifaddr);
    }

    std::string path = joystickPath ? joystickPath : Constants::DEFAULT_JOYSTICK_PATH;
    
    joystickThread = std::thread(&InputManager::joystickWorker, this, path);
    udpThread = std::thread(&InputManager::udpWorker, this);
}

void InputManager::stop() {
    running.store(false);
    if (joystickThread.joinable()) joystickThread.join();
    if (udpThread.joinable()) udpThread.join();
}

int16_t InputManager::getAxis(int axis) {
    if (axis >= 0 && axis < 8) {
        return axes[axis].load(std::memory_order_relaxed);
    }
    return 0;
}

int InputManager::openJoystick(const char* path) {
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0) {
        // Only log error if we really expected it, or just once. 
        // For now, we can log to stderr.
        // std::cerr << "Failed to open joystick at " << path << ": " << std::strerror(errno) << '\n';
    }
    return fd;
}

void InputManager::joystickWorker(std::string path) {
    int fd = -1;
    
    while (running.load(std::memory_order_relaxed)) {
        if (fd < 0) {
            fd = openJoystick(path.c_str());
            if (fd < 0) {
                // Retry every second if not found
                std::this_thread::sleep_for(std::chrono::seconds(1));
                continue;
            }
            std::cout << "Joystick connected at " << path << std::endl;
        }

        js_event event;
        ssize_t bytes = read(fd, &event, sizeof(event));
        while (bytes == sizeof(event)) {
            event.type &= ~JS_EVENT_INIT;
            if (event.type == JS_EVENT_AXIS && event.number < 8) {
                axes[event.number].store(event.value, std::memory_order_relaxed);
            }
            bytes = read(fd, &event, sizeof(event));
        }

        if (bytes < 0 && errno != EAGAIN) {
            std::cerr << "Joystick read error: " << std::strerror(errno) << '\n';
            close(fd);
            fd = -1;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    if (fd >= 0) close(fd);
}

void InputManager::udpWorker() {
    int sockfd;
    char buffer[Constants::UDP_BUFFER_SIZE];
    struct sockaddr_in servaddr, cliaddr;

    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("socket creation failed");
        return;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    memset(&cliaddr, 0, sizeof(cliaddr));

    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = INADDR_ANY;
    servaddr.sin_port = htons(Constants::UDP_PORT);

    if (bind(sockfd, (const struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("bind failed");
        close(sockfd);
        return;
    }

    struct timeval tv;
    tv.tv_sec = 0;
    tv.tv_usec = 100000; // 100ms timeout
    setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof tv);

    std::cout << "UDP Listener started on port " << Constants::UDP_PORT << std::endl;
    std::cout << "Waiting for UDP packets..." << std::endl;

    char lastClientIp[INET_ADDRSTRLEN] = {0};
    int packetCount = 0;

    while (running.load(std::memory_order_relaxed)) {
        socklen_t len = sizeof(cliaddr);
        int n = recvfrom(sockfd, (char *)buffer, Constants::UDP_BUFFER_SIZE,
                    MSG_WAITALL, (struct sockaddr *) &cliaddr, &len);

        uint64_t now = currentMs();

        if (n > 0) {
            // Log new client connections
            char clientIp[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &cliaddr.sin_addr, clientIp, INET_ADDRSTRLEN);
            if (strcmp(clientIp, lastClientIp) != 0) {
                std::cout << ">>> New UDP client connected: " << clientIp 
                          << ":" << ntohs(cliaddr.sin_port) << std::endl;
                strncpy(lastClientIp, clientIp, INET_ADDRSTRLEN);
            }

            packetCount++;
            lastNetworkUpdateMs = now;
            networkActive = true;

            buffer[n] = '\0';
            
            // Debug: print raw packet data every 20 packets
            if (packetCount % 20 == 1) {
                std::cout << "[UDP #" << packetCount << "] Raw (" << n << " bytes): " << buffer << std::endl;
            }

            try {
                auto j = json::parse(buffer);
                if (j.contains("joysticks")) {
                    auto& joy = j["joysticks"];
                    
                    if (joy.contains("left") && joy["left"].is_array()) {
                        float x = joy["left"][0];
                        float y = joy["left"][1];
                        axes[Constants::JOYSTICK_AXIS_X].store(static_cast<int16_t>(x * Constants::MAX_JOYSTICK_VALUE));
                        axes[Constants::JOYSTICK_AXIS_Y].store(static_cast<int16_t>(-y * Constants::MAX_JOYSTICK_VALUE));
                    }
                    if (joy.contains("right") && joy["right"].is_array()) {
                        float x = joy["right"][0];
                        float y = joy["right"][1];
                        axes[Constants::JOYSTICK_AXIS_RX].store(static_cast<int16_t>(x * Constants::MAX_JOYSTICK_VALUE));
                        axes[Constants::JOYSTICK_AXIS_RY].store(static_cast<int16_t>(-y * Constants::MAX_JOYSTICK_VALUE));
                    }
                }
            } catch (const std::exception& e) {
                std::cerr << "JSON parse error: " << e.what() << '\n';
            }
        }

        if (networkActive && (now - lastNetworkUpdateMs > 1000)) {
            std::cout << "Network timeout - resetting inputs" << std::endl;
            networkActive = false;
            for (int i = 0; i < 8; ++i) {
                axes[i].store(0);
            }
        }
    }
    close(sockfd);
}
