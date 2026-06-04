package com.sdr.satellites.store

import platform.Foundation.NSUserDefaults

actual class PlatformSettings {
    private val defaults = NSUserDefaults.standardUserDefaults

    actual fun getString(key: String, defaultValue: String): String =
        defaults.stringForKey(key) ?: defaultValue

    actual fun putString(key: String, value: String) {
        defaults.setObject(value, key)
    }

    actual fun remove(key: String) {
        defaults.removeObjectForKey(key)
    }
}
