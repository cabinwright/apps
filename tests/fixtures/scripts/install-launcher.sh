#!/system/bin/sh
# Replace Kia's launcher (Launcher_WP3) with a rebuilt one: the stock APK, untouched,
# plus our classes.dex. Backs the stock APK + odex up first (verified), then
# re-optimizes like Leafia does. Does not reboot. Undo: restore-launcher.sh.
# usage (as root): install-launcher.sh <new apk>
export PATH=/data/nemesis/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=/vendor/lib:/system/lib
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/conscrypt.jar:/system/framework/okhttp.jar:/system/framework/core-junit.jar:/system/framework/bouncycastle.jar:/system/framework/ext.jar:/system/framework/framework.jar:/system/framework/framework2.jar:/system/framework/telephony-common.jar:/system/framework/voip-common.jar:/system/framework/mms-common.jar:/system/framework/android.policy.jar:/system/framework/services.jar:/system/framework/apache-xml.jar:/system/framework/webviewchromium.jar:/system/framework/automotive.jar
NEW=$1
B=/data/nemesis/backup/ev6.launcher
APP=/system/app
SUM_APK=768d9fda8efcd2d38dbe34e58ca37d1a
SUM_ODEX=12c9a96cae35fce9c11fab3918cd912a

sum() { md5 "$1" 2>/dev/null | while read -r s f; do echo "$s"; done; }
fail() { echo "FAIL: $1"; /system/xbin/nemesis remount ro >/dev/null 2>&1; exit 1; }

[ -s "$NEW" ] || fail "no apk at $NEW"

# 1. stock backup, taken once and only from the stock files
if [ "$(sum $B/Launcher_WP3.apk)" = $SUM_APK ] && [ "$(sum $B/Launcher_WP3.odex)" = $SUM_ODEX ]; then
    echo "stock backup present"
elif [ "$(sum $APP/Launcher_WP3.apk)" = $SUM_APK ] && [ "$(sum $APP/Launcher_WP3.odex)" = $SUM_ODEX ]; then
    mkdir -p $B || fail "mkdir $B"
    cp $APP/Launcher_WP3.apk $B/ && cp $APP/Launcher_WP3.odex $B/ || fail "backup copy"
    [ "$(sum $B/Launcher_WP3.apk)" = $SUM_APK ] && [ "$(sum $B/Launcher_WP3.odex)" = $SUM_ODEX ] || fail "backup doesn't match stock"
    echo "backed up stock launcher to $B"
else
    fail "launcher on /system isn't stock and there is no stock backup - refusing"
fi

# 2. swap the APK; the stock odex no longer matches it, so drop it and re-optimize
/system/xbin/nemesis remount rw >/dev/null 2>&1 || fail "remount rw"
cp "$NEW" $APP/Launcher_WP3.apk.new || fail "copy new apk"
chmod 644 $APP/Launcher_WP3.apk.new
mv $APP/Launcher_WP3.apk.new $APP/Launcher_WP3.apk || fail "move new apk into place"
rm -f $APP/Launcher_WP3.odex
echo "new apk in place ($(sum $APP/Launcher_WP3.apk))"
if /system/bin/dexopt --preopt $APP/Launcher_WP3.apk $APP/Launcher_WP3.odex "m=y,u=n"; then
    chmod 644 $APP/Launcher_WP3.odex
    echo "dexopt ok ($(sum $APP/Launcher_WP3.odex))"
else
    rm -f $APP/Launcher_WP3.odex
    echo "dexopt failed - the boot will optimize it into dalvik-cache"
fi
sync
/system/xbin/nemesis remount ro >/dev/null 2>&1
echo "done - reboot to load it"
