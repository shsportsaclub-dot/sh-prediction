package cricket.shsports.prediction;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private static final String HOME = "https://sh-prediction.onrender.com/";
    private WebView web;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#03050c"));
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if ("sh-prediction.onrender.com".equals(u.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, u));
                return true;
            }
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) {
                    v.loadData("<body style='background:#03050c;color:#dfe5f5;font:16px sans-serif;text-align:center;padding:40px'><h3>Cannot connect</h3><p>Check your internet. The free server may take up to a minute to wake up.</p><button onclick=\"location.href='" + HOME + "'\" style='padding:12px 24px;font-size:16px'>Retry</button></body>", "text/html", "utf-8");
                }
            }
        });
        if (b != null) web.restoreState(b); else web.loadUrl(HOME);
    }

    @Override
    protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); web.saveState(o); }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
