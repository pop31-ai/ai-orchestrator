package com.aiorchestrator.app

import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import com.google.android.material.snackbar.Snackbar
import java.io.BufferedReader
import java.io.InputStreamReader

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var assetLoader: WebViewAssetLoader
    private var serverPort: Int = 8080
    private var serverProcess: Process? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()

        val apiLevel = Build.VERSION.SDK_INT
        val androidVersion = Build.VERSION.RELEASE

        // Инициализация WebView
        webView = WebView(this)
        webView.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        setContentView(webView)

        setupWebView()

        // Обработка back
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    finish()
                }
            }
        })

        // Обработка deep link
        intent?.data?.let { uri ->
            handleDeepLink(uri)
        }

        // Запуск Python backend
        startPythonBackend(apiLevel)
    }

    private fun setupWebView() {
        assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/res/", WebViewAssetLoader.ResourcesPathHandler(this))
            .build()

        webView.apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                allowFileAccess = true
                allowContentAccess = true
                mediaPlaybackRequiresUserGesture = false
                mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

                // Оптимизация для Android 8 (аппаратное ускорение)
                if (Build.VERSION.SDK_INT >= 26) {
                    setEnableFastScrolling()
                }
            }

            webViewClient = object : WebViewClientCompat() {
                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest
                ): Boolean {
                    val uri = request.url
                    return when {
                        uri.scheme == "ai-orchestrator" -> {
                            handleDeepLink(uri)
                            true
                        }
                        uri.host == "localhost" || uri.host == "127.0.0.1" -> false
                        else -> {
                            val intent = Intent(Intent.ACTION_VIEW, uri)
                            startActivity(intent)
                            true
                        }
                    }
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    injectAI()
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onReceivedTitle(view: WebView?, title: String?) {
                    supportActionBar?.title = title
                }
            }

            // Загружаем локальную HTML-страницу
            loadUrl("https://appassets.androidplatform.net/assets/index.html")
        }
    }

    private fun injectAI() {
        // Внедряем JavaScript API для связи с Python
        val js = """
            (function() {
                window.AIOrchestrator = {
                    version: '1.0.0',
                    apiLevel: ,
                    androidVersion: '',
                    serverPort: ,
                    serverUrl: 'http://localhost:',

                    send: async function(message) {
                        try {
                            const resp = await fetch(this.serverUrl + '/api/chat', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({message: message})
                            });
                            return await resp.json();
                        } catch(e) {
                            return {error: e.message};
                        }
                    },

                    stream: function(message, callback) {
                        const evtSource = new EventSource(
                            this.serverUrl + '/api/stream?message=' + encodeURIComponent(message)
                        );
                        evtSource.onmessage = function(e) {
                            callback(JSON.parse(e.data));
                        };
                        evtSource.onerror = function() {
                            evtSource.close();
                            callback({done: true});
                        };
                        return evtSource;
                    },

                    getProviders: async function() {
                        const resp = await fetch(this.serverUrl + '/api/providers');
                        return await resp.json();
                    },

                    getHistory: async function() {
                        const resp = await fetch(this.serverUrl + '/api/history');
                        return await resp.json();
                    }
                };
                console.log('AI Orchestrator API ready');
            })();
        """.trimIndent()
        webView.evaluateJavascript(js, null)
    }

    private fun startPythonBackend(apiLevel: Int) {
        try {
            // Пытаемся запустить Python через Chaquopy
            val python = com.chaquo.python.Python.getInstance()
            val backend = python.getModule("ai_orchestrator_android")
            backend.callAttr("start_server", apiLevel)
        } catch (e: Exception) {
            // Если Chaquopy не сработал — запускаем WebView в офлайн-режиме
            runOnUiThread {
                Snackbar.make(webView, "Python backend: ", Snackbar.LENGTH_LONG).show()
                loadOfflineMode()
            }
        }
    }

    private fun loadOfflineMode() {
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    private fun handleDeepLink(uri: Uri) {
        when (uri.host) {
            "chat" -> {
                val msg = uri.getQueryParameter("message") ?: ""
                webView.evaluateJavascript("document.querySelector('#input').value = '';", null)
            }
            "settings" -> {
                webView.evaluateJavascript("switchTab('settings');", null)
            }
        }
    }

    override fun onDestroy() {
        serverProcess?.destroy()
        super.onDestroy()
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
    }

    override fun onPause() {
        webView.onPause()
        super.onPause()
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
