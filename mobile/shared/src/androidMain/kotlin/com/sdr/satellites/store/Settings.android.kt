package com.sdr.satellites.store

import android.content.Context
import android.content.SharedPreferences

actual class PlatformSettings(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("sdr_satellites", Context.MODE_PRIVATE)

    actual fun getString(key: String, defaultValue: String): String =
        prefs.getString(key, defaultValue) ?: defaultValue

    actual fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }

    actual fun remove(key: String) {
        prefs.edit().remove(key).apply()
    }
}
