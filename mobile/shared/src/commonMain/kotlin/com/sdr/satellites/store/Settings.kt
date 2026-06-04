package com.sdr.satellites.store

expect class PlatformSettings {
    fun getString(key: String, defaultValue: String = ""): String
    fun putString(key: String, value: String)
    fun remove(key: String)
}

const val KEY_SERVER_URL = "server_url"
const val KEY_BEARER_TOKEN = "bearer_token"
const val KEY_LATITUDE = "latitude"
const val KEY_LONGITUDE = "longitude"
const val KEY_ALTITUDE_M = "altitude_m"

val DEFAULT_SERVER_URL = "https://sdr.sadbabyrabbit.com"
val DEFAULT_LAT = "40.42"
val DEFAULT_LON = "-86.88"
val DEFAULT_ALT = "180"
