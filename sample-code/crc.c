#include <stdint.h>
#include "arm_acle.h"

uint32_t arm_crc32c(const uint8_t *data, int length, uint32_t prev_crc) {
    uint32_t crc = ~prev_crc;

    // Align data if it's not aligned
    while (((uintptr_t)data & 7) && length > 0) {
        crc = __crc32cb(crc, *(uint8_t *)data);
        data++;
        length--;
    }

    while (length >= 8) {
        crc = __crc32cd(crc, *(uint64_t *)data);
        data += 8;
        length -= 8;
    }

    while (length > 0) {
        crc = __crc32cb(crc, *(uint8_t *)data);
        data++;
        length--;
    }

    return ~crc;
}

uint32_t arm_crc32(const uint8_t *data, int length, uint32_t prev_crc) {
    uint32_t crc = ~prev_crc;

    // Align data if it's not aligned
    while (((uintptr_t)data & 7) && length > 0) {
        crc = __crc32b(crc, *(uint8_t *)data);
        data++;
        length--;
    }

    while (length >= 8) {
        crc = __crc32d(crc, *(uint64_t *)data);
        data += 8;
        length -= 8;
    }

    while (length > 0) {
        crc = __crc32b(crc, *(uint8_t *)data);
        data++;
        length--;
    }

    return ~crc;
}
