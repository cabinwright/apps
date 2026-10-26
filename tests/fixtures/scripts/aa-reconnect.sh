#!/system/bin/sh
# aa-reconnect (tweak pack tweaks.projection): restarts the stock Android Auto receiver when it
# gets stuck.
# Stock bug (com.google.android.projection.sink = /system/app/HKMC_GPM.apk): after the car's own Wi-Fi hotspot
# has used the radio, GalConnectionManager can keep a stale "starting" state. Every
# wireless attempt then logs "current Already AA Starting mode" and never opens its
# session port: the phone joins the hotspot, times out, and retries every ~3.5 s
# until the receiver restarts. Killing the receiver (a persistent app, so Android
# starts it again at once) clears it, and the phone connects on its next try.
# Where it sticks: GalConnectionManager.initConnectSession() refuses every start while
# mStartMode != 0, and only some of GalReceiverService's and WirelessExplorer's paths put it back
# to 0 (setGpmStartMode(0), allSessionClear()). Fixing that path in HKMC_GPM itself would need a
# new HKMC_GPM build and a car to test it on, so this keeps the workaround.
# A service tweak: the runner keeps this running while the switch is on.
export PATH=/data/nemesis/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
SINK=com.google.android.projection.sink
HITS=6        # stuck lines before acting: two or three per retry, so about three retries
GAP=15        # seconds between stuck lines before the count starts over
SPAN=5        # the hits must cover this many seconds (old lines arrive in one burst)
COOLDOWN=120  # seconds to leave the receiver alone after a restart

log() { echo "$(date) $1"; }
# last action, shown in the Tweaks app (status.sh)
last() { mkdir -p /data/nemesis/tweaks.projection/last && echo "$(date +%s) $1" > /data/nemesis/tweaks.projection/last/aa-reconnect; }

sink_pid() {
    ps | while read -r _u _p _rest; do
        case "$_rest" in *" $SINK") echo "$_p"; break ;; esac
    done
}

# services get root without CAP_KILL (CapEff 0xc0), so kill as the receiver's own uid (system)
restart_sink() {
    /system/xbin/nemesis root 1000 -c "kill $1" >/dev/null 2>&1
}

log "watching $SINK"
while :; do
    logcat -v brief -s AAProjection:E 2>/dev/null | {
        _n=0; _first=0; _last=-999; _quiet=0
        while read -r _line; do
            case "$_line" in *"Already AA Starting mode"*) ;; *) continue ;; esac
            _now=$SECONDS
            [ "$_now" -lt "$_quiet" ] && continue
            [ $((_now - _last)) -gt $GAP ] && { _n=0; _first=$_now; }
            _last=$_now
            _n=$((_n + 1))
            [ $_n -ge $HITS ] && [ $((_now - _first)) -ge $SPAN ] || continue
            _pid=$(sink_pid)
            if [ -n "$_pid" ] && restart_sink "$_pid"; then
                log "receiver stuck ($_n stuck lines in $((_now - _first)) s) - restarted it (pid $_pid)"
                last "restarted the stuck Android Auto receiver"
            else
                log "receiver stuck ($_n stuck lines) but could not restart it (pid ${_pid:-not found})"
                last "Android Auto receiver stuck - restart failed"
            fi
            _n=0
            _quiet=$((_now + COOLDOWN))
        done
    }
    log "logcat ended - watching again in 10 s"
    sleep 10
done
