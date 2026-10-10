package dev.aihuanxi.flowbot;

import java.util.regex.Pattern;

final class NotificationText {
    static String body(CharSequence displayed, CharSequence ticker) {
        String text = displayed == null ? "" : displayed.toString();
        String raw = ticker == null ? "" : ticker.toString();
        // WeCom 5.0.11 aggregates unread counts in EXTRA_TEXT; ticker contains the actual latest text.
        return !raw.isEmpty() && text.matches("\\[[0-9]+条\\]" + Pattern.quote(raw)) ? raw : text;
    }
}
