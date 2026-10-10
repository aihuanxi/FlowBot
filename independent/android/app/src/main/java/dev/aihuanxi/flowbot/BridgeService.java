package dev.aihuanxi.flowbot;

import android.app.*;
import android.content.Intent;
import android.os.IBinder;
import android.os.PowerManager;
import org.json.*;
import javax.net.ssl.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.util.HashSet;
import java.util.Set;

public class BridgeService extends Service {
    static volatile boolean active;
    private volatile boolean running;
    private Thread worker;
    private DeviceStore store;
    private JSONObject config;
    private SSLSocketFactory tls;
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("flowbot", "FlowBot 执行状态", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "flowbot").setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("FlowBot 正在连接独立服务").setContentText("保持专用手机已解锁；点击查看状态或停止")
            .setContentIntent(open).build());
        store = new DeviceStore(this);
    }
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (running) return START_STICKY;
        try {
            config = MainActivity.config(this);
            android.service.notification.NotificationListenerService.requestRebind(new android.content.ComponentName(this, IncomingListener.class));
            String pem = config.optString("ca_pem");
            if (!pem.isEmpty()) {
                KeyStore keys = KeyStore.getInstance(KeyStore.getDefaultType()); keys.load(null);
                keys.setCertificateEntry("server", CertificateFactory.getInstance("X.509").generateCertificate(new ByteArrayInputStream(pem.getBytes(StandardCharsets.UTF_8))));
                TrustManagerFactory tm = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()); tm.init(keys);
                SSLContext context = SSLContext.getInstance("TLS"); context.init(null, tm.getTrustManagers(), null); tls = context.getSocketFactory();
            }
            store.recover();
            running = true; active = true;
            worker = new Thread(this::loop, "flowbot-bridge"); worker.start();
        } catch (Exception e) { status("配置错误：" + e.getMessage()); stopSelf(); }
        return START_STICKY;
    }
    private void status(String value) { getSharedPreferences("state", 0).edit().putString("status", value).apply(); }
    private JSONObject post(String path, JSONObject body) throws Exception {
        URL url = new URL(config.getString("url").replaceAll("/+$", "") + path);
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setInstanceFollowRedirects(false);
        if (c instanceof HttpsURLConnection && tls != null) ((HttpsURLConnection)c).setSSLSocketFactory(tls);
        c.setConnectTimeout(7000); c.setReadTimeout(7000); c.setRequestMethod("POST"); c.setDoOutput(true);
        c.setRequestProperty("Authorization", "Bearer " + config.getString("token")); c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        try {
            try (OutputStream out = c.getOutputStream()) { out.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("接口 HTTP " + code + "：" + path);
            try (InputStream input = c.getInputStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096]; int n;
                while ((n = input.read(buffer)) != -1) { bytes.write(buffer, 0, n); if (bytes.size() > 131072) throw new IOException("响应过大"); }
                return new JSONObject(bytes.toString("UTF-8"));
            }
        } finally { c.disconnect(); }
    }
    private void loop() {
        while (running) {
            try {
                String[] item;
                while (running && (item = store.next()) != null) {
                    post(item[1], new JSONObject(item[2])); store.acknowledge(item[0]);
                }
                WeComAccessibility service = WeComAccessibility.instance;
                boolean unlocked = !getSystemService(KeyguardManager.class).isKeyguardLocked() && getSystemService(PowerManager.class).isInteractive();
                JSONObject state = new JSONObject().put("ready", service != null && unlocked).put("accessibility", service != null)
                    .put("notification", IncomingListener.connected).put("unlocked", unlocked).put("version", BuildConfig.VERSION_NAME);
                JSONObject response = post("/device/poll", new JSONObject().put("state", state));
                JSONArray contacts = response.getJSONArray("allowed_contacts"); Set<String> names = new HashSet<>();
                for (int i = 0; i < contacts.length(); i++) names.add(contacts.getString(i));
                getSharedPreferences("state", 0).edit().putStringSet("contacts", names).putBoolean("listen_all", response.optBoolean("listen_all")).apply();
                JSONObject task = response.optJSONObject("task");
                if (task != null && running) {
                    String id = task.getString("id"); JSONObject result = store.previous(id);
                    if (result == null) {
                        store.begin(id);
                        status("执行中：" + id);
                        result = service == null ? new JSONObject().put("task_id", id).put("status", "failed").put("detail", "无障碍服务不可用") : service.send(task);
                    }
                    store.finish(result);
                    status(result.getString("status") + "：" + result.optString("detail"));
                } else status(unlocked && service != null ? "在线，等待任务" : "在线，请开启无障碍并解锁手机");
            } catch (InterruptedException e) { break;
            } catch (Exception e) { status("连接/执行异常：" + e.getMessage()); }
            try { Thread.sleep(2000); } catch (InterruptedException e) { break; }
        }
        active = false;
        store.close();
    }
    public void onDestroy() { running = false; active = false; if (worker != null) worker.interrupt(); status("已停止"); super.onDestroy(); }
    public IBinder onBind(Intent intent) { return null; }
}
