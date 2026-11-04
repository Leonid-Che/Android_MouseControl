package com.example.touchcursor;

import android.content.Context;

/**
 * Единая точка выбора транспорта связи с компьютером: Wi-Fi (TCP) или Bluetooth (RFCOMM).
 *
 * Команды протокола одинаковы для обоих каналов ({@link Protocol}) — различается
 * только способ установления соединения. Активный транспорт запоминается в {@link Prefs}:
 * после перезапуска приложения используется тот же канал.
 */
public final class Transport {

    public static final int WIFI = 0;
    public static final int BLUETOOTH = 1;

    /** Абстракция канала связи: подключение + отправка команд/дельт. */
    public interface Link {
        void send(String cmd);
        void sendMove(float dx, float dy);
        boolean isConnected();
        String getHost();
        /** @param target адрес: "ip[:порт]" для Wi-Fi или MAC для Bluetooth */
        void connect(String target);
        void disconnect();
    }

    private Transport() { }

    public static int current(Context c) {
        return Prefs.transport(c);
    }

    public static void set(Context c, int which) {
        Prefs.setTransport(c, which);
    }

    public static String label(Context c) {
        return current(c) == BLUETOOTH ? "Bluetooth" : "Wi-Fi";
    }

    /** Ссылка на активный канал — то, куда тачпад и кнопки шлют команды. */
    public static Link activeLink(Context c, NetClient net, BtClient bt) {
        return current(c) == BLUETOOTH ? linkOf(bt) : linkOf(net);
    }

    /** Сохранённый адрес активного транспорта (IP:порт для Wi-Fi, MAC для Bluetooth). */
    public static String savedTarget(Context c) {
        return current(c) == BLUETOOTH ? Prefs.btAddress(c) : Prefs.host(c);
    }

    /** Адаптер, чтобы NetClient/BtClient подходили под интерфейс Link. */
    public static Link linkOf(final NetClient net) {
        return new Link() {
            @Override public void send(String cmd) { net.send(cmd); }
            @Override public void sendMove(float dx, float dy) { net.sendMove(dx, dy); }
            @Override public boolean isConnected() { return net.isConnected(); }
            @Override public String getHost() { return net.getHost(); }
            @Override public void connect(String target) {
                net.connect(NetClient.normalizeHost(target),
                        NetClient.parsePort(target, Protocol.PORT));
            }
            @Override public void disconnect() { net.disconnect(); }
        };
    }

    public static Link linkOf(final BtClient bt) {
        return new Link() {
            @Override public void send(String cmd) { bt.send(cmd); }
            @Override public void sendMove(float dx, float dy) { bt.sendMove(dx, dy); }
            @Override public boolean isConnected() { return bt.isConnected(); }
            @Override public String getHost() { return bt.getHost(); }
            @Override public void connect(String target) { bt.connect(target); }
            @Override public void disconnect() { bt.disconnect(); }
        };
    }
}
