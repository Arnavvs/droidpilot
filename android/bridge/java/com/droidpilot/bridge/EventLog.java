package com.droidpilot.bridge;

import android.graphics.Rect;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.Set;

/**
 * What a person did, as semantic events, for demo recording (Part C, v0.3).
 *
 * OFF unless a session is active. A session names the packages it may record
 * (/events/start?pkgs=a,b); an event from any other package is dropped before
 * anything about it is kept. Within those packages:
 *   - a password field's text is never stored;
 *   - text from direct-message views (resource ids starting "direct_") is never
 *     stored - demos are about routes, not other people's messages;
 *   - typed text (TYPE_VIEW_TEXT_CHANGED) is stored only when the session
 *     asked for it (typed=1), i.e. a declared search task.
 *
 * Only WHICH element was used is recorded - its id, label, class and bounds.
 * No touch coordinates, pressure or timing curves: copying a person's touch
 * signature is out of scope for this project by design.
 */
final class EventLog {

    static final int CAPACITY = 2000;
    static final int TEXT_MAX = 120;

    private static final Object LOCK = new Object();
    private static final ArrayDeque<JSONObject> RING = new ArrayDeque<>();
    private static final Set<String> PKGS = new HashSet<>();
    private static volatile boolean active = false;
    private static boolean typed = false;
    private static int seq = 0;
    private static long startedAt = 0L;
    private static int dropped = 0;

    static JSONObject start(String pkgs, boolean withTyped) throws org.json.JSONException {
        synchronized (LOCK) {
            RING.clear();
            PKGS.clear();
            for (String p : (pkgs == null ? "" : pkgs).split(",")) {
                if (!p.trim().isEmpty()) PKGS.add(p.trim());
            }
            typed = withTyped;
            seq = 0;
            dropped = 0;
            startedAt = System.currentTimeMillis();
            active = !PKGS.isEmpty();
        }
        return status();
    }

    static JSONObject stop() throws org.json.JSONException {
        JSONObject s = status();
        synchronized (LOCK) {
            active = false;
        }
        return s;
    }

    static JSONObject status() throws org.json.JSONException {
        synchronized (LOCK) {
            JSONArray p = new JSONArray();
            for (String x : PKGS) p.put(x);
            return new JSONObject().put("active", active).put("packages", p)
                    .put("typed", typed).put("seq", seq).put("buffered", RING.size())
                    .put("dropped_other_apps", dropped).put("started_at", startedAt);
        }
    }

    static JSONObject since(int after) throws org.json.JSONException {
        JSONArray out = new JSONArray();
        synchronized (LOCK) {
            for (JSONObject e : RING) {
                if (e.optInt("seq") > after) out.put(e);
            }
            return new JSONObject().put("events", out).put("seq", seq)
                    .put("active", active);
        }
    }

    static String typeName(int t) {
        switch (t) {
            case AccessibilityEvent.TYPE_VIEW_CLICKED:        return "click";
            case AccessibilityEvent.TYPE_VIEW_LONG_CLICKED:   return "long_click";
            case AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED:   return "text";
            case AccessibilityEvent.TYPE_VIEW_SELECTED:       return "select";
            case AccessibilityEvent.TYPE_VIEW_SCROLLED:       return "scroll";
            case AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED: return "window";
            default: return null;
        }
    }

    private static String clip(CharSequence s) {
        if (s == null) return "";
        String v = s.toString().trim();
        return v.length() > TEXT_MAX ? v.substring(0, TEXT_MAX) : v;
    }

    /** Called for every accessibility event; cheap when no session is active. */
    static void onEvent(AccessibilityEvent ev) {
        if (!active || ev == null) return;
        String kind = typeName(ev.getEventType());
        if (kind == null) return;
        CharSequence p = ev.getPackageName();
        String pkg = p == null ? "" : p.toString();
        synchronized (LOCK) {
            if (!PKGS.contains(pkg)) {
                dropped++;
                return;
            }
        }
        try {
            JSONObject e = new JSONObject();
            e.put("t", System.currentTimeMillis() - startedAt).put("kind", kind).put("pkg", pkg);
            AccessibilityNodeInfo n = ev.getSource();
            String rid = "";
            boolean password = ev.isPassword();
            if (n != null) {
                String full = n.getViewIdResourceName();
                if (full != null) rid = full.substring(full.indexOf('/') + 1);
                password = password || n.isPassword();
                if (!rid.isEmpty()) e.put("id", rid);
                CharSequence cls = n.getClassName();
                if (cls != null) {
                    String c = cls.toString();
                    e.put("cls", c.substring(c.lastIndexOf('.') + 1));
                }
                Rect b = new Rect();
                n.getBoundsInScreen(b);
                e.put("b", new JSONArray().put(b.left).put(b.top).put(b.right).put(b.bottom));
            } else if (ev.getClassName() != null) {
                String c = ev.getClassName().toString();
                e.put("cls", c.substring(c.lastIndexOf('.') + 1));
            }
            boolean private_ = password || rid.startsWith("direct_");
            if (kind.equals("text")) {
                if (!typed || private_) {
                    e.put("text_withheld", true);
                } else {
                    e.put("text", clip(ev.getText() == null || ev.getText().isEmpty()
                            ? "" : ev.getText().get(0)));
                }
            } else if (!private_) {
                String label = "";
                if (n != null) label = clip(n.getText());
                if (label.isEmpty() && ev.getText() != null && !ev.getText().isEmpty())
                    label = clip(ev.getText().get(0));
                if (!label.isEmpty()) e.put("label", label);
                CharSequence d = n != null ? n.getContentDescription() : ev.getContentDescription();
                if (d != null && d.length() > 0) e.put("desc", clip(d));
            }
            if (kind.equals("scroll") && android.os.Build.VERSION.SDK_INT >= 28) {
                e.put("dy", ev.getScrollDeltaY()).put("dx", ev.getScrollDeltaX());
            }
            synchronized (LOCK) {
                seq++;
                e.put("seq", seq);
                RING.addLast(e);
                while (RING.size() > CAPACITY) RING.removeFirst();
            }
        } catch (Exception ignored) {
            // A malformed event must never take the service down.
        }
    }
}
