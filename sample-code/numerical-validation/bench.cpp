// bench.cpp
//
// Optional throughput benchmark. Separate from pricer.cpp on purpose: pricer
// answers "do the results match", this answers "how fast", and the two
// should not be confused.
//
// Method:
//   - Inputs are generated before the timed region, so the measurement is
//     the pricing arithmetic and math-library calls, not random number
//     generation or allocation.
//   - T worker threads (default: all hardware threads) each price a slice.
//   - The run is repeated R times and the best wall time is reported, which
//     is the least noisy estimate of what the hardware can do.
//   - CPU utilisation is CPU-seconds divided by wall-seconds over the timed
//     region. On a saturated 4-vCPU host it approaches 4.0 (100%).
//   - A checksum is printed so the optimiser cannot delete the work.
//
// Usage: bench [--n N] [--threads T] [--repeats R]
//   defaults: 16,000,000 options, all hardware threads, 8 repeats
//
// This is one closed-form kernel with no memory pressure, no branching and
// no library calls beyond libm. Treat the result as a data point about
// this kernel on this instance size, not as a statement about your grid.

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <ctime>
#include <vector>
#include <thread>
#include <chrono>

// Same kernel as pricer.cpp.
static inline double norm_cdf(double x) { return 0.5 * std::erfc(-x * M_SQRT1_2); }
static inline double black_scholes_call(double S, double K, double r, double sig, double T) {
    double srt = sig * std::sqrt(T);
    double d1  = (std::log(S / K) + (r + 0.5 * sig * sig) * T) / srt;
    double d2  = d1 - srt;
    return S * norm_cdf(d1) - K * std::exp(-r * T) * norm_cdf(d2);
}

int main(int argc, char** argv) {
    size_t   n       = 16'000'000;
    unsigned threads = 0;
    int      repeats = 8;

    for (int i = 1; i < argc; ++i) {
        auto need = [&](const char* opt) -> const char* {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s requires a value\n", opt); std::exit(2); }
            return argv[++i];
        };
        if      (!std::strcmp(argv[i], "--n"))       n       = std::strtoull(need("--n"), nullptr, 10);
        else if (!std::strcmp(argv[i], "--threads")) threads = (unsigned)std::atoi(need("--threads"));
        else if (!std::strcmp(argv[i], "--repeats")) repeats = std::atoi(need("--repeats"));
        else { std::fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    if (threads == 0) threads = std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;
    if (repeats < 1) repeats = 1;

    const double r = 0.03;

    // Deterministic inputs, generated outside the timed region.
    std::vector<double> S(n), K(n), sig(n), T(n);
    uint64_t s = 88172645463325252ULL;
    auto u = [&]() {
        s ^= s >> 12; s ^= s << 25; s ^= s >> 27;
        return (double)((s * 0x2545F4914F6CDD1DULL) >> 11) / 9007199254740992.0;
    };
    for (size_t i = 0; i < n; ++i) {
        S[i] = 50 + 100 * u(); K[i] = 50 + 100 * u();
        sig[i] = 0.1 + 0.5 * u(); T[i] = 0.05 + 1.95 * u();
    }

    std::vector<double> partial(threads, 0.0);
    auto worker = [&](unsigned t) {
        size_t lo = n * t / threads, hi = n * (t + 1) / threads;
        double acc = 0.0;
        for (size_t i = lo; i < hi; ++i) acc += black_scholes_call(S[i], K[i], r, sig[i], T[i]);
        partial[t] = acc;
    };

    double best = 1e300, util_at_best = 0.0, checksum = 0.0;
    for (int rep = 0; rep < repeats; ++rep) {
        auto w0 = std::chrono::steady_clock::now();
        clock_t c0 = std::clock();
        std::vector<std::thread> pool;
        for (unsigned t = 0; t < threads; ++t) pool.emplace_back(worker, t);
        for (auto& th : pool) th.join();
        clock_t c1 = std::clock();
        auto w1 = std::chrono::steady_clock::now();

        double wall = std::chrono::duration<double>(w1 - w0).count();
        double cpu  = double(c1 - c0) / CLOCKS_PER_SEC;
        for (double p : partial) checksum += p;
        if (wall < best) { best = wall; util_at_best = cpu / wall; }
    }

    std::printf("options          : %zu\n", n);
    std::printf("threads          : %u\n", threads);
    std::printf("repeats          : %d\n", repeats);
    std::printf("best wall (s)    : %.6f\n", best);
    std::printf("cpu utilisation  : %.0f%%\n", 100.0 * util_at_best / threads);
    std::printf("options per sec  : %.0f\n", n / best);
    std::printf("checksum         : %.6f\n", checksum);
    return 0;
}
