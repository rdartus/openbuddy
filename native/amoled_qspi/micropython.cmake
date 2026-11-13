add_library(usermod_amoled_qspi INTERFACE)
target_sources(usermod_amoled_qspi INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/amoled_qspi.c
)
target_link_libraries(usermod INTERFACE usermod_amoled_qspi)
