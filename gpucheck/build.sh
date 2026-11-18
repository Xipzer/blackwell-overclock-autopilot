#!/bin/sh
# Linux or WSL with the CUDA toolkit. On Windows, from a Visual Studio developer prompt:
#   nvcc -O2 -o gpucheck.exe gpucheck.cu
#   nvcc -O2 -o ramp.exe ramp.cu
cd "$(dirname "$0")" && nvcc -O2 -o gpucheck gpucheck.cu && nvcc -O2 -o ramp ramp.cu
