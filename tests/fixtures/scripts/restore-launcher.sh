#!/system/bin/sh
# Restore Kia's stock launcher from the backup taken before it was replaced, then reboot.
# Run from the USB stick (NEMESIS.data type=execute), which runs with full root.
# Log: launcher-restore.log on the stick.
export PATH=/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=/vendor/lib:/system/lib
B=/data/nemesis/backup/ev6.launcher
APP=/system/app
SUM_APK=768d9fda8efcd2d38dbe34e58ca37d1a
SUM_ODEX=12c9a96cae35fce9c11fab3918cd912a
L=/storage/usb0/launcher-restore.log
log() { echo "$(date) $1" >> $L; }

sum() { md5 "$1" 2>/dev/null | while read -r s f; do echo "$s"; done; }

log "restore start"
if [ "$(sum $B/Launcher_WP3.apk)" != $SUM_APK ] || [ "$(sum $B/Launcher_WP3.odex)" != $SUM_ODEX ]; then
    log "FAIL: backup in $B is missing or not the stock files - nothing changed"
    exit 1
fi
if [ "$(sum $APP/Launcher_WP3.apk)" = $SUM_APK ] && [ "$(sum $APP/Launcher_WP3.odex)" = $SUM_ODEX ]; then
    log "already stock - nothing to do"
    exit 0
fi
/system/xbin/nemesis remount rw >> $L 2>&1 || { log "FAIL: remount rw"; exit 1; }
cp $B/Launcher_WP3.apk $APP/Launcher_WP3.apk && cp $B/Launcher_WP3.odex $APP/Launcher_WP3.odex
chmod 644 $APP/Launcher_WP3.apk $APP/Launcher_WP3.odex
chown root.root $APP/Launcher_WP3.apk $APP/Launcher_WP3.odex
rm -f /data/dalvik-cache/*Launcher_WP3* /data/dalvik-cache/arm/*Launcher_WP3* /cache/dalvik-cache/*Launcher_WP3*
sync
/system/xbin/nemesis remount ro >> $L 2>&1
if [ "$(sum $APP/Launcher_WP3.apk)" = $SUM_APK ] && [ "$(sum $APP/Launcher_WP3.odex)" = $SUM_ODEX ]; then
    log "stock launcher restored - rebooting"
    sync
    reboot
fi
log "FAIL: files on /system don't match stock after copy - not rebooting"
exit 1
