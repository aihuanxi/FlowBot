package dev.aihuanxi.flowbot;

import android.app.Notification;
import android.os.Bundle;
import android.os.Parcelable;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
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
            if ((!getSharedPreferences("state", 0).getBoolean("listen_all", false) && !allowed.contains(contact)) || extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false)
                || extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) != null) return;
            try (DeviceStore db = new DeviceStore(this)) {
                Parcelable[] messages = extras.getParcelableArray(Notification.EXTRA_MESSAGES);
                if (messages != null) {
                    for (Notification.MessagingStyle.Message m : Notification.MessagingStyle.Message.getMessagesFromBundleArray(messages)) {
                        if (m.getSender() == null) continue; // Messages without a sender are the user's own replies.
                        db.incoming(contact, String.valueOf(m.getText()), sbn.getKey() + ":" + m.getTimestamp(), "wecom_notification");
                    }
                } else {
                    String text = NotificationText.body(extras.getCharSequence(Notification.EXTRA_TEXT), sbn.getNotification().tickerText);
                    if (BuildConfig.DEBUG) android.util.Log.i("FlowBotIncoming", "private notification; aggregate=" + !text.contentEquals(extras.getCharSequence(Notification.EXTRA_TEXT, "")));
                    db.incoming(contact, text, sbn.getKey() + ":" + sbn.getNotification().when, "wecom_notification");
                }
            }
        } catch (Exception e) {
            getSharedPreferences("state", 0).edit().putString("status", "通知解析异常：" + e.getClass().getSimpleName()).apply();
        }
    }
}
