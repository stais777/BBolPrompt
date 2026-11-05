#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

#define CAP 32768
static void fail(const wchar_t *message) {
    MessageBoxW(NULL, message, L"뽈프롬 실행 오류", MB_OK | MB_ICONERROR);
}
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t folder[CAP], runtime[CAP], workdir[CAP], cmd[CAP];
    DWORD n = GetModuleFileNameW(NULL, folder, CAP);
    if (!n || n >= CAP) { fail(L"실행 파일 경로를 읽지 못했습니다."); return 2; }
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (!slash) { fail(L"프로그램 폴더를 찾지 못했습니다."); return 2; }
    *slash = 0;
    if (2*wcslen(folder) + wcslen(arguments) + 200 >= CAP) {
        fail(L"경로 또는 실행 인수가 너무 깁니다. 압축을 짧은 폴더(C:\\Bbolprom 등)에 풀어주세요.");
        return 2;
    }
    swprintf(runtime, CAP, L"%ls\\runtime\\pythonw.exe", folder);
    swprintf(workdir, CAP, L"%ls\\app", folder);
    if (GetFileAttributesW(runtime) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(workdir) == INVALID_FILE_ATTRIBUTES) {
        fail(L"실행에 필요한 runtime 또는 app 폴더가 없습니다. ZIP 전체를 압축 해제한 뒤 실행해주세요.");
        return 2;
    }
    swprintf(cmd, CAP, L"\"%ls\" -B -E -s -m bbolprom_engine.app --portable-root \"%ls\\.\" %ls", runtime, folder, arguments);
    STARTUPINFOW startup = {0}; PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(runtime, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, workdir, &startup, &process)) {
        wchar_t error[512];
        swprintf(error, 512, L"프로그램을 시작하지 못했습니다 (Windows 오류 %lu). ZIP 전체를 압축 해제했는지 확인해주세요.", GetLastError());
        fail(error); return 3;
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 0; GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    if (code) {
        fail(L"자료 준비 또는 프로그램 실행 중 오류가 발생했습니다. 실행 폴더와 data 폴더의 startup-error.log를 확인하세요. 쓰기 가능한 폴더에 압축을 풀었는지, 이전 앱을 종료했는지 확인해주세요.");
    }
    return (int)code;
}
