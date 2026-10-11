// SPDX-License-Identifier: GPL-3.0-only
// DLSS5Tool control host for the pinned Magpie.Core (Magpie contributors).
#include "pch.h"
#include "safety_state.h"
#include "hotkeys.h"
#include "guidance.h"
#include <thread>
#include "ScalingOptions.h"
#include "ScalingRuntime.h"
#include "EffectCompiler.h"
#include "EffectDesc.h"
#include "Logger.h"
#include "StrHelper.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <deque>
#include <mutex>
#include <map>
#include "WindowHelper.h"
#include "quality.h"
#include "telemetry.h"
#include "Win32Helper.h"
#include "HdrDisplayPreflight.h"
#include <io.h>
#include <fcntl.h>

using json = nlohmann::json;
using namespace Magpie;
namespace {
constexpr UINT COMMAND_MESSAGE = WM_APP + 41;
constexpr UINT TASK_SWITCH_MESSAGE = WM_APP + 42;
std::mutex outputMutex, commandMutex;
std::deque<std::string> commands;
DWORD mainThread;
Realtime::Hotkeys hotkeyBindings;
std::array<bool, 4> registeredHotkeys{};
std::atomic<bool> inputClosed = false;
std::shared_ptr<EffectParameterSessionState> session;
json activeConfig;
HWND activeSource = nullptr;
DWORD activeSourcePid = 0;
struct PendingSave {
    EffectParametersRequest request;
    std::chrono::steady_clock::time_point submitted;
};
std::mutex saveMutex;
std::map<uint64_t, PendingSave> pendingSaves;
std::atomic<uint64_t> saveId = 0;
LRESULT CALLBACK keyboardHook(int code, WPARAM message, LPARAM value) {
    if (code >= 0 && (message == WM_KEYDOWN || message == WM_SYSKEYDOWN)) {
        const auto* key = reinterpret_cast<KBDLLHOOKSTRUCT*>(value);
        if ((key->vkCode == VK_TAB && (key->flags & LLKHF_ALTDOWN)) ||
            key->vkCode == VK_LWIN || key->vkCode == VK_RWIN ||
            (key->vkCode == VK_ESCAPE && (GetAsyncKeyState(VK_CONTROL) & 0x8000)))
            PostThreadMessage(mainThread, TASK_SWITCH_MESSAGE, 0, 0);
    }
    return CallNextHookEx(nullptr, code, message, value);
}

void emit(json value) {
    std::lock_guard lock(outputMutex);
    std::cout << value.dump(-1, ' ', false, json::error_handler_t::replace) << '\n' << std::flush;
}
std::wstring wide(const std::string& text) { return StrHelper::UTF8ToUTF16(text); }
std::string errorSummary(ScalingError code) {
    switch (code) {
    case ScalingError::HdrCaptureRequired: return "源显示器未启用 HDR；请启用系统 HDR 或关闭本次 HDR 选项";
    case ScalingError::HdrDisplayRequired: return "所选输出显示器未启用 HDR";
    case ScalingError::HdrCaptureMethodRequired: return "HDR 捕获需要 Windows Graphics Capture";
    case ScalingError::NgxRestartRequired: return "NVIDIA 运行库发生异常，需要重建实时宿主";
    case ScalingError::DlssNrUnavailable: return "NR 不可用，请检查显卡、驱动和所选运行库";
    case ScalingError::FrameGenerationInitFailed: return "插帧初始化失败，请检查效果组合与运行库";
    case ScalingError::CaptureFailed: return "捕获失败，请尝试 WGC 或另一种捕获方式";
    case ScalingError::LowIntegrityLevel: return "目标窗口权限高于本程序，无法控制该窗口";
    case ScalingError::SourceWindowClosed: return "目标窗口已关闭";
    case ScalingError::OpticalFlowProviderUnavailable: return "所选光流后端不可用";
    default: return "实时增强失败（诊断编号 " + std::to_string(int(code)) + "）";
    }
}
std::string unavailableReason(std::string_view name) {
    if (name.starts_with("XeSS") || name.starts_with("RTXVideo\\") ||
        name.starts_with("FSR2\\") || name.starts_with("FSR3\\") || name.starts_with("FSR4\\"))
        return "This optional native backend was not compiled; select a built backend, not a pass-through placeholder";
    return {};
}
void toast(HWND, std::wstring_view message) noexcept {
    try { emit({{"event", "notice"}, {"message", StrHelper::UTF16ToUTF8(message)}}); } catch (...) {}
}
json effectsJson(const std::vector<EffectOption>& effects) {
    auto result = json::array();
    for (const auto& e : effects) {
        auto parameters = json::object();
        for (const auto& [name, value] : e.parameters) parameters[name] = value;
        result.push_back({{"name", e.name}, {"parameters", parameters},
            {"scaling_type", int(e.scalingType)}, {"scale", {e.scale.first, e.scale.second}}});
    }
    return result;
}
void save(const ScalingOptions& options, HWND) noexcept {
    try { emit({{"event", "settings"}, {"effects", effectsJson(options.parameterSession->Applied())}}); } catch (...) {}
}
bool saveRequest(const ScalingOptions&, EffectParametersRequest&& request) noexcept {
    try {
        const auto token = ++saveId;
        json event = {{"event", "settings_requested"}, {"token", token},
            {"run_id", request.scalingRunId}, {"effects", effectsJson(request.effects)},
            {"previous_effects", effectsJson(request.previousEffects)},
            {"sync_enabled", request.frameSync.enabled}, {"frame_rate", request.frameSync.frameRate},
            {"sync_mode", int(request.frameSync.mode)}};
        {
            std::lock_guard lock(saveMutex);
            if (pendingSaves.size() >= 32) return false;
            pendingSaves.emplace(token, PendingSave{std::move(request), std::chrono::steady_clock::now()});
        }
        emit(std::move(event));
        return true;
    } catch (...) { return false; }
}
std::vector<EffectOption> parseEffects(const json& items) {
    if (!items.is_array() || items.empty() || items.size() > 32) throw std::runtime_error("1..32 effects required");
    std::vector<EffectOption> effects;
    for (const auto& item : items) {
        EffectOption e;
        e.name = item.at("name").get<std::string>();
        if (auto reason = unavailableReason(e.name); !reason.empty()) throw std::runtime_error(reason + ": " + e.name);
        if (e.name.empty() || e.name.find("..") != std::string::npos || e.name.find(':') != std::string::npos ||
            e.name.front() == '/' || e.name.front() == '\\') throw std::runtime_error("Invalid effect name");
        EffectDesc desc; desc.name = e.name;
        if (EffectCompiler::Compile(desc, EffectCompilerFlags::NoCompile | EffectCompilerFlags::NoCache))
            throw std::runtime_error("Unknown/invalid effect: " + e.name);
        if (item.contains("parameters")) {
            for (const auto& [key, value] : item.at("parameters").items()) {
                const auto p = std::find_if(desc.params.begin(), desc.params.end(), [&](const auto& d) { return d.name == key; });
                if (p == desc.params.end() || !value.is_number()) throw std::runtime_error("Unknown effect parameter: " + key);
                float number = value.get<float>();
                std::visit([&](const auto& c) {
                    if (!std::isfinite(number) || number < c.minValue || number > c.maxValue ||
                        (p->constant.index() == 1 && std::trunc(number) != number))
                        throw std::runtime_error("Parameter outside range: " + key);
                }, p->constant);
                e.parameters.emplace(key, number);
                if (key.find("opticalFlowMethod") != std::string::npos && number == 1)
                    throw std::runtime_error("AMD optical flow SDK is not present in this build; choose NVOF or explicitly None");
            }
        }
        int scalingType = item.value("scaling_type", 0);
        if (scalingType < 0 || scalingType > 3) throw std::runtime_error("Invalid scaling type");
        e.scalingType = ScalingType(scalingType);
        if (item.contains("scale")) {
            const auto& s = item.at("scale");
            if (!s.is_array() || s.size() != 2) throw std::runtime_error("Invalid scale");
            e.scale = {s[0].get<float>(), s[1].get<float>()};
            if (!std::isfinite(e.scale.first) || !std::isfinite(e.scale.second) || e.scale.first <= 0 || e.scale.second <= 0 ||
                e.scale.first > 16384 || e.scale.second > 16384)
                throw std::runtime_error("Scale must be positive and finite");
        }
        effects.push_back(std::move(e));
    }
    if (ValidateFrameGenerationChain(effects).HasConflict()) throw std::runtime_error("Only one frame generation effect per chain");
    return effects;
}
ScalingOptions options(const json& config) {
    ScalingOptions o;
    o.effects = parseEffects(config.at("effects"));
    o.hdrComponents = BuildHdrComponentPlan(o.effects);
    if (o.hdrComponents.error != HdrComponentError::None) throw std::runtime_error("Invalid HDR effect chain");
    o.IsHdrCompatibilityEnabled(config.value("hdr", false));
    if (config.value("hdr", false)) {
        for (const auto& effect : o.effects) {
            if (effect.name != "DLSSNR\\DLSSNR_AI_Filter") continue;
            const auto value = [&](const char* key, float fallback) {
                const auto it = effect.parameters.find(key);
                return it == effect.parameters.end() ? fallback : it->second;
            };
            if (value("enableInputResolutionScaling", 0) >= .5f && value("inputResolutionPercent", 100) != 100)
                throw std::runtime_error("HDR NR residual controls require 100% input resolution; no automatic SDR fallback");
        }
    }
    o.IsWindowedMode(config.value("windowed", false));
    o.initialWindowedScaleFactor = config.value("window_scale", 1.0f);
    if (!std::isfinite(o.initialWindowedScaleFactor) || o.initialWindowedScaleFactor < 1 || o.initialWindowedScaleFactor > 4)
        throw std::runtime_error("Window scale must be 1..4");
    o.Is3DGameMode(config.value("game_mode", false));
    o.IsAllowScalingMaximized(true);
    o.IsCaptureTitleBar(config.value("capture_title_bar", false));
    o.IsTopmostDisabled(config.value("disable_topmost", false));
    int capture = config.value("capture_method", 0), monitors = config.value("monitor_mode", 0);
    int sync = config.value("sync_mode", 0);
    if (capture < 0 || capture > 3 || monitors < 0 || monitors > 3 || sync < 0 || sync > 2)
        throw std::runtime_error("Invalid capture/monitor/sync mode");
    o.captureMethod = CaptureMethod(capture);
    if (o.IsWindowedMode() && (o.Is3DGameMode() || capture == 1))
        throw std::runtime_error("Game input mode / Desktop Duplication requires fullscreen output");
    o.multiMonitorUsage = MultiMonitorUsage(monitors);
    o.preferredMonitorId = wide(config.value("monitor_id", ""));
    o.graphicsCardId.idx = config.value("gpu_index", -1);
    o.graphicsCardId.vendorId = config.value("gpu_vendor", 0u);
    o.graphicsCardId.deviceId = config.value("gpu_device", 0u);
    if (o.graphicsCardId.idx < -1 || o.graphicsCardId.idx > 63) throw std::runtime_error("Invalid GPU index");
    if (o.graphicsCardId.idx >= 0) {
        winrt::com_ptr<IDXGIFactory1> factory;
        winrt::com_ptr<IDXGIAdapter1> adapter;
        winrt::check_hresult(CreateDXGIFactory1(IID_PPV_ARGS(factory.put())));
        winrt::check_hresult(factory->EnumAdapters1(o.graphicsCardId.idx, adapter.put()));
        DXGI_ADAPTER_DESC1 desc{}; winrt::check_hresult(adapter->GetDesc1(&desc));
        o.graphicsCardId.vendorId = desc.VendorId; o.graphicsCardId.deviceId = desc.DeviceId;
    }
    o.frameSyncMode = FrameSyncMode(sync);
    o.isFrontEdgeSyncEnabled = config.value("sync_enabled", true);
    o.frontEdgeSyncFrameRate = config.value("frame_rate", 60.0f);
    if (!std::isfinite(o.frontEdgeSyncFrameRate) || o.frontEdgeSyncFrameRate < 0 || o.frontEdgeSyncFrameRate > 1000)
        throw std::runtime_error("Frame rate must be 0..1000");
    o.scalingModeName = L"DLSS5Tool";
    o.parameterSession = std::make_shared<EffectParameterSessionState>(o.effects,
        FrameSyncSettings{o.isFrontEdgeSyncEnabled, o.frontEdgeSyncFrameRate, o.frameSyncMode});
    o.screenshotsDir = std::filesystem::current_path() / "screenshots";
    o.showToast = toast;
    o.showError = [](HWND, ScalingError error) { Realtime::FailGuidance(); emit({{"event", "error"}, {"code", int(error)}, {"message", errorSummary(error)}}); };
    o.reportErrorDetails = [](HWND, ScalingError error, std::string_view context, uint32_t system) {
        Realtime::FailGuidance();
        emit({{"event", "error"}, {"code", int(error)}, {"message", errorSummary(error)}, {"details", context}, {"system_error", system}});
    };
    o.save = save;
    o.requestEffectParameters = saveRequest;
    o.isParameterFocusSwitchingEnabled = true;
    o.toolbarShortcutLabels = {registeredHotkeys[2] ? hotkeyBindings[2].label : "",
        registeredHotkeys[3] ? hotkeyBindings[3].label : "", "", "",
        registeredHotkeys[1] ? hotkeyBindings[1].label : "", "", ""};
    return o;
}
Realtime::QualitySettings quality(const json& config) {
    Realtime::QualitySettings result;
    const auto value = config.value("quality", json::object());
    auto read = [&](const char* key, float fallback, float low, float high) {
        float number = value.value(key, fallback);
        if (!std::isfinite(number) || number < low || number > high) throw std::runtime_error(std::string("Invalid quality setting: ") + key);
        return number;
    };
    result.total = read("total", 1, 0, 2);
    result.darken = read("darken", 1, 0, 2);
    result.brighten = read("brighten", 1, 0, 2);
    result.color = read("color", 1, 0, 2);
    result.luminance = read("luminance", 1, 0, 2);
    result.featherPixels = read("feather", 12, 0, 256);
    result.protectionEnabled = value.value("protection", false) ? 1.0f : 0.0f;
    if (value.contains("regions")) {
        const auto& regions = value.at("regions");
        if (!regions.is_array() || regions.size() > 4) throw std::runtime_error("At most four protection regions");
        for (size_t i = 0; i < regions.size(); ++i) {
            if (!regions[i].is_array() || regions[i].size() != 4) throw std::runtime_error("Region must have four coordinates");
            for (size_t n = 0; n < 4; ++n) {
                auto v = regions[i][n].get<float>();
                if (!std::isfinite(v) || v < 0 || v > 1) throw std::runtime_error("Region coordinates must be 0..1");
                result.regions[i][n] = v;
            }
            if (result.regions[i][2] <= result.regions[i][0] || result.regions[i][3] <= result.regions[i][1])
                throw std::runtime_error("Region must have positive extent");
        }
    }
    return result;
}
void catalog() {
    auto result = json::array();
    const auto root = StandaloneEffectsDirectory();
    for (const auto& entry : std::filesystem::recursive_directory_iterator(root)) {
        if (!entry.is_regular_file() || entry.path().extension() != L".hlsl") continue;
        auto path = std::filesystem::relative(entry.path(), root); path.replace_extension();
        EffectDesc desc; desc.name = StrHelper::UTF16ToUTF8(path.wstring());
        if (EffectCompiler::Compile(desc, EffectCompilerFlags::NoCompile | EffectCompilerFlags::NoCache)) continue;
        auto params = json::array();
        for (const auto& p : desc.params) {
            json item = {{"name", p.name}, {"label", p.label}, {"group", p.group}, {"integer", p.constant.index() == 1}};
            std::visit([&](const auto& c) { item["default"] = c.defaultValue; item["min"] = c.minValue;
                item["max"] = c.maxValue; item["step"] = c.step; }, p.constant);
            item["choices"] = json::array();
            for (const auto& choice : p.choices) item["choices"].push_back({choice.value, choice.label});
            params.push_back(std::move(item));
        }
        const auto reason = unavailableReason(desc.name);
        result.push_back({{"name", desc.name}, {"label", desc.sortName}, {"parameters", params},
            {"available", reason.empty()}, {"unavailable_reason", reason}});
    }
    emit({{"event", "catalog"}, {"effects", result}});
}
void devices() {
    auto monitors = json::array(), adapters = json::array();
    for (const auto& m : Win32Helper::GetDisplayMonitors()) {
        monitors.push_back({{"id", StrHelper::UTF16ToUTF8(m.deviceId)},
            {"name", StrHelper::UTF16ToUTF8(m.friendlyName)}, {"primary", m.isPrimary},
            {"hdr_active", IsHdrMonitorActive(m.handle)},
            {"rect", {m.rect.left, m.rect.top, m.rect.right, m.rect.bottom}}});
    }
    winrt::com_ptr<IDXGIFactory1> factory;
    winrt::check_hresult(CreateDXGIFactory1(IID_PPV_ARGS(factory.put())));
    for (UINT i = 0;; ++i) {
        winrt::com_ptr<IDXGIAdapter1> adapter;
        if (factory->EnumAdapters1(i, adapter.put()) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc{};
        if (!adapter || FAILED(adapter->GetDesc1(&desc))) continue;
        adapters.push_back({{"index", i}, {"name", StrHelper::UTF16ToUTF8(desc.Description)},
            {"vendor", desc.VendorId}, {"device", desc.DeviceId}, {"software", bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)}});
    }
    emit({{"event", "devices"}, {"monitors", monitors}, {"adapters", adapters},
        {"runtime", {{"nr", StrHelper::UTF16ToUTF8(StandaloneNrRuntimePath().wstring())},
                     {"features", StrHelper::UTF16ToUTF8(StandaloneRuntimeDirectory().wstring())}}},
        {"capabilities", {{"nvof", true}, {"amdoF", false}, {"dlss_nr", true}, {"dlss_sr", true}, {"dlss_fg", true},
                          {"xess", false}, {"fsr_native", false}, {"rtx_video", false}}}});
}
}

int main(int argc, char** argv) {
    std::set_terminate([] {
        try {
            if (auto current = std::current_exception()) std::rethrow_exception(current);
        } catch (const winrt::hresult_error& error) {
            emit({{"event", "fatal"}, {"hresult", int32_t(error.code())}, {"message", StrHelper::UTF16ToUTF8(error.message())}});
        } catch (const std::exception& error) {
            emit({{"event", "fatal"}, {"message", error.what()}});
        } catch (...) { emit({{"event", "fatal"}, {"message", "Unknown native exception"}}); }
        Logger::Get().Flush();
        std::_Exit(70);
    });
    try {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        winrt::init_apartment(winrt::apartment_type::single_threaded);
        const auto executableRoot = Win32Helper::GetExePath().parent_path().parent_path();
        const auto defaultState = executableRoot.filename() == L"runtime"
            ? executableRoot.parent_path() / L"var/realtime" : executableRoot.parent_path() / L"realtime";
        const auto stateRoot = StandalonePath(L"DLSS5_REALTIME_STATE_ROOT", defaultState.c_str());
        std::filesystem::create_directories(stateRoot);
        std::filesystem::current_path(stateRoot);
        std::filesystem::create_directories("logs");
        Logger::Get().Initialize(spdlog::level::info, L"logs/realtime.log", 1024 * 1024, 3);
        if (argc == 2 && std::string_view(argv[1]) == "--catalog") { catalog(); return 0; }
        mainThread = GetCurrentThreadId();
        MSG message; PeekMessage(&message, nullptr, 0, 0, PM_NOREMOVE);
        Realtime::CenterFeedback feedback;
        ScalingRuntime runtime;
        HHOOK keyboard = SetWindowsHookExW(WH_KEYBOARD_LL, keyboardHook, GetModuleHandle(nullptr), 0);
        struct HookGuard { HHOOK hook; ~HookGuard() { if (hook) UnhookWindowsHookEx(hook); } } hookGuard{keyboard};
        runtime.StateChanged([&runtime](ScalingState state) {
            Realtime::GuidanceState(int(state));
            emit({{"event", "state"}, {"state", int(state)}, {"run_id", runtime.RunId()}});
        });
        wchar_t supervised[2]{};
        Realtime::supervisedStop = GetEnvironmentVariableW(L"DLSS5_REALTIME_SUPERVISED_STOP", supervised, 2) == 1
            && supervised[0] == L'1';
        hotkeyBindings = Realtime::LoadHotkeys();
        json labels = json::object();
        for (size_t i = 0; i < hotkeyBindings.size(); ++i) {
            const auto& binding = hotkeyBindings[i];
            registeredHotkeys[i] = (i == 0 && Realtime::supervisedStop) ||
                RegisterHotKey(nullptr, int(i + 1), binding.modifiers | MOD_NOREPEAT, binding.key) != 0;
            labels[binding.action] = binding.label;
        }
        const bool hotkey = registeredHotkeys[0];
        Realtime::stopAvailable = hotkey;
        const bool compareKey = registeredHotkeys[1];
        const bool profilerKey = registeredHotkeys[2];
        const bool parametersKey = registeredHotkeys[3];
        Realtime::controlAvailable = parametersKey;
        Realtime::ConfigureStopHint(hotkeyBindings[0].label, hotkeyBindings[3].label);
        emit({{"event", "ready"}, {"protocol", 1}, {"stop_hotkey_registered", hotkey},
            {"appearance_hdr_residual_version", 1},
            {"hotkey_bindings", labels}, {"configurable_hotkeys", true},
            {"independent_stop", Realtime::supervisedStop.load()},
            {"hotkeys", {{"stop", hotkey}, {"compare", compareKey}, {"profiler", profilerKey}, {"parameters", parametersKey}}},
            {"task_switch_hook", keyboard != nullptr},
            {"magpie_commit", "2c017d4be8311fac8584e2ff6187b1f03383bde1"}});
        std::thread reader([] {
            std::string line;
            char c;
            while (std::cin.get(c)) {
                if (c == '\n') {
                    { std::lock_guard lock(commandMutex);
                      if (commands.size() >= 64) { inputClosed = true; break; }
                      commands.push_back(std::move(line)); line.clear(); }
                    PostThreadMessage(mainThread, COMMAND_MESSAGE, 0, 0);
                } else {
                    if (line.size() >= 1024 * 1024) { inputClosed = true; break; }
                    line += c;
                }
            }
            inputClosed = true; PostThreadMessage(mainThread, COMMAND_MESSAGE, 0, 0);
        });
        struct ReaderGuard {
            std::thread& thread;
            ~ReaderGuard() { if (thread.joinable()) { CancelSynchronousIo(thread.native_handle()); thread.join(); } }
        } readerGuard{reader};
        bool quitting = false;
        bool fallbackAttempted = false;
        std::optional<std::chrono::steady_clock::time_point> firstFrameWait;
        while (!quitting) {
            while (PeekMessage(&message, nullptr, 0, 0, PM_REMOVE)) {
                if (message.message == WM_QUIT) { quitting = true; break; }
                if (message.message == TASK_SWITCH_MESSAGE) { runtime.StopForTaskSwitch(); continue; }
                if (message.message == WM_HOTKEY) {
                    if (message.wParam == 1) { Realtime::StopGuidance(); runtime.Stop(); }
                    else runtime.InvokeOverlayAction(message.wParam == 2 ? OverlayAction::Comparison :
                        message.wParam == 3 ? OverlayAction::Profiler : OverlayAction::EffectParameters);
                } else { TranslateMessage(&message); DispatchMessage(&message); }
            }
            std::deque<std::string> pending;
            { std::lock_guard lock(commandMutex); pending.swap(commands); }
            for (const auto& line : pending) {
                json request; json id = nullptr;
                try {
                    request = json::parse(line); id = request.value("id", json(nullptr));
                    const std::string command = request.at("command");
                    if (request.contains("run_id") && request.at("run_id") != runtime.RunId())
                        throw std::runtime_error("Command belongs to an expired session");
                    if (command == "start") {
                        auto config = request.at("config");
                        HWND hwnd = reinterpret_cast<HWND>(request.at("hwnd").get<uintptr_t>());
                        DWORD pid = 0; GetWindowThreadProcessId(hwnd, &pid);
                        const auto sourceClass = Win32Helper::GetWindowClassName(hwnd);
                        if (!IsWindow(hwnd) || pid == GetCurrentProcessId() || WindowHelper::IsForbiddenSystemWindow(hwnd) ||
                            sourceClass.starts_with(L"Window_Magpie_") || sourceClass.starts_with(L"Magpie_") ||
                            (request.contains("pid") && request.at("pid").get<DWORD>() != pid))
                            throw std::runtime_error("Invalid or replaced target window");
                        auto parsed = options(config);
                        const auto qualitySettings = quality(config);
                        const int priority = config.value("gpu_priority", 0);
                        if (priority < 0 || priority > 2) throw std::runtime_error("Invalid GPU priority");
                        if (!config.value("windowed", false) && !hotkey)
                            throw std::runtime_error("Emergency stop hotkey unavailable; configure shortcuts or use windowed output");
                        if (request.value("activate", false)) {
                            if (IsIconic(hwnd)) ShowWindowAsync(hwnd, SW_RESTORE);
                            SetForegroundWindow(hwnd);
                        }
                        session = parsed.parameterSession;
                        Realtime::SetQuality(qualitySettings);
                        Realtime::gpuPriority = priority == 1 ? 3 : priority == 2 ? 1 : 2;
                        Realtime::ResetMetrics();
                        const bool usesDlss = std::any_of(parsed.effects.begin(), parsed.effects.end(), [](const auto& effect) {
                            return effect.name.starts_with("DLSS\\") || effect.name.starts_with("DLSSNR\\") || effect.name.starts_with("DLSSFG\\");
                        });
                        Realtime::BeginGuidance(hwnd, usesDlss);
                        if (!runtime.Start(hwnd, std::move(parsed), true)) throw std::runtime_error("Cannot enqueue scaling start");
                        activeConfig = config;
                        activeSource = hwnd; activeSourcePid = pid;
                        fallbackAttempted = false; firstFrameWait.reset();
                    } else if (command == "quality") {
                        if (runtime.State() != ScalingState::Scaling) throw std::runtime_error("No active session");
                        Realtime::SetQuality(quality(request));
                    } else if (command == "save_result") {
                        std::optional<EffectParametersRequest> receipt;
                        { std::lock_guard lock(saveMutex);
                          auto it = pendingSaves.find(request.at("token").get<uint64_t>());
                          if (it == pendingSaves.end()) throw std::runtime_error("Expired save receipt");
                          receipt = std::move(it->second.request); pendingSaves.erase(it); }
                        auto error = request.value("ok", false) ? EffectParametersSaveError::None :
                            request.value("conflict", false) ? EffectParametersSaveError::Conflict : EffectParametersSaveError::WriteFailed;
                        if (receipt->scalingRunId != runtime.RunId() || runtime.State() != ScalingState::Scaling)
                            error = EffectParametersSaveError::SessionExpired;
                        if (error == EffectParametersSaveError::None && receipt->kind == EffectParametersRequestKind::SaveAndRestart &&
                            !runtime.RestartWithEffectParameters(receipt->hwndSource, receipt->hwndScaling,
                                receipt->scalingRunId, std::move(receipt->effects), receipt->frameSync))
                            error = EffectParametersSaveError::SourceUnavailable;
                        if (receipt->saveState) receipt->saveState->Complete(receipt->revision, error);
                    } else if (command == "stop") { Realtime::StopGuidance(); runtime.Stop(); }
                    else if (command == "quit") { Realtime::StopGuidance(); runtime.Stop(); quitting = true; }
                    else if (command == "status") {
                        const auto metrics = Realtime::ReadMetrics();
                        auto modes = json::array();
                        for (const auto& p : Realtime::ReadParameterModes())
                            modes.push_back({{"effect", p.effect}, {"name", p.name}, {"mode", p.mode}});
                        EffectParameterSessionState::Snapshot snapshot;
                        if (session) session->ReadIfChanged(snapshot);
                        emit({{"event", "status"}, {"state", int(runtime.State())}, {"run_id", runtime.RunId()},
                            {"guidance", {{"phase", int(Realtime::ReadGuidance().timing.phase)},
                                {"intro_alpha", Realtime::IntroAlpha()}, {"toolbar_alpha", Realtime::drawnToolbarAlpha.load()},
                                {"stop_alpha", Realtime::drawnStopAlpha.load()}, {"control_mode", Realtime::controlMode.load()},
                                {"control_hwnd", reinterpret_cast<uintptr_t>(Realtime::controlWindow.load())},
                                {"feedback_hwnd", reinterpret_cast<uintptr_t>(Realtime::feedbackWindow.load())},
                                {"output_hwnd", reinterpret_cast<uintptr_t>(Realtime::ReadGuidance().output)}}},
                            {"parameter_modes", modes}, {"desired_effects", effectsJson(snapshot.desired)},
                            {"parameter_revision", snapshot.revision}, {"apply_failed", snapshot.applyFailed},
                            {"quality_revision", Realtime::qualityRevision.load()},
                            {"quality_applied_revision", Realtime::appliedQualityRevision.load()},
                            {"effects", session ? effectsJson(session->Applied()) : json::array()},
                            {"metrics", {{"captured", metrics.captured}, {"processed", metrics.processed},
                                {"submitted", metrics.submitted}, {"real", metrics.real},
                                {"generated", metrics.generatedKnown ? json(metrics.generated) : json(nullptr)},
                                {"nr_evaluations", metrics.nrEvaluations}, {"nr_failures", metrics.nrFailures},
                                {"discarded_capture", metrics.droppedCapture},
                                {"nr_gpu_ms_p95", metrics.gpuSamples ? json(metrics.nrGpuP95) : json(nullptr)},
                                {"dequeue_to_submit_ms_p50", metrics.ageSamples ? json(metrics.ageP50) : json(nullptr)},
                                {"dequeue_to_submit_ms_p95", metrics.ageSamples ? json(metrics.ageP95) : json(nullptr)},
                                {"dequeue_to_submit_ms_p99", metrics.ageSamples ? json(metrics.ageP99) : json(nullptr)},
                                {"age_samples", metrics.ageSamples}, {"source_timestamp_delta_ms", metrics.latestAge},
                                {"publication_cpu_ms_p95", metrics.processSamples ? json(metrics.processP95) : json(nullptr)}}}});
                    } else if (command == "catalog") catalog();
                    else if (command == "devices") devices();
                    else if (command == "compare") runtime.InvokeOverlayAction(OverlayAction::Comparison);
                    else if (command == "profiler") runtime.InvokeOverlayAction(OverlayAction::Profiler);
                    else if (command == "parameters") runtime.InvokeOverlayAction(OverlayAction::EffectParameters);
                    else if (command == "screenshot") runtime.InvokeOverlayAction(OverlayAction::Screenshot);
                    else if (command == "set_parameter") {
                        if (!session || runtime.State() != ScalingState::Scaling) throw std::runtime_error("No active session");
                        auto effects = session->Applied();
                        auto index = request.at("effect").get<size_t>();
                        if (index >= effects.size()) throw std::runtime_error("Invalid effect index");
                        const auto name = request.at("name").get<std::string>();
                        const auto modes = Realtime::ReadParameterModes();
                        const auto mode = std::find_if(modes.begin(), modes.end(), [&](const auto& p) { return p.effect == index && p.name == name; });
                        if (mode == modes.end() || mode->mode != 1)
                            throw std::runtime_error("Parameter is unavailable or requires a session restart; no live change applied");
                        const float value = request.at("value").get<float>();
                        if (!std::isfinite(value)) throw std::runtime_error("Non-finite parameter");
                        auto changed = effectsJson(effects);
                        changed[index]["parameters"][name] = value;
                        parseEffects(changed);
                        runtime.UpdateEffectParameterFromSettings(0, L"DLSS5Tool", uint32_t(index), effects[index], name, value);
                    } else throw std::runtime_error("Unknown command");
                    emit({{"event", "ack"}, {"id", id}, {"ok", true}, {"run_id", runtime.RunId()},
                        {"quality_revision", Realtime::qualityRevision.load()}});
                } catch (const std::exception& error) {
                    if (request.is_object() && request.value("command", "") == "start") Realtime::FailGuidance();
                    emit({{"event", "ack"}, {"id", id}, {"ok", false}, {"message", error.what()}});
                }
            }
            { std::lock_guard lock(saveMutex);
              for (auto it = pendingSaves.begin(); it != pendingSaves.end();) {
                  if (std::chrono::steady_clock::now() - it->second.submitted > std::chrono::seconds(10)) {
                      auto& r = it->second.request;
                      if (r.saveState) r.saveState->Complete(r.revision, EffectParametersSaveError::WriteFailed);
                      it = pendingSaves.erase(it);
                  } else ++it;
              } }
            if (runtime.State() == ScalingState::Scaling && Realtime::ReadMetrics().captured == 0) {
                const auto now = std::chrono::steady_clock::now();
                if (!firstFrameWait) firstFrameWait = now;
                if (!fallbackAttempted && now - *firstFrameWait > std::chrono::seconds(5) &&
                    activeConfig.value("capture_method", 0) == 1 && activeConfig.value("capture_fallback", true)) {
                    fallbackAttempted = true;
                    DWORD pid = 0; GetWindowThreadProcessId(activeSource, &pid);
                    if (IsWindow(activeSource) && pid == activeSourcePid) {
                        try {
                            auto config = activeConfig; config["capture_method"] = 0;
                            auto parsed = options(config); session = parsed.parameterSession;
                            emit({{"event", "capture_fallback"}, {"config", config},
                                {"message", "Desktop Duplication 未收到首帧，正在尝试 WGC；原 DD 路径未标为成功"}});
                            Realtime::ResetMetrics();
                            runtime.Start(activeSource, std::move(parsed), true);
                            activeConfig = config;
                        } catch (const std::exception& e) { emit({{"event", "error"}, {"message", e.what()}}); }
                    }
                }
            } else firstFrameWait.reset();
            if (inputClosed.load()) {
                std::lock_guard lock(commandMutex);
                if (commands.empty()) break;
            }
            if (!quitting) MsgWaitForMultipleObjectsEx(0, nullptr, 20, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        }
        runtime.Stop();
        for (int i = 1; i <= 4; ++i) UnregisterHotKey(nullptr, i);
        // Break the blocking input read on explicit quit; never leave a detached
        // thread referring to globals after native teardown.
        CancelSynchronousIo(reader.native_handle());
        if (reader.joinable()) reader.join();
        Logger::Get().Flush();
        return 0;
    } catch (const winrt::hresult_error& error) {
        emit({{"event", "fatal"}, {"message", StrHelper::UTF16ToUTF8(error.message())}});
    } catch (const std::exception& error) { emit({{"event", "fatal"}, {"message", error.what()}}); }
    return 1;
}
