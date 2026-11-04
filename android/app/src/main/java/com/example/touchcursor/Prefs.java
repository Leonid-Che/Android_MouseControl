package com.example.touchcursor;

import android.content.Context;
import android.content.SharedPreferences;

/** Хранилище настроек (IP компьютера, чувствительность, включённое управление). */
public final class Prefs {

    public static final String NAME = "touchcursor";

    public static final String HOST = "host";                  // IP/имя компьютера
    public static final String TRANSPORT = "transport";        // 0 = Wi-Fi, 1 = Bluetooth
    public static final String BT_ADDRESS = "bt_address";      // MAC-адрес сопряжённого ПК
    public static final String SENS_X = "sens_x";              // множители чувствительности
    public static final String SENS_Y = "sens_y";
    public static final String INVERT_Y = "invert_y";
    public static final String CONTROL_ON = "control_on";      // состояние кнопки вкл/выкл
    public static final String SPEED = "speed";                // ускорение курсора (1.0 = 1x)

    private Prefs() { }

    public static SharedPreferences get(Context c) {
        return c.getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    public static String host(Context c) { return get(c).getString(HOST, ""); }
    public static void setHost(Context c, String h) { get(c).edit().putString(HOST, h).apply(); }

    /** 0 = Wi-Fi (по умолчанию), 1 = Bluetooth. */
    public static int transport(Context c) { return get(c).getInt(TRANSPORT, Transport.WIFI); }
    public static void setTransport(Context c, int t) {
        get(c).edit().putInt(TRANSPORT, t).apply();
    }

    public static String btAddress(Context c) { return get(c).getString(BT_ADDRESS, ""); }
    public static void setBtAddress(Context c, String mac) {
        get(c).edit().putString(BT_ADDRESS, mac).apply();
    }

    public static float sensX(Context c) { return get(c).getFloat(SENS_X, 1.3f); }
    public static float sensY(Context c) { return get(c).getFloat(SENS_Y, 1.3f); }
    public static void setSens(Context c, float x, float y) {
        get(c).edit().putFloat(SENS_X, x).putFloat(SENS_Y, y).apply();
    }

    public static boolean invertY(Context c) { return get(c).getBoolean(INVERT_Y, false); }

    public static boolean controlOn(Context c) { return get(c).getBoolean(CONTROL_ON, false); }
    public static void setControlOn(Context c, boolean on) {
        get(c).edit().putBoolean(CONTROL_ON, on).apply();
    }
}
