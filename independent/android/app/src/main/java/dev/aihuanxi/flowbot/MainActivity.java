package dev.aihuanxi.flowbot;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.text.InputType;
import android.view.WindowManager;
import android.widget.*;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public class MainActivity extends Activity {
    private final Handler handler = new Handler();
    private TextView status;
    private EditText url, device, token, certificate;
    private final Runnable refresh = new Runnable() {
        public void run() {
            status.setText("无障碍：" + (WeComAccessibility.instance != null ? "已开启" : "待开启")
                + "\n通知接收：" + (IncomingListener.connected ? "已开启" : "待开启")
                + "\n运行状态：" + getSharedPreferences("state", 0).getString("status", "未启动"));
            handler.postDelayed(this, 1500);
        }
    };

    static File configFile(android.content.Context context) { return new File(context.getFilesDir(), "config.json"); }

    static JSONObject config(android.content.Context context) throws Exception {
        JSONObject c = new JSONObject(new String(Files.readAllBytes(configFile(context).toPath()), StandardCharsets.UTF_8));
        return validate(c);
    }

    private static JSONObject validate(JSONObject c) throws Exception {
        String address = c.getString("url");
        java.net.URI u = new java.net.URI(address);
        boolean local = "http".equals(u.getScheme()) && ("127.0.0.1".equals(u.getHost()) || "localhost".equals(u.getHost()));
        if ((!local && !"https".equals(u.getScheme())) || u.getHost() == null || u.getUserInfo() != null)
            throw new IllegalArgumentException("远程服务必须使用 HTTPS；HTTP 仅用于本机 USB 测试");
        if (!c.getString("device_id").matches("[a-zA-Z0-9_-]{1,64}") || c.getString("token").length() < 32)
            throw new IllegalArgumentException("请填写设备 ID 和有效设备密钥");
        return c;
    }

    public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL); layout.setPadding(32, 24, 32, 24);
        ScrollView scroll = new ScrollView(this); scroll.addView(layout); setContentView(scroll);
        TextView heading = new TextView(this); heading.setText("FlowBot 独立版\n专用手机保持解锁、充电，企业微信允许通知显示正文。"); layout.addView(heading);
        button(layout, "开启无障碍服务", () -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        button(layout, "开启消息通知读取", () -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        status = new TextView(this); layout.addView(status);
        url = field(layout, "服务器地址", "http://127.0.0.1:8787");
        device = field(layout, "设备 ID", "oppo-test");
        token = field(layout, "设备密钥", ""); token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        certificate = field(layout, "IP 测试证书 PEM（域名可信证书可留空）", ""); certificate.setMinLines(2); certificate.setMaxLines(3);
        try {
            JSONObject c = config(this);
            url.setText(c.getString("url")); device.setText(c.getString("device_id")); token.setText(c.getString("token")); certificate.setText(c.optString("ca_pem"));
        } catch (Exception ignored) { }
        button(layout, "保存并启动", () -> {
            try {
                if (BridgeService.active) throw new IllegalStateException("请先停止再修改配置");
                JSONObject c = new JSONObject().put("url", url.getText().toString().trim()).put("device_id", device.getText().toString().trim())
                    .put("token", token.getText().toString().trim()).put("ca_pem", certificate.getText().toString().trim());
                validate(c);
                File tmp = new File(getFilesDir(), "config.tmp"); Files.write(tmp.toPath(), c.toString().getBytes(StandardCharsets.UTF_8));
                File current = configFile(this);
                Files.move(tmp.toPath(), current.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                startForegroundService(new Intent(this, BridgeService.class));
            } catch (Exception e) { Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show(); }
        });
        button(layout, "停止执行", () -> stopService(new Intent(this, BridgeService.class)));
        button(layout, "打开企业微信", () -> {
            Intent launch = getPackageManager().getLaunchIntentForPackage("com.tencent.wework");
            if (launch != null) startActivity(launch);
        });
        debugStart(getIntent());
    }
    public void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); debugStart(intent); }
    private void debugStart(Intent intent) {
        if (BuildConfig.DEBUG && intent.getBooleanExtra("start_bridge", false)) {
            try { config(this); startForegroundService(new Intent(this, BridgeService.class)); }
            catch (Exception e) { Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show(); }
        }
    }
    private EditText field(LinearLayout layout, String label, String value) {
        TextView text = new TextView(this); text.setText(label); layout.addView(text);
        EditText edit = new EditText(this); edit.setText(value); layout.addView(edit); return edit;
    }
    private void button(LinearLayout layout, String label, Runnable action) {
        Button b = new Button(this); b.setText(label); b.setOnClickListener(v -> action.run()); layout.addView(b);
    }
    public void onResume() { super.onResume(); handler.post(refresh); }
    public void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
}
