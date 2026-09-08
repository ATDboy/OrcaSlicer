# Optional Windows GPU regression

This standalone test renders the actual libvgcode viewer in a hidden WGL window.
It requires a Windows desktop with OpenGL 3.2 or newer and does not use printer
profiles or the installed application's settings. It is separate from the default
CI tests because hosted Windows runners may only provide OpenGL 1.1.

From a developer terminal at the repository root:

```powershell
cmake -S tests/preview_render -B build-preview-render -A x64
cmake --build build-preview-render --config Release
cd build-preview-render
./Release/render_test.exe
```

Success prints `RENDER PASS`. Three PPM files show lower-half, upper-half and
combined selection. Pixel checks verify that interleaved walls belong to the
correct half, the last nominal segment is retained despite carrying the upper
storage ID, and a segment centred directly under the camera remains visible.
The test exits nonzero if an expected lane is missing or an excluded lane appears.
