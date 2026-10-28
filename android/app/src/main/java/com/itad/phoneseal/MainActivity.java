package com.itad.phoneseal;

/*
 * ITAD PhoneSeal - Android test app.
 *
 * The station installs this app over the USB cable and opens it with the
 * address of its test page:
 *   adb shell am start -n com.itad.phoneseal/.MainActivity --es url <address>
 *
 * The app shows the same test page as the browser, but adds a bridge
 * ("PhoneSeal" in JavaScript) so the page can use parts a browser cannot:
 * proximity and light sensors, the earpiece, the flashlight, volume and power
 * buttons, the headphone socket, battery details, Wi-Fi and Bluetooth.
 * Results still go to the station exactly as before.
 */

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.net.Uri;
import android.net.http.SslError;
import android.net.wifi.WifiManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Vibrator;
import android.provider.Settings;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {

    private WebView web;
    private SensorManager sm;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<SensorEventListener> listeners = new ArrayList<>();
    private volatile boolean captureKeys = false;
    private String torchId = null;
    private boolean receiversOn = false;

    private static final String WAIT_PAGE =
            "<html><body style='font-family:sans-serif;background:#ECEFF6;"
            + "color:#14204A;text-align:center;padding:40px 20px'>"
            + "<h2 style='color:#1D3FB8'>ITAD PhoneSeal</h2>"
            + "<p>Plug this phone into the PhoneSeal station.</p>"
            + "<p>The station opens the tests here by itself.</p></body></html>";

    // ---------------------------------------------------------------
    // start
    // ---------------------------------------------------------------
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        sm = (SensorManager) getSystemService(SENSOR_SERVICE);

        web = new WebView(this);
        setContentView(web);
        hideBars();

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);

        web.addJavascriptInterface(new Bridge(), "PhoneSeal");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
                // The station uses its own certificate. Accept it only for
                // the station: this phone (USB cable) or a local network.
                if (isStation(e.getUrl())) h.proceed(); else h.cancel();
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                if (url.startsWith("tel:")) {
                    try {
                        startActivity(new Intent(Intent.ACTION_DIAL, Uri.parse(url)));
                    } catch (Exception ignored) { }
                    return true;
                }
                return false;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest r) {
                ui.post(() -> r.grant(r.getResources()));
            }
        });

        askPermissions();
        openFrom(getIntent());
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        setIntent(i);
        openFrom(i);
    }

    private void openFrom(Intent i) {
        String url = i != null ? i.getStringExtra("url") : null;
        if (url != null && url.length() > 0) {
            web.loadUrl(url);
        } else if (web.getUrl() == null) {
            web.loadData(WAIT_PAGE, "text/html", "utf-8");
        }
    }

    private static boolean isStation(String url) {
        try {
            String h = Uri.parse(url).getHost();
            if (h == null) return false;
            if (h.equals("127.0.0.1") || h.equals("localhost")) return true;
            if (h.startsWith("10.") || h.startsWith("192.168.")) return true;
            if (h.startsWith("172.")) {
                int n = Integer.parseInt(h.split("\\.")[1]);
                return n >= 16 && n <= 31;
            }
        } catch (Exception ignored) { }
        return false;
    }

    private void askPermissions() {
        if (Build.VERSION.SDK_INT < 23) return;
        List<String> want = new ArrayList<>();
        want.add(Manifest.permission.CAMERA);
        want.add(Manifest.permission.RECORD_AUDIO);
        want.add(Manifest.permission.ACCESS_FINE_LOCATION);
        if (Build.VERSION.SDK_INT >= 31) want.add(Manifest.permission.BLUETOOTH_CONNECT);
        List<String> ask = new ArrayList<>();
        for (String p : want) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) ask.add(p);
        }
        if (!ask.isEmpty()) requestPermissions(ask.toArray(new String[0]), 1);
    }

    private void hideBars() {
        web.setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    // ---------------------------------------------------------------
    // send an event to the page:  nativeEvent(kind, a, b)
    // ---------------------------------------------------------------
    private void send(final String kind, final Object a, final Object b) {
        final String js = "window.nativeEvent&&window.nativeEvent("
                + JSONObject.quote(kind) + "," + val(a) + "," + val(b) + ")";
        ui.post(() -> web.evaluateJavascript(js, null));
    }

    private static String val(Object o) {
        if (o == null) return "null";
        if (o instanceof Number || o instanceof Boolean) return o.toString();
        return JSONObject.quote(o.toString());
    }

    // ---------------------------------------------------------------
    // buttons, headphones and screen on/off
    // ---------------------------------------------------------------
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        String name = null;
        switch (e.getKeyCode()) {
            case KeyEvent.KEYCODE_VOLUME_UP: name = "Volume up"; break;
            case KeyEvent.KEYCODE_VOLUME_DOWN: name = "Volume down"; break;
            case KeyEvent.KEYCODE_CAMERA: name = "Camera button"; break;
            case KeyEvent.KEYCODE_HEADSETHOOK:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE: name = "Headset button"; break;
            case KeyEvent.KEYCODE_BACK: name = "Back"; break;
            default: break;
        }
        if (name != null) {
            if (e.getAction() == KeyEvent.ACTION_DOWN && e.getRepeatCount() == 0) {
                send("key", name, null);
            }
            if (captureKeys || e.getKeyCode() == KeyEvent.KEYCODE_BACK) return true;
        }
        return super.dispatchKeyEvent(e);
    }

    private final BroadcastReceiver events = new BroadcastReceiver() {
        @Override
        public void onReceive(Context c, Intent i) {
            String a = i.getAction();
            if (Intent.ACTION_SCREEN_OFF.equals(a)) send("screen", "off", null);
            else if (Intent.ACTION_SCREEN_ON.equals(a)) send("screen", "on", null);
            else if (Intent.ACTION_HEADSET_PLUG.equals(a)) {
                send("headset", i.getIntExtra("state", 0) == 1,
                        i.getIntExtra("microphone", 0) == 1);
            } else if (Intent.ACTION_BATTERY_CHANGED.equals(a)) {
                send("battery", battery(i).toString(), null);
            }
        }
    };

    @Override
    protected void onStart() {
        super.onStart();
        if (!receiversOn) {
            IntentFilter f = new IntentFilter();
            f.addAction(Intent.ACTION_SCREEN_OFF);
            f.addAction(Intent.ACTION_SCREEN_ON);
            f.addAction(Intent.ACTION_HEADSET_PLUG);
            f.addAction(Intent.ACTION_BATTERY_CHANGED);
            registerReceiver(events, f);
            receiversOn = true;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideBars();
    }

    @Override
    protected void onDestroy() {
        stopSensors();
        if (receiversOn) {
            try { unregisterReceiver(events); } catch (Exception ignored) { }
            receiversOn = false;
        }
        super.onDestroy();
    }

    // ---------------------------------------------------------------
    // helpers
    // ---------------------------------------------------------------
    private JSONObject battery(Intent i) {
        JSONObject o = new JSONObject();
        try {
            if (i == null) {
                i = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            }
            if (i == null) return o;
            int level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
            int scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
            int status = i.getIntExtra(BatteryManager.EXTRA_STATUS, 0);
            int plugged = i.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
            int health = i.getIntExtra(BatteryManager.EXTRA_HEALTH, 0);
            o.put("level", scale > 0 ? Math.round(level * 100f / scale) : level);
            o.put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING
                    || status == BatteryManager.BATTERY_STATUS_FULL);
            o.put("plugged", plugged == BatteryManager.BATTERY_PLUGGED_USB ? "USB"
                    : plugged == BatteryManager.BATTERY_PLUGGED_AC ? "charger"
                    : plugged == 4 ? "wireless" : "no");
            String h;
            switch (health) {
                case BatteryManager.BATTERY_HEALTH_GOOD: h = "Good"; break;
                case BatteryManager.BATTERY_HEALTH_OVERHEAT: h = "Overheat"; break;
                case BatteryManager.BATTERY_HEALTH_DEAD: h = "Dead"; break;
                case BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE: h = "Over voltage"; break;
                case BatteryManager.BATTERY_HEALTH_UNSPECIFIED_FAILURE: h = "Failure"; break;
                case BatteryManager.BATTERY_HEALTH_COLD: h = "Cold"; break;
                default: h = "Unknown"; break;
            }
            o.put("health", h);
            o.put("temp_c", i.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0);
            o.put("voltage", i.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0) / 1000.0);
            o.put("technology", i.getStringExtra(BatteryManager.EXTRA_TECHNOLOGY));
        } catch (Exception ignored) { }
        return o;
    }

    private void stopSensors() {
        for (SensorEventListener l : listeners) sm.unregisterListener(l);
        listeners.clear();
    }

    private String findTorch() {
        if (torchId != null || Build.VERSION.SDK_INT < 23) return torchId;
        try {
            CameraManager cm = (CameraManager) getSystemService(CAMERA_SERVICE);
            for (String id : cm.getCameraIdList()) {
                Boolean f = cm.getCameraCharacteristics(id)
                        .get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                if (f != null && f) { torchId = id; break; }
            }
        } catch (Exception ignored) { }
        return torchId;
    }

    // ---------------------------------------------------------------
    // the bridge the test page uses (window.PhoneSeal)
    // ---------------------------------------------------------------
    private class Bridge {

        @JavascriptInterface
        public String info() {
            JSONObject o = new JSONObject();
            try {
                PackageManager pm = getPackageManager();
                PackageInfo pi = pm.getPackageInfo(getPackageName(), 0);
                o.put("app", pi.versionName);
                o.put("brand", Build.BRAND);
                o.put("model", Build.MODEL);
                o.put("android", Build.VERSION.RELEASE);
                o.put("sdk", Build.VERSION.SDK_INT);
                o.put("proximity", sm.getDefaultSensor(Sensor.TYPE_PROXIMITY) != null);
                o.put("light", sm.getDefaultSensor(Sensor.TYPE_LIGHT) != null);
                o.put("accel", sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) != null);
                o.put("gyro", sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE) != null);
                o.put("compass", sm.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD) != null);
                o.put("flash", findTorch() != null);
                o.put("telephony", pm.hasSystemFeature(PackageManager.FEATURE_TELEPHONY));
                o.put("fingerprint", Build.VERSION.SDK_INT >= 23
                        && pm.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT));
                o.put("bluetooth", pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH));
                o.put("wifi", pm.hasSystemFeature(PackageManager.FEATURE_WIFI));
                o.put("nfc", pm.hasSystemFeature(PackageManager.FEATURE_NFC));
            } catch (Exception ignored) { }
            return o.toString();
        }

        /** kind = proximity / light / accel; events: nativeEvent(kind, value, max) */
        @JavascriptInterface
        public boolean sensor(String kind, boolean on) {
            if (!on) { ui.post(MainActivity.this::stopSensors); return true; }
            int type = "proximity".equals(kind) ? Sensor.TYPE_PROXIMITY
                    : "light".equals(kind) ? Sensor.TYPE_LIGHT
                    : Sensor.TYPE_ACCELEROMETER;
            final Sensor sn = sm.getDefaultSensor(type);
            if (sn == null) return false;
            final String k = kind;
            final float max = sn.getMaximumRange();
            final SensorEventListener l = new SensorEventListener() {
                long last = 0;
                @Override public void onSensorChanged(SensorEvent e) {
                    long now = System.currentTimeMillis();
                    if (now - last < 80) return;        // about 12 per second
                    last = now;
                    if ("accel".equals(k)) {
                        send(k, Math.abs(e.values[0]) + Math.abs(e.values[1]), e.values[2]);
                    } else {
                        send(k, e.values[0], max);
                    }
                }
                @Override public void onAccuracyChanged(Sensor s, int a) { }
            };
            ui.post(() -> {
                sm.registerListener(l, sn, SensorManager.SENSOR_DELAY_UI);
                listeners.add(l);
            });
            return true;
        }

        @JavascriptInterface
        @SuppressWarnings("deprecation")
        public void vibrate(int ms) {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v != null) v.vibrate(new long[]{0, ms, 200, ms}, -1);
        }

        @JavascriptInterface
        public boolean hasVibrator() {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            return v != null && v.hasVibrator();
        }

        /** Plays a tone through the earpiece (the small call speaker). */
        @JavascriptInterface
        @SuppressWarnings("deprecation")
        public void earpiece() {
            ui.post(() -> {
                final AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
                try {
                    am.setMode(AudioManager.MODE_IN_COMMUNICATION);
                    am.setSpeakerphoneOn(false);
                    am.setStreamVolume(AudioManager.STREAM_VOICE_CALL,
                            am.getStreamMaxVolume(AudioManager.STREAM_VOICE_CALL), 0);
                    final ToneGenerator tg = new ToneGenerator(AudioManager.STREAM_VOICE_CALL, 100);
                    tg.startTone(ToneGenerator.TONE_DTMF_5, 2500);
                    ui.postDelayed(() -> {
                        try { tg.release(); } catch (Exception ignored) { }
                        am.setMode(AudioManager.MODE_NORMAL);
                    }, 2800);
                } catch (Exception e) {
                    am.setMode(AudioManager.MODE_NORMAL);
                }
            });
        }

        @JavascriptInterface
        public boolean torch(boolean on) {
            if (Build.VERSION.SDK_INT < 23 || findTorch() == null) return false;
            try {
                ((CameraManager) getSystemService(CAMERA_SERVICE)).setTorchMode(torchId, on);
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        @JavascriptInterface
        public String battery() {
            return MainActivity.this.battery(null).toString();
        }

        /** true = volume buttons only report, they do not change the volume */
        @JavascriptInterface
        public void keys(boolean capture) {
            captureKeys = capture;
        }

        @JavascriptInterface
        @SuppressWarnings("deprecation")
        public String wifi() {
            JSONObject o = new JSONObject();
            try {
                WifiManager w = (WifiManager) getApplicationContext()
                        .getSystemService(WIFI_SERVICE);
                o.put("present", w != null);
                if (w != null) {
                    o.put("enabled", w.isWifiEnabled());
                    if (w.isWifiEnabled()) w.startScan();
                    int n = 0;
                    try { n = w.getScanResults().size(); } catch (Exception ignored) { }
                    o.put("networks", n);
                }
            } catch (Exception ignored) { }
            return o.toString();
        }

        @JavascriptInterface
        @SuppressWarnings({"deprecation", "MissingPermission"})
        public String bluetooth() {
            JSONObject o = new JSONObject();
            try {
                BluetoothAdapter a = BluetoothAdapter.getDefaultAdapter();
                o.put("present", a != null);
                if (a != null) o.put("enabled", a.isEnabled());
            } catch (Exception e) {
                try { o.put("error", e.getClass().getSimpleName()); } catch (Exception ignored) { }
            }
            return o.toString();
        }

        /** Opens a settings screen: wifi / bluetooth / location */
        @JavascriptInterface
        public void settings(String which) {
            String a = "bluetooth".equals(which) ? Settings.ACTION_BLUETOOTH_SETTINGS
                    : "location".equals(which) ? Settings.ACTION_LOCATION_SOURCE_SETTINGS
                    : Settings.ACTION_WIFI_SETTINGS;
            try {
                startActivity(new Intent(a).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } catch (Exception ignored) { }
        }
    }
}
