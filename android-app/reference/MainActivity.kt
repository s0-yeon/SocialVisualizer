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

        // 웹 콘텐츠가 상태바/네비바 밑으로 깔리지 않도록(edge-to-edge 해제).
        WindowCompat.setDecorFitsSystemWindows(window, true)

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

        // 일부 기기에서 setDecorFitsSystemWindows 만으로 하단 제스처바가 안 밀릴 때 대비 —
        // 시스템 바 인셋을 패딩으로 한 번 더 반영.
        ViewCompat.setOnApplyWindowInsetsListener(webView) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.updatePadding(top = bars.top, bottom = bars.bottom, left = bars.left, right = bars.right)
            insets
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
