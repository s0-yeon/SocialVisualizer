# MailGrapher Android WebView 앱

노트북에서 도는 MailGrapher(Flask, ngrok 터널)를 폰에서 앱 아이콘으로 여는
**얇은 WebView 껍데기**입니다. 웹 화면 자체는 담고 있지 않으며, 시작 URL만 로드합니다.

- 웹 수정 시 이 APK는 **재빌드 불필요** — 노트북에서 `cd src/web && npm run build` 만.
- ngrok **고정 도메인**을 쓰면 `START_URL` 을 한 번만 박아두면 됩니다.

---

## ⚠️ 중요: 프로젝트는 이 저장소 밖, **영어만 있는 경로**에 만들 것

이 저장소 경로에 한글(`2026-2_산학공동연구`)이 들어 있어 Gradle 빌드가 실패한다
("project path contains non-ASCII characters"). 안드로이드 프로젝트는 저장소와
파일로 엮이지 않으므로(웹앱과 URL로만 연결) 아래처럼 별도 경로에 둔다.

## 1. Android Studio 로 프로젝트 생성

1. Android Studio → **New Project** → **Empty Views Activity** (Phone and Tablet)
2. 설정:
   - **Name**: `MailGrapherWebView`
   - **Package name**: `com.mailgrapher.webview`  ← 이 값으로 해야 아래 파일 경로가 맞음
   - **Language**: Kotlin
   - **Minimum SDK**: API 24 (Android 7.0)
   - Build configuration language: Kotlin DSL
   - **Save location**: `C:\Users\<사용자명>\AndroidStudioProjects\MailGrapherWebView`
     ← **한글·공백 없는 경로**. 저장소 안(`android-app/`)에 두지 말 것.
3. 생성 후 Gradle sync 가 끝날 때까지 대기.

## 2. `reference/` 파일을 생성된 프로젝트에 반영

| `reference/` | 반영 위치 (생성된 프로젝트 루트 기준) |
|---|---|
| `MainActivity.kt` | `app/src/main/java/com/mailgrapher/webview/MainActivity.kt` (덮어쓰기) |
| `AndroidManifest.xml` | `app/src/main/AndroidManifest.xml` 에 표시된 (A)(B) 병합 (아래 3번) |

`reference/network_security_config.xml` 은 **LAN(HTTP) 폴백을 쓸 때만** 필요 —
`app/src/main/res/xml/network_security_config.xml` 로 복사하고 매니페스트
`<application>` 에 `android:networkSecurityConfig="@xml/network_security_config"` 추가.

## 3. AndroidManifest.xml 에 추가할 것

`<manifest>` 안, `<application>` 밖:
```xml
<uses-permission android:name="android.permission.INTERNET" />
```
`<application ...>` 태그 속성에:
```xml
android:usesCleartextTraffic="false"
```
(ngrok 은 HTTPS 라 `false` 로 둔다. LAN HTTP 폴백 시에만 `true` + network security config.)

## 4. 시작 URL 설정

`MainActivity.kt` 상단 `START_URL` 을 본인 ngrok 고정 도메인으로 교체:
```kotlin
private const val START_URL = "https://<본인-고정도메인>.ngrok-free.app/init"
```

## 5. 빌드 & 설치

1. `Build > Build App Bundle(s) / APK(s) > Build APK(s)`
2. 완료 알림의 **locate** → `app/build/outputs/apk/debug/app-debug.apk`
3. APK 를 폰으로 옮기고(USB/드라이브/링크), 폰 설정에서 "출처를 알 수 없는 앱 설치"
   허용 후 설치
4. 노트북에서 `python src/app.py` + `ngrok http 80 --url=<고정도메인>.ngrok-free.app`
   실행한 상태로 앱 실행

## 디버깅

폰을 USB 로 연결하고 크롬에서 `chrome://inspect` → 이 WebView 를 열면 콘솔/네트워크
확인 가능.
