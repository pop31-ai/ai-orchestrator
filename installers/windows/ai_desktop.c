#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0600
#include <windows.h>
#include <winhttp.h>
#include <shellapi.h>
#include <commctrl.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")

#define CHAR_COUNT 5
#define WM_TRAYICON (WM_APP + 1)
#define ID_TRAY_SHOW 1001
#define ID_TRAY_EXIT 1002
#define ID_CHAT_SEND 2000
#define ID_TIMER_HEALTH 3000

typedef struct {
    WCHAR name[32];
    WCHAR provider[64];
    WCHAR avatar[8];
    WCHAR model[16];
    WCHAR desc[64];
    COLORREF color;
    BOOL loaded;
    int x, y, w, h;
} Character;

Character chars[CHAR_COUNT] = {
    { L"Assistant", L"local_tinyllama", L"\U0001F916", L"Q4_K_M", L"Balanced, docs & tools", RGB(63,185,80), FALSE },
    { L"Speedy",    L"local_tinyllama_q2", L"\u26A1", L"Q2_K", L"Fast responses", RGB(210,153,34), FALSE },
    { L"Thinker",   L"local_tinyllama_q3", L"\U0001F4DA", L"Q3_K_M", L"Creative, ideas", RGB(88,166,255), FALSE },
    { L"Analyst",   L"local_tinyllama_q5", L"\U0001F50C", L"Q5_K_M", L"Deep analysis", RGB(188,140,255), FALSE },
    { L"Scholar",   L"local_tinyllama_q8", L"\u2B50", L"Q8_0", L"Best quality", RGB(255,123,156), FALSE },
};

HINSTANCE hInst;
HWND hMainWnd = NULL, hChatWnd = NULL, hChatEdit = NULL, hChatList = NULL, hChatSend = NULL;
NOTIFYICONDATAW nid = {0};
int currentCharIdx = 0;

LRESULT CALLBACK WndProc(HWND, UINT, WPARAM, LPARAM);
LRESULT CALLBACK ChatProc(HWND, UINT, WPARAM, LPARAM);
void DrawTiles(HDC hdc, RECT* rc);
void ShowTrayIcon(HWND hWnd);
void RemoveTrayIcon(HWND hWnd);
void OpenChat(int idx);
char* HttpPost(const WCHAR* path, const char* body);
char* JsonStr(const char* json, const char* key);
void CheckHealth();

char* HttpPost(const WCHAR* path, const char* body) {
    static char buffer[131072];
    buffer[0] = 0;
    HINTERNET hSession = WinHttpOpen(L"AI-Desktop/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, NULL, NULL, 0);
    if (!hSession) return buffer;
    HINTERNET hConnect = WinHttpConnect(hSession, L"127.0.0.1", 8080, 0);
    if (!hConnect) { WinHttpCloseHandle(hSession); return buffer; }
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", path, NULL, NULL, NULL, 0);
    if (!hRequest) { WinHttpCloseHandle(hConnect); WinHttpCloseHandle(hSession); return buffer; }
    LPCWSTR headers = L"Content-Type: application/json\r\n";
    int bodyLen = (int)strlen(body);
    if (WinHttpSendRequest(hRequest, headers, -1, (void*)body, bodyLen, bodyLen, 0) &&
        WinHttpReceiveResponse(hRequest, NULL)) {
        DWORD bytesRead = 0;
        WinHttpReadData(hRequest, buffer, sizeof(buffer)-1, &bytesRead);
        buffer[bytesRead] = 0;
    }
    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return buffer;
}

char* JsonStr(const char* json, const char* key) {
    static char val[65536];
    val[0] = 0;
    char search[128];
    sprintf(search, "\"%s\":\"", key);
    const char* start = strstr(json, search);
    if (!start) return val;
    start += strlen(search);
    const char* end = strchr(start, '"');
    if (!end || end - start > 65535) return val;
    strncpy(val, start, end - start);
    val[end - start] = 0;
    return val;
}

void DrawTiles(HDC hdc, RECT* rc) {
    int tileW = (rc->right - 80) / CHAR_COUNT;
    int tileH = 220;
    int startX = 20, startY = 60;

    if (tileW > 180) tileW = 180;
    startX = (rc->right - (tileW * CHAR_COUNT + 10 * (CHAR_COUNT - 1))) / 2;

    HFONT hFontBig = CreateFontW(28, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT hFontName = CreateFontW(15, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT hFontSmall = CreateFontW(11, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT hFontTiny = CreateFontW(10, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");

    for (int i = 0; i < CHAR_COUNT; i++) {
        int x = startX + i * (tileW + 10);
        int y = startY;
        chars[i].x = x; chars[i].y = y; chars[i].w = tileW; chars[i].h = tileH;

        HPEN pen = CreatePen(PS_SOLID, 1, RGB(48, 54, 61));
        HBRUSH bg = CreateSolidBrush(RGB(22, 27, 34));
        SelectObject(hdc, pen);
        SelectObject(hdc, bg);
        RoundRect(hdc, x, y, x + tileW, y + tileH, 8, 8);
        DeleteObject(pen);
        DeleteObject(bg);

        // Avatar circle
        HBRUSH av = CreateSolidBrush(chars[i].color);
        SelectObject(hdc, av);
        Ellipse(hdc, x + tileW/2 - 30, y + 20, x + tileW/2 + 30, y + 80);
        DeleteObject(av);

        // Avatar emoji
        SetBkMode(hdc, TRANSPARENT);
        SetTextColor(hdc, RGB(255, 255, 255));
        SelectObject(hdc, hFontBig);
        RECT tr = {x, y + 22, x + tileW, y + 78};
        DrawTextW(hdc, chars[i].avatar, -1, &tr, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        // Status dot
        HBRUSH dot = CreateSolidBrush(chars[i].loaded ? RGB(63,185,80) : RGB(218,51,51));
        SelectObject(hdc, dot);
        SelectObject(hdc, GetStockObject(NULL_PEN));
        Ellipse(hdc, x + tileW - 24, y + 8, x + tileW - 14, y + 18);
        DeleteObject(dot);

        // Name
        SelectObject(hdc, hFontName);
        SetTextColor(hdc, RGB(201, 209, 217));
        tr = (RECT){x, y + 90, x + tileW, y + 115};
        DrawTextW(hdc, chars[i].name, -1, &tr, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        // Model badge
        SelectObject(hdc, hFontSmall);
        SetTextColor(hdc, RGB(88, 166, 255));
        tr = (RECT){x, y + 115, x + tileW, y + 135};
        DrawTextW(hdc, chars[i].model, -1, &tr, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        // Description
        SelectObject(hdc, hFontTiny);
        SetTextColor(hdc, RGB(139, 148, 158));
        tr = (RECT){x + 5, y + 135, x + tileW - 5, y + 160};
        DrawTextW(hdc, chars[i].desc, -1, &tr, DT_CENTER | DT_VCENTER | DT_WORDBREAK);
    }
    DeleteObject(hFontBig);
    DeleteObject(hFontName);
    DeleteObject(hFontSmall);
    DeleteObject(hFontTiny);
}

void CheckHealth() {
    char* resp = HttpPost(L"/api/providers", "{}");
    for (int i = 0; i < CHAR_COUNT; i++) {
        char prov[64];
        WideCharToMultiByte(CP_UTF8, 0, chars[i].provider, -1, prov, 64, NULL, NULL);
        chars[i].loaded = strstr(resp, prov) != NULL;
    }
    InvalidateRect(hMainWnd, NULL, TRUE);
}

void ShowTrayIcon(HWND hWnd) {
    nid.cbSize = sizeof(NOTIFYICONDATAW);
    nid.hWnd = hWnd;
    nid.uID = 1;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = WM_TRAYICON;
    nid.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wcscpy_s(nid.szTip, 128, L"AI Orchestrator Desktop");
    Shell_NotifyIconW(NIM_ADD, &nid);
}

void RemoveTrayIcon(HWND hWnd) {
    nid.hWnd = hWnd;
    Shell_NotifyIconW(NIM_DELETE, &nid);
}

LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_CREATE:
        hMainWnd = hWnd;
        ShowTrayIcon(hWnd);
        SetTimer(hWnd, ID_TIMER_HEALTH, 5000, NULL);
        CheckHealth();
        return 0;
    case WM_TIMER:
        if (wParam == ID_TIMER_HEALTH) CheckHealth();
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);
        RECT rc;
        GetClientRect(hWnd, &rc);
        HBRUSH bg = CreateSolidBrush(RGB(13, 17, 23));
        FillRect(hdc, &rc, bg);
        DeleteObject(bg);

        HFONT hFont = CreateFontW(22, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        SelectObject(hdc, hFont);
        SetBkColor(hdc, RGB(13, 17, 23));
        SetTextColor(hdc, RGB(201, 209, 217));
        RECT hr = {20, 8, rc.right, 40};
        DrawTextW(hdc, L"\u26A1 AI Orchestrator Desktop", -1, &hr, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        DeleteObject(hFont);

        DrawTiles(hdc, &rc);
        EndPaint(hWnd, &ps);
        return 0;
    }
    case WM_LBUTTONDBLCLK: {
        POINT pt;
        GetCursorPos(&pt);
        ScreenToClient(hWnd, &pt);
        for (int i = 0; i < CHAR_COUNT; i++) {
            if (pt.x >= chars[i].x && pt.x <= chars[i].x + chars[i].w &&
                pt.y >= chars[i].y && pt.y <= chars[i].y + chars[i].h) {
                OpenChat(i);
                break;
            }
        }
        return 0;
    }
    case WM_TRAYICON:
        if (lParam == WM_LBUTTONDBLCLK) {
            ShowWindow(hWnd, SW_SHOW);
            SetForegroundWindow(hWnd);
        } else if (lParam == WM_RBUTTONUP) {
            POINT pt;
            GetCursorPos(&pt);
            HMENU hMenu = CreatePopupMenu();
            AppendMenuW(hMenu, MF_STRING, ID_TRAY_SHOW, L"Show");
            AppendMenuW(hMenu, MF_SEPARATOR, 0, NULL);
            AppendMenuW(hMenu, MF_STRING, ID_TRAY_EXIT, L"Exit");
            SetForegroundWindow(hWnd);
            TrackPopupMenu(hMenu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hWnd, NULL);
            DestroyMenu(hMenu);
        }
        return 0;
    case WM_COMMAND:
        if (LOWORD(wParam) == ID_TRAY_SHOW) {
            ShowWindow(hWnd, SW_SHOW);
            SetForegroundWindow(hWnd);
        } else if (LOWORD(wParam) == ID_TRAY_EXIT) {
            DestroyWindow(hWnd);
        }
        return 0;
    case WM_CLOSE:
        ShowWindow(hWnd, SW_HIDE);
        return 0;
    case WM_DESTROY:
        RemoveTrayIcon(hWnd);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

LRESULT CALLBACK ChatProc(HWND hDlg, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_INITDIALOG: {
        hChatWnd = hDlg;
        SetWindowTextW(hDlg, chars[currentCharIdx].name);

        HWND hIcon = CreateWindowW(L"STATIC", chars[currentCharIdx].avatar,
            WS_CHILD | WS_VISIBLE | SS_CENTER, 15, 15, 40, 40, hDlg, NULL, hInst, NULL);
        HFONT hFont = CreateFontW(32, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        SendMessageW(hIcon, WM_SETFONT, (WPARAM)hFont, TRUE);

        HWND hName = CreateWindowW(L"STATIC", chars[currentCharIdx].name,
            WS_CHILD | WS_VISIBLE | SS_LEFT, 65, 20, 200, 20, hDlg, NULL, hInst, NULL);
        HFONT hFontN = CreateFontW(18, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        SendMessageW(hName, WM_SETFONT, (WPARAM)hFontN, TRUE);

        HWND hModel = CreateWindowW(L"STATIC", chars[currentCharIdx].model,
            WS_CHILD | WS_VISIBLE | SS_LEFT, 65, 40, 200, 15, hDlg, NULL, hInst, NULL);
        HFONT hFontS = CreateFontW(12, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        SendMessageW(hModel, WM_SETFONT, (WPARAM)hFontS, TRUE);

        hChatList = CreateWindowW(L"LISTBOX", NULL,
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOINTEGRALHEIGHT | LBS_NOTIFY,
            15, 70, 420, 250, hDlg, NULL, hInst, NULL);
        SendMessageW(hChatList, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);

        hChatEdit = CreateWindowW(L"EDIT", NULL,
            WS_CHILD | WS_VISIBLE | ES_MULTILINE | WS_VSCROLL | ES_AUTOVSCROLL,
            15, 330, 340, 40, hDlg, NULL, hInst, NULL);
        SendMessageW(hChatEdit, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);

        hChatSend = CreateWindowW(L"BUTTON", L"Send",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            365, 330, 70, 40, hDlg, (HMENU)ID_CHAT_SEND, hInst, NULL);

        SetFocus(hChatEdit);
        return TRUE;
    }
    case WM_COMMAND:
        if (LOWORD(wParam) == ID_CHAT_SEND || (LOWORD(wParam) == ID_CHAT_SEND && HIWORD(wParam) == BN_CLICKED)) {
            WCHAR wtext[4096];
            GetWindowTextW(hChatEdit, wtext, 4096);
            if (wcslen(wtext) == 0) return TRUE;

            char text[4096];
            WideCharToMultiByte(CP_UTF8, 0, wtext, -1, text, sizeof(text), NULL, NULL);
            SetWindowTextW(hChatEdit, L"");

            char json[8192];
            char prov[64];
            WideCharToMultiByte(CP_UTF8, 0, chars[currentCharIdx].provider, -1, prov, 64, NULL, NULL);
            sprintf(json, "{\"message\":\"%s\",\"provider\":\"%s\"}", text, prov);

            SetWindowTextW(hChatList, L"");

            char* resp = HttpPost(L"/api/chat", json);
            char* response = JsonStr(resp, "response");
            if (!response[0]) response = JsonStr(resp, "error");
            if (!response[0]) strcpy(response, "No response");

            WCHAR wresp[131072];
            char display[131072];
            sprintf(display, "You: %s\r\n%s: %s", text, chars[currentCharIdx].name, response);
            MultiByteToWideChar(CP_UTF8, 0, display, -1, wresp, 131072);
            SetWindowTextW(hChatList, wresp);
            return TRUE;
        }
        break;
    case WM_CLOSE:
        hChatWnd = NULL;
        DestroyWindow(hDlg);
        return TRUE;
    }
    return FALSE;
}

void OpenChat(int idx) {
    currentCharIdx = idx;
    if (hChatWnd && IsWindow(hChatWnd)) {
        SetForegroundWindow(hChatWnd);
        return;
    }
    HWND hDlg = CreateDialogW(hInst, NULL, hMainWnd, ChatProc);
    if (!hDlg) {
        hDlg = CreateWindowExW(0, L"#32770", chars[idx].name,
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
            CW_USEDEFAULT, CW_USEDEFAULT, 470, 420,
            hMainWnd, NULL, hInst, NULL);
        if (hDlg) {
            SetWindowLongPtrW(hDlg, GWLP_WNDPROC, (LONG_PTR)ChatProc);
            SendMessageW(hDlg, WM_INITDIALOG, 0, 0);
        }
    }
    ShowWindow(hDlg, SW_SHOW);
    SetForegroundWindow(hDlg);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    hInst = hInstance;
    INITCOMMONCONTROLSEX icex = {sizeof(icex), ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&icex);

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = CreateSolidBrush(RGB(13, 17, 23));
    wc.lpszClassName = L"AIOrchDesktop";
    if (!RegisterClassW(&wc)) return 1;

    HWND hWnd = CreateWindowExW(0, L"AIOrchDesktop", L"AI Orchestrator Desktop",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_SIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 950, 360,
        NULL, NULL, hInstance, NULL);
    if (!hWnd) return 1;

    ShowWindow(hWnd, nCmdShow);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        if (!hChatWnd || !IsDialogMessageW(hChatWnd, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    return (int)msg.wParam;
}
