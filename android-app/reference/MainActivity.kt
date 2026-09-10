package com.mailgrapher.webview

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding

/**
 * 노트북에서 도는 MailGrapher(Flask + ngrok)를 전체화면 WebView 하나로 띄우는 얇은 껍데기.
 *
 * - 웹 자산을 담지 않는다. START_URL 만 로드한다.
 * - START_URL 은 ngrok 고정 도메인으로 교체할 것. 도메인이 바뀌면 여기만 고치고 재빌드.
 */
private const val START_URL = "https://interatrial-tana-wishfully.ngrok-free.dev/init"

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // targetSdk 35+ 는 edge-to-edge 가 강제라 setDecorFitsSystemWindows(true) 는 no-op.
        // 명시적으로 edge-to-edge 로 두고, 아래 inset 리스너가 WebView 에 패딩을 직접 반영한다.
        WindowCompat.setDecorFitsSystemWindows(window, false)

        webView = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true            // localStorage (globalStore, gw_flask_url 등)
                useWideViewPort = true
                loadWithOverviewMode = true
                // ngrok 무료 플랜의 "Visit Site" 경고 페이지를 건너뛰기 위해
                // 비-브라우저 User-Agent 로 지정. 이 앱은 UA 스니핑을 하지 않는다.
                userAgentString = "MailGrapherAndroid"
            }
            // 링크 이동을 외부 브라우저로 넘기지 않고 앱 안에서 처리.
            // 모든 하위 요청에 ngrok 경고 스킵 헤더를 붙인다.
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest,
                ): Boolean {
                    view.loadUrl(
                        request.url.toString(),
                        mapOf("ngrok-skip-browser-warning" to "true"),
                    )
                    return true
                }
            }
        }

        setContentView(webView)

        // 시스템 바 + 노치 + 키보드(IME) 인셋을 WebView 패딩으로 반영 →
        // 웹 콘텐츠가 상태바/네비바 밑으로 안 깔리고, 키보드가 입력창을 안 가림.
        ViewCompat.setOnApplyWindowInsetsListener(webView) { v, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
                    or WindowInsetsCompat.Type.displayCutout()
                    or WindowInsetsCompat.Type.ime(),
            )
            v.updatePadding(
                left = bars.left,
                top = bars.top,
                right = bars.right,
                bottom = bars.bottom,
            )
            WindowInsetsCompat.CONSUMED
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        if (savedInstanceState == null) {
            webView.loadUrl(START_URL, mapOf("ngrok-skip-browser-warning" to "true"))
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    override fun onRestoreInstanceState(savedInstanceState: Bundle) {
        super.onRestoreInstanceState(savedInstanceState)
        webView.restoreState(savedInstanceState)
    }
}
