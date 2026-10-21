package top.magichub.panel

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.KeyEvent
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import top.magichub.panel.databinding.ActivityMainBinding

/**
 * MagicPanel 安卓客户端。
 *
 * 管理端本身是 Web 应用，这里用 WebView 承载，保证与浏览器里完全一致的
 * 行为（登录态、CSRF、批量操作、上传下载都不需要另外实现一套）。
 * 关键点：
 *  - CookieManager 持久化会话，登录一次后长期有效；
 *  - 开启 file chooser，支持"本地上传"核心文件；
 *  - 下行走系统 DownloadManager；
 *  - 站内地址留在 WebView，站外地址交给系统浏览器；
 *  - 适配 Android 15+ 的强制 edge-to-edge。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: SharedPreferences
    private var fileCallback: android.webkit.ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE)

        applyInsets()
        setupToolbar()
        setupWebView()

        binding.errorRetry.setOnClickListener {
            binding.errorBox.visibility = View.GONE
            binding.web.reload()
        }

        if (savedInstanceState != null) {
            binding.web.restoreState(savedInstanceState)
        } else {
            openUrl(baseUrl() + "/admin")
        }
    }

    // ---- 状态栏 / 手势条适配（Android 15 起强制 edge-to-edge）----

    private fun applyInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(0, bars.top, 0, 0)
            binding.content.setPadding(0, 0, 0, bars.bottom)
            insets
        }
    }

    private fun setupToolbar() {
        binding.topBar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_reload -> {
                    binding.web.reload()
                    true
                }
                R.id.action_home -> {
                    openUrl(baseUrl() + "/admin")
                    true
                }
                R.id.action_settings -> {
                    showSettingsDialog()
                    true
                }
                R.id.action_relogin -> {
                    relogin()
                    true
                }
                else -> false
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val web = binding.web
        val settings: WebSettings = web.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.setSupportZoom(true)
        settings.builtInZoomControls = true
        settings.displayZoomControls = false
        settings.mediaPlaybackRequiresUserGesture = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.safeBrowsingEnabled = true
        }

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView, request: WebResourceRequest
            ): Boolean {
                val url = request.url
                return if (isInternal(url)) {
                    false
                } else {
                    openExternally(url)
                    true
                }
            }

            override fun onPageFinished(view: WebView, url: String) {
                hideProgress()
                binding.errorBox.visibility = View.GONE
            }

            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError
            ) {
                if (request.isForMainFrame) {
                    hideProgress()
                    binding.errorBox.visibility = View.VISIBLE
                }
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                if (newProgress >= 100) {
                    hideProgress()
                } else {
                    showProgress(newProgress)
                }
            }

            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: android.webkit.ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                this@MainActivity.fileCallback?.onReceiveValue(null)
                this@MainActivity.fileCallback = filePathCallback
                return try {
                    startActivityForResult(
                        fileChooserParams.createIntent(),
                        REQUEST_FILE,
                    )
                    true
                } catch (e: ActivityNotFoundException) {
                    this@MainActivity.fileCallback = null
                    Toast.makeText(this@MainActivity, R.string.no_picker, Toast.LENGTH_SHORT).show()
                    false
                }
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            download(url, userAgent, contentDisposition, mimeType)
        }
    }

    // ---- 加载指示：任何路径都要能关掉，不能一直转圈 ----

    private var progressWatchdog: Runnable? = null

    private fun showProgress(value: Int) {
        binding.progress.visibility = View.VISIBLE
        binding.progress.progress = value
        // 看门狗：某些情况下页面不会回调 onPageFinished（例如被重定向到
        // 空白页），超时后强制收起，避免进度条一直挂在屏幕上。
        progressWatchdog?.let { binding.root.removeCallbacks(it) }
        val watchdog = Runnable { hideProgress() }
        progressWatchdog = watchdog
        binding.root.postDelayed(watchdog, PROGRESS_TIMEOUT_MS)
    }

    private fun hideProgress() {
        progressWatchdog?.let { binding.root.removeCallbacks(it) }
        progressWatchdog = null
        binding.progress.visibility = View.GONE
    }

    @Deprecated("兼容旧版 Android 的 onActivityResult")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_FILE) {
            val callback = fileCallback
            fileCallback = null
            if (callback == null) return
            val results = if (resultCode == RESULT_OK) {
                WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            } else {
                null
            }
            callback.onReceiveValue(results)
        }
    }

    private fun download(
        url: String, userAgent: String?, contentDisposition: String?, mimeType: String?
    ) {
        try {
            val request = DownloadManager.Request(Uri.parse(url))
            request.setMimeType(mimeType)
            request.addRequestHeader("User-Agent", userAgent ?: USER_AGENT)
            request.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
            request.setDescription(getString(R.string.downloading))
            request.setNotificationVisibility(
                DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            )
            request.setDestinationInExternalPublicDir(
                Environment.DIRECTORY_DOWNLOADS,
                fileNameOf(url, contentDisposition),
            )
            val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
            Toast.makeText(this, R.string.download_started, Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            openExternally(Uri.parse(url))
        }
    }

    private fun fileNameOf(url: String, contentDisposition: String?): String {
        var name = android.webkit.URLUtil.guessFileName(url, contentDisposition, null)
        if (name.isNullOrBlank()) name = "magichub-download"
        return name
    }

    // ---- 地址与跳转 ----

    private fun baseUrl(): String =
        (prefs.getString(KEY_URL, DEFAULT_URL) ?: DEFAULT_URL).trimEnd('/')

    private fun isInternal(url: Uri): Boolean {
        val base = Uri.parse(baseUrl())
        return url.host.equals(base.host, ignoreCase = true)
    }

    private fun openUrl(path: String) {
        val url = if (path.startsWith("http")) path else baseUrl() + path
        binding.errorBox.visibility = View.GONE
        binding.web.loadUrl(url)
    }

    private fun openExternally(url: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, url))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_browser, Toast.LENGTH_SHORT).show()
        }
    }

    private fun relogin() {
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
        openUrl("/admin/login")
        Toast.makeText(this, R.string.relogged, Toast.LENGTH_SHORT).show()
    }

    private fun showSettingsDialog() {
        val input = android.widget.EditText(this).apply {
            setText(baseUrl())
            hint = DEFAULT_URL
            setSingleLine()
        }
        val wrap = android.widget.FrameLayout(this).apply {
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad / 2, pad, 0)
            addView(input)
        }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.settings_title)
            .setMessage(R.string.settings_hint)
            .setView(wrap)
            .setPositiveButton(R.string.save) { _, _ ->
                val value = input.text.toString().trim().trimEnd('/')
                if (value.isEmpty() || !value.startsWith("http")) {
                    Toast.makeText(this, R.string.bad_url, Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                prefs.edit().putString(KEY_URL, value).apply()
                openUrl("/admin")
                Toast.makeText(this, R.string.saved, Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    // ---- 返回键：先在站内后退，站内没有历史才退出 ----

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && binding.web.canGoBack()) {
            binding.web.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        binding.web.saveState(outState)
    }

    companion object {
        private const val REQUEST_FILE = 1001
        private const val PROGRESS_TIMEOUT_MS = 15000L
        private const val PREFS = "magichub_panel"
        private const val KEY_URL = "base_url"
        private const val DEFAULT_URL = "https://magichub.top:8443"
        private const val USER_AGENT =
            "Mozilla/5.0 (Linux; Android 15; MagicPanel) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
    }
}
