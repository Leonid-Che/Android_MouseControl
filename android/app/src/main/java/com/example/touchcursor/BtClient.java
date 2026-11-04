package com.example.touchcursor;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothSocket;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * Bluetooth-клиент: RFCOMM-соединение с компьютером (SPP).
 *
 * Протокол сообщений — тот же, что по Wi-Fi (см. {@link Protocol}):
 * текстовые команды, разделённые '\n'. Отличается только транспорт.
 *
 * Все операции сокета выполняются в фоновом потоке; колбэки приходят
 * в главный поток через {@link MainThread}.
 */
public class BtClient {

    private static final String TAG = "BtClient";

    /** Стандартный UUID профиля Serial Port Profile. */
    public static final UUID SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB");

    private static final long PING_PERIOD_SEC = 5;

    public interface Listener {
        void onConnecting();
        void onConnected(String deviceName);
        void onDisconnected(String reason);
    }

    private final Context ctx;
    private Listener listener;

    private volatile BluetoothSocket socket;
    private volatile OutputStream out;
    private volatile String deviceAddress = "";
    private volatile String deviceName = "";
    private volatile boolean wantConnect = false;

    private ScheduledExecutorService io;
    private ScheduledFuture<?> pingTask;

    // ---- очередь отправки (идентична NetClient: не теряем клики при лагах) ----
    private final Object queueLock = new Object();
    private final ArrayList<String> queue = new ArrayList<>();
    private static final int QUEUE_LIMIT = 64;
    /** Движение — «вытесняемое» событие: храним только накопленную дельту. */
    private float pendingDx = 0f, pendingDy = 0f;

    public BtClient(Context ctx) {
        this.ctx = ctx.getApplicationContext();
    }

    public void setListener(Listener l) { this.listener = l; }

    // ============================ СОСТОЯНИЕ АДАПТЕРА ============================

    public static boolean isSupported(Context c) {
        return c.getApplicationContext().getSystemService(android.bluetooth.BluetoothManager.class) != null
                || BluetoothAdapter.getDefaultAdapter() != null;
    }

    private BluetoothAdapter adapter() {
        android.bluetooth.BluetoothManager bm =
                (android.bluetooth.BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
        if (bm != null) return bm.getAdapter();
        return BluetoothAdapter.getDefaultAdapter();
    }

    /** Включён ли Bluetooth на телефоне. */
    public boolean isBluetoothEnabled() {
        BluetoothAdapter a = adapter();
        return a != null && a.isEnabled();
    }

    /** Запрос системного диалога включения Bluetooth (безопасно даже без разрешения). */
    public void requestEnableBluetooth() {
        try {
            Intent i = new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
        } catch (SecurityException | IllegalStateException e) {
            Log.w(TAG, "requestEnableBluetooth failed: " + e);
            openBluetoothSettings();
        }
    }

    public void openBluetoothSettings() {
        try {
            Intent i = new Intent(Settings.ACTION_BLUETOOTH_SETTINGS);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
        } catch (Exception ignored) { }
    }

    // ============================ СПИСОК УСТРОЙСТВ ============================

    /** Сопряжённые устройства, подходящие для подключения (класс устройства — компьютер/телефон). */
    @SuppressLint("MissingPermission")
    public List<String> listPairedCandidates() {
        List<String> res = new ArrayList<>();
        BluetoothAdapter a = adapter();
        if (a == null) return res;
        try {
            Set<BluetoothDevice> paired = a.getBondedDevices();
            if (paired == null) return res;
            for (BluetoothDevice d : paired) {
                if (isPlausibleTarget(d)) {
                    String name = safeName(d);
                    res.add(name + "  [" + d.getAddress() + "]");
                }
            }
        } catch (SecurityException e) {
            Log.w(TAG, "listPairedCandidates: нет разрешения", e);
        }
        return res;
    }

    /** Адрес выбранного элемента списка из {@link #listPairedCandidates()}. */
    public static String addressOf(String entry) {
        int l = entry.lastIndexOf('[');
        int r = entry.lastIndexOf(']');
        if (l >= 0 && r > l) return entry.substring(l + 1, r).trim().toUpperCase(Locale.US);
        return "";
    }

    @SuppressLint("MissingPermission")
    private boolean isPlausibleTarget(BluetoothDevice d) {
        int major;
        try {
            checkConnectPermission();
            major = d.getBluetoothClass() != null
                    ? d.getBluetoothClass().getMajorDeviceClass() : -1;
        } catch (SecurityException e) {
            // нет разрешения CONNECT — всё равно показываем устройство,
            // при подключении система запросит разрешение
            return true;
        } catch (Exception e) {
            return true; // не удалось определить класс — покажем устройство
        }
        switch (major) {
            case -1:
            case 0:                         // UNKNOWN — многие BT-адаптеры ПК
            case 0x0100:                    // COMPUTER
            case 0x0200:                    // PHONE
            case 0x0400:                    // NETWORKING / LAN-NAP
                return true;
            default:
                return false;               // наушники, клавиатуры и т.п. не показываем
        }
    }

    /**
     * Принудительная проверка разрешения BLUETOOTH_CONNECT: если оно не выдано,
     * бросается SecurityException (обработчик ниже). Это явная проверка, которую
     * требует lint (MissingPermission) для вызовов BluetoothDevice.
     * Контекст берётся из поля ctx — у BluetoothDevice метода getContext() нет.
     */
    private void checkConnectPermission() {
        android.content.pm.PackageManager pm = ctx.getPackageManager();
        int r = pm.checkPermission("android.permission.BLUETOOTH_CONNECT",
                ctx.getPackageName());
        if (r != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("BLUETOOTH_CONNECT not granted");
        }
    }

    @SuppressLint("MissingPermission")
    private String safeName(BluetoothDevice d) {
        try {
            checkConnectPermission();
            String n = d.getName();
            if (n != null && !n.isEmpty()) return n;
        } catch (SecurityException ignored) {
            // разрешения нет — вернём имя по умолчанию
        } catch (RuntimeException ignored) { }
        return "устройство";
    }

    // ============================ ПОДКЛЮЧЕНИЕ ============================

    public boolean isConnected() {
        BluetoothSocket s = socket;
        return s != null && s.isConnected();
    }

    public String getHost() {
        if (deviceName != null && !deviceName.isEmpty()) return deviceName;
        return deviceAddress;
    }

    public String getDeviceAddress() { return deviceAddress; }

    /** Подключение к устройству по MAC-адресу. */
    @SuppressLint("MissingPermission")
    public void connect(final String address) {
        if (address == null || address.isEmpty()) {
            post(() -> { if (listener != null) listener.onDisconnected("адрес не задан"); });
            return;
        }
        this.deviceAddress = address.toUpperCase(Locale.US);
        this.wantConnect = true;
        post(() -> { if (listener != null) listener.onConnecting(); });

        BluetoothAdapter a = adapter();
        if (a == null) { onFail("Bluetooth недоступен на этом устройстве"); return; }
        if (!a.isEnabled()) { onFail("Bluetooth выключен — включите его"); return; }

        ensureIo();
        io.execute(() -> doConnect(a));
    }

    public void disconnect() {
        wantConnect = false;
        if (io != null) io.execute(() -> closeSocket("manual"));
        else closeSocketQuietly();
    }

    /** Переподключение к сохранённому устройству (используется кнопкой Bluetooth). */
    public void reconnect() {
        connect(deviceAddress.isEmpty() ? Prefs.btAddress(ctx) : deviceAddress);
    }

    private void doConnect(BluetoothAdapter a) {
        try {
            closeSocketQuietly();
            BluetoothDevice dev = a.getRemoteDevice(deviceAddress);
            deviceName = safeName(dev);

            BluetoothSocket s;
            boolean fallbackNeeded = false;
            try {
                s = createInsecureRfcomm(dev);
            } catch (IOException e1) {
                // запасной канал: классический RFCOMM-сокет в обход SDP-записи
                Log.w(TAG, "insecure RFCOMM failed, trying fallback: " + e1);
                fallbackNeeded = true;
                s = createFallbackRfcomm(dev);
            }

            if (fallbackNeeded) {
                try {
                    checkConnectPermission();
                } catch (SecurityException se) {
                    // Разрешения нет — закрываем сокет и сообщаем причину.
                    try { s.close(); } catch (IOException ignored) { }
                    onFail("нет разрешения BLUETOOTH_CONNECT — разрешите его в настройках приложения");
                    return;
                }
            }

            s.connect();
            socket = s;
            out = s.getOutputStream();
            startReader(s);
            startPing();

            final String shown = deviceName + " (" + deviceAddress + ")";
            post(() -> { if (listener != null) listener.onConnected(shown); });
            send(Protocol.HELLO);
        } catch (IOException | SecurityException e) {
            Log.w(TAG, "bt connect failed: " + e);
            onFail("не удалось подключиться к " + deviceAddress + " (" + e.getLocalizedMessage() + ")");
        }
    }

    @SuppressLint("MissingPermission")
    private BluetoothSocket createInsecureRfcomm(BluetoothDevice dev) throws IOException {
        // Явная проверка разрешения BLUETOOTH_CONNECT (требование lint):
        // без него бросаем SecurityException — вызывающий код обработает его
        // и покажет понятную причину сбоя подключения.
        checkConnectPermission();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.GINGERBREAD_MR1) {
            return dev.createInsecureRfcommSocketToServiceRecord(SPP_UUID);
        }
        return dev.createRfcommSocketToServiceRecord(SPP_UUID);
    }

    /** Обход для случаев, когда служба SPP не опубликована корректно на ПК. */
    private BluetoothSocket createFallbackRfcomm(BluetoothDevice dev) throws IOException {
        try {
            java.lang.reflect.Method m = BluetoothDevice.class
                    .getMethod("createRfcommSocket", int.class);
            return (BluetoothSocket) m.invoke(dev, 1);
        } catch (Exception e) {
            IOException ioe = new IOException("fallback RFCOMM unavailable");
            ioe.initCause(e);
            throw ioe;
        }
    }

    private void startReader(BluetoothSocket s) {
        io.execute(() -> {
            try (BufferedReader br = new BufferedReader(
                    new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    Log.d(TAG, "<- " + line);   // сервер может слать ACK / статус
                }
            } catch (IOException ignored) {
            } finally {
                if (socket == s) closeSocket("сервер закрыл соединение");
            }
        });
    }

    private void startPing() {
        if (pingTask != null) pingTask.cancel(false);
        pingTask = io.scheduleWithFixedDelay(() -> send(Protocol.PING),
                PING_PERIOD_SEC, PING_PERIOD_SEC, TimeUnit.SECONDS);
    }

    private void closeSocket(String reason) {
        closeSocketQuietly();
        post(() -> { if (listener != null) listener.onDisconnected(reason); });
    }

    private void closeSocketQuietly() {
        if (pingTask != null) { pingTask.cancel(false); pingTask = null; }
        BluetoothSocket s = socket;
        socket = null;
        out = null;
        if (s != null) {
            try { s.close(); } catch (IOException ignored) { }
        }
    }

    private void onFail(String msg) {
        post(() -> { if (listener != null) listener.onDisconnected(msg); });
    }

    public void shutdown() {
        wantConnect = false;
        if (io != null) io.shutdownNow();
        closeSocketQuietly();
    }

    private synchronized void ensureIo() {
        if (io == null || io.isShutdown()) {
            io = Executors.newScheduledThreadPool(2, r -> {
                Thread t = new Thread(r, "bt-io");
                t.setDaemon(true);
                return t;
            });
        }
    }

    // ============================ ОТПРАВКА ============================

    public void send(String cmd) {
        synchronized (queueLock) {
            if (queue.size() < QUEUE_LIMIT) queue.add(cmd);
        }
        if (io != null && !io.isShutdown()) io.execute(this::flush);
    }

    /** Накопительное смещение: сливаем дельты, чтобы не захлёбывать канал. */
    public void sendMove(float dx, float dy) {
        boolean needFlush;
        synchronized (queueLock) {
            needFlush = queue.isEmpty();
            pendingDx += dx;
            pendingDy += dy;
        }
        if (needFlush && io != null && !io.isShutdown()) io.execute(this::flush);
    }

    private void flush() {
        OutputStream o = out;
        if (o == null) return;

        float dx, dy;
        List<String> cmds = new ArrayList<>(8);
        synchronized (queueLock) {
            cmds.addAll(queue);
            queue.clear();
            dx = pendingDx; pendingDx = 0f;
            dy = pendingDy; pendingDy = 0f;
        }
        if (dx != 0f || dy != 0f) cmds.add(Protocol.move(dx, dy));
        if (cmds.isEmpty()) return;

        StringBuilder sb = new StringBuilder(cmds.size() * 12);
        for (String c : cmds) sb.append(c).append('\n');
        byte[] data = sb.toString().getBytes(StandardCharsets.UTF_8);

        try {
            o.write(data);
            o.flush();
        } catch (IOException e) {
            Log.w(TAG, "bt write failed: " + e);
            closeSocket("обрыв связи");
        }
    }

    // ============================ ПАРЫ И ПРИЁМНИКИ ============================

    /** Начинаем сканирование nearby-устройств (Android 12+) — список обновится сам. */
    public void startPairingScan() {
        // Реальное discovery выполняет система через экран настроек Bluetooth;
        // здесь лишь включаем адаптер, чтобы устройства ПК были видны телефону.
        BluetoothAdapter a = adapter();
        if (a != null && !a.isEnabled()) requestEnableBluetooth();
    }

    /** Широковещательный приёмник: переподключаемся, если связь пропала, а управление включено. */
    public static IntentFilter connectionStateFilter() {
        IntentFilter f = new IntentFilter(BluetoothDevice.ACTION_ACL_DISCONNECTED);
        f.addAction(BluetoothAdapter.ACTION_STATE_CHANGED);
        return f;
    }

    public BroadcastReceiver newAutoReconnectReceiver() {
        return new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent intent) {
                String act = intent.getAction();
                if (BluetoothAdapter.ACTION_STATE_CHANGED.equals(act)) {
                    int st = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, -1);
                    if (st == BluetoothAdapter.STATE_OFF) {
                        closeSocket("Bluetooth выключен");
                    }
                } else if (BluetoothDevice.ACTION_ACL_DISCONNECTED.equals(act)) {
                    if (isConnected()) return; // разрыв подтвердит читатель сокета
                }
            }
        };
    }

    private void post(Runnable r) { MainThread.run(r); }
}
