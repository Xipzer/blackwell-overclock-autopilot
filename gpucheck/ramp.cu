// Load-ramp check, an attempt to reproduce the Time Spy heavy-scene hang with compute (on the RTX 5090 it did not:
// 23 cycles clean at a setting that hung Time Spy). The GPU is kept busy at low power (one small block per SM,
// ~100 % usage, ~100 to 165 W) so a cool core climbs to the top of the curve, then the load ramps up in steps to a
// full load and drops back. Every launch's per-block checksum is compared with that config's first launch.
// Usage: ramp <seconds> <light_ms> <step_ms> <heavy_ms> [iters]
// Output: a line every 5 s, and "RESULT errors=N launches=M cycles=C" (errors=-1 on a driver error).
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <vector>

__global__ void work(const float *seed, unsigned int *sum, int iters) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    float a = seed[tid & 1023], b = a * 0.999f + 0.001f, c = 1.0001f, d = 0.9999f;
    for (int i = 0; i < iters; i++) {
        a = fmaf(a, c, b); b = fmaf(b, d, a * 1e-7f);
        c = fmaf(c, 0.99999f, 1e-5f); d = fmaf(d, 1.00001f, -1e-5f);
        a = a > 1e3f ? a * 1e-3f : a; b = b > 1e3f ? b * 1e-3f : b;
    }
    unsigned int bits = __float_as_uint(a) ^ (__float_as_uint(b) * 2654435761u);
    atomicAdd(&sum[blockIdx.x], bits);
}

typedef std::chrono::steady_clock clk;
static double ms(clk::time_point a) { return std::chrono::duration<double, std::milli>(clk::now() - a).count(); }

int main(int argc, char **argv) {
    int seconds = argc > 1 ? atoi(argv[1]) : 180, lightMs = argc > 2 ? atoi(argv[2]) : 4000;
    int stepMs = argc > 3 ? atoi(argv[3]) : 300, heavyMs = argc > 4 ? atoi(argv[4]) : 2500;
    cudaDeviceProp p; cudaGetDeviceProperties(&p, 0);
    int sms = p.multiProcessorCount, iters = argc > 5 ? atoi(argv[5]) : 100000;
    // light, then the ramp (warps per SM 2, 4, 8, 16, 32), then full (8 blocks x 256 threads per SM)
    int cfgB[] = {sms, sms, sms, sms, sms * 2, sms * 4, sms * 8};
    int cfgT[] = {64, 128, 256, 512, 512, 512, 256};
    const int N = 7, maxBlocks = sms * 8;
    float *seed; unsigned int *sum;
    cudaMalloc(&seed, 1024 * sizeof(float)); cudaMalloc(&sum, maxBlocks * sizeof(unsigned int));
    std::vector<float> hs(1024); for (int i = 0; i < 1024; i++) hs[i] = 0.5f + i * 1e-4f;
    cudaMemcpy(seed, hs.data(), 1024 * sizeof(float), cudaMemcpyHostToDevice);
    std::vector<std::vector<unsigned int>> ref(N);
    std::vector<unsigned int> got(maxBlocks);
    for (int c = 0; c < N; c++) {
        cudaMemset(sum, 0, maxBlocks * 4); work<<<cfgB[c], cfgT[c]>>>(seed, sum, iters);
        if (cudaDeviceSynchronize() != cudaSuccess) { printf("RESULT errors=-1 launches=0 cycles=0 (first launch failed)\n"); return 2; }
        ref[c].resize(cfgB[c]); cudaMemcpy(ref[c].data(), sum, cfgB[c] * 4, cudaMemcpyDeviceToHost);
    }
    printf("sms=%d\n", sms); fflush(stdout);
    long launches = 0, errors = 0, cycles = 0;
    auto t0 = clk::now(), lastPrint = t0;
    auto run = [&](int c, double dur) -> bool {
        auto b0 = clk::now();
        while (ms(b0) < dur) {
            cudaMemset(sum, 0, cfgB[c] * 4); work<<<cfgB[c], cfgT[c]>>>(seed, sum, iters);
            cudaError_t e = cudaDeviceSynchronize();
            if (e != cudaSuccess) {
                printf("RESULT errors=-1 launches=%ld cycles=%ld (driver error in config %d: %s)\n", launches, cycles, c, cudaGetErrorString(e));
                fflush(stdout); return false;
            }
            cudaMemcpy(got.data(), sum, cfgB[c] * 4, cudaMemcpyDeviceToHost);
            for (int i = 0; i < cfgB[c]; i++) if (got[i] != ref[c][i]) errors++;
            launches++;
        }
        return true;
    };
    while (ms(t0) < seconds * 1000.0) {
        if (!run(0, lightMs)) return 3;
        for (int c = 1; c < N - 1; c++) if (!run(c, stepMs)) return 3;
        if (!run(N - 1, heavyMs)) return 3;
        cycles++;
        if (ms(lastPrint) >= 5000) { printf("t=%.0f cycles=%ld launches=%ld errors=%ld\n", ms(t0) / 1000, cycles, launches, errors); fflush(stdout); lastPrint = clk::now(); }
    }
    printf("RESULT errors=%ld launches=%ld cycles=%ld\n", errors, launches, cycles);
    return errors ? 1 : 0;
}
