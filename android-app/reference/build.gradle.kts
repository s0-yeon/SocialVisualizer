import java.text.SimpleDateFormat
import java.util.Date

plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.mailgrapher.webview"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.mailgrapher.webview"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}

// ── 빌드마다 app-debug.apk 를 덮어쓰지 않고 releases/ 에 버전별로 보관 ──
// assembleDebug 가 끝나면 산출물을 프로젝트 루트(MailGrapherWebView/)의 releases/ 로
// 버전 이름 + 타임스탬프를 붙여 복사한다. 원본 app/build/outputs/... 경로는 그대로 둬서
// 다음 빌드도 평소대로 진행된다 — 여기 쌓이는 사본만 계속 남는 기록.
// 다른 ngrok URL/앱 이름으로 만든 변형을 구분하고 싶으면 -PappLabel=이름 을 붙인다.
//   예: ./gradlew.bat :app:assembleDebug -PappLabel=demo2
val appLabel = (findProperty("appLabel") as String?)?.trim()?.takeIf { it.isNotEmpty() }

tasks.register<Copy>("archiveDebugApk") {
    // 매번 새 타임스탬프로 사본을 남기는 게 의도라, Gradle의 최신 상태(UP-TO-DATE) 판단이
    // rename()의 appLabel/타임스탬프 변화를 못 알아채고 두 번째 실행부터 건너뛰는 것을 막는다.
    doNotTrackState("빌드마다 항상 새 타임스탬프 사본을 releases/ 에 남겨야 함")
    val ts = SimpleDateFormat("yyyyMMdd-HHmmss").format(Date())
    val versionName = android.defaultConfig.versionName ?: "0"
    val labelPart = appLabel?.let { "-$it" } ?: ""
    from(layout.buildDirectory.dir("outputs/apk/debug")) {
        include("*.apk")
    }
    into(rootProject.layout.projectDirectory.dir("releases"))
    rename { "MailGrapher-v$versionName$labelPart-$ts.apk" }
}

// assembleDebug 같은 변형(variant) 태스크는 AGP가 이 스크립트 평가 이후에 등록하므로
// afterEvaluate 안에서 연결해야 "Task not found" 없이 걸린다.
afterEvaluate {
    tasks.named("assembleDebug") {
        finalizedBy("archiveDebugApk")
    }
}