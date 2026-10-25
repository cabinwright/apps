#!/system/bin/sh
# status: writes a snapshot of what ev6.fixes looks after, for the status app.
# /data/nemesis/status/ev6.fixes.txt, key=value lines, replaced every few seconds.
# The other services leave their last action in /data/nemesis/status/<name>.last.
export PATH=/data/nemesis/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
DIR=/data/nemesis/status
OUT=$DIR/ev6.fixes.txt
EVERY=3
SINK=com.google.android.projection.sink
LEAFIA_PARTS=/data/nemesis/wireless.carplay.aa.parts

snapshot() {
    local _up _rest _if _state _addr _a _hw _fl _mac _mask _dev _n _p _rq _sq _local _peer _st _f
    echo "time=$(date +%s)"
    read -r _up _rest < /proc/uptime
    echo "uptime=${_up%%.*}"

    netcfg 2>/dev/null | while read -r _if _state _addr _rest; do
        case "$_if" in eth0|wlan0|rmnet0) echo "$_if=$_state $_addr" ;; esac
    done

    echo "adbd=$(getprop init.svc.adbd)"
    echo "adb_switch=$(getprop persist.service.adb.tcp.enable)"
    echo "adb_port=$(getprop persist.adb.tcp.port)"

    _n=0
    while read -r _a _hw _fl _mac _mask _dev; do
        [ "$_dev" = wlan0 ] && [ "$_fl" = 0x2 ] && _n=$((_n + 1))
    done < /proc/net/arp
    echo "wifi_clients=$_n"

    # a projection session is an established TCP link from a hotspot client to a
    # port other than ADB (5555) and DNS (53)
    netstat 2>/dev/null | while read -r _p _rq _sq _local _peer _st; do
        [ "$_st" = ESTABLISHED ] || continue
        case "$_local" in *:5555|*:53|127.*) continue ;; 192.168.0.*) ;; *) continue ;; esac
        echo "projection=${_peer%:*}"
    done

    ps | while read -r _a _p _rest; do
        case "$_rest" in *" $SINK") echo "aa_pid=$_p" ;; esac
    done

    [ -s "$LEAFIA_PARTS" ] && echo "leafia_parts=$(cat "$LEAFIA_PARTS")"
    /system/xbin/nemesis pkg-list 2>/dev/null | while read -r _rest; do echo "pkg=$_rest"; done

    for _f in "$DIR"/*.last; do
        [ -f "$_f" ] || continue
        _rest=${_f##*/}
        echo "last.${_rest%.last}=$(cat "$_f")"
    done
}

mkdir -p "$DIR" && chmod 755 "$DIR"
echo "$(date) writing $OUT every $EVERY s"
while :; do
    snapshot > "$OUT.tmp" 2>/dev/null
    chmod 644 "$OUT.tmp"
    mv "$OUT.tmp" "$OUT"
    sleep $EVERY
done
