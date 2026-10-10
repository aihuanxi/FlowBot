package dev.aihuanxi.flowbot;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.JSONObject;

final class DeviceStore extends SQLiteOpenHelper {
    DeviceStore(Context c) { super(c, "flowbot.db", null, 1); }
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE executions(id TEXT PRIMARY KEY,result TEXT)");
        db.execSQL("CREATE TABLE outbox(id TEXT PRIMARY KEY,path TEXT,body TEXT)");
    }
    public void onUpgrade(SQLiteDatabase db, int old, int next) { throw new IllegalStateException("unsupported schema upgrade"); }
    synchronized JSONObject previous(String id) throws Exception {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT result FROM executions WHERE id=?", new String[]{id})) {
            if (!c.moveToFirst()) return null;
            if (c.isNull(0)) return new JSONObject().put("task_id", id).put("status", "unknown").put("detail", "执行进程中断，未重发；请人工核对会话");
            return new JSONObject(c.getString(0));
        }
    }
    synchronized void begin(String id) {
        ContentValues v = new ContentValues(); v.put("id", id);
        getWritableDatabase().insertOrThrow("executions", null, v);
    }
    synchronized void finish(JSONObject result) throws Exception {
        ContentValues v = new ContentValues(); v.put("result", result.toString());
        getWritableDatabase().update("executions", v, "id=?", new String[]{result.getString("task_id")});
        queue("result:" + result.getString("task_id"), "/device/result", result);
    }
    synchronized void queue(String id, String path, JSONObject body) {
        ContentValues v = new ContentValues(); v.put("id", id); v.put("path", path); v.put("body", body.toString());
        getWritableDatabase().insertWithOnConflict("outbox", null, v, SQLiteDatabase.CONFLICT_IGNORE);
    }
    synchronized String[] next() {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT id,path,body FROM outbox ORDER BY rowid LIMIT 1", null)) {
            return c.moveToFirst() ? new String[]{c.getString(0),c.getString(1),c.getString(2)} : null;
        }
    }
    synchronized void acknowledge(String id) { getWritableDatabase().delete("outbox", "id=?", new String[]{id}); }
    synchronized void recover() throws Exception {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT id FROM executions", null)) {
            while (c.moveToNext()) {
                JSONObject result = previous(c.getString(0));
                queue("result:" + c.getString(0), "/device/result", result);
            }
        }
    }
}
