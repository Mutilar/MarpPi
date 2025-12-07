cmake_minimum_required(VERSION 3.10)
project(stepper_pi)

set(CMAKE_CXX_STANDARD 20)

find_library(LGPIO_LIB lgpio)
find_library(RT_LIB rt)
find_library(PTHREAD_LIB pthread)

add_executable(stepper_pi 
    src/main.cpp
    src/MotorController.cpp
    src/InputManager.cpp
)

target_link_libraries(stepper_pi 
    ${LGPIO_LIB}
    ${RT_LIB}
    ${PTHREAD_LIB}
)

target_include_directories(stepper_pi PRIVATE src)
