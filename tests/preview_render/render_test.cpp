#define NOMINMAX
#include <windows.h>
#include <glad/gl.h>
#include "libvgcode/include/Viewer.hpp"
#include "libvgcode/include/GCodeInputData.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

using namespace libvgcode;

int main()
{
    HWND window = CreateWindowA("STATIC", "OrcaBrick renderer regression", WS_POPUP, 0, 0, 512, 512,
        nullptr, nullptr, GetModuleHandle(nullptr), nullptr);
    HDC dc = GetDC(window);
    PIXELFORMATDESCRIPTOR pf{};
    pf.nSize = sizeof(pf); pf.nVersion = 1;
    pf.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pf.iPixelType = PFD_TYPE_RGBA; pf.cColorBits = 32; pf.cDepthBits = 24;
    SetPixelFormat(dc, ChoosePixelFormat(dc, &pf), &pf);
    HGLRC context = wglCreateContext(dc);
    if (!context || !wglMakeCurrent(dc, context) || !gladLoaderLoadGL())
        throw std::runtime_error("Cannot create OpenGL test context");
    std::cout << "OpenGL " << glGetString(GL_VERSION) << '\n';
    glViewport(0, 0, 512, 512);
    glEnable(GL_DEPTH_TEST);
    Viewer viewer;
    viewer.init(reinterpret_cast<const char*>(glGetString(GL_VERSION)));
    GCodeInputData data;
    data.layer_zs = {0.2f, 0.3f}; data.layer_upper_half = {0, 1};
    data.tools_colors = {{255, 200, 30}}; data.color_print_colors = data.tools_colors;
    for (unsigned lane = 0; lane < 5; ++lane) {
        const float y = -0.8f + 0.4f * lane;
        const float z = lane % 2 ? 0.3f : 0.2f;
        PathVertex v;
        v.position = {-0.8f, y, z}; v.type = EMoveType::Travel;
        v.role = EGCodeExtrusionRole::Perimeter;
        v.height = 0.1f; v.width = 0.08f; v.feedrate = 20.f;
        data.vertices.push_back(v);
        v.type = EMoveType::Extrude;
        data.vertices.push_back(v); // phantom start
        v.position[0] = 0.8f;
        if (lane == 4) v.layer_id = 1; // final extrusion is the upper storage marker
        data.vertices.push_back(v);
    }
    viewer.load(std::move(data));
    viewer.set_view_type(EViewType::FeatureType);
    Mat4x4 view{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,-3,1};
    Mat4x4 proj{1,0,0,0, 0,1,0,0, 0,0,-0.2f,0, 0,0,-1.02f,1};
    bool passed = true;
    for (unsigned mode = 0; mode < 3; ++mode) {
        viewer.set_layers_view_range(mode == 1 ? 1 : 0, mode == 0 ? 0 : 1);
        glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        viewer.render(view, proj); glFinish();
        std::vector<unsigned char> pixels(512 * 512 * 3);
        glReadPixels(0, 0, 512, 512, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
        std::ofstream image("half-" + std::to_string(mode) + ".ppm", std::ios::binary);
        image << "P6\n512 512\n255\n";
        for (int y = 511; y >= 0; --y)
            image.write(reinterpret_cast<const char*>(pixels.data() + y * 512 * 3), 512 * 3);
        for (unsigned lane = 0; lane < 5; ++lane) {
            int count = 0;
            const int cy = int((0.1f + 0.2f * lane) * 512);
            for (int y = cy - 15; y <= cy + 15; ++y)
                for (int x = 60; x < 452; ++x)
                    if (pixels[(y * 512 + x) * 3] > 30) ++count;
            const bool expected = mode == 2 || lane % 2 == mode;
            std::cout << "view " << mode << " lane " << lane << ": " << count << " pixels\n";
            passed &= (count > 100) == expected;
        }
    }
    viewer.shutdown(); wglMakeCurrent(nullptr, nullptr); wglDeleteContext(context);
    ReleaseDC(window, dc); DestroyWindow(window);
    std::cout << (passed ? "RENDER PASS\n" : "RENDER FAIL\n");
    return passed ? 0 : 1;
}
