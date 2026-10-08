// pricer.cpp
//
// Prices a synthetic book of European call options with the Black-Scholes
// closed form and reports two numbers: the total book value and a 64-bit
// fingerprint of every individual price. The fingerprint changes if any
// price changes by a single bit, so it answers "did anything move?" without
// having to inspect a million values.
//
// The same source is meant to be built and run on more than one host (for
// example an x86 instance and a Graviton instance) and the outputs compared.
// With --dump, every individual price is written to a file so compare.py can
// report exactly how many prices differ and by how much.
//
// Black-Scholes exercises log, exp, sqrt and erfc. These transcendental
// functions come from the platform's math library, which is where results
// most often differ across architectures in the last bit.
//
// Usage:
//   pricer [--n N] [--threads T] [--dump FILE]
//     --n        number of options (default 1,000,000)
//     --threads  worker threads, 0 = all hardware threads (default 1)
//     --dump     write every price as raw little-endian doubles to FILE
//
// Results (book value, fingerprint) do not depend on --threads. Inputs are
// generated sequentially and prices are reduced in index order.

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cinttypes>
#include <cmath>
#include <vector>
#include <thread>

#if defined(__aarch64__) && defined(__linux__)
  #include <sys/auxv.h>
  #include <asm/hwcap.h>
#endif

#ifndef BUILD_FLAGS
#define BUILD_FLAGS "(not recorded)"
#endif

// Deterministic input generation.
//
// The generator is xorshift64* over a fixed seed. Its integer output is
// identical on every platform, unlike std::uniform_real_distribution, whose
// result varies between libstdc++ and libc++. Raw 64-bit output is mapped to
// [0,1) by hand so every host draws the same sequence.
//
// range() is an a*b+c, which the compiler would otherwise contract into one
// FMA on the default build (arm64 contracts by default) but not on the
// -ffp-contract=off build, so the two builds would draw different inputs.
// The volatile commits the product's rounding before the add, defeating that
// FMA on GCC and Clang regardless of -ffp-contract, so every build and host
// prices the same book and the comparison isolates the pricing arithmetic.
struct Rng {
    uint64_t s;
    explicit Rng(uint64_t seed) : s(seed) {}
    uint64_t next() {
        s ^= s >> 12; s ^= s << 25; s ^= s >> 27;
        return s * 0x2545F4914F6CDD1DULL;
    }
    double unit() { return (next() >> 11) * (1.0 / 9007199254740992.0); }
    double range(double lo, double hi) {
        volatile double scaled = (hi - lo) * unit();
        return lo + scaled;
    }
};

// FNV-1a over the raw bytes of each price.
struct Fingerprint {
    uint64_t h = 1469598103934665603ULL;
    void add(double d) {
        uint64_t bits; std::memcpy(&bits, &d, sizeof bits);
        for (int i = 0; i < 8; ++i) {
            h ^= (bits >> (8 * i)) & 0xff;
            h *= 1099511628211ULL;
        }
    }
};

static inline double norm_cdf(double x) { return 0.5 * std::erfc(-x * M_SQRT1_2); }

static inline double black_scholes_call(double S, double K, double r, double sig, double T) {
    double srt = sig * std::sqrt(T);
    double d1  = (std::log(S / K) + (r + 0.5 * sig * sig) * T) / srt;
    double d2  = d1 - srt;
    return S * norm_cdf(d1) - K * std::exp(-r * T) * norm_cdf(d2);
}

static void print_host_info() {
#if defined(__aarch64__)
    std::printf("arch             : aarch64\n");
  #if defined(__linux__)
    bool has_sve = getauxval(AT_HWCAP) & HWCAP_SVE;
    long vl_bytes = -1;
    if (FILE* f = std::fopen("/proc/sys/abi/sve_default_vector_length", "r")) {
        if (std::fscanf(f, "%ld", &vl_bytes) != 1) vl_bytes = -1;
        std::fclose(f);
    }
    if (has_sve && vl_bytes > 0)
        std::printf("sve              : %ld-bit (%ld doubles per vector)\n", vl_bytes * 8, vl_bytes / 8);
    else
        std::printf("sve              : not available (NEON only)\n");
  #else
    std::printf("sve              : n/a (non-Linux)\n");
  #endif
#elif defined(__x86_64__)
    std::printf("arch             : x86_64\n");
    std::printf("sve              : n/a\n");
#else
    std::printf("arch             : unknown\n");
#endif
    std::printf("build flags      : %s\n", BUILD_FLAGS);
}

int main(int argc, char** argv) {
    size_t   n       = 1'000'000;
    unsigned threads = 1;
    const char* dump = nullptr;

    for (int i = 1; i < argc; ++i) {
        auto need = [&](const char* opt) -> const char* {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s requires a value\n", opt); std::exit(2); }
            return argv[++i];
        };
        if      (!std::strcmp(argv[i], "--n"))       n       = std::strtoull(need("--n"), nullptr, 10);
        else if (!std::strcmp(argv[i], "--threads")) threads = (unsigned)std::atoi(need("--threads"));
        else if (!std::strcmp(argv[i], "--dump"))    dump    = need("--dump");
        else { std::fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    if (threads == 0) threads = std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;

    const double r = 0.03;

    // Inputs: generated sequentially so every host gets the same book.
    std::vector<double> S(n), K(n), sig(n), T(n), qty(n), px(n);
    {
        Rng rng(123456789ULL);
        for (size_t i = 0; i < n; ++i) {
            S[i]   = rng.range(50.0, 150.0);
            K[i]   = rng.range(50.0, 150.0);
            sig[i] = rng.range(0.10, 0.60);
            T[i]   = rng.range(0.05, 2.00);
            qty[i] = std::floor(rng.range(100.0, 10000.0));
        }
    }

    // Pricing: each option is independent, so the work can be split across
    // threads without changing any individual result.
    {
        std::vector<std::thread> pool;
        for (unsigned t = 0; t < threads; ++t) {
            pool.emplace_back([&, t]() {
                size_t lo = n * t / threads, hi = n * (t + 1) / threads;
                for (size_t i = lo; i < hi; ++i)
                    px[i] = black_scholes_call(S[i], K[i], r, sig[i], T[i]) * qty[i];
            });
        }
        for (auto& th : pool) th.join();
    }

    // Reduction: sequential and in index order, so the book value and
    // fingerprint are independent of thread count.
    double total = 0.0;
    Fingerprint fp;
    for (size_t i = 0; i < n; ++i) { total += px[i]; fp.add(px[i]); }

    if (dump) {
        FILE* f = std::fopen(dump, "wb");
        if (!f) { std::perror(dump); return 1; }
        std::fwrite(px.data(), sizeof(double), n, f);
        std::fclose(f);
    }

    print_host_info();
    std::printf("options          : %zu\n", n);
    std::printf("threads          : %u\n", threads);
    std::printf("book value       : %.6f\n", total);
    std::printf("fingerprint      : %016" PRIx64 "\n", fp.h);
    if (dump) std::printf("dumped           : %s\n", dump);
    return 0;
}
