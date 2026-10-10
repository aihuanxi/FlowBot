package dev.aihuanxi.flowbot;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.graphics.Rect;
import android.os.*;
import android.view.accessibility.*;
import org.json.JSONObject;
import java.util.*;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;

public class WeComAccessibility extends AccessibilityService {
    static volatile WeComAccessibility instance;
    private final Handler main = new Handler(Looper.getMainLooper());
    private static final String PACKAGE = "com.tencent.wework";
    private final ConversationDelta incoming = new ConversationDelta();
    private String activeContact = "";
    private boolean receivingScheduled;
    public void onServiceConnected() { instance = this; }
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) incoming.reset();
        if (!receivingScheduled) {
            receivingScheduled = true;
            main.postDelayed(() -> { receivingScheduled = false; receiveVisible(); }, 200);
        }
    }
    private void receiveVisible() {
        List<AccessibilityNodeInfo> list = nodes();
        try {
            String contact = null; AccessibilityNodeInfo messages = null; int edits = 0;
            for (AccessibilityNodeInfo n : list) {
                if (n.isEditable()) edits++;
                if ("com.tencent.wework:id/nwv".equals(n.getViewIdResourceName()) && n.getText()!=null) contact=n.getText().toString();
                if ("com.tencent.wework:id/iy0".equals(n.getViewIdResourceName())) messages=n;
            }
            // shortcut: foreground fallback covers explicitly subscribed private contacts on WeCom 5.0.11; recalibrate other versions.
            if (contact==null || messages==null || edits!=1 || !getSharedPreferences("state",0).getStringSet("contacts", Collections.emptySet()).contains(contact)) {
                incoming.reset(); activeContact=""; return;
            }
            if (!contact.equals(activeContact)) { incoming.reset(); activeContact=contact; }
            List<String> keys=new ArrayList<>(), texts=new ArrayList<>(); List<Boolean> received=new ArrayList<>();
            for (int i=0; i<messages.getChildCount(); i++) {
                AccessibilityNodeInfo row=messages.getChild(i);
                if (row==null) continue;
                try {
                    AccessibilityNodeInfo.CollectionItemInfo position=row.getCollectionItemInfo();
                    String body=findText(row,"com.tencent.wework:id/ilm");
                    if (position==null || body==null) continue;
                    boolean fromContact=containsId(row,"com.tencent.wework:id/i5g");
                    boolean fromSelf=containsId(row,"com.tencent.wework:id/i4o");
                    if (fromContact==fromSelf) continue;
                    keys.add(position.getRowIndex()+":"+(fromContact ? "I:" : "O:")+body); texts.add(body); received.add(fromContact);
                } finally { row.recycle(); }
            }
            int start=incoming.update(keys);
            try (DeviceStore db=new DeviceStore(this)) {
                for (int i=start; i<keys.size(); i++) if (received.get(i))
                    db.incoming(contact,texts.get(i),"ui:"+UUID.randomUUID(),"wecom_accessibility");
            }
        } catch (Exception e) {
            getSharedPreferences("state",0).edit().putString("status","前台接收异常："+e.getClass().getSimpleName()).apply();
        } finally { for (AccessibilityNodeInfo n:list) n.recycle(); }
    }
    private String findText(AccessibilityNodeInfo n,String id) {
        if (id.equals(n.getViewIdResourceName()) && n.getText()!=null) return n.getText().toString();
        for (int i=0; i<n.getChildCount(); i++) { AccessibilityNodeInfo child=n.getChild(i); if (child!=null) { try { String found=findText(child,id); if (found!=null) return found; } finally { child.recycle(); } } }
        return null;
    }
    private boolean containsId(AccessibilityNodeInfo n,String id) {
        if (id.equals(n.getViewIdResourceName())) return true;
        for (int i=0; i<n.getChildCount(); i++) { AccessibilityNodeInfo child=n.getChild(i); if (child!=null) { try { if (containsId(child,id)) return true; } finally { child.recycle(); } } }
        return false;
    }
    public void onInterrupt() { }
    public void onDestroy() { instance = null; super.onDestroy(); }

    private <T> T ui(java.util.concurrent.Callable<T> action) throws Exception {
        FutureTask<T> task = new FutureTask<>(action); main.post(task); return task.get(4, TimeUnit.SECONDS);
    }
    private List<AccessibilityNodeInfo> nodes() {
        List<AccessibilityNodeInfo> result = new ArrayList<>();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return result;
        if (!PACKAGE.contentEquals(root.getPackageName() == null ? "" : root.getPackageName())) { root.recycle(); return result; }
        // Same depth-first node selection and platform actions as automator/UiObject.kt.
        Deque<AccessibilityNodeInfo> stack = new ArrayDeque<>(); stack.push(root);
        while (!stack.isEmpty()) {
            AccessibilityNodeInfo n = stack.pop(); result.add(n);
            for (int i = n.getChildCount()-1; i >= 0; i--) { AccessibilityNodeInfo child = n.getChild(i); if (child != null) stack.push(child); }
        }
        return result;
    }
    private boolean act(Predicate<AccessibilityNodeInfo> match, int action, Bundle args) throws Exception {
        return ui(() -> {
            List<AccessibilityNodeInfo> nodes = nodes(); List<AccessibilityNodeInfo> matches = new ArrayList<>();
            try {
                for (AccessibilityNodeInfo n : nodes) if (n.isVisibleToUser() && match.test(n)) matches.add(n);
                if (matches.size() != 1) return false;
                AccessibilityNodeInfo n = matches.get(0);
                if (action == AccessibilityNodeInfo.ACTION_CLICK) {
                    while (n != null && !n.isClickable()) {
                        AccessibilityNodeInfo parent = n.getParent(); if (n != matches.get(0)) n.recycle(); n = parent;
                    }
                    if (n == null) return false;
                    boolean ok = n.performAction(action);
                    if (n != matches.get(0)) n.recycle();
                    return ok;
                }
                return n.performAction(action, args);
            } finally { for (AccessibilityNodeInfo n : nodes) n.recycle(); }
        });
    }
    private int count(Predicate<AccessibilityNodeInfo> match) throws Exception {
        return ui(() -> {
            List<AccessibilityNodeInfo> nodes = nodes(); int count = 0;
            try { for (AccessibilityNodeInfo n : nodes) if (n.isVisibleToUser() && match.test(n)) count++; return count;
            } finally { for (AccessibilityNodeInfo n : nodes) n.recycle(); }
        });
    }
    private boolean text(AccessibilityNodeInfo n, String value) { return value.contentEquals(n.getText() == null ? "" : n.getText()); }
    private boolean emptyInput(AccessibilityNodeInfo n) { return n.isEditable() && (n.isShowingHintText() || n.getText() == null || n.getText().length() == 0); }
    private boolean topText(AccessibilityNodeInfo n, String value) { Rect r = new Rect(); n.getBoundsInScreen(r); return text(n, value) && r.top < getResources().getDisplayMetrics().heightPixels / 5; }
    private boolean clickText(String value) throws Exception { return act(n -> text(n, value), AccessibilityNodeInfo.ACTION_CLICK, null); }
    private boolean edit(String value) throws Exception {
        Bundle args = new Bundle(); args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value);
        return act(AccessibilityNodeInfo::isEditable, AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }
    private boolean chat(String contact) throws Exception { return count(n -> topText(n, contact)) == 1 && count(AccessibilityNodeInfo::isEditable) == 1; }
    private void pause() throws InterruptedException { Thread.sleep(600); }
    private void require(boolean condition, String message) { if (!condition) throw new IllegalStateException(message); }

    JSONObject send(JSONObject task) throws Exception {
        String id = task.getString("id"), contact = task.getString("contact"), message = task.getString("text");
        boolean attempted = false;
        JSONObject result = new JSONObject().put("task_id", id);
        try {
            require(!contact.trim().isEmpty() && !message.trim().isEmpty() && message.length() <= 2000, "非法文本任务");
            require(!getSystemService(android.app.KeyguardManager.class).isKeyguardLocked(), "手机锁定");
            ui(() -> {
                incoming.reset(); activeContact="";
                Intent launch = getPackageManager().getLaunchIntentForPackage(PACKAGE);
                if (launch == null) throw new IllegalStateException("未安装企业微信");
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); startActivity(launch); return true;
            });
            pause();
            for (int i = 0; i < 8 && !chat(contact); i++) {
                if (count(n -> topText(n, "消息")) == 1) {
                    if (count(n -> text(n, contact)) == 1 && clickText(contact)) { pause(); break; }
                    // shortcut: WeCom 5.0.11 search icon ID, recalibrate after WeCom UI updates.
                    require(act(n -> "com.tencent.wework:id/nxm".equals(n.getViewIdResourceName()), AccessibilityNodeInfo.ACTION_CLICK, null), "找不到搜索入口");
                    pause(); require(edit(contact), "找不到唯一搜索输入框"); pause(); pause();
                    require(count(n -> text(n, contact) && !n.isEditable()) == 1, "联系人不唯一或未找到");
                    require(act(n -> text(n, contact) && !n.isEditable(), AccessibilityNodeInfo.ACTION_CLICK, null), "无法打开联系人"); pause(); break;
                }
                ui(() -> performGlobalAction(GLOBAL_ACTION_BACK)); pause();
            }
            if (!chat(contact) && count(n -> text(n, "发消息")) == 1) { require(clickText("发消息"), "无法打开会话"); pause(); }
            require(chat(contact), "会话标题或输入框不匹配，未发送");
            require(count(n -> n.isEditable() && !emptyInput(n)) == 0, "会话有未发送草稿，请人工处理");
            require(edit(message), "ACTION_SET_TEXT 未成功"); pause();
            require(chat(contact) && count(n -> n.isEditable() && text(n, message)) == 1, "发送前会话/文本校验失败");
            int before = count(n -> !n.isEditable() && text(n, message));
            attempted = true;
            require(clickText("发送"), "发送按钮操作未确认");
            boolean confirmed = false;
            for (int i = 0; i < 10; i++) {
                pause();
                if (chat(contact) && count(this::emptyInput) == 1
                    && count(n -> !n.isEditable() && text(n, message)) > before) { confirmed = true; break; }
            }
            require(confirmed, "发送后的新消息气泡未确认，请人工核对");
            result.put("status", "succeeded").put("detail", "AccessibilityService ACTION_SET_TEXT/ACTION_CLICK；会话标题、清空输入框与新增文本气泡已确认；不代表对方已读");
            ui(() -> { incoming.reset(); activeContact=""; return performGlobalAction(GLOBAL_ACTION_HOME); });
        } catch (InterruptedException e) {
            result.put("status", attempted ? "unknown" : "failed").put("detail", "执行被停止，请人工核对");
        } catch (Exception e) {
            result.put("status", attempted ? "unknown" : "failed").put("detail", e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
        }
        android.util.Log.i("FlowBotTask", id + " " + result.getString("status") + " " + result.optString("detail"));
        return result;
    }
}
