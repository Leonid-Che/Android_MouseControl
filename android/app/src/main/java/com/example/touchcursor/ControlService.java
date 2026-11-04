package com.example.touchcursor;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.AudioManager;
import android.os.Build;
import android.os.IBinder;
import android.view.KeyEvent;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

/**
 * Сервис, который живёт всё время, пока управление курсором включено:
 *  1) держит открытым TCP-сокет к компьютеру (связь не рвётся при сворачивании экрана);
 *  2) перехватывает кнопки Громкость+ / Громкость- и превращает их в клики мыши,
 *     поэтому громкость телефона не меняется;
 *  3) показывает уведомление с кнопкой «Выключить».
 */
public class ControlService extends Service {

    public static final String CHANNEL_ID = "touchcursor_control";
    private static final int NOTIF_ID = 1001;

    /** Живой экземпляр — нужен MainActivity для отправки событий. */
    public static volatile ControlService instance;

    /** Общий сетевой клиент (переживает пересоздание Activity). */
    public static volatile NetClient net;

    private AudioManager audio;
    private SharedPreferences prefs;
    private boolean listening = false;

    // ---- Кнопки громкости → мышиные кнопки ----
    private MouseButtonMachine volUpMachine, volDownMachine;

    /** Колбэк в UI: изменилось состояние «кнопка зажата» (для подсветки ЛКМ/ПКМ). */
    public interface UiCallback { void onMouseButtonState(boolean leftDown, boolean rightDown); }

    @Nullable private static volatile UiCallback uiCallback;
    private volatile boolean leftDownUi = false, rightDownUi = false;

    public static void setUiCallback(@Nullable UiCallback cb) { uiCallback = cb; }

    public static Intent intent(Context c) { return new Intent(c, ControlService.class); }

    public static void start(Context c) {
        Intent i = intent(c);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) c.startForegroundService(i);
        else c.startService(i);
    }

    public static void stop(Context c) { c.stopService(intent(c)); }

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        prefs = getSharedPreferences(Prefs.NAME, MODE_PRIVATE);
        audio = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIF_ID, buildNotification());
        ensureNet();
        enableVolumeIntercept(true);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        enableVolumeIntercept(false);
        releaseAllButtons();
        instance = null;
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) { return null; }

    // ============================ СЕТЬ ============================

    /** Возвращает общий клиент, создавая его при необходимости. */
    public static NetClient ensureNetStatic(Context c) {
        if (net == null) net = new NetClient(c.getApplicationContext());
        return net;
    }

    private NetClient ensureNet() { return ensureNetStatic(this); }

    public NetClient client() { return ensureNet(); }

    // ============================ КНОПКИ ГРОМКОСТИ ============================

    /**
     * Пока управление активно, берём «аудио-фокус» на поток проигрывания:
     * системная плашка регулировки громкости не показывается, а само изменение
     * громкости блокируется тем, что Activity поглощает onKeyDown/onKeyUp.
     */
    private void enableVolumeIntercept(boolean on) {
        if (audio == null) return;
        try {
            if (on) {
                // OnAudioFocusChangeListener — это void-функциональный интерфейс,
                // поэтому лямбда обязана быть block-body (statement expression не подходит).
                audio.requestAudioFocus(f -> { /* состояние фокуса нам не нужно обрабатывать */ },
                        AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE);
                listening = true;
            } else {
                audio.abandonAudioFocus(null);
                listening = false;
            }
        } catch (Exception ignored) { }
    }

    public boolean isIntercepting() { return listening; }

    private final class MouseSink implements MouseButtonMachine.Sink {
        private final boolean left;
        MouseSink(boolean left) { this.left = left; }

        private String down() { return left ? Protocol.DOWN_LEFT : Protocol.DOWN_RIGHT; }
        private String up()   { return left ? Protocol.UP_LEFT : Protocol.UP_RIGHT; }
        private String dbl()  { return left ? Protocol.DBL_LEFT : Protocol.DBL_RIGHT; }

        @Override public void singleClick() {
            NetClient nc = client();
            nc.send(down());
            nc.send(up());
            flash(left);
        }
        @Override public void doubleClick() { client().send(dbl()); flash(left); }
        @Override public void pressDown()   { client().send(down()); pushUiState(left, true); }
        @Override public void releaseUp()   { client().send(up());   pushUiState(left, false); }

        private void flash(boolean isLeft) {
            pushUiState(isLeft, true);
            MainThread.postDelayed(() -> pushUiState(isLeft, false), 110);
        }
    }

    private void ensureMachines() {
        if (volUpMachine == null) volUpMachine = new MouseButtonMachine(new MouseSink(true));
        if (volDownMachine == null) volDownMachine = new MouseButtonMachine(new MouseSink(false));
    }

    /**
     * Обработка аппаратных кнопок громкости.
     *  Громкость+ : одиночное → клик ЛКМ; двойное → двойной клик ЛКМ; удержание → ЛКМ зажата.
     *  Громкость− : одиночное → клик ПКМ; удержание → ПКМ зажата.
     *
     * @return true — событие поглощено (громкость телефона НЕ меняется).
     */
    public boolean handleKey(int keyCode, KeyEvent ev) {
        if (!listening) return false;
        ensureMachines();
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) {
            if (ev.getAction() == KeyEvent.ACTION_DOWN) volUpMachine.onDown(ev.getRepeatCount() > 0);
            else if (ev.getAction() == KeyEvent.ACTION_UP) volUpMachine.onUp();
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            if (ev.getAction() == KeyEvent.ACTION_DOWN) volDownMachine.onDown(ev.getRepeatCount() > 0);
            else if (ev.getAction() == KeyEvent.ACTION_UP) volDownMachine.onUp();
            return true;
        }
        return false;
    }

    /** Вызывается из Activity, когда палец жмёт экранные ЛКМ/ПКМ — синхронизируем подсветку. */
    public void showScreenButton(boolean left, boolean down) { pushUiState(left, down); }

    /** Отпускаем всё, что могло остаться нажатым (выключение управления, потеря фокуса). */
    public void releaseAllButtons() {
        if (volUpMachine != null) { volUpMachine.reset(); volUpMachine = null; }
        if (volDownMachine != null) { volDownMachine.reset(); volDownMachine = null; }
        NetClient nc = net;
        if (nc != null && nc.isConnected()) {
            nc.send(Protocol.UP_LEFT);
            nc.send(Protocol.UP_RIGHT);
        }
        pushUiState(true, false);
        pushUiState(false, false);
    }

    private void pushUiState(boolean left, boolean down) {
        if (left) leftDownUi = down; else rightDownUi = down;
        UiCallback cb = uiCallback;
        if (cb != null) MainThread.run(() -> cb.onMouseButtonState(leftDownUi, rightDownUi));
    }

    // ============================ УВЕДОМЛЕНИЕ ============================

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null && nm.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, getString(R.string.notif_channel),
                        NotificationManager.IMPORTANCE_LOW);
                ch.setDescription(getString(R.string.notif_channel_desc));
                ch.setShowBadge(false);
                nm.createNotificationChannel(ch);
            }
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Intent off = new Intent(this, MainActivity.class);
        off.setAction(MainActivity.ACTION_DISABLE);
        PendingIntent pioff = PendingIntent.getActivity(this, 1, off,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        String host = Transport.savedTarget(this);
        if (host.isEmpty()) host = prefs.getString(Prefs.HOST, "");
        String text = host.isEmpty()
                ? getString(R.string.notif_no_host)
                : getString(R.string.notif_connected, host);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_mouse)
                .setContentTitle(getString(R.string.notif_title))
                .setContentText(text)
                .setContentIntent(pi)
                .addAction(0, getString(R.string.notif_action_off), pioff)
                .setOngoing(true)
                .setSilent(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    public void refreshNotification() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTIF_ID, buildNotification());
    }
}
