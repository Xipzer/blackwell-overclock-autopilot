// GPU core stability check for clock-cap finding. Deterministic FP32 FMA chains on every SM; each launch's
// checksum per block is compared with the first launch's (same inputs, same order, so any difference is an error).
// Load is pulsed (busy ms, idle ms) so the clock sees the load transitions that trigger boost spikes.
// Usage: gpucheck <seconds> <blocks_per_sm> <busy_ms> <idle_ms>
// Output: one line per second: "t=.. launches=.. errors=..", and a final "RESULT errors=N launches=M".
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <thread>
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

int main(int argc, char **argv) {
    int seconds = argc > 1 ? atoi(argv[1]) : 120, perSm = argc > 2 ? atoi(argv[2]) : 4;
    int busyMs = argc > 3 ? atoi(argv[3]) : 2000, idleMs = argc > 4 ? atoi(argv[4]) : 400;
    cudaDeviceProp p; cudaGetDeviceProperties(&p, 0);
    int blocks = p.multiProcessorCount * perSm, threads = 256, iters = 20000;
    float *seed; unsigned int *sum;
    cudaMalloc(&seed, 1024 * sizeof(float)); cudaMalloc(&sum, blocks * sizeof(unsigned int));
    std::vector<float> hs(1024); for (int i = 0; i < 1024; i++) hs[i] = 0.5f + i * 1e-4f;
    cudaMemcpy(seed, hs.data(), 1024 * sizeof(float), cudaMemcpyHostToDevice);
    std::vector<unsigned int> ref(blocks), got(blocks);
    cudaMemset(sum, 0, blocks * 4); work<<<blocks, threads>>>(seed, sum, iters);
    if (cudaDeviceSynchronize() != cudaSuccess) { printf("RESULT errors=-1 launches=0 (first launch failed: %s)\n", cudaGetErrorString(cudaGetLastError())); return 2; }
    cudaMemcpy(ref.data(), sum, blocks * 4, cudaMemcpyDeviceToHost);
    printf("sms=%d blocks=%d\n", p.multiProcessorCount, blocks); fflush(stdout);
    long launches = 0, errors = 0;
    auto t0 = std::chrono::steady_clock::now(), lastPrint = t0;
    while (std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() < seconds) {
        auto b0 = std::chrono::steady_clock::now();
        while (std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - b0).count() < busyMs) {
            cudaMemset(sum, 0, blocks * 4); work<<<blocks, threads>>>(seed, sum, iters);
            cudaError_t e = cudaDeviceSynchronize();
            if (e != cudaSuccess) { printf("RESULT errors=-1 launches=%ld (driver error: %s)\n", launches, cudaGetErrorString(e)); fflush(stdout); return 3; }
            cudaMemcpy(got.data(), sum, blocks * 4, cudaMemcpyDeviceToHost);
            for (int i = 0; i < blocks; i++) if (got[i] != ref[i]) errors++;
            launches++;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(idleMs));
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration<double>(now - lastPrint).count() >= 5) {
            printf("t=%.0f launches=%ld errors=%ld\n", std::chrono::duration<double>(now - t0).count(), launches, errors); fflush(stdout); lastPrint = now;
        }
    }
    printf("RESULT errors=%ld launches=%ld\n", errors, launches);
    return errors ? 1 : 0;
}
