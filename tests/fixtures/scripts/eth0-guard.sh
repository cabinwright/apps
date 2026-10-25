#!/system/bin/sh
# eth0-guard: keeps the stock "ADB TCP" switch from breaking wireless projection.
# With persist.service.adb.tcp.enable=1 (Engineering Mode > ADB TCP), init runs the
# oneshot set_adb_ip = `ifconfig eth0 192.168.0.123` at boot. That is a /24 in the
# hotspot's range, and eth0's route comes first, so replies to phones go out eth0 and
# wireless Android Auto/CarPlay never connects.
# Fix: re-run the same stock service with an extra netmask argument (init appends
# dynamic args to oneshot services), so eth0 keeps its address as a /32 and wlan0
# owns 192.168.0.0/24 again. Runs as init, so it needs no extra rights here.
# ADB over the network keeps working (adbd listens on every interface).
export PATH=/data/nemesis/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
ADDR=192.168.0.123
CHECK=5   # seconds between checks

log() { echo "$(date) $1"; }
# last action, shown by the status app
last() { mkdir -p /data/nemesis/status && echo "$(date +%s) $1" > /data/nemesis/status/eth0-guard.last; }

eth0_clashes() {
    netcfg 2>/dev/null | while read -r _if _state _addr _rest; do
        [ "$_if" = eth0 ] && [ "$_addr" = "$ADDR/24" ] && echo y
    done
}

log "watching eth0"
while :; do
    if [ -n "$(eth0_clashes)" ]; then
        setprop ctl.start "set_adb_ip:netmask 255.255.255.255"
        sleep 2
        if [ -n "$(eth0_clashes)" ]; then
            log "eth0 has $ADDR/24 and narrowing it failed"
            last "could not narrow eth0"
            sleep 60
        else
            log "eth0 had $ADDR/24 (stock ADB TCP switch) - narrowed it to /32"
            last "narrowed eth0 to /32"
        fi
    fi
    sleep $CHECK
done
