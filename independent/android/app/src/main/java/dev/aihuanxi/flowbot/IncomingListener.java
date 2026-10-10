package dev.aihuanxi.flowbot;

import android.app.Notification;
import android.os.Bundle;
import android.os.Parcelable;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Set;

public class IncomingListener extends NotificationListenerService {
    static volatile boolean connected;
    public void onListenerConnected() {
        connected = true;
        StatusBarNotification[] notifications = getActiveNotifications();
        if (BuildConfig.DEBUG) android.util.Log.i("FlowBotIncoming", "connected; active=" + (notifications == null ? 0 : notifications.length));
        if (notifications != null) for (StatusBarNotification notification : notifications) onNotificationPosted(notification);
    }
    public void onListenerDisconnected() { connected = false; }
    public void onDestroy() { connected = false; super.onDestroy(); }
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (!"com.tencent.wework".equals(sbn.getPackageName()) || (sbn.getNotification().flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;
        try {
            Bundle extras = sbn.getNotification().extras;
            String contact = String.valueOf(extras.getCharSequence(Notification.EXTRA_TITLE, ""));
            Set<String> allowed = getSharedPreferences("state", 0).getStringSet("contacts", Collections.emptySet());
            if (!allowed.contains(contact) || extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false)
                || extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) != null) return;
            try (DeviceStore db = new DeviceStore(this)) {
                Parcelable[] messages = extras.getParcelableArray(Notification.EXTRA_MESSAGES);
                if (messages != null) {
                    for (Notification.MessagingStyle.Message m : Notification.MessagingStyle.Message.getMessagesFromBundleArray(messages)) {
                        if (m.getSender() == null) continue; // Messages without a sender are the user's own replies.
                        record(db, contact, String.valueOf(m.getText()), sbn.getKey() + ":" + m.getTimestamp());
                    }
                } else {
                    // shortcut: only private notifications with visible text, add UI receive when foreground capture is required.
                    String text = NotificationText.body(extras.getCharSequence(Notification.EXTRA_TEXT), sbn.getNotification().tickerText);
                    if (BuildConfig.DEBUG) android.util.Log.i("FlowBotIncoming", "private notification; aggregate=" + !text.contentEquals(extras.getCharSequence(Notification.EXTRA_TEXT, "")));
                    record(db, contact, text, sbn.getKey() + ":" + sbn.getNotification().when);
                }
            }
        } catch (Exception e) {
            getSharedPreferences("state", 0).edit().putString("status", "通知解析异常：" + e.getClass().getSimpleName()).apply();
        }
    }
    private void record(DeviceStore db, String contact, String text, String identity) throws Exception {
        if (text.trim().isEmpty() || text.length() > 4000 || "[新消息]".equals(text) || "你收到了一条新消息".equals(text)) return;
        byte[] digest = MessageDigest.getInstance("SHA-256").digest((identity + "\0" + contact + "\0" + text).getBytes(StandardCharsets.UTF_8));
        StringBuilder key = new StringBuilder(); for (byte b : digest) key.append(String.format("%02x", b));
        JSONObject event = new JSONObject().put("event_id", key.toString()).put("contact", contact).put("text", text).put("source", "wecom_notification");
        db.queue("incoming:" + key, "/device/incoming", event);
    }
}
